import unittest

from src.backtest import Backtester
from src.config import BacktestConfig
from src.maker_fill_model import compute_queue_aware_maker_fill_probability
from src.strategies.base import Signal


class TestQueueAwareFillModel(unittest.TestCase):
    def test_missing_metadata_falls_back_to_base_fill_rate(self) -> None:
        cfg = BacktestConfig(queue_aware_maker_fill=True, maker_fill_rate=0.6)
        signal = Signal(
            strategy="S",
            condition_id="c1",
            timestamp_ts=1,
            side="YES",
            entry_price=0.5,
            confidence=0.7,
            edge_estimate=0.05,
            metadata={},
        )
        prob = compute_queue_aware_maker_fill_probability(signal, cfg)
        self.assertAlmostEqual(prob, 0.6, places=6)

    def test_microstructure_changes_fill_probability(self) -> None:
        cfg = BacktestConfig(queue_aware_maker_fill=True, maker_fill_rate=0.6)

        high_fill_signal = Signal(
            strategy="S",
            condition_id="c1",
            timestamp_ts=1,
            side="YES",
            entry_price=0.5,
            confidence=0.8,
            edge_estimate=0.02,
            metadata={
                "time_remaining_sec": 30,
                "trade_count_60s": 80,
                "trade_flow_imbalance": -0.6,
                "book_imbalance": -0.4,
            },
        )
        low_fill_signal = Signal(
            strategy="S",
            condition_id="c2",
            timestamp_ts=1,
            side="YES",
            entry_price=0.5,
            confidence=0.55,
            edge_estimate=0.18,
            metadata={
                "time_remaining_sec": 700,
                "trade_count_60s": 1,
                "trade_flow_imbalance": 0.7,
                "book_imbalance": 0.7,
            },
        )

        p_high = compute_queue_aware_maker_fill_probability(high_fill_signal, cfg)
        p_low = compute_queue_aware_maker_fill_probability(low_fill_signal, cfg)

        self.assertGreater(p_high, cfg.maker_fill_rate)
        self.assertLess(p_low, cfg.maker_fill_rate)
        self.assertGreater(p_high, p_low)
        self.assertGreaterEqual(p_low, cfg.maker_fill_floor)
        self.assertLessEqual(p_high, cfg.maker_fill_ceiling)

    def test_backtester_uses_queue_aware_fill_probability(self) -> None:
        static = Backtester(BacktestConfig(queue_aware_maker_fill=False, maker_fill_rate=0.6))
        dynamic = Backtester(BacktestConfig(queue_aware_maker_fill=True, maker_fill_rate=0.6))

        high_fill_signal = Signal(
            strategy="S",
            condition_id="c1",
            timestamp_ts=1,
            side="YES",
            entry_price=0.5,
            confidence=0.8,
            edge_estimate=0.02,
            metadata={
                "time_remaining_sec": 30,
                "trade_count_60s": 80,
                "trade_flow_imbalance": -0.6,
                "book_imbalance": -0.4,
            },
        )
        low_fill_signal = Signal(
            strategy="S",
            condition_id="c2",
            timestamp_ts=1,
            side="YES",
            entry_price=0.5,
            confidence=0.55,
            edge_estimate=0.18,
            metadata={
                "time_remaining_sec": 700,
                "trade_count_60s": 1,
                "trade_flow_imbalance": 0.7,
                "book_imbalance": 0.7,
            },
        )

        static_hi = static._trade_pnl(high_fill_signal, "UP")
        dynamic_hi = dynamic._trade_pnl(high_fill_signal, "UP")
        static_lo = static._trade_pnl(low_fill_signal, "UP")
        dynamic_lo = dynamic._trade_pnl(low_fill_signal, "UP")

        self.assertGreater(dynamic_hi.maker, static_hi.maker)
        self.assertLess(dynamic_lo.maker, static_lo.maker)

    def test_trade_through_model_uses_sell_trade_through_flow(self) -> None:
        backtester = Backtester(
            BacktestConfig(
                maker_fill_model="trade_through",
                queue_aware_maker_fill=True,
                maker_fill_rate=0.6,
                maker_fill_trade_through_buffer=0.001,
            )
        )
        backtester.set_trade_tape(
            [
                {
                    "condition_id": "c1",
                    "timestamp_ts": 11,
                    "side": "SELL",
                    "outcome": "Up",
                    "price": 0.499,
                    "size": 100.0,
                }
            ]
        )

        signal = Signal(
            strategy="S",
            condition_id="c1",
            timestamp_ts=10,
            side="YES",
            entry_price=0.5,
            confidence=0.7,
            edge_estimate=0.05,
            metadata={"time_remaining_sec": 60},
        )
        pnl = backtester._trade_pnl(signal, "UP")

        self.assertAlmostEqual(pnl.maker_fill_probability, 0.5, places=6)

    def test_trade_through_model_returns_zero_when_market_seen_but_no_qualifying_prints(self) -> None:
        backtester = Backtester(
            BacktestConfig(
                maker_fill_model="trade_through",
                queue_aware_maker_fill=True,
                maker_fill_rate=0.6,
            )
        )
        backtester.set_trade_tape(
            [
                {
                    "condition_id": "c1",
                    "timestamp_ts": 11,
                    "side": "BUY",
                    "outcome": "Up",
                    "price": 0.49,
                    "size": 500.0,
                }
            ]
        )

        signal = Signal(
            strategy="S",
            condition_id="c1",
            timestamp_ts=10,
            side="YES",
            entry_price=0.5,
            confidence=0.7,
            edge_estimate=0.05,
            metadata={"time_remaining_sec": 60},
        )
        pnl = backtester._trade_pnl(signal, "UP")

        self.assertEqual(pnl.maker_fill_probability, 0.0)


if __name__ == "__main__":
    unittest.main()
