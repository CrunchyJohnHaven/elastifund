from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.runtime_profile import load_runtime_profile, write_effective_runtime_profile


def test_shadow_fast_flow_profile_writes_effective_dump(tmp_path: Path) -> None:
    bundle = load_runtime_profile(
        env={"JJ_RUNTIME_PROFILE": "shadow_fast_flow"},
        remote_cycle_status_path=tmp_path / "remote_cycle_status.json",
    )

    assert bundle.config["mode"]["effective_execution_mode"] == "shadow"
    assert bundle.config["feature_flags"]["fast_flow_only"] is True
    assert bundle.config["signal_thresholds"]["lmsr_entry_threshold"] == 0.04

    output = write_effective_runtime_profile(bundle, output_path=tmp_path / "runtime_profile_effective.json")
    payload = json.loads(output.read_text())

    assert payload["selected_profile"] == "shadow_fast_flow"
    assert payload["mode"]["effective_execution_mode"] == "shadow"
    assert payload["feature_flags"]["enable_wallet_flow"] is True


def test_legacy_env_overrides_beat_profile_defaults(tmp_path: Path) -> None:
    bundle = load_runtime_profile(
        env={
            "JJ_RUNTIME_PROFILE": "shadow_fast_flow",
            "JJ_YES_THRESHOLD": "0.22",
            "ENABLE_WALLET_FLOW": "false",
            "JJ_VPIN_WINDOW": "12",
        },
        remote_cycle_status_path=tmp_path / "remote_cycle_status.json",
    )

    assert bundle.config["signal_thresholds"]["yes_threshold"] == 0.22
    assert bundle.config["feature_flags"]["enable_wallet_flow"] is False
    assert bundle.config["microstructure_thresholds"]["vpin_window_size"] == 12
    assert "JJ_YES_THRESHOLD" in bundle.legacy_overrides
    assert "ENABLE_WALLET_FLOW" in bundle.legacy_overrides


def test_mode_contract_surfaces_launch_gate_and_order_submission() -> None:
    blocked = load_runtime_profile(env={"JJ_RUNTIME_PROFILE": "blocked_safe"})
    shadow = load_runtime_profile(env={"JJ_RUNTIME_PROFILE": "shadow_fast_flow"})

    assert blocked.config["mode"]["requested_execution_mode"] == "blocked"
    assert blocked.config["mode"]["launch_gate"] == "blocked"
    assert blocked.effective_env["JJ_ALLOW_ORDER_SUBMISSION"] == "false"
    assert shadow.config["mode"]["effective_execution_mode"] == "shadow"
    assert shadow.config["mode"]["launch_gate"] == "wallet_flow_ready"
    assert shadow.effective_env["JJ_ALLOW_ORDER_SUBMISSION"] == "true"


def test_runtime_profile_supports_hourly_budget_and_venue_flag_overrides() -> None:
    bundle = load_runtime_profile(
        env={
            "JJ_RUNTIME_PROFILE": "blocked_safe",
            "JJ_HOURLY_NOTIONAL_BUDGET_USD": "50",
            "JJ_ENABLE_POLYMARKET_VENUE": "false",
            "JJ_ENABLE_KALSHI_VENUE": "true",
        }
    )

    assert bundle.config["risk_limits"]["hourly_notional_budget_usd"] == 50.0
    assert bundle.config["feature_flags"]["enable_polymarket_venue"] is False
    assert bundle.config["feature_flags"]["enable_kalshi_venue"] is True
    assert bundle.effective_env["JJ_HOURLY_NOTIONAL_BUDGET_USD"] == "50.0"
    assert bundle.effective_env["JJ_ENABLE_POLYMARKET_VENUE"] == "false"
    assert bundle.effective_env["JJ_ENABLE_KALSHI_VENUE"] == "true"


def test_paper_aggressive_profile_matches_first_trade_collection_posture() -> None:
    bundle = load_runtime_profile(env={"JJ_RUNTIME_PROFILE": "paper_aggressive"})

    assert bundle.selected_profile == "paper_aggressive"
    assert bundle.config["mode"]["effective_execution_mode"] == "shadow"
    assert bundle.config["mode"]["paper_trading"] is True
    assert bundle.effective_env["JJ_ALLOW_ORDER_SUBMISSION"] == "true"
    assert bundle.config["signal_thresholds"]["yes_threshold"] == 0.08
    assert bundle.config["signal_thresholds"]["no_threshold"] == 0.03
    assert bundle.config["risk_limits"]["scan_interval_seconds"] == 120
    assert bundle.config["market_filters"]["min_category_priority"] == 0
    assert bundle.config["market_filters"]["category_priorities"]["crypto"] == 2
    assert bundle.config["market_filters"]["category_priorities"]["sports"] == 1


def test_maker_velocity_all_in_profile_enables_full_cap_multi_lane() -> None:
    bundle = load_runtime_profile(env={"JJ_RUNTIME_PROFILE": "maker_velocity_all_in"})

    assert bundle.selected_profile == "maker_velocity_all_in"
    assert bundle.config["mode"]["effective_execution_mode"] == "shadow"
    assert bundle.config["mode"]["paper_trading"] is False
    assert bundle.config["mode"]["allow_order_submission"] is True
    assert bundle.config["feature_flags"]["fast_flow_only"] is False
    assert bundle.config["feature_flags"]["enable_wallet_flow"] is True
    assert bundle.config["feature_flags"]["enable_lmsr"] is True
    assert bundle.config["feature_flags"]["enable_llm_signals"] is True
    assert bundle.config["risk_limits"]["max_exposure_pct"] == 1.0
    assert bundle.config["risk_limits"]["max_position_usd"] == 50.0
    assert bundle.config["risk_limits"]["max_open_positions"] == 10
    assert bundle.config["risk_limits"]["min_edge"] == 0.01
    assert bundle.config["risk_limits"]["hourly_notional_budget_usd"] == 247.51
    assert bundle.config["market_filters"]["max_resolution_hours"] == 24.0
    assert bundle.config["market_filters"]["category_priorities"]["crypto"] == 3
    assert bundle.effective_env["JJ_FAST_FLOW_ONLY"] == "false"


def test_maker_velocity_live_profile_is_fast_turn_crypto_only() -> None:
    bundle = load_runtime_profile(env={"JJ_RUNTIME_PROFILE": "maker_velocity_live"})

    assert bundle.selected_profile == "maker_velocity_live"
    assert bundle.config["mode"]["effective_execution_mode"] == "shadow"
    assert bundle.config["mode"]["paper_trading"] is False
    assert bundle.config["mode"]["allow_order_submission"] is True
    assert bundle.config["feature_flags"]["fast_flow_only"] is True
    assert bundle.config["feature_flags"]["enable_llm_signals"] is False
    assert bundle.config["feature_flags"]["enable_wallet_flow"] is True
    assert bundle.config["feature_flags"]["enable_lmsr"] is True
    assert bundle.config["risk_limits"]["max_position_usd"] == 10.0
    assert bundle.config["risk_limits"]["hourly_notional_budget_usd"] == 227.38
    assert bundle.config["market_filters"]["max_resolution_hours"] == 1.0
    assert bundle.config["market_filters"]["category_priorities"]["crypto"] == 3
    assert bundle.config["market_filters"]["category_priorities"]["politics"] == 0
    assert bundle.config["market_filters"]["category_priorities"]["weather"] == 0
    assert bundle.effective_env["JJ_FAST_FLOW_ONLY"] == "true"
    assert bundle.effective_env["ENABLE_LLM_SIGNALS"] == "false"
