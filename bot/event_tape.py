#!/usr/bin/env python3
"""
Event Tape Writer — Append-only event log for every system decision and observation.
====================================================================================
Phase 1: Writer only (no replay engine). Captures immutable events to a SQLite-backed
tape with monotonic sequence numbers, causal chains, and correlation grouping.

Architecture:
  - TapeEvent: frozen dataclass envelope (seq, ts, event_type, source, session_id,
    payload, causation_seq, correlation_id)
  - EventTapeWriter: SQLite-backed append-only writer with typed helpers for every
    canonical event family (market, book, decision, execution, settlement, system)

Storage:
  Single SQLite database with WAL journaling. Events table with indexes on
  event_type, correlation_id, ts, and causation_seq for fast querying.

Thread safety:
  All writes go through a threading.Lock so concurrent emitters never interleave.

Usage:
    writer = EventTapeWriter("data/tape/tape.db")
    evt = writer.emit("market.discovered", "jj_live", {"condition_id": "0x...", ...})
    chain = writer.query_causal_chain(evt.seq)
    pnl = writer.derive_pnl()
    writer.close()

March 2026 — Elastifund / JJ
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("JJ.event_tape")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TapeEvent:
    """Immutable event envelope. Every event on the tape shares this shape."""

    seq: int                    # Monotonically increasing, no gaps within a session
    ts: int                     # Unix microseconds (time.time_ns() // 1000)
    event_type: str             # Dot-namespaced: "market.discovered", "decision.trade_proposed"
    source: str                 # Component that emitted: "btc5_maker", "jj_live", "wallet_recon"
    session_id: str             # Runtime session UUID, set at process start
    payload: dict[str, Any]     # Event-type-specific fields
    causation_seq: int | None   # seq of the event that caused this one (causal chain)
    correlation_id: str | None  # Groups related events (e.g., all events for one BTC5 window)


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    seq             INTEGER PRIMARY KEY,
    ts              INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    source          TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    causation_seq   INTEGER,
    correlation_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_event_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_correlation_id ON events (correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS idx_events_causation_seq ON events (causation_seq);
"""

# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class EventTapeWriter:
    """
    Append-only event tape backed by SQLite.

    Thread-safe: all mutations are serialized through a lock. The SQLite
    connection uses WAL mode for concurrent readers.
    """

    def __init__(
        self,
        db_path: str = "data/tape/tape.db",
        session_id: str | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._session_id = session_id or uuid.uuid4().hex
        self._lock = threading.Lock()

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

        # Recover next seq from existing data
        row = self._conn.execute("SELECT MAX(seq) AS m FROM events").fetchone()
        self._next_seq: int = (row["m"] or 0) + 1

        logger.info(
            "EventTapeWriter initialized db=%s session=%s next_seq=%d",
            self._db_path,
            self._session_id,
            self._next_seq,
        )

    @property
    def session_id(self) -> str:
        return self._session_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EventTapeWriter":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Core emit
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        source: str,
        payload: dict[str, Any],
        causation_seq: int | None = None,
        correlation_id: str | None = None,
    ) -> TapeEvent:
        """Append an event to the tape. Returns the event with assigned seq."""
        ts = time.time_ns() // 1000  # Unix microseconds

        with self._lock:
            seq = self._next_seq
            self._next_seq += 1

            event = TapeEvent(
                seq=seq,
                ts=ts,
                event_type=event_type,
                source=source,
                session_id=self._session_id,
                payload=payload,
                causation_seq=causation_seq,
                correlation_id=correlation_id,
            )

            self._conn.execute(
                """
                INSERT INTO events (seq, ts, event_type, source, session_id,
                                    payload, causation_seq, correlation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.seq,
                    event.ts,
                    event.event_type,
                    event.source,
                    event.session_id,
                    json.dumps(event.payload),
                    event.causation_seq,
                    event.correlation_id,
                ),
            )
            self._conn.commit()

        logger.debug(
            "emit seq=%d type=%s source=%s corr=%s",
            seq,
            event_type,
            source,
            correlation_id,
        )
        return event

    # ------------------------------------------------------------------
    # Typed helpers — Market lifecycle
    # ------------------------------------------------------------------

    def emit_market_discovered(
        self,
        condition_id: str,
        market_id: str,
        question: str,
        slug: str,
        category: str,
        end_date_ts: int,
        tokens: list[dict[str, str]],
        source_api: str,
        *,
        source: str = "jj_live",
        causation_seq: int | None = None,
        correlation_id: str | None = None,
    ) -> TapeEvent:
        """Emit a market.discovered event."""
        return self.emit(
            event_type="market.discovered",
            source=source,
            payload={
                "condition_id": condition_id,
                "market_id": market_id,
                "question": question,
                "slug": slug,
                "category": category,
                "end_date_ts": end_date_ts,
                "tokens": tokens,
                "source_api": source_api,
            },
            causation_seq=causation_seq,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Typed helpers — Book
    # ------------------------------------------------------------------

    def emit_book_snapshot(
        self,
        market_id: str,
        token_id: str,
        best_bid: float | None,
        best_ask: float | None,
        bid_depth_usd: float,
        ask_depth_usd: float,
        spread: float,
        midpoint: float,
        imbalance: float,
        book_levels: int,
        *,
        source: str = "btc5_maker",
        causation_seq: int | None = None,
        correlation_id: str | None = None,
    ) -> TapeEvent:
        """Emit a book.snapshot event."""
        return self.emit(
            event_type="book.snapshot",
            source=source,
            payload={
                "market_id": market_id,
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_depth_usd": bid_depth_usd,
                "ask_depth_usd": ask_depth_usd,
                "spread": spread,
                "midpoint": midpoint,
                "imbalance": imbalance,
                "book_levels": book_levels,
            },
            causation_seq=causation_seq,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Typed helpers — Decision
    # ------------------------------------------------------------------

    def emit_decision(
        self,
        decision_type: str,
        payload: dict[str, Any],
        *,
        source: str = "jj_live",
        causation_seq: int | None = None,
        correlation_id: str | None = None,
    ) -> TapeEvent:
        """
        Emit a decision.* event.

        decision_type: one of "trade_proposed", "trade_approved", "trade_rejected",
                       "probability_estimated", "window_skipped"
        """
        event_type = f"decision.{decision_type}"
        return self.emit(
            event_type=event_type,
            source=source,
            payload=payload,
            causation_seq=causation_seq,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Typed helpers — Execution
    # ------------------------------------------------------------------

    def emit_execution(
        self,
        exec_type: str,
        payload: dict[str, Any],
        *,
        source: str = "jj_live",
        causation_seq: int | None = None,
        correlation_id: str | None = None,
    ) -> TapeEvent:
        """
        Emit an execution.* event.

        exec_type: one of "order_placed", "order_filled", "order_cancelled",
                   "order_status_changed", "position_redeemed"
        """
        event_type = f"execution.{exec_type}"
        return self.emit(
            event_type=event_type,
            source=source,
            payload=payload,
            causation_seq=causation_seq,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Typed helpers — Settlement
    # ------------------------------------------------------------------

    def emit_settlement(
        self,
        settlement_type: str,
        payload: dict[str, Any],
        *,
        source: str = "binance_feed",
        causation_seq: int | None = None,
        correlation_id: str | None = None,
    ) -> TapeEvent:
        """
        Emit a settlement.* event.

        settlement_type: one of "binance_price", "candle_open", "oracle_update"
        """
        event_type = f"settlement.{settlement_type}"
        return self.emit(
            event_type=event_type,
            source=source,
            payload=payload,
            causation_seq=causation_seq,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def query_by_type(
        self,
        event_type: str,
        since_ts: int | None = None,
        limit: int = 100,
    ) -> list[TapeEvent]:
        """Return events of a given type, optionally filtered by timestamp."""
        if since_ts is not None:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE event_type = ? AND ts >= ? ORDER BY seq LIMIT ?",
                (event_type, since_ts, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE event_type = ? ORDER BY seq LIMIT ?",
                (event_type, limit),
            ).fetchall()
        return [_row_to_event(r) for r in rows]

    def query_by_correlation(self, correlation_id: str) -> list[TapeEvent]:
        """Return all events sharing a correlation_id, ordered by seq."""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE correlation_id = ? ORDER BY seq",
            (correlation_id,),
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    def query_causal_chain(self, seq: int) -> list[TapeEvent]:
        """
        Walk causation_seq backwards from the given seq, returning the full
        causal chain from root cause to the given event (inclusive).
        """
        chain: list[TapeEvent] = []
        visited: set[int] = set()
        current_seq: int | None = seq

        while current_seq is not None and current_seq not in visited:
            visited.add(current_seq)
            row = self._conn.execute(
                "SELECT * FROM events WHERE seq = ?", (current_seq,)
            ).fetchone()
            if row is None:
                break
            event = _row_to_event(row)
            chain.append(event)
            current_seq = event.causation_seq

        chain.reverse()  # Root cause first
        return chain

    def get_latest_seq(self) -> int:
        """Return the highest seq on the tape, or 0 if empty."""
        row = self._conn.execute("SELECT MAX(seq) AS m FROM events").fetchone()
        return row["m"] or 0

    def count_events(self, event_type: str | None = None) -> int:
        """Count events, optionally filtered by type."""
        if event_type is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE event_type = ?",
                (event_type,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()
        return row["c"]

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    def derive_pnl(self, since_ts: int | None = None) -> dict[str, Any]:
        """
        Derive P&L from execution.order_filled (costs) and
        execution.position_redeemed (payouts) events.

        Returns:
            total_cost: sum of fill_size_usd across all fills
            total_payout: sum of payout_usd across all redemptions
            realized_pnl: total_payout - total_cost
            fill_count: number of fill events
            redemption_count: number of redemption events
            positions: dict of market_id -> {cost, payout, pnl}
        """
        ts_clause = ""
        params: list[Any] = []
        if since_ts is not None:
            ts_clause = " AND ts >= ?"
            params = [since_ts]

        # Fills (costs)
        fill_rows = self._conn.execute(
            f"SELECT payload FROM events WHERE event_type = 'execution.order_filled'{ts_clause} ORDER BY seq",
            params,
        ).fetchall()

        # Redemptions (payouts)
        redeem_rows = self._conn.execute(
            f"SELECT payload FROM events WHERE event_type = 'execution.position_redeemed'{ts_clause} ORDER BY seq",
            params,
        ).fetchall()

        total_cost = 0.0
        total_payout = 0.0
        positions: dict[str, dict[str, float]] = {}

        for row in fill_rows:
            p = json.loads(row["payload"])
            cost = float(p.get("fill_size_usd", 0.0))
            mid = p.get("market_id", "unknown")
            total_cost += cost
            pos = positions.setdefault(mid, {"cost": 0.0, "payout": 0.0, "pnl": 0.0})
            pos["cost"] += cost

        for row in redeem_rows:
            p = json.loads(row["payload"])
            payout = float(p.get("payout_usd", 0.0))
            mid = p.get("market_id", "unknown")
            total_payout += payout
            pos = positions.setdefault(mid, {"cost": 0.0, "payout": 0.0, "pnl": 0.0})
            pos["payout"] += payout

        # Compute per-position P&L
        for pos in positions.values():
            pos["pnl"] = pos["payout"] - pos["cost"]

        return {
            "total_cost": total_cost,
            "total_payout": total_payout,
            "realized_pnl": total_payout - total_cost,
            "fill_count": len(fill_rows),
            "redemption_count": len(redeem_rows),
            "positions": positions,
        }

    def check_wallet_divergence(self, api_balance: float) -> dict[str, Any]:
        """
        Compare tape-derived balance against wallet API balance.

        The tape-derived balance is: sum(payouts) - sum(costs).
        (Initial deposit is NOT included — the caller must account for it
        or compare deltas.)

        Returns:
            tape_derived_balance: float
            api_balance: float
            divergence_usd: absolute difference
            divergence_pct: percentage divergence relative to max of the two
            is_divergent: True if divergence_pct > 5%
        """
        pnl = self.derive_pnl()
        tape_balance = pnl["realized_pnl"]

        max_val = max(abs(tape_balance), abs(api_balance), 0.01)  # avoid div by zero
        divergence_usd = abs(tape_balance - api_balance)
        divergence_pct = divergence_usd / max_val

        return {
            "tape_derived_balance": tape_balance,
            "api_balance": api_balance,
            "divergence_usd": divergence_usd,
            "divergence_pct": divergence_pct,
            "is_divergent": divergence_pct > 0.05,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_event(row: sqlite3.Row) -> TapeEvent:
    """Convert a SQLite row to a TapeEvent."""
    return TapeEvent(
        seq=row["seq"],
        ts=row["ts"],
        event_type=row["event_type"],
        source=row["source"],
        session_id=row["session_id"],
        payload=json.loads(row["payload"]),
        causation_seq=row["causation_seq"],
        correlation_id=row["correlation_id"],
    )
