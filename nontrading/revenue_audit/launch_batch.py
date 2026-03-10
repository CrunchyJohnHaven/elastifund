"""Curated launch-batch refresh for the Website Growth Audit lane."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nontrading.models import Account, Contact, Lead, Opportunity, normalize_country, utc_now
from nontrading.offers.website_growth_audit import WEBSITE_GROWTH_AUDIT
from nontrading.store import RevenueStore

from .discovery import FetchPolicy, PageFetcher, discover_prospect
from .models import AuditBundle, IssueEvidence, ProspectProfile
from .scoring import build_audit_bundle

DEFAULT_CURATED_SOURCE_PATH = Path("reports/nontrading/revenue_audit_launch_batch_seed.json")
DEFAULT_OUTPUT_PATH = Path("reports/nontrading/revenue_audit_launch_batch.json")
CURATED_BATCH_LIMIT = 10
SCHEMA_VERSION = "revenue_audit_launch_batch.v1"


def _nonempty_text(value: Any) -> str:
    return str(value or "").strip()


def _has_signal(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _merge_signal_metadata(*items: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if _has_signal(value):
                merged[key] = value
            else:
                merged.setdefault(key, value)
    return merged


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


@dataclass(frozen=True)
class LaunchBatchProspectRecord:
    company_name: str
    website_url: str
    country_code: str
    segment: str
    city: str = ""
    state: str = ""
    status: str = "selected"
    skip_reason: str = ""
    selection_rank: int | None = None
    account_id: int | None = None
    contact_id: int | None = None
    lead_id: int | None = None
    opportunity_id: int | None = None
    prospect_profile_id: int | None = None
    audit_bundle_id: int | None = None
    fit_score: float = 0.0
    purchase_probability: float = 0.0
    projected_price_usd: float = 0.0
    expected_value_usd: float = 0.0
    price_tier: dict[str, Any] = field(default_factory=dict)
    quick_win: str = ""
    issue_evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    contact_channels: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    discovery_notes: tuple[str, ...] = field(default_factory=tuple)
    failure_detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issue_evidence"] = list(self.issue_evidence)
        payload["contact_channels"] = list(self.contact_channels)
        payload["discovery_notes"] = list(self.discovery_notes)
        return payload


@dataclass(frozen=True)
class LaunchBatchRefreshArtifact:
    schema_version: str
    generated_at: str
    source_artifact: str | None
    max_prospects: int
    seeds_loaded: int
    qualified_candidates: int
    selected_prospects: int
    overflow_count: int
    synced_accounts: int
    synced_contacts: int
    synced_leads: int
    synced_opportunities: int
    stored_prospect_profiles: int
    stored_issue_evidence: int
    stored_audit_bundles: int
    skipped_non_us: int
    skipped_missing_evidence: int
    skipped_missing_contact: int
    skipped_fetch_error: int
    prospects: tuple[LaunchBatchProspectRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prospects"] = [item.to_dict() for item in self.prospects]
        return payload


@dataclass(frozen=True)
class _QualifiedCandidate:
    seed: CuratedProspectSeed
    profile: ProspectProfile
    bundle: AuditBundle
    issues: tuple[IssueEvidence, ...]
    contact_channels: tuple[dict[str, Any], ...]
    primary_email: str
    primary_phone: str
    public_contact_url: str
    quick_win: str
    recommended_price_tier: dict[str, Any]
    fit_score: float


@dataclass(frozen=True)
class _CRMSyncResult:
    account_id: int | None
    contact_id: int | None
    lead_id: int | None
    opportunity_id: int | None
    prospect_profile_id: int | None
    audit_bundle_id: int | None
    issue_evidence_ids: tuple[int, ...] = ()


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


def refresh_curated_launch_batch(
    store: RevenueStore,
    *,
    source_path: Path,
    fetcher: PageFetcher | None = None,
    policy: FetchPolicy | None = None,
    max_prospects: int = CURATED_BATCH_LIMIT,
) -> LaunchBatchRefreshArtifact:
    if not source_path.exists():
        return LaunchBatchRefreshArtifact(
            schema_version=SCHEMA_VERSION,
            generated_at=utc_now(),
            source_artifact=None,
            max_prospects=max(1, int(max_prospects)),
            seeds_loaded=0,
            qualified_candidates=0,
            selected_prospects=0,
            overflow_count=0,
            synced_accounts=0,
            synced_contacts=0,
            synced_leads=0,
            synced_opportunities=0,
            stored_prospect_profiles=0,
            stored_issue_evidence=0,
            stored_audit_bundles=0,
            skipped_non_us=0,
            skipped_missing_evidence=0,
            skipped_missing_contact=0,
            skipped_fetch_error=0,
            prospects=(),
        )

    max_prospects = max(1, int(max_prospects))
    seeds = load_curated_prospect_seeds(source_path)
    skipped_non_us = 0
    skipped_missing_evidence = 0
    skipped_missing_contact = 0
    skipped_fetch_error = 0
    skipped_records: list[LaunchBatchProspectRecord] = []
    qualified: list[_QualifiedCandidate] = []

    for seed in seeds:
        if seed.country_code != "US":
            skipped_non_us += 1
            skipped_records.append(
                LaunchBatchProspectRecord(
                    company_name=seed.company_name,
                    website_url=seed.website_url,
                    country_code=seed.country_code,
                    segment=seed.segment,
                    city=seed.city,
                    state=seed.state,
                    status="skipped",
                    skip_reason="non_us",
                )
            )
            continue

        try:
            profile = discover_prospect(
                seed.website_url,
                fetcher=fetcher,
                policy=policy,
                company_name=seed.company_name,
                country_code=seed.country_code,
                discovery_source="curated_launch_batch",
            )
            bundle = build_audit_bundle(profile, offer=WEBSITE_GROWTH_AUDIT)
        except Exception as exc:  # pragma: no cover - network-path defense
            skipped_fetch_error += 1
            skipped_records.append(
                LaunchBatchProspectRecord(
                    company_name=seed.company_name,
                    website_url=seed.website_url,
                    country_code=seed.country_code,
                    segment=seed.segment,
                    city=seed.city,
                    state=seed.state,
                    status="skipped",
                    skip_reason="fetch_error",
                    failure_detail=exc.__class__.__name__,
                )
            )
            continue

        issues = bundle.issues[:3]
        if len(issues) < 2:
            skipped_missing_evidence += 1
            skipped_records.append(
                LaunchBatchProspectRecord(
                    company_name=seed.company_name,
                    website_url=profile.website_url or seed.website_url,
                    country_code=seed.country_code,
                    segment=seed.segment,
                    city=seed.city,
                    state=seed.state,
                    status="skipped",
                    skip_reason="missing_evidence",
                    discovery_notes=tuple(profile.discovery_notes),
                )
            )
            continue

        contact_channels = tuple(_contact_channels(profile))
        primary_email = next((item["value"] for item in contact_channels if item["kind"] == "email"), "")
        primary_phone = next((item["value"] for item in contact_channels if item["kind"] == "phone"), "")
        public_contact_url = next(
            (item["value"] for item in contact_channels if item["kind"] in {"contact_form", "contact_page"}),
            "",
        )
        if not primary_email and not primary_phone and not public_contact_url:
            skipped_missing_contact += 1
            skipped_records.append(
                LaunchBatchProspectRecord(
                    company_name=seed.company_name,
                    website_url=profile.website_url or seed.website_url,
                    country_code=seed.country_code,
                    segment=seed.segment,
                    city=seed.city,
                    state=seed.state,
                    status="skipped",
                    skip_reason="missing_contact",
                    issue_evidence=tuple(_issue_payload(issue) for issue in issues),
                    discovery_notes=tuple(profile.discovery_notes),
                )
            )
            continue

        qualified.append(
            _QualifiedCandidate(
                seed=seed,
                profile=profile,
                bundle=bundle,
                issues=issues,
                contact_channels=contact_channels,
                primary_email=primary_email,
                primary_phone=primary_phone,
                public_contact_url=public_contact_url,
                quick_win=_quick_win_for_issue(issues[0].issue_id),
                recommended_price_tier=_recommended_price_tier(bundle.score.projected_price_usd),
                fit_score=_fit_score(bundle, issues),
            )
        )

    qualified.sort(
        key=lambda item: (
            item.fit_score,
            item.bundle.score.expected_value_usd,
            item.bundle.score.projected_price_usd,
            item.seed.company_name.lower(),
        ),
        reverse=True,
    )

    synced_accounts = 0
    synced_contacts = 0
    synced_leads = 0
    synced_opportunities = 0
    stored_prospect_profiles = 0
    stored_issue_evidence = 0
    stored_audit_bundles = 0
    synced_records: list[LaunchBatchProspectRecord] = []

    for index, candidate in enumerate(qualified, start=1):
        status = "selected" if index <= max_prospects else "overflow"
        sync_result = _sync_candidate_to_crm(
            store,
            candidate,
            source_path=source_path,
            status=status,
            selection_rank=index if status == "selected" else None,
        )
        synced_accounts += 1 if sync_result.account_id is not None else 0
        synced_contacts += 1 if sync_result.contact_id is not None else 0
        synced_leads += 1 if sync_result.lead_id is not None else 0
        synced_opportunities += 1 if sync_result.opportunity_id is not None else 0
        stored_prospect_profiles += 1 if sync_result.prospect_profile_id is not None else 0
        stored_issue_evidence += len(sync_result.issue_evidence_ids)
        stored_audit_bundles += 1 if sync_result.audit_bundle_id is not None else 0
        synced_records.append(
            LaunchBatchProspectRecord(
                company_name=candidate.seed.company_name,
                website_url=candidate.profile.website_url,
                country_code=candidate.seed.country_code,
                segment=candidate.seed.segment,
                city=candidate.seed.city,
                state=candidate.seed.state,
                status=status,
                selection_rank=index if status == "selected" else None,
                account_id=sync_result.account_id,
                contact_id=sync_result.contact_id,
                lead_id=sync_result.lead_id,
                opportunity_id=sync_result.opportunity_id,
                prospect_profile_id=sync_result.prospect_profile_id,
                audit_bundle_id=sync_result.audit_bundle_id,
                fit_score=candidate.fit_score,
                purchase_probability=candidate.bundle.score.purchase_probability,
                projected_price_usd=candidate.bundle.score.projected_price_usd,
                expected_value_usd=candidate.bundle.score.expected_value_usd,
                price_tier=dict(candidate.recommended_price_tier),
                quick_win=candidate.quick_win,
                issue_evidence=tuple(_issue_payload(issue) for issue in candidate.issues),
                contact_channels=candidate.contact_channels,
                discovery_notes=tuple(candidate.profile.discovery_notes),
            )
        )

    selected_count = min(len(qualified), max_prospects)
    overflow_count = max(len(qualified) - selected_count, 0)
    ordered_records = tuple(synced_records + skipped_records)
    return LaunchBatchRefreshArtifact(
        schema_version=SCHEMA_VERSION,
        generated_at=utc_now(),
        source_artifact=str(source_path),
        max_prospects=max_prospects,
        seeds_loaded=len(seeds),
        qualified_candidates=len(qualified),
        selected_prospects=selected_count,
        overflow_count=overflow_count,
        synced_accounts=synced_accounts,
        synced_contacts=synced_contacts,
        synced_leads=synced_leads,
        synced_opportunities=synced_opportunities,
        stored_prospect_profiles=stored_prospect_profiles,
        stored_issue_evidence=stored_issue_evidence,
        stored_audit_bundles=stored_audit_bundles,
        skipped_non_us=skipped_non_us,
        skipped_missing_evidence=skipped_missing_evidence,
        skipped_missing_contact=skipped_missing_contact,
        skipped_fetch_error=skipped_fetch_error,
        prospects=ordered_records,
    )


def write_launch_batch_artifact(
    artifact: LaunchBatchRefreshArtifact,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def ingest_curated_launch_batch(
    store: RevenueStore,
    *,
    source_path: Path,
    fetcher: PageFetcher | None = None,
    policy: FetchPolicy | None = None,
) -> CuratedLaunchBatchIngestionResult:
    artifact = refresh_curated_launch_batch(
        store,
        source_path=source_path,
        fetcher=fetcher,
        policy=policy,
    )
    return CuratedLaunchBatchIngestionResult(
        source_artifact=artifact.source_artifact,
        seeds_loaded=artifact.seeds_loaded,
        seeded_accounts=artifact.qualified_candidates,
        skipped_non_us=artifact.skipped_non_us,
        skipped_missing_evidence=artifact.skipped_missing_evidence,
        skipped_missing_contact=artifact.skipped_missing_contact,
    )


def _fit_score(bundle: AuditBundle, issues: tuple[IssueEvidence, ...]) -> float:
    return round(
        min(
            100.0,
            bundle.score.purchase_probability * 100.0
            + len(issues) * 4.0
            + min(bundle.score.confidence_score * 10.0, 10.0),
        ),
        2,
    )


def _issue_payload(issue: IssueEvidence) -> dict[str, Any]:
    return {
        "label": issue.title or issue.summary or issue.issue_id.replace("_", " ").title(),
        "detail": issue.summary or issue.title,
        "source_field": issue.issue_id,
        "source_url": issue.source_url,
        "severity": issue.severity,
    }


def _sync_candidate_to_crm(
    store: RevenueStore,
    candidate: _QualifiedCandidate,
    *,
    source_path: Path,
    status: str,
    selection_rank: int | None,
) -> _CRMSyncResult:
    seed = candidate.seed
    issue_payloads = [_issue_payload(issue) for issue in candidate.issues]
    shared_metadata = _build_launch_metadata(
        seed=seed,
        profile=candidate.profile,
        bundle=candidate.bundle,
        issues=candidate.issues,
        contact_channels=candidate.contact_channels,
        public_contact_url=candidate.public_contact_url,
        quick_win=candidate.quick_win,
        recommended_price_tier=candidate.recommended_price_tier,
        fit_score=candidate.fit_score,
        source_path=source_path,
        status=status,
        selection_rank=selection_rank,
    )

    account, _ = store.upsert_account(
        Account(
            name=seed.company_name,
            domain=_domain_from_url(candidate.profile.website_url),
            industry=seed.segment,
            website_url=candidate.profile.website_url,
            status="researched",
            metadata=_merge_signal_metadata(
                shared_metadata,
                {"lead_email": candidate.primary_email} if candidate.primary_email else {},
            ),
        )
    )

    existing_contact_id = _find_matching_contact_id(
        store,
        account_id=account.id or 0,
        primary_email=candidate.primary_email,
        primary_phone=candidate.primary_phone,
        public_contact_url=candidate.public_contact_url,
    )
    contact, _ = store.upsert_contact(
        Contact(
            id=existing_contact_id,
            account_id=account.id or 0,
            full_name=seed.contact_name or "Owner / Team",
            email=candidate.primary_email,
            phone=candidate.primary_phone,
            role=seed.role,
            metadata=_merge_signal_metadata(
                shared_metadata,
                {
                    "country_code": seed.country_code,
                    "public_contact_channels": list(candidate.contact_channels),
                    "public_contact_url": candidate.public_contact_url,
                },
            ),
        )
    )

    lead_id: int | None = None
    if candidate.primary_email:
        lead, _ = store.upsert_lead(
            Lead(
                email=candidate.primary_email,
                company_name=seed.company_name,
                country_code=seed.country_code,
                source="curated_launch_batch",
                explicit_opt_in=False,
                metadata=_merge_signal_metadata(
                    shared_metadata,
                    {
                        "contact_name": contact.full_name,
                        "role": contact.role or seed.role,
                        "industry": seed.segment,
                        "company_size": "11-50",
                    },
                ),
            )
        )
        lead_id = lead.id

    opportunity_name = f"Website Growth Audit for {seed.company_name}"
    existing_opportunity = store.get_opportunity_by_name(
        account.id or 0,
        opportunity_name,
        WEBSITE_GROWTH_AUDIT.name,
    )
    opportunity, _ = store.upsert_opportunity(
        Opportunity(
            id=existing_opportunity.id if existing_opportunity is not None else None,
            account_id=account.id or 0,
            name=opportunity_name,
            offer_name=WEBSITE_GROWTH_AUDIT.name,
            stage="qualified",
            status="open",
            score=candidate.fit_score,
            score_breakdown={
                "purchase_probability": round(candidate.bundle.score.purchase_probability * 100.0, 2),
                "confidence_score": round(candidate.bundle.score.confidence_score * 100.0, 2),
                "issue_count": float(len(candidate.issues)),
            },
            estimated_value=float(candidate.bundle.score.projected_price_usd),
            next_action="launch_bridge",
            metadata=_merge_signal_metadata(
                existing_opportunity.metadata if existing_opportunity is not None else None,
                shared_metadata,
                {
                    "contact_id": contact.id or 0,
                    "recommended_price_usd": candidate.recommended_price_tier["price_usd"],
                    "price_tier": candidate.recommended_price_tier["label"],
                    "price_tier_price_usd": candidate.recommended_price_tier["price_usd"],
                },
            ),
        )
    )

    prospect_profile = store.create_prospect_profile(
        ProspectProfile(
            account_id=account.id,
            opportunity_id=opportunity.id,
            company_name=seed.company_name,
            domain=account.domain,
            website_url=candidate.profile.website_url,
            source="curated_launch_batch",
            segment=seed.segment,
            status="qualified" if status == "selected" else status,
            country_code=seed.country_code,
            score=candidate.fit_score,
            metadata=_merge_signal_metadata(
                shared_metadata,
                {
                    "sampled_pages": [page.url for page in candidate.profile.pages],
                    "public_contact_channels": list(candidate.contact_channels),
                    "public_contact_urls": list(candidate.profile.public_contact_urls),
                    "discovery_notes": list(candidate.profile.discovery_notes),
                },
            ),
        )
    )

    stored_issues = tuple(
        store.create_issue_evidence(
            IssueEvidence(
                prospect_id=prospect_profile.id,
                issue_id=issue.issue_id,
                issue_key=issue.issue_key,
                category=issue.category,
                severity=issue.severity,
                confidence=issue.confidence,
                source_url=issue.source_url,
                summary=issue.summary,
                title=issue.title,
                explanation=issue.explanation,
                evidence_text=issue.evidence_text or issue.summary,
                evidence_snippet=issue.evidence_snippet or issue.summary,
                impact_score=issue.impact_score,
                detector_key=issue.detector_key,
                missing_data_flags=issue.missing_data_flags,
                detector_version=issue.detector_version,
                metadata={"selection_status": status, "selection_rank": selection_rank or 0},
            )
        )
        for issue in candidate.issues
    )
    stored_bundle = store.create_audit_bundle(
        AuditBundle(
            prospect=prospect_profile,
            opportunity_id=opportunity.id,
            bundle_kind="launch_batch",
            status="generated",
            offer_slug=WEBSITE_GROWTH_AUDIT.slug,
            issues=stored_issues,
            score=candidate.bundle.score,
            metadata=_merge_signal_metadata(
                shared_metadata,
                {
                    "score": candidate.bundle.score.to_dict(),
                    "selection_status": status,
                    "selection_rank": selection_rank or 0,
                    "issue_evidence": issue_payloads,
                },
            ),
        )
    )
    return _CRMSyncResult(
        account_id=account.id,
        contact_id=contact.id,
        lead_id=lead_id,
        opportunity_id=opportunity.id,
        prospect_profile_id=prospect_profile.id,
        audit_bundle_id=stored_bundle.id,
        issue_evidence_ids=tuple(issue.id for issue in stored_issues if issue.id is not None),
    )


def _build_launch_metadata(
    *,
    seed: CuratedProspectSeed,
    profile: ProspectProfile,
    bundle: AuditBundle,
    issues: tuple[IssueEvidence, ...],
    contact_channels: tuple[dict[str, Any], ...],
    public_contact_url: str,
    quick_win: str,
    recommended_price_tier: dict[str, Any],
    fit_score: float,
    source_path: Path,
    status: str,
    selection_rank: int | None,
) -> dict[str, Any]:
    issue_payloads = [_issue_payload(issue) for issue in issues]
    metadata = {
        "curated_launch_batch": True,
        "launch_ready": status == "selected",
        "human_review_batch": True,
        "country_code": seed.country_code,
        "website_url": profile.website_url,
        "segment": seed.segment,
        "city": seed.city,
        "state": seed.state,
        "launch_batch_source_artifact": str(source_path),
        "launch_batch_seed_company": seed.company_name,
        "launch_batch_segment": seed.segment,
        "launch_batch_city": seed.city,
        "launch_batch_state": seed.state,
        "launch_batch_notes": seed.notes,
        "launch_batch_status": status,
        "launch_batch_rank": selection_rank or 0,
        "issue_evidence": issue_payloads,
        "website_findings": issues[0].summary,
        "specific_finding": issues[1].summary if len(issues) > 1 else issues[0].summary,
        "quick_win": quick_win,
        "price_tier": recommended_price_tier["label"],
        "price_tier_label": recommended_price_tier["label"],
        "price_tier_price_usd": recommended_price_tier["price_usd"],
        "recommended_price_tier": dict(recommended_price_tier),
        "recommended_price_usd": recommended_price_tier["price_usd"],
        "public_contact_channels": list(contact_channels),
        "public_contact_url": public_contact_url,
        "score_fit": fit_score,
        "score_purchase_probability": bundle.score.purchase_probability,
        "score_projected_price_usd": bundle.score.projected_price_usd,
        "score_expected_value_usd": bundle.score.expected_value_usd,
        "score_confidence": bundle.score.confidence_score,
        "bundle_summary": bundle.summary,
        "discovery_notes": list(profile.discovery_notes),
    }
    return metadata


def _find_matching_contact_id(
    store: RevenueStore,
    *,
    account_id: int,
    primary_email: str,
    primary_phone: str,
    public_contact_url: str,
) -> int | None:
    if primary_email:
        existing = store.get_contact_by_email(account_id, primary_email)
        return existing.id if existing is not None else None

    normalized_phone = _normalized_phone(primary_phone)
    normalized_url = _nonempty_text(public_contact_url)
    for existing in store.list_contacts(account_id=account_id):
        if _nonempty_text(existing.email):
            continue
        if normalized_phone and _normalized_phone(existing.phone) == normalized_phone:
            return existing.id
        if normalized_url and _nonempty_text(existing.metadata.get("public_contact_url")) == normalized_url:
            return existing.id
    return None


def _contact_channels(profile: ProspectProfile) -> list[dict[str, Any]]:
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


def _normalized_phone(value: str) -> str:
    return "".join(character for character in _nonempty_text(value) if character.isdigit())
