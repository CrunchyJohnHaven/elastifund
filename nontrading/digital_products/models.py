"""Dataclasses for digital-product niche discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_slug(value: str) -> str:
    normalized = "-".join(part for part in str(value or "").strip().lower().replace("_", "-").split("-") if part)
    return normalized or "unknown"


def normalize_keywords(value: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not value:
        return ()
    cleaned: list[str] = []
    for item in value:
        token = str(item or "").strip().lower()
        if token and token not in cleaned:
            cleaned.append(token)
    return tuple(cleaned)


def normalize_profit_margin(value: float) -> float:
    margin = float(value)
    if margin > 1.0:
        margin = margin / 100.0
    return max(0.0, min(margin, 1.0))


@dataclass(frozen=True)
class NicheCandidate:
    niche_slug: str
    title: str
    product_type: str
    marketplace: str = "etsy"
    keywords: tuple[str, ...] = ()
    monthly_demand: float = 0.0
    competition_count: int = 0
    average_price: float = 0.0
    profit_margin: float = 0.0
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)
    captured_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "niche_slug", normalize_slug(self.niche_slug))
        object.__setattr__(self, "title", str(self.title).strip())
        object.__setattr__(self, "product_type", str(self.product_type).strip().lower())
        object.__setattr__(self, "marketplace", str(self.marketplace).strip().lower())
        object.__setattr__(self, "keywords", normalize_keywords(self.keywords))
        object.__setattr__(self, "monthly_demand", max(0.0, float(self.monthly_demand)))
        object.__setattr__(self, "competition_count", max(0, int(self.competition_count)))
        object.__setattr__(self, "average_price", max(0.0, float(self.average_price)))
        object.__setattr__(self, "profit_margin", normalize_profit_margin(self.profit_margin))
        object.__setattr__(self, "source", str(self.source).strip().lower() or "manual")
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "captured_at", str(self.captured_at or utc_now()))

    @property
    def search_text(self) -> str:
        keywords = " ".join(self.keywords)
        return " ".join(
            part
            for part in [
                self.marketplace,
                self.title,
                self.product_type,
                self.niche_slug.replace("-", " "),
                keywords,
            ]
            if part
        )


@dataclass(frozen=True)
class RankedNiche:
    candidate: NicheCandidate
    rank: int
    composite_score: float
    demand_value: float
    competition_penalty: float
    saturation_band: str
    embedding: tuple[float, ...]
    id: int | None = None
    run_id: int | None = None
    created_at: str = field(default_factory=utc_now)

    def to_knowledge_document(self, *, index_name: str, similarity_score: float | None = None) -> dict[str, Any]:
        document = {
            "_index": index_name,
            "_id": f"{self.candidate.marketplace}:{self.candidate.niche_slug}:{self.rank}",
            "doc_type": "digital_product_niche",
            "marketplace": self.candidate.marketplace,
            "niche_slug": self.candidate.niche_slug,
            "title": self.candidate.title,
            "product_type": self.candidate.product_type,
            "keywords": list(self.candidate.keywords),
            "search_text": self.candidate.search_text,
            "monthly_demand": self.candidate.monthly_demand,
            "competition_count": self.candidate.competition_count,
            "average_price": self.candidate.average_price,
            "profit_margin": self.candidate.profit_margin,
            "demand_value": self.demand_value,
            "competition_penalty": self.competition_penalty,
            "composite_score": self.composite_score,
            "saturation_band": self.saturation_band,
            "vector": list(self.embedding),
            "captured_at": self.candidate.captured_at,
            "created_at": self.created_at,
            "metadata": self.candidate.metadata,
            "run_id": self.run_id,
            "rank": self.rank,
        }
        if similarity_score is not None:
            document["similarity_score"] = similarity_score
        return document


@dataclass(frozen=True)
class DiscoveryRun:
    marketplace: str
    source_name: str
    status: str = "running"
    candidate_count: int = 0
    persisted_count: int = 0
    settings: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    note: str = ""


@dataclass(frozen=True)
class SimilarNicheMatch:
    niche: RankedNiche
    similarity_score: float


@dataclass(frozen=True)
class DiscoveryResult:
    run: DiscoveryRun
    ranked_niches: tuple[RankedNiche, ...]

    @property
    def top_niche(self) -> RankedNiche | None:
        return self.ranked_niches[0] if self.ranked_niches else None
