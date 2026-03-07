import tempfile
import unittest
from pathlib import Path

from src.backtest import Backtester
from src.config import BacktestConfig
from src.shadow_tracker import SignalShadowTracker
from src.strategies.base import Signal


class TestShadowTracker(unittest.TestCase):
    def test_record_resolve_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shadow.db"
            tracker = SignalShadowTracker(db_path)
            backtester = Backtester(BacktestConfig())

            signals = [
                Signal(
                    strategy="S",
                    condition_id="c1",
                    timestamp_ts=1,
                    side="YES",
                    entry_price=0.4,
                    confidence=0.7,
                    edge_estimate=0.1,
                    metadata={"x": 1},
                ),
                Signal(
                    strategy="S",
                    condition_id="c2",
                    timestamp_ts=2,
                    side="NO",
                    entry_price=0.45,
                    confidence=0.65,
                    edge_estimate=0.08,
                    metadata={"x": 2},
                ),
            ]

            inserted = tracker.record_signals("flow_variant", "v1", "Variant 1", signals)
            self.assertEqual(inserted, 2)

            resolved = tracker.resolve({"c1": "UP"}, backtester)
            self.assertEqual(resolved, 1)

            summary = tracker.summaries("flow_variant")
            self.assertIn("v1", summary)
            item = summary["v1"]
            self.assertEqual(item.total_signals, 2)
            self.assertEqual(item.resolved_signals, 1)
            self.assertEqual(item.open_signals, 1)


if __name__ == "__main__":
    unittest.main()
