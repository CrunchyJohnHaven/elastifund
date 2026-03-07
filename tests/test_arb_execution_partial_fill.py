import unittest

from bot.constraint_arb_engine import ExecutionLeg, ExecutionManager, ExecutionPlan, LegFill


class TestArbExecutionPartialFill(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ExecutionManager(rollback_haircut=0.2, reprice_penalty=0.05)
        self.plan = ExecutionPlan(
            violation_id="v-1",
            event_id="evt-1",
            legs=(
                ExecutionLeg("l1", "m1", "BUY", 1.0, 0.30),
                ExecutionLeg("l2", "m2", "BUY", 1.0, 0.30),
                ExecutionLeg("l3", "m3", "BUY", 1.0, 0.30),
            ),
            payoff_if_complete=1.0,
        )

    def test_first_leg_fills_second_misses(self) -> None:
        fills = {
            "l1": LegFill(filled_qty=1.0, avg_price=0.30, status="filled", ts=100),
            "l2": LegFill(filled_qty=0.0, avg_price=0.30, status="missed", ts=105),
        }
        result = self.manager.simulate(self.plan, fills)

        self.assertFalse(result.complete)
        self.assertGreater(result.rollback_loss, 0.0)
        self.assertLess(result.realized_pnl, 0.0)
        self.assertGreater(result.theoretical_pnl, 0.0)

    def test_reprice_away_penalized_more_than_plain_miss(self) -> None:
        plain = self.manager.simulate(
            self.plan,
            {
                "l1": LegFill(filled_qty=1.0, avg_price=0.30, status="filled", ts=100),
                "l2": LegFill(filled_qty=1.0, avg_price=0.30, status="filled", ts=101),
                "l3": LegFill(filled_qty=0.0, avg_price=0.30, status="missed", ts=102),
            },
        )

        repriced = self.manager.simulate(
            self.plan,
            {
                "l1": LegFill(filled_qty=1.0, avg_price=0.30, status="filled", ts=100),
                "l2": LegFill(filled_qty=1.0, avg_price=0.30, status="filled", ts=101),
                "l3": LegFill(filled_qty=0.0, avg_price=0.33, status="repriced", ts=102),
            },
        )

        self.assertFalse(repriced.complete)
        self.assertGreater(repriced.rollback_loss, plain.rollback_loss)

    def test_partial_largest_leg_and_cancel_latency_metrics(self) -> None:
        plan = ExecutionPlan(
            violation_id="v-2",
            event_id="evt-2",
            legs=(
                ExecutionLeg("l1", "m1", "BUY", 4.0, 0.20),
                ExecutionLeg("l2", "m2", "BUY", 1.0, 0.20),
                ExecutionLeg("l3", "m3", "BUY", 1.0, 0.20),
            ),
            payoff_if_complete=1.0,
        )
        fills = {
            "l1": LegFill(filled_qty=2.0, avg_price=0.20, status="partial", ts=100),
            "l2": LegFill(filled_qty=1.0, avg_price=0.20, status="filled", ts=160),
        }
        result = self.manager.simulate(plan, fills)

        self.assertFalse(result.complete)
        self.assertGreater(result.time_in_partial_basket, 0.0)
        self.assertGreater(result.peak_capital_tied, 0.0)

    def test_market_halt_before_completion(self) -> None:
        fills = {
            "l1": LegFill(filled_qty=1.0, avg_price=0.30, status="filled", ts=100),
            "l2": LegFill(filled_qty=0.0, avg_price=0.30, status="halted", ts=101),
        }
        result = self.manager.simulate(self.plan, fills)

        self.assertFalse(result.complete)
        self.assertGreater(result.rollback_loss, 0.0)


if __name__ == "__main__":
    unittest.main()
