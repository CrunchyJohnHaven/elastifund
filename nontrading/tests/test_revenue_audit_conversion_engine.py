from __future__ import annotations

import json

from nontrading.revenue_audit.acquisition_bridge import RevenueAuditAcquisitionBridge
from nontrading.revenue_audit.conversion_engine import (
    CONVERSION_MESSAGE_METADATA_KEY,
    FOLLOW_UP_MESSAGE_STATUS,
    MANUAL_FOLLOW_UP_STATUS,
    RevenueAuditConversionEngine,
    write_conversion_artifacts,
)
from nontrading.revenue_audit.launch_batch import ingest_curated_launch_batch
from nontrading.store import RevenueStore
from scripts.generate_revenue_audit_conversion_packets import main as generate_conversion_packets_main

from .test_revenue_audit_acquisition_bridge import (
    _curated_fetcher_phone_only,
    _write_curated_source,
    make_settings,
    seed_curated_prospect,
)


def test_conversion_engine_stages_proposal_and_follow_up_idempotently(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=True)
    store = RevenueStore(settings.db_path)
    opportunity = seed_curated_prospect(store, company="Acme Roofing", email="owner@acme-roofing.com", score=92.0)
    bridge = RevenueAuditAcquisitionBridge(store, settings).build_artifact()
    engine = RevenueAuditConversionEngine(store, settings)

    summary, packets = engine.build_artifact(bridge)
    repeat_summary, repeat_packets = engine.build_artifact(bridge)

    assert summary.launch_mode == "approval_queue_only"
    assert summary.staged_packets == 1
    assert summary.staged_proposals == 1
    assert summary.staged_follow_ups == 1
    assert summary.live_send_ready == 1
    assert packets[0].proposal["amount_usd"] == 2500.0
    assert packets[0].follow_up["step_number"] == 2
    assert packets[0].follow_up["status"] == FOLLOW_UP_MESSAGE_STATUS
    assert packets[0].operator_next_action == "approve_teaser_then_send"
    assert packets[0].proposal["proposal_id"] == repeat_packets[0].proposal["proposal_id"]
    assert packets[0].follow_up["message_id"] == repeat_packets[0].follow_up["message_id"]
    assert len(store.list_proposals(opportunity_id=opportunity.id or 0)) == 1
    conversion_messages = [
        message
        for message in store.list_messages(opportunity_id=opportunity.id or 0)
        if message.metadata.get(CONVERSION_MESSAGE_METADATA_KEY)
    ]
    assert len(conversion_messages) == 1
    assert repeat_summary.staged_follow_ups == 1


def test_conversion_engine_keeps_phone_only_manual_close_operator_ready(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=False)
    store = RevenueStore(settings.db_path)
    source_path = _write_curated_source(
        tmp_path,
        company="Phone Only Roofing",
        website_url="https://phone-only-gap.test/",
    )
    ingest_curated_launch_batch(
        store,
        source_path=source_path,
        fetcher=_curated_fetcher_phone_only(),
    )
    bridge = RevenueAuditAcquisitionBridge(store, settings).build_artifact()
    engine = RevenueAuditConversionEngine(store, settings)

    summary, packets = engine.build_artifact(bridge, source_bridge_path=source_path)
    summary_path, packet_paths, persisted_summary, persisted_packets = write_conversion_artifacts(
        summary,
        packets,
        summary_output=tmp_path / "reports" / "conversion_summary.json",
        packet_dir=tmp_path / "reports" / "conversion_packets",
    )

    assert summary.launch_mode == "manual_close_only"
    assert summary.staged_proposals == 1
    assert summary.staged_follow_ups == 0
    assert summary.manual_follow_up_only == 1
    assert packets[0].follow_up["status"] == MANUAL_FOLLOW_UP_STATUS
    assert packets[0].live_send_allowed is False
    assert packets[0].operator_next_action == "review_manual_close_packet"
    assert summary_path.exists()
    assert len(packet_paths) == 1
    payload = json.loads(packet_paths[0].read_text(encoding="utf-8"))
    assert payload["follow_up"]["status"] == MANUAL_FOLLOW_UP_STATUS
    assert payload["proposal"]["status"] == "draft"
    assert persisted_summary.packets[0]["packet_path"] == str(packet_paths[0])
    assert persisted_packets[0].packet_path == str(packet_paths[0])


def test_conversion_packets_script_writes_summary_and_packet_files(tmp_path: Path, monkeypatch) -> None:
    settings = make_settings(tmp_path, sender_domain_verified=True)
    store = RevenueStore(settings.db_path)
    seed_curated_prospect(store, company="Script Prospect", email="owner@scriptprospect.com", score=91.0)
    summary_output = tmp_path / "reports" / "conversion_summary.json"
    packet_dir = tmp_path / "reports" / "conversion_packets"

    monkeypatch.setenv("JJ_REVENUE_PROVIDER", settings.provider)
    monkeypatch.setenv("JJ_REVENUE_PUBLIC_BASE_URL", settings.public_base_url)
    monkeypatch.setenv("JJ_REVENUE_FROM_NAME", settings.from_name)
    monkeypatch.setenv("JJ_REVENUE_FROM_EMAIL", settings.from_email)
    monkeypatch.setenv("SENDGRID_API_KEY", settings.sendgrid_api_key or "")
    monkeypatch.setenv("JJ_REVENUE_SENDER_DOMAIN_VERIFIED", "1")

    exit_code = generate_conversion_packets_main(
        [
            "--db-path",
            str(settings.db_path),
            "--summary-output",
            str(summary_output),
            "--packet-dir",
            str(packet_dir),
        ]
    )

    summary_payload = json.loads(summary_output.read_text(encoding="utf-8"))
    packet_files = sorted(packet_dir.glob("*.json"))

    assert exit_code == 0
    assert summary_payload["launch_mode"] == "approval_queue_only"
    assert summary_payload["staged_packets"] == 1
    assert summary_payload["staged_proposals"] == 1
    assert len(packet_files) == 1
    assert summary_payload["packets"][0]["packet_path"] == str(packet_files[0])
