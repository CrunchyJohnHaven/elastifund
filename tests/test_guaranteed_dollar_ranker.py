import time
import unittest

from infra.clob_ws import BestBidAskStore
from signals.sum_violation.guaranteed_dollar import GuaranteedDollarConfig, GuaranteedDollarRanker
from strategies.a6_sum_violation import EventWatch, OutcomeLeg


class TestGuaranteedDollarRanker(unittest.TestCase):
    def _watch(self) -> EventWatch:
        legs = (
            OutcomeLeg("m1", "Who wins?", "Alice", "yes-a", "no-a", 0.01, 1.0, True, True),
            OutcomeLeg("m2", "Who wins?", "Bob", "yes-b", "no-b", 0.01, 1.0, True, True),
            OutcomeLeg("m3", "Who wins?", "Carol", "yes-c", "no-c", 0.01, 1.0, True, True),
        )
        return EventWatch(event_id="evt-1", title="Who wins?", neg_risk=True, is_augmented=False, legs=legs, raw_event={})

    def test_prefers_two_leg_path_when_no_is_cheaper_than_rest_yes(self) -> None:
        now = time.time()
        store = BestBidAskStore()
        store.update("yes-a", best_bid=0.19, best_ask=0.20, updated_ts=now, best_ask_size=200.0)
        store.update("no-a", best_bid=0.57, best_ask=0.60, updated_ts=now, best_ask_size=200.0)
        store.update("yes-b", best_bid=0.34, best_ask=0.35, updated_ts=now, best_ask_size=200.0)
        store.update("no-b", best_bid=0.64, best_ask=0.66, updated_ts=now, best_ask_size=200.0)
        store.update("yes-c", best_bid=0.35, best_ask=0.36, updated_ts=now, best_ask_size=200.0)
        store.update("no-c", best_bid=0.63, best_ask=0.65, updated_ts=now, best_ask_size=200.0)

        plan = GuaranteedDollarRanker(
            GuaranteedDollarConfig(
                detect_threshold=0.95,
                leg_size_usd=5.0,
                require_size_support=True,
            )
        ).evaluate_event(self._watch(), store, now_ts=now)

        self.assertIsNotNone(plan.best_construction)
        assert plan.best_construction is not None
        self.assertEqual(plan.best_construction.construction_type, "neg_risk_conversion")
        self.assertEqual(plan.best_construction.leg_count, 2)
        self.assertAlmostEqual(plan.best_construction.top_of_book_cost, 0.80, places=6)
        self.assertTrue(plan.best_construction.readiness.ready)

    def test_falls_back_to_full_basket_when_no_quotes_missing(self) -> None:
        now = time.time()
        store = BestBidAskStore()
        store.update("yes-a", best_bid=0.29, best_ask=0.30, updated_ts=now)
        store.update("yes-b", best_bid=0.30, best_ask=0.31, updated_ts=now)
        store.update("yes-c", best_bid=0.31, best_ask=0.32, updated_ts=now)

        plan = GuaranteedDollarRanker(GuaranteedDollarConfig(detect_threshold=0.95)).evaluate_event(
            self._watch(),
            store,
            now_ts=now,
        )

        self.assertIsNotNone(plan.best_construction)
        assert plan.best_construction is not None
        self.assertEqual(plan.best_construction.construction_type, "full_event_basket")
        self.assertAlmostEqual(plan.best_construction.top_of_book_cost, 0.93, places=6)

    def test_marks_size_unverified_when_required(self) -> None:
        now = time.time()
        store = BestBidAskStore()
        store.update("yes-a", best_bid=0.19, best_ask=0.20, updated_ts=now)
        store.update("no-a", best_bid=0.57, best_ask=0.60, updated_ts=now)
        store.update("yes-b", best_bid=0.34, best_ask=0.35, updated_ts=now)
        store.update("no-b", best_bid=0.64, best_ask=0.66, updated_ts=now)
        store.update("yes-c", best_bid=0.35, best_ask=0.36, updated_ts=now)
        store.update("no-c", best_bid=0.63, best_ask=0.65, updated_ts=now)

        plan = GuaranteedDollarRanker(
            GuaranteedDollarConfig(
                detect_threshold=0.95,
                require_size_support=True,
            )
        ).evaluate_event(self._watch(), store, now_ts=now)

        self.assertIsNotNone(plan.best_construction)
        assert plan.best_construction is not None
        self.assertFalse(plan.best_construction.readiness.ready)
        self.assertIn("top_of_book_size_insufficient_or_unverified", plan.best_construction.readiness.reasons)


if __name__ == "__main__":
    unittest.main()
