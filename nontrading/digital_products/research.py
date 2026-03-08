"""Research pipeline for digital-product niche discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .config import DigitalProductResearchSettings
from .embeddings import build_embedding
from .models import DiscoveryResult, DiscoveryRun, NicheCandidate, RankedNiche
from .store import DigitalProductStore


class MarketplaceResearchSource(Protocol):
    def fetch_candidates(self, *, marketplace: str, limit: int | None = None) -> list[NicheCandidate]:
        """Return normalized niche candidates from one upstream source."""


class StaticMarketplaceSource:
    """Deterministic source backed by normalized JSON fixtures or generated data."""

    def __init__(self, candidates: list[NicheCandidate], *, source_name: str = "static_snapshot") -> None:
        self._candidates = list(candidates)
        self.source_name = source_name

    @classmethod
    def from_json_file(cls, path: str | Path, *, marketplace: str = "etsy") -> "StaticMarketplaceSource":
        data = json.loads(Path(path).read_text())
        candidates = [
            NicheCandidate(
                niche_slug=item["niche_slug"],
                title=item["title"],
                product_type=item["product_type"],
                marketplace=item.get("marketplace", marketplace),
                keywords=tuple(item.get("keywords", [])),
                monthly_demand=item.get("monthly_demand", 0),
                competition_count=item.get("competition_count", 0),
                average_price=item.get("average_price", 0),
                profit_margin=item.get("profit_margin", 0),
                source=item.get("source", "static_snapshot"),
                metadata=item.get("metadata", {}),
                captured_at=item.get("captured_at") or item.get("created_at") or item.get("observed_at"),
            )
            for item in data
        ]
        return cls(candidates, source_name=str(Path(path)))

    def fetch_candidates(self, *, marketplace: str, limit: int | None = None) -> list[NicheCandidate]:
        filtered = [
            candidate
            for candidate in self._candidates
            if candidate.marketplace == marketplace.lower()
        ]
        if limit is None:
            return filtered
        return filtered[: max(1, int(limit))]


class NicheDiscoveryAgent:
    """Ranks digital-product niches and stores research snapshots."""

    def __init__(self, store: DigitalProductStore, settings: DigitalProductResearchSettings) -> None:
        self.store = store
        self.settings = settings

    def run_once(
        self,
        source: MarketplaceResearchSource,
        *,
        marketplace: str | None = None,
        limit: int | None = None,
        source_name: str | None = None,
    ) -> DiscoveryResult:
        selected_marketplace = (marketplace or self.settings.default_marketplace).lower()
        result_limit = limit or self.settings.default_limit
        run = self.store.start_run(
            DiscoveryRun(
                marketplace=selected_marketplace,
                source_name=source_name or getattr(source, "source_name", source.__class__.__name__),
                settings={
                    "default_limit": result_limit,
                    "embedding_dimensions": self.settings.embedding_dimensions,
                    "competition_floor": self.settings.competition_floor,
                    "minimum_monthly_demand": self.settings.minimum_monthly_demand,
                    "minimum_average_price": self.settings.minimum_average_price,
                },
            )
        )
        candidates = self._filter_candidates(
            source.fetch_candidates(marketplace=selected_marketplace, limit=result_limit)
        )
        ranked = self.rank_candidates(candidates)
        persisted = [self.store.record_ranked_niche(run.id or 0, item) for item in ranked]
        note = "No candidates passed filters." if not ranked else ""
        self.store.complete_run(
            run.id or 0,
            status="success",
            candidate_count=len(candidates),
            persisted_count=len(persisted),
            note=note,
        )
        latest_run = self.store.latest_run()
        return DiscoveryResult(run=latest_run or run, ranked_niches=tuple(persisted))

    def rank_candidates(self, candidates: list[NicheCandidate]) -> list[RankedNiche]:
        scored = []
        for candidate in candidates:
            demand_value = round(
                candidate.monthly_demand * candidate.average_price * candidate.profit_margin,
                6,
            )
            competition_penalty = round(
                1.0 / max(candidate.competition_count, self.settings.competition_floor),
                6,
            )
            composite_score = round(demand_value * competition_penalty, 6)
            scored.append(
                RankedNiche(
                    candidate=candidate,
                    rank=0,
                    composite_score=composite_score,
                    demand_value=demand_value,
                    competition_penalty=competition_penalty,
                    saturation_band=self._saturation_band(candidate),
                    embedding=build_embedding(
                        candidate.search_text,
                        dimensions=self.settings.embedding_dimensions,
                    ),
                )
            )

        scored.sort(
            key=lambda item: (
                item.composite_score,
                item.candidate.monthly_demand,
                item.candidate.average_price,
                -item.candidate.competition_count,
            ),
            reverse=True,
        )
        return [
            RankedNiche(
                id=item.id,
                run_id=item.run_id,
                candidate=item.candidate,
                rank=index,
                composite_score=item.composite_score,
                demand_value=item.demand_value,
                competition_penalty=item.competition_penalty,
                saturation_band=item.saturation_band,
                embedding=item.embedding,
                created_at=item.created_at,
            )
            for index, item in enumerate(scored, start=1)
        ]

    def build_elastic_bulk(self, ranked_niches: list[RankedNiche]) -> str:
        lines: list[str] = []
        for item in ranked_niches:
            document = item.to_knowledge_document(index_name=self.settings.elastic_index_name)
            action = {"index": {"_index": document.pop("_index"), "_id": document.pop("_id")}}
            lines.append(json.dumps(action, sort_keys=True))
            lines.append(json.dumps(document, sort_keys=True))
        return "\n".join(lines) + ("\n" if lines else "")

    def _filter_candidates(self, candidates: list[NicheCandidate]) -> list[NicheCandidate]:
        filtered: list[NicheCandidate] = []
        for candidate in candidates:
            if candidate.monthly_demand < self.settings.minimum_monthly_demand:
                continue
            if candidate.average_price < self.settings.minimum_average_price:
                continue
            filtered.append(candidate)
        return filtered

    @staticmethod
    def _saturation_band(candidate: NicheCandidate) -> str:
        ratio = candidate.monthly_demand / max(candidate.competition_count, 1)
        if ratio >= 0.5:
            return "low"
        if ratio >= 0.15:
            return "medium"
        return "high"
