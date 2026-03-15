from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inventory.systems.openclaw.adapter import build_openclaw_benchmark_packet
from nontrading.models import Account, ApprovalRequest, Contact, Lead, Meeting, Message, Opportunity, Outcome, Proposal
from nontrading.revenue_audit.launch_summary import build_launch_summary
from nontrading.store import RevenueStore
from nontrading.telemetry import NonTradingTelemetry
from scripts.generate_nontrading_public_report import (
    build_public_report,
    resolve_optional_input_path,
    write_report,
    write_sidecar_artifacts,
)


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


def _configure_launch_env(monkeypatch, db_path: Path) -> None:
    monkeypatch.setenv("JJ_REVENUE_DB_PATH", str(db_path))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_launch_ready")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_launch_ready")
    monkeypatch.setenv(
        "JJ_N_WEBSITE_GROWTH_AUDIT_SUCCESS_URL",
        "https://elastifund.io/jjn/checkout/success?session_id={CHECKOUT_SESSION_ID}",
    )
    monkeypatch.setenv(
        "JJ_N_WEBSITE_GROWTH_AUDIT_CANCEL_URL",
        "https://elastifund.io/jjn/checkout/cancel",
    )
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", "https://elastifund.io")
    monkeypatch.setenv("JJ_REVENUE_PROVIDER", "sendgrid")
    monkeypatch.setenv("JJ_REVENUE_FROM_NAME", "JJ-N")
    monkeypatch.setenv("JJ_REVENUE_FROM_EMAIL", "ops@elastifund.io")
    monkeypatch.setenv("JJ_REVENUE_SENDER_DOMAIN_VERIFIED", "1")
    monkeypatch.setenv("SENDGRID_API_KEY", "sg_test_launch_ready")


def _seed_launch_ready_manual_close_fixture(store: RevenueStore) -> None:
    lead, _ = store.upsert_lead(
        Lead(
            email="owner@launch-ready-roofing.com",
            company_name="Launch Ready Roofing",
            country_code="US",
            source="manual_csv",
            explicit_opt_in=True,
            metadata={
                "curated_launch_batch": True,
                "website_url": "https://launch-ready-roofing.com",
                "website_findings": "the quote CTA is buried below the fold on mobile",
                "quick_win": "move the quote CTA into the hero and service pages",
            },
        )
    )
    account = store.create_account(
        Account(
            name="Launch Ready Roofing",
            domain="launch-ready-roofing.com",
            website_url="https://launch-ready-roofing.com",
            metadata={"lead_email": lead.email, "country_code": "US"},
        )
    )
    contact = store.create_contact(
        Contact(
            account_id=account.id or 0,
            full_name="Pat Owner",
            email=lead.email,
            role="owner",
            metadata={"country_code": "US"},
        )
    )
    store.create_opportunity(
        Opportunity(
            account_id=account.id or 0,
            name="Website Growth Audit for Launch Ready Roofing",
            offer_name="Website Growth Audit",
            stage="qualified",
            status="open",
            score=88.0,
            estimated_value=1800.0,
            next_action="launch_bridge",
            metadata={
                "contact_id": contact.id or 0,
                "curated_launch_batch": True,
                "website_findings": "the quote CTA is buried below the fold on mobile",
                "quick_win": "move the quote CTA into the hero and service pages",
                "website_url": "https://launch-ready-roofing.com",
            },
        )
    )


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
    assert payload["schema_version"] == "nontrading_public_report.v2"
    assert payload["wedge"]["offer_name"] == "Website Growth Audit"
    assert payload["wedge"]["status"] == "revenue_evidence"
    assert payload["commercial"]["time_to_first_dollar_status"] == "observed"
    assert payload["first_dollar_readiness"]["status"] == "first_dollar_observed"
    assert payload["first_dollar_readiness"]["expected_net_cash_30d"] == 1600.0
    assert payload["first_dollar_scoreboard"]["status"] == "first_dollar_observed"
    assert payload["first_dollar_scoreboard"]["forecast_arr_usd_p50"] == payload["arr_lab"]["summary"]["p50_arr_usd"]
    assert payload["first_dollar_scoreboard"]["recommended_experiment"] == payload["arr_lab"]["recommended_next_experiment"]["experiment_key"]
    assert payload["allocator_input"]["engine_family"] == "revenue_audit"
    assert payload["allocator_input"]["expected_net_cash_30d"] == 1600.0
    assert payload["allocator_input"]["metadata"]["arr_lab"]["forecast_arr_usd_p50"] == payload["arr_lab"]["summary"]["p50_arr_usd"]
    assert payload["arr_lab"]["schema_version"] == "nontrading_arr_lab.v1"
    assert payload["recurring_monitor"]["schema_version"] in {
        "revenue_audit_recurring_monitor.v1",
        "nontrading_recurring_monitor.v1",
    }
    assert payload["comparison_artifact"]["items"][1]["comparison_only"] is True
    assert payload["comparison_artifact"]["items"][1]["excluded_from_allocator"] is True
    assert payload["source_artifacts"]["report_artifact"].endswith("reports/nontrading_public_report.json")
    assert payload["source_artifacts"]["arr_lab_artifact"].endswith("nontrading_arr_lab/latest.json")


def test_generator_builds_launch_summary_from_real_surfaces(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "revenue_agent.db"
    _configure_launch_env(monkeypatch, db_path)
    store = RevenueStore(db_path)
    telemetry = NonTradingTelemetry(store)
    account = store.create_account(Account(name="Launch Ready Co", domain="launch-ready.example"))
    telemetry.account_researched(account, source="fixture", notes="launchable")
    _seed_launch_ready_manual_close_fixture(store)

    report_path = tmp_path / "nontrading_public_report.json"
    launch_summary_path = tmp_path / "nontrading_launch_summary.json"
    launch_checklist_path = tmp_path / "nontrading_launch_operator_checklist.json"
    status_path = tmp_path / "nontrading_first_dollar_status.json"
    allocator_path = tmp_path / "nontrading_allocator_input.json"
    comparison_path = tmp_path / "nontrading_benchmark_comparison.json"
    arr_lab_path = tmp_path / "nontrading_arr_lab" / "latest.json"
    recurring_monitor_path = tmp_path / "nontrading_recurring_monitor" / "latest.json"
    report = build_public_report(
        store,
        report_path=report_path,
        launch_summary_path=launch_summary_path,
        launch_checklist_path=launch_checklist_path,
        status_path=status_path,
        allocator_path=allocator_path,
        comparison_path=comparison_path,
        arr_lab_path=arr_lab_path,
        recurring_monitor_path=recurring_monitor_path,
    )
    write_sidecar_artifacts(
        report,
        launch_summary_path=launch_summary_path,
        launch_checklist_path=launch_checklist_path,
        status_path=status_path,
        allocator_path=allocator_path,
        comparison_path=comparison_path,
        arr_lab_path=arr_lab_path,
        recurring_monitor_path=recurring_monitor_path,
    )

    launch_payload = json.loads(launch_summary_path.read_text(encoding="utf-8"))
    checklist_payload = json.loads(launch_checklist_path.read_text(encoding="utf-8"))

    assert report["launch_summary"]["checkout_ready"] is True
    assert report["launch_summary"]["webhook_ready"] is True
    assert report["launch_summary"]["manual_close_ready"] is True
    assert report["launch_summary"]["fulfillment_ready"] is True
    assert report["launch_summary"]["launchable"] is True
    assert report["first_dollar_readiness"]["status"] == "launchable"
    assert report["first_dollar_readiness"]["launchable"] is True
    assert report["first_dollar_scoreboard"]["live_offer_url"] == "https://elastifund.io/v1/nontrading/offers/website-growth-audit"
    assert report["allocator_input"]["metadata"]["arr_lab"]["recommended_experiment"] == report["arr_lab"]["recommended_next_experiment"]["experiment_key"]
    assert launch_payload["selected_prospects"] == 1
    assert launch_payload["operator_checklist"]["status"] == "ready"
    assert checklist_payload["status"] == "ready"
    assert checklist_payload["source_artifact"] == str(launch_checklist_path)
    assert launch_payload["source_artifact"] == str(launch_summary_path)
    assert arr_lab_path.exists()
    assert recurring_monitor_path.exists()


def test_launch_summary_uses_audit_public_base_url_and_does_not_require_curated_prospects(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "revenue_agent.db"
    _configure_launch_env(monkeypatch, db_path)
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("JJ_N_WEBSITE_GROWTH_AUDIT_PUBLIC_BASE_URL", "https://offers.elastifund.io")
    monkeypatch.setenv(
        "JJ_N_WEBSITE_GROWTH_AUDIT_SUCCESS_URL",
        "https://offers.elastifund.io/nontrading/website-growth-audit/success?session_id={CHECKOUT_SESSION_ID}",
    )
    monkeypatch.setenv(
        "JJ_N_WEBSITE_GROWTH_AUDIT_CANCEL_URL",
        "https://offers.elastifund.io/nontrading/website-growth-audit/cancel",
    )

    summary = build_launch_summary(
        db_path=db_path,
        output_path=tmp_path / "nontrading_launch_summary.json",
        operator_checklist_path=tmp_path / "nontrading_launch_operator_checklist.json",
    )

    assert summary["checkout_ready"] is True
    assert summary["webhook_ready"] is True
    assert summary["manual_close_ready"] is True
    assert summary["launchable"] is True
    assert summary["selected_prospects"] == 0
    assert summary["surface_checks"]["checkout_config"]["public_base_url_ready"] is True
    assert summary["live_offer_url"] == "https://offers.elastifund.io/v1/nontrading/offers/website-growth-audit"
    assert summary["operator_checklist"]["status"] == "ready"
    assert "manual_close_lane_not_ready" not in summary["blocking_reasons"]


def test_generator_derives_launchable_and_paid_order_states_from_launch_inputs(tmp_path: Path) -> None:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    telemetry = NonTradingTelemetry(store)
    account = store.create_account(Account(name="Launch Ready Co", domain="launch.example"))
    launch_summary_path = tmp_path / "nontrading_launch_summary.json"
    launch_checklist_path = tmp_path / "nontrading_launch_operator_checklist.json"
    store.create_opportunity(
        Opportunity(
            account_id=account.id or 0,
            name="Website Growth Audit",
            offer_name="Website Growth Audit",
            stage="qualified",
            status="open",
            score=78.0,
        )
    )
    telemetry.account_researched(account, source="fixture", notes="launchable")

    launchable_report = build_public_report(
        store,
        launch_summary_path=launch_summary_path,
        launch_checklist_path=launch_checklist_path,
        launch_summary={
            "checkout_ready": True,
            "webhook_ready": True,
            "manual_close_ready": True,
            "fulfillment_ready": True,
            "checkout_sessions_created": 3,
            "orders_recorded": 1,
        },
    )

    assert launchable_report["first_dollar_readiness"]["status"] == "launchable"
    assert launchable_report["first_dollar_readiness"]["launchable"] is True
    assert launchable_report["first_dollar_readiness"]["expected_net_cash_30d"] == 315.0
    assert launchable_report["allocator_input"]["compliance_status"] == "pass"

    paid_report = build_public_report(
        store,
        launch_summary_path=launch_summary_path,
        launch_checklist_path=launch_checklist_path,
        launch_summary={
            "checkout_ready": True,
            "webhook_ready": True,
            "manual_close_ready": True,
            "fulfillment_ready": True,
            "checkout_sessions_created": 3,
            "orders_recorded": 1,
            "paid_orders_seen": 1,
            "paid_revenue_usd": 500.0,
            "delivery_artifacts_generated": 1,
        },
        benchmark_payload={
            "status": "comparison_ready",
            "decision_count": "9",
            "cost_usd": "14.5",
            "outcome_value_usd": "42.0",
        },
    )

    status_path = tmp_path / "nontrading_first_dollar_status.json"
    allocator_path = tmp_path / "nontrading_allocator_input.json"
    comparison_path = tmp_path / "nontrading_benchmark_comparison.json"
    write_sidecar_artifacts(
        paid_report,
        launch_summary_path=launch_summary_path,
        status_path=status_path,
        allocator_path=allocator_path,
        comparison_path=comparison_path,
        launch_checklist_path=launch_checklist_path,
    )

    launch_payload = json.loads(launch_summary_path.read_text(encoding="utf-8"))
    checklist_payload = json.loads(launch_checklist_path.read_text(encoding="utf-8"))
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    allocator_payload = json.loads(allocator_path.read_text(encoding="utf-8"))
    comparison_payload = json.loads(comparison_path.read_text(encoding="utf-8"))

    assert paid_report["first_dollar_readiness"]["status"] == "paid_order_seen"
    assert paid_report["first_dollar_readiness"]["paid_orders_seen"] == 1
    assert paid_report["allocator_input"]["metadata"]["arr_lab"]["forecast_confidence"] == paid_report["arr_lab"]["confidence"]["score"]
    assert launch_payload["paid_orders_seen"] == 1
    assert checklist_payload["source_artifact"] == str(launch_checklist_path)
    assert status_payload["status"] == "paid_order_seen"
    assert allocator_payload["revenue_audit"]["metadata"]["first_dollar_status"] == "paid_order_seen"
    assert comparison_payload["items"][1]["comparison_only"] is True
    assert comparison_payload["items"][1]["excluded_from_allocator"] is True
    assert comparison_payload["items"][1]["metrics"]["decision_count"] == 9
    assert comparison_payload["items"][1]["metrics"]["cost_usd"] == 14.5


def test_generator_normalizes_openclaw_evidence_packet_into_comparison_artifact(tmp_path: Path) -> None:
    store = RevenueStore(tmp_path / "revenue_agent.db")
    telemetry = NonTradingTelemetry(store)
    account = store.create_account(Account(name="Benchmark Ready Co", domain="benchmark.example"))
    store.create_opportunity(
        Opportunity(
            account_id=account.id or 0,
            name="Website Growth Audit",
            offer_name="Website Growth Audit",
            stage="qualified",
            status="open",
            score=74.0,
        )
    )
    telemetry.account_researched(account, source="fixture", notes="benchmark bridge")

    packet = build_openclaw_benchmark_packet(
        run_id="openclaw-cycle3-comparison-only",
        diagnostics_events=[
            {"ts": 1_000, "type": "message.processed", "outcome": "completed", "durationMs": 300},
            {"ts": 2_000, "type": "message.processed", "outcome": "completed", "durationMs": 500},
            {"ts": 3_000, "type": "model.usage", "costUsd": 0.08, "durationMs": 420},
        ],
        outcome_comparisons=[
            {
                "case_id": "cta-coverage",
                "elastifund_value": {"issues_found": 3},
                "openclaw_value": {"issues_found": 2},
                "winner": "elastifund",
            }
        ],
        source_artifacts=["tests/fixtures/openclaw/diagnostics.jsonl"],
    )

    report = build_public_report(
        store,
        benchmark_payload=packet.to_dict(),
    )

    benchmark_row = report["comparison_artifact"]["items"][1]

    assert report["comparison_artifact"]["state"] == "comparison_ready"
    assert benchmark_row["status"] == "comparison_ready"
    assert benchmark_row["comparison_mode"] == "comparison_only"
    assert benchmark_row["comparison_only"] is True
    assert benchmark_row["excluded_from_allocator"] is True
    assert benchmark_row["allocator_eligible"] is False
    assert benchmark_row["metrics"]["decision_count"] == 2
    assert benchmark_row["metrics"]["cycle_time_seconds"] == 0.4
    assert benchmark_row["metrics"]["cost_usd"] == 0.08
    assert benchmark_row["isolation"]["wallet_access"] == "none"
    assert benchmark_row["isolation"]["shared_state_access"] == "none"
    assert benchmark_row["metadata"]["comparison_case_count"] == 1
    assert benchmark_row["metadata"]["upstream_commit"]
    assert benchmark_row["notes"][0] == "OpenClaw comparison is isolated and excluded from live allocator decisions."
    assert benchmark_row["source_artifact"] == "tests/fixtures/openclaw/diagnostics.jsonl"


def test_resolve_optional_input_path_uses_existing_fallback(tmp_path: Path) -> None:
    fallback = tmp_path / "openclaw.json"
    fallback.write_text("{}", encoding="utf-8")

    assert resolve_optional_input_path(None, fallback=fallback) == fallback
