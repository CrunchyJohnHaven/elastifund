#!/usr/bin/env python3
"""Tests for WebSocket circuit breaker and REST fallback."""

import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.ws_trade_stream import TradeStreamManager, MAX_SUBSCRIPTIONS


class FakeWebSocket:
    """Minimal async websocket test double."""

    def __init__(self, messages, hold_open: bool = False):
        self.messages = deque(messages)
        self.sent: list[str] = []
        self.closed = False
        self.hold_open = hold_open

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True
        return False

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            if self.closed:
                raise StopAsyncIteration
            if self.messages:
                item = self.messages.popleft()
                if isinstance(item, BaseException):
                    raise item
                return item
            if not self.hold_open:
                raise StopAsyncIteration
            await asyncio.sleep(0.005)


class FakeConnectFactory:
    def __init__(self, sockets):
        self.sockets = deque(sockets)
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.sockets.popleft()


def run(coro):
    return asyncio.run(coro)


class TestCircuitBreaker:
    """Verify circuit breaker triggers REST fallback after repeated disconnects."""

    def test_circuit_breaker_activates_on_threshold(self):
        manager = TradeStreamManager(
            token_ids=["t1"],
            disconnect_threshold=3,
            disconnect_window_seconds=60.0,
        )
        now = time.time()

        # First two disconnects: no fallback
        assert manager._register_disconnect(now) is False
        assert manager._register_disconnect(now + 1) is False
        # Third disconnect: triggers fallback
        assert manager._register_disconnect(now + 2) is True
        assert manager._fallback_active is True
        assert manager._fallback_activations == 1

    def test_circuit_breaker_resets_after_window(self):
        manager = TradeStreamManager(
            token_ids=["t1"],
            disconnect_threshold=3,
            disconnect_window_seconds=10.0,
        )
        now = time.time()

        manager._register_disconnect(now)
        manager._register_disconnect(now + 1)
        # Wait past the window
        result = manager._register_disconnect(now + 15)
        # Only 1 disconnect in the new window
        assert result is False

    def test_fallback_counter_increments_once_per_activation(self):
        manager = TradeStreamManager(
            token_ids=["t1"],
            disconnect_threshold=2,
            disconnect_window_seconds=60.0,
        )
        now = time.time()

        manager._register_disconnect(now)
        manager._register_disconnect(now + 1)  # activates
        assert manager._fallback_activations == 1

        # Additional disconnects while already in fallback don't increment
        manager._register_disconnect(now + 2)
        assert manager._fallback_activations == 1

    def test_rest_fallback_polls_when_triggered(self):
        async def scenario():
            rest_calls = []

            async def fake_rest_fetch(token_id: str):
                rest_calls.append(token_id)
                return {
                    "bids": [{"price": "0.50", "size": "100"}],
                    "asks": [{"price": "0.52", "size": "100"}],
                }

            first = FakeWebSocket([RuntimeError("disconnect")])
            factory = FakeConnectFactory([first])

            manager = TradeStreamManager(
                token_ids=["t1"],
                websocket_connect=factory,
                rest_book_fetcher=fake_rest_fetch,
                disconnect_threshold=1,
                disconnect_window_seconds=60.0,
                fallback_cooldown_seconds=0.01,
                backoff_base=0.01,
                backoff_max=0.01,
                heartbeat_interval=1.0,
                latency_log_interval=3600,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())

            deadline = time.time() + 2.0
            while not rest_calls and time.time() < deadline:
                await asyncio.sleep(0.01)

            assert len(rest_calls) >= 1
            assert "t1" in rest_calls

            status = manager.get_status()
            assert status["fallback_active"] is True
            assert status["connection_mode"] == "rest_fallback"
            assert manager.get_book("t1") is not None

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())

    def test_fallback_callback_fired(self):
        async def scenario():
            fallback_events = []

            first = FakeWebSocket([RuntimeError("disconnect")])
            factory = FakeConnectFactory([first])

            manager = TradeStreamManager(
                token_ids=["t1"],
                websocket_connect=factory,
                rest_book_fetcher=lambda tid: asyncio.coroutine(lambda: {"bids": [], "asks": []})(),
                on_fallback=lambda status: fallback_events.append(status),
                disconnect_threshold=1,
                disconnect_window_seconds=60.0,
                fallback_cooldown_seconds=0.01,
                backoff_base=0.01,
                backoff_max=0.01,
                heartbeat_interval=1.0,
                latency_log_interval=3600,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())

            deadline = time.time() + 2.0
            while not fallback_events and time.time() < deadline:
                await asyncio.sleep(0.01)

            assert len(fallback_events) >= 1
            assert fallback_events[0]["fallback_active"] is True

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())


class TestSubscriptionManagement:
    """Verify max subscription cap and add/remove behavior."""

    def test_max_subscriptions_enforced_on_init(self):
        tokens = [f"t{i}" for i in range(100)]
        manager = TradeStreamManager(token_ids=tokens, max_subscriptions=10)
        assert len(manager.token_ids) == 10
        assert manager.token_ids == tokens[:10]

    def test_add_token_rejected_at_max(self):
        tokens = [f"t{i}" for i in range(5)]
        manager = TradeStreamManager(token_ids=tokens, max_subscriptions=5)
        result = manager.add_token("t_new")
        assert result is False
        assert len(manager.token_ids) == 5
        assert "t_new" not in manager.token_ids

    def test_add_token_succeeds_under_max(self):
        manager = TradeStreamManager(token_ids=["t1"], max_subscriptions=5)
        result = manager.add_token("t2")
        assert result is True
        assert "t2" in manager.token_ids

    def test_add_duplicate_returns_true(self):
        manager = TradeStreamManager(token_ids=["t1"], max_subscriptions=5)
        result = manager.add_token("t1")
        assert result is True
        assert manager.token_ids.count("t1") == 1

    def test_remove_frees_slot(self):
        tokens = [f"t{i}" for i in range(5)]
        manager = TradeStreamManager(token_ids=tokens, max_subscriptions=5)
        manager.remove_token("t0")
        assert len(manager.token_ids) == 4
        result = manager.add_token("t_new")
        assert result is True

    def test_default_max_subscriptions(self):
        manager = TradeStreamManager()
        assert manager.max_subscriptions == MAX_SUBSCRIPTIONS

    def test_status_includes_max_subscriptions(self):
        manager = TradeStreamManager(token_ids=["t1"], max_subscriptions=25)
        status = manager.get_status()
        assert status["max_subscriptions"] == 25
        assert status["tokens_tracked"] == 1

    def test_remove_cleans_up_state(self):
        manager = TradeStreamManager(token_ids=["t1", "t2"])
        # Simulate book data
        from bot.ws_trade_stream import OrderBookState, OrderBookLevel
        manager._books["t1"] = OrderBookState(
            token_id="t1",
            bids=[OrderBookLevel(0.5, 100)],
            asks=[OrderBookLevel(0.52, 100)],
        )
        manager.remove_token("t1")
        assert "t1" not in manager.token_ids
        assert "t1" not in manager._books
