#!/usr/bin/env python3
"""Standalone edge discovery data collector.

Runs independently of jj_live.py. Scans 50+ diverse markets every 15 minutes,
records market prices to edge_discovery.db, and handles CLOB errors gracefully
via quarantine. Can run on local machine or VPS as a cron job or daemon.

Usage:
    python scripts/run_edge_collector.py                    # Run daemon (loop)
    python scripts/run_edge_collector.py --once             # Single scan
    python scripts/run_edge_collector.py --interval 600     # Custom interval (10 min)
    python scripts/run_edge_collector.py --target-markets 80  # More markets

Environment:
    EDGE_COLLECTOR_INTERVAL  - scan interval seconds (default 900 = 15 min)
    EDGE_COLLECTOR_TARGET    - target market count (default 50)
    EDGE_COLLECTOR_DB        - database path (default data/edge_discovery.db)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.market_quarantine import MarketQuarantine
from bot.expanded_scanner import ExpandedScanner, MarketSnapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("edge_collector")


class EdgeCollector:
    """Collects market price snapshots for edge discovery analysis."""

    def __init__(
        self,
        db_path: str | Path = "data/edge_discovery.db",
        target_markets: int = 50,
        min_volume: float = 1000.0,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.quarantine = MarketQuarantine(db_path=db_path)
        self.scanner = ExpandedScanner(
            quarantine=self.quarantine,
            target_market_count=target_markets,
            min_volume=min_volume,
        )
        self._init_tables()
        self._shutdown = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_tables(self) -> None:
        """Ensure all required tables exist."""
        with self._connect() as conn:
            # Market registry table (upsert on each scan)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS markets (
                    market_id TEXT PRIMARY KEY,
                    condition_id TEXT UNIQUE,
                    slug TEXT UNIQUE,
                    timeframe TEXT,
                    question TEXT,
                    resolution_source TEXT,
                    window_start_ts INTEGER,
                    window_end_ts INTEGER,
                    market_start_ts INTEGER,
                    market_end_ts INTEGER,
                    opening_price REAL,
                    final_resolution TEXT,
                    active INTEGER,
                    closed INTEGER,
                    yes_token_id TEXT,
                    no_token_id TEXT,
                    updated_at_ts INTEGER,
                    raw_json TEXT
                )
            """)

            # Price snapshots table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_prices (
                    condition_id TEXT,
                    timestamp_ts INTEGER,
                    yes_price REAL,
                    no_price REAL,
                    source TEXT,
                    PRIMARY KEY (condition_id, timestamp_ts)
                )
            """)

            # Collection runs audit
            conn.execute("""
                CREATE TABLE IF NOT EXISTS collector_runs (
                    run_id TEXT PRIMARY KEY,
                    timestamp_ts INTEGER NOT NULL,
                    markets_scanned INTEGER NOT NULL,
                    markets_collected INTEGER NOT NULL,
                    prices_recorded INTEGER NOT NULL,
                    quarantined_count INTEGER NOT NULL,
                    categories_json TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL
                )
            """)

    def _record_prices(
        self, snapshots: list[MarketSnapshot], now_ts: int
    ) -> int:
        """Record price snapshots to edge_discovery.db. Returns count recorded."""
        recorded = 0
        with self._connect() as conn:
            for snap in snapshots:
                # Upsert market metadata
                conn.execute(
                    """INSERT OR REPLACE INTO markets
                    (market_id, question, active, closed, yes_token_id, no_token_id, updated_at_ts)
                    VALUES (?, ?, 1, 0, ?, ?, ?)""",
                    (
                        snap.market_id,
                        snap.question,
                        snap.token_ids[0] if snap.token_ids else None,
                        snap.token_ids[1] if len(snap.token_ids) > 1 else None,
                        now_ts,
                    ),
                )

                # Record price snapshot (condition_id = market_id in this context)
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO market_prices
                        (condition_id, timestamp_ts, yes_price, no_price, source)
                        VALUES (?, ?, ?, ?, ?)""",
                        (
                            snap.market_id,
                            now_ts,
                            snap.yes_price,
                            snap.no_price,
                            "edge_collector",
                        ),
                    )
                    recorded += 1
                except sqlite3.IntegrityError:
                    pass  # Duplicate timestamp, skip
        return recorded

    def _record_run(
        self,
        run_id: str,
        now_ts: int,
        scanned: int,
        collected: int,
        prices_recorded: int,
        categories: dict[str, int],
        elapsed: float,
    ) -> None:
        """Log collection run metadata."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO collector_runs
                (run_id, timestamp_ts, markets_scanned, markets_collected,
                 prices_recorded, quarantined_count, categories_json, elapsed_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    now_ts,
                    scanned,
                    collected,
                    prices_recorded,
                    len(self.quarantine.get_quarantined_ids()),
                    json.dumps(categories),
                    round(elapsed, 2),
                ),
            )

    async def collect_once(self) -> dict:
        """Run a single collection cycle. Returns summary dict."""
        start = time.time()
        now_ts = int(time.time())
        run_id = hashlib.sha1(f"ec-{now_ts}".encode()).hexdigest()[:12]

        logger.info("collection_cycle_start", run_id=run_id)

        # Cleanup expired quarantine entries
        self.quarantine.cleanup_expired()

        # Scan diverse markets
        snapshots = await self.scanner.scan_diverse_markets()

        # Categorize for logging
        categories: dict[str, int] = {}
        for snap in snapshots:
            categories[snap.category] = categories.get(snap.category, 0) + 1

        # Record prices
        prices_recorded = self._record_prices(snapshots, now_ts)

        elapsed = time.time() - start

        # Audit
        self._record_run(
            run_id=run_id,
            now_ts=now_ts,
            scanned=len(snapshots),
            collected=len(snapshots),
            prices_recorded=prices_recorded,
            categories=categories,
            elapsed=elapsed,
        )

        summary = {
            "run_id": run_id,
            "markets_scanned": len(snapshots),
            "prices_recorded": prices_recorded,
            "categories": categories,
            "quarantine_stats": self.quarantine.stats(),
            "elapsed_seconds": round(elapsed, 2),
        }

        logger.info(
            "collection_cycle_complete",
            markets=len(snapshots),
            prices=prices_recorded,
            categories=len(categories),
            quarantined=summary["quarantine_stats"]["active_count"],
            elapsed=f"{elapsed:.1f}s",
        )
        return summary

    async def run_daemon(self, interval_seconds: int = 900) -> None:
        """Run collection loop until shutdown signal."""
        logger.info(
            "edge_collector_daemon_start",
            interval=interval_seconds,
            db=str(self.db_path),
        )

        cycle = 0
        hourly_summary_at = time.time()

        while not self._shutdown:
            cycle += 1
            try:
                summary = await self.collect_once()

                # Hourly summary
                if time.time() - hourly_summary_at >= 3600:
                    q_stats = self.quarantine.stats()
                    logger.info(
                        "EDGE COLLECTOR HOURLY: %d cycles, last scan %d markets, "
                        "%d quarantined",
                        cycle,
                        summary["markets_scanned"],
                        q_stats["active_count"],
                    )
                    hourly_summary_at = time.time()

            except Exception as e:
                logger.error("collection_cycle_error", error=str(e), cycle=cycle)

            # Wait for next cycle or shutdown
            for _ in range(interval_seconds):
                if self._shutdown:
                    break
                await asyncio.sleep(1)

        logger.info("edge_collector_daemon_shutdown", cycles_completed=cycle)
        await self.scanner.close()

    def request_shutdown(self) -> None:
        """Signal the daemon to stop after current cycle."""
        logger.info("shutdown_requested")
        self._shutdown = True


def main():
    parser = argparse.ArgumentParser(
        description="Edge discovery data collector daemon"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single collection cycle and exit",
    )
    parser.add_argument(
        "--interval", type=int,
        default=int(os.getenv("EDGE_COLLECTOR_INTERVAL", "900")),
        help="Scan interval in seconds (default: 900 = 15 min)",
    )
    parser.add_argument(
        "--target-markets", type=int,
        default=int(os.getenv("EDGE_COLLECTOR_TARGET", "50")),
        help="Target number of diverse markets (default: 50)",
    )
    parser.add_argument(
        "--db", type=str,
        default=os.getenv("EDGE_COLLECTOR_DB", "data/edge_discovery.db"),
        help="Database path (default: data/edge_discovery.db)",
    )
    args = parser.parse_args()

    collector = EdgeCollector(
        db_path=args.db,
        target_markets=args.target_markets,
    )

    # Register signal handlers for clean shutdown
    def handle_signal(signum, frame):
        collector.request_shutdown()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if args.once:
        summary = asyncio.run(collector.collect_once())
        print(json.dumps(summary, indent=2))
    else:
        asyncio.run(collector.run_daemon(interval_seconds=args.interval))


if __name__ == "__main__":
    main()
