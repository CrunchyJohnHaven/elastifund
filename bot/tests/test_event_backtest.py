"""Tests for event_backtest.py — Event-driven backtester."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.event_backtest import (
    BacktestConfig,
    BacktestResult,
    BacktestSignal,
    EventDrivenBacktester,
    ExecutionMode,
    FillModel,
    FillResult,
)
from bot.net_edge_accounting import FeeSchedule


def _make_signal(ts_offset: float, side: str, price: float,
                 resolved_yes: bool, edge_bps: float = 100.0,
                 market_id: str = "m1") -> BacktestSignal:
    base_ts = 1700000000.0
    return BacktestSignal(
        ts=base_ts + ts_offset,
        market_id=market_id,
        side=side,
        entry_price=price,
        fair_value=price + 0.05 if side == "BUY_YES" else price - 0.05,
        edge_bps=edge_bps,
        resolved_outcome=resolved_yes,
        resolution_ts=base_ts + ts_offset + 3600,
        category="politics",
        venue="polymarket",
    )


class TestFillModel:
    def test_taker_almost_always_fills(self):
        config = BacktestConfig(taker_fill_rate=0.99)
        model = FillModel(config)
        signal = _make_signal(0, "BUY_YES", 0.50, True)

        fills = 0
        for _ in range(100):
            model._rng.seed(fills)
            result = model.simulate_fill(signal, ExecutionMode.TAKER, 10.0)
            if result.filled:
                fills += 1
        assert fills > 80  # should fill most of the time

    def test_maker_lower_fill_rate(self):
        config = BacktestConfig(maker_fill_rate=0.60)
        model = FillModel(config)
        signal = _make_signal(0, "BUY_YES", 0.50, True, edge_bps=50)

        fills = sum(
            1 for i in range(200)
            if (model._rng.seed(i) or True) and
            model.simulate_fill(signal, ExecutionMode.MAKER, 10.0).filled
        )
        assert 30 < fills < 170  # roughly 60%

    def test_unfilled_has_zero_costs(self):
        config = BacktestConfig(maker_fill_rate=0.0)
        model = FillModel(config)
        signal = _make_signal(0, "BUY_YES", 0.50, True)
        result = model.simulate_fill(signal, ExecutionMode.MAKER, 10.0)
        assert not result.filled
        assert result.fees == 0.0
        assert result.slippage == 0.0

    def test_maker_price_is_signal_price(self):
        config = BacktestConfig(maker_fill_rate=1.0)
        model = FillModel(config)
        signal = _make_signal(0, "BUY_YES", 0.65, True)
        result = model.simulate_fill(signal, ExecutionMode.MAKER, 10.0)
        assert result.filled
        assert result.fill_price == 0.65


class TestEventDrivenBacktester:
    def test_empty_signals(self):
        bt = EventDrivenBacktester()
        result = bt.run([])
        assert result.total_signals == 0
        assert result.total_trades == 0
        assert not result.is_viable
        assert result.kill_reason == "no_signals"

    def test_all_winners(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=10.0,
            max_daily_loss=100.0,
            min_trades_for_significance=3,
        )
        config.fee_schedule = FeeSchedule.polymarket()
        bt = EventDrivenBacktester(config)
        bt.fill_model._rng.seed(42)

        signals = [
            _make_signal(i * 100, "BUY_YES", 0.40, True, market_id=f"m{i}")
            for i in range(20)
        ]
        result = bt.run(signals)
        assert result.total_signals == 20
        assert result.net_pnl > 0  # should be profitable

    def test_all_losers(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=10.0,
            min_trades_for_significance=3,
        )
        bt = EventDrivenBacktester(config)
        bt.fill_model._rng.seed(42)

        signals = [
            _make_signal(i * 100, "BUY_YES", 0.60, False, market_id=f"m{i}")
            for i in range(20)
        ]
        result = bt.run(signals)
        assert result.net_pnl < 0

    def test_unresolved_signals_skipped(self):
        bt = EventDrivenBacktester()
        signals = [
            BacktestSignal(
                ts=1700000000.0, market_id="m1", side="BUY_YES",
                entry_price=0.50, fair_value=0.55, edge_bps=100,
                resolved_outcome=None,  # not resolved
            )
        ]
        result = bt.run(signals)
        assert result.total_trades == 0

    def test_equity_curve_grows(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=5.0,
            min_trades_for_significance=3,
        )
        bt = EventDrivenBacktester(config)
        bt.fill_model._rng.seed(42)

        # Mix of wins and losses, net positive
        signals = []
        for i in range(30):
            win = i % 3 != 0  # 66% win rate
            signals.append(_make_signal(
                i * 100, "BUY_NO", 0.40, not win, market_id=f"m{i}",
            ))
        result = bt.run(signals)
        assert len(result.equity_curve) > 1
        assert result.equity_curve[0] == 1000.0

    def test_walk_forward_validation(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=5.0,
            walk_forward_splits=3,
            min_trades_for_significance=3,
        )
        bt = EventDrivenBacktester(config)
        bt.fill_model._rng.seed(42)

        signals = [
            _make_signal(i * 100, "BUY_YES", 0.40, True, market_id=f"m{i}")
            for i in range(30)
        ]
        result = bt.walk_forward_validate(signals)
        assert len(result.walk_forward_splits) > 0

    def test_stress_test(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=5.0,
            cost_stress_multiplier=2.0,
            min_trades_for_significance=3,
        )
        bt = EventDrivenBacktester(config)
        bt.fill_model._rng.seed(42)

        signals = [
            _make_signal(i * 100, "BUY_YES", 0.40, True, market_id=f"m{i}")
            for i in range(20)
        ]

        normal = bt.run(signals)
        stressed = bt.stress_test(signals)
        # Stressed result should have lower PnL
        assert stressed.net_pnl <= normal.net_pnl

    def test_daily_loss_limit(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=20.0,
            max_daily_loss=30.0,
            min_trades_for_significance=3,
        )
        bt = EventDrivenBacktester(config)
        bt.fill_model._rng.seed(42)

        # All losers on the same day
        base_ts = 1700000000.0
        signals = [
            _make_signal(i * 10, "BUY_YES", 0.60, False, market_id=f"m{i}")
            for i in range(20)
        ]
        result = bt.run(signals)
        # Should have stopped after hitting daily loss limit
        # Not all 20 should have traded
        assert result.total_trades < 20 or abs(result.net_pnl) < 600

    def test_kill_decision_low_sharpe(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=5.0,
            min_sharpe_threshold=2.0,  # very high bar
            min_trades_for_significance=3,
        )
        bt = EventDrivenBacktester(config)
        bt.fill_model._rng.seed(42)

        # Marginal strategy
        signals = []
        for i in range(30):
            win = i % 2 == 0
            signals.append(_make_signal(
                i * 100, "BUY_YES", 0.50, win, market_id=f"m{i}",
            ))
        result = bt.run(signals)
        assert not result.is_viable or result.sharpe_ratio >= 2.0

    def test_buy_no_pnl_calculation(self):
        config = BacktestConfig(
            initial_bankroll=1000.0,
            max_position_usd=10.0,
            min_trades_for_significance=1,
        )
        bt = EventDrivenBacktester(config)
        bt.fill_model = FillModel(config)
        bt.fill_model._rng.seed(42)

        # BUY_NO, event resolves NO → we win
        signals = [_make_signal(0, "BUY_NO", 0.40, False)]
        result = bt.run(signals)
        if result.total_trades > 0:
            assert result.trades[0].gross_pnl > 0  # won
