"""JJ-N first-dollar reporting helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from nontrading.models import EngineState, FirstDollarReadiness
from orchestration.models import NON_TRADING_AGENT, REVENUE_AUDIT_ENGINE

UTC = timezone.utc
PUBLIC_REPORT_SCHEMA_VERSION = "nontrading_public_report.v2"
BENCHMARK_COMPARISON_SCHEMA_VERSION = "nontrading_benchmark_comparison.v1"
DEFAULT_REQUIRED_BUDGET_USD = 12.0
DEFAULT_SEND_QUOTA_CAP = 10
DEFAULT_LLM_TOKEN_CAP = 2500
DEFAULT_MARGIN_PCT = 0.60


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "ready", "verified"}
    return bool(value)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _seconds_between(start: str | None, end: str | None) -> float | None:
    start_dt = _parse_timestamp(start)
    end_dt = _parse_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    return round(max((end_dt - start_dt).total_seconds(), 0.0), 6)


def _pick_value(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _mapping_or_attr(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def build_operations_summary(
    *,
    status_snapshot: Mapping[str, Any],
    engine_states: Sequence[EngineState],
) -> dict[str, Any]:
    revenue_pipeline = next(
        (state for state in engine_states if state.engine_name == "revenue_pipeline"),
        None,
    )
    revenue_metadata = dict(revenue_pipeline.metadata) if revenue_pipeline is not None else {}
    active_engines = [
        {
            "engine_name": state.engine_name,
            "engine_family": state.engine_family,
            "status": state.status,
            "run_mode": state.run_mode,
            "kill_switch_active": state.kill_switch_active,
        }
        for state in engine_states
    ]
    return {
        "global_kill_switch": bool(status_snapshot.get("global_kill_switch")),
        "deliverability_status": str(status_snapshot.get("deliverability_status") or "unknown").strip().lower(),
        "engine_states_recorded": int(status_snapshot.get("engine_states") or len(engine_states)),
        "engine_kill_switches": int(status_snapshot.get("engine_kill_switches") or 0),
        "run_modes": sorted({str(state.run_mode or "unknown") for state in engine_states}),
        "active_engines": active_engines,
        "revenue_pipeline": {
            "present": revenue_pipeline is not None,
            "status": revenue_pipeline.status if revenue_pipeline is not None else None,
            "run_mode": revenue_pipeline.run_mode if revenue_pipeline is not None else None,
            "kill_switch_active": revenue_pipeline.kill_switch_active if revenue_pipeline is not None else False,
            "last_heartbeat_at": revenue_pipeline.last_heartbeat_at if revenue_pipeline is not None else None,
            "last_event_at": revenue_pipeline.last_event_at if revenue_pipeline is not None else None,
            "latest_cycle_time_seconds": _seconds_between(
                revenue_metadata.get("started_at"),
                revenue_metadata.get("completed_at"),
            ),
        },
    }


def normalize_launch_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else {}
    operator_checklist = raw.get("operator_checklist") if isinstance(raw.get("operator_checklist"), Mapping) else {}
    source = {**metrics, **raw}
    normalized = {
        "checkout_ready": _safe_bool(_pick_value(source, "checkout_ready", "checkout_surface_ready")),
        "webhook_ready": _safe_bool(_pick_value(source, "webhook_ready", "stripe_webhook_ready", "webhook_verified")),
        "manual_close_ready": _safe_bool(_pick_value(source, "manual_close_ready", "approval_lane_ready")),
        "fulfillment_ready": _safe_bool(_pick_value(source, "fulfillment_ready", "fulfillment_surface_ready")),
        "checkout_sessions_created": _safe_int(
            _pick_value(source, "checkout_sessions_created", "checkout_sessions", "sessions_created")
        ),
        "orders_recorded": _safe_int(_pick_value(source, "orders_recorded", "order_count")),
        "paid_orders_seen": _safe_int(_pick_value(source, "paid_orders_seen", "paid_order_count")),
        "paid_revenue_usd": round(
            _safe_float(_pick_value(source, "paid_revenue_usd", "collected_revenue_usd")),
            2,
        ),
        "refund_rate": _pick_value(source, "refund_rate"),
        "first_paid_order_at": _pick_value(source, "first_paid_order_at", "paid_order_at"),
        "delivery_artifacts_generated": _safe_int(
            _pick_value(source, "delivery_artifacts_generated", "fulfillment_artifacts_generated")
        ),
        "monitor_runs_completed": _safe_int(
            _pick_value(source, "monitor_runs_completed", "recurring_monitor_runs_completed")
        ),
        "operating_cost_usd_30d": round(_safe_float(_pick_value(source, "operating_cost_usd_30d")), 2),
        "live_offer_url": _pick_value(source, "live_offer_url", "offer_url"),
        "launch_checklist_artifact": (
            str(
                _pick_value(source, "launch_checklist_artifact")
                or operator_checklist.get("source_artifact")
                or ""
            ).strip()
            or None
        ),
        "source_artifact": str(_pick_value(source, "source_artifact") or "").strip() or None,
    }
    if normalized["paid_orders_seen"] > 0:
        normalized["checkout_ready"] = True
        normalized["webhook_ready"] = True
    return normalized


def _expected_orders_30d(
    *,
    funnel: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> float:
    stage_estimates = (
        _safe_int(launch.get("checkout_sessions_created")) * 0.35,
        _safe_int(funnel.get("proposals_sent")) * 0.55,
        _safe_int(funnel.get("meetings_booked")) * 0.30,
        _safe_int(funnel.get("delivered_messages")) * 0.10,
        _safe_int(funnel.get("qualified_accounts")) * 0.18,
    )
    return max(stage_estimates, default=0.0)


def _confidence_for_status(
    *,
    status: str,
    funnel: Mapping[str, Any],
    operations: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> float:
    base = {
        "setup_only": 0.10,
        "launchable": 0.35,
        "paid_order_seen": 0.65,
        "first_dollar_observed": 0.85,
    }[status]
    bonus = min(
        0.10,
        (_safe_int(funnel.get("qualified_accounts")) * 0.01)
        + (_safe_int(funnel.get("proposals_sent")) * 0.03)
        + (_safe_int(launch.get("paid_orders_seen")) * 0.05),
    )
    deliverability_penalty = {
        "green": 0.0,
        "yellow": 0.05,
        "red": 0.10,
    }.get(str(operations.get("deliverability_status") or "").strip().lower(), 0.02)
    return round(_clamp(base + bonus - deliverability_penalty), 6)


def _arr_lab_confidence(payload: Mapping[str, Any] | None) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    confidence = payload.get("confidence")
    if isinstance(confidence, Mapping):
        score = confidence.get("score")
        if score is not None:
            return round(_clamp(_safe_float(score)), 6)
    return None


def build_first_dollar_readiness(
    *,
    snapshot: Mapping[str, Any],
    offer: Any,
    operations: Mapping[str, Any],
    launch_summary: Mapping[str, Any] | None = None,
    arr_lab: Mapping[str, Any] | None = None,
    source_artifacts: Mapping[str, str] | None = None,
) -> FirstDollarReadiness:
    funnel = dict(snapshot.get("funnel") or {})
    commercial = dict(snapshot.get("commercial") or {})
    freshness = dict(snapshot.get("freshness") or {})
    launch = normalize_launch_summary(launch_summary)
    revenue_won_usd = round(_safe_float(commercial.get("revenue_won_usd")), 2)
    paid_orders_seen = _safe_int(launch.get("paid_orders_seen"))
    paid_revenue_usd = round(_safe_float(launch.get("paid_revenue_usd")), 2)
    first_dollar_at = str(freshness.get("first_revenue_at") or "").strip() or None
    manual_close_ready = bool(
        launch.get("manual_close_ready")
        or _safe_int(funnel.get("proposals_sent")) > 0
        or revenue_won_usd > 0.0
    )
    fulfillment_ready = bool(
        launch.get("fulfillment_ready")
        or _safe_int(snapshot.get("fulfillment", {}).get("events_recorded")) > 0
        or revenue_won_usd > 0.0
    )
    launch_gates = {
        "offer_defined": bool(_mapping_or_attr(offer, "slug") and _mapping_or_attr(offer, "name")),
        "pipeline_available": bool(
            operations.get("revenue_pipeline", {}).get("present")
            or _safe_int(funnel.get("researched_accounts")) > 0
        ),
        "checkout_surface_ready": bool(launch.get("checkout_ready")),
        "billing_webhook_ready": bool(launch.get("webhook_ready")),
        "manual_close_ready": manual_close_ready,
        "fulfillment_surface_ready": fulfillment_ready,
        "compliance_clear": not bool(operations.get("global_kill_switch"))
        and _safe_int(operations.get("engine_kill_switches")) == 0,
    }
    launchable_gate_keys = (
        "checkout_surface_ready",
        "billing_webhook_ready",
        "manual_close_ready",
        "fulfillment_surface_ready",
    )
    launchable_now = all(bool(launch_gates[key]) for key in launchable_gate_keys)

    if revenue_won_usd > 0.0 or first_dollar_at:
        status = "first_dollar_observed"
    elif paid_orders_seen > 0:
        status = "paid_order_seen"
    elif launchable_now:
        status = "launchable"
    else:
        status = "setup_only"

    price_range = _mapping_or_attr(offer, "price_range", (500, 2500))
    low_price = max(1.0, _safe_float(price_range[0], 500.0))
    margin_pct = _safe_float(commercial.get("gross_margin_pct"), DEFAULT_MARGIN_PCT)
    if margin_pct <= 0:
        margin_pct = DEFAULT_MARGIN_PCT
    if status == "first_dollar_observed":
        expected_net_cash_30d = round(
            max(_safe_float(commercial.get("gross_margin_usd")), revenue_won_usd * margin_pct),
            2,
        )
    elif status == "paid_order_seen":
        expected_net_cash_30d = round(
            max(0.0, paid_revenue_usd * margin_pct),
            2,
        )
    elif status == "launchable":
        expected_net_cash_30d = round(
            _expected_orders_30d(funnel=funnel, launch=launch) * low_price * margin_pct,
            2,
        )
    else:
        expected_net_cash_30d = 0.0

    if status in {"launchable", "paid_order_seen", "first_dollar_observed"}:
        launchable = True
        blocking_reasons: tuple[str, ...] = ()
    else:
        launchable = False
        gate_labels = {
            "checkout_surface_ready": "checkout_surface_not_ready",
            "billing_webhook_ready": "billing_webhook_not_ready",
            "manual_close_ready": "manual_close_lane_not_ready",
            "fulfillment_surface_ready": "fulfillment_surface_not_ready",
        }
        blocking_reasons = tuple(
            gate_labels[key]
            for key in launchable_gate_keys
            if not launch_gates[key]
        )

    artifacts = {
        str(key): str(value)
        for key, value in (source_artifacts or {}).items()
        if value is not None and str(value).strip()
    }
    if launch.get("source_artifact"):
        artifacts["launch_summary"] = str(launch["source_artifact"])
    if launch.get("launch_checklist_artifact"):
        artifacts["launch_checklist_artifact"] = str(launch["launch_checklist_artifact"])

    confidence = _confidence_for_status(
        status=status,
        funnel=funnel,
        operations=operations,
        launch=launch,
    )
    arr_lab_confidence = _arr_lab_confidence(arr_lab)
    if arr_lab_confidence is not None:
        confidence = round(_clamp((confidence * 0.6) + (arr_lab_confidence * 0.4)), 6)

    return FirstDollarReadiness(
        status=status,
        launchable=launchable,
        paid_orders_seen=paid_orders_seen,
        paid_revenue_usd=paid_revenue_usd,
        first_paid_order_at=str(launch.get("first_paid_order_at") or "").strip() or None,
        first_dollar_at=first_dollar_at,
        time_to_first_dollar_hours=commercial.get("time_to_first_dollar_hours"),
        checkout_sessions_created=_safe_int(launch.get("checkout_sessions_created")),
        orders_recorded=_safe_int(launch.get("orders_recorded")),
        delivery_artifacts_generated=_safe_int(launch.get("delivery_artifacts_generated")),
        monitor_runs_completed=_safe_int(launch.get("monitor_runs_completed")),
        expected_net_cash_30d=expected_net_cash_30d,
        confidence=confidence,
        launch_gates=launch_gates,
        blocking_reasons=blocking_reasons,
        source_artifacts=artifacts,
    )


def build_allocator_input(
    *,
    snapshot: Mapping[str, Any],
    readiness: FirstDollarReadiness,
    operations: Mapping[str, Any],
    launch_summary: Mapping[str, Any] | None = None,
    arr_lab: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    commercial = dict(snapshot.get("commercial") or {})
    launch = normalize_launch_summary(launch_summary)
    deliverability_status = str(operations.get("deliverability_status") or "unknown").strip().lower()
    if not readiness.launch_gates.get("compliance_clear", True):
        compliance_status = "fail"
    elif readiness.status in {"launchable", "paid_order_seen", "first_dollar_observed"} and deliverability_status == "green":
        compliance_status = "pass"
    else:
        compliance_status = "warning"

    refund_rate = launch.get("refund_rate")
    refund_penalty = round(_clamp(_safe_float(refund_rate)), 6) if refund_rate is not None else 0.0
    if readiness.status == "paid_order_seen" and readiness.delivery_artifacts_generated == 0:
        fulfillment_penalty = 0.10
    elif readiness.status == "first_dollar_observed" and readiness.monitor_runs_completed == 0:
        fulfillment_penalty = 0.02
    else:
        fulfillment_penalty = 0.0
    domain_health_penalty = {
        "green": 0.0,
        "yellow": 0.05,
        "red": 0.15,
    }.get(deliverability_status, 0.02)

    arr_lab_summary = (
        {
            "forecast_net_cash_30d_p50": arr_lab.get("summary", {}).get("p50_net_cash_30d"),
            "forecast_arr_usd_p50": arr_lab.get("summary", {}).get("p50_arr_usd"),
            "forecast_confidence": arr_lab.get("confidence", {}).get("score"),
            "forecast_confidence_label": arr_lab.get("confidence", {}).get("label"),
            "recommended_experiment": arr_lab.get("recommended_next_experiment", {}).get("experiment_key"),
        }
        if isinstance(arr_lab, Mapping)
        else {}
    )
    return {
        "engine_family": REVENUE_AUDIT_ENGINE,
        "agent_name": NON_TRADING_AGENT,
        "expected_net_cash_30d": readiness.expected_net_cash_30d,
        "confidence": readiness.confidence,
        "required_budget": DEFAULT_REQUIRED_BUDGET_USD,
        "capacity_limits": {
            "budget_usd": DEFAULT_REQUIRED_BUDGET_USD,
            "send_quota": DEFAULT_SEND_QUOTA_CAP,
            "llm_tokens": DEFAULT_LLM_TOKEN_CAP,
        },
        "refund_penalty": refund_penalty,
        "fulfillment_penalty": round(fulfillment_penalty, 6),
        "domain_health_penalty": round(domain_health_penalty, 6),
        "compliance_status": compliance_status,
        "metadata": {
            "first_dollar_status": readiness.status,
            "launchable": readiness.launchable,
            "launch_gates": dict(readiness.launch_gates),
            "blocking_reasons": list(readiness.blocking_reasons),
            "launch_checklist_artifact": launch.get("launch_checklist_artifact"),
            "paid_orders_seen": readiness.paid_orders_seen,
            "paid_revenue_usd": readiness.paid_revenue_usd,
            "revenue_won_usd": round(_safe_float(commercial.get("revenue_won_usd")), 2),
            "gross_margin_usd": round(_safe_float(commercial.get("gross_margin_usd")), 2),
            "time_to_first_dollar_hours": commercial.get("time_to_first_dollar_hours"),
            "deliverability_status": deliverability_status,
            "comparison_only": False,
            "excluded_from_allocator": False,
            "arr_lab": {key: value for key, value in arr_lab_summary.items() if value is not None},
        },
    }


def build_first_dollar_scoreboard(
    *,
    snapshot: Mapping[str, Any],
    readiness: FirstDollarReadiness,
    allocator_input: Mapping[str, Any],
    launch_summary: Mapping[str, Any] | None = None,
    arr_lab: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    funnel = dict(snapshot.get("funnel") or {})
    commercial = dict(snapshot.get("commercial") or {})
    launch = normalize_launch_summary(launch_summary)
    checkout_sessions_created = readiness.checkout_sessions_created
    paid_order_conversion = None
    if checkout_sessions_created > 0:
        paid_order_conversion = round(readiness.paid_orders_seen / checkout_sessions_created, 6)
    return {
        "metric_name": "JJ-N first-dollar scoreboard",
        "status": readiness.status,
        "launchable": readiness.launchable,
        "checkout_sessions_created": checkout_sessions_created,
        "orders_recorded": readiness.orders_recorded,
        "paid_orders_seen": readiness.paid_orders_seen,
        "paid_order_conversion_rate": paid_order_conversion,
        "paid_revenue_usd": readiness.paid_revenue_usd,
        "revenue_won_usd": round(_safe_float(commercial.get("revenue_won_usd")), 2),
        "gross_margin_usd": round(_safe_float(commercial.get("gross_margin_usd")), 2),
        "gross_margin_pct": commercial.get("gross_margin_pct"),
        "time_to_first_dollar_hours": commercial.get("time_to_first_dollar_hours"),
        "time_to_first_dollar_status": commercial.get("time_to_first_dollar_status"),
        "delivery_artifacts_generated": readiness.delivery_artifacts_generated,
        "monitor_runs_completed": readiness.monitor_runs_completed,
        "qualified_accounts": _safe_int(funnel.get("qualified_accounts")),
        "proposals_sent": _safe_int(funnel.get("proposals_sent")),
        "expected_net_cash_30d": readiness.expected_net_cash_30d,
        "allocator_confidence": allocator_input.get("confidence"),
        "allocator_required_budget": allocator_input.get("required_budget"),
        "allocator_compliance_status": allocator_input.get("compliance_status"),
        "forecast_net_cash_30d_p50": (
            arr_lab.get("summary", {}).get("p50_net_cash_30d")
            if isinstance(arr_lab, Mapping)
            else None
        ),
        "forecast_arr_usd_p50": (
            arr_lab.get("summary", {}).get("p50_arr_usd")
            if isinstance(arr_lab, Mapping)
            else None
        ),
        "forecast_confidence_label": (
            arr_lab.get("confidence", {}).get("label")
            if isinstance(arr_lab, Mapping)
            else None
        ),
        "recommended_experiment": (
            arr_lab.get("recommended_next_experiment", {}).get("experiment_key")
            if isinstance(arr_lab, Mapping)
            else None
        ),
        "blocking_reasons": list(readiness.blocking_reasons),
        "live_offer_url": launch.get("live_offer_url"),
    }


def _normalize_benchmark_isolation(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(payload)
    normalized = {
        "namespace": str(raw.get("namespace") or "comparison-only").strip() or "comparison-only",
        "wallet_access": str(raw.get("wallet_access") or "none").strip() or "none",
        "shared_state_access": str(raw.get("shared_state_access") or "none").strip() or "none",
        "secrets_scope": str(raw.get("secrets_scope") or "isolated").strip() or "isolated",
        "state_scope": str(raw.get("state_scope") or "isolated").strip() or "isolated",
        "log_index_prefix": str(raw.get("log_index_prefix") or "").strip() or None,
    }
    return normalized


def _normalize_benchmark_metadata(
    payload: Mapping[str, Any],
    *,
    comparison_mode: str,
    allocator_eligible: bool,
    comparison_case_count: int,
) -> dict[str, Any]:
    raw = dict(payload)
    metadata = {
        "spec_version": str(raw.get("spec_version") or "").strip() or None,
        "execution_label": str(raw.get("execution_label") or "").strip() or None,
        "evaluation_track": str(raw.get("evaluation_track") or "").strip() or None,
        "upstream_repo": str(raw.get("upstream_repo") or "").strip() or None,
        "upstream_commit": str(raw.get("upstream_commit") or "").strip() or None,
        "comparison_mode": comparison_mode,
        "allocator_eligible": allocator_eligible,
        "comparison_case_count": comparison_case_count,
    }
    adapter_metadata = raw.get("metadata")
    if isinstance(adapter_metadata, Mapping) and adapter_metadata:
        metadata["adapter_metadata"] = dict(adapter_metadata)
    return {key: value for key, value in metadata.items() if value is not None}


def _normalize_benchmark_notes(
    *,
    payload: Mapping[str, Any],
    comparison_only: bool,
    comparison_case_count: int,
    isolation: Mapping[str, Any] | None,
) -> list[str]:
    raw_notes = payload.get("notes")
    if isinstance(raw_notes, Sequence) and not isinstance(raw_notes, (str, bytes)):
        notes = [str(item).strip() for item in raw_notes if str(item).strip()]
    else:
        notes = []
    if not notes:
        if comparison_only:
            notes.append("OpenClaw comparison is isolated and excluded from live allocator decisions.")
        else:
            notes.append("Benchmark payload is present but must remain excluded from allocator decisions.")
    if comparison_case_count > 0:
        notes.append(f"Normalized {comparison_case_count} shared outcome comparison case(s).")
    if isolation and (
        isolation.get("wallet_access") != "none"
        or isolation.get("shared_state_access") != "none"
    ):
        notes.append("Isolation contract violation: wallet or shared state access is not disabled.")
    return notes


def normalize_benchmark_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(payload or {})
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), Mapping) else {}
    telemetry = raw.get("telemetry") if isinstance(raw.get("telemetry"), Mapping) else {}
    source = {**telemetry, **metrics, **raw}
    provided = bool(payload)
    comparison_rows = (
        raw.get("outcome_comparisons")
        if isinstance(raw.get("outcome_comparisons"), Sequence) and not isinstance(raw.get("outcome_comparisons"), (str, bytes))
        else []
    )
    comparison_case_count = len(comparison_rows)
    comparison_mode = str(_pick_value(source, "comparison_mode", "evaluation_track") or "").strip() or None
    allocator_eligible = _safe_bool(_pick_value(source, "allocator_eligible"))
    comparison_only = (
        _safe_bool(_pick_value(source, "comparison_only"))
        or comparison_mode == "comparison_only"
        or not allocator_eligible
    )
    cycle_time_seconds_value = _pick_value(source, "cycle_time_seconds")
    if cycle_time_seconds_value is not None:
        cycle_time_seconds = round(_safe_float(cycle_time_seconds_value), 6)
    elif _pick_value(source, "avg_cycle_time_ms") is not None:
        cycle_time_seconds = round(_safe_float(_pick_value(source, "avg_cycle_time_ms")) / 1000.0, 6)
    else:
        cycle_time_seconds = None
    source_artifact = str(_pick_value(source, "source_artifact") or "").strip() or None
    if source_artifact is None and isinstance(raw.get("source_artifacts"), Sequence) and not isinstance(
        raw.get("source_artifacts"),
        (str, bytes),
    ):
        for artifact in raw.get("source_artifacts", []):
            candidate = str(artifact).strip()
            if candidate:
                source_artifact = candidate
                break
    isolation = (
        _normalize_benchmark_isolation(raw["isolation"])
        if isinstance(raw.get("isolation"), Mapping)
        else None
    )
    return {
        "system_id": str(_pick_value(source, "system_id", "bot_id") or "openclaw"),
        "label": str(_pick_value(source, "label", "system_name") or "OpenClaw"),
        "status": str(_pick_value(source, "status") or ("comparison_ready" if provided else "awaiting_adapter")),
        "source_artifact": source_artifact,
        "comparison_mode": comparison_mode or ("comparison_only" if provided else None),
        "comparison_only": comparison_only,
        "excluded_from_allocator": not allocator_eligible,
        "allocator_eligible": allocator_eligible,
        "metrics": {
            "cycle_time_seconds": cycle_time_seconds,
            "decision_count": (
                _safe_int(_pick_value(source, "decision_count"))
                if _pick_value(source, "decision_count") is not None
                else None
            ),
            "cost_usd": (
                round(_safe_float(_pick_value(source, "cost_usd", "operating_cost_usd", "total_cost_usd")), 2)
                if _pick_value(source, "cost_usd", "operating_cost_usd", "total_cost_usd") is not None
                else None
            ),
            "outcome_value_usd": (
                round(_safe_float(_pick_value(source, "outcome_value_usd", "revenue_won_usd")), 2)
                if _pick_value(source, "outcome_value_usd", "revenue_won_usd") is not None
                else None
            ),
            "confidence": (
                round(_clamp(_safe_float(_pick_value(source, "confidence"))), 6)
                if _pick_value(source, "confidence") is not None
                else None
            ),
        },
        "isolation": isolation,
        "metadata": (
            _normalize_benchmark_metadata(
                raw,
                comparison_mode=comparison_mode or ("comparison_only" if provided else "comparison_only"),
                allocator_eligible=allocator_eligible,
                comparison_case_count=comparison_case_count,
            )
            if provided
            else {}
        ),
        "notes": _normalize_benchmark_notes(
            payload=raw,
            comparison_only=comparison_only,
            comparison_case_count=comparison_case_count,
            isolation=isolation,
        )
        if provided
        else [
            "Awaiting the isolated OpenClaw sibling benchmark adapter output.",
            "Benchmark rows stay comparison_only and excluded from live allocator decisions.",
        ],
    }


def build_comparison_artifact(
    *,
    snapshot: Mapping[str, Any],
    operations: Mapping[str, Any],
    readiness: FirstDollarReadiness,
    allocator_input: Mapping[str, Any],
    launch_summary: Mapping[str, Any] | None = None,
    benchmark_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    funnel = dict(snapshot.get("funnel") or {})
    commercial = dict(snapshot.get("commercial") or {})
    launch = normalize_launch_summary(launch_summary)
    benchmark = normalize_benchmark_payload(benchmark_payload)
    elastifund_row = {
        "system_id": "elastifund_jjn",
        "label": "Elastifund JJ-N",
        "engine_family": REVENUE_AUDIT_ENGINE,
        "status": readiness.status,
        "comparison_only": False,
        "excluded_from_allocator": False,
        "metrics": {
            "cycle_time_seconds": operations.get("revenue_pipeline", {}).get("latest_cycle_time_seconds"),
            "decision_count": _safe_int(funnel.get("researched_accounts")),
            "cost_usd": launch.get("operating_cost_usd_30d"),
            "outcome_value_usd": round(_safe_float(commercial.get("revenue_won_usd")), 2),
            "expected_net_cash_30d": readiness.expected_net_cash_30d,
            "confidence": allocator_input.get("confidence"),
        },
        "source_artifact": readiness.source_artifacts.get("public_report"),
    }
    return {
        "schema_version": BENCHMARK_COMPARISON_SCHEMA_VERSION,
        "generated_at": readiness.generated_at,
        "state": "comparison_ready" if benchmark_payload else "awaiting_benchmark_payload",
        "evaluation_contract": "inventory/metrics/README.md",
        "allocator_guardrail": "comparison_only rows are excluded from live allocator decisions.",
        "items": [
            elastifund_row,
            {
                "system_id": benchmark["system_id"],
                "label": benchmark["label"],
                "engine_family": "comparison_only",
                "status": benchmark["status"],
                "comparison_mode": benchmark["comparison_mode"],
                "comparison_only": benchmark["comparison_only"],
                "excluded_from_allocator": benchmark["excluded_from_allocator"],
                "allocator_eligible": benchmark["allocator_eligible"],
                "metrics": benchmark["metrics"],
                "source_artifact": benchmark["source_artifact"],
                "isolation": benchmark["isolation"],
                "metadata": benchmark["metadata"],
                "notes": benchmark["notes"],
            },
        ],
    }
