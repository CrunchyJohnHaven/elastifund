import unittest

from src.backtest import Backtester
from src.config import BacktestConfig
from src.strategies.base import Signal


class TestBacktest(unittest.TestCase):
    def test_backtester_evaluate(self) -> None:
        backtester = Backtester(BacktestConfig())
        signals = [
            Signal(
                strategy="Test",
                condition_id="c1",
                timestamp_ts=1,
                side="YES",
                entry_price=0.4,
                confidence=0.7,
                edge_estimate=0.1,
            ),
            Signal(
                strategy="Test",
                condition_id="c2",
                timestamp_ts=2,
                side="NO",
                entry_price=0.45,
                confidence=0.65,
                edge_estimate=0.08,
            ),
        ]
        resolutions = {"c1": "UP", "c2": "DOWN"}
        result = backtester.evaluate("Test", signals, resolutions)
        self.assertEqual(result.signals, 2)
        self.assertEqual(result.wins, 2)
        self.assertGreater(result.win_rate, 0.5)


if __name__ == "__main__":
    unittest.main()
