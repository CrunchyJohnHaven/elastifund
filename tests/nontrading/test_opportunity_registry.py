from __future__ import annotations

from nontrading.crm_schema import Lead, LeadStatus, Opportunity
from nontrading.models import Account, Opportunity as StoredOpportunity
from nontrading.opportunity_registry import OpportunityRegistry, OpportunityScoreInput
from nontrading.store import RevenueStore


def make_lead() -> Lead:
    return Lead(
        id="lead-1",
        company="Acme Builders",
        contact_name="Pat Jones",
        contact_email="pat@acme.example",
        source="manual_list",
    )


def make_opportunity(opportunity_id: str, *, days: int = 7, value: float = 2500.0) -> Opportunity:
    return Opportunity(
        id=opportunity_id,
        lead_id="lead-1",
        service_type="estimate_automation",
        estimated_value_usd=value,
        time_to_first_dollar_days=days,
        gross_margin_pct=0.6,
        automation_fraction=0.5,
        data_exhaust_score=0.8,
        compliance_simplicity=0.9,
        capital_required_usd=2.0,
        sales_cycle_days=10,
    )


def make_store(tmp_path) -> RevenueStore:
    return RevenueStore(tmp_path / "revenue_agent.db")


def test_add_lead_stores_record() -> None:
    registry = OpportunityRegistry()
    lead = make_lead()

    stored = registry.add_lead(lead)

    assert stored is lead
    assert registry.get_lead("lead-1") is lead


def test_get_lead_returns_none_for_unknown_id() -> None:
    registry = OpportunityRegistry()

    assert registry.get_lead("missing") is None


def test_add_opportunity_computes_score_and_logs_event() -> None:
    registry = OpportunityRegistry()

    opportunity = registry.add_opportunity(make_opportunity("opp-1"))

    assert opportunity.composite_score > 0.0
    assert registry.events[-1]["event_type"] == "opportunity_scored"


def test_rank_opportunities_orders_highest_score_first() -> None:
    registry = OpportunityRegistry()
    registry.add_opportunity(make_opportunity("slow", days=30))
    registry.add_opportunity(make_opportunity("fast", days=2))
    registry.add_opportunity(make_opportunity("mid", days=10))

    ranked = registry.rank_opportunities()

    assert [opportunity.id for opportunity in ranked] == ["fast", "mid", "slow"]


def test_update_lead_status_mutates_lead_and_logs_event() -> None:
    registry = OpportunityRegistry()
    lead = registry.add_lead(make_lead())

    updated = registry.update_lead_status(lead.id, LeadStatus.OUTREACH)

    assert updated is lead
    assert updated.status is LeadStatus.OUTREACH
    assert registry.events[-1]["status"] == "outreach"


def test_update_missing_lead_returns_none() -> None:
    registry = OpportunityRegistry()

    assert registry.update_lead_status("missing", LeadStatus.LOST) is None


def test_flush_events_returns_snapshot_and_clears_buffer() -> None:
    registry = OpportunityRegistry()
    registry.add_lead(make_lead())
    registry.add_opportunity(make_opportunity("opp-1"))

    events = registry.flush_events()

    assert len(events) == 2
    assert registry.events == []


def test_weighted_score_api_still_returns_phase0_assessment() -> None:
    registry = OpportunityRegistry()

    assessment = registry.score(
        OpportunityScoreInput(
            time_to_first_dollar=0.9,
            gross_margin=0.8,
            automation_fraction=0.7,
            data_exhaust=0.6,
            compliance_simplicity=0.95,
            capital_required=0.85,
            sales_cycle_length=0.75,
        )
    )

    assert assessment.total_score == 79.0
    assert assessment.decision == "advance"


def test_apply_preserves_existing_store_model_shape() -> None:
    registry = OpportunityRegistry()
    stored = StoredOpportunity(account_id=1, name="Construction outreach")

    scored = registry.apply(
        stored,
        OpportunityScoreInput(
            time_to_first_dollar=0.9,
            gross_margin=0.8,
            automation_fraction=0.7,
            data_exhaust=0.6,
            compliance_simplicity=0.95,
            capital_required=0.85,
            sales_cycle_length=0.75,
        ),
    )

    assert scored.score == 79.0
    assert scored.metadata["registry_decision"] == "advance"


def test_registry_round_trip_persists_leads_and_opportunities(tmp_path) -> None:
    store = make_store(tmp_path)
    first = OpportunityRegistry(store=store)
    lead = first.add_lead(make_lead())
    opportunity = first.add_opportunity(make_opportunity("opp-1"))

    second = OpportunityRegistry(store=store)
    reloaded_lead = second.get_lead(lead.id)
    ranked = second.rank_opportunities()

    assert reloaded_lead is not None
    assert reloaded_lead.company == "Acme Builders"
    assert ranked[0].id == opportunity.id
    assert ranked[0].composite_score == opportunity.composite_score


def test_registry_ranking_reads_persisted_store_order_after_reload(tmp_path) -> None:
    store = make_store(tmp_path)
    registry = OpportunityRegistry(store=store)
    registry.add_lead(make_lead())
    registry.add_opportunity(make_opportunity("slow", days=30))
    registry.add_opportunity(make_opportunity("fast", days=2))
    registry.add_opportunity(make_opportunity("mid", days=10))

    reloaded = OpportunityRegistry(store=store)

    assert [opportunity.id for opportunity in reloaded.rank_opportunities()] == ["fast", "mid", "slow"]


def test_apply_persists_to_store_when_registry_is_store_backed(tmp_path) -> None:
    store = make_store(tmp_path)
    registry = OpportunityRegistry(store=store)
    account = store.create_account(Account(name="Acme Builders"))
    stored = store.create_opportunity(StoredOpportunity(account_id=account.id or 0, name="Construction outreach"))

    scored = registry.apply(
        stored,
        OpportunityScoreInput(
            time_to_first_dollar=0.9,
            gross_margin=0.8,
            automation_fraction=0.7,
            data_exhaust=0.6,
            compliance_simplicity=0.95,
            capital_required=0.85,
            sales_cycle_length=0.75,
        ),
    )

    persisted = store.get_opportunity(scored.id or 0)
    assert persisted is not None
    assert persisted.score == 79.0
    assert persisted.metadata["registry_decision"] == "advance"
