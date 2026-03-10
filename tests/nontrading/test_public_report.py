from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nontrading.models import Account, ApprovalRequest, Meeting, Message, Opportunity, Outcome, Proposal
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry
from scripts.generate_nontrading_public_report import build_public_report, write_report


def _seed_public_report_fixture(tmp_path: Path) -> RevenueStore:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    telemetry = NonTradingTelemetry(store)

    account = store.create_account(Account(name="Acme Builders", domain="acme.example"))
    opportunity = store.create_opportunity(
        Opportunity(account_id=account.id or 0, name="Website Growth Audit", offer_name="Website Growth Audit", stage="qualified", status="open", score=82.5)
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
        )
    )
    meeting = store.create_meeting(
        Meeting(
            account_id=account.id or 0,
            opportunity_id=opportunity.id,
            scheduled_for="2026-03-10T14:00:00+00:00",
            owner="john",
            status="booked",
        )
    )
    proposal = store.create_proposal(
        Proposal(
            account_id=account.id or 0,
            opportunity_id=opportunity.id or 0,
            title="Website Growth Audit",
            amount=2500.0,
            status="sent",
        )
    )
    outcome = store.create_outcome(
        Outcome(
            account_id=account.id or 0,
            opportunity_id=opportunity.id or 0,
            proposal_id=proposal.id,
            status="won",
            revenue=2500.0,
            gross_margin=1600.0,
            metadata={"fulfillment_status": "delivery_pending"},
        )
    )
    request = store.create_approval_request(
        ApprovalRequest(
            action_type="outreach_message",
            entity_type="message",
            entity_id=str(outbound.id or 0),
            summary="Approve outreach",
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
    return store


def test_public_report_snapshot_exposes_claim_safe_metrics(tmp_path: Path) -> None:
    store = _seed_public_report_fixture(tmp_path)

    snapshot = store.public_report_snapshot()

    assert snapshot["funnel"]["researched_accounts"] == 1
    assert snapshot["funnel"]["qualified_accounts"] == 1
    assert snapshot["funnel"]["delivered_messages"] == 1
    assert snapshot["funnel"]["reply_rate"] == 1.0
    assert snapshot["commercial"]["revenue_won_usd"] == 2500.0
    assert snapshot["commercial"]["gross_margin_usd"] == 1600.0
    assert snapshot["commercial"]["gross_margin_pct"] == 0.64
    assert snapshot["approval"]["approved_requests"] == 1
    assert snapshot["approval"]["decisions_recorded"] == 1
    assert snapshot["fulfillment"]["events_recorded"] == 1
    assert snapshot["phase"]["claim_status"] == "actual_revenue_recorded"


def test_generator_writes_public_safe_report_artifact(tmp_path: Path) -> None:
    store = _seed_public_report_fixture(tmp_path)

    report = build_public_report(store)
    output_path = tmp_path / "nontrading_public_report.json"
    write_report(report, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["headline"]["title"] == "JJ-N Website Growth Audit"
    assert payload["wedge"]["offer_name"] == "Website Growth Audit"
    assert payload["wedge"]["status"] == "revenue_evidence"
    assert payload["commercial"]["time_to_first_dollar_status"] == "observed"
    assert payload["source_artifacts"]["report_artifact"].endswith("reports/nontrading_public_report.json")
