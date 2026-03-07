#!/usr/bin/env python3
"""B-1 dependency graph shadow monitor.

Runs the B-1 violation monitor in shadow mode: scans every 5 minutes,
logs violations to SQLite, does NOT execute trades.

Usage:
    python scripts/run_b1_shadow.py
    python scripts/run_b1_shadow.py --scan-interval 300 --db-path data/constraint_arb.db
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.b1_monitor import B1Monitor, B1MonitorBatch, B1Opportunity
from bot.constraint_arb_engine import (
    CandidateGenerator,
    ConstraintArbEngine,
    GraphEdge,
    MarketQuote,
    fetch_gamma_markets,
)
from bot.resolution_normalizer import NormalizedMarket, normalize_market

logger = logging.getLogger("JJ.b1_shadow")

DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
DEFAULT_DB_PATH = Path("data") / "constraint_arb.db"
DEFAULT_RELATION_THRESHOLD = 0.03
DEFAULT_STALE_BOOK_SECONDS = 120  # more lenient for shadow mode (REST polling)


class B1ShadowMonitor:
    """Standalone shadow-mode B-1 violation scanner."""

    def __init__(
        self,
        *,
        db_path: Path = DEFAULT_DB_PATH,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        relation_threshold: float = DEFAULT_RELATION_THRESHOLD,
        stale_book_seconds: int = DEFAULT_STALE_BOOK_SECONDS,
        max_pages: int = 3,
        page_limit: int = 200,
    ) -> None:
        self.db_path = Path(db_path)
        self.scan_interval = max(60, int(scan_interval))
        self.max_pages = max_pages
        self.page_limit = page_limit
        self._running = True
        self._scan_count = 0
        self._total_violations = 0
        self._hourly_scan_count = 0
        self._hourly_violation_count = 0
        self._hour_start = time.time()

        self.engine = ConstraintArbEngine(db_path=self.db_path)
        self.monitor = B1Monitor(
            relation_threshold=relation_threshold,
            stale_book_seconds=stale_book_seconds,
        )

        self._init_violation_table()

    def _init_violation_table(self) -> None:
        """Create the b1_violations table if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS b1_violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    timestamp_iso TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    market_a_id TEXT NOT NULL,
                    market_b_id TEXT NOT NULL,
                    basket_action TEXT NOT NULL,
                    trigger_edge REAL NOT NULL,
                    theoretical_edge REAL NOT NULL,
                    relation_confidence REAL NOT NULL,
                    resolution_gate_status TEXT NOT NULL,
                    quote_age_seconds INTEGER NOT NULL,
                    details_json TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'shadow'
                );

                CREATE INDEX IF NOT EXISTS idx_b1_violations_ts
                    ON b1_violations(timestamp);
                CREATE INDEX IF NOT EXISTS idx_b1_violations_relation
                    ON b1_violations(relation_type);
                CREATE INDEX IF NOT EXISTS idx_b1_violations_edge
                    ON b1_violations(edge_id);
            """)
            conn.commit()
        finally:
            conn.close()

    def _log_violation(self, opp: B1Opportunity) -> None:
        """Persist a violation to SQLite."""
        now = int(time.time())
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            conn.execute(
                """
                INSERT INTO b1_violations (
                    timestamp, timestamp_iso, edge_id, relation_type,
                    market_a_id, market_b_id, basket_action,
                    trigger_edge, theoretical_edge, relation_confidence,
                    resolution_gate_status, quote_age_seconds, details_json, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    now_iso,
                    opp.edge_id,
                    opp.relation_type,
                    opp.market_ids[0],
                    opp.market_ids[1],
                    opp.basket_action,
                    float(opp.trigger_edge),
                    float(opp.theoretical_edge),
                    float(opp.relation_confidence),
                    opp.resolution_gate_status,
                    int(opp.quote_age_seconds),
                    json.dumps(opp.details, sort_keys=True),
                    "shadow",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _fetch_and_register_markets(self) -> list[NormalizedMarket]:
        """Fetch markets from Gamma and register in engine."""
        raw = fetch_gamma_markets(max_pages=self.max_pages, page_limit=self.page_limit)
        if not raw:
            logger.warning("No markets fetched from Gamma API")
            return []
        return self.engine.register_markets(raw)

    def _fetch_quotes(self, markets: list[NormalizedMarket]) -> None:
        """Fetch current order book quotes for registered markets.

        Uses the Gamma API for mid-price approximation since we don't have
        WebSocket in shadow mode.
        """
        now_ts = int(time.time())
        for market in markets:
            # Use the engine's existing quote if fresh enough
            existing = self.engine.quotes.get(market.market_id)
            if existing and (now_ts - existing.updated_ts) < self.monitor.stale_book_seconds:
                continue

            # In shadow mode, we approximate from any available data
            # The engine build_constraint_graph will handle quote freshness
            # For now, just mark as needing update
            pass

    def _build_graph_and_scan(self) -> B1MonitorBatch | None:
        """Run a full scan cycle: fetch, classify, detect violations."""
        try:
            markets = self._fetch_and_register_markets()
            if not markets:
                return None

            logger.info("Registered %d markets, building constraint graph", len(markets))
            edges = self.engine.build_constraint_graph(max_pairs=500)
            logger.info("Built %d graph edges", len(edges))

            if not edges:
                return None

            # Scan for violations
            batch = self.monitor.scan_engine(self.engine, now_ts=int(time.time()))
            return batch

        except Exception:
            logger.exception("Scan cycle failed")
            return None

    def _process_batch(self, batch: B1MonitorBatch) -> None:
        """Process scan results: log violations, update counters."""
        metrics = batch.metrics

        for opp in batch.executable:
            self._log_violation(opp)
            self._total_violations += 1
            self._hourly_violation_count += 1
            logger.info(
                "VIOLATION: %s | edge=%s | trigger=%.4f | theory=%.4f | conf=%.2f | %s vs %s",
                opp.relation_type,
                opp.edge_id[:12],
                opp.trigger_edge,
                opp.theoretical_edge,
                opp.relation_confidence,
                opp.market_ids[0][:12],
                opp.market_ids[1][:12],
            )

        if batch.log_only:
            logger.debug(
                "Log-only violations: %d (non-tradable relation types)",
                len(batch.log_only),
            )

        logger.info(
            "Scan #%d: executable=%d, log_only=%d, dropped=%d (stale=%d, gate=%d, dup=%d)",
            self._scan_count,
            metrics["executable_count"],
            metrics["log_only_count"],
            metrics["dropped_count"],
            metrics.get("stale_book_count", 0),
            metrics.get("resolution_gate_drop_count", 0),
            metrics.get("duplicate_drop_count", 0),
        )

    def _maybe_log_hourly_summary(self) -> None:
        """Log summary every hour."""
        elapsed = time.time() - self._hour_start
        if elapsed >= 3600:
            logger.info(
                "B-1 SHADOW HOURLY: %d pairs monitored, %d violations detected, "
                "total scans=%d, total violations=%d",
                len(self.engine.edges),
                self._hourly_violation_count,
                self._scan_count,
                self._total_violations,
            )
            self._hourly_scan_count = 0
            self._hourly_violation_count = 0
            self._hour_start = time.time()

    def run(self) -> None:
        """Main loop: scan every interval until SIGINT."""
        logger.info(
            "B-1 shadow monitor starting (interval=%ds, threshold=%.3f, db=%s)",
            self.scan_interval,
            self.monitor.relation_threshold,
            self.db_path,
        )

        while self._running:
            self._scan_count += 1
            self._hourly_scan_count += 1

            batch = self._build_graph_and_scan()
            if batch is not None:
                self._process_batch(batch)

            self._maybe_log_hourly_summary()

            if not self._running:
                break

            logger.debug("Sleeping %ds until next scan", self.scan_interval)
            # Interruptible sleep
            for _ in range(self.scan_interval):
                if not self._running:
                    break
                time.sleep(1)

        logger.info(
            "B-1 shadow monitor stopped. Total scans=%d, total violations=%d",
            self._scan_count,
            self._total_violations,
        )

    def stop(self) -> None:
        """Signal the monitor to stop."""
        self._running = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan-interval", type=int, default=DEFAULT_SCAN_INTERVAL, help="Seconds between scans")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite database path")
    parser.add_argument("--relation-threshold", type=float, default=DEFAULT_RELATION_THRESHOLD)
    parser.add_argument("--stale-book-seconds", type=int, default=DEFAULT_STALE_BOOK_SECONDS)
    parser.add_argument("--max-pages", type=int, default=3, help="Gamma API pages per scan")
    parser.add_argument("--page-limit", type=int, default=200, help="Markets per page")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    shadow = B1ShadowMonitor(
        db_path=Path(args.db_path),
        scan_interval=args.scan_interval,
        relation_threshold=args.relation_threshold,
        stale_book_seconds=args.stale_book_seconds,
        max_pages=args.max_pages,
        page_limit=args.page_limit,
    )

    def handle_signal(signum: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down gracefully", signum)
        shadow.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    shadow.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
