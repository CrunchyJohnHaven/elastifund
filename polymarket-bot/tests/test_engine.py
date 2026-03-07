"""Tests for engine loop."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.broker.base import OrderSide, OrderStatus, Order
from src.broker.paper_broker import PaperBroker
from src.data.mock_feed import MockDataFeed
from src.strategy.sma_cross import SMACrossStrategy


class TestEngineKillSwitch:
    @pytest.mark.asyncio
    async def test_mock_data_feed_returns_prices(self):
        feed = MockDataFeed()
        price = await feed.get_price("tok1")
        assert 0.01 <= price <= 0.99

    @pytest.mark.asyncio
    async def test_strategy_hold_when_insufficient_data(self):
        strategy = SMACrossStrategy(fast_period=5, slow_period=20)
        signal = await strategy.generate_signal({
            "market_id": "mkt1",
            "token_id": "YES",
            "current_price": 0.5,
        })
        assert signal["action"] == "hold"
        assert "insufficient" in signal["reason"].lower()

    @pytest.mark.asyncio
    async def test_paper_broker_tracks_positions_correctly(self):
        broker = PaperBroker(initial_cash=1000, slippage_bps=0, fee_bps=0)
        await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.6, 50)
        positions = await broker.get_positions()
        assert len(positions) == 1
        assert positions[0].size == 150
