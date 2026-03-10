import json
import tempfile
import unittest
from pathlib import Path

from bot.sum_violation_scanner import SumViolationScanner


class TestStructuralMeasurementCapture(unittest.TestCase):
    def _sample_event(self) -> list[dict]:
        return [
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

    def test_measurement_only_mode_writes_stable_capture_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_path = root / "capture.json"
            scanner = SumViolationScanner(
                db_path=root / "constraint.db",
                output_path=root / "sum_events.jsonl",
                report_path=root / "report.md",
                measurement_only=True,
                measurement_artifact_path=artifact_path,
                use_websocket=False,
                max_pages=1,
                max_events=10,
                min_event_markets=3,
                buy_threshold=0.97,
                execute_threshold=0.95,
            )
            scanner.fetch_active_events = self._sample_event  # type: ignore[assignment]
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

            self.assertGreaterEqual(stats.measurement_records, 1)
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "structural_measurement_capture.v1")
            self.assertTrue(payload["non_ordering_guardrail"]["measurement_only"])
            self.assertFalse(payload["non_ordering_guardrail"]["order_routing_reachable"])
            self.assertIn("measurements", payload)
            self.assertGreaterEqual(len(payload["measurements"]), 1)
            measurement = payload["measurements"][0]
            self.assertIn("construction", measurement)
            self.assertIn("quote", measurement)
            self.assertIn("fill_proxy_inputs", measurement)
            self.assertGreaterEqual(len(measurement["fill_proxy_inputs"]), 1)

    def test_measurement_only_guardrail_rejects_order_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "measurement_only mode forbids order routing"):
                SumViolationScanner(
                    db_path=root / "constraint.db",
                    output_path=root / "sum_events.jsonl",
                    report_path=root / "report.md",
                    measurement_only=True,
                    enable_order_routing=True,
                    use_websocket=False,
                )

    def test_measurement_capture_tracks_state_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_path = root / "capture.json"
            scanner = SumViolationScanner(
                db_path=root / "constraint.db",
                output_path=root / "sum_events.jsonl",
                report_path=root / "report.md",
                measurement_only=True,
                measurement_artifact_path=artifact_path,
                use_websocket=False,
                max_pages=1,
                max_events=10,
                min_event_markets=3,
                buy_threshold=0.97,
                execute_threshold=0.95,
            )
            scanner.fetch_active_events = self._sample_event  # type: ignore[assignment]

            # First cycle has one missing quote leg: blocked state.
            scanner._fetch_quotes_for_events = lambda _: (  # type: ignore[assignment]
                {
                    "m-a": (0.29, 0.30),
                    "m-b": (0.31, 0.32),
                },
                set(),
            )
            scanner.scan_once()

            # Second cycle has all legs quoted: executable state.
            scanner._fetch_quotes_for_events = lambda _: (  # type: ignore[assignment]
                {
                    "m-a": (0.29, 0.30),
                    "m-b": (0.31, 0.32),
                    "m-c": (0.30, 0.31),
                },
                set(),
            )
            try:
                scanner.scan_once()
            finally:
                scanner.close()

            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            transitions = payload.get("state_transitions", [])
            self.assertTrue(
                any(
                    row.get("event_id") == "evt-1"
                    and row.get("from_state") == "blocked"
                    and row.get("to_state") == "executable"
                    for row in transitions
                )
            )


if __name__ == "__main__":
    unittest.main()
