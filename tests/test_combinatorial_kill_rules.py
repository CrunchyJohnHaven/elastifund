import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.kill_rules import KillReason, run_combinatorial_promotion_battery


class TestCombinatorialKillRules(unittest.TestCase):
    def test_promotion_battery_passes_with_strong_shadow_metrics(self) -> None:
        passed, results = run_combinatorial_promotion_battery(
            signal_count=25,
            capture_rate=0.61,
            false_positive_rate=0.02,
            consecutive_rollbacks=1,
            minimum_signals=20,
            minimum_capture_rate=0.50,
            maximum_false_positive_rate=0.05,
            maximum_consecutive_rollbacks=3,
            require_classification=True,
            classification_accuracy=0.86,
            minimum_classification_accuracy=0.80,
        )

        self.assertTrue(passed)
        self.assertTrue(all(result.passed for result in results))

    def test_promotion_battery_fails_when_b1_accuracy_missing(self) -> None:
        passed, results = run_combinatorial_promotion_battery(
            signal_count=25,
            capture_rate=0.61,
            false_positive_rate=0.02,
            consecutive_rollbacks=1,
            require_classification=True,
            classification_accuracy=None,
        )

        self.assertFalse(passed)
        reasons = {result.reason for result in results if result.reason is not None}
        self.assertIn(KillReason.CLASSIFICATION_ACCURACY, reasons)


if __name__ == "__main__":
    unittest.main()
