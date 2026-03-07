import unittest

from src.models.mc_engine import MCParams, MonteCarloEngine


class TestMCEngine(unittest.TestCase):
    def test_deterministic_seed(self) -> None:
        engine = MonteCarloEngine(seed=42)
        params = MCParams(
            s0=100.0,
            mu_per_sec=0.0,
            sigma_per_sqrt_sec=0.0005,
            horizon_sec=60,
            paths=200,
            seed=7,
        )
        a = engine.simulate_gbm(params)
        b = engine.simulate_gbm(params)
        self.assertEqual(a, b)

    def test_probability_bounds(self) -> None:
        engine = MonteCarloEngine()
        prob = engine.probability_close_above([101, 99, 102, 98], 100)
        self.assertTrue(0.0 <= prob <= 1.0)


if __name__ == "__main__":
    unittest.main()
