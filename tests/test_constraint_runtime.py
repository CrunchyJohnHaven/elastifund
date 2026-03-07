import unittest

from bot.constraint_arb_engine import (
    RelationClassifier,
    RelationResult,
    _extract_yes_quote,
    parse_clob_token_ids,
)
from bot.resolution_normalizer import normalize_market


class TestConstraintRuntimeHelpers(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        question: str,
        outcome: str = "Yes",
        outcomes: list[str] | None = None,
    ) -> dict:
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": outcome,
            "outcomes": outcomes or ["Yes", "No"],
            "category": "politics",
            "resolutionSource": "Associated Press",
            "endDate": "2026-11-03T23:59:00Z",
            "rules": "Resolves using Associated Press.",
        }

    def test_parse_clob_token_ids_accepts_json_string(self) -> None:
        yes, no = parse_clob_token_ids('["yes-token","no-token"]')
        self.assertEqual(yes, "yes-token")
        self.assertEqual(no, "no-token")

    def test_parse_clob_token_ids_accepts_csv_string(self) -> None:
        yes, no = parse_clob_token_ids("yes-token,no-token")
        self.assertEqual(yes, "yes-token")
        self.assertEqual(no, "no-token")

    def test_extract_yes_quote_uses_best_bid_ask_when_present(self) -> None:
        yes_bid, yes_ask = _extract_yes_quote(
            {
                "bestBid": "0.42",
                "bestAsk": "0.46",
                "outcomePrices": "[0.40,0.60]",
            }
        )
        self.assertAlmostEqual(yes_bid, 0.42)
        self.assertAlmostEqual(yes_ask, 0.46)

    def test_extract_yes_quote_falls_back_to_outcome_prices(self) -> None:
        yes_bid, yes_ask = _extract_yes_quote({"outcomePrices": "[0.33,0.67]"})
        self.assertAlmostEqual(yes_bid, 0.33)
        self.assertAlmostEqual(yes_ask, 0.33)

    def test_debate_fallback_called_only_after_heuristic_prefilter(self) -> None:
        calls: list[tuple[str, str]] = []

        def fallback(market_a, market_b):
            calls.append((market_a.market_id, market_b.market_id))
            return RelationResult("A_implies_B", 0.7, "mock_fallback")

        classifier = RelationClassifier(debate_fallback=fallback)

        # Hard threshold implication should bypass fallback.
        threshold_a = normalize_market(
            self._mk_market(
                market_id="a1",
                event_id="evt-1",
                question="Will CPI be above 4.0 by June 2026?",
            )
        )
        threshold_b = normalize_market(
            self._mk_market(
                market_id="b1",
                event_id="evt-2",
                question="Will CPI be above 3.0 by June 2026?",
            )
        )
        result_threshold = classifier.classify(threshold_a, threshold_b)
        self.assertEqual(result_threshold.relation_type, "A_implies_B")
        self.assertEqual(calls, [])

        # Unresolved pair should invoke fallback exactly once.
        unresolved_a = normalize_market(
            self._mk_market(
                market_id="a2",
                event_id="evt-3",
                question="Will incumbent party gain seats in June 2026?",
            )
        )
        unresolved_b = normalize_market(
            self._mk_market(
                market_id="b2",
                event_id="evt-4",
                question="Will coalition parties lose vote share in June 2026?",
            )
        )
        result_unresolved = classifier.classify(unresolved_a, unresolved_b)
        self.assertEqual(result_unresolved.reason, "mock_fallback")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
