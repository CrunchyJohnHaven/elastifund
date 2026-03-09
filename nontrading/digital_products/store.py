"""SQLite store for digital-product niche discovery."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from nontrading.models import Account, Lead, Opportunity
from nontrading.store import RevenueStore

from .embeddings import build_embedding, cosine_similarity
from .models import CRMSyncSummary, DiscoveryRun, GeneratedLead, NicheCandidate, RankedNiche, SimilarNicheMatch, utc_now


class DigitalProductStore:
    """Persistence for repeatable niche discovery runs and rankings."""

    def __init__(self, db_path: str | Path, revenue_store: RevenueStore | None = None):
        self.db_path = Path(db_path)
        self.revenue_store = revenue_store
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
                    audit_opportunity REAL NOT NULL DEFAULT 0,
                    icp_match_score REAL NOT NULL DEFAULT 0,
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
            self._ensure_column(conn, "dp_niche_rankings", "audit_opportunity", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "dp_niche_rankings", "icp_match_score", "REAL NOT NULL DEFAULT 0")

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        ddl: str,
    ) -> None:
        existing = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")

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
                    audit_opportunity,
                    icp_match_score,
                    saturation_band,
                    search_text,
                    embedding_json,
                    metadata_json,
                    rank_position,
                    captured_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    niche.audit_opportunity,
                    niche.icp_match_score,
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
                audit_opportunity=niche.audit_opportunity,
                icp_match_score=niche.icp_match_score,
                saturation_band=niche.saturation_band,
                embedding=niche.embedding,
                id=int(cursor.lastrowid),
                run_id=run_id,
                created_at=niche.created_at,
            )

    def sync_to_revenue_store(
        self,
        ranked_niches: list[RankedNiche],
        lead_list: list[GeneratedLead],
        *,
        include_synthetic: bool = False,
    ) -> CRMSyncSummary:
        if self.revenue_store is None:
            return CRMSyncSummary()

        leads_processed = 0
        accounts_processed = 0
        opportunities_processed = 0
        ranked_by_slug = {item.candidate.niche_slug: item for item in ranked_niches}

        for generated in lead_list:
            if generated.synthetic and not include_synthetic:
                continue
            lead_metadata = dict(generated.metadata)
            lead_metadata.update(
                {
                    "website_url": generated.website_url,
                    "domain": generated.domain,
                    "industry": generated.industry,
                    "niche_slug": generated.niche_slug,
                    "niche_title": generated.niche_title,
                    "marketplace": generated.marketplace,
                    "synthetic": generated.synthetic,
                    "source_module": "digital_products",
                }
            )
            self.revenue_store.upsert_lead(
                Lead(
                    email=generated.email,
                    company_name=generated.company_name,
                    country_code=generated.country_code,
                    source=generated.source,
                    explicit_opt_in=generated.explicit_opt_in,
                    opt_in_recorded_at=generated.opt_in_recorded_at,
                    metadata=lead_metadata,
                )
            )
            leads_processed += 1

            account, _ = self.revenue_store.upsert_account(
                Account(
                    name=generated.company_name,
                    domain=generated.domain,
                    industry=generated.industry,
                    website_url=generated.website_url,
                    status="researching",
                    metadata=lead_metadata,
                )
            )
            accounts_processed += 1

            ranked = ranked_by_slug.get(generated.niche_slug)
            if ranked is None or account.id is None:
                continue

            opportunity_name = f"{generated.company_name} Website Growth Audit"
            estimated_value = round(500.0 + (2000.0 * ranked.audit_fit_score), 2)
            self.revenue_store.upsert_opportunity(
                Opportunity(
                    account_id=account.id,
                    name=opportunity_name,
                    offer_name="Website Growth Audit",
                    stage="research",
                    status="open",
                    score=ranked.audit_fit_score,
                    score_breakdown={
                        "composite_score": ranked.composite_score,
                        "audit_opportunity": ranked.audit_opportunity,
                        "icp_match_score": ranked.icp_match_score,
                    },
                    estimated_value=estimated_value,
                    next_action="Review generated website-audit target.",
                    metadata=lead_metadata,
                )
            )
            opportunities_processed += 1

        return CRMSyncSummary(
            leads_processed=leads_processed,
            accounts_processed=accounts_processed,
            opportunities_processed=opportunities_processed,
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
            audit_opportunity=row["audit_opportunity"],
            icp_match_score=row["icp_match_score"],
            saturation_band=row["saturation_band"],
            embedding=tuple(json.loads(row["embedding_json"])),
            created_at=row["created_at"],
        )
