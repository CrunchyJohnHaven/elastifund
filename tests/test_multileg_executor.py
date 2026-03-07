import unittest

from execution.multileg_executor import LegFillUpdate, LegSpec, MultiLegExecutor, MultiLegState


class TestMultiLegExecutor(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = MultiLegExecutor()
        self.legs = [
            LegSpec("l1", "m1", "t1", "BUY", 0.30, 1.0),
            LegSpec("l2", "m2", "t2", "BUY", 0.31, 1.0),
            LegSpec("l3", "m3", "t3", "BUY", 0.29, 1.0),
        ]

    def test_partial_fill_rolls_back_after_ttl(self) -> None:
        attempt = self.executor.create_attempt(
            attempt_id="a1",
            strategy_id="A6",
            group_id="evt-1",
            leg_specs=self.legs,
            now_ts=100.0,
        )
        self.executor.mark_signalled(attempt, now_ts=100.0)
        self.executor.mark_orders_live(attempt, order_ids={"l1": "o1", "l2": "o2", "l3": "o3"}, now_ts=101.0)
        self.executor.apply_fill(attempt, LegFillUpdate("l1", 1.0, 0.30, 102.0))

        decision = self.executor.evaluate(attempt, now_ts=130.0)
        self.assertEqual(decision.next_state, MultiLegState.ROLLBACK)
        self.assertTrue(decision.should_cancel_open_orders)
        self.assertTrue(decision.should_start_unwind)

    def test_unhedged_timeout_freezes_attempt(self) -> None:
        attempt = self.executor.create_attempt(
            attempt_id="a2",
            strategy_id="B1",
            group_id="pair-1",
            leg_specs=self.legs[:2],
            now_ts=100.0,
        )
        self.executor.mark_signalled(attempt, now_ts=100.0)
        self.executor.mark_orders_live(attempt, order_ids={"l1": "o1", "l2": "o2"}, now_ts=101.0)
        self.executor.apply_fill(attempt, LegFillUpdate("l1", 1.0, 0.30, 102.0))
        self.executor.evaluate(attempt, now_ts=130.0)

        decision = self.executor.evaluate(attempt, now_ts=500.0)
        self.assertEqual(decision.next_state, MultiLegState.FROZEN)
        self.assertTrue(decision.should_freeze_strategy)


if __name__ == "__main__":
    unittest.main()
