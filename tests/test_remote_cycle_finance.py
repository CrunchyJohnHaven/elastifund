from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.remote_cycle_finance import build_finance_gate_status, load_finance_gate_status  # noqa: E402
from tests._remote_cycle_status_shared import _write_finance_latest  # noqa: E402


def test_load_finance_gate_status_allows_launch_for_hold_no_spend_stage_one(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_finance_latest(
        tmp_path,
        generated_at=now,
        finance_gate_pass=False,
        reason="hold_no_spend:wallet_flow_vs_llm_not_ready",
        status="hold",
        retry_in_minutes=15,
        finance_state="hold_no_spend",
        stage_cap=1,
    )

    status = load_finance_gate_status(tmp_path)

    assert status["available"] is True
    assert status["finance_gate_pass"] is True
    assert status["treasury_gate_pass"] is False
    assert status["capital_expansion_only_hold"] is True
    assert status["finance_state"] == "hold_no_spend"
    assert status["stage_cap"] == 1


def test_load_finance_gate_status_preserves_real_treasury_block(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_finance_latest(
        tmp_path,
        generated_at=now,
        finance_gate_pass=False,
        reason="destination_not_whitelisted",
        status="hold_repair",
        retry_in_minutes=30,
        finance_state="hold_repair",
        stage_cap=0,
    )

    status = load_finance_gate_status(tmp_path)

    assert status["finance_gate_pass"] is False
    assert status["treasury_gate_pass"] is False
    assert status["capital_expansion_only_hold"] is False
    assert status["reason"] == "destination_not_whitelisted"


def test_load_finance_gate_status_uses_explicit_hold_flag_when_stage_cap_is_top_level_only(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports" / "finance"
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "finance_gate_pass": True,
        "capital_expansion_only_hold": True,
        "stage_cap": 1,
        "finance_state": "hold_no_spend",
        "finance_gate": {
            "pass": True,
            "capital_expansion_only_hold": True,
            "stage_cap": 1,
        },
        "last_execute": {
            "finance_gate_pass": False,
            "requested_mode": "live_treasury",
        },
    }
    (reports_dir / "latest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    status = load_finance_gate_status(tmp_path)

    assert status["finance_gate_pass"] is True
    assert status["treasury_gate_pass"] is False
    assert status["capital_expansion_only_hold"] is True
    assert status["stage_cap"] == 1


def test_build_finance_gate_status_keeps_baseline_pass_when_expansion_is_hold_no_spend(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _write_finance_latest(
        tmp_path,
        generated_at=now,
        finance_gate_pass=True,
        reason="hold_no_spend:stage_upgrade_blocked",
        status="hold",
        retry_in_minutes=15,
        finance_state="hold_no_spend",
        stage_cap=1,
    )

    status = build_finance_gate_status(root=tmp_path)

    assert status["status"] == "pass"
    assert status["finance_gate_pass"] is True
    assert status["baseline_live_trading_pass"] is True
    assert status["capital_expansion_only_hold"] is True
    assert status["max_live_stage_cap"] == 1


def test_load_finance_gate_status_normalizes_legacy_lane_names_and_bankroll_sleeves(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports" / "finance"
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "finance_gate_pass": True,
        "treasury_gate_pass": False,
        "capital_expansion_only_hold": True,
        "finance_state": "hold_no_spend",
        "allocation_contract": {
            "max_live_stage_cap": 1,
        },
        "verdict": {
            "btc5_live_baseline": "baseline_allowed",
            "weather": "shadow_only",
            "everything_else": "blocked",
        },
        "bankroll": {
            "sleeves": {
                "btc5_live_baseline": {
                    "lane_id": "btc5_live_baseline",
                    "approved_live_budget_usd": 25.0,
                    "trade_size_cap_usd": 5.0,
                },
                "weather_shadow_only": {
                    "lane_id": "weather_shadow_only",
                    "approved_live_budget_usd": 0.0,
                },
                "everything_else_no_spend": {
                    "lane_id": "everything_else_no_spend",
                    "approved_live_budget_usd": 0.0,
                },
            }
        },
    }
    (reports_dir / "latest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    status = load_finance_gate_status(tmp_path)

    assert status["finance_lane_verdicts"]["maker_bootstrap_live"] == "baseline_allowed"
    assert status["finance_lane_verdicts"]["weather"] == "shadow_only"
    assert status["finance_lane_verdicts"]["everything_else"] == "blocked"
    assert status["finance_lane_budgets"]["maker_bootstrap_live"]["lane_id"] == "maker_bootstrap_live"
    assert status["finance_lane_budgets"]["weather"]["lane_id"] == "weather"
    assert status["finance_lane_budgets"]["everything_else"]["lane_id"] == "everything_else"
    assert status["max_live_stage_cap"] == 1
