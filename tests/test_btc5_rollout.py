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
            "btc5_stage_readiness": {
                "allowed_stage": 2,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 2,
                "can_btc5_trade_now": True,
                "confidence_label": "medium",
                "validated_package": {"validated_for_live_stage1": True},
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
            "btc5_stage_readiness": {
                "allowed_stage": 2,
                "can_trade_now": True,
            },
            "deployment_confidence": {
                "allowed_stage": 2,
                "can_btc5_trade_now": True,
                "confidence_label": "high",
                "validated_package": {"validated_for_live_stage1": False},
            },
        }
    )

    assert decision.deploy_mode == "shadow_probe"
    assert "validated_btc5_package_not_ready_for_live_stage1" in decision.rationale


def test_select_rollout_decision_allows_continuous_live_baseline_override() -> None:
    decision = select_rollout_decision(
        {
            "root_tests": {"status": "passing"},
            "service": {"status": "running"},
            "capital": {"deployed_capital_usd": 43.10},
            "runtime": {"closed_trades": 50},
            "polymarket_wallet": {"free_collateral_usd": 483.65},
            "launch": {"blocked_checks": []},
            "btc5_stage_readiness": {
                "allowed_stage": 0,
                "can_trade_now": False,
            },
            "deployment_confidence": {
                "allowed_stage": 0,
                "can_btc5_trade_now": False,
                "confidence_label": "low",
                "stage_1_blockers": [
                    "wallet_export_btc_open_markets_not_zero",
                    "stage_1_wallet_reconciliation_not_ready",
                    "btc5_forecast_not_promote_high",
                    "selected_runtime_package_not_promote",
                    "runtime_package_load_pending",
                    "validated_runtime_package_not_loaded",
                    "confirmation_coverage_insufficient",
                ],
                "validated_package": {"validated_for_live_stage1": False},
            },
            "btc_5min_maker": {"live_filled_rows": 140},
        }
    )

    assert decision.deploy_mode == "live_stage1"
    assert decision.paper_trading is False
    assert decision.allowed_stage == 1
    assert "continuous_live_baseline_override" in decision.rationale


def test_select_rollout_decision_prefers_explicit_baseline_live_contract() -> None:
    decision = select_rollout_decision(
        {
            "allow_order_submission": True,
            "root_tests": {"status": "passing"},
            "service": {"status": "running"},
            "capital": {"deployed_capital_usd": 17.58},
            "polymarket_wallet": {"free_collateral_usd": 373.31},
            "btc5_baseline_live_allowed": True,
            "btc5_stage_readiness": {
                "allowed_stage": 0,
                "can_trade_now": True,
                "baseline_live_allowed": True,
                "baseline_live_status": "unblocked",
                "trade_now_status": "unblocked",
            },
            "deployment_confidence": {
                "allowed_stage": 0,
                "can_btc5_trade_now": False,
                "confidence_label": "low",
                "baseline_live_allowed": True,
                "baseline_live_status": "unblocked",
                "validated_package": {"validated_for_live_stage1": False},
            },
        }
    )

    assert decision.deploy_mode == "live_stage1"
    assert decision.paper_trading is False
    assert "explicit_baseline_live_contract_override" in decision.rationale


def test_select_rollout_decision_allows_bounded_live_restart_override_for_frontier_winner() -> None:
    decision = select_rollout_decision(
        {
            "root_tests": {"status": "passing"},
            "service": {"status": "running"},
            "capital": {"deployed_capital_usd": 17.58},
            "polymarket_wallet": {"free_collateral_usd": 368.53},
            "launch": {
                "blocked_checks": [
                    "no_closed_trades",
                    "mode_alignment",
                    "finance_gate_blocked",
                ]
            },
            "btc5_stage_readiness": {
                "allowed_stage": 0,
                "can_trade_now": False,
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
            "deployment_confidence": {
                "allowed_stage": 0,
                "can_btc5_trade_now": False,
                "confidence_label": "low",
                "stage_1_blockers": [
                    "runtime_package_load_pending",
                    "validated_runtime_package_not_loaded",
                    "confirmation_coverage_insufficient",
                ],
                "validated_package": {"validated_for_live_stage1": False},
            },
        }
    )

    assert decision.deploy_mode == "live_stage1"
    assert decision.paper_trading is False
    assert "bounded_live_restart_override" in decision.rationale


def test_select_rollout_decision_allows_bounded_live_restart_with_stale_stage1_telemetry() -> None:
    decision = select_rollout_decision(
        {
            "root_tests": {"status": "passing"},
            "service": {"status": "running"},
            "capital": {"deployed_capital_usd": 17.58},
            "polymarket_wallet": {"free_collateral_usd": 368.53},
            "launch": {
                "blocked_checks": [
                    "no_closed_trades",
                    "mode_alignment",
                ]
            },
            "btc5_stage_readiness": {
                "allowed_stage": 0,
                "can_trade_now": False,
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
            "deployment_confidence": {
                "allowed_stage": 0,
                "can_btc5_trade_now": False,
                "confidence_label": "low",
                "stage_1_blockers": [
                    "wallet_reconciliation_stale",
                    "trailing_12_live_filled_not_positive",
                    "runtime_package_load_pending",
                    "validated_runtime_package_not_loaded",
                    "confirmation_coverage_insufficient",
                ],
                "validated_package": {"validated_for_live_stage1": False},
            },
        }
    )

    assert decision.deploy_mode == "live_stage1"
    assert decision.paper_trading is False
    assert "bounded_live_restart_override" in decision.rationale


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
    assert payload["baseline_contract"]["stage_upgrade_status"] == "stage_upgrade_blocked"
    assert payload["baseline_contract"]["treasury_expansion_status"] == "treasury_expansion_blocked"
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
        assert payload["selected_package"]["selected_best_profile_name"] == "active_profile_probe_d0_00075"
        assert payload["selected_package"]["selected_active_profile_name"] == "active_profile"
        assert payload["selected_package"]["runtime_package_loaded"] is True
