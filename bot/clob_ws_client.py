#!/usr/bin/env python3
"""Shared CLOB market-channel client for structural arbitrage book state."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
import contextlib
from dataclasses import dataclass
import json
import logging
import time
import threading
from typing import Any, Awaitable, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import websockets
    from websockets.exceptions import WebSocketException
except ImportError:  # pragma: no cover - optional dependency in tests
    websockets = None
    WebSocketException = Exception

try:
    from infra.clob_ws import build_market_subscription, chunk_asset_ids
except ImportError:  # pragma: no cover - direct script mode
    from clob_ws import build_market_subscription, chunk_asset_ids  # type: ignore


logger = logging.getLogger("JJ.clob_ws_client")

WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
HTTP_TIMEOUT_SECONDS = 20
DEFAULT_HEADERS = {
    "User-Agent": "constraint-arb-engine/1.0",
    "Accept": "application/json",
}
LATENCY_SAMPLE_LIMIT = 4096


class TokenBook404Error(Exception):
    """Raised when Polymarket has no order book for a token."""

    def __init__(self, token_id: str):
        super().__init__(f"order book missing for token {token_id}")
        self.token_id = token_id


BookFetcher = Callable[[str], Awaitable[dict[str, Any] | None] | dict[str, Any] | None]
WebsocketConnect = Callable[..., Any]


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ts(raw: Any) -> float | None:
    value = _safe_float(raw)
    if value is None:
        return None
    if value > 1e12:
        return value / 1000.0
    if value > 1e10:
        return value / 1000.0
    return value


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(float(pct) / 100.0, 1.0)) * float(len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _fetch_book_snapshot_sync(token_id: str, rest_book_url: str) -> dict[str, Any]:
    params = urlencode({"token_id": token_id})
    request = Request(f"{rest_book_url}?{params}", headers=DEFAULT_HEADERS)
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        if int(exc.code) == 404:
            raise TokenBook404Error(token_id) from exc
        raise
    return json.loads(body)


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class TokenBook:
    token_id: str
    market_id: str | None
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    exchange_ts: float | None
    received_ts: float
    source: str

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None


@dataclass(frozen=True)
class TradeUpdate:
    token_id: str
    market_id: str | None
    price: float
    size: float
    side: str
    exchange_ts: float | None
    received_ts: float
    lag_ms: float | None


@dataclass(frozen=True)
class TokenState:
    token_id: str
    market_id: str | None
    status: str
    reason: str | None
    updated_ts: float
    retry_at_ts: float | None = None


class CLOBWebSocketClient:
    """Track live order books and trades for a token universe."""

    def __init__(
        self,
        *,
        ws_url: str = WS_ENDPOINT,
        rest_book_url: str = CLOB_BOOK_URL,
        chunk_size: int = 200,
        heartbeat_interval_seconds: float = 10.0,
        pong_timeout_seconds: float = 10.0,
        reconnect_base_seconds: float = 1.0,
        reconnect_max_seconds: float = 60.0,
        stale_book_seconds: float = 30.0,
        quarantine_retry_seconds: float = 120.0,
        rest_poll_interval_seconds: float = 15.0,
        websocket_connect: WebsocketConnect | None = None,
        rest_book_fetcher: BookFetcher | None = None,
        on_book_update: Callable[[TokenBook], None] | None = None,
        on_trade_update: Callable[[TradeUpdate], None] | None = None,
        on_status_change: Callable[[TokenState], None] | None = None,
        clock: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.rest_book_url = rest_book_url
        self.chunk_size = max(1, int(chunk_size))
        self.heartbeat_interval_seconds = max(1.0, float(heartbeat_interval_seconds))
        self.pong_timeout_seconds = max(1.0, float(pong_timeout_seconds))
        self.reconnect_base_seconds = max(0.25, float(reconnect_base_seconds))
        self.reconnect_max_seconds = max(self.reconnect_base_seconds, float(reconnect_max_seconds))
        self.stale_book_seconds = max(1.0, float(stale_book_seconds))
        self.quarantine_retry_seconds = max(self.stale_book_seconds, float(quarantine_retry_seconds))
        self.rest_poll_interval_seconds = max(5.0, float(rest_poll_interval_seconds))
        self._connect = websocket_connect or (websockets.connect if websockets is not None else None)
        self._rest_book_fetcher = rest_book_fetcher
        self._on_book_update = on_book_update
        self._on_trade_update = on_trade_update
        self._on_status_change = on_status_change
        self._clock = clock or time.time
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or asyncio.sleep

        self._books: dict[str, TokenBook] = {}
        self._token_states: dict[str, TokenState] = {}
        self._token_to_market_id: dict[str, str | None] = {}
        self._last_fingerprints: dict[str, tuple[Any, ...]] = {}
        self._stale_tokens: set[str] = set()
        self._quarantined_until: dict[str, float] = {}

        self._book_subscribers: list[asyncio.Queue[TokenBook]] = []
        self._trade_subscribers: list[asyncio.Queue[TradeUpdate]] = []
        self._status_subscribers: list[asyncio.Queue[TokenState]] = []

        self._lag_samples_ms: deque[float] = deque(maxlen=LATENCY_SAMPLE_LIMIT)
        self._clock_skew_samples_ms: deque[float] = deque(maxlen=LATENCY_SAMPLE_LIMIT)

        self._running = False
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pong_event = asyncio.Event()
        self._lock = threading.RLock()

        self._message_count = 0
        self._deduped_snapshot_count = 0
        self._reconnect_count = 0
        self._stale_book_drop_count = 0
        self._token_404_count = 0
        self._last_message_ts = 0.0
        self._subscribed_tokens: set[str] = set()

    def subscribe_books(self, *, maxsize: int = 1000) -> asyncio.Queue[TokenBook]:
        queue: asyncio.Queue[TokenBook] = asyncio.Queue(maxsize=max(1, maxsize))
        self._book_subscribers.append(queue)
        return queue

    def subscribe_trades(self, *, maxsize: int = 1000) -> asyncio.Queue[TradeUpdate]:
        queue: asyncio.Queue[TradeUpdate] = asyncio.Queue(maxsize=max(1, maxsize))
        self._trade_subscribers.append(queue)
        return queue

    def subscribe_status(self, *, maxsize: int = 1000) -> asyncio.Queue[TokenState]:
        queue: asyncio.Queue[TokenState] = asyncio.Queue(maxsize=max(1, maxsize))
        self._status_subscribers.append(queue)
        return queue

    def sync_tokens(self, token_to_market_id: Mapping[str, str | None] | Sequence[str]) -> None:
        if isinstance(token_to_market_id, Mapping):
            new_mapping = {str(token_id): market_id for token_id, market_id in token_to_market_id.items() if str(token_id).strip()}
        else:
            new_mapping = {str(token_id): None for token_id in token_to_market_id if str(token_id).strip()}

        with self._lock:
            previous_tokens = set(self._token_to_market_id)
            self._token_to_market_id = dict(new_mapping)
            removed = previous_tokens - set(new_mapping)

            for token_id in removed:
                self._books.pop(token_id, None)
                self._token_states[token_id] = TokenState(
                    token_id=token_id,
                    market_id=None,
                    status="removed",
                    reason="token_removed",
                    updated_ts=self._clock(),
                    retry_at_ts=None,
                )
                self._stale_tokens.discard(token_id)
                self._quarantined_until.pop(token_id, None)
                self._last_fingerprints.pop(token_id, None)
                self._subscribed_tokens.discard(token_id)

        added = [token_id for token_id in new_mapping if token_id not in previous_tokens]
        for token_id in added:
            self._set_token_state(token_id, status="tracking", reason="token_added")
        self._schedule_subscription(added)

    def tracked_tokens(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._token_to_market_id))

    def get_book(self, token_id: str, *, require_fresh: bool = True) -> TokenBook | None:
        self.sweep_stale_books()
        with self._lock:
            book = self._books.get(str(token_id))
            if book is None:
                return None
            if require_fresh and str(token_id) in self._stale_tokens:
                return None
            return book

    def get_token_state(self, token_id: str) -> TokenState | None:
        with self._lock:
            return self._token_states.get(str(token_id))

    def snapshot_books(self, *, require_fresh: bool = True) -> dict[str, TokenBook]:
        self.sweep_stale_books()
        with self._lock:
            if not require_fresh:
                return dict(self._books)
            return {
                token_id: book
                for token_id, book in self._books.items()
                if token_id not in self._stale_tokens
            }

    def get_market_freshness(self) -> dict[str, float | None]:
        self.sweep_stale_books()
        now = self._clock()
        out: dict[str, list[float]] = {}
        with self._lock:
            for token_id, market_id in self._token_to_market_id.items():
                if not market_id:
                    continue
                book = self._books.get(token_id)
                if book is None:
                    out.setdefault(market_id, [])
                    continue
                out.setdefault(market_id, []).append(max(0.0, now - book.received_ts))

        freshness: dict[str, float | None] = {}
        for market_id, ages in out.items():
            freshness[market_id] = max(ages) if ages else None
        return freshness

    def get_metrics(self) -> dict[str, Any]:
        self.sweep_stale_books()
        freshness = self.get_market_freshness()
        with self._lock:
            quarantined = {
                token_id: retry_at
                for token_id, retry_at in self._quarantined_until.items()
                if retry_at > self._clock()
            }
            return {
                "message_count": self._message_count,
                "deduped_snapshot_count": self._deduped_snapshot_count,
                "ws_reconnect_count": self._reconnect_count,
                "stale_book_drop_count": self._stale_book_drop_count,
                "token_404_count": self._token_404_count,
                "books_tracked": len(self._books),
                "books_fresh": len([token_id for token_id in self._books if token_id not in self._stale_tokens]),
                "quarantined_tokens": dict(quarantined),
                "message_lag_p50_ms": round(_percentile(self._lag_samples_ms, 50), 3),
                "message_lag_p99_ms": round(_percentile(self._lag_samples_ms, 99), 3),
                "clock_skew_p50_ms": round(_percentile(self._clock_skew_samples_ms, 50), 3),
                "clock_skew_p99_ms": round(_percentile(self._clock_skew_samples_ms, 99), 3),
                "last_message_age_s": round(max(0.0, self._clock() - self._last_message_ts), 3) if self._last_message_ts else None,
                "per_market_freshness": freshness,
            }

    async def bootstrap_tokens(self, token_ids: Sequence[str] | None = None) -> None:
        tokens = [str(token_id) for token_id in (token_ids or self.tracked_tokens()) if str(token_id).strip()]
        for token_id in tokens:
            now = self._clock()
            retry_at = self._quarantined_until.get(token_id)
            if retry_at and retry_at > now:
                continue
            await self._fetch_and_apply_rest_snapshot(token_id)

    async def retry_quarantined_tokens(self) -> None:
        now = self._clock()
        due = [
            token_id
            for token_id, retry_at in self._quarantined_until.items()
            if retry_at <= now and token_id in self._token_to_market_id
        ]
        for token_id in due:
            await self._fetch_and_apply_rest_snapshot(token_id)

    def sweep_stale_books(self) -> int:
        now = self._clock()
        dropped = 0
        with self._lock:
            for token_id, book in self._books.items():
                age = max(0.0, now - book.received_ts)
                if age > self.stale_book_seconds and token_id not in self._stale_tokens:
                    self._stale_tokens.add(token_id)
                    dropped += 1
                    self._stale_book_drop_count += 1
                    self._token_states[token_id] = TokenState(
                        token_id=token_id,
                        market_id=self._token_to_market_id.get(token_id),
                        status="stale",
                        reason="stale_book",
                        updated_ts=now,
                        retry_at_ts=None,
                    )
        if dropped:
            for token_id in list(self._stale_tokens):
                state = self.get_token_state(token_id)
                if state is not None and state.reason == "stale_book":
                    self._emit_status(state)
        return dropped

    async def run(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        backoff = self.reconnect_base_seconds
        stale_task = asyncio.create_task(self._stale_loop(), name="clob-stale-loop")
        quarantine_task = asyncio.create_task(self._quarantine_loop(), name="clob-quarantine-loop")
        try:
            await self.bootstrap_tokens()
            while self._running:
                if self._connect is None:
                    await self._sleep(self.rest_poll_interval_seconds)
                    await self.bootstrap_tokens()
                    continue
                try:
                    await self._connect_once()
                    backoff = self.reconnect_base_seconds
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not self._running:
                        break
                    self._note_disconnect()
                    logger.warning("clob_ws_disconnect err=%s backoff=%.1fs", exc, backoff)
                    await self._sleep(backoff)
                    backoff = min(self.reconnect_max_seconds, max(self.reconnect_base_seconds, backoff * 2.0))
        finally:
            self._running = False
            for task in (stale_task, quarantine_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def stop(self) -> None:
        self._running = False
        ws = self._ws
        if ws is not None:
            await ws.close()

    async def _stale_loop(self) -> None:
        while self._running:
            self.sweep_stale_books()
            await self._sleep(max(1.0, self.stale_book_seconds / 2.0))

    async def _quarantine_loop(self) -> None:
        while self._running:
            await self.retry_quarantined_tokens()
            await self._sleep(self.rest_poll_interval_seconds)

    async def _connect_once(self) -> None:
        assert self._connect is not None
        async with self._connect(
            self.ws_url,
            ping_interval=None,
            ping_timeout=None,
        ) as ws:
            self._ws = ws
            self._subscribed_tokens.clear()
            await self._subscribe_all(ws)
            heartbeat = asyncio.create_task(self._heartbeat_loop(ws), name="clob-heartbeat")
            try:
                async for raw in ws:
                    if not self._running:
                        return
                    await self._handle_message(raw)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                self._ws = None

    async def _heartbeat_loop(self, ws: Any) -> None:
        while self._running and self._ws is ws:
            await self._sleep(self.heartbeat_interval_seconds)
            if not self._running or self._ws is not ws:
                return
            self._pong_event.clear()
            await ws.send("PING")
            try:
                await asyncio.wait_for(self._pong_event.wait(), timeout=self.pong_timeout_seconds)
            except asyncio.TimeoutError:
                await ws.close()
                return

    async def _subscribe_all(self, ws: Any) -> None:
        for chunk in chunk_asset_ids(self.tracked_tokens(), self.chunk_size):
            await ws.send(json.dumps(build_market_subscription(chunk)))
            self._subscribed_tokens.update(chunk)

    def _schedule_subscription(self, token_ids: Sequence[str]) -> None:
        if not token_ids or self._ws is None or self._loop is None:
            return
        async def _subscribe() -> None:
            fresh = [token_id for token_id in token_ids if token_id not in self._subscribed_tokens]
            if not fresh or self._ws is None:
                return
            for chunk in chunk_asset_ids(fresh, self.chunk_size):
                await self._ws.send(json.dumps(build_market_subscription(chunk)))
                self._subscribed_tokens.update(chunk)
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            self._loop.create_task(_subscribe())
            return
        asyncio.run_coroutine_threadsafe(_subscribe(), self._loop)

    async def _fetch_and_apply_rest_snapshot(self, token_id: str) -> None:
        try:
            payload = await self._fetch_book_snapshot(token_id)
        except TokenBook404Error:
            with self._lock:
                self._token_404_count += 1
                self._quarantined_until[token_id] = self._clock() + self.quarantine_retry_seconds
            self._set_token_state(
                token_id,
                status="quarantined",
                reason="token_404",
                retry_at_ts=self._clock() + self.quarantine_retry_seconds,
            )
            return
        except Exception as exc:
            self._set_token_state(token_id, status="error", reason=f"rest_error:{exc}")
            return
        if payload:
            self._apply_book_payload(token_id, payload, source="rest")

    async def _fetch_book_snapshot(self, token_id: str) -> dict[str, Any] | None:
        if self._rest_book_fetcher is None:
            return await asyncio.to_thread(_fetch_book_snapshot_sync, token_id, self.rest_book_url)
        result = self._rest_book_fetcher(token_id)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def _handle_message(self, raw: Any) -> None:
        received_at = self._clock()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if not isinstance(raw, str):
            return
        text = raw.strip()
        if text == "PONG":
            self._pong_event.set()
            return
        if text == "PING":
            if self._ws is not None:
                await self._ws.send("PONG")
            return

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return

        messages = payload if isinstance(payload, list) else [payload]
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            self._message_count += 1
            self._last_message_ts = received_at
            event_ts = _normalize_ts(message.get("timestamp") or message.get("ts"))
            if event_ts is not None:
                lag_ms = max(0.0, (received_at - event_ts) * 1000.0)
                skew_ms = (event_ts - received_at) * 1000.0
                self._lag_samples_ms.append(lag_ms)
                self._clock_skew_samples_ms.append(skew_ms)

            if self._maybe_handle_trade_message(message, received_at):
                continue
            self._maybe_handle_book_message(message, received_at)

    def _maybe_handle_trade_message(self, message: Mapping[str, Any], received_at: float) -> bool:
        msg_type = str(message.get("event_type") or message.get("type") or "").lower()
        if msg_type not in {"trade", "last_trade_price"}:
            return False
        token_id = str(message.get("asset_id") or message.get("token_id") or message.get("market") or "").strip()
        price = _safe_float(message.get("price"))
        size = _safe_float(message.get("size") or message.get("amount") or 0.0)
        if not token_id or price is None or size is None:
            return False
        exchange_ts = _normalize_ts(message.get("timestamp") or message.get("ts"))
        lag_ms = max(0.0, (received_at - exchange_ts) * 1000.0) if exchange_ts is not None else None
        trade = TradeUpdate(
            token_id=token_id,
            market_id=self._token_to_market_id.get(token_id),
            price=float(price),
            size=float(size),
            side=str(message.get("side") or "buy").lower(),
            exchange_ts=exchange_ts,
            received_ts=received_at,
            lag_ms=lag_ms,
        )
        self._emit_trade(trade)
        return True

    def _maybe_handle_book_message(self, message: Mapping[str, Any], received_at: float) -> bool:
        msg_type = str(message.get("event_type") or message.get("type") or "").lower()
        token_id = str(message.get("asset_id") or message.get("token_id") or message.get("market") or "").strip()
        exchange_ts = _normalize_ts(message.get("timestamp") or message.get("ts"))

        if msg_type in {"book", "best_bid_ask"} or "bids" in message or "asks" in message:
            if not token_id:
                return False
            self._apply_book_payload(token_id, message, source="ws", received_at=received_at, exchange_ts=exchange_ts)
            return True

        if msg_type == "price_change":
            changes = message.get("price_changes") or message.get("changes") or []
            if not token_id and isinstance(changes, list) and changes:
                first = changes[0]
                if isinstance(first, Mapping):
                    token_id = str(first.get("asset_id") or first.get("token_id") or first.get("market") or "").strip()
            if not token_id:
                return False
            self._apply_price_changes(token_id, changes, received_at=received_at, exchange_ts=exchange_ts)
            return True
        return False

    def _parse_levels(self, raw_levels: Any, *, descending: bool) -> tuple[BookLevel, ...]:
        levels: list[BookLevel] = []
        if not isinstance(raw_levels, list):
            return tuple()
        for level in raw_levels:
            if isinstance(level, Mapping):
                price = _safe_float(level.get("price"))
                size = _safe_float(level.get("size"))
            elif isinstance(level, Sequence) and not isinstance(level, (str, bytes, bytearray)) and len(level) >= 2:
                price = _safe_float(level[0])
                size = _safe_float(level[1])
            else:
                continue
            if price is None or size is None:
                continue
            if not (0.0 <= price <= 1.0) or size < 0:
                continue
            levels.append(BookLevel(float(price), float(size)))
        levels.sort(key=lambda level: level.price, reverse=descending)
        return tuple(levels)

    def _apply_book_payload(
        self,
        token_id: str,
        payload: Mapping[str, Any],
        *,
        source: str,
        received_at: float | None = None,
        exchange_ts: float | None = None,
    ) -> None:
        received = received_at if received_at is not None else self._clock()
        bids = self._parse_levels(payload.get("bids") or [], descending=True)
        asks = self._parse_levels(payload.get("asks") or [], descending=False)

        if not bids and not asks:
            best_bid = _safe_float(payload.get("best_bid") or payload.get("bestBid") or payload.get("bid"))
            best_ask = _safe_float(payload.get("best_ask") or payload.get("bestAsk") or payload.get("ask"))
            if best_bid is not None:
                bids = (BookLevel(float(best_bid), float(_safe_float(payload.get("best_bid_size") or payload.get("bid_size") or 0.0) or 0.0)),)
            if best_ask is not None:
                asks = (BookLevel(float(best_ask), float(_safe_float(payload.get("best_ask_size") or payload.get("ask_size") or 0.0) or 0.0)),)

        if not bids and not asks:
            return

        book = TokenBook(
            token_id=token_id,
            market_id=self._token_to_market_id.get(token_id),
            bids=bids,
            asks=asks,
            exchange_ts=exchange_ts if exchange_ts is not None else _normalize_ts(payload.get("timestamp") or payload.get("ts")),
            received_ts=received,
            source=source,
        )
        if self._is_duplicate(book):
            self._deduped_snapshot_count += 1
            return

        with self._lock:
            self._books[token_id] = book
            self._stale_tokens.discard(token_id)
            self._quarantined_until.pop(token_id, None)
        self._set_token_state(token_id, status="active", reason=f"{source}_book")
        self._emit_book(book)

    def _apply_price_changes(
        self,
        token_id: str,
        changes: Any,
        *,
        received_at: float,
        exchange_ts: float | None,
    ) -> None:
        with self._lock:
            current = self._books.get(token_id)
        if current is None:
            return
        bids = list(current.bids)
        asks = list(current.asks)
        if not isinstance(changes, list):
            return

        for change in changes:
            if not isinstance(change, Mapping):
                continue
            side = str(change.get("side") or "").upper()
            price = _safe_float(change.get("price"))
            size = _safe_float(change.get("size"))
            if price is None or size is None:
                continue
            levels = bids if side == "BUY" else asks if side == "SELL" else None
            if levels is None:
                continue
            updated = False
            for index, level in enumerate(levels):
                if abs(level.price - float(price)) < 1e-9:
                    if size <= 0:
                        levels.pop(index)
                    else:
                        levels[index] = BookLevel(float(price), float(size))
                    updated = True
                    break
            if not updated and size > 0:
                levels.append(BookLevel(float(price), float(size)))

        bids.sort(key=lambda level: level.price, reverse=True)
        asks.sort(key=lambda level: level.price)
        self._apply_book_payload(
            token_id,
            {"bids": [{"price": level.price, "size": level.size} for level in bids], "asks": [{"price": level.price, "size": level.size} for level in asks]},
            source="ws",
            received_at=received_at,
            exchange_ts=exchange_ts,
        )

    def _is_duplicate(self, book: TokenBook) -> bool:
        fingerprint = (
            book.token_id,
            round(book.exchange_ts or 0.0, 6),
            tuple((round(level.price, 6), round(level.size, 6)) for level in book.bids[:5]),
            tuple((round(level.price, 6), round(level.size, 6)) for level in book.asks[:5]),
        )
        previous = self._last_fingerprints.get(book.token_id)
        self._last_fingerprints[book.token_id] = fingerprint
        return previous == fingerprint

    def _note_disconnect(self) -> None:
        self._reconnect_count += 1

    def _set_token_state(
        self,
        token_id: str,
        *,
        status: str,
        reason: str | None,
        retry_at_ts: float | None = None,
    ) -> None:
        state = TokenState(
            token_id=token_id,
            market_id=self._token_to_market_id.get(token_id),
            status=status,
            reason=reason,
            updated_ts=self._clock(),
            retry_at_ts=retry_at_ts,
        )
        with self._lock:
            self._token_states[token_id] = state
        self._emit_status(state)

    def _emit_book(self, book: TokenBook) -> None:
        if self._on_book_update is not None:
            self._on_book_update(book)
        for queue in list(self._book_subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(book)
            except asyncio.QueueFull:  # pragma: no cover - guarded above
                continue

    def _emit_trade(self, trade: TradeUpdate) -> None:
        if self._on_trade_update is not None:
            self._on_trade_update(trade)
        for queue in list(self._trade_subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(trade)
            except asyncio.QueueFull:  # pragma: no cover - guarded above
                continue

    def _emit_status(self, state: TokenState) -> None:
        if self._on_status_change is not None:
            self._on_status_change(state)
        for queue in list(self._status_subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(state)
            except asyncio.QueueFull:  # pragma: no cover - guarded above
                continue
