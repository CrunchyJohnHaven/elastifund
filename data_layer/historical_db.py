"""
Historical Data Pipeline -- Unified multi-venue data layer for edge discovery.

Supports: Polymarket, Kalshi, Alpaca
Stores: market metadata, resolution outcomes, YES-price time series, trades
Enforces: data quality checks, incremental watermarks, rate-limit safety
"""
import sqlite3
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("HISTORICAL_DB_PATH", "data/historical.sqlite3")

SCHEMA_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS markets (
    venue                  TEXT    NOT NULL,
    market_id              TEXT    NOT NULL,
    title                  TEXT,
    category               TEXT,
    rule_type              TEXT,
    rules_primary          TEXT,
    rules_secondary        TEXT,
    settlement_source      TEXT,
    resolution_source      TEXT,
    open_ts                INTEGER,
    close_ts               INTEGER,
    settle_ts              INTEGER,
    fee_model              TEXT,
    taker_fee_param        REAL,
    maker_fee_param        REAL,
    metadata_json          TEXT,
    PRIMARY KEY (venue, market_id)
);

CREATE TABLE IF NOT EXISTS market_resolution (
    venue                  TEXT    NOT NULL,
    market_id              TEXT    NOT NULL,
    outcome_yes            INTEGER NOT NULL CHECK (outcome_yes IN (0,1)),
    settlement_value       REAL    NOT NULL,
    settled_ts             INTEGER NOT NULL,
    time_to_resolution_s   INTEGER NOT NULL,
    final_yes_price        REAL    CHECK (final_yes_price >= 0.0 AND final_yes_price <= 1.0),
    final_yes_price_ts     INTEGER,
    PRIMARY KEY (venue, market_id),
    FOREIGN KEY (venue, market_id) REFERENCES markets(venue, market_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS market_yes_price (
    venue                  TEXT    NOT NULL,
    market_id              TEXT    NOT NULL,
    ts                     INTEGER NOT NULL,
    yes_price              REAL    NOT NULL CHECK (yes_price >= 0.0 AND yes_price <= 1.0),
    best_bid               REAL    CHECK (best_bid >= 0.0 AND best_bid <= 1.0),
    best_ask               REAL    CHECK (best_ask >= 0.0 AND best_ask <= 1.0),
    volume                 REAL,
    source                 TEXT    NOT NULL,
    PRIMARY KEY (venue, market_id, ts),
    FOREIGN KEY (venue, market_id) REFERENCES markets(venue, market_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trades (
    venue                  TEXT    NOT NULL,
    trade_id               TEXT    NOT NULL,
    market_id              TEXT    NOT NULL,
    ts                     INTEGER NOT NULL,
    side                   TEXT,
    price                  REAL    NOT NULL,
    size                   REAL    NOT NULL,
    taker_side             TEXT,
    tx_hash                TEXT,
    PRIMARY KEY (venue, trade_id),
    FOREIGN KEY (venue, market_id) REFERENCES markets(venue, market_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingestion_state (
    venue                  TEXT PRIMARY KEY,
    last_market_scan_ts    INTEGER NOT NULL,
    last_settle_scan_ts    INTEGER NOT NULL,
    notes                  TEXT
);

CREATE TABLE IF NOT EXISTS calibration_snapshots (
    venue                  TEXT    NOT NULL,
    market_id              TEXT    NOT NULL,
    snapshot_type          TEXT    NOT NULL,  -- 'final_trade', 'pre_close_1h', 'vwap_6h'
    snapshot_ts            INTEGER NOT NULL,
    yes_probability        REAL    NOT NULL CHECK (yes_probability >= 0.0 AND yes_probability <= 1.0),
    outcome_yes            INTEGER CHECK (outcome_yes IN (0,1)),
    probability_bin        TEXT,  -- '[0.01,0.05]', '(0.05,0.10]', etc.
    PRIMARY KEY (venue, market_id, snapshot_type)
);

CREATE INDEX IF NOT EXISTS idx_market_yes_price_ts ON market_yes_price (venue, ts);
CREATE INDEX IF NOT EXISTS idx_trades_market_ts ON trades (venue, market_id, ts);
CREATE INDEX IF NOT EXISTS idx_calibration_bin ON calibration_snapshots (probability_bin);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets (venue, category);
CREATE INDEX IF NOT EXISTS idx_markets_settle ON markets (venue, settle_ts);
"""


# Probability bins for calibration (fixed boundaries)
CALIBRATION_BINS = [
    (0.01, 0.05, "[0.01,0.05]"),
    (0.05, 0.10, "(0.05,0.10]"),
    (0.10, 0.20, "(0.10,0.20]"),
    (0.20, 0.30, "(0.20,0.30]"),
    (0.30, 0.40, "(0.30,0.40]"),
    (0.40, 0.50, "(0.40,0.50]"),
    (0.50, 0.60, "(0.50,0.60]"),
    (0.60, 0.70, "(0.60,0.70]"),
    (0.70, 0.80, "(0.70,0.80]"),
    (0.80, 0.90, "(0.80,0.90]"),
    (0.90, 0.95, "(0.90,0.95]"),
    (0.95, 0.99, "(0.95,0.99]"),
]

# Minimum samples per bin for 2pp miscalibration detection (90% power, alpha=0.05)
MIN_SAMPLES_PER_BIN = {
    "[0.01,0.05]": 942,
    "(0.05,0.10]": 1990,
    "(0.10,0.20]": 3489,
    "(0.20,0.30]": 5025,
    "(0.30,0.40]": 6035,
    "(0.40,0.50]": 6519,
    "(0.50,0.60]": 6519,
    "(0.60,0.70]": 6035,
    "(0.70,0.80]": 5025,
    "(0.80,0.90]": 3489,
    "(0.90,0.95]": 1990,
    "(0.95,0.99]": 942,
}


def classify_bin(probability: float) -> str:
    """Classify a probability into its calibration bin."""
    for low, high, label in CALIBRATION_BINS:
        if label.startswith("["):
            if low <= probability <= high:
                return label
        else:
            if low < probability <= high:
                return label
    return "out_of_range"


class HistoricalDB:
    """Manages the unified historical data store."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA_DDL)
        conn.commit()
        conn.close()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_market(self, venue: str, market_id: str, **kwargs):
        """Insert or update a market record."""
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO markets
                (venue, market_id, title, category, rule_type, rules_primary,
                 rules_secondary, settlement_source, resolution_source,
                 open_ts, close_ts, settle_ts, fee_model, taker_fee_param,
                 maker_fee_param, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                venue, market_id,
                kwargs.get("title"), kwargs.get("category"),
                kwargs.get("rule_type", "binary"),
                kwargs.get("rules_primary"), kwargs.get("rules_secondary"),
                kwargs.get("settlement_source"), kwargs.get("resolution_source"),
                kwargs.get("open_ts"), kwargs.get("close_ts"), kwargs.get("settle_ts"),
                kwargs.get("fee_model"), kwargs.get("taker_fee_param"),
                kwargs.get("maker_fee_param"), kwargs.get("metadata_json"),
            ))
            conn.commit()
        finally:
            conn.close()

    def upsert_resolution(self, venue: str, market_id: str, outcome_yes: int,
                          settlement_value: float, settled_ts: int,
                          time_to_resolution_s: int, final_yes_price: float = None,
                          final_yes_price_ts: int = None):
        """Insert or update market resolution."""
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO market_resolution
                (venue, market_id, outcome_yes, settlement_value, settled_ts,
                 time_to_resolution_s, final_yes_price, final_yes_price_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (venue, market_id, outcome_yes, settlement_value, settled_ts,
                  time_to_resolution_s, final_yes_price, final_yes_price_ts))
            conn.commit()
        finally:
            conn.close()

    def insert_yes_prices(self, rows: List[Tuple]):
        """Bulk insert YES price observations.

        Each row: (venue, market_id, ts, yes_price, best_bid, best_ask, volume, source).
        """
        conn = self.get_connection()
        try:
            conn.executemany("""
                INSERT OR IGNORE INTO market_yes_price
                (venue, market_id, ts, yes_price, best_bid, best_ask, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
            logger.info(f"Inserted {len(rows)} yes_price rows")
        finally:
            conn.close()

    def insert_trades(self, rows: List[Tuple]):
        """Bulk insert trades.

        Each row: (venue, trade_id, market_id, ts, side, price, size, taker_side, tx_hash).
        """
        conn = self.get_connection()
        try:
            conn.executemany("""
                INSERT OR IGNORE INTO trades
                (venue, trade_id, market_id, ts, side, price, size, taker_side, tx_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
        finally:
            conn.close()

    def get_watermark(self, venue: str) -> dict:
        """Get ingestion watermarks for a venue."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM ingestion_state WHERE venue = ?", (venue,)
            ).fetchone()
            if row:
                return dict(row)
            return {"venue": venue, "last_market_scan_ts": 0, "last_settle_scan_ts": 0}
        finally:
            conn.close()

    def set_watermark(self, venue: str, last_market_scan_ts: int = None,
                      last_settle_scan_ts: int = None, notes: str = None):
        """Update ingestion watermarks."""
        conn = self.get_connection()
        try:
            existing = self.get_watermark(venue)
            conn.execute("""
                INSERT OR REPLACE INTO ingestion_state
                (venue, last_market_scan_ts, last_settle_scan_ts, notes)
                VALUES (?, ?, ?, ?)
            """, (
                venue,
                last_market_scan_ts or existing.get("last_market_scan_ts", 0),
                last_settle_scan_ts or existing.get("last_settle_scan_ts", 0),
                notes,
            ))
            conn.commit()
        finally:
            conn.close()

    def build_calibration_snapshots(self, snapshot_type: str = "final_trade"):
        """Build calibration snapshot table from resolved markets + price history."""
        conn = self.get_connection()
        try:
            # Get all resolved markets
            rows = conn.execute("""
                SELECT r.venue, r.market_id, r.outcome_yes, r.final_yes_price, r.final_yes_price_ts
                FROM market_resolution r
                WHERE r.final_yes_price IS NOT NULL
            """).fetchall()

            for row in rows:
                prob = row["final_yes_price"]
                bin_label = classify_bin(prob)
                conn.execute("""
                    INSERT OR REPLACE INTO calibration_snapshots
                    (venue, market_id, snapshot_type, snapshot_ts, yes_probability,
                     outcome_yes, probability_bin)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["venue"], row["market_id"], snapshot_type,
                    row["final_yes_price_ts"] or 0, prob,
                    row["outcome_yes"], bin_label,
                ))

            conn.commit()
            logger.info(f"Built {len(rows)} calibration snapshots ({snapshot_type})")
        finally:
            conn.close()

    def get_calibration_stats(self) -> Dict[str, dict]:
        """Get calibration statistics per bin."""
        conn = self.get_connection()
        try:
            rows = conn.execute("""
                SELECT
                    probability_bin,
                    COUNT(*) as n,
                    AVG(outcome_yes) as empirical_rate,
                    AVG(yes_probability) as avg_predicted
                FROM calibration_snapshots
                WHERE probability_bin != 'out_of_range'
                GROUP BY probability_bin
                ORDER BY avg_predicted
            """).fetchall()

            stats = {}
            for row in rows:
                bin_label = row["probability_bin"]
                n = row["n"]
                min_required = MIN_SAMPLES_PER_BIN.get(bin_label, 0)
                stats[bin_label] = {
                    "n": n,
                    "empirical_rate": row["empirical_rate"],
                    "avg_predicted": row["avg_predicted"],
                    "miscalibration": row["empirical_rate"] - row["avg_predicted"] if row["empirical_rate"] else None,
                    "min_required": min_required,
                    "sufficient": n >= min_required,
                }
            return stats
        finally:
            conn.close()

    def run_quality_checks(self) -> List[str]:
        """Run data quality assertions. Returns list of issues found."""
        conn = self.get_connection()
        issues = []
        try:
            # 1. Impossible prices
            bad_prices = conn.execute(
                "SELECT COUNT(*) FROM market_yes_price WHERE yes_price < 0 OR yes_price > 1"
            ).fetchone()[0]
            if bad_prices > 0:
                issues.append(f"CRITICAL: {bad_prices} impossible prices (outside [0,1])")

            # 2. Resolution completeness
            missing_resolution = conn.execute("""
                SELECT COUNT(*) FROM markets m
                LEFT JOIN market_resolution r USING (venue, market_id)
                WHERE m.settle_ts IS NOT NULL AND r.market_id IS NULL
            """).fetchone()[0]
            if missing_resolution > 0:
                issues.append(f"WARNING: {missing_resolution} settled markets without resolution records")

            # 3. Time ordering sanity
            bad_times = conn.execute("""
                SELECT COUNT(*) FROM markets
                WHERE open_ts IS NOT NULL AND close_ts IS NOT NULL AND open_ts >= close_ts
            """).fetchone()[0]
            if bad_times > 0:
                issues.append(f"WARNING: {bad_times} markets with open_ts >= close_ts")

            # 4. Duplicate check (should be impossible with PKs)
            dupes = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT venue, market_id, COUNT(*) as cnt
                    FROM markets GROUP BY 1, 2 HAVING cnt > 1
                )
            """).fetchone()[0]
            if dupes > 0:
                issues.append(f"CRITICAL: {dupes} duplicate market entries")

            # 5. Stale data check
            for venue in ["polymarket", "kalshi"]:
                wm = self.get_watermark(venue)
                if wm["last_market_scan_ts"] > 0:
                    age_hours = (int(datetime.now(timezone.utc).timestamp()) - wm["last_market_scan_ts"]) / 3600
                    if age_hours > 48:
                        issues.append(f"WARNING: {venue} data is {age_hours:.0f} hours stale")

            if not issues:
                issues.append("ALL CHECKS PASSED")

            return issues
        finally:
            conn.close()

    def get_venue_stats(self) -> Dict[str, dict]:
        """Get summary statistics per venue."""
        conn = self.get_connection()
        try:
            stats = {}
            for venue in ["polymarket", "kalshi", "alpaca"]:
                markets = conn.execute(
                    "SELECT COUNT(*) FROM markets WHERE venue = ?", (venue,)
                ).fetchone()[0]
                resolved = conn.execute(
                    "SELECT COUNT(*) FROM market_resolution WHERE venue = ?", (venue,)
                ).fetchone()[0]
                prices = conn.execute(
                    "SELECT COUNT(*) FROM market_yes_price WHERE venue = ?", (venue,)
                ).fetchone()[0]
                trades_count = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE venue = ?", (venue,)
                ).fetchone()[0]

                stats[venue] = {
                    "markets": markets,
                    "resolved": resolved,
                    "price_observations": prices,
                    "trades": trades_count,
                }
            return stats
        finally:
            conn.close()
