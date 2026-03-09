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
