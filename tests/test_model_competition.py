import unittest

from src.backtest import walk_forward_model_competition


class TestModelCompetition(unittest.TestCase):
    def test_walk_forward_model_competition_includes_bootstrap_ensemble(self) -> None:
        features: list[dict[str, float | int | str]] = []
        base_ts = 1_700_300_000
        for idx in range(120):
            up = idx % 2 == 0
            signed = 1.0 if up else -1.0
            features.append(
                {
                    "condition_id": f"c{idx}",
                    "timeframe": "15m",
                    "timestamp_ts": base_ts + (idx * 60),
                    "label_up": 1 if up else 0,
                    "yes_price": 0.42 if up else 0.58,
                    "btc_price": 100.0 + idx,
                    "open_price": 100.0,
                    "btc_return_since_open": 0.010 * signed,
                    "btc_return_60s": 0.002 * signed,
                    "realized_vol_30m": 0.012,
                    "realized_vol_1h": 0.014,
                    "realized_vol_2h": 0.016,
                    "vol_ratio_30m_2h": 0.75,
                    "range_position_2h": 0.62 if up else 0.38,
                    "ma_gap_15m": 0.010 * signed,
                    "ma_gap_30m": 0.008 * signed,
                    "momentum_15m": 0.009 * signed,
                    "momentum_30m": 0.007 * signed,
                    "rsi_14": 38.0 if up else 62.0,
                    "macd_hist": 0.004 * signed,
                    "bollinger_zscore_20": -1.1 if up else 1.1,
                    "trade_count_60s": 18,
                    "trade_flow_imbalance": 0.20 * signed,
                    "book_imbalance": 0.10 * signed,
                    "basis_lag_score": 0.05 * signed,
                    "time_remaining_sec": 480,
                    "inner_up_bias": 0.65 if up else 0.35,
                    "prev_window_return": 0.006 * signed,
                    "hour_utc": idx % 24,
                    "weekday": idx % 7,
                    "mu_per_sec": 0.0,
                    "sigma_per_sqrt_sec": 1e-4,
                }
            )

        results = walk_forward_model_competition(features, model_seed=11, mc_paths=500)
        model_names = {row["model"] for row in results}

        self.assertIn("Bootstrap ensemble", model_names)


if __name__ == "__main__":
    unittest.main()
