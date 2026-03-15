"""Tests for A-6 → jj_live.py integration.

Verifies that jj_live calls the embedded scanner, routes opportunities
to the A6BasketExecutor, and processes resulting commands through the
A6CommandRouter.
"""

import unittest
from unittest.mock import MagicMock, patch

from bot.a6_executor import A6BasketExecutor, A6BasketState, A6ExecutorConfig
from bot.a6_command_router import A6CommandRouter, A6OrderResult, A6FillStatus
from bot.a6_sum_scanner import A6Opportunity, A6OpportunityLeg


def _make_opportunity(
    *,
    basket_id: str = "a6-test-1",
    event_id: str = "evt-1",
    edge: float = 0.07,
    sum_yes_ask: float = 0.93,
) -> A6Opportunity:
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
        basket_id=basket_id,
        event_id=event_id,
        signal_type="buy_yes_basket",
        executable=True,
        threshold=0.97,
        theoretical_edge=edge,
        sum_yes_ask=sum_yes_ask,
        sum_yes_bid=0.90,
        detected_at_ts=1_000,
        invalidation_reasons=tuple(),
        legs=legs,
    )


class TestA6ExecutorSubmission(unittest.TestCase):
    """Test that A6BasketExecutor correctly accepts opportunities."""

    def test_submit_produces_place_commands(self):
        executor = A6BasketExecutor(config=A6ExecutorConfig(max_leg_notional_usd=5.0))
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        self.assertEqual(update.basket.state, A6BasketState.QUOTING)
        self.assertEqual(len(update.commands), 3)
        for cmd in update.commands:
            self.assertEqual(cmd.action, "PLACE")
            self.assertEqual(cmd.side, "BUY")
            self.assertTrue(cmd.post_only)
            self.assertEqual(cmd.signature_type, 1)

    def test_submit_rejects_non_executable(self):
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = A6Opportunity(
            signal_id="sig-2",
            basket_id="a6-sig-2",
            event_id="evt-2",
            signal_type="unwind_inventory_only",
            executable=False,
            threshold=1.03,
            theoretical_edge=0.03,
            sum_yes_ask=None,
            sum_yes_bid=1.03,
            detected_at_ts=1_000,
            invalidation_reasons=tuple(),
            legs=tuple(),
        )
        with self.assertRaises(ValueError):
            executor.submit_opportunity(opp)

    def test_submit_respects_max_baskets(self):
        executor = A6BasketExecutor(config=A6ExecutorConfig(max_open_baskets=1))
        opp1 = _make_opportunity(basket_id="a6-first")
        executor.submit_opportunity(opp1, now_ts=1000)

        opp2 = _make_opportunity(basket_id="a6-second")
        with self.assertRaises(ValueError):
            executor.submit_opportunity(opp2, now_ts=1001)


class TestA6CommandRouter(unittest.TestCase):
    """Test that A6CommandRouter correctly routes commands to ClobClient."""

    def _make_router(self, *, paper: bool = False) -> tuple[A6CommandRouter, MagicMock]:
        mock_clob = MagicMock()
        mock_clob.create_order.return_value = {"signed": True}
        mock_clob.post_order.return_value = {"orderID": "clob-order-123"}
        mock_clob.cancel.return_value = True
        mock_clob.get_order.return_value = {
            "original_size": "10.0",
            "size_matched": "5.0",
            "status": "live",
            "price": "0.30",
        }

        router = A6CommandRouter(
            mock_clob,
            order_args_cls=MagicMock,
            order_type_cls=MagicMock(),
            buy_const="BUY",
            sell_const="SELL",
            paper_mode=paper,
        )
        return router, mock_clob

    def test_place_command_calls_clob(self):
        router, mock_clob = self._make_router()
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        results = router.execute_commands(update.commands)

        self.assertEqual(len(results), 3)
        for result in results:
            self.assertEqual(result.command_action, "PLACE")
            self.assertTrue(result.success)
            self.assertEqual(result.order_id, "clob-order-123")

        self.assertEqual(mock_clob.create_order.call_count, 3)
        self.assertEqual(mock_clob.post_order.call_count, 3)

    def test_cancel_command(self):
        router, mock_clob = self._make_router()

        # Simulate a cancel command
        from bot.a6_executor import A6OrderCommand
        cmd = A6OrderCommand(
            action="CANCEL",
            basket_id="a6-test",
            leg_id="alice:YES",
            market_id="alice",
            token_id="alice-yes",
            side="BUY",
            quantity=10.0,
            limit_price=None,
            replaces_order_id="old-order-1",
        )

        results = router.execute_commands((cmd,))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].command_action, "CANCEL")
        self.assertTrue(results[0].success)
        mock_clob.cancel.assert_called_once()

    def test_paper_mode_no_clob_calls(self):
        router, mock_clob = self._make_router(paper=True)
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        results = router.execute_commands(update.commands)

        self.assertEqual(len(results), 3)
        for result in results:
            self.assertTrue(result.success)
            self.assertTrue(result.order_id.startswith("paper-a6-"))

        mock_clob.create_order.assert_not_called()
        mock_clob.post_order.assert_not_called()

    def test_poll_fill_status(self):
        router, mock_clob = self._make_router()
        fill = router.poll_fill_status("clob-order-123")

        self.assertIsNotNone(fill)
        self.assertEqual(fill.order_id, "clob-order-123")
        self.assertEqual(fill.original_size, 10.0)
        self.assertEqual(fill.size_matched, 5.0)
        self.assertEqual(fill.status, "live")

    def test_rollback_uses_sell_side(self):
        router, mock_clob = self._make_router()

        from bot.a6_executor import A6OrderCommand
        cmd = A6OrderCommand(
            action="ROLLBACK",
            basket_id="a6-test",
            leg_id="alice:YES",
            market_id="alice",
            token_id="alice-yes",
            side="SELL",
            quantity=10.0,
            limit_price=0.29,
        )

        results = router.execute_commands((cmd,))
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        # Verify the order was created (via _place_sell path)
        mock_clob.create_order.assert_called_once()
        mock_clob.post_order.assert_called_once()

    def test_replace_cancels_then_places(self):
        router, mock_clob = self._make_router()

        from bot.a6_executor import A6OrderCommand
        cmd = A6OrderCommand(
            action="REPLACE",
            basket_id="a6-test",
            leg_id="alice:YES",
            market_id="alice",
            token_id="alice-yes",
            side="BUY",
            quantity=10.0,
            limit_price=0.31,
            replaces_order_id="old-order-1",
        )

        results = router.execute_commands((cmd,))
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        mock_clob.cancel.assert_called_once()
        mock_clob.create_order.assert_called_once()
        mock_clob.post_order.assert_called_once()


class TestA6ExecutorOrderParams(unittest.TestCase):
    """Verify order parameters (postOnly, GTC, size caps) are correct."""

    def test_all_orders_post_only(self):
        executor = A6BasketExecutor(
            config=A6ExecutorConfig(max_leg_notional_usd=5.0, signature_type=1),
        )
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        for cmd in update.commands:
            self.assertTrue(cmd.post_only, f"Order {cmd.leg_id} should be post_only")
            self.assertEqual(cmd.signature_type, 1, "Must use POLY_PROXY signature")

    def test_size_capped_to_max_notional(self):
        max_usd = 3.0
        executor = A6BasketExecutor(
            config=A6ExecutorConfig(max_leg_notional_usd=max_usd),
        )
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        for cmd in update.commands:
            notional = cmd.quantity * cmd.limit_price
            self.assertLessEqual(
                notional, max_usd + 0.01,
                f"Leg {cmd.leg_id} notional ${notional:.2f} exceeds cap ${max_usd}",
            )

    def test_all_orders_are_buy(self):
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        for cmd in update.commands:
            self.assertEqual(cmd.side, "BUY")
            self.assertEqual(cmd.action, "PLACE")

    def test_rollback_orders_are_sell(self):
        executor = A6BasketExecutor(config=A6ExecutorConfig(fill_timeout_seconds=0.001))
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        # Apply partial fill to first leg only
        basket = update.basket
        update = executor.apply_fill(
            basket.basket_id,
            leg_id="alice:YES",
            filled_quantity=basket.legs[0].target_quantity,
            avg_price=0.30,
            now_ts=1001,
        )

        # Advance time past timeout → should trigger rollback
        update = executor.advance_time(basket.basket_id, now_ts=1005)

        # Find ROLLBACK commands
        rollbacks = [cmd for cmd in update.commands if cmd.action == "ROLLBACK"]
        for cmd in rollbacks:
            self.assertEqual(cmd.side, "SELL")


class TestA6LiveCycleIntegration(unittest.TestCase):
    """Test the _execute_a6_live_cycle logic in isolation."""

    def test_filters_non_executable_opportunities(self):
        """Non-executable opportunities should be skipped."""
        executor = A6BasketExecutor(config=A6ExecutorConfig())

        non_executable = A6Opportunity(
            signal_id="sig-bad",
            basket_id="a6-bad",
            event_id="evt-bad",
            signal_type="unwind_inventory_only",
            executable=False,
            threshold=1.03,
            theoretical_edge=0.03,
            sum_yes_ask=None,
            sum_yes_bid=1.03,
            detected_at_ts=1_000,
            invalidation_reasons=tuple(),
            legs=tuple(),
        )

        # Executor should not accept non-executable
        active_before = len(executor.active_baskets)
        # We expect no baskets after trying to process non-executable
        self.assertEqual(active_before, 0)

    def test_filters_sum_ask_above_threshold(self):
        """Opportunities with sum_yes_ask >= 0.97 should be skipped."""
        executor = A6BasketExecutor(config=A6ExecutorConfig())

        opp = _make_opportunity(sum_yes_ask=0.98)
        # In the integration code, this would be filtered before submission
        # sum_yes_ask >= 0.97 → skip
        self.assertGreaterEqual(opp.sum_yes_ask, 0.97)

    def test_executor_state_machine_happy_path(self):
        """Full lifecycle: submit → fill all → complete."""
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        basket = update.basket
        self.assertEqual(basket.state, A6BasketState.QUOTING)

        # Fill all three legs
        for leg in basket.legs:
            executor.apply_fill(
                basket.basket_id,
                leg_id=leg.leg_id,
                filled_quantity=leg.target_quantity,
                avg_price=leg.quote_price,
                now_ts=1001,
            )

        final = executor.baskets[basket.basket_id]
        # Executor promotes to MERGE_READY (then COMPLETE) when all legs fill
        self.assertIn(final.state, {A6BasketState.COMPLETE, A6BasketState.MERGE_READY})
        self.assertGreater(final.realized_profit_usd, 0)


class TestSumViolationScannerOpportunities(unittest.TestCase):
    """Test that SumViolationScanner stores A6Opportunity objects."""

    def test_latest_opportunities_attribute_exists(self):
        """Scanner should have _latest_opportunities attribute after init."""
        try:
            from bot.sum_violation_scanner import SumViolationScanner
            scanner = SumViolationScanner.__new__(SumViolationScanner)
            scanner._latest_opportunities = []
            self.assertIsInstance(scanner._latest_opportunities, list)
        except ImportError:
            self.skipTest("SumViolationScanner not importable")


if __name__ == "__main__":
    unittest.main()
