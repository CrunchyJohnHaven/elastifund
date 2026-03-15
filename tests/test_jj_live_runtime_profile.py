from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bot.jj_live as jj_live_module


def _restore_env(key: str, original: str | None) -> None:
    if original is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = original


def test_reload_runtime_settings_applies_shadow_fast_flow_profile() -> None:
    originals = {
        "JJ_RUNTIME_PROFILE": os.environ.get("JJ_RUNTIME_PROFILE"),
        "JJ_YES_THRESHOLD": os.environ.get("JJ_YES_THRESHOLD"),
        "JJ_NO_THRESHOLD": os.environ.get("JJ_NO_THRESHOLD"),
    }
    try:
        os.environ["JJ_RUNTIME_PROFILE"] = "shadow_fast_flow"
        bundle = jj_live_module._reload_runtime_settings(persist=False)

        assert bundle.selected_profile == "shadow_fast_flow"
        assert jj_live_module.RUNTIME_EXECUTION_MODE == "shadow"
        assert jj_live_module.PAPER_TRADING is True
        assert jj_live_module.SCAN_INTERVAL == 60
        assert jj_live_module.KELLY_FRACTION == 0.0625
        assert jj_live_module.MIN_EDGE == 0.04
        assert jj_live_module.CATEGORY_PRIORITY["crypto"] == 3
        assert jj_live_module.ALLOWED_FAST_ASSETS == set()
        assert os.environ["JJ_ALLOW_ORDER_SUBMISSION"] == "true"
    finally:
        for key, original in originals.items():
            _restore_env(key, original)
        jj_live_module._reload_runtime_settings(persist=False)


def test_compute_calibrated_signal_flips_with_profile_thresholds() -> None:
    originals = {
        "JJ_RUNTIME_PROFILE": os.environ.get("JJ_RUNTIME_PROFILE"),
        "JJ_YES_THRESHOLD": os.environ.get("JJ_YES_THRESHOLD"),
        "JJ_NO_THRESHOLD": os.environ.get("JJ_NO_THRESHOLD"),
    }
    try:
        os.environ["JJ_RUNTIME_PROFILE"] = "research_scan"
        jj_live_module._reload_runtime_settings(persist=False)
        research_yes = jj_live_module.compute_calibrated_signal(
            0.62,
            0.50,
            "politics",
            already_calibrated=True,
        )
        research_no = jj_live_module.compute_calibrated_signal(
            0.465,
            0.50,
            "politics",
            already_calibrated=True,
        )

        os.environ["JJ_RUNTIME_PROFILE"] = "blocked_safe"
        jj_live_module._reload_runtime_settings(persist=False)
        blocked_yes = jj_live_module.compute_calibrated_signal(
            0.62,
            0.50,
            "politics",
            already_calibrated=True,
        )
        blocked_no = jj_live_module.compute_calibrated_signal(
            0.465,
            0.50,
            "politics",
            already_calibrated=True,
        )

        assert research_yes["mispriced"] is True
        assert research_yes["direction"] == "buy_yes"
        assert research_no["mispriced"] is True
        assert research_no["direction"] == "buy_no"
        assert blocked_yes["mispriced"] is False
        assert blocked_no["mispriced"] is False
    finally:
        for key, original in originals.items():
            _restore_env(key, original)
        jj_live_module._reload_runtime_settings(persist=False)


def test_reload_runtime_settings_applies_paper_aggressive_profile() -> None:
    originals = {
        "JJ_RUNTIME_PROFILE": os.environ.get("JJ_RUNTIME_PROFILE"),
        "JJ_YES_THRESHOLD": os.environ.get("JJ_YES_THRESHOLD"),
        "JJ_NO_THRESHOLD": os.environ.get("JJ_NO_THRESHOLD"),
    }
    try:
        os.environ["JJ_RUNTIME_PROFILE"] = "paper_aggressive"
        bundle = jj_live_module._reload_runtime_settings(persist=False)

        assert bundle.selected_profile == "paper_aggressive"
        assert jj_live_module.RUNTIME_EXECUTION_MODE == "shadow"
        assert jj_live_module.PAPER_TRADING is True
        assert jj_live_module.ALLOW_ORDER_SUBMISSION is True
        assert jj_live_module.SCAN_INTERVAL == 120
        assert jj_live_module.KELLY_FRACTION == 0.25
        assert jj_live_module.MIN_EDGE == 0.03
        assert jj_live_module.MIN_CATEGORY_PRIORITY == 0
        assert jj_live_module.CATEGORY_PRIORITY["crypto"] == 2
        assert jj_live_module.CATEGORY_PRIORITY["sports"] == 1
    finally:
        for key, original in originals.items():
            _restore_env(key, original)
        jj_live_module._reload_runtime_settings(persist=False)


def test_sum_violation_lane_disabled_for_paper_aggressive_profile() -> None:
    original = os.environ.get("ENABLE_SUM_VIOLATION")
    try:
        os.environ["ENABLE_SUM_VIOLATION"] = "true"
        assert jj_live_module._sum_violation_lane_enabled("paper_aggressive") is False
        assert jj_live_module._sum_violation_lane_enabled("shadow_fast_flow") is True

        os.environ["ENABLE_SUM_VIOLATION"] = "false"
        assert jj_live_module._sum_violation_lane_enabled("shadow_fast_flow") is False
    finally:
        _restore_env("ENABLE_SUM_VIOLATION", original)


def test_fast_flow_market_detector_handles_time_window_titles() -> None:
    assert (
        jj_live_module.looks_like_fast_flow_market(
            "Bitcoin Up or Down - March 9, 8:05AM-8:10AM ET"
        )
        is True
    )
    assert (
        jj_live_module.looks_like_fast_flow_market(
            "Bitcoin Up or Down - March 9, 8:00AM-8:15AM ET"
        )
        is True
    )
    assert jj_live_module.looks_like_fast_flow_market("Aziz Akhannouch out as Morocco Prime Minister?") is False


def test_dedicated_btc5_detector_distinguishes_5m_and_15m_titles() -> None:
    assert (
        jj_live_module.is_dedicated_btc5_market(
            "Bitcoin Up or Down - March 9, 8:05AM-8:10AM ET",
            slug="btc-updown-5m-1741507500",
        )
        is True
    )
    assert (
        jj_live_module.is_dedicated_btc5_market(
            "Bitcoin Up or Down - March 9, 8:00AM-8:15AM ET",
            slug="btc-updown-15m-1741507200",
        )
        is False
    )


def test_maker_velocity_live_restricts_non_btc_fast_assets() -> None:
    originals = {
        "JJ_RUNTIME_PROFILE": os.environ.get("JJ_RUNTIME_PROFILE"),
    }
    try:
        os.environ["JJ_RUNTIME_PROFILE"] = "maker_velocity_live"
        jj_live_module._reload_runtime_settings(persist=False)

        allowed, reason, category, _ = jj_live_module.apply_llm_market_filters(
            "Ethereum Up or Down - March 11, 8:00AM-8:05AM ET",
            resolution_hours=0.1,
        )
        assert allowed is False
        assert reason == "fast_asset_not_allowed"
        assert category == "crypto"

        allowed_btc, reason_btc, _, _ = jj_live_module.apply_llm_market_filters(
            "Bitcoin Up or Down - March 11, 8:00AM-8:15AM ET",
            resolution_hours=0.25,
        )
        assert allowed_btc is True
        assert reason_btc == "ok"
    finally:
        for key, original in originals.items():
            _restore_env(key, original)
        jj_live_module._reload_runtime_settings(persist=False)
