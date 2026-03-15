from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.remote_cycle_launch_packet import build_canonical_launch_packet  # noqa: E402
from tests._remote_cycle_status_shared import _write_finance_latest  # noqa: E402


def _runtime_truth_snapshot(now: datetime) -> dict:
    return {
        "generated_at": now.isoformat(),
        "service_state": "running",
        "agent_run_mode": "shadow",
        "execution_mode": "shadow",
        "paper_trading": True,
        "allow_order_submission": False,
        "order_submit_enabled": False,
        "launch_posture": "blocked",
        "root_tests": {"status": "passing"},
        "service": {
            "status": "running",
            "systemctl_state": "active",
            "checked_at": now.isoformat(),
        },
        "capital": {"deployed_capital_usd": 17.58},
        "polymarket_wallet": {"free_collateral_usd": 368.53},
        "launch": {
            "posture": "blocked",
            "live_launch_blocked": True,
            "blocked_checks": ["no_closed_trades", "finance_gate_blocked"],
            "blocked_reasons": ["no_closed_trades", "finance_gate_blocked"],
        },
        "deployment_confidence": {"overall_score": 0.49, "confidence_label": "high"},
        "btc5_selected_package": {
            "selected_best_profile_name": "active_profile",
            "selected_active_profile_name": "current_live_profile",
            "selected_package_confidence_label": "high",
            "selected_deploy_recommendation": "shadow_only",
            "validation_live_filled_rows": 205,
            "generalization_ratio": 1.0099,
        },
        "state_improvement": {
            "strategy_recommendations": {
                "truth_lattice": {
                    "repair_branch_required": False,
                    "broken_reasons": [],
                },
                "public_performance_scoreboard": {},
                "btc5_forecast_confidence": {},
            },
            "improvement_velocity": {"deltas": {}},
        },
        "artifacts": {},
    }


def test_build_canonical_launch_packet_allows_bounded_stage1_restart_without_new_spend(
    tmp_path: Path,
) -> None:
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
    launch_checklist = tmp_path / "docs" / "ops" / "TRADING_LAUNCH_CHECKLIST.md"
    launch_checklist.parent.mkdir(parents=True, exist_ok=True)
    launch_checklist.write_text("checklist\n")

    packet = build_canonical_launch_packet(
        root=tmp_path,
        runtime_truth_snapshot=_runtime_truth_snapshot(now),
        launch_checklist_path=launch_checklist.relative_to(tmp_path),
    )

    assert packet["finance_gate"]["pass"] is True
    assert packet["finance_gate"]["treasury_pass"] is False
    assert packet["finance_gate"]["capital_expansion_only_hold"] is True
    assert packet["bounded_stage1_restart"]["eligible"] is True
    assert packet["launch_verdict"]["allow_execution"] is True
    assert packet["launch_verdict"]["reason"] == "clear_bounded_stage1_restart"
    assert "no_closed_trades" not in packet["mandatory_outputs"]["block_reasons"]
    assert all(
        not str(reason).startswith("finance_gate_blocked:")
        for reason in packet["mandatory_outputs"]["block_reasons"]
    )


def test_build_canonical_launch_packet_keeps_real_treasury_block_in_place(tmp_path: Path) -> None:
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
    launch_checklist = tmp_path / "docs" / "ops" / "TRADING_LAUNCH_CHECKLIST.md"
    launch_checklist.parent.mkdir(parents=True, exist_ok=True)
    launch_checklist.write_text("checklist\n")

    packet = build_canonical_launch_packet(
        root=tmp_path,
        runtime_truth_snapshot=_runtime_truth_snapshot(now),
        launch_checklist_path=launch_checklist.relative_to(tmp_path),
    )

    assert packet["finance_gate"]["pass"] is False
    assert packet["bounded_stage1_restart"]["eligible"] is True
    assert packet["launch_verdict"]["allow_execution"] is False
    assert packet["launch_verdict"]["reason"] == "blocked_by_finance_gate"


def test_build_canonical_launch_packet_uses_verification_when_root_tests_missing(
    tmp_path: Path,
) -> None:
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
    launch_checklist = tmp_path / "docs" / "ops" / "TRADING_LAUNCH_CHECKLIST.md"
    launch_checklist.parent.mkdir(parents=True, exist_ok=True)
    launch_checklist.write_text("checklist\n")
    snapshot = _runtime_truth_snapshot(now)
    snapshot.pop("root_tests", None)
    snapshot["verification"] = {"status": "passing"}

    packet = build_canonical_launch_packet(
        root=tmp_path,
        runtime_truth_snapshot=snapshot,
        launch_checklist_path=launch_checklist.relative_to(tmp_path),
    )

    assert packet["bounded_stage1_restart"]["eligible"] is True
    assert packet["launch_verdict"]["allow_execution"] is True
    assert packet["launch_verdict"]["reason"] == "clear_bounded_stage1_restart"
