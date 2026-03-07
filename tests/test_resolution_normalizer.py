import unittest

from bot.resolution_normalizer import evaluate_event_tradability, normalize_market, resolution_equivalence_gate


class TestResolutionNormalizer(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        question: str,
        outcome: str = "Yes",
        outcomes: list[str] | None = None,
        source: str = "Associated Press",
        end_date: str | None = "2026-11-03T23:59:00Z",
        rules: str | None = None,
        augmented: bool = False,
    ) -> dict:
        base_rules = rules
        if base_rules is None and source and end_date:
            base_rules = f"Resolves using {source} at {end_date}."
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": outcome,
            "outcomes": outcomes or ["Yes", "No"],
            "category": "politics",
            "negRisk": True,
            "negRiskAugmented": augmented,
            "resolutionSource": source,
            "endDate": end_date,
            "rules": base_rules,
        }

    def test_resolution_gate_blocks_same_candidate_different_office(self) -> None:
        presidency = normalize_market(
            self._mk_market(
                market_id="pres",
                event_id="evt-pres",
                question="Will Alice win the presidency in 2028?",
            )
        )
        governor = normalize_market(
            self._mk_market(
                market_id="gov",
                event_id="evt-gov",
                question="Will Alice win the governorship of California in 2028?",
            )
        )

        gate = resolution_equivalence_gate([presidency, governor])
        self.assertFalse(gate.passed)
        self.assertEqual(gate.safety_status, "hard_blocked")
        self.assertIn("office_mismatch", gate.reasons)

    def test_resolution_gate_blocks_same_office_different_geography(self) -> None:
        texas = normalize_market(
            self._mk_market(
                market_id="tx",
                event_id="evt-tx",
                question="Will Alice win the governor race in Texas?",
            )
        )
        california = normalize_market(
            self._mk_market(
                market_id="ca",
                event_id="evt-ca",
                question="Will Alice win the governor race in California?",
            )
        )

        gate = resolution_equivalence_gate([texas, california])
        self.assertFalse(gate.passed)
        self.assertIn("geography_mismatch", gate.reasons)

    def test_resolution_gate_blocks_named_vs_binary_umbrella_market(self) -> None:
        named = normalize_market(
            self._mk_market(
                market_id="named",
                event_id="evt-mayor",
                question="Who will win the 2028 mayor race? Alice",
                outcome="Alice",
                outcomes=["Alice", "Bob", "Carol"],
            )
        )
        umbrella = normalize_market(
            self._mk_market(
                market_id="umbrella",
                event_id="evt-umbrella",
                question="Will a Democrat win the 2028 mayor race?",
                outcomes=["Yes", "No"],
            )
        )

        gate = resolution_equivalence_gate([named, umbrella])
        self.assertFalse(gate.passed)
        self.assertIn("ontology_kind_mismatch", gate.reasons)

    def test_resolution_gate_logs_unknown_source_and_cutoff(self) -> None:
        left = normalize_market(
            self._mk_market(
                market_id="left",
                event_id="evt-left",
                question="Will CPI be above 3.0 in June 2026?",
                source="",
                end_date=None,
                rules="",
            )
        )
        right = normalize_market(
            self._mk_market(
                market_id="right",
                event_id="evt-right",
                question="Will CPI be above 3.5 in June 2026?",
                source="",
                end_date=None,
                rules="",
            )
        )

        gate = resolution_equivalence_gate([left, right])
        self.assertFalse(gate.passed)
        self.assertEqual(gate.safety_status, "log_only")
        self.assertIn("source_uncertain", gate.reasons)
        self.assertIn("cutoff_uncertain", gate.reasons)

    def test_augmented_duplicate_named_mapping_is_hard_blocked(self) -> None:
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="a",
                    event_id="evt-dup",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=["Alice", "Alice ", "Bob"],
                    augmented=True,
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="b",
                    event_id="evt-dup",
                    question="Who wins? Bob",
                    outcome="Bob",
                    outcomes=["Alice", "Alice ", "Bob"],
                    augmented=True,
                )
            ),
        ]

        tradability = evaluate_event_tradability(markets)
        self.assertEqual(tradability.status, "hard_blocked")
        self.assertIn("named_outcome_mapping_ambiguous", tradability.reasons)


if __name__ == "__main__":
    unittest.main()
