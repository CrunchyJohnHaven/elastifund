import tempfile
import unittest
from pathlib import Path

from bot.sum_violation_scanner import SumViolationScanner


class TestSumViolationScanner(unittest.TestCase):
    def _event(self, *, event_id: str, title: str, cumulative: bool = False, questions: list[str]) -> dict:
        markets = []
        for idx, question in enumerate(questions, start=1):
            markets.append(
                {
                    "id": f"{event_id}-m{idx}",
                    "question": question,
                    "enableOrderBook": True,
                    "clobTokenIds": '["yes-token","no-token"]',
                    "outcomePrices": "[0.30,0.70]",
                }
            )
        return {
            "id": event_id,
            "slug": event_id,
            "title": title,
            "category": "politics",
            "cumulativeMarkets": cumulative,
            "markets": markets,
        }

    def test_rejects_explicit_cumulative_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scanner = SumViolationScanner(
                db_path=Path(tmp) / "constraint.db",
                output_path=Path(tmp) / "sum.jsonl",
                report_path=Path(tmp) / "report.md",
            )
            event = self._event(
                event_id="evt-cum",
                title="BTC ladder",
                cumulative=True,
                questions=[
                    "Will BTC be above $90,000 by March 31, 2026?",
                    "Will BTC be above $95,000 by March 31, 2026?",
                    "Will BTC be above $100,000 by March 31, 2026?",
                ],
            )
            self.assertFalse(scanner._event_is_candidate(event))
            scanner.close()

    def test_rejects_threshold_ladder_even_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scanner = SumViolationScanner(
                db_path=Path(tmp) / "constraint.db",
                output_path=Path(tmp) / "sum.jsonl",
                report_path=Path(tmp) / "report.md",
            )
            event = self._event(
                event_id="evt-ladder",
                title="BTC ladder",
                questions=[
                    "Will BTC be above $90,000 by March 31, 2026?",
                    "Will BTC be above $95,000 by March 31, 2026?",
                    "Will BTC be above $100,000 by March 31, 2026?",
                ],
            )
            self.assertFalse(scanner._event_is_candidate(event))
            scanner.close()

    def test_flattens_valid_event_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scanner = SumViolationScanner(
                db_path=Path(tmp) / "constraint.db",
                output_path=Path(tmp) / "sum.jsonl",
                report_path=Path(tmp) / "report.md",
            )
            event = self._event(
                event_id="evt-valid",
                title="Who wins the race?",
                questions=[
                    "Who will win the race? Alice",
                    "Who will win the race? Bob",
                    "Who will win the race? Carol",
                ],
            )
            flattened = scanner._flatten_event_markets(event)
            self.assertEqual(len(flattened), 3)
            self.assertEqual(flattened[0]["event_id"], "evt-valid")
            self.assertEqual(flattened[0]["eventSlug"], "evt-valid")
            self.assertTrue(scanner._event_is_candidate(event))
            scanner.close()


if __name__ == "__main__":
    unittest.main()
