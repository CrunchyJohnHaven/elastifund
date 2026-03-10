#!/usr/bin/env python3
"""Run one BTC5 autoresearch cycle and optionally promote a better profile."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo import (  # noqa: E402
    GuardrailProfile,
    _safe_float,
    assemble_observed_rows,
    build_summary as build_global_summary,
)
from scripts.btc5_regime_policy_lab import build_summary as build_regime_policy_summary  # noqa: E402


DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BASE_ENV = Path("config/btc5_strategy.env")
DEFAULT_OVERRIDE_ENV = Path("state/btc5_autoresearch.env")
DEFAULT_REPORT_DIR = Path("reports/btc5_autoresearch")
DEFAULT_SERVICE_NAME = "btc-5min-maker.service"
DEFAULT_HYPOTHESIS_SUMMARY = Path("reports/btc5_hypothesis_lab/summary.json")
DEFAULT_REGIME_POLICY_SUMMARY = Path("reports/btc5_regime_policy_lab/summary.json")
DEFAULT_CURRENT_PROBE_LATEST = Path("reports/btc5_autoresearch_current_probe/latest.json")
DEFAULT_RUNTIME_TRUTH = Path("reports/runtime_truth_latest.json")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now_utc().strftime("%Y%m%dT%H%M%SZ")


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _parse_iso_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _confidence_rank(label: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(label).strip().lower(), 0)


def _deploy_rank(label: str) -> int:
    return {"promote": 3, "shadow_only": 2, "hold": 1}.get(str(label).strip().lower(), 0)


def _extract_forecast_candidate(payload: dict[str, Any] | None, *, source_artifact: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    arr = payload.get("arr_tracking") or {}
    generated_at = _parse_iso_timestamp(payload.get("generated_at"))
    confidence_label = str(payload.get("package_confidence_label") or "low")
    deploy_recommendation = str(payload.get("deploy_recommendation") or "hold")
    return {
        "source_artifact": source_artifact,
        "generated_at": generated_at.isoformat() if generated_at else "",
        "forecast_active_arr_pct": _safe_float(arr.get("current_median_arr_pct"), 0.0),
        "forecast_best_arr_pct": _safe_float(arr.get("best_median_arr_pct"), 0.0),
        "forecast_arr_delta_pct": _safe_float(arr.get("median_arr_delta_pct"), 0.0),
        "package_confidence_label": confidence_label,
        "package_confidence_reasons": list(payload.get("package_confidence_reasons") or []),
        "deploy_recommendation": deploy_recommendation,
        "validation_live_filled_rows": int(payload.get("validation_live_filled_rows") or 0),
        "generalization_ratio": _safe_float(payload.get("generalization_ratio"), 0.0),
        "best_runtime_package": payload.get("best_runtime_package") or {},
        "active_runtime_package": payload.get("active_runtime_package") or {},
    }


def _select_public_forecast(
    *,
    standard_payload: dict[str, Any] | None,
    current_probe_payload: dict[str, Any] | None,
    standard_source: str,
    current_probe_source: str,
) -> dict[str, Any]:
    now = _now_utc()
    candidates: list[dict[str, Any]] = []
    standard = _extract_forecast_candidate(standard_payload, source_artifact=standard_source)
    current_probe = _extract_forecast_candidate(current_probe_payload, source_artifact=current_probe_source)
    if standard:
        candidates.append(standard)
    if current_probe:
        candidates.append(current_probe)
    if not candidates:
        return {
            "selected": None,
            "candidates": [],
            "selection_reason": "no_forecast_artifacts_available",
        }

    for candidate in candidates:
        generated = _parse_iso_timestamp(candidate.get("generated_at"))
        age_hours = ((now - generated).total_seconds() / 3600.0) if generated else 9999.0
        candidate["age_hours"] = round(max(0.0, age_hours), 4)
        candidate["is_fresh_6h"] = bool(generated and age_hours <= 6.0)

    fresh = [item for item in candidates if item.get("is_fresh_6h")]
    pool = fresh or candidates
    pool.sort(
        key=lambda item: (
            _confidence_rank(str(item.get("package_confidence_label") or "")),
            _deploy_rank(str(item.get("deploy_recommendation") or "")),
            _parse_iso_timestamp(item.get("generated_at")) or datetime.fromtimestamp(0, tz=timezone.utc),
        ),
        reverse=True,
    )
    selected = pool[0]
    selection_reason = (
        "selected_from_fresh_pool_by_confidence_then_deploy_then_generated_at"
        if fresh
        else "no_fresh_artifacts_within_6h_selected_best_available"
    )
    return {
        "selected": selected,
        "candidates": candidates,
        "selection_reason": selection_reason,
    }


def _merged_strategy_env(base_env: Path, override_env: Path) -> dict[str, str]:
    merged = _load_env_file(base_env)
    merged.update(_load_env_file(override_env))
    return merged


def _profile_from_env(name: str, env: dict[str, str]) -> GuardrailProfile:
    return GuardrailProfile(
        name=name,
        max_abs_delta=_safe_float(env.get("BTC5_MAX_ABS_DELTA"), 0.0) or None,
        up_max_buy_price=_safe_float(env.get("BTC5_UP_MAX_BUY_PRICE"), 0.0) or None,
        down_max_buy_price=_safe_float(env.get("BTC5_DOWN_MAX_BUY_PRICE"), 0.0) or None,
        note="loaded from strategy env",
    )


def _arr_for_candidate(candidate: dict[str, Any] | None) -> dict[str, float]:
    continuation = (candidate or {}).get("continuation") or {}
    return {
        "historical_arr_pct": _safe_float(continuation.get("historical_arr_pct"), 0.0),
        "median_arr_pct": _safe_float(continuation.get("median_arr_pct"), 0.0),
        "p05_arr_pct": _safe_float(continuation.get("p05_arr_pct"), 0.0),
    }


def _arr_tracking(best: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    best_arr = _arr_for_candidate(best)
    current_arr = _arr_for_candidate(current)
    return {
        "metric_name": "continuation_arr_pct",
        "current_historical_arr_pct": round(current_arr["historical_arr_pct"], 4),
        "current_median_arr_pct": round(current_arr["median_arr_pct"], 4),
        "current_p05_arr_pct": round(current_arr["p05_arr_pct"], 4),
        "best_historical_arr_pct": round(best_arr["historical_arr_pct"], 4),
        "best_median_arr_pct": round(best_arr["median_arr_pct"], 4),
        "best_p05_arr_pct": round(best_arr["p05_arr_pct"], 4),
        "historical_arr_delta_pct": round(best_arr["historical_arr_pct"] - current_arr["historical_arr_pct"], 4),
        "median_arr_delta_pct": round(best_arr["median_arr_pct"] - current_arr["median_arr_pct"], 4),
        "p05_arr_delta_pct": round(best_arr["p05_arr_pct"] - current_arr["p05_arr_pct"], 4),
    }


def _find_candidate(summary: dict[str, Any], name: str) -> dict[str, Any] | None:
    for candidate in summary.get("candidates") or []:
        if candidate.get("profile", {}).get("name") == name:
            return candidate
    return None


def _session_override_sort_key(item: dict[str, Any]) -> tuple[int, tuple[int, ...], str]:
    hours = tuple(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int))
    return (len(hours), hours, str(item.get("session_name") or ""))


def _normalized_session_overrides(overrides: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in overrides or []:
        if not isinstance(item, dict):
            continue
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        hours = sorted(
            {
                int(hour)
                for hour in (item.get("et_hours") or [])
                if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
            }
        )
        if not hours:
            continue
        normalized.append(
            {
                "session_name": str(item.get("session_name") or "").strip(),
                "et_hours": hours,
                "profile": {
                    "name": str(profile.get("name") or "").strip(),
                    "max_abs_delta": _safe_float(profile.get("max_abs_delta"), 0.0) or None,
                    "up_max_buy_price": _safe_float(profile.get("up_max_buy_price"), 0.0) or None,
                    "down_max_buy_price": _safe_float(profile.get("down_max_buy_price"), 0.0) or None,
                },
            }
        )
    normalized.sort(key=_session_override_sort_key)
    return normalized


def _runtime_session_policy_from_overrides(overrides: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    runtime_policy: list[dict[str, Any]] = []
    for item in _normalized_session_overrides(overrides):
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        record: dict[str, Any] = {
            "name": str(item.get("session_name") or profile.get("name") or "session_policy").strip(),
            "et_hours": list(item.get("et_hours") or []),
        }
        max_abs_delta = profile.get("max_abs_delta")
        up_max_buy_price = profile.get("up_max_buy_price")
        down_max_buy_price = profile.get("down_max_buy_price")
        if max_abs_delta is not None:
            record["max_abs_delta"] = _safe_float(max_abs_delta, 0.0) or 0.0
        if up_max_buy_price is not None:
            record["up_max_buy_price"] = _safe_float(up_max_buy_price, 0.0) or 0.0
        if down_max_buy_price is not None:
            record["down_max_buy_price"] = _safe_float(down_max_buy_price, 0.0) or 0.0
        runtime_policy.append(record)
    return runtime_policy


def _runtime_session_policy_from_env(env: dict[str, str]) -> list[dict[str, Any]]:
    raw = str(env.get("BTC5_SESSION_POLICY_JSON") or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        hours = item.get("et_hours")
        if not name or not isinstance(hours, list):
            continue
        out.append(dict(item))
    return out


def _normalize_global_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    profile = dict(candidate.get("profile") or {})
    return {
        **candidate,
        "candidate_family": "global_profile",
        "profile": profile,
        "base_profile": dict(profile),
        "session_overrides": [],
        "recommended_session_policy": [],
    }


def _normalize_regime_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    policy = candidate.get("policy") or {}
    base_profile = dict(policy.get("default_profile") or {})
    session_overrides = _normalized_session_overrides((policy.get("overrides") or []))
    profile = dict(base_profile)
    profile["name"] = str(policy.get("name") or base_profile.get("name") or "session_policy")
    return {
        "candidate_family": "regime_policy",
        "profile": profile,
        "base_profile": base_profile,
        "session_overrides": session_overrides,
        "recommended_session_policy": _runtime_session_policy_from_overrides(session_overrides),
        "historical": candidate.get("historical") or {},
        "monte_carlo": candidate.get("monte_carlo") or {},
        "continuation": candidate.get("continuation") or {},
        "scoring": candidate.get("scoring") or {},
        "policy": policy,
    }


def _candidate_identity(candidate: dict[str, Any] | None) -> tuple[Any, ...]:
    if candidate is None:
        return tuple()
    base_profile = (candidate.get("base_profile") or candidate.get("profile") or {})
    return (
        _safe_float(base_profile.get("max_abs_delta"), 0.0) or None,
        _safe_float(base_profile.get("up_max_buy_price"), 0.0) or None,
        _safe_float(base_profile.get("down_max_buy_price"), 0.0) or None,
        tuple(
            (
                item.get("session_name"),
                tuple(item.get("et_hours") or []),
                (item.get("profile") or {}).get("max_abs_delta"),
                (item.get("profile") or {}).get("up_max_buy_price"),
                (item.get("profile") or {}).get("down_max_buy_price"),
            )
            for item in _normalized_session_overrides(candidate.get("session_overrides"))
        ),
    )


def _runtime_package(
    *,
    profile: dict[str, Any] | None,
    session_policy: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "profile": dict(profile or {}),
        "session_policy": list(session_policy or []),
    }


def _package_signature(package: dict[str, Any] | None) -> tuple[Any, ...]:
    package = package or {}
    profile = package.get("profile") if isinstance(package.get("profile"), dict) else {}
    policy = package.get("session_policy") if isinstance(package.get("session_policy"), list) else []
    normalized_policy: list[tuple[Any, ...]] = []
    for item in policy:
        if not isinstance(item, dict):
            continue
        hours = tuple(sorted(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int)))
        normalized_policy.append(
            (
                str(item.get("name") or ""),
                hours,
                _safe_float(item.get("max_abs_delta"), None),
                _safe_float(item.get("up_max_buy_price"), None),
                _safe_float(item.get("down_max_buy_price"), None),
            )
        )
    normalized_policy.sort()
    return (
        str(profile.get("name") or ""),
        _safe_float(profile.get("max_abs_delta"), None),
        _safe_float(profile.get("up_max_buy_price"), None),
        _safe_float(profile.get("down_max_buy_price"), None),
        tuple(normalized_policy),
    )


def _live_fill_windows(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    live = [row for row in rows if str(row.get("order_status") or "").strip().lower() == "live_filled"]
    live.sort(key=lambda row: int(row.get("window_start_ts") or row.get("timestamp") or 0))

    def summarize(count: int) -> dict[str, float]:
        sample = live[-count:] if len(live) >= count else list(live)
        fills = len(sample)
        pnl = sum(_safe_float(row.get("pnl_usd"), 0.0) for row in sample)
        if fills >= 2:
            first_ts = int(sample[0].get("window_start_ts") or sample[0].get("timestamp") or 0)
            last_ts = int(sample[-1].get("window_start_ts") or sample[-1].get("timestamp") or 0)
            hours = max(0.0, (last_ts - first_ts) / 3600.0)
        else:
            hours = 0.0
        return {
            "fills": fills,
            "pnl_usd": round(pnl, 4),
            "hours": round(hours, 4),
            "net_positive": bool(pnl > 0.0),
        }

    return {
        "trailing_5": summarize(5),
        "trailing_12": summarize(12),
        "trailing_20": summarize(20),
    }


def _fund_reconciliation_blocked(runtime_truth: dict[str, Any] | None) -> tuple[bool, list[str]]:
    launch = (runtime_truth or {}).get("launch") or {}
    blocked_checks = [str(item) for item in (launch.get("blocked_checks") or []) if item]
    reconciliation_flags = {"accounting_reconciliation_drift", "polymarket_capital_truth_drift"}
    active = sorted([item for item in blocked_checks if item in reconciliation_flags])
    return (len(active) > 0, active)


def _capital_scale_recommendation(
    *,
    package_confidence_label: str,
    trailing: dict[str, dict[str, float]],
    promoted_package_selected: bool,
    fund_reconciliation_blocked: bool,
    fund_block_reasons: list[str],
) -> dict[str, Any]:
    trailing_5 = trailing.get("trailing_5") or {}
    trailing_12 = trailing.get("trailing_12") or {}
    trailing_20 = trailing.get("trailing_20") or {}
    conf_high = str(package_confidence_label).strip().lower() == "high"
    positive_12 = bool(trailing_12.get("net_positive"))
    positive_20 = bool(trailing_20.get("net_positive"))

    status = "hold"
    tranche = 0
    basis = trailing_5
    reason = "confidence_or_live_fill_window_not_sufficient_for_capital_add"

    if conf_high and positive_12 and positive_20 and promoted_package_selected and not fund_reconciliation_blocked:
        status = "scale_add"
        tranche = 1000
        basis = trailing_20
        reason = "high_confidence_and_trailing20_12_positive_with_promoted_package_selected"
    elif conf_high and positive_12 and fund_reconciliation_blocked:
        status = "test_add"
        tranche = 100
        basis = trailing_12
        reason = "high_confidence_and_trailing12_positive_but_fund_reconciliation_blocks_full_scale"
    elif conf_high and positive_12 and not promoted_package_selected:
        status = "hold"
        tranche = 0
        basis = trailing_12
        reason = "promoted_package_not_currently_selected"

    return {
        "status": status,
        "recommended_tranche_usd": tranche,
        "basis_window_fills": int(basis.get("fills") or 0),
        "basis_window_pnl_usd": round(_safe_float(basis.get("pnl_usd"), 0.0), 4),
        "basis_window_hours": round(_safe_float(basis.get("hours"), 0.0), 4),
        "reason": reason,
        "promoted_package_selected": bool(promoted_package_selected),
        "fund_reconciliation_blocked": bool(fund_reconciliation_blocked),
        "fund_blocking_checks": list(fund_block_reasons),
        "trailing_windows": trailing,
    }


def _extract_validation_rows(candidate: dict[str, Any] | None) -> int:
    if not isinstance(candidate, dict):
        return 0
    scoring = candidate.get("scoring") or {}
    historical = candidate.get("historical") or {}
    for source in (scoring, historical):
        for key in ("validation_live_filled_rows", "replay_live_filled_rows", "baseline_live_filled_rows"):
            value = source.get(key)
            if value is None:
                continue
            return max(0, int(_safe_float(value, 0.0) or 0))
    return 0


def _extract_generalization_ratio(
    candidate: dict[str, Any] | None,
    *,
    hypothesis_summary: dict[str, Any] | None,
) -> float:
    if isinstance(candidate, dict):
        scoring = candidate.get("scoring") or {}
        continuation = candidate.get("continuation") or {}
        for source in (scoring, continuation):
            value = _safe_float(source.get("generalization_ratio"), None)
            if value is not None:
                return float(value)

    if isinstance(hypothesis_summary, dict):
        # Prefer best_hypothesis summary from the latest hypothesis lab when available.
        best_hypothesis = hypothesis_summary.get("best_hypothesis") or {}
        summary = best_hypothesis.get("summary") if isinstance(best_hypothesis, dict) else {}
        if isinstance(summary, dict):
            value = _safe_float(summary.get("generalization_ratio"), None)
            if value is not None:
                return float(value)
        value = _safe_float(hypothesis_summary.get("generalization_ratio"), None)
        if value is not None:
            return float(value)
    return 0.0


def _package_confidence(
    *,
    validation_live_filled_rows: int,
    generalization_ratio: float,
) -> tuple[str, list[str]]:
    reasons = [
        f"validation_live_filled_rows={int(validation_live_filled_rows)}",
        f"generalization_ratio={float(generalization_ratio):.4f}",
    ]
    if validation_live_filled_rows >= 12 and generalization_ratio >= 0.80:
        return "high", reasons
    if validation_live_filled_rows >= 6 and generalization_ratio >= 0.70:
        return "medium", reasons
    reasons.append("insufficient_validation_or_generalization")
    return "low", reasons


def _deploy_recommendation(
    *,
    decision_action: str,
    decision: dict[str, Any],
    validation_live_filled_rows: int,
    generalization_ratio: float,
) -> str:
    if decision_action == "promote":
        return "promote"
    median_arr_delta_pct = _safe_float(decision.get("median_arr_delta_pct"), 0.0)
    profit_probability_delta = _safe_float(decision.get("profit_probability_delta"), 0.0)
    p95_drawdown_delta_usd = _safe_float(decision.get("p95_drawdown_delta_usd"), 0.0)
    if (
        median_arr_delta_pct > 0.0
        and validation_live_filled_rows >= 6
        and generalization_ratio >= 0.80
        and profit_probability_delta >= -0.01
        and p95_drawdown_delta_usd <= 3.0
    ):
        return "shadow_only"
    return "hold"


def _select_best_target(
    *,
    candidates: list[tuple[str, dict[str, Any] | None]],
    current: dict[str, Any] | None,
    min_median_arr_improvement_pct: float,
    min_median_pnl_improvement_usd: float,
    min_replay_pnl_improvement_usd: float,
    max_profit_prob_drop: float,
    max_p95_drawdown_increase_usd: float,
    max_loss_hit_prob_increase: float,
    min_fill_lift: int,
    min_fill_retention_ratio: float,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    evaluated: list[dict[str, Any]] = []
    for source_name, candidate in candidates:
        if candidate is None:
            continue
        decision = _promotion_decision(
            best=candidate,
            current=current,
            min_median_arr_improvement_pct=min_median_arr_improvement_pct,
            min_median_pnl_improvement_usd=min_median_pnl_improvement_usd,
            min_replay_pnl_improvement_usd=min_replay_pnl_improvement_usd,
            max_profit_prob_drop=max_profit_prob_drop,
            max_p95_drawdown_increase_usd=max_p95_drawdown_increase_usd,
            max_loss_hit_prob_increase=max_loss_hit_prob_increase,
            min_fill_lift=min_fill_lift,
            min_fill_retention_ratio=min_fill_retention_ratio,
        )
        evaluated.append(
            {
                "source": source_name,
                "candidate": candidate,
                "decision": decision,
            }
        )

    if not evaluated:
        return None, {"action": "hold", "reason": "missing_candidate_data"}, []

    evaluated.sort(
        key=lambda item: (
            1 if (item.get("decision") or {}).get("action") == "promote" else 0,
            _safe_float((item.get("decision") or {}).get("median_arr_delta_pct"), float("-inf")),
            _safe_float((item.get("decision") or {}).get("replay_pnl_delta_usd"), float("-inf")),
            _safe_float((item.get("decision") or {}).get("median_pnl_delta_usd"), float("-inf")),
            _safe_float((item.get("decision") or {}).get("p05_arr_delta_pct"), float("-inf")),
            -_safe_float((item.get("decision") or {}).get("p95_drawdown_delta_usd"), float("inf")),
            _safe_float(((item.get("candidate") or {}).get("continuation") or {}).get("median_arr_pct"), float("-inf")),
        ),
        reverse=True,
    )
    best_entry = evaluated[0]
    decision = dict(best_entry.get("decision") or {})
    decision["selected_source"] = best_entry.get("source")
    decision["selected_family"] = ((best_entry.get("candidate") or {}).get("candidate_family") or "unknown")
    return best_entry.get("candidate"), decision, evaluated


def _build_hypothesis_candidate(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    best = summary.get("best_candidate")
    best_hypothesis = summary.get("best_hypothesis") or {}
    hypothesis = best_hypothesis.get("hypothesis") if isinstance(best_hypothesis, dict) else {}
    best_summary = best_hypothesis.get("summary") if isinstance(best_hypothesis, dict) else {}
    if not isinstance(best, dict):
        best = {}
    if not isinstance(hypothesis, dict):
        hypothesis = {}
    if not isinstance(best_summary, dict):
        best_summary = {}
    name = str(best.get("name") or hypothesis.get("name") or "").strip()
    if not name:
        return None
    profile = {
        "name": name,
        "max_abs_delta": _safe_float(best.get("max_abs_delta"), _safe_float(hypothesis.get("max_abs_delta"), None)),
        "up_max_buy_price": _safe_float(
            best.get("up_max_buy_price"), _safe_float(hypothesis.get("up_max_buy_price"), None)
        ),
        "down_max_buy_price": _safe_float(
            best.get("down_max_buy_price"), _safe_float(hypothesis.get("down_max_buy_price"), None)
        ),
    }
    session_name = str(best.get("session_name") or hypothesis.get("session_name") or "").strip()
    hours = [int(hour) for hour in (best.get("et_hours") or hypothesis.get("et_hours") or []) if isinstance(hour, int)]
    session_policy: list[dict[str, Any]] = []
    if session_name and hours:
        record: dict[str, Any] = {"name": session_name, "et_hours": sorted(hours)}
        if profile.get("max_abs_delta") is not None:
            record["max_abs_delta"] = profile["max_abs_delta"]
        if profile.get("up_max_buy_price") is not None:
            record["up_max_buy_price"] = profile["up_max_buy_price"]
        if profile.get("down_max_buy_price") is not None:
            record["down_max_buy_price"] = profile["down_max_buy_price"]
        session_policy.append(record)
    validation_rows = int(
        _safe_float(
            best.get("validation_live_filled_rows"),
            _safe_float(best_summary.get("validation_live_filled_rows"), 0.0),
        )
        or 0
    )
    return {
        "candidate_family": "hypothesis",
        "profile": profile,
        "base_profile": dict(profile),
        "session_overrides": [],
        "recommended_session_policy": session_policy,
        "historical": {
            "replay_live_filled_rows": validation_rows,
            "replay_live_filled_pnl_usd": _safe_float(best_summary.get("validation_replay_pnl_usd"), 0.0),
        },
        "monte_carlo": {
            "profit_probability": _safe_float(best_summary.get("validation_profit_probability"), 0.0),
            "p95_max_drawdown_usd": _safe_float(best_summary.get("validation_p95_drawdown_usd"), 0.0),
        },
        "continuation": {
            "median_arr_pct": _safe_float(best.get("validation_median_arr_pct"), _safe_float(best_summary.get("validation_median_arr_pct"), 0.0)),
            "p05_arr_pct": _safe_float(best.get("validation_p05_arr_pct"), _safe_float(best_summary.get("validation_p05_arr_pct"), 0.0)),
            "historical_arr_pct": _safe_float(best.get("validation_median_arr_pct"), _safe_float(best_summary.get("validation_median_arr_pct"), 0.0)),
        },
        "scoring": {
            "generalization_ratio": _safe_float(best.get("generalization_ratio"), _safe_float(best_summary.get("generalization_ratio"), 0.0)),
            "validation_live_filled_rows": validation_rows,
            "evidence_band": str(best.get("evidence_band") or best_summary.get("evidence_band") or ""),
        },
    }


def _execution_drag_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(1, len(rows))
    skip_price = 0
    order_failed = 0
    cancelled_unfilled = 0
    direction_stats: dict[str, dict[str, float]] = {}
    for row in rows:
        status = str(row.get("order_status") or "").strip().lower()
        direction = str(row.get("direction") or "UNKNOWN").strip().upper()
        stats = direction_stats.setdefault(
            direction,
            {"filled_rows": 0.0, "filled_pnl_usd": 0.0, "skip_price_count": 0.0, "order_failed_count": 0.0, "cancelled_unfilled_count": 0.0},
        )
        if status == "skip_price_outside_guardrails":
            skip_price += 1
            stats["skip_price_count"] += 1.0
        elif status in {"live_order_failed", "order_failed", "order_placement_failed", "post_only_cross_failure"}:
            order_failed += 1
            stats["order_failed_count"] += 1.0
        elif status in {"live_cancelled_unfilled", "cancelled_unfilled", "cancel_before_fill"}:
            cancelled_unfilled += 1
            stats["cancelled_unfilled_count"] += 1.0
        elif status == "live_filled":
            stats["filled_rows"] += 1.0
            stats["filled_pnl_usd"] += _safe_float(row.get("pnl_usd"), 0.0)
    return {
        "total_rows": len(rows),
        "skip_price_count": skip_price,
        "order_failed_count": order_failed,
        "cancelled_unfilled_count": cancelled_unfilled,
        "skip_rate": skip_price / float(total),
        "order_failure_rate": order_failed / float(total),
        "cancelled_unfilled_rate": cancelled_unfilled / float(total),
        "direction_stats": direction_stats,
    }


def _candidate_package_record(
    *,
    source: str,
    candidate: dict[str, Any] | None,
    active_candidate: dict[str, Any] | None,
    drag_context: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    profile = candidate.get("profile") if isinstance(candidate.get("profile"), dict) else {}
    if not profile:
        return None
    active_arr = _arr_for_candidate(active_candidate)
    arr = _arr_for_candidate(candidate)
    active_rows = max(1, int(_safe_float((active_candidate or {}).get("historical", {}).get("replay_live_filled_rows"), 1.0) or 1))
    validation_rows = max(0, int(_safe_float(candidate.get("historical", {}).get("replay_live_filled_rows"), 0.0) or 0))
    fill_retention = validation_rows / float(active_rows) if active_rows > 0 else 1.0
    fill_drop = max(0.0, 1.0 - fill_retention)
    arr_delta = arr["median_arr_pct"] - active_arr["median_arr_pct"]
    p05_delta = arr["p05_arr_pct"] - active_arr["p05_arr_pct"]
    current_scale = max(1.0, abs(active_arr["median_arr_pct"]))
    arr_delta_norm = (arr_delta / current_scale) * 100.0
    p05_delta_norm = (p05_delta / current_scale) * 100.0
    sample_bonus = min(20.0, float(validation_rows)) * 0.2
    raw_score = arr_delta_norm + (0.6 * p05_delta_norm) + sample_bonus
    skip_penalty = float(drag_context.get("skip_rate") or 0.0) + fill_drop
    order_failure_penalty = float(drag_context.get("order_failure_rate") or 0.0) + (0.5 * fill_drop)
    live_score = raw_score - (45.0 * skip_penalty) - (45.0 * order_failure_penalty)
    session_policy = (
        _runtime_session_policy_from_overrides(candidate.get("session_overrides"))
        or list(candidate.get("recommended_session_policy") or [])
    )
    return {
        "source": source,
        "candidate_family": str(candidate.get("candidate_family") or "unknown"),
        "runtime_package": _runtime_package(profile=profile, session_policy=session_policy),
        "candidate": candidate,
        "median_arr_pct": round(arr["median_arr_pct"], 4),
        "p05_arr_pct": round(arr["p05_arr_pct"], 4),
        "median_arr_delta_pct": round(arr_delta, 4),
        "p05_arr_delta_pct": round(p05_delta, 4),
        "validation_live_filled_rows": validation_rows,
        "fill_retention_ratio": round(fill_retention, 4),
        "skip_rate_penalty": round(skip_penalty, 6),
        "order_failure_penalty": round(order_failure_penalty, 6),
        "raw_research_score": round(raw_score, 6),
        "live_execution_score": round(live_score, 6),
    }


def _rank_candidate_packages(
    *,
    active_candidate: dict[str, Any] | None,
    candidates: list[tuple[str, dict[str, Any] | None]],
    drag_context: dict[str, Any],
    min_fill_retention_ratio: float,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source, candidate in candidates:
        record = _candidate_package_record(
            source=source,
            candidate=candidate,
            active_candidate=active_candidate,
            drag_context=drag_context,
        )
        if record is None:
            continue
        signature = _package_signature(record.get("runtime_package"))
        if signature in seen:
            continue
        seen.add(signature)
        ranked.append(record)
    if not ranked:
        empty = {
            "source": "none",
            "candidate_family": "unknown",
            "runtime_package": {"profile": {}, "session_policy": []},
            "candidate": None,
            "median_arr_pct": 0.0,
            "p05_arr_pct": 0.0,
            "median_arr_delta_pct": 0.0,
            "p05_arr_delta_pct": 0.0,
            "validation_live_filled_rows": 0,
            "fill_retention_ratio": 0.0,
            "skip_rate_penalty": 0.0,
            "order_failure_penalty": 0.0,
            "raw_research_score": 0.0,
            "live_execution_score": 0.0,
        }
        return empty, empty, [], {
            "skip_price_count": int(drag_context.get("skip_price_count") or 0),
            "order_failed_count": int(drag_context.get("order_failed_count") or 0),
            "cancelled_unfilled_count": int(drag_context.get("cancelled_unfilled_count") or 0),
            "skip_rate": round(float(drag_context.get("skip_rate") or 0.0), 6),
            "order_failure_rate": round(float(drag_context.get("order_failure_rate") or 0.0), 6),
            "cancelled_unfilled_rate": round(float(drag_context.get("cancelled_unfilled_rate") or 0.0), 6),
            "sample_size_rows": int(drag_context.get("total_rows") or 0),
        }

    ranked.sort(
        key=lambda item: (
            float(item.get("raw_research_score") or 0.0),
            float(item.get("median_arr_delta_pct") or 0.0),
            int(item.get("validation_live_filled_rows") or 0),
        ),
        reverse=True,
    )
    best_raw = ranked[0]
    live_eligible = [
        item
        for item in ranked
        if float(item.get("fill_retention_ratio") or 0.0) >= float(min_fill_retention_ratio)
    ] or list(ranked)
    live_eligible.sort(
        key=lambda item: (
            float(item.get("live_execution_score") or 0.0),
            float(item.get("raw_research_score") or 0.0),
            int(item.get("validation_live_filled_rows") or 0),
        ),
        reverse=True,
    )
    best_live = live_eligible[0]
    drag_summary = {
        "skip_price_count": int(drag_context.get("skip_price_count") or 0),
        "order_failed_count": int(drag_context.get("order_failed_count") or 0),
        "cancelled_unfilled_count": int(drag_context.get("cancelled_unfilled_count") or 0),
        "skip_rate": round(float(drag_context.get("skip_rate") or 0.0), 6),
        "order_failure_rate": round(float(drag_context.get("order_failure_rate") or 0.0), 6),
        "cancelled_unfilled_rate": round(float(drag_context.get("cancelled_unfilled_rate") or 0.0), 6),
        "sample_size_rows": int(drag_context.get("total_rows") or 0),
        "best_live_fill_retention_ratio": float(best_live.get("fill_retention_ratio") or 0.0),
        "best_raw_fill_retention_ratio": float(best_raw.get("fill_retention_ratio") or 0.0),
        "winner_changed_due_to_execution_drag": bool(
            _package_signature(best_live.get("runtime_package")) != _package_signature(best_raw.get("runtime_package"))
        ),
    }
    return best_live, best_raw, ranked, drag_summary


def _one_sided_bias_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _execution_drag_context(rows)
    stats = summary.get("direction_stats") if isinstance(summary.get("direction_stats"), dict) else {}
    up = stats.get("UP") if isinstance(stats.get("UP"), dict) else {}
    down = stats.get("DOWN") if isinstance(stats.get("DOWN"), dict) else {}
    up_pnl = _safe_float(up.get("filled_pnl_usd"), 0.0)
    down_pnl = _safe_float(down.get("filled_pnl_usd"), 0.0)
    up_fills = int(_safe_float(up.get("filled_rows"), 0.0) or 0)
    down_fills = int(_safe_float(down.get("filled_rows"), 0.0) or 0)
    up_skip = int(_safe_float(up.get("skip_price_count"), 0.0) or 0)
    down_skip = int(_safe_float(down.get("skip_price_count"), 0.0) or 0)
    recommendation = "balanced_directional_bias"
    reason = "directional_performance_mixed"
    if down_pnl > 0.0 and up_pnl <= 0.0 and down_fills >= max(3, up_fills):
        recommendation = "tighten_down_and_suppress_up"
        reason = "down_is_profitable_while_up_is_non_positive"
    elif down_pnl > up_pnl and down_skip <= up_skip:
        recommendation = "suppress_up"
        reason = "up_underperforms_and_absorbs_more_skips"
    elif down_pnl > up_pnl:
        recommendation = "tighten_down"
        reason = "down_outperforms_up"
    return {
        "recommendation": recommendation,
        "reason": reason,
        "up_filled_pnl_usd": round(up_pnl, 4),
        "down_filled_pnl_usd": round(down_pnl, 4),
        "up_filled_rows": up_fills,
        "down_filled_rows": down_fills,
        "up_skip_price_count": up_skip,
        "down_skip_price_count": down_skip,
    }


def _promotion_decision(
    *,
    best: dict[str, Any] | None,
    current: dict[str, Any] | None,
    min_median_arr_improvement_pct: float,
    min_median_pnl_improvement_usd: float,
    min_replay_pnl_improvement_usd: float,
    max_profit_prob_drop: float,
    max_p95_drawdown_increase_usd: float,
    max_loss_hit_prob_increase: float,
    min_fill_lift: int,
    min_fill_retention_ratio: float,
) -> dict[str, Any]:
    if best is None or current is None:
        return {"action": "hold", "reason": "missing_candidate_data"}

    if _candidate_identity(best) == _candidate_identity(current):
        return {"action": "hold", "reason": "current_profile_is_best"}

    best_hist = best.get("historical") or {}
    current_hist = current.get("historical") or {}
    best_mc = best.get("monte_carlo") or {}
    current_mc = current.get("monte_carlo") or {}
    best_arr = _arr_for_candidate(best)
    current_arr = _arr_for_candidate(current)

    median_arr_delta = best_arr["median_arr_pct"] - current_arr["median_arr_pct"]
    median_pnl_delta = _safe_float(best_mc.get("median_total_pnl_usd")) - _safe_float(
        current_mc.get("median_total_pnl_usd")
    )
    replay_pnl_delta = _safe_float(best_hist.get("replay_live_filled_pnl_usd")) - _safe_float(
        current_hist.get("replay_live_filled_pnl_usd")
    )
    profit_prob_delta = _safe_float(best_mc.get("profit_probability")) - _safe_float(
        current_mc.get("profit_probability")
    )
    p95_drawdown_delta = _safe_float(best_mc.get("p95_max_drawdown_usd")) - _safe_float(
        current_mc.get("p95_max_drawdown_usd")
    )
    loss_hit_delta = _safe_float(best_mc.get("loss_limit_hit_probability")) - _safe_float(
        current_mc.get("loss_limit_hit_probability")
    )
    current_fill_rows = max(1, int(current_hist.get("replay_live_filled_rows") or 0))
    best_fill_rows = int(best_hist.get("replay_live_filled_rows") or 0)
    fill_lift = best_fill_rows - current_fill_rows
    fill_retention_ratio = best_fill_rows / float(current_fill_rows) if current_fill_rows > 0 else 1.0

    reasons: list[str] = []
    if median_arr_delta < min_median_arr_improvement_pct:
        reasons.append(
            f"median_arr_delta_below_threshold:{median_arr_delta:.4f}<{min_median_arr_improvement_pct:.4f}"
        )
    if median_pnl_delta < min_median_pnl_improvement_usd:
        reasons.append(
            f"median_pnl_delta_below_threshold:{median_pnl_delta:.4f}<{min_median_pnl_improvement_usd:.4f}"
        )
    if replay_pnl_delta < min_replay_pnl_improvement_usd:
        reasons.append(
            f"replay_pnl_delta_below_threshold:{replay_pnl_delta:.4f}<{min_replay_pnl_improvement_usd:.4f}"
        )
    if profit_prob_delta < -abs(max_profit_prob_drop):
        reasons.append(
            f"profit_probability_drop_too_large:{profit_prob_delta:.4f}<-{abs(max_profit_prob_drop):.4f}"
        )
    if p95_drawdown_delta > max_p95_drawdown_increase_usd:
        reasons.append(
            f"drawdown_increase_too_large:{p95_drawdown_delta:.4f}>{max_p95_drawdown_increase_usd:.4f}"
        )
    if loss_hit_delta > max_loss_hit_prob_increase:
        reasons.append(
            f"loss_hit_increase_too_large:{loss_hit_delta:.4f}>{max_loss_hit_prob_increase:.4f}"
        )
    if fill_lift < min_fill_lift and fill_retention_ratio < max(0.0, float(min_fill_retention_ratio)):
        reasons.append(
            "fill_retention_below_threshold:"
            f"{fill_retention_ratio:.4f}<{max(0.0, float(min_fill_retention_ratio)):.4f}"
        )

    decision = {
        "action": "promote" if not reasons else "hold",
        "reason": "promotion_thresholds_met" if not reasons else ";".join(reasons),
        "median_arr_delta_pct": round(median_arr_delta, 4),
        "historical_arr_delta_pct": round(best_arr["historical_arr_pct"] - current_arr["historical_arr_pct"], 4),
        "p05_arr_delta_pct": round(best_arr["p05_arr_pct"] - current_arr["p05_arr_pct"], 4),
        "median_pnl_delta_usd": round(median_pnl_delta, 4),
        "replay_pnl_delta_usd": round(replay_pnl_delta, 4),
        "profit_probability_delta": round(profit_prob_delta, 4),
        "p95_drawdown_delta_usd": round(p95_drawdown_delta, 4),
        "loss_hit_probability_delta": round(loss_hit_delta, 4),
        "fill_lift": int(fill_lift),
        "fill_retention_ratio": round(fill_retention_ratio, 4),
    }
    return decision


def render_strategy_env(target: dict[str, Any], metadata: dict[str, Any]) -> str:
    base_profile = target.get("base_profile") if isinstance(target.get("base_profile"), dict) else None
    profile = base_profile or (target.get("profile") if isinstance(target.get("profile"), dict) else target)
    candidate_profile = target.get("profile") if isinstance(target.get("profile"), dict) else profile
    session_overrides = _normalized_session_overrides(target.get("session_overrides"))
    session_policy = _runtime_session_policy_from_overrides(session_overrides)
    lines = [
        "# Managed by scripts/run_btc5_autoresearch_cycle.py",
        f"# generated_at={metadata['generated_at']}",
        f"# candidate={candidate_profile.get('name')}",
        f"# reason={metadata['reason']}",
        f"BTC5_MAX_ABS_DELTA={profile.get('max_abs_delta')}",
        f"BTC5_UP_MAX_BUY_PRICE={profile.get('up_max_buy_price')}",
        f"BTC5_DOWN_MAX_BUY_PRICE={profile.get('down_max_buy_price')}",
        f"BTC5_PROBE_MAX_ABS_DELTA={profile.get('max_abs_delta')}",
        f"BTC5_PROBE_UP_MAX_BUY_PRICE={profile.get('up_max_buy_price')}",
        f"BTC5_PROBE_DOWN_MAX_BUY_PRICE={profile.get('down_max_buy_price')}",
        f"BTC5_SESSION_OVERRIDES_JSON={json.dumps(session_overrides, separators=(',', ':'))}",
        f"BTC5_SESSION_POLICY_JSON={json.dumps(session_policy, separators=(',', ':'))}",
    ]
    return "\n".join(lines) + "\n"


def _write_override_env(path: Path, *, best_target: dict[str, Any], decision: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_strategy_env(
            best_target,
            {
                "generated_at": _now_utc().isoformat(),
                "reason": decision.get("reason"),
            },
        )
    )


def _restart_service(service_name: str) -> dict[str, Any]:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    active = subprocess.run(
        ["sudo", "systemctl", "is-active", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {
        "restart_returncode": result.returncode,
        "restart_stderr_tail": (result.stderr or "").strip()[-300:],
        "restart_stdout_tail": (result.stdout or "").strip()[-300:],
        "service_state": (active.stdout or "").strip(),
    }


def _runtime_load_status(
    *,
    override_env_path: Path,
    restart_on_promote: bool,
    decision_action: str,
    restart_result: dict[str, Any] | None,
) -> dict[str, Any]:
    override_values = _load_env_file(override_env_path)
    session_policy_records = len(_runtime_session_policy_from_env(override_values))
    return {
        "override_env_written": bool(override_values),
        "override_env_path": str(override_env_path),
        "session_policy_records": session_policy_records,
        "base_env_changed": False,
        "service_restart_requested": bool(
            str(decision_action or "").strip().lower() == "promote" and restart_on_promote
        ),
        "service_restart_state": (
            str((restart_result or {}).get("service_state") or "").strip() or None
        ),
    }


def _write_reports(report_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    json_path = report_dir / f"cycle_{stamp}.json"
    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    artifacts = {
        "cycle_json": str(json_path),
        "latest_json": str(latest_json),
        "latest_md": str(latest_md),
    }
    json_payload = dict(payload, artifacts=artifacts)
    md_lines = [
        "# BTC5 Autoresearch Cycle",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Action: `{payload['decision']['action']}`",
        f"- Deploy recommendation: `{payload.get('deploy_recommendation', 'hold')}`",
        f"- Reason: `{payload['decision']['reason']}`",
        f"- Selected source: `{payload['decision'].get('selected_source', 'none')}`",
        f"- Selected family: `{payload['decision'].get('selected_family', 'none')}`",
        f"- Chosen public forecast source: `{payload.get('public_forecast_source_artifact', 'none')}`",
        f"- Public forecast selection reason: `{(payload.get('public_forecast_selection') or {}).get('selection_reason', 'none')}`",
        f"- Active profile: `{payload['active_profile']['name']}`",
        f"- Best profile: `{payload['best_candidate']['profile']['name'] if payload.get('best_candidate') else 'none'}`",
        f"- Package confidence: `{payload.get('package_confidence_label', 'low')}`",
        f"- Package confidence reasons: `{'; '.join(payload.get('package_confidence_reasons') or ['none'])}`",
        f"- Capital scale recommendation: `{(payload.get('capital_scale_recommendation') or {}).get('status', 'hold')}`",
        f"- Best live package source: `{(payload.get('best_live_package') or {}).get('source', 'none')}`",
        f"- Best raw package source: `{(payload.get('best_raw_research_package') or {}).get('source', 'none')}`",
        f"- One-sided bias recommendation: `{(payload.get('one_sided_bias_recommendation') or {}).get('recommendation', 'balanced_directional_bias')}`",
        f"- Observed window rows: `{payload['simulation_summary']['input']['observed_window_rows']}`",
        f"- Observed live-filled rows: `{payload['simulation_summary']['input']['live_filled_rows']}`",
        "",
        "## Deltas",
        "",
        f"- Median continuation ARR delta: `{payload['decision'].get('median_arr_delta_pct', 0.0):.2f}` percentage points",
        f"- Historical continuation ARR delta: `{payload['decision'].get('historical_arr_delta_pct', 0.0):.2f}` percentage points",
        f"- P05 continuation ARR delta: `{payload['decision'].get('p05_arr_delta_pct', 0.0):.2f}` percentage points",
        f"- Replay PnL delta: `{payload['decision'].get('replay_pnl_delta_usd', 0.0):.4f}` USD",
        f"- Median Monte Carlo PnL delta: `{payload['decision'].get('median_pnl_delta_usd', 0.0):.4f}` USD",
        f"- Profit-probability delta: `{payload['decision'].get('profit_probability_delta', 0.0):.2%}`",
        f"- P95 drawdown delta: `{payload['decision'].get('p95_drawdown_delta_usd', 0.0):.4f}` USD",
        f"- Loss-hit delta: `{payload['decision'].get('loss_hit_probability_delta', 0.0):.2%}`",
        f"- Fill lift: `{payload['decision'].get('fill_lift', 0)}`",
        "",
        "## Recommended Session Policy",
        "",
        f"- Runtime-ready policy records: `{len(payload.get('recommended_session_policy') or [])}`",
        "",
        "```json",
        json.dumps(payload.get("recommended_session_policy") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Runtime Package",
        "",
        f"- Active package profile: `{((payload.get('active_runtime_package') or {}).get('profile') or {}).get('name', 'none')}`",
        f"- Active package session-policy records: `{len(((payload.get('active_runtime_package') or {}).get('session_policy') or []))}`",
        f"- Best package profile: `{((payload.get('best_runtime_package') or {}).get('profile') or {}).get('name', 'none')}`",
        f"- Best package session-policy records: `{len(((payload.get('best_runtime_package') or {}).get('session_policy') or []))}`",
        f"- Validation live-filled rows: `{payload.get('validation_live_filled_rows', 0)}`",
        f"- Generalization ratio: `{payload.get('generalization_ratio', 0.0):.4f}`",
        f"- Promoted package selected: `{((payload.get('capital_scale_recommendation') or {}).get('promoted_package_selected'))}`",
        "",
        "## Execution Drag",
        "",
        f"- Skip-price count: `{((payload.get('execution_drag_summary') or {}).get('skip_price_count', 0))}`",
        f"- Order-failed count: `{((payload.get('execution_drag_summary') or {}).get('order_failed_count', 0))}`",
        f"- Cancelled-unfilled count: `{((payload.get('execution_drag_summary') or {}).get('cancelled_unfilled_count', 0))}`",
        f"- Skip-rate penalty: `{((payload.get('best_live_package') or {}).get('skip_rate_penalty', 0.0))}`",
        f"- Order-failure penalty: `{((payload.get('best_live_package') or {}).get('order_failure_penalty', 0.0))}`",
        f"- Winner changed by drag: `{((payload.get('execution_drag_summary') or {}).get('winner_changed_due_to_execution_drag', False))}`",
        "",
        "## Runtime Load Status",
        "",
        f"- Override env written: `{((payload.get('runtime_load_status') or {}).get('override_env_written'))}`",
        f"- Override env path: `{((payload.get('runtime_load_status') or {}).get('override_env_path') or 'none')}`",
        f"- Runtime session-policy records: `{((payload.get('runtime_load_status') or {}).get('session_policy_records'))}`",
        f"- Base env changed: `{((payload.get('runtime_load_status') or {}).get('base_env_changed'))}`",
        f"- Service restart requested: `{((payload.get('runtime_load_status') or {}).get('service_restart_requested'))}`",
        f"- Service restart state: `{((payload.get('runtime_load_status') or {}).get('service_restart_state') or 'none')}`",
        "",
        "## Package Decision",
        "",
        f"- Deploy recommendation: `{payload.get('deploy_recommendation', 'hold')}`",
        f"- Evidence missing: `{'; '.join(payload.get('package_missing_evidence') or ['none'])}`",
        f"- Recommendation explanation: `{payload.get('decision', {}).get('reason', 'none')}`",
        f"- Capital tranche recommendation: `{((payload.get('capital_scale_recommendation') or {}).get('recommended_tranche_usd', 0))}` USD",
        f"- Capital reason: `{((payload.get('capital_scale_recommendation') or {}).get('reason') or 'none')}`",
        "",
        "## Best Candidate",
        "",
        json.dumps(payload.get("best_candidate") or {}, indent=2, sort_keys=True),
    ]
    json_path.write_text(json.dumps(json_payload, indent=2, sort_keys=True) + "\n")
    latest_json.write_text(json.dumps(json_payload, indent=2, sort_keys=True) + "\n")
    latest_md.write_text("\n".join(md_lines) + "\n")
    return artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--strategy-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--override-env", type=Path, default=DEFAULT_OVERRIDE_ENV)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--top-grid-candidates", type=int, default=5)
    parser.add_argument("--min-replay-fills", type=int, default=12)
    parser.add_argument("--loss-limit-usd", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--restart-on-promote", action="store_true")
    parser.add_argument("--include-archive-csvs", action="store_true")
    parser.add_argument("--archive-glob", default="reports/btc_intraday_llm_bundle_*/raw/remote_btc5_window_trades.csv")
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
    parser.add_argument("--regime-min-session-rows", type=int, default=6)
    parser.add_argument("--regime-max-session-overrides", type=int, default=2)
    parser.add_argument("--regime-top-single-overrides-per-session", type=int, default=2)
    parser.add_argument("--regime-max-composed-candidates", type=int, default=64)
    parser.add_argument("--hypothesis-summary", type=Path, default=DEFAULT_HYPOTHESIS_SUMMARY)
    parser.add_argument("--regime-policy-summary", type=Path, default=DEFAULT_REGIME_POLICY_SUMMARY)
    parser.add_argument("--current-probe-latest", type=Path, default=DEFAULT_CURRENT_PROBE_LATEST)
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_env = _load_env_file(args.strategy_env)
    merged_env = _merged_strategy_env(args.strategy_env, args.override_env)
    active_profile = _profile_from_env("current_live_profile", merged_env)
    runtime_profile = _profile_from_env("runtime_recommended", merged_env)

    rows, baseline = assemble_observed_rows(
        db_path=args.db_path,
        include_archive_csvs=bool(args.include_archive_csvs),
        archive_glob=str(args.archive_glob),
        refresh_remote=bool(args.refresh_remote),
        remote_cache_json=args.remote_cache_json,
    )
    horizon_trades = max(len(rows), 40)
    global_summary = build_global_summary(
        rows=rows,
        db_path=args.db_path,
        current_live_profile=active_profile,
        runtime_recommended_profile=runtime_profile,
        paths=max(1, int(args.paths)),
        horizon_trades=horizon_trades,
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        top_grid_candidates=max(1, int(args.top_grid_candidates)),
        min_replay_fills=max(1, int(args.min_replay_fills)),
    )
    global_summary["baseline"] = baseline
    regime_policy_summary = build_regime_policy_summary(
        rows=rows,
        db_path=args.db_path,
        current_live_profile=active_profile,
        runtime_recommended_profile=runtime_profile,
        paths=max(1, int(args.paths)),
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        min_replay_fills=max(1, int(args.min_replay_fills)),
        min_session_rows=max(1, int(args.regime_min_session_rows)),
        max_session_overrides=max(1, int(args.regime_max_session_overrides)),
        top_single_overrides_per_session=max(1, int(args.regime_top_single_overrides_per_session)),
        max_composed_candidates=max(0, int(args.regime_max_composed_candidates)),
    )
    regime_policy_summary["baseline"] = baseline
    hypothesis_summary = _load_json(args.hypothesis_summary) or {}
    latest_regime_summary = _load_json(args.regime_policy_summary) or {}
    prior_standard_latest = _load_json(args.report_dir / "latest.json") or {}
    current_probe_latest = _load_json(args.current_probe_latest) or {}
    runtime_truth = _load_json(args.runtime_truth) or {}

    current_candidate = _normalize_global_candidate(_find_candidate(global_summary, "current_live_profile"))
    if current_candidate is None:
        current_candidate = _normalize_regime_candidate(regime_policy_summary.get("current_policy"))
    global_best_candidate = _normalize_global_candidate(global_summary.get("best_candidate"))
    regime_best_candidate = _normalize_regime_candidate(regime_policy_summary.get("best_policy"))
    hypothesis_best_candidate = _build_hypothesis_candidate(hypothesis_summary)
    drag_context = _execution_drag_context(rows)
    best_live_package_record, best_raw_package_record, ranked_packages, execution_drag_summary = _rank_candidate_packages(
        active_candidate=current_candidate,
        candidates=[
            ("active_profile", current_candidate),
            ("global_best_candidate", global_best_candidate),
            ("regime_best_candidate", regime_best_candidate),
            ("hypothesis_best_candidate", hypothesis_best_candidate),
        ],
        drag_context=drag_context,
        min_fill_retention_ratio=float(args.min_fill_retention_ratio),
    )
    best_live_candidate = best_live_package_record.get("candidate") if isinstance(best_live_package_record, dict) else None
    best_candidate, decision, evaluated_targets = _select_best_target(
        candidates=[
            ("best_live_package", best_live_candidate),
            ("global_best_candidate", global_best_candidate),
            ("regime_best_candidate", regime_best_candidate),
            ("hypothesis_best_candidate", hypothesis_best_candidate),
        ],
        current=current_candidate,
        min_median_arr_improvement_pct=float(args.min_median_arr_improvement_pct),
        min_median_pnl_improvement_usd=float(args.min_median_pnl_improvement_usd),
        min_replay_pnl_improvement_usd=float(args.min_replay_pnl_improvement_usd),
        max_profit_prob_drop=float(args.max_profit_prob_drop),
        max_p95_drawdown_increase_usd=float(args.max_p95_drawdown_increase_usd),
        max_loss_hit_prob_increase=float(args.max_loss_hit_prob_increase),
        min_fill_lift=int(args.min_fill_lift),
        min_fill_retention_ratio=float(args.min_fill_retention_ratio),
    )

    restart_result: dict[str, Any] | None = None
    if decision["action"] == "promote" and best_candidate is not None:
        _write_override_env(
            args.override_env,
            best_target=best_candidate,
            decision=decision,
        )
        if args.restart_on_promote:
            restart_result = _restart_service(str(args.service_name))

    best_session_policy = (
        _runtime_session_policy_from_overrides((best_candidate or {}).get("session_overrides"))
        or list((latest_regime_summary or {}).get("recommended_session_policy") or [])
        or list((hypothesis_summary or {}).get("recommended_session_policy") or [])
    )
    active_session_policy = _runtime_session_policy_from_env(merged_env)
    active_runtime_package = _runtime_package(
        profile={
            "name": active_profile.name,
            "max_abs_delta": active_profile.max_abs_delta,
            "up_max_buy_price": active_profile.up_max_buy_price,
            "down_max_buy_price": active_profile.down_max_buy_price,
        },
        session_policy=active_session_policy,
    )
    best_runtime_package = _runtime_package(
        profile=(best_candidate or {}).get("profile") or {},
        session_policy=best_session_policy,
    )
    validation_live_filled_rows = _extract_validation_rows(best_candidate)
    generalization_ratio = _extract_generalization_ratio(
        best_candidate,
        hypothesis_summary=hypothesis_summary,
    )
    package_confidence_label, package_confidence_reasons = _package_confidence(
        validation_live_filled_rows=validation_live_filled_rows,
        generalization_ratio=generalization_ratio,
    )
    deploy_recommendation = _deploy_recommendation(
        decision_action=str(decision.get("action") or "hold"),
        decision=decision,
        validation_live_filled_rows=validation_live_filled_rows,
        generalization_ratio=generalization_ratio,
    )
    package_missing_evidence: list[str] = []
    if validation_live_filled_rows < 6:
        package_missing_evidence.append("validation_live_filled_rows_below_6")
    if generalization_ratio < 0.80:
        package_missing_evidence.append("generalization_ratio_below_0.80")
    if _safe_float(decision.get("median_arr_delta_pct"), 0.0) <= 0:
        package_missing_evidence.append("median_arr_delta_not_positive")
    if _safe_float(decision.get("profit_probability_delta"), 0.0) < -0.01:
        package_missing_evidence.append("profit_probability_delta_below_-0.01")
    if _safe_float(decision.get("p95_drawdown_delta_usd"), 0.0) > 3.0:
        package_missing_evidence.append("p95_drawdown_delta_above_3.0")

    payload = {
        "generated_at": _now_utc().isoformat(),
        "base_strategy_env": str(args.strategy_env),
        "override_env": str(args.override_env),
        "base_strategy_values": base_env,
        "active_profile": {
            "name": active_profile.name,
            "max_abs_delta": active_profile.max_abs_delta,
            "up_max_buy_price": active_profile.up_max_buy_price,
            "down_max_buy_price": active_profile.down_max_buy_price,
        },
        "decision": decision,
        "deploy_recommendation": deploy_recommendation,
        "package_confidence_label": package_confidence_label,
        "package_confidence_reasons": package_confidence_reasons,
        "validation_live_filled_rows": int(validation_live_filled_rows),
        "generalization_ratio": round(float(generalization_ratio), 4),
        "package_missing_evidence": package_missing_evidence,
        "active_runtime_package": active_runtime_package,
        "best_runtime_package": best_runtime_package,
        "arr_tracking": _arr_tracking(best_candidate, current_candidate),
        "recommended_session_policy": best_session_policy,
        "best_candidate": best_candidate,
        "current_candidate": current_candidate,
        "global_best_candidate": global_best_candidate,
        "regime_best_candidate": regime_best_candidate,
        "hypothesis_best_candidate": hypothesis_best_candidate,
        "promotion_candidates": evaluated_targets,
        "best_live_package": {
            "source": best_live_package_record.get("source"),
            "candidate_family": best_live_package_record.get("candidate_family"),
            "runtime_package": best_live_package_record.get("runtime_package"),
            "median_arr_delta_pct": best_live_package_record.get("median_arr_delta_pct"),
            "p05_arr_delta_pct": best_live_package_record.get("p05_arr_delta_pct"),
            "fill_retention_ratio": best_live_package_record.get("fill_retention_ratio"),
            "skip_rate_penalty": best_live_package_record.get("skip_rate_penalty"),
            "order_failure_penalty": best_live_package_record.get("order_failure_penalty"),
            "validation_live_filled_rows": best_live_package_record.get("validation_live_filled_rows"),
            "live_execution_score": best_live_package_record.get("live_execution_score"),
        },
        "best_raw_research_package": {
            "source": best_raw_package_record.get("source"),
            "candidate_family": best_raw_package_record.get("candidate_family"),
            "runtime_package": best_raw_package_record.get("runtime_package"),
            "median_arr_delta_pct": best_raw_package_record.get("median_arr_delta_pct"),
            "p05_arr_delta_pct": best_raw_package_record.get("p05_arr_delta_pct"),
            "fill_retention_ratio": best_raw_package_record.get("fill_retention_ratio"),
            "skip_rate_penalty": best_raw_package_record.get("skip_rate_penalty"),
            "order_failure_penalty": best_raw_package_record.get("order_failure_penalty"),
            "validation_live_filled_rows": best_raw_package_record.get("validation_live_filled_rows"),
            "raw_research_score": best_raw_package_record.get("raw_research_score"),
        },
        "ranked_runtime_packages": ranked_packages,
        "execution_drag_summary": execution_drag_summary,
        "one_sided_bias_recommendation": _one_sided_bias_recommendation(rows),
        "simulation_summary": global_summary,
        "regime_policy_summary": regime_policy_summary,
        "service_restart": restart_result,
        "runtime_load_status": _runtime_load_status(
            override_env_path=args.override_env,
            restart_on_promote=bool(args.restart_on_promote),
            decision_action=str(decision.get("action") or ""),
            restart_result=restart_result,
        ),
    }
    public_forecast_selection = _select_public_forecast(
        standard_payload=payload,
        current_probe_payload=current_probe_latest,
        standard_source=str(args.report_dir / "latest.json"),
        current_probe_source=str(args.current_probe_latest),
    )
    if not (public_forecast_selection.get("selected")) and prior_standard_latest:
        public_forecast_selection = _select_public_forecast(
            standard_payload=prior_standard_latest,
            current_probe_payload=current_probe_latest,
            standard_source=str(args.report_dir / "latest.json"),
            current_probe_source=str(args.current_probe_latest),
        )
    selected_public = public_forecast_selection.get("selected") or {}
    payload["public_forecast_selection"] = public_forecast_selection
    payload["public_forecast_source_artifact"] = selected_public.get("source_artifact")
    payload["selected_best_runtime_package"] = selected_public.get("best_runtime_package") or payload.get("best_runtime_package") or {}
    promoted_package_selected = _package_signature(payload.get("selected_best_runtime_package")) == _package_signature(
        payload.get("active_runtime_package")
    )
    fund_blocked, fund_block_reasons = _fund_reconciliation_blocked(runtime_truth)
    trailing_windows = _live_fill_windows(rows)
    payload["capital_scale_recommendation"] = _capital_scale_recommendation(
        package_confidence_label=str(payload.get("package_confidence_label") or "low"),
        trailing=trailing_windows,
        promoted_package_selected=promoted_package_selected,
        fund_reconciliation_blocked=fund_blocked,
        fund_block_reasons=fund_block_reasons,
    )

    artifacts = _write_reports(args.report_dir, payload)
    payload["artifacts"] = artifacts
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
