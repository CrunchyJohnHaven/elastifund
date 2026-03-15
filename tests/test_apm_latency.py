from __future__ import annotations

import contextlib
import json
import logging
import time

from bot import apm_setup, latency_tracker, log_config


def test_track_latency_emits_event(monkeypatch) -> None:
    events: list[latency_tracker.LatencyEvent] = []
    recorded_metrics: list[tuple[str, float, dict[str, str] | None]] = []

    class DummyRuntime:
        def record_metric(self, name: str, value: float, *, labels=None) -> None:
            recorded_metrics.append((name, value, labels))

    monkeypatch.setattr(latency_tracker, "emit_latency_event", lambda event: events.append(event))
    monkeypatch.setattr(latency_tracker, "get_apm_runtime", lambda: DummyRuntime())
    monkeypatch.setattr(latency_tracker, "capture_span", lambda *args, **kwargs: contextlib.nullcontext())

    @latency_tracker.track_latency("estimate_probability")
    def measured_call() -> str:
        time.sleep(0.01)
        return "ok"

    assert measured_call() == "ok"
    assert len(events) == 1
    assert events[0].operation == "estimate_probability"
    assert events[0].latency_ms >= 0.0
    assert recorded_metrics
    assert recorded_metrics[0][0] == "llm_response_ms"


def test_configure_logging_writes_ecs_json(tmp_path) -> None:
    log_path = tmp_path / "bot.json.log"
    runtime = apm_setup.initialize_apm(force=True, client=_NoopAPMClient())
    log_config.configure_logging(
        force=True,
        console_enabled=False,
        log_path=log_path,
        service_name="elastifund-bot",
    )

    logger = logging.getLogger("test.json")
    with runtime.transaction("logging-test"):
        logger.info(
            "structured message",
            extra=log_config.ecs_extra(market_id="market-1", strategy="latency-test", extra_field="value"),
        )

    payload = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert payload["message"] == "structured message"
    assert payload["service.name"] == "elastifund-bot"
    assert payload["labels.market_id"] == "market-1"
    assert payload["labels.strategy"] == "latency-test"
    assert payload["extra_field"] == "value"
    assert payload["trace.id"]


def test_apm_graceful_degradation_warns_once(caplog) -> None:
    caplog.set_level(logging.WARNING)
    runtime = apm_setup.initialize_apm(force=True, client=_FailingAPMClient())

    with runtime.transaction("first"):
        pass
    with runtime.transaction("second"):
        pass

    warnings = [record for record in caplog.records if "Elastic APM unavailable" in record.getMessage()]
    assert len(warnings) == 1


class _NoopAPMClient:
    def begin_transaction(self, transaction_type: str) -> None:
        return None

    def end_transaction(self, name: str, outcome: str) -> None:
        return None


class _FailingAPMClient:
    def begin_transaction(self, transaction_type: str) -> None:
        raise RuntimeError("server unreachable")

    def end_transaction(self, name: str, outcome: str) -> None:
        raise RuntimeError("server unreachable")
