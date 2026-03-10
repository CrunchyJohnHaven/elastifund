from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

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


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number} must contain JSON objects")
        rows.append(payload)
    return rows


def _read_json_payload(path: Path) -> Any:
    return json.loads(path.read_text())


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
    upstream_commit: str = OPENCLAW_AUDITED_COMMIT,
    captured_at: str | None = None,
) -> BenchmarkEvidencePacket:
    telemetry, raw_metadata = summarize_openclaw_diagnostics(diagnostics_events)
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
        "raw_event_type_counts": raw_metadata["event_type_counts"],
        "comparison_count": len(comparison_rows),
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
        metadata=metadata,
    )
