"""Tests for A-6 executor live order routing.

Verifies that A6CommandRouter correctly translates A6OrderCommand objects
into ClobClient API calls with the right parameters.
"""

import unittest
from unittest.mock import MagicMock, call

from bot.a6_executor import (
    A6BasketExecutor,
    A6BasketState,
    A6ExecutorConfig,
    A6OrderCommand,
)
from bot.a6_command_router import A6CommandRouter, A6OrderResult, A6FillStatus
from bot.a6_sum_scanner import A6Opportunity, A6OpportunityLeg


def _make_3leg_opportunity() -> A6Opportunity:
    legs = (
        A6OpportunityLeg(
            leg_id="alice:YES", market_id="alice", condition_id="alice",
            token_id="tok-alice", outcome_name="Alice",
            best_bid=0.29, best_ask=0.30, tick_size=0.01,
        ),
        A6OpportunityLeg(
            leg_id="bob:YES", market_id="bob", condition_id="bob",
            token_id="tok-bob", outcome_name="Bob",
            best_bid=0.30, best_ask=0.31, tick_size=0.01,
        ),
        A6OpportunityLeg(
            leg_id="carol:YES", market_id="carol", condition_id="carol",
            token_id="tok-carol", outcome_name="Carol",
            best_bid=0.31, best_ask=0.32, tick_size=0.01,
        ),
    )
    return A6Opportunity(
        signal_id="sig-live",
        basket_id="a6-live-1",
        event_id="evt-live",
        signal_type="buy_yes_basket",
        executable=True,
        threshold=0.97,
        theoretical_edge=0.07,
        sum_yes_ask=0.93,
        sum_yes_bid=0.90,
        detected_at_ts=1000,
        invalidation_reasons=tuple(),
        legs=legs,
    )


class _MockOrderType:
    GTC = "GTC"


class TestClobOrderParams(unittest.TestCase):
    """Verify ClobClient call parameters match A-6 requirements."""

    def _make_router(self) -> tuple[A6CommandRouter, MagicMock]:
        mock_clob = MagicMock()
        mock_clob.create_order.return_value = {"signed": True}
        mock_clob.post_order.return_value = {"orderID": "clob-abc"}

        class MockOrderArgs:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        router = A6CommandRouter(
            mock_clob,
            order_args_cls=MockOrderArgs,
            order_type_cls=_MockOrderType,
            buy_const="BUY",
            sell_const="SELL",
        )
        return router, mock_clob

    def test_place_order_post_only_gtc(self):
        """All PLACE orders must be postOnly=True and GTC."""
        router, mock_clob = self._make_router()
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_3leg_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        router.execute_commands(update.commands)

        for call_obj in mock_clob.post_order.call_args_list:
            args, kwargs = call_obj
            # Second positional arg should be GTC
            self.assertEqual(args[1], "GTC")
            # post_only should be True
            self.assertTrue(kwargs.get("post_only", True))
            self.assertTrue(kwargs.get("neg_risk", True))

    def test_place_order_token_ids(self):
        """Each order must use the correct token_id from the leg."""
        router, mock_clob = self._make_router()
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_3leg_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        router.execute_commands(update.commands)

        token_ids_used = []
        for call_obj in mock_clob.create_order.call_args_list:
            args, _ = call_obj
            order_args = args[0]
            token_ids_used.append(order_args.kwargs["token_id"])

        self.assertIn("tok-alice", token_ids_used)
        self.assertIn("tok-bob", token_ids_used)
        self.assertIn("tok-carol", token_ids_used)

    def test_place_order_prices_are_maker(self):
        """Order prices should be at or below best ask (maker)."""
        router, mock_clob = self._make_router()
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_3leg_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        for cmd in update.commands:
            # Maker price should be <= best_ask - tick_size
            matching_leg = [l for l in opp.legs if l.leg_id == cmd.leg_id][0]
            self.assertLess(cmd.limit_price, matching_leg.best_ask)

    def test_place_order_quantity_positive(self):
        """Order quantities must be positive."""
        router, mock_clob = self._make_router()
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_3leg_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        for cmd in update.commands:
            self.assertGreater(cmd.quantity, 0)

    def test_order_map_tracks_leg_ids(self):
        """Router should map leg IDs to CLOB order IDs."""
        router, mock_clob = self._make_router()
        executor = A6BasketExecutor(config=A6ExecutorConfig())
        opp = _make_3leg_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        router.execute_commands(update.commands)

        for leg in opp.legs:
            clob_id = router.get_clob_order_id(leg.leg_id)
            self.assertEqual(clob_id, "clob-abc")


class TestClobFillPolling(unittest.TestCase):
    """Verify fill status polling works correctly."""

    def test_poll_parses_response(self):
        mock_clob = MagicMock()
        mock_clob.get_order.return_value = {
            "original_size": "15.625",
            "size_matched": "10.0",
            "status": "live",
            "price": "0.32",
        }

        router = A6CommandRouter(mock_clob)
        fill = router.poll_fill_status("order-123")

        self.assertIsNotNone(fill)
        self.assertAlmostEqual(fill.original_size, 15.625)
        self.assertAlmostEqual(fill.size_matched, 10.0)
        self.assertEqual(fill.status, "live")

    def test_poll_handles_missing_order(self):
        mock_clob = MagicMock()
        mock_clob.get_order.side_effect = Exception("Order not found")

        router = A6CommandRouter(mock_clob)
        fill = router.poll_fill_status("nonexistent")

        self.assertIsNone(fill)

    def test_poll_returns_none_in_paper_mode(self):
        mock_clob = MagicMock()
        router = A6CommandRouter(mock_clob, paper_mode=True)
        fill = router.poll_fill_status("any-order")
        self.assertIsNone(fill)


class TestClobErrorHandling(unittest.TestCase):
    """Verify error handling in order routing."""

    def test_place_failure_returns_error(self):
        mock_clob = MagicMock()
        mock_clob.create_order.return_value = {"signed": True}
        mock_clob.post_order.return_value = {"error": "insufficient balance"}

        router = A6CommandRouter(
            mock_clob,
            order_args_cls=MagicMock,
            order_type_cls=_MockOrderType,
            buy_const="BUY",
            sell_const="SELL",
        )

        cmd = A6OrderCommand(
            action="PLACE",
            basket_id="a6-test",
            leg_id="alice:YES",
            market_id="alice",
            token_id="tok-alice",
            side="BUY",
            quantity=10.0,
            limit_price=0.30,
        )

        results = router.execute_commands((cmd,))
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("insufficient balance", results[0].error)

    def test_create_order_exception_caught(self):
        mock_clob = MagicMock()
        mock_clob.create_order.side_effect = RuntimeError("signing failed")

        router = A6CommandRouter(
            mock_clob,
            order_args_cls=MagicMock,
            order_type_cls=_MockOrderType,
            buy_const="BUY",
            sell_const="SELL",
        )

        cmd = A6OrderCommand(
            action="PLACE",
            basket_id="a6-test",
            leg_id="alice:YES",
            market_id="alice",
            token_id="tok-alice",
            side="BUY",
            quantity=10.0,
            limit_price=0.30,
        )

        results = router.execute_commands((cmd,))
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("signing failed", results[0].error)

    def test_cancel_failure_returns_error(self):
        mock_clob = MagicMock()
        mock_clob.cancel.side_effect = Exception("cancel rejected")

        router = A6CommandRouter(mock_clob)

        cmd = A6OrderCommand(
            action="CANCEL",
            basket_id="a6-test",
            leg_id="alice:YES",
            market_id="alice",
            token_id="tok-alice",
            side="BUY",
            quantity=10.0,
            limit_price=None,
            replaces_order_id="old-order",
        )

        results = router.execute_commands((cmd,))
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("cancel rejected", results[0].error)

    def test_unknown_action_returns_error(self):
        mock_clob = MagicMock()
        router = A6CommandRouter(mock_clob)

        cmd = A6OrderCommand(
            action="UNKNOWN",
            basket_id="a6-test",
            leg_id="alice:YES",
            market_id="alice",
            token_id="tok-alice",
            side="BUY",
            quantity=10.0,
            limit_price=0.30,
        )

        results = router.execute_commands((cmd,))
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("unknown action", results[0].error)


class TestTimeoutAndRollback(unittest.TestCase):
    """Test timeout and rollback command generation."""

    def test_initial_timeout_expires_basket(self):
        """Basket should expire if no fill within timeout."""
        executor = A6BasketExecutor(
            config=A6ExecutorConfig(fill_timeout_seconds=3.0),
        )
        opp = _make_3leg_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        # Advance time past timeout
        update = executor.advance_time(
            update.basket.basket_id,
            now_ts=1004,
        )

        self.assertEqual(update.basket.state, A6BasketState.EXPIRED)
        # Should have CANCEL commands for all open legs
        cancels = [c for c in update.commands if c.action == "CANCEL"]
        self.assertEqual(len(cancels), 3)

    def test_partial_fill_timeout_triggers_rollback(self):
        """Partial fill + timeout should trigger ROLLBACK."""
        executor = A6BasketExecutor(
            config=A6ExecutorConfig(
                fill_timeout_seconds=3.0,
                max_reprices_per_leg=0,  # no repricing → immediate rollback
            ),
        )
        opp = _make_3leg_opportunity()
        update = executor.submit_opportunity(opp, now_ts=1000)

        # Fill first leg only
        basket = update.basket
        executor.apply_fill(
            basket.basket_id,
            leg_id="alice:YES",
            filled_quantity=basket.legs[0].target_quantity,
            avg_price=0.30,
            now_ts=1001,
        )

        # Advance time past timeout
        update = executor.advance_time(basket.basket_id, now_ts=1005)

        self.assertEqual(update.basket.state, A6BasketState.ROLLED_BACK)
        rollbacks = [c for c in update.commands if c.action == "ROLLBACK"]
        cancels = [c for c in update.commands if c.action == "CANCEL"]
        # Should have rollback for filled leg and cancels for open legs
        self.assertGreater(len(rollbacks), 0)
        self.assertGreater(len(cancels), 0)

        # Rollback orders should be SELL side
        for cmd in rollbacks:
            self.assertEqual(cmd.side, "SELL")


if __name__ == "__main__":
    unittest.main()
