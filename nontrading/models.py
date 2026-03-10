"""Shared dataclasses for the non-trading revenue agent and JJ-N Phase 0."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_email(email: str | None) -> str:
    if not email:
        return ""
    return email.strip().lower()


def normalize_domain(domain: str | None) -> str:
    if not domain:
        return ""
    return domain.strip().lower().lstrip("@")


def normalize_country(country_code: str | None) -> str:
    if not country_code:
        return "US"
    return country_code.strip().upper()


@dataclass(frozen=True)
class Lead:
    email: str
    company_name: str = ""
    country_code: str = "US"
    source: str = "manual"
    explicit_opt_in: bool = False
    opt_in_recorded_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def email_normalized(self) -> str:
        return normalize_email(self.email)


@dataclass(frozen=True)
class Campaign:
    name: str
    subject_template: str
    body_template: str
    status: str = "active"
    daily_send_quota: int = 25
    allowed_countries: tuple[str, ...] = ("US",)
    kill_switch_active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class SendEvent:
    email: str
    event_type: str
    status: str
    provider: str
    detail: str = ""
    campaign_id: int | None = None
    lead_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class RiskEvent:
    scope: str
    severity: str
    event_type: str
    detail: str
    scope_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class AgentState:
    global_kill_switch: bool = False
    kill_reason: str = ""
    deliverability_status: str = "green"
    last_heartbeat_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class EngineState:
    engine_name: str
    engine_family: str = "non_trading"
    status: str = "idle"
    run_mode: str = "sim"
    kill_switch_active: bool = False
    kill_reason: str = ""
    last_heartbeat_at: str | None = None
    last_event_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class OutboxMessage:
    campaign_id: int
    lead_id: int
    recipient_email: str
    subject: str
    body: str
    from_email: str
    headers: dict[str, str]
    provider: str
    status: str = "queued"
    detail: str = ""
    transport_message_id: str | None = None
    filesystem_path: str | None = None
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def recipient_email_normalized(self) -> str:
        return normalize_email(self.recipient_email)


@dataclass(frozen=True)
class SuppressionEntry:
    email: str
    reason: str
    source: str
    id: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    body: str
    headers: dict[str, str]
    unsubscribe_url: str


@dataclass(frozen=True)
class Account:
    name: str
    domain: str = ""
    industry: str = ""
    website_url: str = ""
    status: str = "researching"
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def domain_normalized(self) -> str:
        return normalize_domain(self.domain)


@dataclass(frozen=True)
class Contact:
    account_id: int
    full_name: str
    email: str = ""
    title: str = ""
    phone: str = ""
    role: str = ""
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def email_normalized(self) -> str:
        return normalize_email(self.email)


@dataclass(frozen=True)
class Opportunity:
    account_id: int
    name: str
    offer_name: str = ""
    stage: str = "research"
    status: str = "open"
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    estimated_value: float = 0.0
    currency: str = "USD"
    next_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class Message:
    account_id: int
    recipient_email: str
    subject: str
    body: str
    opportunity_id: int | None = None
    contact_id: int | None = None
    channel: str = "email"
    direction: str = "outbound"
    status: str = "draft"
    requires_approval: bool = True
    approval_status: str = "pending"
    sender_name: str = ""
    sender_email: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def recipient_email_normalized(self) -> str:
        return normalize_email(self.recipient_email)

    @property
    def sender_email_normalized(self) -> str:
        return normalize_email(self.sender_email)


@dataclass(frozen=True)
class Meeting:
    account_id: int
    scheduled_for: str
    opportunity_id: int | None = None
    contact_id: int | None = None
    status: str = "booked"
    owner: str = ""
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class Proposal:
    account_id: int
    opportunity_id: int
    title: str
    contact_id: int | None = None
    status: str = "draft"
    amount: float = 0.0
    currency: str = "USD"
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class Outcome:
    account_id: int
    opportunity_id: int
    status: str
    proposal_id: int | None = None
    revenue: float = 0.0
    gross_margin: float = 0.0
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    action_type: str
    entity_type: str
    entity_id: str
    summary: str
    status: str = "pending"
    requested_by: str = "system"
    reviewed_by: str = ""
    review_notes: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    reviewed_at: str | None = None


@dataclass(frozen=True)
class TelemetryEvent:
    event_type: str
    entity_type: str
    entity_id: str = ""
    status: str = "recorded"
    payload: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class FirstDollarReadiness:
    """Public-safe readiness contract for the JJ-N first-dollar lane."""

    status: str
    launchable: bool
    paid_orders_seen: int = 0
    paid_revenue_usd: float = 0.0
    first_paid_order_at: str | None = None
    first_dollar_at: str | None = None
    time_to_first_dollar_hours: float | None = None
    checkout_sessions_created: int = 0
    orders_recorded: int = 0
    delivery_artifacts_generated: int = 0
    monitor_runs_completed: int = 0
    expected_net_cash_30d: float = 0.0
    confidence: float = 0.0
    launch_gates: dict[str, bool] = field(default_factory=dict)
    blocking_reasons: tuple[str, ...] = field(default_factory=tuple)
    source_artifacts: dict[str, str] = field(default_factory=dict)
    schema_version: str = "first_dollar_readiness.v1"
    generated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        valid_statuses = {
            "setup_only",
            "launchable",
            "paid_order_seen",
            "first_dollar_observed",
        }
        normalized_status = str(self.status).strip().lower()
        if normalized_status not in valid_statuses:
            raise ValueError(f"Unsupported first-dollar status: {self.status}")
        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "launchable", bool(self.launchable))
        object.__setattr__(self, "paid_orders_seen", max(0, int(self.paid_orders_seen)))
        object.__setattr__(self, "paid_revenue_usd", round(max(0.0, float(self.paid_revenue_usd)), 2))
        object.__setattr__(
            self,
            "checkout_sessions_created",
            max(0, int(self.checkout_sessions_created)),
        )
        object.__setattr__(self, "orders_recorded", max(0, int(self.orders_recorded)))
        object.__setattr__(
            self,
            "delivery_artifacts_generated",
            max(0, int(self.delivery_artifacts_generated)),
        )
        object.__setattr__(
            self,
            "monitor_runs_completed",
            max(0, int(self.monitor_runs_completed)),
        )
        object.__setattr__(
            self,
            "expected_net_cash_30d",
            round(max(0.0, float(self.expected_net_cash_30d)), 2),
        )
        object.__setattr__(
            self,
            "confidence",
            max(0.0, min(1.0, float(self.confidence))),
        )
        object.__setattr__(self, "launch_gates", {str(key): bool(value) for key, value in self.launch_gates.items()})
        object.__setattr__(
            self,
            "blocking_reasons",
            tuple(str(item) for item in self.blocking_reasons if str(item).strip()),
        )
        object.__setattr__(
            self,
            "source_artifacts",
            {
                str(key): str(value)
                for key, value in self.source_artifacts.items()
                if str(key).strip() and value is not None and str(value).strip()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "status": self.status,
            "launchable": self.launchable,
            "paid_orders_seen": self.paid_orders_seen,
            "paid_revenue_usd": self.paid_revenue_usd,
            "first_paid_order_at": self.first_paid_order_at,
            "first_dollar_at": self.first_dollar_at,
            "time_to_first_dollar_hours": self.time_to_first_dollar_hours,
            "checkout_sessions_created": self.checkout_sessions_created,
            "orders_recorded": self.orders_recorded,
            "delivery_artifacts_generated": self.delivery_artifacts_generated,
            "monitor_runs_completed": self.monitor_runs_completed,
            "expected_net_cash_30d": self.expected_net_cash_30d,
            "confidence": self.confidence,
            "launch_gates": dict(self.launch_gates),
            "blocking_reasons": list(self.blocking_reasons),
            "source_artifacts": dict(self.source_artifacts),
        }
