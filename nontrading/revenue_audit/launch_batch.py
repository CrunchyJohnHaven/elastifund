"""Curated launch-batch ingestion for the Website Growth Audit lane."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nontrading.models import Account, Contact, Lead, Opportunity, normalize_country
from nontrading.offers.website_growth_audit import WEBSITE_GROWTH_AUDIT
from nontrading.store import RevenueStore

from .discovery import FetchPolicy, PageFetcher, discover_prospect
from .scoring import build_audit_bundle

DEFAULT_CURATED_SOURCE_PATH = Path("reports/nontrading/revenue_audit_launch_batch_seed.json")
CURATED_BATCH_LIMIT = 10


def _nonempty_text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class CuratedProspectSeed:
    company_name: str
    website_url: str
    country_code: str = "US"
    segment: str = "local_services"
    city: str = ""
    state: str = ""
    contact_name: str = ""
    role: str = "owner"
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "company_name", _nonempty_text(self.company_name))
        object.__setattr__(self, "website_url", _nonempty_text(self.website_url))
        object.__setattr__(self, "country_code", normalize_country(self.country_code))
        object.__setattr__(self, "segment", _nonempty_text(self.segment).lower() or "local_services")
        object.__setattr__(self, "city", _nonempty_text(self.city))
        object.__setattr__(self, "state", _nonempty_text(self.state))
        object.__setattr__(self, "contact_name", _nonempty_text(self.contact_name))
        object.__setattr__(self, "role", _nonempty_text(self.role).lower() or "owner")
        object.__setattr__(self, "notes", _nonempty_text(self.notes))
        if not self.company_name:
            raise ValueError("curated launch seed company_name is required")
        if not self.website_url:
            raise ValueError("curated launch seed website_url is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CuratedLaunchBatchIngestionResult:
    source_artifact: str | None
    seeds_loaded: int
    seeded_accounts: int
    skipped_non_us: int
    skipped_missing_evidence: int
    skipped_missing_contact: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_curated_prospect_seeds(path: Path) -> tuple[CuratedProspectSeed, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"curated launch source must be a JSON list: {path}")
    seeds: list[CuratedProspectSeed] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"curated launch source entries must be objects: {path}")
        seeds.append(CuratedProspectSeed(**item))
    return tuple(seeds)


def ingest_curated_launch_batch(
    store: RevenueStore,
    *,
    source_path: Path,
    fetcher: PageFetcher | None = None,
    policy: FetchPolicy | None = None,
) -> CuratedLaunchBatchIngestionResult:
    if not source_path.exists():
        return CuratedLaunchBatchIngestionResult(
            source_artifact=None,
            seeds_loaded=0,
            seeded_accounts=0,
            skipped_non_us=0,
            skipped_missing_evidence=0,
            skipped_missing_contact=0,
        )

    seeds = load_curated_prospect_seeds(source_path)
    seeded_accounts = 0
    skipped_non_us = 0
    skipped_missing_evidence = 0
    skipped_missing_contact = 0

    for seed in seeds:
        if seed.country_code != "US":
            skipped_non_us += 1
            continue

        profile = discover_prospect(
            seed.website_url,
            fetcher=fetcher,
            policy=policy,
            company_name=seed.company_name,
            country_code=seed.country_code,
            discovery_source="curated_launch_batch",
        )
        bundle = build_audit_bundle(profile, offer=WEBSITE_GROWTH_AUDIT)
        issues = bundle.issues[:3]
        if len(issues) < 2:
            skipped_missing_evidence += 1
            continue

        contact_channels = _contact_channels(profile)
        primary_email = next((item["value"] for item in contact_channels if item["kind"] == "email"), "")
        primary_phone = next((item["value"] for item in contact_channels if item["kind"] == "phone"), "")
        public_contact_url = next(
            (item["value"] for item in contact_channels if item["kind"] in {"contact_form", "contact_page"}),
            "",
        )
        if not primary_email and not primary_phone and not public_contact_url:
            skipped_missing_contact += 1
            continue

        quick_win = _quick_win_for_issue(issues[0].issue_id)
        recommended_price_tier = _recommended_price_tier(bundle.score.projected_price_usd)
        account_metadata = {
            "curated_launch_batch": True,
            "launch_ready": True,
            "human_review_batch": True,
            "country_code": seed.country_code,
            "website_url": profile.website_url,
            "launch_batch_source_artifact": str(source_path),
            "launch_batch_seed_company": seed.company_name,
            "launch_batch_segment": seed.segment,
            "launch_batch_city": seed.city,
            "launch_batch_state": seed.state,
            "launch_batch_notes": seed.notes,
            "issue_evidence": [
                {
                    "label": issue.title or issue.summary or issue.issue_id.replace("_", " ").title(),
                    "detail": issue.summary or issue.title,
                    "source_field": issue.issue_id,
                    "source_url": issue.source_url,
                    "severity": issue.severity,
                }
                for issue in issues
            ],
            "website_findings": issues[0].summary,
            "specific_finding": issues[1].summary if len(issues) > 1 else issues[0].summary,
            "quick_win": quick_win,
            "recommended_price_tier": recommended_price_tier,
            "public_contact_channels": contact_channels,
            "public_contact_url": public_contact_url,
            "score_purchase_probability": bundle.score.purchase_probability,
            "score_projected_price_usd": bundle.score.projected_price_usd,
            "score_expected_value_usd": bundle.score.expected_value_usd,
            "bundle_summary": bundle.summary,
            "discovery_notes": list(profile.discovery_notes),
        }

        account, _ = store.upsert_account(
            Account(
                name=seed.company_name,
                domain=_domain_from_url(profile.website_url),
                industry=seed.segment,
                website_url=profile.website_url,
                status="researched",
                metadata={
                    **account_metadata,
                    "lead_email": primary_email,
                },
            )
        )

        contact, _ = store.upsert_contact(
            Contact(
                account_id=account.id or 0,
                full_name=seed.contact_name or "Owner / Team",
                email=primary_email,
                phone=primary_phone,
                role=seed.role,
                metadata={
                    "country_code": seed.country_code,
                    "public_contact_channels": contact_channels,
                    "public_contact_url": public_contact_url,
                },
            )
        )

        if primary_email:
            store.upsert_lead(
                Lead(
                    email=primary_email,
                    company_name=seed.company_name,
                    country_code=seed.country_code,
                    source="curated_launch_batch",
                    explicit_opt_in=False,
                    metadata={
                        **account_metadata,
                        "contact_name": contact.full_name,
                        "role": contact.role or seed.role,
                        "industry": seed.segment,
                        "company_size": "11-50",
                    },
                )
            )

        score = round(
            min(
                100.0,
                bundle.score.purchase_probability * 100.0
                + len(issues) * 4.0
                + min(bundle.score.confidence_score * 10.0, 10.0),
            ),
            2,
        )
        store.upsert_opportunity(
            Opportunity(
                account_id=account.id or 0,
                name=f"Website Growth Audit for {seed.company_name}",
                offer_name=WEBSITE_GROWTH_AUDIT.name,
                stage="qualified",
                status="open",
                score=score,
                score_breakdown={
                    "purchase_probability": round(bundle.score.purchase_probability * 100.0, 2),
                    "confidence_score": round(bundle.score.confidence_score * 100.0, 2),
                    "issue_count": float(len(issues)),
                },
                estimated_value=float(bundle.score.projected_price_usd),
                next_action="launch_bridge",
                metadata={
                    **account_metadata,
                    "contact_id": contact.id or 0,
                    "recommended_price_usd": recommended_price_tier["price_usd"],
                },
            )
        )
        seeded_accounts += 1

    return CuratedLaunchBatchIngestionResult(
        source_artifact=str(source_path),
        seeds_loaded=len(seeds),
        seeded_accounts=seeded_accounts,
        skipped_non_us=skipped_non_us,
        skipped_missing_evidence=skipped_missing_evidence,
        skipped_missing_contact=skipped_missing_contact,
    )


def _contact_channels(profile: Any) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    profile_domain = _normalized_domain(profile.domain)
    for channel in profile.contact_channels:
        if channel.kind == "email" and not channel.is_business:
            continue
        if channel.kind == "email" and profile_domain and _normalized_domain(channel.value.partition("@")[2]) != profile_domain:
            continue
        key = (channel.kind, channel.value)
        if key in seen:
            continue
        seen.add(key)
        channels.append(channel.to_dict())
    return channels


def _recommended_price_tier(projected_price_usd: float) -> dict[str, Any]:
    if projected_price_usd >= 1800.0:
        return {"label": "premium", "price_usd": 2500}
    if projected_price_usd >= 1100.0:
        return {"label": "standard", "price_usd": 1500}
    return {"label": "starter", "price_usd": 500}


def _quick_win_for_issue(issue_id: str) -> str:
    normalized = _nonempty_text(issue_id).lower()
    mapping = {
        "heavy_homepage_payload": "Compress the homepage hero assets and trim unused scripts on mobile.",
        "missing_meta_description": "Rewrite the homepage title and meta description around city-plus-service intent.",
        "unclear_primary_offer": "Replace the hero copy with a concrete service-and-location promise above the fold.",
        "weak_cta_structure": "Add a single Request Estimate CTA in the first screen and repeat it on service pages.",
        "missing_contact_affordance": "Expose phone and contact-form access in the header and first viewport.",
        "missing_direct_contact_affordance": "Promote the fastest contact path above the fold instead of burying it on a contact page.",
        "missing_business_schema": "Add LocalBusiness and service schema to the homepage and top service pages.",
        "weak_title_signal": "Rewrite the homepage title to name the service, location, and primary action.",
    }
    return mapping.get(normalized, "Turn the strongest public-web issue into a same-week conversion fix.")


def _domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower().strip()


def _normalized_domain(value: str) -> str:
    domain = _nonempty_text(value).lower()
    if domain.startswith("www."):
        return domain[4:]
    return domain
