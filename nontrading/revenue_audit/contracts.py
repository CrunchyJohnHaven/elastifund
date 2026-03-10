"""Shared contracts for the JJ-N revenue_audit engine family."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_email(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def normalize_currency(value: str | None) -> str:
    text = (value or "USD").strip().upper()
    return text or "USD"


@dataclass(frozen=True)
class ProspectProfile:
    business_name: str
    website_url: str = ""
    contact_email: str = ""
    contact_name: str = ""
    country_code: str = "US"
    industry: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "business_name", str(self.business_name).strip())
        object.__setattr__(self, "website_url", str(self.website_url).strip())
        object.__setattr__(self, "contact_email", normalize_email(self.contact_email))
        object.__setattr__(self, "contact_name", str(self.contact_name).strip())
        object.__setattr__(self, "country_code", str(self.country_code or "US").strip().upper() or "US")
        object.__setattr__(self, "industry", str(self.industry).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class IssueEvidence:
    detector_key: str
    summary: str
    severity: str = "medium"
    evidence_url: str = ""
    evidence_snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "detector_key", str(self.detector_key).strip())
        object.__setattr__(self, "summary", str(self.summary).strip())
        object.__setattr__(self, "severity", str(self.severity or "medium").strip().lower())
        object.__setattr__(self, "evidence_url", str(self.evidence_url).strip())
        object.__setattr__(self, "evidence_snippet", str(self.evidence_snippet).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class AuditBundle:
    bundle_id: str
    offer_slug: str = "website-growth-audit"
    generated_at: str = field(default_factory=utc_now)
    prospect: ProspectProfile | None = None
    issues: tuple[IssueEvidence, ...] = field(default_factory=tuple)
    score: dict[str, float] = field(default_factory=dict)
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", str(self.bundle_id).strip())
        object.__setattr__(self, "offer_slug", str(self.offer_slug or "website-growth-audit").strip().lower())
        object.__setattr__(self, "generated_at", str(self.generated_at or utc_now()).strip())
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "score", {str(key): float(value) for key, value in self.score.items()})
        object.__setattr__(self, "summary", str(self.summary).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class CheckoutPrice:
    key: str
    label: str
    amount_usd: float
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", str(self.key).strip().lower())
        object.__setattr__(self, "label", str(self.label).strip())
        object.__setattr__(self, "amount_usd", round(float(self.amount_usd), 2))
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def amount_cents(self) -> int:
        return int(round(self.amount_usd * 100))


@dataclass(frozen=True)
class CreateCheckoutRequest:
    price_key: str
    customer_email: str
    customer_name: str = ""
    business_name: str = ""
    website_url: str = ""
    success_url: str = ""
    cancel_url: str = ""
    prospect_profile: ProspectProfile | None = None
    audit_bundle: AuditBundle | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "price_key", str(self.price_key).strip().lower())
        object.__setattr__(self, "customer_email", normalize_email(self.customer_email))
        object.__setattr__(self, "customer_name", str(self.customer_name).strip())
        object.__setattr__(self, "business_name", str(self.business_name).strip())
        object.__setattr__(self, "website_url", str(self.website_url).strip())
        object.__setattr__(self, "success_url", str(self.success_url).strip())
        object.__setattr__(self, "cancel_url", str(self.cancel_url).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class AuditOrder:
    order_id: str
    offer_slug: str
    price_key: str
    amount_subtotal_usd: float
    amount_total_usd: float
    currency: str = "USD"
    status: str = "checkout_pending"
    fulfillment_status: str = "not_started"
    customer_email: str = ""
    customer_name: str = ""
    business_name: str = ""
    website_url: str = ""
    crm_account_id: int | None = None
    crm_opportunity_id: int | None = None
    crm_proposal_id: int | None = None
    crm_outcome_id: int | None = None
    prospect_profile: ProspectProfile | None = None
    audit_bundle: AuditBundle | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    paid_at: str | None = None
    delivered_at: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "offer_slug", str(self.offer_slug).strip().lower())
        object.__setattr__(self, "price_key", str(self.price_key).strip().lower())
        object.__setattr__(self, "amount_subtotal_usd", round(float(self.amount_subtotal_usd), 2))
        object.__setattr__(self, "amount_total_usd", round(float(self.amount_total_usd), 2))
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(self, "status", str(self.status).strip().lower())
        object.__setattr__(self, "fulfillment_status", str(self.fulfillment_status).strip().lower())
        object.__setattr__(self, "customer_email", normalize_email(self.customer_email))
        object.__setattr__(self, "customer_name", str(self.customer_name).strip())
        object.__setattr__(self, "business_name", str(self.business_name).strip())
        object.__setattr__(self, "website_url", str(self.website_url).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class CheckoutSession:
    session_id: str
    order_id: str
    provider: str = "stripe"
    provider_session_id: str = ""
    provider_payment_intent_id: str = ""
    status: str = "created"
    hosted_url: str = ""
    amount_subtotal_usd: float = 0.0
    amount_total_usd: float = 0.0
    currency: str = "USD"
    customer_email: str = ""
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", str(self.session_id).strip())
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "provider", str(self.provider or "stripe").strip().lower())
        object.__setattr__(self, "provider_session_id", str(self.provider_session_id).strip())
        object.__setattr__(self, "provider_payment_intent_id", str(self.provider_payment_intent_id).strip())
        object.__setattr__(self, "status", str(self.status or "created").strip().lower())
        object.__setattr__(self, "hosted_url", str(self.hosted_url).strip())
        object.__setattr__(self, "amount_subtotal_usd", round(float(self.amount_subtotal_usd), 2))
        object.__setattr__(self, "amount_total_usd", round(float(self.amount_total_usd), 2))
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(self, "customer_email", normalize_email(self.customer_email))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class PaymentEvent:
    payment_event_id: str
    order_id: str
    provider: str
    provider_event_id: str
    event_type: str
    status: str
    amount_total_usd: float = 0.0
    currency: str = "USD"
    provider_session_id: str = ""
    provider_payment_intent_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payment_event_id", str(self.payment_event_id).strip())
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "provider", str(self.provider).strip().lower())
        object.__setattr__(self, "provider_event_id", str(self.provider_event_id).strip())
        object.__setattr__(self, "event_type", str(self.event_type).strip())
        object.__setattr__(self, "status", str(self.status).strip().lower())
        object.__setattr__(self, "amount_total_usd", round(float(self.amount_total_usd), 2))
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        object.__setattr__(self, "provider_session_id", str(self.provider_session_id).strip())
        object.__setattr__(self, "provider_payment_intent_id", str(self.provider_payment_intent_id).strip())
        object.__setattr__(self, "payload", dict(self.payload))


@dataclass(frozen=True)
class FulfillmentJob:
    job_id: str
    order_id: str
    job_type: str
    status: str = "queued"
    artifact_uri: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", str(self.job_id).strip())
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "job_type", str(self.job_type).strip().lower())
        object.__setattr__(self, "status", str(self.status).strip().lower())
        object.__setattr__(self, "artifact_uri", str(self.artifact_uri).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class MonitorRun:
    run_id: str
    order_id: str
    status: str = "queued"
    baseline_bundle_id: str = ""
    current_bundle_id: str = ""
    delta_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", str(self.run_id).strip())
        object.__setattr__(self, "order_id", str(self.order_id).strip())
        object.__setattr__(self, "status", str(self.status).strip().lower())
        object.__setattr__(self, "baseline_bundle_id", str(self.baseline_bundle_id).strip())
        object.__setattr__(self, "current_bundle_id", str(self.current_bundle_id).strip())
        object.__setattr__(self, "delta_summary", str(self.delta_summary).strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class FirstDollarReadiness:
    state: str
    score: float = 0.0
    blockers: tuple[str, ...] = field(default_factory=tuple)
    signals: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", str(self.state).strip().lower())
        object.__setattr__(self, "score", round(float(self.score), 4))
        object.__setattr__(self, "blockers", tuple(str(item).strip() for item in self.blockers if str(item).strip()))
        object.__setattr__(self, "signals", dict(self.signals))


def contract_to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, tuple):
        return [contract_to_dict(item) for item in value]
    if isinstance(value, list):
        return [contract_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): contract_to_dict(item) for key, item in value.items()}
    return value
