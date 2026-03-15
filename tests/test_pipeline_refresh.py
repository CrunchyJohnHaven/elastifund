from __future__ import annotations

import math

import pytest

from src.pipeline_refresh import (
    build_category_snapshot,
    build_refresh_payload,
    build_threshold_summary,
    classify_category,
    filter_basic_markets,
    inverse_platt_probability,
    required_probability_window,
)


def test_classify_category_prefers_tag_map_before_keyword_fallback() -> None:
    tags = [{"slug": "finance"}, {"slug": "crypto"}]
    assert classify_category(tags, "Kraken IPO in 2025?") == "crypto"


def test_required_probability_window_expands_yes_reachability_under_lower_thresholds() -> None:
    current = required_probability_window(
        yes_price=0.90,
        yes_threshold=0.15,
        no_threshold=0.05,
        platt_a=0.5914,
        platt_b=-0.3977,
    )
    aggressive = required_probability_window(
        yes_price=0.90,
        yes_threshold=0.08,
        no_threshold=0.03,
        platt_a=0.5914,
        platt_b=-0.3977,
    )

    assert current["required_raw_prob_yes"] is None
    assert aggressive["required_raw_prob_yes"] is not None
    assert current["max_raw_prob_no"] is not None


def test_inverse_platt_probability_round_trips() -> None:
    raw = inverse_platt_probability(0.71, 0.5914, -0.3977)
    calibrated = 1.0 / (1.0 + math.exp(-(0.5914 * math.log(raw / (1.0 - raw)) - 0.3977)))
    assert calibrated == pytest.approx(0.71, abs=1e-6)


def test_build_threshold_summary_counts_only_eligible_markets() -> None:
    markets = [
        {"question": "A", "category": "politics", "yes_price": 0.82, "resolution_hours": 12.0},
        {"question": "B", "category": "sports", "yes_price": 0.82, "resolution_hours": 12.0},
        {"question": "C", "category": "politics", "yes_price": 0.95, "resolution_hours": 12.0},
        {"question": "D", "category": "politics", "yes_price": 0.35, "resolution_hours": 72.0},
    ]

    summary = build_threshold_summary(
        markets=markets,
        profile_name="current",
        yes_threshold=0.15,
        no_threshold=0.05,
        min_category_priority=1,
        category_priorities={"politics": 3, "sports": 0, "other": 0},
        platt_a=0.5914,
        platt_b=-0.3977,
    )

    assert summary["tradeable"] == 1
    assert summary["yes_reachable_markets"] == 1
    assert summary["no_reachable_markets"] == 1


def test_build_category_snapshot_rolls_counts_into_expected_buckets() -> None:
    snapshot = build_category_snapshot(
        [
            {"category": "politics", "yes_price": 0.4, "resolution_hours": 5.0},
            {"category": "politics", "yes_price": 0.6, "resolution_hours": 30.0},
            {"category": "crypto", "yes_price": 0.5, "resolution_hours": 6.0},
        ]
    )

    assert snapshot["politics"]["count"] == 2
    assert snapshot["politics"]["under_24h"] == 1
    assert snapshot["politics"]["avg_yes_price"] == 0.5
    assert snapshot["crypto"]["count"] == 1


def test_filter_basic_markets_requires_price_window_and_horizon() -> None:
    filtered = filter_basic_markets(
        [
            {"question": "A", "yes_price": 0.40, "resolution_hours": 12.0},
            {"question": "B", "yes_price": 0.95, "resolution_hours": 12.0},
            {"question": "C", "yes_price": 0.40, "resolution_hours": 72.0},
            {"question": "D", "yes_price": 0.10, "resolution_hours": 6.0},
        ]
    )

    assert [item["question"] for item in filtered] == ["A", "D"]


def test_build_refresh_payload_prefers_fast_market_universe_for_threshold_sensitivity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 3, 9, 2, 0, tzinfo=timezone.utc)
    gamma_events = [
        {
            "title": "Test event",
            "tags": [{"slug": "politics"}],
            "markets": [
                {
                    "id": "m1",
                    "question": "Will X happen?",
                    "outcomePrices": "[\"0.40\", \"0.60\"]",
                    "endDate": (now + timedelta(hours=12)).isoformat().replace("+00:00", "Z"),
                    "active": True,
                    "closed": False,
                    "acceptingOrders": True,
                }
            ],
        }
    ]

    monkeypatch.setattr(
        "src.pipeline_refresh.load_current_profile",
        lambda: {
            "yes": 0.15,
            "no": 0.05,
            "min_category_priority": 1,
            "category_priorities": {"politics": 3, "crypto": 0, "other": 0},
        },
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.load_fast_markets",
        lambda _now: [
            {
                "question": "Bitcoin Up or Down - test window",
                "category": "crypto",
                "yes_price": 0.50,
                "resolution_hours": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.load_latest_pipeline_verdict",
        lambda: ("REJECT ALL", "No validated edge.", []),
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.load_a6_scan_summary",
        lambda: {"status": "blocked", "executable": 0},
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.run_a6_live_scan",
        lambda: {"status": "active", "executable": 0, "candidates": 0, "opportunities": [], "stats": {}},
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.load_wallet_flow_status",
        lambda: {"ready": True, "scored_wallets": 80, "status": "ready"},
    )
    monkeypatch.setattr("src.pipeline_refresh.load_system_status", lambda: "stopped")

    payload = build_refresh_payload(now, tmp_path, gamma_events)

    assert payload["threshold_market_source"] == "fast_market_discovery"
    assert payload["fast_markets_pulled"] == 1
    assert payload["threshold_markets_pulled"] == 1
    assert payload["markets_in_price_window"] == 1
    assert payload["threshold_sensitivity"]["current"]["tradeable"] == 0
    assert payload["threshold_sensitivity"]["aggressive"]["tradeable"] == 1
    assert "Fast-market discovery surfaced 1 BTC markets" in payload["reasoning"]


def test_build_refresh_payload_falls_back_to_gamma_universe_for_threshold_sensitivity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 3, 9, 2, 0, tzinfo=timezone.utc)
    gamma_events = [
        {
            "title": "Test event",
            "tags": [{"slug": "politics"}],
            "markets": [
                {
                    "id": "m1",
                    "question": "Will X happen?",
                    "outcomePrices": "[\"0.40\", \"0.60\"]",
                    "endDate": (now + timedelta(hours=12)).isoformat().replace("+00:00", "Z"),
                    "active": True,
                    "closed": False,
                    "acceptingOrders": True,
                }
            ],
        }
    ]

    monkeypatch.setattr(
        "src.pipeline_refresh.load_current_profile",
        lambda: {
            "yes": 0.15,
            "no": 0.05,
            "min_category_priority": 1,
            "category_priorities": {"politics": 3, "other": 0},
        },
    )
    monkeypatch.setattr("src.pipeline_refresh.load_fast_markets", lambda _now: [])
    monkeypatch.setattr(
        "src.pipeline_refresh.load_latest_pipeline_verdict",
        lambda: ("REJECT ALL", "No validated edge.", []),
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.load_a6_scan_summary",
        lambda: {"status": "blocked", "executable": 0},
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.run_a6_live_scan",
        lambda: {"status": "active", "executable": 0, "candidates": 0, "opportunities": [], "stats": {}},
    )
    monkeypatch.setattr(
        "src.pipeline_refresh.load_wallet_flow_status",
        lambda: {"ready": True, "scored_wallets": 80, "status": "ready"},
    )
    monkeypatch.setattr("src.pipeline_refresh.load_system_status", lambda: "stopped")

    payload = build_refresh_payload(now, tmp_path, gamma_events)

    assert payload["fast_markets_pulled"] == 0
    assert payload["threshold_market_source"] == "gamma_events_flattened"
    assert payload["threshold_markets_pulled"] == 1
    assert payload["basic_filter_markets"] == 1
    assert payload["markets_under_24h"] == 1
    assert payload["a6_live_scan"]["status"] == "active"
    assert payload["threshold_sensitivity"]["current"]["tradeable"] == 1
    assert payload["threshold_sensitivity"]["aggressive"]["tradeable"] == 1
