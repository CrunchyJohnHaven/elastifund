#!/usr/bin/env python3
"""Build a normalized fast-market opportunity map for BTC5 and adjacent lanes."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AUTORESEARCH = Path("reports/btc5_autoresearch/latest.json")
DEFAULT_CURRENT_PROBE = Path("reports/btc5_autoresearch_current_probe/latest.json")
DEFAULT_RUNTIME_TRUTH = Path("reports/runtime_truth_latest.json")
DEFAULT_SIGNAL_SOURCE_AUDIT = Path("reports/signal_source_audit.json")
DEFAULT_HYPOTHESIS_FRONTIER = Path("research/btc5_hypothesis_frontier_latest.json")
DEFAULT_OUTPUT_DIR = Path("reports/fast_market_search")
SCHEMA_VERSION = "fast_market_search.v1"
ADJACENT_PRIORITY_ORDER = ("btc_15m", "eth_intraday", "btc_4h")
SEARCH_TRACK_ORDER = (
    "package_selection",
    "session_policy_followup",
    "guardrail_parameter_sweep",
    "loss_cluster_suppression",
    "hypothesis_sweep",
    "adjacent_shadow_discovery",
)
NON_BLOCKING_MARKERS = {
    "active_profile_baseline",
    "clear_for_promotion",
    "promotion_ready",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now_utc().strftime("%Y%m%dT%H%M%SZ")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        if isinstance(value, str) and value.strip().lower() in {"inf", "+inf", "-inf", "nan"}:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_latest_report(repo_root: Path, pattern: str) -> Path | None:
    matches = sorted((repo_root / "reports").rglob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _relative_path_text(repo_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _parse_iso8601(raw: Any) -> datetime | None:
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


def _evidence_band(validation_rows: int) -> str:
    if int(validation_rows) >= 16:
        return "validated"
    if int(validation_rows) >= 8:
        return "candidate"
    return "exploratory"


def _evidence_priority(label: str) -> int:
    return {"validated": 3, "candidate": 2, "exploratory": 1}.get(str(label).strip().lower(), 0)


def _deployment_priority(label: str) -> int:
    return {
        "validated_btc5_live_candidate": 4,
        "validated_btc5_blocked": 3,
        "btc5_probe_only": 2,
        "adjacent_shadow_only": 1,
        "adjacent_watch_only": 0,
    }.get(str(label).strip().lower(), -1)


def _execution_realism_label(score: float) -> str:
    if score >= 0.75:
        return "strong"
    if score >= 0.55:
        return "moderate"
    return "weak"


def _execution_realism_btc5(item: dict[str, Any]) -> dict[str, Any]:
    fill_retention_ratio = _clamp(_safe_float(item.get("fill_retention_ratio"), 0.0))
    order_failure_penalty = _clamp(_safe_float(item.get("order_failure_penalty"), 0.0))
    skip_rate_penalty = _clamp(_safe_float(item.get("skip_rate_penalty"), 0.0))
    score = round(
        _clamp(
            (0.50 * fill_retention_ratio)
            + (0.25 * (1.0 - order_failure_penalty))
            + (0.25 * (1.0 - skip_rate_penalty))
        ),
        4,
    )
    return {
        "score": score,
        "label": _execution_realism_label(score),
        "fill_retention_ratio": round(fill_retention_ratio, 4),
        "order_failure_penalty": round(order_failure_penalty, 4),
        "skip_rate_penalty": round(skip_rate_penalty, 4),
    }


def _execution_realism_from_score(score: float, **details: Any) -> dict[str, Any]:
    normalized = round(_clamp(score), 4)
    payload: dict[str, Any] = {
        "score": normalized,
        "label": _execution_realism_label(normalized),
    }
    for key, value in details.items():
        if value is None:
            continue
        if isinstance(value, (int, float)):
            payload[key] = round(float(value), 4)
        else:
            payload[key] = value
    return payload


def _btc5_confirmation(signal_source_audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "coverage_label": str(
            signal_source_audit.get("capital_ranking_support", {}).get("confirmation_coverage_label") or "missing"
        ),
        "strength_label": str(
            signal_source_audit.get("capital_ranking_support", {}).get("confirmation_strength_label") or "missing"
        ),
        "wallet_flow_status": str(signal_source_audit.get("wallet_flow_vs_llm", {}).get("status") or "unknown"),
        "btc_fast_window_confirmation_status": str(
            signal_source_audit.get("btc_fast_window_confirmation", {}).get("status") or "unknown"
        ),
    }


def _btc5_readiness(
    runtime_truth: dict[str, Any],
    *,
    package_confidence_label: str,
    runnable_package_available: bool,
) -> dict[str, Any]:
    stage_readiness = runtime_truth.get("btc5_stage_readiness") or {}
    deployment_confidence = runtime_truth.get("deployment_confidence") or {}
    return {
        "can_trade_now": bool(stage_readiness.get("can_trade_now")),
        "allowed_stage": _safe_int(deployment_confidence.get("allowed_stage"), 0),
        "allowed_stage_label": str(deployment_confidence.get("allowed_stage_label") or "stage_0"),
        "package_confidence_label": package_confidence_label or "low",
        "runnable_package_available": bool(runnable_package_available),
    }


def _signature(package: dict[str, Any] | None) -> str:
    if not isinstance(package, dict):
        return ""
    return json.dumps(package, sort_keys=True, separators=(",", ":"))


def _forecast_score(item: dict[str, Any]) -> float:
    p05_arr_pct = _safe_float(item.get("p05_arr_pct"), 0.0)
    if p05_arr_pct <= 0.0:
        return 0.0
    return round(_clamp(math.log10(max(1.0, p05_arr_pct + 1.0)) / 7.0), 4)


def _btc5_deployment_class(
    *,
    evidence_band: str,
    can_trade_now: bool,
    allowed_stage: int,
) -> str:
    if evidence_band == "validated":
        if can_trade_now and allowed_stage >= 1:
            return "validated_btc5_live_candidate"
        return "validated_btc5_blocked"
    return "btc5_probe_only"


def _btc5_blockers(
    *,
    evidence_band: str,
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    stage_readiness: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if evidence_band != "validated":
        blockers.append("validation_rows_below_live_threshold")
    blockers.extend(str(item) for item in (stage_readiness.get("trade_now_blocking_checks") or []))
    blockers.extend(str(item) for item in (runtime_truth.get("deployment_confidence", {}).get("blocking_checks") or []))
    blockers.extend(
        str(item)
        for item in (signal_source_audit.get("capital_ranking_support", {}).get("confirmation_blocking_checks") or [])
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for blocker in blockers:
        if not blocker or blocker in seen:
            continue
        seen.add(blocker)
        deduped.append(blocker)
    return deduped


def _btc5_blockers_with_extra(
    *,
    evidence_band: str,
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    stage_readiness: dict[str, Any],
    extra_blockers: list[str] | None = None,
) -> list[str]:
    blockers = _btc5_blockers(
        evidence_band=evidence_band,
        runtime_truth=runtime_truth,
        signal_source_audit=signal_source_audit,
        stage_readiness=stage_readiness,
    )
    blockers.extend(str(item) for item in (extra_blockers or []))
    return _blocking_checks(blockers)


def _present_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _btc5_runtime_package_guardrail_envelope(
    *,
    profile: dict[str, Any] | None,
    session_policy: list[dict[str, Any]] | None,
) -> dict[str, float | None]:
    max_abs_delta_values: list[float] = []
    up_cap_values: list[float] = []
    down_cap_values: list[float] = []

    for record in [profile or {}, *(session_policy or [])]:
        if not isinstance(record, dict):
            continue
        max_abs_delta = _present_optional_float(record.get("max_abs_delta"))
        up_max_buy_price = _present_optional_float(record.get("up_max_buy_price"))
        down_max_buy_price = _present_optional_float(record.get("down_max_buy_price"))
        if max_abs_delta is not None:
            max_abs_delta_values.append(max_abs_delta)
        if up_max_buy_price is not None:
            up_cap_values.append(up_max_buy_price)
        if down_max_buy_price is not None:
            down_cap_values.append(down_max_buy_price)

    return {
        "max_abs_delta": max(max_abs_delta_values) if max_abs_delta_values else None,
        "up_max_buy_price": max(up_cap_values) if up_cap_values else None,
        "down_max_buy_price": max(down_cap_values) if down_cap_values else None,
    }


def _btc5_stage0_guardrail_blockers(
    *,
    runtime_truth: dict[str, Any],
    profile: dict[str, Any] | None,
    session_policy: list[dict[str, Any]] | None,
) -> list[str]:
    maker = runtime_truth.get("btc_5min_maker") or {}
    recommendation = maker.get("guardrail_recommendation") or {}
    if not isinstance(recommendation, dict) or not recommendation:
        return []

    envelope = _btc5_runtime_package_guardrail_envelope(profile=profile, session_policy=session_policy)
    blockers: list[str] = []

    stage0_max_abs_delta = _present_optional_float(recommendation.get("max_abs_delta"))
    candidate_max_abs_delta = envelope.get("max_abs_delta")
    if (
        stage0_max_abs_delta is not None
        and candidate_max_abs_delta is not None
        and candidate_max_abs_delta > stage0_max_abs_delta + 1e-12
    ):
        blockers.append(
            f"stage0_max_abs_delta_exceeded:{candidate_max_abs_delta:.5f}>{stage0_max_abs_delta:.5f}"
        )

    fill_attribution = maker.get("fill_attribution") or {}
    recent_regime = fill_attribution.get("recent_direction_regime") or {}
    if not bool(recent_regime.get("triggered")):
        best_direction = str((fill_attribution.get("best_direction") or {}).get("label") or "").strip().upper()
        weaker_key = {"DOWN": "up_max_buy_price", "UP": "down_max_buy_price"}.get(best_direction)
        weaker_label = {"up_max_buy_price": "UP", "down_max_buy_price": "DOWN"}.get(weaker_key or "")
        allowed_weaker_cap = _present_optional_float(recommendation.get(weaker_key)) if weaker_key else None
        candidate_weaker_cap = envelope.get(weaker_key) if weaker_key else None
        if (
            weaker_key
            and weaker_label
            and allowed_weaker_cap is not None
            and candidate_weaker_cap is not None
            and candidate_weaker_cap > allowed_weaker_cap + 1e-12
        ):
            blockers.append(
                f"recent_regime_untriggered_{weaker_label.lower()}_cap_exceeded:"
                f"{candidate_weaker_cap:.2f}>{allowed_weaker_cap:.2f}"
            )

    return blockers


def _build_btc5_candidate(
    *,
    candidate_id: str,
    candidate_name: str,
    candidate_family: str,
    search_track: str,
    source: str,
    source_artifact: str,
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    evidence_band: str,
    validation_counts: dict[str, Any],
    arr_estimates: dict[str, Any],
    execution_realism: dict[str, Any],
    ranking_score: float,
    ranking_reason_tags: list[str],
    package_confidence_label: str,
    deployment_class: str | None = None,
    extra_blockers: list[str] | None = None,
    readiness_overrides: dict[str, Any] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stage_readiness = runtime_truth.get("btc5_stage_readiness") or {}
    deployment_confidence = runtime_truth.get("deployment_confidence") or {}
    resolved_evidence_band = str(evidence_band or _evidence_band(_safe_int(validation_counts.get("validation_live_filled_rows"))))
    resolved_deployment_class = deployment_class or _btc5_deployment_class(
        evidence_band=resolved_evidence_band,
        can_trade_now=bool(stage_readiness.get("can_trade_now")),
        allowed_stage=_safe_int(deployment_confidence.get("allowed_stage"), 0),
    )
    readiness = _btc5_readiness(
        runtime_truth,
        package_confidence_label=package_confidence_label,
        runnable_package_available=bool(
            readiness_overrides.get("runnable_package_available")
            if isinstance(readiness_overrides, dict) and "runnable_package_available" in readiness_overrides
            else True
        ),
    )
    if readiness_overrides:
        readiness.update(readiness_overrides)
    candidate = {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "market_scope": "btc_5m",
        "lane_type": "core_btc5",
        "candidate_family": candidate_family,
        "search_track": search_track,
        "source": source,
        "source_artifact": source_artifact,
        "deployment_class": resolved_deployment_class,
        "deployment_mode": "bounded_live_only" if resolved_deployment_class != "btc5_probe_only" else "shadow_only",
        "evidence_band": resolved_evidence_band,
        "validation_counts": validation_counts,
        "arr_estimates": arr_estimates,
        "execution_realism": execution_realism,
        "confirmation": _btc5_confirmation(signal_source_audit),
        "readiness": readiness,
        "ranking_score": round(_safe_float(ranking_score), 4),
        "ranking_reason_tags": _dedupe_texts([str(item) for item in ranking_reason_tags]),
        "blocking_checks": _btc5_blockers_with_extra(
            evidence_band=resolved_evidence_band,
            runtime_truth=runtime_truth,
            signal_source_audit=signal_source_audit,
            stage_readiness=stage_readiness,
            extra_blockers=extra_blockers,
        ),
    }
    if extra_fields:
        candidate.update(extra_fields)
    return candidate


def _normalize_btc5_candidates(
    *,
    autoresearch: dict[str, Any],
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    source_artifact: str,
) -> list[dict[str, Any]]:
    ranked = autoresearch.get("ranked_runtime_packages")
    if not isinstance(ranked, list):
        return []

    deployment_confidence = runtime_truth.get("deployment_confidence") or {}
    stage_readiness = runtime_truth.get("btc5_stage_readiness") or {}
    selected_signature = _signature(autoresearch.get("selected_best_runtime_package"))
    active_signature = _signature(autoresearch.get("active_runtime_package"))
    package_confidence_label = str(autoresearch.get("selected_package_confidence_label") or "").strip().lower() or str(
        autoresearch.get("package_confidence_label") or "low"
    ).strip().lower()
    candidates: list[dict[str, Any]] = []

    for item in ranked:
        if not isinstance(item, dict):
            continue
        runtime_package = item.get("runtime_package") if isinstance(item.get("runtime_package"), dict) else {}
        candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        profile = runtime_package.get("profile") if isinstance(runtime_package.get("profile"), dict) else {}
        session_policy = runtime_package.get("session_policy") if isinstance(runtime_package.get("session_policy"), list) else []
        if _btc5_stage0_guardrail_blockers(
            runtime_truth=runtime_truth,
            profile=profile,
            session_policy=session_policy,
        ):
            continue
        profile_name = str(
            profile.get("name")
            or (candidate.get("profile") or {}).get("name")
            or (candidate.get("base_profile") or {}).get("name")
            or item.get("source")
            or "btc5_candidate"
        )
        candidate_family = str(item.get("candidate_family") or candidate.get("candidate_family") or "unknown")
        validation_rows = _safe_int(
            item.get("validation_live_filled_rows"),
            _safe_int((candidate.get("scoring") or {}).get("validation_live_filled_rows"), 0),
        )
        evidence_band = str(
            (candidate.get("scoring") or {}).get("evidence_band") or _evidence_band(validation_rows)
        ).strip().lower()
        execution_realism = _execution_realism_btc5(item)
        deployment_class = _btc5_deployment_class(
            evidence_band=evidence_band,
            can_trade_now=bool(stage_readiness.get("can_trade_now")),
            allowed_stage=_safe_int(deployment_confidence.get("allowed_stage"), 0),
        )
        search_track = "hypothesis_sweep" if candidate_family == "hypothesis" else "package_selection"
        reason_tags = [
            f"source:{item.get('source') or 'unknown'}",
            f"candidate_family:{candidate_family}",
            f"evidence_band:{evidence_band}",
            f"execution_realism:{execution_realism['label']}",
        ]
        if _signature(runtime_package) == selected_signature and selected_signature:
            reason_tags.append("selected_best_runtime_package")
        if _signature(runtime_package) == active_signature and active_signature:
            reason_tags.append("active_runtime_package")
        if package_confidence_label:
            reason_tags.append(f"package_confidence:{package_confidence_label}")

        ranking_score = round(
            100.0
            * (
                0.45 * (_evidence_priority(evidence_band) / 3.0)
                + 0.35 * _safe_float(execution_realism.get("score"), 0.0)
                + 0.20 * _forecast_score(item)
            ),
            4,
        )
        candidates.append(
            _build_btc5_candidate(
                candidate_id=f"btc5:{profile_name}",
                candidate_name=profile_name,
                candidate_family=candidate_family,
                search_track=search_track,
                source=str(item.get("source") or "unknown"),
                source_artifact=source_artifact,
                runtime_truth=runtime_truth,
                signal_source_audit=signal_source_audit,
                evidence_band=evidence_band,
                validation_counts={
                    "validation_live_filled_rows": validation_rows,
                    "replay_live_filled_rows": _safe_int((candidate.get("historical") or {}).get("replay_live_filled_rows"), 0),
                    "replay_attempt_rows": _safe_int((candidate.get("historical") or {}).get("replay_attempt_rows"), 0),
                    "replay_window_rows": _safe_int((candidate.get("historical") or {}).get("replay_window_rows"), 0),
                },
                arr_estimates={
                    "p05_arr_pct": round(_safe_float(item.get("p05_arr_pct"), 0.0), 4),
                    "median_arr_pct": round(_safe_float(item.get("median_arr_pct"), 0.0), 4),
                    "p05_arr_delta_pct": round(_safe_float(item.get("p05_arr_delta_pct"), 0.0), 4),
                    "median_arr_delta_pct": round(_safe_float(item.get("median_arr_delta_pct"), 0.0), 4),
                },
                execution_realism=execution_realism,
                ranking_score=ranking_score,
                ranking_reason_tags=reason_tags,
                package_confidence_label=package_confidence_label,
                deployment_class=deployment_class,
                extra_fields={
                    "session_policy": session_policy,
                },
            )
        )

    candidates.sort(
        key=lambda item: (
            _deployment_priority(item.get("deployment_class")),
            _evidence_priority(item.get("evidence_band")),
            _safe_float(item.get("ranking_score"), 0.0),
        ),
        reverse=True,
    )
    return candidates


def _normalize_btc5_session_followups(
    *,
    current_probe: dict[str, Any],
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    source_artifact: str,
    existing_ids: set[str],
) -> list[dict[str, Any]]:
    regime_summary = current_probe.get("regime_policy_summary") or {}
    followups = regime_summary.get("best_live_followups") or []
    if not isinstance(followups, list):
        return []

    package_confidence_label = str(
        (runtime_truth.get("deployment_confidence") or {}).get("confidence_label")
        or current_probe.get("selected_package_confidence_label")
        or "low"
    ).strip().lower()
    candidates: list[dict[str, Any]] = []
    for item in followups:
        if not isinstance(item, dict):
            continue
        session_policy = item.get("session_policy") if isinstance(item.get("session_policy"), list) else []
        if _btc5_stage0_guardrail_blockers(
            runtime_truth=runtime_truth,
            profile={
                "max_abs_delta": item.get("max_abs_delta"),
                "up_max_buy_price": item.get("up_max_buy_price"),
                "down_max_buy_price": item.get("down_max_buy_price"),
            },
            session_policy=session_policy,
        ):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        candidate_id = f"btc5:{name}"
        if candidate_id in existing_ids:
            continue
        validation_rows = _safe_int(item.get("validation_live_filled_rows"), 0)
        evidence_band = str(item.get("evidence_band") or _evidence_band(validation_rows)).strip().lower()
        execution_score = _clamp(_safe_float(item.get("execution_realism_score"), 0.0))
        fill_retention = _safe_float(item.get("fill_retention_vs_active"), 0.0)
        ranking_score = round(
            100.0
            * (
                0.40 * (_evidence_priority(evidence_band) / 3.0)
                + 0.30 * execution_score
                + 0.20 * _forecast_score({"p05_arr_pct": item.get("validation_p05_arr_pct")})
                + 0.10 * _clamp(fill_retention / 1.05)
            ),
            4,
        )
        reason_tags = [
            "search_track:session_policy_followup",
            f"session_name:{item.get('session_name') or 'unknown'}",
            f"candidate_class:{item.get('candidate_class') or 'unknown'}",
            f"evidence_band:{evidence_band}",
            f"execution_realism:{str(item.get('execution_realism_label') or 'unknown').lower()}",
        ]
        promotion_gate = str(item.get("promotion_gate") or "").strip()
        if promotion_gate:
            reason_tags.append(f"promotion_gate:{promotion_gate}")
        candidates.append(
            _build_btc5_candidate(
                candidate_id=candidate_id,
                candidate_name=name,
                candidate_family="regime_policy_followup",
                search_track="session_policy_followup",
                source="current_probe_regime_policy",
                source_artifact=source_artifact,
                runtime_truth=runtime_truth,
                signal_source_audit=signal_source_audit,
                evidence_band=evidence_band,
                validation_counts={
                    "validation_live_filled_rows": validation_rows,
                    "session_policy_records": len(item.get("session_policy") or []),
                    "session_count": _safe_int(item.get("session_count"), len(item.get("session_policy") or [])),
                },
                arr_estimates={
                    "p05_arr_pct": round(_safe_float(item.get("validation_p05_arr_pct"), 0.0), 4),
                    "median_arr_pct": round(_safe_float(item.get("validation_median_arr_pct"), 0.0), 4),
                    "p05_arr_delta_pct": round(_safe_float(item.get("p05_arr_improvement_vs_active_pct"), 0.0), 4),
                    "median_arr_delta_pct": round(_safe_float(item.get("arr_improvement_vs_active_pct"), 0.0), 4),
                },
                execution_realism=_execution_realism_from_score(
                    execution_score,
                    fill_retention_vs_active=fill_retention,
                    profit_probability=_safe_float(item.get("validation_profit_probability"), 0.0),
                    generalization_ratio=_safe_float(item.get("generalization_ratio"), 0.0),
                ),
                ranking_score=ranking_score,
                ranking_reason_tags=reason_tags,
                package_confidence_label=package_confidence_label,
                extra_blockers=[
                    promotion_gate,
                ],
                extra_fields={
                    "session_policy": session_policy,
                    "follow_up_families": item.get("follow_up_families") or [],
                    "risk_metrics": {
                        "p95_drawdown_usd": round(_safe_float(item.get("validation_p95_drawdown_usd"), 0.0), 4),
                        "profit_probability": round(_safe_float(item.get("validation_profit_probability"), 0.0), 4),
                        "replay_pnl_usd": round(_safe_float(item.get("validation_replay_pnl_usd"), 0.0), 4),
                    },
                },
            )
        )
    candidates.sort(
        key=lambda item: (
            _deployment_priority(item.get("deployment_class")),
            _evidence_priority(item.get("evidence_band")),
            _safe_float(item.get("ranking_score"), 0.0),
        ),
        reverse=True,
    )
    return candidates


def _normalize_btc5_guardrail_followup(
    *,
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    source_artifact: str,
    existing_ids: set[str],
) -> list[dict[str, Any]]:
    maker = runtime_truth.get("btc_5min_maker") or {}
    recommendation = maker.get("guardrail_recommendation") or {}
    if not isinstance(recommendation, dict) or not recommendation:
        return []

    max_abs_delta = _safe_float(recommendation.get("max_abs_delta"), 0.0)
    up_max = _safe_float(recommendation.get("up_max_buy_price"), 0.0)
    down_max = _safe_float(recommendation.get("down_max_buy_price"), 0.0)
    candidate_name = f"guardrail_replay_d{max_abs_delta:.5f}_up{up_max:.2f}_down{down_max:.2f}"
    candidate_id = f"btc5:{candidate_name}"
    if candidate_id in existing_ids:
        return []

    baseline_rows = _safe_int(recommendation.get("baseline_live_filled_rows"), 0)
    replay_rows = _safe_int(recommendation.get("replay_live_filled_rows"), 0)
    baseline_pnl = _safe_float(recommendation.get("baseline_live_filled_pnl_usd"), 0.0)
    replay_pnl = _safe_float(recommendation.get("replay_live_filled_pnl_usd"), 0.0)
    recent_regime = ((maker.get("fill_attribution") or {}).get("recent_direction_regime") or {})
    fill_retention = (replay_rows / baseline_rows) if baseline_rows else 0.0
    regime_ready_score = 1.0 if bool(recent_regime.get("triggered")) else 0.45
    pnl_improvement = replay_pnl - baseline_pnl
    pnl_score = _clamp(0.5 + (pnl_improvement / max(10.0, abs(baseline_pnl), abs(replay_pnl), 1.0)))
    execution_score = _clamp((0.45 * fill_retention) + (0.30 * pnl_score) + (0.25 * regime_ready_score))
    evidence_band = _evidence_band(replay_rows)
    ranking_score = round(
        100.0
        * (
            0.35 * (_evidence_priority(evidence_band) / 3.0)
            + 0.40 * execution_score
            + 0.25 * _clamp(max(0.0, pnl_improvement) / 25.0)
        ),
        4,
    )
    blockers = [
        f"recent_quote_tick_regime:{str(recent_regime.get('trigger_reason') or 'unknown')}",
    ]
    latest_trade = maker.get("latest_trade") or {}
    latest_status = str(latest_trade.get("order_status") or "").strip()
    if latest_status:
        blockers.append(f"latest_order_status:{latest_status}")
    package_confidence_label = str(
        (runtime_truth.get("deployment_confidence") or {}).get("confidence_label") or "low"
    ).strip().lower()
    return [
        _build_btc5_candidate(
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            candidate_family="guardrail_followup",
            search_track="guardrail_parameter_sweep",
            source="runtime_guardrail_recommendation",
            source_artifact=source_artifact,
            runtime_truth=runtime_truth,
            signal_source_audit=signal_source_audit,
            evidence_band=evidence_band,
            validation_counts={
                "validation_live_filled_rows": replay_rows,
                "baseline_live_filled_rows": baseline_rows,
            },
            arr_estimates={
                "p05_arr_pct": 0.0,
                "median_arr_pct": 0.0,
                "p05_arr_delta_pct": 0.0,
                "median_arr_delta_pct": 0.0,
            },
            execution_realism=_execution_realism_from_score(
                execution_score,
                fill_retention_ratio=fill_retention,
                replay_pnl_usd=replay_pnl,
                baseline_pnl_usd=baseline_pnl,
                pnl_improvement_usd=pnl_improvement,
            ),
            ranking_score=ranking_score,
            ranking_reason_tags=[
                "search_track:guardrail_parameter_sweep",
                "source:runtime_guardrail_recommendation",
                f"best_direction:{((maker.get('fill_attribution') or {}).get('best_direction') or {}).get('label') or 'unknown'}",
                f"best_price_bucket:{((maker.get('fill_attribution') or {}).get('best_price_bucket') or {}).get('label') or 'unknown'}",
            ],
            package_confidence_label=package_confidence_label,
            deployment_class="btc5_probe_only",
            extra_blockers=blockers,
            readiness_overrides={"runnable_package_available": False},
            extra_fields={
                "guardrail_recommendation": recommendation,
                "quote_tick_followup": {
                    "favored_direction": recent_regime.get("favored_direction"),
                    "fills_considered": _safe_int(recent_regime.get("fills_considered"), 0),
                    "default_quote_ticks": _safe_int(recent_regime.get("default_quote_ticks"), 0),
                    "trigger_reason": recent_regime.get("trigger_reason"),
                    "triggered": bool(recent_regime.get("triggered")),
                },
            },
        )
    ]


def _normalize_btc5_loss_cluster_candidates(
    *,
    current_probe: dict[str, Any],
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    source_artifact: str,
) -> list[dict[str, Any]]:
    regime_summary = current_probe.get("regime_policy_summary") or {}
    suppressors = regime_summary.get("loss_cluster_suppression_candidates") or []
    if not isinstance(suppressors, list):
        return []

    package_confidence_label = str(
        (runtime_truth.get("deployment_confidence") or {}).get("confidence_label") or "low"
    ).strip().lower()
    candidates: list[dict[str, Any]] = []
    for item in suppressors[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("filter_name") or "").strip()
        if not name:
            session_name = str(item.get("session_name") or "session")
            direction = str(item.get("direction") or "direction").lower()
            price_bucket = str(item.get("price_bucket") or "bucket")
            delta_bucket = str(item.get("delta_bucket") or "delta")
            name = f"{direction}_{session_name}_{price_bucket}_{delta_bucket}"
        validation_rows = _safe_int(item.get("loss_rows"), 0)
        evidence_band = _evidence_band(validation_rows)
        severity = str(item.get("severity") or "high").strip().lower()
        severity_score = {"high": 1.0, "medium": 0.75, "low": 0.55}.get(severity, 0.65)
        loss_usd = abs(_safe_float(item.get("total_loss_usd"), 0.0))
        execution_score = _clamp(
            (0.50 * severity_score)
            + (0.30 * _clamp(validation_rows / 5.0))
            + (0.20 * _clamp(loss_usd / max(5.0, validation_rows * 5.0 if validation_rows else 5.0)))
        )
        ranking_score = round(
            100.0
            * (
                0.25 * (_evidence_priority(evidence_band) / 3.0)
                + 0.45 * execution_score
                + 0.30 * _clamp(loss_usd / 25.0)
            ),
            4,
        )
        candidates.append(
            _build_btc5_candidate(
                candidate_id=f"btc5:suppress:{name}",
                candidate_name=name,
                candidate_family="loss_cluster_suppression",
                search_track="loss_cluster_suppression",
                source="current_probe_loss_cluster",
                source_artifact=source_artifact,
                runtime_truth=runtime_truth,
                signal_source_audit=signal_source_audit,
                evidence_band=evidence_band,
                validation_counts={
                    "validation_live_filled_rows": validation_rows,
                    "negative_live_filled_rows": validation_rows,
                },
                arr_estimates={
                    "p05_arr_pct": 0.0,
                    "median_arr_pct": 0.0,
                    "p05_arr_delta_pct": 0.0,
                    "median_arr_delta_pct": 0.0,
                },
                execution_realism=_execution_realism_from_score(
                    execution_score,
                    severity=severity,
                    total_loss_usd=-loss_usd,
                ),
                ranking_score=ranking_score,
                ranking_reason_tags=[
                    "search_track:loss_cluster_suppression",
                    f"direction:{item.get('direction') or 'unknown'}",
                    f"session_name:{item.get('session_name') or 'unknown'}",
                    f"price_bucket:{item.get('price_bucket') or 'unknown'}",
                ],
                package_confidence_label=package_confidence_label,
                deployment_class="btc5_probe_only",
                extra_blockers=[
                    str(item.get("promotion_gate") or ""),
                    str(item.get("suggested_action") or ""),
                ],
                readiness_overrides={"runnable_package_available": False},
                extra_fields={
                    "suppression_target": {
                        "direction": item.get("direction"),
                        "session_name": item.get("session_name"),
                        "price_bucket": item.get("price_bucket"),
                        "delta_bucket": item.get("delta_bucket"),
                    },
                    "next_action": str(item.get("suggested_action") or "suppress_cluster_until_revalidated"),
                },
            )
        )
    candidates.sort(
        key=lambda item: (
            _deployment_priority(item.get("deployment_class")),
            _evidence_priority(item.get("evidence_band")),
            _safe_float(item.get("ranking_score"), 0.0),
        ),
        reverse=True,
    )
    return candidates


def _infer_interval_minutes(text: str) -> int | None:
    match = re.search(
        r"(\d{1,2}):(\d{2})\s*(am|pm)\s*-\s*(\d{1,2}):(\d{2})\s*(am|pm)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    def _to_minutes(hour_text: str, minute_text: str, ampm: str) -> int:
        hour = int(hour_text) % 12
        if ampm.lower() == "pm":
            hour += 12
        return (hour * 60) + int(minute_text)

    start = _to_minutes(match.group(1), match.group(2), match.group(3))
    end = _to_minutes(match.group(4), match.group(5), match.group(6))
    if end < start:
        end += 24 * 60
    diff = end - start
    return diff if diff > 0 else None


def infer_lane(text: str) -> str:
    lowered = str(text or "").lower()
    interval_minutes = _infer_interval_minutes(lowered)
    is_btc = "bitcoin" in lowered or "btc" in lowered
    is_eth = "ethereum" in lowered or "eth" in lowered

    if is_btc and any(token in lowered for token in ("15m", "15-minute", "15 minute")):
        return "btc_15m"
    if is_btc and interval_minutes == 15:
        return "btc_15m"
    if is_btc and any(token in lowered for token in ("5m", "5-minute", "5 minute")):
        return "btc_5m"
    if is_btc and interval_minutes == 5:
        return "btc_5m"
    if is_btc and any(token in lowered for token in ("4h", "4-hour", "4 hour")):
        return "btc_4h"
    if is_eth and any(token in lowered for token in ("5m", "15m", "30m", "1h", "2h", "3h", "4h", "intraday", "hour")):
        return "eth_intraday"
    return "other_fast"


def _toxicity_penalty(value: Any) -> float:
    lowered = str(value or "").strip().lower()
    if lowered == "toxic":
        return 1.0
    if lowered in {"neutral", "unknown"}:
        return 0.4
    return 0.2


def _execution_realism_adjacent(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "score": 0.1,
            "label": "weak",
            "expected_fill_probability": 0.0,
            "quality_flags": 0,
            "top_route_score": 0.0,
        }

    top_fill_probability = max(_safe_float(item.get("expected_maker_fill_probability"), 0.0) for item in records)
    max_route_score = max(_safe_float(item.get("route_score"), 0.0) for item in records)
    avg_flag_count = sum(len(item.get("data_quality_flags") or []) for item in records) / float(len(records))
    avg_visible_depth = sum(_safe_float(item.get("visible_depth_proxy"), 0.0) for item in records) / float(len(records))
    toxicity_penalty = max(_toxicity_penalty(item.get("toxicity_state")) for item in records)
    liquidity_component = _clamp(math.log10(max(1.0, avg_visible_depth + 1.0)) / 5.0)
    route_component = _clamp(max_route_score * 8.0)
    quality_component = 1.0 - _clamp(avg_flag_count / 4.0)
    score = round(
        _clamp(
            (0.35 * top_fill_probability)
            + (0.20 * route_component)
            + (0.20 * liquidity_component)
            + (0.15 * quality_component)
            + (0.10 * (1.0 - toxicity_penalty))
        ),
        4,
    )
    return {
        "score": score,
        "label": _execution_realism_label(score),
        "expected_fill_probability": round(top_fill_probability, 4),
        "quality_flags": round(avg_flag_count, 4),
        "top_route_score": round(max_route_score, 4),
    }


def _dedupe_texts(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _blocking_checks(values: list[str]) -> list[str]:
    filtered: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in NON_BLOCKING_MARKERS or lowered.startswith("clear_for_"):
            continue
        filtered.append(normalized)
    return _dedupe_texts(filtered)


def _adjacent_blockers(
    *,
    lane: str,
    fastlane_records: list[dict[str, Any]],
    edge_scan_records: list[dict[str, Any]],
    signal_source_audit: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not fastlane_records and not edge_scan_records:
        blockers.append("no_candidate_markets_observed")
    if not any(not str(item.get("reject_reason") or "").strip() for item in fastlane_records):
        blockers.append("no_replayable_evidence")
    reject_reasons = _dedupe_texts([str(item.get("reject_reason") or "") for item in fastlane_records])
    blockers.extend(reject_reasons)
    blockers.extend(
        str(item)
        for item in (signal_source_audit.get("capital_ranking_support", {}).get("confirmation_blocking_checks") or [])
    )
    if lane in {"btc_15m", "eth_intraday", "btc_4h"}:
        blockers.append("adjacent_lane_shadow_only_until_replayable_validation")
    return _dedupe_texts(blockers)


def _adjacent_evidence_band(
    *,
    fastlane_records: list[dict[str, Any]],
    edge_scan_records: list[dict[str, Any]],
) -> str:
    accepted = sum(1 for item in fastlane_records if not str(item.get("reject_reason") or "").strip())
    if accepted >= 3:
        return "candidate"
    if fastlane_records or edge_scan_records:
        return "exploratory"
    return "exploratory"


def _adjacent_lane_candidates(
    *,
    fastlane_payload: dict[str, Any],
    edge_scan_payload: dict[str, Any],
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    fastlane_source_artifact: str | None,
    edge_scan_source_artifact: str | None,
) -> list[dict[str, Any]]:
    fastlane_candidates = [
        item for item in (fastlane_payload.get("candidates") or []) if isinstance(item, dict)
    ]
    edge_scan_candidates = [
        item for item in (edge_scan_payload.get("candidate_markets") or []) if isinstance(item, dict)
    ]
    priority_order = list(fastlane_payload.get("universe", {}).get("priority_order") or ADJACENT_PRIORITY_ORDER)
    lanes = _dedupe_texts(priority_order + list(ADJACENT_PRIORITY_ORDER))

    by_lane_fastlane: dict[str, list[dict[str, Any]]] = {}
    for item in fastlane_candidates:
        lane = str(item.get("priority_lane") or infer_lane(str(item.get("title") or "")) or "other_fast")
        by_lane_fastlane.setdefault(lane, []).append(item)

    by_lane_edge_scan: dict[str, list[dict[str, Any]]] = {}
    for item in edge_scan_candidates:
        lane = infer_lane(str(item.get("question") or item.get("title") or ""))
        by_lane_edge_scan.setdefault(lane, []).append(item)
        if lane not in lanes and lane != "btc_5m":
            lanes.append(lane)

    wallet_flow_status = str((runtime_truth.get("wallet_flow") or {}).get("status") or "unknown")
    lmsr_status = str((((edge_scan_payload.get("lane_health") or {}).get("lmsr")) or {}).get("status") or "unknown")
    candidates: list[dict[str, Any]] = []

    for lane in lanes:
        if lane == "btc_5m":
            continue
        lane_fastlane = by_lane_fastlane.get(lane, [])
        lane_edge_scan = by_lane_edge_scan.get(lane, [])
        evidence_band = _adjacent_evidence_band(fastlane_records=lane_fastlane, edge_scan_records=lane_edge_scan)
        execution_realism = _execution_realism_adjacent(lane_fastlane)
        observed_markets = len(lane_fastlane) + len(lane_edge_scan)
        accepted_candidates = sum(1 for item in lane_fastlane if not str(item.get("reject_reason") or "").strip())
        route_component = _clamp(_safe_float(execution_realism.get("top_route_score"), 0.0) * 8.0)
        discovery_component = _clamp(observed_markets / 4.0)
        readiness_component = 1.0 if wallet_flow_status == "ready" else 0.4
        ranking_score = round(
            100.0
            * (
                0.40 * _safe_float(execution_realism.get("score"), 0.0)
                + 0.25 * discovery_component
                + 0.20 * readiness_component
                + 0.15 * route_component
            ),
            4,
        )
        blockers = _adjacent_blockers(
            lane=lane,
            fastlane_records=lane_fastlane,
            edge_scan_records=lane_edge_scan,
            signal_source_audit=signal_source_audit,
        )
        ranking_reason_tags = [
            "adjacent_fast_market",
            f"lane:{lane}",
            f"evidence_band:{evidence_band}",
            f"execution_realism:{execution_realism['label']}",
            f"wallet_flow_status:{wallet_flow_status}",
            f"lmsr_status:{lmsr_status}",
        ]
        if observed_markets > 0:
            ranking_reason_tags.append(f"observed_markets:{observed_markets}")
        if accepted_candidates > 0:
            ranking_reason_tags.append(f"accepted_candidates:{accepted_candidates}")

        sample_titles = _dedupe_texts(
            [str(item.get("title") or "") for item in lane_fastlane]
            + [str(item.get("question") or item.get("title") or "") for item in lane_edge_scan]
        )[:3]
        candidates.append(
            {
                "candidate_id": f"adjacent:{lane}",
                "candidate_name": lane.replace("_", " "),
                "market_scope": lane,
                "lane_type": "adjacent_fast_market",
                "candidate_family": "fast_market_discovery",
                "search_track": "adjacent_shadow_discovery",
                "source": "fastlane_surface",
                "source_artifact": fastlane_source_artifact or edge_scan_source_artifact or "reports/poly_fastlane_candidates_*.json",
                "deployment_class": "adjacent_shadow_only" if observed_markets > 0 else "adjacent_watch_only",
                "deployment_mode": "shadow_only",
                "evidence_band": evidence_band,
                "validation_counts": {
                    "validation_live_filled_rows": 0,
                    "accepted_candidate_markets": accepted_candidates,
                    "observed_candidate_markets": observed_markets,
                    "edge_scan_markets": len(lane_edge_scan),
                },
                "execution_realism": execution_realism,
                "confirmation": {
                    "coverage_label": str(
                        signal_source_audit.get("capital_ranking_support", {}).get("confirmation_coverage_label")
                        or "missing"
                    ),
                    "strength_label": str(
                        signal_source_audit.get("capital_ranking_support", {}).get("confirmation_strength_label")
                        or "missing"
                    ),
                    "wallet_flow_status": wallet_flow_status,
                    "lmsr_status": lmsr_status,
                },
                "readiness": {
                    "wallet_flow_ready": wallet_flow_status == "ready",
                    "lmsr_active": lmsr_status == "active",
                    "confirmation_support_status": str(
                        signal_source_audit.get("capital_ranking_support", {}).get("confirmation_support_status")
                        or "unknown"
                    ),
                },
                "sample_markets": sample_titles,
                "ranking_score": ranking_score,
                "ranking_reason_tags": ranking_reason_tags,
                "blocking_checks": blockers,
            }
        )

    candidates.sort(
        key=lambda item: (
            _deployment_priority(item.get("deployment_class")),
            _evidence_priority(item.get("evidence_band")),
            _safe_float(item.get("ranking_score"), 0.0),
        ),
        reverse=True,
    )
    return candidates


def build_fast_market_search_report(
    *,
    autoresearch: dict[str, Any],
    current_probe: dict[str, Any] | None = None,
    runtime_truth: dict[str, Any],
    signal_source_audit: dict[str, Any],
    hypothesis_frontier: dict[str, Any] | None = None,
    fastlane_payload: dict[str, Any],
    edge_scan_payload: dict[str, Any],
    autoresearch_source_artifact: str = str(DEFAULT_AUTORESEARCH),
    current_probe_source_artifact: str = str(DEFAULT_CURRENT_PROBE),
    runtime_truth_source_artifact: str = str(DEFAULT_RUNTIME_TRUTH),
    signal_source_audit_source_artifact: str = str(DEFAULT_SIGNAL_SOURCE_AUDIT),
    hypothesis_frontier_source_artifact: str = str(DEFAULT_HYPOTHESIS_FRONTIER),
    fastlane_source_artifact: str | None = None,
    edge_scan_source_artifact: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    current_probe_payload = current_probe if isinstance(current_probe, dict) else {}
    hypothesis_frontier_payload = hypothesis_frontier if isinstance(hypothesis_frontier, dict) else {}
    btc5_package_candidates = _normalize_btc5_candidates(
        autoresearch=autoresearch,
        runtime_truth=runtime_truth,
        signal_source_audit=signal_source_audit,
        source_artifact=autoresearch_source_artifact,
    )
    existing_ids = {str(item.get("candidate_id") or "") for item in btc5_package_candidates}
    btc5_followup_candidates = _normalize_btc5_session_followups(
        current_probe=current_probe_payload,
        runtime_truth=runtime_truth,
        signal_source_audit=signal_source_audit,
        source_artifact=current_probe_source_artifact,
        existing_ids=existing_ids,
    )
    existing_ids.update(str(item.get("candidate_id") or "") for item in btc5_followup_candidates)
    btc5_guardrail_candidates = _normalize_btc5_guardrail_followup(
        runtime_truth=runtime_truth,
        signal_source_audit=signal_source_audit,
        source_artifact=runtime_truth_source_artifact,
        existing_ids=existing_ids,
    )
    btc5_loss_cluster_candidates = _normalize_btc5_loss_cluster_candidates(
        current_probe=current_probe_payload,
        runtime_truth=runtime_truth,
        signal_source_audit=signal_source_audit,
        source_artifact=current_probe_source_artifact,
    )
    btc5_candidates = (
        btc5_package_candidates
        + btc5_followup_candidates
        + btc5_guardrail_candidates
        + btc5_loss_cluster_candidates
    )
    adjacent_candidates = _adjacent_lane_candidates(
        fastlane_payload=fastlane_payload,
        edge_scan_payload=edge_scan_payload,
        runtime_truth=runtime_truth,
        signal_source_audit=signal_source_audit,
        fastlane_source_artifact=fastlane_source_artifact,
        edge_scan_source_artifact=edge_scan_source_artifact,
    )
    ranked_candidates = btc5_candidates + adjacent_candidates
    ranked_candidates.sort(
        key=lambda item: (
            _deployment_priority(item.get("deployment_class")),
            _evidence_priority(item.get("evidence_band")),
            _safe_float(item.get("ranking_score"), 0.0),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked_candidates, start=1):
        item["rank"] = index

    lane_map: list[dict[str, Any]] = []
    for lane in ["btc_5m"] + list(ADJACENT_PRIORITY_ORDER):
        lane_items = [item for item in ranked_candidates if item.get("market_scope") == lane]
        top_item = lane_items[0] if lane_items else None
        lane_map.append(
            {
                "lane": lane,
                "candidate_count": len(lane_items),
                "observed_market_count": (
                    top_item.get("validation_counts", {}).get("observed_candidate_markets")
                    if top_item
                    else 0
                ),
                "validation_live_filled_rows": (
                    top_item.get("validation_counts", {}).get("validation_live_filled_rows")
                    if top_item
                    else 0
                ),
                "top_candidate_id": top_item.get("candidate_id") if top_item else None,
                "top_deployment_class": top_item.get("deployment_class") if top_item else "adjacent_watch_only",
                "top_evidence_band": top_item.get("evidence_band") if top_item else "exploratory",
                "top_ranking_score": top_item.get("ranking_score") if top_item else 0.0,
                "blocking_checks": top_item.get("blocking_checks") if top_item else ["no_candidate_markets_observed"],
            }
        )

    deployment_class_counts: dict[str, int] = {}
    for item in ranked_candidates:
        deployment_class = str(item.get("deployment_class") or "unknown")
        deployment_class_counts[deployment_class] = deployment_class_counts.get(deployment_class, 0) + 1

    search_tracks: list[dict[str, Any]] = []
    for track in SEARCH_TRACK_ORDER:
        track_items = [item for item in ranked_candidates if item.get("search_track") == track]
        top_item = track_items[0] if track_items else None
        search_tracks.append(
            {
                "track": track,
                "candidate_count": len(track_items),
                "best_candidate_id": top_item.get("candidate_id") if top_item else None,
                "best_deployment_class": top_item.get("deployment_class") if top_item else None,
                "best_evidence_band": top_item.get("evidence_band") if top_item else None,
                "primary_blockers": (top_item.get("blocking_checks") or [])[:5] if top_item else [],
            }
        )

    primary_blockers = _dedupe_texts(
        [blocker for item in ranked_candidates[:5] for blocker in (item.get("blocking_checks") or [])]
    )[:10]
    btc5_ranked = [item for item in ranked_candidates if item.get("market_scope") == "btc_5m"]
    summary_tracks = {item["track"]: item["candidate_count"] for item in search_tracks}
    summary = {
        "node_owner": "TradingNode4",
        "core_lane": "btc_5m",
        "best_candidate_id": ranked_candidates[0]["candidate_id"] if ranked_candidates else None,
        "best_btc5_candidate_id": btc5_ranked[0]["candidate_id"] if btc5_ranked else None,
        "best_runtime_package_id": btc5_package_candidates[0]["candidate_id"] if btc5_package_candidates else None,
        "best_session_followup_candidate_id": (
            next((item.get("best_candidate_id") for item in search_tracks if item["track"] == "session_policy_followup"), None)
        ),
        "best_guardrail_followup_candidate_id": (
            next((item.get("best_candidate_id") for item in search_tracks if item["track"] == "guardrail_parameter_sweep"), None)
        ),
        "best_loss_cluster_candidate_id": (
            next((item.get("best_candidate_id") for item in search_tracks if item["track"] == "loss_cluster_suppression"), None)
        ),
        "best_adjacent_candidate_id": adjacent_candidates[0]["candidate_id"] if adjacent_candidates else None,
        "ranked_candidate_count": len(ranked_candidates),
        "deployment_class_counts": deployment_class_counts,
        "search_track_counts": summary_tracks,
        "tracked_lanes": [item["lane"] for item in lane_map],
        "capital_policy": {
            "live_capital_rule": "validated_btc5_only",
            "size_expansion_rule": "larger_size_requires_fresh_evidence",
            "adjacent_lane_rule": "shadow_only_until_replayable_validation",
        },
        "primary_blockers": primary_blockers,
    }

    return {
        "schema": SCHEMA_VERSION,
        "generated_at": generated_at or _now_utc().isoformat(),
        "sources": {
            "autoresearch": {
                "path": autoresearch_source_artifact,
                "generated_at": autoresearch.get("generated_at"),
            },
            "current_probe": {
                "path": current_probe_source_artifact,
                "generated_at": current_probe_payload.get("generated_at"),
            },
            "runtime_truth": {
                "path": runtime_truth_source_artifact,
                "generated_at": runtime_truth.get("generated_at"),
            },
            "signal_source_audit": {
                "path": signal_source_audit_source_artifact,
                "generated_at": signal_source_audit.get("generated_at"),
            },
            "hypothesis_frontier": {
                "path": hypothesis_frontier_source_artifact,
                "generated_at": hypothesis_frontier_payload.get("latest_finished_at"),
            },
            "fastlane_candidates": {
                "path": fastlane_source_artifact,
                "generated_at": fastlane_payload.get("generated_at"),
            },
            "edge_scan": {
                "path": edge_scan_source_artifact,
                "generated_at": edge_scan_payload.get("generated_at"),
            },
        },
        "summary": summary,
        "lane_map": lane_map,
        "search_tracks": search_tracks,
        "exploratory_hypothesis_frontier": {
            "candidate_name": hypothesis_frontier_payload.get("latest_hypothesis_name"),
            "direction": hypothesis_frontier_payload.get("latest_direction"),
            "session_name": hypothesis_frontier_payload.get("latest_session_name"),
            "evidence_band": hypothesis_frontier_payload.get("latest_evidence_band"),
            "validation_live_filled_rows": _safe_int(
                hypothesis_frontier_payload.get("latest_validation_live_filled_rows"),
                0,
            ),
            "generalization_ratio": round(
                _safe_float(hypothesis_frontier_payload.get("latest_generalization_ratio"), 0.0),
                4,
            ),
            "frontier_p05_arr_pct": round(_safe_float(hypothesis_frontier_payload.get("frontier_p05_arr_pct"), 0.0), 4),
            "frontier_median_arr_pct": round(
                _safe_float(hypothesis_frontier_payload.get("frontier_median_arr_pct"), 0.0),
                4,
            ),
        },
        "ranked_candidates": ranked_candidates,
    }


def write_report_artifacts(
    *,
    output_dir: Path,
    payload: dict[str, Any],
    stamp: str | None = None,
    history_jsonl: Path | None = None,
) -> dict[str, str]:
    actual_stamp = stamp or _stamp()
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / "latest.json"
    snapshot_path = output_dir / f"fast_market_search_{actual_stamp}.json"
    latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if history_jsonl is not None:
        history_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with history_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return {
        "latest_json": str(latest_path),
        "snapshot_json": str(snapshot_path),
        "history_jsonl": str(history_jsonl) if history_jsonl is not None else "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autoresearch", type=Path, default=DEFAULT_AUTORESEARCH)
    parser.add_argument("--current-probe", type=Path, default=DEFAULT_CURRENT_PROBE)
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--signal-source-audit", type=Path, default=DEFAULT_SIGNAL_SOURCE_AUDIT)
    parser.add_argument("--hypothesis-frontier", type=Path, default=DEFAULT_HYPOTHESIS_FRONTIER)
    parser.add_argument(
        "--fastlane-candidates",
        type=Path,
        default=None,
        help="Explicit fast-lane candidate artifact. Defaults to the newest reports/poly_fastlane_candidates_*.json.",
    )
    parser.add_argument(
        "--edge-scan",
        type=Path,
        default=None,
        help="Explicit edge scan artifact. Defaults to the newest reports/edge_scan_*.json.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--history-jsonl",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "history.jsonl",
        help="Append each rendered payload to this history file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    fastlane_path = args.fastlane_candidates or _find_latest_report(repo_root, "poly_fastlane_candidates_*.json")
    edge_scan_path = args.edge_scan or _find_latest_report(repo_root, "edge_scan_*.json")

    payload = build_fast_market_search_report(
        autoresearch=_load_json(args.autoresearch),
        current_probe=_load_json(args.current_probe),
        runtime_truth=_load_json(args.runtime_truth),
        signal_source_audit=_load_json(args.signal_source_audit),
        hypothesis_frontier=_load_json(args.hypothesis_frontier),
        fastlane_payload=_load_json(fastlane_path) if fastlane_path is not None else {},
        edge_scan_payload=_load_json(edge_scan_path) if edge_scan_path is not None else {},
        autoresearch_source_artifact=_relative_path_text(repo_root, args.autoresearch) or str(args.autoresearch),
        current_probe_source_artifact=_relative_path_text(repo_root, args.current_probe) or str(args.current_probe),
        runtime_truth_source_artifact=_relative_path_text(repo_root, args.runtime_truth) or str(args.runtime_truth),
        signal_source_audit_source_artifact=(
            _relative_path_text(repo_root, args.signal_source_audit) or str(args.signal_source_audit)
        ),
        hypothesis_frontier_source_artifact=(
            _relative_path_text(repo_root, args.hypothesis_frontier) or str(args.hypothesis_frontier)
        ),
        fastlane_source_artifact=_relative_path_text(repo_root, fastlane_path),
        edge_scan_source_artifact=_relative_path_text(repo_root, edge_scan_path),
    )
    artifacts = write_report_artifacts(
        output_dir=args.output_dir,
        payload=payload,
        history_jsonl=args.history_jsonl,
    )
    print(json.dumps({"generated_at": payload.get("generated_at"), "artifacts": artifacts}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
