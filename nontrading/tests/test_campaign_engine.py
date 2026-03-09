from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from nontrading.campaigns.engine import CampaignEngine
from nontrading.config import RevenueAgentSettings
from nontrading.email.sender import DryRunSender
from nontrading.importers.csv_import import import_csv
from nontrading.models import Campaign
from nontrading.risk import RevenueRiskManager
from nontrading.store import RevenueStore


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "sample_leads.csv"


def make_settings(tmp_path: Path, daily_send_quota: int = 10) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        public_base_url="https://example.invalid",
        postal_address="100 Main Street, Austin, TX 78701",
        daily_send_quota=daily_send_quota,
    )


def bootstrap_engine(tmp_path: Path, daily_send_quota: int = 10) -> tuple[RevenueAgentSettings, RevenueStore, CampaignEngine]:
    settings = make_settings(tmp_path, daily_send_quota=daily_send_quota)
    store = RevenueStore(settings.db_path)
    import_csv(FIXTURE_PATH, store)
    store.ensure_default_campaign(settings)
    sender = DryRunSender(settings, store)
    risk = RevenueRiskManager(store, settings)
    return settings, store, CampaignEngine(store, risk, sender, settings)


def test_campaign_engine_only_sends_us_role_based_or_opted_in_recipients(tmp_path: Path) -> None:
    _, store, engine = bootstrap_engine(tmp_path)

    summary = engine.run_once()
    recipients = {
        message.recipient_email
        for message in store.list_outbox_messages()
        if message.status == "dry_run"
    }

    assert recipients == {
        "info@usbiz.com",
        "sales@vendor.example.com",
        "owner@optedin-us.com",
    }
    assert summary.sent == 3
    assert summary.filtered == 3
    engine_state = store.get_engine_state("outbound_followup")
    assert engine_state is not None
    assert engine_state.status == "idle"
    assert engine_state.run_mode == "sim"


def test_global_kill_switch_stops_all_sends_immediately(tmp_path: Path) -> None:
    _, store, engine = bootstrap_engine(tmp_path)
    store.set_global_kill_switch(True, "manual_stop")

    summary = engine.run_once()

    assert summary.blocked_campaigns == 1
    assert summary.sent == 0
    assert store.list_outbox_messages() == []


def test_unsubscribe_event_appends_suppression_and_blocks_followup_campaign(tmp_path: Path) -> None:
    settings, store, engine = bootstrap_engine(tmp_path, daily_send_quota=1)
    first_summary = engine.run_once()
    assert first_summary.sent == 1

    sent_messages = store.list_outbox_messages()
    first_message = sent_messages[0]
    store.record_unsubscribe(
        email=first_message.recipient_email,
        campaign_id=first_message.campaign_id,
        lead_id=first_message.lead_id,
    )
    assert store.is_suppressed(first_message.recipient_email)

    store.set_campaign_kill_switch(first_message.campaign_id, True, "pause_original_campaign")
    follow_up = store.create_campaign(
        Campaign(
            name="follow-up-campaign",
            subject_template="Follow up for {company_name}",
            body_template="Checking whether {company_name} wants routed leads.",
            daily_send_quota=10,
            allowed_countries=settings.allowed_countries,
        )
    )
    updated_settings = replace(settings, daily_send_quota=10)
    follow_up_engine = CampaignEngine(
        store,
        RevenueRiskManager(store, updated_settings),
        DryRunSender(updated_settings, store),
        updated_settings,
    )
    second_summary = follow_up_engine.run_once()

    follow_up_recipients = {
        message.recipient_email
        for message in store.list_outbox_messages(campaign_id=follow_up.id or 0)
        if message.status == "dry_run"
    }

    assert first_message.recipient_email not in follow_up_recipients
    assert follow_up_recipients == {"info@usbiz.com", "sales@vendor.example.com"}
    assert second_summary.sent == 2


def test_daily_quota_limits_campaign_sends(tmp_path: Path) -> None:
    _, store, engine = bootstrap_engine(tmp_path, daily_send_quota=1)

    summary = engine.run_once()

    assert summary.sent == 1
    assert summary.deferred == 2
    assert len(store.list_outbox_messages()) == 1
