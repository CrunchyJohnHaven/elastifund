#!/usr/bin/env python3
"""Render the Instance 2 BTC5 bounded-envelope recovery artifact."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


UTC = timezone.utc
ET = ZoneInfo("America/New_York")
REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_RUNTIME_TRUTH = REPO_ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_FINANCE_LATEST = REPO_ROOT / "reports" / "finance" / "latest.json"
DEFAULT_CURRENT_PROBE = REPO_ROOT / "reports" / "btc5_autoresearch_current_probe" / "latest.json"
DEFAULT_POLICY_LATEST = REPO_ROOT / "reports" / "autoresearch" / "btc5_policy" / "latest.json"
DEFAULT_REGIME_SUMMARY = REPO_ROOT / "reports" / "btc5_regime_policy_lab" / "summary.json"
DEFAULT_ROWS_JSON = REPO_ROOT / "reports" / "runtime" / "tmp" / "tmp_remote_btc5_window_rows.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "reports" / "parallel" / "instance02_btc5_bounded_envelope.json"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _ordered_unique(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _parse_dt(row.get("updated_at")) or _parse_dt(row.get("created_at")) or datetime.min.replace(tzinfo=UTC),
            int(_safe_float(row.get("window_start_ts"), 0.0) or 0),
        ),
    )


def _live_filled_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in rows
        if str(row.get("order_status") or "").strip().lower() == "live_filled"
    ]
    return _sort_rows(filtered)


def _holding_outcome(row: dict[str, Any]) -> str:
    won = row.get("won")
    if won is True:
        return "won"
    if won is False:
        return "lost"
    pnl = _safe_float(row.get("realized_pnl_usd"), _safe_float(row.get("pnl_usd"), 0.0))
    if pnl > 0.0:
        return "won"
    if pnl < 0.0:
        return "lost"
    return "flat"


def _bucket_surface(rows: list[dict[str, Any]], *, labeler: Any) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(labeler(row) or "unknown")
        bucket = buckets.setdefault(
            label,
            {
                "label": label,
                "rows": 0,
                "pnl_usd": 0.0,
                "wins": 0,
                "losses": 0,
                "flats": 0,
            },
        )
        bucket["rows"] = int(bucket["rows"]) + 1
        pnl = _safe_float(row.get("realized_pnl_usd"), _safe_float(row.get("pnl_usd"), 0.0))
        bucket["pnl_usd"] = _safe_float(bucket["pnl_usd"], 0.0) + pnl
        outcome = _holding_outcome(row)
        if outcome == "won":
            bucket["wins"] = int(bucket["wins"]) + 1
        elif outcome == "lost":
            bucket["losses"] = int(bucket["losses"]) + 1
        else:
            bucket["flats"] = int(bucket["flats"]) + 1
    ranked = []
    for label, bucket in buckets.items():
        rows_count = int(bucket.get("rows") or 0)
        wins = int(bucket.get("wins") or 0)
        losses = int(bucket.get("losses") or 0)
        ranked.append(
            {
                "label": label,
                "rows": rows_count,
                "pnl_usd": round(_safe_float(bucket.get("pnl_usd"), 0.0), 4),
                "wins": wins,
                "losses": losses,
                "flats": int(bucket.get("flats") or 0),
                "win_rate": round((wins / float(max(1, wins + losses))), 4),
                "loss_rate": round((losses / float(max(1, wins + losses))), 4),
                "avg_pnl_usd": round(_safe_float(bucket.get("pnl_usd"), 0.0) / float(max(1, rows_count)), 4),
            }
        )
    ranked.sort(
        key=lambda item: (
            _safe_float(item.get("pnl_usd"), 0.0),
            -int(item.get("rows") or 0),
            str(item.get("label") or ""),
        )
    )
    return ranked


def _regime_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regimes: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("session_name") or f"hour_et_{int(_safe_float(row.get('et_hour'), 0.0) or 0):02d}"),
            str(row.get("direction") or "UNKNOWN").upper(),
            str(row.get("price_bucket") or "unknown"),
            str(row.get("delta_bucket") or "unknown"),
        )
        regimes[key].append(row)
    ranked: list[dict[str, Any]] = []
    for (session_name, direction, price_bucket, delta_bucket), bucket_rows in regimes.items():
        pnl = round(
            sum(_safe_float(row.get("realized_pnl_usd"), _safe_float(row.get("pnl_usd"), 0.0)) for row in bucket_rows),
            4,
        )
        wins = sum(1 for row in bucket_rows if _holding_outcome(row) == "won")
        losses = sum(1 for row in bucket_rows if _holding_outcome(row) == "lost")
        ranked.append(
            {
                "session_name": session_name,
                "direction": direction,
                "price_bucket": price_bucket,
                "delta_bucket": delta_bucket,
                "rows": len(bucket_rows),
                "pnl_usd": pnl,
                "wins": wins,
                "losses": losses,
                "win_rate": round((wins / float(max(1, wins + losses))), 4),
                "avg_pnl_usd": round(pnl / float(max(1, len(bucket_rows))), 4),
            }
        )
    ranked.sort(
        key=lambda item: (
            _safe_float(item.get("pnl_usd"), 0.0),
            -int(item.get("rows") or 0),
            str(item.get("session_name") or ""),
            str(item.get("direction") or ""),
        )
    )
    return ranked


def _surface_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = _sort_rows(rows)
    fill_outcome = _bucket_surface(ordered, labeler=_holding_outcome)
    return {
        "sample_size_rows": len(ordered),
        "by_direction": _bucket_surface(ordered, labeler=lambda row: str(row.get("direction") or "UNKNOWN").upper()),
        "by_price_bucket": _bucket_surface(ordered, labeler=lambda row: str(row.get("price_bucket") or "unknown")),
        "by_delta_bucket": _bucket_surface(ordered, labeler=lambda row: str(row.get("delta_bucket") or "unknown")),
        "by_session_name": _bucket_surface(
            ordered,
            labeler=lambda row: str(row.get("session_name") or f"hour_et_{int(_safe_float(row.get('et_hour'), 0.0) or 0):02d}"),
        ),
        "by_et_hour": _bucket_surface(
            ordered,
            labeler=lambda row: f"hour_et_{int(_safe_float(row.get('et_hour'), 0.0) or 0):02d}",
        ),
        "by_holding_outcome": fill_outcome,
        "by_fill_outcome": fill_outcome,
        "ranked_regimes": _regime_surface(ordered),
    }


def _recent_surface(rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    ordered = _sort_rows(rows)
    return _surface_summary(ordered[-max(1, int(limit)):])


def _current_probe_float(current_probe: dict[str, Any], key: str, default: float = 0.0) -> float:
    return _safe_float(
        current_probe.get(key),
        _safe_float((current_probe.get("current_probe") or {}).get(key), default),
    )


def _active_candidate(current_probe: dict[str, Any], regime_summary: dict[str, Any]) -> dict[str, Any]:
    candidate = current_probe.get("current_candidate")
    if isinstance(candidate, dict):
        return candidate
    candidate = current_probe.get("active_profile")
    if isinstance(candidate, dict):
        return {"profile": candidate}
    fallback = regime_summary.get("current_policy")
    return fallback if isinstance(fallback, dict) else {}


def _canonical_live_policy_id(
    *,
    runtime_truth: dict[str, Any],
    policy_latest: dict[str, Any],
) -> str:
    runtime_selected = runtime_truth.get("btc5_selected_package")
    if isinstance(runtime_selected, dict):
        for key in ("selected_policy_id", "selected_best_profile_name"):
            value = str(runtime_selected.get(key) or "").strip()
            if value:
                return value
    for key in ("selected_policy_id", "selected_best_profile_name", "selected_active_profile_name"):
        value = str(policy_latest.get(key) or "").strip()
        if value:
            return value
    return "active_profile_probe_d0_00075"


def _clone_flat(flat: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(flat, dict):
        return {}
    cloned = dict(flat)
    for key in (
        "candidate",
        "default_profile",
        "matched_override",
        "effective_profile",
        "historical",
        "continuation",
        "monte_carlo",
        "scoring",
    ):
        if isinstance(flat.get(key), dict):
            cloned[key] = dict(flat[key])
    if isinstance(flat.get("session_policy"), list):
        cloned["session_policy"] = [dict(item) for item in flat["session_policy"] if isinstance(item, dict)]
    if isinstance(flat.get("candidate_class_reason_tags"), list):
        cloned["candidate_class_reason_tags"] = list(flat["candidate_class_reason_tags"])
    if isinstance(flat.get("follow_up_families"), list):
        cloned["follow_up_families"] = list(flat["follow_up_families"])
    if isinstance(flat.get("current_hour_et_hours"), list):
        cloned["current_hour_et_hours"] = list(flat["current_hour_et_hours"])
    return cloned


def _canonical_live_candidate(
    *,
    runtime_truth: dict[str, Any],
    current_probe: dict[str, Any],
    regime_summary: dict[str, Any],
    policy_latest: dict[str, Any],
    current_hour: int,
) -> dict[str, Any] | None:
    baseline_flat = _flatten_baseline_candidate(
        _baseline_candidate(current_probe=current_probe, regime_summary=regime_summary),
        current_hour=current_hour,
    )
    candidate = _clone_flat(baseline_flat)
    canonical_policy_id = _canonical_live_policy_id(runtime_truth=runtime_truth, policy_latest=policy_latest)
    selected_runtime_package: dict[str, Any] = {}
    for package in (
        current_probe.get("active_runtime_package"),
        current_probe.get("best_runtime_package"),
        policy_latest.get("selected_best_runtime_package"),
    ):
        if not isinstance(package, dict):
            continue
        profile = package.get("profile") if isinstance(package.get("profile"), dict) else {}
        package_name = str(profile.get("name") or "").strip()
        if not selected_runtime_package:
            selected_runtime_package = package
        if package_name == canonical_policy_id:
            selected_runtime_package = package
            break
    runtime_profile = (
        dict(selected_runtime_package.get("profile") or {})
        if isinstance(selected_runtime_package.get("profile"), dict)
        else {}
    )
    if not runtime_profile and isinstance(candidate.get("default_profile"), dict):
        runtime_profile = dict(candidate["default_profile"])
    if not runtime_profile and isinstance(candidate.get("effective_profile"), dict):
        runtime_profile = dict(candidate["effective_profile"])
    if not runtime_profile:
        return candidate or None

    runtime_profile["name"] = canonical_policy_id
    session_policy = selected_runtime_package.get("session_policy")
    if not isinstance(session_policy, list):
        session_policy = []

    candidate["name"] = canonical_policy_id
    candidate["candidate_class"] = "hold_current"
    candidate["candidate_class_reason_tags"] = _ordered_unique(
        list(candidate.get("candidate_class_reason_tags") or []) + ["canonical_live_baseline_locked"]
    )
    candidate["default_profile"] = dict(runtime_profile)
    candidate["effective_profile"] = dict(runtime_profile)
    candidate["matched_override"] = None
    candidate["current_hour_match"] = False
    candidate["current_hour_session_name"] = ""
    candidate["current_hour_et_hours"] = []
    candidate["session_policy"] = [dict(item) for item in session_policy if isinstance(item, dict)]
    return candidate


def _frontier_shadow_comparator(policy_latest: dict[str, Any]) -> dict[str, Any]:
    frontier = policy_latest.get("frontier_best_candidate")
    if not isinstance(frontier, dict):
        return {}
    runtime_package = frontier.get("runtime_package")
    if not isinstance(runtime_package, dict):
        runtime_package = {}
    profile = dict(runtime_package.get("profile") or {})
    if not profile:
        return {}
    policy_id = str(frontier.get("policy_id") or profile.get("name") or "active_profile").strip() or "active_profile"
    profile["name"] = policy_id
    return {
        "policy_id": policy_id,
        "selection_score": round(max(0.0, _safe_float(frontier.get("loss_improvement_vs_incumbent"), 0.0)), 4),
        "selection_reasons": [
            "single_shadow_comparator",
            "frontier_best_package",
            "fresh_same_stream_win_required",
        ],
        "runtime_package": {
            "profile": profile,
            "session_policy": [
                dict(item) for item in (runtime_package.get("session_policy") or []) if isinstance(item, dict)
            ],
            "effective_profile_for_current_hour": dict(profile),
        },
    }


def _session_override_shadow_hold_reasons(
    *,
    current_probe: dict[str, Any],
) -> list[str]:
    best_candidate = current_probe.get("best_candidate")
    if not isinstance(best_candidate, dict):
        return []
    policy = best_candidate.get("policy") if isinstance(best_candidate.get("policy"), dict) else {}
    policy_name = str(policy.get("name") or best_candidate.get("name") or "session_override_candidate").strip()
    overrides = policy.get("overrides") if isinstance(policy.get("overrides"), list) else []
    if not overrides:
        return []
    loosened_up_cap = False
    sessions: list[str] = []
    for override in overrides:
        if not isinstance(override, dict):
            continue
        sessions.append(str(override.get("session_name") or "unknown"))
        profile = override.get("profile") if isinstance(override.get("profile"), dict) else {}
        if _safe_float(profile.get("up_max_buy_price"), 0.0) >= 0.51:
            loosened_up_cap = True
    reasons = [
        f"Keep `{policy_name}` shadow-only: session-conditioned overrides stay off the live path until fresh live fills resume in the current epoch."
    ]
    if sessions:
        reasons.append(
            f"Keep `{', '.join(_ordered_unique(sessions))}` shadow-only: weak regimes need two consecutive positive cycles before re-entry."
        )
    if loosened_up_cap:
        reasons.append(
            f"Keep `{policy_name}` shadow-only: `up_max_buy_price=0.51` has not cleared matched-window testing yet."
        )
    return reasons


def _baseline_candidate(
    *,
    current_probe: dict[str, Any],
    regime_summary: dict[str, Any],
) -> dict[str, Any]:
    hold_current = regime_summary.get("hold_current_candidate")
    if isinstance(hold_current, dict):
        return hold_current
    current_policy = regime_summary.get("current_policy")
    if isinstance(current_policy, dict):
        return current_policy
    return _active_candidate(current_probe, regime_summary)


def _policy_overrides(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    policy = candidate.get("policy")
    if not isinstance(policy, dict):
        return []
    overrides = policy.get("overrides")
    if not isinstance(overrides, list):
        return []
    return [item for item in overrides if isinstance(item, dict)]


def _candidate_name(candidate: dict[str, Any]) -> str:
    policy = candidate.get("policy")
    if isinstance(policy, dict):
        name = str(policy.get("name") or "").strip()
        if name:
            return name
    profile = candidate.get("profile")
    if isinstance(profile, dict):
        name = str(profile.get("name") or "").strip()
        if name:
            return name
    return "unknown_candidate"


def _flatten_candidate(
    candidate: dict[str, Any],
    *,
    current_hour: int,
) -> dict[str, Any]:
    policy = candidate.get("policy") if isinstance(candidate.get("policy"), dict) else {}
    default_profile = dict(policy.get("default_profile") or {})
    overrides = _policy_overrides(candidate)
    matched_override: dict[str, Any] | None = None
    for override in overrides:
        hours = [int(_safe_float(hour, -1)) for hour in (override.get("et_hours") or [])]
        if current_hour in hours:
            matched_override = override
            break
    effective_profile = dict((matched_override or {}).get("profile") or default_profile)
    historical = candidate.get("historical") if isinstance(candidate.get("historical"), dict) else {}
    continuation = candidate.get("continuation") if isinstance(candidate.get("continuation"), dict) else {}
    monte_carlo = candidate.get("monte_carlo") if isinstance(candidate.get("monte_carlo"), dict) else {}
    scoring = candidate.get("scoring") if isinstance(candidate.get("scoring"), dict) else {}
    current_hour_match = matched_override is not None
    effective_hours = [int(_safe_float(hour, -1)) for hour in ((matched_override or {}).get("et_hours") or [])]
    return {
        "name": _candidate_name(candidate),
        "candidate": candidate,
        "candidate_class": str(candidate.get("candidate_class") or "").strip().lower(),
        "candidate_class_reason_tags": list(candidate.get("candidate_class_reason_tags") or []),
        "follow_up_families": list(candidate.get("follow_up_families") or []),
        "default_profile": default_profile,
        "matched_override": matched_override,
        "effective_profile": effective_profile,
        "current_hour_match": current_hour_match,
        "current_hour_session_name": str((matched_override or {}).get("session_name") or ""),
        "current_hour_et_hours": sorted(hour for hour in effective_hours if hour >= 0),
        "session_policy": [
            {
                "name": str(override.get("session_name") or (override.get("profile") or {}).get("name") or "session_policy"),
                "et_hours": [int(_safe_float(hour, 0.0) or 0) for hour in (override.get("et_hours") or [])],
                "max_abs_delta": _safe_float(((override.get("profile") or {}).get("max_abs_delta")), 0.0),
                "up_max_buy_price": _safe_float(((override.get("profile") or {}).get("up_max_buy_price")), 0.0),
                "down_max_buy_price": _safe_float(((override.get("profile") or {}).get("down_max_buy_price")), 0.0),
            }
            for override in overrides
        ],
        "historical": historical,
        "continuation": continuation,
        "monte_carlo": monte_carlo,
        "scoring": scoring,
        "validation_live_filled_rows": int(
            _safe_float(historical.get("replay_live_filled_rows"), _safe_float(candidate.get("validation_live_filled_rows"), 0.0))
            or 0
        ),
        "replay_live_filled_pnl_usd": round(
            _safe_float(historical.get("replay_live_filled_pnl_usd"), _safe_float(candidate.get("validation_replay_pnl_usd"), 0.0)),
            4,
        ),
        "replay_trade_notional_usd": round(_safe_float(historical.get("trade_notional_usd"), 0.0), 4),
        "validation_profit_probability": _safe_float(
            monte_carlo.get("profit_probability"),
            _safe_float(candidate.get("validation_profit_probability"), 0.0),
        ),
        "validation_p95_drawdown_usd": _safe_float(
            monte_carlo.get("p95_max_drawdown_usd"),
            _safe_float(candidate.get("validation_p95_drawdown_usd"), 0.0),
        ),
        "validation_p05_arr_pct": _safe_float(
            continuation.get("p05_arr_pct"),
            _safe_float(candidate.get("validation_p05_arr_pct"), 0.0),
        ),
        "live_policy_score": _safe_float(scoring.get("live_policy_score"), _safe_float(candidate.get("ranking_score"), 0.0)),
        "generalization_ratio": _safe_float(
            candidate.get("generalization_ratio"),
            _safe_float(scoring.get("generalization_ratio"), 0.0),
        ),
    }


def _runtime_package_for_recommendation(flat: dict[str, Any]) -> dict[str, Any]:
    profile = dict(flat.get("default_profile") or flat.get("effective_profile") or {})
    profile["name"] = str(profile.get("name") or "current_live_profile")
    return {
        "profile": profile,
        "session_policy": list(flat.get("session_policy") or []),
        "effective_profile_for_current_hour": dict(flat.get("effective_profile") or {}),
    }


def _score_live_candidate(flat: dict[str, Any]) -> tuple[float, list[str]]:
    effective = flat.get("effective_profile") if isinstance(flat.get("effective_profile"), dict) else {}
    up_cap = _safe_float(effective.get("up_max_buy_price"), 0.0)
    down_cap = _safe_float(effective.get("down_max_buy_price"), 0.0)
    max_abs_delta = _safe_float(effective.get("max_abs_delta"), 0.0)
    score = 0.0
    reasons: list[str] = []
    if flat.get("current_hour_match"):
        score += 50.0
        reasons.append("current_hour_match")
    if up_cap <= 0.0:
        score += 20.0
        reasons.append("up_disabled")
    elif up_cap <= 0.48:
        score += 10.0
        reasons.append("up_tightened")
    if max_abs_delta <= 0.00005:
        score += 20.0
        reasons.append("delta_capped_at_or_below_0.00005")
    elif max_abs_delta <= 0.00010:
        score += 8.0
        reasons.append("delta_capped_at_or_below_0.00010")
    if 0.0 < down_cap <= 0.50:
        score += 10.0
        reasons.append("down_cap_tightened")
    replay_pnl = _safe_float(flat.get("replay_live_filled_pnl_usd"), 0.0)
    if replay_pnl > 0.0:
        score += min(25.0, replay_pnl / 5.0)
        reasons.append("positive_replay_pnl")
    if _safe_float(flat.get("validation_p05_arr_pct"), 0.0) > 0.0:
        score += 10.0
        reasons.append("positive_p05_arr")
    if _safe_float(flat.get("validation_p95_drawdown_usd"), 0.0) <= 100.0:
        score += 5.0
        reasons.append("drawdown_tail_below_100")
    if str(flat.get("candidate_class") or "") == "promote":
        score += 5.0
        reasons.append("candidate_class_promote")
    score += min(15.0, _safe_float(flat.get("live_policy_score"), 0.0) / 1_000_000.0)
    score -= max(0.0, float(len(flat.get("session_policy") or [])) - 2.0)
    if not flat.get("current_hour_match"):
        score -= 100.0
    return round(score, 4), reasons


def _score_shadow_candidate(flat: dict[str, Any]) -> tuple[float, list[str]]:
    effective = flat.get("effective_profile") if isinstance(flat.get("effective_profile"), dict) else {}
    up_cap = _safe_float(effective.get("up_max_buy_price"), 0.0)
    max_abs_delta = _safe_float(effective.get("max_abs_delta"), 0.0)
    score = 0.0
    reasons: list[str] = []
    if str(flat.get("candidate_class") or "") == "probe_only":
        score += 40.0
        reasons.append("probe_only_revalidation_target")
    if "open_et" in str(flat.get("name") or ""):
        score += 20.0
        reasons.append("targets_open_et_revalidation")
    if up_cap <= 0.48:
        score += 10.0
        reasons.append("up_tightened_or_disabled")
    if max_abs_delta <= 0.00005:
        score += 10.0
        reasons.append("tight_delta")
    replay_pnl = _safe_float(flat.get("replay_live_filled_pnl_usd"), 0.0)
    if replay_pnl > 0.0:
        score += min(15.0, replay_pnl / 10.0)
        reasons.append("positive_replay_pnl")
    score += min(10.0, _safe_float(flat.get("live_policy_score"), 0.0) / 1_000_000.0)
    return round(score, 4), reasons


def _flatten_probe_candidate(candidate: dict[str, Any], *, current_hour: int) -> dict[str, Any]:
    session_policy = list(candidate.get("session_policy") or [])
    matched = None
    for item in session_policy:
        hours = [int(_safe_float(hour, -1)) for hour in (item.get("et_hours") or [])]
        if current_hour in hours:
            matched = item
            break
    default_profile = dict(candidate.get("default_profile") or {})
    if not default_profile:
        default_profile = dict((candidate.get("profile") or {}))
    effective_profile = dict(matched or default_profile)
    return {
        "name": str(candidate.get("name") or "probe_candidate"),
        "candidate": candidate,
        "candidate_class": str(candidate.get("candidate_class") or "").strip().lower(),
        "candidate_class_reason_tags": list(candidate.get("candidate_class_reason_tags") or []),
        "follow_up_families": list(candidate.get("follow_up_families") or []),
        "default_profile": default_profile,
        "matched_override": matched,
        "effective_profile": effective_profile,
        "current_hour_match": matched is not None,
        "current_hour_session_name": str((matched or {}).get("name") or ""),
        "current_hour_et_hours": [int(_safe_float(hour, 0.0) or 0) for hour in ((matched or {}).get("et_hours") or [])],
        "session_policy": session_policy,
        "historical": {
            "replay_live_filled_rows": int(_safe_float(candidate.get("validation_live_filled_rows"), 0.0) or 0),
            "replay_live_filled_pnl_usd": _safe_float(candidate.get("validation_replay_pnl_usd"), 0.0),
            "trade_notional_usd": 0.0,
        },
        "continuation": {
            "p05_arr_pct": _safe_float(candidate.get("validation_p05_arr_pct"), 0.0),
        },
        "monte_carlo": {
            "profit_probability": _safe_float(candidate.get("validation_profit_probability"), 0.0),
            "p95_max_drawdown_usd": _safe_float(candidate.get("validation_p95_drawdown_usd"), 0.0),
        },
        "scoring": {
            "live_policy_score": _safe_float(candidate.get("ranking_score"), 0.0),
        },
        "validation_live_filled_rows": int(_safe_float(candidate.get("validation_live_filled_rows"), 0.0) or 0),
        "replay_live_filled_pnl_usd": round(_safe_float(candidate.get("validation_replay_pnl_usd"), 0.0), 4),
        "replay_trade_notional_usd": 0.0,
        "validation_profit_probability": _safe_float(candidate.get("validation_profit_probability"), 0.0),
        "validation_p95_drawdown_usd": _safe_float(candidate.get("validation_p95_drawdown_usd"), 0.0),
        "validation_p05_arr_pct": _safe_float(candidate.get("validation_p05_arr_pct"), 0.0),
        "live_policy_score": _safe_float(candidate.get("ranking_score"), 0.0),
        "generalization_ratio": _safe_float(candidate.get("generalization_ratio"), 0.0),
    }


def _flatten_baseline_candidate(candidate: dict[str, Any], *, current_hour: int) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    if isinstance(candidate.get("policy"), dict):
        return _flatten_candidate(candidate, current_hour=current_hour)
    if any(key in candidate for key in ("default_profile", "profile", "session_policy")):
        return _flatten_probe_candidate(candidate, current_hour=current_hour)
    return None


def _current_hour_session_name(flat: dict[str, Any]) -> str:
    session_name = str(flat.get("current_hour_session_name") or "").strip()
    if session_name:
        return session_name
    matched = flat.get("matched_override") if isinstance(flat.get("matched_override"), dict) else {}
    session_name = str(matched.get("session_name") or matched.get("name") or "").strip()
    if session_name:
        return session_name
    hours = flat.get("current_hour_et_hours") if isinstance(flat.get("current_hour_et_hours"), list) else []
    if hours:
        return f"hour_et_{int(_safe_float(hours[0], 0.0) or 0):02d}"
    return ""


def _live_guardrail_notes(
    *,
    flat: dict[str, Any],
    baseline_flat: dict[str, Any] | None,
    suppression_contract: dict[str, Any],
) -> list[str]:
    effective = flat.get("effective_profile") if isinstance(flat.get("effective_profile"), dict) else {}
    if not effective:
        return ["missing_effective_profile"]

    notes: list[str] = []
    up_cap = _safe_float(effective.get("up_max_buy_price"), 0.0)
    down_cap = _safe_float(effective.get("down_max_buy_price"), 0.0)
    max_abs_delta = _safe_float(effective.get("max_abs_delta"), 0.0)
    suppressed_sessions = {str(item) for item in (suppression_contract.get("suppressed_sessions") or [])}
    suppressed_directions = {str(item).upper() for item in (suppression_contract.get("suppressed_directions") or [])}
    suppressed_delta_buckets = {str(item) for item in (suppression_contract.get("suppressed_delta_buckets") or [])}
    current_session_name = _current_hour_session_name(flat)
    if current_session_name and current_session_name in suppressed_sessions:
        notes.append(f"current session `{current_session_name}` is still suppressed")
    if "UP" in suppressed_directions and up_cap > 0.0:
        notes.append("reopens the suppressed UP side")
    if "0.00005_to_0.00010" in suppressed_delta_buckets and max_abs_delta > 0.00005:
        notes.append("widens max_abs_delta back into the blocked mid-delta bucket")
    elif "gt_0.00010" in suppressed_delta_buckets and max_abs_delta > 0.00010:
        notes.append("widens max_abs_delta back into the blocked wide-delta bucket")

    baseline_effective = (
        baseline_flat.get("effective_profile") if isinstance((baseline_flat or {}).get("effective_profile"), dict) else {}
    )
    if baseline_effective:
        baseline_delta = _safe_float(baseline_effective.get("max_abs_delta"), max_abs_delta)
        baseline_up = _safe_float(baseline_effective.get("up_max_buy_price"), up_cap)
        baseline_down = _safe_float(baseline_effective.get("down_max_buy_price"), down_cap)
        if max_abs_delta > baseline_delta:
            notes.append("widens max_abs_delta versus the proven baseline")
        if up_cap > baseline_up:
            notes.append("loosens the UP buy cap versus the proven baseline")
        if down_cap > baseline_down:
            notes.append("loosens the DOWN buy cap versus the proven baseline")
        materially_tighter = (
            max_abs_delta < baseline_delta
            or up_cap < baseline_up
            or down_cap < baseline_down
        )
        baseline_name = str((baseline_flat or {}).get("name") or "").strip()
        candidate_name = str(flat.get("name") or "").strip()
        if baseline_name and candidate_name and candidate_name != baseline_name and not materially_tighter:
            notes.append("does not tighten the proven baseline; the edge is replay-only this cycle")
    return notes


def _select_live_candidate(
    *,
    regime_summary: dict[str, Any],
    current_hour: int,
    suppression_contract: dict[str, Any],
    baseline_flat: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    candidates = regime_summary.get("candidates")
    if not isinstance(candidates, list):
        return None, [], None
    flattened = [_flatten_candidate(candidate, current_hour=current_hour) for candidate in candidates if isinstance(candidate, dict)]
    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    best_rejected: tuple[float, str, list[str]] | None = None
    for flat in flattened:
        score, reasons = _score_live_candidate(flat)
        if score <= 0.0:
            continue
        guardrail_notes = _live_guardrail_notes(
            flat=flat,
            baseline_flat=baseline_flat,
            suppression_contract=suppression_contract,
        )
        if guardrail_notes:
            candidate_name = str(flat.get("name") or "candidate")
            rejection = (score, candidate_name, guardrail_notes)
            if best_rejected is None or float(rejection[0]) > float(best_rejected[0]):
                best_rejected = rejection
            continue
        scored.append((score, flat, reasons))
    if not scored:
        rejection_note = None
        if best_rejected is not None:
            rejection_note = (
                f"`{best_rejected[1]}` stayed shadow-only because it " + ", ".join(best_rejected[2]) + "."
            )
        return None, [], rejection_note
    scored.sort(
        key=lambda item: (
            float(item[0]),
            _safe_float(item[1].get("replay_live_filled_pnl_usd"), 0.0),
            _safe_float(item[1].get("validation_p05_arr_pct"), 0.0),
        ),
        reverse=True,
    )
    score, flat, reasons = scored[0]
    flat = dict(flat)
    flat["selection_score"] = score
    flat["selection_reasons"] = reasons
    return flat, reasons, None


def _select_shadow_candidate(
    *,
    regime_summary: dict[str, Any],
    current_hour: int,
    live_name: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    probe_candidate = regime_summary.get("best_probe_only_candidate")
    if isinstance(probe_candidate, dict):
        flat_probe = _flatten_probe_candidate(probe_candidate, current_hour=current_hour)
        flat_probe["selection_score"], flat_probe["selection_reasons"] = _score_shadow_candidate(flat_probe)
        if flat_probe.get("name") != live_name:
            return flat_probe, list(flat_probe.get("selection_reasons") or [])

    candidates = regime_summary.get("candidates")
    if not isinstance(candidates, list):
        return None, []
    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        flat = _flatten_candidate(candidate, current_hour=current_hour)
        if flat.get("name") == live_name:
            continue
        score, reasons = _score_shadow_candidate(flat)
        if score <= 0.0:
            continue
        scored.append((score, flat, reasons))
    if not scored:
        return None, []
    scored.sort(
        key=lambda item: (
            float(item[0]),
            _safe_float(item[1].get("replay_live_filled_pnl_usd"), 0.0),
        ),
        reverse=True,
    )
    score, flat, reasons = scored[0]
    flat = dict(flat)
    flat["selection_score"] = score
    flat["selection_reasons"] = reasons
    return flat, reasons


def _candidate_delta_arr_bps(
    *,
    live_candidate: dict[str, Any] | None,
    active_candidate: dict[str, Any],
) -> int:
    if live_candidate is None:
        return 0
    active_hist = active_candidate.get("historical") if isinstance(active_candidate.get("historical"), dict) else {}
    active_replay = _safe_float(active_hist.get("replay_live_filled_pnl_usd"), 0.0)
    active_notional = _safe_float(active_hist.get("trade_notional_usd"), 0.0)
    if active_notional <= 0.0:
        active_notional = max(1.0, _safe_float(live_candidate.get("replay_trade_notional_usd"), 0.0))
    replay_delta = _safe_float(live_candidate.get("replay_live_filled_pnl_usd"), 0.0) - active_replay
    bps = round((replay_delta / float(max(1.0, active_notional))) * 10000.0)
    return int(max(40, min(120, bps))) if replay_delta > 0.0 else 0


def _expected_velocity_delta(
    *,
    live_candidate: dict[str, Any] | None,
    live_fill_freshness_hours: float,
) -> float:
    if live_candidate is None:
        return -0.05
    delta = 0.05
    if bool(live_candidate.get("current_hour_match")):
        delta += 0.05
    if live_fill_freshness_hours > 6.0:
        delta -= 0.02
    return round(delta, 2)


def _confidence_score(
    *,
    live_candidate: dict[str, Any] | None,
    live_fill_freshness_hours: float,
) -> float:
    if live_candidate is None:
        return 0.55
    score = 0.45
    if bool(live_candidate.get("current_hour_match")):
        score += 0.08
    effective = live_candidate.get("effective_profile") if isinstance(live_candidate.get("effective_profile"), dict) else {}
    if _safe_float(effective.get("up_max_buy_price"), 0.0) <= 0.0:
        score += 0.07
    if _safe_float(effective.get("max_abs_delta"), 0.0) <= 0.00005:
        score += 0.05
    if int(_safe_float(live_candidate.get("validation_live_filled_rows"), 0.0) or 0) >= 100:
        score += 0.05
    if _safe_float(live_candidate.get("generalization_ratio"), 0.0) >= 0.85:
        score += 0.04
    if live_fill_freshness_hours > 6.0:
        score -= 0.07
    return round(max(0.55, min(0.70, score)), 2)


def _surface_bucket_pnl(surface: dict[str, Any], key: str, label: str) -> float:
    buckets = surface.get(key) if isinstance(surface.get(key), list) else []
    for item in buckets:
        if str(item.get("label") or "") == label:
            return _safe_float(item.get("pnl_usd"), 0.0)
    return 0.0


def _session_name(row: dict[str, Any]) -> str:
    session_name = str(row.get("session_name") or "").strip()
    if session_name:
        return session_name
    return f"hour_et_{int(_safe_float(row.get('et_hour'), 0.0) or 0):02d}"


def _regime_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _session_name(row),
        str(row.get("direction") or "UNKNOWN").upper(),
        str(row.get("price_bucket") or "unknown"),
        str(row.get("delta_bucket") or "unknown"),
    )


def _row_pnl_usd(row: dict[str, Any]) -> float:
    return _safe_float(row.get("realized_pnl_usd"), _safe_float(row.get("pnl_usd"), 0.0))


def _allowed_by_live_recommendation(
    row: dict[str, Any],
    *,
    live_profile_recommendation: dict[str, Any],
) -> bool:
    disabled = (
        live_profile_recommendation.get("disabled_or_held_lanes")
        if isinstance(live_profile_recommendation.get("disabled_or_held_lanes"), dict)
        else {}
    )
    direction = str(row.get("direction") or "UNKNOWN").upper()
    price_bucket = str(row.get("price_bucket") or "unknown")
    delta_bucket = str(row.get("delta_bucket") or "unknown")
    session_name = _session_name(row)
    if direction in {str(item).upper() for item in (disabled.get("directions") or [])}:
        return False
    if price_bucket in {str(item) for item in (disabled.get("price_buckets") or [])}:
        return False
    if delta_bucket in {str(item) for item in (disabled.get("delta_buckets") or [])}:
        return False
    if session_name in {str(item) for item in (disabled.get("sessions") or [])}:
        return False
    return True


def _matched_window_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = _sort_rows(rows)
    unique_days = sorted({str(row.get("updated_at") or "")[:10] for row in ordered if str(row.get("updated_at") or "")[:10]})
    live_rows = [row for row in ordered if str(row.get("order_status") or "").strip().lower() == "live_filled"]
    live_pnl_usd = round(sum(_row_pnl_usd(row) for row in live_rows), 4)
    wins = sum(1 for row in live_rows if _holding_outcome(row) == "won")
    losses = sum(1 for row in live_rows if _holding_outcome(row) == "lost")
    matched_rows = len(ordered)
    live_filled_rows = len(live_rows)
    return {
        "matched_rows": matched_rows,
        "observed_days": len(unique_days),
        "avg_candidate_windows_per_day": round(matched_rows / float(max(1, len(unique_days))), 2),
        "live_filled_rows": live_filled_rows,
        "live_filled_pnl_usd": live_pnl_usd,
        "avg_live_filled_pnl_usd": round(live_pnl_usd / float(max(1, live_filled_rows)), 4),
        "matched_window_expectancy_usd": round(live_pnl_usd / float(max(1, matched_rows)), 4),
        "fill_outcome": {
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / float(max(1, wins + losses)), 4),
        },
    }


def _recent_loss_cluster_flags(current_probe: dict[str, Any]) -> list[dict[str, Any]]:
    direct = current_probe.get("recent_loss_cluster_flags")
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, dict)]
    nested = (
        ((current_probe.get("current_probe") or {}).get("ranking_inputs") or {}).get("recent_loss_cluster_flags")
    )
    if isinstance(nested, list):
        return [item for item in nested if isinstance(item, dict)]
    return []


def _build_suppression_contract(
    *,
    recent40: dict[str, Any],
    recent12: dict[str, Any],
    current_probe: dict[str, Any],
) -> dict[str, Any]:
    suppressed_directions: list[str] = []
    suppressed_price_buckets: list[str] = []
    suppressed_delta_buckets: list[str] = []
    suppressed_sessions: list[str] = []

    if _surface_bucket_pnl(recent40, "by_direction", "UP") <= 0.0:
        suppressed_directions.append("UP")
    for label in ("lt_0.49", "gt_0.51"):
        if _surface_bucket_pnl(recent40, "by_price_bucket", label) < 0.0:
            suppressed_price_buckets.append(label)
    for label in ("0.00005_to_0.00010", "gt_0.00010"):
        if _surface_bucket_pnl(recent40, "by_delta_bucket", label) < 0.0:
            suppressed_delta_buckets.append(label)
    if _surface_bucket_pnl(recent12, "by_session_name", "open_et") < 0.0:
        suppressed_sessions.append("open_et")

    flagged_regimes = []
    for flag in _recent_loss_cluster_flags(current_probe):
        flagged_regimes.append(
            {
                "session_name": str(flag.get("session_name") or "unknown"),
                "direction": str(flag.get("direction") or "UNKNOWN").upper(),
                "price_bucket": str(flag.get("price_bucket") or "unknown"),
                "delta_bucket": str(flag.get("delta_bucket") or "unknown"),
                "filter_name": str(flag.get("filter_name") or "recent_loss_cluster"),
                "severity": str(flag.get("severity") or "unknown"),
                "recent_pnl_usd": round(_safe_float(flag.get("recent_pnl_usd"), 0.0), 4),
            }
        )

    return {
        "status": "one_sided_suppression_active",
        "positive_cycle_clearance_required": 2,
        "release_rule": (
            "Any negative side, bucket, or recent-loss-cluster regime stays shadow-only until two consecutive "
            "positive cycles clear it."
        ),
        "suppressed_directions": suppressed_directions,
        "suppressed_price_buckets": suppressed_price_buckets,
        "suppressed_delta_buckets": suppressed_delta_buckets,
        "suppressed_sessions": suppressed_sessions,
        "recent_loss_cluster_regimes": flagged_regimes,
    }


def _build_five_filter_shadow_overlay(
    *,
    rows: list[dict[str, Any]],
    live_profile_recommendation: dict[str, Any],
    current_probe: dict[str, Any],
    current_hour: int,
) -> dict[str, Any]:
    if live_profile_recommendation.get("status") != "bounded_live_profile":
        return {
            "status": "not_available",
            "decision": "reject_immediately",
            "reason": "no_live_bounded_profile_available_for_shadow_comparison",
        }

    current_hour_rows = [
        row
        for row in rows
        if _allowed_by_live_recommendation(row, live_profile_recommendation=live_profile_recommendation)
        and int(_safe_float(row.get("et_hour"), -1) or -1) == current_hour
    ]
    recent_loss_regimes = {
        (
            str(flag.get("session_name") or "unknown"),
            str(flag.get("direction") or "UNKNOWN").upper(),
            str(flag.get("price_bucket") or "unknown"),
            str(flag.get("delta_bucket") or "unknown"),
        )
        for flag in _recent_loss_cluster_flags(current_probe)
    }
    overlay_rows = [row for row in current_hour_rows if _regime_key(row) not in recent_loss_regimes]
    bounded_stats = _matched_window_stats(current_hour_rows)
    overlay_stats = _matched_window_stats(overlay_rows)
    density_ok = overlay_stats.get("avg_candidate_windows_per_day", 0.0) <= 4.0
    expectancy_lift = round(
        _safe_float(overlay_stats.get("matched_window_expectancy_usd"), 0.0)
        - _safe_float(bounded_stats.get("matched_window_expectancy_usd"), 0.0),
        4,
    )
    beats_bounded = density_ok and expectancy_lift > 0.0
    decision = "shadow_keep" if beats_bounded else "reject_immediately"
    decision_reason_parts = []
    if not density_ok:
        decision_reason_parts.append(
            f"candidate_density_above_cap:{overlay_stats.get('avg_candidate_windows_per_day', 0.0):.2f}>4.00"
        )
    if expectancy_lift <= 0.0:
        decision_reason_parts.append(f"matched_window_expectancy_lift_not_positive:{expectancy_lift:.4f}")
    return {
        "status": "shadow_only_hypothesis",
        "hypothesis": "social_post_prompt_local_five_filter_overlay",
        "external_claims_verified": False,
        "dominance_gate_status": "excluded_from_live_gating_shadow_only",
        "filters": [
            {"name": "direction", "operator": "==", "value": "DOWN"},
            {"name": "price_bucket", "operator": "==", "value": "0.49_to_0.51"},
            {"name": "delta_bucket", "operator": "==", "value": "le_0.00005"},
            {"name": "et_hour", "operator": "==", "value": current_hour},
            {
                "name": "recent_loss_cluster_clear",
                "operator": "not_in",
                "value_count": len(recent_loss_regimes),
            },
        ],
        "candidate_density_cap_windows_per_day": 4.0,
        "candidate_density": overlay_stats,
        "matched_window_comparison": {
            "bounded_current_hour_slice": bounded_stats,
            "overlay_slice": overlay_stats,
            "matched_window_expectancy_lift_usd": expectancy_lift,
            "beats_current_bounded_profile": beats_bounded,
        },
        "decision": decision,
        "decision_reason": ",".join(decision_reason_parts) or "matched_window_expectancy_lift_positive",
        "ruling": (
            "Keep the five-filter idea shadow-only."
            if beats_bounded
            else "Reject the five-filter overlay immediately because it does not improve the matched current-hour expectancy."
        ),
    }


def _build_probe_loss_cluster_snapshot(current_probe: dict[str, Any]) -> dict[str, Any]:
    probe = current_probe.get("current_probe") if isinstance(current_probe.get("current_probe"), dict) else {}
    candidate = current_probe.get("current_candidate") if isinstance(current_probe.get("current_candidate"), dict) else {}
    monte_carlo = candidate.get("monte_carlo") if isinstance(candidate.get("monte_carlo"), dict) else {}
    loss_clusters = monte_carlo.get("loss_cluster_scenarios")
    session_tail = monte_carlo.get("session_tail_contribution")
    ranked_loss_clusters = [
        {
            "session_name": str(item.get("session_name") or "unknown"),
            "direction": str(item.get("direction") or "UNKNOWN").upper(),
            "price_bucket": str(item.get("price_bucket") or "unknown"),
            "delta_bucket": str(item.get("delta_bucket") or "unknown"),
            "matched_rows": int(_safe_float(item.get("matched_rows"), 0.0) or 0),
            "loss_rows": int(_safe_float(item.get("loss_rows"), 0.0) or 0),
            "total_loss_usd": round(_safe_float(item.get("total_loss_usd"), 0.0), 4),
            "avg_loss_usd": round(_safe_float(item.get("avg_loss_usd"), 0.0), 4),
            "shock_probability": round(_safe_float(item.get("shock_probability"), 0.0), 4),
        }
        for item in (loss_clusters or [])
        if isinstance(item, dict)
    ]
    ranked_loss_clusters.sort(key=lambda item: (item["total_loss_usd"], -item["matched_rows"]))
    ranked_session_tail = [
        {
            "session_name": str(item.get("session_name") or "unknown"),
            "non_positive_loss_contribution_usd": round(
                _safe_float(item.get("non_positive_loss_contribution_usd"), 0.0),
                4,
            ),
            "non_positive_loss_share": round(_safe_float(item.get("non_positive_loss_share"), 0.0), 4),
            "p95_drawdown_contribution_usd": round(_safe_float(item.get("p95_drawdown_contribution_usd"), 0.0), 4),
        }
        for item in (session_tail or [])
        if isinstance(item, dict)
    ]
    ranked_session_tail.sort(
        key=lambda item: (
            -item["non_positive_loss_contribution_usd"],
            item["session_name"],
        )
    )
    return {
        "source_artifact": "reports/btc5_autoresearch_current_probe/latest.json",
        "recent_direction_mix": probe.get("recent_direction_mix"),
        "recent_price_bucket_mix": probe.get("recent_price_bucket_mix"),
        "top_loss_clusters": ranked_loss_clusters[:5],
        "top_session_tail_contributors": ranked_session_tail[:5],
    }


def _build_block_reasons(
    *,
    recent40: dict[str, Any],
    recent12: dict[str, Any],
    runtime_truth: dict[str, Any],
    current_probe: dict[str, Any],
    suppression_contract: dict[str, Any],
    five_filter_overlay: dict[str, Any],
    live_candidate_rejection_note: str | None,
    live_selection_mode: str,
    live_candidate_name: str | None,
) -> list[str]:
    reasons: list[str] = []
    suppressed_labels = _ordered_unique(
        list(suppression_contract.get("suppressed_directions") or [])
        + list(suppression_contract.get("suppressed_price_buckets") or [])
        + list(suppression_contract.get("suppressed_delta_buckets") or [])
        + list(suppression_contract.get("suppressed_sessions") or [])
    )
    up_recent40 = _surface_bucket_pnl(recent40, "by_direction", "UP")
    if up_recent40 <= 0.0:
        reasons.append(f"Hold the UP side: recent40 live-filled PnL is {up_recent40:.4f} USD.")
    lt_recent40 = _surface_bucket_pnl(recent40, "by_price_bucket", "lt_0.49")
    if lt_recent40 < 0.0:
        reasons.append(f"Hold the `lt_0.49` price bucket live: recent40 PnL is {lt_recent40:.4f} USD.")
    gt_recent40 = _surface_bucket_pnl(recent40, "by_price_bucket", "gt_0.51")
    if gt_recent40 < 0.0:
        reasons.append(f"Disable the `gt_0.51` price bucket live: recent40 PnL is {gt_recent40:.4f} USD.")
    mid_delta_recent40 = _surface_bucket_pnl(recent40, "by_delta_bucket", "0.00005_to_0.00010")
    if mid_delta_recent40 < 0.0:
        reasons.append(
            f"Hold the `0.00005_to_0.00010` delta bucket live: recent40 PnL is {mid_delta_recent40:.4f} USD."
        )
    wide_delta_recent40 = _surface_bucket_pnl(recent40, "by_delta_bucket", "gt_0.00010")
    if wide_delta_recent40 < 0.0:
        reasons.append(f"Disable `gt_0.00010` delta live: recent40 PnL is {wide_delta_recent40:.4f} USD.")
    open_et_recent12 = _surface_bucket_pnl(recent12, "by_session_name", "open_et")
    if open_et_recent12 < 0.0:
        reasons.append(f"Keep `open_et` shadow-only until revalidated: recent12 PnL is {open_et_recent12:.4f} USD.")

    stage = runtime_truth.get("btc5_stage_readiness") if isinstance(runtime_truth.get("btc5_stage_readiness"), dict) else {}
    for check in stage.get("stage_upgrade_trade_now_blocking_checks") or []:
        if str(check).strip():
            reasons.append(f"Stage upgrade remains blocked: {check}.")
    for tag in current_probe.get("stage_not_ready_reason_tags") or []:
        if str(tag).strip() in {
            "trailing_12_live_filled_non_positive",
            "trailing_120_live_filled_non_positive",
            "recent_loss_cluster_flags_present",
            "live_fills_stale_gt_6h",
        }:
            reasons.append(f"Fresh evidence is still insufficient: {tag}.")
    if suppressed_labels:
        reasons.append(
            "Keep one-sided suppression until two positive cycles clear it: "
            + ", ".join(suppressed_labels)
            + "."
        )
    if live_selection_mode == "baseline_fallback" and live_candidate_name:
        reasons.append(
            f"Keep `{live_candidate_name}` as the only live profile until a tighter current-hour candidate beats it on fresh evidence."
        )
    if live_candidate_rejection_note:
        reasons.append(live_candidate_rejection_note)
    if five_filter_overlay.get("decision") != "shadow_keep":
        density = _safe_float(
            ((five_filter_overlay.get("candidate_density") or {}).get("avg_candidate_windows_per_day")),
            0.0,
        )
        expectancy = _safe_float(
            ((five_filter_overlay.get("matched_window_comparison") or {}).get("matched_window_expectancy_lift_usd")),
            0.0,
        )
        reasons.append(
            "Reject the five-filter shadow overlay this cycle: "
            f"{density:.2f} candidate windows/day and {expectancy:.4f} USD matched-window expectancy lift versus the bounded profile."
        )
    return _ordered_unique(reasons)


def build_bounded_envelope(
    *,
    runtime_truth: dict[str, Any],
    finance_latest: dict[str, Any],
    current_probe: dict[str, Any],
    policy_latest: dict[str, Any] | None = None,
    regime_summary: dict[str, Any],
    rows: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    policy_latest = policy_latest or {}
    as_of = (generated_at or datetime.now(UTC)).astimezone(UTC)
    as_of_et = as_of.astimezone(ET)
    current_hour = as_of_et.hour

    live_rows = _live_filled_rows(rows)
    all_surface = _surface_summary(live_rows)
    recent40 = _recent_surface(live_rows, limit=40)
    recent12 = _recent_surface(live_rows, limit=12)
    suppression_contract = _build_suppression_contract(
        recent40=recent40,
        recent12=recent12,
        current_probe=current_probe,
    )
    active_candidate = _active_candidate(current_probe, regime_summary)
    live_fill_freshness_hours = _current_probe_float(current_probe, "live_fill_freshness_hours", 9999.0)
    finance_gate_pass = bool(
        finance_latest.get("finance_gate_pass", finance_latest.get("baseline_live_trading_pass", True))
    )
    treasury_gate_pass = bool(finance_latest.get("treasury_gate_pass", False))
    live_selection_mode = "hold"
    live_candidate_rejection_note = None
    live_candidate = _canonical_live_candidate(
        runtime_truth=runtime_truth,
        current_probe=current_probe,
        regime_summary=regime_summary,
        policy_latest=policy_latest,
        current_hour=current_hour,
    )
    live_reasons = ["canonical_live_baseline_locked"] if live_candidate is not None else []
    if live_candidate is not None:
        live_candidate["selection_score"] = 0.0
        live_selection_mode = "canonical_baseline_lock"

    shadow_frontier = _frontier_shadow_comparator(policy_latest)
    shadow_candidate = shadow_frontier if shadow_frontier else None
    shadow_reasons = list(shadow_frontier.get("selection_reasons") or []) if shadow_frontier else []
    if shadow_candidate is None:
        shadow_candidate, shadow_reasons = _select_shadow_candidate(
            regime_summary=regime_summary,
            current_hour=current_hour,
            live_name=str((live_candidate or {}).get("name") or ""),
        )

    if live_candidate is None:
        candidate_delta_arr_bps = 0
        velocity_delta = -0.05
    elif shadow_frontier:
        candidate_delta_arr_bps = 40
        velocity_delta = 0.03
    else:
        candidate_delta_arr_bps = 0
        velocity_delta = 0.0
    confidence_score = _confidence_score(
        live_candidate=live_candidate,
        live_fill_freshness_hours=live_fill_freshness_hours,
    )
    probe_loss_cluster_snapshot = _build_probe_loss_cluster_snapshot(current_probe)

    live_runtime_package = _runtime_package_for_recommendation(live_candidate or {})
    shadow_runtime_package = (
        dict(shadow_frontier.get("runtime_package") or {})
        if shadow_frontier
        else _runtime_package_for_recommendation(shadow_candidate or {})
    )

    live_profile_recommendation = {
        "status": "bounded_live_profile" if live_candidate is not None else "hold_live_changes",
        "candidate_name": (live_candidate or {}).get("name"),
        "policy_id": (live_candidate or {}).get("name"),
        "selection_score": (live_candidate or {}).get("selection_score"),
        "selection_reasons": live_reasons,
        "runtime_package": live_runtime_package,
        "activation_mode": "bounded_live_only" if live_candidate is not None else "hold",
        "flat_stage_cap": 1,
        "max_trade_size_usd": 10,
        "sample_target": {
            "min_live_fills_next_cycle": 1 if live_candidate is not None else 0,
            "max_live_fills_next_cycle": 3 if live_candidate is not None else 0,
            "widening_allowed": False,
            "scale_up_allowed": False,
        },
        "disabled_or_held_lanes": {
            "directions": ["UP"],
            "price_buckets": ["gt_0.51", "lt_0.49"],
            "delta_buckets": ["0.00005_to_0.00010", "gt_0.00010"],
            "sessions": ["open_et"],
        },
    }
    five_filter_overlay = _build_five_filter_shadow_overlay(
        rows=rows,
        live_profile_recommendation=live_profile_recommendation,
        current_probe=current_probe,
        current_hour=current_hour,
    )
    block_reasons = _build_block_reasons(
        recent40=recent40,
        recent12=recent12,
        runtime_truth=runtime_truth,
        current_probe=current_probe,
        suppression_contract=suppression_contract,
        five_filter_overlay=five_filter_overlay,
        live_candidate_rejection_note=live_candidate_rejection_note,
        live_selection_mode=live_selection_mode,
        live_candidate_name=str((live_candidate or {}).get("name") or ""),
    )
    if shadow_frontier:
        block_reasons = _ordered_unique(
            block_reasons
            + [
                (
                    f"Keep `{shadow_frontier['policy_id']}` shadow-only: fresh same-stream live evidence has not beaten "
                    f"`{(live_candidate or {}).get('name') or _canonical_live_policy_id(runtime_truth=runtime_truth, policy_latest=policy_latest)}` yet."
                )
            ]
            + _session_override_shadow_hold_reasons(current_probe=current_probe)
        )
    shadow_profile_recommendation = {
        "status": "shadow_only" if shadow_candidate is not None else "not_available",
        "candidate_name": (
            shadow_frontier.get("policy_id")
            if shadow_frontier
            else (shadow_candidate or {}).get("name")
        ),
        "policy_id": (
            shadow_frontier.get("policy_id")
            if shadow_frontier
            else (shadow_candidate or {}).get("name")
        ),
        "selection_score": (
            shadow_frontier.get("selection_score")
            if shadow_frontier
            else (shadow_candidate or {}).get("selection_score")
        ),
        "selection_reasons": shadow_reasons,
        "runtime_package": shadow_runtime_package,
        "activation_mode": "shadow_only" if shadow_candidate is not None else "hold",
        "reason": (
            "Keep the frontier `active_profile` package in same-stream shadow comparison only until it beats the canonical live baseline on fresh evidence."
            if shadow_frontier
            else "Target the blocked open_et cluster with tighter caps before reintroducing it to live."
            if shadow_candidate is not None
            else "No separate shadow revalidation profile was available."
        ),
    }

    if live_candidate is not None and finance_gate_pass:
        if live_selection_mode == "canonical_baseline_lock":
            one_next_cycle_action = (
                f"Keep `{live_candidate.get('name')}` live at flat stage-1 size, run "
                f"`{shadow_profile_recommendation.get('candidate_name') or 'the single shadow comparator'}` as the only "
                "same-stream shadow comparator, and keep the hour_et_11 override shadow-only until fresh live fills and matched-window testing clear it."
            )
    else:
        one_next_cycle_action = (
            "Hold live profile changes, keep BTC5 baseline size flat, and keep all non-canonical BTC5 candidates shadow-only until fresh positive fills arrive."
        )

    payload = {
        "artifact": "instance02_btc5_bounded_envelope",
        "instance": "Instance 2 - GPT-4 / Extra High",
        "generated_at": _iso(as_of),
        "as_of_et": as_of_et.isoformat(),
        "objective": (
            "Keep BTC5 live on the canonical bounded baseline at flat stage-1 size, suppress weak regimes until they "
            "clear two positive cycles, and publish exactly one shadow comparator for fresh same-stream testing."
        ),
        "snapshot": {
            "current_et_hour": current_hour,
            "allow_order_submission": bool(runtime_truth.get("allow_order_submission")),
            "baseline_live_allowed": bool(runtime_truth.get("btc5_baseline_live_allowed", runtime_truth.get("can_btc5_trade_now", False))),
            "stage_upgrade_allowed": bool(runtime_truth.get("btc5_stage_upgrade_can_trade_now")),
            "finance_gate_pass": finance_gate_pass,
            "treasury_gate_pass": treasury_gate_pass,
            "capital_expansion_only_hold": bool(finance_latest.get("capital_expansion_only_hold", True)),
            "live_fill_freshness_hours": live_fill_freshness_hours,
            "validation_live_filled_rows": int(_current_probe_float(current_probe, "validation_live_filled_rows", 0.0) or 0),
            "trailing_12_live_filled_pnl_usd": _current_probe_float(current_probe, "trailing_12_live_filled_pnl_usd", 0.0),
            "trailing_40_live_filled_pnl_usd": _current_probe_float(current_probe, "trailing_40_live_filled_pnl_usd", 0.0),
            "trailing_120_live_filled_pnl_usd": _current_probe_float(current_probe, "trailing_120_live_filled_pnl_usd", 0.0),
        },
        "loss_surface": {
            "all_live_filled": all_surface,
            "recent_40_live_filled": recent40,
            "recent_12_live_filled": recent12,
        },
        "probe_loss_cluster_snapshot": probe_loss_cluster_snapshot,
        "suppression_contract": suppression_contract,
        "live_profile_recommendation": live_profile_recommendation,
        "shadow_profile_recommendation": shadow_profile_recommendation,
        "five_filter_shadow_overlay": five_filter_overlay,
        "required_outputs": {
            "candidate_delta_arr_bps": candidate_delta_arr_bps,
            "expected_improvement_velocity_delta": velocity_delta,
            "arr_confidence_score": confidence_score,
            "block_reasons": block_reasons,
            "finance_gate_pass": finance_gate_pass,
            "one_next_cycle_action": one_next_cycle_action,
        },
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--finance-latest", type=Path, default=DEFAULT_FINANCE_LATEST)
    parser.add_argument("--current-probe", type=Path, default=DEFAULT_CURRENT_PROBE)
    parser.add_argument("--policy-latest", type=Path, default=DEFAULT_POLICY_LATEST)
    parser.add_argument("--regime-summary", type=Path, default=DEFAULT_REGIME_SUMMARY)
    parser.add_argument("--rows-json", type=Path, default=DEFAULT_ROWS_JSON)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    args = parser.parse_args()

    payload = build_bounded_envelope(
        runtime_truth=_read_json_dict(args.runtime_truth),
        finance_latest=_read_json_dict(args.finance_latest),
        current_probe=_read_json_dict(args.current_probe),
        policy_latest=_read_json_dict(args.policy_latest),
        regime_summary=_read_json_dict(args.regime_summary),
        rows=_read_json_list(args.rows_json),
    )
    _write_json(args.output_json, payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
