import unittest

from bot.a6_executor import A6BasketExecutor, A6BasketState, A6ExecutorConfig
from bot.a6_sum_scanner import (
    A6LegSnapshot,
    A6MarketSnapshot,
    A6Opportunity,
    A6OpportunityLeg,
)


class TestA6ExecutorStateMachine(unittest.TestCase):
    def _make_opportunity(self) -> A6Opportunity:
        legs = (
            A6OpportunityLeg(
                leg_id="alice:YES",
                market_id="alice",
                condition_id="alice",
                token_id="alice-yes",
                outcome_name="Alice",
                best_bid=0.29,
                best_ask=0.30,
                tick_size=0.01,
            ),
            A6OpportunityLeg(
                leg_id="bob:YES",
                market_id="bob",
                condition_id="bob",
                token_id="bob-yes",
                outcome_name="Bob",
                best_bid=0.30,
                best_ask=0.31,
                tick_size=0.01,
            ),
            A6OpportunityLeg(
                leg_id="carol:YES",
                market_id="carol",
                condition_id="carol",
                token_id="carol-yes",
                outcome_name="Carol",
                best_bid=0.31,
                best_ask=0.32,
                tick_size=0.01,
            ),
        )
        return A6Opportunity(
            signal_id="sig-1",
            basket_id="a6-sig-1",
            event_id="evt-1",
            signal_type="buy_yes_basket",
            executable=True,
            threshold=0.97,
            theoretical_edge=0.07,
            sum_yes_ask=0.93,
            sum_yes_bid=0.90,
            detected_at_ts=1_000,
            invalidation_reasons=tuple(),
            legs=legs,
        )

    def _make_snapshot(
        self,
        *,
        executable: bool,
        sum_yes_ask: float | None,
        bids: tuple[float, float, float],
        asks: tuple[float, float, float],
        detected_at_ts: int,
        invalidation_reasons: tuple[str, ...] = tuple(),
    ) -> A6MarketSnapshot:
        legs = (
            A6LegSnapshot(
                leg_id="alice:YES",
                market_id="alice",
                condition_id="alice",
                token_id="alice-yes",
                outcome_name="Alice",
                yes_bid=bids[0],
                yes_ask=asks[0],
                tick_size=0.01,
                updated_ts=detected_at_ts,
                fresh=True,
                executable=executable,
                invalidation_reasons=invalidation_reasons if not executable else tuple(),
            ),
            A6LegSnapshot(
                leg_id="bob:YES",
                market_id="bob",
                condition_id="bob",
                token_id="bob-yes",
                outcome_name="Bob",
                yes_bid=bids[1],
                yes_ask=asks[1],
                tick_size=0.01,
                updated_ts=detected_at_ts,
                fresh=True,
                executable=executable,
                invalidation_reasons=invalidation_reasons if not executable else tuple(),
            ),
            A6LegSnapshot(
                leg_id="carol:YES",
                market_id="carol",
                condition_id="carol",
                token_id="carol-yes",
                outcome_name="Carol",
                yes_bid=bids[2],
                yes_ask=asks[2],
                tick_size=0.01,
                updated_ts=detected_at_ts,
                fresh=True,
                executable=executable,
                invalidation_reasons=invalidation_reasons if not executable else tuple(),
            ),
        )
        sum_yes_bid = sum(bids) if executable else None
        return A6MarketSnapshot(
            event_id="evt-1",
            event_label="Who will win the race?",
            category="politics",
            resolution_key="evt-1-key",
            detected_at_ts=detected_at_ts,
            legs=legs,
            expected_legs=3,
            fresh_legs=3 if executable else 0,
            executable=executable,
            invalidation_reasons=invalidation_reasons,
            missing_leg_ids=tuple(),
            stale_leg_ids=tuple(),
            blocked_leg_ids=tuple(),
            sum_yes_ask=sum_yes_ask,
            sum_yes_bid=sum_yes_bid,
        )

    def test_complete_basket_transitions_to_merge_ready(self) -> None:
        executor = A6BasketExecutor(A6ExecutorConfig(fill_timeout_ms=3_000))
        start = executor.submit_opportunity(self._make_opportunity(), now_ts=1_000)
        qty = start.basket.target_quantity

        self.assertEqual(start.basket.state, A6BasketState.QUOTING)
        self.assertEqual([event.state for event in start.events], ["DETECTED", "QUOTING"])
        self.assertEqual(len(start.commands), 3)
        self.assertTrue(all(command.post_only for command in start.commands))
        self.assertTrue(all(command.signature_type == 1 for command in start.commands))

        first = executor.apply_fill("a6-sig-1", leg_id="alice:YES", filled_quantity=qty, avg_price=0.29, now_ts=1_200)
        self.assertEqual(first.basket.state, A6BasketState.PARTIAL)
        self.assertEqual(len(first.events), 1)
        self.assertEqual(first.events[0].state, "PARTIAL")

        executor.apply_fill("a6-sig-1", leg_id="bob:YES", filled_quantity=qty, avg_price=0.30, now_ts=1_600)
        final = executor.apply_fill("a6-sig-1", leg_id="carol:YES", filled_quantity=qty, avg_price=0.31, now_ts=2_200)

        self.assertEqual(final.basket.state, A6BasketState.MERGE_READY)
        self.assertEqual(final.events[0].state, "COMPLETE")
        self.assertEqual(final.events[1].event_type, "MERGE_READY")
        self.assertGreater(final.basket.realized_profit_usd, 0.0)
        self.assertGreater(final.basket.capture_rate or 0.0, 0.0)
        self.assertEqual(final.basket.time_to_fill_ms, 1_200)

    def test_no_fill_timeout_expires_basket(self) -> None:
        executor = A6BasketExecutor(A6ExecutorConfig(fill_timeout_ms=3_000))
        executor.submit_opportunity(self._make_opportunity(), now_ts=1_000)

        expired = executor.advance_time("a6-sig-1", now_ts=4_500)
        self.assertEqual(expired.basket.state, A6BasketState.EXPIRED)
        self.assertEqual(len(expired.commands), 3)
        self.assertTrue(all(command.action == "CANCEL" for command in expired.commands))
        self.assertEqual(expired.events[0].state, "EXPIRED")

    def test_partial_fill_then_edge_collapse_rolls_back(self) -> None:
        executor = A6BasketExecutor(A6ExecutorConfig(fill_timeout_ms=3_000))
        start = executor.submit_opportunity(self._make_opportunity(), now_ts=1_000)
        executor.apply_fill("a6-sig-1", leg_id="alice:YES", filled_quantity=start.basket.target_quantity, avg_price=0.29, now_ts=1_200)

        collapsed = executor.update_snapshot(
            "a6-sig-1",
            self._make_snapshot(
                executable=False,
                sum_yes_ask=None,
                bids=(0.24, 0.25, 0.26),
                asks=(0.25, 0.26, 0.27),
                detected_at_ts=1_500,
                invalidation_reasons=("stale_quote",),
            ),
            now_ts=1_500,
        )

        self.assertEqual(collapsed.basket.state, A6BasketState.ROLLED_BACK)
        self.assertEqual([event.state for event in collapsed.events], ["ABORTING", "ROLLED_BACK"])
        self.assertTrue(any(command.action == "ROLLBACK" for command in collapsed.commands))
        self.assertGreater(collapsed.basket.rollback_loss_usd, 0.0)
        self.assertLess(collapsed.basket.realized_profit_usd, 0.0)

    def test_reprices_once_then_aborts_on_second_timeout(self) -> None:
        executor = A6BasketExecutor(A6ExecutorConfig(fill_timeout_ms=3_000, max_reprices_per_leg=1))
        start = executor.submit_opportunity(self._make_opportunity(), now_ts=1_000)
        executor.apply_fill("a6-sig-1", leg_id="alice:YES", filled_quantity=start.basket.target_quantity, avg_price=0.29, now_ts=1_200)
        improved_snapshot = self._make_snapshot(
            executable=True,
            sum_yes_ask=0.95,
            bids=(0.29, 0.31, 0.32),
            asks=(0.30, 0.32, 0.33),
            detected_at_ts=1_500,
        )
        executor.update_snapshot("a6-sig-1", improved_snapshot, now_ts=1_500)

        repriced = executor.advance_time("a6-sig-1", now_ts=4_500, snapshot=improved_snapshot)
        self.assertEqual(repriced.basket.state, A6BasketState.PARTIAL)
        self.assertEqual(repriced.events[0].event_type, "REPRICE")
        self.assertTrue(all(command.action == "REPLACE" for command in repriced.commands))

        aborted = executor.advance_time("a6-sig-1", now_ts=8_000, snapshot=improved_snapshot)
        self.assertEqual(aborted.basket.state, A6BasketState.ROLLED_BACK)
        self.assertEqual([event.state for event in aborted.events], ["ABORTING", "ROLLED_BACK"])


if __name__ == "__main__":
    unittest.main()
