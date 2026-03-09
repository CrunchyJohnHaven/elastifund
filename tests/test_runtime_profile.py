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
