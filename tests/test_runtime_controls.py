from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_controls(*args: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parent.parent
    return subprocess.run(
        [sys.executable, "scripts/runtime_controls.py", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )


def test_runtime_controls_set_controls_updates_effective_profile_and_writes_action(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"

    result = _run_controls(
        "--reports-dir",
        str(reports_dir),
        "--profile",
        "blocked_safe",
        "set-controls",
        "--yes-threshold",
        "0.08",
        "--no-threshold",
        "0.03",
        "--max-resolution-hours",
        "24",
        "--hourly-notional-budget-usd",
        "50",
        "--per-trade-cap-usd",
        "10",
        "--enable-polymarket",
        "true",
        "--enable-kalshi",
        "false",
    )
    payload = json.loads(result.stdout.strip())

    effective_path = Path(payload["effective_profile"])
    action_path = Path(payload["operator_action"])
    assert effective_path.exists()
    assert action_path.exists()

    effective = json.loads(effective_path.read_text())
    assert effective["signal_thresholds"]["yes_threshold"] == 0.08
    assert effective["signal_thresholds"]["no_threshold"] == 0.03
    assert effective["market_filters"]["max_resolution_hours"] == 24.0
    assert effective["risk_limits"]["hourly_notional_budget_usd"] == 50.0
    assert effective["risk_limits"]["max_position_usd"] == 10.0
    assert effective["feature_flags"]["enable_polymarket_venue"] is True
    assert effective["feature_flags"]["enable_kalshi_venue"] is False

    action = json.loads(action_path.read_text())
    changed_keys = {item["env_var"] for item in action["operator_action"]["changed_values"]}
    assert "JJ_YES_THRESHOLD" in changed_keys
    assert "JJ_NO_THRESHOLD" in changed_keys
    assert "JJ_MAX_RESOLUTION_HOURS" in changed_keys
    assert "JJ_HOURLY_NOTIONAL_BUDGET_USD" in changed_keys
    assert "JJ_MAX_POSITION_USD" in changed_keys
    assert "JJ_ENABLE_KALSHI_VENUE" in changed_keys

    overrides_path = reports_dir / "runtime_operator_overrides.env"
    overrides = overrides_path.read_text()
    assert "JJ_YES_THRESHOLD=0.08" in overrides
    assert "JJ_NO_THRESHOLD=0.03" in overrides
    assert "JJ_HOURLY_NOTIONAL_BUDGET_USD=50" in overrides
    assert "JJ_ENABLE_KALSHI_VENUE=false" in overrides


def test_runtime_controls_fail_closed_when_per_trade_cap_exceeds_hourly_budget(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "scripts/runtime_controls.py",
            "--reports-dir",
            str(reports_dir),
            "--profile",
            "blocked_safe",
            "set-controls",
            "--hourly-notional-budget-usd",
            "50",
            "--per-trade-cap-usd",
            "60",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "cannot exceed hourly-notional-budget-usd" in result.stderr
    assert not (reports_dir / "runtime_operator_overrides.env").exists()
    assert not (reports_dir / "runtime_profile_effective.json").exists()
