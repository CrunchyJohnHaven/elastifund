"""SQLite persistence for standalone resource allocation."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import sqlite3
import time

from .models import (
    AllocationDecision,
    AllocationMode,
    ArmStats,
    DeliverabilityRisk,
    NON_TRADING_AGENT,
    PerformanceObservation,
    TRADING_AGENT,
)

DEFAULT_DB_PATH = Path("data") / "allocator.db"


def _dump_json(payload: dict | None) -> str:
    return json.dumps(payload or {}, sort_keys=True)


def _load_json(payload: str | None) -> dict:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class AllocatorStore:
    """Simple SQLite store for decisions and observed outcomes."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS allocation_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_date TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    trading_share REAL NOT NULL,
                    non_trading_share REAL NOT NULL,
                    trading_budget_usd REAL NOT NULL,
                    non_trading_send_quota INTEGER NOT NULL,
                    non_trading_llm_token_budget INTEGER NOT NULL,
                    cash_reserve_share REAL NOT NULL DEFAULT 0.0,
                    deliverability_risk TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    risk_override_applied INTEGER NOT NULL DEFAULT 0,
                    bandit_sample_trading REAL,
                    bandit_sample_non_trading REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at_ts INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS allocation_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    observed_on TEXT NOT NULL,
                    roi REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at_ts INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_allocator_decisions_date
                    ON allocation_decisions(decision_date, id DESC);

                CREATE INDEX IF NOT EXISTS idx_allocator_observations_agent_date
                    ON allocation_observations(agent_name, observed_on);

                CREATE TABLE IF NOT EXISTS allocation_strategy_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id INTEGER NOT NULL,
                    index_name TEXT NOT NULL,
                    strategy_key TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    decision_date TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    created_at_ts INTEGER NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES allocation_decisions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_allocator_strategy_snapshots_decision
                    ON allocation_strategy_snapshots(decision_id, id DESC);

                CREATE INDEX IF NOT EXISTS idx_allocator_strategy_snapshots_agent_date
                    ON allocation_strategy_snapshots(agent_name, decision_date);
                """
            )
            self._ensure_column(
                conn,
                "allocation_decisions",
                "cash_reserve_share",
                "ALTER TABLE allocation_decisions ADD COLUMN cash_reserve_share REAL NOT NULL DEFAULT 0.0",
            )

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        ddl: str,
    ) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(ddl)
            conn.commit()

    def record_observation(self, observation: PerformanceObservation) -> PerformanceObservation:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO allocation_observations (
                    agent_name,
                    observed_on,
                    roi,
                    metadata_json,
                    created_at_ts
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    observation.agent_name,
                    observation.observed_on.isoformat(),
                    observation.roi,
                    _dump_json(observation.metadata),
                    now,
                ),
            )
            conn.commit()
        return observation

    def arm_stats(
        self,
        *,
        success_threshold: float = 0.0,
        since_date: date | None = None,
    ) -> dict[str, ArmStats]:
        stats = {
            TRADING_AGENT: ArmStats(agent_name=TRADING_AGENT),
            NON_TRADING_AGENT: ArmStats(agent_name=NON_TRADING_AGENT),
        }
        since_iso = since_date.isoformat() if since_date else None
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    agent_name,
                    COUNT(*) AS observations,
                    SUM(CASE WHEN roi >= ? THEN 1 ELSE 0 END) AS successes,
                    SUM(CASE WHEN roi < ? THEN 1 ELSE 0 END) AS failures,
                    AVG(roi) AS avg_roi
                FROM allocation_observations
                WHERE (? IS NULL OR observed_on >= ?)
                GROUP BY agent_name
                """,
                (success_threshold, success_threshold, since_iso, since_iso),
            ).fetchall()
        for row in rows:
            stats[row["agent_name"]] = ArmStats(
                agent_name=row["agent_name"],
                observations=int(row["observations"] or 0),
                successes=int(row["successes"] or 0),
                failures=int(row["failures"] or 0),
                avg_roi=float(row["avg_roi"] or 0.0),
            )
        return stats

    def list_observations(
        self,
        *,
        agent_name: str | None = None,
        since_date: date | None = None,
        limit: int | None = None,
    ) -> list[PerformanceObservation]:
        clauses: list[str] = []
        params: list[object] = []
        if agent_name is not None:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if since_date is not None:
            clauses.append("observed_on >= ?")
            params.append(since_date.isoformat())

        query = """
            SELECT *
            FROM allocation_observations
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY observed_on ASC, id ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            PerformanceObservation(
                agent_name=row["agent_name"],
                observed_on=date.fromisoformat(row["observed_on"]),
                roi=float(row["roi"]),
                metadata=_load_json(row["metadata_json"]),
            )
            for row in rows
        ]

    def record_decision(self, decision: AllocationDecision) -> AllocationDecision:
        now = int(time.time())
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO allocation_decisions (
                    decision_date,
                    mode,
                    trading_share,
                    non_trading_share,
                    trading_budget_usd,
                    non_trading_send_quota,
                    non_trading_llm_token_budget,
                    cash_reserve_share,
                    deliverability_risk,
                    rationale,
                    risk_override_applied,
                    bandit_sample_trading,
                    bandit_sample_non_trading,
                    metadata_json,
                    created_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_date.isoformat(),
                    decision.mode.value,
                    decision.trading_share,
                    decision.non_trading_share,
                    decision.trading_budget_usd,
                    decision.non_trading_send_quota,
                    decision.non_trading_llm_token_budget,
                    decision.cash_reserve_share,
                    decision.deliverability_risk.value,
                    decision.rationale,
                    int(decision.risk_override_applied),
                    decision.bandit_sample_trading,
                    decision.bandit_sample_non_trading,
                    _dump_json(decision.metadata),
                    now,
                ),
            )
            decision_id = int(cursor.lastrowid)
            for document in decision.strategy_documents:
                conn.execute(
                    """
                    INSERT INTO allocation_strategy_snapshots (
                        decision_id,
                        index_name,
                        strategy_key,
                        agent_name,
                        decision_date,
                        document_json,
                        created_at_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        str(document.get("index", "elastifund-strategies")),
                        str(document.get("strategy_key", "capital_allocator")),
                        str(document.get("agent_name", "")),
                        str(document.get("decision_date", decision.decision_date.isoformat())),
                        _dump_json(document),
                        now,
                    ),
                )
            conn.commit()
        return replace(decision, decision_id=decision_id, created_at_ts=now)

    def latest_decision(self, *, before_date: date | None = None) -> AllocationDecision | None:
        params: tuple[str, ...] | tuple[()] = ()
        query = """
            SELECT *
            FROM allocation_decisions
        """
        if before_date:
            query += " WHERE decision_date < ?"
            params = (before_date.isoformat(),)
        query += " ORDER BY decision_date DESC, id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        return self._decision_from_row(row)

    def list_decisions(self, *, limit: int = 20) -> list[AllocationDecision]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM allocation_decisions
                ORDER BY decision_date DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._decision_from_row(row) for row in rows]

    def status(self) -> dict[str, object]:
        with self._connect() as conn:
            decisions = conn.execute("SELECT COUNT(*) FROM allocation_decisions").fetchone()[0]
            observations = conn.execute("SELECT COUNT(*) FROM allocation_observations").fetchone()[0]
            strategy_snapshots = conn.execute(
                "SELECT COUNT(*) FROM allocation_strategy_snapshots"
            ).fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "decisions": int(decisions),
            "observations": int(observations),
            "strategy_snapshots": int(strategy_snapshots),
        }

    def list_strategy_snapshots(
        self,
        *,
        decision_id: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        params: tuple[object, ...]
        query = """
            SELECT *
            FROM allocation_strategy_snapshots
        """
        if decision_id is not None:
            query += " WHERE decision_id = ?"
            params = (decision_id, limit)
            query += " ORDER BY id ASC LIMIT ?"
        else:
            params = (limit,)
            query += " ORDER BY id DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        documents = [_load_json(row["document_json"]) for row in rows]
        return documents if decision_id is not None else list(reversed(documents))

    def _decision_from_row(self, row: sqlite3.Row) -> AllocationDecision:
        return AllocationDecision(
            decision_date=date.fromisoformat(row["decision_date"]),
            mode=AllocationMode.normalize(row["mode"]),
            trading_share=float(row["trading_share"]),
            non_trading_share=float(row["non_trading_share"]),
            trading_budget_usd=float(row["trading_budget_usd"]),
            non_trading_send_quota=int(row["non_trading_send_quota"]),
            non_trading_llm_token_budget=int(row["non_trading_llm_token_budget"]),
            cash_reserve_share=float(row["cash_reserve_share"] or 0.0),
            deliverability_risk=DeliverabilityRisk.normalize(row["deliverability_risk"]),
            rationale=str(row["rationale"]),
            risk_override_applied=bool(row["risk_override_applied"]),
            bandit_sample_trading=(
                float(row["bandit_sample_trading"])
                if row["bandit_sample_trading"] is not None
                else None
            ),
            bandit_sample_non_trading=(
                float(row["bandit_sample_non_trading"])
                if row["bandit_sample_non_trading"] is not None
                else None
            ),
            metadata=_load_json(row["metadata_json"]),
            strategy_documents=tuple(
                self.list_strategy_snapshots(decision_id=int(row["id"]), limit=1000)
            ),
            decision_id=int(row["id"]),
            created_at_ts=int(row["created_at_ts"]),
        )
