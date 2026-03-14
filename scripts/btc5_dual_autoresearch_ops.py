#!/usr/bin/env python3
"""Supervise BTC5 dual-autoresearch lanes and publish operator-facing summaries."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from scripts.render_btc5_usd_per_day_progress import (
        build_outcome_summary as build_usd_per_day_summary,
        load_records as load_usd_per_day_records,
        render_svg as render_usd_per_day_svg,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from render_btc5_usd_per_day_progress import (
        build_outcome_summary as build_usd_per_day_summary,
        load_records as load_usd_per_day_records,
        render_svg as render_usd_per_day_svg,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_RELATIVE = Path("reports/autoresearch")
OPS_STATE_RELATIVE = Path("state/btc5_dual_autoresearch_state.json")
SURFACE_RELATIVE = REPORTS_RELATIVE / "latest.json"
SERVICE_AUDIT_RELATIVE = REPORTS_RELATIVE / "ops" / "service_audit.jsonl"
BURNIN_START_RELATIVE = REPORTS_RELATIVE / "ops" / "burnin_start.json"
MORNING_JSON_RELATIVE = REPORTS_RELATIVE / "morning" / "latest.json"
MORNING_MD_RELATIVE = REPORTS_RELATIVE / "morning" / "latest.md"
OVERNIGHT_CLOSEOUT_JSON_RELATIVE = REPORTS_RELATIVE / "overnight_closeout" / "latest.json"
OVERNIGHT_CLOSEOUT_MD_RELATIVE = REPORTS_RELATIVE / "overnight_closeout" / "latest.md"
INSTANCE_OUTPUT_RELATIVE = Path("instance05_dual_autoresearch_ops.json")
RUNTIME_TRUTH_RELATIVE = Path("reports/runtime_truth_latest.json")
REMOTE_SERVICE_STATUS_RELATIVE = Path("reports/remote_service_status.json")
REMOTE_CYCLE_STATUS_RELATIVE = Path("reports/remote_cycle_status.json")
DEFAULT_OVERNIGHT_WINDOW_HOURS = 12
MIN_OVERNIGHT_AUDIT_SPAN_HOURS = 8
MIN_OVERNIGHT_OBJECTIVE_RUNS = 4
OVERNIGHT_OBJECTIVE_LANES = ("market", "command_node")
OUTCOME_HISTORY_RELATIVE = REPORTS_RELATIVE / "outcomes" / "history.jsonl"
OUTCOME_LATEST_RELATIVE = REPORTS_RELATIVE / "outcomes" / "latest.json"
PORTFOLIO_EXPECTATION_RELATIVE = Path("reports/btc5_portfolio_expectation/latest.json")
ARR_LATEST_RELATIVE = Path("research/btc5_arr_latest.json")
ARR_SVG_RELATIVE = Path("research/btc5_arr_progress.svg")
USD_PER_DAY_SVG_RELATIVE = Path("research/btc5_usd_per_day_progress.svg")
DAYS_PER_MONTH = 30.0

DEFAULT_MARKET_COMMANDS: tuple[tuple[str, ...], ...] = (
    (sys.executable, "scripts/run_btc5_market_model_autoresearch.py"),
)
DEFAULT_POLICY_COMMANDS: tuple[tuple[str, ...], ...] = (
    (sys.executable, "scripts/run_btc5_policy_autoresearch.py", "--skip-cycle"),
    (
        sys.executable,
        "scripts/run_btc5_autoresearch_cycle.py",
        "--db-path",
        "data/btc_5min_maker.db",
        "--strategy-env",
        "config/btc5_strategy.env",
        "--override-env",
        "state/btc5_autoresearch.env",
        "--report-dir",
        "reports/btc5_autoresearch",
        "--paths",
        "10",
        "--block-size",
        "1",
        "--top-grid-candidates",
        "1",
        "--min-replay-fills",
        "2",
        "--regime-max-session-overrides",
        "1",
        "--regime-top-single-overrides-per-session",
        "1",
        "--regime-max-composed-candidates",
        "0",
    ),
)
DEFAULT_COMMAND_NODE_COMMANDS: tuple[tuple[str, ...], ...] = (
    (sys.executable, "scripts/run_btc5_command_node_autoresearch.py"),
    (sys.executable, "scripts/run_btc5_command_node_benchmark.py"),
)


@dataclass(frozen=True)
class LaneSpec:
    key: str
    name: str
    mutable_surface: str
    benchmark_label: str
    service_name: str
    timer_name: str
    latest_candidates: tuple[str, ...]
    ledger_candidates: tuple[str, ...]
    event_globs: tuple[str, ...]
    chart_paths: tuple[str, ...]
    command_candidates: tuple[tuple[str, ...], ...]
    freshness_seconds: int
    timeout_seconds: int
    cadence_seconds: int
    daily_runtime_budget_seconds: int
    backoff_base_seconds: int
    backoff_max_seconds: int


LANE_SPECS: dict[str, LaneSpec] = {
    "market": LaneSpec(
        key="market",
        name="btc5-market-model-autoresearch",
        mutable_surface="btc5_market_model_candidate.py",
        benchmark_label="BTC5 market-model benchmark progress",
        service_name="btc5-market-model-autoresearch.service",
        timer_name="btc5-market-model-autoresearch.timer",
        latest_candidates=("reports/autoresearch/btc5_market/latest.json",),
        ledger_candidates=("reports/autoresearch/btc5_market/results.jsonl",),
        event_globs=(),
        chart_paths=("research/btc5_market_model_progress.svg",),
        command_candidates=DEFAULT_MARKET_COMMANDS,
        freshness_seconds=4 * 3600,
        timeout_seconds=1800,
        cadence_seconds=3600,
        daily_runtime_budget_seconds=3 * 3600,
        backoff_base_seconds=300,
        backoff_max_seconds=4 * 3600,
    ),
    "policy": LaneSpec(
        key="policy",
        name="btc5-policy-autoresearch",
        mutable_surface="candidate JSON/env packages only",
        benchmark_label="BTC5 policy benchmark progress",
        service_name="btc5-policy-autoresearch.service",
        timer_name="btc5-policy-autoresearch.timer",
        latest_candidates=(
            "reports/autoresearch/btc5_policy/latest.json",
            "reports/btc5_autoresearch/latest.json",
            "reports/btc5_autoresearch_loop/latest.json",
        ),
        ledger_candidates=(
            "reports/autoresearch/btc5_policy/results.jsonl",
            "reports/btc5_autoresearch_loop/history.jsonl",
        ),
        event_globs=("reports/btc5_autoresearch/cycle_*.json",),
        chart_paths=(),
        command_candidates=DEFAULT_POLICY_COMMANDS,
        freshness_seconds=2 * 3600,
        timeout_seconds=600,
        cadence_seconds=15 * 60,
        daily_runtime_budget_seconds=4 * 3600,
        backoff_base_seconds=180,
        backoff_max_seconds=2 * 3600,
    ),
    "command_node": LaneSpec(
        key="command_node",
        name="btc5-command-node-autoresearch",
        mutable_surface="btc5_command_node.md",
        benchmark_label="BTC5 command-node benchmark progress",
        service_name="btc5-command-node-autoresearch.service",
        timer_name="btc5-command-node-autoresearch.timer",
        latest_candidates=("reports/autoresearch/command_node/latest.json",),
        ledger_candidates=("reports/autoresearch/command_node/results.jsonl",),
        event_globs=(),
        chart_paths=("research/btc5_command_node_progress.svg",),
        command_candidates=DEFAULT_COMMAND_NODE_COMMANDS,
        freshness_seconds=6 * 3600,
        timeout_seconds=1800,
        cadence_seconds=3600,
        daily_runtime_budget_seconds=3 * 3600,
        backoff_base_seconds=300,
        backoff_max_seconds=4 * 3600,
    ),
}


PROMOTION_STATES = {
    "live_activated",
    "live_promoted",
    "promote",
    "promoted",
    "queued_live_activation",
    "shadow_updated",
}
CRASH_STATES = {"crash", "error", "failed", "timeout"}
KEEP_STATES = {"keep", "kept", "promote", "promoted"}
AUDIT_RUN_FAILURE_STATUSES = {"runner_failed", "timeout"}


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _resolve(repo_root: Path, relative: str | Path) -> Path:
    return repo_root / Path(relative)


def _relative_text(repo_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_burnin_start(repo_root: Path) -> dict[str, Any]:
    payload = _read_json(_resolve(repo_root, BURNIN_START_RELATIVE))
    return payload if isinstance(payload, dict) else {}


def write_burnin_start_marker(
    *,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
    reason: str = "manual",
) -> dict[str, Any]:
    marker = {
        "artifact": "btc5_dual_autoresearch_burnin_start",
        "generated_at": (now or _utc_now()).isoformat(),
        "reason": str(reason or "manual").strip() or "manual",
    }
    _write_json(_resolve(repo_root, BURNIN_START_RELATIVE), marker)
    return marker


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
    except (OSError, json.JSONDecodeError):
        return []
    return rows


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


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


def _age_seconds(path: Path, payload: dict[str, Any], now: datetime) -> float | None:
    for key in ("generated_at", "finished_at", "timestamp", "updated_at", "created_at", "checked_at"):
        parsed = _parse_timestamp(payload.get(key))
        if parsed is not None:
            return max(0.0, (now - parsed).total_seconds())
    if not path.exists():
        return None
    return max(0.0, now.timestamp() - path.stat().st_mtime)


def _freshness_label(age_seconds: float | None, threshold_seconds: int) -> str:
    if age_seconds is None:
        return "missing"
    if age_seconds <= threshold_seconds:
        return "fresh"
    if age_seconds <= threshold_seconds * 2:
        return "aging"
    return "stale"


def _first_existing_path(repo_root: Path, candidates: Sequence[str]) -> Path | None:
    for candidate in candidates:
        path = _resolve(repo_root, candidate)
        if path.exists():
            return path
    return None


def _load_event_rows(repo_root: Path, spec: LaneSpec) -> tuple[list[dict[str, Any]], str | None]:
    ledger_path = _first_existing_path(repo_root, spec.ledger_candidates)
    if ledger_path is not None and ledger_path.suffix == ".jsonl":
        return _load_jsonl(ledger_path), _relative_text(repo_root, ledger_path)
    event_paths: list[Path] = []
    for pattern in spec.event_globs:
        event_paths.extend(sorted(repo_root.glob(pattern)))
    rows = [_read_json(path) | {"_source_path": _relative_text(repo_root, path)} for path in event_paths]
    rows = [row for row in rows if row]
    return rows, None


def _infer_status(row: dict[str, Any]) -> str:
    raw_status = str(row.get("status") or "").strip().lower()
    if raw_status in CRASH_STATES:
        return "crash"
    if raw_status in KEEP_STATES:
        return "keep"
    if raw_status in {"discard", "skipped", "hold"}:
        return "discard"
    if row.get("keep") is True:
        return "keep"
    if row.get("keep") is False:
        return "discard"
    decision = row.get("decision")
    if isinstance(decision, dict) and str(decision.get("action") or "").strip().lower() == "promote":
        return "keep"
    promotion_state = str(row.get("promotion_state") or "").strip().lower()
    if promotion_state in PROMOTION_STATES:
        return "keep"
    return "discard" if raw_status else "unknown"


def _infer_event_timestamp(row: dict[str, Any]) -> str | None:
    for key in (
        "generated_at",
        "finished_at",
        "timestamp",
        "updated_at",
        "evaluated_at",
        "created_at",
        "checked_at",
        "started_at",
    ):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_per_day(
    payload: dict[str, Any],
    *,
    per_day_key: str,
    pnl_30d_key: str,
) -> float | None:
    per_day = _coerce_float(payload.get(per_day_key))
    if per_day is not None:
        return per_day
    pnl_30d = _coerce_float(payload.get(pnl_30d_key))
    if pnl_30d is not None:
        return pnl_30d / DAYS_PER_MONTH
    return None


def _payload_generated_at(payload: dict[str, Any], path: Path | None = None) -> str | None:
    for key in (
        "generated_at",
        "finished_at",
        "latest_finished_at",
        "timestamp",
        "updated_at",
        "created_at",
        "checked_at",
        "source_generated_at",
    ):
        parsed = _parse_timestamp(payload.get(key))
        if parsed is not None:
            return parsed.isoformat()
    if path is None or not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _payload_generated_dt(payload: dict[str, Any], path: Path | None = None) -> datetime | None:
    timestamp = _payload_generated_at(payload, path)
    return _parse_timestamp(timestamp)


def _load_portfolio_expectation(repo_root: Path) -> dict[str, Any]:
    return _read_json(_resolve(repo_root, PORTFOLIO_EXPECTATION_RELATIVE))


def _load_outcome_summary(repo_root: Path) -> dict[str, Any]:
    return _read_json(_resolve(repo_root, OUTCOME_LATEST_RELATIVE))


def write_outcome_surfaces(repo_root: Path) -> dict[str, Any] | None:
    history_path = _resolve(repo_root, OUTCOME_HISTORY_RELATIVE)
    portfolio_expectation = _load_portfolio_expectation(repo_root)
    arr_summary = _read_json(_resolve(repo_root, ARR_LATEST_RELATIVE))
    records = load_usd_per_day_records(history_path)
    if not portfolio_expectation and not records and not arr_summary:
        return None
    summary = build_usd_per_day_summary(
        records,
        portfolio_expectation=portfolio_expectation,
        arr_summary=arr_summary,
    )
    summary["generated_at"] = _utc_now().isoformat()
    summary["source_path"] = (
        str(PORTFOLIO_EXPECTATION_RELATIVE) if portfolio_expectation else str(OUTCOME_HISTORY_RELATIVE)
    )
    summary["source_generated_at"] = (
        _payload_generated_at(portfolio_expectation, _resolve(repo_root, PORTFOLIO_EXPECTATION_RELATIVE))
        if portfolio_expectation
        else summary.get("latest_finished_at")
    )
    render_usd_per_day_svg(_resolve(repo_root, USD_PER_DAY_SVG_RELATIVE), records, summary)
    _write_json(_resolve(repo_root, OUTCOME_LATEST_RELATIVE), summary)
    return summary


def _build_outcome_surfaces(repo_root: Path) -> dict[str, Any]:
    """Build outcome surface block for inclusion in morning/overnight packets."""
    pe = _load_portfolio_expectation(repo_root)
    outcome = _load_outcome_summary(repo_root)
    arr_summary = _read_json(_resolve(repo_root, ARR_LATEST_RELATIVE))
    pe_path = _resolve(repo_root, PORTFOLIO_EXPECTATION_RELATIVE)
    outcome_path = _resolve(repo_root, OUTCOME_LATEST_RELATIVE)
    current_live = pe.get("current_live") or {}
    best_variant = pe.get("best_validated_variant") or {}
    pe_generated_dt = _payload_generated_dt(pe, pe_path) if pe else None
    outcome_generated_dt = _payload_generated_dt(outcome, outcome_path) if outcome else None
    primary_payload = dict(outcome or {})
    source = "outcome_ledger" if outcome else "portfolio_expectation"
    source_path = str(OUTCOME_LATEST_RELATIVE) if outcome else str(PORTFOLIO_EXPECTATION_RELATIVE)
    source_generated_at = _payload_generated_at(outcome, outcome_path) if outcome else None
    if pe and (outcome_generated_dt is None or (pe_generated_dt is not None and pe_generated_dt >= outcome_generated_dt)):
        primary_payload = {
            "expected_usd_per_day": _coerce_per_day(
                current_live,
                per_day_key="expected_pnl_per_day_usd",
                pnl_30d_key="expected_pnl_30d_usd",
            ),
            "historical_usd_per_day": _coerce_per_day(
                current_live,
                per_day_key="historical_pnl_per_day_usd",
                pnl_30d_key="historical_pnl_30d_usd",
            ),
            "expected_fills_per_day": _coerce_float(current_live.get("expected_fills_per_day")),
            "expected_pnl_30d_usd": _coerce_float(current_live.get("expected_pnl_30d_usd")),
        }
        source = "portfolio_expectation"
        source_path = str(PORTFOLIO_EXPECTATION_RELATIVE)
        source_generated_at = _payload_generated_at(pe, pe_path)

    expected_usd_per_day = _coerce_float(primary_payload.get("expected_usd_per_day"))
    if expected_usd_per_day is None:
        expected_usd_per_day = _coerce_per_day(
            current_live,
            per_day_key="expected_pnl_per_day_usd",
            pnl_30d_key="expected_pnl_30d_usd",
        )
    historical_usd_per_day = _coerce_float(primary_payload.get("historical_usd_per_day"))
    if historical_usd_per_day is None:
        historical_usd_per_day = _coerce_per_day(
            current_live,
            per_day_key="historical_pnl_per_day_usd",
            pnl_30d_key="historical_pnl_30d_usd",
        )
    expected_fills_per_day = _coerce_float(primary_payload.get("expected_fills_per_day"))
    if expected_fills_per_day is None:
        expected_fills_per_day = _coerce_float(current_live.get("expected_fills_per_day"))
    expected_pnl_30d_usd = _coerce_float(primary_payload.get("expected_pnl_30d_usd"))
    if expected_pnl_30d_usd is None and expected_usd_per_day is not None:
        expected_pnl_30d_usd = expected_usd_per_day * DAYS_PER_MONTH
    best_variant_expected_usd_per_day = _coerce_per_day(
        best_variant,
        per_day_key="expected_pnl_per_day_usd",
        pnl_30d_key="expected_pnl_30d_usd",
    )
    return {
        "disclaimer": "Outcome estimates, not realized P&L. Not benchmark loss metrics.",
        "expected_usd_per_day": round(expected_usd_per_day or 0.0, 4),
        "historical_usd_per_day": round(historical_usd_per_day or 0.0, 4),
        "expected_fills_per_day": round(expected_fills_per_day or 0.0, 4),
        "expected_pnl_30d_usd": round(expected_pnl_30d_usd or 0.0, 2),
        "best_variant_expected_usd_per_day": round(best_variant_expected_usd_per_day or 0.0, 4),
        "edge_status_current": (current_live.get("edge_status") or {}).get("status", "unknown"),
        "edge_status_best": (best_variant.get("edge_status") or {}).get("status", "unknown"),
        "portfolio_wallet_usd": round(
            _coerce_float((pe.get("portfolio") or {}).get("wallet_value_usd")) or 0.0, 2
        ),
        "source": source,
        "source_path": source_path,
        "source_generated_at": source_generated_at,
        "portfolio_expectation_generated_at": _payload_generated_at(pe, pe_path) if pe else None,
        "outcome_generated_at": _payload_generated_at(outcome, outcome_path) if outcome else None,
        "arr_latest_active_arr_pct": round(_coerce_float(arr_summary.get("latest_active_arr_pct")) or 0.0, 4),
        "arr_latest_best_arr_pct": round(_coerce_float(arr_summary.get("latest_best_arr_pct")) or 0.0, 4),
        "arr_latest_delta_arr_pct": round(_coerce_float(arr_summary.get("latest_delta_arr_pct")) or 0.0, 4),
        "arr_frontier_active_arr_pct": round(
            _coerce_float(arr_summary.get("frontier_active_arr_pct")) or 0.0, 4
        ),
        "arr_latest_action": arr_summary.get("latest_action"),
        "arr_latest_finished_at": arr_summary.get("latest_finished_at"),
        "arr_json_path": str(ARR_LATEST_RELATIVE),
        "arr_json_exists": _resolve(repo_root, ARR_LATEST_RELATIVE).exists(),
        "arr_svg_path": str(ARR_SVG_RELATIVE),
        "arr_svg_exists": _resolve(repo_root, ARR_SVG_RELATIVE).exists(),
        "usd_per_day_svg_path": str(USD_PER_DAY_SVG_RELATIVE),
        "usd_per_day_svg_exists": _resolve(repo_root, USD_PER_DAY_SVG_RELATIVE).exists(),
        "outcome_json_path": str(OUTCOME_LATEST_RELATIVE),
        "outcome_json_exists": _resolve(repo_root, OUTCOME_LATEST_RELATIVE).exists(),
    }


def append_outcome_record(
    repo_root: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Append a single outcome record from current portfolio expectation."""
    pe = _load_portfolio_expectation(repo_root)
    if not pe:
        return None
    now = now or _utc_now()
    current_live = pe.get("current_live") or {}
    source_generated_at = _payload_generated_at(pe, _resolve(repo_root, PORTFOLIO_EXPECTATION_RELATIVE))
    record = {
        "finished_at": now.isoformat(),
        "source": "portfolio_expectation",
        "source_generated_at": source_generated_at,
        "expected_usd_per_day": round(
            _coerce_per_day(
                current_live,
                per_day_key="expected_pnl_per_day_usd",
                pnl_30d_key="expected_pnl_30d_usd",
            )
            or 0.0,
            4,
        ),
        "historical_usd_per_day": round(
            _coerce_per_day(
                current_live,
                per_day_key="historical_pnl_per_day_usd",
                pnl_30d_key="historical_pnl_30d_usd",
            )
            or 0.0,
            4,
        ),
        "expected_fills_per_day": round(_coerce_float(current_live.get("expected_fills_per_day")) or 0.0, 4),
        "edge_status": (current_live.get("edge_status") or {}).get("status", "unknown"),
    }
    history_path = _resolve(repo_root, OUTCOME_HISTORY_RELATIVE)
    history_rows = _load_jsonl(history_path)
    if history_rows and source_generated_at:
        last_row = history_rows[-1]
        if str(last_row.get("source_generated_at") or "") == source_generated_at:
            write_outcome_surfaces(repo_root)
            return last_row
    _append_jsonl(_resolve(repo_root, OUTCOME_HISTORY_RELATIVE), record)
    write_outcome_surfaces(repo_root)
    return record


def _extract_loss(row: dict[str, Any]) -> float | None:
    for key in ("loss", "policy_loss", "simulator_loss", "agent_loss"):
        value = _coerce_float(row.get(key))
        if value is not None:
            return value
    decision = row.get("decision")
    if isinstance(decision, dict):
        for key in ("loss", "policy_loss", "simulator_loss", "agent_loss"):
            value = _coerce_float(decision.get(key))
            if value is not None:
                return value
    return None


def _extract_label(row: dict[str, Any]) -> str:
    candidates = [
        row.get("champion_id"),
        row.get("candidate_hash"),
        row.get("candidate_label"),
        row.get("candidate_policy"),
        row.get("prompt_hash"),
        row.get("experiment_id"),
        row.get("best_profile", {}).get("name") if isinstance(row.get("best_profile"), dict) else None,
        row.get("best_candidate", {}).get("policy", {}).get("name")
        if isinstance(row.get("best_candidate"), dict)
        and isinstance(row.get("best_candidate", {}).get("policy"), dict)
        else None,
        row.get("best_candidate", {}).get("profile", {}).get("name")
        if isinstance(row.get("best_candidate"), dict)
        and isinstance(row.get("best_candidate", {}).get("profile"), dict)
        else None,
        row.get("best_runtime_package", {}).get("profile", {}).get("name")
        if isinstance(row.get("best_runtime_package"), dict)
        and isinstance(row.get("best_runtime_package", {}).get("profile"), dict)
        else None,
        row.get("selected_best_runtime_package", {}).get("profile", {}).get("name")
        if isinstance(row.get("selected_best_runtime_package"), dict)
        and isinstance(row.get("selected_best_runtime_package", {}).get("profile"), dict)
        else None,
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return "unknown"


def _normalize_events(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        timestamp = _infer_event_timestamp(row)
        status = _infer_status(row)
        decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
        promotion_state = str(row.get("promotion_state") or decision.get("action") or "").strip().lower()
        events.append(
            {
                "timestamp": timestamp,
                "parsed_timestamp": _parse_timestamp(timestamp),
                "status": status,
                "label": _extract_label(row),
                "loss": _extract_loss(row),
                "promotion_state": promotion_state or None,
                "is_keep": status == "keep",
                "is_crash": status == "crash",
                "is_promotion": promotion_state in PROMOTION_STATES,
                "artifact_path": row.get("_source_path"),
            }
        )
    events.sort(key=lambda item: item["parsed_timestamp"] or datetime.min.replace(tzinfo=UTC))
    return events


def _extract_champion(latest_payload: dict[str, Any], events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    champion_field = latest_payload.get("champion")
    champion_dict = champion_field if isinstance(champion_field, dict) else {}
    if isinstance(champion_field, dict):
        champion_candidate = (
            champion_field.get("candidate_label")
            or champion_field.get("prompt_hash")
            or champion_field.get("candidate_hash")
            or champion_field.get("experiment_id")
        )
    else:
        champion_candidate = champion_field
    champion_id: str | None = None
    for candidate in (
        latest_payload.get("champion_id"),
        champion_candidate,
        latest_payload.get("best_candidate", {}).get("policy", {}).get("name")
        if isinstance(latest_payload.get("best_candidate"), dict)
        and isinstance(latest_payload.get("best_candidate", {}).get("policy"), dict)
        else None,
        latest_payload.get("best_candidate", {}).get("profile", {}).get("name")
        if isinstance(latest_payload.get("best_candidate"), dict)
        and isinstance(latest_payload.get("best_candidate", {}).get("profile"), dict)
        else None,
        latest_payload.get("best_runtime_package", {}).get("profile", {}).get("name")
        if isinstance(latest_payload.get("best_runtime_package"), dict)
        and isinstance(latest_payload.get("best_runtime_package", {}).get("profile"), dict)
        else None,
        latest_payload.get("selected_best_runtime_package", {}).get("profile", {}).get("name")
        if isinstance(latest_payload.get("selected_best_runtime_package"), dict)
        and isinstance(latest_payload.get("selected_best_runtime_package", {}).get("profile"), dict)
        else None,
        latest_payload.get("best_profile", {}).get("name")
        if isinstance(latest_payload.get("best_profile"), dict)
        else None,
    ):
        text = str(candidate or "").strip()
        if text:
            champion_id = text
            break
    if champion_id is None:
        for event in reversed(events):
            if event["is_keep"]:
                champion_id = event["label"]
                break
    # Extract loss: prefer champion dict metadata, then top-level fields.
    loss = _extract_loss(champion_dict) if champion_dict else None
    if loss is None:
        loss = _extract_loss(latest_payload)
    # Extract model name from champion dict metadata.
    model_name = str(
        champion_dict.get("candidate_model_name")
        or champion_dict.get("candidate_label")
        or ""
    ).strip() or None
    # Extract updated_at: prefer champion dict, then top-level.
    updated_at = _infer_event_timestamp(champion_dict) if champion_dict else None
    if updated_at is None:
        updated_at = _infer_event_timestamp(latest_payload)
    result: dict[str, Any] = {
        "id": champion_id,
        "loss": loss,
        "updated_at": updated_at,
    }
    if model_name:
        result["model_name"] = model_name
    policy_id = str(champion_dict.get("policy_id") or "").strip() or None
    if policy_id:
        result["policy_id"] = policy_id
    return result


def _subject_from_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    subject_id: str | None = None
    for key in (
        "package_hash",
        "candidate_hash",
        "prompt_hash",
        "mutable_surface_sha256",
        "policy_id",
        "candidate_policy",
        "candidate_model_name",
        "candidate_label",
        "experiment_id",
        "champion_id",
    ):
        text = str(source.get(key) or "").strip()
        if text:
            subject_id = text
            break
    label: str | None = None
    for key in ("candidate_model_name", "candidate_label", "policy_id", "candidate_policy"):
        text = str(source.get(key) or "").strip()
        if text:
            label = text
            break
    updated_at = _infer_event_timestamp(source)
    loss = _extract_loss(source)
    subject: dict[str, Any] = {}
    if subject_id:
        subject["id"] = subject_id
    if label and label != subject_id:
        subject["label"] = label
    if loss is not None:
        subject["loss"] = loss
    if updated_at:
        subject["updated_at"] = updated_at
    for key in (
        "candidate_hash",
        "candidate_label",
        "candidate_model_name",
        "experiment_id",
        "package_hash",
        "policy_id",
        "prompt_hash",
    ):
        value = source.get(key)
        if value not in (None, ""):
            subject[key] = value
    return subject or None


def _subject_from_latest_payload(latest_payload: dict[str, Any]) -> dict[str, Any] | None:
    champion = latest_payload.get("champion")
    if isinstance(champion, dict):
        subject = _subject_from_source(champion)
        if subject is not None:
            return subject
    return _subject_from_source(latest_payload)


def _subject_from_incumbent_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    incumbent_policy = str(row.get("incumbent_policy") or "").strip()
    if not incumbent_policy:
        return None
    return _subject_from_source(
        {
            "policy_id": incumbent_policy,
            "policy_loss": row.get("incumbent_policy_loss"),
            "generated_at": _infer_event_timestamp(row),
        }
    )


def _subjects_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    left_id = str(left.get("id") or "").strip()
    right_id = str(right.get("id") or "").strip()
    if left_id and right_id:
        return left_id == right_id
    left_label = str(left.get("label") or "").strip()
    right_label = str(right.get("label") or "").strip()
    return bool(left_label and right_label and left_label == right_label)


def _loss_delta_if_comparable(
    champion_before: dict[str, Any] | None,
    champion_after: dict[str, Any] | None,
) -> float | None:
    before_loss = _coerce_float((champion_before or {}).get("loss"))
    after_loss = _coerce_float((champion_after or {}).get("loss"))
    if before_loss is None or after_loss is None:
        return None
    return round(after_loss - before_loss, 6)


def _render_subject(subject: dict[str, Any] | None) -> str:
    if not isinstance(subject, dict) or not subject:
        return "n/a"
    name = str(subject.get("label") or subject.get("id") or "n/a")
    loss = _coerce_float(subject.get("loss"))
    if loss is None:
        return name
    return f"{name} (loss={loss})"


def _resolve_command(
    repo_root: Path,
    spec: LaneSpec,
    *,
    override_command: str | None = None,
) -> list[str] | None:
    if override_command:
        return shlex.split(override_command)
    env_key = f"BTC5_DUAL_AUTORESEARCH_{spec.key.upper()}_COMMAND"
    env_value = os.environ.get(env_key)
    if env_value:
        return shlex.split(env_value)
    for candidate in spec.command_candidates:
        missing_target = False
        for part in candidate:
            if part.endswith(".py"):
                if not _resolve(repo_root, part).exists():
                    missing_target = True
                    break
        if not missing_target:
            return list(candidate)
    return None


def _load_state(repo_root: Path) -> dict[str, Any]:
    return _read_json(_resolve(repo_root, OPS_STATE_RELATIVE))


def _save_state(repo_root: Path, payload: dict[str, Any]) -> None:
    _write_json(_resolve(repo_root, OPS_STATE_RELATIVE), payload)


def _load_audit_rows(repo_root: Path) -> list[dict[str, Any]]:
    return _load_jsonl(_resolve(repo_root, SERVICE_AUDIT_RELATIVE))


def _runtime_budget_used_seconds(
    *,
    lane_key: str,
    audit_rows: Sequence[dict[str, Any]],
    now: datetime,
) -> float:
    cutoff = now - timedelta(hours=24)
    total = 0.0
    for row in audit_rows:
        if str(row.get("lane")) != lane_key:
            continue
        parsed = _parse_timestamp(row.get("generated_at"))
        if parsed is None or parsed < cutoff:
            continue
        total += max(_coerce_float(row.get("duration_seconds")) or 0.0, 0.0)
    return round(total, 4)


def update_lane_state_after_run(
    lane_state: dict[str, Any],
    *,
    success: bool,
    now: datetime,
    spec: LaneSpec,
    status_label: str,
) -> dict[str, Any]:
    updated = dict(lane_state)
    updated["last_run_at"] = now.isoformat()
    if success:
        updated["consecutive_failures"] = 0
        updated["backoff_until"] = None
        updated["last_success_at"] = now.isoformat()
        updated["last_status"] = status_label
        return updated
    failures = int(updated.get("consecutive_failures") or 0) + 1
    backoff_seconds = min(spec.backoff_base_seconds * (2 ** max(failures - 1, 0)), spec.backoff_max_seconds)
    updated["consecutive_failures"] = failures
    updated["backoff_until"] = (now + timedelta(seconds=backoff_seconds)).isoformat()
    updated["last_status"] = status_label
    return updated


def build_lane_snapshot(
    spec: LaneSpec,
    *,
    repo_root: Path = REPO_ROOT,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utc_now()
    current_state = state or {}
    lane_state = dict((current_state.get("lanes") or {}).get(spec.key) or {})
    latest_path = _first_existing_path(repo_root, spec.latest_candidates)
    latest_payload = _read_json(latest_path) if latest_path is not None else {}
    latest_age_seconds = _age_seconds(latest_path, latest_payload, now) if latest_path is not None else None
    latest_freshness = _freshness_label(latest_age_seconds, spec.freshness_seconds)
    event_rows, ledger_source = _load_event_rows(repo_root, spec)
    events = _normalize_events(event_rows)
    recent_cutoff = now - timedelta(hours=24)
    recent_event_items = [
        item
        for item in events
        if item["parsed_timestamp"] is not None and item["parsed_timestamp"] >= recent_cutoff
    ]
    recent_events = [
        {
            "timestamp": item["timestamp"],
            "status": item["status"],
            "label": item["label"],
            "loss": item["loss"],
            "promotion_state": item["promotion_state"],
            "artifact_path": item["artifact_path"],
        }
        for item in recent_event_items
    ]
    charts: list[dict[str, Any]] = []
    blockers: list[str] = []
    for chart_relative in spec.chart_paths:
        chart_path = _resolve(repo_root, chart_relative)
        chart_age = None
        if chart_path.exists():
            chart_age = max(0.0, now.timestamp() - chart_path.stat().st_mtime)
        chart_freshness = _freshness_label(chart_age, spec.freshness_seconds)
        chart_info = {
            "path": chart_relative,
            "exists": chart_path.exists(),
            "age_seconds": round(chart_age, 4) if chart_age is not None else None,
            "freshness": chart_freshness,
        }
        charts.append(chart_info)
        if not chart_path.exists():
            blockers.append(f"missing_chart:{chart_relative}")
        elif chart_freshness == "stale":
            blockers.append(f"stale_chart:{chart_relative}")
    if latest_path is None:
        blockers.append("missing_latest_artifact")
    elif latest_freshness == "stale":
        blockers.append(
            f"stale_latest_artifact:{_relative_text(repo_root, latest_path)}:{int(latest_age_seconds or 0)}s"
        )
    if not event_rows:
        blockers.append("missing_append_only_event_history")
    command = _resolve_command(repo_root, spec)
    if command is None:
        blockers.append("missing_lane_runner")
    budget_used_seconds = _runtime_budget_used_seconds(
        lane_key=spec.key,
        audit_rows=_load_audit_rows(repo_root),
        now=now,
    )
    budget_remaining_seconds = max(spec.daily_runtime_budget_seconds - budget_used_seconds, 0.0)
    if budget_remaining_seconds <= 0.0:
        blockers.append("daily_runtime_budget_exhausted")
    backoff_until = _parse_timestamp(lane_state.get("backoff_until"))
    if backoff_until is not None and backoff_until > now:
        blockers.append(f"backoff_active_until:{backoff_until.isoformat()}")
    champion = _extract_champion(latest_payload, events)
    status = "healthy"
    if any(blocker.startswith("missing_") for blocker in blockers):
        status = "blocked"
    elif blockers:
        status = "degraded"
    recent_keep_count = sum(1 for item in recent_events if item["status"] == "keep")
    recent_crash_count = sum(1 for item in recent_events if item["status"] == "crash")
    recent_discard_count = sum(1 for item in recent_events if item["status"] == "discard")
    recent_promotion_count = sum(1 for item in recent_events if item["promotion_state"] in PROMOTION_STATES)
    return {
        "lane": spec.key,
        "name": spec.name,
        "mutable_surface": spec.mutable_surface,
        "benchmark_label": spec.benchmark_label,
        "status": status,
        "blockers": blockers,
        "service_name": spec.service_name,
        "timer_name": spec.timer_name,
        "configured_cadence_seconds": spec.cadence_seconds,
        "timeout_seconds": spec.timeout_seconds,
        "daily_runtime_budget_seconds": spec.daily_runtime_budget_seconds,
        "daily_runtime_used_seconds": budget_used_seconds,
        "daily_runtime_remaining_seconds": round(budget_remaining_seconds, 4),
        "command": command,
        "command_available": command is not None,
        "latest_artifact_path": _relative_text(repo_root, latest_path),
        "latest_artifact_freshness": latest_freshness,
        "latest_artifact_age_seconds": round(latest_age_seconds, 4) if latest_age_seconds is not None else None,
        "event_history_path": ledger_source,
        "event_count": len(events),
        "recent_experiment_count_24h": len(recent_event_items),
        "recent_keep_count_24h": recent_keep_count,
        "recent_crash_count_24h": recent_crash_count,
        "recent_discard_count_24h": recent_discard_count,
        "recent_promotion_count_24h": recent_promotion_count,
        "recent_events": recent_events[-10:],
        "charts": charts,
        "champion": champion,
        "consecutive_failures": int(lane_state.get("consecutive_failures") or 0),
        "backoff_until": lane_state.get("backoff_until"),
        "last_success_at": lane_state.get("last_success_at"),
        "last_status": lane_state.get("last_status"),
        "benchmark_progress_only": True,
    }


def _load_runtime_safety(repo_root: Path) -> dict[str, Any]:
    runtime_truth = _read_json(_resolve(repo_root, RUNTIME_TRUTH_RELATIVE))
    remote_service_status = _read_json(_resolve(repo_root, REMOTE_SERVICE_STATUS_RELATIVE))
    remote_cycle_status = _read_json(_resolve(repo_root, REMOTE_CYCLE_STATUS_RELATIVE))
    launch_posture = str(
        runtime_truth.get("launch_posture")
        or runtime_truth.get("launch", {}).get("posture")
        or remote_cycle_status.get("launch", {}).get("posture")
        or "unknown"
    ).strip()
    service_status = str(
        remote_service_status.get("status")
        or runtime_truth.get("service", {}).get("status")
        or remote_cycle_status.get("service", {}).get("status")
        or "unknown"
    ).strip()
    allow_order_submission = bool(
        runtime_truth.get("allow_order_submission")
        if "allow_order_submission" in runtime_truth
        else runtime_truth.get("launch", {}).get("allow_order_submission")
    )
    blockers = list(runtime_truth.get("block_reasons") or [])
    if launch_posture and launch_posture != "clear":
        blockers.append(f"launch_posture_not_clear:{launch_posture}")
    if service_status and service_status != "running":
        blockers.append(f"primary_service_not_running:{service_status}")
    return {
        "launch_posture": launch_posture or "unknown",
        "service_status": service_status or "unknown",
        "allow_order_submission": allow_order_submission,
        "blockers": _dedupe(blockers),
        "source_artifacts": [
            _relative_text(repo_root, _resolve(repo_root, RUNTIME_TRUTH_RELATIVE)),
            _relative_text(repo_root, _resolve(repo_root, REMOTE_SERVICE_STATUS_RELATIVE)),
            _relative_text(repo_root, _resolve(repo_root, REMOTE_CYCLE_STATUS_RELATIVE)),
        ],
    }


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _audit_row_is_run(row: dict[str, Any]) -> bool:
    return str(row.get("event_type") or "").strip().lower() == "run"


def _audit_row_is_failed_run(row: dict[str, Any]) -> bool:
    if not _audit_row_is_run(row):
        return False
    status = str(row.get("status") or "").strip().lower()
    if status in AUDIT_RUN_FAILURE_STATUSES or status in CRASH_STATES:
        return True
    returncode = _coerce_float(row.get("returncode"))
    return returncode is not None and returncode != 0.0


def _build_service_audit_window_summary(
    audit_rows: Sequence[dict[str, Any]],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    window_rows: list[dict[str, Any]] = []
    lane_run_counts = {lane_key: 0 for lane_key in LANE_SPECS}
    lane_failed_run_counts = {lane_key: 0 for lane_key in LANE_SPECS}
    lane_first_run_at = {lane_key: None for lane_key in LANE_SPECS}
    lane_last_run_at = {lane_key: None for lane_key in LANE_SPECS}
    objective_run_rows: list[dict[str, Any]] = []
    for row in audit_rows:
        parsed = _parse_timestamp(row.get("generated_at"))
        if parsed is None or parsed < cutoff:
            continue
        item = {"row": row, "parsed_timestamp": parsed}
        window_rows.append(item)
        lane_key = str(row.get("lane") or "").strip()
        if lane_key not in LANE_SPECS or not _audit_row_is_run(row):
            continue
        lane_run_counts[lane_key] += 1
        if lane_first_run_at[lane_key] is None:
            lane_first_run_at[lane_key] = row.get("generated_at")
        lane_last_run_at[lane_key] = row.get("generated_at")
        if _audit_row_is_failed_run(row):
            lane_failed_run_counts[lane_key] += 1
        if lane_key in OVERNIGHT_OBJECTIVE_LANES:
            objective_run_rows.append(item)
    window_rows.sort(key=lambda item: item["parsed_timestamp"])
    objective_run_rows.sort(key=lambda item: item["parsed_timestamp"])
    window_first_event_at = window_rows[0]["row"].get("generated_at") if window_rows else None
    window_last_event_at = window_rows[-1]["row"].get("generated_at") if window_rows else None
    objective_window_first_run_at = (
        objective_run_rows[0]["row"].get("generated_at") if objective_run_rows else None
    )
    objective_window_last_run_at = (
        objective_run_rows[-1]["row"].get("generated_at") if objective_run_rows else None
    )
    objective_span_seconds: float | None = None
    if objective_run_rows:
        objective_span_seconds = max(
            0.0,
            (
                objective_run_rows[-1]["parsed_timestamp"] - objective_run_rows[0]["parsed_timestamp"]
            ).total_seconds(),
        )
    return {
        "window_rows": window_rows,
        "window_first_event_at": window_first_event_at,
        "window_last_event_at": window_last_event_at,
        "objective_window_first_run_at": objective_window_first_run_at,
        "objective_window_last_run_at": objective_window_last_run_at,
        "objective_span_seconds": objective_span_seconds,
        "lane_run_counts": lane_run_counts,
        "lane_failed_run_counts": lane_failed_run_counts,
        "lane_first_run_at": lane_first_run_at,
        "lane_last_run_at": lane_last_run_at,
    }


def build_surface_snapshot(
    *,
    repo_root: Path = REPO_ROOT,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utc_now()
    current_state = state or _load_state(repo_root)
    lanes = {
        key: build_lane_snapshot(spec, repo_root=repo_root, state=current_state, now=now)
        for key, spec in LANE_SPECS.items()
    }
    stale_alarms = _dedupe(
        blocker
        for lane in lanes.values()
        for blocker in list(lane.get("blockers") or [])
        if blocker.startswith("missing_") or blocker.startswith("stale_")
    )
    blocked_lanes = [key for key, lane in lanes.items() if lane["status"] == "blocked"]
    degraded_lanes = [key for key, lane in lanes.items() if lane["status"] == "degraded"]
    backoff_lanes = [
        key
        for key, lane in lanes.items()
        if any(str(blocker).startswith("backoff_active_until:") for blocker in lane.get("blockers") or [])
    ]
    budget_lanes = [
        key
        for key, lane in lanes.items()
        if "daily_runtime_budget_exhausted" in (lane.get("blockers") or [])
    ]
    overall_status = "healthy"
    if blocked_lanes:
        overall_status = "blocked"
    elif degraded_lanes:
        overall_status = "degraded"
    champions = {key: lane["champion"] for key, lane in lanes.items()}
    lane_summaries = {
        key: {
            "benchmark_label": lane["benchmark_label"],
            "status": lane["status"],
            "blockers": list(lane.get("blockers") or []),
            "champion": dict(lane.get("champion") or {}),
            "chart": dict((lane.get("charts") or [{}])[0] or {}),
            "recent_experiment_count_24h": int(lane.get("recent_experiment_count_24h") or 0),
            "recent_keep_count_24h": int(lane.get("recent_keep_count_24h") or 0),
            "recent_crash_count_24h": int(lane.get("recent_crash_count_24h") or 0),
            "recent_promotion_count_24h": int(lane.get("recent_promotion_count_24h") or 0),
            "benchmark_progress_only": True,
        }
        for key, lane in lanes.items()
    }
    runtime_safety = _load_runtime_safety(repo_root)
    audit_trail_paths = {
        "service_audit_jsonl": str(SERVICE_AUDIT_RELATIVE),
        "lane_event_history": {
            key: lane.get("event_history_path")
            for key, lane in lanes.items()
            if lane.get("event_history_path")
        },
    }
    source_artifacts = _dedupe(
        [
            *(lane.get("latest_artifact_path") for lane in lanes.values()),
            *(lane.get("event_history_path") for lane in lanes.values()),
            *(
                chart.get("path")
                for lane in lanes.values()
                for chart in list(lane.get("charts") or [])
            ),
            str(ARR_SVG_RELATIVE),
            str(USD_PER_DAY_SVG_RELATIVE),
            str(OUTCOME_LATEST_RELATIVE),
            _relative_text(repo_root, _resolve(repo_root, SERVICE_AUDIT_RELATIVE)),
            *list(runtime_safety.get("source_artifacts") or []),
        ]
    )
    public_charts = {
        "market_model": {
            "label": "BTC5 market-model loss (lower is better)",
            "benchmark_progress_only": True,
            "path": "research/btc5_market_model_progress.svg",
            "exists": _resolve(repo_root, "research/btc5_market_model_progress.svg").exists(),
        },
        "command_node": {
            "label": "BTC5 command-node loss (lower is better)",
            "benchmark_progress_only": True,
            "path": "research/btc5_command_node_progress.svg",
            "exists": _resolve(repo_root, "research/btc5_command_node_progress.svg").exists(),
        },
        "arr_outcome": {
            "label": "BTC5 continuation ARR (outcome estimate, not benchmark loss)",
            "benchmark_progress_only": False,
            "path": str(ARR_SVG_RELATIVE),
            "exists": _resolve(repo_root, ARR_SVG_RELATIVE).exists(),
        },
        "usd_per_day_outcome": {
            "label": "BTC5 USD/day (outcome estimate, not benchmark loss)",
            "benchmark_progress_only": False,
            "path": str(USD_PER_DAY_SVG_RELATIVE),
            "exists": _resolve(repo_root, USD_PER_DAY_SVG_RELATIVE).exists(),
        },
    }
    summary = (
        "BTC5 dual-autoresearch surface. Benchmark progress only, not realized P&L. "
        f"Healthy lanes: {sum(1 for lane in lanes.values() if lane['status'] == 'healthy')}/{len(lanes)}."
    )
    return {
        "artifact": "btc5_dual_autoresearch_surface",
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "summary": summary,
        "benchmark_progress_only": True,
        "service_health": {
            "overall_status": overall_status,
            "blocked_lanes": blocked_lanes,
            "degraded_lanes": degraded_lanes,
            "backoff_lanes": backoff_lanes,
            "budget_exhausted_lanes": budget_lanes,
            "stale_artifact_alarms": stale_alarms,
        },
        "runtime_safety": runtime_safety,
        "lanes": lanes,
        "lane_summaries": lane_summaries,
        "current_champions": champions,
        "public_charts": public_charts,
        "audit_trail_paths": audit_trail_paths,
        "morning_report_paths": {
            "json": str(MORNING_JSON_RELATIVE),
            "markdown": str(MORNING_MD_RELATIVE),
        },
        "source_artifacts": source_artifacts,
    }


def write_surface_snapshot(
    *,
    repo_root: Path = REPO_ROOT,
    state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    write_outcome_surfaces(repo_root)
    payload = build_surface_snapshot(repo_root=repo_root, state=state, now=now)
    _write_json(_resolve(repo_root, SURFACE_RELATIVE), payload)
    return payload


def _build_champion_deltas(
    surface: dict[str, Any],
    *,
    previous_champions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build per-lane champion-delta dicts comparing current to previous champion."""
    current_champions = dict(surface.get("current_champions") or {})
    prev = previous_champions or {}
    deltas: dict[str, dict[str, Any]] = {}
    for lane_key in LANE_SPECS:
        current = dict(current_champions.get(lane_key) or {})
        previous = dict(prev.get(lane_key) or {})
        current_id = current.get("id")
        previous_id = previous.get("id")
        changed = bool(current_id and previous_id and current_id != previous_id)
        delta_if_comparable: float | None = None
        if changed:
            cur_loss = _coerce_float(current.get("loss"))
            prev_loss = _coerce_float(previous.get("loss"))
            if cur_loss is not None and prev_loss is not None:
                delta_if_comparable = round(cur_loss - prev_loss, 6)
        deltas[lane_key] = {
            "previous_champion": previous if previous.get("id") else None,
            "current_champion": current if current.get("id") else None,
            "changed": changed,
            "delta_if_comparable": delta_if_comparable,
        }
    return deltas


def build_morning_packet(
    surface: dict[str, Any],
    *,
    now: datetime | None = None,
    window_hours: int = 24,
    previous_champions: dict[str, dict[str, Any]] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    now = now or _utc_now()
    cutoff = now - timedelta(hours=window_hours)
    experiment_samples: list[dict[str, Any]] = []
    experiments_run_by_lane: dict[str, int] = {}
    kept_improvements: list[dict[str, Any]] = []
    crashes: list[dict[str, Any]] = []
    promotions: list[dict[str, Any]] = []
    # Separate benchmark blockers from live posture blockers.
    benchmark_blockers = list(((surface.get("service_health") or {}).get("stale_artifact_alarms") or []))
    live_posture_blockers = list(((surface.get("runtime_safety") or {}).get("blockers") or []))
    for lane_key, lane in dict(surface.get("lanes") or {}).items():
        experiments_run_by_lane[lane_key] = int(
            lane.get("recent_experiment_count_24h") or len(list(lane.get("recent_events") or []))
        )
        for event in list(lane.get("recent_events") or []):
            parsed = _parse_timestamp(event.get("timestamp"))
            if parsed is not None and parsed < cutoff:
                continue
            entry = {"lane": lane_key, **event}
            experiment_samples.append(entry)
            if str(event.get("status")) == "keep":
                kept_improvements.append(entry)
            if str(event.get("status")) == "crash":
                crashes.append(entry)
            if str(event.get("promotion_state") or "").strip().lower() in PROMOTION_STATES:
                promotions.append(entry)
        benchmark_blockers.extend(list(lane.get("blockers") or []))
    benchmark_blockers = _dedupe(benchmark_blockers)
    live_posture_blockers = _dedupe(live_posture_blockers)
    # Combined blockers for backward compat.
    all_blockers = _dedupe(benchmark_blockers + live_posture_blockers)
    experiment_samples.sort(
        key=lambda item: _parse_timestamp(item.get("timestamp")) or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    experiments_run = {
        "total": sum(experiments_run_by_lane.values()),
        "by_lane": experiments_run_by_lane,
        "recent_samples": experiment_samples[:20],
    }
    null_result_lanes = [
        lane_key
        for lane_key, lane in dict(surface.get("lanes") or {}).items()
        if int(lane.get("recent_keep_count_24h") or 0) == 0
        and int(lane.get("recent_promotion_count_24h") or 0) == 0
        and int(lane.get("recent_crash_count_24h") or 0) == 0
    ]
    champion_deltas = _build_champion_deltas(surface, previous_champions=previous_champions)
    outcome_surfaces = _build_outcome_surfaces(repo_root)
    summary_lines = [
        "BTC5 dual-autoresearch morning summary.",
        "Benchmark progress only, not realized P&L.",
        f"Current champions: market={surface.get('current_champions', {}).get('market', {}).get('id') or 'n/a'}, "
        f"policy={surface.get('current_champions', {}).get('policy', {}).get('id') or 'n/a'}, "
        f"command_node={surface.get('current_champions', {}).get('command_node', {}).get('id') or 'n/a'}.",
        (
            f"Window {window_hours}h experiments={experiments_run['total']} kept={len(kept_improvements)} "
            f"crashes={len(crashes)} promotions={len(promotions)}."
        ),
    ]
    if benchmark_blockers:
        summary_lines.append("Benchmark blockers: " + ", ".join(benchmark_blockers[:8]))
    if live_posture_blockers:
        summary_lines.append("Live posture blockers: " + ", ".join(live_posture_blockers[:8]))
    summary_lines.append(
        "Outcome surfaces: "
        f"ARR={outcome_surfaces.get('arr_latest_active_arr_pct', 0):.2f}% "
        f"USD/day=${outcome_surfaces.get('expected_usd_per_day', 0):.2f} "
        f"source={outcome_surfaces.get('source', 'unknown')}."
    )
    return {
        "artifact": "btc5_dual_autoresearch_morning_report",
        "schema_version": 3,
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "benchmark_progress_only": True,
        "summary_lines": summary_lines,
        "current_champions": surface.get("current_champions") or {},
        "champion_deltas": champion_deltas,
        "champion_summaries": surface.get("lane_summaries") or {},
        "experiments_run": experiments_run,
        "kept_improvements": kept_improvements,
        "crashes": crashes,
        "promotions": promotions,
        "live_promotions": promotions,
        "null_result_lanes": null_result_lanes,
        "benchmark_blockers": benchmark_blockers,
        "live_posture_blockers": live_posture_blockers,
        "blockers": all_blockers,
        "blocker_count": len(all_blockers),
        "service_health": surface.get("service_health") or {},
        "runtime_safety": surface.get("runtime_safety") or {},
        "public_charts": surface.get("public_charts") or {},
        "audit_trail_paths": surface.get("audit_trail_paths") or {},
        "outcome_surfaces": outcome_surfaces,
    }


def _lane_closeout_summary(
    spec: LaneSpec,
    lane_snapshot: dict[str, Any],
    *,
    repo_root: Path,
    cutoff: datetime,
) -> dict[str, Any]:
    latest_path = _first_existing_path(repo_root, spec.latest_candidates)
    latest_payload = _read_json(latest_path) if latest_path is not None else {}
    champion_after = _subject_from_latest_payload(latest_payload) or _subject_from_source(
        dict(lane_snapshot.get("champion") or {})
    )
    event_rows, _ = _load_event_rows(repo_root, spec)
    event_items: list[dict[str, Any]] = []
    for row in event_rows:
        timestamp = _infer_event_timestamp(row)
        event_items.append(
            {
                "row": row,
                "timestamp": timestamp,
                "parsed_timestamp": _parse_timestamp(timestamp),
                "status": _infer_status(row),
            }
        )
    event_items.sort(key=lambda item: item["parsed_timestamp"] or datetime.min.replace(tzinfo=UTC))
    window_events = [
        item
        for item in event_items
        if item["parsed_timestamp"] is not None and item["parsed_timestamp"] >= cutoff
    ]
    keep_events = [item for item in window_events if item["status"] == "keep"]
    crash_events = [item for item in window_events if item["status"] == "crash"]
    prior_keep = next(
        (
            item
            for item in reversed(event_items)
            if item["status"] == "keep"
            and item["parsed_timestamp"] is not None
            and item["parsed_timestamp"] < cutoff
        ),
        None,
    )
    champion_before = _subject_from_source((prior_keep or {}).get("row"))
    if champion_before is None and keep_events:
        champion_before = _subject_from_incumbent_row(keep_events[-1]["row"])
    if champion_before is None and not keep_events and champion_after is not None:
        champion_before = dict(champion_after)
    if champion_after is None and keep_events:
        champion_after = _subject_from_source(keep_events[-1]["row"])
    delta_if_comparable = _loss_delta_if_comparable(champion_before, champion_after)
    improved = False
    if keep_events:
        if delta_if_comparable is not None:
            improved = delta_if_comparable < 0.0
        else:
            decision_reason = str(keep_events[-1]["row"].get("decision_reason") or "").strip().lower()
            improved = bool(
                (
                    decision_reason
                    and decision_reason != "baseline_frontier"
                )
                or _subject_from_incumbent_row(keep_events[-1]["row"]) is not None
                or champion_before is not None
            )
    changed = False
    if keep_events:
        if champion_before is not None and champion_after is not None:
            changed = not _subjects_equal(champion_before, champion_after)
        else:
            changed = improved
    if crash_events:
        outcome = "crash"
        outcome_note = "lane crashed during the overnight window"
    elif improved:
        outcome = "improved"
        outcome_note = "candidate beat the incumbent"
    elif window_events:
        outcome = "no_better_candidate"
        outcome_note = "no candidate beat the incumbent"
    else:
        outcome = "no_experiments"
        outcome_note = "no supervised experiment recorded in the overnight window"
    return {
        "lane": spec.key,
        "benchmark_label": lane_snapshot.get("benchmark_label"),
        "benchmark_progress_only": True,
        "champion_before": champion_before,
        "champion_after": champion_after,
        "changed": changed,
        "improved": improved,
        "outcome": outcome,
        "outcome_note": outcome_note,
        "delta_if_comparable": delta_if_comparable,
        "experiment_count": len(window_events),
        "keep_count": len(keep_events),
        "crash_count": len(crash_events),
        "fresh": str(lane_snapshot.get("latest_artifact_freshness") or "") == "fresh",
        "latest_artifact_path": lane_snapshot.get("latest_artifact_path"),
        "latest_artifact_freshness": lane_snapshot.get("latest_artifact_freshness"),
        "window_first_event_at": window_events[0]["timestamp"] if window_events else None,
        "window_last_event_at": window_events[-1]["timestamp"] if window_events else None,
    }


def build_overnight_closeout(
    surface: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
    window_hours: int = DEFAULT_OVERNIGHT_WINDOW_HOURS,
) -> dict[str, Any]:  # noqa: C901
    now = now or _utc_now()
    requested_cutoff = now - timedelta(hours=window_hours)
    burnin_marker = _load_burnin_start(repo_root)
    burnin_started_at = _parse_timestamp(burnin_marker.get("generated_at"))
    cutoff = requested_cutoff
    burnin_window_active = False
    if burnin_started_at is not None and burnin_started_at > cutoff:
        cutoff = burnin_started_at
        burnin_window_active = True
    lanes = {
        key: _lane_closeout_summary(
            spec,
            dict((surface.get("lanes") or {}).get(key) or {}),
            repo_root=repo_root,
            cutoff=cutoff,
        )
        for key, spec in LANE_SPECS.items()
    }
    audit_rows = _load_audit_rows(repo_root)
    audit_summary = _build_service_audit_window_summary(audit_rows, cutoff=cutoff)
    audit_window_rows = [item["row"] for item in audit_summary["window_rows"]]
    for lane_key, lane in lanes.items():
        failed_run_count = int((audit_summary["lane_failed_run_counts"] or {}).get(lane_key) or 0)
        lane["service_audit_run_count"] = int((audit_summary["lane_run_counts"] or {}).get(lane_key) or 0)
        lane["service_audit_failed_run_count"] = failed_run_count
        lane["service_audit_window_first_run_at"] = (audit_summary["lane_first_run_at"] or {}).get(lane_key)
        lane["service_audit_window_last_run_at"] = (audit_summary["lane_last_run_at"] or {}).get(lane_key)
        if failed_run_count > 0 and lane.get("outcome") != "crash":
            lane["outcome"] = "crash"
            lane["outcome_note"] = "lane runner failed during the overnight window"
    crashed_lanes = [
        key
        for key, lane in lanes.items()
        if int(lane.get("crash_count") or 0) > 0 or int(lane.get("service_audit_failed_run_count") or 0) > 0
    ]
    improved_lanes = [key for key, lane in lanes.items() if bool(lane.get("improved"))]
    null_result_lanes = [key for key, lane in lanes.items() if lane.get("outcome") == "no_better_candidate"]
    objective_span_seconds = _coerce_float(audit_summary.get("objective_span_seconds"))
    objective_span_hours = (
        round((objective_span_seconds or 0.0) / 3600.0, 4) if objective_span_seconds is not None else 0.0
    )
    overall_checks = {
        "market_fresh": bool((lanes.get("market") or {}).get("fresh")),
        "command_node_fresh": bool((lanes.get("command_node") or {}).get("fresh")),
        "service_audit_grew_during_window": bool(audit_window_rows),
        "service_audit_span_at_least_8h": bool(
            objective_span_seconds is not None
            and objective_span_seconds >= MIN_OVERNIGHT_AUDIT_SPAN_HOURS * 3600
        ),
        "market_runs_at_least_4": int((audit_summary["lane_run_counts"] or {}).get("market") or 0)
        >= MIN_OVERNIGHT_OBJECTIVE_RUNS,
        "command_node_runs_at_least_4": int((audit_summary["lane_run_counts"] or {}).get("command_node") or 0)
        >= MIN_OVERNIGHT_OBJECTIVE_RUNS,
        "no_lane_crashes": not crashed_lanes,
    }
    blockers: list[str] = []
    if not overall_checks["market_fresh"]:
        blockers.append("market_latest_artifact_not_fresh")
    if not overall_checks["command_node_fresh"]:
        blockers.append("command_node_latest_artifact_not_fresh")
    if not overall_checks["service_audit_grew_during_window"]:
        blockers.append("service_audit_did_not_grow_in_window")
    if not overall_checks["service_audit_span_at_least_8h"]:
        blockers.append(
            "service_audit_span_below_target:"
            f"{objective_span_hours:.4f}h/{MIN_OVERNIGHT_AUDIT_SPAN_HOURS}h"
        )
    market_run_count = int((audit_summary["lane_run_counts"] or {}).get("market") or 0)
    if not overall_checks["market_runs_at_least_4"]:
        blockers.append(
            f"market_run_count_below_target:{market_run_count}/{MIN_OVERNIGHT_OBJECTIVE_RUNS}"
        )
    command_node_run_count = int((audit_summary["lane_run_counts"] or {}).get("command_node") or 0)
    if not overall_checks["command_node_runs_at_least_4"]:
        blockers.append(
            "command_node_run_count_below_target:"
            f"{command_node_run_count}/{MIN_OVERNIGHT_OBJECTIVE_RUNS}"
        )
    if crashed_lanes:
        blockers.append("lane_crashes:" + ",".join(crashed_lanes))
    overall_status = "green" if all(overall_checks.values()) else "red"
    outcome_surfaces = _build_outcome_surfaces(repo_root)
    summary_lines = [
        "BTC5 overnight closeout.",
        "Benchmark progress only, not realized P&L.",
        "Green gates on market + command_node overnight supervision; policy is informational unless it crashes.",
        f"Overall overnight status: {overall_status}.",
        f"Service audit rows in window: {len(audit_window_rows)}.",
        (
            f"Objective-lane service-audit span: {objective_span_hours:.4f}h "
            f"(target >= {MIN_OVERNIGHT_AUDIT_SPAN_HOURS}h)."
        ),
        (
            "Service-audit run counts in window: "
            f"market={market_run_count}, "
            f"policy={int((audit_summary['lane_run_counts'] or {}).get('policy') or 0)}, "
            f"command_node={command_node_run_count}."
        ),
    ]
    if burnin_window_active and burnin_started_at is not None:
        summary_lines.append(
            "Burn-in window anchored to deployment marker at "
            f"{burnin_started_at.isoformat()}."
        )
    summary_lines.append(
        "Outcome surfaces: "
        f"ARR={outcome_surfaces.get('arr_latest_active_arr_pct', 0):.2f}% "
        f"USD/day=${outcome_surfaces.get('expected_usd_per_day', 0):.2f} "
        f"source={outcome_surfaces.get('source', 'unknown')}."
    )
    for lane_key in ("market", "policy", "command_node"):
        lane = dict(lanes.get(lane_key) or {})
        summary_lines.append(
            f"{lane_key}: {lane.get('outcome') or 'unknown'}; "
            f"before={_render_subject(lane.get('champion_before'))}; "
            f"after={_render_subject(lane.get('champion_after'))}; "
            f"experiments={int(lane.get('experiment_count') or 0)} "
            f"keeps={int(lane.get('keep_count') or 0)} "
            f"crashes={int(lane.get('crash_count') or 0)} "
            f"service_runs={int(lane.get('service_audit_run_count') or 0)} "
            f"service_failures={int(lane.get('service_audit_failed_run_count') or 0)} "
            f"fresh={bool(lane.get('fresh'))}."
        )
    if blockers:
        summary_lines.append("Blockers: " + ", ".join(blockers))
    return {
        "artifact": "btc5_dual_autoresearch_overnight_closeout",
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "window_started_at": cutoff.isoformat(),
        "requested_window_started_at": requested_cutoff.isoformat(),
        "burnin_started_at": burnin_started_at.isoformat() if burnin_started_at is not None else None,
        "burnin_window_active": burnin_window_active,
        "benchmark_progress_only": True,
        "overall_status": overall_status,
        "overall_checks": overall_checks,
        "blockers": blockers,
        "summary_lines": summary_lines,
        "lanes": lanes,
        "improved_lanes": improved_lanes,
        "null_result_lanes": null_result_lanes,
        "crashed_lanes": crashed_lanes,
        "outcome_surfaces": outcome_surfaces,
        "service_audit": {
            "path": str(SERVICE_AUDIT_RELATIVE),
            "burnin_marker_path": str(BURNIN_START_RELATIVE),
            "burnin_marker_reason": burnin_marker.get("reason"),
            "total_rows": len(audit_rows),
            "rows_in_window": len(audit_window_rows),
            "grew_during_window": bool(audit_window_rows),
            "window_first_event_at": audit_summary.get("window_first_event_at"),
            "window_last_event_at": audit_summary.get("window_last_event_at"),
            "span_basis_lanes": list(OVERNIGHT_OBJECTIVE_LANES),
            "minimum_required_span_hours": MIN_OVERNIGHT_AUDIT_SPAN_HOURS,
            "minimum_required_runs_per_lane": MIN_OVERNIGHT_OBJECTIVE_RUNS,
            "objective_window_first_run_at": audit_summary.get("objective_window_first_run_at"),
            "objective_window_last_run_at": audit_summary.get("objective_window_last_run_at"),
            "objective_span_seconds": round(objective_span_seconds, 4)
            if objective_span_seconds is not None
            else None,
            "objective_span_hours": objective_span_hours,
            "lane_run_counts": dict(audit_summary["lane_run_counts"] or {}),
            "lane_failed_run_counts": dict(audit_summary["lane_failed_run_counts"] or {}),
            "lane_first_run_at": dict(audit_summary["lane_first_run_at"] or {}),
            "lane_last_run_at": dict(audit_summary["lane_last_run_at"] or {}),
        },
    }


def _render_morning_markdown(packet: dict[str, Any]) -> str:
    experiments = dict(packet.get("experiments_run") or {})
    lines = [
        "# BTC5 Dual Autoresearch Morning Report",
        "",
        "Benchmark progress only. This report does not claim realized P&L.",
        "",
        "## Summary",
    ]
    for line in list(packet.get("summary_lines") or []):
        lines.append(f"- {line}")
    lines.extend(["", "## Benchmark Charts"])
    for chart_key in ("market_model", "command_node"):
        chart = dict((packet.get("public_charts") or {}).get(chart_key) or {})
        lines.append(
            f"- {chart_key}: {chart.get('path') or 'missing'}"
            f" (benchmark_progress_only={bool(chart.get('benchmark_progress_only', True))},"
            f" exists={bool(chart.get('exists'))})"
        )
    lines.extend(["", "## Outcome Charts (estimates, not benchmark loss)"])
    for chart_key in ("arr_outcome", "usd_per_day_outcome"):
        chart = dict((packet.get("public_charts") or {}).get(chart_key) or {})
        lines.append(
            f"- {chart_key}: {chart.get('path') or 'missing'}"
            f" (exists={bool(chart.get('exists'))})"
        )
    outcome = dict(packet.get("outcome_surfaces") or {})
    if outcome:
        lines.append(f"- Latest ARR: {outcome.get('arr_latest_active_arr_pct', 0):.2f}%")
        lines.append(f"- ARR frontier: {outcome.get('arr_frontier_active_arr_pct', 0):.2f}%")
        lines.append(f"- ARR latest action: {outcome.get('arr_latest_action') or 'n/a'}")
        lines.append(f"- Expected USD/day: ${outcome.get('expected_usd_per_day', 0):.2f}")
        lines.append(f"- Historical USD/day: ${outcome.get('historical_usd_per_day', 0):.2f}")
        lines.append(f"- Expected fills/day: {outcome.get('expected_fills_per_day', 0):.1f}")
        lines.append(f"- Edge status: current={outcome.get('edge_status_current', 'n/a')}, best={outcome.get('edge_status_best', 'n/a')}")
        lines.append(f"- Outcome source: {outcome.get('source', 'unknown')} @ {outcome.get('source_generated_at') or 'unknown'}")
    lines.extend(["", "## Champion Summaries"])
    champions = dict(packet.get("current_champions") or {})
    for lane_key in ("market", "policy", "command_node"):
        champion = dict(champions.get(lane_key) or {})
        loss = champion.get("loss")
        loss_text = "n/a" if loss is None else str(loss)
        model_name = champion.get("model_name") or ""
        name_part = f" model={model_name}" if model_name else ""
        lines.append(
            f"- {lane_key}: id={champion.get('id') or 'n/a'};{name_part} "
            f"loss={loss_text}; updated_at={champion.get('updated_at') or 'unknown'}"
        )
    # Champion deltas section.
    deltas = dict(packet.get("champion_deltas") or {})
    if deltas:
        lines.extend(["", "## Champion Deltas"])
        for lane_key in ("market", "policy", "command_node"):
            delta = dict(deltas.get(lane_key) or {})
            changed = delta.get("changed", False)
            delta_val = delta.get("delta_if_comparable")
            delta_text = f"delta={delta_val}" if delta_val is not None else "not comparable"
            prev = delta.get("previous_champion") or {}
            prev_id = prev.get("id") or "n/a"
            cur = delta.get("current_champion") or {}
            cur_id = cur.get("id") or "n/a"
            lines.append(
                f"- {lane_key}: changed={changed}; {prev_id} -> {cur_id}; {delta_text}"
            )
    lines.extend(["", "## Experiments Run"])
    lines.append(f"- total: {int(experiments.get('total') or 0)}")
    for lane_key, count in dict(experiments.get("by_lane") or {}).items():
        lines.append(f"- {lane_key}: {count}")
    for item in list(experiments.get("recent_samples") or [])[:10]:
        lines.append(
            f"- sample {item.get('lane')}: {item.get('status') or 'unknown'} "
            f"{item.get('label') or 'unknown'} at {item.get('timestamp') or 'unknown_time'}"
        )
    lines.extend(["", "## Kept Improvements"])
    kept = list(packet.get("kept_improvements") or [])
    if kept:
        for item in kept:
            lines.append(
                f"- {item.get('lane')}: {item.get('label')} at {item.get('timestamp') or 'unknown_time'}"
            )
    else:
        lines.append("- none in the report window")
    lines.extend(["", "## Promotions"])
    promotions = list(packet.get("promotions") or packet.get("live_promotions") or [])
    if promotions:
        for item in promotions:
            lines.append(
                f"- {item.get('lane')}: {item.get('label')} state={item.get('promotion_state') or 'unknown'}"
            )
    else:
        lines.append("- none in the report window")
    lines.extend(["", "## Crashes"])
    crashes = list(packet.get("crashes") or [])
    if crashes:
        for item in crashes:
            lines.append(
                f"- {item.get('lane')}: {item.get('label')} at {item.get('timestamp') or 'unknown_time'}"
            )
    else:
        lines.append("- none in the report window")
    lines.extend(["", "## Benchmark Blockers"])
    bench_blockers = list(packet.get("benchmark_blockers") or [])
    if bench_blockers:
        for blocker in bench_blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Live Posture Blockers"])
    live_blockers = list(packet.get("live_posture_blockers") or [])
    if live_blockers:
        for blocker in live_blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Audit Trail"])
    audit_trail = dict(packet.get("audit_trail_paths") or {})
    lines.append(f"- service_audit: {audit_trail.get('service_audit_jsonl') or 'missing'}")
    for lane_key, path in dict(audit_trail.get("lane_event_history") or {}).items():
        lines.append(f"- {lane_key}_events: {path}")
    return "\n".join(lines) + "\n"


def _render_overnight_closeout_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# BTC5 Overnight Closeout",
        "",
        "Benchmark progress only. This report does not claim realized P&L.",
        "",
        "## Summary",
    ]
    for line in list(packet.get("summary_lines") or []):
        lines.append(f"- {line}")
    lines.extend(["", "## Overall Checks"])
    for key, value in dict(packet.get("overall_checks") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Lane Closeout"])
    for lane_key in ("market", "policy", "command_node"):
        lane = dict((packet.get("lanes") or {}).get(lane_key) or {})
        lines.append(f"- {lane_key}: outcome={lane.get('outcome') or 'unknown'}")
        lines.append(f"- {lane_key}_before: {_render_subject(lane.get('champion_before'))}")
        lines.append(f"- {lane_key}_after: {_render_subject(lane.get('champion_after'))}")
        lines.append(
            f"- {lane_key}_counts: experiments={int(lane.get('experiment_count') or 0)} "
            f"keeps={int(lane.get('keep_count') or 0)} "
            f"crashes={int(lane.get('crash_count') or 0)} "
            f"fresh={bool(lane.get('fresh'))}"
        )
        lines.append(f"- {lane_key}_note: {lane.get('outcome_note') or 'n/a'}")
    outcome = dict(packet.get("outcome_surfaces") or {})
    if outcome:
        lines.extend(["", "## Outcome Surfaces (estimates, not benchmark loss)"])
        lines.append(f"- Latest ARR: {outcome.get('arr_latest_active_arr_pct', 0):.2f}%")
        lines.append(f"- ARR frontier: {outcome.get('arr_frontier_active_arr_pct', 0):.2f}%")
        lines.append(f"- ARR latest action: {outcome.get('arr_latest_action') or 'n/a'}")
        lines.append(f"- Expected USD/day: ${outcome.get('expected_usd_per_day', 0):.2f}")
        lines.append(f"- Historical USD/day: ${outcome.get('historical_usd_per_day', 0):.2f}")
        lines.append(f"- Expected fills/day: {outcome.get('expected_fills_per_day', 0):.1f}")
        lines.append(f"- Expected PnL 30d: ${outcome.get('expected_pnl_30d_usd', 0):.2f}")
        lines.append(f"- Edge status: current={outcome.get('edge_status_current', 'n/a')}, best={outcome.get('edge_status_best', 'n/a')}")
        lines.append(f"- Outcome source: {outcome.get('source', 'unknown')} @ {outcome.get('source_generated_at') or 'unknown'}")
        lines.append(f"- ARR chart: {outcome.get('arr_svg_path', 'missing')} (exists={outcome.get('arr_svg_exists', False)})")
        lines.append(f"- USD/day chart: {outcome.get('usd_per_day_svg_path', 'missing')} (exists={outcome.get('usd_per_day_svg_exists', False)})")
    service_audit = dict(packet.get("service_audit") or {})
    lines.extend(["", "## Service Audit"])
    lines.append(f"- path: {service_audit.get('path') or 'missing'}")
    lines.append(f"- burnin_marker_path: {service_audit.get('burnin_marker_path') or 'missing'}")
    lines.append(f"- burnin_marker_reason: {service_audit.get('burnin_marker_reason') or 'n/a'}")
    lines.append(f"- rows_in_window: {int(service_audit.get('rows_in_window') or 0)}")
    lines.append(f"- grew_during_window: {bool(service_audit.get('grew_during_window'))}")
    lines.append(f"- objective_span_hours: {service_audit.get('objective_span_hours')}")
    lines.append(
        "- lane_run_counts: "
        f"market={int((service_audit.get('lane_run_counts') or {}).get('market') or 0)} "
        f"policy={int((service_audit.get('lane_run_counts') or {}).get('policy') or 0)} "
        f"command_node={int((service_audit.get('lane_run_counts') or {}).get('command_node') or 0)}"
    )
    lines.append(
        "- lane_failed_run_counts: "
        f"market={int((service_audit.get('lane_failed_run_counts') or {}).get('market') or 0)} "
        f"policy={int((service_audit.get('lane_failed_run_counts') or {}).get('policy') or 0)} "
        f"command_node={int((service_audit.get('lane_failed_run_counts') or {}).get('command_node') or 0)}"
    )
    return "\n".join(lines) + "\n"


def write_morning_packet(
    surface: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
    window_hours: int = 24,
) -> dict[str, Any]:
    state = _load_state(repo_root)
    previous_champions = dict(state.get("previous_champions") or {})
    packet = build_morning_packet(
        surface,
        now=now,
        window_hours=window_hours,
        previous_champions=previous_champions,
        repo_root=repo_root,
    )
    _write_json(_resolve(repo_root, MORNING_JSON_RELATIVE), packet)
    md_path = _resolve(repo_root, MORNING_MD_RELATIVE)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_morning_markdown(packet), encoding="utf-8")
    # Persist current champions as next run's previous for delta tracking.
    state["previous_champions"] = dict(surface.get("current_champions") or {})
    _save_state(repo_root, state)
    return packet


def write_overnight_closeout(
    surface: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
    window_hours: int = DEFAULT_OVERNIGHT_WINDOW_HOURS,
) -> dict[str, Any]:
    packet = build_overnight_closeout(surface, repo_root=repo_root, now=now, window_hours=window_hours)
    _write_json(_resolve(repo_root, OVERNIGHT_CLOSEOUT_JSON_RELATIVE), packet)
    md_path = _resolve(repo_root, OVERNIGHT_CLOSEOUT_MD_RELATIVE)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_overnight_closeout_markdown(packet), encoding="utf-8")
    return packet


def write_instance_output(
    surface: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    morning_packet: dict[str, Any] | None = None,
    overnight_closeout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "artifact": "instance05_dual_autoresearch_ops",
        "schema_version": 1,
        "generated_at": surface.get("generated_at"),
        "summary": surface.get("summary"),
        "services": [
            {
                "lane": spec.key,
                "service_name": spec.service_name,
                "timer_name": spec.timer_name,
                "cadence_seconds": spec.cadence_seconds,
                "timeout_seconds": spec.timeout_seconds,
                "daily_runtime_budget_seconds": spec.daily_runtime_budget_seconds,
            }
            for spec in LANE_SPECS.values()
        ],
        "surface_artifacts": {
            "surface_json": str(SURFACE_RELATIVE),
            "morning_json": str(MORNING_JSON_RELATIVE),
            "morning_markdown": str(MORNING_MD_RELATIVE),
            "overnight_closeout_json": str(OVERNIGHT_CLOSEOUT_JSON_RELATIVE),
            "overnight_closeout_markdown": str(OVERNIGHT_CLOSEOUT_MD_RELATIVE),
            "service_audit_jsonl": str(SERVICE_AUDIT_RELATIVE),
            "outcomes_json": str(OUTCOME_LATEST_RELATIVE),
            "arr_chart_svg": str(ARR_SVG_RELATIVE),
            "usd_per_day_chart_svg": str(USD_PER_DAY_SVG_RELATIVE),
        },
        "current_champions": surface.get("current_champions") or {},
        "lane_summaries": surface.get("lane_summaries") or {},
        "service_health": surface.get("service_health") or {},
        "runtime_safety": surface.get("runtime_safety") or {},
        "public_charts": surface.get("public_charts") or {},
        "audit_trail_paths": surface.get("audit_trail_paths") or {},
        "morning_summary": (morning_packet or {}).get("summary_lines"),
        "overnight_closeout_summary": (overnight_closeout or {}).get("summary_lines"),
    }
    _write_json(_resolve(repo_root, INSTANCE_OUTPUT_RELATIVE), payload)
    return payload


def _stdout_tail(result: subprocess.CompletedProcess[str] | None, *, stderr: bool = False) -> str:
    if result is None:
        return ""
    value = result.stderr if stderr else result.stdout
    return (value or "").strip()[-1000:]


def run_lane(
    spec: LaneSpec,
    *,
    repo_root: Path = REPO_ROOT,
    override_command: str | None = None,
    write_morning_report: bool = False,
    now: datetime | None = None,
) -> tuple[int, dict[str, Any]]:
    now = now or _utc_now()
    state = _load_state(repo_root)
    state.setdefault("lanes", {})
    lane_state = dict(state["lanes"].get(spec.key) or {})
    audit_rows = _load_audit_rows(repo_root)
    budget_used_seconds = _runtime_budget_used_seconds(lane_key=spec.key, audit_rows=audit_rows, now=now)
    command = _resolve_command(repo_root, spec, override_command=override_command)

    if command is None:
        lane_state = update_lane_state_after_run(
            lane_state,
            success=False,
            now=now,
            spec=spec,
            status_label="blocked_missing_runner",
        )
        state["lanes"][spec.key] = lane_state
        _save_state(repo_root, state)
        audit_record = {
            "generated_at": now.isoformat(),
            "lane": spec.key,
            "event_type": "blocked",
            "status": "blocked_missing_runner",
            "command": None,
            "duration_seconds": 0.0,
        }
        _append_jsonl(_resolve(repo_root, SERVICE_AUDIT_RELATIVE), audit_record)
        surface = write_surface_snapshot(repo_root=repo_root, state=state, now=now)
        morning_packet = write_morning_packet(surface, repo_root=repo_root, now=now) if write_morning_report else None
        closeout_packet = write_overnight_closeout(surface, repo_root=repo_root, now=now) if write_morning_report else None
        write_instance_output(
            surface,
            repo_root=repo_root,
            morning_packet=morning_packet,
            overnight_closeout=closeout_packet,
        )
        return 0, audit_record

    backoff_until = _parse_timestamp(lane_state.get("backoff_until"))
    if backoff_until is not None and backoff_until > now:
        audit_record = {
            "generated_at": now.isoformat(),
            "lane": spec.key,
            "event_type": "backoff_skip",
            "status": "backoff_skip",
            "command": command,
            "duration_seconds": 0.0,
            "backoff_until": backoff_until.isoformat(),
        }
        _append_jsonl(_resolve(repo_root, SERVICE_AUDIT_RELATIVE), audit_record)
        surface = write_surface_snapshot(repo_root=repo_root, state=state, now=now)
        morning_packet = write_morning_packet(surface, repo_root=repo_root, now=now) if write_morning_report else None
        closeout_packet = write_overnight_closeout(surface, repo_root=repo_root, now=now) if write_morning_report else None
        write_instance_output(
            surface,
            repo_root=repo_root,
            morning_packet=morning_packet,
            overnight_closeout=closeout_packet,
        )
        return 0, audit_record

    if budget_used_seconds >= spec.daily_runtime_budget_seconds:
        audit_record = {
            "generated_at": now.isoformat(),
            "lane": spec.key,
            "event_type": "budget_skip",
            "status": "budget_skip",
            "command": command,
            "duration_seconds": 0.0,
            "daily_runtime_budget_seconds": spec.daily_runtime_budget_seconds,
            "daily_runtime_used_seconds": budget_used_seconds,
        }
        _append_jsonl(_resolve(repo_root, SERVICE_AUDIT_RELATIVE), audit_record)
        surface = write_surface_snapshot(repo_root=repo_root, state=state, now=now)
        morning_packet = write_morning_packet(surface, repo_root=repo_root, now=now) if write_morning_report else None
        closeout_packet = write_overnight_closeout(surface, repo_root=repo_root, now=now) if write_morning_report else None
        write_instance_output(
            surface,
            repo_root=repo_root,
            morning_packet=morning_packet,
            overnight_closeout=closeout_packet,
        )
        return 0, audit_record

    started_at = _utc_now()
    result: subprocess.CompletedProcess[str] | None = None
    timed_out = False
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=spec.timeout_seconds,
        )
        success = result.returncode == 0
        status_label = "ok" if success else "runner_failed"
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        success = False
        status_label = "timeout"
        result = subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )
    finished_at = _utc_now()
    duration_seconds = max(0.0, (finished_at - started_at).total_seconds())
    lane_state = update_lane_state_after_run(
        lane_state,
        success=success,
        now=finished_at,
        spec=spec,
        status_label=status_label,
    )
    state["lanes"][spec.key] = lane_state
    _save_state(repo_root, state)
    surface = write_surface_snapshot(repo_root=repo_root, state=state, now=finished_at)
    lane_snapshot = dict((surface.get("lanes") or {}).get(spec.key) or {})
    promotion_events = [
        event
        for event in list(lane_snapshot.get("recent_events") or [])
        if str(event.get("promotion_state") or "").strip().lower() in PROMOTION_STATES
    ]
    audit_record = {
        "generated_at": finished_at.isoformat(),
        "lane": spec.key,
        "event_type": "run",
        "status": status_label,
        "command": command,
        "returncode": None if result is None else result.returncode,
        "duration_seconds": round(duration_seconds, 4),
        "stdout_tail": _stdout_tail(result),
        "stderr_tail": _stdout_tail(result, stderr=True),
        "consecutive_failures": int(lane_state.get("consecutive_failures") or 0),
        "backoff_until": lane_state.get("backoff_until"),
        "latest_artifact_path": lane_snapshot.get("latest_artifact_path"),
        "latest_artifact_freshness": lane_snapshot.get("latest_artifact_freshness"),
        "promotion_events": promotion_events[-3:],
        "timed_out": timed_out,
    }
    _append_jsonl(_resolve(repo_root, SERVICE_AUDIT_RELATIVE), audit_record)
    append_outcome_record(repo_root, now=finished_at)
    surface = write_surface_snapshot(repo_root=repo_root, state=state, now=finished_at)
    morning_packet = write_morning_packet(surface, repo_root=repo_root, now=finished_at) if write_morning_report else None
    closeout_packet = (
        write_overnight_closeout(surface, repo_root=repo_root, now=finished_at) if write_morning_report else None
    )
    write_instance_output(
        surface,
        repo_root=repo_root,
        morning_packet=morning_packet,
        overnight_closeout=closeout_packet,
    )
    return (0 if success else 1), audit_record


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_lane_parser = subparsers.add_parser("run-lane", help="Run one supervised lane cycle")
    run_lane_parser.add_argument("--lane", choices=sorted(LANE_SPECS), required=True)
    run_lane_parser.add_argument("--command-override", default="", help="Optional shell-style command override")
    run_lane_parser.add_argument("--write-morning-report", action="store_true")

    refresh_parser = subparsers.add_parser("refresh", help="Refresh dual-autoresearch surfaces")
    refresh_parser.add_argument("--write-morning-report", action="store_true")

    morning_parser = subparsers.add_parser("morning-report", help="Write the morning report now")
    morning_parser.add_argument("--window-hours", type=int, default=24)

    closeout_parser = subparsers.add_parser("overnight-closeout", help="Write the overnight closeout now")
    closeout_parser.add_argument("--window-hours", type=int, default=DEFAULT_OVERNIGHT_WINDOW_HOURS)

    burnin_parser = subparsers.add_parser("mark-burnin-start", help="Reset the overnight burn-in window anchor")
    burnin_parser.add_argument("--reason", default="manual", help="Reason recorded with the burn-in marker")

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "run-lane":
        code, payload = run_lane(
            LANE_SPECS[str(args.lane)],
            override_command=str(args.command_override or "").strip() or None,
            write_morning_report=bool(args.write_morning_report),
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return code
    if args.command == "refresh":
        surface = write_surface_snapshot()
        morning_packet = write_morning_packet(surface) if args.write_morning_report else None
        closeout_packet = write_overnight_closeout(surface) if args.write_morning_report else None
        output = write_instance_output(
            surface,
            morning_packet=morning_packet,
            overnight_closeout=closeout_packet,
        )
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    if args.command == "overnight-closeout":
        surface = write_surface_snapshot()
        packet = write_overnight_closeout(surface, window_hours=int(args.window_hours))
        output = write_instance_output(surface, overnight_closeout=packet)
        print(json.dumps({"overnight_closeout": packet, "instance_output": output}, indent=2, sort_keys=True))
        return 0
    if args.command == "mark-burnin-start":
        marker = write_burnin_start_marker(reason=str(args.reason or "manual"))
        surface = write_surface_snapshot()
        closeout_packet = write_overnight_closeout(surface)
        output = write_instance_output(surface, overnight_closeout=closeout_packet)
        print(json.dumps({"burnin_start": marker, "overnight_closeout": closeout_packet, "instance_output": output}, indent=2, sort_keys=True))
        return 0
    surface = write_surface_snapshot()
    packet = write_morning_packet(surface, window_hours=int(args.window_hours))
    closeout_packet = write_overnight_closeout(surface)
    output = write_instance_output(surface, morning_packet=packet, overnight_closeout=closeout_packet)
    print(
        json.dumps(
            {"morning_report": packet, "overnight_closeout": closeout_packet, "instance_output": output},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
