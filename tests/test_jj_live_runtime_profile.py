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
