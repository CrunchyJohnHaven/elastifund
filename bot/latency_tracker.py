"""Latency tracking helpers for structured logs, APM, and Elastic."""

from __future__ import annotations

import contextlib
import functools
import inspect
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, ParamSpec, TypeVar

from bot import elastic_client
from bot.apm_setup import capture_span, current_trace_id, get_apm_manager
from bot.log_config import ecs_extra


logger = logging.getLogger("JJ.latency")

get_apm_runtime = get_apm_manager

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(slots=True)
class LatencyEvent:
    operation: str
    latency_ms: float
    success: bool = True
    error: str | None = None
    timestamp: str | None = None
    trace_id: str | None = None

    def to_document(self) -> dict[str, Any]:
        timestamp = self.timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return {
            "@timestamp": timestamp,
            "timestamp": timestamp,
            "operation": self.operation,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error": self.error,
            "trace_id": self.trace_id,
        }


def emit_latency_event(event: LatencyEvent) -> None:
    try:
        elastic_client.index_latency(event.to_document())
    except Exception as exc:
        logger.warning("latency indexing failed: %s", exc)


def _metric_name_for_operation(operation_name: str) -> str:
    normalized = operation_name.lower()
    if "llm" in normalized or "estimate_probability" in normalized:
        return "llm_response_ms"
    if "fill" in normalized:
        return "order_to_fill_ms"
    if "ws" in normalized:
        return "ws_message_lag_ms"
    return "signal_latency_ms"


def _emit_latency(operation_name: str, latency_ms: float, *, success: bool, error: str | None = None) -> None:
    logger.info(
        "latency_tracked",
        extra=ecs_extra(
            operation=operation_name,
            latency_ms=round(latency_ms, 3),
            success=success,
            error=error,
            trace_id=current_trace_id(),
        ),
    )

    runtime = get_apm_runtime()
    runtime.record_metric(
        _metric_name_for_operation(operation_name),
        latency_ms,
        labels={"operation": operation_name},
    )
    emit_latency_event(
        LatencyEvent(
            operation=operation_name,
            latency_ms=round(latency_ms, 3),
            success=success,
            error=error,
            trace_id=current_trace_id(),
        )
    )


def track_latency(operation_name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                started = time.perf_counter()
                with capture_span(operation_name, span_type="latency"):
                    try:
                        result = await func(*args, **kwargs)
                    except Exception as exc:
                        _emit_latency(
                            operation_name,
                            (time.perf_counter() - started) * 1000.0,
                            success=False,
                            error=str(exc),
                        )
                        raise
                _emit_latency(operation_name, (time.perf_counter() - started) * 1000.0, success=True)
                return result

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.perf_counter()
            with capture_span(operation_name, span_type="latency"):
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    _emit_latency(
                        operation_name,
                        (time.perf_counter() - started) * 1000.0,
                        success=False,
                        error=str(exc),
                    )
                    raise
            _emit_latency(operation_name, (time.perf_counter() - started) * 1000.0, success=True)
            return result

        return sync_wrapper

    return decorator


def get_latency_report(hours: int = 24) -> dict[str, dict[str, float]]:
    client = elastic_client.get_raw_client()
    if client is None:
        return {}

    query = {
        "size": 0,
        "query": {
            "range": {
                "@timestamp": {
                    "gte": f"now-{max(1, int(hours))}h",
                }
            }
        },
        "aggs": {
            "operations": {
                "terms": {"field": "operation.keyword", "size": 100},
                "aggs": {
                    "p50": {"percentiles": {"field": "latency_ms", "percents": [50]}},
                    "p95": {"percentiles": {"field": "latency_ms", "percents": [95]}},
                    "p99": {"percentiles": {"field": "latency_ms", "percents": [99]}},
                },
            }
        },
    }

    try:
        response = client.search(index="elastifund-latency*", body=query)
    except TypeError:  # pragma: no cover - newer client signature
        response = client.search(
            index="elastifund-latency*",
            query=query["query"],
            aggs=query["aggs"],
            size=0,
        )
    except Exception as exc:
        logger.warning("latency report query failed: %s", exc)
        return {}

    buckets = (
        response.get("aggregations", {})
        .get("operations", {})
        .get("buckets", [])
    )
    report: dict[str, dict[str, float]] = {}
    for bucket in buckets:
        op = bucket.get("key")
        if not op:
            continue
        report[str(op)] = {
            "p50_ms": float(bucket["p50"]["values"].get("50.0", 0.0)),
            "p95_ms": float(bucket["p95"]["values"].get("95.0", 0.0)),
            "p99_ms": float(bucket["p99"]["values"].get("99.0", 0.0)),
        }
    return report
