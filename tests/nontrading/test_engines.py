from __future__ import annotations

import pytest

from nontrading.crm_schema import ApprovalClass, Lead, Opportunity
from nontrading.engines import (
    AccountIntelligenceEngine,
    InteractionEngine,
    LearningEngine,
    OutreachEngine,
    ProposalEngine,
)


def make_lead() -> Lead:
    return Lead(
        id="lead-1",
        company="Acme Builders",
        contact_name="Pat Jones",
        contact_email="pat@acme.example",
        source="manual_list",
    )


def make_opportunity() -> Opportunity:
    return Opportunity(
        id="opp-1",
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


@pytest.mark.parametrize(
    ("engine", "payload", "engine_name"),
    [
        (AccountIntelligenceEngine(), make_lead(), "account_intelligence"),
        (OutreachEngine(), make_lead(), "outreach"),
        (InteractionEngine(), make_lead(), "interaction"),
        (ProposalEngine(), make_opportunity(), "proposal"),
        (LearningEngine(), make_opportunity(), "learning"),
    ],
)
def test_engine_process_returns_interaction(engine: object, payload: object, engine_name: str) -> None:
    interaction = engine.process(payload)

    assert interaction.engine == engine_name
    assert interaction.id


@pytest.mark.parametrize(
    ("engine", "payload", "approval_class"),
    [
        (AccountIntelligenceEngine(), make_lead(), ApprovalClass.AUTO),
        (OutreachEngine(), make_lead(), ApprovalClass.REVIEW),
        (InteractionEngine(), make_lead(), ApprovalClass.REVIEW),
        (ProposalEngine(), make_opportunity(), ApprovalClass.ESCALATE),
        (LearningEngine(), make_opportunity(), ApprovalClass.AUTO),
    ],
)
def test_engine_to_event_returns_valid_interaction_event(
    engine: object,
    payload: object,
    approval_class: ApprovalClass,
) -> None:
    interaction = engine.process(payload)

    event = engine.to_event(interaction)

    assert event["event_type"] == "interaction"
    assert event["approval_class"] == approval_class.value
