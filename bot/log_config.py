"""Logging bootstrap for human console logs plus ECS-style JSON files."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from typing import Any

try:  # pragma: no cover - optional dependency
    from pythonjsonlogger import jsonlogger
except Exception:  # pragma: no cover - optional dependency
    jsonlogger = None

from bot.apm_setup import current_trace_id


_LOGGING_CONFIGURED = False
_STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys())


def _json_default(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return value
    return str(value)


def _resolve_log_path(log_path: str | os.PathLike[str] | None = None) -> Path:
    target = Path(log_path or os.environ.get("ELASTIFUND_JSON_LOG_PATH", "/var/log/elastifund/bot.json.log"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
        return target
    except Exception:
        fallback = Path(os.environ.get("ELASTIFUND_JSON_LOG_FALLBACK", "logs/elastifund/bot.json.log"))
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.touch(exist_ok=True)
        return fallback


class _ECSFormatter(logging.Formatter):
    service_name = os.environ.get("ELASTIFUND_SERVICE_NAME", "elastifund-bot")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "@timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "log.level": record.levelname.lower(),
            "message": record.getMessage(),
            "service.name": os.environ.get("ELASTIFUND_SERVICE_NAME", self.service_name),
        }
        trace_id = current_trace_id()
        if trace_id:
            payload["trace.id"] = trace_id

        market_id = getattr(record, "market_id", None)
        strategy = getattr(record, "strategy", None)
        if market_id is not None:
            payload["labels.market_id"] = market_id
        if strategy is not None:
            payload["labels.strategy"] = strategy

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key in {"market_id", "strategy"}:
                continue
            payload[key] = value

        if record.exc_info:
            payload["error.stack_trace"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=_json_default)


class ECSJsonFormatter(_ECSFormatter if jsonlogger is None else jsonlogger.JsonFormatter):
    def __init__(self) -> None:
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:
        return _ECSFormatter.format(self, record)


def structured_extra(*, market_id: str | None = None, strategy: str | None = None, **fields: Any) -> dict[str, Any]:
    extra = dict(fields)
    if market_id is not None:
        extra["market_id"] = market_id
    if strategy is not None:
        extra["strategy"] = strategy
    return extra


def setup_logging(
    *,
    level: int | str = logging.INFO,
    service_name: str = "elastifund-bot",
    json_log_path: str | None = None,
    log_path: str | None = None,
    console_enabled: bool = True,
    force: bool = False,
) -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED and not force:
        return

    os.environ["ELASTIFUND_SERVICE_NAME"] = service_name

    file_path = _resolve_log_path(log_path or json_log_path)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level if isinstance(level, int) else getattr(logging, str(level).upper(), logging.INFO))

    if console_enabled:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(root.level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        file_path,
        maxBytes=50 * 1024 * 1024,
        backupCount=10,
    )
    file_handler.setLevel(root.level)
    file_handler.setFormatter(ECSJsonFormatter())
    root.addHandler(file_handler)

    _LOGGING_CONFIGURED = True


def configure_logging(
    *,
    level: int | str = logging.INFO,
    service_name: str = "elastifund-bot",
    json_log_path: str | None = None,
    log_path: str | None = None,
    console_enabled: bool = True,
    force: bool = False,
) -> None:
    global _LOGGING_CONFIGURED
    if force:
        _LOGGING_CONFIGURED = False
    setup_logging(
        level=level,
        service_name=service_name,
        json_log_path=json_log_path,
        log_path=log_path,
        console_enabled=console_enabled,
    )


def ecs_extra(*, market_id: str | None = None, strategy: str | None = None, **fields: Any) -> dict[str, Any]:
    return structured_extra(market_id=market_id, strategy=strategy, **fields)
