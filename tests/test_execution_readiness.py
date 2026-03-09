from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from bot.execution_readiness import (
    build_fast_flow_restart_report,
    ExecutionReadinessInputs,
    evaluate_fast_flow_restart,
    builder_relayer_available,
    evaluate_execution_readiness,
    evaluate_feed_health,
    evaluate_structural_lane_readiness,
    FastFlowRestartInputs,
    in_polymarket_restart_window,
    RestartRequiredArtifact,
    StructuralLaneReadinessInputs,
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

    def test_a6_structural_lane_blocks_until_fill_and_half_life_pass(self) -> None:
        status = evaluate_structural_lane_readiness(
            StructuralLaneReadinessInputs(
                lane="a6",
                maker_fill_proxy_rate=None,
                maker_fill_wilson_lower=None,
                violation_half_life_seconds=5.0,
                settlement_evidence_count=0,
                public_a6_executable_count=0,
            )
        )

        self.assertEqual(status.status, "blocked")
        self.assertIn("maker_fill_proxy_unmeasured", status.blocked_reasons)
        self.assertIn("violation_half_life_below_minimum", status.blocked_reasons)
        self.assertIn("public_audit_zero_executable_constructions_below_0.95_gate", status.blocked_reasons)
        self.assertEqual(status.settlement_evidence_count, 0)

    def test_a6_structural_lane_promotes_to_shadow_then_micro_live(self) -> None:
        shadow = evaluate_structural_lane_readiness(
            StructuralLaneReadinessInputs(
                lane="a6",
                maker_fill_proxy_rate=0.42,
                maker_fill_wilson_lower=0.24,
                violation_half_life_seconds=18.0,
                settlement_evidence_count=0,
                public_a6_executable_count=2,
            )
        )
        micro_live = evaluate_structural_lane_readiness(
            StructuralLaneReadinessInputs(
                lane="a6",
                maker_fill_proxy_rate=0.42,
                maker_fill_wilson_lower=0.24,
                violation_half_life_seconds=18.0,
                settlement_evidence_count=3,
                public_a6_executable_count=2,
            )
        )

        self.assertEqual(shadow.status, "ready_for_shadow")
        self.assertEqual(shadow.blocked_reasons, tuple())
        self.assertEqual(micro_live.status, "ready_for_micro_live")

    def test_b1_structural_lane_blocks_without_precision_and_pair_density(self) -> None:
        status = evaluate_structural_lane_readiness(
            StructuralLaneReadinessInputs(
                lane="b1",
                maker_fill_proxy_rate=0.30,
                maker_fill_wilson_lower=0.22,
                violation_half_life_seconds=15.0,
                settlement_evidence_count=0,
                classification_accuracy=0.82,
                false_positive_rate=0.08,
                public_b1_template_pair_count=0,
                public_b1_market_sample_size=1000,
            )
        )

        self.assertEqual(status.status, "blocked")
        self.assertIn("classification_accuracy_below_85pct", status.blocked_reasons)
        self.assertIn("false_positive_rate_above_5pct", status.blocked_reasons)
        self.assertIn("public_audit_zero_deterministic_pairs_in_first_1000_allowed_markets", status.blocked_reasons)
        self.assertAlmostEqual(status.classification_accuracy, 0.82)
        self.assertAlmostEqual(status.false_positive_rate, 0.08)

    def test_b1_structural_lane_promotes_to_shadow_then_micro_live(self) -> None:
        shadow = evaluate_structural_lane_readiness(
            StructuralLaneReadinessInputs(
                lane="b1",
                maker_fill_proxy_rate=0.30,
                maker_fill_wilson_lower=0.22,
                violation_half_life_seconds=8.0,
                settlement_evidence_count=0,
                classification_accuracy=0.90,
                false_positive_rate=0.03,
                public_b1_template_pair_count=6,
                public_b1_market_sample_size=1000,
            )
        )
        micro_live = evaluate_structural_lane_readiness(
            StructuralLaneReadinessInputs(
                lane="b1",
                maker_fill_proxy_rate=0.30,
                maker_fill_wilson_lower=0.22,
                violation_half_life_seconds=12.0,
                settlement_evidence_count=3,
                classification_accuracy=0.90,
                false_positive_rate=0.03,
                public_b1_template_pair_count=6,
                public_b1_market_sample_size=1000,
            )
        )

        self.assertEqual(shadow.status, "ready_for_shadow")
        self.assertEqual(shadow.blocked_reasons, tuple())
        self.assertEqual(micro_live.status, "ready_for_micro_live")

    def test_fast_flow_restart_blocks_march_9_runtime_truth_snapshot(self) -> None:
        cycle_status = {
            "launch": {"live_launch_blocked": True},
            "wallet_flow": {
                "ready": False,
                "status": "not_ready",
                "wallet_count": 0,
                "reasons": [
                    "missing_data/smart_wallets.json",
                    "missing_data/wallet_scores.db",
                    "no_scored_wallets",
                ],
            },
            "runtime": {"cycles_completed": 294, "closed_trades": 0},
            "service": {
                "status": "running",
                "systemctl_state": "active",
                "detail": "active",
            },
            "root_tests": {"status": "passing"},
        }

        decision = evaluate_fast_flow_restart(
            FastFlowRestartInputs(
                remote_cycle_status=cycle_status,
                remote_service_status={
                    "status": "running",
                    "systemctl_state": "active",
                    "detail": "active",
                },
                jj_state={"cycles_completed": 294},
                root_test_status={"status": "passing"},
                required_artifacts=(
                    RestartRequiredArtifact("remote_cycle_status", "reports/remote_cycle_status.json", True),
                    RestartRequiredArtifact("remote_service_status", "reports/remote_service_status.json", True),
                    RestartRequiredArtifact("jj_state", "jj_state.json", True),
                    RestartRequiredArtifact("root_test_status", "reports/root_test_status.json", True),
                ),
            )
        )

        self.assertFalse(decision.restart_ready)
        self.assertEqual(decision.recommended_mode, "hold")
        self.assertIn("wallet_bootstrap_not_ready", decision.blocked_reasons)
        self.assertIn("remote_service_state_ambiguous", decision.blocked_reasons)
        self.assertIn("remote_service_mode_unconfirmed", decision.blocked_reasons)
        self.assertIn("remote_service_running_while_launch_blocked", decision.blocked_reasons)

    def test_fast_flow_restart_recommends_paper_when_wallet_ready_and_service_stopped(self) -> None:
        decision = evaluate_fast_flow_restart(
            FastFlowRestartInputs(
                remote_cycle_status={
                    "launch": {"live_launch_blocked": True},
                    "wallet_flow": {
                        "ready": True,
                        "status": "ready",
                        "wallet_count": 12,
                        "reasons": [],
                    },
                    "runtime": {"cycles_completed": 295, "closed_trades": 0},
                    "service": {
                        "status": "stopped",
                        "systemctl_state": "inactive",
                        "detail": "inactive",
                    },
                    "root_tests": {"status": "passing"},
                },
                remote_service_status={
                    "status": "stopped",
                    "systemctl_state": "inactive",
                    "detail": "inactive",
                },
                jj_state={"cycles_completed": 295},
                root_test_status={"status": "passing"},
                required_artifacts=(
                    RestartRequiredArtifact("remote_cycle_status", "reports/remote_cycle_status.json", True),
                    RestartRequiredArtifact("remote_service_status", "reports/remote_service_status.json", True),
                    RestartRequiredArtifact("jj_state", "jj_state.json", True),
                    RestartRequiredArtifact("root_test_status", "reports/root_test_status.json", True),
                ),
            )
        )

        self.assertTrue(decision.restart_ready)
        self.assertEqual(decision.recommended_mode, "paper")
        self.assertEqual(decision.service_status, "stopped")
        self.assertEqual(decision.blocked_reasons, tuple())

    def test_build_fast_flow_restart_report_reads_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports_dir = root / "reports"
            reports_dir.mkdir()
            (root / "jj_state.json").write_text(json.dumps({"cycles_completed": 12}))
            (reports_dir / "root_test_status.json").write_text(
                json.dumps({"status": "passing"})
            )
            (reports_dir / "remote_service_status.json").write_text(
                json.dumps(
                    {
                        "status": "stopped",
                        "systemctl_state": "inactive",
                        "detail": "inactive",
                    }
                )
            )
            (reports_dir / "remote_cycle_status.json").write_text(
                json.dumps(
                    {
                        "launch": {"live_launch_blocked": True},
                        "wallet_flow": {
                            "ready": True,
                            "status": "ready",
                            "wallet_count": 9,
                            "reasons": [],
                        },
                        "runtime": {"cycles_completed": 12, "closed_trades": 2},
                        "service": {
                            "status": "stopped",
                            "systemctl_state": "inactive",
                            "detail": "inactive",
                        },
                        "root_tests": {"status": "passing"},
                    }
                )
            )

            report = build_fast_flow_restart_report(root)

        self.assertTrue(report["restart_ready"])
        self.assertEqual(report["recommended_mode"], "shadow")
        self.assertEqual(report["cycles_completed"], 12)
        self.assertEqual(len(report["required_artifacts"]), 4)
        self.assertTrue(all(item["exists"] for item in report["required_artifacts"]))


if __name__ == "__main__":
    unittest.main()
