"""Angle selection and rendering for the Website Growth Audit outreach offer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nontrading.config import RevenueAgentSettings
from nontrading.email.render import render_file_email_template
from nontrading.email.validate import validate_outbox_message
from nontrading.models import Lead, OutboxMessage, RenderedEmail
from nontrading.offers.website_growth_audit import ServiceOffer

ANGLE_1 = "angle_1_growth_opportunity"
ANGLE_2 = "angle_2_competitor_benchmark"
ANGLE_3 = "angle_3_quick_win"
ANGLE_ORDER = (ANGLE_1, ANGLE_2, ANGLE_3)
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "email" / "templates"
ANGLE_TEMPLATE_MAP = {
    ANGLE_1: TEMPLATE_DIR / "angle_1_growth_opportunity.txt",
    ANGLE_2: TEMPLATE_DIR / "angle_2_competitor_benchmark.txt",
    ANGLE_3: TEMPLATE_DIR / "angle_3_quick_win.txt",
}


def _first_present(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                token = str(item).strip()
                if token:
                    return token
        token = str(value or "").strip()
        if token:
            return token
    return ""


def _as_lower_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_company_size(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.lower()


def _derive_first_name(lead: Lead) -> str:
    metadata = dict(lead.metadata)
    explicit = _first_present(metadata, "first_name")
    if explicit:
        return explicit
    contact_name = _first_present(metadata, "contact_name", "full_name")
    if contact_name:
        return contact_name.split()[0]
    localpart = lead.email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
    token = localpart.split()[0] if localpart else "there"
    return token.capitalize()


@dataclass(frozen=True)
class TemplateSelection:
    angle: str
    template_name: str
    rendered_email: RenderedEmail
    preview_message: OutboxMessage
    context: dict[str, str]


class TemplateSelector:
    def __init__(self, settings: RevenueAgentSettings):
        self.settings = settings

    def select_angle(self, lead: Lead, offer: ServiceOffer) -> str:
        metadata = dict(lead.metadata)
        industry = _as_lower_text(metadata.get("industry"))
        role = _as_lower_text(metadata.get("role"))
        company_size = _normalize_company_size(metadata.get("company_size"))
        icp_industries = tuple(
            _as_lower_text(value) for value in offer.ideal_customer_profile.get("industries", ())
        )
        has_competitor_data = bool(_first_present(metadata, "competitor_name", "competitor_gap", "competitor_finding"))
        has_website_data = bool(
            _first_present(
                metadata,
                "website_findings",
                "specific_finding",
                "website_url",
                "seo_issue",
                "conversion_issue",
            )
        )
        owner_led = role in {"owner", "founder", "ceo", "president"}
        small_team = any(token in company_size for token in ("2-10", "11-50", "1-10", "small"))
        icp_match = not icp_industries or industry in icp_industries

        if has_competitor_data and (icp_match or owner_led or "marketing" in role or "growth" in role):
            return ANGLE_2
        if has_website_data:
            return ANGLE_1
        if owner_led or small_team:
            return ANGLE_3
        return ANGLE_1

    def angle_options(self, lead: Lead, offer: ServiceOffer, *, used_angles: tuple[str, ...] = ()) -> tuple[str, ...]:
        primary = self.select_angle(lead, offer)
        used = set(used_angles)
        ordered = [primary]
        ordered.extend(angle for angle in ANGLE_ORDER if angle not in ordered)
        return tuple(angle for angle in ordered if angle not in used)

    def select(
        self,
        lead: Lead,
        offer: ServiceOffer,
        *,
        preferred_angle: str | None = None,
        campaign_name: str | None = None,
    ) -> TemplateSelection:
        angle = preferred_angle if preferred_angle in ANGLE_TEMPLATE_MAP else self.select_angle(lead, offer)
        template_path = ANGLE_TEMPLATE_MAP[angle]
        context = self._build_context(lead, offer, angle)
        rendered = render_file_email_template(
            template_path,
            context,
            self.settings,
            campaign_name=campaign_name or offer.slug,
        )
        preview_message = OutboxMessage(
            campaign_id=0,
            lead_id=lead.id or 0,
            recipient_email=lead.email,
            subject=rendered.subject,
            body=rendered.body,
            from_email=self.settings.from_email,
            headers=rendered.headers,
            provider="template_preview",
        )
        validate_outbox_message(preview_message, self.settings.postal_address)
        return TemplateSelection(
            angle=angle,
            template_name=template_path.name,
            rendered_email=rendered,
            preview_message=preview_message,
            context=context,
        )

    def _build_context(self, lead: Lead, offer: ServiceOffer, angle: str) -> dict[str, str]:
        metadata = dict(lead.metadata)
        company = lead.company_name or lead.email.split("@", 1)[-1]
        specific_finding = self._specific_finding(metadata, angle)
        competitor_name = _first_present(metadata, "competitor_name") or "a nearby competitor"
        price_range = f"${offer.price_range[0]:,}-${offer.price_range[1]:,}"
        return {
            "company": company,
            "competitor_name": competitor_name,
            "delivery_days": str(offer.delivery_days),
            "email": lead.email,
            "first_name": _derive_first_name(lead),
            "offer_name": offer.name,
            "price_range": price_range,
            "specific_finding": specific_finding,
        }

    def _specific_finding(self, metadata: dict[str, Any], angle: str) -> str:
        if angle == ANGLE_2:
            return (
                _first_present(metadata, "competitor_gap", "competitor_finding", "specific_finding")
                or "a stronger service-page and local-search footprint than yours"
            )
        if angle == ANGLE_3:
            return (
                _first_present(metadata, "quick_win", "specific_finding", "website_findings")
                or "the main call to action is hard to find on mobile"
            )
        return (
            _first_present(metadata, "website_findings", "specific_finding", "seo_issue", "conversion_issue")
            or "high-intent pages are missing a clear next step"
        )
