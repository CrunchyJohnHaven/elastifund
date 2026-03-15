from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from infra.fast_json import load_path, loads as fast_loads
from inventory.metrics.evidence_plane import (
    COMPARISON_ONLY_MODE,
    BenchmarkEvidencePacket,
    BenchmarkTelemetrySummary,
    IsolationBoundary,
    OutcomeComparison,
)


OPENCLAW_SYSTEM_ID = "openclaw"
OPENCLAW_SYSTEM_NAME = "OpenClaw"
OPENCLAW_UPSTREAM_REPOSITORY = "https://github.com/openclaw/openclaw.git"
OPENCLAW_AUDITED_COMMIT = "59bc3c66300ba93a71b4220146e7135950387770"
OPENCLAW_AUDITED_VERSION = "2026.3.9"
DEFAULT_NAMESPACE = "openclaw-benchmark"
DEFAULT_LOG_INDEX_PREFIX = "elastifund-openclaw-benchmark"
MODEL_TIER_ROUTINE_INGESTION = "routine_ingestion"
MODEL_TIER_STRUCTURED_RANKING = "structured_ranking"
MODEL_TIER_CONFLICT_ARBITRATION = "conflict_arbitration"
_MODEL_TIER_ORDER = (
    MODEL_TIER_ROUTINE_INGESTION,
    MODEL_TIER_STRUCTURED_RANKING,
    MODEL_TIER_CONFLICT_ARBITRATION,
)
_MODEL_TIER_ESTIMATED_COST_PER_MINUTE = {
    MODEL_TIER_ROUTINE_INGESTION: 0.004,
    MODEL_TIER_STRUCTURED_RANKING: 0.02,
    MODEL_TIER_CONFLICT_ARBITRATION: 0.08,
}
_MODEL_TIER_CONFIDENCE_GAIN = {
    MODEL_TIER_ROUTINE_INGESTION: 0.0,
    MODEL_TIER_STRUCTURED_RANKING: 0.20,
    MODEL_TIER_CONFLICT_ARBITRATION: 0.32,
}
_MODEL_TIER_CONFIDENCE_TARGET = {
    MODEL_TIER_ROUTINE_INGESTION: 0.0,
    MODEL_TIER_STRUCTURED_RANKING: 0.65,
    MODEL_TIER_CONFLICT_ARBITRATION: 0.82,
}
_MODEL_TIER_MIN_ARR_BPS = {
    MODEL_TIER_ROUTINE_INGESTION: 0.0,
    MODEL_TIER_STRUCTURED_RANKING: 5.0,
    MODEL_TIER_CONFLICT_ARBITRATION: 20.0,
}
_MODEL_TIER_MIN_ARR_PER_MIN = {
    MODEL_TIER_ROUTINE_INGESTION: 0.0,
    MODEL_TIER_STRUCTURED_RANKING: 3.0,
    MODEL_TIER_CONFLICT_ARBITRATION: 10.0,
}
_MODEL_TIER_MIN_CONF_GAIN = {
    MODEL_TIER_ROUTINE_INGESTION: 0.0,
    MODEL_TIER_STRUCTURED_RANKING: 0.08,
    MODEL_TIER_CONFLICT_ARBITRATION: 0.12,
}


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = fast_loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number} must contain JSON objects")
        rows.append(payload)
    return rows


def _read_json_payload(path: Path) -> Any:
    return load_path(path)


def load_jsonl_events(path: str | Path) -> list[dict[str, Any]]:
    """Load OpenClaw diagnostic events from a JSONL file."""

    return _read_json_lines(Path(path))


def load_outcome_comparisons(path: str | Path) -> list[dict[str, Any]]:
    """Load shared evaluation comparisons from JSON or JSONL."""

    source = Path(path)
    if source.suffix == ".jsonl":
        return _read_json_lines(source)

    payload = _read_json_payload(source)
    if isinstance(payload, list):
        return [dict(item) for item in payload]
    if isinstance(payload, dict):
        if isinstance(payload.get("comparisons"), list):
            return [dict(item) for item in payload["comparisons"]]
        if isinstance(payload.get("items"), list):
            return [dict(item) for item in payload["items"]]
    raise ValueError(f"{source} must contain a list or a {{comparisons: [...]}} object")


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coherent_float(value: float | None) -> float | None:
    if value is None:
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return float(value)


def _normalize_model_tier(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return MODEL_TIER_ROUTINE_INGESTION
    if "arb" in raw or "conflict" in raw:
        return MODEL_TIER_CONFLICT_ARBITRATION
    if "struct" in raw or "rank" in raw or "synth" in raw:
        return MODEL_TIER_STRUCTURED_RANKING
    if "cheap" in raw or "mini" in raw or "basic" in raw or "small" in raw or "flash" in raw:
        return MODEL_TIER_ROUTINE_INGESTION
    return MODEL_TIER_ROUTINE_INGESTION


def _confidence_after_tier(base_confidence: float | None, model_tier: str) -> float:
    base_confidence_value = _coerce_float(base_confidence)
    if base_confidence_value is None:
        base_confidence_value = 0.52
    gain = _MODEL_TIER_CONFIDENCE_GAIN.get(model_tier, 0.0)
    return min(1.0, base_confidence_value + gain)


def _model_minutes(duration_ms_sum: float | None, model_usage_events: int) -> float | None:
    if not model_usage_events:
        return None
    if duration_ms_sum is None or duration_ms_sum <= 0:
        return None
    return max(duration_ms_sum / 60_000.0, 0.000001)


def _estimated_arr_uplift_per_model_minute(
    expected_arr_delta: float | None,
    model_minutes: float | None,
) -> float | None:
    arr_delta = _coerce_float(expected_arr_delta)
    if arr_delta is None or model_minutes is None or model_minutes <= 0:
        return None
    return _coherent_float(arr_delta / model_minutes)


def _estimate_selected_model_cost(model_minutes: float | None, model_tier: str) -> float | None:
    if model_minutes is None:
        return None
    cost_rate = _MODEL_TIER_ESTIMATED_COST_PER_MINUTE.get(
        model_tier,
        _MODEL_TIER_ESTIMATED_COST_PER_MINUTE[MODEL_TIER_ROUTINE_INGESTION],
    )
    return round(model_minutes * cost_rate, 6)


def _round_currency(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def _should_route_to_tier(
    model_tier: str,
    expected_arr_delta: float | None,
    candidate_confidence: float | None,
    arr_uplift_per_minute: float | None,
) -> bool:
    arr_delta = _coerce_float(expected_arr_delta)
    if arr_delta is None or arr_delta <= 0:
        return False
    if arr_delta < _MODEL_TIER_MIN_ARR_BPS.get(model_tier, 0.0):
        return False
    if arr_uplift_per_minute is not None and arr_uplift_per_minute < _MODEL_TIER_MIN_ARR_PER_MIN.get(
        model_tier,
        0.0,
    ):
        return False
    gain = _confidence_after_tier(candidate_confidence, model_tier) - (
        _coerce_float(candidate_confidence) or 0.52
    )
    if gain < _MODEL_TIER_MIN_CONF_GAIN.get(model_tier, 0.0):
        return False
    return (
        _confidence_after_tier(candidate_confidence, model_tier)
        >= _MODEL_TIER_CONFIDENCE_TARGET.get(model_tier, 1.0)
    )


def _build_routing_plan(
    *,
    expected_arr_delta: float | None,
    candidate_confidence: float | None,
    raw_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    model_tier_counts = raw_metadata.get("model_tier_counts")
    if isinstance(model_tier_counts, Mapping) and model_tier_counts:
        observed = sorted(model_tier_counts.items(), key=lambda item: item[1], reverse=True)[0][0]
        if observed not in _MODEL_TIER_ORDER:
            observed = MODEL_TIER_ROUTINE_INGESTION
    else:
        observed = MODEL_TIER_ROUTINE_INGESTION

    model_minutes = _model_minutes(
        duration_ms_sum=_coerce_float(raw_metadata.get("model_duration_ms_total")),
        model_usage_events=_coerce_int(raw_metadata.get("model_usage_events")) or 0,
    )
    arr_uplift_per_minute = _estimated_arr_uplift_per_model_minute(
        expected_arr_delta=expected_arr_delta,
        model_minutes=model_minutes,
    )

    selected_tier = MODEL_TIER_ROUTINE_INGESTION
    escalation_reasons: list[str] = []
    for candidate_tier in _MODEL_TIER_ORDER[1:]:
        if _should_route_to_tier(
            candidate_tier,
            expected_arr_delta=expected_arr_delta,
            candidate_confidence=candidate_confidence,
            arr_uplift_per_minute=arr_uplift_per_minute,
        ):
            selected_tier = candidate_tier
            escalation_reasons.append(f"escalated_to_{candidate_tier}")

    estimated_cost = _estimate_selected_model_cost(model_minutes, selected_tier)
    detected_cost = _coerce_float(raw_metadata.get("total_cost_usd"))
    if estimated_cost is not None and detected_cost is not None:
        estimated_compute_cost_usd = max(detected_cost, estimated_cost)
        selected_cost_justification = "harmonized_from_observed_and_estimate"
    elif estimated_cost is not None:
        estimated_compute_cost_usd = estimated_cost
        selected_cost_justification = "estimated_from_model_minutes"
    else:
        estimated_compute_cost_usd = detected_cost
        selected_cost_justification = "observed_cost_missing"

    base_conf = _coerce_float(candidate_confidence)
    if base_conf is None:
        base_conf = 0.52
    confidence_gain = _confidence_after_tier(base_conf, selected_tier) - base_conf

    return {
        "model_tier": selected_tier,
        "estimated_compute_cost_usd": _round_currency(_coherent_float(estimated_compute_cost_usd)),
        "observed_model_cost_usd": _round_currency(detected_cost),
        "observed_model_minutes": model_minutes,
        "estimated_arr_uplift_per_model_minute": _coherent_float(arr_uplift_per_minute),
        "estimated_confidence_gain": _coherent_float(confidence_gain),
        "observed_model_tier": observed,
        "routing_reason": ", ".join(escalation_reasons) if escalation_reasons else "kept_at_cheapest_tier",
        "escalation_allowed": selected_tier != MODEL_TIER_ROUTINE_INGESTION,
        "selected_cost_justification": selected_cost_justification,
    }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(value) for value in values)
    rank = max(0, min(len(ordered) - 1, round((percentile / 100.0) * (len(ordered) - 1))))
    return ordered[rank]


def _utc_isoformat_from_ms(ts_ms: int | float | None) -> str | None:
    if ts_ms is None:
        return None
    return (
        datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _now_utc_isoformat() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_comparisons(
    comparisons: Sequence[Mapping[str, Any]] | None,
    *,
    comparison_system_id: str,
) -> tuple[OutcomeComparison, ...]:
    if not comparisons:
        return ()
    return tuple(
        OutcomeComparison.from_mapping(
            item,
            reference_system_id="elastifund",
            comparison_system_id=comparison_system_id,
        )
        for item in comparisons
    )


def summarize_openclaw_diagnostics(
    events: Sequence[Mapping[str, Any]],
) -> tuple[BenchmarkTelemetrySummary, dict[str, Any]]:
    message_durations: list[float] = []
    model_durations: list[float] = []
    event_types: Counter[str] = Counter()
    first_ts_ms: int | None = None
    last_ts_ms: int | None = None
    decision_count = 0
    completed_count = 0
    skipped_count = 0
    error_count = 0
    webhook_count = 0
    model_usage_events = 0
    total_cost_usd = 0.0
    model_duration_ms_total = 0.0
    model_tier_counts: Counter[str] = Counter()
    max_lane_queue_size = 0
    heartbeat_max_active = 0
    heartbeat_max_waiting = 0
    heartbeat_max_queued = 0

    for raw_event in events:
        event = dict(raw_event)
        event_type = str(event.get("type") or "").strip()
        if not event_type:
            continue
        event_types[event_type] += 1

        event_ts = _coerce_int(event.get("ts"))
        if event_ts is not None:
            first_ts_ms = event_ts if first_ts_ms is None else min(first_ts_ms, event_ts)
            last_ts_ms = event_ts if last_ts_ms is None else max(last_ts_ms, event_ts)

        if event_type == "message.processed":
            decision_count += 1
            outcome = str(event.get("outcome") or "").strip().lower()
            if outcome == "completed":
                completed_count += 1
            elif outcome == "skipped":
                skipped_count += 1
            else:
                error_count += 1
            duration_ms = _coerce_float(event.get("durationMs"))
            if duration_ms is not None and duration_ms >= 0:
                message_durations.append(duration_ms)
        elif event_type == "model.usage":
            model_usage_events += 1
            duration_ms = _coerce_float(event.get("durationMs"))
            if duration_ms is not None and duration_ms >= 0:
                model_durations.append(duration_ms)
                model_duration_ms_total += duration_ms
            model_tier = _normalize_model_tier(
                event.get("model_tier") or event.get("tier") or event.get("model")
            )
            model_tier_counts[model_tier] += 1
            cost_usd = _coerce_float(event.get("costUsd"))
            if cost_usd is not None and cost_usd >= 0:
                total_cost_usd += cost_usd
        elif event_type == "webhook.processed":
            webhook_count += 1
        elif event_type == "queue.lane.enqueue":
            queue_size = _coerce_int(event.get("queueSize"))
            if queue_size is not None:
                max_lane_queue_size = max(max_lane_queue_size, queue_size)
        elif event_type == "diagnostic.heartbeat":
            heartbeat_max_active = max(
                heartbeat_max_active,
                _coerce_int(event.get("active")) or 0,
            )
            heartbeat_max_waiting = max(
                heartbeat_max_waiting,
                _coerce_int(event.get("waiting")) or 0,
            )
            heartbeat_max_queued = max(
                heartbeat_max_queued,
                _coerce_int(event.get("queued")) or 0,
            )

    telemetry = BenchmarkTelemetrySummary(
        decision_count=decision_count,
        completed_decision_count=completed_count,
        skipped_decision_count=skipped_count,
        error_decision_count=error_count,
        webhook_count=webhook_count,
        model_usage_events=model_usage_events,
        avg_cycle_time_ms=mean(message_durations) if message_durations else None,
        p95_cycle_time_ms=_percentile(message_durations, 95.0),
        avg_model_duration_ms=mean(model_durations) if model_durations else None,
        total_cost_usd=total_cost_usd,
        max_lane_queue_size=max_lane_queue_size,
        heartbeat_max_active=heartbeat_max_active,
        heartbeat_max_waiting=heartbeat_max_waiting,
        heartbeat_max_queued=heartbeat_max_queued,
    )
    metadata = {
        "event_count": len(events),
        "event_type_counts": dict(event_types),
        "first_event_ts_ms": first_ts_ms,
        "last_event_ts_ms": last_ts_ms,
        "model_duration_ms_total": model_duration_ms_total,
        "model_usage_events": model_usage_events,
        "model_tier_counts": dict(model_tier_counts),
        "total_cost_usd": round(total_cost_usd, 6),
    }
    return telemetry, metadata


def build_openclaw_benchmark_packet(
    *,
    run_id: str,
    diagnostics_events: Sequence[Mapping[str, Any]],
    outcome_comparisons: Sequence[Mapping[str, Any]] | None = None,
    namespace: str = DEFAULT_NAMESPACE,
    log_index_prefix: str = DEFAULT_LOG_INDEX_PREFIX,
    source_artifacts: Sequence[str] = (),
    source: str | None = "openclaw",
    upstream_commit: str = OPENCLAW_AUDITED_COMMIT,
    pipeline_version: str | None = None,
    expected_arr_delta: float | None = None,
    improvement_velocity: float | None = None,
    candidate_confidence: float | None = None,
    data_timestamp: str | None = None,
    captured_at: str | None = None,
) -> BenchmarkEvidencePacket:
    telemetry, raw_metadata = summarize_openclaw_diagnostics(diagnostics_events)
    routing_plan = _build_routing_plan(
        expected_arr_delta=expected_arr_delta,
        candidate_confidence=candidate_confidence,
        raw_metadata=raw_metadata,
    )
    started_at = _utc_isoformat_from_ms(raw_metadata.get("first_event_ts_ms"))
    finished_at = _utc_isoformat_from_ms(raw_metadata.get("last_event_ts_ms"))
    comparison_rows = _normalize_comparisons(
        outcome_comparisons,
        comparison_system_id=OPENCLAW_SYSTEM_ID,
    )
    isolation = IsolationBoundary(
        namespace=namespace,
        secrets_scope="isolated",
        state_scope="isolated",
        wallet_access="none",
        shared_state_access="none",
        log_index_prefix=log_index_prefix,
        metadata={
            "aws_stack_mode": "sibling",
            "allocator_access": "denied",
        },
    )
    metadata = {
        "upstream_version": OPENCLAW_AUDITED_VERSION,
        "comparison_reason": "sibling benchmark only",
        "comparison_only": True,
        "routing": routing_plan,
        "routing_version": "2026.03-openclaw-routing-v1",
        "raw_event_type_counts": raw_metadata["event_type_counts"],
        "comparison_count": len(comparison_rows),
        "pipeline_version": raw_metadata.get("pipeline_version"),
    }
    return BenchmarkEvidencePacket(
        system_id=OPENCLAW_SYSTEM_ID,
        system_name=OPENCLAW_SYSTEM_NAME,
        run_id=run_id,
        comparison_mode=COMPARISON_ONLY_MODE,
        allocator_eligible=False,
        upstream_repo=OPENCLAW_UPSTREAM_REPOSITORY,
        upstream_commit=upstream_commit,
        execution_label="internal_simulation",
        evaluation_track=COMPARISON_ONLY_MODE,
        captured_at=captured_at or finished_at or _now_utc_isoformat(),
        started_at=started_at,
        finished_at=finished_at,
        telemetry=telemetry,
        isolation=isolation,
        outcome_comparisons=comparison_rows,
        source_artifacts=tuple(source_artifacts),
        source=source,
        expected_arr_delta=expected_arr_delta,
        improvement_velocity=improvement_velocity,
        candidate_confidence=candidate_confidence,
        data_timestamp=data_timestamp,
        pipeline_version=pipeline_version,
        metadata=metadata,
    )
