"""Persistent shadow tracking for unresolved hypothesis signals."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .backtest import Backtester
from .strategies.base import Signal


@dataclass
class ShadowSummary:
    group: str
    key: str
    label: str
    total_signals: int
    resolved_signals: int
    open_signals: int
    win_rate: float
    ev_maker: float
    ev_taker: float
    last_signal_ts: int
    last_resolved_ts: int


class SignalShadowTracker:
    """Store raw signals and resolve them when market outcomes become available."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS signal_shadow (
                    track_id TEXT PRIMARY KEY,
                    signal_group TEXT NOT NULL,
                    signal_key TEXT NOT NULL,
                    signal_label TEXT NOT NULL,
                    condition_id TEXT NOT NULL,
                    timestamp_ts INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    confidence REAL NOT NULL,
                    edge_estimate REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    resolved_outcome TEXT,
                    win INTEGER,
                    pnl_maker REAL,
                    pnl_taker REAL,
                    created_at_ts INTEGER NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_shadow_group_key ON signal_shadow(signal_group, signal_key);
                CREATE INDEX IF NOT EXISTS idx_shadow_status_condition ON signal_shadow(status, condition_id);
                """
            )

    @staticmethod
    def _track_id(signal_group: str, signal_key: str, signal: Signal) -> str:
        entry = round(float(signal.entry_price), 5)
        return (
            f"{signal_group}:{signal_key}:{signal.condition_id}:"
            f"{int(signal.timestamp_ts)}:{signal.side}:{entry}"
        )

    def record_signals(
        self,
        signal_group: str,
        signal_key: str,
        signal_label: str,
        signals: list[Signal],
    ) -> int:
        if not signals:
            return 0

        now_ts = int(time.time())
        inserted = 0
        with self._connect() as conn:
            for signal in signals:
                track_id = self._track_id(signal_group, signal_key, signal)
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO signal_shadow (
                        track_id, signal_group, signal_key, signal_label,
                        condition_id, timestamp_ts, side, entry_price, confidence,
                        edge_estimate, metadata_json, status, created_at_ts, updated_at_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                    """,
                    (
                        track_id,
                        signal_group,
                        signal_key,
                        signal_label,
                        signal.condition_id,
                        int(signal.timestamp_ts),
                        signal.side,
                        float(signal.entry_price),
                        float(signal.confidence),
                        float(signal.edge_estimate),
                        json.dumps(signal.metadata or {}),
                        now_ts,
                        now_ts,
                    ),
                )
                inserted += max(0, cursor.rowcount or 0)
            conn.commit()
        return inserted

    def resolve(self, resolutions: dict[str, str], backtester: Backtester) -> int:
        if not resolutions:
            return 0

        placeholders = ",".join(["?"] * len(resolutions))
        resolved = 0
        now_ts = int(time.time())

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT track_id, condition_id, side, entry_price, confidence, edge_estimate, metadata_json, timestamp_ts
                FROM signal_shadow
                WHERE status='open' AND condition_id IN ({placeholders})
                """,
                tuple(resolutions.keys()),
            ).fetchall()

            for row in rows:
                condition_id = str(row[1])
                outcome = str(resolutions.get(condition_id) or "")
                if outcome not in ("UP", "DOWN"):
                    continue

                metadata_raw = str(row[6] or "{}")
                try:
                    metadata = json.loads(metadata_raw)
                except Exception:
                    metadata = {}

                signal = Signal(
                    strategy="shadow",
                    condition_id=condition_id,
                    timestamp_ts=int(row[7]),
                    side=str(row[2]),
                    entry_price=float(row[3]),
                    confidence=float(row[4]),
                    edge_estimate=float(row[5]),
                    metadata=metadata,
                )
                pnl = backtester._trade_pnl(signal, outcome)

                conn.execute(
                    """
                    UPDATE signal_shadow
                    SET status='resolved',
                        resolved_outcome=?,
                        win=?,
                        pnl_maker=?,
                        pnl_taker=?,
                        updated_at_ts=?
                    WHERE track_id=?
                    """,
                    (
                        outcome,
                        1 if pnl.win else 0,
                        float(pnl.maker),
                        float(pnl.taker),
                        now_ts,
                        str(row[0]),
                    ),
                )
                resolved += 1
            conn.commit()
        return resolved

    def summaries(self, signal_group: str) -> dict[str, ShadowSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    signal_group,
                    signal_key,
                    signal_label,
                    COUNT(*) AS total_signals,
                    SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved_signals,
                    SUM(CASE WHEN status!='resolved' THEN 1 ELSE 0 END) AS open_signals,
                    AVG(CASE WHEN status='resolved' THEN win END) AS win_rate,
                    AVG(CASE WHEN status='resolved' THEN pnl_maker END) AS ev_maker,
                    AVG(CASE WHEN status='resolved' THEN pnl_taker END) AS ev_taker,
                    MAX(timestamp_ts) AS last_signal_ts,
                    MAX(CASE WHEN status='resolved' THEN updated_at_ts END) AS last_resolved_ts
                FROM signal_shadow
                WHERE signal_group=?
                GROUP BY signal_group, signal_key, signal_label
                """,
                (signal_group,),
            ).fetchall()

        out: dict[str, ShadowSummary] = {}
        for row in rows:
            summary = ShadowSummary(
                group=str(row[0]),
                key=str(row[1]),
                label=str(row[2]),
                total_signals=int(row[3] or 0),
                resolved_signals=int(row[4] or 0),
                open_signals=int(row[5] or 0),
                win_rate=float(row[6] or 0.0),
                ev_maker=float(row[7] or 0.0),
                ev_taker=float(row[8] or 0.0),
                last_signal_ts=int(row[9] or 0),
                last_resolved_ts=int(row[10] or 0),
            )
            out[summary.key] = summary
        return out

    @staticmethod
    def summaries_to_dict(summaries: dict[str, ShadowSummary]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key, summary in summaries.items():
            out[key] = {
                "total_signals": summary.total_signals,
                "resolved_signals": summary.resolved_signals,
                "open_signals": summary.open_signals,
                "win_rate": summary.win_rate,
                "ev_maker": summary.ev_maker,
                "ev_taker": summary.ev_taker,
                "last_signal_ts": summary.last_signal_ts,
                "last_resolved_ts": summary.last_resolved_ts,
            }
        return out
