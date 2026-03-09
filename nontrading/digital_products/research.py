"""Research pipeline for digital-product niche discovery."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from .config import DigitalProductResearchSettings
from .embeddings import build_embedding
from .models import DiscoveryResult, DiscoveryRun, GeneratedLead, NicheCandidate, RankedNiche
from .store import DigitalProductStore


TARGET_REVENUE_MIN = 500_000.0
TARGET_REVENUE_MAX = 10_000_000.0
LOCAL_SERVICE_KEYWORDS = {
    "accounting",
    "agency",
    "attorney",
    "builder",
    "carpet",
    "chiropractic",
    "cleaning",
    "clinic",
    "contractor",
    "dental",
    "dentist",
    "electrician",
    "flooring",
    "hvac",
    "landscaping",
    "law",
    "legal",
    "medspa",
    "painting",
    "plumber",
    "remodeling",
    "roofing",
    "salon",
    "spa",
    "therapy",
    "wellness",
}
SERVICE_PRODUCT_TYPES = {
    "service",
    "service_business",
    "local_service",
    "agency",
    "contractor",
    "clinic",
}
WEBSITE_SIGNAL_KEYS = (
    ("missing_meta_tags", "meta_missing", "missing_meta"),
    ("slow_load", "slow_page", "slow_load_time"),
    ("not_mobile_optimized", "mobile_unfriendly", "missing_mobile_optimization"),
    ("missing_schema_markup", "missing_schema", "no_schema"),
    ("weak_cta", "no_cta", "weak_calls_to_action"),
)


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
        generated_leads = self.generate_lead_list(persisted)
        crm_sync_summary = self.store.sync_to_revenue_store(
            persisted,
            generated_leads,
            include_synthetic=self.settings.crm_sync_include_synthetic,
        )
        note = "No candidates passed filters." if not ranked else ""
        self.store.complete_run(
            run.id or 0,
            status="success",
            candidate_count=len(candidates),
            persisted_count=len(persisted),
            note=note,
        )
        latest_run = self.store.latest_run()
        return DiscoveryResult(
            run=latest_run or run,
            ranked_niches=tuple(persisted),
            generated_leads=tuple(generated_leads),
            crm_sync_summary=crm_sync_summary,
        )

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
            audit_opportunity = self._audit_opportunity_score(candidate)
            icp_match_score = self._icp_match_score(candidate)
            composite_score = round(
                (demand_value * competition_penalty)
                * (1.0 + (0.30 * audit_opportunity) + (0.20 * icp_match_score)),
                6,
            )
            scored.append(
                RankedNiche(
                    candidate=candidate,
                    rank=0,
                    composite_score=composite_score,
                    demand_value=demand_value,
                    competition_penalty=competition_penalty,
                    audit_opportunity=audit_opportunity,
                    icp_match_score=icp_match_score,
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
                item.icp_match_score,
                item.audit_opportunity,
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
                audit_opportunity=item.audit_opportunity,
                icp_match_score=item.icp_match_score,
                saturation_band=item.saturation_band,
                embedding=item.embedding,
                created_at=item.created_at,
            )
            for index, item in enumerate(scored, start=1)
        ]

    def generate_lead_list(
        self,
        ranked_niches: list[RankedNiche],
        *,
        leads_per_niche: int | None = None,
    ) -> list[GeneratedLead]:
        limit = leads_per_niche or self.settings.lead_list_per_niche
        leads: list[GeneratedLead] = []
        seen_emails: set[str] = set()

        for ranked in ranked_niches:
            if not self._qualifies_for_website_audit(ranked):
                continue
            candidate_leads = self._candidate_leads_for_ranked_niche(ranked, limit=limit)
            for lead in candidate_leads:
                if not lead.email or lead.email in seen_emails:
                    continue
                seen_emails.add(lead.email)
                leads.append(lead)
        return leads

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

    def _qualifies_for_website_audit(self, ranked: RankedNiche) -> bool:
        return (
            ranked.audit_opportunity >= self.settings.minimum_audit_opportunity
            and ranked.icp_match_score >= self.settings.minimum_icp_match_score
        )

    def _candidate_leads_for_ranked_niche(self, ranked: RankedNiche, *, limit: int) -> list[GeneratedLead]:
        metadata = ranked.candidate.metadata
        generated: list[GeneratedLead] = []
        raw_targets = metadata.get("lead_targets", ())
        if not isinstance(raw_targets, (list, tuple)):
            raw_targets = ()
        for raw in raw_targets[:limit]:
            lead = self._generated_lead_from_blueprint(raw, ranked)
            if lead is not None:
                generated.append(lead)

        if generated or not self.settings.synthetic_leads_enabled:
            return generated

        synthetic = self._build_synthetic_lead(ranked)
        return [synthetic] if synthetic is not None else []

    def _generated_lead_from_blueprint(self, raw: object, ranked: RankedNiche) -> GeneratedLead | None:
        if not isinstance(raw, dict):
            return None
        company_name = str(raw.get("company_name") or raw.get("name") or "").strip()
        if not company_name:
            return None
        domain = self._normalize_domain(raw.get("domain"))
        website_url = str(raw.get("website_url") or raw.get("url") or "").strip()
        email = str(raw.get("email") or "").strip().lower()
        if not email and domain:
            localpart = str(raw.get("localpart") or "info").strip().lower() or "info"
            email = f"{localpart}@{domain}"
        if not email:
            return None

        lead_metadata = {
            "niche_rank": ranked.rank,
            "audit_opportunity": ranked.audit_opportunity,
            "icp_match_score": ranked.icp_match_score,
            "composite_score": ranked.composite_score,
        }
        extra_metadata = raw.get("metadata")
        if isinstance(extra_metadata, dict):
            lead_metadata.update(extra_metadata)

        return GeneratedLead(
            email=email,
            company_name=company_name,
            country_code=str(raw.get("country_code") or "US"),
            source=str(raw.get("source") or "digital_product_niche_discovery"),
            explicit_opt_in=bool(raw.get("explicit_opt_in", False)),
            opt_in_recorded_at=raw.get("opt_in_recorded_at"),
            website_url=website_url,
            domain=domain,
            industry=str(raw.get("industry") or ranked.candidate.product_type),
            niche_slug=ranked.candidate.niche_slug,
            niche_title=ranked.candidate.title,
            marketplace=ranked.candidate.marketplace,
            metadata=lead_metadata,
            synthetic=False,
        )

    def _build_synthetic_lead(self, ranked: RankedNiche) -> GeneratedLead | None:
        slug = ranked.candidate.niche_slug
        if not slug:
            return None
        domain = f"{slug}.example"
        company_name = f"{ranked.candidate.title} Studio"
        return GeneratedLead(
            email=f"info@{domain}",
            company_name=company_name,
            country_code="US",
            source="digital_product_niche_discovery_synthetic",
            website_url=f"https://{domain}",
            domain=domain,
            industry=ranked.candidate.product_type,
            niche_slug=ranked.candidate.niche_slug,
            niche_title=ranked.candidate.title,
            marketplace=ranked.candidate.marketplace,
            metadata={
                "niche_rank": ranked.rank,
                "audit_opportunity": ranked.audit_opportunity,
                "icp_match_score": ranked.icp_match_score,
                "composite_score": ranked.composite_score,
                "synthetic_reason": "no_explicit_lead_targets_in_source_metadata",
            },
            synthetic=True,
        )

    def _audit_opportunity_score(self, candidate: NicheCandidate) -> float:
        weak_web_presence = self._weak_web_presence_score(candidate)
        service_model = self._service_business_score(candidate)
        ratio = candidate.competition_count / max(candidate.monthly_demand, 1.0)
        if ratio >= 5.0:
            competition_pressure = 1.0
        elif ratio >= 2.0:
            competition_pressure = 0.7
        elif ratio >= 1.0:
            competition_pressure = 0.5
        elif ratio >= 0.5:
            competition_pressure = 0.35
        else:
            competition_pressure = 0.2

        marketplace_dependency = 1.0 if candidate.marketplace in {"etsy", "gumroad"} else 0.5
        score = (
            (0.50 * weak_web_presence)
            + (0.25 * competition_pressure)
            + (0.15 * marketplace_dependency)
            + (0.10 * service_model)
        )
        return round(min(max(score, 0.0), 1.0), 6)

    def _icp_match_score(self, candidate: NicheCandidate) -> float:
        service_model = self._service_business_score(candidate)
        revenue_fit = self._revenue_fit_score(candidate)
        weak_web_presence = self._weak_web_presence_score(candidate)
        smb_fit = self._smb_fit_score(candidate)
        score = (
            (0.45 * service_model)
            + (0.25 * revenue_fit)
            + (0.20 * weak_web_presence)
            + (0.10 * smb_fit)
        )
        return round(min(max(score, 0.0), 1.0), 6)

    def _service_business_score(self, candidate: NicheCandidate) -> float:
        metadata = candidate.metadata
        business_model = str(metadata.get("business_model") or "").strip().lower()
        if business_model in {"service", "services", "service_business", "local_service", "agency"}:
            return 1.0
        if candidate.product_type in SERVICE_PRODUCT_TYPES:
            return 0.9

        tokens = set(self._tokenize(candidate.search_text))
        if tokens & LOCAL_SERVICE_KEYWORDS:
            return 0.8
        if candidate.marketplace in {"web", "manual", "google_maps"}:
            return 0.45
        return 0.1

    def _revenue_fit_score(self, candidate: NicheCandidate) -> float:
        metadata = candidate.metadata
        annual_revenue = self._estimated_annual_revenue(candidate)
        revenue_min = metadata.get("annual_revenue_min")
        revenue_max = metadata.get("annual_revenue_max")
        if revenue_min is not None and revenue_max is not None:
            minimum = float(revenue_min)
            maximum = float(revenue_max)
            if maximum >= TARGET_REVENUE_MIN and minimum <= TARGET_REVENUE_MAX:
                return 1.0

        if TARGET_REVENUE_MIN <= annual_revenue <= TARGET_REVENUE_MAX:
            return 1.0
        if 250_000.0 <= annual_revenue <= 15_000_000.0:
            return 0.55
        if annual_revenue > 0:
            return 0.2
        return 0.0

    def _weak_web_presence_score(self, candidate: NicheCandidate) -> float:
        metadata = candidate.metadata
        website_signals = metadata.get("website_signals")
        signal_score = self._website_signal_score(website_signals)
        website_maturity = str(metadata.get("website_maturity") or "").strip().lower()
        maturity_penalty = 0.25 if website_maturity in {"outdated", "basic", "weak"} else 0.0
        marketplace_dependency = 0.45 if candidate.marketplace in {"etsy", "gumroad"} else 0.15
        return round(min(max(signal_score + maturity_penalty + marketplace_dependency, 0.0), 1.0), 6)

    def _smb_fit_score(self, candidate: NicheCandidate) -> float:
        metadata = candidate.metadata
        employee_count = metadata.get("employee_count")
        if employee_count is not None:
            employees = max(0, int(employee_count))
            if employees <= 50:
                return 1.0
            if employees <= 250:
                return 0.65
            return 0.2

        company_size = str(metadata.get("company_size") or "").strip().lower()
        if company_size in {"solo", "small", "micro"}:
            return 1.0
        if company_size in {"medium", "midmarket"}:
            return 0.65
        if company_size in {"enterprise", "large"}:
            return 0.2

        return 0.6 if self._service_business_score(candidate) >= 0.8 else 0.35

    @staticmethod
    def _website_signal_score(raw: object) -> float:
        if not isinstance(raw, dict):
            return 0.0
        hits = 0
        for aliases in WEBSITE_SIGNAL_KEYS:
            if any(bool(raw.get(alias)) for alias in aliases):
                hits += 1
        return hits / float(len(WEBSITE_SIGNAL_KEYS))

    @staticmethod
    def _estimated_annual_revenue(candidate: NicheCandidate) -> float:
        metadata = candidate.metadata
        for key in ("estimated_annual_revenue", "annual_revenue_estimate", "annual_revenue"):
            value = metadata.get(key)
            if value is not None:
                return max(0.0, float(value))
        return max(0.0, candidate.monthly_demand * candidate.average_price * 12.0)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", str(text or "").lower())

    @staticmethod
    def _normalize_domain(value: object) -> str:
        domain = str(value or "").strip().lower().lstrip("@")
        domain = domain.removeprefix("https://").removeprefix("http://")
        return domain.split("/", 1)[0]

    @staticmethod
    def _saturation_band(candidate: NicheCandidate) -> str:
        ratio = candidate.monthly_demand / max(candidate.competition_count, 1)
        if ratio >= 0.5:
            return "low"
        if ratio >= 0.15:
            return "medium"
        return "high"
