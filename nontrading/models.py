"""Shared dataclasses for the non-trading revenue agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_email(email: str) -> str:
    return email.strip().lower()


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

