#!/usr/bin/env python3
"""Run the BTC5 autoresearch cycle continuously on the local machine."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BASE_ENV = Path("config/btc5_strategy.env")
DEFAULT_OVERRIDE_ENV = Path("state/btc5_autoresearch.env")
DEFAULT_CYCLE_REPORT_DIR = Path("reports/btc5_autoresearch")
DEFAULT_CURRENT_PROBE_LATEST = Path("reports/btc5_autoresearch_current_probe/latest.json")
DEFAULT_LOOP_REPORT_DIR = Path("reports/btc5_autoresearch_loop")
DEFAULT_HYPOTHESIS_REPORT_DIR = Path("reports/btc5_hypothesis_lab")
DEFAULT_REGIME_POLICY_REPORT_DIR = Path("reports/btc5_regime_policy_lab")
DEFAULT_ARR_TSV = Path("research/btc5_arr_progress.tsv")
DEFAULT_ARR_SVG = Path("research/btc5_arr_progress.svg")
DEFAULT_ARR_SUMMARY_MD = Path("research/btc5_arr_summary.md")
DEFAULT_ARR_LATEST_JSON = Path("research/btc5_arr_latest.json")
DEFAULT_HYPOTHESIS_FRONTIER_TSV = Path("research/btc5_hypothesis_frontier.tsv")
DEFAULT_HYPOTHESIS_FRONTIER_SVG = Path("research/btc5_hypothesis_frontier.svg")
DEFAULT_HYPOTHESIS_FRONTIER_SUMMARY_MD = Path("research/btc5_hypothesis_frontier_summary.md")
DEFAULT_HYPOTHESIS_FRONTIER_LATEST_JSON = Path("research/btc5_hypothesis_frontier_latest.json")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_cycle_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_btc5_autoresearch_cycle.py"),
        "--db-path",
        str(args.db_path),
        "--strategy-env",
        str(args.strategy_env),
        "--override-env",
        str(args.override_env),
        "--report-dir",
        str(args.cycle_report_dir),
        "--current-probe-latest",
        str(args.current_probe_latest),
        "--paths",
        str(args.paths),
        "--block-size",
        str(args.block_size),
        "--top-grid-candidates",
        str(args.top_grid_candidates),
        "--min-replay-fills",
        str(args.min_replay_fills),
        "--loss-limit-usd",
        str(args.loss_limit_usd),
        "--seed",
        str(args.seed),
        "--archive-glob",
        str(args.archive_glob),
        "--remote-cache-json",
        str(args.remote_cache_json),
        "--min-median-arr-improvement-pct",
        str(args.min_median_arr_improvement_pct),
        "--min-median-pnl-improvement-usd",
        str(args.min_median_pnl_improvement_usd),
        "--min-replay-pnl-improvement-usd",
        str(args.min_replay_pnl_improvement_usd),
        "--max-profit-prob-drop",
        str(args.max_profit_prob_drop),
        "--max-p95-drawdown-increase-usd",
        str(args.max_p95_drawdown_increase_usd),
        "--max-loss-hit-prob-increase",
        str(args.max_loss_hit_prob_increase),
        "--min-fill-lift",
        str(args.min_fill_lift),
        "--min-fill-retention-ratio",
        str(args.min_fill_retention_ratio),
        "--regime-max-session-overrides",
        str(args.regime_max_session_overrides),
        "--regime-top-single-overrides-per-session",
        str(args.regime_top_single_overrides_per_session),
        "--regime-max-composed-candidates",
        str(args.regime_max_composed_candidates),
    ]
    if args.service_name:
        cmd.extend(["--service-name", str(args.service_name)])
    if args.include_archive_csvs:
        cmd.append("--include-archive-csvs")
    if args.refresh_remote:
        cmd.append("--refresh-remote")
    if args.restart_on_promote:
        cmd.append("--restart-on-promote")
    return cmd


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _run_hook(command: str) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
    }


def _render_arr_progress(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "render_btc5_arr_progress.py"),
        "--history-jsonl",
        str(args.loop_report_dir / "history.jsonl"),
        "--tsv-out",
        str(args.arr_tsv_out),
        "--svg-out",
        str(args.arr_svg_out),
        "--summary-md-out",
        str(args.arr_summary_md_out),
        "--latest-json-out",
        str(args.arr_latest_json_out),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
    }


def _run_hypothesis_lab(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "btc5_hypothesis_lab.py"),
        "--db-path",
        str(args.db_path),
        "--output-dir",
        str(args.hypothesis_report_dir),
        "--paths",
        str(args.paths),
        "--block-size",
        str(args.block_size),
        "--loss-limit-usd",
        str(args.loss_limit_usd),
        "--seed",
        str(args.seed),
    ]
    if args.include_archive_csvs:
        command.append("--include-archive-csvs")
    if args.refresh_remote:
        command.append("--refresh-remote")
    command.extend(["--archive-glob", str(args.archive_glob)])
    command.extend(["--remote-cache-json", str(args.remote_cache_json)])
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=240,
    )
    latest_summary = _load_json(args.hypothesis_report_dir / "summary.json")
    best_hypothesis = (latest_summary or {}).get("best_hypothesis") or {}
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
        "best_hypothesis": (best_hypothesis.get("hypothesis") or {}),
        "best_summary": (best_hypothesis.get("summary") or {}),
        "recommended_session_policy": (latest_summary or {}).get("recommended_session_policy") or [],
    }


def _run_regime_policy_lab(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "btc5_regime_policy_lab.py"),
        "--db-path",
        str(args.db_path),
        "--strategy-env",
        str(args.strategy_env),
        "--override-env",
        str(args.override_env),
        "--output-dir",
        str(args.regime_policy_report_dir),
        "--paths",
        str(args.paths),
        "--block-size",
        str(args.block_size),
        "--loss-limit-usd",
        str(args.loss_limit_usd),
        "--seed",
        str(args.seed),
        "--min-replay-fills",
        str(args.min_replay_fills),
    ]
    if args.include_archive_csvs:
        command.append("--include-archive-csvs")
    if args.refresh_remote:
        command.append("--refresh-remote")
    command.extend(["--archive-glob", str(args.archive_glob)])
    command.extend(["--remote-cache-json", str(args.remote_cache_json)])
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=240,
    )
    latest_summary = _load_json(args.regime_policy_report_dir / "summary.json")
    best_policy = (latest_summary or {}).get("best_policy") or {}
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
        "best_policy": (best_policy.get("policy") or {}),
        "best_summary": {
            "continuation": (best_policy.get("continuation") or {}),
            "historical": (best_policy.get("historical") or {}),
            "monte_carlo": (best_policy.get("monte_carlo") or {}),
        },
        "recommended_session_policy": (latest_summary or {}).get("recommended_session_policy") or [],
    }


def _render_hypothesis_frontier(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "render_btc5_hypothesis_frontier.py"),
        "--history-jsonl",
        str(args.loop_report_dir / "history.jsonl"),
        "--tsv-out",
        str(args.hypothesis_frontier_tsv_out),
        "--svg-out",
        str(args.hypothesis_frontier_svg_out),
        "--summary-md-out",
        str(args.hypothesis_frontier_summary_md_out),
        "--latest-json-out",
        str(args.hypothesis_frontier_latest_json_out),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
    }


def _build_entry(
    *,
    cycle_command: list[str],
    cycle_result: subprocess.CompletedProcess[str],
    cycle_payload: dict[str, Any] | None,
    started_at: datetime,
    finished_at: datetime,
    hook_result: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = (cycle_payload or {}).get("decision") or {}
    best_profile = ((cycle_payload or {}).get("best_candidate") or {}).get("profile") or {}
    active_profile = (cycle_payload or {}).get("active_profile") or {}
    arr = (cycle_payload or {}).get("arr_tracking") or {}
    public_forecast_selection = (cycle_payload or {}).get("public_forecast_selection") or {}
    public_selected = public_forecast_selection.get("selected") or {}
    package_confidence_reasons = list((cycle_payload or {}).get("package_confidence_reasons") or [])
    package_missing_evidence = list((cycle_payload or {}).get("package_missing_evidence") or [])
    best_live_package = (cycle_payload or {}).get("best_live_package") or {}
    best_raw_package = (cycle_payload or {}).get("best_raw_research_package") or {}
    execution_drag_summary = (cycle_payload or {}).get("execution_drag_summary") or {}
    one_sided_bias_recommendation = (cycle_payload or {}).get("one_sided_bias_recommendation") or {}
    size_aware_deployment = (cycle_payload or {}).get("size_aware_deployment") or {}
    package_ranking = (cycle_payload or {}).get("package_ranking") or {}
    current_probe = (cycle_payload or {}).get("current_probe") or {}
    probe_feedback = (cycle_payload or {}).get("probe_feedback") or {}
    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "cycle_command": cycle_command,
        "cycle_returncode": cycle_result.returncode,
        "status": "ok" if cycle_result.returncode == 0 and cycle_payload else "error",
        "decision": decision,
        "best_profile": best_profile,
        "active_profile": active_profile,
        "arr": {
            "active_median_arr_pct": arr.get("current_median_arr_pct"),
            "best_median_arr_pct": arr.get("best_median_arr_pct"),
            "median_arr_delta_pct": arr.get("median_arr_delta_pct"),
            "active_p05_arr_pct": arr.get("current_p05_arr_pct"),
            "best_p05_arr_pct": arr.get("best_p05_arr_pct"),
            "historical_arr_delta_pct": arr.get("historical_arr_delta_pct"),
            "replay_pnl_delta_usd": decision.get("replay_pnl_delta_usd"),
            "profit_probability_delta": decision.get("profit_probability_delta"),
            "fill_lift": decision.get("fill_lift"),
        },
        "active_runtime_package": (cycle_payload or {}).get("active_runtime_package") or {},
        "best_runtime_package": (cycle_payload or {}).get("best_runtime_package") or {},
        "selected_active_runtime_package": (cycle_payload or {}).get("selected_active_runtime_package") or {},
        "selected_best_runtime_package": (cycle_payload or {}).get("selected_best_runtime_package") or {},
        "selected_deploy_recommendation": (cycle_payload or {}).get("selected_deploy_recommendation") or (cycle_payload or {}).get("deploy_recommendation") or "hold",
        "selected_package_confidence_label": (cycle_payload or {}).get("selected_package_confidence_label") or (cycle_payload or {}).get("package_confidence_label") or "low",
        "selected_package_confidence_reasons": list((cycle_payload or {}).get("selected_package_confidence_reasons") or (cycle_payload or {}).get("package_confidence_reasons") or []),
        "package_class": (cycle_payload or {}).get("package_class"),
        "package_candidate_class": (cycle_payload or {}).get("package_candidate_class"),
        "package_class_reason": (cycle_payload or {}).get("package_class_reason"),
        "package_class_reason_tags": list((cycle_payload or {}).get("package_class_reason_tags") or []),
        "selected_package_class": (cycle_payload or {}).get("selected_package_class") or (cycle_payload or {}).get("package_class"),
        "selected_package_candidate_class": (cycle_payload or {}).get("selected_package_candidate_class") or (cycle_payload or {}).get("package_candidate_class"),
        "selected_package_class_reason": (cycle_payload or {}).get("selected_package_class_reason") or (cycle_payload or {}).get("package_class_reason"),
        "selected_package_class_reason_tags": list((cycle_payload or {}).get("selected_package_class_reason_tags") or (cycle_payload or {}).get("package_class_reason_tags") or []),
        "promoted_package_selected": bool((cycle_payload or {}).get("promoted_package_selected")),
        "deploy_recommendation": (cycle_payload or {}).get("deploy_recommendation") or "hold",
        "package_confidence_label": (cycle_payload or {}).get("package_confidence_label") or "low",
        "package_confidence_reasons": package_confidence_reasons,
        "package_missing_evidence": package_missing_evidence,
        "validation_live_filled_rows": int((cycle_payload or {}).get("validation_live_filled_rows") or 0),
        "generalization_ratio": float((cycle_payload or {}).get("generalization_ratio") or 0.0),
        "public_forecast_selection": public_forecast_selection,
        "public_forecast_source_artifact": (cycle_payload or {}).get("public_forecast_source_artifact") or public_selected.get("source_artifact"),
        "public_forecast_arr_delta_pct": float(public_selected.get("forecast_arr_delta_pct") or 0.0),
        "best_live_package": best_live_package,
        "best_raw_research_package": best_raw_package,
        "execution_drag_summary": execution_drag_summary,
        "one_sided_bias_recommendation": one_sided_bias_recommendation,
        "size_aware_deployment": size_aware_deployment,
        "package_ranking": package_ranking,
        "current_probe": current_probe,
        "probe_feedback": probe_feedback,
        "probe_freshness_hours": current_probe.get("probe_freshness_hours"),
        "current_probe_path": (cycle_payload or {}).get("current_probe_path"),
        "runtime_load_status": (cycle_payload or {}).get("runtime_load_status") or {},
        "capital_scale_recommendation": (cycle_payload or {}).get("capital_scale_recommendation") or {},
        "capital_stage_recommendation": (cycle_payload or {}).get("capital_stage_recommendation") or {},
        "recommended_session_policy": (cycle_payload or {}).get("recommended_session_policy") or [],
        "artifacts": (cycle_payload or {}).get("artifacts") or {},
        "hook": hook_result,
        "stdout_tail": (cycle_result.stdout or "").strip()[-1000:],
        "stderr_tail": (cycle_result.stderr or "").strip()[-1000:],
    }


def _parse_history_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _safe_finished_at(entry: dict[str, Any]) -> datetime | None:
    raw = str(entry.get("finished_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _velocity_window(entries: list[dict[str, Any]], *, hours: int, now: datetime) -> dict[str, Any]:
    cutoff = now.timestamp() - float(hours * 3600)
    in_window = [
        entry
        for entry in entries
        if (_safe_finished_at(entry) is not None and _safe_finished_at(entry).timestamp() >= cutoff)
    ]
    in_window.sort(key=lambda item: _safe_finished_at(item) or now)
    cycles = len(in_window)
    if cycles == 0:
        return {
            "window_hours": float(hours),
            "cycles_in_window": 0,
            "forecast_arr_gain_pct": 0.0,
            "forecast_arr_gain_pct_per_day": 0.0,
            "validation_fill_growth": 0,
            "validation_fill_growth_per_day": 0.0,
            "promotion_rate": 0.0,
        }
    first = in_window[0]
    last = in_window[-1]
    first_arr = float(first.get("public_forecast_arr_delta_pct") or 0.0)
    last_arr = float(last.get("public_forecast_arr_delta_pct") or 0.0)
    first_fills = int(first.get("validation_live_filled_rows") or 0)
    last_fills = int(last.get("validation_live_filled_rows") or 0)
    gain = last_arr - first_arr
    fill_growth = last_fills - first_fills
    elapsed_hours = max(1e-9, (_safe_finished_at(last) - _safe_finished_at(first)).total_seconds() / 3600.0) if cycles > 1 else float(hours)
    promotions = sum(1 for entry in in_window if str((entry.get("decision") or {}).get("action") or "").lower() == "promote")
    return {
        "window_hours": float(hours),
        "cycles_in_window": cycles,
        "forecast_arr_gain_pct": round(gain, 4),
        "forecast_arr_gain_pct_per_day": round(gain / (elapsed_hours / 24.0), 4) if elapsed_hours > 0 else 0.0,
        "validation_fill_growth": int(fill_growth),
        "validation_fill_growth_per_day": round(fill_growth / (elapsed_hours / 24.0), 4) if elapsed_hours > 0 else 0.0,
        "promotion_rate": round(promotions / float(cycles), 4),
    }


def _build_velocity_summary(entries: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    return {
        "window_24h": _velocity_window(entries, hours=24, now=now),
        "window_7d": _velocity_window(entries, hours=24 * 7, now=now),
    }


def _cadence_decision(
    *,
    entry: dict[str, Any],
    previous_entry: dict[str, Any] | None,
    base_interval_seconds: int,
) -> dict[str, Any]:
    base_interval = max(60, int(base_interval_seconds))
    current_probe = entry.get("current_probe") if isinstance(entry.get("current_probe"), dict) else {}
    previous_probe = (
        previous_entry.get("current_probe")
        if isinstance((previous_entry or {}).get("current_probe"), dict)
        else {}
    )
    live_fill_delta = _safe_int(
        current_probe.get("live_filled_rows_delta"),
        _safe_int(current_probe.get("live_filled_row_count"), 0)
        - _safe_int(previous_probe.get("live_filled_row_count"), 0),
    )
    validation_delta = _safe_int(
        current_probe.get("validation_live_filled_rows_delta"),
        _safe_int(entry.get("validation_live_filled_rows"), 0)
        - _safe_int((previous_entry or {}).get("validation_live_filled_rows"), 0),
    )
    probe_freshness_hours = _safe_float(current_probe.get("probe_freshness_hours"), 9999.0)
    stage_not_ready_tags = {
        str(tag).strip()
        for tag in (current_probe.get("stage_not_ready_reason_tags") or [])
        if str(tag).strip()
    }
    package_class = str(entry.get("selected_package_class") or entry.get("package_class") or "").strip().lower()
    previous_package_class = str(
        (previous_entry or {}).get("selected_package_class") or (previous_entry or {}).get("package_class") or ""
    ).strip().lower()
    package_class_changed = bool(package_class and previous_package_class and package_class != previous_package_class)
    weak_regime = bool(
        {"trailing_12_live_filled_non_positive", "trailing_40_live_filled_non_positive", "recent_loss_cluster_flags_present"}
        & stage_not_ready_tags
    ) or package_class in {"shadow_only", "suppress"}
    has_new_evidence = live_fill_delta > 0 or validation_delta > 0
    if has_new_evidence:
        if live_fill_delta > 0 and (weak_regime or package_class_changed):
            multiplier = 0.25 if (validation_delta > 0 or package_class_changed) else 0.3
            reason = "fresh_fills_arrived_in_weak_or_changed_regime"
        else:
            multiplier = 0.4 if live_fill_delta > 0 and validation_delta > 0 else 0.5
            reason = "new_fills_or_validation_rows_arrived"
        recommended = max(60, int(round(base_interval * multiplier)))
        mode = "accelerated"
    elif package_class_changed:
        recommended = max(60, int(round(base_interval * 0.5)))
        mode = "accelerated"
        reason = "package_class_changed_without_new_evidence"
    elif probe_freshness_hours > 6.0:
        recommended = min(1800, int(round(base_interval * 2.0)))
        mode = "slowed"
        reason = "probe_stale_and_no_new_evidence"
    else:
        stable_package_class = bool(
            package_class and previous_package_class and package_class == previous_package_class
        )
        multiplier = 2.0 if stable_package_class and package_class in {"hold_current", "shadow_only", "suppress"} else 1.5
        recommended = min(1800 if multiplier >= 2.0 else 1200, int(round(base_interval * multiplier)))
        mode = "slowed"
        reason = "evidence_flat_and_package_class_stable" if multiplier >= 2.0 else "no_new_evidence"
    return {
        "mode": mode,
        "reason": reason,
        "base_interval_seconds": int(base_interval),
        "recommended_interval_seconds": int(recommended),
        "live_filled_rows_delta": int(live_fill_delta),
        "validation_live_filled_rows_delta": int(validation_delta),
        "probe_freshness_hours": round(probe_freshness_hours, 4) if probe_freshness_hours < 9999.0 else None,
        "package_class": package_class or None,
        "previous_package_class": previous_package_class or None,
        "package_class_changed": package_class_changed,
    }


def _resolved_max_cycles(args: argparse.Namespace) -> int:
    explicit_max_cycles = _safe_int(getattr(args, "max_cycles", 0), 0)
    if explicit_max_cycles > 0:
        return explicit_max_cycles
    if bool(getattr(args, "once", False)):
        return 1
    return 0


def _write_loop_reports(loop_report_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    loop_report_dir.mkdir(parents=True, exist_ok=True)
    latest_path = loop_report_dir / "latest.json"
    latest_md_path = loop_report_dir / "latest.md"
    history_path = loop_report_dir / "history.jsonl"
    previous = _load_json(latest_path) or {}
    previous_summary = previous.get("summary") or {}
    summary = {
        "cycles_total": int(previous_summary.get("cycles_total") or 0) + 1,
        "holds_total": int(previous_summary.get("holds_total") or 0)
        + (1 if entry.get("decision", {}).get("action") == "hold" else 0),
        "promotions_total": int(previous_summary.get("promotions_total") or 0)
        + (1 if entry.get("decision", {}).get("action") == "promote" else 0),
        "errors_total": int(previous_summary.get("errors_total") or 0)
        + (1 if entry.get("status") != "ok" else 0),
        "last_cycle_started_at": entry["started_at"],
        "last_cycle_finished_at": entry["finished_at"],
    }
    payload = {"summary": summary, "latest_entry": entry}
    history_entries = _parse_history_entries(history_path)
    history_entries.append(entry)
    payload["velocity_summary"] = _build_velocity_summary(history_entries, now=_now_utc())
    payload["decision"] = entry.get("decision") or {}
    payload["decision_action"] = (entry.get("decision") or {}).get("action") or "hold"
    payload["decision_reason"] = (entry.get("decision") or {}).get("reason") or "cycle_failed"
    payload["arr"] = entry.get("arr") or {}
    payload["deploy_recommendation"] = entry.get("deploy_recommendation") or "hold"
    payload["selected_deploy_recommendation"] = entry.get("selected_deploy_recommendation") or payload["deploy_recommendation"]
    payload["package_confidence_label"] = entry.get("package_confidence_label") or "low"
    payload["selected_package_confidence_label"] = entry.get("selected_package_confidence_label") or payload["package_confidence_label"]
    payload["package_confidence_reasons"] = list(entry.get("package_confidence_reasons") or [])
    payload["selected_package_confidence_reasons"] = list(entry.get("selected_package_confidence_reasons") or payload["package_confidence_reasons"])
    payload["package_class"] = entry.get("package_class")
    payload["package_candidate_class"] = entry.get("package_candidate_class")
    payload["package_class_reason"] = entry.get("package_class_reason")
    payload["package_class_reason_tags"] = list(entry.get("package_class_reason_tags") or [])
    payload["selected_package_class"] = entry.get("selected_package_class") or payload["package_class"]
    payload["selected_package_candidate_class"] = entry.get("selected_package_candidate_class") or payload["package_candidate_class"]
    payload["selected_package_class_reason"] = entry.get("selected_package_class_reason") or payload["package_class_reason"]
    payload["selected_package_class_reason_tags"] = list(
        entry.get("selected_package_class_reason_tags") or payload["package_class_reason_tags"]
    )
    payload["public_forecast_selection"] = entry.get("public_forecast_selection") or {}
    payload["public_forecast_source_artifact"] = entry.get("public_forecast_source_artifact")
    payload["active_runtime_package"] = entry.get("active_runtime_package") or {}
    payload["best_runtime_package"] = entry.get("best_runtime_package") or {}
    payload["selected_active_runtime_package"] = entry.get("selected_active_runtime_package") or {}
    payload["selected_best_runtime_package"] = entry.get("selected_best_runtime_package") or {}
    payload["promoted_package_selected"] = bool(entry.get("promoted_package_selected"))
    payload["best_live_package"] = entry.get("best_live_package") or {}
    payload["best_raw_research_package"] = entry.get("best_raw_research_package") or {}
    payload["execution_drag_summary"] = entry.get("execution_drag_summary") or {}
    payload["one_sided_bias_recommendation"] = entry.get("one_sided_bias_recommendation") or {}
    payload["size_aware_deployment"] = entry.get("size_aware_deployment") or {}
    payload["package_ranking"] = entry.get("package_ranking") or {}
    payload["current_probe"] = entry.get("current_probe") or {}
    payload["probe_feedback"] = entry.get("probe_feedback") or {}
    payload["probe_freshness_hours"] = entry.get("probe_freshness_hours")
    payload["current_probe_path"] = entry.get("current_probe_path")
    payload["cadence"] = entry.get("cadence") or {}
    payload["runtime_load_status"] = entry.get("runtime_load_status") or {}
    payload["capital_scale_recommendation"] = entry.get("capital_scale_recommendation") or {}
    payload["capital_stage_recommendation"] = entry.get("capital_stage_recommendation") or {}
    latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    latest_md_path.write_text(
        "\n".join(
            [
                "# BTC5 Local Autoresearch Loop",
                "",
                f"- Cycles total: `{summary['cycles_total']}`",
                f"- Promotions total: `{summary['promotions_total']}`",
                f"- Holds total: `{summary['holds_total']}`",
                f"- Errors total: `{summary['errors_total']}`",
                f"- Last status: `{entry['status']}`",
                f"- Last action: `{entry.get('decision', {}).get('action', 'error')}`",
                f"- Last reason: `{entry.get('decision', {}).get('reason', 'cycle_failed')}`",
                f"- Last best profile: `{entry.get('best_profile', {}).get('name', 'none')}`",
                f"- Last active profile: `{entry.get('active_profile', {}).get('name', 'none')}`",
                f"- Last best hypothesis: `{((entry.get('hypothesis_lab') or {}).get('best_hypothesis') or {}).get('name', 'none')}`",
                f"- Last best regime policy: `{((entry.get('regime_policy_lab') or {}).get('best_policy') or {}).get('name', 'none')}`",
                f"- Last best session policy records: `{len(entry.get('recommended_session_policy') or [])}`",
                f"- Last package decision: `{entry.get('deploy_recommendation', 'hold')}`",
                f"- Last package confidence: `{entry.get('package_confidence_label', 'low')}`",
                f"- Last package class: `{entry.get('package_class', 'none')}`",
                f"- Last selected package class: `{entry.get('selected_package_class', entry.get('package_class', 'none'))}`",
                f"- Last package confidence reasons: `{'; '.join(entry.get('package_confidence_reasons') or ['none'])}`",
                f"- Last missing evidence: `{'; '.join(entry.get('package_missing_evidence') or ['none'])}`",
                f"- Last public forecast source: `{entry.get('public_forecast_source_artifact', 'none')}`",
                f"- Last public forecast selection reason: `{((entry.get('public_forecast_selection') or {}).get('selection_reason') or 'none')}`",
                f"- Last probe freshness hours: `{entry.get('probe_freshness_hours')}`",
                f"- Last validation row delta: `{(((entry.get('current_probe') or {}).get('validation_live_filled_rows_delta')) or 0)}`",
                f"- Last live-fill delta: `{(((entry.get('current_probe') or {}).get('live_filled_rows_delta')) or 0)}`",
                f"- Last best package profile: `{((entry.get('best_runtime_package') or {}).get('profile') or {}).get('name', 'none')}`",
                f"- Last active package profile: `{((entry.get('active_runtime_package') or {}).get('profile') or {}).get('name', 'none')}`",
                f"- Last best package session-policy records: `{len(((entry.get('best_runtime_package') or {}).get('session_policy') or []))}`",
                f"- Last best live package source: `{(entry.get('best_live_package') or {}).get('source', 'none')}`",
                f"- Last best raw package source: `{(entry.get('best_raw_research_package') or {}).get('source', 'none')}`",
                f"- Last live-candidate package count: `{(((entry.get('package_ranking') or {}).get('package_set_breakdown') or {}).get('live_candidate', 0))}`",
                f"- Last shadow-only package count: `{(((entry.get('package_ranking') or {}).get('package_set_breakdown') or {}).get('shadow_only', 0))}`",
                f"- Last hold-current package count: `{(((entry.get('package_ranking') or {}).get('package_set_breakdown') or {}).get('hold_current', 0))}`",
                f"- Last suppress package count: `{(((entry.get('package_ranking') or {}).get('package_set_breakdown') or {}).get('suppress', 0))}`",
                f"- Last top package set: `{((entry.get('package_ranking') or {}).get('top_package_set') or 'none')}`",
                f"- Last one-sided bias recommendation: `{(entry.get('one_sided_bias_recommendation') or {}).get('recommendation', 'balanced_directional_bias')}`",
                f"- Last median ARR delta: `{(entry.get('arr') or {}).get('median_arr_delta_pct', 0.0)}`",
                f"- Last replay PnL delta (USD): `{(entry.get('arr') or {}).get('replay_pnl_delta_usd', 0.0)}`",
                f"- Last profit-probability delta: `{(entry.get('arr') or {}).get('profit_probability_delta', 0.0)}`",
                f"- Last fill lift: `{(entry.get('arr') or {}).get('fill_lift', 0)}`",
                f"- Last skip-price count: `{(entry.get('execution_drag_summary') or {}).get('skip_price_count', 0)}`",
                f"- Last order-failed count: `{(entry.get('execution_drag_summary') or {}).get('order_failed_count', 0)}`",
                f"- Last cancelled-unfilled count: `{(entry.get('execution_drag_summary') or {}).get('cancelled_unfilled_count', 0)}`",
                f"- Last runtime override written: `{((entry.get('runtime_load_status') or {}).get('override_env_written'))}`",
                f"- Last runtime session-policy records: `{((entry.get('runtime_load_status') or {}).get('session_policy_records'))}`",
                f"- Last runtime restart requested: `{((entry.get('runtime_load_status') or {}).get('service_restart_requested'))}`",
                f"- Last capital status: `{((entry.get('capital_scale_recommendation') or {}).get('status') or 'hold')}`",
                f"- Last capital tranche (USD): `{((entry.get('capital_scale_recommendation') or {}).get('recommended_tranche_usd') or 0)}`",
                f"- Last capital reason: `{((entry.get('capital_scale_recommendation') or {}).get('reason') or 'none')}`",
                f"- Last capital stage: `{((entry.get('capital_stage_recommendation') or {}).get('recommended_stage') or 1)}`",
                f"- Last capital max trade (USD): `{((entry.get('capital_stage_recommendation') or {}).get('recommended_max_trade_usd') or 10)}`",
                f"- Last stage guardrails passed: `{((entry.get('capital_stage_recommendation') or {}).get('promotion_guardrails_passed') or False)}`",
                f"- Last stage reason: `{((entry.get('capital_stage_recommendation') or {}).get('stage_reason') or 'none')}`",
                f"- Next cadence mode: `{((entry.get('cadence') or {}).get('mode') or 'none')}`",
                f"- Next cadence seconds: `{((entry.get('cadence') or {}).get('recommended_interval_seconds') or 0)}`",
                f"- Next cadence reason: `{((entry.get('cadence') or {}).get('reason') or 'none')}`",
                "",
                "## Timebound Velocity",
                "",
                f"- 24h cycles: `{payload['velocity_summary']['window_24h']['cycles_in_window']}`",
                f"- 24h forecast ARR gain (%): `{payload['velocity_summary']['window_24h']['forecast_arr_gain_pct']}`",
                f"- 24h forecast ARR gain (%/day): `{payload['velocity_summary']['window_24h']['forecast_arr_gain_pct_per_day']}`",
                f"- 24h validation fill growth: `{payload['velocity_summary']['window_24h']['validation_fill_growth']}`",
                f"- 24h validation fill growth/day: `{payload['velocity_summary']['window_24h']['validation_fill_growth_per_day']}`",
                f"- 24h promotion rate: `{payload['velocity_summary']['window_24h']['promotion_rate']}`",
                f"- 7d cycles: `{payload['velocity_summary']['window_7d']['cycles_in_window']}`",
                f"- 7d forecast ARR gain (%): `{payload['velocity_summary']['window_7d']['forecast_arr_gain_pct']}`",
                f"- 7d forecast ARR gain (%/day): `{payload['velocity_summary']['window_7d']['forecast_arr_gain_pct_per_day']}`",
                f"- 7d validation fill growth: `{payload['velocity_summary']['window_7d']['validation_fill_growth']}`",
                f"- 7d validation fill growth/day: `{payload['velocity_summary']['window_7d']['validation_fill_growth_per_day']}`",
                f"- 7d promotion rate: `{payload['velocity_summary']['window_7d']['promotion_rate']}`",
                f"- Last finished at: `{entry['finished_at']}`",
            ]
        )
        + "\n"
    )
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--strategy-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--override-env", type=Path, default=DEFAULT_OVERRIDE_ENV)
    parser.add_argument("--cycle-report-dir", type=Path, default=DEFAULT_CYCLE_REPORT_DIR)
    parser.add_argument("--current-probe-latest", type=Path, default=DEFAULT_CURRENT_PROBE_LATEST)
    parser.add_argument("--loop-report-dir", type=Path, default=DEFAULT_LOOP_REPORT_DIR)
    parser.add_argument("--hypothesis-report-dir", type=Path, default=DEFAULT_HYPOTHESIS_REPORT_DIR)
    parser.add_argument("--regime-policy-report-dir", type=Path, default=DEFAULT_REGIME_POLICY_REPORT_DIR)
    parser.add_argument("--service-name", default="")
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--top-grid-candidates", type=int, default=5)
    parser.add_argument("--min-replay-fills", type=int, default=12)
    parser.add_argument("--loss-limit-usd", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-archive-csvs", action="store_true")
    parser.add_argument(
        "--archive-glob",
        default="reports/btc_intraday_llm_bundle_*/raw/remote_btc5_window_trades.csv",
    )
    parser.add_argument("--refresh-remote", action="store_true")
    parser.add_argument("--remote-cache-json", type=Path, default=Path("reports/tmp_remote_btc5_window_rows.json"))
    parser.add_argument("--min-median-arr-improvement-pct", type=float, default=0.0)
    parser.add_argument("--min-median-pnl-improvement-usd", type=float, default=2.0)
    parser.add_argument("--min-replay-pnl-improvement-usd", type=float, default=1.0)
    parser.add_argument("--max-profit-prob-drop", type=float, default=0.01)
    parser.add_argument("--max-p95-drawdown-increase-usd", type=float, default=3.0)
    parser.add_argument("--max-loss-hit-prob-increase", type=float, default=0.03)
    parser.add_argument("--min-fill-lift", type=int, default=0)
    parser.add_argument("--min-fill-retention-ratio", type=float, default=0.85)
    parser.add_argument("--regime-max-session-overrides", type=int, default=2)
    parser.add_argument("--regime-top-single-overrides-per-session", type=int, default=2)
    parser.add_argument("--regime-max-composed-candidates", type=int, default=64)
    parser.add_argument("--restart-on-promote", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--on-promote-command", default="")
    parser.add_argument("--arr-tsv-out", type=Path, default=DEFAULT_ARR_TSV)
    parser.add_argument("--arr-svg-out", type=Path, default=DEFAULT_ARR_SVG)
    parser.add_argument("--arr-summary-md-out", type=Path, default=DEFAULT_ARR_SUMMARY_MD)
    parser.add_argument("--arr-latest-json-out", type=Path, default=DEFAULT_ARR_LATEST_JSON)
    parser.add_argument("--hypothesis-frontier-tsv-out", type=Path, default=DEFAULT_HYPOTHESIS_FRONTIER_TSV)
    parser.add_argument("--hypothesis-frontier-svg-out", type=Path, default=DEFAULT_HYPOTHESIS_FRONTIER_SVG)
    parser.add_argument(
        "--hypothesis-frontier-summary-md-out",
        type=Path,
        default=DEFAULT_HYPOTHESIS_FRONTIER_SUMMARY_MD,
    )
    parser.add_argument(
        "--hypothesis-frontier-latest-json-out",
        type=Path,
        default=DEFAULT_HYPOTHESIS_FRONTIER_LATEST_JSON,
    )
    parser.add_argument("--skip-arr-render", action="store_true")
    parser.add_argument("--skip-hypothesis-lab", action="store_true")
    parser.add_argument("--skip-regime-policy-lab", action="store_true")
    parser.add_argument("--skip-hypothesis-frontier-render", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    max_cycles = _resolved_max_cycles(args)
    cycle_count = 0
    while True:
        history_entries = _parse_history_entries(args.loop_report_dir / "history.jsonl")
        previous_entry = history_entries[-1] if history_entries else None
        started_at = _now_utc()
        cycle_command = _build_cycle_command(args)
        cycle_result = subprocess.run(
            cycle_command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        cycle_payload = _load_json(args.cycle_report_dir / "latest.json")
        hook_result = None
        if (
            cycle_result.returncode == 0
            and cycle_payload
            and (cycle_payload.get("decision") or {}).get("action") == "promote"
            and args.on_promote_command
        ):
            hook_result = _run_hook(args.on_promote_command)
        finished_at = _now_utc()
        entry = _build_entry(
            cycle_command=cycle_command,
            cycle_result=cycle_result,
            cycle_payload=cycle_payload,
            started_at=started_at,
            finished_at=finished_at,
            hook_result=hook_result,
        )
        entry["cadence"] = _cadence_decision(
            entry=entry,
            previous_entry=previous_entry,
            base_interval_seconds=int(args.interval_seconds),
        )
        if not args.skip_hypothesis_lab:
            entry["hypothesis_lab"] = _run_hypothesis_lab(args)
        if not args.skip_regime_policy_lab:
            entry["regime_policy_lab"] = _run_regime_policy_lab(args)
        loop_payload = _write_loop_reports(args.loop_report_dir, entry)
        if not args.skip_arr_render:
            loop_payload["arr_render"] = _render_arr_progress(args)
        if not args.skip_hypothesis_frontier_render:
            loop_payload["hypothesis_frontier_render"] = _render_hypothesis_frontier(args)
        print(json.dumps(loop_payload, indent=2, sort_keys=True))
        cycle_count += 1
        if max_cycles and cycle_count >= max_cycles:
            return 0
        recommended_interval_seconds = _safe_float(
            ((entry.get("cadence") or {}).get("recommended_interval_seconds")),
            float(args.interval_seconds),
        )
        sleep_seconds = max(0.0, recommended_interval_seconds - (finished_at - started_at).total_seconds())
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
