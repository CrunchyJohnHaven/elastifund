"""CLOB WebSocket helpers for best-bid/ask and user order streams."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
import logging
import threading
import time
from typing import Any, Callable

from infra.fast_json import loads as fast_json_loads

try:
    import websockets
    from websockets.exceptions import WebSocketException
except ImportError:  # pragma: no cover - optional dependency in tests
    websockets = None
    WebSocketException = Exception


MARKET_WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
USER_WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

logger = logging.getLogger("JJ.clob_ws")


def chunk_asset_ids(asset_ids: Sequence[str], chunk_size: int = 200) -> list[list[str]]:
    """Split token ids into subscription-sized chunks."""
    clean = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [clean[idx: idx + chunk_size] for idx in range(0, len(clean), chunk_size)]


def build_market_subscription(asset_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "market",
        "assets_ids": list(asset_ids),
        "custom_feature_enabled": True,
    }


def build_user_subscription(
    market_ids: Sequence[str],
    *,
    auth: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "user",
        "markets": list(market_ids),
    }
    if auth:
        payload["auth"] = dict(auth)
    return payload


@dataclass(frozen=True)
class BestBidAsk:
    token_id: str
    best_bid: float
    best_ask: float
    updated_ts: float
    tick_size: float | None = None
    best_bid_size: float | None = None
    best_ask_size: float | None = None


@dataclass(frozen=True)
class UserOrderEvent:
    event_type: str
    order_id: str
    market_id: str | None
    token_id: str | None
    status: str | None
    filled_size: float
    price: float | None
    updated_ts: float
    raw: dict[str, Any]


class BestBidAskStore:
    """Thread-safe quote cache shared by scanners and monitors."""

    def __init__(self) -> None:
        self._quotes: dict[str, BestBidAsk] = {}
        self._no_orderbook: set[str] = set()
        self._tick_sizes: dict[str, float] = {}
        self._lock = threading.Lock()

    def update(
        self,
        token_id: str,
        *,
        best_bid: float,
        best_ask: float,
        updated_ts: float | None = None,
        tick_size: float | None = None,
        best_bid_size: float | None = None,
        best_ask_size: float | None = None,
    ) -> None:
        if not token_id:
            return
        ts = float(updated_ts or time.time())
        with self._lock:
            prior = self._quotes.get(str(token_id))
            quote = BestBidAsk(
                token_id=str(token_id),
                best_bid=float(best_bid),
                best_ask=float(best_ask),
                updated_ts=ts,
                tick_size=(
                    float(tick_size)
                    if tick_size is not None and float(tick_size) > 0.0
                    else (
                        prior.tick_size
                        if prior is not None and prior.tick_size is not None
                        else self._tick_sizes.get(str(token_id))
                    )
                ),
                best_bid_size=(
                    _safe_float(best_bid_size)
                    if _safe_float(best_bid_size) is not None
                    else (prior.best_bid_size if prior is not None else None)
                ),
                best_ask_size=(
                    _safe_float(best_ask_size)
                    if _safe_float(best_ask_size) is not None
                    else (prior.best_ask_size if prior is not None else None)
                ),
            )
            self._quotes[str(token_id)] = quote
            self._no_orderbook.discard(str(token_id))

    def update_tick_size(self, token_id: str, *, tick_size: float, updated_ts: float | None = None) -> None:
        if not token_id:
            return
        tick = float(tick_size)
        if tick <= 0.0:
            return
        with self._lock:
            self._tick_sizes[str(token_id)] = tick

    def mark_no_orderbook(self, token_id: str) -> None:
        if not token_id:
            return
        with self._lock:
            self._no_orderbook.add(str(token_id))
            self._quotes.pop(str(token_id), None)

    def clear_token(self, token_id: str) -> None:
        with self._lock:
            self._quotes.pop(str(token_id), None)
            self._no_orderbook.discard(str(token_id))
            self._tick_sizes.pop(str(token_id), None)

    def get(self, token_id: str) -> BestBidAsk | None:
        with self._lock:
            return self._quotes.get(str(token_id))

    def is_fresh(self, token_id: str, *, max_age_seconds: float) -> bool:
        quote = self.get(token_id)
        if quote is None:
            return False
        return (time.time() - quote.updated_ts) <= float(max_age_seconds)

    def has_no_orderbook(self, token_id: str) -> bool:
        with self._lock:
            return str(token_id) in self._no_orderbook

    def snapshot(self, token_ids: Iterable[str]) -> dict[str, BestBidAsk]:
        with self._lock:
            return {str(token_id): self._quotes[str(token_id)] for token_id in token_ids if str(token_id) in self._quotes}

    def tokens_without_orderbook(self) -> set[str]:
        with self._lock:
            return set(self._no_orderbook)

    def get_tick_size(self, token_id: str) -> float | None:
        with self._lock:
            quote = self._quotes.get(str(token_id))
            if quote is not None and quote.tick_size is not None:
                return float(quote.tick_size)
            tick_size = self._tick_sizes.get(str(token_id))
            return None if tick_size is None else float(tick_size)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_best_bid_ask_messages(payload: Any) -> list[BestBidAsk]:
    """Extract best_bid_ask updates from a market-channel payload."""
    messages: list[BestBidAsk] = []
    now = time.time()

    if isinstance(payload, list):
        for item in payload:
            messages.extend(parse_best_bid_ask_messages(item))
        return messages

    if not isinstance(payload, dict):
        return messages

    event_type = str(payload.get("event_type") or payload.get("type") or payload.get("channel") or "").lower()
    candidates: list[dict[str, Any]] = []

    if event_type == "best_bid_ask":
        candidates.append(payload)
    elif isinstance(payload.get("data"), list):
        candidates.extend([item for item in payload["data"] if isinstance(item, dict)])
    elif isinstance(payload.get("data"), dict):
        candidates.append(payload["data"])
    elif {"asset_id", "best_bid", "best_ask"} <= set(payload.keys()):
        candidates.append(payload)

    for item in candidates:
        item_type = str(item.get("event_type") or item.get("type") or "best_bid_ask").lower()
        if item_type not in {"best_bid_ask", ""}:
            continue
        token_id = str(item.get("asset_id") or item.get("token_id") or item.get("market") or "").strip()
        best_bid = _safe_float(item.get("best_bid") or item.get("bid"))
        best_ask = _safe_float(item.get("best_ask") or item.get("ask"))
        best_bid_size = _safe_float(item.get("best_bid_size") or item.get("bid_size"))
        best_ask_size = _safe_float(item.get("best_ask_size") or item.get("ask_size"))
        updated_ts = _safe_float(item.get("timestamp") or item.get("ts")) or now
        if not token_id or best_bid is None or best_ask is None:
            continue
        if not (0.0 <= best_bid <= 1.0 and 0.0 <= best_ask <= 1.0):
            continue
        messages.append(
            BestBidAsk(
                token_id=token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                updated_ts=updated_ts,
                best_bid_size=best_bid_size,
                best_ask_size=best_ask_size,
            )
        )
    return messages


def parse_tick_size_messages(payload: Any) -> list[tuple[str, float, float]]:
    """Extract tick_size_change updates from a market-channel payload."""
    out: list[tuple[str, float, float]] = []
    now = time.time()

    if isinstance(payload, list):
        for item in payload:
            out.extend(parse_tick_size_messages(item))
        return out

    if not isinstance(payload, dict):
        return out

    candidates: list[dict[str, Any]] = []
    event_type = str(payload.get("event_type") or payload.get("type") or "").lower()
    if event_type == "tick_size_change":
        candidates.append(payload)
    elif isinstance(payload.get("data"), list):
        candidates.extend([item for item in payload["data"] if isinstance(item, dict)])
    elif isinstance(payload.get("data"), dict):
        candidates.append(payload["data"])

    for item in candidates:
        item_type = str(item.get("event_type") or item.get("type") or "").lower()
        if item_type != "tick_size_change":
            continue
        token_id = str(item.get("asset_id") or item.get("token_id") or item.get("market") or "").strip()
        tick_size = _safe_float(item.get("tick_size") or item.get("new_tick_size"))
        updated_ts = _safe_float(item.get("timestamp") or item.get("ts")) or now
        if not token_id or tick_size is None or tick_size <= 0.0:
            continue
        out.append((token_id, float(tick_size), float(updated_ts)))
    return out


def parse_user_order_events(payload: Any) -> list[UserOrderEvent]:
    if isinstance(payload, list):
        out: list[UserOrderEvent] = []
        for item in payload:
            out.extend(parse_user_order_events(item))
        return out
    if not isinstance(payload, dict):
        return []

    raw_items: list[dict[str, Any]] = []
    if isinstance(payload.get("data"), list):
        raw_items.extend([item for item in payload["data"] if isinstance(item, dict)])
    elif isinstance(payload.get("data"), dict):
        raw_items.append(payload["data"])
    else:
        raw_items.append(payload)

    events: list[UserOrderEvent] = []
    for item in raw_items:
        order_id = str(item.get("order_id") or item.get("id") or "").strip()
        if not order_id:
            continue
        events.append(
            UserOrderEvent(
                event_type=str(item.get("event_type") or item.get("type") or "user_event"),
                order_id=order_id,
                market_id=str(item.get("market_id") or item.get("market") or "").strip() or None,
                token_id=str(item.get("asset_id") or item.get("token_id") or "").strip() or None,
                status=str(item.get("status") or item.get("order_status") or "").strip() or None,
                filled_size=float(_safe_float(item.get("filled_size") or item.get("size_filled")) or 0.0),
                price=_safe_float(item.get("price") or item.get("avg_price")),
                updated_ts=float(_safe_float(item.get("timestamp") or item.get("ts")) or time.time()),
                raw=dict(item),
            )
        )
    return events


class ClobMarketWebSocketClient:
    """Async market-channel client with reconnect/backoff and chunked subscriptions."""

    def __init__(
        self,
        *,
        asset_ids: Sequence[str],
        store: BestBidAskStore | None = None,
        endpoint: str = MARKET_WS_ENDPOINT,
        chunk_size: int = 200,
        reconnect_base_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        ping_interval_seconds: float = 20.0,
        metrics_hook: Callable[[str, dict[str, Any]], None] | None = None,
        message_hook: Callable[[BestBidAsk], None] | None = None,
    ) -> None:
        self.asset_ids = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]
        self.store = store or BestBidAskStore()
        self.endpoint = endpoint
        self.chunk_size = max(1, int(chunk_size))
        self.reconnect_base_seconds = max(0.25, float(reconnect_base_seconds))
        self.reconnect_max_seconds = max(self.reconnect_base_seconds, float(reconnect_max_seconds))
        self.ping_interval_seconds = max(5.0, float(ping_interval_seconds))
        self.metrics_hook = metrics_hook
        self.message_hook = message_hook
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        if websockets is None:  # pragma: no cover - depends on optional package
            raise RuntimeError("websockets package is required for market WebSocket usage")
        backoff = self.reconnect_base_seconds
        while not self._stop.is_set():
            try:
                await self._connect_once()
                backoff = self.reconnect_base_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network path
                logger.warning("market_ws_error err=%s", exc)
                self._emit_metric("disconnect", {"error": str(exc), "backoff_seconds": backoff})
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, max(self.reconnect_base_seconds, backoff * 2.0))

    async def _connect_once(self) -> None:
        assert websockets is not None  # pragma: no cover - optional dependency guard
        async with websockets.connect(
            self.endpoint,
            ping_interval=self.ping_interval_seconds,
            ping_timeout=self.ping_interval_seconds,
        ) as ws:
            await self._subscribe(ws)
            self._emit_metric("connected", {"assets": len(self.asset_ids)})
            async for raw in ws:
                if self._stop.is_set():
                    return
                try:
                    payload = fast_json_loads(raw)
                except (ValueError, TypeError):
                    continue
                for token_id, tick_size, updated_ts in parse_tick_size_messages(payload):
                    self.store.update_tick_size(token_id, tick_size=tick_size, updated_ts=updated_ts)
                messages = parse_best_bid_ask_messages(payload)
                for msg in messages:
                    self.store.update(
                        msg.token_id,
                        best_bid=msg.best_bid,
                        best_ask=msg.best_ask,
                        updated_ts=msg.updated_ts,
                        tick_size=msg.tick_size,
                        best_bid_size=msg.best_bid_size,
                        best_ask_size=msg.best_ask_size,
                    )
                    if self.message_hook is not None:
                        self.message_hook(msg)

    async def _subscribe(self, ws: Any) -> None:
        for chunk in chunk_asset_ids(self.asset_ids, self.chunk_size):
            await ws.send(json.dumps(build_market_subscription(chunk)))

    def _emit_metric(self, name: str, payload: dict[str, Any]) -> None:
        if self.metrics_hook is not None:
            self.metrics_hook(name, payload)


class ClobUserWebSocketClient:
    """Async user-channel client for fills, cancels, and order status."""

    def __init__(
        self,
        *,
        market_ids: Sequence[str],
        auth: Mapping[str, Any] | None = None,
        endpoint: str = USER_WS_ENDPOINT,
        reconnect_base_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        ping_interval_seconds: float = 20.0,
        metrics_hook: Callable[[str, dict[str, Any]], None] | None = None,
        event_hook: Callable[[UserOrderEvent], None] | None = None,
    ) -> None:
        self.market_ids = [str(market_id).strip() for market_id in market_ids if str(market_id).strip()]
        self.auth = dict(auth or {})
        self.endpoint = endpoint
        self.reconnect_base_seconds = max(0.25, float(reconnect_base_seconds))
        self.reconnect_max_seconds = max(self.reconnect_base_seconds, float(reconnect_max_seconds))
        self.ping_interval_seconds = max(5.0, float(ping_interval_seconds))
        self.metrics_hook = metrics_hook
        self.event_hook = event_hook
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        if websockets is None:  # pragma: no cover - depends on optional package
            raise RuntimeError("websockets package is required for user WebSocket usage")
        backoff = self.reconnect_base_seconds
        while not self._stop.is_set():
            try:
                await self._connect_once()
                backoff = self.reconnect_base_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - network path
                logger.warning("user_ws_error err=%s", exc)
                self._emit_metric("disconnect", {"error": str(exc), "backoff_seconds": backoff})
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, max(self.reconnect_base_seconds, backoff * 2.0))

    async def _connect_once(self) -> None:
        assert websockets is not None  # pragma: no cover
        async with websockets.connect(
            self.endpoint,
            ping_interval=self.ping_interval_seconds,
            ping_timeout=self.ping_interval_seconds,
        ) as ws:
            await ws.send(json.dumps(build_user_subscription(self.market_ids, auth=self.auth)))
            self._emit_metric("connected", {"markets": len(self.market_ids)})
            async for raw in ws:
                if self._stop.is_set():
                    return
                try:
                    payload = fast_json_loads(raw)
                except (ValueError, TypeError):
                    continue
                for event in parse_user_order_events(payload):
                    if self.event_hook is not None:
                        self.event_hook(event)

    def _emit_metric(self, name: str, payload: dict[str, Any]) -> None:
        if self.metrics_hook is not None:
            self.metrics_hook(name, payload)


class ThreadedMarketStream:
    """Background-thread wrapper for the async market-channel client."""

    def __init__(
        self,
        *,
        asset_ids: Sequence[str],
        store: BestBidAskStore | None = None,
        endpoint: str = MARKET_WS_ENDPOINT,
        chunk_size: int = 200,
        metrics_hook: Callable[[str, dict[str, Any]], None] | None = None,
        message_hook: Callable[[BestBidAsk], None] | None = None,
    ) -> None:
        self.asset_ids = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]
        self.store = store or BestBidAskStore()
        self.endpoint = endpoint
        self.chunk_size = max(1, int(chunk_size))
        self.metrics_hook = metrics_hook
        self.message_hook = message_hook
        self._thread: threading.Thread | None = None
        self._client: ClobMarketWebSocketClient | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="clob-market-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._client is not None:
            self._client.stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._client = None

    def replace_asset_ids(self, asset_ids: Sequence[str]) -> None:
        new_ids = [str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()]
        if new_ids == self.asset_ids:
            return
        self.asset_ids = new_ids
        self.stop()
        self.start()

    def _thread_main(self) -> None:  # pragma: no cover - thread wrapper
        asyncio.run(self._async_main())

    async def _async_main(self) -> None:  # pragma: no cover - thread wrapper
        self._client = ClobMarketWebSocketClient(
            asset_ids=self.asset_ids,
            store=self.store,
            endpoint=self.endpoint,
            chunk_size=self.chunk_size,
            metrics_hook=self.metrics_hook,
            message_hook=self.message_hook,
        )
        await self._client.run_forever()
