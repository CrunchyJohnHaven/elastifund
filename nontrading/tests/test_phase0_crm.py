from __future__ import annotations

import sqlite3
from pathlib import Path

from nontrading.approval import ApprovalGate
from nontrading.compliance import ComplianceGuard
from nontrading.engines import (
    AccountIntelligenceEngine,
    InteractionEngine,
    LearningEngine,
    OutreachEngine,
    ProposalEngine,
)
from nontrading.models import Account, Contact, Meeting, Message, Opportunity, Outcome, Proposal
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry


def make_runtime(tmp_path: Path) -> dict[str, object]:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    telemetry = NonTradingTelemetry(store)
    approval = ApprovalGate(store, paper_mode=True)
    compliance = ComplianceGuard(
        store,
        verified_domains={"elastifund.io"},
        daily_message_limit=5,
    )
    return {
        "store": store,
        "telemetry": telemetry,
        "approval": approval,
        "compliance": compliance,
        "account_engine": AccountIntelligenceEngine(store, telemetry),
        "outreach_engine": OutreachEngine(store, approval, compliance, telemetry),
        "interaction_engine": InteractionEngine(store, telemetry),
        "proposal_engine": ProposalEngine(store, telemetry),
        "learning_engine": LearningEngine(store, telemetry),
    }


def test_store_initializes_phase0_tables(tmp_path: Path) -> None:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    with sqlite3.connect(store.db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert {
        "accounts",
        "contacts",
        "crm_opportunities",
        "crm_messages",
        "crm_meetings",
        "crm_proposals",
        "crm_outcomes",
        "approval_requests",
        "telemetry_events",
    }.issubset(tables)


def test_account_and_contact_crud_round_trip(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = runtime["store"]
    assert isinstance(store, RevenueStore)
    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    contact = store.create_contact(
        Contact(account_id=account.id or 0, full_name="Pat Jones", email="pat@acme.example", title="Owner")
    )

    assert store.get_account(account.id or 0) is not None
    assert store.get_contact(contact.id or 0) is not None
    assert store.list_contacts(account_id=account.id or 0)[0].email == "pat@acme.example"


def test_opportunity_message_meeting_proposal_and_outcome_crud(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = runtime["store"]
    assert isinstance(store, RevenueStore)
    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    opportunity = store.create_opportunity(
        Opportunity(account_id=account.id or 0, name="Roofing estimate automation", score=82.5)
    )
    message = store.create_message(
        Message(
            account_id=account.id or 0,
            opportunity_id=opportunity.id,
            recipient_email="pat@acme.example",
            subject="Intro",
            body="Hello",
        )
    )
    meeting = store.create_meeting(Meeting(account_id=account.id or 0, opportunity_id=opportunity.id, scheduled_for="2026-03-10T14:00:00+00:00"))
    proposal = store.create_proposal(
        Proposal(account_id=account.id or 0, opportunity_id=opportunity.id or 0, title="Pilot", amount=1500.0)
    )
    outcome = store.create_outcome(
        Outcome(account_id=account.id or 0, opportunity_id=opportunity.id or 0, proposal_id=proposal.id, status="won", revenue=1500.0, gross_margin=900.0)
    )

    assert store.get_opportunity(opportunity.id or 0) is not None
    assert store.get_message(message.id or 0) is not None
    assert store.get_meeting(meeting.id or 0) is not None
    assert store.get_proposal(proposal.id or 0) is not None
    assert store.get_outcome(outcome.id or 0) is not None


def test_account_intelligence_emits_account_researched_event(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    account_engine = runtime["account_engine"]
    store = runtime["store"]
    assert isinstance(account_engine, AccountIntelligenceEngine)
    assert isinstance(store, RevenueStore)

    result = account_engine.research_account(
        Account(name="Acme Builders", domain="acme.example"),
        source="manual_list",
        notes="High-ticket fit",
    )

    events = store.list_telemetry_events("account_researched")
    assert result.account.status == "researched"
    assert len(events) == 1
    assert events[0].payload["source"] == "manual_list"


def test_outreach_engine_blocks_send_until_approved(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = runtime["store"]
    outreach_engine = runtime["outreach_engine"]
    assert isinstance(store, RevenueStore)
    assert isinstance(outreach_engine, OutreachEngine)
    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    message = outreach_engine.stage_message(
        Message(
            account_id=account.id or 0,
            recipient_email="pat@acme.example",
            subject="Pilot intro",
            body="Want a faster estimate workflow?",
        )
    )

    result = outreach_engine.request_send(
        message.id or 0,
        sender_name="JJ-N",
        sender_email="ops@elastifund.io",
    )

    assert not result.allowed
    assert result.reason == "approval_required"
    assert result.message.status == "pending_approval"
    assert store.list_approval_requests(status="pending")


def test_outreach_engine_sends_after_approval(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = runtime["store"]
    outreach_engine = runtime["outreach_engine"]
    approval = runtime["approval"]
    assert isinstance(store, RevenueStore)
    assert isinstance(outreach_engine, OutreachEngine)
    assert isinstance(approval, ApprovalGate)
    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    message = outreach_engine.stage_message(
        Message(
            account_id=account.id or 0,
            recipient_email="pat@acme.example",
            subject="Pilot intro",
            body="Want a faster estimate workflow?",
        )
    )
    first = outreach_engine.request_send(
        message.id or 0,
        sender_name="JJ-N",
        sender_email="ops@elastifund.io",
    )
    assert first.approval.request is not None
    approval.approve(first.approval.request.id or 0, reviewed_by="john")

    second = outreach_engine.request_send(
        message.id or 0,
        sender_name="JJ-N",
        sender_email="ops@elastifund.io",
    )

    events = store.list_telemetry_events("message_sent")
    assert second.allowed
    assert second.message.status == "sent"
    assert len(events) == 1


def test_interaction_engine_records_reply_and_meeting(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = runtime["store"]
    interaction_engine = runtime["interaction_engine"]
    assert isinstance(store, RevenueStore)
    assert isinstance(interaction_engine, InteractionEngine)
    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    outbound = store.create_message(
        Message(
            account_id=account.id or 0,
            recipient_email="pat@acme.example",
            subject="Pilot intro",
            body="Want a faster estimate workflow?",
            status="sent",
            approval_status="approved",
            requires_approval=True,
        )
    )
    reply = interaction_engine.record_reply(
        Message(
            account_id=account.id or 0,
            opportunity_id=None,
            contact_id=None,
            recipient_email="pat@acme.example",
            subject=f"Re: {outbound.subject}",
            body="Yes, let's talk.",
            sender_name="Pat Jones",
            sender_email="pat@acme.example",
        )
    )
    meeting = interaction_engine.book_meeting(
        Meeting(account_id=account.id or 0, scheduled_for="2026-03-10T14:00:00+00:00", owner="john")
    )

    assert reply.record_id is not None
    assert meeting.record_id is not None
    assert len(store.list_telemetry_events("reply_received")) == 1
    assert len(store.list_telemetry_events("meeting_booked")) == 1


def test_proposal_and_learning_engines_emit_events(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = runtime["store"]
    proposal_engine = runtime["proposal_engine"]
    learning_engine = runtime["learning_engine"]
    assert isinstance(store, RevenueStore)
    assert isinstance(proposal_engine, ProposalEngine)
    assert isinstance(learning_engine, LearningEngine)
    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    opportunity = store.create_opportunity(Opportunity(account_id=account.id or 0, name="Pilot"))

    proposal_result = proposal_engine.send_proposal(
        Proposal(account_id=account.id or 0, opportunity_id=opportunity.id or 0, title="Pilot proposal", amount=2500.0)
    )
    outcome_result = learning_engine.record_outcome(
        Outcome(
            account_id=account.id or 0,
            opportunity_id=opportunity.id or 0,
            proposal_id=proposal_result.proposal_id,
            status="won",
            revenue=2500.0,
            gross_margin=1600.0,
        )
    )

    assert proposal_result.proposal_id is not None
    assert outcome_result.outcome_id is not None
    assert len(store.list_telemetry_events("proposal_sent")) == 1
    assert len(store.list_telemetry_events("outcome_recorded")) == 1


def test_telemetry_documents_are_elastic_ready(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = runtime["store"]
    telemetry = runtime["telemetry"]
    account_engine = runtime["account_engine"]
    assert isinstance(store, RevenueStore)
    assert isinstance(telemetry, NonTradingTelemetry)
    assert isinstance(account_engine, AccountIntelligenceEngine)

    account_engine.research_account(Account(name="Acme Builders", domain="acme.example"), source="manual")
    event = store.list_telemetry_events("account_researched")[0]
    document = telemetry.build_document(event)

    assert document["event"]["category"] == "nontrading"
    assert document["elastifund"]["worker_name"] == "jj-n"
    assert document["payload"]["environment"] == "paper"
