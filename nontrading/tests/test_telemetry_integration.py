from __future__ import annotations

import json
from pathlib import Path

from nontrading.models import Account, ApprovalRequest, Meeting, Message, Opportunity, Outcome, Proposal
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry, TelemetryBridge


EXPECTED_EVENT_ALIASES = {
    "account_researched": "jjn.account.researched",
    "approval_decision": "jjn.approval.decision",
    "cycle_complete": "jjn.cycle.complete",
    "fulfillment_status_changed": "jjn.fulfillment.status.changed",
    "message_sent": "jjn.outreach.sent",
    "reply_received": "jjn.interaction.reply_received",
    "meeting_booked": "jjn.interaction.meeting_booked",
    "proposal_sent": "jjn.proposal.sent",
    "outcome_recorded": "jjn.outcome.recorded",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _emit_phase0_events(tmp_path: Path) -> tuple[RevenueStore, NonTradingTelemetry, TelemetryBridge]:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    telemetry = NonTradingTelemetry(store)
    bridge = TelemetryBridge(output_path=tmp_path / "events.jsonl")

    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    opportunity = store.create_opportunity(
        Opportunity(account_id=account.id or 0, name="Website Growth Audit", score=82.5)
    )
    outbound = store.create_message(
        Message(
            account_id=account.id or 0,
            opportunity_id=opportunity.id,
            recipient_email="pat@acme.example",
            subject="Audit intro",
            body="We found a few clear growth gaps.",
            status="sent",
            approval_status="approved",
        )
    )
    inbound = store.create_message(
        Message(
            account_id=account.id or 0,
            opportunity_id=opportunity.id,
            recipient_email="pat@acme.example",
            subject="Re: Audit intro",
            body="Interested. Let's talk.",
            direction="inbound",
            status="received",
            requires_approval=False,
            approval_status="not_required",
            sender_name="Pat Jones",
            sender_email="pat@acme.example",
        )
    )
    meeting = store.create_meeting(
        Meeting(
            account_id=account.id or 0,
            opportunity_id=opportunity.id,
            scheduled_for="2026-03-10T14:00:00+00:00",
            owner="john",
        )
    )
    proposal = store.create_proposal(
        Proposal(
            account_id=account.id or 0,
            opportunity_id=opportunity.id or 0,
            title="Website Growth Audit",
            amount=1500.0,
            status="sent",
        )
    )
    outcome = store.create_outcome(
        Outcome(
            account_id=account.id or 0,
            opportunity_id=opportunity.id or 0,
            proposal_id=proposal.id,
            status="won",
            revenue=1500.0,
            gross_margin=900.0,
            metadata={"fulfillment_status": "delivery_pending"},
        )
    )
    request = store.create_approval_request(
        ApprovalRequest(
            action_type="outreach_message",
            entity_type="message",
            entity_id=str(outbound.id or 0),
            summary="Approve outreach to pat@acme.example",
            requested_by="fixture",
        )
    )
    store.update_approval_request_status(request.id or 0, status="approved", reviewed_by="john")

    telemetry.account_researched(account, source="fixture", notes="High-fit SMB")
    telemetry.message_sent(outbound)
    telemetry.reply_received(inbound)
    telemetry.meeting_booked(meeting)
    telemetry.proposal_sent(proposal)
    telemetry.outcome_recorded(outcome)
    telemetry.cycle_completed(
        {
            "cycle_id": "cycle-fixture",
            "started_at": "2026-03-09T00:00:00+00:00",
            "completed_at": "2026-03-09T00:15:00+00:00",
            "status": "completed",
            "accounts_researched": 1,
            "qualified_accounts": 1,
            "outreach_attempted": 1,
            "outreach_sent": 1,
            "approval_pending": 0,
            "replies_recorded": 1,
            "meetings_booked": 1,
            "proposals_sent": 1,
            "outcomes_recorded": 1,
        }
    )
    return store, telemetry, bridge


def test_phase0_telemetry_exports_dashboard_ready_ecs_documents(tmp_path: Path) -> None:
    store, telemetry, bridge = _emit_phase0_events(tmp_path)
    template = json.loads(
        (_repo_root() / "infra" / "index_templates" / "elastifund-nontrading-events.json").read_text(
            encoding="utf-8"
        )
    )
    properties = template["template"]["mappings"]["properties"]

    events = store.list_telemetry_events()
    exported = [bridge.emit(telemetry.build_document(event)) for event in events]
    persisted = bridge.read_all()

    assert len(events) == len(EXPECTED_EVENT_ALIASES)
    assert persisted == exported
    assert {row["event"]["action"] for row in persisted} == set(EXPECTED_EVENT_ALIASES)

    labels_properties = properties["labels"]["properties"]
    elastifund_properties = properties["elastifund"]["properties"]
    assert labels_properties["engine"]["type"] == "keyword"
    assert labels_properties["pipeline_stage"]["type"] == "keyword"
    assert elastifund_properties["event_alias"]["type"] == "keyword"
    assert elastifund_properties["pipeline_stage"]["type"] == "keyword"

    for document in persisted:
        action = document["event"]["action"]
        assert TelemetryBridge.is_ecs_compatible(document)
        assert document["event"]["dataset"] == "elastifund.nontrading"
        assert document["labels"]["engine"]
        assert document["labels"]["pipeline_stage"]
        assert document["elastifund"]["event_type"] == action
        assert document["elastifund"]["event_alias"] == EXPECTED_EVENT_ALIASES[action]
        for field_name in ("@timestamp", "ecs", "event", "service", "labels", "entity", "payload", "elastifund"):
            assert field_name in document
            assert field_name in properties or field_name == "@timestamp"


def test_nontrading_dashboard_asset_is_valid_ndjson() -> None:
    dashboard_path = _repo_root() / "infra" / "kibana_dashboards" / "nontrading-revenue-funnel.ndjson"
    lines = [json.loads(line) for line in dashboard_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(lines) == 6
    assert sum(1 for row in lines if row["type"] == "visualization") == 5
    dashboard = next(row for row in lines if row["type"] == "dashboard")
    titles = {row["attributes"]["title"] for row in lines}

    assert "JJ-N Revenue Funnel" in titles
    assert "JJ-N Approval And Fulfillment Coverage" in titles
    assert dashboard["attributes"]["title"] == "JJ-N Non-Trading Revenue Funnel"
    assert "event.dataset : \\\"elastifund.nontrading\\\"" in dashboard["attributes"]["kibanaSavedObjectMeta"]["searchSourceJSON"]
    assert len(dashboard["references"]) == 5

    funnel_markdown = next(
        row["attributes"]["visState"]
        for row in lines
        if row["attributes"]["title"] == "JJ-N Revenue Funnel"
    )
    assert "account_researched" in funnel_markdown
    assert "message_sent" in funnel_markdown
    assert "approval_decision" in funnel_markdown
    assert "fulfillment_status_changed" in funnel_markdown
    assert "cycle_complete" in funnel_markdown
