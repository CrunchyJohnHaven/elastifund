import time
import unittest

from infra.clob_ws import BestBidAskStore
from strategies.a6_sum_violation import A6SignalEngine, A6WatchlistBuilder


class TestA6Strategy(unittest.TestCase):
    def test_watchlist_filters_augmented_other_outcomes(self) -> None:
        builder = A6WatchlistBuilder()
        events = [
            {
                "id": "evt-ok",
                "title": "Who wins?",
                "active": True,
                "closed": False,
                "negRisk": True,
                "enableOrderBook": True,
                "markets": [
                    {"id": "a", "question": "Who wins?", "groupItemTitle": "Alice", "clobTokenIds": '["ta","na"]', "acceptingOrders": True, "enableOrderBook": True},
                    {"id": "b", "question": "Who wins?", "groupItemTitle": "Bob", "clobTokenIds": '["tb","nb"]', "acceptingOrders": True, "enableOrderBook": True},
                    {"id": "c", "question": "Who wins?", "groupItemTitle": "Carol", "clobTokenIds": '["tc","nc"]', "acceptingOrders": True, "enableOrderBook": True},
                ],
            },
            {
                "id": "evt-bad",
                "title": "Who wins?",
                "active": True,
                "closed": False,
                "negRisk": True,
                "negRiskAugmented": True,
                "enableOrderBook": True,
                "markets": [
                    {"id": "x", "question": "Who wins?", "groupItemTitle": "Alice", "clobTokenIds": '["tx","nx"]', "acceptingOrders": True, "enableOrderBook": True},
                    {"id": "y", "question": "Who wins?", "groupItemTitle": "Bob", "clobTokenIds": '["ty","ny"]', "acceptingOrders": True, "enableOrderBook": True},
                    {"id": "z", "question": "Who wins?", "groupItemTitle": "Other", "clobTokenIds": '["tz","nz"]', "acceptingOrders": True, "enableOrderBook": True},
                ],
            },
        ]
        watches = builder.build_watchlist(events)
        self.assertEqual([watch.event_id for watch in watches], ["evt-ok", "evt-bad"])
        filtered = next(watch for watch in watches if watch.event_id == "evt-bad")
        self.assertEqual(tuple(leg.outcome for leg in filtered.legs), ("Alice", "Bob"))
        self.assertEqual(filtered.excluded_outcomes, ("Other",))

    def test_signal_engine_marks_execute_ready_only_when_liquid(self) -> None:
        builder = A6WatchlistBuilder()
        event = {
            "id": "evt-1",
            "title": "Who wins?",
            "active": True,
            "closed": False,
            "negRisk": True,
            "enableOrderBook": True,
            "markets": [
                {"id": "a", "question": "Who wins?", "groupItemTitle": "Alice", "clobTokenIds": '["ta","na"]', "acceptingOrders": True, "enableOrderBook": True},
                {"id": "b", "question": "Who wins?", "groupItemTitle": "Bob", "clobTokenIds": '["tb","nb"]', "acceptingOrders": True, "enableOrderBook": True},
                {"id": "c", "question": "Who wins?", "groupItemTitle": "Carol", "clobTokenIds": '["tc","nc"]', "acceptingOrders": True, "enableOrderBook": True},
            ],
        }
        watch = builder.build_watchlist([event])[0]
        store = BestBidAskStore()
        now = time.time()
        store.update("ta", best_bid=0.29, best_ask=0.30, updated_ts=now)
        store.update("tb", best_bid=0.31, best_ask=0.32, updated_ts=now)
        store.update("tc", best_bid=0.30, best_ask=0.31, updated_ts=now)

        opp = A6SignalEngine().evaluate_event(watch, store, now_ts=now)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertTrue(opp.execute_ready)
        self.assertEqual(opp.a6_mode, "neg_risk_sum")
        self.assertEqual(opp.settlement_path, "hold_to_resolution")
        self.assertAlmostEqual(opp.maker_sum_bid, 0.90)


if __name__ == "__main__":
    unittest.main()
