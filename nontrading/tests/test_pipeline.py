from __future__ import annotations

import json
from pathlib import Path

import pytest

from nontrading.config import RevenueAgentSettings
from nontrading.importers.csv_import import import_csv
from nontrading.main import RuntimeSafetyError, build_runtime, main, run_daemon
from nontrading.models import Lead
from nontrading.store import RevenueStore


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "sample_leads.csv"


def make_settings(tmp_path: Path, *, loop_seconds: int = 7) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        public_base_url="https://example.invalid",
        from_name="JJ-N",
        from_email="ops@elastifund.io",
        postal_address="100 Main Street, Austin, TX 78701",
        default_campaign_name="jjn-pipeline",
        loop_seconds=loop_seconds,
    )


def seed_pipeline_leads(store: RevenueStore) -> None:
    store.upsert_lead(
        Lead(
            email="owner@optedin-us.com",
            company_name="Opted In US",
            country_code="US",
            source="manual_csv",
            explicit_opt_in=True,
        )
    )
    store.upsert_lead(
        Lead(
            email="founder@gmail.com",
            company_name="Personal Gmail",
            country_code="US",
            source="manual_csv",
            explicit_opt_in=False,
        )
    )
    store.upsert_lead(
        Lead(
            email="sales@suppressed.example",
            company_name="Suppressed Co",
            country_code="US",
            source="manual_csv",
            explicit_opt_in=False,
        )
    )
    store.append_suppression("sales@suppressed.example", reason="manual_test", source="pytest")


def test_pipeline_run_cycle_processes_full_dry_run(tmp_path: Path, monkeypatch) -> None:
    cycle_report_path = tmp_path / "reports" / "website_growth_audit_cycle_reports.jsonl"
    monkeypatch.setenv("JJ_NONTRADING_CYCLE_REPORT_PATH", str(cycle_report_path))
    settings = make_settings(tmp_path)
    store, pipeline = build_runtime(settings, dry_run=True)
    seed_pipeline_leads(store)

    report = pipeline.run_cycle()
    snapshot = store.status_snapshot()
    events = {event.event_type for event in store.list_telemetry_events()}

    assert report.status == "completed"
    assert report.scanned_leads == 3
    assert report.suppressed_leads == 1
    assert report.accounts_researched == 2
    assert report.qualified_accounts == 1
    assert report.outreach_approved == 1
    assert report.outreach_blocked == 0
    assert report.outreach_sent == 1
    assert report.replies_recorded == 1
    assert report.meetings_booked == 1
    assert report.proposals_sent == 1
    assert report.fulfillment_planned == 1
    assert report.outcomes_recorded == 1
    assert report.offer_slug == "website-growth-audit"
    assert report.funnel_stage_counts is not None
    assert report.persisted_report_path == str(cycle_report_path)
    assert snapshot["accounts"] == 2
    assert snapshot["crm_opportunities"] == 2
    assert len(store.list_outbox_messages()) == 1
    opportunities = store.list_opportunities()
    assert any("fulfillment" in dict(item.metadata) for item in opportunities if item.status != "research_only")
    assert cycle_report_path.exists()
    payloads = [json.loads(line) for line in cycle_report_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert payloads[-1]["fulfillment_planned"] == 1
    assert payloads[-1]["outreach_approved"] == 1
    assert {
        "account_researched",
        "message_sent",
        "reply_received",
        "meeting_booked",
        "proposal_sent",
        "outcome_recorded",
        "cycle_complete",
    }.issubset(events)


def test_pipeline_honors_kill_switch_before_processing(tmp_path: Path, monkeypatch) -> None:
    cycle_report_path = tmp_path / "reports" / "blocked_cycle_reports.jsonl"
    monkeypatch.setenv("JJ_NONTRADING_CYCLE_REPORT_PATH", str(cycle_report_path))
    settings = make_settings(tmp_path)
    store, pipeline = build_runtime(settings, dry_run=True)
    seed_pipeline_leads(store)
    store.set_engine_kill_switch("revenue_pipeline", True, "manual_pause")

    report = pipeline.run_cycle()

    assert report.status == "blocked"
    assert report.reason == "engine_kill_switch"
    assert report.blocked_stage == "revenue_pipeline"
    assert report.persisted_report_path == str(cycle_report_path)
    assert cycle_report_path.exists()
    assert store.list_accounts() == []


def test_run_daemon_respects_interval(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, loop_seconds=13)
    store, pipeline = build_runtime(settings, dry_run=True)
    sleep_calls: list[int] = []

    run_daemon(
        store,
        pipeline,
        settings,
        sleep_fn=lambda seconds: sleep_calls.append(seconds),
        max_cycles=2,
    )

    assert sleep_calls == [13]


def test_main_run_once_dry_run_prints_cycle_report(tmp_path: Path, capsys) -> None:
    settings = make_settings(tmp_path)
    import_csv(FIXTURE_PATH, RevenueStore(settings.db_path))

    exit_code = main(
        [
            "--run-once",
            "--dry-run",
            "--db-path",
            str(settings.db_path),
            "--import-csv",
            str(FIXTURE_PATH),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "revenue-pipeline status" in captured.out
    assert "status=completed" in captured.out


def test_build_runtime_blocks_live_provider_with_placeholder_sender_domain(tmp_path: Path) -> None:
    settings = RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        provider="sendgrid",
        sendgrid_api_key="test-key",
        from_email="ops@example.invalid",
    )

    with pytest.raises(RuntimeSafetyError) as exc:
        build_runtime(settings, dry_run=False)
    assert "placeholder or unverified" in str(exc.value)


def test_build_runtime_blocks_live_provider_without_verified_sender_flag(tmp_path: Path) -> None:
    settings = RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        provider="sendgrid",
        sendgrid_api_key="test-key",
        from_email="ops@elastifund.io",
    )

    with pytest.raises(RuntimeSafetyError) as exc:
        build_runtime(settings, dry_run=False)
    assert "JJ_REVENUE_SENDER_DOMAIN_VERIFIED" in str(exc.value)


def test_build_runtime_allows_dry_run_with_placeholder_sender_domain(tmp_path: Path) -> None:
    settings = RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        from_email="ops@example.invalid",
    )
    store, pipeline = build_runtime(settings, dry_run=True)

    assert store is not None
    assert pipeline.run_mode == "sim"
