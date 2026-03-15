"""SQLite cache and validation store for B-1 dependency edges."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


def question_hash(text: str) -> str:
    return hashlib.sha1(str(text).strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DepEdgeRecord:
    edge_id: str
    a_market_id: str
    b_market_id: str
    relation: str
    confidence: float
    constraint: str
    model_version: str
    a_question_hash: str
    b_question_hash: str
    reason: str
    metadata: dict[str, Any]


class DepGraphStore:
    """Durable local store for candidate cache, edges, and validation labels."""

    def __init__(self, db_path: str | Path = Path("data") / "dep_graph.sqlite") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dep_edges (
                    edge_id TEXT PRIMARY KEY,
                    a_market_id TEXT NOT NULL,
                    b_market_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    constraint_text TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    a_question_hash TEXT NOT NULL,
                    b_question_hash TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_ts INTEGER NOT NULL DEFAULT (unixepoch()),
                    updated_ts INTEGER NOT NULL DEFAULT (unixepoch())
                );

                CREATE TABLE IF NOT EXISTS dep_market_meta (
                    market_id TEXT PRIMARY KEY,
                    category TEXT,
                    end_date TEXT,
                    question_hash TEXT NOT NULL,
                    question TEXT NOT NULL,
                    last_seen_ts INTEGER NOT NULL DEFAULT (unixepoch()),
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dep_validation_samples (
                    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    edge_id TEXT NOT NULL,
                    label_human TEXT,
                    label_resolved TEXT,
                    checked_ts INTEGER NOT NULL DEFAULT (unixepoch()),
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_dep_edges_pair ON dep_edges(a_market_id, b_market_id, model_version);
                CREATE INDEX IF NOT EXISTS idx_dep_edges_conf ON dep_edges(confidence);
                CREATE INDEX IF NOT EXISTS idx_dep_validation_edge ON dep_validation_samples(edge_id);
                """
            )

    def upsert_market_meta(
        self,
        *,
        market_id: str,
        question: str,
        category: str | None = None,
        end_date: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dep_market_meta (
                    market_id, category, end_date, question_hash, question, metadata_json, last_seen_ts
                ) VALUES (?, ?, ?, ?, ?, ?, unixepoch())
                ON CONFLICT(market_id) DO UPDATE SET
                    category=excluded.category,
                    end_date=excluded.end_date,
                    question_hash=excluded.question_hash,
                    question=excluded.question,
                    metadata_json=excluded.metadata_json,
                    last_seen_ts=unixepoch()
                """,
                (
                    str(market_id),
                    category,
                    end_date,
                    question_hash(question),
                    str(question),
                    json.dumps(dict(metadata or {}), sort_keys=True),
                ),
            )
            conn.commit()

    def upsert_edge(self, edge: DepEdgeRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dep_edges (
                    edge_id, a_market_id, b_market_id, relation, confidence,
                    constraint_text, model_version, a_question_hash, b_question_hash,
                    reason, metadata_json, created_ts, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, unixepoch(), unixepoch())
                ON CONFLICT(edge_id) DO UPDATE SET
                    relation=excluded.relation,
                    confidence=excluded.confidence,
                    constraint_text=excluded.constraint_text,
                    model_version=excluded.model_version,
                    a_question_hash=excluded.a_question_hash,
                    b_question_hash=excluded.b_question_hash,
                    reason=excluded.reason,
                    metadata_json=excluded.metadata_json,
                    updated_ts=unixepoch()
                """,
                (
                    edge.edge_id,
                    edge.a_market_id,
                    edge.b_market_id,
                    edge.relation,
                    float(edge.confidence),
                    edge.constraint,
                    edge.model_version,
                    edge.a_question_hash,
                    edge.b_question_hash,
                    edge.reason,
                    json.dumps(edge.metadata or {}, sort_keys=True),
                ),
            )
            conn.commit()

    def get_cached_edge(
        self,
        *,
        a_market_id: str,
        b_market_id: str,
        model_version: str,
        a_question_hash: str,
        b_question_hash: str,
    ) -> DepEdgeRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM dep_edges
                WHERE a_market_id = ? AND b_market_id = ? AND model_version = ?
                """,
                (str(a_market_id), str(b_market_id), str(model_version)),
            ).fetchone()
        if row is None:
            return None
        if row["a_question_hash"] != a_question_hash or row["b_question_hash"] != b_question_hash:
            return None
        return self._row_to_edge(row)

    def sample_edges_for_review(self, *, limit: int = 50, min_confidence: float = 0.7) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.*, a.question AS a_question, b.question AS b_question
                FROM dep_edges e
                LEFT JOIN dep_market_meta a ON a.market_id = e.a_market_id
                LEFT JOIN dep_market_meta b ON b.market_id = e.b_market_id
                WHERE e.confidence >= ?
                ORDER BY e.confidence DESC, e.updated_ts DESC
                LIMIT ?
                """,
                (float(min_confidence), int(limit)),
            ).fetchall()
        return [
            {
                "edge_id": row["edge_id"],
                "a_market_id": row["a_market_id"],
                "b_market_id": row["b_market_id"],
                "relation": row["relation"],
                "confidence": float(row["confidence"]),
                "constraint": row["constraint_text"],
                "reason": row["reason"],
                "a_question": row["a_question"],
                "b_question": row["b_question"],
            }
            for row in rows
        ]

    def record_validation_samples(self, rows: Sequence[Mapping[str, Any]]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO dep_validation_samples (edge_id, label_human, label_resolved, checked_ts, notes)
                VALUES (?, ?, ?, unixepoch(), ?)
                """,
                [
                    (
                        str(row["edge_id"]),
                        row.get("label_human"),
                        row.get("label_resolved"),
                        str(row.get("notes") or ""),
                    )
                    for row in rows
                ],
            )
            conn.commit()

    def accuracy_summary(self, *, min_confidence: float | None = None) -> dict[str, float | int]:
        clauses = []
        params: list[Any] = []
        if min_confidence is not None:
            clauses.append("e.confidence >= ?")
            params.append(float(min_confidence))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN v.label_human IS NOT NULL AND v.label_human = e.relation THEN 1 ELSE 0 END) AS correct_human,
                    SUM(CASE WHEN v.label_resolved IS NOT NULL AND v.label_resolved = e.relation THEN 1 ELSE 0 END) AS correct_resolved,
                    SUM(CASE WHEN v.label_human IS NOT NULL THEN 1 ELSE 0 END) AS human_labeled,
                    SUM(CASE WHEN v.label_resolved IS NOT NULL THEN 1 ELSE 0 END) AS resolved_labeled
                FROM dep_edges e
                LEFT JOIN dep_validation_samples v ON v.edge_id = e.edge_id
                {where}
                """,
                tuple(params),
            ).fetchone()

        total = int(rows["total"] or 0)
        human_labeled = int(rows["human_labeled"] or 0)
        resolved_labeled = int(rows["resolved_labeled"] or 0)
        correct_human = int(rows["correct_human"] or 0)
        correct_resolved = int(rows["correct_resolved"] or 0)
        return {
            "edges_total": total,
            "human_labeled": human_labeled,
            "resolved_labeled": resolved_labeled,
            "accuracy_human": (correct_human / human_labeled) if human_labeled else 0.0,
            "accuracy_resolved": (correct_resolved / resolved_labeled) if resolved_labeled else 0.0,
        }

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> DepEdgeRecord:
        metadata: dict[str, Any] = {}
        try:
            parsed = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            if isinstance(parsed, dict):
                metadata = parsed
        except json.JSONDecodeError:
            metadata = {}
        return DepEdgeRecord(
            edge_id=row["edge_id"],
            a_market_id=row["a_market_id"],
            b_market_id=row["b_market_id"],
            relation=row["relation"],
            confidence=float(row["confidence"]),
            constraint=row["constraint_text"],
            model_version=row["model_version"],
            a_question_hash=row["a_question_hash"],
            b_question_hash=row["b_question_hash"],
            reason=row["reason"],
            metadata=metadata,
        )
