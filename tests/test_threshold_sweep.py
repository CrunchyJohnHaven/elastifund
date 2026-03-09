from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.threshold_sweep import build_report, derive_fast_market_reachability


def test_derive_fast_market_reachability_uses_exact_sample_window_union() -> None:
    summary = {
        "tradeable": 3,
        "yes_reachable_markets": 2,
        "no_reachable_markets": 2,
        "sample_windows": [
            {"required_calibrated_prob_yes": 0.62, "max_calibrated_prob_no": None},
            {"required_calibrated_prob_yes": None, "max_calibrated_prob_no": 0.41},
            {"required_calibrated_prob_yes": 0.57, "max_calibrated_prob_no": 0.44},
        ],
    }

    result = derive_fast_market_reachability(summary)

    assert result == {
        "count": 3,
        "source": "sample_windows_exact",
        "inferred": False,
        "sample_windows_count": 3,
    }


def test_build_report_marks_aggressive_profile_as_reachability_only_breakpoint(tmp_path: Path) -> None:
    payload = {
        "timestamp": "2026-03-09T01:58:34.672967+00:00",
        "threshold_market_source": "fast_market_discovery",
        "fast_markets_pulled": 22,
        "basic_filter_markets": 6,
        "markets_in_allowed_categories": 0,
        "recommendation": "REJECT ALL",
        "new_viable_strategies": [],
        "threshold_sensitivity": {
            "current": {
                "yes": 0.15,
                "no": 0.05,
                "tradeable": 0,
                "yes_reachable_markets": 0,
                "no_reachable_markets": 0,
                "sample_windows": [],
            },
            "aggressive": {
                "yes": 0.08,
                "no": 0.03,
                "tradeable": 6,
                "yes_reachable_markets": 6,
                "no_reachable_markets": 6,
                "sample_windows": [
                    {"required_calibrated_prob_yes": 0.57, "max_calibrated_prob_no": 0.46}
                    for _ in range(6)
                ],
            },
            "wide_open": {
                "yes": 0.05,
                "no": 0.02,
                "tradeable": 6,
                "yes_reachable_markets": 6,
                "no_reachable_markets": 6,
                "sample_windows": [
                    {"required_calibrated_prob_yes": 0.54, "max_calibrated_prob_no": 0.47}
                    for _ in range(6)
                ],
            },
        },
    }

    artifact = tmp_path / "pipeline_refresh_20260309T015834Z.json"
    artifact.write_text("{}")
    report = build_report(
        generated_at=datetime(2026, 3, 9, 3, 0, tzinfo=timezone.utc),
        source_artifact=artifact,
        source_mode="offline_artifact",
        payload=payload,
    )

    assert report["source_artifact"]["threshold_market_source"] == "fast_market_discovery"
    assert report["threshold_pairs_tested"] == [
        {
            "profile": "current",
            "yes_threshold": 0.15,
            "no_threshold": 0.05,
            "pipeline_refresh_tradeable_field": 0,
            "fast_market_reachability": 0,
            "pipeline_tradeable": 0,
            "yes_reachable_markets": 0,
            "no_reachable_markets": 0,
            "reachability_count_source": "sample_windows_exact",
            "reachability_count_inferred": False,
            "sample_windows_count": 0,
        },
        {
            "profile": "aggressive",
            "yes_threshold": 0.08,
            "no_threshold": 0.03,
            "pipeline_refresh_tradeable_field": 6,
            "fast_market_reachability": 6,
            "pipeline_tradeable": 0,
            "yes_reachable_markets": 6,
            "no_reachable_markets": 6,
            "reachability_count_source": "sample_windows_exact",
            "reachability_count_inferred": False,
            "sample_windows_count": 6,
        },
        {
            "profile": "wide_open",
            "yes_threshold": 0.05,
            "no_threshold": 0.02,
            "pipeline_refresh_tradeable_field": 6,
            "fast_market_reachability": 6,
            "pipeline_tradeable": 0,
            "yes_reachable_markets": 6,
            "no_reachable_markets": 6,
            "reachability_count_source": "sample_windows_exact",
            "reachability_count_inferred": False,
            "sample_windows_count": 6,
        },
    ]
    assert report["breakpoint_detection"]["fast_market_reachability"] == [
        {
            "metric": "fast_market_reachability",
            "from_profile": "current",
            "to_profile": "aggressive",
            "yes_threshold": 0.08,
            "no_threshold": 0.03,
            "previous_count": 0,
            "current_count": 6,
            "delta": 6,
        }
    ]
    assert report["breakpoint_detection"]["pipeline_tradeable"] == []
    assert report["conclusion"]["aggressive_pair_unlocks_reachability"] is True
    assert report["conclusion"]["aggressive_pair_unlocks_pipeline_tradeable"] is False
    assert "unlocks only reachability" in report["conclusion"]["plain_english"]
    assert report["conclusion"]["latest_pipeline_recommendation"] == "REJECT ALL"
