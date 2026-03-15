"""JJ-N CRM schema for the Phase 0 foundations milestone."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

UTC = timezone.utc


def utc_now() -> str:
    """Return a stable UTC timestamp string for emitted events."""

    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _event_payload(instance: Any) -> dict[str, Any]:
    return {key: _serialize(value) for key, value in asdict(instance).items()}


class LeadStatus(Enum):
    RESEARCH = "research"
    QUALIFIED = "qualified"
    OUTREACH = "outreach"
    RESPONDED = "responded"
    MEETING = "meeting"
    PROPOSAL = "proposal"
    WON = "won"
    LOST = "lost"
    DISQUALIFIED = "disqualified"


class ApprovalClass(Enum):
    AUTO = "auto"
    REVIEW = "review"
    ESCALATE = "escalate"


@dataclass
class Lead:
    id: str
    company: str
    contact_name: str
    contact_email: str
    source: str
    status: LeadStatus = LeadStatus.RESEARCH
    fit_score: float = 0.0
    opportunity_score: float = 0.0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "event_type": "lead_update",
            "timestamp": utc_now(),
            **_event_payload(self),
        }


@dataclass
class Contact:
    id: str
    lead_id: str
    full_name: str
    email: str = ""
    title: str = ""
    phone: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "event_type": "contact_update",
            "timestamp": utc_now(),
            **_event_payload(self),
        }


@dataclass
class Opportunity:
    id: str
    lead_id: str
    service_type: str
    estimated_value_usd: float
    time_to_first_dollar_days: int
    gross_margin_pct: float
    automation_fraction: float
    data_exhaust_score: float
    compliance_simplicity: float
    capital_required_usd: float
    sales_cycle_days: int
    composite_score: float = 0.0
    status: str = "research"
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_score(self) -> float:
        """Compute the weighted Phase 0 opportunity score."""

        self.composite_score = round(
            (25.0 / max(self.time_to_first_dollar_days, 1))
            + (max(min(self.gross_margin_pct, 1.0), 0.0) * 20.0)
            + (max(min(self.automation_fraction, 1.0), 0.0) * 20.0)
            + (max(min(self.data_exhaust_score, 1.0), 0.0) * 15.0)
            + (max(min(self.compliance_simplicity, 1.0), 0.0) * 10.0)
            + (5.0 / max(self.capital_required_usd, 1.0))
            + (5.0 / max(self.sales_cycle_days, 1)),
            4,
        )
        return self.composite_score

    def to_event(self) -> dict[str, Any]:
        return {
            "event_type": "opportunity_scored",
            "timestamp": utc_now(),
            **_event_payload(self),
        }


@dataclass
class Interaction:
    id: str
    lead_id: str
    engine: str
    action: str
    approval_class: ApprovalClass = ApprovalClass.REVIEW
    approved: bool = False
    result: str = ""
    timestamp: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "event_type": "interaction",
            **_event_payload(self),
        }
