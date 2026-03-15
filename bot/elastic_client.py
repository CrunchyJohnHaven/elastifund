"""Best-effort Elasticsearch client for JJ runtime telemetry."""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

try:  # pragma: no cover - optional dependency
    from elasticsearch import Elasticsearch
    from elasticsearch import helpers
except Exception:  # pragma: no cover - optional dependency
    Elasticsearch = None
    helpers = None


logger = logging.getLogger("JJ.elastic")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_document(document: Any) -> dict[str, Any]:
    if is_dataclass(document):
        payload = asdict(document)
    elif isinstance(document, Mapping):
        payload = dict(document)
    else:
        payload = {
            key: value
            for key, value in vars(document).items()
            if not key.startswith("_")
        }

    timestamp = payload.get("@timestamp") or payload.get("timestamp")
    if not timestamp:
        timestamp = _utcnow()
    payload.setdefault("@timestamp", timestamp)
    payload.setdefault("timestamp", timestamp)
    return payload


@dataclass(slots=True)
class ElasticConfig:
    host: str
    port: int
    user: str
    password: str
    enabled: bool
    verify_certs: bool
    request_timeout_seconds: float
    flush_interval_seconds: float
    batch_size: int

    @classmethod
    def from_env(cls) -> "ElasticConfig":
        return cls(
            host=os.environ.get("ES_HOST", "127.0.0.1"),
            port=int(os.environ.get("ES_PORT", "9200")),
            user=os.environ.get("ES_USER", "elastic"),
            password=os.environ.get("ES_PASSWORD", ""),
            enabled=_env_bool("ES_ENABLED", default=False),
            verify_certs=_env_bool("ES_VERIFY_CERTS", default=False),
            request_timeout_seconds=float(os.environ.get("ES_TIMEOUT_SECONDS", "5.0")),
            flush_interval_seconds=float(os.environ.get("ES_FLUSH_INTERVAL_SECONDS", "5.0")),
            batch_size=int(os.environ.get("ES_BATCH_SIZE", "100")),
        )


@dataclass(slots=True)
class TradeEvent:
    market_id: str
    side: str
    price: float
    size: float
    fee: float = 0.0
    order_type: str = "maker"
    fill_status: str = "submitted"
    latency_ms: float | None = None
    strategy: str | None = None
    confidence: float | None = None
    kelly_fraction: float | None = None
    timestamp: str | None = None


@dataclass(slots=True)
class SignalEvent:
    signal_source: str
    market_id: str
    signal_value: float
    confidence: float | None = None
    acted_on: bool = False
    reason_skipped: str | None = None
    timestamp: str | None = None


@dataclass(slots=True)
class KillEvent:
    kill_rule: str
    market_id: str | None = None
    metric_value: float | None = None
    threshold: float | None = None
    action_taken: str = "halt"
    timestamp: str | None = None


@dataclass(slots=True)
class OrderbookSnapshotEvent:
    market_id: str
    best_bid: float | None = None
    best_ask: float | None = None
    spread_bps: float | None = None
    depth_5lvl_bid: float | None = None
    depth_5lvl_ask: float | None = None
    vpin: float | None = None
    ofi: float | None = None
    timestamp: str | None = None


@dataclass(slots=True)
class LatencyEvent:
    operation: str
    latency_ms: float
    success: bool = True
    error: str | None = None
    timestamp: str | None = None


class ElasticClient:
    """Thread-backed best-effort bulk writer.

    Caller-facing methods never raise. When Elastic is disabled or unavailable
    the client becomes a no-op so trading paths keep running unchanged.
    """

    TRADE_INDEX = "elastifund-trades"
    SIGNAL_INDEX = "elastifund-signals"
    KILL_INDEX = "elastifund-kills"
    ORDERBOOK_INDEX = "elastifund-orderbook"
    LATENCY_INDEX = "elastifund-latency"

    def __init__(
        self,
        config: ElasticConfig | None = None,
        *,
        enabled: bool | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        verify_certs: bool | None = None,
        request_timeout_seconds: float | None = None,
        flush_interval_seconds: float | None = None,
        max_batch_size: int | None = None,
        client_factory: Any | None = None,
        bulk_helper: Any | None = None,
    ) -> None:
        base_config = config or ElasticConfig.from_env()
        self.config = ElasticConfig(
            host=host or base_config.host,
            port=int(port if port is not None else base_config.port),
            user=user or base_config.user,
            password=password if password is not None else base_config.password,
            enabled=base_config.enabled if enabled is None else bool(enabled),
            verify_certs=base_config.verify_certs if verify_certs is None else bool(verify_certs),
            request_timeout_seconds=(
                base_config.request_timeout_seconds
                if request_timeout_seconds is None
                else float(request_timeout_seconds)
            ),
            flush_interval_seconds=(
                base_config.flush_interval_seconds
                if flush_interval_seconds is None
                else float(flush_interval_seconds)
            ),
            batch_size=base_config.batch_size if max_batch_size is None else int(max_batch_size),
        )
        self._client_factory = client_factory or Elasticsearch
        self._bulk_helper = bulk_helper or (helpers.bulk if helpers is not None else None)
        self.enabled = bool(self.config.enabled and self._client_factory is not None and self._bulk_helper is not None)
        self._client = None
        self._queue: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._warning_lock = threading.Lock()
        self._warned_messages: set[str] = set()

        if self.enabled:
            try:
                self._client = self._client_factory(
                    hosts=[f"http://{self.config.host}:{self.config.port}"],
                    basic_auth=(self.config.user, self.config.password),
                    verify_certs=self.config.verify_certs,
                    request_timeout=self.config.request_timeout_seconds,
                )
                self._thread = threading.Thread(
                    target=self._bulk_loop,
                    name="elastic-bulk-writer",
                    daemon=True,
                )
                self._thread.start()
            except Exception as exc:  # pragma: no cover - dependency/runtime specific
                self.enabled = False
                self._client = None
                self._warn_once(f"elastic init failed: {exc}")

    @property
    def raw_client(self):
        return self._client

    def _warn_once(self, message: str) -> None:
        with self._warning_lock:
            if message in self._warned_messages:
                return
            self._warned_messages.add(message)
        logger.warning("%s", message)

    def _bulk_loop(self) -> None:
        pending: list[dict[str, Any]] = []
        last_flush = time.monotonic()
        while not self._stop_event.is_set():
            timeout = max(0.1, self.config.flush_interval_seconds - (time.monotonic() - last_flush))
            try:
                pending.append(self._queue.get(timeout=timeout))
            except queue.Empty:
                pass

            should_flush = False
            if pending and len(pending) >= self.config.batch_size:
                should_flush = True
            if pending and (time.monotonic() - last_flush) >= self.config.flush_interval_seconds:
                should_flush = True

            if should_flush:
                self._flush_actions(pending)
                pending = []
                last_flush = time.monotonic()

        if pending:
            self._flush_actions(pending)

    def _flush_actions(self, actions: list[dict[str, Any]]) -> None:
        if not actions or not self.enabled or self._client is None or self._bulk_helper is None:
            return
        try:
            self._bulk_helper(self._client, actions, raise_on_error=False, raise_on_exception=False)
        except Exception as exc:  # pragma: no cover - runtime/network specific
            self._warn_once(f"elastic bulk write failed: {exc}")

    def _enqueue(self, index_name: str, document: Any) -> bool:
        if not self.enabled:
            return False
        try:
            payload = _coerce_document(document)
            self._queue.put_nowait({"_index": index_name, "_source": payload})
            return True
        except Exception as exc:
            self._warn_once(f"elastic enqueue failed: {exc}")
            return False

    def index_trade(self, document: TradeEvent | Mapping[str, Any] | Any) -> bool:
        return self._enqueue(self.TRADE_INDEX, document)

    def index_signal(self, document: SignalEvent | Mapping[str, Any] | Any) -> bool:
        return self._enqueue(self.SIGNAL_INDEX, document)

    def index_kill(self, document: KillEvent | Mapping[str, Any] | Any) -> bool:
        return self._enqueue(self.KILL_INDEX, document)

    def index_orderbook_snapshot(self, document: OrderbookSnapshotEvent | Mapping[str, Any] | Any) -> bool:
        return self._enqueue(self.ORDERBOOK_INDEX, document)

    def index_latency(self, document: LatencyEvent | Mapping[str, Any] | Any) -> bool:
        return self._enqueue(self.LATENCY_INDEX, document)

    def search(self, *args, **kwargs) -> dict[str, Any] | None:
        if not self.enabled or self._client is None:
            return None
        try:
            return self._client.search(*args, **kwargs)
        except Exception as exc:
            self._warn_once(f"elastic search failed: {exc}")
            return None

    def health_check(self) -> dict[str, Any]:
        if not self.enabled or self._client is None:
            return {"enabled": False, "status": "disabled"}
        try:
            health = self._client.cluster.health()
            return {
                "enabled": True,
                "status": health.get("status", "unknown"),
                "cluster_name": health.get("cluster_name", ""),
            }
        except Exception as exc:
            self._warn_once(f"elastic health check failed: {exc}")
            return {"enabled": True, "status": "unavailable", "error": str(exc)}

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.config.flush_interval_seconds + 1.0))


_singleton: ElasticClient | None = None
_singleton_lock = threading.Lock()

ElasticClientManager = ElasticClient


def get_elastic_client() -> ElasticClient:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ElasticClient()
    return _singleton


def get_raw_client():
    return get_elastic_client().raw_client


def index_trade(document: TradeEvent | Mapping[str, Any] | Any) -> bool:
    return get_elastic_client().index_trade(document)


def index_signal(document: SignalEvent | Mapping[str, Any] | Any) -> bool:
    return get_elastic_client().index_signal(document)


def index_kill(document: KillEvent | Mapping[str, Any] | Any) -> bool:
    return get_elastic_client().index_kill(document)


def index_orderbook_snapshot(document: OrderbookSnapshotEvent | Mapping[str, Any] | Any) -> bool:
    return get_elastic_client().index_orderbook_snapshot(document)


def index_latency(document: LatencyEvent | Mapping[str, Any] | Any) -> bool:
    return get_elastic_client().index_latency(document)


def health_check() -> dict[str, Any]:
    return get_elastic_client().health_check()


def close() -> None:
    get_elastic_client().close()


atexit.register(close)
