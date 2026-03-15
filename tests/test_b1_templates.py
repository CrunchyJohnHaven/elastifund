import unittest

from strategies.b1_dependency_graph import MarketMeta
from strategies.b1_templates import build_templated_pairs, describe_market, infer_pair_compatibility


def _market(market_id: str, question: str) -> MarketMeta:
    return MarketMeta(
        market_id=market_id,
        event_id="evt-1",
        question=question,
        description="",
        category="politics",
        subcategory="elections",
        end_date_iso="2026-11-03T23:59:00Z",
        yes_token_id=f"yes-{market_id}",
        no_token_id=f"no-{market_id}",
        neg_risk=False,
        text_hash=f"hash-{market_id}",
    )


class TestB1Templates(unittest.TestCase):
    def test_describe_market_detects_composite_family(self) -> None:
        descriptor = describe_market(
            _market("m1", "Will Democrats win both the presidency and the House?")
        )
        self.assertIsNotNone(descriptor)
        assert descriptor is not None
        self.assertEqual(descriptor.family, "winner_balance_of_power")
        self.assertEqual(len(descriptor.components), 2)

    def test_infers_winner_margin_implication(self) -> None:
        outright = _market("a", "Will Alice win the Texas Senate race?")
        margin = _market("b", "Will Alice win the Texas Senate race by more than 5 points?")

        compatibility = infer_pair_compatibility(outright, margin)

        self.assertIsNotNone(compatibility)
        assert compatibility is not None
        self.assertEqual(compatibility.label, "B_implies_A")
        self.assertFalse(compatibility.matrix["NY"])
        self.assertTrue(compatibility.matrix["YN"])

    def test_infers_composite_market_implication(self) -> None:
        composite = _market("a", "Will Democrats win both the presidency and the House?")
        component = _market("b", "Will Democrats win the House?")

        compatibility = infer_pair_compatibility(composite, component)

        self.assertIsNotNone(compatibility)
        assert compatibility is not None
        self.assertEqual(compatibility.label, "A_implies_B")
        self.assertFalse(compatibility.matrix["YN"])

    def test_build_templated_pairs_returns_only_supported_templates(self) -> None:
        supported = build_templated_pairs(
            [
                _market("a", "Will Alice win the Texas Senate race?"),
                _market("b", "Will Alice win the Texas Senate race by more than 5 points?"),
                _market("c", "Will GDP grow above 3% in Q4 2026?"),
            ]
        )

        self.assertEqual(len(supported), 1)
        self.assertEqual(supported[0].family, "state_winner_margin")


if __name__ == "__main__":
    unittest.main()
