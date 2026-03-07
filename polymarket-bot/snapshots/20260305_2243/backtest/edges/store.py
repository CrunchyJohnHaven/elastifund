"""SQLite storage for EdgeCards, Experiments, and global config."""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional

from .models import EdgeCard, EdgeStatus, Experiment, ExperimentStatus

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "data", "edges.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    source TEXT DEFAULT 'manual',
    status TEXT DEFAULT 'backlog',
    expected_win_rate REAL,
    expected_ev_per_trade REAL,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    edge_id TEXT NOT NULL REFERENCES edges(id),
    config TEXT DEFAULT '{}',
    status TEXT DEFAULT 'running',
    num_trades INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    max_drawdown REAL DEFAULT 0.0,
    notes TEXT DEFAULT '',
    started_at REAL NOT NULL,
    ended_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_status ON edges(status);
CREATE INDEX IF NOT EXISTS idx_experiments_edge_id ON experiments(edge_id);
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
"""


class EdgeStore:
    """SQLite-backed storage for edges, experiments, and config."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    # --- EdgeCard CRUD ---

    def add_edge(self, edge: EdgeCard) -> EdgeCard:
        self._conn.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            edge.to_row(),
        )
        self._conn.commit()
        return edge

    def get_edge(self, edge_id: str) -> Optional[EdgeCard]:
        row = self._conn.execute(
            "SELECT * FROM edges WHERE id = ?", (edge_id,)
        ).fetchone()
        return EdgeCard.from_row(row) if row else None

    def list_edges(self, status: Optional[str] = None) -> list[EdgeCard]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges ORDER BY created_at DESC"
            ).fetchall()
        return [EdgeCard.from_row(r) for r in rows]

    def update_edge_status(self, edge_id: str, status: str) -> bool:
        now = time.time()
        cur = self._conn.execute(
            "UPDATE edges SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, edge_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_edge(self, edge: EdgeCard) -> bool:
        edge.updated_at = time.time()
        cur = self._conn.execute(
            """UPDATE edges SET name=?, hypothesis=?, source=?, status=?,
               expected_win_rate=?, expected_ev_per_trade=?, tags=?, notes=?,
               updated_at=? WHERE id=?""",
            (edge.name, edge.hypothesis, edge.source, edge.status,
             edge.expected_win_rate, edge.expected_ev_per_trade,
             edge.tags, edge.notes, edge.updated_at, edge.id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # --- Experiment CRUD ---

    def start_experiment(self, experiment: Experiment) -> Experiment:
        # Move edge to testing
        self.update_edge_status(experiment.edge_id, EdgeStatus.TESTING)
        self._conn.execute(
            "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            experiment.to_row(),
        )
        self._conn.commit()
        return experiment

    def get_experiment(self, exp_id: str) -> Optional[Experiment]:
        row = self._conn.execute(
            "SELECT * FROM experiments WHERE id = ?", (exp_id,)
        ).fetchone()
        return Experiment.from_row(row) if row else None

    def list_experiments(
        self, edge_id: Optional[str] = None, status: Optional[str] = None
    ) -> list[Experiment]:
        query = "SELECT * FROM experiments WHERE 1=1"
        params = []
        if edge_id:
            query += " AND edge_id = ?"
            params.append(edge_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY started_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [Experiment.from_row(r) for r in rows]

    def log_result(self, exp_id: str, won: bool, pnl: float) -> Optional[Experiment]:
        """Log a single trade result to an experiment."""
        exp = self.get_experiment(exp_id)
        if not exp or exp.status != ExperimentStatus.RUNNING:
            return None

        exp.num_trades += 1
        if won:
            exp.wins += 1
        else:
            exp.losses += 1
        exp.total_pnl += pnl

        # Track drawdown
        if exp.total_pnl < -exp.max_drawdown:
            exp.max_drawdown = abs(exp.total_pnl)

        exp.updated_at = time.time()
        self._conn.execute(
            """UPDATE experiments SET num_trades=?, wins=?, losses=?,
               total_pnl=?, max_drawdown=?, updated_at=? WHERE id=?""",
            (exp.num_trades, exp.wins, exp.losses,
             exp.total_pnl, exp.max_drawdown, exp.updated_at, exp.id),
        )
        self._conn.commit()
        return exp

    def complete_experiment(self, exp_id: str, notes: str = "") -> Optional[Experiment]:
        exp = self.get_experiment(exp_id)
        if not exp:
            return None
        now = time.time()
        self._conn.execute(
            "UPDATE experiments SET status=?, ended_at=?, notes=?, updated_at=? WHERE id=?",
            (ExperimentStatus.COMPLETED, now, notes, now, exp_id),
        )
        self._conn.commit()
        return self.get_experiment(exp_id)

    def abort_experiment(self, exp_id: str, reason: str = "") -> Optional[Experiment]:
        exp = self.get_experiment(exp_id)
        if not exp:
            return None
        now = time.time()
        self._conn.execute(
            "UPDATE experiments SET status=?, ended_at=?, notes=?, updated_at=? WHERE id=?",
            (ExperimentStatus.ABORTED, now, reason, now, exp_id),
        )
        self._conn.commit()
        return self.get_experiment(exp_id)

    # --- Config (no-trade mode, etc.) ---

    def set_config(self, key: str, value: str):
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?,?,?)",
            (key, value, now),
        )
        self._conn.commit()

    def get_config(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    @property
    def no_trade_mode(self) -> bool:
        return self.get_config("no_trade_mode", "true") == "true"

    @no_trade_mode.setter
    def no_trade_mode(self, enabled: bool):
        self.set_config("no_trade_mode", "true" if enabled else "false")
