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
