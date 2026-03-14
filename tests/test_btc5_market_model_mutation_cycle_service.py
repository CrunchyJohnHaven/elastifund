from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPO_ROOT / "deploy" / "btc5-market-model-autoresearch.service"
TIMER_PATH = REPO_ROOT / "deploy" / "btc5-market-model-autoresearch.timer"
RUNNER_PATH = REPO_ROOT / "scripts" / "run_btc5_market_model_mutation_cycle.py"


def test_market_service_uses_market_mutation_cycle_entrypoint() -> None:
    service_text = SERVICE_PATH.read_text(encoding="utf-8")
    timer_text = TIMER_PATH.read_text(encoding="utf-8")

    assert "scripts/run_btc5_market_model_mutation_cycle.py" in service_text
    assert "Restart=on-failure" in service_text
    assert "TimeoutStartSec=1800" in service_text
    assert "OnUnitActiveSec=60min" in timer_text


def test_market_mutation_cycle_wrapper_exposes_autoresearch_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "run_btc5_market_model_mutation_cycle.py" in result.stdout
    assert "--command-override" in result.stdout
    assert "--write-morning-report" in result.stdout
