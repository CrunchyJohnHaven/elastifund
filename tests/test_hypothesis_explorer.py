import unittest

from src.config import BacktestConfig
from src.hypothesis_explorer import FlowHypothesisExplorer


class TestFlowHypothesisExplorer(unittest.TestCase):
    def test_explorer_runs_and_ranks_variants(self) -> None:
        features: list[dict] = []
        resolutions: dict[str, str] = {}

        base_ts = 1_700_000_000
        for i in range(40):
            condition_id = f"c{i}"
            outcome = "UP" if i < 30 else "DOWN"
            resolutions[condition_id] = outcome

            features.append(
                {
                    "condition_id": condition_id,
                    "timeframe": "15m",
                    "timestamp_ts": base_ts + (i * 3),
                    "window_start_ts": base_ts + (i * 3) - 40,
                    "yes_price": 0.42,
                    "no_price": 0.58,
                    "wallet_signal_wallets": 4,
                    "wallet_signal_trades": 28,
                    "wallet_up_bias": 0.55,
                    "wallet_avg_win_rate": 0.62,
                    "wallet_consensus_strength": 0.90,
                    "trade_flow_imbalance": 0.35,
                    "book_imbalance": 0.15,
                    "basis_lag_score": 0.08,
                }
            )

        explorer = FlowHypothesisExplorer(BacktestConfig())
        output = explorer.run(features, resolutions)

        self.assertGreater(output["tested_variants"], 0)
        self.assertEqual(output["tested_variants"], len(output["variants"]))
        self.assertIn(output["verdict"], {"PAPER_TEST_CANDIDATE", "CONTINUE_DATA_COLLECTION", "REJECT_ALL_VARIANTS"})
        self.assertIsNotNone(output["best_variant_label"])
        self.assertIn("gate_status", output["variants"][0])
        self.assertIn("maker_fill_sensitivity", output["variants"][0])


if __name__ == "__main__":
    unittest.main()
