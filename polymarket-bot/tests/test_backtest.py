"""Tests for backtesting harness."""
import pytest
from src.strategy.sma_cross import SMACrossStrategy
from src.strategy.backtest import Backtester, generate_synthetic_prices


class TestBacktest:
    @pytest.mark.asyncio
    async def test_deterministic_backtest(self):
        prices = generate_synthetic_prices(n=100, seed=42)
        strategy = SMACrossStrategy(fast_period=5, slow_period=20)
        bt = Backtester(strategy, initial_cash=1000, slippage_bps=0, fee_bps=0)
        
        result = await bt.run(prices)
        
        assert result.strategy_name == "SMACross(5,20)"
        assert result.initial_cash == 1000
        assert len(result.equity_curve) == 101  # initial + 100 steps
        assert result.max_drawdown >= 0

    @pytest.mark.asyncio
    async def test_deterministic_reproducibility(self):
        prices = generate_synthetic_prices(n=100, seed=42)
        strategy1 = SMACrossStrategy(fast_period=5, slow_period=20)
        strategy2 = SMACrossStrategy(fast_period=5, slow_period=20)
        
        bt1 = Backtester(strategy1, initial_cash=1000, slippage_bps=0, fee_bps=0)
        bt2 = Backtester(strategy2, initial_cash=1000, slippage_bps=0, fee_bps=0)
        
        r1 = await bt1.run(prices)
        r2 = await bt2.run(prices)
        
        assert r1.final_cash == r2.final_cash
        assert r1.trade_count == r2.trade_count

    def test_synthetic_prices_reproducible(self):
        p1 = generate_synthetic_prices(n=50, seed=123)
        p2 = generate_synthetic_prices(n=50, seed=123)
        assert p1 == p2

    def test_synthetic_prices_clamped(self):
        prices = generate_synthetic_prices(n=1000, volatility=0.1)
        assert all(0.01 <= p <= 0.99 for p in prices)
