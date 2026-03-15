#!/usr/bin/env python3
"""Run one BTC5 market-model mutation cycle and update lane artifacts."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime, timezone
from hashlib import sha256
from pathlib import Path
from pprint import pformat
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.btc5_market.v1.benchmark import (
    DEFAULT_LOCAL_DB,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_MUTABLE_SURFACE,
    DEFAULT_REMOTE_ROWS_JSON,
    default_artifact_paths,
    freeze_current_benchmark,
    run_benchmark,
    sha256_file,
    write_benchmark_artifacts,
)
from scripts.btc5_policy_benchmark import write_market_policy_handoff
from scripts.render_btc5_market_model_progress import load_records, render_progress
from infra.fast_json import dump_path_atomic, write_text_atomic

DEFAULT_LEDGER = ROOT / "reports" / "autoresearch" / "btc5_market" / "results.jsonl"
DEFAULT_PACKET_DIR = ROOT / "reports" / "autoresearch" / "btc5_market" / "packets"
DEFAULT_CHAMPION = ROOT / "reports" / "autoresearch" / "btc5_market" / "champion.json"
DEFAULT_LATEST_JSON = ROOT / "reports" / "autoresearch" / "btc5_market" / "latest.json"
DEFAULT_LATEST_MD = ROOT / "reports" / "autoresearch" / "btc5_market" / "latest.md"
DEFAULT_POLICY_HANDOFF = ROOT / "reports" / "autoresearch" / "btc5_market" / "policy_handoff.json"
DEFAULT_CHART = ROOT / "research" / "btc5_market_model_progress.svg"
DEFAULT_INSTANCE_OUTPUT = ROOT / "instance01_btc5_market_model_autoresearch.json"

DEFAULT_DAILY_PROPOSER_BUDGET_USD = 10.0
DEFAULT_ROUTINE_MODEL = "heuristic_market_routine_v1"
DEFAULT_EXPENSIVE_MODEL = "heuristic_market_expensive_v1"
DEFAULT_BUDGET_FALLBACK_MODEL = "heuristic_market_budget_fallback_v1"
DEFAULT_ROUTINE_ESTIMATED_LLM_COST_USD = 0.35
DEFAULT_EXPENSIVE_ESTIMATED_LLM_COST_USD = 2.5
ESCALATE_AFTER_CONSECUTIVE_DISCARDS = 10
ESCALATE_AFTER_HOURS_WITHOUT_KEEP = 24.0
RECENT_DISCARD_LIMIT = 10
RECENT_CRASH_LIMIT = 3
MAX_RECENT_HASH_LOOKBACK = 32

DEFAULT_MUTATION_SURFACE = {
    "model_name": "empirical_backoff_v1",
    "model_version": 1,
    "feature_levels": [
        ["direction", "session_name", "price_bucket", "delta_bucket"],
        ["direction", "session_name", "price_bucket"],
        ["direction", "session_name"],
        ["direction", "price_bucket"],
        ["direction"],
        [],
    ],
    "target_priors": {
        "p_up": 0.50,
        "fill_rate": 0.42,
        "pnl_pct": 0.00,
    },
    "target_smoothing": {
        "p_up": 6.0,
        "fill_rate": 8.0,
        "pnl_pct": 10.0,
    },
    "global_backstop_weight_min": 0.15,
    "global_backstop_weight_max": 0.85,
    "pnl_fill_blend_base": 0.60,
    "pnl_fill_blend_scale": 0.40,
    "pnl_clamp_abs": 1.50,
}

DISCRETE_FEATURE_FIELDS = (
    "direction",
    "session_name",
    "price_bucket",
    "delta_bucket",
    "edge_tier",
    "session_policy_name",
    "et_hour",
)
COMBO_POOL = (
    ("direction", "session_name", "price_bucket", "delta_bucket"),
    ("direction", "session_name", "price_bucket"),
    ("direction", "session_name", "delta_bucket"),
    ("direction", "session_name"),
    ("direction", "price_bucket", "delta_bucket"),
    ("direction", "price_bucket"),
    ("direction", "delta_bucket"),
    ("session_name", "price_bucket"),
    ("session_name", "delta_bucket"),
    ("price_bucket", "delta_bucket"),
    ("direction",),
    ("session_name",),
    ("price_bucket",),
    ("delta_bucket",),
)
ROUTINE_MUTATION_SEQUENCE = (
    "ranked_hierarchy",
    "session_focus",
    "price_delta_focus",
    "conservative_backoff",
    "fill_aware_pnl",
)
EXPENSIVE_MUTATION_SEQUENCE = (
    "escalated_blend",
    "ranked_hierarchy",
    "session_focus",
    "price_delta_focus",
    "fill_aware_pnl",
    "conservative_backoff",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Benchmark manifest path")
    parser.add_argument("--candidate-path", default=str(DEFAULT_MUTABLE_SURFACE), help="Mutable candidate file")
    parser.add_argument("--db-path", default=str(DEFAULT_LOCAL_DB), help="Optional local BTC5 SQLite path")
    parser.add_argument(
        "--remote-cache-json",
        default=str(DEFAULT_REMOTE_ROWS_JSON),
        help="Cached BTC5 rows JSON path",
    )
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="Append-only JSONL results ledger")
    parser.add_argument("--packet-dir", default=str(DEFAULT_PACKET_DIR), help="Benchmark packet directory")
    parser.add_argument("--champion-path", default=str(DEFAULT_CHAMPION), help="Champion registry JSON")
    parser.add_argument("--latest-json", default=str(DEFAULT_LATEST_JSON), help="Latest lane summary JSON")
    parser.add_argument("--latest-md", default=str(DEFAULT_LATEST_MD), help="Latest lane summary markdown")
    parser.add_argument(
        "--policy-handoff-json",
        default=str(DEFAULT_POLICY_HANDOFF),
        help="Market-to-policy handoff JSON output",
    )
    parser.add_argument("--chart-out", default=str(DEFAULT_CHART), help="Public chart SVG path")
    parser.add_argument("--instance-output", default="", help="Optional instance handoff JSON")
    parser.add_argument("--description", default="", help="Free-text experiment description")
    parser.add_argument(
        "--allow-noncanonical-candidate",
        action="store_true",
        help="Allow a non-default candidate path (test-only escape hatch)",
    )
    parser.add_argument(
        "--keep-epsilon",
        type=float,
        default=1e-9,
        help="Minimum loss improvement required to mark a run as keep",
    )
    parser.add_argument(
        "--refresh-benchmark",
        action="store_true",
        help="Freeze the current benchmark epoch before running",
    )
    parser.add_argument(
        "--daily-proposer-budget-usd",
        type=float,
        default=DEFAULT_DAILY_PROPOSER_BUDGET_USD,
        help="Daily estimated LLM proposer budget for the market lane",
    )
    parser.add_argument(
        "--routine-proposer-model",
        default=DEFAULT_ROUTINE_MODEL,
        help="Default routine proposer tier label",
    )
    parser.add_argument(
        "--expensive-proposer-model",
        default=DEFAULT_EXPENSIVE_MODEL,
        help="Escalated proposer tier label",
    )
    parser.add_argument(
        "--budget-fallback-proposer-model",
        default=DEFAULT_BUDGET_FALLBACK_MODEL,
        help="Zero-cost proposer label used when the daily budget is exhausted",
    )
    parser.add_argument(
        "--routine-estimated-llm-cost-usd",
        type=float,
        default=DEFAULT_ROUTINE_ESTIMATED_LLM_COST_USD,
        help="Estimated cost recorded for each routine proposal",
    )
    parser.add_argument(
        "--expensive-estimated-llm-cost-usd",
        type=float,
        default=DEFAULT_EXPENSIVE_ESTIMATED_LLM_COST_USD,
        help="Estimated cost recorded for each escalated proposal",
    )
    parser.add_argument(
        "--force-proposer-tier",
        choices=("auto", "routine", "expensive", "budget_fallback"),
        default="auto",
        help="Force a proposer tier for this run instead of waiting for auto escalation",
    )
    return parser.parse_args(argv)


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
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


def _relative(path: str | Path) -> str:
    target = Path(path)
    try:
        return str(target.relative_to(ROOT))
    except ValueError:
        return str(target)


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    return target.resolve()


def _resolve_candidate_path(path: str | Path) -> Path:
    return _resolve_path(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    dump_path_atomic(path, payload, indent=2, sort_keys=True, trailing_newline=True)


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def _candidate_hash(path: Path) -> str:
    try:
        return sha256_file(path)
    except FileNotFoundError:
        return ""


def _source_hash(source: str) -> str:
    return sha256(source.encode("utf-8")).hexdigest()


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


def _jsonl_rows_for_day(rows: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    day = now.astimezone(UTC).date()
    selected: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_timestamp(row.get("generated_at") or row.get("timestamp"))
        if parsed is None or parsed.date() != day:
            continue
        selected.append(row)
    return selected


def _last_keep_timestamp(rows: list[dict[str, Any]]) -> datetime | None:
    for row in reversed(rows):
        if str(row.get("status") or "").strip().lower() != "keep":
            continue
        parsed = _parse_timestamp(row.get("generated_at") or row.get("timestamp"))
        if parsed is not None:
            return parsed
    return None


def _first_run_timestamp(rows: list[dict[str, Any]]) -> datetime | None:
    for row in rows:
        parsed = _parse_timestamp(row.get("generated_at") or row.get("timestamp"))
        if parsed is not None:
            return parsed
    return None


def _consecutive_discards(rows: list[dict[str, Any]]) -> int:
    discard_count = 0
    for row in reversed(rows):
        status = str(row.get("status") or "").strip().lower()
        if status == "keep":
            break
        if status == "discard":
            discard_count += 1
    return discard_count


def _budget_used_today(rows: list[dict[str, Any]], *, now: datetime) -> float:
    return round(
        sum(
            _safe_float(row.get("estimated_llm_cost_usd"), 0.0) or 0.0
            for row in _jsonl_rows_for_day(rows, now=now)
        ),
        4,
    )


def _select_proposer_tier(
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    args: argparse.Namespace,
) -> dict[str, Any]:
    discard_streak = _consecutive_discards(rows)
    last_keep_at = _last_keep_timestamp(rows)
    reference_timestamp = last_keep_at or _first_run_timestamp(rows)
    hours_without_keep = (
        round((now - reference_timestamp).total_seconds() / 3600.0, 4)
        if reference_timestamp is not None
        else None
    )
    escalation_reason: str | None = None
    preferred_tier = "routine"
    preferred_model = str(args.routine_proposer_model)
    preferred_cost = max(0.0, float(args.routine_estimated_llm_cost_usd))

    forced_tier = str(getattr(args, "force_proposer_tier", "auto") or "auto").strip().lower()
    if forced_tier == "expensive":
        preferred_tier = "expensive"
        preferred_model = str(args.expensive_proposer_model)
        preferred_cost = max(0.0, float(args.expensive_estimated_llm_cost_usd))
        escalation_reason = "forced_expensive"
    elif forced_tier == "budget_fallback":
        preferred_tier = "budget_fallback"
        preferred_model = str(args.budget_fallback_proposer_model)
        preferred_cost = 0.0
        escalation_reason = "forced_budget_fallback"
    elif forced_tier == "routine":
        preferred_tier = "routine"
        preferred_model = str(args.routine_proposer_model)
        preferred_cost = max(0.0, float(args.routine_estimated_llm_cost_usd))
        escalation_reason = "forced_routine"
    elif discard_streak >= ESCALATE_AFTER_CONSECUTIVE_DISCARDS:
        preferred_tier = "expensive"
        preferred_model = str(args.expensive_proposer_model)
        preferred_cost = max(0.0, float(args.expensive_estimated_llm_cost_usd))
        escalation_reason = f"discard_streak_{discard_streak}"
    elif hours_without_keep is not None and hours_without_keep >= ESCALATE_AFTER_HOURS_WITHOUT_KEEP:
        preferred_tier = "expensive"
        preferred_model = str(args.expensive_proposer_model)
        preferred_cost = max(0.0, float(args.expensive_estimated_llm_cost_usd))
        escalation_reason = f"hours_without_keep_{hours_without_keep:.2f}"

    budget_used_before = _budget_used_today(rows, now=now)
    daily_budget = max(0.0, float(args.daily_proposer_budget_usd))
    tier = preferred_tier
    model = preferred_model
    estimated_cost = preferred_cost
    budget_reason = "within_budget"

    if budget_used_before + estimated_cost > daily_budget:
        if preferred_tier == "expensive":
            routine_cost = max(0.0, float(args.routine_estimated_llm_cost_usd))
            if budget_used_before + routine_cost <= daily_budget:
                tier = "routine"
                model = str(args.routine_proposer_model)
                estimated_cost = routine_cost
                budget_reason = "expensive_tier_budget_blocked"
            else:
                tier = "budget_fallback"
                model = str(args.budget_fallback_proposer_model)
                estimated_cost = 0.0
                budget_reason = "daily_budget_exhausted"
        else:
            tier = "budget_fallback"
            model = str(args.budget_fallback_proposer_model)
            estimated_cost = 0.0
            budget_reason = "daily_budget_exhausted"

    budget_used_after = round(budget_used_before + estimated_cost, 4)
    budget_remaining_after = round(max(0.0, daily_budget - budget_used_after), 4)
    return {
        "selected_tier": tier,
        "preferred_tier": preferred_tier,
        "proposer_model": model,
        "estimated_llm_cost_usd": round(estimated_cost, 4),
        "daily_budget_usd": round(daily_budget, 4),
        "budget_used_today_before_usd": budget_used_before,
        "budget_used_today_after_usd": budget_used_after,
        "budget_remaining_today_after_usd": budget_remaining_after,
        "budget_reason": budget_reason,
        "consecutive_discards": discard_streak,
        "hours_without_keep": hours_without_keep,
        "escalation_reason": escalation_reason,
        "last_keep_at": last_keep_at.isoformat().replace("+00:00", "Z") if last_keep_at else None,
    }


def _resolve_artifact_path(path_value: Any) -> Path | None:
    text = str(path_value or "").strip()
    if not text:
        return None
    return _resolve_path(text)


def _load_recent_crash_packets(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    crashes: list[dict[str, Any]] = []
    for row in reversed(rows):
        if str(row.get("status") or "").strip().lower() != "crash":
            continue
        packet_path = _resolve_artifact_path(row.get("packet_json"))
        packet_payload = _load_json(packet_path) if packet_path is not None else None
        crashes.append(
            {
                "experiment_id": row.get("experiment_id"),
                "generated_at": row.get("generated_at") or row.get("timestamp"),
                "decision_reason": row.get("decision_reason"),
                "proposal_id": row.get("proposal_id"),
                "candidate_hash": row.get("candidate_hash"),
                "error": (packet_payload or {}).get("error") or row.get("error"),
                "packet_json": _relative(packet_path) if packet_path is not None else row.get("packet_json"),
            }
        )
        if len(crashes) >= limit:
            break
    return crashes


def _load_snapshot_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _split_rows(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warmup_rows = int(((manifest.get("epoch") or {}).get("warmup_rows")) or 0)
    benchmark_rows = int(((manifest.get("epoch") or {}).get("benchmark_rows")) or 0)
    holdout_rows = rows[warmup_rows : warmup_rows + benchmark_rows]
    return rows[:warmup_rows], holdout_rows


def _available_combo_pool(manifest: dict[str, Any]) -> list[tuple[str, ...]]:
    feature_fields = {
        str(field)
        for field in (((manifest.get("data") or {}).get("feature_fields")) or [])
        if str(field)
    }
    available_discrete = feature_fields.intersection(DISCRETE_FEATURE_FIELDS)
    combos = [combo for combo in COMBO_POOL if set(combo).issubset(available_discrete)]
    if ("direction",) in combos:
        return combos
    return [("direction",)] + combos


def _global_priors(rows: list[dict[str, Any]]) -> dict[str, float]:
    count = max(1, len(rows))
    return {
        "p_up": round(sum(_safe_float(row.get("actual_side_up"), 0.5) or 0.5 for row in rows) / float(count), 6),
        "fill_rate": round(sum(_safe_float(row.get("actual_fill_rate"), 0.0) or 0.0 for row in rows) / float(count), 6),
        "pnl_pct": round(sum(_safe_float(row.get("actual_pnl_pct"), 0.0) or 0.0 for row in rows) / float(count), 6),
    }


def _combo_signal_score(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> float:
    if not rows or not fields:
        return 0.0
    priors = _global_priors(rows)
    grouped: dict[tuple[str, ...], list[float]] = {}
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in fields)
        bucket = grouped.setdefault(key, [0.0, 0.0, 0.0, 0.0])
        bucket[0] += 1.0
        bucket[1] += _safe_float(row.get("actual_side_up"), 0.5) or 0.5
        bucket[2] += _safe_float(row.get("actual_fill_rate"), 0.0) or 0.0
        bucket[3] += _safe_float(row.get("actual_pnl_pct"), 0.0) or 0.0
    total_rows = float(len(rows))
    score = 0.0
    for count, p_up_sum, fill_sum, pnl_sum in grouped.values():
        weight = count / total_rows
        score += weight * (
            abs((p_up_sum / count) - priors["p_up"])
            + (0.8 * abs((fill_sum / count) - priors["fill_rate"]))
            + (4.0 * abs((pnl_sum / count) - priors["pnl_pct"]))
        )
    return round(score, 6)


def _rank_feature_levels(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    ranked = [
        {"fields": combo, "score": _combo_signal_score(rows, combo)}
        for combo in _available_combo_pool(manifest)
    ]
    ranked.sort(key=lambda item: (item["score"], len(item["fields"])), reverse=True)
    return ranked


def _find_assignment_node(module: ast.Module, name: str) -> ast.Assign | ast.AnnAssign | None:
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node
    return None


def _load_mutation_surface(candidate_path: Path) -> tuple[str, dict[str, Any]]:
    source = candidate_path.read_text(encoding="utf-8")
    parsed = ast.parse(source)
    assignment = _find_assignment_node(parsed, "MUTATION_SURFACE")
    if assignment is None:
        raise ValueError(f"{_relative(candidate_path)} must define MUTATION_SURFACE")
    value = assignment.value if isinstance(assignment, (ast.Assign, ast.AnnAssign)) else None
    if value is None:
        raise ValueError("MUTATION_SURFACE assignment is empty")
    raw_surface = ast.literal_eval(value)
    if not isinstance(raw_surface, dict):
        raise ValueError("MUTATION_SURFACE must be a dictionary literal")
    return source, raw_surface


def _normalized_surface(raw_surface: dict[str, Any], *, manifest: dict[str, Any]) -> dict[str, Any]:
    surface = copy.deepcopy(DEFAULT_MUTATION_SURFACE)
    surface.update({key: value for key, value in raw_surface.items() if key in surface})
    priors = dict(surface["target_priors"])
    priors.update(raw_surface.get("target_priors") or {})
    smoothing = dict(surface["target_smoothing"])
    smoothing.update(raw_surface.get("target_smoothing") or {})

    available_fields = set().union(*_available_combo_pool(manifest))
    feature_levels_input = raw_surface.get("feature_levels") or surface["feature_levels"]
    normalized_levels: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for fields in feature_levels_input:
        normalized = tuple(
            field
            for field in (str(item) for item in (fields or []))
            if field in available_fields
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_levels.append(list(normalized))
    if [] not in normalized_levels:
        normalized_levels.append([])

    surface["model_name"] = str(raw_surface.get("model_name") or surface["model_name"])
    surface["model_version"] = max(1, _safe_int(raw_surface.get("model_version"), int(surface["model_version"])))
    surface["feature_levels"] = normalized_levels
    surface["target_priors"] = {
        "p_up": round(_safe_float(priors.get("p_up"), 0.50) or 0.50, 6),
        "fill_rate": round(_safe_float(priors.get("fill_rate"), 0.42) or 0.42, 6),
        "pnl_pct": round(_safe_float(priors.get("pnl_pct"), 0.0) or 0.0, 6),
    }
    surface["target_smoothing"] = {
        "p_up": round(max(1.0, _safe_float(smoothing.get("p_up"), 6.0) or 6.0), 4),
        "fill_rate": round(max(1.0, _safe_float(smoothing.get("fill_rate"), 8.0) or 8.0), 4),
        "pnl_pct": round(max(1.0, _safe_float(smoothing.get("pnl_pct"), 10.0) or 10.0), 4),
    }
    surface["global_backstop_weight_min"] = round(
        max(0.0, min(0.5, _safe_float(raw_surface.get("global_backstop_weight_min"), 0.15) or 0.15)),
        4,
    )
    surface["global_backstop_weight_max"] = round(
        max(
            surface["global_backstop_weight_min"],
            min(0.95, _safe_float(raw_surface.get("global_backstop_weight_max"), 0.85) or 0.85),
        ),
        4,
    )
    surface["pnl_fill_blend_base"] = round(
        max(0.0, min(1.0, _safe_float(raw_surface.get("pnl_fill_blend_base"), 0.60) or 0.60)),
        4,
    )
    surface["pnl_fill_blend_scale"] = round(
        max(0.0, min(1.0, _safe_float(raw_surface.get("pnl_fill_blend_scale"), 0.40) or 0.40)),
        4,
    )
    surface["pnl_clamp_abs"] = round(
        max(0.25, min(2.0, _safe_float(raw_surface.get("pnl_clamp_abs"), 1.50) or 1.50)),
        4,
    )
    return surface


def _mutation_surface_search_replace(source: str, surface: dict[str, Any]) -> dict[str, str]:
    parsed = ast.parse(source)
    assignment = _find_assignment_node(parsed, "MUTATION_SURFACE")
    if assignment is None:
        raise ValueError("MUTATION_SURFACE assignment not found")
    replacement = "MUTATION_SURFACE = " + pformat(surface, width=100, sort_dicts=False) + "\n"
    lines = source.splitlines()
    search = "\n".join(lines[assignment.lineno - 1 : assignment.end_lineno]) + "\n"
    return {
        "search": search,
        "replace": replacement,
    }


def _apply_search_replace_edits(source: str, edits: list[dict[str, str]]) -> str:
    updated = source
    for edit in edits:
        search = str(edit.get("search") or "")
        replace = str(edit.get("replace") or "")
        if not search:
            raise ValueError("SEARCH/REPLACE edit is missing search text")
        if search not in updated:
            raise ValueError("SEARCH block not found in mutation surface")
        updated = updated.replace(search, replace, 1)
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def _replace_mutation_surface(source: str, surface: dict[str, Any]) -> str:
    edit = _mutation_surface_search_replace(source, surface)
    return _apply_search_replace_edits(source, [edit])


def _model_stem(name: str) -> str:
    head = str(name or "empirical_backoff_v1").strip()
    return head.split("__", 1)[0] or "empirical_backoff_v1"


def _top_feature_levels(ranked_levels: list[dict[str, Any]], count: int) -> list[list[str]]:
    selected: list[list[str]] = []
    for item in ranked_levels:
        fields = list(item.get("fields") or [])
        if not fields:
            continue
        selected.append(fields)
        if len(selected) >= count:
            break
    return selected


def _dedupe_levels(levels: list[list[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    ordered: list[list[str]] = []
    for fields in levels:
        key = tuple(fields)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(list(fields))
    if [] not in ordered:
        ordered.append([])
    return ordered


def _apply_strategy(
    *,
    base_surface: dict[str, Any],
    ranked_levels: list[dict[str, Any]],
    priors: dict[str, float],
    strategy: str,
    selection: dict[str, Any],
) -> dict[str, Any]:
    surface = copy.deepcopy(base_surface)
    top_four = _top_feature_levels(ranked_levels, 4)
    top_two = _top_feature_levels(ranked_levels, 2)
    direction_session = [fields for fields in top_four if "direction" in fields and "session_name" in fields]
    price_delta = [fields for fields in top_four if "price_bucket" in fields or "delta_bucket" in fields]
    discard_streak = int(selection.get("consecutive_discards") or 0)

    if strategy == "ranked_hierarchy":
        surface["feature_levels"] = _dedupe_levels(top_four + [["direction"], []])
        surface["target_priors"] = dict(priors)
        surface["target_smoothing"] = {"p_up": 4.0, "fill_rate": 6.0, "pnl_pct": 8.0}
        surface["global_backstop_weight_min"] = 0.08
        surface["global_backstop_weight_max"] = 0.72
        surface["pnl_fill_blend_base"] = 0.52
        surface["pnl_fill_blend_scale"] = 0.48
        surface["pnl_clamp_abs"] = 1.75
    elif strategy == "session_focus":
        focus_levels = direction_session or top_two
        surface["feature_levels"] = _dedupe_levels(
            focus_levels
            + [["direction", "session_name"], ["session_name"], ["direction"], []]
        )
        surface["target_priors"] = dict(priors)
        surface["target_smoothing"] = {"p_up": 3.0, "fill_rate": 5.0, "pnl_pct": 7.0}
        surface["global_backstop_weight_min"] = 0.05
        surface["global_backstop_weight_max"] = 0.68
        surface["pnl_fill_blend_base"] = 0.48
        surface["pnl_fill_blend_scale"] = 0.52
        surface["pnl_clamp_abs"] = 1.65
    elif strategy == "price_delta_focus":
        focus_levels = price_delta or top_two
        surface["feature_levels"] = _dedupe_levels(
            focus_levels
            + [["direction", "price_bucket"], ["direction", "delta_bucket"], ["direction"], []]
        )
        surface["target_priors"] = dict(priors)
        surface["target_smoothing"] = {"p_up": 5.0, "fill_rate": 6.0, "pnl_pct": 6.0}
        surface["global_backstop_weight_min"] = 0.10
        surface["global_backstop_weight_max"] = 0.70
        surface["pnl_fill_blend_base"] = 0.44
        surface["pnl_fill_blend_scale"] = 0.56
        surface["pnl_clamp_abs"] = 1.35
    elif strategy == "conservative_backoff":
        surface["feature_levels"] = _dedupe_levels(top_two + [["direction"], []])
        surface["target_priors"] = dict(priors)
        surface["target_smoothing"] = {"p_up": 8.0, "fill_rate": 10.0, "pnl_pct": 12.0}
        surface["global_backstop_weight_min"] = 0.20
        surface["global_backstop_weight_max"] = 0.88
        surface["pnl_fill_blend_base"] = 0.68
        surface["pnl_fill_blend_scale"] = 0.32
        surface["pnl_clamp_abs"] = 1.10
    elif strategy == "fill_aware_pnl":
        surface["feature_levels"] = _dedupe_levels(top_four + [["direction"], []])
        surface["target_priors"] = {
            "p_up": priors["p_up"],
            "fill_rate": min(1.0, priors["fill_rate"] + 0.03),
            "pnl_pct": priors["pnl_pct"],
        }
        surface["target_smoothing"] = {"p_up": 4.0, "fill_rate": 4.5, "pnl_pct": 6.0}
        surface["global_backstop_weight_min"] = 0.06
        surface["global_backstop_weight_max"] = 0.70
        surface["pnl_fill_blend_base"] = 0.38
        surface["pnl_fill_blend_scale"] = 0.62
        surface["pnl_clamp_abs"] = 1.00
    elif strategy == "escalated_blend":
        surface["feature_levels"] = _dedupe_levels(top_four + [["direction", "session_name"], ["direction"], []])
        surface["target_priors"] = dict(priors)
        surface["target_smoothing"] = {"p_up": 2.0, "fill_rate": 3.0, "pnl_pct": 4.0}
        surface["global_backstop_weight_min"] = 0.03
        surface["global_backstop_weight_max"] = 0.62
        surface["pnl_fill_blend_base"] = 0.42
        surface["pnl_fill_blend_scale"] = 0.58
        surface["pnl_clamp_abs"] = 1.80
    else:
        raise ValueError(f"unknown mutation strategy: {strategy}")

    surface["model_name"] = f"{_model_stem(str(base_surface.get('model_name') or 'empirical_backoff_v1'))}__{strategy}"
    surface["model_version"] = int(base_surface.get("model_version") or 1) + 1
    if discard_streak:
        surface["target_smoothing"]["p_up"] = round(
            max(1.0, float(surface["target_smoothing"]["p_up"]) - min(2.0, discard_streak * 0.1)),
            4,
        )
    return surface


def _mutation_sequence(selection: dict[str, Any], recent_crashes: list[dict[str, Any]]) -> list[str]:
    base = list(
        EXPENSIVE_MUTATION_SEQUENCE
        if selection.get("selected_tier") == "expensive"
        else ROUTINE_MUTATION_SEQUENCE
    )
    if recent_crashes:
        base = ["conservative_backoff"] + [item for item in base if item != "conservative_backoff"]
    offset = int(selection.get("consecutive_discards") or 0) % max(1, len(base))
    return base[offset:] + base[:offset]


def _mutation_jitter(surface: dict[str, Any], *, seed: int) -> dict[str, Any]:
    adjusted = copy.deepcopy(surface)
    delta = ((seed % 5) - 2) * 0.25
    adjusted["target_smoothing"]["p_up"] = round(max(1.0, adjusted["target_smoothing"]["p_up"] + delta), 4)
    adjusted["target_smoothing"]["fill_rate"] = round(
        max(1.0, adjusted["target_smoothing"]["fill_rate"] - (delta / 2.0)),
        4,
    )
    adjusted["target_smoothing"]["pnl_pct"] = round(
        max(1.0, adjusted["target_smoothing"]["pnl_pct"] + (delta / 3.0)),
        4,
    )
    adjusted["global_backstop_weight_max"] = round(
        max(adjusted["global_backstop_weight_min"], min(0.95, adjusted["global_backstop_weight_max"] - 0.01 * (seed % 4))),
        4,
    )
    adjusted["pnl_clamp_abs"] = round(max(0.25, min(2.0, adjusted["pnl_clamp_abs"] + 0.05 * ((seed % 3) - 1))), 4)
    adjusted["model_name"] = f"{adjusted['model_name']}__j{seed % 7}"
    return adjusted


def _recent_candidate_hashes(rows: list[dict[str, Any]], champion: dict[str, Any] | None) -> set[str]:
    hashes = {
        str(row.get("candidate_hash") or "").strip()
        for row in rows[-MAX_RECENT_HASH_LOOKBACK:]
        if str(row.get("candidate_hash") or "").strip()
    }
    if champion and str(champion.get("candidate_hash") or "").strip():
        hashes.add(str(champion["candidate_hash"]).strip())
    return hashes


def _proposal_summary_text(
    *,
    strategy: str,
    ranked_levels: list[dict[str, Any]],
    priors: dict[str, float],
    selection: dict[str, Any],
) -> str:
    top_item = ranked_levels[0] if ranked_levels else {"fields": (), "score": 0.0}
    top_label = "+".join(top_item.get("fields") or ()) or "global_backoff"
    return (
        f"{strategy}; top_warmup_combo={top_label}; "
        f"signal_score={top_item.get('score', 0.0):.4f}; "
        f"priors(p_up={priors['p_up']:.3f}, fill={priors['fill_rate']:.3f}, pnl={priors['pnl_pct']:.3f}); "
        f"tier={selection.get('selected_tier')}"
    )


def _build_proposal_context(
    *,
    manifest: dict[str, Any],
    champion: dict[str, Any] | None,
    ledger_rows: list[dict[str, Any]],
    selection: dict[str, Any],
) -> dict[str, Any]:
    recent_discards = [
        {
            "experiment_id": row.get("experiment_id"),
            "generated_at": row.get("generated_at") or row.get("timestamp"),
            "decision_reason": row.get("decision_reason"),
            "candidate_hash": row.get("candidate_hash"),
            "candidate_model_name": row.get("candidate_model_name"),
            "loss": row.get("loss"),
            "proposal_id": row.get("proposal_id"),
            "mutation_type": row.get("mutation_type"),
        }
        for row in reversed(ledger_rows)
        if str(row.get("status") or "").strip().lower() == "discard"
    ][:RECENT_DISCARD_LIMIT]
    return {
        "benchmark": {
            "benchmark_id": manifest.get("benchmark_id"),
            "epoch_id": ((manifest.get("epoch") or {}).get("epoch_id")),
            "mutable_surface": manifest.get("mutable_surface"),
            "objective": (manifest.get("objective") or {}).get("formula"),
        },
        "champion_before": {
            "experiment_id": (champion or {}).get("experiment_id"),
            "candidate_hash": (champion or {}).get("candidate_hash"),
            "candidate_model_name": (champion or {}).get("candidate_model_name"),
            "candidate_path": (champion or {}).get("candidate_path"),
            "loss": (champion or {}).get("loss"),
        },
        "recent_discards": recent_discards,
        "recent_crashes": _load_recent_crash_packets(ledger_rows, limit=RECENT_CRASH_LIMIT),
        "proposer_selection": selection,
    }


def _generate_mutation_candidate(
    *,
    candidate_path: Path,
    manifest: dict[str, Any],
    champion: dict[str, Any] | None,
    existing_rows: list[dict[str, Any]],
    experiment_id: int,
    generated_at: str,
    selection: dict[str, Any],
    proposal_context: dict[str, Any],
) -> dict[str, Any]:
    source, raw_surface = _load_mutation_surface(candidate_path)
    base_surface = _normalized_surface(raw_surface, manifest=manifest)
    snapshot_path = _resolve_path((manifest.get("data") or {}).get("snapshot_path") or "")
    rows = _load_snapshot_rows(snapshot_path)
    warmup_rows, _ = _split_rows(rows, manifest)
    if not warmup_rows:
        raise ValueError("benchmark manifest does not contain warmup rows")
    priors = _global_priors(warmup_rows)
    ranked_levels = _rank_feature_levels(warmup_rows, manifest)
    seen_hashes = _recent_candidate_hashes(existing_rows, champion)
    mutation_sequence = _mutation_sequence(selection, proposal_context.get("recent_crashes") or [])
    selected_strategy: str | None = None
    selected_surface: dict[str, Any] | None = None
    selected_source: str | None = None
    selected_hash: str | None = None
    selected_patch: list[dict[str, str]] | None = None

    for strategy in mutation_sequence:
        candidate_surface = _apply_strategy(
            base_surface=base_surface,
            ranked_levels=ranked_levels,
            priors=priors,
            strategy=strategy,
            selection=selection,
        )
        candidate_edit = _mutation_surface_search_replace(source, candidate_surface)
        candidate_source = _apply_search_replace_edits(source, [candidate_edit])
        candidate_hash = _source_hash(candidate_source)
        if candidate_hash == _source_hash(source):
            continue
        if candidate_hash in seen_hashes:
            continue
        selected_strategy = strategy
        selected_surface = candidate_surface
        selected_source = candidate_source
        selected_hash = candidate_hash
        selected_patch = [candidate_edit]
        break

    if selected_surface is None or selected_source is None or selected_hash is None or selected_patch is None:
        jitter_seed = experiment_id + int(selection.get("consecutive_discards") or 0)
        fallback_strategy = mutation_sequence[0] if mutation_sequence else "ranked_hierarchy"
        jitter_surface = _mutation_jitter(
            _apply_strategy(
                base_surface=base_surface,
                ranked_levels=ranked_levels,
                priors=priors,
                strategy=fallback_strategy,
                selection=selection,
            ),
            seed=jitter_seed,
        )
        jitter_edit = _mutation_surface_search_replace(source, jitter_surface)
        selected_strategy = f"{fallback_strategy}_jitter"
        selected_surface = jitter_surface
        selected_source = _apply_search_replace_edits(source, [jitter_edit])
        selected_hash = _source_hash(selected_source)
        selected_patch = [jitter_edit]

    proposal_id = f"btc5-market-proposal-{experiment_id:04d}-{generated_at.replace(':', '').replace('-', '')}"
    mutation_summary = _proposal_summary_text(
        strategy=selected_strategy,
        ranked_levels=ranked_levels,
        priors=priors,
        selection=selection,
    )
    return {
        "proposal_id": proposal_id,
        "parent_champion_id": (champion or {}).get("experiment_id"),
        "proposer_model": selection["proposer_model"],
        "proposer_tier": selection["selected_tier"],
        "estimated_llm_cost_usd": selection["estimated_llm_cost_usd"],
        "mutation_summary": mutation_summary,
        "mutation_type": selected_strategy,
        "candidate_model_name": selected_surface["model_name"],
        "candidate_model_version": selected_surface["model_version"],
        "candidate_source": selected_source,
        "candidate_patch": selected_patch,
        "candidate_hash": selected_hash,
        "surface": selected_surface,
        "warmup_priors": priors,
        "ranked_feature_levels": ranked_levels[:6],
        "selection": selection,
    }


def _build_crash_packet(
    *,
    manifest_path: Path,
    proposal_path: Path,
    mutable_surface_path: Path,
    mutable_surface_sha256_before: str,
    description: str,
    error: Exception,
    proposal_summary: dict[str, Any],
) -> dict[str, Any]:
    manifest = _load_json(manifest_path) or {}
    candidate_hash = _candidate_hash(proposal_path)
    packet = {
        "benchmark_id": str(manifest.get("benchmark_id") or "btc5_market_v1"),
        "benchmark_version": int(manifest.get("version") or 1),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "description": description.strip(),
        "manifest_path": _relative(manifest_path),
        "mutable_surface": str(manifest.get("mutable_surface") or _relative(mutable_surface_path)),
        "mutable_surface_path": _relative(mutable_surface_path),
        "mutable_surface_sha256": candidate_hash,
        "mutable_surface_sha256_before": mutable_surface_sha256_before,
        "mutable_surface_sha256_after": _candidate_hash(mutable_surface_path),
        "candidate_hash": candidate_hash,
        "candidate_path": _relative(proposal_path),
        "candidate_model_name": proposal_summary.get("candidate_model_name", proposal_path.stem),
        "epoch": manifest.get("epoch") or {"epoch_id": "unknown"},
        "metrics": {},
        "proposal": proposal_summary,
        "error": {"type": type(error).__name__, "message": str(error)},
    }
    packet.update(
        {
            "proposal_id": proposal_summary.get("proposal_id"),
            "parent_champion_id": proposal_summary.get("parent_champion_id"),
            "proposer_model": proposal_summary.get("proposer_model"),
            "proposer_tier": proposal_summary.get("proposer_tier"),
            "estimated_llm_cost_usd": proposal_summary.get("estimated_llm_cost_usd"),
            "mutation_summary": proposal_summary.get("mutation_summary"),
            "mutation_type": proposal_summary.get("mutation_type"),
        }
    )
    packet["decision"] = {
        "status": "crash",
        "keep": False,
        "reason": type(error).__name__,
    }
    return packet


def _classify_run(
    *,
    loss: float | None,
    epoch_id: str,
    champion: dict[str, Any] | None,
    keep_epsilon: float,
) -> tuple[str, str, bool, int | None]:
    if loss is None:
        champion_id = int(champion["experiment_id"]) if champion and champion.get("experiment_id") else None
        return "crash", "benchmark_failed", False, champion_id
    if not champion or str(champion.get("epoch_id") or "") != epoch_id:
        return "keep", "baseline_frontier", True, None
    champion_loss = _safe_float(champion.get("loss"), 0.0) or 0.0
    champion_id = int(champion["experiment_id"]) if champion.get("experiment_id") else None
    if loss < (champion_loss - keep_epsilon):
        return "keep", "improved_frontier", True, champion_id
    return "discard", "below_frontier", False, champion_id


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "keep": sum(1 for row in rows if row.get("status") == "keep"),
        "discard": sum(1 for row in rows if row.get("status") == "discard"),
        "crash": sum(1 for row in rows if row.get("status") == "crash"),
    }


def _write_latest_markdown(path: Path, summary: dict[str, Any]) -> None:
    champion = summary.get("champion") or {}
    latest = summary.get("latest_experiment") or {}
    counts = summary.get("counts") or {}
    budget = summary.get("budget") or {}
    lines = [
        "# BTC5 Market-Model Autoresearch",
        "",
        f"- Epoch: `{summary.get('epoch_id') or 'unknown'}`",
        f"- Total experiments: `{counts.get('total', 0)}`",
        f"- Kept: `{counts.get('keep', 0)}`",
        f"- Discarded: `{counts.get('discard', 0)}`",
        f"- Crashes: `{counts.get('crash', 0)}`",
        f"- Champion experiment: `{champion.get('experiment_id', 'n/a')}`",
        f"- Champion loss: `{champion.get('loss', 'n/a')}`",
        f"- Latest experiment: `{latest.get('experiment_id', 'n/a')}`",
        f"- Latest status: `{latest.get('status', 'n/a')}`",
        f"- Latest loss: `{latest.get('loss', 'n/a')}`",
        f"- Latest proposal: `{latest.get('proposal_id', 'n/a')}`",
        f"- Latest proposer model: `{latest.get('proposer_model', 'n/a')}`",
        f"- Latest mutation type: `{latest.get('mutation_type', 'n/a')}`",
        f"- Estimated proposer cost: `{latest.get('estimated_llm_cost_usd', 'n/a')}`",
        f"- Daily proposer budget used: `{budget.get('budget_used_today_after_usd', 'n/a')}` of `{budget.get('daily_budget_usd', 'n/a')}`",
        f"- Chart: `{summary.get('chart_svg') or ''}`",
        "",
        "Benchmark progress is benchmark evidence, not realized P&L.",
    ]
    write_text_atomic(path, "\n".join(lines) + "\n", encoding="utf-8")


def _write_crash_markdown(path: Path, packet: dict[str, Any], error: Exception) -> None:
    proposal = packet.get("proposal") or {}
    lines = [
        "# BTC5 Market Mutation Crash",
        "",
        f"- Proposal id: `{proposal.get('proposal_id') or 'n/a'}`",
        f"- Candidate path: `{packet.get('candidate_path') or ''}`",
        f"- Mutable surface path: `{packet.get('mutable_surface_path') or ''}`",
        f"- Candidate hash: `{packet.get('candidate_hash') or ''}`",
        f"- Proposer model: `{proposal.get('proposer_model') or 'n/a'}`",
        f"- Mutation type: `{proposal.get('mutation_type') or 'n/a'}`",
        f"- Error type: `{type(error).__name__}`",
        f"- Error: {error}",
    ]
    write_text_atomic(path, "\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    manifest_path = _resolve_path(args.manifest)
    candidate_path = _resolve_candidate_path(args.candidate_path)
    canonical_candidate = DEFAULT_MUTABLE_SURFACE.resolve()
    if (not args.allow_noncanonical_candidate) and candidate_path != canonical_candidate:
        raise SystemExit(
            "btc5_market lane allows one mutable surface only: "
            f"{_relative(canonical_candidate)}"
        )
    db_path = _resolve_path(args.db_path)
    remote_cache_json = _resolve_path(args.remote_cache_json)
    ledger_path = _resolve_path(args.ledger)
    packet_dir = _resolve_path(args.packet_dir)
    champion_path = _resolve_path(args.champion_path)
    latest_json_path = _resolve_path(args.latest_json)
    latest_md_path = _resolve_path(args.latest_md)
    policy_handoff_path = _resolve_path(args.policy_handoff_json)
    chart_out = _resolve_path(args.chart_out)
    instance_output = _resolve_path(args.instance_output) if args.instance_output else None

    if args.refresh_benchmark or not manifest_path.exists():
        freeze_current_benchmark(
            manifest_path=manifest_path,
            db_path=db_path,
            remote_cache_path=remote_cache_json,
        )

    manifest = _load_json(manifest_path) or {}
    existing_rows = _load_ledger(ledger_path)
    experiment_id = max((_safe_int(row.get("experiment_id"), 0) for row in existing_rows), default=0) + 1
    packet_json, packet_md = default_artifact_paths(packet_dir, slug=f"experiment_{experiment_id:04d}")
    proposal_candidate_path = packet_dir / f"experiment_{experiment_id:04d}_candidate.py"
    proposal_json_path = packet_dir / f"experiment_{experiment_id:04d}_proposal.json"

    now = datetime.now(tz=UTC)
    generated_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    champion_before = _load_json(champion_path)
    mutable_surface_sha256_before = _candidate_hash(candidate_path)
    selection = _select_proposer_tier(existing_rows, now=now, args=args)
    proposal_context = _build_proposal_context(
        manifest=manifest,
        champion=champion_before,
        ledger_rows=existing_rows,
        selection=selection,
    )

    packet: dict[str, Any] | None = None
    proposal_record: dict[str, Any] | None = None
    loss: float | None = None
    status = "crash"
    decision_reason = "benchmark_failed"
    keep = False
    previous_champion_id = _safe_int((champion_before or {}).get("experiment_id"), 0) or None

    try:
        proposal = _generate_mutation_candidate(
            candidate_path=candidate_path,
            manifest=manifest,
            champion=champion_before,
            existing_rows=existing_rows,
            experiment_id=experiment_id,
            generated_at=generated_at,
            selection=selection,
            proposal_context=proposal_context,
        )
        proposal_candidate_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(proposal_candidate_path, proposal["candidate_source"], encoding="utf-8")
        proposal_record = {
            "proposal_id": proposal["proposal_id"],
            "parent_champion_id": proposal.get("parent_champion_id"),
            "proposer_model": proposal["proposer_model"],
            "proposer_tier": proposal["proposer_tier"],
            "estimated_llm_cost_usd": proposal["estimated_llm_cost_usd"],
            "mutation_summary": proposal["mutation_summary"],
            "mutation_type": proposal["mutation_type"],
            "candidate_model_name": proposal["candidate_model_name"],
            "candidate_model_version": proposal["candidate_model_version"],
            "candidate_patch": proposal.get("candidate_patch") or [],
            "candidate_hash": proposal["candidate_hash"],
            "generated_at": generated_at,
            "selection": proposal["selection"],
            "warmup_priors": proposal["warmup_priors"],
            "ranked_feature_levels": proposal["ranked_feature_levels"],
            "context": proposal_context,
            "artifact_paths": {
                "proposal_json": _relative(proposal_json_path),
                "proposal_candidate_py": _relative(proposal_candidate_path),
                "mutable_surface_path": _relative(candidate_path),
            },
        }

        with tempfile.TemporaryDirectory(prefix=f"btc5_market_proposal_{experiment_id:04d}_") as temp_dir:
            temp_candidate = Path(temp_dir) / candidate_path.name
            shutil.copy2(candidate_path, temp_candidate)
            temp_source = temp_candidate.read_text(encoding="utf-8")
            patched_temp_source = _apply_search_replace_edits(
                temp_source,
                list(proposal.get("candidate_patch") or []),
            )
            if patched_temp_source != proposal["candidate_source"]:
                raise ValueError("SEARCH/REPLACE mutation did not reproduce candidate_source")
            write_text_atomic(temp_candidate, patched_temp_source, encoding="utf-8")
            packet = run_benchmark(
                manifest_path,
                candidate_path=temp_candidate,
                allow_noncanonical_candidate=True,
                description=args.description,
            )

        loss = _safe_float((packet.get("metrics") or {}).get("simulator_loss"), None)
        epoch_id = str(((packet or {}).get("epoch") or {}).get("epoch_id") or "unknown")
        status, decision_reason, keep, previous_champion_id = _classify_run(
            loss=loss,
            epoch_id=epoch_id,
            champion=champion_before,
            keep_epsilon=float(args.keep_epsilon),
        )
        if keep and status == "keep":
            incumbent_source = candidate_path.read_text(encoding="utf-8")
            patched_incumbent = _apply_search_replace_edits(
                incumbent_source,
                list(proposal.get("candidate_patch") or []),
            )
            write_text_atomic(candidate_path, patched_incumbent, encoding="utf-8")

        mutable_surface_sha256_after = _candidate_hash(candidate_path)
        champion_after_id = experiment_id if keep and status == "keep" else previous_champion_id
        proposal_record["status"] = status
        proposal_record["keep"] = keep
        proposal_record["decision_reason"] = decision_reason
        proposal_record["experiment_id"] = experiment_id
        proposal_record["champion_after_id"] = champion_after_id
        proposal_record["artifact_paths"]["packet_json"] = _relative(packet_json)
        proposal_record["artifact_paths"]["packet_md"] = _relative(packet_md)
        _write_json(proposal_json_path, proposal_record)

        packet["candidate_hash"] = proposal["candidate_hash"]
        packet["candidate_path"] = _relative(proposal_candidate_path)
        packet["candidate_model_name"] = proposal["candidate_model_name"]
        packet["candidate_model_version"] = proposal["candidate_model_version"]
        packet["mutable_surface_path"] = _relative(candidate_path)
        packet["mutable_surface_sha256_before"] = mutable_surface_sha256_before
        packet["mutable_surface_sha256_after"] = mutable_surface_sha256_after
        packet["proposal"] = proposal_record
        packet.update(
            {
                "proposal_id": proposal_record["proposal_id"],
                "parent_champion_id": proposal_record.get("parent_champion_id"),
                "proposer_model": proposal_record["proposer_model"],
                "proposer_tier": proposal_record["proposer_tier"],
                "estimated_llm_cost_usd": proposal_record["estimated_llm_cost_usd"],
                "mutation_summary": proposal_record["mutation_summary"],
                "mutation_type": proposal_record["mutation_type"],
            }
        )
        packet["decision"] = {
            "status": status,
            "keep": keep,
            "reason": decision_reason,
            "champion_before_id": (champion_before or {}).get("experiment_id"),
            "champion_after_id": champion_after_id,
        }
        write_benchmark_artifacts(packet, json_path=packet_json, summary_path=packet_md)
    except Exception as exc:  # pragma: no cover - exercised via CLI and crash path
        proposal_record = proposal_record or {
            "proposal_id": f"btc5-market-proposal-{experiment_id:04d}-{generated_at.replace(':', '').replace('-', '')}",
            "parent_champion_id": (champion_before or {}).get("experiment_id"),
            "proposer_model": selection["proposer_model"],
            "proposer_tier": selection["selected_tier"],
            "estimated_llm_cost_usd": selection["estimated_llm_cost_usd"],
            "mutation_summary": "proposal_generation_failed",
            "mutation_type": "proposal_generation_failed",
            "candidate_model_name": candidate_path.stem,
            "generated_at": generated_at,
            "selection": selection,
            "context": proposal_context,
            "artifact_paths": {
                "proposal_json": _relative(proposal_json_path),
                "proposal_candidate_py": _relative(proposal_candidate_path),
                "mutable_surface_path": _relative(candidate_path),
            },
        }
        proposal_record["status"] = "crash"
        proposal_record["keep"] = False
        proposal_record["decision_reason"] = type(exc).__name__
        proposal_record["experiment_id"] = experiment_id
        proposal_record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        _write_json(proposal_json_path, proposal_record)
        packet = _build_crash_packet(
            manifest_path=manifest_path,
            proposal_path=proposal_candidate_path if proposal_candidate_path.exists() else candidate_path,
            mutable_surface_path=candidate_path,
            mutable_surface_sha256_before=mutable_surface_sha256_before,
            description=args.description,
            error=exc,
            proposal_summary=proposal_record,
        )
        epoch_id = str(((packet or {}).get("epoch") or {}).get("epoch_id") or "unknown")
        status = "crash"
        decision_reason = type(exc).__name__
        keep = False
        champion_after_id = previous_champion_id
        packet_json.parent.mkdir(parents=True, exist_ok=True)
        packet_md.parent.mkdir(parents=True, exist_ok=True)
        dump_path_atomic(packet_json, packet, indent=2, sort_keys=True, trailing_newline=True)
        _write_crash_markdown(packet_md, packet, exc)
        loss = None

    champion_id = experiment_id if keep and status == "keep" else previous_champion_id
    metrics = (packet or {}).get("metrics") or {}
    ledger_row = {
        "experiment_id": experiment_id,
        "generated_at": (packet or {}).get("generated_at") or generated_at,
        "benchmark_id": (packet or {}).get("benchmark_id", "btc5_market_v1"),
        "epoch_id": str(((packet or {}).get("epoch") or {}).get("epoch_id") or "unknown"),
        "candidate_hash": (packet or {}).get("candidate_hash") or "",
        "candidate_model_name": (packet or {}).get("candidate_model_name", proposal_record.get("candidate_model_name") if proposal_record else candidate_path.stem),
        "candidate_path": (packet or {}).get("candidate_path") or _relative(candidate_path),
        "mutable_surface_path": _relative(candidate_path),
        "mutable_surface_sha256_before": mutable_surface_sha256_before,
        "mutable_surface_sha256_after": (packet or {}).get("mutable_surface_sha256_after") or _candidate_hash(candidate_path),
        "status": status,
        "keep": keep,
        "decision_reason": decision_reason,
        "loss": loss,
        "champion_id": champion_id,
        "proposal_id": proposal_record.get("proposal_id") if proposal_record else None,
        "parent_champion_id": proposal_record.get("parent_champion_id") if proposal_record else None,
        "proposer_model": proposal_record.get("proposer_model") if proposal_record else selection["proposer_model"],
        "proposer_tier": proposal_record.get("proposer_tier") if proposal_record else selection["selected_tier"],
        "estimated_llm_cost_usd": proposal_record.get("estimated_llm_cost_usd") if proposal_record else selection["estimated_llm_cost_usd"],
        "mutation_summary": proposal_record.get("mutation_summary") if proposal_record else None,
        "mutation_type": proposal_record.get("mutation_type") if proposal_record else None,
        "manifest_path": _relative(manifest_path),
        "packet_json": _relative(packet_json),
        "packet_md": _relative(packet_md),
        "chart_svg": _relative(chart_out),
        "artifact_paths": {
            "packet_json": _relative(packet_json),
            "packet_md": _relative(packet_md),
            "proposal_json": _relative(proposal_json_path),
            "proposal_candidate_py": _relative(proposal_candidate_path),
            "chart_svg": _relative(chart_out),
            "manifest_path": _relative(manifest_path),
        },
        "metrics": metrics,
        "error": (packet or {}).get("error"),
    }
    _append_jsonl(ledger_path, ledger_row)

    champion_payload = champion_before
    if keep and status == "keep":
        champion_payload = {
            "benchmark_id": ledger_row["benchmark_id"],
            "epoch_id": ledger_row["epoch_id"],
            "experiment_id": experiment_id,
            "loss": loss,
            "candidate_hash": ledger_row["candidate_hash"],
            "candidate_model_name": ledger_row["candidate_model_name"],
            "candidate_path": ledger_row["candidate_path"],
            "mutable_surface_path": ledger_row["mutable_surface_path"],
            "mutable_surface_sha256": ledger_row["mutable_surface_sha256_after"],
            "proposal_id": ledger_row["proposal_id"],
            "parent_champion_id": ledger_row["parent_champion_id"],
            "proposer_model": ledger_row["proposer_model"],
            "proposer_tier": ledger_row["proposer_tier"],
            "estimated_llm_cost_usd": ledger_row["estimated_llm_cost_usd"],
            "mutation_summary": ledger_row["mutation_summary"],
            "mutation_type": ledger_row["mutation_type"],
            "decision_reason": decision_reason,
            "generated_at": ledger_row["generated_at"],
            "packet_json": ledger_row["packet_json"],
            "manifest_path": ledger_row["manifest_path"],
        }
        _write_json(champion_path, champion_payload)

    render_progress(
        load_records(ledger_path),
        svg_out=chart_out,
        title="BTC5 Market-Model Benchmark Progress",
        y_label="BTC5 market-model loss (lower is better)",
    )

    rows_after = _load_ledger(ledger_path)
    budget_summary = {
        key: selection.get(key)
        for key in (
            "selected_tier",
            "preferred_tier",
            "daily_budget_usd",
            "budget_used_today_before_usd",
            "budget_used_today_after_usd",
            "budget_remaining_today_after_usd",
            "budget_reason",
            "consecutive_discards",
            "hours_without_keep",
            "escalation_reason",
            "last_keep_at",
        )
    }
    summary = {
        "benchmark_id": ledger_row["benchmark_id"],
        "epoch_id": ledger_row["epoch_id"],
        "manifest_path": _relative(manifest_path),
        "ledger_path": _relative(ledger_path),
        "chart_svg": _relative(chart_out),
        "counts": _counts(rows_after),
        "budget": budget_summary,
        "champion": champion_payload,
        "latest_proposal": proposal_record,
        "latest_experiment": ledger_row,
    }
    dump_path_atomic(latest_json_path, summary, indent=2, sort_keys=True, trailing_newline=True)
    policy_handoff = write_market_policy_handoff(
        market_latest_path=latest_json_path,
        output_path=policy_handoff_path,
    )
    summary.setdefault("artifacts", {})
    summary["artifacts"].update(
        {
            "policy_handoff_json": _relative(policy_handoff_path),
            "proposal_json": _relative(proposal_json_path),
            "proposal_candidate_py": _relative(proposal_candidate_path),
        }
    )
    summary["policy_handoff"] = {
        "path": _relative(policy_handoff_path),
        "policy_loss_contract_version": ((policy_handoff.get("policy_benchmark") or {}).get("policy_loss_contract_version")),
        "evaluation_source": ((policy_handoff.get("policy_benchmark") or {}).get("evaluation_source")),
        "market_epoch_active": policy_handoff.get("market_epoch_active"),
    }
    dump_path_atomic(latest_json_path, summary, indent=2, sort_keys=True, trailing_newline=True)
    _write_latest_markdown(latest_md_path, summary)

    if instance_output is not None:
        instance_payload = {
            "instance": 1,
            "project": "BTC5 Dual Autoresearch",
            "generated_at": ledger_row["generated_at"],
            "deliverables": {
                "manifest_path": _relative(manifest_path),
                "mutable_surface_path": _relative(candidate_path),
                "ledger_path": _relative(ledger_path),
                "champion_path": _relative(champion_path),
                "latest_json": _relative(latest_json_path),
                "latest_md": _relative(latest_md_path),
                "chart_svg": _relative(chart_out),
                "packet_json": _relative(packet_json),
                "packet_md": _relative(packet_md),
                "proposal_json": _relative(proposal_json_path),
                "proposal_candidate_py": _relative(proposal_candidate_path),
            },
            "latest_experiment": ledger_row,
            "champion": champion_payload,
            "budget": budget_summary,
        }
        _write_json(instance_output, instance_payload)

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
