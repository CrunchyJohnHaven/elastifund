"""Elastic APM bootstrap and lightweight instrumentation helpers."""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
import functools
import inspect
import logging
import os
import re
from typing import Any, Callable, Iterator, ParamSpec, TypeVar
import uuid

try:  # pragma: no cover - optional dependency
    import elasticapm
    from elasticapm import capture_span as _capture_span
except Exception:  # pragma: no cover - optional dependency
    elasticapm = None
    _capture_span = None


logger = logging.getLogger("JJ.apm")

P = ParamSpec("P")
R = TypeVar("R")

_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("elastic_trace_id", default="")
_SINGLETON: "APMManager | None" = None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_label_key(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.]", "_", name).strip("_") or "metric"


def _clean_mapping(values: dict[str, Any] | None) -> dict[str, Any]:
    if not values:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        cleaned[_normalize_label_key(str(key))] = value
    return cleaned


@dataclass(slots=True)
class APMConfig:
    server_url: str
    secret_token: str
    service_name: str
    environment: str
    enabled: bool

    @classmethod
    def from_env(cls) -> "APMConfig":
        server_url = os.environ.get("APM_SERVER_URL", "").strip()
        return cls(
            server_url=server_url,
            secret_token=os.environ.get("APM_SECRET_TOKEN", "").strip(),
            service_name=os.environ.get("APM_SERVICE_NAME", "elastifund-bot").strip() or "elastifund-bot",
            environment=os.environ.get("ELASTIFUND_ENVIRONMENT", os.environ.get("ENVIRONMENT", "production")),
            enabled=bool(server_url) and _env_bool("APM_ENABLED", default=True),
        )


class APMManager:
    def __init__(
        self,
        config: APMConfig | None = None,
        *,
        client: Any = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or APMConfig.from_env()
        self.client = client
        self.enabled = bool(client) or bool(self.config.enabled and elasticapm is not None)
        self._warning_emitted = False

        if self.enabled and self.client is None and elasticapm is not None:
            try:
                factory = client_factory or elasticapm.Client
                self.client = factory(
                    {
                        "SERVICE_NAME": self.config.service_name,
                        "SERVER_URL": self.config.server_url,
                        "SECRET_TOKEN": self.config.secret_token,
                        "ENVIRONMENT": self.config.environment,
                        "CAPTURE_BODY": "off",
                        "VERIFY_SERVER_CERT": False,
                    }
                )
                elasticapm.instrument()
            except Exception as exc:  # pragma: no cover - runtime specific
                self._warn_once(f"Elastic APM unavailable, continuing without tracing: {exc}")
                self.client = None
                self.enabled = False

    def _warn_once(self, message: str) -> None:
        if self._warning_emitted:
            return
        self._warning_emitted = True
        logger.warning("%s", message)

    def _safe_call(self, operation: str, callback: Callable[[], Any]) -> Any:
        if not self.enabled or self.client is None:
            return None
        try:
            return callback()
        except Exception as exc:  # pragma: no cover - runtime specific
            self._warn_once(f"Elastic APM unavailable during {operation}: {exc}")
            return None

    def set_context(self, context: dict[str, Any] | None) -> None:
        payload = _clean_mapping(context)
        if not payload or elasticapm is None:
            return
        self._safe_call("set_context", lambda: elasticapm.set_custom_context(payload))

    def set_custom_context(self, context: dict[str, Any] | None) -> None:
        self.set_context(context)

    def set_labels(self, *args: Any, **kwargs: Any) -> None:
        payload: dict[str, Any] = {}
        if args:
            if len(args) == 1 and isinstance(args[0], dict):
                payload.update(args[0])
        payload.update(kwargs)
        cleaned = _clean_mapping(payload)
        if not cleaned or elasticapm is None:
            return
        self._safe_call("set_labels", lambda: elasticapm.label(**cleaned))

    def label(self, **labels: Any) -> None:
        self.set_labels(labels)

    def capture_metric(self, name: str, value: float) -> None:
        self.set_labels(**{f"metric.{_normalize_label_key(name)}": float(value)})
        self.set_context({"custom_metrics": {_normalize_label_key(name): float(value)}})

    def record_metric(
        self,
        name: str,
        value: float,
        labels: dict[str, Any] | None = None,
    ) -> None:
        if labels:
            self.set_labels(labels)
        self.capture_metric(name, value)

    def current_trace_id(self) -> str | None:
        trace_id = _TRACE_ID.get()
        return trace_id or None

    @contextmanager
    def transaction(self, name: str, transaction_type: str = "custom") -> Iterator[None]:
        existing = _TRACE_ID.get()
        if existing:
            with self.span(name, span_type=f"app.{transaction_type}"):
                yield
            return

        token = _TRACE_ID.set(uuid.uuid4().hex)
        self._safe_call("begin_transaction", lambda: self.client.begin_transaction(transaction_type))
        if elasticapm is not None:
            self._safe_call("set_transaction_name", lambda: elasticapm.set_transaction_name(name))
        outcome = "success"
        try:
            yield
        except Exception:
            outcome = "error"
            if elasticapm is not None:
                self._safe_call("capture_exception", lambda: elasticapm.capture_exception())
            raise
        finally:
            self._safe_call("end_transaction", lambda: self.client.end_transaction(name, outcome))
            _TRACE_ID.reset(token)

    @contextmanager
    def span(self, name: str, span_type: str = "custom") -> Iterator[None]:
        if not self.enabled or _capture_span is None:
            yield
            return
        try:
            manager = _capture_span(name, span_type=span_type)
        except Exception as exc:  # pragma: no cover - runtime specific
            self._warn_once(f"Elastic APM unavailable during span: {exc}")
            yield
            return

        with manager:
            yield


def get_apm_manager() -> APMManager:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = APMManager()
    return _SINGLETON


def initialize_apm(
    *,
    force: bool = False,
    client: Any = None,
    client_factory: Callable[..., Any] | None = None,
) -> APMManager:
    global _SINGLETON
    if _SINGLETON is None or force:
        _SINGLETON = APMManager(client=client, client_factory=client_factory)
    return _SINGLETON


def current_trace_id() -> str | None:
    return get_apm_manager().current_trace_id()


def get_apm_runtime() -> APMManager:
    return get_apm_manager()


@contextmanager
def capture_external_span(
    name: str,
    *,
    system: str = "external",
    action: str = "call",
    labels: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    span_type: str | None = None,
) -> Iterator[None]:
    manager = get_apm_manager()
    merged_labels = {"external.system": system, "external.action": action}
    if labels:
        merged_labels.update(labels)
    if context:
        manager.set_context(context)
    manager.set_labels(merged_labels)
    with manager.span(name, span_type or f"{system}.{action}"):
        yield


@contextmanager
def capture_span(
    name: str,
    span_type: str = "custom",
    labels: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    **extra_labels: Any,
) -> Iterator[None]:
    manager = get_apm_manager()
    merged_labels = dict(labels or {})
    merged_labels.update(extra_labels)
    if context:
        manager.set_context(context)
    if merged_labels:
        manager.set_labels(merged_labels)
    with manager.span(name, span_type):
        yield


def apm_transaction(name: str, transaction_type: str = "custom") -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        if getattr(func, "__wrapped_apm__", False):
            return func

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with get_apm_manager().transaction(name, transaction_type):
                    return await func(*args, **kwargs)

            setattr(async_wrapper, "__wrapped_apm__", True)
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with get_apm_manager().transaction(name, transaction_type):
                return func(*args, **kwargs)

        setattr(sync_wrapper, "__wrapped_apm__", True)
        return sync_wrapper

    return decorator
