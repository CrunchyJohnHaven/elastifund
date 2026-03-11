from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from scripts.run_btc5_autoresearch_loop import (
    _build_cycle_command,
    _cadence_decision,
    _resolved_max_cycles,
    _write_loop_reports,
    parse_args,
)


def test_build_cycle_command_includes_selected_flags() -> None:
    args = Namespace(
        db_path=Path("data/btc_5min_maker.db"),
        strategy_env=Path("config/btc5_strategy.env"),
        override_env=Path("state/btc5_autoresearch.env"),
        cycle_report_dir=Path("reports/btc5_autoresearch"),
        current_probe_latest=Path("reports/btc5_autoresearch_current_probe/latest.json"),
        service_name="btc-5min-maker.service",
        paths=2000,
        block_size=4,
        top_grid_candidates=5,
        min_replay_fills=12,
        loss_limit_usd=10.0,
        seed=42,
        include_archive_csvs=True,
        archive_glob="reports/archive/*.csv",
        refresh_remote=False,
        remote_cache_json=Path("reports/tmp_remote.json"),
        min_median_arr_improvement_pct=0.0,
        min_median_pnl_improvement_usd=2.0,
        min_replay_pnl_improvement_usd=1.0,
        max_profit_prob_drop=0.01,
        max_p95_drawdown_increase_usd=3.0,
        max_loss_hit_prob_increase=0.03,
        min_fill_lift=0,
        min_fill_retention_ratio=0.85,
        regime_max_session_overrides=2,
        regime_top_single_overrides_per_session=2,
        regime_max_composed_candidates=64,
        restart_on_promote=False,
    )
    command = _build_cycle_command(args)
    assert "--db-path" in command
    assert "--include-archive-csvs" in command
    assert "--current-probe-latest" in command
    assert "--min-median-arr-improvement-pct" in command
    assert "--regime-max-session-overrides" in command
    assert "--service-name" in command
    assert "btc-5min-maker.service" in command
    assert "--restart-on-promote" not in command


def test_write_loop_reports_accumulates_summary(tmp_path: Path) -> None:
    first_entry = {
        "started_at": "2026-03-09T18:30:00+00:00",
        "finished_at": "2026-03-09T18:30:05+00:00",
        "duration_seconds": 5.0,
        "cycle_command": ["python3", "scripts/run_btc5_autoresearch_cycle.py"],
        "cycle_returncode": 0,
        "status": "ok",
        "decision": {"action": "hold", "reason": "current_profile_is_best"},
        "best_profile": {"name": "current_live_profile"},
        "active_profile": {"name": "current_live_profile"},
        "arr": {"active_median_arr_pct": 1000.0, "best_median_arr_pct": 1000.0, "median_arr_delta_pct": 0.0},
        "active_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
        "best_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": [{"name": "open_et", "et_hours": [9]}]},
        "selected_active_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": []},
        "selected_best_runtime_package": {"profile": {"name": "current_live_profile"}, "session_policy": [{"name": "open_et", "et_hours": [9]}]},
        "selected_deploy_recommendation": "hold",
        "selected_package_confidence_label": "medium",
        "selected_package_confidence_reasons": ["validation_live_filled_rows=8", "generalization_ratio=0.8200"],
        "promoted_package_selected": True,
        "deploy_recommendation": "hold",
        "package_confidence_label": "medium",
        "package_confidence_reasons": ["validation_live_filled_rows=8", "generalization_ratio=0.8200"],
        "package_missing_evidence": ["median_arr_delta_not_positive"],
        "validation_live_filled_rows": 8,
        "generalization_ratio": 0.82,
        "public_forecast_selection": {
            "selection_reason": "selected_from_fresh_pool_by_probe_feedback_then_confidence_then_deploy_then_generated_at",
            "selected": {
                "source_artifact": "reports/btc5_autoresearch/latest.json",
                "forecast_arr_delta_pct": 20.0,
            },
        },
        "public_forecast_source_artifact": "reports/btc5_autoresearch/latest.json",
        "public_forecast_arr_delta_pct": 20.0,
        "best_live_package": {"source": "regime_best_candidate", "runtime_package": {"profile": {"name": "live_balanced"}}},
        "best_raw_research_package": {"source": "global_best_candidate", "runtime_package": {"profile": {"name": "raw_thin"}}},
        "execution_drag_summary": {"skip_price_count": 20, "order_failed_count": 19, "cancelled_unfilled_count": 3},
        "one_sided_bias_recommendation": {"recommendation": "tighten_down_and_suppress_up"},
        "size_aware_deployment": {
            "available": True,
            "recommended_live_stage_cap": 2,
            "recommended_live_trade_size_cap_usd": 20,
        },
        "current_probe": {
            "probe_freshness_hours": 0.75,
            "live_filled_rows_delta": 1,
            "validation_live_filled_rows_delta": 2,
            "stage_ready_reason_tags": ["validation_rows_growing"],
            "stage_not_ready_reason_tags": [],
        },
        "probe_feedback": {
            "effective_package_confidence_label": "medium",
            "effective_deploy_recommendation": "hold",
        },
        "probe_freshness_hours": 0.75,
        "current_probe_path": "reports/btc5_autoresearch_current_probe/latest.json",
        "cadence": {
            "mode": "accelerated",
            "reason": "new_fills_or_validation_rows_arrived",
            "base_interval_seconds": 300,
            "recommended_interval_seconds": 120,
            "live_filled_rows_delta": 1,
            "validation_live_filled_rows_delta": 2,
            "probe_freshness_hours": 0.75,
        },
        "runtime_load_status": {
            "override_env_written": True,
            "override_env_path": "state/btc5_autoresearch.env",
            "session_policy_records": 1,
            "base_env_changed": False,
            "service_restart_requested": False,
            "service_restart_state": None,
        },
        "capital_scale_recommendation": {
            "status": "test_add",
            "recommended_tranche_usd": 100,
            "reason": "high_confidence_and_trailing12_positive_but_fund_reconciliation_blocks_full_scale",
        },
        "capital_stage_recommendation": {
            "recommended_stage": 2,
            "recommended_max_trade_usd": 20,
            "stage_reason": "stage2_guardrails_passed_trailing40_12_positive_and_order_failure_below_25pct",
            "promotion_guardrails_passed": True,
        },
        "recommended_session_policy": [{"name": "open_et", "et_hours": [9, 10, 11], "max_abs_delta": 0.0001}],
        "hypothesis_lab": {"best_hypothesis": {"name": "hyp_down_open"}},
        "regime_policy_lab": {"best_policy": {"name": "policy_current_live_profile__open_et__grid_d0.00010_up0.49_down0.49"}},
        "artifacts": {},
        "hook": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }
    second_entry = {
        **first_entry,
        "started_at": "2026-03-09T18:35:00+00:00",
        "finished_at": "2026-03-09T18:35:05+00:00",
        "decision": {"action": "promote", "reason": "promotion_thresholds_met"},
        "best_profile": {"name": "grid_candidate"},
    }

    first_payload = _write_loop_reports(tmp_path, first_entry)
    second_payload = _write_loop_reports(tmp_path, second_entry)

    assert first_payload["summary"]["cycles_total"] == 1
    assert second_payload["summary"]["cycles_total"] == 2
    assert second_payload["summary"]["holds_total"] == 1
    assert second_payload["summary"]["promotions_total"] == 1

    latest_json = json.loads((tmp_path / "latest.json").read_text())
    latest_md = (tmp_path / "latest.md").read_text()
    history_lines = (tmp_path / "history.jsonl").read_text().strip().splitlines()
    assert latest_json["summary"]["cycles_total"] == 2
    assert latest_json["latest_entry"]["hypothesis_lab"]["best_hypothesis"]["name"] == "hyp_down_open"
    assert latest_json["latest_entry"]["regime_policy_lab"]["best_policy"]["name"].startswith("policy_current_live_profile")
    assert len(latest_json["latest_entry"]["recommended_session_policy"]) == 1
    assert "velocity_summary" in latest_json
    assert latest_json["decision_action"] == "promote"
    assert latest_json["decision"]["action"] == "promote"
    assert "arr" in latest_json
    assert latest_json["deploy_recommendation"] == "hold"
    assert latest_json["selected_deploy_recommendation"] == "hold"
    assert latest_json["selected_package_confidence_label"] == "medium"
    assert latest_json["promoted_package_selected"] is True
    assert latest_json["public_forecast_selection"]["selection_reason"].startswith("selected_from_fresh_pool")
    assert latest_json["runtime_load_status"]["override_env_written"] is True
    assert latest_json["best_live_package"]["source"] == "regime_best_candidate"
    assert latest_json["execution_drag_summary"]["skip_price_count"] == 20
    assert latest_json["size_aware_deployment"]["recommended_live_stage_cap"] == 2
    assert latest_json["current_probe"]["validation_live_filled_rows_delta"] == 2
    assert latest_json["cadence"]["recommended_interval_seconds"] == 120
    assert "capital_stage_recommendation" in latest_json
    assert set(latest_json["velocity_summary"]) == {"window_24h", "window_7d"}
    assert "cycles_in_window" in latest_json["velocity_summary"]["window_24h"]
    assert "forecast_arr_gain_pct_per_day" in latest_json["velocity_summary"]["window_24h"]
    assert "Last best hypothesis" in latest_md
    assert "Last best regime policy" in latest_md
    assert "Last best session policy records" in latest_md
    assert "Last package decision" in latest_md
    assert "Last package confidence" in latest_md
    assert "Last public forecast source" in latest_md
    assert "Last best live package source" in latest_md
    assert "Last best raw package source" in latest_md
    assert "Last one-sided bias recommendation" in latest_md
    assert "Last skip-price count" in latest_md
    assert "Last capital status" in latest_md
    assert "Last capital tranche" in latest_md
    assert "Last capital stage" in latest_md
    assert "Last capital max trade" in latest_md
    assert "Last stage guardrails passed" in latest_md
    assert "Last probe freshness hours" in latest_md
    assert "Next cadence seconds" in latest_md
    assert "Timebound Velocity" in latest_md
    assert "Last median ARR delta" in latest_md
    assert "Last runtime override written" in latest_md
    assert len(history_lines) == 2


def test_cadence_decision_accelerates_when_new_fills_arrive() -> None:
    cadence = _cadence_decision(
        entry={
            "current_probe": {
                "probe_freshness_hours": 0.5,
                "live_filled_rows_delta": 2,
                "validation_live_filled_rows_delta": 1,
            }
        },
        previous_entry=None,
        base_interval_seconds=300,
    )

    assert cadence["mode"] == "accelerated"
    assert cadence["recommended_interval_seconds"] < 300
    assert cadence["reason"] == "new_fills_or_validation_rows_arrived"


def test_cadence_decision_slows_when_no_new_evidence_arrives() -> None:
    cadence = _cadence_decision(
        entry={
            "current_probe": {
                "probe_freshness_hours": 7.5,
                "live_filled_rows_delta": 0,
                "validation_live_filled_rows_delta": 0,
            }
        },
        previous_entry=None,
        base_interval_seconds=300,
    )

    assert cadence["mode"] == "slowed"
    assert cadence["recommended_interval_seconds"] > 300
    assert cadence["reason"] == "probe_stale_and_no_new_evidence"


def test_parse_args_supports_once_alias() -> None:
    args = parse_args(["--once"])

    assert args.once is True
    assert _resolved_max_cycles(args) == 1


def test_explicit_max_cycles_beats_once_alias() -> None:
    args = parse_args(["--once", "--max-cycles", "3"])

    assert args.once is True
    assert _resolved_max_cycles(args) == 3
