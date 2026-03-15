import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.arb_empirical_analysis import (
    LegObservation,
    PassiveOrderProbe,
    ReplayViolationRow,
    build_structural_gate_pack,
    build_passive_order_probes,
    build_violation_episodes,
    evaluate_lane_statuses,
    measure_fill_proxy,
    midpoint_bucket,
    recommend_a6_thresholds,
    summarize_public_a6_audit,
    summarize_public_b1_audit,
    trade_matches_passive_yes_buy,
)


class TestArbEmpiricalAnalysis(unittest.TestCase):
    def test_midpoint_bucket_assigns_tail_and_favorite_ranges(self) -> None:
        self.assertEqual(midpoint_bucket(0.03), "tail_0_5pct")
        self.assertEqual(midpoint_bucket(0.12), "tail_5_15pct")
        self.assertEqual(midpoint_bucket(0.70), "favorite_65_100pct")

    def test_build_violation_episodes_splits_on_gap(self) -> None:
        rows = [
            ReplayViolationRow(
                violation_id="a",
                event_id="evt-1",
                detected_at_ts=100,
                gross_edge=0.04,
                score=0.01,
                slippage_est=0.01,
                fill_risk=0.003,
                theoretical_pnl=0.04,
                realized_pnl=0.0,
                action="buy_yes_basket",
                relation_type="same_event_sum",
                event_legs=4,
                missing_legs=0,
                complete_basket=True,
                sum_yes_ask=0.96,
            ),
            ReplayViolationRow(
                violation_id="b",
                event_id="evt-1",
                detected_at_ts=150,
                gross_edge=0.05,
                score=0.02,
                slippage_est=0.01,
                fill_risk=0.003,
                theoretical_pnl=0.05,
                realized_pnl=0.0,
                action="buy_yes_basket",
                relation_type="same_event_sum",
                event_legs=4,
                missing_legs=0,
                complete_basket=True,
                sum_yes_ask=0.95,
            ),
            ReplayViolationRow(
                violation_id="c",
                event_id="evt-1",
                detected_at_ts=400,
                gross_edge=0.06,
                score=0.03,
                slippage_est=0.01,
                fill_risk=0.003,
                theoretical_pnl=0.06,
                realized_pnl=0.0,
                action="buy_yes_basket",
                relation_type="same_event_sum",
                event_legs=4,
                missing_legs=0,
                complete_basket=True,
                sum_yes_ask=0.94,
            ),
        ]

        episodes = build_violation_episodes(rows, gap_seconds=120)
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0].duration_seconds, 50)
        self.assertEqual(episodes[1].duration_seconds, 0)

    def test_recommend_a6_thresholds_uses_drag_fallback_for_thin_samples(self) -> None:
        rows = [
            ReplayViolationRow(
                violation_id="a",
                event_id="evt-1",
                detected_at_ts=100,
                gross_edge=0.04,
                score=0.01,
                slippage_est=0.015,
                fill_risk=0.003,
                theoretical_pnl=0.04,
                realized_pnl=0.0,
                action="buy_yes_basket",
                relation_type="same_event_sum",
                event_legs=5,
                missing_legs=0,
                complete_basket=True,
                sum_yes_ask=0.96,
            ),
            ReplayViolationRow(
                violation_id="b",
                event_id="evt-2",
                detected_at_ts=130,
                gross_edge=0.03,
                score=-0.01,
                slippage_est=0.02,
                fill_risk=0.003,
                theoretical_pnl=0.03,
                realized_pnl=0.0,
                action="buy_yes_basket",
                relation_type="same_event_sum",
                event_legs=5,
                missing_legs=0,
                complete_basket=True,
                sum_yes_ask=0.97,
            ),
        ]

        recs = recommend_a6_thresholds(rows)
        bucket = recs["by_leg_bucket"]["3_5_legs"]
        self.assertEqual(bucket["sample_count"], 2)
        self.assertAlmostEqual(bucket["recommended_min_gross_edge"], 0.0318)
        self.assertAlmostEqual(bucket["recommended_sum_yes_ask_threshold"], 0.9683)
        self.assertEqual(bucket["basis"], "thin_sample_execution_drag_plus_buffer")

    def test_trade_matches_passive_yes_buy_handles_yes_sell_and_no_buy(self) -> None:
        probe = PassiveOrderProbe(
            cycle_index=0,
            snapshot_ts=100,
            condition_id="cond-1",
            market_id="mkt-1",
            event_id="evt-1",
            midpoint=0.2,
            price_bucket="tail_5_15pct",
            quote_price=0.19,
            required_size=10.0,
        )
        yes_sell = {
            "conditionId": "cond-1",
            "outcome": "Yes",
            "side": "SELL",
            "price": 0.18,
            "size": 6.0,
            "timestamp": 110,
        }
        no_buy = {
            "conditionId": "cond-1",
            "outcome": "No",
            "side": "BUY",
            "price": 0.82,
            "size": 5.0,
            "timestamp": 115,
        }
        self.assertEqual(trade_matches_passive_yes_buy(yes_sell, probe), 6.0)
        self.assertEqual(trade_matches_passive_yes_buy(no_buy, probe), 5.0)

    def test_measure_fill_proxy_counts_full_fill(self) -> None:
        probes = [
            PassiveOrderProbe(
                cycle_index=0,
                snapshot_ts=100,
                condition_id="cond-1",
                market_id="m1",
                event_id="evt-1",
                midpoint=0.10,
                price_bucket="tail_5_15pct",
                quote_price=0.10,
                required_size=50.0,
            ),
            PassiveOrderProbe(
                cycle_index=0,
                snapshot_ts=100,
                condition_id="cond-2",
                market_id="m2",
                event_id="evt-2",
                midpoint=0.70,
                price_bucket="favorite_65_100pct",
                quote_price=0.70,
                required_size=10.0,
            ),
        ]
        trades = [
            {"conditionId": "cond-1", "outcome": "Yes", "side": "SELL", "price": 0.10, "size": 60.0, "timestamp": 110},
            {"conditionId": "cond-2", "outcome": "Yes", "side": "SELL", "price": 0.75, "size": 20.0, "timestamp": 110},
        ]

        result = measure_fill_proxy(probes, trades, lookahead_seconds=30, trade_data_end_ts=140)
        self.assertEqual(result["eligible_probe_count"], 2)
        self.assertAlmostEqual(result["full_fill_proxy_rate"], 0.5)
        self.assertIn("tail_5_15pct", result["bucketed"])

    def test_build_passive_order_probes_stratifies_by_cycle(self) -> None:
        legs = []
        for cycle_index in range(3):
            for idx in range(3):
                legs.append(
                    LegObservation(
                        cycle_index=cycle_index,
                        observed_at_ts=100 + cycle_index,
                        event_id=f"evt-{cycle_index}",
                        event_title="Event",
                        market_id=f"m-{cycle_index}-{idx}",
                        condition_id=f"cond-{cycle_index}-{idx}",
                        question="Question",
                        category="politics",
                        outcome_name="Yes",
                        tick_size=0.01,
                        yes_bid=0.10,
                        yes_ask=0.11,
                        midpoint=0.105 + idx,
                        spread=0.01,
                        fetch_status="ok",
                        is_tradable_outcome=True,
                    )
                )

        probes = build_passive_order_probes(legs, fill_sample_size=6)
        sampled_cycles = {probe.cycle_index for probe in probes}
        self.assertEqual(sampled_cycles, {0, 1, 2})

    def test_public_audit_summaries_extract_repo_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            a6_json = tmp_path / "guaranteed_dollar_audit.json"
            a6_md = tmp_path / "guaranteed_dollar_audit.md"
            b1_json = tmp_path / "b1_template_audit.json"
            b1_md = tmp_path / "b1_template_audit.md"

            a6_json.write_text(
                json.dumps(
                    [
                        {"best_construction": {"executable": True, "top_of_book_cost": 0.94}},
                        {"best_construction": {"executable": True, "top_of_book_cost": 0.97}},
                        {"best_construction": {"executable": False, "top_of_book_cost": 0.90}},
                    ]
                ),
                encoding="utf-8",
            )
            a6_md.write_text("- Allowed neg-risk events audited: 92\n", encoding="utf-8")
            b1_json.write_text(json.dumps({"template_pairs": [{"id": 1}, {"id": 2}]}), encoding="utf-8")
            b1_md.write_text("- Template-compatible pairs: 2\n", encoding="utf-8")

            a6_summary = summarize_public_a6_audit(
                json_path=a6_json,
                markdown_path=a6_md,
                execute_threshold=0.95,
            )
            b1_summary = summarize_public_b1_audit(
                json_path=b1_json,
                markdown_path=b1_md,
                market_sample_size=1000,
            )

        self.assertEqual(a6_summary["allowed_neg_risk_event_count"], 92)
        self.assertEqual(a6_summary["executable_constructions_below_threshold"], 1)
        self.assertEqual(b1_summary["deterministic_template_pair_count"], 2)
        self.assertEqual(b1_summary["allowed_market_sample_size"], 1000)

    def test_evaluate_lane_statuses_surfaces_blocked_repo_truth(self) -> None:
        snapshot = {
            "fill_proxy": {
                "full_fill_proxy_rate": None,
                "wilson_low": None,
            },
            "a6_replay": {
                "observed_persistence_lower_bound_seconds": 0.0,
            },
            "b1": {
                "b1_half_life_lower_bound_seconds": None,
                "classification_accuracy": None,
                "false_positive_rate": None,
            },
            "settlement": {
                "total": 0,
            },
            "repo_truth": {
                "public_a6_audit": {
                    "execute_threshold": 0.95,
                    "executable_constructions_below_threshold": 0,
                },
                "public_b1_audit": {
                    "allowed_market_sample_size": 1000,
                    "deterministic_template_pair_count": 0,
                },
            },
        }

        lane_status = evaluate_lane_statuses(snapshot)

        self.assertEqual(lane_status["a6"]["status"], "blocked")
        self.assertEqual(lane_status["b1"]["status"], "blocked")
        self.assertEqual(lane_status["a6"]["settlement_evidence_count"], 0)
        self.assertIsNone(lane_status["a6"]["maker_fill_proxy_rate"])
        self.assertIsNone(lane_status["b1"]["classification_accuracy"])
        self.assertIsNone(lane_status["b1"]["false_positive_rate"])
        self.assertIn("maker_fill_proxy_unmeasured", lane_status["a6"]["blocked_reasons"])
        self.assertIn(
            "public_audit_zero_executable_constructions_below_0.95_gate",
            lane_status["a6"]["blocked_reasons"],
        )
        self.assertIn("classification_accuracy_unmeasured", lane_status["b1"]["blocked_reasons"])
        self.assertIn(
            "public_audit_zero_deterministic_pairs_in_first_1000_allowed_markets",
            lane_status["b1"]["blocked_reasons"],
        )

    def test_build_structural_gate_pack_reports_stage_threshold_deltas(self) -> None:
        snapshot = {
            "generated_at": "2026-03-09T00:05:51+00:00",
            "fill_proxy": {
                "full_fill_proxy_rate": None,
                "wilson_low": None,
            },
            "a6_replay": {
                "observed_persistence_lower_bound_seconds": 0.0,
            },
            "b1": {
                "b1_half_life_lower_bound_seconds": None,
                "classification_accuracy": None,
                "false_positive_rate": None,
            },
            "settlement": {
                "total": 0,
            },
            "repo_truth": {
                "public_a6_audit": {
                    "execute_threshold": 0.95,
                    "executable_constructions_below_threshold": 0,
                },
                "public_b1_audit": {
                    "allowed_market_sample_size": 1000,
                    "deterministic_template_pair_count": 0,
                },
            },
        }

        snapshot["lane_status"] = evaluate_lane_statuses(snapshot)
        gate_pack = build_structural_gate_pack(snapshot, source_snapshot="reports/arb_empirical_snapshot.json")

        self.assertEqual(gate_pack["source_snapshot"], "reports/arb_empirical_snapshot.json")

        a6 = gate_pack["per_lane_status"]["a6"]
        self.assertEqual(a6["status"], "blocked")
        self.assertIn("maker_fill_proxy_unmeasured", a6["blocked_reasons"])
        self.assertEqual(a6["current_metrics"]["public_a6_executable_count"], 0)
        self.assertEqual(
            a6["required_thresholds"]["ready_for_shadow"]["maker_fill_wilson_lower"],
            {"comparison": ">", "value": 0.2},
        )
        self.assertIsNone(a6["threshold_deltas"]["ready_for_shadow"]["maker_fill_wilson_lower"])
        self.assertEqual(a6["threshold_deltas"]["ready_for_shadow"]["violation_half_life_seconds"], -10.0)
        self.assertEqual(a6["threshold_deltas"]["ready_for_micro_live"]["settlement_evidence_count"], -3.0)
        self.assertFalse(a6["stage_readiness"]["ready_for_shadow"])
        self.assertFalse(a6["stage_readiness"]["ready_for_micro_live"])

        b1 = gate_pack["per_lane_status"]["b1"]
        self.assertEqual(b1["status"], "blocked")
        self.assertIn("classification_accuracy_unmeasured", b1["blocked_reasons"])
        self.assertEqual(
            b1["required_thresholds"]["ready_for_shadow"]["false_positive_rate"],
            {"comparison": "<=", "value": 0.05},
        )
        self.assertIsNone(b1["threshold_deltas"]["ready_for_shadow"]["classification_accuracy"])
        self.assertEqual(b1["threshold_deltas"]["ready_for_shadow"]["public_b1_template_pair_count"], -1.0)
        self.assertEqual(b1["threshold_deltas"]["ready_for_micro_live"]["settlement_evidence_count"], -3.0)
        self.assertFalse(b1["stage_readiness"]["ready_for_shadow"])
        self.assertFalse(b1["stage_readiness"]["ready_for_micro_live"])


if __name__ == "__main__":
    unittest.main()
