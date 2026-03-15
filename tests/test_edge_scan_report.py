from __future__ import annotations

from datetime import timedelta

import pytest

import bot.edge_scan_report as edge_scan_report
from bot.edge_scan_report import (
    AGGRESSIVE_THRESHOLDS,
    CURRENT_THRESHOLDS,
    WIDE_OPEN_THRESHOLDS,
    _recommend_action,
    _required_llm_probabilities,
    fetch_recent_open_markets,
    inverse_platt_probability,
)
from bot.jj_live import calibrate_probability_with_params


def test_inverse_platt_probability_round_trips_with_calibration():
    raw = inverse_platt_probability(0.71, 0.5914, -0.3977)
    calibrated = calibrate_probability_with_params(raw, 0.5914, -0.3977)

    assert calibrated == pytest.approx(0.71, abs=1e-6)


def test_required_probability_windows_expand_under_aggressive_thresholds():
    current = _required_llm_probabilities(
        yes_price=0.90,
        thresholds=CURRENT_THRESHOLDS,
        a=0.5914,
        b=-0.3977,
    )
    aggressive = _required_llm_probabilities(
        yes_price=0.90,
        thresholds=AGGRESSIVE_THRESHOLDS,
        a=0.5914,
        b=-0.3977,
    )

    assert current["required_llm_prob_yes"] is None
    assert aggressive["required_llm_prob_yes"] is not None
    assert current["in_price_window"] is True
    assert aggressive["in_price_window"] is True


def test_required_probability_windows_expand_under_wide_open_thresholds():
    aggressive = _required_llm_probabilities(
        yes_price=0.92,
        thresholds=AGGRESSIVE_THRESHOLDS,
        a=0.5914,
        b=-0.3977,
    )
    wide_open = _required_llm_probabilities(
        yes_price=0.92,
        thresholds=WIDE_OPEN_THRESHOLDS,
        a=0.5914,
        b=-0.3977,
    )

    assert aggressive["required_llm_prob_yes"] is None
    assert wide_open["required_llm_prob_yes"] is not None
    assert wide_open["in_price_window"] is True


def test_recommend_action_requires_human_review_when_service_is_running_and_blocked():
    action, restart_recommended, reason = _recommend_action(
        restart_gate={
            "restart_ready": False,
            "service_status": "running",
            "blocked_reasons": ["remote_service_running_while_launch_blocked"],
        },
        viable_current=0,
        viable_aggressive=2,
        candidate_notes=["Conflicting live directions on a fast market."],
    )

    assert action == "human_review_required"
    assert restart_recommended is False
    assert "Service is already running" in reason


def test_recommend_action_recalibrates_when_nothing_is_viable_even_wide_open():
    action, restart_recommended, reason = _recommend_action(
        restart_gate={
            "restart_ready": True,
            "service_status": "stopped",
            "blocked_reasons": [],
        },
        viable_current=0,
        viable_aggressive=0,
        viable_wide_open=0,
        candidate_notes=[],
    )

    assert action == "recalibrate"
    assert restart_recommended is False
    assert "Platt parameters may be stale" in reason


@pytest.mark.asyncio
async def test_fetch_recent_open_markets_skips_hydration_failures(monkeypatch):
    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_recent_trades(client, *, limit=1000):
        return [
            {"title": "Bitcoin Up or Down - March 10, 1:00PM-1:05PM ET (5m)", "conditionId": "ok"},
            {"title": "Bitcoin Up or Down - March 10, 1:00PM-1:15PM ET (15m)", "conditionId": "timeout"},
        ]

    async def fake_fetch_market(client, condition_id):
        if condition_id == "timeout":
            raise edge_scan_report.httpx.ConnectTimeout("boom")
        return {
            "conditionId": condition_id,
            "endDate": (edge_scan_report._now_utc() + timedelta(hours=1)).isoformat(),
            "closed": False,
            "acceptingOrders": True,
        }

    monkeypatch.setattr(edge_scan_report.httpx, "AsyncClient", DummyAsyncClient)
    monkeypatch.setattr(edge_scan_report, "_fetch_recent_trades", fake_recent_trades)
    monkeypatch.setattr(edge_scan_report, "_fetch_market_by_condition_id", fake_fetch_market)

    markets, trades, scan_health = await fetch_recent_open_markets(max_markets=2)

    assert len(markets) == 1
    assert len(trades) == 2
    assert scan_health["recent_market_hydrations"] == 1
    assert scan_health["recent_market_hydration_failures"] == 1
    assert scan_health["recent_fast_markets_seen"] == 2
