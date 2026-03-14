from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.remote_cycle_reconciliation import (  # noqa: E402
    apply_canonical_launch_packet,
    apply_canonical_launch_packet_to_status,
)


def _runtime_truth_snapshot(now: datetime) -> dict:
    return {
        "generated_at": now.isoformat(),
        "service_state": "running",
        "agent_run_mode": "live",
        "execution_mode": "live",
        "paper_trading": False,
        "allow_order_submission": True,
        "order_submit_enabled": True,
        "launch_posture": "clear",
        "service": {
            "status": "running",
            "service_name": "btc-5min-maker.service",
            "checked_at": now.isoformat(),
        },
        "launch": {
            "posture": "clear",
            "live_launch_blocked": False,
            "blocked_checks": [],
            "blocked_reasons": [],
        },
        "launch_state": {"stage": {}},
        "drift": {"detected": False, "reasons": []},
        "summary": {},
        "btc5_stage_readiness": {
            "stage_upgrade_trade_now_blocking_checks": [
                "wallet_export_stale",
                "selected_runtime_package_stale",
                "confirmation_coverage_insufficient",
            ],
            "wallet_export_freshness_hours": 25.2,
            "probe_freshness_hours": 15.8,
            "current_probe_artifact": "reports/btc5_autoresearch_current_probe/latest.json",
            "source_artifact": "reports/strategy_scale_comparison.json",
        },
        "btc5_selected_package": {
            "age_hours": 11.4,
            "path": "reports/autoresearch/btc5_policy/latest.json",
            "selection_source": "reports/parallel/btc5_probe_cycle_d0_00075.json",
        },
        "deployment_confidence": {
            "stage_upgrade_can_trade_now": False,
            "stage_1_blockers": [
                "wallet_export_stale",
                "selected_runtime_package_stale",
                "confirmation_coverage_insufficient",
            ],
            "blocking_checks": [
                "wallet_export_stale",
                "selected_runtime_package_stale",
                "confirmation_coverage_insufficient",
            ],
        },
        "accounting_reconciliation": {"drift_detected": False},
        "state_improvement": {
            "strategy_recommendations": {
                "wallet_reconciliation_summary": {
                    "source_artifact": "reports/wallet_export_latest.csv",
                    "source_age_hours": 25.2,
                },
                "btc5_candidate_recovery": {"generated_at": now.isoformat()},
                "champion_lane_contract": {
                    "status": "hold_repair",
                    "decision_reason": "truth_surface_repair_required_before_champion_lane_can_run",
                    "champion_lane": {"selected_profile_name": "active_profile"},
                    "finance_gate": {"retry_in_minutes": None},
                    "blocker_classes": {
                        "truth": {"checks": ["wallet_export_stale"], "status": "blocked"},
                        "candidate": {
                            "checks": ["selected_runtime_package_stale"],
                            "status": "blocked",
                        },
                        "confirmation": {
                            "checks": ["confirmation_coverage_insufficient"],
                            "status": "blocked",
                        },
                        "capital": {"checks": [], "status": "clear"},
                    },
                    "required_outputs": {
                        "arr_confidence_score": 0.64,
                        "candidate_delta_arr_bps": 20.0,
                        "expected_improvement_velocity_delta": 0.03,
                        "finance_gate_pass": True,
                        "block_reasons": [
                            "wallet_export_stale",
                            "selected_runtime_package_stale",
                            "confirmation_coverage_insufficient",
                        ],
                        "one_next_cycle_action": "repair stale artifacts before promotion",
                    },
                },
            }
        },
    }


def _launch_packet(now: datetime) -> dict:
    return {
        "artifact": "launch_packet",
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "launch_verdict": {
            "posture": "clear",
            "allow_execution": True,
            "drift_kill_gate_triggered": False,
            "live_launch_blocked": False,
            "reason": "clear",
        },
        "contract": {
            "service_state": "running",
            "agent_run_mode": "live",
            "execution_mode": "live",
            "paper_trading": False,
            "allow_order_submission": True,
            "order_submit_enabled": True,
            "failed_checks": [],
            "checks": [],
        },
        "launch_state": {"stage": {}},
        "mandatory_outputs": {
            "candidate_delta_arr_bps": 20.0,
            "expected_improvement_velocity_delta": 0.03,
            "arr_confidence_score": 0.64,
            "block_reasons": [],
            "finance_gate_pass": True,
            "treasury_gate_pass": False,
            "one_next_cycle_action": "continue baseline live",
        },
    }


def test_apply_canonical_launch_packet_splits_permissions_and_emits_stale_hold_repair(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot = _runtime_truth_snapshot(now)
    launch_packet = _launch_packet(now)

    reconciled = apply_canonical_launch_packet(
        snapshot,
        root=tmp_path,
        launch_packet=launch_packet,
        launch_packet_latest_path=Path("reports/launch_packet_latest.json"),
        launch_packet_timestamped_path=Path("reports/runtime/launch_packets/launch_packet_test.json"),
    )

    assert reconciled["baseline_live_allowed"] is True
    assert reconciled["stage_upgrade_allowed"] is False
    assert reconciled["capital_expansion_allowed"] is False
    assert reconciled["state_permissions"] == {
        "baseline_live_allowed": True,
        "stage_upgrade_allowed": False,
        "capital_expansion_allowed": False,
    }

    stale_hold_repair = reconciled["stale_hold_repair"]
    assert stale_hold_repair["active"] is True
    assert stale_hold_repair["status"] == "hold_repair"
    assert stale_hold_repair["retry_in_minutes"] == 10
    assert any(
        branch["check"] == "wallet_export_stale"
        and branch["source"] == "reports/wallet_export_latest.csv"
        and branch["age_hours"] == 25.2
        for branch in stale_hold_repair["repair_branches"]
    )
    assert any(
        str(reason).startswith(
            "hold_repair:wallet_export_stale:source=reports/wallet_export_latest.csv:age_hours=25.2000:retry_in_minutes=10"
        )
        for reason in stale_hold_repair["block_reasons"]
    )

    champion = reconciled["state_improvement"]["strategy_recommendations"]["champion_lane_contract"]
    assert champion["status"] == "candidate_ready"
    assert champion["blocker_classes"]["truth"]["checks"] == []
    assert any(
        str(reason).startswith("hold_repair:selected_runtime_package_stale:")
        for reason in champion["required_outputs"]["block_reasons"]
    )

    rollout_checks = reconciled["rollout_checks"]
    assert rollout_checks["baseline_live_permission_consensus"] is True
    assert rollout_checks["launch_packet_allows_baseline_live"] is True
    assert rollout_checks["runtime_truth_allows_baseline_live"] is True
    assert rollout_checks["finance_packet_allows_baseline_live"] is True
    assert rollout_checks["mismatches"] == []

    assert launch_packet["state_permissions"]["baseline_live_allowed"] is True
    assert launch_packet["state_permissions"]["stage_upgrade_allowed"] is False
    assert launch_packet["state_permissions"]["capital_expansion_allowed"] is False
    assert launch_packet["stale_hold_repair"]["active"] is True
    assert launch_packet["hold_repair"] == launch_packet["stale_hold_repair"]
    assert reconciled["service_name"] == "btc-5min-maker.service"
    assert reconciled["service_name_resolution"] == "observed_service_probe"
    assert reconciled["baseline_live_trading_pass"] is True
    assert reconciled["capital_expansion_only_hold"] is True
    assert reconciled["operator_verdict"]["code"] == "continue_bounded_live"
    assert reconciled["launch_operator_verdict"] == "continue_bounded_live"
    assert reconciled["hold_repair"] == reconciled["stale_hold_repair"]
    assert reconciled["candidate_delta_arr_bps"] == 20.0
    assert reconciled["expected_improvement_velocity_delta"] == 0.03
    assert reconciled["arr_confidence_score"] == 0.64
    assert any(
        str(reason).startswith("hold_repair:wallet_export_stale:")
        for reason in reconciled["block_reasons"]
    )
    assert reconciled["finance_gate_pass"] is True
    assert reconciled["required_outputs"] == {
        "candidate_delta_arr_bps": 20.0,
        "expected_improvement_velocity_delta": 0.03,
        "arr_confidence_score": 0.64,
        "block_reasons": reconciled["block_reasons"],
        "finance_gate_pass": True,
        "treasury_gate_pass": False,
        "one_next_cycle_action": reconciled["one_next_cycle_action"],
    }
    assert launch_packet["service_name"] == "btc-5min-maker.service"
    assert launch_packet["service_name_resolution"] == "observed_service_probe"
    assert launch_packet["allow_order_submission"] is True
    assert launch_packet["order_submit_enabled"] is True
    assert launch_packet["canonical_live_profile_id"] == "active_profile"
    assert launch_packet["baseline_live_trading_pass"] is True
    assert launch_packet["capital_expansion_only_hold"] is True
    assert launch_packet["operator_verdict"]["code"] == "continue_bounded_live"
    assert launch_packet["one_next_cycle_action"] == reconciled["one_next_cycle_action"]
    assert (
        launch_packet["mandatory_outputs"]["one_next_cycle_action"]
        == reconciled["one_next_cycle_action"]
    )
    assert launch_packet["required_outputs"] == reconciled["required_outputs"]


def test_apply_canonical_launch_packet_emits_wallet_flow_readiness_disagreement_repair_branch(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot = _runtime_truth_snapshot(now)
    snapshot["btc5_stage_readiness"]["stage_upgrade_trade_now_blocking_checks"] = [
        "wallet_flow_vs_llm_not_ready"
    ]
    snapshot["state_improvement"]["strategy_recommendations"]["champion_lane_contract"][
        "required_outputs"
    ]["block_reasons"] = ["wallet_flow_vs_llm_not_ready"]
    snapshot["state_improvement"]["strategy_recommendations"]["control_plane_consistency"] = {
        "capital_consistency": {
            "artifacts": {
                "signal_source_audit": {
                    "path": "reports/runtime/signals/signal_source_audit.json",
                    "age_hours": 0.4,
                    "wallet_flow_confirmation_ready": True,
                    "confirmation_sources_ready": ["wallet_flow"],
                    "stage_upgrade_blocking_checks": ["wallet_flow_vs_llm_not_ready"],
                }
            }
        }
    }
    launch_packet = _launch_packet(now)

    reconciled = apply_canonical_launch_packet(
        snapshot,
        root=tmp_path,
        launch_packet=launch_packet,
        launch_packet_latest_path=Path("reports/launch_packet_latest.json"),
        launch_packet_timestamped_path=Path("reports/runtime/launch_packets/launch_packet_test.json"),
    )

    assert reconciled["baseline_live_allowed"] is True
    assert any(
        branch["check"] == "wallet_flow_readiness_disagreement_finance_vs_signal_source"
        for branch in reconciled["stale_hold_repair"]["repair_branches"]
    )
    assert any(
        str(reason).startswith(
            "hold_repair:wallet_flow_readiness_disagreement_finance_vs_signal_source:"
        )
        for reason in reconciled["stale_hold_repair"]["block_reasons"]
    )


def test_apply_canonical_launch_packet_falls_back_service_name_with_explicit_resolution(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot = _runtime_truth_snapshot(now)
    snapshot["service"] = {"status": "running", "checked_at": now.isoformat()}
    launch_packet = _launch_packet(now)

    reconciled = apply_canonical_launch_packet(
        snapshot,
        root=tmp_path,
        launch_packet=launch_packet,
        launch_packet_latest_path=Path("reports/launch_packet_latest.json"),
        launch_packet_timestamped_path=Path("reports/runtime/launch_packets/launch_packet_test.json"),
    )

    assert reconciled["service_name"] == "btc-5min-maker.service"
    assert (
        reconciled["service_name_resolution"]
        == "default_expected_service_non_safety_hold_repair"
    )
    assert launch_packet["service_name"] == "btc-5min-maker.service"
    assert (
        launch_packet["service_name_resolution"]
        == "default_expected_service_non_safety_hold_repair"
    )


def test_apply_canonical_launch_packet_to_status_propagates_required_outputs_and_hold_repair(
    tmp_path: Path,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    snapshot = _runtime_truth_snapshot(now)
    launch_packet = _launch_packet(now)

    reconciled = apply_canonical_launch_packet(
        snapshot,
        root=tmp_path,
        launch_packet=launch_packet,
        launch_packet_latest_path=Path("reports/launch_packet_latest.json"),
        launch_packet_timestamped_path=Path("reports/runtime/launch_packets/launch_packet_test.json"),
    )

    payload = apply_canonical_launch_packet_to_status(
        {
            "service": {"status": "running"},
            "runtime_truth": {"service": {"status": "running"}},
        },
        launch_packet=launch_packet,
    )

    assert payload["service_name"] == "btc-5min-maker.service"
    assert payload["service_name_resolution"] == "observed_service_probe"
    assert payload["hold_repair"] == payload["stale_hold_repair"]
    assert payload["operator_verdict"]["code"] == "continue_bounded_live"
    assert payload["candidate_delta_arr_bps"] == 20.0
    assert payload["expected_improvement_velocity_delta"] == 0.03
    assert payload["arr_confidence_score"] == 0.64
    assert payload["required_outputs"] == reconciled["required_outputs"]
    assert payload["runtime_truth"]["hold_repair"]["active"] is True
    assert payload["runtime_truth"]["required_outputs"] == reconciled["required_outputs"]
    assert payload["runtime_truth"]["one_next_cycle_action"] == payload["one_next_cycle_action"]
