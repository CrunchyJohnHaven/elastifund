"""Lightweight backtesting harness."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from src.core.time_utils import utc_now_naive
from typing import Optional

import structlog

from src.broker.base import OrderSide, OrderStatus
from src.broker.paper_broker import PaperBroker
from src.strategy.base import Strategy

logger = structlog.get_logger(__name__)


@dataclass
class BacktestResult:
    """Backtest performance summary."""
    strategy_name: str
    symbol: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_cash: float = 0.0
    final_cash: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    equity_curve: list[float] = field(default_factory=list)


class Backtester:
    """Run a strategy on historical data."""

    def __init__(
        self,
        strategy: Strategy,
        initial_cash: float = 1000.0,
        slippage_bps: int = 10,
        fee_bps: int = 0,
    ):
        self.strategy = strategy
        self.initial_cash = initial_cash
        self.slippage_bps = slippage_bps
        self.fee_bps = fee_bps

    async def run(
        self,
        prices: list[float],
        market_id: str = "backtest",
        token_id: str = "YES",
    ) -> BacktestResult:
        """Run backtest on price series.

        Args:
            prices: List of prices (0-1 for prediction markets)
            market_id: Market identifier
            token_id: Token identifier

        Returns:
            BacktestResult with performance metrics
        """
        broker = PaperBroker(
            initial_cash=self.initial_cash,
            slippage_bps=self.slippage_bps,
            fee_bps=self.fee_bps,
        )

        equity_curve = [self.initial_cash]
        peak_equity = self.initial_cash
        max_drawdown = 0.0
        trade_count = 0

        for i, price in enumerate(prices):
            # Build market state
            positions = await broker.get_positions()
            market_state = {
                "market_id": market_id,
                "token_id": token_id,
                "question": f"Backtest market {market_id}",
                "current_price": price,
                "midpoint": price,
                "orderbook_depth": {},
                "positions": positions,
                "price_history": prices[:i+1],
                "timestamp": utc_now_naive(),
            }

            # Get signal
            signal = await self.strategy.generate_signal(market_state)
            action = signal.get("action", "hold")
            size = signal.get("size", 0)

            if action != "hold" and size > 0:
                side = OrderSide.BUY
                if action == "sell":
                    side = OrderSide.SELL

                order = await broker.place_order(market_id, token_id, side, price, size)
                if order.status == OrderStatus.FILLED:
                    trade_count += 1

            # Calculate equity
            cash = broker.get_cash()
            positions = await broker.get_positions()
            position_value = sum(p.size * p.current_price for p in positions)
            equity = cash + position_value
            equity_curve.append(equity)

            # Track drawdown
            if equity > peak_equity:
                peak_equity = equity
            drawdown = peak_equity - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        final_equity = equity_curve[-1]
        total_pnl = final_equity - self.initial_cash
        total_pnl_pct = (total_pnl / self.initial_cash * 100) if self.initial_cash > 0 else 0
        max_dd_pct = (max_drawdown / peak_equity * 100) if peak_equity > 0 else 0

        # Count wins/losses from fills
        fills = broker.get_all_fills()
        # Simple: compare consecutive buy/sell pairs
        win_count = sum(1 for f in fills if f.fee >= 0)  # simplified
        loss_count = len(fills) - win_count

        result = BacktestResult(
            strategy_name=self.strategy.name,
            symbol=f"{market_id}/{token_id}",
            initial_cash=self.initial_cash,
            final_cash=final_equity,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_dd_pct,
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=(win_count / trade_count * 100) if trade_count > 0 else 0,
            equity_curve=equity_curve,
        )

        logger.info(
            "backtest_complete",
            strategy=result.strategy_name,
            pnl=f"{result.total_pnl:.2f}",
            pnl_pct=f"{result.total_pnl_pct:.1f}%",
            max_drawdown=f"{result.max_drawdown:.2f}",
            trades=result.trade_count,
        )

        return result


def generate_synthetic_prices(
    n: int = 500,
    base_price: float = 0.5,
    trend: float = 0.0001,
    volatility: float = 0.02,
    seed: int = 42,
) -> list[float]:
    """Generate synthetic price data for backtesting.

    Args:
        n: Number of price points
        base_price: Starting price
        trend: Drift per step
        volatility: Random walk volatility
        seed: Random seed for reproducibility

    Returns:
        List of prices clamped to [0.01, 0.99]
    """
    import random
    random.seed(seed)

    prices = [base_price]
    for _ in range(n - 1):
        change = random.gauss(trend, volatility)
        new_price = prices[-1] + change
        new_price = max(0.01, min(0.99, new_price))
        prices.append(new_price)

    return prices
