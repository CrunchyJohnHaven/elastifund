#!/usr/bin/env python3
"""Persistent cache and cost counters for relation classification."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping


def _now_ts() -> int:
    return int(time.time())


@dataclass(frozen=True)
class CachedRelation:
    pair_key: str
    prompt_version: str
    response: dict[str, Any]
    source: str
    metadata: dict[str, Any]
    created_at_ts: int
    updated_at_ts: int


@dataclass(frozen=True)
class RelationCacheStats:
    entries: int
    cache_hits: int
    cache_misses: int
    total_events: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    @property
    def hit_rate(self) -> float:
        if self.total_events <= 0:
            return 0.0
        return float(self.cache_hits / self.total_events)


class RelationCache:
    """SQLite-backed cache keyed by canonical pair signature and prompt version."""

    def __init__(self, db_path: str | Path = Path("data") / "relation_cache.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS relation_cache (
                    cache_key TEXT PRIMARY KEY,
                    pair_key TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    label TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    ambiguous INTEGER NOT NULL,
                    needs_human_review INTEGER NOT NULL,
                    short_rationale TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at_ts INTEGER NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_relation_cache_pair_prompt
                    ON relation_cache(pair_key, prompt_version);

                CREATE TABLE IF NOT EXISTS relation_cost_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_key TEXT NOT NULL,
                    pair_key TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    model TEXT NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    estimated_cost_usd REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    created_at_ts INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_relation_cost_events_pair_prompt
                    ON relation_cost_events(pair_key, prompt_version);
                """
            )

    @staticmethod
    def make_cache_key(pair_key: str, prompt_version: str) -> str:
        return f"{pair_key}:{prompt_version}"

    def get(self, pair_key: str, prompt_version: str) -> CachedRelation | None:
        cache_key = self.make_cache_key(pair_key, prompt_version)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT pair_key, prompt_version, response_json, source, metadata_json,
                       created_at_ts, updated_at_ts
                FROM relation_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()

        if row is None:
            return None

        response = json.loads(row[2])
        metadata = json.loads(row[4])
        return CachedRelation(
            pair_key=str(row[0]),
            prompt_version=str(row[1]),
            response=dict(response) if isinstance(response, Mapping) else {},
            source=str(row[3]),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
            created_at_ts=int(row[5]),
            updated_at_ts=int(row[6]),
        )

    def put(
        self,
        *,
        pair_key: str,
        prompt_version: str,
        response: Mapping[str, Any],
        source: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        cache_key = self.make_cache_key(pair_key, prompt_version)
        now = _now_ts()
        response_dict = dict(response)
        metadata_dict = dict(metadata or {})

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO relation_cache (
                    cache_key, pair_key, prompt_version, label, confidence, ambiguous,
                    needs_human_review, short_rationale, response_json, metadata_json,
                    source, created_at_ts, updated_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    label = excluded.label,
                    confidence = excluded.confidence,
                    ambiguous = excluded.ambiguous,
                    needs_human_review = excluded.needs_human_review,
                    short_rationale = excluded.short_rationale,
                    response_json = excluded.response_json,
                    metadata_json = excluded.metadata_json,
                    source = excluded.source,
                    updated_at_ts = excluded.updated_at_ts
                """,
                (
                    cache_key,
                    pair_key,
                    prompt_version,
                    str(response_dict.get("label", "")),
                    float(response_dict.get("confidence", 0.0)),
                    1 if response_dict.get("ambiguous") else 0,
                    1 if response_dict.get("needs_human_review") else 0,
                    str(response_dict.get("short_rationale", "")),
                    json.dumps(response_dict, sort_keys=True),
                    json.dumps(metadata_dict, sort_keys=True),
                    source,
                    now,
                    now,
                ),
            )

    def record_event(
        self,
        *,
        pair_key: str,
        prompt_version: str,
        model: str,
        cache_hit: bool,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        cache_key = self.make_cache_key(pair_key, prompt_version)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO relation_cost_events (
                    cache_key, pair_key, prompt_version, model, cache_hit,
                    input_tokens, output_tokens, estimated_cost_usd, latency_ms, created_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    pair_key,
                    prompt_version,
                    model,
                    1 if cache_hit else 0,
                    int(input_tokens),
                    int(output_tokens),
                    float(estimated_cost_usd),
                    float(latency_ms),
                    _now_ts(),
                ),
            )

    def stats(self) -> RelationCacheStats:
        with self._connect() as conn:
            cache_entries = conn.execute("SELECT COUNT(*) FROM relation_cache").fetchone()
            event_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_events,
                    COALESCE(SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END), 0) AS cache_hits,
                    COALESCE(SUM(CASE WHEN cache_hit = 0 THEN 1 ELSE 0 END), 0) AS cache_misses,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0.0) AS estimated_cost_usd
                FROM relation_cost_events
                """
            ).fetchone()

        return RelationCacheStats(
            entries=int(cache_entries[0] if cache_entries else 0),
            cache_hits=int(event_row[1] if event_row else 0),
            cache_misses=int(event_row[2] if event_row else 0),
            total_events=int(event_row[0] if event_row else 0),
            input_tokens=int(event_row[3] if event_row else 0),
            output_tokens=int(event_row[4] if event_row else 0),
            estimated_cost_usd=float(event_row[5] if event_row else 0.0),
        )
