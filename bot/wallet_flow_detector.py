#!/usr/bin/env python3
"""
Smart Wallet Flow Detector — Signal Source #2 for JJ
=====================================================
Monitors Polymarket trade flow via the public data-api.polymarket.com/trades
endpoint, identifies top-performing wallets ("smart money"), and generates
trading signals when multiple smart wallets converge on the same side of a
fast-resolving market.

Architecture:
  1. WalletScorer: Fetches historical trades, scores wallets by activity + diversity
  2. FlowMonitor: Polls recent trades, filters for smart wallet activity
  3. ConsensusDetector: Signals when N of top-K wallets agree on a side
  4. WalletFlowSignal: Output format for integration with jj_live.py

Data source: https://data-api.polymarket.com/trades (public, no auth)
  - Returns: proxyWallet, side, size, price, conditionId, title, timestamp,
             outcome (e.g., "Up", "Down"), outcomeIndex (0 or 1)
  - Filter by wallet: ?proxyWallet=0x...
  - Filter by market: ?conditionId=0x...

Direction Logic (from actual API data):
  - BUY + outcomeIndex=0 → betting on first outcome (e.g., "Up")
  - BUY + outcomeIndex=1 → betting on second outcome (e.g., "Down")
  - SELL + outcomeIndex=0 → betting AGAINST first outcome
  - SELL + outcomeIndex=1 → betting AGAINST second outcome
  - effective_outcome = outcomeIndex if BUY, else (1 - outcomeIndex)

Usage:
  python wallet_flow_detector.py --build-scores     # Build wallet database
  python wallet_flow_detector.py --monitor           # Continuous monitoring
  python wallet_flow_detector.py --scan              # Single scan (for jj_live.py)
  python wallet_flow_detector.py --status            # Show database stats
  python wallet_flow_detector.py --status-json       # Machine-readable readiness

March 7, 2026 — Elastifund / JJ
"""

import os
import sys
import json
import time
import re
import sqlite3
import logging
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
from typing import Any, Optional, Dict, List
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("WalletFlow")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# Minimum criteria for a "smart wallet" (MVP thresholds, will tighten later)
MIN_TRADES = 5                 # Minimum trades to qualify
MIN_UNIQUE_MARKETS = 3         # Must trade in multiple distinct markets
MIN_TOTAL_VOLUME = 50.0        # At least $50 total traded

# Consensus signal parameters
MIN_SMART_WALLETS_AGREE = 3    # At least N smart wallets on same side
CONSENSUS_WINDOW_MINUTES = 30  # Within this time window
MIN_TOTAL_SIZE_USD = 15.0      # Combined smart wallet size must exceed this

# Markets to monitor (fast-resolving crypto)
FAST_MARKET_KEYWORDS = [
    "up or down", "5m", "15m", "5-minute", "15-minute",
    "5 minute", "15 minute", "updown",
]

# How many trades to fetch for initial scoring
INITIAL_FETCH_LIMIT = 5000     # Fetch 5000 trades for wallet discovery
PER_WALLET_FETCH_LIMIT = 200   # Per-wallet trade history depth
TOP_WALLETS_TO_PROFILE = 100   # Profile this many top wallets individually

# Polling interval
POLL_INTERVAL_SECONDS = 15     # How often to check for new trades

# Storage
DB_FILE = Path(os.environ.get("JJ_WALLET_FLOW_DB_FILE", "data/wallet_scores.db"))
SCORES_FILE = Path(os.environ.get("JJ_WALLET_FLOW_SCORES_FILE", "data/smart_wallets.json"))
BOOTSTRAP_MAX_AGE_HOURS = 24


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class WalletScore:
    """Scoring record for a single wallet."""
    address: str
    total_trades: int = 0
    crypto_trades: int = 0       # Trades on crypto fast-markets specifically
    unique_markets: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_volume: float = 0.0
    avg_size: float = 0.0
    win_rate: float = 0.0
    activity_score: float = 0.0  # Composite score
    last_active: str = ""
    is_smart: bool = False

    # These fields exist for backward compat with JSON loading
    categories: list = field(default_factory=list)


@dataclass
class WalletFlowSignal:
    """Output signal from the flow detector."""
    market_id: str              # conditionId
    market_title: str
    direction: str              # "outcome_0" or "outcome_1"
    outcome_name: str           # Human-readable: "Up", "Down", etc.
    confidence: float           # 0.0 - 1.0
    smart_wallets_count: int    # How many smart wallets agree
    total_smart_size: float     # Combined USD size from smart wallets
    avg_smart_score: float      # Average activity score of agreeing wallets
    signal_age_seconds: float   # How old the earliest trade in consensus is
    timestamp: str
    wallet_consensus_wallets: Optional[int] = None
    wallet_consensus_notional_usd: Optional[float] = None
    wallet_consensus_share: Optional[float] = None
    wallet_opposition_wallets: Optional[int] = None
    wallet_opposition_notional_usd: Optional[float] = None
    wallet_signal_age_seconds: Optional[float] = None
    wallet_window_start_ts: Optional[str] = None
    wallet_window_minutes: Optional[int] = None
    wallet_conflict_resolution: Optional[Dict[str, Any]] = None


@dataclass
class BootstrapStatus:
    """Explicit readiness status for wallet-flow bootstrap artifacts."""

    ready: bool
    reasons: List[str]
    wallet_count: int
    scores_exists: bool
    db_exists: bool
    last_updated: Optional[str]


def _wallet_signal_sort_key(signal: Dict[str, Any]) -> tuple[float, float, float]:
    """Rank competing market directions by wallet count, size, then confidence."""
    return (
        float(signal.get("smart_wallets_count", 0) or 0),
        float(signal.get("total_smart_size", 0.0) or 0.0),
        float(signal.get("confidence", 0.0) or 0.0),
    )


def _resolve_conflicting_market_signals(raw_signals: List[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Suppress or resolve opposite-direction wallet consensus on the same market."""
    by_market: Dict[str, List[Dict[str, Any]]] = {}
    for signal in raw_signals:
        market_id = str(signal.get("market_id") or "").strip()
        if not market_id:
            continue
        by_market.setdefault(market_id, []).append(signal)

    resolved: list[Dict[str, Any]] = []
    for market_id, grouped_signals in by_market.items():
        if len(grouped_signals) <= 1:
            resolved.extend(grouped_signals)
            continue

        ranked = sorted(grouped_signals, key=_wallet_signal_sort_key, reverse=True)
        top = ranked[0]
        runner_up = ranked[1]

        top_wallets = int(top.get("smart_wallets_count", 0) or 0)
        runner_wallets = int(runner_up.get("smart_wallets_count", 0) or 0)
        top_size = float(top.get("total_smart_size", 0.0) or 0.0)
        runner_size = float(runner_up.get("total_smart_size", 0.0) or 0.0)
        top_conf = float(top.get("confidence", 0.0) or 0.0)
        runner_conf = float(runner_up.get("confidence", 0.0) or 0.0)

        dominant = (
            top_wallets >= runner_wallets + 2
            or top_size >= max(1.0, runner_size) * 1.5
            or top_conf >= runner_conf + 0.15
        )
        title = str(top.get("market_title") or market_id)
        if not dominant:
            logger.info(
                "Skipping wallet-flow market %s due to conflicting consensus "
                "(%s wallets=$%.2f conf=%.2f vs %s wallets=$%.2f conf=%.2f)",
                title[:60],
                top_wallets,
                top_size,
                top_conf,
                runner_wallets,
                runner_size,
                runner_conf,
            )
            continue

        top["conflict_resolution"] = {
            "suppressed_direction": runner_up.get("direction"),
            "suppressed_wallets": runner_wallets,
            "suppressed_size": round(runner_size, 2),
            "suppressed_confidence": round(runner_conf, 4),
        }
        logger.info(
            "Resolved wallet-flow conflict on %s in favor of %s "
            "(%s wallets=$%.2f conf=%.2f over %s wallets=$%.2f conf=%.2f)",
            title[:60],
            top.get("direction", "?"),
            top_wallets,
            top_size,
            top_conf,
            runner_wallets,
            runner_size,
            runner_conf,
        )
        resolved.append(top)

    return resolved


def _parse_window_metadata_from_title(
    title: str,
    *,
    reference_ts: int,
) -> tuple[Optional[str], Optional[int]]:
    """
    Parse BTC fast-window metadata from market title text when available.

    Returns:
      (window_start_ts_utc_iso, window_minutes)
    """
    text = str(title or "")
    lowered = text.lower()

    window_minutes = None
    minutes_match = re.search(r"(\d{1,2})\s*(?:m|min|minute)s?\b", lowered)
    if minutes_match:
        try:
            window_minutes = int(minutes_match.group(1))
        except ValueError:
            window_minutes = None

    start_ts = None
    et_match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*et\b",
        lowered,
        flags=re.IGNORECASE,
    )
    if et_match:
        try:
            hour = int(et_match.group(1))
            minute = int(et_match.group(2) or "0")
            am_pm = str(et_match.group(3)).lower()
            if hour == 12:
                hour = 0
            if am_pm == "pm":
                hour += 12
            ref_et = datetime.fromtimestamp(int(reference_ts), tz=ZoneInfo("America/New_York"))
            start_et = ref_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
            start_ts = start_et.astimezone(timezone.utc).isoformat()
        except Exception:
            start_ts = None

    return start_ts, window_minutes


def is_crypto_fast_market(title: str) -> bool:
    """Check if a market title indicates a crypto fast-resolving market."""
    title_lower = (title or "").lower()
    return any(kw in title_lower for kw in FAST_MARKET_KEYWORDS)


def get_effective_outcome(side: str, outcome_index) -> int:
    """
    Determine which outcome a trade is effectively betting on.

    On Polymarket's data API:
      - BUY + outcomeIndex=0 → betting first outcome will happen
      - BUY + outcomeIndex=1 → betting second outcome will happen
      - SELL + outcomeIndex=0 → betting first outcome WON'T happen = betting on outcome 1
      - SELL + outcomeIndex=1 → betting second outcome WON'T happen = betting on outcome 0

    Returns: 0 or 1 (which outcome they're effectively betting on)
    """
    try:
        idx = int(outcome_index)
    except (TypeError, ValueError):
        idx = 0

    side_upper = (side or "").upper()
    if side_upper == "SELL":
        return 1 - idx
    return idx  # BUY or unknown → same as outcomeIndex


def _file_updated_at(path: Path) -> Optional[str]:
    """Return the file mtime as an ISO8601 UTC timestamp."""
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        return None


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse a stored ISO8601 timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_scores_payload(scores_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the smart-wallet JSON payload."""
    target = scores_path or SCORES_FILE
    with open(target) as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("scores payload must be a JSON object")
    return payload


def load_smart_wallets(scores_path: Optional[Path] = None) -> tuple[dict, Optional[str]]:
    """Load smart wallets from JSON for scanning and status reporting."""
    payload = _load_scores_payload(scores_path)
    raw_wallets = payload.get("wallets", {})
    if not isinstance(raw_wallets, dict):
        raise ValueError("wallets payload must be a JSON object")

    smart = {}
    for addr, info in raw_wallets.items():
        if not isinstance(info, dict):
            continue
        filtered_info = {"address": addr}
        for key, value in info.items():
            if key in WalletScore.__dataclass_fields__:
                filtered_info[key] = value
        smart[addr] = WalletScore(**filtered_info)
    last_updated = payload.get("updated_at")
    if not isinstance(last_updated, str):
        last_updated = _file_updated_at(scores_path or SCORES_FILE)
    return smart, last_updated


def get_bootstrap_status(
    scores_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> BootstrapStatus:
    """
    Assess whether wallet-flow bootstrap artifacts are present and fresh enough
    for live scanning.
    """
    scores_target = scores_path or SCORES_FILE
    db_target = db_path or DB_FILE
    current_time = now or datetime.now(timezone.utc)
    scores_exists = scores_target.exists()
    db_exists = db_target.exists()
    reasons: List[str] = []
    wallet_count = 0
    last_updated = _file_updated_at(scores_target)

    if not scores_exists:
        reasons.append("missing_scores_json")
    if not db_exists:
        reasons.append("missing_scores_db")

    if scores_exists:
        try:
            smart, loaded_updated_at = load_smart_wallets(scores_target)
            wallet_count = len(smart)
            if loaded_updated_at:
                last_updated = loaded_updated_at
            if wallet_count == 0:
                reasons.append("no_wallets_loaded")

            parsed_updated = _parse_timestamp(last_updated)
            if parsed_updated is None:
                reasons.append("invalid_last_updated")
            elif current_time - parsed_updated > timedelta(hours=BOOTSTRAP_MAX_AGE_HOURS):
                reasons.append("stale_bootstrap")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(f"Failed to read wallet bootstrap payload: {exc}")
            reasons.append("invalid_scores_json")

    return BootstrapStatus(
        ready=not reasons,
        reasons=reasons,
        wallet_count=wallet_count,
        scores_exists=scores_exists,
        db_exists=db_exists,
        last_updated=last_updated,
    )


def _bootstrap_status_payload(status: BootstrapStatus) -> dict:
    """Convert bootstrap status to a JSON-serializable dict."""
    return {
        "ready": status.ready,
        "reasons": list(status.reasons),
        "wallet_count": status.wallet_count,
        "scores_exists": status.scores_exists,
        "db_exists": status.db_exists,
        "last_updated": status.last_updated,
    }


def _format_bootstrap_status(status: BootstrapStatus) -> str:
    """Render a concise human-readable bootstrap summary."""
    state = "ready" if status.ready else "not ready"
    lines = [
        "Smart Wallet Bootstrap Status:",
        f"  Ready: {state}",
        f"  Reasons: {', '.join(status.reasons) if status.reasons else 'none'}",
        f"  Smart Wallets: {status.wallet_count}",
        f"  smart_wallets.json: {'present' if status.scores_exists else 'missing'}",
        f"  wallet_scores.db: {'present' if status.db_exists else 'missing'}",
        f"  Last Updated: {status.last_updated or 'unknown'}",
        (
            f"  Thresholds: min_trades={MIN_TRADES}, min_markets={MIN_UNIQUE_MARKETS}, "
            f"min_vol=${MIN_TOTAL_VOLUME}, max_age={BOOTSTRAP_MAX_AGE_HOURS}h"
        ),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wallet Scorer — Builds and maintains smart wallet database
# ---------------------------------------------------------------------------
class WalletScorer:
    """Identifies and scores top-performing Polymarket wallets."""

    def __init__(self, db_path: Path = DB_FILE, scores_path: Path = SCORES_FILE):
        db_path = Path(db_path)
        scores_path = Path(scores_path)
        scores_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.scores_path = scores_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def close(self) -> None:
        """Close the SQLite connection cleanly."""
        try:
            self.conn.close()
        except Exception:
            pass

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS wallet_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                title TEXT,
                side TEXT,
                outcome TEXT,
                outcome_index INTEGER,
                effective_outcome INTEGER,
                size REAL,
                price REAL,
                timestamp INTEGER,
                is_crypto_fast INTEGER DEFAULT 0,
                event_slug TEXT,
                pnl REAL,
                UNIQUE(wallet, condition_id, timestamp, side, outcome_index)
            );

            CREATE TABLE IF NOT EXISTS wallet_scores (
                wallet TEXT PRIMARY KEY,
                total_trades INTEGER DEFAULT 0,
                crypto_trades INTEGER DEFAULT 0,
                unique_markets INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0.0,
                total_volume REAL DEFAULT 0.0,
                avg_size REAL DEFAULT 0.0,
                win_rate REAL DEFAULT 0.0,
                activity_score REAL DEFAULT 0.0,
                is_smart INTEGER DEFAULT 0,
                last_active TEXT,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_wt_wallet ON wallet_trades(wallet);
            CREATE INDEX IF NOT EXISTS idx_wt_condition ON wallet_trades(condition_id);
            CREATE INDEX IF NOT EXISTS idx_wt_crypto ON wallet_trades(is_crypto_fast);
            CREATE INDEX IF NOT EXISTS idx_ws_smart ON wallet_scores(is_smart);
            CREATE INDEX IF NOT EXISTS idx_ws_score ON wallet_scores(activity_score);
        """)
        self.conn.commit()

    def fetch_trades_batch(self, limit: int = 100, offset: int = 0) -> list:
        """Fetch a batch of trades from the data API."""
        try:
            resp = requests.get(
                f"{DATA_API}/trades",
                params={"limit": min(limit, 100), "offset": offset},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"Data API returned {resp.status_code} at offset {offset}")
        except Exception as e:
            logger.error(f"Fetch failed at offset {offset}: {e}")
        return []

    def fetch_bulk_trades(self, total_limit: int = INITIAL_FETCH_LIMIT) -> list:
        """Fetch many trades in batches for wallet discovery."""
        all_trades = []
        batch_size = 100
        for offset in range(0, total_limit, batch_size):
            batch = self.fetch_trades_batch(batch_size, offset)
            if not batch:
                break
            all_trades.extend(batch)
            if len(batch) < batch_size:
                break
            # Gentle rate limiting
            if offset > 0 and offset % 500 == 0:
                logger.info(f"  Fetched {len(all_trades)} trades so far...")
                time.sleep(0.5)
            else:
                time.sleep(0.15)
        return all_trades

    def fetch_wallet_trades(self, wallet: str, limit: int = PER_WALLET_FETCH_LIMIT) -> list:
        """Fetch trades for a specific wallet."""
        try:
            resp = requests.get(
                f"{DATA_API}/trades",
                params={"proxyWallet": wallet, "limit": limit},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Wallet trades fetch failed for {wallet[:12]}...: {e}")
        return []

    def ingest_trades(self, trades: list) -> int:
        """Store trades in the database. Returns count of new trades."""
        new_count = 0
        c = self.conn.cursor()
        for t in trades:
            wallet = t.get("proxyWallet", "")
            if not wallet:
                continue

            title = t.get("title", "") or ""
            side = t.get("side", "") or ""
            outcome = t.get("outcome", "") or ""
            outcome_index = t.get("outcomeIndex", 0)
            try:
                outcome_index = int(outcome_index)
            except (TypeError, ValueError):
                outcome_index = 0

            effective = get_effective_outcome(side, outcome_index)
            crypto_fast = 1 if is_crypto_fast_market(title) else 0
            event_slug = t.get("eventSlug", "") or ""

            try:
                c.execute("""
                    INSERT OR IGNORE INTO wallet_trades
                    (wallet, condition_id, title, side, outcome, outcome_index,
                     effective_outcome, size, price, timestamp, is_crypto_fast, event_slug)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    wallet,
                    t.get("conditionId", ""),
                    title,
                    side,
                    outcome,
                    outcome_index,
                    effective,
                    float(t.get("size", 0) or 0),
                    float(t.get("price", 0) or 0),
                    int(t.get("timestamp", 0) or 0),
                    crypto_fast,
                    event_slug,
                ))
                if c.rowcount > 0:
                    new_count += 1
            except Exception as e:
                logger.debug(f"Ingest error: {e}")
                continue
        self.conn.commit()
        return new_count

    def discover_wallets(self, trades: list) -> list:
        """
        Discover candidate wallets from trade data.
        Returns wallet addresses sorted by activity (frequency first, then volume).
        """
        from collections import defaultdict
        wallet_stats = defaultdict(lambda: {"count": 0, "volume": 0.0, "markets": set(),
                                            "crypto_count": 0})

        for t in trades:
            w = t.get("proxyWallet", "")
            if not w:
                continue
            size = float(t.get("size", 0) or 0)
            wallet_stats[w]["count"] += 1
            wallet_stats[w]["volume"] += size
            wallet_stats[w]["markets"].add(t.get("conditionId", ""))
            if is_crypto_fast_market(t.get("title", "")):
                wallet_stats[w]["crypto_count"] += 1

        # Sort by trade frequency (active traders are more informative than one-off whales)
        sorted_wallets = sorted(
            wallet_stats.items(),
            key=lambda x: (x[1]["count"], x[1]["volume"]),
            reverse=True,
        )

        logger.info(
            f"Discovery: {len(sorted_wallets)} unique wallets, "
            f"top by freq: {sorted_wallets[0][0][:12]}...({sorted_wallets[0][1]['count']} trades)"
            if sorted_wallets else "no wallets found"
        )

        return [w for w, _ in sorted_wallets]

    def compute_scores(self) -> list:
        """
        Compute wallet scores from trade data.

        Scoring is based on:
        1. Trade frequency (active traders)
        2. Market diversity (not just one-market bots)
        3. Crypto fast-market specialization (relevant to our signal use case)
        4. Size consistency (disciplined traders)
        5. Volume (skin in the game)
        """
        c = self.conn.cursor()

        rows = c.execute("""
            SELECT
                wallet,
                COUNT(*) as total_trades,
                SUM(CASE WHEN is_crypto_fast = 1 THEN 1 ELSE 0 END) as crypto_trades,
                AVG(size) as avg_size,
                SUM(size) as total_volume,
                MAX(timestamp) as last_active,
                COUNT(DISTINCT condition_id) as unique_markets
            FROM wallet_trades
            GROUP BY wallet
            HAVING total_trades >= ?
            ORDER BY total_trades DESC
        """, (MIN_TRADES,)).fetchall()

        scores = []
        for row in rows:
            wallet = row["wallet"]
            total_trades = row["total_trades"]
            crypto_trades = row["crypto_trades"] or 0
            avg_size = row["avg_size"] or 0
            total_volume = row["total_volume"] or 0
            unique_markets = row["unique_markets"] or 0

            # Qualification check
            if unique_markets < MIN_UNIQUE_MARKETS:
                continue
            if total_volume < MIN_TOTAL_VOLUME:
                continue

            # --- Composite Activity Score ---
            # Higher = more likely to be an informed trader

            # 1. Frequency score: log-scaled trade count (0-30 points)
            import math
            freq_score = min(30, math.log2(max(total_trades, 1)) * 5)

            # 2. Diversity score: trading many markets (0-20 points)
            div_score = min(20, unique_markets * 2)

            # 3. Crypto specialization: bonus for crypto fast-market activity (0-20 points)
            crypto_ratio = crypto_trades / total_trades if total_trades > 0 else 0
            crypto_score = min(20, crypto_ratio * 25 + (1 if crypto_trades >= 3 else 0) * 5)

            # 4. Volume score: more skin in game (0-15 points)
            vol_score = min(15, math.log10(max(total_volume, 1)) * 5)

            # 5. Size consistency: low coefficient of variation = disciplined (0-15 points)
            # (Approximated: if avg_size is reasonable relative to volume, it's consistent)
            size_ratio = avg_size / (total_volume / total_trades) if total_trades > 0 else 1
            consistency_score = min(15, 15 * (1 - abs(1 - size_ratio)))

            activity_score = freq_score + div_score + crypto_score + vol_score + consistency_score

            # Win rate is unknown at MVP — will improve with resolution tracking
            estimated_win_rate = 0.50

            score = WalletScore(
                address=wallet,
                total_trades=total_trades,
                crypto_trades=crypto_trades,
                unique_markets=unique_markets,
                avg_size=avg_size,
                total_volume=total_volume,
                win_rate=estimated_win_rate,
                total_pnl=0.0,  # Unknown until we track resolutions
                activity_score=activity_score,
                is_smart=True,
                last_active=str(row["last_active"]),
            )
            scores.append(score)

            # Update DB
            c.execute("""
                INSERT OR REPLACE INTO wallet_scores
                (wallet, total_trades, crypto_trades, unique_markets, wins, losses,
                 total_pnl, total_volume, avg_size, win_rate, activity_score,
                 is_smart, last_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                wallet, total_trades, crypto_trades, unique_markets, 0, 0,
                0.0, total_volume, avg_size, estimated_win_rate, activity_score,
                1, score.last_active, datetime.now(timezone.utc).isoformat(),
            ))

        self.conn.commit()

        # Sort by activity score (highest first)
        scores.sort(key=lambda s: s.activity_score, reverse=True)
        logger.info(f"Scored {len(rows)} wallets with {MIN_TRADES}+ trades, "
                    f"{len(scores)} qualify as smart")
        return scores

    def get_smart_wallets(self) -> dict:
        """Get current smart wallet registry as {address: WalletScore}."""
        c = self.conn.cursor()
        rows = c.execute("""
            SELECT * FROM wallet_scores WHERE is_smart = 1
            ORDER BY activity_score DESC
        """).fetchall()

        smart = {}
        for row in rows:
            smart[row["wallet"]] = WalletScore(
                address=row["wallet"],
                total_trades=row["total_trades"],
                crypto_trades=row["crypto_trades"],
                unique_markets=row["unique_markets"],
                wins=row["wins"],
                losses=row["losses"],
                total_pnl=row["total_pnl"],
                total_volume=row["total_volume"],
                avg_size=row["avg_size"],
                win_rate=row["win_rate"],
                activity_score=row["activity_score"],
                is_smart=True,
                last_active=row["last_active"],
            )
        return smart

    def save_smart_wallets_json(self, scores: list):
        """Save smart wallet list to JSON for quick loading."""
        self.scores_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(scores),
            "wallets": {s.address: asdict(s) for s in scores},
        }
        with open(self.scores_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(scores)} smart wallets to {self.scores_path}")

    def build_initial_scores(self):
        """Full pipeline: fetch trades → discover wallets → profile → score → save."""
        logger.info("=== Building initial wallet scores ===")

        # 1. Bulk fetch recent trades
        logger.info(f"Fetching {INITIAL_FETCH_LIMIT} recent trades...")
        bulk_trades = self.fetch_bulk_trades(INITIAL_FETCH_LIMIT)
        logger.info(f"Fetched {len(bulk_trades)} trades total")

        ingested = self.ingest_trades(bulk_trades)
        logger.info(f"Ingested {ingested} new trades from bulk fetch")

        # 2. Discover top wallets from the bulk data
        wallets = self.discover_wallets(bulk_trades)

        # 3. Profile top wallets individually (deeper history)
        profiled = 0
        for i, wallet in enumerate(wallets[:TOP_WALLETS_TO_PROFILE]):
            trades = self.fetch_wallet_trades(wallet, PER_WALLET_FETCH_LIMIT)
            if trades:
                new = self.ingest_trades(trades)
                if new > 0:
                    profiled += 1
                    if profiled % 10 == 0:
                        logger.info(f"  Profiled {profiled}/{min(len(wallets), TOP_WALLETS_TO_PROFILE)} wallets...")
            time.sleep(0.25)  # Rate limit

        logger.info(f"Profiled {profiled} wallets with new trade data")

        # 4. Compute scores
        scores = self.compute_scores()

        # 5. Save
        self.save_smart_wallets_json(scores)

        logger.info(f"=== Done: {len(scores)} smart wallets identified ===")
        return scores


def ensure_bootstrap_artifacts(
    scores_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> BootstrapStatus:
    """
    Rebuild wallet-flow bootstrap artifacts when they are missing or stale.

    This keeps jj_live startup self-contained on fresh VPS deploys where the
    wallet-flow data files were not copied over yet.
    """
    scores_target = scores_path or SCORES_FILE
    db_target = db_path or DB_FILE
    status = get_bootstrap_status(scores_path=scores_target, db_path=db_target)
    if status.ready:
        return status

    logger.info(
        "Wallet-flow bootstrap missing or stale (%s) — rebuilding locally",
        ", ".join(status.reasons) if status.reasons else "unknown",
    )

    scorer: Optional[WalletScorer] = None
    try:
        scorer = WalletScorer(db_path=db_target, scores_path=scores_target)
        scorer.build_initial_scores()
    except Exception as exc:
        logger.warning(f"Wallet-flow bootstrap rebuild failed: {exc}")
    finally:
        if scorer is not None:
            scorer.close()

    return get_bootstrap_status(scores_path=scores_target, db_path=db_target)


# ---------------------------------------------------------------------------
# Flow Monitor — Real-time trade flow monitoring
# ---------------------------------------------------------------------------
class FlowMonitor:
    """Monitors real-time trade flow for smart wallet activity."""

    def __init__(self, smart_wallets: dict):
        """
        Args:
            smart_wallets: {address: WalletScore} dict of tracked wallets
        """
        self.smart_wallets = smart_wallets
        self.last_seen_timestamp = int(time.time()) - 300  # Start 5 min ago
        self._recent_trades = []  # Rolling window of recent smart trades

    def poll_trades(self) -> list:
        """Fetch new trades since last poll. Returns list of smart wallet trades."""
        try:
            resp = requests.get(
                f"{DATA_API}/trades",
                params={"limit": 100},
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            trades = resp.json()
        except Exception as e:
            logger.error(f"Poll failed: {e}")
            return []

        smart_trades = []
        max_ts = self.last_seen_timestamp

        for t in trades:
            ts = int(t.get("timestamp", 0) or 0)
            if ts <= self.last_seen_timestamp:
                continue
            max_ts = max(max_ts, ts)

            wallet = t.get("proxyWallet", "")
            if wallet in self.smart_wallets:
                # Enrich with effective outcome
                side = t.get("side", "")
                outcome_index = t.get("outcomeIndex", 0)
                t["_effective_outcome"] = get_effective_outcome(side, outcome_index)
                t["_is_crypto_fast"] = is_crypto_fast_market(t.get("title", ""))
                smart_trades.append(t)
                self._recent_trades.append(t)

        self.last_seen_timestamp = max_ts

        # Trim rolling window to CONSENSUS_WINDOW_MINUTES
        cutoff = int(time.time()) - (CONSENSUS_WINDOW_MINUTES * 60)
        self._recent_trades = [
            t for t in self._recent_trades
            if int(t.get("timestamp", 0) or 0) > cutoff
        ]

        if smart_trades:
            for t in smart_trades:
                w = t["proxyWallet"][:12]
                title = t.get("title", "")[:50]
                side = t.get("side", "?")
                outcome = t.get("outcome", "?")
                size = float(t.get("size", 0) or 0)
                score = self.smart_wallets.get(t["proxyWallet"])
                score_str = f"score={score.activity_score:.0f}" if score else ""
                logger.info(
                    f"  SMART: {w}... {side} {outcome} ${size:.2f} | {title} [{score_str}]"
                )

        return smart_trades

    def get_consensus_signals(self) -> list:
        """
        Check for wallet consensus in the rolling window.

        Groups trades by (conditionId, effective_outcome) — which is which
        outcome of the market smart wallets are betting on.

        Returns list of WalletFlowSignal for markets where N+ smart wallets
        agree on the same effective outcome.
        """
        market_sides = {}  # {(conditionId, effective_outcome): [trades]}
        market_all_sides: Dict[str, Dict[int, list]] = {}

        for t in self._recent_trades:
            wallet = t.get("proxyWallet", "")
            if wallet not in self.smart_wallets:
                continue

            cid = t.get("conditionId", "")
            effective = t.get("_effective_outcome")
            if effective is None:
                effective = get_effective_outcome(
                    t.get("side", ""),
                    t.get("outcomeIndex", 0)
                )

            key = (cid, effective)
            if key not in market_sides:
                market_sides[key] = []
            market_sides[key].append(t)
            market_all_sides.setdefault(cid, {}).setdefault(effective, []).append(t)

        # Check for consensus
        signals = []
        now = int(time.time())

        for (cid, effective_outcome), trades in market_sides.items():
            # Count unique smart wallets
            unique_wallets = set(t["proxyWallet"] for t in trades)
            if len(unique_wallets) < MIN_SMART_WALLETS_AGREE:
                continue

            # Calculate aggregate metrics
            total_size = sum(float(t.get("size", 0) or 0) for t in trades)
            if total_size < MIN_TOTAL_SIZE_USD:
                continue

            # Average activity score of agreeing wallets
            scores_list = []
            for w in unique_wallets:
                if w in self.smart_wallets:
                    scores_list.append(self.smart_wallets[w].activity_score)
            avg_score = sum(scores_list) / len(scores_list) if scores_list else 0

            # Signal age (how old is the earliest trade in this consensus)
            earliest_ts = min(int(t.get("timestamp", 0) or 0) for t in trades)
            signal_age = now - earliest_ts

            # Confidence based on number of wallets and their quality
            wallet_factor = min(0.3, (len(unique_wallets) - 2) * 0.1)
            quality_factor = min(0.2, (avg_score / 100) * 0.2)
            size_factor = min(0.15, (total_size / 100) * 0.15)
            base_confidence = min(0.95, 0.35 + wallet_factor + quality_factor + size_factor)

            opposite_outcome = 1 - int(effective_outcome)
            opposing_trades = market_all_sides.get(cid, {}).get(opposite_outcome, [])
            opposing_wallets = {t.get("proxyWallet", "") for t in opposing_trades if t.get("proxyWallet", "")}
            opposing_size = sum(float(t.get("size", 0) or 0) for t in opposing_trades)

            combined_size = max(1e-6, total_size + opposing_size)
            consensus_share = max(0.0, min(1.0, total_size / combined_size))
            opposition_penalty = min(0.20, (1.0 - consensus_share) * 0.35)

            max_age_seconds = max(1, CONSENSUS_WINDOW_MINUTES * 60)
            freshness_factor = max(0.40, 1.0 - (signal_age / (max_age_seconds * 1.25)))
            confidence = min(0.95, max(0.01, (base_confidence * freshness_factor) - opposition_penalty))

            title = trades[0].get("title", "Unknown Market")
            outcome_name = trades[0].get("outcome", f"Outcome {effective_outcome}")
            direction = f"outcome_{effective_outcome}"
            window_start_ts, window_minutes = _parse_window_metadata_from_title(
                title,
                reference_ts=earliest_ts,
            )

            signal = WalletFlowSignal(
                market_id=cid,
                market_title=title,
                direction=direction,
                outcome_name=outcome_name,
                confidence=confidence,
                smart_wallets_count=len(unique_wallets),
                total_smart_size=total_size,
                avg_smart_score=avg_score,
                signal_age_seconds=signal_age,
                timestamp=datetime.now(timezone.utc).isoformat(),
                wallet_consensus_wallets=len(unique_wallets),
                wallet_consensus_notional_usd=round(total_size, 4),
                wallet_consensus_share=round(consensus_share, 4),
                wallet_opposition_wallets=len(opposing_wallets),
                wallet_opposition_notional_usd=round(opposing_size, 4),
                wallet_signal_age_seconds=round(float(signal_age), 4),
                wallet_window_start_ts=window_start_ts,
                wallet_window_minutes=window_minutes,
            )
            signals.append(signal)

            logger.info(
                f"CONSENSUS SIGNAL: {outcome_name} ({direction}) on {title[:50]}\n"
                f"  Wallets: {len(unique_wallets)} | Size: ${total_size:.2f} | "
                f"Opposition: {len(opposing_wallets)} wallets ${opposing_size:.2f} | "
                f"Confidence: {confidence:.2f} | Avg Score: {avg_score:.0f} | "
                f"Age: {signal_age}s | Share: {consensus_share:.2f}"
            )

        return signals


# ---------------------------------------------------------------------------
# Integration: scan_for_signals() — called by jj_live.py
# ---------------------------------------------------------------------------

# Module-level monitor for persistent state between scan calls
_persistent_monitor: Optional[FlowMonitor] = None
_monitor_initialized_at: float = 0


def scan_for_signals() -> list:
    """
    Main entry point for integration with jj_live.py.

    Returns list of WalletFlowSignal dicts ready for the trading engine.
    Maintains a persistent FlowMonitor instance so the rolling window
    accumulates across multiple scan calls.
    """
    global _persistent_monitor, _monitor_initialized_at

    status = get_bootstrap_status()
    if not status.ready:
        _persistent_monitor = None
        logger.warning(
            "Wallet flow bootstrap not ready: %s",
            ", ".join(status.reasons),
        )
        return []

    try:
        smart, _ = load_smart_wallets()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _persistent_monitor = None
        logger.warning(f"Failed to load smart wallets for scan: {exc}")
        return []

    if not smart:
        _persistent_monitor = None
        return []

    # Create or refresh monitor (refresh every 30 min to pick up new wallets)
    now = time.time()
    if _persistent_monitor is None or (now - _monitor_initialized_at) > 1800:
        _persistent_monitor = FlowMonitor(smart)
        _monitor_initialized_at = now
        logger.info(f"Initialized FlowMonitor with {len(smart)} smart wallets")

    # Fetch recent trades and check for consensus
    _persistent_monitor.poll_trades()
    signals = _persistent_monitor.get_consensus_signals()

    out: list[Dict[str, Any]] = []
    for signal in signals:
        if isinstance(signal, WalletFlowSignal):
            out.append(asdict(signal))
        elif isinstance(signal, dict):
            out.append(signal)
    return out


def get_signals_for_engine() -> list:
    """
    Wrapper around scan_for_signals() that converts WalletFlowSignal dicts
    to the standard signal format expected by jj_live.py's confirmation layer.

    Returns list of signal dicts with: market_id, question, direction,
    market_price, estimated_prob, edge, confidence, reasoning, source, etc.
    """
    raw_signals = _resolve_conflicting_market_signals(scan_for_signals())
    engine_signals = []

    for sig in raw_signals:
        # Convert direction: "outcome_0" → "buy_yes", "outcome_1" → "buy_no"
        raw_dir = sig.get("direction", "")
        if raw_dir == "outcome_0":
            direction = "buy_yes"
        elif raw_dir == "outcome_1":
            direction = "buy_no"
        else:
            continue

        confidence = sig.get("confidence", 0.5)
        wallet_count = sig.get("smart_wallets_count", 0)
        total_size = sig.get("total_smart_size", 0)
        avg_score = sig.get("avg_smart_score", 0)

        # Estimate edge from confidence (wallet consensus confidence maps roughly to edge)
        # Higher confidence = more wallets agree = stronger signal
        edge = max(0.01, confidence - 0.35)  # Base 0.35 → ~0% edge, 0.95 → ~60% edge

        reasoning = (
            f"Wallet flow: {wallet_count} smart wallets agree on "
            f"{sig.get('outcome_name', '?')}, total ${total_size:.2f}, "
            f"avg score {avg_score:.0f}, age {sig.get('signal_age_seconds', 0):.0f}s"
        )
        conflict_resolution = sig.get("conflict_resolution")
        if isinstance(conflict_resolution, dict):
            suppressed_direction = str(conflict_resolution.get("suppressed_direction") or "?")
            suppressed_wallets = int(conflict_resolution.get("suppressed_wallets", 0) or 0)
            suppressed_size = float(conflict_resolution.get("suppressed_size", 0.0) or 0.0)
            reasoning += (
                f"; suppressed opposite-direction consensus "
                f"({suppressed_direction}, {suppressed_wallets} wallets, ${suppressed_size:.2f})"
            )

        payload: Dict[str, Any] = {
            "market_id": sig.get("market_id", ""),
            "question": sig.get("market_title", ""),
            "direction": direction,
            "market_price": 0.5,  # Unknown from wallet flow — will be filled by caller
            "estimated_prob": confidence,
            "edge": round(edge, 4),
            "confidence": round(confidence, 4),
            "reasoning": reasoning,
            "source": "wallet_flow",
            "taker_fee": 0.0,  # Maker orders
            "category": "crypto",
            "resolution_hours": 0.25,  # Fast markets (15 min default)
            "velocity_score": edge * 365 * 24 / 0.25,  # Annualized edge / lockup
        }

        consensus_wallets = sig.get("wallet_consensus_wallets")
        if consensus_wallets is None:
            consensus_wallets = sig.get("smart_wallets_count")
        if consensus_wallets is not None:
            payload["wallet_consensus_wallets"] = int(consensus_wallets)

        consensus_notional = sig.get("wallet_consensus_notional_usd")
        if consensus_notional is None:
            consensus_notional = sig.get("total_smart_size")
        if consensus_notional is not None:
            payload["wallet_consensus_notional_usd"] = float(consensus_notional)

        if sig.get("wallet_consensus_share") is not None:
            payload["wallet_consensus_share"] = float(sig.get("wallet_consensus_share"))
        if sig.get("wallet_opposition_wallets") is not None:
            payload["wallet_opposition_wallets"] = int(sig.get("wallet_opposition_wallets"))
        if sig.get("wallet_opposition_notional_usd") is not None:
            payload["wallet_opposition_notional_usd"] = float(sig.get("wallet_opposition_notional_usd"))

        signal_age = sig.get("wallet_signal_age_seconds")
        if signal_age is None:
            signal_age = sig.get("signal_age_seconds")
        if signal_age is not None:
            payload["wallet_signal_age_seconds"] = float(signal_age)

        if sig.get("wallet_window_start_ts"):
            payload["wallet_window_start_ts"] = sig.get("wallet_window_start_ts")
        if sig.get("wallet_window_minutes") is not None:
            payload["wallet_window_minutes"] = int(sig.get("wallet_window_minutes"))
        if isinstance(conflict_resolution, dict):
            payload["wallet_conflict_resolution"] = conflict_resolution

        engine_signals.append(payload)

    return engine_signals


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Smart Wallet Flow Detector — Signal Source #2 for JJ"
    )
    parser.add_argument("--build-scores", action="store_true",
                       help="Build initial wallet scores from trade data")
    parser.add_argument("--monitor", action="store_true",
                       help="Run continuous monitoring loop")
    parser.add_argument("--scan", action="store_true",
                       help="Single scan for signals (for integration)")
    parser.add_argument("--status", action="store_true",
                       help="Show current smart wallet database status")
    parser.add_argument("--status-json", action="store_true",
                       help="Emit machine-readable bootstrap status as JSON")
    parser.add_argument("--top", type=int, default=20,
                       help="Number of wallets to display (default: 20)")
    args = parser.parse_args()

    if args.build_scores:
        scorer = WalletScorer()
        scores = scorer.build_initial_scores()
        print(f"\n{'='*70}")
        print(f"Smart wallets identified: {len(scores)}")
        print(f"{'='*70}")
        for i, s in enumerate(scores[:args.top]):
            print(
                f"  {i+1:3d}. {s.address[:18]}... | "
                f"score={s.activity_score:.0f} trades={s.total_trades} "
                f"crypto={s.crypto_trades} markets={s.unique_markets} "
                f"vol=${s.total_volume:.0f} avg=${s.avg_size:.1f}"
            )

    elif args.monitor:
        status = get_bootstrap_status()
        if not status.ready:
            print(_format_bootstrap_status(status))
            return
        try:
            smart, _ = load_smart_wallets()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Failed to load smart wallets: {exc}")
            return

        print(f"Monitoring {len(smart)} smart wallets...")
        print(f"Polling every {POLL_INTERVAL_SECONDS}s | "
              f"Consensus: {MIN_SMART_WALLETS_AGREE} wallets / "
              f"{CONSENSUS_WINDOW_MINUTES}min window / "
              f"${MIN_TOTAL_SIZE_USD} min size")
        print("-" * 60)

        monitor = FlowMonitor(smart)
        poll_count = 0

        while True:
            try:
                new_trades = monitor.poll_trades()
                poll_count += 1

                if new_trades:
                    signals = monitor.get_consensus_signals()
                    if signals:
                        for s in signals:
                            print(f"\n{'='*60}")
                            print(f"SIGNAL: {s.outcome_name} on {s.market_title}")
                            print(f"  Direction: {s.direction}")
                            print(f"  Wallets: {s.smart_wallets_count} | "
                                  f"Size: ${s.total_smart_size:.2f} | "
                                  f"Confidence: {s.confidence:.2f}")
                            print(f"  Avg Score: {s.avg_smart_score:.0f} | "
                                  f"Age: {s.signal_age_seconds}s")
                            print(f"{'='*60}")

                # Periodic heartbeat
                if poll_count % 20 == 0:
                    window_size = len(monitor._recent_trades)
                    print(f"  [heartbeat] poll #{poll_count} | "
                          f"{window_size} trades in window")

                time.sleep(POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                print(f"\nStopping monitor after {poll_count} polls.")
                break

    elif args.scan:
        signals = scan_for_signals()
        print(json.dumps(signals, indent=2))

    elif args.status or args.status_json:
        status = get_bootstrap_status()
        if args.status_json:
            print(json.dumps(_bootstrap_status_payload(status), indent=2, sort_keys=True))
            return

        print(_format_bootstrap_status(status))

        if status.scores_exists:
            try:
                data = _load_scores_payload()
                wallets = data.get("wallets", {})
                if isinstance(wallets, dict) and wallets:
                    print()
                    sorted_wallets = sorted(
                        wallets.items(),
                        key=lambda x: x[1].get("activity_score", 0),
                        reverse=True,
                    )
                    for i, (addr, info) in enumerate(sorted_wallets[:args.top]):
                        print(
                            f"  {i+1:3d}. {addr[:18]}... | "
                            f"score={info.get('activity_score', 0):.0f} "
                            f"trades={info.get('total_trades', 0)} "
                            f"crypto={info.get('crypto_trades', 0)} "
                            f"markets={info.get('unique_markets', 0)} "
                            f"vol=${info.get('total_volume', 0):.0f}"
                        )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"\n  Wallet list unavailable: {exc}")

        # Also show DB stats if available
        if DB_FILE.exists():
            conn = sqlite3.connect(str(DB_FILE))
            c = conn.cursor()
            try:
                total_trades = c.execute("SELECT COUNT(*) FROM wallet_trades").fetchone()[0]
                total_wallets = c.execute("SELECT COUNT(DISTINCT wallet) FROM wallet_trades").fetchone()[0]
                crypto_trades = c.execute("SELECT COUNT(*) FROM wallet_trades WHERE is_crypto_fast=1").fetchone()[0]
                print(f"\n  Database: {total_trades} trades, {total_wallets} wallets, "
                      f"{crypto_trades} crypto-fast trades")
            except Exception:
                pass
            conn.close()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
