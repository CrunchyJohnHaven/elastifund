"""SQLite store for digital-product niche discovery."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .embeddings import build_embedding, cosine_similarity
from .models import DiscoveryRun, NicheCandidate, RankedNiche, SimilarNicheMatch, utc_now


class DigitalProductStore:
    """Persistence for repeatable niche discovery runs and rankings."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dp_research_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    marketplace TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    persisted_count INTEGER NOT NULL DEFAULT 0,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    note TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS dp_niche_rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    marketplace TEXT NOT NULL,
                    source TEXT NOT NULL,
                    niche_slug TEXT NOT NULL,
                    title TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    keywords_json TEXT NOT NULL DEFAULT '[]',
                    monthly_demand REAL NOT NULL DEFAULT 0,
                    competition_count INTEGER NOT NULL DEFAULT 0,
                    average_price REAL NOT NULL DEFAULT 0,
                    profit_margin REAL NOT NULL DEFAULT 0,
                    demand_value REAL NOT NULL DEFAULT 0,
                    competition_penalty REAL NOT NULL DEFAULT 0,
                    composite_score REAL NOT NULL DEFAULT 0,
                    saturation_band TEXT NOT NULL DEFAULT 'unknown',
                    search_text TEXT NOT NULL DEFAULT '',
                    embedding_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    rank_position INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES dp_research_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_dp_rankings_run_score
                    ON dp_niche_rankings(run_id, composite_score DESC);
                CREATE INDEX IF NOT EXISTS idx_dp_rankings_marketplace_slug
                    ON dp_niche_rankings(marketplace, niche_slug, created_at DESC);
                """
            )

    def start_run(self, run: DiscoveryRun) -> DiscoveryRun:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO dp_research_runs (
                    marketplace,
                    source_name,
                    status,
                    candidate_count,
                    persisted_count,
                    settings_json,
                    started_at,
                    finished_at,
                    note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.marketplace,
                    run.source_name,
                    run.status,
                    run.candidate_count,
                    run.persisted_count,
                    json.dumps(run.settings, sort_keys=True),
                    run.started_at,
                    run.finished_at,
                    run.note,
                ),
            )
            return DiscoveryRun(
                marketplace=run.marketplace,
                source_name=run.source_name,
                status=run.status,
                candidate_count=run.candidate_count,
                persisted_count=run.persisted_count,
                settings=run.settings,
                id=int(cursor.lastrowid),
                started_at=run.started_at,
                finished_at=run.finished_at,
                note=run.note,
            )

    def complete_run(
        self,
        run_id: int,
        *,
        status: str,
        candidate_count: int,
        persisted_count: int,
        note: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE dp_research_runs
                SET status = ?,
                    candidate_count = ?,
                    persisted_count = ?,
                    finished_at = ?,
                    note = ?
                WHERE id = ?
                """,
                (
                    status,
                    int(candidate_count),
                    int(persisted_count),
                    utc_now(),
                    note,
                    int(run_id),
                ),
            )

    def record_ranked_niche(self, run_id: int, niche: RankedNiche) -> RankedNiche:
        candidate = niche.candidate
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO dp_niche_rankings (
                    run_id,
                    marketplace,
                    source,
                    niche_slug,
                    title,
                    product_type,
                    keywords_json,
                    monthly_demand,
                    competition_count,
                    average_price,
                    profit_margin,
                    demand_value,
                    competition_penalty,
                    composite_score,
                    saturation_band,
                    search_text,
                    embedding_json,
                    metadata_json,
                    rank_position,
                    captured_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(run_id),
                    candidate.marketplace,
                    candidate.source,
                    candidate.niche_slug,
                    candidate.title,
                    candidate.product_type,
                    json.dumps(list(candidate.keywords)),
                    candidate.monthly_demand,
                    candidate.competition_count,
                    candidate.average_price,
                    candidate.profit_margin,
                    niche.demand_value,
                    niche.competition_penalty,
                    niche.composite_score,
                    niche.saturation_band,
                    candidate.search_text,
                    json.dumps(list(niche.embedding)),
                    json.dumps(candidate.metadata, sort_keys=True),
                    niche.rank,
                    candidate.captured_at,
                    niche.created_at,
                ),
            )
            return RankedNiche(
                candidate=candidate,
                rank=niche.rank,
                composite_score=niche.composite_score,
                demand_value=niche.demand_value,
                competition_penalty=niche.competition_penalty,
                saturation_band=niche.saturation_band,
                embedding=niche.embedding,
                id=int(cursor.lastrowid),
                run_id=run_id,
                created_at=niche.created_at,
            )

    def latest_run(self) -> DiscoveryRun | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM dp_research_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return DiscoveryRun(
            id=row["id"],
            marketplace=row["marketplace"],
            source_name=row["source_name"],
            status=row["status"],
            candidate_count=row["candidate_count"],
            persisted_count=row["persisted_count"],
            settings=json.loads(row["settings_json"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            note=row["note"],
        )

    def list_ranked_niches(self, *, run_id: int | None = None, limit: int = 25) -> list[RankedNiche]:
        with self._connect() as conn:
            resolved_run_id = run_id
            if resolved_run_id is None:
                latest = conn.execute("SELECT id FROM dp_research_runs ORDER BY id DESC LIMIT 1").fetchone()
                resolved_run_id = int(latest["id"]) if latest else None
            if resolved_run_id is None:
                return []

            rows = conn.execute(
                """
                SELECT *
                FROM dp_niche_rankings
                WHERE run_id = ?
                ORDER BY rank_position ASC, composite_score DESC, id ASC
                LIMIT ?
                """,
                (int(resolved_run_id), int(limit)),
            ).fetchall()
        return [self._ranked_niche_from_row(row) for row in rows]

    def similar_niches(self, query_text: str, *, limit: int = 5, run_id: int | None = None) -> list[SimilarNicheMatch]:
        candidates = self.list_ranked_niches(run_id=run_id, limit=200)
        query_embedding = build_embedding(query_text, dimensions=len(candidates[0].embedding) if candidates else 768)
        scored = [
            SimilarNicheMatch(niche=niche, similarity_score=cosine_similarity(query_embedding, niche.embedding))
            for niche in candidates
        ]
        scored.sort(key=lambda item: item.similarity_score, reverse=True)
        return scored[:limit]

    def _ranked_niche_from_row(self, row: sqlite3.Row) -> RankedNiche:
        candidate = NicheCandidate(
            niche_slug=row["niche_slug"],
            title=row["title"],
            product_type=row["product_type"],
            marketplace=row["marketplace"],
            keywords=tuple(json.loads(row["keywords_json"])),
            monthly_demand=row["monthly_demand"],
            competition_count=row["competition_count"],
            average_price=row["average_price"],
            profit_margin=row["profit_margin"],
            source=row["source"],
            metadata=json.loads(row["metadata_json"]),
            captured_at=row["captured_at"],
        )
        return RankedNiche(
            id=row["id"],
            run_id=row["run_id"],
            candidate=candidate,
            rank=row["rank_position"],
            composite_score=row["composite_score"],
            demand_value=row["demand_value"],
            competition_penalty=row["competition_penalty"],
            saturation_band=row["saturation_band"],
            embedding=tuple(json.loads(row["embedding_json"])),
            created_at=row["created_at"],
        )
