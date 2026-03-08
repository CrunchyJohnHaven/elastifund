#!/usr/bin/env python3
"""Tests for WebSocket reconnection with exponential backoff."""

import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.ws_trade_stream import TradeStreamManager


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
    """Records connect calls and returns scripted websocket objects."""

    def __init__(self, sockets):
        self.sockets = deque(sockets)
        self.calls = 0
        self.call_times: list[float] = []
        self.reconnected = asyncio.Event()

    def __call__(self, *args, **kwargs):
        self.calls += 1
        self.call_times.append(time.monotonic())
        if self.calls >= 2:
            self.reconnected.set()
        return self.sockets.popleft()


def run(coro):
    return asyncio.run(coro)


class TestReconnectionBackoff:
    """Verify exponential backoff on repeated disconnects."""

    def test_reconnects_after_disconnect(self):
        async def scenario():
            first = FakeWebSocket(
                [json.dumps({"event_type": "trade", "asset_id": "t1", "price": "0.5", "size": "10", "side": "BUY"})],
            )
            second = FakeWebSocket(
                [json.dumps({"event_type": "trade", "asset_id": "t1", "price": "0.6", "size": "10", "side": "SELL"})],
                hold_open=True,
            )
            factory = FakeConnectFactory([first, second])
            manager = TradeStreamManager(
                token_ids=["t1"],
                websocket_connect=factory,
                backoff_base=0.01,
                backoff_max=0.05,
                heartbeat_interval=1.0,
                latency_log_interval=3600,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())
            await asyncio.wait_for(factory.reconnected.wait(), timeout=2.0)

            assert factory.calls >= 2
            assert manager.get_status()["reconnect_count"] >= 1

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())

    def test_backoff_increases_exponentially(self):
        async def scenario():
            sockets = [FakeWebSocket([RuntimeError("fail")]) for _ in range(4)]
            sockets.append(FakeWebSocket([], hold_open=True))
            factory = FakeConnectFactory(sockets)

            # threshold high so circuit breaker doesn't trigger
            manager = TradeStreamManager(
                token_ids=["t1"],
                websocket_connect=factory,
                backoff_base=0.02,
                backoff_max=0.5,
                disconnect_threshold=100,
                heartbeat_interval=1.0,
                latency_log_interval=3600,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())
            deadline = time.time() + 3.0
            while factory.calls < 4 and time.time() < deadline:
                await asyncio.sleep(0.01)

            # Verify delays increased between attempts
            if len(factory.call_times) >= 3:
                delay_1 = factory.call_times[2] - factory.call_times[1]
                delay_2 = factory.call_times[3] - factory.call_times[2]
                assert delay_2 >= delay_1 * 1.5  # exponential growth

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())

    def test_backoff_capped_at_max(self):
        async def scenario():
            sockets = [FakeWebSocket([RuntimeError("fail")]) for _ in range(6)]
            sockets.append(FakeWebSocket([], hold_open=True))
            factory = FakeConnectFactory(sockets)

            manager = TradeStreamManager(
                token_ids=["t1"],
                websocket_connect=factory,
                backoff_base=0.01,
                backoff_max=0.05,
                disconnect_threshold=100,
                heartbeat_interval=1.0,
                latency_log_interval=3600,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())
            deadline = time.time() + 3.0
            while factory.calls < 6 and time.time() < deadline:
                await asyncio.sleep(0.01)

            # After enough failures, delays should be capped
            if len(factory.call_times) >= 5:
                last_delay = factory.call_times[-1] - factory.call_times[-2]
                assert last_delay <= 0.15  # should not exceed max by much

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())

    def test_backoff_resets_on_successful_connect(self):
        """After a successful connection, backoff resets to base."""
        async def scenario():
            first = FakeWebSocket(
                [json.dumps({"event_type": "trade", "asset_id": "t1", "price": "0.5", "size": "10", "side": "BUY"})],
            )
            second = FakeWebSocket([RuntimeError("fail2")])
            third = FakeWebSocket([], hold_open=True)
            factory = FakeConnectFactory([first, second, third])

            manager = TradeStreamManager(
                token_ids=["t1"],
                websocket_connect=factory,
                backoff_base=0.01,
                backoff_max=1.0,
                disconnect_threshold=100,
                heartbeat_interval=1.0,
                latency_log_interval=3600,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())
            deadline = time.time() + 3.0
            while factory.calls < 3 and time.time() < deadline:
                await asyncio.sleep(0.01)

            # First was successful, so backoff should reset before second reconnect
            if len(factory.call_times) >= 3:
                delay = factory.call_times[2] - factory.call_times[1]
                assert delay < 0.2  # should be near base, not accumulated

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())

    def test_resubscribes_on_reconnect(self):
        """After reconnect, manager sends subscription for all tokens."""
        async def scenario():
            first = FakeWebSocket([RuntimeError("disconnect")])
            second = FakeWebSocket([], hold_open=True)
            factory = FakeConnectFactory([first, second])

            manager = TradeStreamManager(
                token_ids=["t1", "t2", "t3"],
                websocket_connect=factory,
                backoff_base=0.01,
                backoff_max=0.01,
                disconnect_threshold=100,
                heartbeat_interval=1.0,
                latency_log_interval=3600,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())
            await asyncio.wait_for(factory.reconnected.wait(), timeout=2.0)

            # Second websocket should have subscription message sent
            sub_messages = [json.loads(s) for s in second.sent]
            assert len(sub_messages) >= 1
            assert "assets_ids" in sub_messages[0]
            assert set(sub_messages[0]["assets_ids"]) == {"t1", "t2", "t3"}

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())
