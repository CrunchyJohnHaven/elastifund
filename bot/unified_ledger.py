"""
Unified Trade Ledger — Single source of truth for all execution paths.

Replaces fragmented jj_trades.db + btc_5min_maker.db with one schema.
Wallet API remains the authoritative external truth; this ledger is the
authoritative internal record that all subsystems read and write.
"""
import sqlite3
import hashlib
import json
import os
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("UNIFIED_LEDGER_PATH", "data/unified_ledger.db")


class OrderStatus(Enum):
    PENDING = "pending"
    PLACED = "placed"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SKIPPED = "skipped"


class PromotionProof(Enum):
    MECHANISM = "mechanism"
    DATA = "data"
    STATISTICAL = "statistical"
    EXECUTION = "execution"
    LIVE = "live"


@dataclass
class TradeRecord:
    trade_id: str  # UUID or deterministic hash
    instance_id: str  # "jj_live", "btc5_maker", "kalshi_weather", etc.
    market_id: str
    token_id: str
    condition_id: str = ""
    slug: str = ""
    direction: str = ""  # UP/DOWN/YES/NO
    side: str = ""  # BUY/SELL

    # Order details
    order_id: str = ""
    order_price: float = 0.0
    order_size: float = 0.0
    order_type: str = "POST_ONLY"  # POST_ONLY, LIMIT, MARKET
    order_status: str = "pending"
    skip_reason: str = ""

    # Fill details
    fill_price: float = 0.0
    fill_size: float = 0.0
    fill_time: str = ""
    fill_latency_seconds: float = 0.0
    partial_fills: int = 0

    # P&L
    entry_price: float = 0.0
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees_paid: float = 0.0

    # Strategy context
    strategy_name: str = ""
    signal_confidence: float = 0.0
    kelly_fraction: float = 0.0
    edge_estimate: float = 0.0

    # Metadata
    paper: bool = False
    created_at: str = ""
    updated_at: str = ""
    resolved_at: str = ""
    resolution_outcome: str = ""  # WIN/LOSS/PUSH

    # Reconciliation
    wallet_matched: bool = False
    wallet_match_time: str = ""
    reconciliation_notes: str = ""

    # Fingerprint for dedup
    fingerprint: str = ""

    def compute_fingerprint(self) -> str:
        raw = f"{self.instance_id}|{self.market_id}|{self.token_id}|{self.direction}|{self.order_id}|{self.created_at}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class UnifiedLedger:
    """Single-writer, multi-reader trade ledger."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                instance_id TEXT NOT NULL,
                market_id TEXT NOT NULL,
                token_id TEXT NOT NULL,
                condition_id TEXT DEFAULT '',
                slug TEXT DEFAULT '',
                direction TEXT DEFAULT '',
                side TEXT DEFAULT '',

                order_id TEXT DEFAULT '',
                order_price REAL DEFAULT 0.0,
                order_size REAL DEFAULT 0.0,
                order_type TEXT DEFAULT 'POST_ONLY',
                order_status TEXT DEFAULT 'pending',
                skip_reason TEXT DEFAULT '',

                fill_price REAL DEFAULT 0.0,
                fill_size REAL DEFAULT 0.0,
                fill_time TEXT DEFAULT '',
                fill_latency_seconds REAL DEFAULT 0.0,
                partial_fills INTEGER DEFAULT 0,

                entry_price REAL DEFAULT 0.0,
                exit_price REAL DEFAULT 0.0,
                realized_pnl REAL DEFAULT 0.0,
                unrealized_pnl REAL DEFAULT 0.0,
                fees_paid REAL DEFAULT 0.0,

                strategy_name TEXT DEFAULT '',
                signal_confidence REAL DEFAULT 0.0,
                kelly_fraction REAL DEFAULT 0.0,
                edge_estimate REAL DEFAULT 0.0,

                paper INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT DEFAULT '',
                resolution_outcome TEXT DEFAULT '',

                wallet_matched INTEGER DEFAULT 0,
                wallet_match_time TEXT DEFAULT '',
                reconciliation_notes TEXT DEFAULT '',

                fingerprint TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                trade_id TEXT NOT NULL REFERENCES trades(trade_id),
                order_id TEXT NOT NULL,
                fill_price REAL NOT NULL,
                fill_size REAL NOT NULL,
                fill_time TEXT NOT NULL,
                cumulative_filled REAL DEFAULT 0.0,
                raw_json TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reconciliation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT REFERENCES trades(trade_id),
                reconciliation_time TEXT NOT NULL,
                source TEXT NOT NULL,  -- 'wallet_api', 'csv_export', 'manual'
                action TEXT NOT NULL,  -- 'matched', 'backfilled', 'phantom_removed', 'pnl_corrected'
                old_value TEXT DEFAULT '',
                new_value TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS skip_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instance_id TEXT NOT NULL,
                market_id TEXT DEFAULT '',
                slug TEXT DEFAULT '',
                direction TEXT DEFAULT '',
                skip_reason TEXT NOT NULL,
                skip_detail TEXT DEFAULT '',
                delta_value REAL DEFAULT 0.0,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trades_instance ON trades(instance_id);
            CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
            CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(order_status);
            CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);
            CREATE INDEX IF NOT EXISTS idx_trades_fingerprint ON trades(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_fills_trade ON fills(trade_id);
            CREATE INDEX IF NOT EXISTS idx_skip_instance ON skip_log(instance_id);
            CREATE INDEX IF NOT EXISTS idx_skip_reason ON skip_log(skip_reason);
        """)
        conn.commit()
        conn.close()

    def record_trade(self, trade: TradeRecord) -> str:
        """Insert or update a trade record. Returns trade_id."""
        now = datetime.now(timezone.utc).isoformat()
        if not trade.created_at:
            trade.created_at = now
        trade.updated_at = now
        if not trade.fingerprint:
            trade.fingerprint = trade.compute_fingerprint()

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT OR REPLACE INTO trades (
                    trade_id, instance_id, market_id, token_id, condition_id, slug,
                    direction, side, order_id, order_price, order_size, order_type,
                    order_status, skip_reason, fill_price, fill_size, fill_time,
                    fill_latency_seconds, partial_fills, entry_price, exit_price,
                    realized_pnl, unrealized_pnl, fees_paid, strategy_name,
                    signal_confidence, kelly_fraction, edge_estimate, paper,
                    created_at, updated_at, resolved_at, resolution_outcome,
                    wallet_matched, wallet_match_time, reconciliation_notes,
                    fingerprint
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                trade.trade_id, trade.instance_id, trade.market_id, trade.token_id,
                trade.condition_id, trade.slug, trade.direction, trade.side,
                trade.order_id, trade.order_price, trade.order_size, trade.order_type,
                trade.order_status, trade.skip_reason, trade.fill_price, trade.fill_size,
                trade.fill_time, trade.fill_latency_seconds, trade.partial_fills,
                trade.entry_price, trade.exit_price, trade.realized_pnl,
                trade.unrealized_pnl, trade.fees_paid, trade.strategy_name,
                trade.signal_confidence, trade.kelly_fraction, trade.edge_estimate,
                int(trade.paper), trade.created_at, trade.updated_at,
                trade.resolved_at, trade.resolution_outcome,
                int(trade.wallet_matched), trade.wallet_match_time,
                trade.reconciliation_notes, trade.fingerprint
            ))
            conn.commit()
            logger.info(f"Recorded trade {trade.trade_id} [{trade.instance_id}] {trade.order_status}")
            return trade.trade_id
        finally:
            conn.close()

    def record_fill(self, trade_id: str, order_id: str, fill_price: float,
                    fill_size: float, fill_time: str, raw_json: str = "") -> str:
        """Record a fill event and update the parent trade."""
        import uuid
        fill_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            # Get cumulative
            row = conn.execute(
                "SELECT COALESCE(SUM(fill_size), 0) FROM fills WHERE trade_id = ?",
                (trade_id,)
            ).fetchone()
            cumulative = (row[0] if row else 0.0) + fill_size

            conn.execute("""
                INSERT INTO fills (fill_id, trade_id, order_id, fill_price, fill_size,
                                   fill_time, cumulative_filled, raw_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (fill_id, trade_id, order_id, fill_price, fill_size,
                  fill_time, cumulative, raw_json, now))

            # Update parent trade
            conn.execute("""
                UPDATE trades SET
                    fill_price = ?, fill_size = ?, fill_time = ?,
                    partial_fills = partial_fills + 1,
                    order_status = CASE
                        WHEN ? >= order_size THEN 'filled'
                        ELSE 'partially_filled'
                    END,
                    updated_at = ?
                WHERE trade_id = ?
            """, (fill_price, cumulative, fill_time, cumulative, now, trade_id))

            conn.commit()
            logger.info(f"Fill recorded: trade={trade_id} price={fill_price} size={fill_size} cumulative={cumulative}")
            return fill_id
        finally:
            conn.close()

    def record_skip(self, instance_id: str, skip_reason: str, market_id: str = "",
                    slug: str = "", direction: str = "", skip_detail: str = "",
                    delta_value: float = 0.0):
        """Record a skip decision to the skip log (separate from trades)."""
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO skip_log (instance_id, market_id, slug, direction,
                                      skip_reason, skip_detail, delta_value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (instance_id, market_id, slug, direction, skip_reason,
                  skip_detail, delta_value, now))
            conn.commit()
        finally:
            conn.close()

    def reconcile_from_wallet(self, wallet_positions: list, source: str = "wallet_api"):
        """Match wallet API positions against local trades. Backfill missing."""
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            matched = 0
            backfilled = 0
            for pos in wallet_positions:
                condition_id = pos.get("conditionId", pos.get("condition_id", ""))
                token_id = pos.get("tokenId", pos.get("token_id", ""))

                row = conn.execute(
                    "SELECT trade_id FROM trades WHERE condition_id = ? AND token_id = ?",
                    (condition_id, token_id)
                ).fetchone()

                if row:
                    # Match existing
                    conn.execute("""
                        UPDATE trades SET wallet_matched = 1, wallet_match_time = ?,
                            updated_at = ? WHERE trade_id = ?
                    """, (now, now, row[0]))
                    conn.execute("""
                        INSERT INTO reconciliation_log (trade_id, reconciliation_time, source, action, notes)
                        VALUES (?, ?, ?, 'matched', ?)
                    """, (row[0], now, source, json.dumps(pos)))
                    matched += 1
                else:
                    # Backfill from wallet — inline insert to avoid second connection
                    import uuid
                    trade_id = f"wallet_backfill_{str(uuid.uuid4())[:8]}"
                    size = float(pos.get("size", pos.get("currentQty", 0)))
                    avg_price = float(pos.get("avgPrice", pos.get("avg_price", 0)))
                    pnl = float(pos.get("realizedPnl", pos.get("pnl", 0)))
                    market = pos.get("market", pos.get("market_slug", ""))
                    slug = pos.get("slug", pos.get("market_slug", ""))
                    direction = pos.get("outcome", "")
                    fp_raw = f"wallet_backfill|{market}|{token_id}|{direction}||{now}"
                    fingerprint = hashlib.sha256(fp_raw.encode()).hexdigest()[:16]

                    conn.execute("""
                        INSERT OR REPLACE INTO trades (
                            trade_id, instance_id, market_id, token_id, condition_id, slug,
                            direction, side, order_id, order_price, order_size, order_type,
                            order_status, skip_reason, fill_price, fill_size, fill_time,
                            fill_latency_seconds, partial_fills, entry_price, exit_price,
                            realized_pnl, unrealized_pnl, fees_paid, strategy_name,
                            signal_confidence, kelly_fraction, edge_estimate, paper,
                            created_at, updated_at, resolved_at, resolution_outcome,
                            wallet_matched, wallet_match_time, reconciliation_notes,
                            fingerprint
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                    """, (
                        trade_id, "wallet_backfill", market, token_id,
                        condition_id, slug, direction, "BUY",
                        "", 0.0, 0.0, "POST_ONLY",
                        "filled", "", avg_price, size,
                        "", 0.0, 0,
                        avg_price, 0.0, pnl,
                        0.0, 0.0, "",
                        0.0, 0.0, 0.0, 0,
                        now, now, "", "",
                        1, now, f"Backfilled from {source}",
                        fingerprint
                    ))
                    conn.execute("""
                        INSERT INTO reconciliation_log (trade_id, reconciliation_time, source, action, notes)
                        VALUES (?, ?, ?, 'backfilled', ?)
                    """, (trade_id, now, source, json.dumps(pos)))
                    backfilled += 1

            conn.commit()
            logger.info(f"Reconciliation: {matched} matched, {backfilled} backfilled from {source}")
            return {"matched": matched, "backfilled": backfilled}
        finally:
            conn.close()

    def get_trades(self, instance_id: str = None, status: str = None,
                   since: str = None, limit: int = 1000) -> list:
        """Query trades with optional filters."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = "SELECT * FROM trades WHERE 1=1"
            params = []
            if instance_id:
                query += " AND instance_id = ?"
                params.append(instance_id)
            if status:
                query += " AND order_status = ?"
                params.append(status)
            if since:
                query += " AND created_at >= ?"
                params.append(since)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_skip_stats(self, instance_id: str = None, hours: int = 24) -> dict:
        """Get skip reason breakdown for monitoring."""
        conn = sqlite3.connect(self.db_path)
        try:
            query = """
                SELECT skip_reason, COUNT(*) as cnt
                FROM skip_log
                WHERE timestamp >= datetime('now', ?)
            """
            params = [f"-{hours} hours"]
            if instance_id:
                query += " AND instance_id = ?"
                params.append(instance_id)
            query += " GROUP BY skip_reason ORDER BY cnt DESC"

            rows = conn.execute(query, params).fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            conn.close()

    def get_pnl_summary(self, instance_id: str = None) -> dict:
        """Get P&L summary across all trades."""
        conn = sqlite3.connect(self.db_path)
        try:
            query = """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN order_status = 'filled' THEN 1 ELSE 0 END) as filled,
                    SUM(CASE WHEN order_status = 'skipped' THEN 1 ELSE 0 END) as skipped,
                    SUM(CASE WHEN resolution_outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN resolution_outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(realized_pnl), 0) as total_realized_pnl,
                    COALESCE(SUM(unrealized_pnl), 0) as total_unrealized_pnl,
                    COALESCE(SUM(fees_paid), 0) as total_fees
                FROM trades WHERE 1=1
            """
            params = []
            if instance_id:
                query += " AND instance_id = ?"
                params.append(instance_id)

            row = conn.execute(query, params).fetchone()
            total = row[0] or 0
            filled = row[1] or 0
            wins = row[3] or 0
            losses = row[4] or 0

            return {
                "total_trades": total,
                "filled": filled,
                "skipped": row[2] or 0,
                "wins": wins,
                "losses": losses,
                "win_rate": wins / max(wins + losses, 1),
                "fill_rate": filled / max(total, 1),
                "total_realized_pnl": row[5],
                "total_unrealized_pnl": row[6],
                "total_fees": row[7],
                "net_pnl": row[5] + row[6] - row[7],
            }
        finally:
            conn.close()
