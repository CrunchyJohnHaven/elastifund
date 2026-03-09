from __future__ import annotations

from nontrading.crm_schema import (
    ApprovalClass,
    Contact,
    Interaction,
    Lead,
    LeadStatus,
    Opportunity,
)


def make_lead(lead_id: str = "lead-1") -> Lead:
    return Lead(
        id=lead_id,
        company="Acme Builders",
        contact_name="Pat Jones",
        contact_email="pat@acme.example",
        source="manual_list",
    )


def make_opportunity(opportunity_id: str = "opp-1") -> Opportunity:
    return Opportunity(
        id=opportunity_id,
        lead_id="lead-1",
        service_type="estimate_automation",
        estimated_value_usd=2500.0,
        time_to_first_dollar_days=7,
        gross_margin_pct=0.6,
        automation_fraction=0.5,
        data_exhaust_score=0.8,
        compliance_simplicity=0.9,
        capital_required_usd=2.0,
        sales_cycle_days=10,
    )


def test_lead_defaults_to_research_status() -> None:
    lead = make_lead()

    assert lead.status is LeadStatus.RESEARCH


def test_lead_event_serializes_status_value() -> None:
    lead = make_lead()

    event = lead.to_event()

    assert event["event_type"] == "lead_update"
    assert event["status"] == "research"
    assert event["company"] == "Acme Builders"


def test_contact_event_contains_linked_lead() -> None:
    contact = Contact(id="contact-1", lead_id="lead-1", full_name="Pat Jones", email="pat@acme.example")

    event = contact.to_event()

    assert event["event_type"] == "contact_update"
    assert event["lead_id"] == "lead-1"


def test_opportunity_compute_score_sets_composite_score() -> None:
    opportunity = make_opportunity()

    score = opportunity.compute_score()

    assert score == opportunity.composite_score
    assert score > 0.0


def test_opportunity_event_includes_computed_score() -> None:
    opportunity = make_opportunity()
    opportunity.compute_score()

    event = opportunity.to_event()

    assert event["event_type"] == "opportunity_scored"
    assert event["composite_score"] == opportunity.composite_score


def test_interaction_event_serializes_approval_class() -> None:
    interaction = Interaction(
        id="interaction-1",
        lead_id="lead-1",
        engine="proposal",
        action="draft_proposal",
        approval_class=ApprovalClass.ESCALATE,
    )

    event = interaction.to_event()

    assert event["event_type"] == "interaction"
    assert event["approval_class"] == "escalate"


def test_interaction_defaults_to_review() -> None:
    interaction = Interaction(id="interaction-2", lead_id="lead-1", engine="outreach", action="draft_outreach")

    assert interaction.approval_class is ApprovalClass.REVIEW


def test_list_defaults_are_not_shared_across_leads() -> None:
    first = make_lead("lead-a")
    second = make_lead("lead-b")

    first.tags.append("priority")

    assert second.tags == []
