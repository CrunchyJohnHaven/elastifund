#!/usr/bin/env python3
"""Render repo-root public metrics from runtime and forecast artifacts."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PUBLIC_RUNTIME_SNAPSHOT = ROOT / "reports/public_runtime_snapshot.json"
DEFAULT_RUNTIME_TRUTH = ROOT / "reports/runtime_truth_latest.json"
DEFAULT_REMOTE_CYCLE_STATUS = ROOT / "reports/remote_cycle_status.json"
DEFAULT_ROOT_TEST_STATUS = ROOT / "reports/root_test_status.json"
DEFAULT_FORECAST_ARTIFACTS = (
    ROOT / "reports/btc5_autoresearch/latest.json",
    ROOT / "reports/btc5_autoresearch_current_probe/latest.json",
    ROOT / "reports/btc5_autoresearch_loop/latest.json",
)
DEFAULT_LOOP_HISTORY = ROOT / "reports/btc5_autoresearch_loop/history.jsonl"
DEFAULT_WINDOW_ROWS = ROOT / "reports/tmp_remote_btc5_window_rows.json"
DEFAULT_OUTPUT_JSON = ROOT / "improvement_velocity.json"
DEFAULT_OUTPUT_VELOCITY_SVG = ROOT / "improvement_velocity.svg"
DEFAULT_OUTPUT_ARR_SVG = ROOT / "arr_estimate.svg"

CONFIDENCE_RANK = {
    "unknown": 0,
    "speculative": 1,
    "low": 1,
    "medium": 2,
    "high": 3,
}

DEPLOYMENT_RANK = {
    "hold": 0,
    "shadow_only": 1,
    "promote": 2,
}

SOURCE_CLASS_LABELS = {
    "runtime_public_snapshot": "runtime snapshot",
    "runtime_truth": "runtime truth",
    "remote_cycle_status": "remote cycle status",
    "forecast_latest": "forecast latest",
    "forecast_current_probe": "forecast current probe",
    "forecast_loop_latest": "forecast loop latest",
    "forecast_loop_history": "forecast loop history",
    "btc5_window_rows": "BTC5 window rows",
}

FONT_STACK = "'Trebuchet MS','Segoe UI',sans-serif"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the repo-root public metrics contract and SVGs.")
    parser.add_argument(
        "--public-runtime-snapshot",
        type=Path,
        default=DEFAULT_PUBLIC_RUNTIME_SNAPSHOT,
        help="Path to reports/public_runtime_snapshot.json",
    )
    parser.add_argument(
        "--runtime-truth",
        type=Path,
        default=DEFAULT_RUNTIME_TRUTH,
        help="Path to reports/runtime_truth_latest.json",
    )
    parser.add_argument(
        "--remote-cycle-status",
        type=Path,
        default=DEFAULT_REMOTE_CYCLE_STATUS,
        help="Path to reports/remote_cycle_status.json",
    )
    parser.add_argument(
        "--root-test-status",
        type=Path,
        default=DEFAULT_ROOT_TEST_STATUS,
        help="Path to reports/root_test_status.json",
    )
    parser.add_argument(
        "--forecast-artifact",
        dest="forecast_artifacts",
        action="append",
        type=Path,
        default=None,
        help="Forecast artifact candidate. Can be passed multiple times.",
    )
    parser.add_argument(
        "--loop-history",
        type=Path,
        default=DEFAULT_LOOP_HISTORY,
        help="Path to reports/btc5_autoresearch_loop/history.jsonl",
    )
    parser.add_argument(
        "--btc5-window-rows",
        type=Path,
        default=DEFAULT_WINDOW_ROWS,
        help="Path to the checked-in BTC5 probe rows JSON used for realized sleeve fallback.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Path to write improvement_velocity.json",
    )
    parser.add_argument(
        "--velocity-svg-out",
        type=Path,
        default=DEFAULT_OUTPUT_VELOCITY_SVG,
        help="Path to write improvement_velocity.svg",
    )
    parser.add_argument(
        "--arr-svg-out",
        type=Path,
        default=DEFAULT_OUTPUT_ARR_SVG,
        help="Path to write arr_estimate.svg",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    forecast_artifacts = args.forecast_artifacts or list(DEFAULT_FORECAST_ARTIFACTS)
    contract = build_public_metrics_contract(
        public_runtime_snapshot_path=args.public_runtime_snapshot,
        runtime_truth_path=args.runtime_truth,
        remote_cycle_status_path=args.remote_cycle_status,
        root_test_status_path=args.root_test_status,
        forecast_artifact_paths=forecast_artifacts,
        loop_history_path=args.loop_history,
        btc5_window_rows_path=args.btc5_window_rows,
    )

    write_json(args.output_json, contract)
    render_improvement_velocity_svg(args.velocity_svg_out, contract)
    render_arr_estimate_svg(args.arr_svg_out, contract)

    print(json.dumps(
        {
            "json": str(args.output_json),
            "velocity_svg": str(args.velocity_svg_out),
            "arr_svg": str(args.arr_svg_out),
            "selected_forecast": contract["scoreboard"]["public_forecast_source_artifact"],
        },
        indent=2,
        sort_keys=True,
    ))


def build_public_metrics_contract(
    *,
    public_runtime_snapshot_path: Path,
    runtime_truth_path: Path,
    remote_cycle_status_path: Path,
    root_test_status_path: Path,
    forecast_artifact_paths: list[Path],
    loop_history_path: Path,
    btc5_window_rows_path: Path,
) -> dict[str, Any]:
    public_runtime_snapshot = load_json(public_runtime_snapshot_path)
    runtime_truth = load_json(runtime_truth_path)
    remote_cycle_status = load_json(remote_cycle_status_path)
    root_test_status = load_optional_json(root_test_status_path) or {}
    loop_history = load_jsonl(loop_history_path)

    existing_scoreboard = (
        get_path(
            public_runtime_snapshot,
            "state_improvement.strategy_recommendations.public_performance_scoreboard",
        )
        or get_path(
            runtime_truth,
            "state_improvement.strategy_recommendations.public_performance_scoreboard",
        )
        or get_path(
            load_optional_json(public_runtime_snapshot_path.parent / "state_improvement_latest.json"),
            "strategy_recommendations.public_performance_scoreboard",
        )
        or {}
    )

    forecast_candidates = [
        build_forecast_candidate(path, load_optional_json(path))
        for path in forecast_artifact_paths
        if load_optional_json(path) is not None
    ]
    selected_forecast = select_public_forecast(
        candidates=forecast_candidates,
        reference_time=pick_first(
            parse_timestamp(get_path(public_runtime_snapshot, "generated_at")),
            parse_timestamp(get_path(runtime_truth, "generated_at")),
            datetime.now(tz=UTC),
        ),
    )

    live_fill_window = build_live_fill_window(
        btc5_window_rows_path=btc5_window_rows_path,
        deployed_capital_usd=as_number(
            pick_first(
                get_path(public_runtime_snapshot, "capital.deployed_capital_usd"),
                get_path(runtime_truth, "capital.deployed_capital_usd"),
                runtime_truth.get("deployed_capital_usd"),
            )
        ),
        existing_scoreboard=existing_scoreboard,
    )
    use_existing_realized_window = live_fill_window["source_class"] == "runtime_public_snapshot"

    fund_claim = build_fund_realized_claim(runtime_truth=runtime_truth, existing_scoreboard=existing_scoreboard)
    timebound_velocity = build_timebound_velocity(
        loop_history=loop_history,
        selected_forecast=selected_forecast,
        btc5_window_rows_path=btc5_window_rows_path,
        loop_latest=load_optional_json(ROOT / "reports/btc5_autoresearch_loop/latest.json")
        if loop_history_path == DEFAULT_LOOP_HISTORY
        else load_optional_json(loop_history_path.parent / "latest.json"),
    )

    verification_summary = build_verification_summary(root_test_status, public_runtime_snapshot, runtime_truth)
    contribution_flywheel = build_contribution_flywheel(ROOT if runtime_truth_path == DEFAULT_RUNTIME_TRUTH else runtime_truth_path.parents[1])

    live_total_rows = as_int(
        pick_first(
            get_path(public_runtime_snapshot, "runtime.btc5_live_filled_rows"),
            get_path(runtime_truth, "runtime.btc5_live_filled_rows"),
            get_path(runtime_truth, "btc_5min_maker.live_filled_rows"),
        )
    )
    live_total_pnl_usd = as_number(
        pick_first(
            get_path(public_runtime_snapshot, "runtime.btc5_live_filled_pnl_usd"),
            get_path(runtime_truth, "runtime.btc5_live_filled_pnl_usd"),
            get_path(runtime_truth, "btc_5min_maker.live_filled_pnl_usd"),
        )
    )
    intraday_summary = normalize_intraday_live_summary(
        pick_first(
            existing_scoreboard.get("intraday_live_summary"),
            get_path(public_runtime_snapshot, "runtime.btc5_intraday_live_summary"),
            get_path(runtime_truth, "runtime.btc5_intraday_live_summary"),
            get_path(public_runtime_snapshot, "btc_5min_maker.intraday_live_summary"),
            get_path(runtime_truth, "btc_5min_maker.intraday_live_summary"),
            {},
        )
    )

    scoreboard = {
        "metric_name": "BTC5 public performance scoreboard",
        "fund_realized_arr_claim_status": pick_first(
            existing_scoreboard.get("fund_realized_arr_claim_status"),
            fund_claim["status"],
        ),
        "fund_realized_arr_claim_reason": pick_first(
            existing_scoreboard.get("fund_realized_arr_claim_reason"),
            fund_claim["reason"],
        ),
        "fund_realized_arr_pct": as_number(existing_scoreboard.get("fund_realized_arr_pct")),
        "realized_btc5_sleeve_run_rate_pct": (
            as_number(existing_scoreboard.get("realized_btc5_sleeve_run_rate_pct"))
            if use_existing_realized_window
            else live_fill_window["run_rate_pct"]
        ),
        "realized_btc5_sleeve_window_label": (
            pick_first(existing_scoreboard.get("realized_btc5_sleeve_window_label"), live_fill_window["window_label"])
            if use_existing_realized_window
            else live_fill_window["window_label"]
        ),
        "realized_btc5_sleeve_window_pnl_usd": (
            pick_first(as_number(existing_scoreboard.get("realized_btc5_sleeve_window_pnl_usd")), live_fill_window["window_pnl_usd"])
            if use_existing_realized_window
            else live_fill_window["window_pnl_usd"]
        ),
        "realized_btc5_sleeve_window_live_fills": (
            pick_first(as_int_or_none(existing_scoreboard.get("realized_btc5_sleeve_window_live_fills")), live_fill_window["window_live_fills"])
            if use_existing_realized_window
            else live_fill_window["window_live_fills"]
        ),
        "realized_btc5_sleeve_window_hours": (
            pick_first(as_number(existing_scoreboard.get("realized_btc5_sleeve_window_hours")), live_fill_window["elapsed_window_hours"])
            if use_existing_realized_window
            else live_fill_window["elapsed_window_hours"]
        ),
        "btc5_live_filled_rows_total": live_total_rows,
        "btc5_live_filled_pnl_usd_total": round(live_total_pnl_usd, 4),
        "active_forecast_arr_pct": pick_first(
            as_number(existing_scoreboard.get("forecast_active_arr_pct")),
            selected_forecast.get("active_arr_pct"),
        ),
        "best_package_forecast_arr_pct": pick_first(
            as_number(existing_scoreboard.get("forecast_best_arr_pct")),
            selected_forecast.get("best_arr_pct"),
        ),
        "p05_forecast_arr_pct": pick_first(
            as_number(existing_scoreboard.get("forecast_p05_arr_pct")),
            selected_forecast.get("p05_arr_pct"),
        ),
        "forecast_arr_delta_pct": pick_first(
            as_number(existing_scoreboard.get("forecast_arr_delta_pct")),
            selected_forecast.get("arr_delta_pct"),
        ),
        "forecast_confidence_label": pick_first(
            existing_scoreboard.get("forecast_confidence_label"),
            selected_forecast.get("confidence_label"),
            "unknown",
        ),
        "forecast_confidence_reasons": pick_first(
            existing_scoreboard.get("forecast_confidence_reasons"),
            selected_forecast.get("confidence_reasons"),
            [],
        ),
        "deploy_recommendation": pick_first(
            existing_scoreboard.get("deploy_recommendation"),
            selected_forecast.get("deploy_recommendation"),
            "hold",
        ),
        "public_forecast_source_artifact": pick_first(
            existing_scoreboard.get("public_forecast_source_artifact"),
            selected_forecast.get("source_path"),
        ),
        "active_package": selected_forecast.get("active_package"),
        "best_package": selected_forecast.get("best_package"),
        "validation_live_filled_rows": selected_forecast.get("validation_live_filled_rows"),
        "baseline_live_filled_rows": selected_forecast.get("baseline_live_filled_rows"),
        "baseline_window_rows": selected_forecast.get("baseline_window_rows"),
        "sample_size_annotation": build_sample_size_annotation(live_fill_window, selected_forecast),
        "intraday_live_summary": intraday_summary,
    }

    chart_series = build_chart_series(
        loop_history=loop_history,
        selected_forecast=selected_forecast,
        btc5_window_rows_path=btc5_window_rows_path,
    )

    source_artifacts = build_source_artifacts(
        public_runtime_snapshot_path=public_runtime_snapshot_path,
        public_runtime_snapshot=public_runtime_snapshot,
        runtime_truth_path=runtime_truth_path,
        runtime_truth=runtime_truth,
        remote_cycle_status_path=remote_cycle_status_path,
        remote_cycle_status=remote_cycle_status,
        root_test_status_path=root_test_status_path,
        root_test_status=root_test_status,
        forecast_candidates=forecast_candidates,
        loop_history_path=loop_history_path,
        btc5_window_rows_path=btc5_window_rows_path,
    )

    current_realized_arr_pct = 0.0
    if scoreboard["fund_realized_arr_claim_status"] not in {"blocked", "withheld"}:
        current_realized_arr_pct = as_number(scoreboard["fund_realized_arr_pct"])

    headline = {
        "title": "Based on latest BTC5 live trading data",
        "summary": build_headline_summary(scoreboard),
        "generated_at": pick_first(
            get_path(public_runtime_snapshot, "generated_at"),
            get_path(runtime_truth, "generated_at"),
            isoformat(datetime.now(tz=UTC)),
        ),
        "btc5_live_filled_rows_total": scoreboard["btc5_live_filled_rows_total"],
        "btc5_live_filled_pnl_usd_total": scoreboard["btc5_live_filled_pnl_usd_total"],
        "realized_btc5_sleeve_run_rate_pct": scoreboard["realized_btc5_sleeve_run_rate_pct"],
        "fund_realized_arr_claim_status": scoreboard["fund_realized_arr_claim_status"],
        "fund_realized_arr_claim_reason": scoreboard["fund_realized_arr_claim_reason"],
        "active_forecast_arr_pct": scoreboard["active_forecast_arr_pct"],
        "best_package_forecast_arr_pct": scoreboard["best_package_forecast_arr_pct"],
        "p05_forecast_arr_pct": scoreboard["p05_forecast_arr_pct"],
        "deploy_recommendation": scoreboard["deploy_recommendation"],
        "forecast_confidence_label": scoreboard["forecast_confidence_label"],
        "public_forecast_source_artifact": scoreboard["public_forecast_source_artifact"],
    }
    polymarket_tie_out = (
        get_path(public_runtime_snapshot, "polymarket_tie_out")
        or get_path(runtime_truth, "polymarket_tie_out")
        or get_path(
            runtime_truth,
            "state_improvement.strategy_recommendations.wallet_reconciliation_summary",
        )
        or {}
    )
    btc5_daily_pnl = (
        get_path(public_runtime_snapshot, "btc5_daily_pnl")
        or get_path(runtime_truth, "btc5_daily_pnl")
        or {}
    )

    contract = {
        "schema_version": "3.0.0",
        "generated_at": headline["generated_at"],
        "headline": headline,
        "scoreboard": scoreboard,
        "timebound_velocity": timebound_velocity,
        "polymarket_tie_out": polymarket_tie_out,
        "btc5_daily_pnl": btc5_daily_pnl,
        "confidence": {
            "label": scoreboard["forecast_confidence_label"],
            "reasons": scoreboard["forecast_confidence_reasons"],
            "sample_size_annotation": scoreboard["sample_size_annotation"],
            "fund_realized_arr_blocked": scoreboard["fund_realized_arr_claim_status"] == "blocked",
        },
        "source_artifacts": source_artifacts,
        "sources": {
            "runtime_public_snapshot": to_repo_relative(public_runtime_snapshot_path),
            "runtime_truth": to_repo_relative(runtime_truth_path),
            "remote_cycle_status": to_repo_relative(remote_cycle_status_path),
            "root_test_status": to_repo_relative(root_test_status_path),
            "selected_public_forecast": scoreboard["public_forecast_source_artifact"],
            "btc5_window_rows": to_repo_relative(btc5_window_rows_path),
        },
        "chart_series": chart_series,
        "runtime_summary": {
            "cycles_completed": as_int(
                pick_first(
                    get_path(public_runtime_snapshot, "runtime.cycles_completed"),
                    get_path(runtime_truth, "runtime.cycles_completed"),
                    runtime_truth.get("cycles_completed"),
                )
            ),
            "total_trades": as_int(
                pick_first(
                    get_path(public_runtime_snapshot, "runtime.total_trades"),
                    get_path(runtime_truth, "runtime.total_trades"),
                    runtime_truth.get("total_trades"),
                )
            ),
            "closed_trades": as_int(
                pick_first(
                    get_path(public_runtime_snapshot, "runtime.closed_trades"),
                    get_path(runtime_truth, "runtime.closed_trades"),
                    get_path(runtime_truth, "polymarket_wallet.closed_positions_count"),
                )
            ),
            "service_status": pick_first(
                get_path(public_runtime_snapshot, "service.status"),
                get_path(runtime_truth, "service.status"),
                get_path(remote_cycle_status, "service.status"),
                "unknown",
            ),
            "launch_posture": pick_first(
                get_path(public_runtime_snapshot, "launch.posture"),
                get_path(runtime_truth, "launch.posture"),
                "unknown",
            ),
            "verification_summary": verification_summary,
        },
        "trading_agent": {
            "tracked_capital_usd": as_number(
                pick_first(
                    get_path(public_runtime_snapshot, "capital.tracked_capital_usd"),
                    get_path(runtime_truth, "capital.tracked_capital_usd"),
                )
            ),
            "deployed_capital_usd": as_number(
                pick_first(
                    get_path(public_runtime_snapshot, "capital.deployed_capital_usd"),
                    get_path(runtime_truth, "capital.deployed_capital_usd"),
                    runtime_truth.get("deployed_capital_usd"),
                )
            ),
            "cycles_completed": as_int(
                pick_first(
                    get_path(public_runtime_snapshot, "runtime.cycles_completed"),
                    get_path(runtime_truth, "runtime.cycles_completed"),
                    runtime_truth.get("cycles_completed"),
                )
            ),
            "closed_trades": as_int(
                pick_first(
                    get_path(public_runtime_snapshot, "runtime.closed_trades"),
                    get_path(runtime_truth, "runtime.closed_trades"),
                    runtime_truth.get("polymarket_wallet", {}).get("closed_positions_count"),
                )
            ),
            "total_trades": as_int(
                pick_first(
                    get_path(public_runtime_snapshot, "runtime.total_trades"),
                    get_path(runtime_truth, "runtime.total_trades"),
                    runtime_truth.get("total_trades"),
                )
            ),
            "service_status": pick_first(
                get_path(public_runtime_snapshot, "service.status"),
                get_path(runtime_truth, "service.status"),
                get_path(remote_cycle_status, "service.status"),
                "unknown",
            ),
            "launch_posture": pick_first(
                get_path(public_runtime_snapshot, "launch.posture"),
                get_path(runtime_truth, "launch.posture"),
                "unknown",
            ),
            "wallet_flow_ready": bool(
                pick_first(
                    get_path(public_runtime_snapshot, "launch.fast_flow_restart_ready"),
                    get_path(runtime_truth, "launch.fast_flow_restart_ready"),
                    False,
                )
            ),
            "wallet_count": as_int(
                pick_first(
                    get_path(public_runtime_snapshot, "wallet_flow.wallet_count"),
                    get_path(runtime_truth, "wallet_flow.wallet_count"),
                )
            ),
            "btc5_live_filled_rows": scoreboard["btc5_live_filled_rows_total"],
            "btc5_live_filled_pnl_usd": scoreboard["btc5_live_filled_pnl_usd_total"],
        },
        "contribution_flywheel": contribution_flywheel,
        "velocity_metrics": {
            "project_age_days": contribution_flywheel["project_age_days"],
            "dispatch_work_orders": contribution_flywheel["dispatch_work_orders"],
            "dispatch_markdown_files": contribution_flywheel["dispatch_markdown_files"],
            "commits_total_after_instance": contribution_flywheel["commits_total_after_instance"],
        },
        "arr_estimate": {
            "trading_realized_pct": current_realized_arr_pct,
            "trading_realized_usd": 0.0,
            "trading_next_target_pct": as_number(scoreboard["active_forecast_arr_pct"]),
            "trading_next_target_usd": 0.0,
            "trading_next_target_confidence": scoreboard["forecast_confidence_label"],
            "trading_backtest_reference_pct": as_number(scoreboard["best_package_forecast_arr_pct"]),
            "trading_backtest_reference_methodology": (
                "Selected BTC5 forecast continuation ARR from the freshest public forecast artifact."
            ),
            "non_trading_current_pct": 0.0,
            "non_trading_current_usd": 0.0,
            "non_trading_status": "Not part of this public BTC5 metrics surface.",
            "combined_current_pct": current_realized_arr_pct,
            "combined_current_usd": 0.0,
            "combined_next_target_pct": as_number(scoreboard["active_forecast_arr_pct"]),
            "combined_next_target_usd": 0.0,
            "methodology": (
                "combined_current_pct remains fund-level realized ARR for backward compatibility. "
                "Use headline/scoreboard for the BTC5 sleeve run-rate and selected forecast."
            ),
        },
    }
    return contract


def build_forecast_candidate(path: Path, payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    arr_tracking = payload.get("arr_tracking") or {}
    latest_entry = payload.get("latest_entry") or {}
    latest_entry_arr = latest_entry.get("arr") or {}
    best_candidate = payload.get("best_candidate") or {}
    best_candidate_continuation = best_candidate.get("continuation") or {}
    best_candidate_historical = best_candidate.get("historical") or {}
    decision = payload.get("decision") or latest_entry.get("decision") or {}
    selection = payload.get("public_forecast_selection") or {}
    selected_entry = selection.get("selected") or {}
    active_runtime_package = payload.get("active_runtime_package") or {}
    best_runtime_package = payload.get("best_runtime_package") or {}

    confidence_label = normalize_confidence_label(
        pick_first(
            selected_entry.get("package_confidence_label"),
            selection.get("forecast_confidence_label"),
            selection.get("confidence_label"),
            payload.get("package_confidence_label"),
            payload.get("confidence_label"),
            get_path(selection, "selected_forecast.forecast_confidence_label"),
            "unknown",
        )
    )
    confidence_reasons = normalize_string_list(
        pick_first(
            selected_entry.get("package_confidence_reasons"),
            selection.get("forecast_confidence_reasons"),
            selection.get("confidence_reasons"),
            payload.get("package_confidence_reasons"),
            [],
        )
    )
    source_class = "forecast_latest"
    path_text = to_repo_relative(path)
    if "current_probe" in path_text:
        source_class = "forecast_current_probe"
    elif "loop" in path_text:
        source_class = "forecast_loop_latest"

    deploy_recommendation = normalize_deploy_recommendation(
        pick_first(
            selected_entry.get("deploy_recommendation"),
            selection.get("deploy_recommendation"),
            payload.get("deploy_recommendation"),
            decision.get("action"),
            "hold",
        )
    )

    return {
        "source_path": pick_first(
            selected_entry.get("source_artifact"),
            path_text,
        ),
        "source_class": source_class,
        "generated_at": pick_first(
            selected_entry.get("generated_at"),
            selection.get("generated_at"),
            payload.get("generated_at"),
            latest_entry.get("finished_at"),
        ),
        "active_arr_pct": as_number(
            pick_first(
                selected_entry.get("forecast_active_arr_pct"),
                selection.get("active_forecast_arr_pct"),
                selection.get("selected_forecast", {}).get("active_forecast_arr_pct"),
                arr_tracking.get("current_median_arr_pct"),
                latest_entry_arr.get("active_median_arr_pct"),
            )
        ),
        "best_arr_pct": as_number(
            pick_first(
                selected_entry.get("forecast_best_arr_pct"),
                selection.get("best_forecast_arr_pct"),
                selection.get("selected_forecast", {}).get("best_forecast_arr_pct"),
                arr_tracking.get("best_median_arr_pct"),
                best_candidate_continuation.get("median_arr_pct"),
                latest_entry_arr.get("best_median_arr_pct"),
            )
        ),
        "p05_arr_pct": as_number(
            pick_first(
                selection.get("p05_forecast_arr_pct"),
                selection.get("selected_forecast", {}).get("p05_forecast_arr_pct"),
                arr_tracking.get("best_p05_arr_pct"),
                best_candidate_continuation.get("p05_arr_pct"),
                latest_entry_arr.get("best_p05_arr_pct"),
            )
        ),
        "arr_delta_pct": as_number(
            pick_first(
                selected_entry.get("forecast_arr_delta_pct"),
                selection.get("forecast_arr_delta_pct"),
                selection.get("selected_forecast", {}).get("forecast_arr_delta_pct"),
                arr_tracking.get("median_arr_delta_pct"),
                decision.get("median_arr_delta_pct"),
                latest_entry_arr.get("median_arr_delta_pct"),
            )
        ),
        "confidence_label": confidence_label,
        "confidence_reasons": confidence_reasons,
        "deploy_recommendation": deploy_recommendation,
        "validation_live_filled_rows": as_int(
            pick_first(
                selected_entry.get("validation_live_filled_rows"),
                selection.get("validation_live_filled_rows"),
                payload.get("validation_live_filled_rows"),
                best_candidate_historical.get("replay_live_filled_rows"),
                latest_entry.get("validation_live_filled_rows"),
            )
        ) if pick_first(
            selected_entry.get("validation_live_filled_rows"),
            selection.get("validation_live_filled_rows"),
            payload.get("validation_live_filled_rows"),
            best_candidate_historical.get("replay_live_filled_rows"),
            latest_entry.get("validation_live_filled_rows"),
        ) is not None else None,
        "baseline_live_filled_rows": as_int_or_none(
            pick_first(
                selection.get("baseline_live_filled_rows"),
                get_path(payload, "simulation_summary.baseline.deduped_live_filled_rows"),
                best_candidate_historical.get("baseline_live_filled_rows"),
            )
        ),
        "baseline_window_rows": as_int_or_none(
            pick_first(
                selection.get("baseline_window_rows"),
                get_path(payload, "simulation_summary.baseline.deduped_rows"),
                best_candidate_historical.get("baseline_window_rows"),
            )
        ),
        "active_package": pick_first(
            get_path(selected_entry, "active_runtime_package.profile.name"),
            get_path(active_runtime_package, "profile.name"),
            get_path(payload, "active_profile.name"),
        ),
        "best_package": pick_first(
            get_path(selected_entry, "best_runtime_package.profile.name"),
            get_path(best_runtime_package, "profile.name"),
            get_path(best_candidate, "profile.name"),
            get_path(payload, "best_profile.name"),
        ),
    }


def select_public_forecast(*, candidates: list[dict[str, Any]], reference_time: datetime) -> dict[str, Any]:
    usable = [candidate for candidate in candidates if parse_timestamp(candidate.get("generated_at")) is not None]
    if not usable:
        return {
            "source_path": None,
            "source_class": None,
            "generated_at": None,
            "active_arr_pct": None,
            "best_arr_pct": None,
            "p05_arr_pct": None,
            "arr_delta_pct": None,
            "confidence_label": "unknown",
            "confidence_reasons": ["no_forecast_artifacts_found"],
            "deploy_recommendation": "hold",
            "validation_live_filled_rows": None,
            "baseline_live_filled_rows": None,
            "baseline_window_rows": None,
            "active_package": None,
            "best_package": None,
        }

    fresh = []
    for candidate in usable:
        generated_at = parse_timestamp(candidate["generated_at"])
        if generated_at is None:
            continue
        age_hours = (reference_time - generated_at).total_seconds() / 3600.0
        if age_hours <= 6.0:
            fresh.append(candidate)
    ranked = fresh or usable
    ranked.sort(
        key=lambda candidate: (
            CONFIDENCE_RANK.get(normalize_confidence_label(candidate.get("confidence_label")), 0),
            DEPLOYMENT_RANK.get(normalize_deploy_recommendation(candidate.get("deploy_recommendation")), 0),
            parse_timestamp(candidate.get("generated_at")) or datetime.min.replace(tzinfo=UTC),
        )
    )
    return ranked[-1]


def build_live_fill_window(
    *,
    btc5_window_rows_path: Path,
    deployed_capital_usd: float | None,
    existing_scoreboard: dict[str, Any],
) -> dict[str, Any]:
    existing_run_rate = as_number(existing_scoreboard.get("realized_btc5_sleeve_run_rate_pct"))
    existing_window_pnl = as_number(existing_scoreboard.get("realized_btc5_sleeve_window_pnl_usd"))
    existing_window_fills = as_int_or_none(existing_scoreboard.get("realized_btc5_sleeve_window_live_fills"))
    existing_window_hours = as_number(existing_scoreboard.get("realized_btc5_sleeve_window_hours"))
    if (
        existing_run_rate is not None
        and existing_window_pnl is not None
        and existing_window_fills is not None
        and existing_window_hours is not None
    ):
        return {
            "source_path": "reports/public_runtime_snapshot.json",
            "source_class": "runtime_public_snapshot",
            "window_label": pick_first(
                existing_scoreboard.get("realized_btc5_sleeve_window_label"),
                "trailing_12_live_fills",
            ),
            "window_pnl_usd": existing_window_pnl,
            "window_live_fills": existing_window_fills,
            "elapsed_window_hours": existing_window_hours,
            "run_rate_pct": existing_run_rate,
        }

    rows = load_optional_json(btc5_window_rows_path) or []
    live_rows = []
    for row in rows:
        if row.get("order_status") != "live_filled":
            continue
        timestamp = parse_timestamp(row.get("updated_at"))
        if timestamp is None:
            continue
        live_rows.append(
            {
                "updated_at": timestamp,
                "window_start_ts": row.get("window_start_ts"),
                "realized_pnl_usd": as_number(pick_first(row.get("realized_pnl_usd"), row.get("pnl_usd")), default=0.0),
            }
        )
    live_rows.sort(key=lambda row: row["updated_at"])
    if not live_rows:
        return {
            "source_path": to_repo_relative(btc5_window_rows_path),
            "source_class": "btc5_window_rows",
            "window_label": "no_live_fills",
            "window_pnl_usd": 0.0,
            "window_live_fills": 0,
            "elapsed_window_hours": 0.0,
            "run_rate_pct": 0.0,
        }

    window_rows = live_rows[-12:] if len(live_rows) >= 12 else live_rows
    window_label = "trailing_12_live_fills" if len(live_rows) >= 12 else "since_first_live_fill"
    window_pnl_usd = round(sum(row["realized_pnl_usd"] for row in window_rows), 4)
    elapsed_seconds = (window_rows[-1]["updated_at"] - window_rows[0]["updated_at"]).total_seconds()
    elapsed_hours = max(elapsed_seconds / 3600.0, 5.0 / 60.0)
    run_rate_pct = 0.0
    if deployed_capital_usd and deployed_capital_usd > 0 and elapsed_hours > 0:
        run_rate_pct = ((window_pnl_usd / deployed_capital_usd) * ((24.0 * 365.0) / elapsed_hours)) * 100.0
    return {
        "source_path": to_repo_relative(btc5_window_rows_path),
        "source_class": "btc5_window_rows",
        "window_label": window_label,
        "window_pnl_usd": round(window_pnl_usd, 4),
        "window_live_fills": len(window_rows),
        "elapsed_window_hours": round(elapsed_hours, 4),
        "run_rate_pct": round(run_rate_pct, 4),
    }


def build_fund_realized_claim(*, runtime_truth: dict[str, Any], existing_scoreboard: dict[str, Any]) -> dict[str, Any]:
    existing_status = existing_scoreboard.get("fund_realized_arr_claim_status")
    existing_reason = existing_scoreboard.get("fund_realized_arr_claim_reason")
    if existing_status and existing_reason:
        return {"status": existing_status, "reason": existing_reason}

    reconciliation = (
        runtime_truth.get("accounting_reconciliation")
        or get_path(runtime_truth, "reconciliation.accounting")
        or {}
    )
    drift_detected = bool(reconciliation.get("drift_detected"))
    if drift_detected:
        reasons = normalize_string_list(reconciliation.get("drift_reasons"))
        if reasons:
            return {
                "status": "blocked",
                "reason": "Ledger and wallet reconciliation remain open: " + "; ".join(reasons),
            }
        return {
            "status": "blocked",
            "reason": "Ledger and wallet reconciliation remain open.",
        }
    return {
        "status": "unblocked",
        "reason": "Ledger and wallet reconciliation are closed.",
    }


def build_timebound_velocity(
    *,
    loop_history: list[dict[str, Any]],
    selected_forecast: dict[str, Any],
    btc5_window_rows_path: Path,
    loop_latest: dict[str, Any] | None,
) -> dict[str, Any]:
    velocity_from_artifact = (
        get_path(loop_latest, "public_forecast_selection.timebound_velocity")
        if loop_latest
        else None
    )
    if velocity_from_artifact:
        return {
            "metric_name": "BTC5 public forecast velocity",
            "window_hours": as_number(velocity_from_artifact.get("window_hours")),
            "cycles_in_window": as_int(velocity_from_artifact.get("cycles_in_window")),
            "forecast_arr_gain_pct": as_number(velocity_from_artifact.get("forecast_arr_gain_pct")),
            "forecast_arr_gain_pct_per_day": as_number(velocity_from_artifact.get("forecast_arr_gain_pct_per_day")),
            "validation_fill_growth": as_int(velocity_from_artifact.get("validation_fill_growth")),
            "validation_fill_growth_per_day": as_number(velocity_from_artifact.get("validation_fill_growth_per_day")),
            "window_started_at": velocity_from_artifact.get("window_started_at"),
            "window_ended_at": velocity_from_artifact.get("window_ended_at"),
            "confidence_label": normalize_confidence_label(selected_forecast.get("confidence_label")),
            "source_artifact": selected_forecast.get("source_path"),
            "source_class": "forecast_loop_latest",
        }

    history_points = []
    for row in loop_history:
        timestamp = pick_first(
            parse_timestamp(row.get("finished_at")),
            parse_timestamp(row.get("started_at")),
        )
        if timestamp is None:
            continue
        arr = row.get("arr") or {}
        history_points.append(
            {
                "timestamp": timestamp,
                "active_arr_pct": as_number(arr.get("active_median_arr_pct")),
                "best_arr_pct": as_number(arr.get("best_median_arr_pct")),
            }
        )
    history_points.sort(key=lambda point: point["timestamp"])
    end_at = pick_first(parse_timestamp(selected_forecast.get("generated_at")), history_points[-1]["timestamp"] if history_points else None)
    start_at = history_points[0]["timestamp"] if history_points else end_at
    if start_at is None or end_at is None:
        return {
            "metric_name": "BTC5 public forecast velocity",
            "window_hours": 0.0,
            "cycles_in_window": 0,
            "forecast_arr_gain_pct": as_number(selected_forecast.get("arr_delta_pct")),
            "forecast_arr_gain_pct_per_day": 0.0,
            "validation_fill_growth": 0,
            "validation_fill_growth_per_day": 0.0,
            "window_started_at": None,
            "window_ended_at": None,
            "confidence_label": normalize_confidence_label(selected_forecast.get("confidence_label")),
            "source_artifact": selected_forecast.get("source_path"),
            "source_class": selected_forecast.get("source_class"),
        }

    window_hours = max((end_at - start_at).total_seconds() / 3600.0, 1.0 / 60.0)
    fill_counts = build_fill_counts_by_timestamp(btc5_window_rows_path, [start_at, end_at])
    validation_fill_growth = max(fill_counts[-1] - fill_counts[0], 0)
    cycles_in_window = sum(1 for point in history_points if start_at <= point["timestamp"] <= end_at)
    forecast_arr_gain_pct = as_number(selected_forecast.get("arr_delta_pct"))
    if forecast_arr_gain_pct is None and history_points:
        first_active = as_number(history_points[0]["active_arr_pct"])
        last_best = as_number(selected_forecast.get("best_arr_pct"))
        if first_active is not None and last_best is not None:
            forecast_arr_gain_pct = last_best - first_active
    forecast_arr_gain_pct = forecast_arr_gain_pct or 0.0
    window_days = window_hours / 24.0
    return {
        "metric_name": "BTC5 public forecast velocity",
        "window_hours": round(window_hours, 4),
        "cycles_in_window": cycles_in_window or as_int(get_path(loop_latest or {}, "summary.cycles_total")),
        "forecast_arr_gain_pct": round(forecast_arr_gain_pct, 4),
        "forecast_arr_gain_pct_per_day": round(forecast_arr_gain_pct / window_days, 4) if window_days > 0 else 0.0,
        "validation_fill_growth": validation_fill_growth,
        "validation_fill_growth_per_day": round(validation_fill_growth / window_days, 4) if window_days > 0 else 0.0,
        "window_started_at": isoformat(start_at),
        "window_ended_at": isoformat(end_at),
        "confidence_label": normalize_confidence_label(selected_forecast.get("confidence_label")),
        "source_artifact": selected_forecast.get("source_path"),
        "source_class": "forecast_loop_history",
    }


def build_chart_series(
    *,
    loop_history: list[dict[str, Any]],
    selected_forecast: dict[str, Any],
    btc5_window_rows_path: Path,
) -> dict[str, Any]:
    points = []
    for row in loop_history:
        timestamp = pick_first(parse_timestamp(row.get("finished_at")), parse_timestamp(row.get("started_at")))
        if timestamp is None:
            continue
        arr = row.get("arr") or {}
        best_arr_pct = as_number(arr.get("best_median_arr_pct"))
        active_arr_pct = as_number(arr.get("active_median_arr_pct"))
        if best_arr_pct is None:
            continue
        point = {
            "timestamp": isoformat(timestamp),
            "best_forecast_arr_pct": round(best_arr_pct, 4),
            "active_forecast_arr_pct": round(active_arr_pct or 0.0, 4),
            "source_artifact": "reports/btc5_autoresearch_loop/history.jsonl",
        }
        if not points or (
            points[-1]["best_forecast_arr_pct"] != point["best_forecast_arr_pct"]
            or points[-1]["active_forecast_arr_pct"] != point["active_forecast_arr_pct"]
        ):
            points.append(point)

    selected_timestamp = parse_timestamp(selected_forecast.get("generated_at"))
    if (
        selected_timestamp is not None
        and selected_forecast.get("best_arr_pct") is not None
        and (
            not points
            or points[-1]["timestamp"] != isoformat(selected_timestamp)
            or points[-1]["best_forecast_arr_pct"] != round(as_number(selected_forecast["best_arr_pct"], default=0.0), 4)
        )
    ):
        points.append(
            {
                "timestamp": isoformat(selected_timestamp),
                "best_forecast_arr_pct": round(as_number(selected_forecast["best_arr_pct"], default=0.0), 4),
                "active_forecast_arr_pct": round(as_number(selected_forecast.get("active_arr_pct"), default=0.0), 4),
                "source_artifact": selected_forecast.get("source_path"),
            }
        )

    timestamps = [parse_timestamp(point["timestamp"]) for point in points]
    fill_counts = build_fill_counts_by_timestamp(btc5_window_rows_path, [timestamp for timestamp in timestamps if timestamp is not None])
    for point, fill_count in zip(points, fill_counts):
        point["live_filled_rows"] = fill_count
    return {
        "forecast_arr_trend": points,
    }


def build_source_artifacts(
    *,
    public_runtime_snapshot_path: Path,
    public_runtime_snapshot: dict[str, Any],
    runtime_truth_path: Path,
    runtime_truth: dict[str, Any],
    remote_cycle_status_path: Path,
    remote_cycle_status: dict[str, Any],
    root_test_status_path: Path,
    root_test_status: dict[str, Any],
    forecast_candidates: list[dict[str, Any]],
    loop_history_path: Path,
    btc5_window_rows_path: Path,
) -> list[dict[str, Any]]:
    artifacts = [
        {
            "path": to_repo_relative(public_runtime_snapshot_path),
            "source_class": "runtime_public_snapshot",
            "generated_at": public_runtime_snapshot.get("generated_at"),
        },
        {
            "path": to_repo_relative(runtime_truth_path),
            "source_class": "runtime_truth",
            "generated_at": runtime_truth.get("generated_at"),
        },
        {
            "path": to_repo_relative(remote_cycle_status_path),
            "source_class": "remote_cycle_status",
            "generated_at": remote_cycle_status.get("generated_at"),
        },
        {
            "path": to_repo_relative(root_test_status_path),
            "source_class": "root_test_status",
            "generated_at": root_test_status.get("checked_at"),
        },
        {
            "path": to_repo_relative(loop_history_path),
            "source_class": "forecast_loop_history",
            "generated_at": None,
        },
        {
            "path": to_repo_relative(btc5_window_rows_path),
            "source_class": "btc5_window_rows",
            "generated_at": None,
        },
    ]
    for candidate in forecast_candidates:
        artifacts.append(
            {
                "path": candidate["source_path"],
                "source_class": candidate["source_class"],
                "generated_at": candidate["generated_at"],
                "confidence_label": candidate["confidence_label"],
            }
        )
    seen: set[tuple[str, str]] = set()
    deduped = []
    for artifact in artifacts:
        key = (artifact["path"], artifact["source_class"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def build_headline_summary(scoreboard: dict[str, Any]) -> str:
    intraday = normalize_intraday_live_summary(scoreboard.get("intraday_live_summary"))
    day_pnl = as_number(intraday.get("filled_pnl_usd_today"))
    day_direction = "positive" if day_pnl > 0 else ("negative" if day_pnl < 0 else "flat")
    return (
        f"BTC5 live sleeve has {scoreboard['btc5_live_filled_rows_total']} live-filled rows and "
        f"{format_usd(scoreboard['btc5_live_filled_pnl_usd_total'])} live-filled PnL "
        f"(today {format_usd(day_pnl)}, {day_direction}). "
        f"Fund-level realized ARR is {scoreboard['fund_realized_arr_claim_status']}. "
        f"Selected public forecast is {scoreboard['deploy_recommendation']} / "
        f"{scoreboard['forecast_confidence_label']} confidence from "
        f"{scoreboard['public_forecast_source_artifact']}."
    )


def normalize_intraday_live_summary(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    return {
        "filled_rows_today": as_int(data.get("filled_rows_today")),
        "filled_pnl_usd_today": round(as_number(data.get("filled_pnl_usd_today"), 0.0) or 0.0, 4),
        "win_rate_today": as_number(data.get("win_rate_today")) if data.get("win_rate_today") is not None else None,
        "recent_5_pnl_usd": round(as_number(data.get("recent_5_pnl_usd"), 0.0) or 0.0, 4),
        "recent_12_pnl_usd": round(as_number(data.get("recent_12_pnl_usd"), 0.0) or 0.0, 4),
        "recent_20_pnl_usd": round(as_number(data.get("recent_20_pnl_usd"), 0.0) or 0.0, 4),
        "skip_price_count": as_int(data.get("skip_price_count")),
        "order_failed_count": as_int(data.get("order_failed_count")),
        "cancelled_unfilled_count": as_int(data.get("cancelled_unfilled_count")),
        "best_direction_today": data.get("best_direction_today"),
        "best_price_bucket_today": data.get("best_price_bucket_today"),
    }


def build_sample_size_annotation(live_fill_window: dict[str, Any], selected_forecast: dict[str, Any]) -> str:
    pieces = [
        f"{live_fill_window['window_live_fills']} live fills in the realized sleeve window",
    ]
    if selected_forecast.get("validation_live_filled_rows") is not None:
        pieces.append(f"{selected_forecast['validation_live_filled_rows']} validation live-filled rows in the selected forecast")
    if selected_forecast.get("baseline_window_rows") is not None:
        pieces.append(f"{selected_forecast['baseline_window_rows']} observed BTC5 windows in the selected forecast artifact")
    return "; ".join(pieces)


def build_verification_summary(
    root_test_status: dict[str, Any],
    public_runtime_snapshot: dict[str, Any],
    runtime_truth: dict[str, Any],
) -> str:
    summary = pick_first(
        root_test_status.get("summary"),
        get_path(public_runtime_snapshot, "verification.summary"),
        get_path(runtime_truth, "verification.summary"),
        "verification summary unavailable",
    )
    return str(summary)


def build_contribution_flywheel(repo_root: Path) -> dict[str, Any]:
    dispatch_dir = repo_root / "research/dispatches"
    dispatch_markdown_files = 0
    dispatch_work_orders = 0
    if dispatch_dir.exists():
        for path in dispatch_dir.glob("*.md"):
            if path.name.lower() == "readme.md":
                continue
            dispatch_markdown_files += 1
            if path.name.startswith("DISPATCH_"):
                dispatch_work_orders += 1

    commits_total = git_count(repo_root, ["rev-list", "--count", "HEAD"])
    first_commit_date = git_first_commit_date(repo_root)
    project_age_days = 0
    if first_commit_date is not None:
        project_age_days = max((datetime.now(tz=UTC) - first_commit_date).days, 0)

    return {
        "dispatch_work_orders": dispatch_work_orders,
        "dispatch_markdown_files": dispatch_markdown_files,
        "commits_total_after_instance": commits_total,
        "project_age_days": project_age_days,
    }


def render_improvement_velocity_svg(path: Path, contract: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    series = contract.get("chart_series", {}).get("forecast_arr_trend") or []
    scoreboard = contract["scoreboard"]
    velocity = contract["timebound_velocity"]
    confidence = contract["confidence"]

    width = 1280
    height = 780
    chart_left = 100
    chart_top = 170
    chart_width = 760
    chart_height = 360
    panel_x = 900
    panel_y = 150
    panel_width = 320
    panel_height = 420

    timestamps = [parse_timestamp(point["timestamp"]) for point in series if parse_timestamp(point["timestamp"]) is not None]
    forecast_values = [as_number(point.get("best_forecast_arr_pct"), default=0.0) for point in series]
    fill_values = [as_int(point.get("live_filled_rows")) for point in series]

    min_time = timestamps[0] if timestamps else None
    max_time = timestamps[-1] if timestamps else None
    min_forecast = min(forecast_values) if forecast_values else 0.0
    max_forecast = max(forecast_values) if forecast_values else 1.0
    if math.isclose(min_forecast, max_forecast):
        max_forecast = min_forecast + 1.0
    max_fills = max(fill_values) if fill_values else 1
    if max_fills <= 0:
        max_fills = 1

    def x_for(ts: datetime) -> float:
        if min_time is None or max_time is None or min_time == max_time:
            return chart_left + chart_width / 2.0
        return chart_left + (((ts - min_time).total_seconds()) / ((max_time - min_time).total_seconds())) * chart_width

    def y_for_forecast(value: float) -> float:
        return chart_top + chart_height - ((value - min_forecast) / (max_forecast - min_forecast)) * chart_height

    def y_for_fill(value: int) -> float:
        return chart_top + chart_height - (value / max_fills) * chart_height

    forecast_points = []
    fill_points = []
    labels = []
    for point in series:
        timestamp = parse_timestamp(point["timestamp"])
        if timestamp is None:
            continue
        x_value = x_for(timestamp)
        forecast_points.append(f"{x_value:.2f},{y_for_forecast(as_number(point['best_forecast_arr_pct'], default=0.0)):.2f}")
        fill_points.append(f"{x_value:.2f},{y_for_fill(as_int(point.get('live_filled_rows'))):.2f}")
        labels.append((x_value, format_axis_time(timestamp)))

    footer_sources = [
        f"Metric: Best-package BTC5 continuation ARR trend | Window: {format_window(contract['timebound_velocity'])}",
        (
            f"Confidence: {confidence['label']} | Sample: {escape(scoreboard['sample_size_annotation'])} | "
            f"Source: {escape(scoreboard['public_forecast_source_artifact'] or 'n/a')}"
        ),
        (
            "Source class: "
            f"{escape(SOURCE_CLASS_LABELS.get(velocity['source_class'], velocity['source_class'] or 'unknown'))} + "
            f"{escape(SOURCE_CLASS_LABELS['btc5_window_rows'])}"
        ),
    ]

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        '  <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">',
        '    <stop offset="0%" stop-color="#07111f"/>',
        '    <stop offset="100%" stop-color="#10263f"/>',
        "  </linearGradient>",
        '  <linearGradient id="forecastLine" x1="0" x2="1" y1="0" y2="0">',
        '    <stop offset="0%" stop-color="#4df0c7"/>',
        '    <stop offset="100%" stop-color="#6bf1ff"/>',
        "  </linearGradient>",
        '  <linearGradient id="fillLine" x1="0" x2="1" y1="0" y2="0">',
        '    <stop offset="0%" stop-color="#ffaf45"/>',
        '    <stop offset="100%" stop-color="#ffd36a"/>',
        "  </linearGradient>",
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="url(#bg)"/>',
        '<circle cx="1130" cy="90" r="160" fill="#18314d" opacity="0.35"/>',
        '<circle cx="180" cy="660" r="120" fill="#0c3b49" opacity="0.22"/>',
        f'<text x="80" y="78" font-family="{FONT_STACK}" font-size="34" font-weight="700" fill="#f7fafc">BTC5 Public Improvement Velocity</text>',
        f'<text x="80" y="116" font-family="{FONT_STACK}" font-size="17" fill="#bfd0ea">Generated {escape(format_timestamp(contract["generated_at"]))} from runtime truth and the freshest public BTC5 forecast artifact.</text>',
        f'<rect x="{panel_x}" y="{panel_y}" width="{panel_width}" height="{panel_height}" rx="24" fill="#0d1b2e" opacity="0.92" stroke="#27496d"/>',
    ]

    for index in range(5):
        y_value = chart_top + (chart_height / 4.0) * index
        svg.append(
            f'<line x1="{chart_left}" y1="{y_value:.2f}" x2="{chart_left + chart_width}" y2="{y_value:.2f}" stroke="#28425e" stroke-width="1"/>'
        )
    svg.append(
        f'<rect x="{chart_left}" y="{chart_top}" width="{chart_width}" height="{chart_height}" rx="18" fill="#081423" opacity="0.45" stroke="#29405d"/>'
    )

    if forecast_points:
        svg.append(
            f'<polyline points="{" ".join(forecast_points)}" fill="none" stroke="url(#forecastLine)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for point in series:
            timestamp = parse_timestamp(point["timestamp"])
            if timestamp is None:
                continue
            x_value = x_for(timestamp)
            y_value = y_for_forecast(as_number(point["best_forecast_arr_pct"], default=0.0))
            svg.append(f'<circle cx="{x_value:.2f}" cy="{y_value:.2f}" r="6" fill="#07111f" stroke="#72fff0" stroke-width="3"/>')

    if fill_points:
        svg.append(
            f'<polyline points="{" ".join(fill_points)}" fill="none" stroke="url(#fillLine)" stroke-width="3" stroke-dasharray="10 8" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for point in series:
            timestamp = parse_timestamp(point["timestamp"])
            if timestamp is None:
                continue
            x_value = x_for(timestamp)
            y_value = y_for_fill(as_int(point.get("live_filled_rows")))
            svg.append(f'<circle cx="{x_value:.2f}" cy="{y_value:.2f}" r="4" fill="#ffcf71"/>')

    for x_value, label in labels:
        svg.append(f'<line x1="{x_value:.2f}" y1="{chart_top + chart_height}" x2="{x_value:.2f}" y2="{chart_top + chart_height + 10}" stroke="#89a6ca"/>')
        svg.append(f'<text x="{x_value:.2f}" y="{chart_top + chart_height + 34}" text-anchor="middle" font-family="{FONT_STACK}" font-size="13" fill="#d7e4f5">{escape(label)}</text>')

    forecast_axis_labels = axis_labels(min_forecast, max_forecast, 5, formatter=format_compact_percent)
    for label_value, y_value in forecast_axis_labels:
        svg.append(
            f'<text x="{chart_left - 18}" y="{y_value + 4:.2f}" text-anchor="end" font-family="{FONT_STACK}" font-size="13" fill="#c6dbf4">{escape(label_value)}</text>'
        )
    fill_axis_labels = axis_labels(0, float(max_fills), 5, formatter=lambda value: f"{int(round(value))} fills")
    for label_value, y_value in fill_axis_labels:
        svg.append(
            f'<text x="{chart_left + chart_width + 18}" y="{y_value + 4:.2f}" font-family="{FONT_STACK}" font-size="13" fill="#ffd8a8">{escape(label_value)}</text>'
        )

    legend_y = chart_top - 24
    svg.extend(
        [
            f'<rect x="{chart_left}" y="{legend_y}" width="18" height="4" rx="2" fill="#5cf2df"/>',
            f'<text x="{chart_left + 28}" y="{legend_y + 8}" font-family="{FONT_STACK}" font-size="14" fill="#e8f2ff">Best-package forecast ARR</text>',
            f'<rect x="{chart_left + 260}" y="{legend_y}" width="18" height="4" rx="2" fill="#ffc25f"/>',
            f'<text x="{chart_left + 288}" y="{legend_y + 8}" font-family="{FONT_STACK}" font-size="14" fill="#e8f2ff">Live-filled row growth</text>',
        ]
    )

    panel_lines = [
        ("Selected source", scoreboard["public_forecast_source_artifact"] or "n/a"),
        ("Deploy recommendation", scoreboard["deploy_recommendation"]),
        ("Confidence", scoreboard["forecast_confidence_label"]),
        ("Forecast ARR gain", format_compact_percent(velocity["forecast_arr_gain_pct"])),
        ("Cycles in window", str(velocity["cycles_in_window"])),
        ("Window", f"{velocity['window_hours']:.2f}h"),
        ("Fill growth", f"+{velocity['validation_fill_growth']} rows"),
        ("Per day", f"{format_compact_percent(velocity['forecast_arr_gain_pct_per_day'])} / {velocity['validation_fill_growth_per_day']:.1f} fills"),
        ("Sample", scoreboard["sample_size_annotation"]),
    ]
    panel_text_y = panel_y + 54
    for label, value in panel_lines:
        svg.append(f'<text x="{panel_x + 26}" y="{panel_text_y}" font-family="{FONT_STACK}" font-size="13" fill="#91a8c7">{escape(label.upper())}</text>')
        wrapped = wrap_text(str(value), 34)
        for wrapped_line in wrapped:
            panel_text_y += 22
            svg.append(f'<text x="{panel_x + 26}" y="{panel_text_y}" font-family="{FONT_STACK}" font-size="18" fill="#f8fbff">{escape(wrapped_line)}</text>')
        panel_text_y += 28

    footer_y = 630
    for line in footer_sources:
        for wrapped_line in wrap_text(line, 118):
            svg.append(f'<text x="80" y="{footer_y}" font-family="{FONT_STACK}" font-size="13" fill="#c3d6ee">{wrapped_line}</text>')
            footer_y += 20

    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def render_arr_estimate_svg(path: Path, contract: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scoreboard = contract["scoreboard"]
    metrics = [
        {
            "label": "Realized BTC5 sleeve run-rate",
            "value": as_number(scoreboard["realized_btc5_sleeve_run_rate_pct"], default=0.0),
            "window": scoreboard["realized_btc5_sleeve_window_label"],
            "confidence": "high",
            "source": contract["sources"]["btc5_window_rows"],
            "note": (
                f"{scoreboard['realized_btc5_sleeve_window_live_fills']} live fills, "
                f"{scoreboard['realized_btc5_sleeve_window_hours']:.2f}h, "
                f"{format_usd(scoreboard['realized_btc5_sleeve_window_pnl_usd'])} PnL"
            ),
            "color": "#53f3c8",
        },
        {
            "label": "Active forecast ARR",
            "value": as_number(scoreboard["active_forecast_arr_pct"], default=0.0),
            "window": "selected_public_forecast",
            "confidence": scoreboard["forecast_confidence_label"],
            "source": scoreboard["public_forecast_source_artifact"] or "n/a",
            "note": f"Active package: {scoreboard['active_package'] or 'n/a'}",
            "color": "#58b5ff",
        },
        {
            "label": "Best package forecast ARR",
            "value": as_number(scoreboard["best_package_forecast_arr_pct"], default=0.0),
            "window": "selected_public_forecast",
            "confidence": scoreboard["forecast_confidence_label"],
            "source": scoreboard["public_forecast_source_artifact"] or "n/a",
            "note": f"Best package: {scoreboard['best_package'] or 'n/a'}",
            "color": "#ff8d5c",
        },
        {
            "label": "P05 forecast ARR",
            "value": as_number(scoreboard["p05_forecast_arr_pct"], default=0.0),
            "window": "selected_public_forecast",
            "confidence": scoreboard["forecast_confidence_label"],
            "source": scoreboard["public_forecast_source_artifact"] or "n/a",
            "note": f"Selected forecast validation rows: {scoreboard['validation_live_filled_rows'] or 'n/a'}",
            "color": "#ffd467",
        },
    ]
    positive_values = [metric["value"] for metric in metrics if metric["value"] > 0]
    min_log = math.log10(min(positive_values)) if positive_values else 0.0
    max_log = math.log10(max(positive_values)) if positive_values else 1.0
    if math.isclose(min_log, max_log):
        max_log = min_log + 1.0

    width = 1280
    height = 780
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        '  <linearGradient id="arrBg" x1="0" x2="1" y1="0" y2="1">',
        '    <stop offset="0%" stop-color="#120d1a"/>',
        '    <stop offset="100%" stop-color="#1d2235"/>',
        "  </linearGradient>",
        "</defs>",
        f'<rect width="{width}" height="{height}" fill="url(#arrBg)"/>',
        '<circle cx="150" cy="130" r="140" fill="#22304d" opacity="0.22"/>',
        '<circle cx="1140" cy="650" r="160" fill="#412c1b" opacity="0.25"/>',
        f'<text x="80" y="84" font-family="{FONT_STACK}" font-size="34" font-weight="700" fill="#fafcff">BTC5 Public ARR Surface</text>',
        f'<text x="80" y="122" font-family="{FONT_STACK}" font-size="17" fill="#c7d4e7">Linear annualized sleeve run-rate from live-filled BTC5 results, plus the freshest selected BTC5 forecast.</text>',
        '<rect x="80" y="154" width="1120" height="126" rx="26" fill="#0e1523" stroke="#5b3046" opacity="0.95"/>',
        f'<text x="112" y="194" font-family="{FONT_STACK}" font-size="14" fill="#e1a7be">FUND-LEVEL REALIZED ARR CLAIM</text>',
        f'<text x="112" y="234" font-family="{FONT_STACK}" font-size="30" font-weight="700" fill="#fff0f4">{escape(scoreboard["fund_realized_arr_claim_status"].upper())}</text>',
    ]
    blocked_reason_lines = wrap_text(scoreboard["fund_realized_arr_claim_reason"], 108)
    blocked_y = 262
    for line in blocked_reason_lines[:2]:
        svg.append(f'<text x="112" y="{blocked_y}" font-family="{FONT_STACK}" font-size="16" fill="#e5d7de">{escape(line)}</text>')
        blocked_y += 22
    svg.append(
        f'<text x="112" y="{blocked_y + 12}" font-family="{FONT_STACK}" font-size="14" fill="#d3c4cc">Source: reports/runtime_truth_latest.json | Time window: fund lifetime | Confidence: high</text>'
    )

    row_y = 350
    bar_x = 520
    bar_width = 560
    for metric in metrics:
        svg.append(f'<text x="80" y="{row_y}" font-family="{FONT_STACK}" font-size="24" fill="#f7fafc">{escape(metric["label"])}</text>')
        svg.append(
            f'<text x="80" y="{row_y + 28}" font-family="{FONT_STACK}" font-size="15" fill="#c9d4e4">'
            f'Time window: {escape(str(metric["window"]))} | Confidence: {escape(str(metric["confidence"]))} | '
            f'Source: {escape(str(metric["source"]))}</text>'
        )
        svg.append(f'<text x="80" y="{row_y + 54}" font-family="{FONT_STACK}" font-size="15" fill="#9eb1ca">{escape(metric["note"])}</text>')
        svg.append(f'<rect x="{bar_x}" y="{row_y - 18}" width="{bar_width}" height="22" rx="11" fill="#111b2a"/>')
        if metric["value"] > 0:
            value_log = math.log10(metric["value"])
            length = 88.0 + ((value_log - min_log) / (max_log - min_log)) * (bar_width - 88.0)
            svg.append(
                f'<rect x="{bar_x}" y="{row_y - 18}" width="{length:.2f}" height="22" rx="11" fill="{metric["color"]}" opacity="0.92"/>'
            )
        svg.append(
            f'<text x="{bar_x + bar_width + 24}" y="{row_y}" font-family="{FONT_STACK}" font-size="22" font-weight="700" fill="#fefefe">{escape(format_compact_percent(metric["value"]))}</text>'
        )
        row_y += 110

    svg.append(
        f'<text x="80" y="716" font-family="{FONT_STACK}" font-size="14" fill="#d5e2f3">'
        f'Deploy recommendation: {escape(str(scoreboard["deploy_recommendation"]))} | '
        f'Forecast delta vs active: {escape(format_compact_percent(as_number(scoreboard["forecast_arr_delta_pct"], default=0.0)))} | '
        f'Sample: {escape(scoreboard["sample_size_annotation"])}</text>'
    )
    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def axis_labels(min_value: float, max_value: float, count: int, formatter) -> list[tuple[str, float]]:
    labels = []
    if count <= 1:
        return labels
    for index in range(count):
        ratio = index / (count - 1)
        value = max_value - ((max_value - min_value) * ratio)
        y_value = 170 + (360 / (count - 1)) * index
        labels.append((formatter(value), y_value))
    return labels


def format_window(velocity: dict[str, Any]) -> str:
    start = velocity.get("window_started_at")
    end = velocity.get("window_ended_at")
    if start and end:
        return f"{format_timestamp(start)} -> {format_timestamp(end)} ({velocity['window_hours']:.2f}h)"
    return f"{velocity['window_hours']:.2f}h"


def format_timestamp(value: str | datetime | None) -> str:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return "unknown"
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def format_axis_time(timestamp: datetime) -> str:
    return timestamp.strftime("%H:%M")


def format_usd(value: float | None) -> str:
    numeric = as_number(value, default=0.0)
    return f"${numeric:,.2f}"


def format_compact_percent(value: float | None) -> str:
    numeric = abs(as_number(value, default=0.0))
    sign = "-" if as_number(value, default=0.0) < 0 else ""
    if numeric >= 1_000_000:
        return f"{sign}{numeric / 1_000_000:.2f}M%"
    if numeric >= 1_000:
        return f"{sign}{numeric / 1_000:.1f}k%"
    return f"{sign}{numeric:,.1f}%"


def wrap_text(text: str, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(escape(current))
            current = word
    lines.append(escape(current))
    return lines


def build_fill_counts_by_timestamp(btc5_window_rows_path: Path, timestamps: list[datetime]) -> list[int]:
    rows = load_optional_json(btc5_window_rows_path) or []
    live_timestamps = []
    for row in rows:
        if row.get("order_status") != "live_filled":
            continue
        timestamp = parse_timestamp(row.get("updated_at"))
        if timestamp is not None:
            live_timestamps.append(timestamp)
    live_timestamps.sort()
    counts = []
    for timestamp in timestamps:
        count = 0
        for live_timestamp in live_timestamps:
            if live_timestamp <= timestamp:
                count += 1
        counts.append(count)
    return counts


def load_json(path: Path) -> dict[str, Any]:
    payload = load_optional_json(path)
    if payload is None:
        raise FileNotFoundError(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def load_optional_json(path: Path | None) -> dict[str, Any] | list[Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def to_repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def parse_timestamp(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def isoformat(timestamp: datetime | None) -> str | None:
    if timestamp is None:
        return None
    return timestamp.astimezone(UTC).isoformat()


def get_path(payload: dict[str, Any] | None, dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def pick_first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def normalize_confidence_label(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    return text if text in CONFIDENCE_RANK else "unknown"


def normalize_deploy_recommendation(value: Any) -> str:
    text = str(value or "hold").strip().lower()
    return text if text in DEPLOYMENT_RANK else "hold"


def as_number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric) or math.isinf(numeric):
        return default
    return numeric


def as_int(value: Any, default: int = 0) -> int:
    numeric = as_number(value)
    if numeric is None:
        return default
    return int(round(numeric))


def as_int_or_none(value: Any) -> int | None:
    numeric = as_number(value)
    if numeric is None:
        return None
    return int(round(numeric))


def git_count(repo_root: Path, args: list[str]) -> int:
    try:
        output = subprocess.check_output(
            ["git", *args],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return int(output)
    except Exception:
        return 0


def git_first_commit_date(repo_root: Path) -> datetime | None:
    try:
        output = subprocess.check_output(
            ["git", "log", "--reverse", "--format=%cI", "--max-count=1"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None
    return parse_timestamp(output)


if __name__ == "__main__":
    main()
