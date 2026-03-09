from __future__ import annotations

from pathlib import Path

from nontrading.campaigns.sequences import (
    WEBSITE_GROWTH_AUDIT_SEQUENCE,
    SequenceRunner,
    SequenceState,
)
from nontrading.campaigns.template_selector import TemplateSelector
from nontrading.config import RevenueAgentSettings
from nontrading.email.sender import DryRunSender
from nontrading.models import Campaign, Lead
from nontrading.offers.website_growth_audit import WEBSITE_GROWTH_AUDIT
from nontrading.store import RevenueStore


def make_settings(tmp_path: Path) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        public_base_url="https://example.invalid",
        postal_address="100 Main Street, Austin, TX 78701",
    )


def make_sequence_lead() -> Lead:
    return Lead(
        email="owner@bluepeak.example.com",
        company_name="Blue Peak Plumbing",
        country_code="US",
        source="manual_csv",
        explicit_opt_in=True,
        metadata={
            "first_name": "Jordan",
            "industry": "home_services",
            "role": "owner",
            "company_size": "11-50",
            "website_findings": "the emergency plumbing page buries the phone number below images",
            "competitor_name": "Rapid Rooter",
            "competitor_gap": "Rapid Rooter has dedicated service pages for each city while your location coverage is bundled onto one page",
            "quick_win": "promoting the emergency phone number in the first mobile viewport",
        },
    )


def test_follow_up_sequence_respects_timing_rotation_and_terminal_action(tmp_path: Path) -> None:
    selector = TemplateSelector(make_settings(tmp_path))
    lead = make_sequence_lead()
    state = SequenceState()

    first_step = WEBSITE_GROWTH_AUDIT_SEQUENCE.next_step(
        lead,
        WEBSITE_GROWTH_AUDIT,
        selector,
        days_since_start=0,
        state=state,
    )
    assert first_step is not None

    state = state.advance(first_step.angle)
    assert (
        WEBSITE_GROWTH_AUDIT_SEQUENCE.next_step(
            lead,
            WEBSITE_GROWTH_AUDIT,
            selector,
            days_since_start=1,
            state=state,
        )
        is None
    )

    second_step = WEBSITE_GROWTH_AUDIT_SEQUENCE.next_step(
        lead,
        WEBSITE_GROWTH_AUDIT,
        selector,
        days_since_start=3,
        state=state,
    )
    assert second_step is not None
    assert second_step.angle != first_step.angle

    state = state.advance(second_step.angle)
    third_step = WEBSITE_GROWTH_AUDIT_SEQUENCE.next_step(
        lead,
        WEBSITE_GROWTH_AUDIT,
        selector,
        days_since_start=7,
        state=state,
    )
    assert third_step is not None
    assert third_step.angle not in state.sent_angles

    final_state = state.advance(third_step.angle)
    assert WEBSITE_GROWTH_AUDIT_SEQUENCE.terminal_action(days_since_start=8, state=final_state) == "nurture"
    assert WEBSITE_GROWTH_AUDIT_SEQUENCE.terminal_action(
        days_since_start=8,
        state=SequenceState(unsubscribed=True),
    ) == "suppress"


def test_dry_run_sender_processes_full_three_message_sequence(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = RevenueStore(settings.db_path)
    selector = TemplateSelector(settings)
    sender = DryRunSender(settings, store)
    runner = SequenceRunner(store, sender, settings, selector=selector)
    lead, _ = store.upsert_lead(make_sequence_lead())
    campaign = store.create_campaign(
        Campaign(
            name="website-growth-audit-sequence",
            subject_template="unused",
            body_template="unused",
            daily_send_quota=10,
            allowed_countries=settings.allowed_countries,
            metadata={"offer_slug": WEBSITE_GROWTH_AUDIT.slug},
        )
    )

    state = SequenceState()
    deliveries = []
    for day in (0, 3, 7):
        result = runner.send_due_step(
            lead,
            WEBSITE_GROWTH_AUDIT,
            campaign,
            days_since_start=day,
            state=state,
        )
        assert result is not None
        assert result.delivery.status == "dry_run"
        deliveries.append(result)
        state = result.next_state

    stored_messages = store.list_outbox_messages(campaign_id=campaign.id or 0)
    assert len(deliveries) == 3
    assert len(stored_messages) == 3
    assert len({delivery.planned_step.angle for delivery in deliveries}) == 3
    assert all(message.status == "dry_run" for message in stored_messages)
