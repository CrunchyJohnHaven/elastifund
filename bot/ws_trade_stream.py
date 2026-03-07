#!/usr/bin/env python3
"""
WebSocket market-depth stream for VPIN + OFI.

Keeps a lightweight local order-book state keyed by token id, feeds VPIN and
OFI calculators, and falls back to REST orderbook polling when the market
stream becomes unstable.
"""

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import httpx
except ImportError:  # pragma: no cover - optional dependency
    httpx = None

try:
    import websockets
except ImportError:  # pragma: no cover - optional dependency
    websockets = None

from bot.vpin_toxicity import FlowRegime, VPINManager


logger = logging.getLogger("JJ.ws_stream")

WS_ENDPOINT = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
CLOB_API_BASE = "https://clob.polymarket.com"

WS_BACKOFF_BASE = 1.0
WS_BACKOFF_MAX = 60.0
WS_PING_TIMEOUT = 10
WS_CIRCUIT_BREAKER_DISCONNECTS = 3
WS_CIRCUIT_BREAKER_WINDOW_SECONDS = 300
REST_FALLBACK_POLL_SECONDS = 5
LATENCY_SAMPLE_LIMIT = 2048
MAX_SUBSCRIPTIONS = 50
LATENCY_LOG_INTERVAL_SECONDS = 300  # 5 minutes
LATENCY_P99_ALERT_THRESHOLD_MS = 200.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _percentile(values: list[float], pct: float) -> float:
    """Compute percentile from sorted values list (pct in 0-1 range)."""
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
    return float(values[idx])


class LatencyPersistence:
    """Persist latency snapshots to SQLite for production monitoring."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path(os.environ.get("ELASTIFUND_DATA_DIR", "data")) / "ws_latency.db"
        self._db_path = str(db_path)
        self._init_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS latency_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'ws_trade_stream',
                    exchange_p50_ms REAL,
                    exchange_p95_ms REAL,
                    exchange_p99_ms REAL,
                    processing_p50_ms REAL,
                    processing_p95_ms REAL,
                    processing_p99_ms REAL,
                    sample_count INTEGER,
                    connection_mode TEXT
                )"""
            )
            conn.commit()
        finally:
            conn.close()

    def record(self, stats: dict[str, float], *, connection_mode: str = "unknown") -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """INSERT INTO latency_snapshots
                   (timestamp, exchange_p50_ms, exchange_p95_ms, exchange_p99_ms,
                    processing_p50_ms, processing_p95_ms, processing_p99_ms,
                    sample_count, connection_mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.time(),
                    stats.get("exchange_p50_ms", 0.0),
                    stats.get("exchange_p95_ms", 0.0),
                    stats.get("exchange_p99_ms", 0.0),
                    stats.get("processing_p50_ms", 0.0),
                    stats.get("processing_p95_ms", 0.0),
                    stats.get("processing_p99_ms", 0.0),
                    stats.get("samples", 0),
                    connection_mode,
                ),
            )
            conn.commit()
        finally:
            conn.close()


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBookState:
    token_id: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    last_update: float = 0.0

    @property
    def midpoint(self) -> float:
        if not self.bids or not self.asks:
            return 0.0
        return (self.bids[0].price + self.asks[0].price) / 2.0

    @property
    def spread(self) -> float:
        if not self.bids or not self.asks:
            return float("inf")
        return self.asks[0].price - self.bids[0].price


@dataclass
class OFISnapshot:
    timestamp: float
    token_id: str
    raw_ofi: float
    normalized_ofi: float
    levels_used: int
    directional_skew: float


class OFICalculator:
    """Multi-level order-flow imbalance calculator."""

    LEVEL_WEIGHTS = [1.0, 0.5, 0.25, 0.125, 0.0625]
    MAX_LEVELS = 5
    SKEW_THRESHOLD = 0.60
    RATIO_THRESHOLD = 3.0
    Z_SCORE_WINDOW = 300.0

    def __init__(self) -> None:
        self._prev_books: dict[str, OrderBookState] = {}
        self._ofi_history: dict[str, list[tuple[float, float]]] = {}

    def update(self, token_id: str, book: OrderBookState) -> Optional[OFISnapshot]:
        prev = self._prev_books.get(token_id)
        self._prev_books[token_id] = book

        if prev is None or not book.bids or not book.asks or not prev.bids or not prev.asks:
            return None

        now = time.time()
        total_ofi = 0.0
        levels_used = 0
        max_levels = min(self.MAX_LEVELS, len(book.bids), len(book.asks), len(prev.bids), len(prev.asks))

        for idx in range(max_levels):
            weight = self.LEVEL_WEIGHTS[idx]

            b_price = book.bids[idx].price
            b_size = book.bids[idx].size
            b_price_prev = prev.bids[idx].price
            b_size_prev = prev.bids[idx].size

            a_price = book.asks[idx].price
            a_size = book.asks[idx].size
            a_price_prev = prev.asks[idx].price
            a_size_prev = prev.asks[idx].size

            delta = 0.0
            if b_price >= b_price_prev:
                delta += b_size
            if b_price <= b_price_prev:
                delta -= b_size_prev
            if a_price <= a_price_prev:
                delta -= a_size
            if a_price >= a_price_prev:
                delta += a_size_prev

            total_ofi += weight * delta
            levels_used += 1

        if levels_used == 0:
            return None

        history = self._ofi_history.setdefault(token_id, [])
        history.append((now, total_ofi))
        cutoff = now - self.Z_SCORE_WINDOW
        history[:] = [(ts, value) for ts, value in history if ts >= cutoff]

        if len(history) < 3:
            normalized = 0.0
        else:
            values = [value for _, value in history]
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            std = variance ** 0.5 if variance > 0 else 1.0
            normalized = (total_ofi - mean) / std

        buy_pressure = sum(
            self.LEVEL_WEIGHTS[idx] * book.bids[idx].size
            for idx in range(min(self.MAX_LEVELS, len(book.bids)))
        )
        sell_pressure = sum(
            self.LEVEL_WEIGHTS[idx] * book.asks[idx].size
            for idx in range(min(self.MAX_LEVELS, len(book.asks)))
        )
        total_pressure = buy_pressure + sell_pressure
        directional_skew = max(buy_pressure, sell_pressure) / total_pressure if total_pressure > 0 else 0.5

        return OFISnapshot(
            timestamp=now,
            token_id=token_id,
            raw_ofi=total_ofi,
            normalized_ofi=normalized,
            levels_used=levels_used,
            directional_skew=directional_skew,
        )

    def should_kill(self, snapshot: OFISnapshot) -> bool:
        if snapshot.directional_skew > self.SKEW_THRESHOLD:
            return True
        if abs(snapshot.normalized_ofi) > self.RATIO_THRESHOLD:
            return True
        return False


class TradeStreamManager:
    """Best-effort market WebSocket manager with REST fallback."""

    def __init__(
        self,
        token_ids: Optional[list[str]] = None,
        vpin_bucket_size: float = 500.0,
        vpin_window_size: int = 10,
        on_regime_change: Optional[Callable[[str, FlowRegime, FlowRegime], None]] = None,
        on_ofi_update: Optional[Callable[[str, OFISnapshot], None]] = None,
        on_ofi_alert: Optional[Callable[[str, OFISnapshot], None]] = None,
        on_fallback: Optional[Callable[[dict[str, Any]], None]] = None,
        websocket_connect: Optional[Callable[..., Any]] = None,
        rest_book_fetcher: Optional[Callable[[str], Any]] = None,
        disconnect_threshold: int = WS_CIRCUIT_BREAKER_DISCONNECTS,
        disconnect_window_seconds: float = WS_CIRCUIT_BREAKER_WINDOW_SECONDS,
        fallback_cooldown_seconds: float = REST_FALLBACK_POLL_SECONDS,
        rest_poll_interval: float = REST_FALLBACK_POLL_SECONDS,
        backoff_base: float = WS_BACKOFF_BASE,
        backoff_max: float = WS_BACKOFF_MAX,
        heartbeat_interval: float = 30.0,
        max_subscriptions: int = MAX_SUBSCRIPTIONS,
        latency_log_interval: float = LATENCY_LOG_INTERVAL_SECONDS,
        latency_db_path: Optional[str] = None,
    ) -> None:
        initial = list(dict.fromkeys(token_ids or []))
        self.max_subscriptions = max(1, int(max_subscriptions))
        self.token_ids: list[str] = initial[: self.max_subscriptions]
        if len(initial) > self.max_subscriptions:
            logger.warning(
                "token list truncated from %d to max %d subscriptions",
                len(initial), self.max_subscriptions,
            )
        self.vpin = VPINManager(bucket_size=vpin_bucket_size, window_size=vpin_window_size)
        self.ofi = OFICalculator()
        self.on_regime_change = on_regime_change
        self.on_ofi_update = on_ofi_update
        self.on_ofi_alert = on_ofi_alert
        self.on_fallback = on_fallback
        self.websocket_connect = websocket_connect
        self.rest_book_fetcher = rest_book_fetcher
        self.disconnect_threshold = max(1, int(disconnect_threshold))
        self.disconnect_window_seconds = max(1.0, float(disconnect_window_seconds))
        self.fallback_cooldown_seconds = max(0.0, float(fallback_cooldown_seconds))
        self.rest_poll_interval = max(0.001, float(rest_poll_interval))
        self.backoff_base = max(0.001, float(backoff_base))
        self.backoff_max = max(self.backoff_base, float(backoff_max))
        self.heartbeat_interval = max(0.5, float(heartbeat_interval))
        self.latency_log_interval = max(10.0, float(latency_log_interval))

        self._books: dict[str, OrderBookState] = {}
        self._last_ofi: dict[str, OFISnapshot] = {}
        self._running = False
        self._connected = False
        self._fallback_active = False
        self._fallback_activations = 0
        self._rest_fallback_polls = 0
        self._reconnect_count = 0
        self._disconnect_times: deque[float] = deque()
        self._exchange_latency_samples: deque[float] = deque(maxlen=LATENCY_SAMPLE_LIMIT)
        self._processing_latency_samples: deque[float] = deque(maxlen=LATENCY_SAMPLE_LIMIT)
        self._ws: Any = None

        self._latency_persistence: LatencyPersistence | None = None
        self._latency_db_path = latency_db_path

    def _ensure_latency_persistence(self) -> LatencyPersistence:
        if self._latency_persistence is None:
            self._latency_persistence = LatencyPersistence(db_path=self._latency_db_path)
        return self._latency_persistence

    def add_token(self, token_id: str) -> bool:
        """Add a token to track. Returns False if at max subscriptions."""
        token = str(token_id).strip()
        if not token or token in self.token_ids:
            return token in self.token_ids
        if len(self.token_ids) >= self.max_subscriptions:
            logger.warning(
                "cannot add token %s: at max subscriptions (%d)",
                token[:12], self.max_subscriptions,
            )
            return False
        self.token_ids.append(token)
        return True

    def remove_token(self, token_id: str) -> None:
        token = str(token_id).strip()
        self.token_ids = [existing for existing in self.token_ids if existing != token]
        self._books.pop(token, None)
        self._last_ofi.pop(token, None)

    def get_regime(self, token_id: str) -> FlowRegime:
        return self.vpin.get_regime(token_id)

    def should_quote(self, token_id: str) -> bool:
        return self.vpin.should_quote(token_id)

    def get_spread_adjustment(self, token_id: str) -> float:
        return self.vpin.get_spread_adjustment(token_id)

    def get_book(self, token_id: str) -> Optional[OrderBookState]:
        return self._books.get(token_id)

    def _register_disconnect(self, now: Optional[float] = None) -> bool:
        ts = float(now if now is not None else time.time())
        self._disconnect_times.append(ts)
        cutoff = ts - self.disconnect_window_seconds
        while self._disconnect_times and self._disconnect_times[0] < cutoff:
            self._disconnect_times.popleft()

        triggered = len(self._disconnect_times) >= self.disconnect_threshold
        if triggered and not self._fallback_active:
            self._fallback_activations += 1
        self._fallback_active = triggered
        return triggered

    def _record_exchange_latency(self, event_timestamp: float) -> None:
        if event_timestamp <= 0:
            return
        latency_ms = max(0.0, (time.time() - event_timestamp) * 1000.0)
        self._exchange_latency_samples.append(latency_ms)

    def _record_processing_latency(self, started_at: float) -> None:
        latency_ms = max(0.0, (time.time() - started_at) * 1000.0)
        self._processing_latency_samples.append(latency_ms)

    def get_latency_stats(self) -> dict[str, float]:
        exchange = sorted(self._exchange_latency_samples)
        processing = sorted(self._processing_latency_samples)
        if not exchange and not processing:
            return {
                "samples": 0,
                "exchange_p50_ms": 0.0,
                "exchange_p95_ms": 0.0,
                "exchange_p99_ms": 0.0,
                "processing_p50_ms": 0.0,
                "processing_p95_ms": 0.0,
                "processing_p99_ms": 0.0,
            }

        def percentile(values: list[float], pct: float) -> float:
            if not values:
                return 0.0
            idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * pct))))
            return float(values[idx])

        return {
            "samples": max(len(exchange), len(processing)),
            "exchange_p50_ms": percentile(exchange, 0.50),
            "exchange_p95_ms": percentile(exchange, 0.95),
            "exchange_p99_ms": percentile(exchange, 0.99),
            "processing_p50_ms": percentile(processing, 0.50),
            "processing_p95_ms": percentile(processing, 0.95),
            "processing_p99_ms": percentile(processing, 0.99),
        }

    @staticmethod
    def _parse_levels(levels: Any) -> list[OrderBookLevel]:
        parsed: list[OrderBookLevel] = []
        if not isinstance(levels, list):
            return parsed

        for level in levels:
            if isinstance(level, dict):
                price = _safe_float(level.get("price"), -1.0)
                size = _safe_float(level.get("size"), 0.0)
            elif isinstance(level, list) and len(level) >= 2:
                price = _safe_float(level[0], -1.0)
                size = _safe_float(level[1], 0.0)
            else:
                continue
            if 0.0 <= price <= 1.0 and size >= 0.0:
                parsed.append(OrderBookLevel(price=price, size=size))
        return parsed

    def _replace_book(self, token_id: str, bids: list[OrderBookLevel], asks: list[OrderBookLevel]) -> None:
        self._books[token_id] = OrderBookState(
            token_id=token_id,
            bids=sorted(bids, key=lambda level: -level.price),
            asks=sorted(asks, key=lambda level: level.price),
            last_update=time.time(),
        )

    @staticmethod
    def _iter_changes(data: dict[str, Any]) -> Optional[list[Any]]:
        changes = data.get("changes")
        if isinstance(changes, list):
            return changes
        changes = data.get("price_changes")
        if isinstance(changes, list):
            return changes
        return None

    def _apply_level_change(self, levels: list[OrderBookLevel], *, price: float, size: float, reverse: bool) -> list[OrderBookLevel]:
        updated = [level for level in levels if abs(level.price - price) > 1e-9]
        if size > 0.0:
            updated.append(OrderBookLevel(price=price, size=size))
        return sorted(updated, key=lambda level: -level.price if reverse else level.price)

    async def fetch_initial_books(self) -> None:
        if not self.token_ids:
            return

        if self.rest_book_fetcher is not None:
            for token_id in list(self.token_ids):
                try:
                    payload = await self.rest_book_fetcher(token_id)
                except Exception as exc:  # pragma: no cover - caller-defined fetcher
                    logger.debug("custom rest fetch failed for %s: %s", token_id, exc)
                    continue
                if not isinstance(payload, dict):
                    continue
                self._replace_book(token_id, self._parse_levels(payload.get("bids")), self._parse_levels(payload.get("asks")))
            return

        if httpx is None:
            return

        async with httpx.AsyncClient(timeout=10.0) as client:
            for token_id in list(self.token_ids):
                try:
                    response = await client.get(f"{CLOB_API_BASE}/book", params={"token_id": token_id})
                except Exception as exc:  # pragma: no cover - network failure path
                    logger.debug("book bootstrap failed for %s: %s", token_id, exc)
                    continue
                if response.status_code == 404:
                    continue
                if response.status_code != 200:
                    continue
                payload = response.json()
                self._replace_book(token_id, self._parse_levels(payload.get("bids")), self._parse_levels(payload.get("asks")))

    def _parse_trade_message(self, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        msg_type = str(data.get("event_type") or data.get("type") or "").lower()
        if msg_type != "trade":
            return None

        token_id = str(data.get("asset_id") or data.get("market") or data.get("token_id") or "").strip()
        if not token_id:
            return None

        side_raw = str(data.get("side") or data.get("taker_side") or "").strip().lower()
        if side_raw.startswith("b"):
            side = "buy"
        elif side_raw.startswith("s"):
            side = "sell"
        else:
            side = side_raw or "buy"

        timestamp = _safe_float(data.get("timestamp") or data.get("ts"), 0.0)
        if timestamp > 1e12:
            timestamp /= 1000.0
        if timestamp > 0:
            self._record_exchange_latency(timestamp)

        return {
            "token_id": token_id,
            "price": _safe_float(data.get("price"), 0.0),
            "size": _safe_float(data.get("size"), 0.0),
            "side": side,
            "timestamp": timestamp or time.time(),
        }

    def _parse_book_message(self, data: dict[str, Any]) -> Optional[str]:
        msg_type = str(data.get("event_type") or data.get("type") or "").lower()
        if msg_type not in {"book", "price_change", "best_bid_ask"}:
            return None

        token_id = str(data.get("asset_id") or data.get("market") or data.get("token_id") or "").strip()
        if not token_id:
            return None

        timestamp = _safe_float(data.get("timestamp") or data.get("ts"), 0.0)
        if timestamp > 1e12:
            timestamp /= 1000.0
        if timestamp > 0:
            self._record_exchange_latency(timestamp)

        if msg_type in {"book", "best_bid_ask"}:
            bids = self._parse_levels(data.get("bids"))
            asks = self._parse_levels(data.get("asks"))
            if not bids and data.get("best_bid") is not None:
                bids = [OrderBookLevel(_safe_float(data.get("best_bid")), _safe_float(data.get("best_bid_size"), 0.0))]
            if not asks and data.get("best_ask") is not None:
                asks = [OrderBookLevel(_safe_float(data.get("best_ask")), _safe_float(data.get("best_ask_size"), 0.0))]
            self._replace_book(token_id, bids, asks)
            return token_id

        book = self._books.setdefault(token_id, OrderBookState(token_id=token_id))
        changes = self._iter_changes(data)
        if changes is not None:
            for change in changes:
                if isinstance(change, dict):
                    side = str(change.get("side") or "").lower()
                    price = _safe_float(change.get("price"), -1.0)
                    size = _safe_float(change.get("size"), 0.0)
                elif isinstance(change, list) and len(change) >= 3:
                    side = str(change[0]).lower()
                    price = _safe_float(change[1], -1.0)
                    size = _safe_float(change[2], 0.0)
                else:
                    continue
                if not (0.0 <= price <= 1.0):
                    continue
                if side.startswith("b"):
                    book.bids = self._apply_level_change(book.bids, price=price, size=size, reverse=True)
                elif side.startswith("a") or side.startswith("s"):
                    book.asks = self._apply_level_change(book.asks, price=price, size=size, reverse=False)
        else:
            bids = self._parse_levels(data.get("bids"))
            asks = self._parse_levels(data.get("asks"))
            if bids or asks:
                self._replace_book(token_id, bids or book.bids, asks or book.asks)
                return token_id

        book.last_update = time.time()
        return token_id

    async def _handle_message(self, raw_message: str) -> None:
        started_at = time.time()
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        messages = payload if isinstance(payload, list) else [payload]
        for message in messages:
            if not isinstance(message, dict):
                continue

            trade = self._parse_trade_message(message)
            if trade is not None:
                before = self.vpin.get_regime(trade["token_id"])
                after = self.vpin.on_trade(
                    trade["token_id"],
                    trade["price"],
                    trade["size"],
                    trade["side"],
                    trade["timestamp"],
                )
                if after != before and self.on_regime_change is not None:
                    self.on_regime_change(trade["token_id"], before, after)

            updated_token = self._parse_book_message(message)
            if updated_token is not None:
                book = self._books.get(updated_token)
                if book is None:
                    continue
                snapshot = self.ofi.update(updated_token, book)
                if snapshot:
                    self._last_ofi[updated_token] = snapshot
                    if self.on_ofi_update is not None:
                        self.on_ofi_update(updated_token, snapshot)
                    if self.ofi.should_kill(snapshot) and self.on_ofi_alert is not None:
                        self.on_ofi_alert(updated_token, snapshot)

        self._record_processing_latency(started_at)

    async def _run_rest_fallback_once(self) -> None:
        self._rest_fallback_polls += 1
        if self.rest_book_fetcher is not None:
            for token_id in list(self.token_ids):
                try:
                    payload = await self.rest_book_fetcher(token_id)
                except Exception as exc:  # pragma: no cover - caller-defined fetcher
                    logger.debug("fallback rest fetch failed for %s: %s", token_id, exc)
                    continue
                if not isinstance(payload, dict):
                    continue
                self._replace_book(token_id, self._parse_levels(payload.get("bids")), self._parse_levels(payload.get("asks")))
        else:
            await self.fetch_initial_books()
        for token_id, book in list(self._books.items()):
            snapshot = self.ofi.update(token_id, book)
            if snapshot:
                self._last_ofi[token_id] = snapshot
                if self.on_ofi_update is not None:
                    self.on_ofi_update(token_id, snapshot)
                if self.ofi.should_kill(snapshot) and self.on_ofi_alert is not None:
                    self.on_ofi_alert(token_id, snapshot)

    async def _connect_and_stream(self) -> None:
        connector = self.websocket_connect
        if connector is None:
            if websockets is None:  # pragma: no cover - optional dependency path
                raise RuntimeError("websockets dependency unavailable")
            connector = websockets.connect

        async with connector(
            WS_ENDPOINT,
            ping_interval=self.heartbeat_interval,
            ping_timeout=WS_PING_TIMEOUT,
        ) as ws:
            self._ws = ws
            self._connected = True
            self._fallback_active = False
            await ws.send(json.dumps({"type": "market", "assets_ids": list(self.token_ids)}))
            async for raw in ws:
                if not self._running:
                    break
                await self._handle_message(raw)

    async def _latency_log_loop(self) -> None:
        """Periodically log and persist latency stats. Warn if p99 > threshold."""
        while self._running:
            await asyncio.sleep(self.latency_log_interval)
            if not self._running:
                break
            stats = self.get_latency_stats()
            if stats["samples"] == 0:
                continue
            mode = "websocket" if self._connected else "rest_fallback" if self._fallback_active else "disconnected"
            logger.info(
                "WS latency: exchange p50=%.1fms p95=%.1fms p99=%.1fms | "
                "processing p50=%.1fms p95=%.1fms p99=%.1fms | "
                "samples=%d mode=%s",
                stats["exchange_p50_ms"], stats["exchange_p95_ms"], stats["exchange_p99_ms"],
                stats["processing_p50_ms"], stats["processing_p95_ms"], stats["processing_p99_ms"],
                stats["samples"], mode,
            )
            if stats["processing_p99_ms"] > LATENCY_P99_ALERT_THRESHOLD_MS:
                logger.warning(
                    "processing p99 latency %.1fms exceeds %.0fms threshold",
                    stats["processing_p99_ms"], LATENCY_P99_ALERT_THRESHOLD_MS,
                )
            if stats["exchange_p99_ms"] > LATENCY_P99_ALERT_THRESHOLD_MS:
                logger.warning(
                    "exchange p99 latency %.1fms exceeds %.0fms threshold",
                    stats["exchange_p99_ms"], LATENCY_P99_ALERT_THRESHOLD_MS,
                )
            try:
                persistence = self._ensure_latency_persistence()
                persistence.record(stats, connection_mode=mode)
            except Exception as exc:
                logger.debug("failed to persist latency snapshot: %s", exc)

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        latency_task = asyncio.create_task(self._latency_log_loop(), name="ws-latency-log")
        try:
            await self.fetch_initial_books()

            if (self.websocket_connect is None and websockets is None) or not self.token_ids:  # pragma: no cover - optional dependency path
                while self._running:
                    await self._run_rest_fallback_once()
                    await asyncio.sleep(self.rest_poll_interval)
                return

            backoff = self.backoff_base
            while self._running:
                try:
                    await self._connect_and_stream()
                    if self._running:
                        raise ConnectionError("market stream ended")
                except asyncio.CancelledError:  # pragma: no cover - shutdown path
                    raise
                except Exception as exc:  # pragma: no cover - exercised by injected doubles
                    self._connected = False
                    self._ws = None
                    self._reconnect_count += 1
                    logger.warning("market ws disconnected: %s", exc)
                    fallback = self._register_disconnect()
                    if fallback:
                        if self.on_fallback is not None:
                            self.on_fallback(self.get_status())
                        await self._run_rest_fallback_once()
                        await asyncio.sleep(self.fallback_cooldown_seconds)
                    else:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2.0, self.backoff_max)

            self._connected = False
            self._ws = None
        finally:
            latency_task.cancel()
            try:
                await latency_task
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # pragma: no cover - best effort close
                pass

    def get_microstructure(self, token_id: str) -> Optional[dict[str, Any]]:
        book = self._books.get(token_id)
        if book is None:
            return None
        ofi = self._last_ofi.get(token_id)
        latency = self.get_latency_stats()
        return {
            "token_id": token_id,
            "vpin": self.vpin.get_vpin(token_id),
            "regime": self.get_regime(token_id).value,
            "ofi": ofi.normalized_ofi if ofi is not None else None,
            "ofi_raw": ofi.raw_ofi if ofi is not None else None,
            "ofi_skew": ofi.directional_skew if ofi is not None else None,
            "midpoint": book.midpoint,
            "spread": book.spread,
            "connection_mode": self.get_status()["connection_mode"],
            "fallback_active": self._fallback_active,
            "latency_p99_ms": latency["processing_p99_ms"],
        }

    def get_status(self) -> dict[str, Any]:
        markets: dict[str, dict[str, Any]] = {}
        for token_id in self.token_ids:
            short = token_id[:12]
            book = self._books.get(token_id)
            status: dict[str, Any] = {
                "regime": self.get_regime(token_id).value,
                "vpin": round(self.vpin.get_vpin(token_id), 4),
                "has_book": book is not None,
            }
            if book is not None:
                status["midpoint"] = round(book.midpoint, 4)
                status["spread"] = round(book.spread, 4)
                status["bid_levels"] = len(book.bids)
                status["ask_levels"] = len(book.asks)
            markets[short] = status

        return {
            "connected": self._connected,
            "tokens_tracked": len(self.token_ids),
            "max_subscriptions": self.max_subscriptions,
            "fallback_active": self._fallback_active,
            "fallback_activations": self._fallback_activations,
            "rest_fallback_polls": self._rest_fallback_polls,
            "reconnect_count": self._reconnect_count,
            "connection_mode": "websocket" if self._connected else "rest_fallback" if self._fallback_active else "disconnected",
            "markets": markets,
            "latency": self.get_latency_stats(),
        }
