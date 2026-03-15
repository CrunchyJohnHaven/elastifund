import unittest

from bot.neg_risk_inventory import NegRiskInventory
from bot.resolution_normalizer import (
    evaluate_event_tradability,
    is_tradable_outcome,
    normalize_market,
    resolution_equivalence_gate,
)


class TestNegRiskFilters(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        question: str,
        outcome: str,
        outcomes: list[str],
        neg_risk: bool = True,
        augmented: bool = False,
        source: str = "Associated Press",
        end_date: str = "2026-11-03T23:59:00Z",
    ) -> dict:
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": outcome,
            "outcomes": outcomes,
            "category": "politics",
            "negRisk": neg_risk,
            "negRiskAugmented": augmented,
            "resolutionSource": source,
            "endDate": end_date,
            "rules": f"Resolves using {source} at {end_date}.",
        }

    def test_augmented_other_outcome_blocked(self) -> None:
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-a",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=["Alice", "Bob", "Other"],
                    augmented=True,
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-a",
                    question="Who wins? Bob",
                    outcome="Bob",
                    outcomes=["Alice", "Bob", "Other"],
                    augmented=True,
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="other",
                    event_id="evt-a",
                    question="Who wins? Other",
                    outcome="Other",
                    outcomes=["Alice", "Bob", "Other"],
                    augmented=True,
                )
            ),
        ]
        self.assertFalse(is_tradable_outcome(markets[2], "Other"))
        self.assertTrue(is_tradable_outcome(markets[0], "Alice"))

        tradability = evaluate_event_tradability(markets)
        self.assertEqual(tradability.status, "hard_blocked")
        self.assertIn("augmented_other_bucket_present", tradability.reasons)

    def test_resolution_gate_rejects_source_and_cutoff_mismatch(self) -> None:
        a = normalize_market(
            self._mk_market(
                market_id="a",
                event_id="evt-1",
                question="Will Alice win the election?",
                outcome="Yes",
                outcomes=["Yes", "No"],
                source="Associated Press",
                end_date="2026-11-03T23:59:00Z",
            )
        )
        b = normalize_market(
            self._mk_market(
                market_id="b",
                event_id="evt-2",
                question="Will Alice win the election?",
                outcome="Yes",
                outcomes=["Yes", "No"],
                source="Decision Desk HQ",
                end_date="2026-10-01T23:59:00Z",
            )
        )

        gate = resolution_equivalence_gate([a, b], cutoff_tolerance_hours=24)
        self.assertFalse(gate.passed)
        self.assertEqual(gate.safety_status, "hard_blocked")
        self.assertIn("source_mismatch", gate.reasons)
        self.assertIn("cutoff_mismatch", gate.reasons)

    def test_augmented_catch_all_and_placeholder_event_blocked(self) -> None:
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-catch",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=["Alice", "Field", "TBD"],
                    augmented=True,
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="field",
                    event_id="evt-catch",
                    question="Who wins? Field",
                    outcome="Field",
                    outcomes=["Alice", "Field", "TBD"],
                    augmented=True,
                )
            ),
        ]

        tradability = evaluate_event_tradability(markets)
        self.assertEqual(tradability.status, "hard_blocked")
        self.assertIn("augmented_catch_all_bucket_present", tradability.reasons)
        self.assertIn("augmented_placeholder_outcome_present", tradability.reasons)

    def test_neg_risk_conversion_bookkeeping(self) -> None:
        inventory = NegRiskInventory()

        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-nr",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=["Alice", "Bob", "Carol"],
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-nr",
                    question="Who wins? Bob",
                    outcome="Bob",
                    outcomes=["Alice", "Bob", "Carol"],
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="carol",
                    event_id="evt-nr",
                    question="Who wins? Carol",
                    outcome="Carol",
                    outcomes=["Alice", "Bob", "Carol"],
                )
            ),
        ]
        inventory.register_markets(markets)

        self.assertEqual(inventory.route_exchange(markets[0]), "neg_risk_ctf_exchange")

        inventory.record_fill(
            event_id="evt-nr",
            outcome="Alice",
            side="NO",
            quantity=5.0,
            price=0.42,
        )
        record = inventory.convert_no_to_yes_others(
            event_id="evt-nr",
            outcome="Alice",
            quantity=3.0,
        )

        self.assertEqual(record.event_id, "evt-nr")
        self.assertEqual(inventory.quantity("evt-nr", "Alice", "NO"), 2.0)
        self.assertEqual(inventory.quantity("evt-nr", "Bob", "YES"), 3.0)
        self.assertEqual(inventory.quantity("evt-nr", "Carol", "YES"), 3.0)
        self.assertEqual(inventory.event_tradability("evt-nr").status, "tradable")

    def test_conversion_requires_no_inventory(self) -> None:
        inventory = NegRiskInventory()
        with self.assertRaises(ValueError):
            inventory.convert_no_to_yes_others(event_id="evt-x", outcome="Alice", quantity=1.0)

    def test_validate_order_uses_event_level_safety(self) -> None:
        inventory = NegRiskInventory()
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-blocked",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=["Alice", "Bob", "Other"],
                    augmented=True,
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="evt-blocked",
                    question="Who wins? Bob",
                    outcome="Bob",
                    outcomes=["Alice", "Bob", "Other"],
                    augmented=True,
                )
            ),
        ]
        inventory.register_markets(markets)

        self.assertFalse(inventory.validate_order(markets[0], "Alice"))
        self.assertIn("augmented_other_bucket_present", inventory.order_block_reasons(markets[0], "Alice"))

    def test_safety_matrix_reports_blocked_and_tradable_events(self) -> None:
        inventory = NegRiskInventory()
        inventory.register_markets(
            [
                normalize_market(
                    self._mk_market(
                        market_id="alice",
                        event_id="evt-tradable",
                        question="Who wins? Alice",
                        outcome="Alice",
                        outcomes=["Alice", "Bob"],
                    )
                ),
                normalize_market(
                    self._mk_market(
                        market_id="bob",
                        event_id="evt-tradable",
                        question="Who wins? Bob",
                        outcome="Bob",
                        outcomes=["Alice", "Bob"],
                    )
                ),
                normalize_market(
                    self._mk_market(
                        market_id="other",
                        event_id="evt-blocked",
                        question="Who wins? Other",
                        outcome="Other",
                        outcomes=["Alice", "Bob", "Other"],
                        augmented=True,
                    )
                ),
            ]
        )

        matrix = {row.event_id: row for row in inventory.safety_matrix()}
        self.assertEqual(matrix["evt-tradable"].status, "tradable")
        self.assertEqual(matrix["evt-blocked"].status, "hard_blocked")

    def test_merge_bookkeeping_reduces_offsetting_inventory(self) -> None:
        inventory = NegRiskInventory()
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="evt-merge",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=["Alice", "Bob"],
                )
            ),
        ]
        inventory.register_markets(markets)
        inventory.record_fill(
            event_id="evt-merge",
            outcome="Alice",
            side="YES",
            quantity=4.0,
            price=0.61,
        )
        inventory.record_fill(
            event_id="evt-merge",
            outcome="Alice",
            side="NO",
            quantity=6.0,
            price=0.39,
        )

        record = inventory.apply_merge(
            event_id="evt-merge",
            outcome="Alice",
            quantity=3.0,
            tx_hash="0xabc",
        )

        self.assertEqual(record.quantity, 3.0)
        self.assertEqual(record.tx_hash, "0xabc")
        self.assertEqual(inventory.quantity("evt-merge", "Alice", "YES"), 1.0)
        self.assertEqual(inventory.quantity("evt-merge", "Alice", "NO"), 3.0)
        self.assertEqual(len(inventory.merges()), 1)

    def test_normalize_market_uses_gamma_events_id_when_eventid_missing(self) -> None:
        market = normalize_market(
            {
                "id": "m-1",
                "eventId": None,
                "events": [{"id": "24383", "slug": "harvey-weinstein-prison-time"}],
                "question": "Will Harvey Weinstein be sentenced to no prison time?",
                "groupItemTitle": ": No Prison Time",
                "outcomes": ["Yes", "No"],
                "negRisk": True,
                "endDate": "2026-07-31T23:59:00Z",
                "resolutionSource": "Court filing",
            }
        )
        self.assertEqual(market.event_id, "24383")

    def test_normalize_market_uses_group_item_title_for_outcome(self) -> None:
        market = normalize_market(
            {
                "id": "m-2",
                "events": [{"id": "e-2"}],
                "question": "How many years of prison time for X?",
                "outcome": None,
                "groupItemTitle": " : 5+ years",
                "outcomes": ["Yes", "No"],
                "negRisk": True,
                "endDate": "2026-07-31T23:59:00Z",
                "resolutionSource": "Court filing",
            }
        )
        self.assertEqual(market.outcome, "5+ years")


if __name__ == "__main__":
    unittest.main()
