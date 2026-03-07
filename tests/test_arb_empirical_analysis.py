from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.arb_empirical_analysis import (
    PassiveOrderProbe,
    ReplayViolationRow,
    build_violation_episodes,
    measure_fill_proxy,
    midpoint_bucket,
    recommend_a6_thresholds,
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
        self.assertAlmostEqual(bucket["recommended_sum_yes_ask_threshold"], 0.9682)
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


if __name__ == "__main__":
    unittest.main()
