import unittest

from src.feature_engineering import FeatureEngineer


class TestFeatureIndicators(unittest.TestCase):
    def setUp(self) -> None:
        self.engineer = FeatureEngineer("data/edge_discovery.db")

    def test_indicator_helpers_capture_uptrend(self) -> None:
        series = [100.0 + (idx * 0.75) for idx in range(40)]

        rsi = self.engineer._rsi(series, period=14)
        macd_line, macd_signal, macd_hist = self.engineer._macd(series)
        bollinger_z, bollinger_bw = self.engineer._bollinger(series, period=20)

        self.assertGreater(rsi, 70.0)
        self.assertGreater(macd_line, 0.0)
        self.assertGreater(macd_signal, 0.0)
        self.assertGreaterEqual(macd_hist, -1e-6)
        self.assertGreater(bollinger_z, 0.0)
        self.assertGreater(bollinger_bw, 0.0)

    def test_sampled_series_respects_requested_window(self) -> None:
        btc_ts = [idx * 60 for idx in range(8)]
        btc_prices = [100.0 + idx for idx in range(8)]

        sampled = self.engineer._sampled_series(
            300,
            btc_ts,
            btc_prices,
            window_sec=180,
            step_sec=60,
        )

        self.assertEqual(sampled, [102.0, 103.0, 104.0, 105.0])


if __name__ == "__main__":
    unittest.main()
