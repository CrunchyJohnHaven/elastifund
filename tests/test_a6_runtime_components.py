import json
import tempfile
import unittest
from pathlib import Path

from infra.clob_ws import BestBidAskStore
from signals.sum_violation.sum_discovery import A6PriceSnapshotter
from signals.sum_violation.sum_executor import A6ExecutionPlanner
from signals.sum_violation.sum_state import A6QuarantineCache
from strategies.a6_sum_violation import EventWatch, OutcomeLeg


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, *, buy_payload=None, sell_payload=None, book_payloads=None):
        self.buy_payload = buy_payload or {}
        self.sell_payload = sell_payload or {}
        self.book_payloads = dict(book_payloads or {})
        self.post_calls = []
        self.get_calls = []

    def post(self, url, json=None, timeout=None):
        self.post_calls.append((url, json, timeout))
        side = json[0]["side"] if json else ""
        payload = self.sell_payload if side == "SELL" else self.buy_payload
        return _FakeResponse(payload)

    def get(self, url, params=None, timeout=None):
        token_id = params["token_id"]
        self.get_calls.append((url, token_id, timeout))
        payload, status_code = self.book_payloads[token_id]
        return _FakeResponse(payload, status_code=status_code)


class TestA6RuntimeComponents(unittest.TestCase):
    def _watch(self) -> EventWatch:
        legs = (
            OutcomeLeg("m1", "Who wins? Alice", "Alice", "yes-1", "no-1", 0.01, 1.0, True, True),
            OutcomeLeg("m2", "Who wins? Bob", "Bob", "yes-2", "no-2", 0.01, 1.0, True, True),
            OutcomeLeg("m3", "Who wins? Carol", "Carol", "yes-3", "no-3", 0.01, 1.0, True, True),
        )
        return EventWatch(event_id="evt-1", title="Race", neg_risk=True, is_augmented=False, legs=legs, raw_event={})

    def test_quarantine_backoff_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = A6QuarantineCache(Path(tmp) / "quarantine.json")
            first = cache.mark_failure("tok-1", reason="book_404", status_code=404, now_ts=100.0)
            second = cache.mark_failure("tok-1", reason="book_404", status_code=404, now_ts=200.0)

            self.assertEqual(first.failures, 1)
            self.assertEqual(second.failures, 2)
            self.assertTrue(cache.is_quarantined("tok-1", now_ts=201.0))
            self.assertFalse(cache.is_quarantined("tok-1", now_ts=4000.0))

            cache.mark_success("tok-1")
            self.assertFalse(cache.is_quarantined("tok-1", now_ts=201.0))

    def test_price_snapshotter_uses_batch_prices_then_book_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quarantine = A6QuarantineCache(Path(tmp) / "quarantine.json")
            session = _FakeSession(
                buy_payload={"yes-1": {"BUY": 0.29}, "yes-2": {"BUY": 0.30}},
                sell_payload={"yes-1": {"SELL": 0.31}, "yes-2": {"SELL": 0.32}},
                book_payloads={
                    "yes-3": ({"bids": [{"price": 0.11}], "asks": [{"price": 0.13}]}, 200),
                },
            )
            store = BestBidAskStore()
            snapshotter = A6PriceSnapshotter(session=session, quarantine=quarantine)

            updated = snapshotter.refresh_store([self._watch()], store)

            self.assertEqual(updated, 3)
            self.assertEqual(len(session.post_calls), 2)
            self.assertEqual(len(session.get_calls), 1)
            self.assertAlmostEqual(store.get("yes-3").best_ask, 0.13)
            self.assertFalse(quarantine.is_quarantined("yes-3"))

    def test_price_snapshotter_quarantines_404_book_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            quarantine = A6QuarantineCache(Path(tmp) / "quarantine.json")
            session = _FakeSession(
                buy_payload={},
                sell_payload={},
                book_payloads={"yes-1": ({}, 404), "yes-2": ({}, 404), "yes-3": ({}, 404)},
            )
            snapshotter = A6PriceSnapshotter(session=session, quarantine=quarantine)
            store = BestBidAskStore()

            updated = snapshotter.refresh_store([self._watch()], store)

            self.assertEqual(updated, 0)
            self.assertTrue(quarantine.is_quarantined("yes-1"))
            self.assertEqual(len(quarantine.snapshot()), 3)

    def test_execution_planner_builds_linked_attempt(self) -> None:
        watch = self._watch()
        store = BestBidAskStore()
        store.update("yes-1", best_bid=0.29, best_ask=0.31, updated_ts=1)
        store.update("yes-2", best_bid=0.30, best_ask=0.32, updated_ts=1)
        store.update("yes-3", best_bid=0.11, best_ask=0.13, updated_ts=1)

        from strategies.a6_sum_violation import A6SignalEngine

        opportunity = A6SignalEngine(detect_threshold=0.95, execute_threshold=0.95).evaluate_event(watch, store, now_ts=1.5)
        self.assertIsNotNone(opportunity)

        planner = A6ExecutionPlanner(leg_usd_cap=5.0)
        attempt = planner.build_attempt(watch, opportunity, now_ts=10.0)
        payload = planner.to_state_payload(attempt)

        self.assertEqual(attempt.strategy_id, "A6")
        self.assertEqual(len(attempt.legs), 3)
        self.assertIn("maker_sum_bid", attempt.metadata)
        self.assertEqual(payload["group_id"], "evt-1")
        self.assertEqual(payload["state"], "ARMED")


if __name__ == "__main__":
    unittest.main()
