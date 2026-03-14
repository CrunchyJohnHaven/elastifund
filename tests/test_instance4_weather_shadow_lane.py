from __future__ import annotations

from datetime import datetime, timezone

from scripts.run_instance4_weather_shadow_lane import (
    CitySnapshot,
    _contains_bracket_structure,
    _scan_windows,
    build_instance4_weather_lane_artifact,
)


def test_contains_bracket_structure_detects_ranges() -> None:
    assert _contains_bracket_structure("between 62 and 63") is True
    assert _contains_bracket_structure("62-63") is True
    assert _contains_bracket_structure("Will high temp be >62") is False


def test_scan_windows_marks_active_window() -> None:
    now = datetime(2026, 3, 12, 14, 25, tzinfo=timezone.utc)
    schedule = _scan_windows(now)
    assert schedule["should_scan_now"] is True
    assert schedule["active_windows"]
    assert schedule["next_windows"]


def test_build_instance4_weather_lane_artifact_filters_brackets_and_keeps_shadow_policy(tmp_path) -> None:
    reports_dir = tmp_path / "reports"
    (reports_dir / "finance").mkdir(parents=True)
    (reports_dir / "finance" / "latest.json").write_text('{"finance_gate_pass": true}\n', encoding="utf-8")
    (reports_dir / "runtime_truth_latest.json").write_text(
        '{"launch_posture":"clear","allow_order_submission":true,"execution_mode":"live","agent_run_mode":"live"}\n',
        encoding="utf-8",
    )

    markets = [
        {
            "ticker": "KXHIGHNY-26MAR13-T52",
            "event_ticker": "KXHIGHNY-26MAR13",
            "title": "Will high temp in NYC be >52 on Mar 13, 2026?",
            "subtitle": "53 or above",
            "rules_primary": "Highest temperature according to National Weather Service Climatological Report (Daily).",
            "rules_secondary": "Official value is from NWS Climatological Report.",
            "status": "active",
            "yes_bid_dollars": 0.42,
            "yes_ask_dollars": 0.45,
            "no_bid_dollars": 0.54,
            "no_ask_dollars": 0.57,
        },
        {
            "ticker": "KXHIGHNY-26MAR13-RANGE",
            "event_ticker": "KXHIGHNY-26MAR13",
            "title": "Will high temp in NYC be between 52 and 53 on Mar 13, 2026?",
            "subtitle": "52-53",
            "rules_primary": "Highest temperature according to National Weather Service Climatological Report (Daily).",
            "rules_secondary": "Official value is from NWS Climatological Report.",
            "status": "active",
            "yes_bid_dollars": 0.12,
            "yes_ask_dollars": 0.14,
            "no_bid_dollars": 0.86,
            "no_ask_dollars": 0.88,
        },
        {
            "ticker": "KXHIGHAUS-26MAR13-T80",
            "event_ticker": "KXHIGHAUS-26MAR13",
            "title": "Will high temp in Austin be >80 on Mar 13, 2026?",
            "subtitle": "81 or above",
            "rules_primary": "Highest temperature according to National Weather Service Climatological Report (Daily).",
            "rules_secondary": "Official value is from NWS Climatological Report.",
            "status": "active",
            "yes_bid_dollars": 0.49,
            "yes_ask_dollars": 0.52,
            "no_bid_dollars": 0.48,
            "no_ask_dollars": 0.51,
        },
        {
            "ticker": "KXHIGHCHI-26MAR13-T48",
            "event_ticker": "KXHIGHCHI-26MAR13",
            "title": "Will high temp in Chicago be >48 on Mar 13, 2026?",
            "subtitle": "49 or above",
            "rules_primary": "Highest temperature according to National Weather Service Climatological Report (Daily).",
            "rules_secondary": "Official value is from NWS Climatological Report.",
            "status": "active",
            "yes_bid_dollars": 0.50,
            "yes_ask_dollars": 0.53,
            "no_bid_dollars": 0.47,
            "no_ask_dollars": 0.50,
        },
    ]

    snapshots = {
        ("NYC", "2026-03-13"): CitySnapshot(
            city="NYC",
            target_date="2026-03-13",
            point_high_f=55.0,
            hourly_high_f=54.0,
            pop_probability=0.2,
            point_updated_at="2026-03-12T14:20:00+00:00",
            hourly_updated_at="2026-03-12T14:50:00+00:00",
        ),
        ("AUS", "2026-03-13"): CitySnapshot(
            city="AUS",
            target_date="2026-03-13",
            point_high_f=85.0,
            hourly_high_f=84.0,
            pop_probability=0.1,
            point_updated_at="2026-03-12T14:20:00+00:00",
            hourly_updated_at="2026-03-12T14:50:00+00:00",
        ),
        ("CHI", "2026-03-13"): CitySnapshot(
            city="CHI",
            target_date="2026-03-13",
            point_high_f=51.0,
            hourly_high_f=50.0,
            pop_probability=0.3,
            point_updated_at="2026-03-12T14:20:00+00:00",
            hourly_updated_at="2026-03-12T14:50:00+00:00",
        ),
    }

    payload = build_instance4_weather_lane_artifact(
        repo_root=tmp_path,
        now=datetime(2026, 3, 12, 14, 25, tzinfo=timezone.utc),
        markets=markets,
        snapshot_overrides=snapshots,
    )

    assert payload["execution_policy"]["mode"] == "shadow_only"
    assert payload["execution_policy"]["live_capital_usd"] == 0
    assert payload["source_mapping_summary"]["clean_city_count"] >= 3
    assert payload["market_scan"]["clean_tradeable_markets"] == 3
    assert payload["finance_gate_pass"] is True
    assert "bracket_rounding_thesis_rejected" in payload["block_reasons"]
    excluded_tickers = {row["ticker"] for row in payload["market_scan"]["excluded_rows"]}
    assert "KXHIGHNY-26MAR13-RANGE" in excluded_tickers
