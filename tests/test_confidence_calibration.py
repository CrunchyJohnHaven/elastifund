import unittest

from src.backtest import Backtester
from src.confidence_calibration import _isotonic_non_decreasing, sequential_bayes_isotonic
from src.config import BacktestConfig
from src.strategies.base import Signal


class TestConfidenceCalibration(unittest.TestCase):
    def test_isotonic_smoothing_enforces_monotonicity(self) -> None:
        values = [0.10, 0.62, 0.41, 0.77, 0.73]
        smoothed = _isotonic_non_decreasing(values, [1, 1, 1, 1, 1])

        self.assertEqual(len(smoothed), len(values))
        for i in range(1, len(smoothed)):
            self.assertLessEqual(smoothed[i - 1], smoothed[i])

    def test_sequential_calibration_uses_only_past_outcomes(self) -> None:
        raw = [0.90, 0.90, 0.90]
        outcomes = [False, False, False]
        calibrated, summary = sequential_bayes_isotonic(
            raw,
            outcomes,
            bins=5,
            prior_strength=4.0,
            min_history=0,
            floor=0.01,
            ceiling=0.99,
        )

        self.assertTrue(summary.applied)
        self.assertEqual(summary.method, "sequential_bayes_isotonic")
        self.assertGreater(calibrated[0], calibrated[1])
        self.assertGreaterEqual(calibrated[1], calibrated[2])

    def test_backtester_applies_confidence_calibration(self) -> None:
        signals: list[Signal] = []
        resolutions: dict[str, str] = {}
        for i in range(30):
            cid = f"c{i}"
            signals.append(
                Signal(
                    strategy="CalTest",
                    condition_id=cid,
                    timestamp_ts=1_700_000_000 + i,
                    side="YES",
                    entry_price=0.55,
                    confidence=0.90,
                    edge_estimate=0.05,
                )
            )
            resolutions[cid] = "UP" if i % 2 == 0 else "DOWN"

        plain = Backtester(
            BacktestConfig(
                confidence_calibration_enabled=False,
                queue_aware_maker_fill=False,
                maker_fill_rate=0.6,
            )
        )
        calibrated = Backtester(
            BacktestConfig(
                confidence_calibration_enabled=True,
                confidence_calibration_min_history=0,
                confidence_calibration_prior_strength=4.0,
                queue_aware_maker_fill=False,
                maker_fill_rate=0.6,
            )
        )

        plain_result = plain.evaluate("CalTest", signals, resolutions)
        calibrated_result = calibrated.evaluate("CalTest", signals, resolutions)

        self.assertLess(calibrated_result.calibration_error, plain_result.calibration_error)
        self.assertIn("sequential_bayes_isotonic", " ".join(calibrated_result.notes))


if __name__ == "__main__":
    unittest.main()
