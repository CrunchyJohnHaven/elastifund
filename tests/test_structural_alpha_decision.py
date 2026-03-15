from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.structural_alpha_decision import build_decision_report


UTC = timezone.utc


def iso_days_ago(days: float) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()


class TestStructuralAlphaDecision(unittest.TestCase):
    def _snapshot(self, start: str, end: str) -> dict:
        return {
            "generated_at": end,
            "a6_replay": {
                "observed_start": start,
                "observed_end": end,
                "row_count": 44,
            },
            "lane_status": {
                "a6": {
                    "status": "blocked",
                    "blocked_reasons": [
                        "maker_fill_proxy_unmeasured",
                        "public_audit_zero_executable_constructions_below_0.95_gate",
                    ],
                },
                "b1": {
                    "status": "blocked",
                    "blocked_reasons": [
                        "classification_accuracy_unmeasured",
                        "public_audit_zero_deterministic_pairs_in_first_1000_allowed_markets",
                    ],
                },
            },
            "repo_truth": {
                "public_a6_audit": {
                    "allowed_neg_risk_event_count": 563,
                    "execute_threshold": 0.95,
                    "executable_constructions_below_threshold": 0,
                },
                "public_b1_audit": {
                    "allowed_market_sample_size": 1000,
                    "deterministic_template_pair_count": 0,
                },
            },
            "gating_metrics": {
                "kill_decision": "kill",
                "kill_reason": "upper_confidence_bound=0.0803<0.50 over 44 completed cycles",
            },
            "live_surface": {
                "qualified_underround_count": 0,
                "qualified_overround_count": 57,
            },
            "fill_proxy": {
                "eligible_probe_count": 0,
                "full_fill_proxy_rate": None,
            },
            "b1": {
                "graph_edge_count": 0,
                "historical_violation_count": 0,
                "classification_accuracy": None,
                "false_positive_rate": None,
            },
        }

    def test_incomplete_window_keeps_both_lanes_in_continue_state(self) -> None:
        snapshot = self._snapshot(
            start="2026-03-07T18:49:58+00:00",
            end="2026-03-09T01:40:02+00:00",
        )
        report = build_decision_report(
            snapshot,
            guaranteed_dollar_audit=[
                {
                    "best_construction": {
                        "construction_type": "neg_risk_conversion",
                        "top_of_book_cost": 0.982,
                        "executable": False,
                        "readiness": {"ready": False},
                    }
                }
            ],
            b1_template_audit={
                "template_markets": {"winner_margin": 478},
                "template_pairs": [],
            },
            lookback_days=7,
        )

        self.assertFalse(report["observation_window"]["window_complete"])
        self.assertEqual(report["a6"]["decision"], "continue")
        self.assertEqual(report["b1"]["decision"], "continue")
        self.assertIsNotNone(report["a6"]["kill_if_unchanged_by"])
        self.assertIsNotNone(report["b1"]["kill_if_unchanged_by"])

    def test_complete_window_with_zero_density_kills_both_lanes(self) -> None:
        start = iso_days_ago(8.0)
        end = iso_days_ago(0.0)
        snapshot = self._snapshot(start=start, end=end)
        report = build_decision_report(
            snapshot,
            guaranteed_dollar_audit=[
                {
                    "best_construction": {
                        "construction_type": "neg_risk_conversion",
                        "top_of_book_cost": 0.99,
                        "executable": False,
                        "readiness": {"ready": False},
                    }
                }
            ],
            b1_template_audit={
                "template_markets": {"winner_margin": 478},
                "template_pairs": [],
            },
            lookback_days=7,
        )

        self.assertTrue(report["observation_window"]["window_complete"])
        self.assertEqual(report["a6"]["decision"], "kill")
        self.assertEqual(report["b1"]["decision"], "kill")
        self.assertEqual(report["portfolio_call"]["status"], "kill_both")


if __name__ == "__main__":
    unittest.main()
