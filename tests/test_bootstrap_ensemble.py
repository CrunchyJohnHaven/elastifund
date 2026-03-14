import unittest

from src.models.bootstrap_ensemble import BootstrapEnsembleClassifier


class TestBootstrapEnsemble(unittest.TestCase):
    def test_predict_distribution_returns_ordered_summary(self) -> None:
        feature_names = ["yes_price", "momentum_15m", "macd_hist"]
        train_rows: list[dict[str, float]] = []
        labels: list[int] = []

        for idx in range(160):
            yes_price = 0.20 + (0.004 * idx)
            momentum = yes_price - 0.50
            macd_hist = momentum * 0.12
            label = 1 if (0.55 * yes_price) + (2.2 * momentum) + (4.0 * macd_hist) > 0.05 else 0
            train_rows.append(
                {
                    "yes_price": yes_price,
                    "momentum_15m": momentum,
                    "macd_hist": macd_hist,
                }
            )
            labels.append(label)

        predict_rows = [
            {"yes_price": 0.72, "momentum_15m": 0.18, "macd_hist": 0.020},
            {"yes_price": 0.30, "momentum_15m": -0.16, "macd_hist": -0.018},
        ]

        ensemble = BootstrapEnsembleClassifier(feature_names, members=9, min_rows=40, seed=7)
        predictions = ensemble.predict_distribution(train_rows, labels, predict_rows)

        self.assertEqual(len(predictions), 2)
        self.assertEqual(predictions[0].members, 9)
        self.assertGreater(predictions[0].mean_prob, predictions[1].mean_prob)
        self.assertGreaterEqual(predictions[0].p90_prob, predictions[0].p10_prob)
        self.assertGreaterEqual(predictions[0].consensus_fraction, 0.5)


if __name__ == "__main__":
    unittest.main()
