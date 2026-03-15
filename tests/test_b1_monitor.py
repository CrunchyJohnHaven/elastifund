import tempfile
import unittest
from pathlib import Path

from bot.b1_monitor import B1Monitor
from bot.constraint_arb_engine import ConstraintArbEngine, GraphEdge
from bot.resolution_normalizer import normalize_market


class TestB1Monitor(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        question: str,
        end_date: str = "2026-11-03T23:59:00Z",
        source: str = "Associated Press",
    ) -> dict:
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": "Yes",
            "outcomes": ["Yes", "No"],
            "category": "politics",
            "resolutionSource": source,
            "endDate": end_date,
            "rules": f"Resolves using {source} at {end_date}.",
        }

    def test_monitor_detects_implication_violation_from_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = ConstraintArbEngine(db_path=Path(tmp) / "constraint.db")
            engine.register_markets(
                [
                    self._mk_market(
                        market_id="a",
                        event_id="evt-a",
                        question="Will CPI be above 4.0 by June 2026?",
                    ),
                    self._mk_market(
                        market_id="b",
                        event_id="evt-b",
                        question="Will CPI be above 3.0 by June 2026?",
                    ),
                ]
            )
            engine.build_constraint_graph(max_pairs=10)

            now_ts = 1_700_000_000
            engine.update_quote(market_id="a", yes_bid=0.70, yes_ask=0.71, updated_ts=now_ts)
            engine.update_quote(market_id="b", yes_bid=0.60, yes_ask=0.61, updated_ts=now_ts)

            monitor = B1Monitor(relation_threshold=0.03, stale_book_seconds=30)
            batch = monitor.scan_engine(engine, now_ts=now_ts)

            self.assertEqual(len(batch.executable), 1)
            opp = batch.executable[0]
            self.assertEqual(opp.relation_type, "A_implies_B")
            self.assertEqual(opp.basket_action, "buy_no_a_buy_yes_b")
            self.assertEqual(tuple(leg.side for leg in opp.legs), ("NO", "YES"))
            self.assertAlmostEqual(opp.trigger_edge, 0.09, places=6)
            self.assertAlmostEqual(opp.theoretical_edge, 0.09, places=6)
            self.assertEqual(opp.resolution_gate_status, "passed")
            self.assertEqual(batch.metrics["executable_count"], 1)

    def test_monitor_drops_stale_books(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = ConstraintArbEngine(db_path=Path(tmp) / "constraint.db")
            engine.register_markets(
                [
                    self._mk_market(
                        market_id="a",
                        event_id="evt-a",
                        question="Will CPI be above 4.0 by June 2026?",
                    ),
                    self._mk_market(
                        market_id="b",
                        event_id="evt-b",
                        question="Will CPI be above 3.0 by June 2026?",
                    ),
                ]
            )
            engine.build_constraint_graph(max_pairs=10)

            now_ts = 1_700_000_000
            engine.update_quote(market_id="a", yes_bid=0.70, yes_ask=0.71, updated_ts=now_ts)
            engine.update_quote(market_id="b", yes_bid=0.60, yes_ask=0.61, updated_ts=now_ts - 40)

            monitor = B1Monitor(relation_threshold=0.03, stale_book_seconds=30)
            batch = monitor.scan_engine(engine, now_ts=now_ts)

            self.assertEqual(batch.executable, ())
            self.assertEqual(len(batch.dropped), 1)
            self.assertEqual(batch.dropped[0].reason, "stale_book")
            self.assertEqual(batch.metrics["stale_book_count"], 1)

    def test_monitor_detects_mutually_exclusive_pair(self) -> None:
        now_ts = 1_700_000_000
        market_a = normalize_market(
            self._mk_market(
                market_id="a",
                event_id="evt-a",
                question="Will candidate A win the election?",
            )
        )
        market_b = normalize_market(
            self._mk_market(
                market_id="b",
                event_id="evt-b",
                question="Will candidate B win the election?",
            )
        )
        edge = GraphEdge(
            edge_id="edge-mutual",
            event_id="cross_market",
            market_a="a",
            market_b="b",
            relation_type="mutually_exclusive",
            semantic_confidence=0.92,
            resolution_key=f"{market_a.resolution_key}:{market_b.resolution_key}",
        )
        quotes = {
            "a": engine_quote("a", yes_bid=0.62, yes_ask=0.63, updated_ts=now_ts),
            "b": engine_quote("b", yes_bid=0.45, yes_ask=0.46, updated_ts=now_ts),
        }

        monitor = B1Monitor(relation_threshold=0.03, stale_book_seconds=30)
        batch = monitor.scan(
            markets={"a": market_a, "b": market_b},
            edges=[edge],
            quotes=quotes,
            now_ts=now_ts,
        )

        self.assertEqual(len(batch.executable), 1)
        opp = batch.executable[0]
        self.assertEqual(opp.basket_action, "buy_no_pair")
        self.assertEqual(tuple(leg.side for leg in opp.legs), ("NO", "NO"))
        self.assertAlmostEqual(opp.trigger_edge, 0.07, places=6)
        self.assertAlmostEqual(opp.theoretical_edge, 0.07, places=6)

    def test_monitor_logs_subset_relation_and_dedupes_repeat_snapshot(self) -> None:
        now_ts = 1_700_000_000
        market_a = normalize_market(
            self._mk_market(
                market_id="a",
                event_id="evt-a",
                question="Will CPI be above 4.0 by June 2026?",
            )
        )
        market_b = normalize_market(
            self._mk_market(
                market_id="b",
                event_id="evt-b",
                question="Will CPI be above 3.0 by June 2026?",
            )
        )
        subset_edge = GraphEdge(
            edge_id="edge-subset",
            event_id="cross_market",
            market_a="a",
            market_b="b",
            relation_type="subset",
            semantic_confidence=0.81,
            resolution_key=f"{market_a.resolution_key}:{market_b.resolution_key}",
        )
        implies_edge = GraphEdge(
            edge_id="edge-implies",
            event_id="cross_market",
            market_a="a",
            market_b="b",
            relation_type="A_implies_B",
            semantic_confidence=0.91,
            resolution_key=f"{market_a.resolution_key}:{market_b.resolution_key}",
        )
        quotes = {
            "a": engine_quote("a", yes_bid=0.66, yes_ask=0.67, updated_ts=now_ts),
            "b": engine_quote("b", yes_bid=0.55, yes_ask=0.56, updated_ts=now_ts),
        }

        monitor = B1Monitor(relation_threshold=0.03, stale_book_seconds=30, snapshot_dedupe_seconds=15)
        subset_batch = monitor.scan(
            markets={"a": market_a, "b": market_b},
            edges=[subset_edge],
            quotes=quotes,
            now_ts=now_ts,
        )
        self.assertEqual(len(subset_batch.log_only), 1)
        self.assertEqual(subset_batch.log_only[0].reason, "phase1_log_only")

        first = monitor.scan(
            markets={"a": market_a, "b": market_b},
            edges=[implies_edge],
            quotes=quotes,
            now_ts=now_ts,
        )
        second = monitor.scan(
            markets={"a": market_a, "b": market_b},
            edges=[implies_edge],
            quotes=quotes,
            now_ts=now_ts,
        )

        self.assertEqual(len(first.executable), 1)
        self.assertEqual(second.executable, ())
        self.assertEqual(len(second.dropped), 1)
        self.assertEqual(second.dropped[0].reason, "duplicate_snapshot")


def engine_quote(market_id: str, *, yes_bid: float, yes_ask: float, updated_ts: int):
    from bot.constraint_arb_engine import MarketQuote

    return MarketQuote(
        market_id=market_id,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=1.0 - yes_ask,
        no_ask=1.0 - yes_bid,
        updated_ts=updated_ts,
    )


if __name__ == "__main__":
    unittest.main()
