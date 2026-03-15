from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nontrading.campaigns.template_selector import ANGLE_1, ANGLE_2, ANGLE_3, TemplateSelector
from nontrading.config import RevenueAgentSettings
from nontrading.email.validate import validate_outbox_message
from nontrading.models import Lead
from nontrading.offers.website_growth_audit import ServiceOffer, WEBSITE_GROWTH_AUDIT


def make_settings(tmp_path: Path) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        public_base_url="https://example.invalid",
        postal_address="100 Main Street, Austin, TX 78701",
    )


def test_service_offer_is_frozen_and_nested_mappings_are_immutable() -> None:
    offer = ServiceOffer(
        name=" Website Growth Audit ",
        slug="Website_Growth_Audit",
        description=" Test offer ",
        price_range=(500, 2500),
        delivery_days=5,
        ideal_customer_profile={"industries": ["construction"], "signals": ["weak_local_seo"]},
        fulfillment_type="hybrid",
        scoring_criteria={"time_to_first_dollar": 0.25},
    )

    assert offer.slug == "website-growth-audit"
    with pytest.raises(FrozenInstanceError):
        offer.name = "Changed"
    with pytest.raises(TypeError):
        offer.ideal_customer_profile["industries"] = ("roofing",)
    assert offer.funnel_stages[0] == "intake"
    assert offer.funnel_stages[-1] == "outcome"


def test_template_selector_prefers_growth_angle_for_leads_with_website_data(tmp_path: Path) -> None:
    selector = TemplateSelector(make_settings(tmp_path))
    lead = Lead(
        email="owner@greenhammer.example.com",
        company_name="GreenHammer Roofing",
        country_code="US",
        source="manual_csv",
        explicit_opt_in=True,
        metadata={
            "first_name": "Pat",
            "industry": "construction",
            "role": "owner",
            "company_size": "11-50",
            "website_findings": "three service pages bury the quote request CTA below the fold",
        },
    )

    selection = selector.select(lead, WEBSITE_GROWTH_AUDIT)

    assert selection.angle == ANGLE_1
    assert "GreenHammer Roofing" in selection.rendered_email.subject
    assert "Pat" in selection.rendered_email.body


def test_template_selector_prefers_competitor_angle_when_competitor_gap_exists(tmp_path: Path) -> None:
    selector = TemplateSelector(make_settings(tmp_path))
    lead = Lead(
        email="growth@ridgefield.example.com",
        company_name="Ridgefield HVAC",
        country_code="US",
        source="manual_csv",
        explicit_opt_in=True,
        metadata={
            "first_name": "Morgan",
            "industry": "home_services",
            "role": "growth manager",
            "company_size": "11-50",
            "competitor_name": "Peak Comfort",
            "competitor_gap": "Peak Comfort has dedicated landing pages for every core service while your highest-intent traffic lands on a generic home page",
        },
    )

    selection = selector.select(lead, WEBSITE_GROWTH_AUDIT)

    assert selection.angle == ANGLE_2
    assert "Peak Comfort" in selection.rendered_email.body


@pytest.mark.parametrize("angle", [ANGLE_1, ANGLE_2, ANGLE_3])
def test_rendered_templates_pass_can_spam_validation(tmp_path: Path, angle: str) -> None:
    settings = make_settings(tmp_path)
    selector = TemplateSelector(settings)
    lead = Lead(
        email="team@northshore.example.com",
        company_name="Northshore Decks",
        country_code="US",
        source="manual_csv",
        explicit_opt_in=True,
        metadata={
            "first_name": "Alex",
            "industry": "construction",
            "role": "owner",
            "company_size": "2-10",
            "website_findings": "the mobile hero banner hides the main estimate button",
            "competitor_name": "Harbor Build",
            "competitor_gap": "Harbor Build ranks ahead of you for deck repair and inspection queries",
            "quick_win": "moving the estimate CTA into the first screen on mobile",
        },
    )

    selection = selector.select(lead, WEBSITE_GROWTH_AUDIT, preferred_angle=angle)

    assert settings.postal_address in selection.rendered_email.body
    assert selection.rendered_email.unsubscribe_url in selection.rendered_email.body
    validate_outbox_message(selection.preview_message, settings.postal_address)
