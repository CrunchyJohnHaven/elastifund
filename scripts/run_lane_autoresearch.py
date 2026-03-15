#!/usr/bin/env python3
"""Run one calibration-lane benchmark iteration and append it to the ledger."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.calibration_v1.benchmark import run_benchmark, write_benchmark_artifacts  # noqa: E402
from data_layer import crud, database  # noqa: E402
from flywheel.intelligence import FindingSpec, TaskSpec, record_finding_with_task  # noqa: E402
from scripts.render_lane_progress import render_progress  # noqa: E402


LEDGER_COLUMNS = [
    "run_id",
    "timestamp",
    "benchmark_id",
    "candidate_label",
    "description",
    "mutable_surface",
    "git_sha",
    "mutable_surface_sha256",
    "selected_variant",
    "benchmark_score",
    "brier",
    "ece",
    "log_loss",
    "status",
    "decision_reason",
    "warmup_rows",
    "holdout_rows",
    "packet_json",
    "packet_md",
    "mutation_cmd",
    "candidate_stale_reasons",
    "candidate_stage",
    "promotion_action",
    "promotion_gate_reasons",
    "expected_arr_delta",
    "expected_arr_delta_interval",
    "expected_improvement_velocity",
    "expected_improvement_velocity_interval",
    "candidate_confidence",
    "candidate_confidence_score",
    "candidate_confidence_source",
    "candidate_gate_quality",
    "candidate_information_gain_bps",
    "evaluation_burn_usd",
    "arr_per_burn_bps_per_usd",
    "candidate_edge_bps",
    "arr_per_compute_bps_per_usd",
    "model_tier",
    "estimated_compute_cost_usd",
    "arr_per_compute_usd",
]


ARR_SCALE_BPS = 10_000.0
DEFAULT_ARR_BURN_BPS_PER_ROW = 0.01
DEFAULT_CANDIDATE_STALE_MINUTES = 7 * 24 * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one calibration-lane autoresearch iteration.")
    parser.add_argument(
        "--manifest",
        default="benchmarks/calibration_v1/manifest.json",
        help="Frozen benchmark manifest",
    )
    parser.add_argument(
        "--ledger",
        default="research/results/calibration/results.tsv",
        help="Append-only results ledger",
    )
    parser.add_argument(
        "--progress-tsv",
        default="research/results/calibration/progress.tsv",
        help="Derived progress TSV path",
    )
    parser.add_argument(
        "--progress-svg",
        default="research/results/calibration/progress.svg",
        help="Derived progress SVG path",
    )
    parser.add_argument(
        "--summary-md",
        default="research/results/calibration/summary.md",
        help="Lane summary markdown path",
    )
    parser.add_argument(
        "--output-dir",
        default="research/results/calibration/packets",
        help="Directory for benchmark packets",
    )
    parser.add_argument(
        "--candidate-label",
        default="manual",
        help="Short label for the current candidate",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Free-text description recorded in the ledger",
    )
    parser.add_argument(
        "--mutation-cmd",
        help="Optional shell command that mutates the mutable surface before benchmarking",
    )
    parser.add_argument(
        "--control-db-url",
        help="Optional SQLAlchemy database URL for publishing flywheel review tasks",
    )
    parser.add_argument(
        "--keep-epsilon",
        type=float,
        default=1e-9,
        help="Minimum score delta required to mark a run as keep",
    )
    parser.add_argument(
        "--weekly-loop-report",
        default="research/results/calibration/weekly_loop.json",
        help="Write weekly candidate loop summary to this path",
    )
    parser.add_argument(
        "--candidate-stale-minutes",
        type=float,
        default=DEFAULT_CANDIDATE_STALE_MINUTES,
        help="Candidate is stale after this many minutes and cannot advance to paper/shadow",
    )
    parser.add_argument(
        "--arr-per-burn-min-bps-per-usd",
        type=float,
        default=0.35,
        help="Reject candidates where expected_arr_delta / burn_usd is below this value",
    )
    parser.add_argument(
        "--arr-per-compute-min-bps-per-usd",
        type=float,
        default=0.10,
        help="Reject candidates where expected conf-adjusted ARR per model compute dollar is below this value",
    )
    parser.add_argument(
        "--simulation-row-cost-usd",
        type=float,
        default=DEFAULT_ARR_BURN_BPS_PER_ROW,
        help="Per-dataset-row simulation burn proxy used for information-gain / capital scoring",
    )
    parser.add_argument(
        "--arr-gain-threshold-bps",
        type=float,
        default=0.0,
        help="Minimum confidence-adjusted ARR lift (bps) to pass the next stage",
    )
    parser.add_argument(
        "--paper-confidence-threshold",
        type=float,
        default=0.64,
        help="Confidence threshold required for paper-stage advancement",
    )
    parser.add_argument(
        "--shadow-confidence-threshold",
        type=float,
        default=0.74,
        help="Confidence threshold required for shadow-stage advancement",
    )
    parser.add_argument(
        "--promote-confidence-threshold",
        type=float,
        default=0.84,
        help="Confidence threshold required for a promotion recommendation",
    )
    parser.add_argument(
        "--routine-confidence-threshold",
        type=float,
        default=0.76,
        help="Confidence threshold for default routing class",
    )
    parser.add_argument(
        "--structured-confidence-threshold",
        type=float,
        default=0.58,
        help="Confidence threshold for structured routing class",
    )
    parser.add_argument(
        "--min-arr-lift-for-escalation-bps",
        type=float,
        default=0.10,
        help="Escalate routing only if this confidence-adjusted ARR lift remains positive",
    )
    parser.add_argument(
        "--arr-velocity-scale",
        type=float,
        default=1000.0,
        help="Scale factor for expected_improvement_velocity metric",
    )
    parser.add_argument(
        "--weekly-loop-window-days",
        type=float,
        default=7.0,
        help="Window in days for the weekly loop summary",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ledger_path = ROOT / args.ledger
    progress_tsv = ROOT / args.progress_tsv
    progress_svg = ROOT / args.progress_svg
    summary_md = ROOT / args.summary_md
    output_dir = ROOT / args.output_dir

    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_ledger(ledger_path)
    existing_rows = read_ledger(ledger_path)
    run_id = (max((int(row["run_id"]) for row in existing_rows), default=0) + 1)

    packet_stem = f"run_{run_id:04d}_{slugify(args.candidate_label)}"
    packet_json = output_dir / f"{packet_stem}.json"
    packet_md = output_dir / f"{packet_stem}.md"

    packet: dict[str, Any] | None = None
    status = "crash"
    decision_reason = "benchmark_failed"
    backup_path: Path | None = None
    mutable_surface = ROOT / "bot/adaptive_platt.py"

    try:
        if args.mutation_cmd:
            backup_path = backup_surface(mutable_surface)
            run_mutation(args.mutation_cmd)

        packet = run_benchmark(args.manifest, description=args.description)
        write_benchmark_artifacts(packet, json_path=packet_json, summary_path=packet_md)
        status, decision_reason = classify_run(existing_rows, packet, epsilon=args.keep_epsilon)
        if backup_path is not None and status != "keep":
            restore_surface(backup_path, mutable_surface)
    except Exception as exc:  # pragma: no cover - exercised through CLI behavior
        if backup_path is not None:
            restore_surface(backup_path, mutable_surface)
        packet = crash_packet(args.manifest, args.description, exc)
        packet_json.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
        packet_md.write_text(render_crash_markdown(packet), encoding="utf-8")
        status = "crash"
        decision_reason = type(exc).__name__
    finally:
        if backup_path is not None and backup_path.exists():
            backup_path.unlink()

    candidate_metrics = assess_candidate(
        packet=packet,
        existing_rows=existing_rows,
        status=status,
        decision_reason=decision_reason,
        stale_minutes=float(args.candidate_stale_minutes),
        arr_gain_threshold_bps=float(args.arr_gain_threshold_bps),
        arr_per_burn_min_bps_per_usd=float(args.arr_per_burn_min_bps_per_usd),
        row_cost_usd=float(args.simulation_row_cost_usd),
        paper_conf=float(args.paper_confidence_threshold),
        shadow_conf=float(args.shadow_confidence_threshold),
        promote_conf=float(args.promote_confidence_threshold),
        routine_conf=float(args.routine_confidence_threshold),
        structured_conf=float(args.structured_confidence_threshold),
        escalation_gain=float(args.min_arr_lift_for_escalation_bps),
        velocity_scale=float(args.arr_velocity_scale),
        arr_per_compute_min_bps_per_usd=float(args.arr_per_compute_min_bps_per_usd),
    )

    row = ledger_row(
        run_id=run_id,
        packet=packet,
        status=status,
        decision_reason=decision_reason,
        candidate_label=args.candidate_label,
        description=args.description,
        packet_json=display_path(packet_json),
        packet_md=display_path(packet_md),
        mutation_cmd=args.mutation_cmd or "",
        candidate_metrics=candidate_metrics,
    )
    append_ledger_row(ledger_path, row)

    records = read_ledger(ledger_path)
    render_progress(ledger_path, progress_tsv, progress_svg)
    write_summary(summary_md, rows=records, records_count=len(records))

    weekly_report = build_weekly_loop_report(
        rows=records,
        now=utc_now_iso_datetime(),
        window_minutes=max(7.0, 24 * 60 * float(args.weekly_loop_window_days)),
    )
    weekly_loop_report = ROOT / args.weekly_loop_report
    weekly_loop_report.parent.mkdir(parents=True, exist_ok=True)
    weekly_loop_report.write_text(json.dumps(weekly_report, indent=2, sort_keys=True), encoding="utf-8")

    task_info = None
    if args.control_db_url:
        task_info = publish_flywheel_review(
            control_db_url=args.control_db_url,
            row=row,
            candidate_metrics=assess_row_metrics(row),
        )

    result = {
        "run_id": run_id,
        "status": status,
        "decision_reason": decision_reason,
        "candidate_stage": row["candidate_stage"],
        "promotion_action": row["promotion_action"],
        "candidate_confidence": candidate_metrics["candidate_confidence"],
        "candidate_confidence_score": candidate_metrics["candidate_confidence_score"],
        "benchmark_score": row["benchmark_score"],
        "packet_json": display_path(packet_json),
        "packet_md": display_path(packet_md),
        "progress_tsv": display_path(progress_tsv),
        "progress_svg": display_path(progress_svg),
        "summary_md": display_path(summary_md),
        "weekly_loop_report": display_path(weekly_loop_report),
        "flywheel": task_info,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def ensure_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.write_text("\t".join(LEDGER_COLUMNS) + "\n", encoding="utf-8")


def read_ledger(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def append_ledger_row(path: Path, row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(row[column] for column in LEDGER_COLUMNS) + "\n")


def classify_run(
    existing_rows: list[dict[str, str]],
    packet: dict[str, Any],
    *,
    epsilon: float,
) -> tuple[str, str]:
    score = float(packet["selected_variant"]["benchmark_score"])
    prior_scores = [
        float(row["benchmark_score"])
        for row in existing_rows
        if row.get("benchmark_score")
    ]
    if not prior_scores:
        return "keep", "baseline_frontier"
    prior_best = max(prior_scores)
    if score > prior_best + epsilon:
        return "keep", "improved_frontier"
    return "discard", "below_frontier"


def assess_candidate(
    *,
    packet: dict[str, Any],
    existing_rows: list[dict[str, str]],
    status: str,
    decision_reason: str,
    stale_minutes: float,
    arr_gain_threshold_bps: float,
    arr_per_burn_min_bps_per_usd: float,
    row_cost_usd: float,
    paper_conf: float,
    shadow_conf: float,
    promote_conf: float,
    routine_conf: float,
    structured_conf: float,
    escalation_gain: float,
    velocity_scale: float,
    arr_per_compute_min_bps_per_usd: float,
) -> dict[str, Any]:
    selected = packet.get("selected_variant") or {}
    score = parse_float(selected.get("benchmark_score"), default=0.0)
    brier = parse_float(selected.get("brier"), default=0.0)
    ece = parse_float(selected.get("ece"), default=0.0)

    dataset = packet.get("dataset") or {}
    warmup_rows = parse_float(dataset.get("warmup_rows"), default=0.0)
    holdout_rows = parse_float(dataset.get("holdout_rows"), default=0.0)
    total_rows = max(warmup_rows + holdout_rows, 1.0)

    frontier_best = _best_frontier_score(existing_rows)
    baseline = score if frontier_best is None else frontier_best
    candidate_edge = score - baseline
    expected_arr_delta = max(candidate_edge, 0.0) * ARR_SCALE_BPS
    candidate_edge_bps = candidate_edge * ARR_SCALE_BPS

    variant_scores = _collect_scores(packet.get("variants"))
    variant_deltas = [value - baseline for value in variant_scores]
    expected_arr_lower, expected_arr_upper = _interval_from_values(variant_deltas, fallback=0.0)
    expected_arr_lower *= ARR_SCALE_BPS
    expected_arr_upper *= ARR_SCALE_BPS

    candidate_confidence = max(0.0, min(1.0, 1.0 - ((brier or 0.0) + (ece or 0.0))))

    generated_at = parse_iso_timestamp(packet.get("generated_at"))
    stale_reasons: list[str] = []
    if generated_at is None:
        stale_reasons.append("generated_at_missing")
        stale = True
    else:
        now = utc_now_iso_datetime()
        age_minutes = (now - generated_at).total_seconds() / 60.0
        stale = age_minutes > stale_minutes
        if stale:
            stale_reasons.append("candidate_stale_too_old")
        elif age_minutes >= stale_minutes * 0.9:
            stale_reasons.append("candidate_near_stale_boundary")

    interval_uncertainty = max(0.0, expected_arr_upper - expected_arr_lower)
    confidence_adjusted = expected_arr_delta * candidate_confidence
    confidence_adjusted_minus_uncertainty = confidence_adjusted - (0.5 * interval_uncertainty)
    confidence_adjusted_minus_uncertainty = max(0.0, confidence_adjusted_minus_uncertainty)

    expected_improvement_velocity = (confidence_adjusted_minus_uncertainty / total_rows) * velocity_scale
    expected_improvement_velocity_interval = {
        "lower": (expected_arr_lower / total_rows) * velocity_scale,
        "upper": (expected_arr_upper / total_rows) * velocity_scale,
    }

    burn_usd = max(total_rows * row_cost_usd, 1.0)
    arr_per_burn = confidence_adjusted_minus_uncertainty / burn_usd if burn_usd > 0 else 0.0

    model_tier = "routine_ingestion"
    compute_cost_usd = 0.03
    if not stale:
        if candidate_confidence < structured_conf:
            if confidence_adjusted_minus_uncertainty >= escalation_gain * 1.4:
                model_tier = "conflict_arbitration"
                compute_cost_usd = 0.32
        elif candidate_confidence < routine_conf:
            if confidence_adjusted_minus_uncertainty >= escalation_gain:
                model_tier = "structured_ranking"
                compute_cost_usd = 0.09
    if stale:
        model_tier = f"escalation_blocked:{model_tier}"

    arr_per_compute = confidence_adjusted_minus_uncertainty / compute_cost_usd if compute_cost_usd > 0 else 0.0

    promotion_gate_reasons: list[str] = []
    if status != "keep":
        candidate_stage = "discovery"
        promotion_action = "hold"
        promotion_gate_reasons.append(f"status_not_frontier:{decision_reason}")
    elif stale:
        candidate_stage = "discovery"
        promotion_action = "hold"
        promotion_gate_reasons.extend(stale_reasons)
    elif expected_arr_delta <= 0:
        candidate_stage = "discovery"
        promotion_action = "hold"
        promotion_gate_reasons.append("no_expected_arr_gain")
    elif confidence_adjusted_minus_uncertainty <= arr_gain_threshold_bps:
        candidate_stage = "discovery"
        promotion_action = "hold"
        promotion_gate_reasons.append("confidence_adjusted_arr_gain_too_low")
    elif arr_per_burn < arr_per_burn_min_bps_per_usd:
        candidate_stage = "discovery"
        promotion_action = "hold"
        promotion_gate_reasons.append("low_arr_per_burn_efficiency")
    elif candidate_confidence < paper_conf:
        candidate_stage = "sim"
        promotion_action = "hold"
        promotion_gate_reasons.append("paper_confidence_below_threshold")
    elif expected_improvement_velocity <= 0.0:
        candidate_stage = "paper"
        promotion_action = "hold"
        promotion_gate_reasons.append("non_positive_improvement_velocity")
    elif arr_per_compute < arr_per_compute_min_bps_per_usd:
        candidate_stage = "paper"
        promotion_action = "hold"
        promotion_gate_reasons.append("low_arr_per_compute_efficiency")
    elif candidate_confidence < shadow_conf:
        candidate_stage = "paper"
        promotion_action = "hold"
        promotion_gate_reasons.append("shadow_confidence_below_threshold")
    elif candidate_confidence < promote_conf:
        candidate_stage = "shadow"
        promotion_action = "hold"
        promotion_gate_reasons.append("promotion_confidence_below_threshold")
    else:
        candidate_stage = "promote"
        promotion_action = "promote"

    confidence_quality = candidate_confidence * max(0.0, confidence_adjusted_minus_uncertainty / max(abs(candidate_edge_bps), 1.0))

    return {
        "candidate_stale_reasons": stale_reasons,
        "candidate_stage": candidate_stage,
        "promotion_action": promotion_action,
        "promotion_gate_reasons": promotion_gate_reasons,
        "candidate_confidence": candidate_confidence,
        "candidate_confidence_source": "calibration_proxy_v1",
        "candidate_confidence_score": confidence_adjusted_minus_uncertainty,
        "candidate_gate_quality": confidence_quality,
        "candidate_information_gain_bps": interval_uncertainty,
        "expected_arr_delta": expected_arr_delta,
        "expected_arr_delta_interval": {
            "lower": expected_arr_lower,
            "upper": expected_arr_upper,
        },
        "candidate_edge_bps": candidate_edge_bps,
        "expected_improvement_velocity": expected_improvement_velocity,
        "expected_improvement_velocity_interval": expected_improvement_velocity_interval,
        "evaluation_burn_usd": burn_usd,
        "arr_per_burn_bps_per_usd": arr_per_burn,
        "arr_per_compute_bps_per_usd": arr_per_compute,
        "model_tier": model_tier,
        "estimated_compute_cost_usd": compute_cost_usd,
        "arr_per_compute_usd": arr_per_compute,
        "status_code": status,
    }


def build_weekly_loop_report(
    *,
    rows: list[dict[str, str]],
    now: datetime,
    window_minutes: float,
) -> dict[str, Any]:
    threshold = now - timedelta(minutes=max(1.0, window_minutes))
    recent_rows = [
        row
        for row in rows
        if (parse_iso_timestamp(row.get("timestamp")) or now) >= threshold
    ]

    ranked_rows: list[dict[str, Any]] = []
    accepted_rows: list[dict[str, Any]] = []
    stalled_by_reason: dict[str, int] = {}

    for row in recent_rows:
        metrics = assess_row_metrics(row)
        if row.get("status") != "keep":
            continue

        entry = {
            "run_id": int(row.get("run_id") or 0),
            "candidate_label": row.get("candidate_label") or "unknown",
            "candidate_stage": row.get("candidate_stage") or "discovery",
            "promotion_action": row.get("promotion_action") or "hold",
            "candidate_confidence": metrics["candidate_confidence"],
            "expected_arr_delta": metrics["expected_arr_delta"],
            "candidate_gate_quality": metrics["candidate_gate_quality"],
            "candidate_information_gain_bps": metrics["candidate_information_gain_bps"],
            "candidate_confidence_score": metrics["candidate_confidence_score"],
            "expected_improvement_velocity": metrics["expected_improvement_velocity"],
            "arr_per_burn_bps_per_usd": metrics["arr_per_burn_bps_per_usd"],
            "arr_per_compute_bps_per_usd": metrics["arr_per_compute_bps_per_usd"],
            "candidate_edge_bps": metrics["candidate_edge_bps"],
            "candidate_stale_reasons": metrics["candidate_stale_reasons"],
            "promotion_gate_reasons": metrics["promotion_gate_reasons"],
            "model_tier": metrics["model_tier"],
            "packet_json": row.get("packet_json") or "",
        }
        ranked_rows.append(entry)
        if entry["candidate_stage"] == "promote" and entry["promotion_action"] == "promote":
            accepted_rows.append(entry)
            continue

        for reason in metrics["promotion_gate_reasons"]:
            stalled_by_reason[reason] = stalled_by_reason.get(reason, 0) + 1

    ranked_rows.sort(
        key=lambda item: (
            float(item.get("candidate_gate_quality") or 0.0),
            float(item.get("candidate_confidence") or 0.0),
            float(item.get("expected_arr_delta") or 0.0),
        ),
        reverse=True,
    )

    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "window_minutes": float(window_minutes),
        "rows_considered": len(recent_rows),
        "keep_count": sum(1 for row in recent_rows if row.get("status") == "keep"),
        "discard_count": sum(1 for row in recent_rows if row.get("status") == "discard"),
        "crash_count": sum(1 for row in recent_rows if row.get("status") == "crash"),
        "promotion_ready_count": sum(1 for row in recent_rows if row.get("candidate_stage") == "promote"),
        "discovery_count": sum(1 for row in recent_rows if row.get("candidate_stage") == "discovery"),
        "sim_count": sum(1 for row in recent_rows if row.get("candidate_stage") == "sim"),
        "paper_count": sum(1 for row in recent_rows if row.get("candidate_stage") == "paper"),
        "shadow_count": sum(1 for row in recent_rows if row.get("candidate_stage") == "shadow"),
        "accepted_count": len(accepted_rows),
        "stale_count": sum(1 for row in recent_rows if "candidate_stale" in (row.get("candidate_stale_reasons") or "")),
        "promotion_gate_reason_counts": stalled_by_reason,
        "accepted_candidates": accepted_rows[:20],
        "ranking": ranked_rows[:50],
    }


def assess_row_metrics(row: dict[str, str]) -> dict[str, Any]:
    return {
        "status": row["status"],
        "decision_reason": row["decision_reason"],
        "candidate_stage": row.get("candidate_stage", "discovery"),
        "promotion_action": row.get("promotion_action", "hold"),
        "candidate_confidence": parse_float(row.get("candidate_confidence"), default=0.0),
        "candidate_confidence_score": parse_float(row.get("candidate_confidence_score"), default=0.0),
        "candidate_confidence_source": row.get("candidate_confidence_source") or "calibration_proxy_v1",
        "candidate_gate_quality": parse_float(row.get("candidate_gate_quality"), default=0.0),
        "candidate_information_gain_bps": parse_float(row.get("candidate_information_gain_bps"), default=0.0),
        "expected_arr_delta": parse_float(row.get("expected_arr_delta"), default=0.0),
        "expected_arr_delta_interval": _parse_json_dict(row.get("expected_arr_delta_interval")),
        "expected_improvement_velocity": parse_float(row.get("expected_improvement_velocity"), default=0.0),
        "expected_improvement_velocity_interval": _parse_json_dict(row.get("expected_improvement_velocity_interval")),
        "candidate_stale_reasons": _split_codes(row.get("candidate_stale_reasons")),
        "promotion_gate_reasons": _split_codes(row.get("promotion_gate_reasons")),
        "evaluation_burn_usd": parse_float(row.get("evaluation_burn_usd"), default=0.0),
        "arr_per_burn_bps_per_usd": parse_float(row.get("arr_per_burn_bps_per_usd"), default=0.0),
        "candidate_edge_bps": parse_float(row.get("candidate_edge_bps"), default=0.0),
        "arr_per_compute_bps_per_usd": parse_float(row.get("arr_per_compute_bps_per_usd"), default=0.0),
        "model_tier": row.get("model_tier") or "routine_ingestion",
        "estimated_compute_cost_usd": parse_float(row.get("estimated_compute_cost_usd"), default=0.0),
        "arr_per_compute_usd": parse_float(row.get("arr_per_compute_usd"), default=0.0),
    }


def ledger_row(
    *,
    run_id: int,
    packet: dict[str, Any],
    status: str,
    decision_reason: str,
    candidate_label: str,
    description: str,
    packet_json: str,
    packet_md: str,
    mutation_cmd: str,
    candidate_metrics: dict[str, Any],
) -> dict[str, str]:
    selected = packet.get("selected_variant") or {}
    dataset = packet.get("dataset") or {}
    git_info = packet.get("git") or {}
    return {
        "run_id": str(run_id),
        "timestamp": str(packet.get("generated_at") or utc_now_iso()),
        "benchmark_id": str(packet.get("benchmark_id") or "calibration_v1"),
        "candidate_label": sanitize_tsv(candidate_label),
        "description": sanitize_tsv(description or packet.get("description") or ""),
        "mutable_surface": str(packet.get("mutable_surface") or "bot/adaptive_platt.py"),
        "git_sha": str(git_info.get("sha") or "unknown"),
        "mutable_surface_sha256": str(packet.get("mutable_surface_sha256") or ""),
        "selected_variant": str(selected.get("name") or ""),
        "benchmark_score": format_metric(selected.get("benchmark_score")),
        "brier": format_metric(selected.get("brier")),
        "ece": format_metric(selected.get("ece")),
        "log_loss": format_metric(selected.get("log_loss")),
        "status": status,
        "decision_reason": sanitize_tsv(decision_reason),
        "warmup_rows": str(dataset.get("warmup_rows") or ""),
        "holdout_rows": str(dataset.get("holdout_rows") or ""),
        "packet_json": packet_json,
        "packet_md": packet_md,
        "mutation_cmd": sanitize_tsv(mutation_cmd),
        "candidate_stale_reasons": _join_codes(candidate_metrics["candidate_stale_reasons"]),
        "candidate_stage": str(candidate_metrics["candidate_stage"]),
        "promotion_action": str(candidate_metrics["promotion_action"]),
        "promotion_gate_reasons": _join_codes(candidate_metrics["promotion_gate_reasons"]),
        "expected_arr_delta": format_metric(candidate_metrics.get("expected_arr_delta")),
        "expected_arr_delta_interval": json.dumps(candidate_metrics["expected_arr_delta_interval"], sort_keys=True),
        "expected_improvement_velocity": format_metric(candidate_metrics.get("expected_improvement_velocity")),
        "expected_improvement_velocity_interval": json.dumps(candidate_metrics["expected_improvement_velocity_interval"], sort_keys=True),
        "candidate_confidence": format_metric(candidate_metrics.get("candidate_confidence")),
        "candidate_confidence_score": format_metric(candidate_metrics.get("candidate_confidence_score")),
        "candidate_confidence_source": str(candidate_metrics.get("candidate_confidence_source") or "calibration_proxy_v1"),
        "candidate_gate_quality": format_metric(candidate_metrics.get("candidate_gate_quality")),
        "candidate_information_gain_bps": format_metric(candidate_metrics.get("candidate_information_gain_bps")),
        "evaluation_burn_usd": format_metric(candidate_metrics.get("evaluation_burn_usd")),
        "arr_per_burn_bps_per_usd": format_metric(candidate_metrics.get("arr_per_burn_bps_per_usd")),
        "candidate_edge_bps": format_metric(candidate_metrics.get("candidate_edge_bps")),
        "arr_per_compute_bps_per_usd": format_metric(candidate_metrics.get("arr_per_compute_bps_per_usd")),
        "model_tier": str(candidate_metrics.get("model_tier") or "routine_ingestion"),
        "estimated_compute_cost_usd": format_metric(candidate_metrics.get("estimated_compute_cost_usd")),
        "arr_per_compute_usd": format_metric(candidate_metrics.get("arr_per_compute_usd")),
    }


def write_summary(path: Path, *, rows: list[dict[str, str]], records_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keep_count = sum(1 for row in rows if row["status"] == "keep")
    discard_count = sum(1 for row in rows if row["status"] == "discard")
    crash_count = sum(1 for row in rows if row["status"] == "crash")
    promoted = [row for row in rows if row.get("candidate_stage") == "promote" and row.get("promotion_action") == "promote"]
    latest = rows[-1] if rows else None
    valid_scores = [(int(row["run_id"]), float(row["benchmark_score"])) for row in rows if row.get("benchmark_score")]
    best_run = max(valid_scores, key=lambda item: item[1]) if valid_scores else None

    lines = [
        "# Calibration Lane Summary",
        "",
        f"- Logged runs: {records_count}",
        f"- Kept frontier marks: {keep_count}",
        f"- Discarded runs: {discard_count}",
        f"- Crashes: {crash_count}",
        f"- Discovery stage: {sum(1 for row in rows if row.get('candidate_stage') == 'discovery')}",
        f"- Sim stage: {sum(1 for row in rows if row.get('candidate_stage') == 'sim')}",
        f"- Paper stage: {sum(1 for row in rows if row.get('candidate_stage') == 'paper')}",
        f"- Shadow stage: {sum(1 for row in rows if row.get('candidate_stage') == 'shadow')}",
        f"- Promoted candidates (loop-ready): {len(promoted)}",
        "",
        "Calibration benchmark wins do not imply paper, shadow, or live-trading readiness.",
        "Confidence-adjusted ARR gates apply to downstream progression stages in this lane.",
    ]

    if best_run:
        lines.extend(
            [
                "",
                "## Frontier",
                "",
                f"- Best run: `{best_run[0]}`",
                f"- Best benchmark score: {best_run[1]:.6f}",
            ]
        )
    if latest:
        lines.extend(
            [
                "",
                "## Latest Run",
                "",
                f"- Run: `{latest['run_id']}`",
                f"- Status: `{latest['status']}`",
                f"- Decision reason: `{latest['decision_reason']}`",
                f"- Selected variant: `{latest['selected_variant']}`",
                f"- Benchmark score: {latest['benchmark_score'] or 'n/a'}",
                f"- Candidate stage: `{latest.get('candidate_stage', 'n/a')}`",
                f"- Promotion action: `{latest.get('promotion_action', 'n/a')}`",
                f"- Confidence-adjusted ARR: `{latest.get('candidate_confidence_score') or 'n/a'}`",
                f"- ARR per burn (bps/USD): `{latest.get('arr_per_burn_bps_per_usd') or 'n/a'}`",
                f"- Packet: `{latest['packet_json']}`",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish_flywheel_review(
    *,
    control_db_url: str,
    row: dict[str, str],
    candidate_metrics: dict[str, Any],
) -> dict[str, Any]:
    database.reset_engine()
    engine = database.get_engine(control_db_url)
    database.init_db(engine)
    session = database.get_session_factory(engine)()
    try:
        cycle = crud.create_flywheel_cycle(
            session,
            cycle_key=f"calibration-benchmark-{row['run_id']}-{timestamp_slug()}",
            status="running",
            summary=None,
            artifacts_path=row["packet_json"],
        )
        title, action, priority = flywheel_task_fields(row)
        finding, task = record_finding_with_task(
            session,
            finding=FindingSpec(
                finding_key=f"benchmark:{row['benchmark_id']}:{row['run_id']}",
                cycle_id=cycle.id,
                strategy_version_id=None,
                lane="slow_directional",
                environment="benchmark",
                source_kind="benchmark_lane",
                finding_type=benchmark_finding_type(row),
                title=benchmark_finding_title(row),
                summary=flywheel_details(row),
                lesson=benchmark_lesson(row),
                evidence={
                    "run_id": row["run_id"],
                    "benchmark_id": row["benchmark_id"],
                    "candidate_label": row["candidate_label"],
                    "decision_reason": row["decision_reason"],
                    "selected_variant": row["selected_variant"],
                    "benchmark_score": row["benchmark_score"],
                    "packet_json": row["packet_json"],
                    "packet_md": row["packet_md"],
                    "candidate_stage": row["candidate_stage"],
                    "promotion_action": row["promotion_action"],
                    "candidate_confidence": candidate_metrics["candidate_confidence"],
                    "candidate_confidence_score": candidate_metrics["candidate_confidence_score"],
                    "candidate_confidence_source": candidate_metrics["candidate_confidence_source"],
                    "expected_arr_delta": candidate_metrics["expected_arr_delta"],
                    "expected_improvement_velocity": candidate_metrics["expected_improvement_velocity"],
                    "candidate_gate_quality": candidate_metrics["candidate_gate_quality"],
                    "candidate_information_gain_bps": candidate_metrics["candidate_information_gain_bps"],
                    "candidate_edge_bps": candidate_metrics["candidate_edge_bps"],
                    "candidate_stale_reasons": candidate_metrics["candidate_stale_reasons"],
                    "promotion_gate_reasons": candidate_metrics["promotion_gate_reasons"],
                    "model_tier": candidate_metrics["model_tier"],
                    "estimated_compute_cost_usd": candidate_metrics["estimated_compute_cost_usd"],
                    "arr_per_compute_bps_per_usd": candidate_metrics["arr_per_compute_bps_per_usd"],
                    "arr_per_compute_usd": candidate_metrics["arr_per_compute_usd"],
                    **{k: v for k, v in candidate_metrics.get("expected_arr_delta_interval", {}).items()},
                    "candidate_status": row.get("status_code", "n/a"),
                },
                priority=priority,
                confidence=None,
                status="open",
            ),
            task=TaskSpec(
                cycle_id=cycle.id,
                strategy_version_id=None,
                action=action,
                title=title,
                details=flywheel_details(row),
                priority=priority,
                status="open",
                lane="slow_directional",
                environment="benchmark",
                source_kind="benchmark_lane",
                source_ref=f"benchmark:{row['benchmark_id']}:{row['run_id']}",
                metadata={
                    "run_id": row["run_id"],
                    "benchmark_id": row["benchmark_id"],
                    "candidate_label": row["candidate_label"],
                    "candidate_stage": row["candidate_stage"],
                    "promotion_action": row["promotion_action"],
                    "candidate_confidence": candidate_metrics["candidate_confidence"],
                    "candidate_confidence_score": candidate_metrics["candidate_confidence_score"],
                    "candidate_confidence_source": candidate_metrics["candidate_confidence_source"],
                    "candidate_gate_quality": candidate_metrics["candidate_gate_quality"],
                    "candidate_information_gain_bps": candidate_metrics["candidate_information_gain_bps"],
                    "candidate_edge_bps": candidate_metrics["candidate_edge_bps"],
                    "expected_arr_delta": candidate_metrics["expected_arr_delta"],
                    "expected_improvement_velocity": candidate_metrics["expected_improvement_velocity"],
                    "arr_per_burn_bps_per_usd": candidate_metrics["arr_per_burn_bps_per_usd"],
                    "arr_per_compute_bps_per_usd": candidate_metrics["arr_per_compute_bps_per_usd"],
                    "arr_per_compute_usd": candidate_metrics["arr_per_compute_usd"],
                    "model_tier": candidate_metrics["model_tier"],
                    "decision_reason": row["decision_reason"],
                    "status": row["status"],
                    "packet_json": row["packet_json"],
                    "packet_md": row["packet_md"],
                },
            ),
        )
        crud.finish_flywheel_cycle(
            session,
            cycle.id,
            status="completed",
            summary=title,
            artifacts_path=row["packet_json"],
        )
        session.commit()
        return {
            "cycle_id": cycle.id,
            "task_id": task.id,
            "finding_id": None if finding is None else finding.id,
            "action": action,
            "title": title,
            "candidate_stage": row["candidate_stage"],
            "promotion_action": row["promotion_action"],
            "candidate_confidence": candidate_metrics["candidate_confidence"],
            "candidate_confidence_score": candidate_metrics["candidate_confidence_score"],
        }
    finally:
        session.close()
        database.reset_engine()


def flywheel_task_fields(row: dict[str, str]) -> tuple[str, str, int]:
    if row["status"] == "keep" and row["decision_reason"] != "baseline_frontier":
        return (
            "Review retained calibration benchmark improvement",
            "recommend",
            20,
        )
    if row["status"] == "keep":
        return (
            "Freeze calibration benchmark baseline",
            "observe",
            40,
        )
    if row["status"] == "discard":
        return (
            "Record calibration benchmark null result",
            "observe",
            50,
        )
    return (
        "Investigate calibration lane benchmark crash",
        "observe",
        10,
    )


def flywheel_details(row: dict[str, str]) -> str:
    return (
        f"Run {row['run_id']} ended with status={row['status']} reason={row['decision_reason']}. "
        f"variant={row['selected_variant']} benchmark_score={row['benchmark_score'] or 'n/a'} "
        f"candidate_stage={row['candidate_stage']} promotion_action={row['promotion_action']} "
        f"brier={row['brier'] or 'n/a'} ece={row['ece'] or 'n/a'} packet={row['packet_json']}. "
        "Calibration benchmark results require replay or paper validation before any broader adoption."
    )


def benchmark_finding_title(row: dict[str, str]) -> str:
    return f"Calibration lane run {row['run_id']} {row['status']} ({row['decision_reason']})"


def benchmark_finding_type(row: dict[str, str]) -> str:
    if row["status"] == "keep" and row["decision_reason"] == "baseline_frontier":
        return "benchmark_baseline"
    if row["status"] == "keep":
        return "benchmark_improvement"
    if row["status"] == "discard":
        return "benchmark_null"
    return "benchmark_crash"


def benchmark_lesson(row: dict[str, str]) -> str:
    if row["status"] == "keep" and row["decision_reason"] == "baseline_frontier":
        return "Freeze the initial benchmark frontier before expanding the search surface."
    if row["status"] == "keep":
        return "Benchmark gains should enter review as staged evidence packets, not silent code adoption."
    if row["status"] == "discard":
        return "Null results are useful search bounds and should remain in the append-only ledger."
    return "Crashes in the lane harness are control-plane work, not hidden experimental noise."


def run_mutation(command: str) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"mutation command failed with return code {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )


def backup_surface(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    handle = tempfile.NamedTemporaryFile(prefix="lane_backup_", suffix=path.suffix, delete=False)
    handle.close()
    backup = Path(handle.name)
    shutil.copy2(path, backup)
    return backup


def restore_surface(backup_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, target_path)


def crash_packet(*, manifest: str, description: str, exc: Exception) -> dict[str, Any]:
    return {
        "benchmark_id": "calibration_v1",
        "generated_at": utc_now_iso(),
        "description": description,
        "manifest_path": manifest,
        "mutable_surface": "bot/adaptive_platt.py",
        "mutable_surface_sha256": "",
        "git": {"sha": "unknown", "dirty": True},
        "selected_variant": {},
        "dataset": {},
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def render_crash_markdown(packet: dict[str, Any]) -> str:
    error = packet.get("error") or {}
    lines = [
        "# Calibration Benchmark Crash",
        "",
        f"- Generated at: {packet['generated_at']}",
        f"- Error type: `{error.get('type', 'unknown')}`",
        f"- Error: {error.get('message', 'unknown')}",
        "",
        "The mutation was restored from a local backup before the crash packet was written.",
    ]
    return "\n".join(lines) + "\n"


def sanitize_tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").strip()


def format_metric(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):.6f}"


def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "run"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_iso_datetime() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json_dict(value: Any) -> dict[str, float] | None:
    if not value:
        return None
    if isinstance(value, dict):
        return {
            "lower": parse_float(value.get("lower"), default=0.0),
            "upper": parse_float(value.get("upper"), default=0.0),
        }
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "lower": parse_float(payload.get("lower"), default=0.0),
        "upper": parse_float(payload.get("upper"), default=0.0),
    }


def _join_codes(values: list[str]) -> str:
    return ";".join(values)


def _split_codes(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def parse_iso_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _best_frontier_score(rows: list[dict[str, str]]) -> float | None:
    scores = [parse_float(row.get("benchmark_score")) for row in rows if row.get("status") == "keep"]
    scores = [score for score in scores if score is not None]
    if not scores:
        return None
    return max(scores)


def _collect_scores(variants: Any) -> list[float]:
    if not isinstance(variants, list):
        return []
    values: list[float] = []
    for item in variants:
        value = parse_float(item.get("benchmark_score") if isinstance(item, dict) else None)
        if value is not None:
            values.append(value)
    if not values:
        return [0.0]
    return values


def _interval_from_values(values: list[float], *, fallback: float = 0.0) -> tuple[float, float]:
    if not values:
        return fallback, fallback
    return min(values), max(values)


if __name__ == "__main__":
    main()
