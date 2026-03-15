#!/usr/bin/env python3
"""Shadow-mode runner for wallet-flow and LMSR signal lanes.

Runs alongside BTC5 without placing real orders. Logs what each lane
WOULD have traded, records hypothetical P&L, and persists results in
SQLite for later comparison with BTC5 actual fills.

Usage:
  python bot/shadow_runner.py --lane wallet_flow --continuous
  python bot/shadow_runner.py --lane lmsr --continuous
  python bot/shadow_runner.py --lane wallet_flow --once
  python bot/shadow_runner.py --lane lmsr --once
  python bot/shadow_runner.py --status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Lane imports — deferred to avoid import errors when one lane is broken
logger = logging.getLogger("ShadowRunner")

DEFAULT_DB_PATH = Path("data/shadow_signals.db")
POLL_INTERVAL_SECONDS = int(os.environ.get("SHADOW_POLL_INTERVAL", "30"))
SHADOW_MAX_TRADE_USD = float(os.environ.get("SHADOW_MAX_TRADE_USD", "5.0"))


@dataclass
class ShadowSignal:
    """A signal captured in shadow mode — no real order placed."""
    lane: str               # "wallet_flow" or "lmsr"
    market_id: str
    question: str
    direction: str          # "buy_yes" or "buy_no"
    market_price: float
    estimated_prob: float
    edge: float
    confidence: float
    reasoning: str
    hypothetical_size_usd: float
    timestamp_utc: str
    extra_json: str = ""    # Lane-specific metadata as JSON


class ShadowDB:
    """SQLite persistence for shadow signals and hypothetical P&L."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS shadow_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                market_id TEXT NOT NULL,
                question TEXT,
                direction TEXT,
                market_price REAL,
                estimated_prob REAL,
                edge REAL,
                confidence REAL,
                reasoning TEXT,
                hypothetical_size_usd REAL,
                timestamp_utc TEXT,
                extra_json TEXT,
                resolved INTEGER DEFAULT 0,
                resolution_price REAL,
                hypothetical_pnl REAL,
                resolved_at TEXT,
                UNIQUE(lane, market_id, direction, timestamp_utc)
            );
            CREATE INDEX IF NOT EXISTS idx_ss_lane ON shadow_signals(lane);
            CREATE INDEX IF NOT EXISTS idx_ss_ts ON shadow_signals(timestamp_utc);
            CREATE INDEX IF NOT EXISTS idx_ss_resolved ON shadow_signals(resolved);
        """)
        self.conn.commit()

    def record_signal(self, sig: ShadowSignal) -> bool:
        """Insert a shadow signal. Returns True if new, False if duplicate."""
        try:
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO shadow_signals
                   (lane, market_id, question, direction, market_price,
                    estimated_prob, edge, confidence, reasoning,
                    hypothetical_size_usd, timestamp_utc, extra_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sig.lane, sig.market_id, sig.question, sig.direction,
                 sig.market_price, sig.estimated_prob, sig.edge,
                 sig.confidence, sig.reasoning, sig.hypothetical_size_usd,
                 sig.timestamp_utc, sig.extra_json),
            )
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.warning(f"DB insert failed: {e}")
            return False

    def resolve_signal(
        self, signal_id: int, resolution_price: float, pnl: float
    ):
        """Mark a shadow signal as resolved with hypothetical P&L."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE shadow_signals
               SET resolved=1, resolution_price=?, hypothetical_pnl=?, resolved_at=?
               WHERE id=?""",
            (resolution_price, pnl, now, signal_id),
        )
        self.conn.commit()

    def get_unresolved(self, lane: Optional[str] = None) -> list[dict]:
        """Get all unresolved shadow signals."""
        if lane:
            rows = self.conn.execute(
                "SELECT * FROM shadow_signals WHERE resolved=0 AND lane=?",
                (lane,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM shadow_signals WHERE resolved=0"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self, lane: Optional[str] = None) -> dict[str, Any]:
        """Aggregate statistics for a lane or all lanes."""
        where = "WHERE lane=?" if lane else ""
        params: tuple = (lane,) if lane else ()

        total = self.conn.execute(
            f"SELECT COUNT(*) FROM shadow_signals {where}", params
        ).fetchone()[0]

        resolved = self.conn.execute(
            f"SELECT COUNT(*) FROM shadow_signals {where} AND resolved=1"
            if lane
            else "SELECT COUNT(*) FROM shadow_signals WHERE resolved=1",
            params if lane else (),
        ).fetchone()[0]

        pnl_row = self.conn.execute(
            f"SELECT COALESCE(SUM(hypothetical_pnl), 0) FROM shadow_signals "
            f"{'WHERE lane=? AND' if lane else 'WHERE'} resolved=1",
            params if lane else (),
        ).fetchone()
        total_pnl = pnl_row[0] if pnl_row else 0.0

        wins = self.conn.execute(
            f"SELECT COUNT(*) FROM shadow_signals "
            f"{'WHERE lane=? AND' if lane else 'WHERE'} resolved=1 AND hypothetical_pnl > 0",
            params if lane else (),
        ).fetchone()[0]

        return {
            "lane": lane or "all",
            "total_signals": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "wins": wins,
            "losses": resolved - wins,
            "win_rate": round(wins / max(1, resolved), 4),
            "total_hypothetical_pnl": round(total_pnl, 4),
        }

    def close(self):
        self.conn.close()


def _compute_hypothetical_size(edge: float, confidence: float) -> float:
    """Compute hypothetical position size using quarter-Kelly."""
    if edge <= 0 or confidence <= 0:
        return 0.0
    kelly_f = min(0.25, edge / max(0.01, 1.0 - confidence))
    return min(SHADOW_MAX_TRADE_USD, max(1.0, kelly_f * 100.0))


def _run_wallet_flow_scan(db: ShadowDB) -> int:
    """Run one wallet-flow scan cycle. Returns count of new signals."""
    try:
        from bot.wallet_flow_detector import get_signals_for_engine
    except ImportError:
        from wallet_flow_detector import get_signals_for_engine  # type: ignore

    signals = get_signals_for_engine()
    new_count = 0
    now = datetime.now(timezone.utc).isoformat()

    for sig in signals:
        edge = float(sig.get("edge", 0))
        confidence = float(sig.get("confidence", 0))
        hyp_size = _compute_hypothetical_size(edge, confidence)

        extra = {
            k: sig[k]
            for k in (
                "wallet_consensus_wallets",
                "wallet_consensus_notional_usd",
                "wallet_consensus_share",
                "wallet_opposition_wallets",
                "wallet_opposition_notional_usd",
                "wallet_signal_age_seconds",
                "wallet_window_start_ts",
                "wallet_window_minutes",
            )
            if k in sig
        }

        shadow = ShadowSignal(
            lane="wallet_flow",
            market_id=sig.get("market_id", ""),
            question=sig.get("question", ""),
            direction=sig.get("direction", ""),
            market_price=float(sig.get("market_price", 0.5)),
            estimated_prob=float(sig.get("estimated_prob", 0.5)),
            edge=edge,
            confidence=confidence,
            reasoning=sig.get("reasoning", ""),
            hypothetical_size_usd=hyp_size,
            timestamp_utc=now,
            extra_json=json.dumps(extra) if extra else "",
        )
        if db.record_signal(shadow):
            new_count += 1
            logger.info(
                f"SHADOW wallet_flow: {shadow.question[:60]} → {shadow.direction} "
                f"edge={shadow.edge:.3f} conf={shadow.confidence:.3f} "
                f"hyp_size=${shadow.hypothetical_size_usd:.2f}"
            )

    return new_count


def _run_lmsr_scan(db: ShadowDB) -> int:
    """Run one LMSR scan cycle. Returns count of new signals."""
    import requests

    try:
        from bot.lmsr_engine import LMSREngine
    except ImportError:
        from lmsr_engine import LMSREngine  # type: ignore

    engine = LMSREngine(entry_threshold=0.05)

    # Fetch active markets from Gamma API
    try:
        resp = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": 30, "active": True, "closed": False},
            timeout=10,
        )
        resp.raise_for_status()
        markets = resp.json()
    except Exception as e:
        logger.warning(f"LMSR market fetch failed: {e}")
        return 0

    signals = engine.get_signals(markets)
    new_count = 0
    now = datetime.now(timezone.utc).isoformat()

    for sig in signals:
        edge = float(sig.get("edge", 0))
        confidence = float(sig.get("confidence", 0))
        hyp_size = _compute_hypothetical_size(edge, confidence)

        extra = {
            "kelly_fraction": sig.get("kelly_fraction"),
            "source": sig.get("source"),
        }

        shadow = ShadowSignal(
            lane="lmsr",
            market_id=sig.get("market_id", ""),
            question=sig.get("question", ""),
            direction=sig.get("direction", ""),
            market_price=float(sig.get("market_price", 0.5)),
            estimated_prob=float(sig.get("estimated_prob", 0.5)),
            edge=edge,
            confidence=confidence,
            reasoning=sig.get("reasoning", ""),
            hypothetical_size_usd=hyp_size,
            timestamp_utc=now,
            extra_json=json.dumps(extra) if extra else "",
        )
        if db.record_signal(shadow):
            new_count += 1
            logger.info(
                f"SHADOW lmsr: {shadow.question[:60]} → {shadow.direction} "
                f"edge={shadow.edge:.3f} conf={shadow.confidence:.3f} "
                f"hyp_size=${shadow.hypothetical_size_usd:.2f}"
            )

    return new_count


LANE_SCANNERS = {
    "wallet_flow": _run_wallet_flow_scan,
    "lmsr": _run_lmsr_scan,
}


def run_shadow_loop(lane: str, db: ShadowDB, max_cycles: int = 0):
    """Continuous shadow scanning loop."""
    scanner = LANE_SCANNERS.get(lane)
    if not scanner:
        logger.error(f"Unknown lane: {lane}")
        return

    cycle = 0
    logger.info(
        f"Shadow runner started: lane={lane}, interval={POLL_INTERVAL_SECONDS}s"
    )
    while max_cycles == 0 or cycle < max_cycles:
        cycle += 1
        try:
            new = scanner(db)
            if new > 0:
                logger.info(f"Shadow cycle {cycle}: {new} new {lane} signals")
        except Exception as e:
            logger.error(f"Shadow cycle {cycle} error: {e}")

        if max_cycles == 0 or cycle < max_cycles:
            time.sleep(POLL_INTERVAL_SECONDS)


def print_status(db: ShadowDB):
    """Print shadow signal status for all lanes."""
    for lane in ("wallet_flow", "lmsr", None):
        summary = db.get_summary(lane)
        label = summary["lane"]
        print(f"\n=== Shadow Status: {label} ===")
        print(f"  Total signals: {summary['total_signals']}")
        print(f"  Resolved: {summary['resolved']}")
        print(f"  Win rate: {summary['win_rate']:.1%}")
        print(f"  Hypothetical P&L: ${summary['total_hypothetical_pnl']:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Shadow-mode signal runner")
    parser.add_argument(
        "--lane",
        choices=["wallet_flow", "lmsr"],
        help="Which signal lane to run in shadow mode",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run continuously (default: one cycle)",
    )
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle")
    parser.add_argument("--status", action="store_true", help="Show shadow signal status")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to shadow signals database",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="Max cycles (0 = infinite, only with --continuous)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db = ShadowDB(Path(args.db_path))

    try:
        if args.status:
            print_status(db)
            return

        if not args.lane:
            parser.error("--lane is required unless --status is used")

        if args.continuous:
            run_shadow_loop(args.lane, db, max_cycles=args.max_cycles)
        else:
            scanner = LANE_SCANNERS.get(args.lane)
            if scanner:
                new = scanner(db)
                print(f"Shadow scan complete: {new} new signals")
                print_status(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
