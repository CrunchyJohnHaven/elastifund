"""Website Growth Audit funnel helpers used by the JJ-N pipeline."""

from __future__ import annotations

from typing import Any

from nontrading.models import utc_now

WEBSITE_GROWTH_AUDIT_STEPS: tuple[str, ...] = (
    "intake",
    "approval",
    "outreach",
    "meeting",
    "proposal",
    "fulfillment",
    "outcome",
)


def fulfillment_placeholder(
    *,
    opportunity_id: int,
    proposal_id: int,
    simulated: bool,
) -> dict[str, Any]:
    """Return a stable, explicit fulfillment/provisioning placeholder payload."""
    return {
        "offer_slug": "website-growth-audit",
        "opportunity_id": int(opportunity_id),
        "proposal_id": int(proposal_id),
        "status": "planned",
        "provisioning": {
            "workspace": "pending",
            "data_intake": "pending",
            "audit_brief": "pending",
            "delivery_packet": "pending",
        },
        "checklist": [
            {"step": "intake_confirmed", "status": "pending"},
            {"step": "analytics_access_requested", "status": "pending"},
            {"step": "competitor_set_locked", "status": "pending"},
            {"step": "report_outline_created", "status": "pending"},
            {"step": "delivery_review_scheduled", "status": "pending"},
        ],
        "simulated": bool(simulated),
        "created_at": utc_now(),
    }
