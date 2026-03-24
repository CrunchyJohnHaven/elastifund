from __future__ import annotations

import json
from pathlib import Path

import scripts.btc5_rollout as rollout_module
from scripts.btc5_rollout import (
    RolloutDecision,
    build_rollout_artifact,
    evaluate_post_deploy,
    render_selected_runtime_override_env,
    render_stage_env,
    select_rollout_decision,
)


def test_select_rollout_decision_allows_bounded_live_stage1() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": False,
            "rollout_checks": {"baseline_live_permission_consensus": True},
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": False,
                    "order_submit_enabled": True,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": True,
                },
                "live_order_submission_allowed": True,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": 6.25}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "medium",
                "confirmation_coverage_sufficient": True,
                "validated_package": {"validated_for_live_stage1": True},
            },
            "btc5_selected_package": {
                "selected_deploy_recommendation": "promote",
                "selected_package_confidence_label": "medium",
                "validation_live_filled_rows": 12,
                "generalization_ratio": 0.70,
            },
        }
    )

    assert decision.deploy_mode == "live_stage1"
    assert decision.paper_trading is False
    assert decision.desired_stage == 1
    assert decision.shipped_mode == "live_stage1"


def test_select_rollout_decision_falls_back_to_shadow_probe_when_truth_blocks_live() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "blocked",
            "allow_order_submission": False,
            "paper_trading": True,
            "rollout_checks": {"baseline_live_permission_consensus": False},
            "accounting_reconciliation": {"drift_detected": True},
            "launch_packet": {
                "launch_verdict": {"posture": "blocked"},
                "contract": {
                    "allow_order_submission": False,
                    "paper_trading": True,
                    "order_submit_enabled": False,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": False,
                    "allow_order_submission": False,
                    "paper_trading_disabled": False,
                },
                "live_order_submission_allowed": False,
            },
            "btc5_stage_readiness": {
                "allowed_stage": 0,
                "can_trade_now": False,
            },
            "deployment_confidence": {
                "allowed_stage": 0,
                "can_btc5_trade_now": False,
                "confidence_label": "low",
                "validated_package": {"validated_for_live_stage1": False},
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert decision.paper_trading is True
    assert "truth_surface_blocks_live_stage_1" in decision.rationale


def test_select_rollout_decision_blocks_live_when_selected_package_is_not_validated() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": False,
            "rollout_checks": {"baseline_live_permission_consensus": True},
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": False,
                    "order_submit_enabled": True,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": True,
                },
                "live_order_submission_allowed": True,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": 4.0}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "high",
                "confirmation_coverage_sufficient": True,
                "validated_package": {"validated_for_live_stage1": False},
            },
            "btc5_selected_package": {
                "selected_deploy_recommendation": "promote",
                "selected_package_confidence_label": "high",
                "validation_live_filled_rows": 12,
                "generalization_ratio": 0.9,
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "validated_btc5_package_not_ready_for_live_stage1" in decision.rationale


def test_select_rollout_decision_blocks_legacy_baseline_override_without_package_green() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": False,
            "rollout_checks": {"baseline_live_permission_consensus": True},
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": False,
                    "order_submit_enabled": True,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": True,
                },
                "live_order_submission_allowed": True,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": -2.5}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "low",
                "validated_package": {"validated_for_live_stage1": False},
            },
            "btc5_selected_package": {
                "selected_deploy_recommendation": "hold",
                "selected_package_confidence_label": "low",
                "validation_live_filled_rows": 140,
                "generalization_ratio": 0.92,
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "selected_runtime_package_not_promote" in decision.rationale
    assert "trailing_12_live_filled_not_positive" in decision.rationale


def test_select_rollout_decision_blocks_when_launch_packet_keeps_paper_trading() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": True,
            "rollout_checks": {"baseline_live_permission_consensus": True},
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": True,
                    "order_submit_enabled": True,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": False,
                },
                "live_order_submission_allowed": False,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": 3.5}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "medium",
                "confirmation_coverage_sufficient": True,
                "validated_package": {"validated_for_live_stage1": True},
            },
            "btc5_selected_package": {
                "selected_deploy_recommendation": "promote",
                "selected_package_confidence_label": "medium",
                "validation_live_filled_rows": 12,
                "generalization_ratio": 0.75,
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "launch_packet_keeps_paper_trading_enabled" in decision.rationale


def test_select_rollout_decision_blocks_when_launch_packet_disables_order_submit() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": False,
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": False,
                    "order_submit_enabled": False,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": True,
                },
                "live_order_submission_allowed": False,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": 4.25}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "medium",
                "confirmation_coverage_sufficient": True,
                "validated_package": {"validated_for_live_stage1": True},
            },
            "btc5_selected_package": {
                "selected_deploy_recommendation": "promote",
                "selected_package_confidence_label": "medium",
                "validation_live_filled_rows": 12,
                "generalization_ratio": 0.82,
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "launch_packet_order_submit_disabled" in decision.rationale
    assert "launch_packet_does_not_permit_live_submission" in decision.rationale


def test_select_rollout_decision_blocks_frontier_restart_override_without_promote_gate() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": False,
            "rollout_checks": {"baseline_live_permission_consensus": True},
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": False,
                    "order_submit_enabled": True,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": True,
                },
                "live_order_submission_allowed": True,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": 10.0}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "high",
                "confirmation_coverage_sufficient": True,
                "validated_package": {"validated_for_live_stage1": True},
            },
            "btc5_selected_package": {
                "selected_best_profile_name": "active_profile",
                "selected_active_profile_name": "current_live_profile",
                "selected_package_confidence_label": "high",
                "selected_deploy_recommendation": "shadow_only",
                "validation_live_filled_rows": 205,
                "generalization_ratio": 1.0099,
                "stage1_live_candidate": True,
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "selected_runtime_package_not_promote" in decision.rationale


def test_select_rollout_decision_blocks_when_confirmation_or_trailing_pnl_fail() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": False,
            "rollout_checks": {"baseline_live_permission_consensus": True},
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": False,
                    "order_submit_enabled": True,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": True,
                },
                "live_order_submission_allowed": True,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": -1.0}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "high",
                "confirmation_coverage_sufficient": False,
                "validated_package": {"validated_for_live_stage1": True},
            },
            "btc5_selected_package": {
                "selected_package_confidence_label": "high",
                "selected_deploy_recommendation": "promote",
                "validation_live_filled_rows": 205,
                "generalization_ratio": 1.0099,
                "stage1_live_candidate": True,
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "confirmation_coverage_insufficient" in decision.rationale
    assert "trailing_12_live_filled_not_positive" in decision.rationale


def test_select_rollout_decision_blocks_when_generalization_ratio_is_below_floor() -> None:
    decision = select_rollout_decision(
        {
            "launch_posture": "clear",
            "allow_order_submission": True,
            "paper_trading": False,
            "accounting_reconciliation": {"drift_detected": False},
            "launch_packet": {
                "launch_verdict": {"posture": "clear"},
                "contract": {
                    "allow_order_submission": True,
                    "paper_trading": False,
                    "order_submit_enabled": True,
                },
                "submission_contract_consensus": {
                    "launch_posture_clear": True,
                    "allow_order_submission": True,
                    "paper_trading_disabled": True,
                },
                "live_order_submission_allowed": True,
            },
            "btc_5min_maker": {"intraday_live_summary": {"recent_12_pnl_usd": 2.0}},
            "btc5_stage_readiness": {
                "allowed_stage": 1,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 1,
                "can_btc5_trade_now": True,
                "confidence_label": "medium",
                "confirmation_coverage_sufficient": True,
                "validated_package": {"validated_for_live_stage1": True},
            },
            "btc5_selected_package": {
                "selected_deploy_recommendation": "promote",
                "selected_package_confidence_label": "medium",
                "validation_live_filled_rows": 12,
                "generalization_ratio": 0.69,
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "selected_runtime_package_generalization_below_0.70" in decision.rationale


def test_render_stage_env_preserves_numeric_caps_and_sets_mode_fields() -> None:
    decision = RolloutDecision(
        deploy_mode="shadow_probe",
        paper_trading=True,
        desired_stage=1,
        allowed_stage=0,
        confidence_label="low",
        can_trade_now=False,
        rationale=("truth_surface_blocks_live_stage_1",),
    )

    env_text = render_stage_env(
        {
            "BTC5_BANKROLL_USD": "1250",
            "BTC5_RISK_FRACTION": "0.02",
            "BTC5_MAX_TRADE_USD": "10",
            "BTC5_MIN_TRADE_USD": "5",
            "BTC5_DAILY_LOSS_LIMIT_USD": "250",
        },
        decision,
    )

    assert "BTC5_DEPLOY_MODE=shadow_probe" in env_text
    assert "BTC5_PAPER_TRADING=true" in env_text
    assert "BTC5_CAPITAL_STAGE=1" in env_text
    assert "BTC5_BANKROLL_USD=1250" in env_text
    assert "BTC5_DAILY_LOSS_LIMIT_USD=250" in env_text


def test_render_stage_env_defaults_to_micro_live_budget_and_daily_stop() -> None:
    decision = RolloutDecision(
        deploy_mode="shadow_probe",
        paper_trading=True,
        desired_stage=1,
        allowed_stage=0,
        confidence_label="low",
        can_trade_now=False,
        rationale=("truth_surface_blocks_live_stage_1",),
    )

    env_text = render_stage_env({}, decision)

    assert "BTC5_BANKROLL_USD=250" in env_text
    assert "BTC5_DAILY_LOSS_LIMIT_USD=25" in env_text
    assert "BTC5_STAGE1_DAILY_LOSS_LIMIT_USD=25" in env_text


def test_render_selected_runtime_override_env_uses_frontier_winner_package() -> None:
    decision = RolloutDecision(
        deploy_mode="live_stage1",
        paper_trading=False,
        desired_stage=1,
        allowed_stage=1,
        confidence_label="high",
        can_trade_now=True,
        rationale=("bounded_live_restart_override",),
    )

    env_text = render_selected_runtime_override_env(
        decision=decision,
        cycle_payload={
            "runtime_package_selection": {"selection_reason": "frontier_policy_loss"},
            "selected_best_runtime_package": {
                "profile": {
                    "name": "active_profile",
                    "max_abs_delta": 0.00015,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [],
            },
        },
    )

    assert env_text is not None
    assert "candidate=active_profile" in env_text
    assert "reason=frontier_policy_loss" in env_text
    assert "BTC5_MAX_ABS_DELTA=0.00015" in env_text
    assert "BTC5_UP_MAX_BUY_PRICE=0.49" in env_text
    assert "BTC5_DOWN_MAX_BUY_PRICE=0.51" in env_text


def test_render_selected_runtime_override_env_lowers_conflicting_min_buy_price(
    tmp_path: Path,
    monkeypatch,
) -> None:
    decision = RolloutDecision(
        deploy_mode="live_stage1",
        paper_trading=False,
        desired_stage=1,
        allowed_stage=1,
        confidence_label="high",
        can_trade_now=True,
        rationale=("bounded_live_restart_override",),
    )
    stage_env = tmp_path / "btc5_capital_stage.env"
    stage_env.write_text("BTC5_MIN_BUY_PRICE=0.50\n", encoding="utf-8")
    monkeypatch.setattr(rollout_module, "STAGE_ENV_PATH", stage_env)
    monkeypatch.setattr(rollout_module, "REPO_ROOT", tmp_path)

    env_text = render_selected_runtime_override_env(
        decision=decision,
        cycle_payload={
            "runtime_package_selection": {"selection_reason": "frontier_policy_loss"},
            "selected_best_runtime_package": {
                "profile": {
                    "name": "active_profile",
                    "max_abs_delta": 0.00015,
                    "up_max_buy_price": 0.49,
                    "down_max_buy_price": 0.51,
                },
                "session_policy": [],
            },
        },
    )

    assert env_text is not None
    assert "BTC5_MIN_BUY_PRICE=0.49" in env_text


def test_evaluate_post_deploy_requires_fresh_probe_and_matching_mode() -> None:
    decision = RolloutDecision(
        deploy_mode="shadow_probe",
        paper_trading=True,
        desired_stage=1,
        allowed_stage=0,
        confidence_label="low",
        can_trade_now=False,
        rationale=("truth_surface_blocks_live_stage_1",),
    )

    validation = evaluate_post_deploy(
        decision=decision,
        activation={
            "service_status": "running",
            "deploy_mode": "live_stage1",
            "paper_trading": False,
            "stage_in_effect": {"capital_stage": 2},
            "status_summary": {"rows": 10},
            "verification_checks": {"required_passed": False},
        },
        remote_cycle_status={
            "accounting_reconciliation": {
                "source_confidence_freshness": {
                    "btc_5min_maker": {
                        "freshness": "stale",
                        "checked_at": "2026-03-10T15:49:24+00:00",
                    }
                }
            }
        },
        remote_service_status={"status": "stopped"},
        deploy_returncode=1,
    )

    assert validation["valid"] is False
    assert validation["rollback_required"] is True
    assert "deploy_command_failed" in validation["critical_errors"]
    assert "activation_checks_failed" in validation["critical_errors"]
    assert "service_not_running" in validation["critical_errors"]
    assert "stage_mismatch" in validation["critical_errors"]
    assert "deploy_mode_mismatch" in validation["critical_errors"]
    assert "paper_mode_mismatch" in validation["critical_errors"]
    assert "remote_probe_not_fresh" in validation["critical_errors"]


def test_evaluate_post_deploy_rolls_back_live_when_launch_packet_regresses() -> None:
    decision = RolloutDecision(
        deploy_mode="live_stage1",
        paper_trading=False,
        desired_stage=1,
        allowed_stage=1,
        confidence_label="medium",
        can_trade_now=True,
        rationale=("launch_packet_and_btc5_package_gates_green",),
    )

    validation = evaluate_post_deploy(
        decision=decision,
        activation={
            "service_status": "running",
            "deploy_mode": "live_stage1",
            "paper_trading": False,
            "stage_in_effect": {"capital_stage": 1},
            "status_summary": {"rows": 10},
            "verification_checks": {"required_passed": True},
        },
        remote_cycle_status={
            "generated_at": "2026-03-23T21:40:00+00:00",
            "data_cadence": {"stale": False, "freshness_sla_minutes": 45},
            "accounting_reconciliation": {
                "source_confidence_freshness": {
                    "btc_5min_maker": {
                        "freshness": "fresh",
                        "checked_at": "2026-03-23T21:41:00+00:00",
                    }
                }
            },
            "trade_proof": {
                "service_name": "btc-5min-maker.service",
                "source_of_truth": "remote_sqlite_probe",
                "lane_id": "maker_bootstrap_live",
                "profile_id": "current_live_profile",
                "attribution_mode": "runtime_truth",
                "fill_confirmed": False,
                "proof_status": "no_fill_yet",
            },
            "service": {"service_name": "btc-5min-maker.service"},
        },
        launch_packet={
            "launch_verdict": {
                "posture": "blocked",
                "live_launch_blocked": True,
                "allow_execution": False,
            },
            "contract": {
                "launch_posture": "blocked",
                "allow_order_submission": False,
                "order_submit_enabled": False,
                "paper_trading": True,
            },
            "submission_contract_consensus": {
                "launch_posture_clear": False,
                "allow_order_submission": False,
                "paper_trading_disabled": False,
            },
            "live_order_submission_allowed": False,
        },
        remote_service_status={"status": "running"},
        deploy_returncode=0,
    )

    assert validation["valid"] is False
    assert validation["rollback_required"] is True
    assert "post_refresh_launch_posture_not_clear" in validation["critical_errors"]
    assert "post_refresh_allow_order_submission_false" in validation["critical_errors"]
    assert "post_refresh_order_submit_disabled" in validation["critical_errors"]
    assert "post_refresh_paper_trading_enabled" in validation["critical_errors"]
    assert "post_refresh_live_submission_not_allowed" in validation["critical_errors"]
    assert "post_refresh_launch_packet_blocked" in validation["critical_errors"]


def test_build_rollout_artifact_clears_required_outputs_for_valid_live_stage1(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rollout_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        rollout_module,
        "DEFAULT_OUTPUT_PATH",
        tmp_path / "instance2_btc5_baseline" / "latest.json",
    )
    monkeypatch.setattr(
        rollout_module,
        "LEGACY_OUTPUT_PATHS",
        (
            tmp_path / "btc5_rollout_latest.json",
            tmp_path / "runtime" / "btc5" / "btc5_rollout_latest.json",
        ),
    )
    decision = RolloutDecision(
        deploy_mode="live_stage1",
        paper_trading=False,
        desired_stage=1,
        allowed_stage=1,
        confidence_label="low",
        can_trade_now=True,
        rationale=("continuous_live_baseline_override",),
    )

    payload = build_rollout_artifact(
        output_path=tmp_path / "instance2.json",
        decision=decision,
        deploy_result=None,
        backup_report=None,
        validation={
            "valid": True,
            "rollback_required": False,
            "critical_errors": [],
        },
        rollback_report=None,
        launch_packet={
            "launch_verdict": {
                "posture": "clear",
                "allow_execution": True,
                "live_launch_blocked": False,
            },
            "contract": {
                "allow_order_submission": True,
                "order_submit_enabled": True,
                "paper_trading": False,
            },
            "submission_contract_consensus": {
                "launch_posture_clear": True,
                "allow_order_submission": True,
                "paper_trading_disabled": True,
            },
            "live_order_submission_allowed": True,
        },
        remote_cycle_status={
            "btc5_baseline_live_allowed": True,
            "deployment_confidence": {"overall_score": 0.49},
            "btc5_selected_package": {
                "generated_at": "2026-03-12T02:10:42+00:00",
            },
            "btc5_stage_readiness": {
                "allowed_stage": 0,
                "ready_for_stage_1": False,
                "stage_upgrade_trade_now_blocking_checks": [
                    "trailing_12_live_filled_not_positive",
                ],
            },
            "btc5_stage_upgrade_can_trade_now": False,
        },
        remote_service_status={"status": "running"},
        finance_latest={
            "finance_gate_pass": True,
            "baseline_live_trading_pass": True,
            "capital_expansion_only_hold": True,
            "treasury_gate_pass": False,
        },
        rollout_control={
            "generated_at": "2026-03-11T15:01:51+00:00",
            "action": "repair",
            "repair_branches": [{"retry_eta_minutes": 5}],
        },
    )

    assert payload["baseline_contract"]["schema_version"] == "baseline_contract.v1"
    assert payload["baseline_contract"]["baseline_status"] == "baseline_live_ok"
    assert payload["baseline_contract"]["launch_authority_source"] == "reports/launch_packet_latest.json"
    assert payload["baseline_contract"]["stage_upgrade_status"] == "stage_upgrade_blocked"
    assert payload["baseline_contract"]["treasury_expansion_status"] == "treasury_expansion_blocked"
    assert payload["launch_authority"]["authority_green"] is True
    assert payload["required_outputs"]["block_reasons"] == [
        "stage_readiness_vs_live_baseline_mismatch",
        "capital_expansion_hold",
        "stale_promotion_artifact:reports/btc5_autoresearch/latest.json",
        "stale_promotion_artifact:reports/rollout_control/latest.json",
    ]
    assert payload["required_outputs"]["finance_gate_pass"] is True
    assert payload["required_outputs"]["candidate_delta_arr_bps"] == 60
    assert payload["required_outputs"]["expected_improvement_velocity_delta"] == 0.08
    assert payload["required_outputs"]["arr_confidence_score"] == 0.8
    assert payload["required_outputs"]["one_next_cycle_action"] == "consume baseline_guard.v1 inside autoprompt gating"
    assert payload["baseline_guard"]["control_modes"]["deploy_recommend"]["allowed_actions"][0] == (
        "recommend_maintain_live_stage1_flat_size"
    )


def test_build_rollout_artifact_updates_all_legacy_targets(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rollout_module, "REPO_ROOT", tmp_path)
    default_output = tmp_path / "instance2_btc5_baseline" / "latest.json"
    legacy_root = tmp_path / "btc5_rollout_latest.json"
    legacy_runtime = tmp_path / "runtime" / "btc5" / "btc5_rollout_latest.json"
    monkeypatch.setattr(rollout_module, "DEFAULT_OUTPUT_PATH", default_output)
    monkeypatch.setattr(rollout_module, "LEGACY_OUTPUT_PATHS", (legacy_root, legacy_runtime))

    build_rollout_artifact(
        output_path=tmp_path / "custom" / "instance2.json",
        decision=RolloutDecision(
            deploy_mode="live_stage1",
            paper_trading=False,
            desired_stage=1,
            allowed_stage=1,
            confidence_label="medium",
            can_trade_now=True,
            rationale=("explicit_baseline_live_contract_override",),
        ),
        deploy_result=None,
        backup_report=None,
        validation={"valid": True, "rollback_required": False, "critical_errors": []},
        rollback_report=None,
        launch_packet={
            "launch_verdict": {
                "posture": "clear",
                "allow_execution": True,
                "live_launch_blocked": False,
            },
            "contract": {
                "allow_order_submission": True,
                "order_submit_enabled": True,
                "paper_trading": False,
            },
            "submission_contract_consensus": {
                "launch_posture_clear": True,
                "allow_order_submission": True,
                "paper_trading_disabled": True,
            },
            "live_order_submission_allowed": True,
        },
        remote_cycle_status={
            "btc5_selected_package": {
                "selected_best_profile_name": "active_profile_probe_d0_00075",
                "selected_active_profile_name": "active_profile",
                "selected_deploy_recommendation": "shadow_only",
                "selected_package_confidence_label": "high",
                "selection_source": "reports/parallel/btc5_probe_cycle_d0_00075.json",
                "runtime_package_loaded": True,
                "runtime_load_required": False,
                "validated_for_live_stage1": False,
            }
        },
        remote_service_status={"status": "running"},
        finance_latest={"finance_gate_pass": True},
        rollout_control={},
    )

    for path in (
        tmp_path / "custom" / "instance2.json",
        default_output,
        legacy_root,
        legacy_runtime,
    ):
        payload = json.loads(path.read_text())
        assert payload["launch_authority"]["source"] == "reports/launch_packet_latest.json"
        assert payload["selected_package"]["selected_best_profile_name"] == "active_profile_probe_d0_00075"
        assert payload["selected_package"]["selected_active_profile_name"] == "active_profile"
        assert payload["selected_package"]["runtime_package_loaded"] is True
