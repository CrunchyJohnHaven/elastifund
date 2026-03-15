from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bot.jj_live as jj_live_module
from bot.runtime_profile import load_runtime_profile


def _restore_env(key: str, original: str | None) -> None:
    if original is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = original


def test_paper_aggressive_profile_loads_checked_in_contract() -> None:
    bundle = load_runtime_profile(env={"JJ_RUNTIME_PROFILE": "paper_aggressive"})

    assert bundle.selected_profile == "paper_aggressive"
    assert bundle.source_path.endswith("config/runtime_profiles/paper_aggressive.json")
    assert bundle.config["mode"]["effective_execution_mode"] == "shadow"
    assert bundle.config["mode"]["launch_gate"] == "none"
    assert bundle.config["mode"]["paper_trading"] is True
    assert bundle.effective_env["JJ_ALLOW_ORDER_SUBMISSION"] == "true"
    assert bundle.config["feature_flags"]["enable_wallet_flow"] is True
    assert bundle.config["signal_thresholds"]["yes_threshold"] == 0.08
    assert bundle.config["signal_thresholds"]["no_threshold"] == 0.03
    assert bundle.config["risk_limits"]["scan_interval_seconds"] == 120
    assert bundle.config["risk_limits"]["kelly_fraction"] == 0.25


def test_paper_aggressive_profile_unlocks_crypto_without_negative_priorities() -> None:
    bundle = load_runtime_profile(env={"JJ_RUNTIME_PROFILE": "paper_aggressive"})
    market_filters = bundle.config["market_filters"]
    category_priorities = market_filters["category_priorities"]

    assert market_filters["min_category_priority"] == 0
    assert category_priorities["crypto"] == 2
    assert category_priorities["sports"] == 1
    assert category_priorities["financial_speculation"] == 1
    assert category_priorities["unknown"] == 0
    assert all(priority >= 0 for priority in category_priorities.values())


def test_reload_runtime_settings_applies_paper_aggressive_profile() -> None:
    originals = {
        "JJ_RUNTIME_PROFILE": os.environ.get("JJ_RUNTIME_PROFILE"),
        "JJ_YES_THRESHOLD": os.environ.get("JJ_YES_THRESHOLD"),
        "JJ_NO_THRESHOLD": os.environ.get("JJ_NO_THRESHOLD"),
        "JJ_ALLOW_ORDER_SUBMISSION": os.environ.get("JJ_ALLOW_ORDER_SUBMISSION"),
        "JJ_SCAN_INTERVAL": os.environ.get("JJ_SCAN_INTERVAL"),
        "JJ_KELLY_FRACTION": os.environ.get("JJ_KELLY_FRACTION"),
        "JJ_MIN_EDGE": os.environ.get("JJ_MIN_EDGE"),
        "JJ_MIN_CATEGORY_PRIORITY": os.environ.get("JJ_MIN_CATEGORY_PRIORITY"),
        "JJ_CAT_PRIORITY_CRYPTO": os.environ.get("JJ_CAT_PRIORITY_CRYPTO"),
        "JJ_CAT_PRIORITY_SPORTS": os.environ.get("JJ_CAT_PRIORITY_SPORTS"),
        "ENABLE_WALLET_FLOW": os.environ.get("ENABLE_WALLET_FLOW"),
        "PAPER_TRADING": os.environ.get("PAPER_TRADING"),
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
        assert os.environ["ENABLE_WALLET_FLOW"] == "true"
        assert os.environ["JJ_ALLOW_ORDER_SUBMISSION"] == "true"
    finally:
        for key, original in originals.items():
            _restore_env(key, original)
        jj_live_module._reload_runtime_settings(persist=False)
