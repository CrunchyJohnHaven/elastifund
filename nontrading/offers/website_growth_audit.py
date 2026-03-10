"""First concrete JJ-N service offer: Website Growth Audit."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


@dataclass(frozen=True)
class ServiceOffer:
    name: str
    slug: str
    description: str
    price_range: tuple[int, int]
    delivery_days: int
    ideal_customer_profile: Mapping[str, Any]
    fulfillment_type: str
    scoring_criteria: Mapping[str, Any]
    funnel_stages: tuple[str, ...] = field(
        default_factory=lambda: (
            "intake",
            "approval",
            "outreach",
            "meeting",
            "proposal",
            "fulfillment",
            "outcome",
        )
    )
    fulfillment_provisioning: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        slug = "-".join(part for part in str(self.slug).strip().lower().replace("_", "-").split("-") if part)
        description = str(self.description).strip()
        low_price, high_price = self.price_range
        delivery_days = int(self.delivery_days)
        fulfillment_type = str(self.fulfillment_type).strip().lower()

        if not name:
            raise ValueError("offer name is required")
        if not slug:
            raise ValueError("offer slug is required")
        if low_price <= 0 or high_price < low_price:
            raise ValueError("price_range must be a positive ascending pair")
        if delivery_days <= 0:
            raise ValueError("delivery_days must be positive")
        if fulfillment_type not in {"expert_led", "automated", "hybrid"}:
            raise ValueError("fulfillment_type must be expert_led, automated, or hybrid")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "slug", slug)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "price_range", (int(low_price), int(high_price)))
        object.__setattr__(self, "delivery_days", delivery_days)
        object.__setattr__(self, "ideal_customer_profile", _freeze_value(dict(self.ideal_customer_profile)))
        object.__setattr__(self, "fulfillment_type", fulfillment_type)
        object.__setattr__(self, "scoring_criteria", _freeze_value(dict(self.scoring_criteria)))
        object.__setattr__(
            self,
            "funnel_stages",
            tuple(str(stage).strip().lower() for stage in self.funnel_stages if str(stage).strip()),
        )
        object.__setattr__(self, "fulfillment_provisioning", _freeze_value(dict(self.fulfillment_provisioning)))


WEBSITE_GROWTH_AUDIT = ServiceOffer(
    name="Website Growth Audit",
    slug="website-growth-audit",
    description=(
        "A five-day expert-led website audit for SMBs with clear search, conversion, "
        "and competitor-gap findings, packaged into a prioritized action plan."
    ),
    price_range=(500, 2500),
    delivery_days=5,
    ideal_customer_profile={
        "industries": (
            "construction",
            "home_services",
            "field_services",
            "professional_services",
            "local_services",
        ),
        "revenue_range_usd": (500_000, 25_000_000),
        "company_size": ("2-10", "11-50", "51-200"),
        "signals": (
            "slow_mobile_pages",
            "weak_local_seo",
            "missing_service_page_ctas",
            "unclear_primary_offer",
            "competitor_gap",
        ),
    },
    fulfillment_type="hybrid",
    scoring_criteria={
        "time_to_first_dollar": 0.25,
        "gross_margin": 0.20,
        "automation_fraction": 0.20,
        "data_exhaust": 0.15,
        "compliance_simplicity": 0.10,
        "capital_required": 0.05,
        "sales_cycle_length": 0.05,
    },
    fulfillment_provisioning={
        "workspace": "pending",
        "data_intake": "pending",
        "audit_brief": "pending",
        "delivery_packet": "pending",
    },
)


def website_growth_audit_offer() -> ServiceOffer:
    return WEBSITE_GROWTH_AUDIT
