import unittest

from bot.b1_executor import B1Executor, B1ExecutorConfig, BasketState
from bot.b1_monitor import B1LegQuote, B1Opportunity


class TestB1ExecutorStateMachine(unittest.TestCase):
    def _mk_opportunity(self, *, updated_ts: int = 100) -> B1Opportunity:
        return B1Opportunity(
            opportunity_id=f"opp-{updated_ts}",
            edge_id="edge-1",
            relation_type="A_implies_B",
            basket_action="buy_no_a_buy_yes_b",
            market_ids=("a", "b"),
            legs=(
                B1LegQuote(
                    leg_id="a:NO",
                    market_id="a",
                    side="NO",
                    best_bid=0.29,
                    best_ask=0.30,
                    updated_ts=updated_ts,
                ),
                B1LegQuote(
                    leg_id="b:YES",
                    market_id="b",
                    side="YES",
                    best_bid=0.60,
                    best_ask=0.61,
                    updated_ts=updated_ts,
                ),
            ),
            trigger_edge=0.09,
            theoretical_edge=0.09,
            payoff_floor=1.0,
            relation_confidence=0.93,
            resolution_gate_status="passed",
            resolution_gate_reasons=("source_match", "cutoff_match"),
            quote_age_seconds=0,
            detected_at_ts=updated_ts,
            details={},
        )

    def test_partial_to_hedged_to_complete(self) -> None:
        executor = B1Executor(B1ExecutorConfig(fill_timeout_seconds=10))
        basket = executor.submit(self._mk_opportunity(updated_ts=100), now_ts=100)
        assert basket is not None
        self.assertEqual(basket.state, BasketState.QUOTING)

        target = basket.target_qty
        executor.apply_fill(basket.basket_id, "a:NO", filled_qty=target, avg_price=0.29, now_ts=101)
        self.assertEqual(basket.state, BasketState.PARTIAL)

        executor.apply_fill(basket.basket_id, "b:YES", filled_qty=target / 2.0, avg_price=0.60, now_ts=105)
        self.assertEqual(basket.state, BasketState.HEDGED)

        executor.apply_fill(
            basket.basket_id,
            "b:YES",
            filled_qty=target / 2.0,
            avg_price=0.60,
            now_ts=108,
        )
        self.assertEqual(basket.state, BasketState.COMPLETE)
        self.assertGreater(basket.realized_pnl, 0.0)
        self.assertGreater(basket.capture_rate, 0.0)
        self.assertGreater(basket.one_sided_exposure_seconds, 0.0)
        self.assertIn((108, BasketState.COMPLETE.value, "all_legs_filled"), basket.transition_log)

    def test_one_leg_fill_then_collapse_rolls_back(self) -> None:
        executor = B1Executor(B1ExecutorConfig(fill_timeout_seconds=10))
        basket = executor.submit(self._mk_opportunity(updated_ts=100), now_ts=100)
        assert basket is not None

        executor.apply_fill(basket.basket_id, "a:NO", filled_qty=basket.target_qty, avg_price=0.30, now_ts=101)
        basket = executor.sync_opportunity(basket.basket_id, None, now_ts=109)

        self.assertEqual(basket.state, BasketState.ROLLED_BACK)
        self.assertGreater(basket.rollback_loss, 0.0)
        self.assertLess(basket.realized_pnl, 0.0)
        self.assertGreater(basket.one_sided_exposure_seconds, 0.0)
        self.assertTrue(any("violation_collapsed" in row for row in basket.false_positive_trace))

    def test_timeout_reprices_once_per_leg_then_expires(self) -> None:
        executor = B1Executor(B1ExecutorConfig(fill_timeout_seconds=10, max_cancel_replace=1))
        basket = executor.submit(self._mk_opportunity(updated_ts=100), now_ts=100)
        assert basket is not None

        refreshed = self._mk_opportunity(updated_ts=111)
        basket = executor.sync_opportunity(basket.basket_id, refreshed, now_ts=111)
        self.assertEqual(basket.state, BasketState.QUOTING)
        self.assertEqual(basket.cancel_replace_count, 2)
        self.assertEqual([leg.reprices for leg in basket.legs], [1, 1])

        refreshed_again = self._mk_opportunity(updated_ts=122)
        basket = executor.sync_opportunity(basket.basket_id, refreshed_again, now_ts=122)
        self.assertEqual(basket.state, BasketState.EXPIRED)
        self.assertTrue(any("fill_timeout" in row for row in basket.false_positive_trace))


if __name__ == "__main__":
    unittest.main()
