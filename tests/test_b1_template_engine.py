from __future__ import annotations

import unittest

from bot.b1_template_engine import compatibility_matrix_for_relation, match_template_pair
from bot.resolution_normalizer import NormalizedMarket, ResolutionProfile


def _mk_market(market_id: str, question: str) -> NormalizedMarket:
    return NormalizedMarket(
        market_id=market_id,
        event_id=f"evt-{market_id}",
        question=question,
        category="politics",
        outcomes=("Yes", "No"),
        outcome="Yes",
        resolution_text="Test resolution",
        is_multi_outcome=False,
        yes_token_id=f"yes-{market_id}",
        no_token_id=f"no-{market_id}",
        tick_size=0.01,
        min_order_size=1.0,
        accepting_orders=True,
        enable_order_book=True,
        profile=ResolutionProfile(
            source="Associated Press",
            cutoff_ts=1_700_000_000,
            scope_fingerprint=("politics",),
            geography_scope=tuple(),
            office_scope=tuple(),
            event_identity=tuple(),
            ontology=("no", "yes"),
            named_outcomes=tuple(),
            outcome_kind="binary",
            is_neg_risk=False,
            is_augmented_neg_risk=False,
            has_other_outcome=False,
            has_placeholder_outcome=False,
            has_catch_all_outcome=False,
            has_ambiguous_named_mapping=False,
        ),
        resolution_key=f"rk-{market_id}",
    )


class TestB1TemplateEngine(unittest.TestCase):
    def test_margin_implies_winner(self) -> None:
        margin = _mk_market("m1", "Will Alice win Pennsylvania by 5 points or more?")
        winner = _mk_market("m2", "Will Alice win Pennsylvania?")

        match = match_template_pair(margin, winner)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.family, "state_winner_margin")
        self.assertEqual(match.relation_type, "A_implies_B")
        self.assertFalse(match.compatibility_matrix["YN"])

    def test_composite_pop_vote_market_implies_component(self) -> None:
        composite = _mk_market("m1", "Will Alice win both the popular vote and the electoral college?")
        component = _mk_market("m2", "Will Alice win the popular vote?")

        match = match_template_pair(composite, component)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.family, "winner_popular_vote_ec")
        self.assertEqual(match.relation_type, "A_implies_B")

    def test_balance_of_power_composite_implies_chamber_component(self) -> None:
        composite = _mk_market("m1", "Will Democrats win both the House and Senate?")
        component = _mk_market("m2", "Will Democrats control the House?")

        match = match_template_pair(composite, component)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.family, "winner_balance_of_power")
        self.assertEqual(match.relation_type, "A_implies_B")

    def test_relation_matrix_helper(self) -> None:
        matrix = compatibility_matrix_for_relation("mutually_exclusive")
        self.assertFalse(matrix["YY"])
        self.assertTrue(matrix["YN"])
        self.assertTrue(matrix["NY"])
        self.assertTrue(matrix["NN"])


if __name__ == "__main__":
    unittest.main()
