from __future__ import annotations

from datetime import datetime, timezone
import unittest

from bot.execution_readiness import (
    ExecutionReadinessInputs,
    builder_relayer_available,
    evaluate_execution_readiness,
    evaluate_feed_health,
    in_polymarket_restart_window,
)


class TestExecutionReadiness(unittest.TestCase):
    def test_restart_window_matches_monday_evening_eastern(self) -> None:
        inside = datetime(2026, 3, 10, 0, 5, tzinfo=timezone.utc)  # Monday 20:05 ET
        outside = datetime(2026, 3, 10, 1, 5, tzinfo=timezone.utc)  # Monday 21:05 ET

        self.assertTrue(in_polymarket_restart_window(inside))
        self.assertFalse(in_polymarket_restart_window(outside))

    def test_builder_creds_detection(self) -> None:
        self.assertFalse(builder_relayer_available({}))
        self.assertTrue(
            builder_relayer_available(
                {
                    "POLY_BUILDER_API_KEY": "key",
                    "POLY_BUILDER_API_SECRET": "secret",
                    "POLY_BUILDER_API_PASSPHRASE": "pass",
                }
            )
        )

    def test_feed_health_flags_silence_and_divergence(self) -> None:
        health = evaluate_feed_health(
            last_data_ts=100.0,
            now_ts=130.0,
            max_silence_seconds=10.0,
            book_best_bid=0.40,
            book_best_ask=0.41,
            price_best_bid=0.52,
            price_best_ask=0.53,
            tick_size=0.01,
        )

        self.assertFalse(health.healthy)
        self.assertIn("feed_silent", health.reasons)
        self.assertIn("book_price_divergence", health.reasons)

    def test_execution_readiness_blocks_when_core_gates_fail(self) -> None:
        readiness = evaluate_execution_readiness(
            ExecutionReadinessInputs(
                feed_healthy=False,
                tick_size_ok=False,
                quote_surface_ok=True,
                estimated_one_leg_loss_usd=6.0,
                max_one_leg_loss_threshold_usd=5.0,
                neg_risk=True,
                neg_risk_flag_configured=False,
                builder_required=True,
                builder_available=False,
                now=datetime(2026, 3, 10, 0, 5, tzinfo=timezone.utc),
            )
        )

        self.assertFalse(readiness.ready)
        self.assertIn("feed_unhealthy", readiness.reasons)
        self.assertIn("tick_size_stale", readiness.reasons)
        self.assertIn("one_leg_loss_exceeds_threshold", readiness.reasons)
        self.assertIn("restart_window_active", readiness.reasons)
        self.assertIn("neg_risk_flag_missing", readiness.reasons)
        self.assertIn("builder_relayer_unavailable", readiness.reasons)

    def test_execution_readiness_allows_clean_surface(self) -> None:
        readiness = evaluate_execution_readiness(
            ExecutionReadinessInputs(
                feed_healthy=True,
                tick_size_ok=True,
                quote_surface_ok=True,
                estimated_one_leg_loss_usd=5.0,
                max_one_leg_loss_threshold_usd=5.0,
                neg_risk=True,
                neg_risk_flag_configured=True,
                builder_required=False,
                builder_available=False,
                now=datetime(2026, 3, 10, 2, 0, tzinfo=timezone.utc),
            )
        )

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, "ready")
        self.assertEqual(readiness.reasons, tuple())


if __name__ == "__main__":
    unittest.main()
