import unittest

from src.models.baseline import ClosedFormInput, closed_form_up_probability


class TestFairValue(unittest.TestCase):
    def test_symmetry_near_half(self) -> None:
        p = closed_form_up_probability(
            ClosedFormInput(
                current_price=100.0,
                open_price=100.0,
                mu_per_sec=0.0,
                sigma_per_sqrt_sec=0.0005,
                time_remaining_sec=300,
            )
        )
        self.assertTrue(0.45 <= p <= 0.55)

    def test_directional_shift(self) -> None:
        p = closed_form_up_probability(
            ClosedFormInput(
                current_price=102.0,
                open_price=100.0,
                mu_per_sec=0.0,
                sigma_per_sqrt_sec=0.0005,
                time_remaining_sec=300,
            )
        )
        self.assertGreater(p, 0.5)


if __name__ == "__main__":
    unittest.main()
