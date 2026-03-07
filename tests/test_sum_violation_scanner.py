import json
import tempfile
import unittest
from pathlib import Path

from bot.sum_violation_scanner import SumViolationScanner, parse_clob_token_ids


class TestSumViolationScanner(unittest.TestCase):
    def test_parse_clob_token_ids_handles_json_and_csv(self) -> None:
        yes_id, no_id = parse_clob_token_ids('["1", "2"]')
        self.assertEqual((yes_id, no_id), ("1", "2"))

        yes_id, no_id = parse_clob_token_ids("3,4")
        self.assertEqual((yes_id, no_id), ("3", "4"))

    def test_scan_once_detects_sum_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scanner = SumViolationScanner(
                db_path=root / "constraint.db",
                output_path=root / "sum_events.jsonl",
                report_path=root / "report.md",
                max_pages=1,
                max_events=10,
                min_event_markets=3,
                buy_threshold=0.97,
                execute_threshold=0.95,
                use_websocket=False,
            )

            events = [
                {
                    "id": "evt-1",
                    "title": "Who wins?",
                    "active": True,
                    "closed": False,
                    "negRisk": True,
                    "enableOrderBook": True,
                    "resolutionSource": "Associated Press",
                    "endDate": "2026-11-03T23:59:00Z",
                    "rules": "Resolves using Associated Press.",
                    "markets": [
                        {
                            "id": "m-a",
                            "question": "Who wins?",
                            "groupItemTitle": "Alice",
                            "clobTokenIds": '["t-a-yes","t-a-no"]',
                            "bestBid": 0.29,
                            "bestAsk": 0.30,
                            "acceptingOrders": True,
                            "enableOrderBook": True,
                        },
                        {
                            "id": "m-b",
                            "question": "Who wins?",
                            "groupItemTitle": "Bob",
                            "clobTokenIds": '["t-b-yes","t-b-no"]',
                            "bestBid": 0.31,
                            "bestAsk": 0.32,
                            "acceptingOrders": True,
                            "enableOrderBook": True,
                        },
                        {
                            "id": "m-c",
                            "question": "Who wins?",
                            "groupItemTitle": "Carol",
                            "clobTokenIds": '["t-c-yes","t-c-no"]',
                            "bestBid": 0.30,
                            "bestAsk": 0.31,
                            "acceptingOrders": True,
                            "enableOrderBook": True,
                        },
                    ],
                }
            ]

            scanner.fetch_active_events = lambda: events  # type: ignore[assignment]
            scanner._fetch_quotes_for_events = lambda _: (  # type: ignore[assignment]
                {
                    "m-a": (0.29, 0.30),
                    "m-b": (0.31, 0.32),
                    "m-c": (0.30, 0.31),
                },
                set(),
            )

            try:
                stats = scanner.scan_once()
            finally:
                scanner.close()

            self.assertEqual(stats.violations_found, 1)
            self.assertTrue((root / "sum_events.jsonl").exists())
            self.assertTrue((root / "report.md").exists())

            lines = (root / "sum_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
            payload = json.loads(lines[0])
            self.assertEqual(payload["relation_type"], "same_event_sum")
            self.assertEqual(payload["action"], "buy_yes_basket")
            self.assertAlmostEqual(payload["details"]["sum_yes_ask"], 0.93, places=6)
            self.assertAlmostEqual(payload["details"]["maker_sum_bid"], 0.90, places=6)
            self.assertTrue(payload["details"]["execute_ready"])

    def test_scan_once_blocks_event_when_orderbook_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scanner = SumViolationScanner(
                db_path=root / "constraint.db",
                output_path=root / "sum_events.jsonl",
                report_path=root / "report.md",
                max_pages=1,
                max_events=10,
                min_event_markets=3,
                use_websocket=False,
            )
            events = [
                {
                    "id": "evt-404",
                    "title": "Who wins?",
                    "active": True,
                    "closed": False,
                    "negRisk": True,
                    "enableOrderBook": True,
                    "resolutionSource": "Associated Press",
                    "endDate": "2026-11-03T23:59:00Z",
                    "rules": "Resolves using Associated Press.",
                    "markets": [
                        {"id": "m-a", "question": "Who wins?", "groupItemTitle": "Alice", "clobTokenIds": '["t-a-yes","t-a-no"]', "bestAsk": 0.30, "acceptingOrders": True, "enableOrderBook": True},
                        {"id": "m-b", "question": "Who wins?", "groupItemTitle": "Bob", "clobTokenIds": '["t-b-yes","t-b-no"]', "bestAsk": 0.31, "acceptingOrders": True, "enableOrderBook": True},
                        {"id": "m-c", "question": "Who wins?", "groupItemTitle": "Carol", "clobTokenIds": '["t-c-yes","t-c-no"]', "bestAsk": 0.32, "acceptingOrders": True, "enableOrderBook": True},
                    ],
                }
            ]
            scanner.fetch_active_events = lambda: events  # type: ignore[assignment]
            scanner._fetch_quotes_for_events = lambda _: ({"m-a": (0.29, 0.30)}, {"evt-404"})  # type: ignore[assignment]

            try:
                stats = scanner.scan_once()
            finally:
                scanner.close()

            self.assertEqual(stats.events_blocked_no_orderbook, 1)
            self.assertEqual(stats.violations_found, 0)


if __name__ == "__main__":
    unittest.main()
