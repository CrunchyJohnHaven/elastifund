#!/usr/bin/env python3
"""Tests for WebSocket Trade Stream + OFI Calculator."""

import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path

import pytest

# Ensure bot/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.vpin_toxicity import FlowRegime
from bot.ws_trade_stream import (
    OFICalculator,
    OFISnapshot,
    OrderBookLevel,
    OrderBookState,
    TradeStreamManager,
)


def run(coro):
    """Run a coroutine from a synchronous pytest test."""
    return asyncio.run(coro)


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
        if payload == "PING":
            self.messages.append("PONG")

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
    """Returns scripted websocket objects on successive connect calls."""

    def __init__(self, sockets):
        self.sockets = deque(sockets)
        self.calls = 0
        self.reconnected = asyncio.Event()

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls >= 2:
            self.reconnected.set()
        return self.sockets.popleft()


# ---------------------------------------------------------------------------
# OFI Calculator Tests
# ---------------------------------------------------------------------------


class TestOFICalculator:
    """Tests for the multi-level Order Flow Imbalance calculator."""

    def _make_book(self, token_id: str, bids: list, asks: list) -> OrderBookState:
        return OrderBookState(
            token_id=token_id,
            bids=[OrderBookLevel(p, s) for p, s in bids],
            asks=[OrderBookLevel(p, s) for p, s in asks],
            last_update=time.time(),
        )

    def test_first_update_returns_none(self):
        calc = OFICalculator()
        book = self._make_book("t1", [(0.50, 100)], [(0.52, 100)])
        result = calc.update("t1", book)
        assert result is None

    def test_second_update_returns_snapshot(self):
        calc = OFICalculator()
        book1 = self._make_book("t1", [(0.50, 100)], [(0.52, 100)])
        calc.update("t1", book1)

        book2 = self._make_book("t1", [(0.50, 150)], [(0.52, 80)])
        result = calc.update("t1", book2)
        assert isinstance(result, OFISnapshot)
        assert result.token_id == "t1"
        assert result.levels_used == 1

    def test_multi_level_weighting(self):
        calc = OFICalculator()
        book1 = self._make_book(
            "t1",
            [(0.50, 100), (0.49, 200), (0.48, 300)],
            [(0.52, 100), (0.53, 200), (0.54, 300)],
        )
        calc.update("t1", book1)

        book2 = self._make_book(
            "t1",
            [(0.50, 200), (0.49, 300), (0.48, 400)],
            [(0.52, 100), (0.53, 200), (0.54, 300)],
        )
        result = calc.update("t1", book2)

        assert result is not None
        assert result.levels_used == 3
        assert result.raw_ofi > 0

    def test_directional_skew_calculation(self):
        calc = OFICalculator()
        bids = [(0.50, 1000), (0.49, 500)]
        asks = [(0.52, 10), (0.53, 5)]
        book1 = self._make_book("t1", bids, asks)
        calc.update("t1", book1)

        result = calc.update("t1", self._make_book("t1", bids, asks))
        assert result is not None
        assert result.directional_skew > 0.8

    def test_kill_switch_on_extreme_skew(self):
        calc = OFICalculator()
        calc.update("t1", self._make_book("t1", [(0.50, 1000)], [(0.52, 10)]))
        result = calc.update("t1", self._make_book("t1", [(0.50, 1000)], [(0.52, 10)]))
        assert result is not None
        assert calc.should_kill(result)

    def test_no_kill_on_balanced_book(self):
        calc = OFICalculator()
        calc.update("t1", self._make_book("t1", [(0.50, 100)], [(0.52, 100)]))
        result = calc.update("t1", self._make_book("t1", [(0.50, 105)], [(0.52, 95)]))
        assert result is not None
        assert not calc.should_kill(result)

    def test_z_score_normalization(self):
        calc = OFICalculator()
        for i in range(10):
            book = self._make_book("t1", [(0.50, 100 + i)], [(0.52, 100 - i)])
            calc.update("t1", book)

        result = calc.update("t1", self._make_book("t1", [(0.50, 105)], [(0.52, 95)]))
        assert result is not None
        assert abs(result.normalized_ofi) < 5.0

    def test_empty_book_handled(self):
        calc = OFICalculator()
        assert calc.update("t1", self._make_book("t1", [], [])) is None
        assert calc.update("t1", self._make_book("t1", [], [])) is None


# ---------------------------------------------------------------------------
# TradeStreamManager Tests
# ---------------------------------------------------------------------------


class TestTradeStreamManager:
    """Tests for the unified trade stream manager."""

    def test_init_defaults(self):
        manager = TradeStreamManager()
        assert manager.token_ids == []
        assert manager._running is False

    def test_add_remove_token(self):
        manager = TradeStreamManager(token_ids=["t1", "t2"])
        manager.add_token("t3")
        manager.remove_token("t1")
        assert manager.token_ids == ["t2", "t3"]

    def test_duplicate_token_not_added(self):
        manager = TradeStreamManager(token_ids=["t1"])
        manager.add_token("t1")
        assert manager.token_ids.count("t1") == 1

    def test_regime_default_neutral(self):
        manager = TradeStreamManager()
        assert manager.get_regime("unknown_token") == FlowRegime.NEUTRAL

    def test_should_quote_default_true(self):
        manager = TradeStreamManager()
        assert manager.should_quote("unknown_token") is True

    def test_spread_adjustment_default(self):
        manager = TradeStreamManager()
        assert manager.get_spread_adjustment("unknown") < float("inf")

    def test_parse_trade_message(self):
        manager = TradeStreamManager(token_ids=["token123"])
        trade = manager._parse_trade_message(
            {
                "event_type": "trade",
                "asset_id": "token123",
                "price": "0.65",
                "size": "50",
                "side": "BUY",
            }
        )
        assert trade is not None
        assert trade["token_id"] == "token123"
        assert trade["price"] == 0.65
        assert trade["size"] == 50.0
        assert trade["side"] == "buy"

    def test_parse_non_trade_message(self):
        manager = TradeStreamManager()
        assert manager._parse_trade_message({"event_type": "heartbeat"}) is None

    def test_parse_book_full_snapshot(self):
        manager = TradeStreamManager(token_ids=["token123"])
        result = manager._parse_book_message(
            {
                "event_type": "book",
                "asset_id": "token123",
                "bids": [{"price": "0.50", "size": "100"}, {"price": "0.49", "size": "200"}],
                "asks": [{"price": "0.52", "size": "100"}, {"price": "0.53", "size": "200"}],
            }
        )
        assert result == "token123"
        assert "token123" in manager._books
        book = manager._books["token123"]
        assert len(book.bids) == 2
        assert len(book.asks) == 2
        assert book.bids[0].price == 0.50
        assert book.asks[0].price == 0.52

    def test_parse_incremental_price_change(self):
        manager = TradeStreamManager(token_ids=["token123"])
        manager._parse_book_message(
            {
                "event_type": "book",
                "asset_id": "token123",
                "bids": [{"price": "0.50", "size": "100"}],
                "asks": [{"price": "0.52", "size": "100"}],
            }
        )
        result = manager._parse_book_message(
            {
                "event_type": "price_change",
                "asset_id": "token123",
                "price_changes": [{"side": "BUY", "price": "0.50", "size": "140"}],
            }
        )
        assert result == "token123"
        assert manager._books["token123"].bids[0].size == 140.0

    def test_get_status(self):
        manager = TradeStreamManager(token_ids=["t1"])
        status = manager.get_status()
        assert status["connected"] is False
        assert status["tokens_tracked"] == 1
        assert status["fallback_active"] is False
        assert status["connection_mode"] == "disconnected"
        assert "t1" in status["markets"]

    def test_handle_message_records_latency_stats(self):
        manager = TradeStreamManager(token_ids=["token123"])
        payload = json.dumps(
            {
                "event_type": "trade",
                "asset_id": "token123",
                "price": "0.63",
                "size": "10",
                "side": "BUY",
                "timestamp": time.time() - 0.02,
            }
        )
        run(manager._handle_message(payload))
        stats = manager.get_latency_stats()
        assert stats["samples"] == 1
        assert stats["exchange_p99_ms"] >= 10.0
        assert stats["processing_p99_ms"] >= 0.0

    def test_ofi_update_callback_emits_on_book_updates(self):
        seen = []
        manager = TradeStreamManager(
            token_ids=["token123"],
            on_ofi_update=lambda token_id, snapshot: seen.append((token_id, snapshot)),
        )
        run(
            manager._handle_message(
                json.dumps(
                    {
                        "event_type": "book",
                        "asset_id": "token123",
                        "bids": [{"price": "0.50", "size": "100"}],
                        "asks": [{"price": "0.52", "size": "100"}],
                    }
                )
            )
        )
        run(
            manager._handle_message(
                json.dumps(
                    {
                        "event_type": "book",
                        "asset_id": "token123",
                        "bids": [{"price": "0.50", "size": "140"}],
                        "asks": [{"price": "0.52", "size": "80"}],
                    }
                )
            )
        )
        assert seen
        assert seen[0][0] == "token123"
        assert isinstance(seen[0][1], OFISnapshot)

    def test_get_microstructure_returns_latest_vpin_and_ofi(self):
        manager = TradeStreamManager(
            token_ids=["token123"],
            vpin_bucket_size=10.0,
            vpin_window_size=1,
        )
        run(
            manager._handle_message(
                json.dumps(
                    {
                        "event_type": "trade",
                        "asset_id": "token123",
                        "price": "0.63",
                        "size": "10",
                        "side": "BUY",
                        "timestamp": time.time(),
                    }
                )
            )
        )
        run(
            manager._handle_message(
                json.dumps(
                    {
                        "event_type": "book",
                        "asset_id": "token123",
                        "bids": [{"price": "0.50", "size": "100"}],
                        "asks": [{"price": "0.52", "size": "100"}],
                    }
                )
            )
        )
        run(
            manager._handle_message(
                json.dumps(
                    {
                        "event_type": "book",
                        "asset_id": "token123",
                        "bids": [{"price": "0.50", "size": "140"}],
                        "asks": [{"price": "0.52", "size": "80"}],
                    }
                )
            )
        )
        snapshot = manager.get_microstructure("token123")
        assert snapshot is not None
        assert snapshot["vpin"] == pytest.approx(1.0)
        assert snapshot["ofi"] is not None
        assert snapshot["midpoint"] == pytest.approx(0.51)

    def test_start_reconnects_after_disconnect(self):
        async def scenario():
            first = FakeWebSocket(
                [
                    json.dumps(
                        {
                            "event_type": "trade",
                            "asset_id": "token123",
                            "price": "0.63",
                            "size": "10",
                            "side": "BUY",
                            "timestamp": time.time(),
                        }
                    ),
                    RuntimeError("disconnect"),
                ]
            )
            second = FakeWebSocket(
                [
                    json.dumps(
                        {
                            "event_type": "trade",
                            "asset_id": "token123",
                            "price": "0.64",
                            "size": "10",
                            "side": "SELL",
                            "timestamp": time.time(),
                        }
                    )
                ],
                hold_open=True,
            )
            factory = FakeConnectFactory([first, second])
            manager = TradeStreamManager(
                token_ids=["token123"],
                websocket_connect=factory,
                vpin_bucket_size=10.0,
                vpin_window_size=1,
                backoff_base=0.01,
                backoff_max=0.01,
                heartbeat_interval=1.0,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())
            await asyncio.wait_for(factory.reconnected.wait(), timeout=1.0)
            assert factory.calls >= 2
            assert manager.get_status()["reconnect_count"] >= 1

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())

    def test_circuit_breaker_falls_back_to_rest_polling(self):
        async def scenario():
            async def fake_rest_fetch(token_id: str):
                return {
                    "bids": [{"price": "0.50", "size": "100"}],
                    "asks": [{"price": "0.52", "size": "100"}],
                }

            first = FakeWebSocket([RuntimeError("disconnect-1")])
            second = FakeWebSocket([RuntimeError("disconnect-2")])
            factory = FakeConnectFactory([first, second])
            manager = TradeStreamManager(
                token_ids=["token123"],
                websocket_connect=factory,
                rest_book_fetcher=fake_rest_fetch,
                disconnect_threshold=1,
                disconnect_window_seconds=30.0,
                fallback_cooldown_seconds=0.2,
                rest_poll_interval=0.01,
                backoff_base=0.01,
                backoff_max=0.01,
                heartbeat_interval=1.0,
            )
            manager.fetch_initial_books = lambda: asyncio.sleep(0)

            task = asyncio.create_task(manager.start())
            deadline = time.time() + 1.0
            while manager.get_status()["rest_fallback_polls"] < 1:
                if time.time() >= deadline:
                    raise AssertionError("REST fallback never triggered")
                await asyncio.sleep(0.01)

            status = manager.get_status()
            assert status["fallback_active"] is True
            assert status["connection_mode"] == "rest_fallback"
            assert manager.get_book("token123") is not None

            await manager.stop()
            await asyncio.wait_for(task, timeout=1.0)

        run(scenario())


class TestOrderBookState:
    """Tests for OrderBookState dataclass."""

    def test_midpoint(self):
        book = OrderBookState(
            token_id="t1",
            bids=[OrderBookLevel(0.50, 100)],
            asks=[OrderBookLevel(0.52, 100)],
        )
        assert book.midpoint == pytest.approx(0.51)

    def test_spread(self):
        book = OrderBookState(
            token_id="t1",
            bids=[OrderBookLevel(0.50, 100)],
            asks=[OrderBookLevel(0.55, 100)],
        )
        assert book.spread == pytest.approx(0.05)

    def test_empty_book(self):
        book = OrderBookState(token_id="t1")
        assert book.midpoint == 0.0
        assert book.spread == float("inf")
