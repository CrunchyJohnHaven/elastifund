#!/usr/bin/env python3
"""Run one BTC5 command-node mutation cycle and update lane artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.command_node_btc5.v4.benchmark import (  # noqa: E402
    DEFAULT_MUTABLE_SURFACE,
    TaskDefinition,
    evaluate_candidate,
    extract_candidate_packet,
    load_manifest,
    load_tasks,
    sha256_file,
)
from scripts.render_btc5_command_node_progress import load_records, render_svg  # noqa: E402


DEFAULT_MANIFEST = ROOT / "benchmarks" / "command_node_btc5" / "v4" / "manifest.json"
DEFAULT_CANDIDATE_MD = DEFAULT_MUTABLE_SURFACE
DEFAULT_RESULTS = ROOT / "reports" / "autoresearch" / "command_node" / "results.jsonl"
DEFAULT_RUNS_DIR = ROOT / "reports" / "autoresearch" / "command_node" / "runs"
DEFAULT_CHAMPION = ROOT / "reports" / "autoresearch" / "command_node" / "champion.json"
DEFAULT_LATEST = ROOT / "reports" / "autoresearch" / "command_node" / "latest.json"
DEFAULT_CHART = ROOT / "research" / "btc5_command_node_progress.svg"
DEFAULT_BENCHMARK_ID = "command_node_btc5_v4"
DEFAULT_TASK_SUITE_ID = "command_node_btc5_v4"

DEFAULT_DAILY_PROPOSER_BUDGET_USD = 5.0
DEFAULT_ROUTINE_COST_USD = 0.35
DEFAULT_ESCALATED_COST_USD = 1.25
DEFAULT_ROUTINE_PROPOSER = "command-node-routine-proposer"
DEFAULT_ESCALATED_PROPOSER = "command-node-escalated-proposer"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-md",
        default=str(DEFAULT_CANDIDATE_MD),
        help="Mutable btc5_command_node.md surface to mutate and overwrite on keep",
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Frozen benchmark manifest path",
    )
    parser.add_argument(
        "--results-ledger",
        default=str(DEFAULT_RESULTS),
        help="Append-only results ledger",
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help="Per-run JSON artifact directory",
    )
    parser.add_argument(
        "--champion-out",
        default=str(DEFAULT_CHAMPION),
        help="Champion registry output",
    )
    parser.add_argument(
        "--latest-out",
        default=str(DEFAULT_LATEST),
        help="Latest evaluation summary output",
    )
    parser.add_argument(
        "--svg-out",
        default=str(DEFAULT_CHART),
        help="Karpathy-style progress chart output",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Optional description recorded in the run packet",
    )
    parser.add_argument(
        "--keep-epsilon",
        type=float,
        default=1e-9,
        help="Minimum loss improvement required to mark a run as keep",
    )
    parser.add_argument(
        "--daily-proposer-budget-usd",
        type=float,
        default=DEFAULT_DAILY_PROPOSER_BUDGET_USD,
        help="Daily proposer budget for the command-node lane",
    )
    parser.add_argument(
        "--routine-estimated-cost-usd",
        type=float,
        default=DEFAULT_ROUTINE_COST_USD,
        help="Estimated cost for the routine proposer tier",
    )
    parser.add_argument(
        "--escalated-estimated-cost-usd",
        type=float,
        default=DEFAULT_ESCALATED_COST_USD,
        help="Estimated cost for the escalated proposer tier",
    )
    parser.add_argument(
        "--routine-proposer-model",
        default=DEFAULT_ROUTINE_PROPOSER,
        help="Metadata label for the routine proposer tier",
    )
    parser.add_argument(
        "--escalated-proposer-model",
        default=DEFAULT_ESCALATED_PROPOSER,
        help="Metadata label for the escalated proposer tier",
    )
    parser.add_argument(
        "--escalate-after-discards",
        type=int,
        default=10,
        help="Escalate after this many consecutive discards since the last keep",
    )
    parser.add_argument(
        "--escalate-after-hours-without-keep",
        type=float,
        default=24.0,
        help="Escalate after this many hours without a keep",
    )
    parser.add_argument(
        "--recent-context-limit",
        type=int,
        default=10,
        help="Number of recent same-suite discard or crash packets to mine for mutation context",
    )
    parser.add_argument(
        "--allow-noncanonical-candidate",
        action="store_true",
        help="Allow a non-default candidate path (test-only escape hatch)",
    )
    parser.add_argument(
        "--force-proposer-tier",
        choices=("auto", "routine", "escalated", "budget_exhausted"),
        default="auto",
        help="Force a proposer tier for this run instead of waiting for auto escalation",
    )
    return parser.parse_args(argv)


def _resolve_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _resolve_candidate_path(path_value: str | Path) -> Path:
    return _resolve_path(path_value)


def _relative_path(path: str | Path) -> str:
    target = Path(path)
    try:
        return str(target.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(target)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _now_stamp() -> str:
    return _now_utc().strftime("%Y%m%dT%H%M%SZ")


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _existing_experiment_count(path: Path) -> int:
    rows = _load_jsonl(path)
    return max((int(row.get("experiment_id") or 0) for row in rows), default=0)


def _manifest_metadata(path_value: str | Path) -> tuple[str, str]:
    manifest_path = _resolve_path(path_value)
    try:
        manifest = load_manifest(manifest_path)
    except Exception:
        return DEFAULT_BENCHMARK_ID, DEFAULT_TASK_SUITE_ID
    benchmark_id = str(manifest.get("benchmark_id") or DEFAULT_BENCHMARK_ID)
    scoring = manifest.get("scoring") if isinstance(manifest.get("scoring"), dict) else {}
    task_suite_id = str(scoring.get("task_suite_id") or benchmark_id or DEFAULT_TASK_SUITE_ID)
    return benchmark_id, task_suite_id


def _row_matches_suite(row: dict[str, Any], benchmark_id: str, task_suite_id: str) -> bool:
    row_benchmark_id = str(row.get("benchmark_id") or "").strip()
    row_task_suite_id = str(row.get("task_suite_id") or "").strip()
    if row_benchmark_id:
        return row_benchmark_id == benchmark_id
    if row_task_suite_id:
        return row_task_suite_id == task_suite_id
    return False


def _matching_suite_rows(
    rows: list[dict[str, Any]],
    benchmark_id: str,
    task_suite_id: str,
) -> list[dict[str, Any]]:
    return [row for row in rows if _row_matches_suite(row, benchmark_id, task_suite_id)]


def _matching_champion(
    payload: dict[str, Any] | None,
    benchmark_id: str,
    task_suite_id: str,
) -> dict[str, Any] | None:
    if not payload:
        return None
    champion_benchmark_id = str(payload.get("benchmark_id") or "").strip()
    champion_task_suite_id = str(payload.get("task_suite_id") or "").strip()
    if champion_benchmark_id and champion_benchmark_id != benchmark_id:
        return None
    if champion_task_suite_id and champion_task_suite_id != task_suite_id:
        return None
    if not champion_benchmark_id and not champion_task_suite_id:
        return None
    return payload


def _latest_keep_time(rows: list[dict[str, Any]], champion: dict[str, Any] | None) -> datetime | None:
    keep_times = [
        _parse_timestamp(row.get("evaluated_at") or row.get("generated_at"))
        for row in rows
        if str(row.get("status") or "") == "keep"
    ]
    keep_times = [item for item in keep_times if item is not None]
    champion_time = _parse_timestamp((champion or {}).get("updated_at"))
    if champion_time is not None:
        keep_times.append(champion_time)
    return max(keep_times) if keep_times else None


def _consecutive_discards(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in reversed(rows):
        status = str(row.get("status") or "")
        if status == "keep":
            break
        if status == "discard":
            count += 1
    return count


def _daily_estimated_spend(rows: list[dict[str, Any]], now: datetime) -> float:
    total = 0.0
    for row in rows:
        timestamp = _parse_timestamp(row.get("evaluated_at") or row.get("generated_at"))
        if timestamp is None or timestamp.date() != now.date():
            continue
        total += _safe_float(row.get("estimated_llm_cost_usd"), 0.0) or 0.0
    return round(total, 4)


def _select_proposer_policy(
    *,
    rows: list[dict[str, Any]],
    champion: dict[str, Any] | None,
    now: datetime,
    args: argparse.Namespace,
) -> dict[str, Any]:
    last_keep = _latest_keep_time(rows, champion)
    hours_without_keep = None if last_keep is None else round((now - last_keep).total_seconds() / 3600.0, 4)
    consecutive_discards = _consecutive_discards(rows)
    forced_tier = str(getattr(args, "force_proposer_tier", "auto") or "auto").strip().lower()
    wants_escalated = (
        consecutive_discards >= int(args.escalate_after_discards)
        or (hours_without_keep is not None and hours_without_keep >= float(args.escalate_after_hours_without_keep))
    )
    daily_spend_before = _daily_estimated_spend(rows, now)
    budget_remaining_before = max(0.0, round(float(args.daily_proposer_budget_usd) - daily_spend_before, 4))
    reason_tags: list[str] = []
    if forced_tier == "escalated":
        reason_tags.append("forced_escalated")
    elif forced_tier == "routine":
        reason_tags.append("forced_routine")
    elif forced_tier == "budget_exhausted":
        reason_tags.append("forced_budget_exhausted")
    if forced_tier == "auto" and consecutive_discards >= int(args.escalate_after_discards):
        reason_tags.append("consecutive_discards_threshold_reached")
    if (
        forced_tier == "auto"
        and hours_without_keep is not None
        and hours_without_keep >= float(args.escalate_after_hours_without_keep)
    ):
        reason_tags.append("hours_without_keep_threshold_reached")
    if not reason_tags:
        reason_tags.append("routine_default")

    tier = "routine"
    proposer_model = str(args.routine_proposer_model)
    estimated_cost = float(args.routine_estimated_cost_usd)

    if forced_tier == "budget_exhausted":
        tier = "budget_exhausted"
        proposer_model = str(args.routine_proposer_model)
        estimated_cost = 0.0
    elif forced_tier == "escalated" or (forced_tier == "auto" and wants_escalated):
        tier = "escalated"
        proposer_model = str(args.escalated_proposer_model)
        estimated_cost = float(args.escalated_estimated_cost_usd)

    if budget_remaining_before < estimated_cost:
        if wants_escalated and budget_remaining_before >= float(args.routine_estimated_cost_usd):
            tier = "routine"
            proposer_model = str(args.routine_proposer_model)
            estimated_cost = float(args.routine_estimated_cost_usd)
            reason_tags.append("budget_fallback_to_routine")
        else:
            tier = "budget_exhausted"
            proposer_model = str(args.routine_proposer_model)
            estimated_cost = 0.0
            reason_tags.append("daily_budget_exhausted")

    return {
        "tier": tier,
        "proposer_model": proposer_model,
        "estimated_llm_cost_usd": round(estimated_cost, 4),
        "daily_budget_usd": round(float(args.daily_proposer_budget_usd), 4),
        "daily_estimated_spend_usd_before_run": daily_spend_before,
        "daily_estimated_spend_usd_after_run": round(daily_spend_before + estimated_cost, 4),
        "budget_remaining_usd_before_run": budget_remaining_before,
        "budget_remaining_usd_after_run": max(0.0, round(budget_remaining_before - estimated_cost, 4)),
        "consecutive_discards": consecutive_discards,
        "hours_without_keep": hours_without_keep,
        "reason_tags": reason_tags,
    }


def _load_candidate_packet(candidate_path: Path) -> dict[str, Any]:
    try:
        return extract_candidate_packet(candidate_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _responses_by_task(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    responses: dict[str, dict[str, Any]] = {}
    for payload in packet.get("responses") or []:
        if not isinstance(payload, dict):
            continue
        task_id = str(payload.get("task_id") or "").strip()
        if task_id:
            responses[task_id] = dict(payload)
    return responses


def _task_score_map(evaluation: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {}
    for payload in (evaluation or {}).get("tasks") or []:
        if not isinstance(payload, dict):
            continue
        task_id = str(payload.get("task_id") or "").strip()
        if task_id:
            scores[task_id] = payload
    return scores


def _load_recent_failure_context(
    *,
    rows: list[dict[str, Any]],
    runs_dir: Path,
    limit: int,
) -> dict[str, Any]:
    task_penalties: Counter[str] = Counter()
    crash_paths: list[str] = []
    recent_statuses: list[str] = []
    recent_run_ids: list[int] = []
    for row in list(reversed(rows))[:limit]:
        recent_statuses.append(str(row.get("status") or ""))
        recent_run_ids.append(int(row.get("experiment_id") or 0))
        if str(row.get("status") or "") == "crash":
            run_json = ((row.get("artifact_paths") or {}).get("run_json")) if isinstance(row.get("artifact_paths"), dict) else row.get("run_json")
            if run_json:
                crash_paths.append(str(run_json))
            continue
        run_json = ((row.get("artifact_paths") or {}).get("run_json")) if isinstance(row.get("artifact_paths"), dict) else row.get("run_json")
        run_path = _resolve_path(run_json) if run_json else None
        payload = _load_json(run_path) if run_path else None
        for task_row in (payload or {}).get("tasks") or []:
            if not isinstance(task_row, dict):
                continue
            task_id = str(task_row.get("task_id") or "").strip()
            total_score = _safe_float(task_row.get("total_score"), 0.0) or 0.0
            penalty = max(0.0, round(100.0 - total_score, 4))
            if task_id and penalty > 0:
                task_penalties[task_id] += penalty
    return {
        "recent_run_ids": recent_run_ids,
        "recent_statuses": recent_statuses,
        "recent_crash_packets": crash_paths,
        "task_penalties": dict(task_penalties),
    }


def _ideal_task_response(
    task: TaskDefinition,
    *,
    mutation_type: str,
    failure_context: dict[str, Any],
) -> dict[str, Any]:
    clarity_terms = "; ".join(task.required_clarity_terms)
    failure_tags = ", ".join(sorted((failure_context.get("task_penalties") or {}).keys())[:3]) or "none"
    return {
        "task_id": task.task_id,
        "objective": (
            f"Execute {task.title} with {clarity_terms} while preserving the frozen {task.task_suite_id} benchmark contract."
        ),
        "owner_model": task.expected_owner_model,
        "read_first": list(task.required_read_first),
        "files_to_edit": list(task.required_files_to_edit),
        "output_files": list(task.required_output_files),
        "dependencies": list(task.required_dependency_order),
        "verification_commands": [f"verify {term}" for term in task.required_verification_terms],
        "checklist": list(task.required_checklist),
        "notes": (
            "Use machine-truth lane artifacts first, keep one owner per path, and preserve "
            f"{clarity_terms}. Mutation strategy: {mutation_type}. Recent failure focus: {failure_tags}."
        ),
    }


def _select_target_task_ids(
    *,
    tasks: list[TaskDefinition],
    current_eval: dict[str, Any] | None,
    failure_context: dict[str, Any],
    proposer_tier: str,
) -> list[str]:
    if proposer_tier == "escalated":
        return [task.task_id for task in tasks]
    current_scores = _task_score_map(current_eval)
    weakest_task_id: str | None = None
    weakest_score = float("inf")
    penalties = failure_context.get("task_penalties") or {}
    for task in tasks:
        score_row = current_scores.get(task.task_id)
        total_score = _safe_float((score_row or {}).get("total_score"), 0.0) or 0.0
        penalty_bonus = _safe_float(penalties.get(task.task_id), 0.0) or 0.0
        effective_score = total_score - min(20.0, penalty_bonus / 10.0)
        if effective_score < weakest_score:
            weakest_task_id = task.task_id
            weakest_score = effective_score
    if weakest_task_id is None:
        weakest_task_id = tasks[0].task_id
    return [weakest_task_id]


def _build_candidate_packet(
    *,
    base_packet: dict[str, Any],
    tasks: list[TaskDefinition],
    current_eval: dict[str, Any] | None,
    failure_context: dict[str, Any],
    proposal_id: str,
    proposer_policy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    task_suite_id = str(tasks[0].task_suite_id) if tasks else DEFAULT_TASK_SUITE_ID
    base_label = str(base_packet.get("candidate_label") or "btc5-command-node").strip() or "btc5-command-node"
    if proposer_policy["tier"] == "budget_exhausted":
        mutation_type = "budget_exhausted_noop"
        target_task_ids: list[str] = []
        packet = dict(base_packet) if base_packet else {}
        packet["task_suite_id"] = task_suite_id
        packet["candidate_label"] = f"{base_label}-{proposal_id}"
        mutation_summary = {
            "target_task_ids": target_task_ids,
            "baseline_loss": _safe_float((current_eval or {}).get("loss"), None),
            "reason_tags": proposer_policy["reason_tags"],
            "task_penalties": failure_context.get("task_penalties") or {},
        }
        return packet, {"mutation_type": mutation_type, "mutation_summary": mutation_summary}

    target_task_ids = _select_target_task_ids(
        tasks=tasks,
        current_eval=current_eval,
        failure_context=failure_context,
        proposer_tier=str(proposer_policy["tier"]),
    )
    mutation_type = "full_packet_refresh" if proposer_policy["tier"] == "escalated" else "targeted_task_repair"
    responses = _responses_by_task(base_packet)
    allowed_task_ids = {task.task_id for task in tasks}
    if proposer_policy["tier"] == "escalated":
        responses = {task_id: payload for task_id, payload in responses.items() if task_id in allowed_task_ids}
    for task in tasks:
        if task.task_id in target_task_ids:
            responses[task.task_id] = _ideal_task_response(
                task,
                mutation_type=mutation_type,
                failure_context=failure_context,
            )
    ordered_responses = [responses[task.task_id] for task in tasks if task.task_id in responses]
    packet = {
        "task_suite_id": task_suite_id,
        "candidate_label": f"{base_label}-{proposal_id}",
        "responses": ordered_responses,
    }
    mutation_summary = {
        "target_task_ids": target_task_ids,
        "baseline_loss": _safe_float((current_eval or {}).get("loss"), None),
        "baseline_total_score": _safe_float((current_eval or {}).get("total_score"), None),
        "reason_tags": proposer_policy["reason_tags"],
        "task_penalties": failure_context.get("task_penalties") or {},
        "recent_crash_packets": failure_context.get("recent_crash_packets") or [],
        "recent_run_ids": failure_context.get("recent_run_ids") or [],
    }
    return packet, {"mutation_type": mutation_type, "mutation_summary": mutation_summary}


def _render_candidate_markdown(packet: dict[str, Any]) -> str:
    review_gate = (
        "Before keeping a new command-node candidate, confirm that the proposal was generated in a temp "
        "workspace, benchmarked on frozen v4, preserves suite-specific champion lineage, and overwrites "
        "the mutable surface only when the frontier improves."
    )
    return (
        "# BTC5 Command Node\n\n"
        "This file is the only mutable surface for the BTC5 command-node autoresearch lane.\n"
        "The task suite, scorer, chart renderer, and append-only results ledger are frozen within each benchmark epoch.\n\n"
        "```json\n"
        + json.dumps(packet, indent=2)
        + "\n```\n\n## Review Gate\n\n"
        + review_gate
        + "\n"
    )


def _classify_run(
    *,
    evaluation: dict[str, Any],
    champion: dict[str, Any] | None,
    keep_epsilon: float,
) -> tuple[str, bool, str, int | None, float | None]:
    loss = _safe_float(evaluation.get("loss"), None)
    if loss is None or evaluation.get("error"):
        champion_id = int(champion["experiment_id"]) if champion and champion.get("experiment_id") else None
        return "crash", False, "benchmark_failed", champion_id, None
    if champion is None:
        return "keep", True, "baseline_frontier", None, None
    champion_loss = _safe_float(champion.get("loss"), None)
    champion_id = int(champion["experiment_id"]) if champion.get("experiment_id") else None
    if champion_loss is None:
        return "keep", True, "baseline_frontier", champion_id, None
    frontier_gap = round(loss - champion_loss, 4)
    if loss < (champion_loss - keep_epsilon):
        return "keep", True, "improved_frontier", champion_id, frontier_gap
    return "discard", False, "no_better_candidate", champion_id, frontier_gap


def _build_crash_packet(
    *,
    manifest_path: Path,
    candidate_path: Path,
    description: str,
    error: Exception,
    benchmark_id: str,
    task_suite_id: str,
) -> dict[str, Any]:
    candidate_hash = sha256_file(candidate_path) if candidate_path.exists() else ""
    return {
        "benchmark_id": benchmark_id,
        "generated_at": _now_utc().replace(microsecond=0).isoformat(),
        "description": description.strip(),
        "manifest_path": _relative_path(manifest_path),
        "candidate_program_path": _relative_path(candidate_path),
        "mutable_surface": _relative_path(candidate_path),
        "mutable_surface_sha256": candidate_hash,
        "prompt_hash": candidate_hash,
        "candidate_hash": candidate_hash,
        "candidate_label": candidate_path.stem,
        "task_suite": {
            "task_suite_id": task_suite_id,
        },
        "error": {"type": type(error).__name__, "message": str(error)},
    }


def _count_statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "keep": sum(1 for row in rows if row.get("status") == "keep"),
        "discard": sum(1 for row in rows if row.get("status") == "discard"),
        "crash": sum(1 for row in rows if row.get("status") == "crash"),
    }


def main() -> int:
    args = parse_args()
    candidate_path = _resolve_candidate_path(args.candidate_md)
    canonical_candidate = DEFAULT_MUTABLE_SURFACE.resolve()
    if (not args.allow_noncanonical_candidate) and candidate_path != canonical_candidate:
        raise SystemExit(
            "command_node_btc5 lane allows one mutable surface only: "
            f"{_relative_path(canonical_candidate)}"
        )

    manifest_path = _resolve_path(args.manifest)
    results_ledger = _resolve_path(args.results_ledger)
    runs_dir = _resolve_path(args.runs_dir)
    champion_out = _resolve_path(args.champion_out)
    latest_out = _resolve_path(args.latest_out)
    svg_out = _resolve_path(args.svg_out)
    benchmark_id, task_suite_id = _manifest_metadata(manifest_path)
    manifest = load_manifest(manifest_path)
    tasks = load_tasks(manifest)

    now = _now_utc()
    experiment_id = _existing_experiment_count(results_ledger) + 1
    proposal_id = f"proposal_{experiment_id:04d}"
    current_surface_sha256 = sha256_file(candidate_path) if candidate_path.exists() else ""

    all_rows = _load_jsonl(results_ledger)
    suite_rows = _matching_suite_rows(all_rows, benchmark_id, task_suite_id)
    champion_any = _load_json(champion_out)
    champion = _matching_champion(champion_any, benchmark_id, task_suite_id)
    failure_context = _load_recent_failure_context(
        rows=[row for row in suite_rows if str(row.get("status") or "") in {"discard", "crash"}],
        runs_dir=runs_dir,
        limit=max(1, int(args.recent_context_limit)),
    )
    proposer_policy = _select_proposer_policy(
        rows=suite_rows,
        champion=champion,
        now=now,
        args=args,
    )

    try:
        current_eval = evaluate_candidate(
            manifest_path,
            candidate_path,
            allow_noncanonical_candidate=True,
            description="baseline_probe",
        )
    except Exception:
        current_eval = None

    base_packet = _load_candidate_packet(candidate_path)
    proposal_packet, proposal_fields = _build_candidate_packet(
        base_packet=base_packet,
        tasks=tasks,
        current_eval=current_eval,
        failure_context=failure_context,
        proposal_id=proposal_id,
        proposer_policy=proposer_policy,
    )
    proposed_markdown = _render_candidate_markdown(proposal_packet)

    runs_dir.mkdir(parents=True, exist_ok=True)
    run_stamp = _now_stamp()
    run_path = runs_dir / f"experiment_{experiment_id:04d}_{run_stamp}.json"
    candidate_artifact_path = runs_dir / f"experiment_{experiment_id:04d}_{run_stamp}_candidate.md"
    candidate_artifact_path.write_text(proposed_markdown, encoding="utf-8")

    try:
        with tempfile.TemporaryDirectory(prefix="btc5_command_node_") as tempdir:
            temp_candidate = Path(tempdir) / candidate_path.name
            temp_candidate.write_text(proposed_markdown, encoding="utf-8")
            evaluation = evaluate_candidate(
                manifest_path,
                temp_candidate,
                allow_noncanonical_candidate=True,
                description=args.description,
            )
    except Exception as error:
        evaluation = _build_crash_packet(
            manifest_path=manifest_path,
            candidate_path=candidate_artifact_path,
            description=args.description,
            error=error,
            benchmark_id=benchmark_id,
            task_suite_id=task_suite_id,
        )

    status, keep, decision_reason, parent_champion_id, frontier_gap = _classify_run(
        evaluation=evaluation,
        champion=champion,
        keep_epsilon=float(args.keep_epsilon),
    )
    if keep:
        candidate_path.write_text(proposed_markdown, encoding="utf-8")
    mutable_surface_sha256_after = sha256_file(candidate_path) if candidate_path.exists() else ""

    run_payload = dict(evaluation)
    run_payload["experiment_id"] = experiment_id
    run_payload["status"] = status
    run_payload["keep"] = keep
    run_payload["decision_reason"] = decision_reason
    run_payload["benchmark_id"] = benchmark_id
    run_payload["task_suite_id"] = task_suite_id
    run_payload["frontier_gap"] = frontier_gap
    run_payload["candidate_program_path"] = _relative_path(candidate_artifact_path)
    run_payload["mutable_surface"] = _relative_path(candidate_path)
    run_payload["mutable_surface_sha256_before"] = current_surface_sha256
    run_payload["mutable_surface_sha256_after"] = mutable_surface_sha256_after
    run_payload["proposal_id"] = proposal_id
    run_payload["parent_champion_id"] = parent_champion_id
    run_payload["proposer_model"] = proposer_policy["proposer_model"]
    run_payload["estimated_llm_cost_usd"] = proposer_policy["estimated_llm_cost_usd"]
    run_payload["mutation_type"] = proposal_fields["mutation_type"]
    run_payload["mutation_summary"] = proposal_fields["mutation_summary"]
    run_payload["proposal"] = {
        "proposal_id": proposal_id,
        "parent_champion_id": parent_champion_id,
        "proposer_model": proposer_policy["proposer_model"],
        "proposer_tier": proposer_policy["tier"],
        "estimated_llm_cost_usd": proposer_policy["estimated_llm_cost_usd"],
        "daily_budget_usd": proposer_policy["daily_budget_usd"],
        "daily_estimated_spend_usd_before_run": proposer_policy["daily_estimated_spend_usd_before_run"],
        "daily_estimated_spend_usd_after_run": proposer_policy["daily_estimated_spend_usd_after_run"],
        "budget_remaining_usd_before_run": proposer_policy["budget_remaining_usd_before_run"],
        "budget_remaining_usd_after_run": proposer_policy["budget_remaining_usd_after_run"],
        "consecutive_discards": proposer_policy["consecutive_discards"],
        "hours_without_keep": proposer_policy["hours_without_keep"],
        "reason_tags": proposer_policy["reason_tags"],
        "mutation_type": proposal_fields["mutation_type"],
        "mutation_summary": proposal_fields["mutation_summary"],
    }
    run_payload["artifact_paths"] = {
        "run_json": _relative_path(run_path),
        "candidate_program": _relative_path(candidate_artifact_path),
        "mutable_surface": _relative_path(candidate_path),
        "chart_svg": _relative_path(svg_out),
    }
    _write_json(run_path, run_payload)

    ledger_entry = {
        "experiment_id": experiment_id,
        "evaluated_at": run_payload.get("generated_at"),
        "benchmark_id": benchmark_id,
        "task_suite_id": task_suite_id,
        "candidate_program_path": _relative_path(candidate_artifact_path),
        "candidate_label": run_payload.get("candidate_label"),
        "candidate_hash": run_payload.get("candidate_hash"),
        "prompt_hash": run_payload.get("prompt_hash"),
        "mutable_surface": _relative_path(candidate_path),
        "mutable_surface_sha256": run_payload.get("mutable_surface_sha256"),
        "mutable_surface_sha256_before": current_surface_sha256,
        "mutable_surface_sha256_after": mutable_surface_sha256_after,
        "status": status,
        "decision_reason": decision_reason,
        "frontier_gap": frontier_gap,
        "loss": run_payload.get("loss"),
        "subscores": run_payload.get("subscores"),
        "keep": keep,
        "champion_id": experiment_id if keep else parent_champion_id,
        "proposal_id": proposal_id,
        "parent_champion_id": parent_champion_id,
        "proposer_model": proposer_policy["proposer_model"],
        "estimated_llm_cost_usd": proposer_policy["estimated_llm_cost_usd"],
        "mutation_type": proposal_fields["mutation_type"],
        "mutation_summary": proposal_fields["mutation_summary"],
        "artifact_paths": run_payload["artifact_paths"],
    }
    _append_jsonl(results_ledger, ledger_entry)

    champion_payload = champion_any
    if keep:
        champion_payload = {
            "benchmark_id": benchmark_id,
            "task_suite_id": task_suite_id,
            "experiment_id": experiment_id,
            "updated_at": run_payload.get("generated_at"),
            "status": status,
            "candidate_program_path": _relative_path(candidate_path),
            "candidate_label": run_payload.get("candidate_label"),
            "loss": run_payload.get("loss"),
            "total_score": run_payload.get("total_score"),
            "subscores": run_payload.get("subscores"),
            "mutable_surface_sha256": mutable_surface_sha256_after,
            "prompt_hash": run_payload.get("prompt_hash"),
            "candidate_hash": run_payload.get("candidate_hash"),
            "proposal_id": proposal_id,
            "parent_champion_id": parent_champion_id,
            "proposer_model": proposer_policy["proposer_model"],
            "estimated_llm_cost_usd": proposer_policy["estimated_llm_cost_usd"],
            "mutation_type": proposal_fields["mutation_type"],
            "mutation_summary": proposal_fields["mutation_summary"],
            "artifact_paths": {
                "candidate_program": _relative_path(candidate_path),
                "proposed_candidate_md": _relative_path(candidate_artifact_path),
                "chart_svg": _relative_path(svg_out),
                "run_json": _relative_path(run_path),
            },
        }
        _write_json(champion_out, champion_payload)

    records = load_records(results_ledger)
    render_svg(svg_out, records)

    refreshed_rows = _matching_suite_rows(_load_jsonl(results_ledger), benchmark_id, task_suite_id)
    latest_payload = {
        "updated_at": run_payload.get("generated_at"),
        "benchmark_id": benchmark_id,
        "task_suite_id": task_suite_id,
        "latest_experiment_id": experiment_id,
        "latest_status": status,
        "latest_decision_reason": decision_reason,
        "latest_loss": run_payload.get("loss"),
        "latest_total_score": run_payload.get("total_score"),
        "latest_candidate_label": run_payload.get("candidate_label"),
        "latest_proposal_id": proposal_id,
        "counts": _count_statuses(refreshed_rows),
        "champion": _matching_champion(_load_json(champion_out), benchmark_id, task_suite_id),
        "budget_policy": {
            "daily_budget_usd": proposer_policy["daily_budget_usd"],
            "daily_estimated_spend_usd_before_run": proposer_policy["daily_estimated_spend_usd_before_run"],
            "daily_estimated_spend_usd_after_run": proposer_policy["daily_estimated_spend_usd_after_run"],
            "budget_remaining_usd_after_run": proposer_policy["budget_remaining_usd_after_run"],
            "routine_estimated_cost_usd": round(float(args.routine_estimated_cost_usd), 4),
            "escalated_estimated_cost_usd": round(float(args.escalated_estimated_cost_usd), 4),
        },
        "latest_proposal": run_payload["proposal"],
        "artifacts": {
            "results_ledger": _relative_path(results_ledger),
            "latest_run": _relative_path(run_path),
            "latest_candidate_md": _relative_path(candidate_artifact_path),
            "chart_svg": _relative_path(svg_out),
        },
    }
    _write_json(latest_out, latest_payload)
    print(json.dumps(latest_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
