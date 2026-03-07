import sqlite3
import tempfile
import unittest
from pathlib import Path

from bot.constraint_arb_engine import CandidateGenerator, ConstraintArbDB, ConstraintArbEngine, ConstraintViolation, RelationClassifier
from bot.resolution_normalizer import normalize_market


class TestConstraintGraph(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        question: str,
        outcome: str,
        outcomes: list[str],
        category: str = "politics",
        neg_risk: bool = True,
        augmented: bool = False,
        end_date: str = "2026-11-03T23:59:00Z",
        source: str = "Associated Press",
    ) -> dict:
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": outcome,
            "outcomes": outcomes,
            "category": category,
            "negRisk": neg_risk,
            "negRiskAugmented": augmented,
            "resolutionSource": source,
            "endDate": end_date,
            "rules": f"Resolves using {source} at {end_date}.",
        }

    def test_candidate_generator_same_event_priority(self) -> None:
        generator = CandidateGenerator()
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="m1",
                    event_id="evt-a",
                    question="Will Alice win the 2026 mayor race?",
                    outcome="Alice",
                    outcomes=["Alice", "Bob"],
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="m2",
                    event_id="evt-a",
                    question="Will Bob win the 2026 mayor race?",
                    outcome="Bob",
                    outcomes=["Alice", "Bob"],
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="m3",
                    event_id="evt-b",
                    question="Will CPI be above 3.0 by June 2026?",
                    outcome="Yes",
                    outcomes=["Yes", "No"],
                )
            ),
        ]

        pairs = generator.generate(markets, max_pairs=10)
        ids = {tuple(sorted((a.market_id, b.market_id))) for a, b in pairs}
        self.assertIn(("m1", "m2"), ids)

    def test_candidate_generator_enforces_resolution_window(self) -> None:
        generator = CandidateGenerator(resolution_window_hours=72)
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="m1",
                    event_id="evt-a",
                    question="Will CPI be above 3.0 by June 2026?",
                    outcome="Yes",
                    outcomes=["Yes", "No"],
                    end_date="2026-06-01T12:00:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="m2",
                    event_id="evt-b",
                    question="Will CPI be above 3.5 by June 2026?",
                    outcome="Yes",
                    outcomes=["Yes", "No"],
                    end_date="2026-06-02T12:00:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="m3",
                    event_id="evt-c",
                    question="Will CPI be above 4.0 by June 2026?",
                    outcome="Yes",
                    outcomes=["Yes", "No"],
                    end_date="2026-06-15T12:00:00Z",
                )
            ),
        ]

        pairs = generator.generate(markets, max_pairs=10)
        ids = {tuple(sorted((a.market_id, b.market_id))) for a, b in pairs}
        self.assertIn(("m1", "m2"), ids)
        self.assertNotIn(("m1", "m3"), ids)

    def test_relation_classifier_detects_threshold_implication(self) -> None:
        classifier = RelationClassifier()
        a = normalize_market(
            self._mk_market(
                market_id="a",
                event_id="evt-1",
                question="Will CPI be above 4.0 by June 2026?",
                outcome="Yes",
                outcomes=["Yes", "No"],
            )
        )
        b = normalize_market(
            self._mk_market(
                market_id="b",
                event_id="evt-2",
                question="Will CPI be above 3.0 by June 2026?",
                outcome="Yes",
                outcomes=["Yes", "No"],
            )
        )

        rel = classifier.classify(a, b)
        self.assertEqual(rel.relation_type, "A_implies_B")

    def test_sum_violation_executable_prices_stale_drop_and_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint.db"
            engine = ConstraintArbEngine(
                db_path=db_path,
                buy_threshold=0.97,
                stale_quote_seconds=5,
                snapshot_dedupe_seconds=15,
            )

            outcomes = ["Alice", "Bob", "Other"]
            markets = [
                self._mk_market(
                    market_id="alice",
                    event_id="evt-aug",
                    question="Who will win? Alice",
                    outcome="Alice",
                    outcomes=outcomes,
                    augmented=True,
                ),
                self._mk_market(
                    market_id="bob",
                    event_id="evt-aug",
                    question="Who will win? Bob",
                    outcome="Bob",
                    outcomes=outcomes,
                    augmented=True,
                ),
                self._mk_market(
                    market_id="other",
                    event_id="evt-aug",
                    question="Who will win? Other",
                    outcome="Other",
                    outcomes=outcomes,
                    augmented=True,
                ),
            ]
            engine.register_markets(markets)

            now_ts = 1_700_000_000
            engine.update_quote(market_id="alice", yes_bid=0.30, yes_ask=0.31, updated_ts=now_ts)
            engine.update_quote(market_id="bob", yes_bid=0.31, yes_ask=0.32, updated_ts=now_ts)
            engine.update_quote(market_id="other", yes_bid=0.09, yes_ask=0.10, updated_ts=now_ts)

            violations = engine.scan_sum_violations(now_ts=now_ts)
            self.assertEqual(len(violations), 1)
            v = violations[0]
            # "Other" must be excluded in augmented neg-risk sums.
            self.assertAlmostEqual(v.details["sum_yes_ask"], 0.63, places=6)

            # Same event snapshot should dedupe.
            second = engine.scan_sum_violations(now_ts=now_ts)
            self.assertEqual(second, [])

            # If one leg is stale, event should no longer produce tradable basket.
            later = now_ts + 30
            engine.update_quote(market_id="alice", yes_bid=0.30, yes_ask=0.31, updated_ts=later)
            stale_scan = engine.scan_sum_violations(now_ts=later)
            self.assertEqual(stale_scan, [])

    def test_underround_requires_complete_event_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint.db"
            engine = ConstraintArbEngine(db_path=db_path, buy_threshold=0.97)

            outcomes = ["Alice", "Bob", "Carol", "Dave"]
            markets = [
                self._mk_market(
                    market_id="alice",
                    event_id="evt-complete",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=outcomes,
                ),
                self._mk_market(
                    market_id="bob",
                    event_id="evt-complete",
                    question="Who wins? Bob",
                    outcome="Bob",
                    outcomes=outcomes,
                ),
                self._mk_market(
                    market_id="carol",
                    event_id="evt-complete",
                    question="Who wins? Carol",
                    outcome="Carol",
                    outcomes=outcomes,
                ),
                self._mk_market(
                    market_id="dave",
                    event_id="evt-complete",
                    question="Who wins? Dave",
                    outcome="Dave",
                    outcomes=outcomes,
                ),
            ]
            engine.register_markets(markets)

            now_ts = 1_700_000_000
            engine.update_quote(market_id="alice", yes_bid=0.29, yes_ask=0.30, updated_ts=now_ts)
            engine.update_quote(market_id="bob", yes_bid=0.30, yes_ask=0.31, updated_ts=now_ts)
            engine.update_quote(market_id="carol", yes_bid=0.31, yes_ask=0.32, updated_ts=now_ts)

            violations = engine.scan_sum_violations(now_ts=now_ts)
            self.assertEqual(violations, [])

    def test_overround_subset_still_detected_with_coverage_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint.db"
            engine = ConstraintArbEngine(db_path=db_path, unwind_threshold=1.03)

            outcomes = ["Alice", "Bob", "Carol", "Dave"]
            markets = [
                self._mk_market(
                    market_id="alice",
                    event_id="evt-over",
                    question="Who wins? Alice",
                    outcome="Alice",
                    outcomes=outcomes,
                ),
                self._mk_market(
                    market_id="bob",
                    event_id="evt-over",
                    question="Who wins? Bob",
                    outcome="Bob",
                    outcomes=outcomes,
                ),
                self._mk_market(
                    market_id="carol",
                    event_id="evt-over",
                    question="Who wins? Carol",
                    outcome="Carol",
                    outcomes=outcomes,
                ),
                self._mk_market(
                    market_id="dave",
                    event_id="evt-over",
                    question="Who wins? Dave",
                    outcome="Dave",
                    outcomes=outcomes,
                ),
            ]
            engine.register_markets(markets)

            now_ts = 1_700_000_000
            engine.update_quote(market_id="alice", yes_bid=0.40, yes_ask=0.41, updated_ts=now_ts)
            engine.update_quote(market_id="bob", yes_bid=0.39, yes_ask=0.40, updated_ts=now_ts)
            engine.update_quote(market_id="carol", yes_bid=0.33, yes_ask=0.34, updated_ts=now_ts)

            violations = engine.scan_sum_violations(now_ts=now_ts)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].action, "unwind_basket")
            self.assertFalse(violations[0].details["complete_basket"])
            self.assertEqual(violations[0].details["missing_legs"], 1)

    def test_graph_violation_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint.db"
            engine = ConstraintArbEngine(db_path=db_path, implication_threshold=0.02)
            markets = [
                self._mk_market(
                    market_id="a",
                    event_id="evt-1",
                    question="Will CPI be above 4.0 by June 2026?",
                    outcome="Yes",
                    outcomes=["Yes", "No"],
                ),
                self._mk_market(
                    market_id="b",
                    event_id="evt-2",
                    question="Will CPI be above 3.0 by June 2026?",
                    outcome="Yes",
                    outcomes=["Yes", "No"],
                ),
            ]
            engine.register_markets(markets)
            edges = engine.build_constraint_graph(max_pairs=10)
            self.assertTrue(edges)

            engine.update_quote(market_id="a", yes_bid=0.70, yes_ask=0.71, updated_ts=1_700_000_000)
            engine.update_quote(market_id="b", yes_bid=0.60, yes_ask=0.61, updated_ts=1_700_000_000)

            violations = engine.scan_graph_violations(now_ts=1_700_000_000)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].action, "buy_B_sell_A")

    def test_sqlite_tables_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint.db"
            _ = ConstraintArbEngine(db_path=db_path)

            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                names = {row[0] for row in rows}

            self.assertIn("graph_edges", names)
            self.assertIn("constraint_violations", names)
            self.assertIn("arb_capture_stats", names)

    def test_shadow_report_includes_backtest_and_kill_gate_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "constraint.db"
            output_path = Path(tmp) / "report.md"
            db = ConstraintArbDB(db_path)

            db.insert_violation(
                ConstraintViolation(
                    violation_id="sum-over-1",
                    event_id="evt-1",
                    relation_type="same_event_sum",
                    market_ids=("m1", "m2", "m3"),
                    semantic_confidence=1.0,
                    gross_edge=0.08,
                    slippage_est=0.009,
                    fill_risk=0.003,
                    semantic_penalty=0.0,
                    score=0.068,
                    vpin=0.0,
                    action="unwind_basket",
                    theoretical_pnl=0.08,
                    realized_pnl=0.0,
                    details={
                        "sum_yes_ask": 1.08,
                        "legs": 3,
                        "event_legs": 4,
                        "missing_legs": 1,
                        "missing_market_ids": ["m4"],
                        "complete_basket": False,
                    },
                    detected_at_ts=1_700_000_000,
                )
            )
            db.insert_violation(
                ConstraintViolation(
                    violation_id="sum-under-1",
                    event_id="evt-2",
                    relation_type="same_event_sum",
                    market_ids=("m5", "m6", "m7"),
                    semantic_confidence=1.0,
                    gross_edge=0.12,
                    slippage_est=0.009,
                    fill_risk=0.003,
                    semantic_penalty=0.0,
                    score=0.108,
                    vpin=0.0,
                    action="buy_yes_basket",
                    theoretical_pnl=0.12,
                    realized_pnl=0.0,
                    details={
                        "sum_yes_ask": 0.88,
                        "legs": 3,
                        "event_legs": 3,
                        "missing_legs": 0,
                        "missing_market_ids": [],
                        "complete_basket": True,
                    },
                    detected_at_ts=1_700_000_600,
                )
            )

            db.write_shadow_report(output_path, days=14)
            report = output_path.read_text(encoding="utf-8")

            self.assertIn("## Sum-Violation Backtest", report)
            self.assertIn("## Kill Gate", report)
            self.assertIn("tradable after coverage filter", report)
            self.assertIn("IN PROGRESS", report)


if __name__ == "__main__":
    unittest.main()
