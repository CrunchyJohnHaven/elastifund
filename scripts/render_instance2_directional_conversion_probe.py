#!/usr/bin/env python3
"""Render the Instance 2 BTC5 directional conversion probe artifact."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.btc5_monte_carlo_core import fetch_remote_rows


UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_RUNTIME_TRUTH = REPO_ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_RUNTIME_ARCHIVE_DIR = REPO_ROOT / "reports" / "runtime" / "runtime_truth"
DEFAULT_ENV_PATH = REPO_ROOT / "state" / "btc5_autoresearch.env"
DEFAULT_HISTORICAL_ROWS = REPO_ROOT / "reports" / "tmp_remote_btc5_window_rows.json"
LEGACY_HISTORICAL_ROWS = REPO_ROOT / "reports" / "runtime" / "tmp" / "tmp_remote_btc5_window_rows.json"
DEFAULT_BASELINE_ARTIFACT = REPO_ROOT / "reports" / "btc5_rollout_latest.json"
LEGACY_BASELINE_ARTIFACT = REPO_ROOT / "reports" / "instance2_btc5_baseline" / "latest.json"
DEFAULT_POLICY_LATEST = REPO_ROOT / "reports" / "autoresearch" / "btc5_policy" / "latest.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "reports" / "parallel" / "instance02_directional_conversion_probe.json"
MATCHED_WINDOW_SAMPLE_SIZE = 60
BASELINE_DELTA_CAP = 0.00075

_LIVE_DECISION_SET = [
    "keep_0.00075",
    "swap_after_same_stream_shadow_win",
    "hold_and_wait_for_better_book_conditions",
]


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _write_json_list(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered


def _safe_slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip()).strip("_")


def _select_freshest_existing_path(*paths: Path) -> Path:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return paths[0]
    return max(existing, key=lambda path: path.stat().st_mtime)


def _load_env_file(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    values: dict[str, str] = {}
    metadata: dict[str, str] = {}
    if not path.exists():
        return values, metadata
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comment = line[1:].strip()
            if "=" in comment:
                key, value = comment.split("=", 1)
                metadata[key.strip()] = value.strip()
            continue
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values, metadata


def _snapshot_generated_at(path: Path, payload: dict[str, Any]) -> datetime | None:
    candidates = (
        payload.get("generated_at"),
        payload.get("checked_at"),
        payload.get("timestamp"),
        payload.get("updated_at"),
    )
    for candidate in candidates:
        parsed = _parse_dt(candidate)
        if parsed is not None:
            return parsed
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def _load_runtime_archive_snapshots(directory: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    if not directory.exists():
        return snapshots
    for path in sorted(directory.glob("runtime_truth_*.json")):
        if path.name == "runtime_truth_latest.json":
            continue
        payload = _read_json_dict(path)
        snapshots.append(
            {
                "path": path,
                "payload": payload,
                "generated_at": _snapshot_generated_at(path, payload),
            }
        )
    return snapshots


def _extract_latest_trade(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        return None
    maker = payload.get("btc_5min_maker")
    if not isinstance(maker, dict):
        return None
    latest_trade = maker.get("latest_trade")
    if not isinstance(latest_trade, dict):
        return None
    window_start_ts = latest_trade.get("window_start_ts")
    order_status = latest_trade.get("order_status")
    slug = latest_trade.get("slug")
    if window_start_ts is None or not order_status or not slug:
        return None
    generated_at = snapshot.get("generated_at")
    return {
        "file": _repo_rel(snapshot["path"]),
        "generated_at": _iso(generated_at),
        "checked_at": maker.get("checked_at"),
        "window_start_ts": int(window_start_ts),
        "slug": str(slug),
        "direction": latest_trade.get("direction"),
        "order_status": str(order_status),
        "created_at": latest_trade.get("created_at"),
        "updated_at": latest_trade.get("updated_at"),
        "source": maker.get("source"),
    }


def _record_sort_key(record: dict[str, Any]) -> tuple[datetime, datetime, str]:
    generated_at = _parse_dt(record.get("generated_at")) or datetime.min.replace(tzinfo=UTC)
    updated_at = _parse_dt(record.get("updated_at")) or datetime.min.replace(tzinfo=UTC)
    return (generated_at, updated_at, str(record.get("file") or ""))


def _collect_unique_runtime_windows(snapshots: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_records: list[dict[str, Any]] = []
    for snapshot in snapshots:
        record = _extract_latest_trade(snapshot)
        if record is not None:
            all_records.append(record)
    deduped: dict[int, dict[str, Any]] = {}
    for record in all_records:
        key = int(record["window_start_ts"])
        current = deduped.get(key)
        if current is None or _record_sort_key(record) >= _record_sort_key(current):
            deduped[key] = record
    unique_windows = sorted(deduped.values(), key=lambda item: int(item["window_start_ts"]))
    return all_records, unique_windows


def _is_skip_status(status: str) -> bool:
    return status.startswith("skip_")


def _has_conversion_event(status: str) -> bool:
    lowered = status.lower()
    return any(token in lowered for token in ("submit", "rest", "cancel", "fill"))


def _classify_lifecycle_counts(statuses: list[str]) -> dict[str, int]:
    lowered = [status.lower() for status in statuses]
    return {
        "submit_like_count": sum("submit" in status for status in lowered),
        "rest_like_count": sum("rest" in status for status in lowered),
        "cancel_like_count": sum("cancel" in status for status in lowered),
        "fill_like_count": sum("fill" in status for status in lowered),
    }


def _build_live_window_observation(unique_windows: list[dict[str, Any]]) -> dict[str, Any]:
    latest_windows = unique_windows[-12:]
    statuses = [str(window.get("order_status") or "") for window in latest_windows]
    status_counts = dict(Counter(statuses))
    last_window = latest_windows[-1] if latest_windows else {}
    last_window_day = str((last_window.get("updated_at") or last_window.get("created_at") or ""))[:10]
    day_statuses = [
        str(window.get("order_status") or "")
        for window in unique_windows
        if str((window.get("updated_at") or window.get("created_at") or ""))[:10] == last_window_day
    ]
    first_window = latest_windows[0] if latest_windows else {}
    lifecycle_counts = _classify_lifecycle_counts(statuses)
    return {
        "source": _repo_rel(DEFAULT_RUNTIME_ARCHIVE_DIR),
        "window_count": len(latest_windows),
        "window_range": {
            "first_window_start_ts": first_window.get("window_start_ts"),
            "first_updated_at": first_window.get("updated_at"),
            "last_window_start_ts": last_window.get("window_start_ts"),
            "last_updated_at": last_window.get("updated_at"),
        },
        "status_counts": status_counts,
        "lifecycle_event_counts": lifecycle_counts,
        "eligible_window_count": sum(not _is_skip_status(status) for status in statuses),
        "submit_rest_cancel_fill_observed": any(_has_conversion_event(status) for status in statuses),
        "windows": latest_windows,
        "day_context_counts": dict(Counter(day_statuses)),
    }


def _build_runtime_gap(
    *,
    runtime_truth: dict[str, Any],
    snapshots: list[dict[str, Any]],
    unique_windows: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime = runtime_truth.get("runtime") if isinstance(runtime_truth.get("runtime"), dict) else {}
    latest_runtime_generated_at = _parse_dt(runtime_truth.get("generated_at"))
    latest_trade_record = unique_windows[-1] if unique_windows else {}
    latest_trade_generated_at = _parse_dt(latest_trade_record.get("generated_at"))
    latest_trade_updated_at = _parse_dt(latest_trade_record.get("updated_at"))
    boundary_dt = latest_trade_generated_at or latest_trade_updated_at
    later_snapshots_without_trade = 0
    for snapshot in snapshots:
        snapshot_generated_at = snapshot.get("generated_at")
        if boundary_dt is None or snapshot_generated_at is None or snapshot_generated_at <= boundary_dt:
            continue
        if _extract_latest_trade(snapshot) is None:
            later_snapshots_without_trade += 1
    gap_minutes = None
    if latest_runtime_generated_at is not None and (latest_trade_updated_at or latest_trade_generated_at) is not None:
        gap_dt = latest_trade_updated_at or latest_trade_generated_at
        gap_minutes = round(max(0.0, (latest_runtime_generated_at - gap_dt).total_seconds() / 60.0), 1)
    service_state = runtime_truth.get("service_state")
    latest_order_status = runtime.get("btc5_latest_order_status")
    gap_detected = latest_order_status is None and later_snapshots_without_trade > 0
    return {
        "source": _repo_rel(DEFAULT_RUNTIME_TRUTH),
        "runtime_truth_generated_at": runtime_truth.get("generated_at"),
        "service_state": service_state,
        "service_consistency": runtime_truth.get("service_consistency"),
        "allow_order_submission": runtime_truth.get("allow_order_submission"),
        "finance_gate_pass": runtime_truth.get("finance_gate_pass"),
        "btc5_latest_order_status": latest_order_status,
        "btc5_latest_window_start_ts": runtime.get("btc5_latest_window_start_ts"),
        "later_snapshots_without_trade_count": later_snapshots_without_trade,
        "latest_trade_snapshot_generated_at": latest_trade_record.get("generated_at"),
        "latest_trade_snapshot_updated_at": latest_trade_record.get("updated_at"),
        "minutes_since_last_trade_snapshot": gap_minutes,
        "gap_detected": gap_detected,
        "gap_reason": (
            "service_reports_running_but_latest_trade_is_empty_in_newer_runtime_truth_snapshots"
            if gap_detected
            else None
        ),
    }


def _build_historical_order_path_proof(
    rows: list[dict[str, Any]],
    live_window_observation: dict[str, Any],
) -> dict[str, Any]:
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            _parse_dt(row.get("updated_at")) or datetime.min.replace(tzinfo=UTC),
            int(row.get("window_start_ts") or 0),
        ),
    )
    last12 = ordered_rows[-12:]
    last200 = ordered_rows[-200:]
    latest_available_updated_at = last12[-1].get("updated_at") if last12 else None
    last_live_window_dt = _parse_dt(live_window_observation.get("window_range", {}).get("last_updated_at"))
    historical_updated_dt = _parse_dt(latest_available_updated_at)
    fresh_for_current_cycle = False
    if historical_updated_dt is not None and last_live_window_dt is not None:
        fresh_for_current_cycle = historical_updated_dt >= last_live_window_dt
    last12_statuses = [str(row.get("order_status") or "") for row in last12]
    last200_statuses = [str(row.get("order_status") or "") for row in last200]
    contains_live_fill = any("live_filled" == status for status in last200_statuses)
    contains_live_cancelled_unfilled = any("live_cancelled_unfilled" == status for status in last200_statuses)
    return {
        "source": _repo_rel(DEFAULT_HISTORICAL_ROWS),
        "fresh_for_current_cycle": fresh_for_current_cycle,
        "latest_available_updated_at": latest_available_updated_at,
        "stale_but_real_path_exists": contains_live_fill or contains_live_cancelled_unfilled,
        "last12_status_counts": dict(Counter(last12_statuses)),
        "last200_status_counts": dict(Counter(last200_statuses)),
        "contains_live_fill": contains_live_fill,
        "contains_live_cancelled_unfilled": contains_live_cancelled_unfilled,
        "note": (
            "Historical BTC5 submit/fill/cancel evidence exists, but the latest durable remote window rows "
            "are older than the March 12 live-window sample and cannot substitute for fresh matched-window conversion proof."
        ),
    }


def _healthy_runtime_only(runtime_truth: dict[str, Any]) -> bool:
    service_state = str(runtime_truth.get("service_state") or "").strip().lower()
    service_consistency = str(runtime_truth.get("service_consistency") or "").strip().lower()
    return (
        bool(runtime_truth.get("allow_order_submission"))
        and bool(runtime_truth.get("finance_gate_pass", True))
        and service_state in {"running", "live"}
        and service_consistency in {"consistent", "ok", "healthy"}
    )


def _sort_rows_by_update(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _parse_dt(row.get("updated_at")) or datetime.min.replace(tzinfo=UTC),
            int(row.get("window_start_ts") or 0),
        ),
    )


def _build_matched_window_comparator(
    *,
    historical_rows: list[dict[str, Any]],
    historical_rows_path: Path,
    runtime_truth: dict[str, Any],
    live_window_observation: dict[str, Any],
    shadow_policy_id: str,
    shadow_delta_cap: float,
) -> dict[str, Any]:
    ordered_rows = _sort_rows_by_update(historical_rows)
    sample = ordered_rows[-MATCHED_WINDOW_SAMPLE_SIZE:]
    healthy_runtime_only = _healthy_runtime_only(runtime_truth)
    sample_last_updated_at = sample[-1].get("updated_at") if sample else None
    probe_reference_dt = (
        _parse_dt(live_window_observation.get("window_range", {}).get("last_updated_at"))
        or _parse_dt(runtime_truth.get("generated_at"))
    )
    sample_last_updated_dt = _parse_dt(sample_last_updated_at)
    fresh_for_current_cycle = bool(
        sample_last_updated_dt is not None
        and probe_reference_dt is not None
        and sample_last_updated_dt.date() == probe_reference_dt.date()
        and abs((probe_reference_dt - sample_last_updated_dt).total_seconds()) <= (8 * 3600)
    )
    sample_ready = healthy_runtime_only and fresh_for_current_cycle and len(sample) >= 12
    first_updated_at = sample[0].get("updated_at") if sample else None
    last_updated_at = sample_last_updated_at
    sample_status_counts = dict(Counter(str(row.get("order_status") or "") for row in sample))
    baseline_eligible = [
        row for row in sample if float(row.get("abs_delta") or 0.0) <= BASELINE_DELTA_CAP
    ]
    shadow_eligible = [
        row for row in sample if float(row.get("abs_delta") or 0.0) <= shadow_delta_cap
    ]
    shadow_is_tighter = shadow_delta_cap <= BASELINE_DELTA_CAP
    if shadow_is_tighter:
        transition_rows = [
            row
            for row in sample
            if shadow_delta_cap < float(row.get("abs_delta") or 0.0) <= BASELINE_DELTA_CAP
        ]
    else:
        transition_rows = [
            row
            for row in sample
            if BASELINE_DELTA_CAP < float(row.get("abs_delta") or 0.0) <= shadow_delta_cap
        ]
    transition_status_counts = dict(Counter(str(row.get("order_status") or "") for row in transition_rows))
    return {
        "source": _repo_rel(historical_rows_path),
        "status": "eligibility_only_same_stream" if sample_ready else "not_ready",
        "healthy_runtime_only": healthy_runtime_only,
        "fresh_for_current_cycle": fresh_for_current_cycle,
        "sample_window_count": len(sample),
        "sample_window_target": MATCHED_WINDOW_SAMPLE_SIZE,
        "sample_updated_at_range": {
            "first_updated_at": first_updated_at,
            "last_updated_at": last_updated_at,
        },
        "baseline_profile": "active_profile_probe_d0_00075",
        "shadow_profile": shadow_policy_id,
        "baseline_delta_cap": BASELINE_DELTA_CAP,
        "shadow_delta_cap": shadow_delta_cap,
        "same_window_comparison_ready": sample_ready,
        "measured_shadow_execution_delta_ready": False,
        "baseline_eligible_window_count": len(baseline_eligible),
        "shadow_eligible_window_count": len(shadow_eligible),
        "incremental_shadow_eligible_window_count": 0 if shadow_is_tighter else len(transition_rows),
        "shadow_restricted_window_count": len(transition_rows) if shadow_is_tighter else 0,
        "sample_status_counts": sample_status_counts,
        "incremental_shadow_status_counts": transition_status_counts if not shadow_is_tighter else {},
        "shadow_restricted_status_counts": transition_status_counts if shadow_is_tighter else {},
        "decision": (
            (
                "Fresh same-window March 12 coverage exists, but it is still an eligibility-only comparator. "
                f"Keep d0_00075 live until `{shadow_policy_id}` proves itself on the same stream."
            )
            if sample_ready and shadow_is_tighter
            else (
                "Fresh same-window March 12 coverage exists, but it is still an eligibility-only comparator. "
                f"Keep d0_00075 live until `{shadow_policy_id}` has same-stream shadow execution telemetry."
            )
            if sample_ready
            else "Same-window comparator is not ready yet."
        ),
    }


def _build_shadow_only_comparator(
    *,
    live_window_observation: dict[str, Any],
    runtime_gap: dict[str, Any],
    matched_window_comparator: dict[str, Any],
) -> dict[str, Any]:
    requested_profile = str(matched_window_comparator.get("shadow_profile") or "active_profile")
    requested_profile_short = requested_profile
    shadow_delta_cap = float(matched_window_comparator.get("shadow_delta_cap") or 0.00015)
    shadow_is_tighter = shadow_delta_cap <= BASELINE_DELTA_CAP
    if matched_window_comparator.get("same_window_comparison_ready"):
        restricted = int(matched_window_comparator.get("shadow_restricted_window_count") or 0)
        unlocked = int(matched_window_comparator.get("incremental_shadow_eligible_window_count") or 0)
        baseline_count = int(matched_window_comparator.get("baseline_eligible_window_count") or 0)
        shadow_count = int(matched_window_comparator.get("shadow_eligible_window_count") or 0)
        return {
            "requested_profile": requested_profile,
            "requested_profile_short": requested_profile_short,
            "status": "eligibility_only_same_stream",
            "matched_window_capture_ready": True,
            "measured_shadow_execution_delta_ready": False,
            "reason": (
                "fresh_same_stream_windows_available_but_shadow_execution_delta_not_measured"
            ),
            "precomputed_eligibility_benchmark": {
                "baseline_eligible_window_count": matched_window_comparator.get("baseline_eligible_window_count"),
                "shadow_eligible_window_count": matched_window_comparator.get("shadow_eligible_window_count"),
                "incremental_shadow_eligible_window_count": unlocked,
                "shadow_restricted_window_count": restricted,
            },
            "decision": (
                (
                    f"Do not swap live yet. The fresh same-stream comparator shows `{requested_profile}` would tighten "
                    f"the eligible window set from {baseline_count} to {shadow_count}, leaving {restricted} baseline "
                    "windows parked, but there is still no same-stream execution or fill delta."
                )
                if shadow_is_tighter
                else
                f"Do not widen live yet. The fresh same-stream comparator shows {unlocked} additional windows "
                f"would become eligible at `{requested_profile}`, but there is still no same-stream execution or fill delta."
            ),
        }
    zero_conversion = not live_window_observation.get("submit_rest_cancel_fill_observed", False)
    reason_parts = []
    if zero_conversion:
        reason_parts.append("fresh_live_sample_is_zero_conversion")
    if runtime_gap.get("gap_detected"):
        reason_parts.append("runtime_truth_latest_has_no_new_btc5_trade_payload")
    reason_parts.append(f"no_same_stream_{_safe_slug(requested_profile)}_shadow_capture_artifact")
    return {
        "requested_profile": requested_profile,
        "requested_profile_short": requested_profile_short,
        "status": "not_captured_on_same_stream",
        "matched_window_capture_ready": False,
        "reason": ",".join(reason_parts),
        "precomputed_eligibility_benchmark": {},
        "decision": (
            f"Do not swap live. Keep d0_00075 unchanged until a same-stream `{requested_profile}` shadow comparator "
            "is captured over a fresh 12-window slice with non-null BTC5 trade telemetry."
        ),
    }


def _build_arr_confidence_score(
    *,
    live_window_observation: dict[str, Any],
    historical_order_path_proof: dict[str, Any],
    shadow_only_comparator: dict[str, Any],
    matched_window_comparator: dict[str, Any],
    runtime_truth: dict[str, Any],
) -> tuple[float, str]:
    window_count = int(live_window_observation.get("window_count") or 0)
    base = 0.05
    fresh_sample_boost = round(0.03 * min(window_count, 12) / 12.0, 4)
    historical_proof_boost = 0.03 if historical_order_path_proof.get("stale_but_real_path_exists") else 0.0
    comparator_boost = 0.18 if matched_window_comparator.get("same_window_comparison_ready") else 0.0
    healthy_runtime_boost = (
        0.12
        if _healthy_runtime_only(runtime_truth) and matched_window_comparator.get("same_window_comparison_ready")
        else 0.0
    )
    execution_delta_boost = 0.08 if shadow_only_comparator.get("measured_shadow_execution_delta_ready") else 0.0
    eligible_boost = 0.01 if int(live_window_observation.get("eligible_window_count") or 0) > 0 else 0.0
    score = round(
        min(
            0.55,
            base
            + fresh_sample_boost
            + historical_proof_boost
            + comparator_boost
            + healthy_runtime_boost
            + execution_delta_boost
            + eligible_boost,
        ),
        2,
    )
    basis = (
        f"{base:.2f} base + {fresh_sample_boost:.2f} fresh-sample boost + "
        f"{historical_proof_boost:.2f} historical-path boost + {comparator_boost:.2f} comparator boost + "
        f"{healthy_runtime_boost:.2f} healthy-runtime boost + {execution_delta_boost:.2f} execution-delta boost + "
        f"{eligible_boost:.2f} eligible-window boost"
    )
    return score, basis


def _resolve_canonical_policy_truth(
    *,
    runtime_truth: dict[str, Any],
    env_metadata: dict[str, str],
    baseline_artifact: dict[str, Any],
) -> dict[str, Any]:
    runtime_selected = runtime_truth.get("btc5_selected_package") if isinstance(runtime_truth.get("btc5_selected_package"), dict) else {}
    baseline_selected = baseline_artifact.get("selected_package") if isinstance(baseline_artifact.get("selected_package"), dict) else {}
    canonical_policy_id = (
        baseline_selected.get("selected_best_profile_name")
        or baseline_selected.get("selected_policy_id")
        or env_metadata.get("candidate")
        or runtime_selected.get("selected_policy_id")
        or runtime_selected.get("selected_best_profile_name")
        or "active_profile_probe_d0_00075"
    )
    runtime_policy_id = (
        runtime_selected.get("selected_policy_id")
        or runtime_selected.get("selected_best_profile_name")
    )
    return {
        "canonical_policy_id": str(canonical_policy_id),
        "source": (
            _repo_rel(DEFAULT_BASELINE_ARTIFACT)
            if baseline_selected
            else _repo_rel(DEFAULT_RUNTIME_TRUTH)
        ),
        "runtime_policy_id": runtime_policy_id,
        "alignment_status": (
            "aligned"
            if not runtime_policy_id or str(runtime_policy_id) == str(canonical_policy_id)
            else "mismatch"
        ),
    }


def _resolve_shadow_comparator(policy_latest: dict[str, Any]) -> dict[str, Any]:
    frontier = policy_latest.get("frontier_best_candidate")
    if not isinstance(frontier, dict):
        return {
            "policy_id": "active_profile",
            "delta_cap": 0.00015,
            "selection_basis": "dispatch_default",
        }
    runtime_package = frontier.get("runtime_package")
    if not isinstance(runtime_package, dict):
        runtime_package = {}
    profile = runtime_package.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    policy_id = str(frontier.get("policy_id") or profile.get("name") or "active_profile").strip() or "active_profile"
    delta_cap = float(profile.get("max_abs_delta") or 0.00015)
    return {
        "policy_id": policy_id,
        "delta_cap": delta_cap,
        "selection_basis": "frontier_best_candidate",
    }


def build_directional_conversion_probe(
    *,
    runtime_truth: dict[str, Any],
    archive_snapshots: list[dict[str, Any]],
    env_values: dict[str, str],
    env_metadata: dict[str, str],
    historical_rows: list[dict[str, Any]],
    historical_rows_path: Path = DEFAULT_HISTORICAL_ROWS,
    baseline_artifact: dict[str, Any] | None = None,
    policy_latest: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    baseline_artifact = baseline_artifact or {}
    policy_latest = policy_latest or {}
    all_window_records, unique_windows = _collect_unique_runtime_windows(archive_snapshots)
    live_window_observation = _build_live_window_observation(unique_windows)
    runtime_gap = _build_runtime_gap(
        runtime_truth=runtime_truth,
        snapshots=archive_snapshots,
        unique_windows=unique_windows,
    )
    historical_order_path_proof = _build_historical_order_path_proof(historical_rows, live_window_observation)
    shadow_comparator = _resolve_shadow_comparator(policy_latest)
    matched_window_comparator = _build_matched_window_comparator(
        historical_rows=historical_rows,
        historical_rows_path=historical_rows_path,
        runtime_truth=runtime_truth,
        live_window_observation=live_window_observation,
        shadow_policy_id=str(shadow_comparator.get("policy_id") or "active_profile"),
        shadow_delta_cap=float(shadow_comparator.get("delta_cap") or 0.00015),
    )
    shadow_only_comparator = _build_shadow_only_comparator(
        live_window_observation=live_window_observation,
        runtime_gap=runtime_gap,
        matched_window_comparator=matched_window_comparator,
    )
    arr_confidence_score, arr_confidence_score_basis = _build_arr_confidence_score(
        live_window_observation=live_window_observation,
        historical_order_path_proof=historical_order_path_proof,
        shadow_only_comparator=shadow_only_comparator,
        matched_window_comparator=matched_window_comparator,
        runtime_truth=runtime_truth,
    )
    canonical_policy_truth = _resolve_canonical_policy_truth(
        runtime_truth=runtime_truth,
        env_metadata=env_metadata,
        baseline_artifact=baseline_artifact,
    )
    policy_id = canonical_policy_truth["canonical_policy_id"]
    shadow_policy_id = str(shadow_comparator.get("policy_id") or matched_window_comparator.get("shadow_profile") or "active_profile")
    shadow_policy_slug = _safe_slug(shadow_policy_id)
    status_counts = live_window_observation.get("status_counts", {})
    block_reasons = _ordered_unique(
        [
            (
                "fresh_12_window_sample_has_zero_submit_rest_cancel_fill_conversion"
                if not live_window_observation.get("submit_rest_cancel_fill_observed", False)
                else ""
            ),
            (
                "runtime_truth_latest_missing_btc5_latest_order_status_while_service_reports_running"
                if runtime_gap.get("gap_detected")
                else ""
            ),
            (
                f"matched_window_shadow_execution_delta_{shadow_policy_slug}_not_measured"
                if shadow_only_comparator.get("matched_window_capture_ready", False)
                and not shadow_only_comparator.get("measured_shadow_execution_delta_ready", False)
                else f"matched_window_shadow_comparator_{shadow_policy_slug}_not_captured_on_same_stream"
                if not shadow_only_comparator.get("matched_window_capture_ready", False)
                else ""
            ),
            (
                "runtime_truth_selected_package_disagrees_with_canonical_live_baseline"
                if canonical_policy_truth.get("alignment_status") == "mismatch"
                else ""
            ),
            (
                "last_12_reconstructed_windows_show_"
                + "_".join(
                    f"{count}_{status}"
                    for status, count in sorted(status_counts.items())
                    if count
                )
                if status_counts
                else ""
            ),
        ]
    )
    generated_at = generated_at or datetime.now(UTC)
    finance_gate_pass = bool(runtime_truth.get("finance_gate_pass", True))
    matched_window_ready = bool(matched_window_comparator.get("same_window_comparison_ready"))
    payload = {
        "artifact": "instance02_directional_conversion_probe",
        "instance": "Instance 2 - GPT-4 / Extra High",
        "generated_at": _iso(generated_at),
        "schema_version": 2,
        "objective": (
            "Keep active_profile_probe_d0_00075 as the live BTC5 baseline, refresh the freshest healthy-runtime "
            f"matched-window evidence we actually have, and keep `{shadow_policy_id}` as the single shadow comparator "
            "until a same-stream execution delta exists."
        ),
        "baseline_policy": {
            "policy_id": str(policy_id),
            "selected_live_profile": str(policy_id),
            "live_baseline_locked": True,
            "live_widening_allowed_this_cycle": False,
            "shadow_comparator_policy_id": shadow_policy_id,
            "canonical_live_package": {
                "policy_id": canonical_policy_truth.get("canonical_policy_id"),
                "source": canonical_policy_truth.get("source"),
                "alignment_status": canonical_policy_truth.get("alignment_status"),
            },
            "runtime_truth_selected_package": {
                "selected_policy_id": (runtime_truth.get("btc5_selected_package") or {}).get("selected_policy_id"),
                "selected_best_profile_name": (
                    (runtime_truth.get("btc5_selected_package") or {}).get("selected_best_profile_name")
                ),
                "trade_now_status": (runtime_truth.get("btc5_stage_readiness") or {}).get("trade_now_status"),
            },
            "runtime_env_evidence": {
                "path": _repo_rel(DEFAULT_ENV_PATH),
                "candidate_comment": env_metadata.get("candidate"),
                "BTC5_MAX_ABS_DELTA": env_values.get("BTC5_MAX_ABS_DELTA"),
                "BTC5_UP_MAX_BUY_PRICE": env_values.get("BTC5_UP_MAX_BUY_PRICE"),
                "BTC5_DOWN_MAX_BUY_PRICE": env_values.get("BTC5_DOWN_MAX_BUY_PRICE"),
                "BTC5_SESSION_POLICY_JSON": env_values.get("BTC5_SESSION_POLICY_JSON"),
            },
        },
        "fresh_live_window_observation": live_window_observation,
        "latest_runtime_gap_observation": runtime_gap,
        "historical_order_path_proof": historical_order_path_proof,
        "matched_window_live_vs_shadow_comparator": matched_window_comparator,
        "shadow_only_comparator": shadow_only_comparator,
        "decision": {
            "status": "keep_0.00075" if matched_window_ready else "hold_and_wait_for_better_book_conditions",
            "same_window_comparison_ready": matched_window_ready,
            "next_live_decision_set": list(_LIVE_DECISION_SET),
            "selected_next_live_decision": "keep_0.00075" if matched_window_ready else "hold_and_wait_for_better_book_conditions",
            "fresh_submit_rest_cancel_fill_proof": live_window_observation.get("submit_rest_cancel_fill_observed", False),
            "ruling": (
                (
                    f"Keep active_profile_probe_d0_00075 live at flat stage-1 size. The fresh March 12 same-window "
                    f"comparator still has no same-stream execution delta for `{shadow_policy_id}`, so the live baseline stays locked."
                )
                if matched_window_ready
                else
                "Keep active_profile_probe_d0_00075 live at flat stage-1 size, do not widen live this cycle, "
                f"and do not treat `{shadow_policy_id}` as anything other than the single shadow-only comparator until the same stream "
                "shows fresh BTC5 trade telemetry and a real matched-window capture."
            ),
            "why": (
                (
                    f"The remote VPS now supplies a healthy March 12 same-window slice, but the evidence for `{shadow_policy_id}` "
                    "is still eligibility-only and replay-led, so it cannot replace the live baseline yet."
                )
                if matched_window_ready
                else
                "The freshest reconstructed 12-window slice is still zero-conversion, the most recent runtime truth "
                "reports the service as running but has no new BTC5 latest-trade payload, and there is no same-window "
                f"`{shadow_policy_id}` comparator artifact yet."
            ),
        },
        "candidate_delta_arr_bps": 0,
        "candidate_delta_arr_bps_basis": (
            f"Pinned at 0 because the refreshed same-window comparator for `{shadow_policy_id}` is still eligibility-only "
            "and does not yet measure an execution or fill delta versus the live d0_00075 baseline."
        ),
        "expected_improvement_velocity_delta": 0.08 if matched_window_ready else 0.0,
        "expected_improvement_velocity_delta_basis": (
            (
                "Set to 0.08 because the packet now uses a fresh healthy-runtime same-window comparator, which removes "
                f"stale-window ambiguity and makes the next live-swap decision depend only on capturing `{shadow_policy_id}` "
                "shadow execution telemetry."
            )
            if matched_window_ready
            else
            "Pinned at 0.0 because the fresh live sample has zero submit/rest/cancel/fill conversion and "
            f"the `{shadow_policy_id}` shadow comparator has not been captured on the same stream."
        ),
        "arr_confidence_score": arr_confidence_score,
        "arr_confidence_score_basis": arr_confidence_score_basis,
        "block_reasons": block_reasons,
        "finance_gate_pass": finance_gate_pass,
        "one_next_cycle_action": (
            (
                f"Keep active_profile_probe_d0_00075 live unchanged, run `{shadow_policy_id}` as the only same-stream "
                "shadow-only over the next fresh 60-window slice, and publish a measured execution-delta packet before "
                "considering any live package swap."
            )
            if matched_window_ready
            else
            "Keep active_profile_probe_d0_00075 live unchanged, wait for the runtime truth snapshots to resume "
            "emitting non-null BTC5 latest-trade payloads, then capture the next bounded 12-window slice with "
            f"`{shadow_policy_id}` shadow-only on the same stream before considering any live package swap."
        ),
        "sources": {
            "runtime_truth_latest": _repo_rel(DEFAULT_RUNTIME_TRUTH),
            "runtime_truth_archive_dir": _repo_rel(DEFAULT_RUNTIME_ARCHIVE_DIR),
            "historical_window_rows": _repo_rel(historical_rows_path),
            "runtime_env": _repo_rel(DEFAULT_ENV_PATH),
            "archive_snapshot_count": len(archive_snapshots),
            "archive_window_record_count": len(all_window_records),
            "archive_unique_window_count": len(unique_windows),
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--runtime-archive-dir", type=Path, default=DEFAULT_RUNTIME_ARCHIVE_DIR)
    parser.add_argument("--env-path", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--historical-rows", type=Path, default=DEFAULT_HISTORICAL_ROWS)
    parser.add_argument("--baseline-artifact", type=Path, default=DEFAULT_BASELINE_ARTIFACT)
    parser.add_argument("--policy-latest", type=Path, default=DEFAULT_POLICY_LATEST)
    parser.add_argument("--refresh-remote", action="store_true")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    args = parser.parse_args()

    runtime_truth = _read_json_dict(args.runtime_truth)
    archive_snapshots = _load_runtime_archive_snapshots(args.runtime_archive_dir)
    env_values, env_metadata = _load_env_file(args.env_path)
    historical_rows_path = _select_freshest_existing_path(args.historical_rows, LEGACY_HISTORICAL_ROWS)
    if args.refresh_remote:
        historical_rows = fetch_remote_rows()
        _write_json_list(args.historical_rows, historical_rows)
        historical_rows_path = args.historical_rows
    else:
        historical_rows = _read_json_list(historical_rows_path)
    baseline_artifact_path = _select_freshest_existing_path(args.baseline_artifact, LEGACY_BASELINE_ARTIFACT)
    baseline_artifact = _read_json_dict(baseline_artifact_path)
    policy_latest = _read_json_dict(args.policy_latest)
    payload = build_directional_conversion_probe(
        runtime_truth=runtime_truth,
        archive_snapshots=archive_snapshots,
        env_values=env_values,
        env_metadata=env_metadata,
        historical_rows=historical_rows,
        historical_rows_path=historical_rows_path,
        baseline_artifact=baseline_artifact,
        policy_latest=policy_latest,
    )
    _write_json(args.output_json, payload)
    print(args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
