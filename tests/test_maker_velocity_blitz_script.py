from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/maker_velocity_blitz.py", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_launch_check_outputs_machine_booleans_and_nonzero_on_block(tmp_path: Path) -> None:
    repo = tmp_path
    (repo / "reports").mkdir()
    (repo / "reports" / "remote_cycle_status.json").write_text(
        json.dumps(
            {
                "wallet_flow": {"ready": False},
                "root_tests": {"status": "passing"},
                "launch": {"fast_flow_restart_ready": False},
                "data_cadence": {"stale": True},
                "service": {"status": "running"},
                "runtime_truth": {"drift_detected": True},
            }
        )
    )
    (repo / "reports" / "remote_service_status.json").write_text(json.dumps({"status": "running"}))
    (repo / "jj_state.json").write_text(json.dumps({"bankroll": 247.51}))

    out_path = repo / "reports" / "launch_gate.json"
    result = _run(
        "launch-check",
        "--repo-root",
        str(repo),
        "--output",
        str(out_path),
    )
    assert result.returncode == 2
    payload = json.loads(out_path.read_text())
    assert payload["launch_go"] is False
    assert payload["checks"]["wallet_ready"] is False
    assert "fresh_pull_required" in payload["blocked_reasons"]


def test_build_hour0_plan_writes_valid_quote_intents(tmp_path: Path) -> None:
    repo = tmp_path
    signals = repo / "signals.json"
    markets = repo / "markets.json"
    signals.write_text(
        json.dumps(
            [
                {
                    "market_id": "m1",
                    "direction": "buy_yes",
                    "edge": 0.12,
                    "fill_prob": 0.6,
                    "velocity_multiplier": 1.2,
                    "wallet_confidence": 0.8,
                    "toxicity_penalty": 0.9,
                }
            ]
        )
    )
    markets.write_text(
        json.dumps(
            [
                {
                    "market_id": "m1",
                    "question": "Will BTC close up?",
                    "yes_price": 0.45,
                    "no_price": 0.55,
                    "resolution_hours": 0.5,
                    "spread": 0.02,
                    "liquidity_usd": 1000.0,
                    "toxicity": 0.2,
                }
            ]
        )
    )

    out_path = repo / "reports" / "hour0.json"
    result = _run(
        "build-hour0-plan",
        "--signals-json",
        str(signals),
        "--markets-json",
        str(markets),
        "--bankroll-usd",
        "100",
        "--output",
        str(out_path),
    )
    assert result.returncode == 0
    payload = json.loads(out_path.read_text())
    assert payload["all_quotes_valid"] is True
    assert len(payload["quote_intents"]) == 3
    assert all(intent["post_only"] is True for intent in payload["quote_intents"])
