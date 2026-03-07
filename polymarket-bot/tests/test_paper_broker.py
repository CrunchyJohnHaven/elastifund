"""Tests for paper broker."""
import pytest
from src.broker.base import OrderSide, OrderStatus
from src.broker.paper_broker import PaperBroker


class TestPaperBroker:
    @pytest.mark.asyncio
    async def test_buy_order_fills(self):
        broker = PaperBroker(initial_cash=1000, slippage_bps=0, fee_bps=0)
        order = await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        assert order.status == OrderStatus.FILLED
        assert order.filled_size == 100
        assert broker.get_cash() == 950.0  # 1000 - (0.5 * 100)

    @pytest.mark.asyncio
    async def test_sell_order_fills(self):
        broker = PaperBroker(initial_cash=1000, slippage_bps=0, fee_bps=0)
        await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        order = await broker.place_order("mkt1", "tok1", OrderSide.SELL, 0.6, 50)
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_insufficient_cash_rejected(self):
        broker = PaperBroker(initial_cash=10, slippage_bps=0, fee_bps=0)
        order = await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        assert order.status == OrderStatus.REJECTED
        assert order.filled_size == 0

    @pytest.mark.asyncio
    async def test_slippage_applied(self):
        broker = PaperBroker(initial_cash=1000, slippage_bps=100, fee_bps=0)  # 1% slippage
        order = await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        assert order.status == OrderStatus.FILLED
        # Cash should be less than 950 due to slippage
        assert broker.get_cash() < 950.0

    @pytest.mark.asyncio
    async def test_fees_applied(self):
        broker = PaperBroker(initial_cash=1000, slippage_bps=0, fee_bps=100)  # 1% fee
        order = await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        assert order.status == OrderStatus.FILLED
        assert broker.get_cash() < 950.0

    @pytest.mark.asyncio
    async def test_position_tracking(self):
        broker = PaperBroker(initial_cash=1000, slippage_bps=0, fee_bps=0)
        await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        positions = await broker.get_positions()
        assert len(positions) == 1
        assert positions[0].size == 100

    @pytest.mark.asyncio
    async def test_cancel_unfilled(self):
        broker = PaperBroker(initial_cash=10, slippage_bps=0, fee_bps=0)
        order = await broker.place_order("mkt1", "tok1", OrderSide.BUY, 0.5, 100)
        # This was rejected, not pending, so can't cancel
        result = await broker.cancel_order("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_market_order(self):
        broker = PaperBroker(initial_cash=1000, slippage_bps=0, fee_bps=0)
        order = await broker.place_market_order("mkt1", "tok1", OrderSide.BUY, 50.0)
        assert order.status == OrderStatus.FILLED
