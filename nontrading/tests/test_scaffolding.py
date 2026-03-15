from __future__ import annotations

import sqlite3
from pathlib import Path

from nontrading.config import RevenueAgentSettings
from nontrading.risk import RevenueRiskManager
from nontrading.store import RevenueStore


def make_settings(tmp_path: Path) -> RevenueAgentSettings:
    return RevenueAgentSettings(
        db_path=tmp_path / "revenue_agent.db",
        outbox_dir=tmp_path / "outbox",
        public_base_url="https://example.invalid",
    )


def test_store_initializes_schema_and_default_campaign(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = RevenueStore(settings.db_path)
    store.ensure_default_campaign(settings)

    with sqlite3.connect(settings.db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert {
        "agent_state",
        "engine_states",
        "campaigns",
        "leads",
        "suppression_list",
        "outbox_messages",
        "send_events",
        "risk_events",
    }.issubset(tables)

    snapshot = store.status_snapshot()
    assert snapshot["campaigns"] == 1
    assert snapshot["engine_states"] == 0
    assert snapshot["db_path"] == str(settings.db_path)


def test_risk_manager_obeys_global_and_campaign_kill_switches(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = RevenueStore(settings.db_path)
    campaign = store.ensure_default_campaign(settings)
    risk = RevenueRiskManager(store, settings)

    initial = risk.evaluate_campaign(campaign)
    assert initial.allowed

    store.set_global_kill_switch(True, "test-global-kill")
    blocked = risk.evaluate_campaign(campaign)
    assert not blocked.allowed
    assert blocked.reason == "global_kill_switch"

    store.set_global_kill_switch(False, "")
    store.set_campaign_kill_switch(campaign.id or 0, True, "test-campaign-kill")
    updated_campaign = store.get_campaign(campaign.id or 0)
    assert updated_campaign is not None
    blocked_campaign = risk.evaluate_campaign(updated_campaign)
    assert not blocked_campaign.allowed
    assert blocked_campaign.reason == "campaign_kill_switch"


def test_engine_kill_switch_blocks_specific_engine(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = RevenueStore(settings.db_path)
    campaign = store.ensure_default_campaign(settings)
    risk = RevenueRiskManager(store, settings)

    store.set_engine_kill_switch("outbound_followup", True, "manual_engine_pause")

    blocked = risk.evaluate_campaign(campaign, engine_name="outbound_followup")
    assert not blocked.allowed
    assert blocked.reason == "engine_kill_switch"

    engine_state = store.get_engine_state("outbound_followup")
    assert engine_state is not None
    assert engine_state.kill_switch_active is True
    assert engine_state.kill_reason == "manual_engine_pause"
