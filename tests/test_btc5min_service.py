#!/usr/bin/env python3
"""Validation tests for deploy/btc-5min-maker.service."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPO_ROOT / "deploy" / "btc-5min-maker.service"
RUNNER_PATH = REPO_ROOT / "scripts" / "run_btc5_service.sh"


def _service_lines() -> list[str]:
    return SERVICE_PATH.read_text(encoding="utf-8").splitlines()


def _option_values(section: str, option: str) -> list[str]:
    values: list[str] = []
    in_section = False
    for raw_line in _service_lines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line == f"[{section}]"
            continue
        if not in_section or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == option:
            values.append(value.strip())
    return values


def test_service_file_has_required_sections_and_keys() -> None:
    lines = _service_lines()

    assert "[Unit]" in lines
    assert "[Service]" in lines
    assert "[Install]" in lines
    assert _option_values("Unit", "Description")
    assert _option_values("Unit", "After")
    assert _option_values("Service", "WorkingDirectory")
    assert _option_values("Service", "EnvironmentFile")
    assert _option_values("Service", "ExecStart")
    assert _option_values("Install", "WantedBy") == ["multi-user.target"]


def test_execstart_targets_mode_aware_btc5_runner() -> None:
    exec_start = _option_values("Service", "ExecStart")[0]

    assert exec_start == "/home/ubuntu/polymarket-trading-bot/scripts/run_btc5_service.sh"


def test_environment_file_chain_loads_stage_overrides_after_base_env() -> None:
    working_dir = _option_values("Service", "WorkingDirectory")[0].rstrip("/")
    env_files = _option_values("Service", "EnvironmentFile")

    assert env_files == [
        f"-{working_dir}/config/btc5_strategy.env",
        f"-{working_dir}/state/btc5_autoresearch.env",
        f"{working_dir}/.env",
        f"-{working_dir}/state/btc5_capital_stage.env",
    ]


def test_runner_script_switches_between_live_stage1_and_shadow_probe() -> None:
    text = RUNNER_PATH.read_text(encoding="utf-8")

    assert "BTC5_DEPLOY_MODE" in text
    assert "BTC5_PAPER_TRADING" in text
    assert "--paper" in text
    assert "--live" in text
    assert "bot/btc_5min_maker.py" in text
