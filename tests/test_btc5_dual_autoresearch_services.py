from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_market_service_uses_dual_ops_runner() -> None:
    text = _read("deploy/btc5-market-model-autoresearch.service")
    timer = _read("deploy/btc5-market-model-autoresearch.timer")
    runner = _read("scripts/run_btc5_market_model_mutation_cycle.py")

    assert "scripts/run_btc5_market_model_mutation_cycle.py" in text
    assert '"run-lane", "--lane", "market", "--write-morning-report"' in runner
    assert "Restart=on-failure" in text
    assert "RestartSec=60" in text
    assert "TimeoutStartSec=1800" in text
    assert "OnUnitActiveSec=60min" in timer


def test_policy_service_uses_dual_ops_runner() -> None:
    text = _read("deploy/btc5-policy-autoresearch.service")
    timer = _read("deploy/btc5-policy-autoresearch.timer")

    assert "scripts/btc5_dual_autoresearch_ops.py run-lane --lane policy --write-morning-report" in text
    assert "Restart=on-failure" in text
    assert "RestartSec=60" in text
    assert "TimeoutStartSec=600" in text
    assert "OnUnitActiveSec=15min" in timer


def test_command_node_service_uses_dual_ops_runner() -> None:
    text = _read("deploy/btc5-command-node-autoresearch.service")
    timer = _read("deploy/btc5-command-node-autoresearch.timer")
    runner = _read("scripts/run_btc5_command_node_mutation_cycle.py")

    assert "scripts/run_btc5_command_node_mutation_cycle.py" in text
    assert '"run-lane", "--lane", "command_node", "--write-morning-report"' in runner
    assert "Restart=on-failure" in text
    assert "RestartSec=60" in text
    assert "TimeoutStartSec=1800" in text
    assert "OnUnitActiveSec=60min" in timer


def test_morning_service_writes_daily_rollup() -> None:
    text = _read("deploy/btc5-dual-autoresearch-morning.service")
    timer = _read("deploy/btc5-dual-autoresearch-morning.timer")

    assert "scripts/btc5_dual_autoresearch_ops.py morning-report --window-hours 24" in text
    assert "TimeoutStartSec=300" in text
    assert "OnCalendar=*-*-* 09:05:00" in timer
