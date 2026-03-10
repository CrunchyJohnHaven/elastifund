"""Shared contracts for the JJ-N revenue audit engine family."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

from nontrading.models import normalize_country, normalize_domain, utc_now

VALID_CONTACT_CHANNEL_KINDS = frozenset({"email", "phone", "contact_form", "contact_page"})
VALID_ISSUE_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
VALID_READINESS_STATUSES = frozenset(
    {
        "setup_only",
        "launchable",
        "paid_order_seen",
        "first_dollar_observed",
    }
)
VALID_PAYMENT_STATUSES = frozenset(
    {
        "pending",
        "requires_action",
        "created",
        "paid",
        "succeeded",
        "completed",
        "failed",
        "refunded",
    }
)
VALID_JOB_STATUSES = frozenset(
    {
        "queued",
        "running",
        "completed",
        "delivered",
        "failed",
        "canceled",
    }
)


def _clamp(value: float | None, *, minimum: float = 0.0, maximum: float = 1.0, default: float = 0.0) -> float:
    if value is None:
        return default
    return max(minimum, min(maximum, float(value)))


def _normalize_url(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme for revenue audit record: {value}")
    if not parsed.netloc:
        raise ValueError(f"Revenue audit record requires an absolute URL: {value}")
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
    )
    path = normalized.path or "/"
    return urlunparse(normalized._replace(path=path))


def _dedupe_key(item: Any) -> str:
    if hasattr(item, "to_dict"):
        payload = item.to_dict()
    else:
        payload = item
    return json.dumps(payload, sort_keys=True, default=str)


def _dedupe(items: tuple[Any, ...]) -> tuple[Any, ...]:
    seen: set[str] = set()
    ordered: list[Any] = []
    for item in items:
        key = _dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return tuple(ordered)


@dataclass(frozen=True)
class PublicContactChannel:
    kind: str
    value: str
    source_url: str
    label: str = ""
    is_business: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip().lower().replace("-", "_")
        if kind not in VALID_CONTACT_CHANNEL_KINDS:
            raise ValueError(f"Unsupported contact channel kind: {self.kind}")
        value = str(self.value).strip()
        if not value:
            raise ValueError("contact channel value is required")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "source_url", _normalize_url(self.source_url))
        object.__setattr__(self, "label", str(self.label).strip())
        object.__setattr__(self, "is_business", bool(self.is_business))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str = ""
    status_code: int = 200
    content_type: str = "text/html"
    title: str = ""
    meta_description: str = ""
    canonical_url: str = ""
    h1: tuple[str, ...] = field(default_factory=tuple)
    text: str = ""
    internal_links: tuple[str, ...] = field(default_factory=tuple)
    external_links: tuple[str, ...] = field(default_factory=tuple)
    cta_texts: tuple[str, ...] = field(default_factory=tuple)
    schema_types: tuple[str, ...] = field(default_factory=tuple)
    contact_channels: tuple[PublicContactChannel, ...] = field(default_factory=tuple)
    forms_detected: bool = False
    script_count: int = 0
    image_count: int = 0
    word_count: int = 0
    html_bytes: int = 0
    fetched_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        url = _normalize_url(self.url)
        final_url = _normalize_url(self.final_url or url)
        canonical_url = _normalize_url(self.canonical_url) if str(self.canonical_url or "").strip() else ""
        text = " ".join(str(self.text or "").split())
        word_count = int(self.word_count or len(text.split()))
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "final_url", final_url)
        object.__setattr__(self, "status_code", int(self.status_code))
        object.__setattr__(self, "content_type", str(self.content_type or "text/html").strip().lower())
        object.__setattr__(self, "title", str(self.title).strip())
        object.__setattr__(self, "meta_description", str(self.meta_description).strip())
        object.__setattr__(self, "canonical_url", canonical_url)
        object.__setattr__(self, "h1", _dedupe(tuple(str(item).strip() for item in self.h1 if str(item).strip())))
        object.__setattr__(self, "text", text)
        object.__setattr__(
            self,
            "internal_links",
            _dedupe(tuple(_normalize_url(link) for link in self.internal_links if str(link).strip())),
        )
        object.__setattr__(
            self,
            "external_links",
            _dedupe(tuple(_normalize_url(link) for link in self.external_links if str(link).strip())),
        )
        object.__setattr__(
            self,
            "cta_texts",
            _dedupe(tuple(str(item).strip() for item in self.cta_texts if str(item).strip())),
        )
        object.__setattr__(
            self,
            "schema_types",
            _dedupe(tuple(str(item).strip() for item in self.schema_types if str(item).strip())),
        )
        object.__setattr__(self, "contact_channels", _dedupe(tuple(self.contact_channels)))
        object.__setattr__(self, "forms_detected", bool(self.forms_detected))
        object.__setattr__(self, "script_count", max(0, int(self.script_count)))
        object.__setattr__(self, "image_count", max(0, int(self.image_count)))
        object.__setattr__(self, "word_count", max(0, word_count))
        object.__setattr__(self, "html_bytes", max(0, int(self.html_bytes)))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProspectProfile:
    website_url: str = ""
    seed_url: str = ""
    domain: str = ""
    company_name: str = ""
    source: str = "public_web"
    discovery_source: str = ""
    segment: str = ""
    status: str = "discovered"
    country_code: str = "US"
    score: float = 0.0
    pages: tuple[FetchedPage, ...] = field(default_factory=tuple)
    contact_channels: tuple[PublicContactChannel, ...] = field(default_factory=tuple)
    public_contact_urls: tuple[str, ...] = field(default_factory=tuple)
    discovery_notes: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    account_id: int | None = None
    opportunity_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        website_url = str(self.website_url or "").strip()
        seed_url = str(self.seed_url or "").strip()
        if not website_url and seed_url:
            website_url = seed_url
        if not seed_url and website_url:
            seed_url = website_url
        if not website_url and self.domain:
            website_url = f"https://{normalize_domain(self.domain)}/"
            seed_url = website_url
        if website_url:
            website_url = _normalize_url(website_url)
        if seed_url:
            seed_url = _normalize_url(seed_url)
        domain = normalize_domain(self.domain) or normalize_domain(urlparse(website_url or seed_url).netloc)
        source = str(self.discovery_source or self.source or "public_web").strip().lower()
        object.__setattr__(self, "website_url", website_url)
        object.__setattr__(self, "seed_url", seed_url)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "company_name", str(self.company_name).strip())
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "discovery_source", source)
        object.__setattr__(self, "segment", str(self.segment).strip().lower())
        object.__setattr__(self, "status", str(self.status or "discovered").strip().lower())
        object.__setattr__(self, "country_code", normalize_country(self.country_code))
        object.__setattr__(self, "score", round(max(0.0, float(self.score)), 4))
        object.__setattr__(self, "pages", _dedupe(tuple(self.pages)))
        object.__setattr__(self, "contact_channels", _dedupe(tuple(self.contact_channels)))
        object.__setattr__(
            self,
            "public_contact_urls",
            _dedupe(tuple(_normalize_url(item) for item in self.public_contact_urls if str(item).strip())),
        )
        object.__setattr__(
            self,
            "discovery_notes",
            _dedupe(tuple(str(note).strip() for note in self.discovery_notes if str(note).strip())),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def homepage(self) -> FetchedPage | None:
        return self.pages[0] if self.pages else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IssueEvidence:
    issue_id: str = ""
    issue_key: str = ""
    category: str = ""
    severity: str = "medium"
    confidence: float = 0.0
    source_url: str = ""
    summary: str = ""
    title: str = ""
    explanation: str = ""
    evidence_text: str = ""
    evidence_snippet: str = ""
    impact_score: float = 0.0
    detector_key: str = ""
    missing_data_flags: tuple[str, ...] = field(default_factory=tuple)
    detector_version: str = "revenue_audit.detectors.v1"
    status: str = "open"
    prospect_id: int | None = None
    id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        severity = str(self.severity).strip().lower()
        if severity not in VALID_ISSUE_SEVERITIES:
            raise ValueError(f"Unsupported issue severity: {self.severity}")
        issue_key = str(self.issue_key or self.issue_id).strip().lower().replace(" ", "_")
        issue_id = str(self.issue_id or issue_key).strip().lower().replace(" ", "_")
        detector_key = str(self.detector_key or self.detector_version).strip().lower()
        source_url = str(self.source_url).strip()
        impact_score = float(self.impact_score) if self.impact_score else 0.0
        if impact_score <= 0.0:
            impact_score = {"critical": 1.0, "high": 0.8, "medium": 0.55, "low": 0.3}[severity] * _clamp(
                self.confidence
            )
        evidence_text = " ".join(str(self.evidence_text or self.evidence_snippet).split())
        evidence_snippet = " ".join(str(self.evidence_snippet or evidence_text).split())
        object.__setattr__(self, "issue_id", issue_id)
        object.__setattr__(self, "issue_key", issue_key)
        object.__setattr__(self, "category", str(self.category).strip().lower())
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "confidence", round(_clamp(self.confidence), 4))
        object.__setattr__(self, "source_url", _normalize_url(source_url) if source_url else "")
        object.__setattr__(self, "summary", str(self.summary).strip())
        object.__setattr__(self, "title", str(self.title or self.summary).strip())
        object.__setattr__(self, "explanation", str(self.explanation).strip())
        object.__setattr__(self, "evidence_text", evidence_text)
        object.__setattr__(self, "evidence_snippet", evidence_snippet)
        object.__setattr__(self, "impact_score", round(max(0.0, impact_score), 4))
        object.__setattr__(self, "detector_key", detector_key)
        object.__setattr__(
            self,
            "missing_data_flags",
            _dedupe(tuple(str(flag).strip().lower() for flag in self.missing_data_flags if str(flag).strip())),
        )
        object.__setattr__(self, "detector_version", str(self.detector_version).strip())
        object.__setattr__(self, "status", str(self.status or "open").strip().lower())
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditScore:
    purchase_probability: float
    projected_price_usd: float
    expected_margin_usd: float
    expected_margin_pct: float
    expected_value_usd: float
    expected_payback_days: float
    confidence_score: float
    compliance_risk_score: float
    explanation: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "purchase_probability", round(_clamp(self.purchase_probability), 4))
        object.__setattr__(self, "projected_price_usd", round(float(self.projected_price_usd), 2))
        object.__setattr__(self, "expected_margin_usd", round(float(self.expected_margin_usd), 2))
        object.__setattr__(self, "expected_margin_pct", round(float(self.expected_margin_pct), 4))
        object.__setattr__(self, "expected_value_usd", round(float(self.expected_value_usd), 2))
        object.__setattr__(self, "expected_payback_days", round(max(0.0, float(self.expected_payback_days)), 2))
        object.__setattr__(self, "confidence_score", round(_clamp(self.confidence_score), 4))
        object.__setattr__(self, "compliance_risk_score", round(_clamp(self.compliance_risk_score), 4))
        object.__setattr__(self, "explanation", dict(self.explanation))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __float__(self) -> float:
        return float(self.expected_value_usd)


@dataclass(frozen=True)
class AuditBundle:
    prospect: ProspectProfile | None = None
    issues: tuple[IssueEvidence, ...] = field(default_factory=tuple)
    score: AuditScore | float = 0.0
    id: int | None = None
    prospect_id: int | None = None
    opportunity_id: int | None = None
    proposal_id: int | None = None
    order_id: str = ""
    bundle_kind: str = "baseline"
    status: str = "generated"
    offer_slug: str = "website-growth-audit"
    issue_ids: tuple[int, ...] = field(default_factory=tuple)
    artifact_path: str = ""
    comparison_only: bool = False
    generated_at: str = field(default_factory=utc_now)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        issues = _dedupe(tuple(self.issues))
        issue_ids = tuple(int(item) for item in self.issue_ids if item not in {None, ""})
        if not issue_ids and issues:
            issue_ids = tuple(int(item.id) for item in issues if item.id is not None)
        summary = str(self.summary).strip()
        if not summary:
            if isinstance(self.score, AuditScore) and self.prospect is not None:
                label = self.prospect.company_name or self.prospect.domain
                summary = (
                    f"{label}: {len(issues)} deterministic issues, "
                    f"purchase_probability={self.score.purchase_probability:.2f}, "
                    f"expected_margin_usd={self.score.expected_margin_usd:.2f}"
                )
            else:
                summary = f"{self.bundle_kind or 'baseline'} revenue-audit bundle"
        prospect_id = self.prospect_id
        if prospect_id is None and self.prospect is not None:
            prospect_id = self.prospect.id
        created_at = self.created_at or self.generated_at
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "prospect_id", prospect_id)
        object.__setattr__(self, "opportunity_id", self.opportunity_id)
        object.__setattr__(self, "proposal_id", self.proposal_id)
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "bundle_kind", str(self.bundle_kind or "baseline").strip().lower())
        object.__setattr__(self, "status", str(self.status or "generated").strip().lower())
        object.__setattr__(self, "offer_slug", str(self.offer_slug).strip().lower())
        object.__setattr__(self, "issue_ids", _dedupe(tuple(issue_ids)))
        object.__setattr__(self, "artifact_path", str(self.artifact_path).strip())
        object.__setattr__(self, "comparison_only", bool(self.comparison_only))
        object.__setattr__(self, "generated_at", str(self.generated_at or created_at).strip())
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", self.updated_at or created_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CheckoutSession:
    id: int | None = None
    prospect_id: int | None = None
    opportunity_id: int | None = None
    proposal_id: int | None = None
    offer_slug: str = "website-growth-audit"
    provider: str = "stripe"
    status: str = "pending"
    amount: float = 0.0
    currency: str = "USD"
    order_id: str = ""
    provider_session_id: str = ""
    success_url: str = ""
    cancel_url: str = ""
    customer_email: str = ""
    checkout_id: str = ""
    checkout_url: str = ""
    amount_usd: float = 0.0
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        amount = float(self.amount if self.amount else self.amount_usd)
        created_at = self.created_at or utc_now()
        checkout_url = str(self.checkout_url).strip()
        object.__setattr__(self, "offer_slug", str(self.offer_slug or "website-growth-audit").strip().lower())
        object.__setattr__(self, "provider", str(self.provider or "stripe").strip().lower())
        object.__setattr__(self, "status", str(self.status or "pending").strip().lower())
        object.__setattr__(self, "amount", round(max(0.0, amount), 2))
        object.__setattr__(self, "amount_usd", round(max(0.0, amount), 2))
        object.__setattr__(self, "currency", str(self.currency or "USD").strip().upper())
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "provider_session_id", str(self.provider_session_id).strip())
        object.__setattr__(self, "success_url", str(self.success_url).strip())
        object.__setattr__(self, "cancel_url", str(self.cancel_url).strip())
        object.__setattr__(self, "customer_email", str(self.customer_email).strip().lower())
        object.__setattr__(self, "checkout_id", str(self.checkout_id or self.id or "").strip())
        object.__setattr__(self, "checkout_url", _normalize_url(checkout_url) if checkout_url else "")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", self.updated_at or created_at)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaymentEvent:
    id: int | None = None
    checkout_session_id: int | None = None
    prospect_id: int | None = None
    opportunity_id: int | None = None
    proposal_id: int | None = None
    provider: str = "stripe"
    event_type: str = "payment"
    status: str = "pending"
    amount: float = 0.0
    currency: str = "USD"
    order_id: str = ""
    provider_event_id: str = ""
    customer_email: str = ""
    event_id: str = ""
    amount_usd: float = 0.0
    received_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        status = str(self.status or "pending").strip().lower()
        if status not in VALID_PAYMENT_STATUSES:
            raise ValueError(f"Unsupported payment status: {self.status}")
        amount = float(self.amount if self.amount else self.amount_usd)
        created_at = self.created_at or self.received_at or utc_now()
        object.__setattr__(self, "provider", str(self.provider or "stripe").strip().lower())
        object.__setattr__(self, "event_type", str(self.event_type or "payment").strip().lower())
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "amount", round(float(amount), 2))
        object.__setattr__(self, "amount_usd", round(float(amount), 2))
        object.__setattr__(self, "currency", str(self.currency or "USD").strip().upper())
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "provider_event_id", str(self.provider_event_id).strip())
        object.__setattr__(self, "customer_email", str(self.customer_email).strip().lower())
        object.__setattr__(self, "event_id", str(self.event_id or self.provider_event_id or self.id or "").strip())
        object.__setattr__(self, "received_at", created_at)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", self.updated_at or created_at)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FulfillmentJob:
    id: int | None = None
    opportunity_id: int | None = None
    proposal_id: int | None = None
    prospect_id: int | None = None
    payment_event_id: int | None = None
    audit_bundle_id: int | None = None
    offer_slug: str = "website-growth-audit"
    status: str = "queued"
    current_step: str = ""
    order_id: str = ""
    artifact_path: str = ""
    checklist: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    job_id: str = ""
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)
    attempt_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = str(self.status or "queued").strip().lower()
        if status not in VALID_JOB_STATUSES:
            raise ValueError(f"Unsupported fulfillment job status: {self.status}")
        created_at = self.created_at or utc_now()
        artifact_path = str(self.artifact_path).strip()
        artifact_paths = tuple(str(path).strip() for path in self.artifact_paths if str(path).strip())
        if not artifact_path and artifact_paths:
            artifact_path = artifact_paths[0]
        if artifact_path and not artifact_paths:
            artifact_paths = (artifact_path,)
        object.__setattr__(self, "offer_slug", str(self.offer_slug or "website-growth-audit").strip().lower())
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "current_step", str(self.current_step or status).strip().lower())
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "artifact_path", artifact_path)
        object.__setattr__(self, "checklist", tuple(self.checklist))
        object.__setattr__(self, "job_id", str(self.job_id or self.id or "").strip())
        object.__setattr__(self, "artifact_paths", _dedupe(tuple(path for path in artifact_paths if path)))
        object.__setattr__(self, "attempt_count", max(0, int(self.attempt_count)))
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", self.updated_at or created_at)
        object.__setattr__(self, "started_at", self.started_at)
        object.__setattr__(self, "completed_at", self.completed_at)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitorRun:
    id: int | None = None
    opportunity_id: int | None = None
    fulfillment_job_id: int | None = None
    baseline_bundle_id: int | None = None
    current_bundle_id: int | None = None
    status: str = "queued"
    delta_artifact_path: str = ""
    new_issue_count: int = 0
    resolved_issue_count: int = 0
    persistent_issue_count: int = 0
    run_id: str = ""
    prospect_domain: str = ""
    order_id: str = ""
    trigger: str = "scheduled"
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)
    delta_summary: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = str(self.status or "queued").strip().lower()
        if status not in VALID_JOB_STATUSES:
            raise ValueError(f"Unsupported monitor run status: {self.status}")
        created_at = self.created_at or utc_now()
        domain = normalize_domain(self.prospect_domain)
        artifact_paths = tuple(str(path).strip() for path in self.artifact_paths if str(path).strip())
        delta_artifact_path = str(self.delta_artifact_path).strip()
        if not delta_artifact_path and artifact_paths:
            delta_artifact_path = artifact_paths[0]
        if delta_artifact_path and not artifact_paths:
            artifact_paths = (delta_artifact_path,)
        delta_summary = dict(self.delta_summary)
        if delta_summary:
            new_issue_count = int(delta_summary.get("new_issue_count", self.new_issue_count))
            resolved_issue_count = int(delta_summary.get("resolved_issue_count", self.resolved_issue_count))
            persistent_issue_count = int(delta_summary.get("persistent_issue_count", self.persistent_issue_count))
        else:
            new_issue_count = int(self.new_issue_count)
            resolved_issue_count = int(self.resolved_issue_count)
            persistent_issue_count = int(self.persistent_issue_count)
            delta_summary = {
                "new_issue_count": new_issue_count,
                "resolved_issue_count": resolved_issue_count,
                "persistent_issue_count": persistent_issue_count,
            }
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "delta_artifact_path", delta_artifact_path)
        object.__setattr__(self, "new_issue_count", max(0, new_issue_count))
        object.__setattr__(self, "resolved_issue_count", max(0, resolved_issue_count))
        object.__setattr__(self, "persistent_issue_count", max(0, persistent_issue_count))
        object.__setattr__(self, "run_id", str(self.run_id or self.id or "").strip())
        object.__setattr__(self, "prospect_domain", domain)
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "trigger", str(self.trigger or "scheduled").strip().lower())
        object.__setattr__(self, "artifact_paths", _dedupe(tuple(path for path in artifact_paths if path)))
        object.__setattr__(self, "delta_summary", delta_summary)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", self.updated_at or created_at)
        object.__setattr__(self, "started_at", self.started_at)
        object.__setattr__(self, "completed_at", self.completed_at)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FirstDollarReadiness:
    status: str
    launchable: bool = False
    paid_order_seen: bool = False
    first_dollar_observed: bool = False
    paid_orders_count: int = 0
    payments_collected_usd: float = 0.0
    fulfillment_jobs_total: int = 0
    delivered_jobs_total: int = 0
    completed_monitor_runs: int = 0
    expected_30d_cashflow_usd: float = 0.0
    readiness_score: float = 0.0
    paid_orders_seen: int = 0
    cash_collected_usd: float = 0.0
    time_to_first_dollar_hours: float | None = None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        status = str(self.status).strip().lower()
        if status not in VALID_READINESS_STATUSES:
            raise ValueError(f"Unsupported first-dollar readiness status: {self.status}")
        paid_orders_count = max(int(self.paid_orders_count), int(self.paid_orders_seen))
        payments_collected_usd = max(float(self.payments_collected_usd), float(self.cash_collected_usd))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "launchable", bool(self.launchable or status != "setup_only"))
        object.__setattr__(self, "paid_order_seen", bool(self.paid_order_seen or paid_orders_count > 0))
        object.__setattr__(
            self,
            "first_dollar_observed",
            bool(self.first_dollar_observed or status == "first_dollar_observed"),
        )
        object.__setattr__(self, "paid_orders_count", max(0, paid_orders_count))
        object.__setattr__(self, "payments_collected_usd", round(max(0.0, payments_collected_usd), 2))
        object.__setattr__(self, "fulfillment_jobs_total", max(0, int(self.fulfillment_jobs_total)))
        object.__setattr__(self, "delivered_jobs_total", max(0, int(self.delivered_jobs_total)))
        object.__setattr__(self, "completed_monitor_runs", max(0, int(self.completed_monitor_runs)))
        object.__setattr__(
            self,
            "expected_30d_cashflow_usd",
            round(max(0.0, float(self.expected_30d_cashflow_usd)), 2),
        )
        object.__setattr__(self, "readiness_score", round(_clamp(self.readiness_score, maximum=100.0), 2))
        object.__setattr__(self, "paid_orders_seen", max(0, paid_orders_count))
        object.__setattr__(self, "cash_collected_usd", round(max(0.0, payments_collected_usd), 2))
        object.__setattr__(
            self,
            "time_to_first_dollar_hours",
            None
            if self.time_to_first_dollar_hours is None
            else round(max(0.0, float(self.time_to_first_dollar_hours)), 2),
        )
        object.__setattr__(
            self,
            "blockers",
            _dedupe(tuple(str(item).strip() for item in self.blockers if str(item).strip())),
        )
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
