"""Unit tests for Edge Backlog + Experiment Harness."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

# Add parent to path so we can import edges package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from edges.metrics import arr_estimate, expected_value, kelly_fraction, SLIPPAGE_NORMAL
from edges.models import EdgeCard, EdgeStatus, Experiment, ExperimentStatus
from edges.store import EdgeStore


class TestEdgeCard(unittest.TestCase):
    def test_create(self):
        e = EdgeCard(name="NO bias", hypothesis="Crowd overprices YES")
        self.assertEqual(e.name, "NO bias")
        self.assertEqual(e.status, EdgeStatus.BACKLOG)
        self.assertIsNotNone(e.id)
        self.assertEqual(len(e.id), 12)

    def test_roundtrip(self):
        e = EdgeCard(
            name="Test", hypothesis="H1",
            expected_win_rate=0.75, expected_ev_per_trade=0.30,
        )
        row = e.to_row()
        e2 = EdgeCard.from_row(row)
        self.assertEqual(e.id, e2.id)
        self.assertEqual(e.name, e2.name)
        self.assertEqual(e.expected_win_rate, e2.expected_win_rate)


class TestExperiment(unittest.TestCase):
    def test_create(self):
        exp = Experiment(edge_id="abc123")
        self.assertEqual(exp.status, ExperimentStatus.RUNNING)
        self.assertEqual(exp.num_trades, 0)
        self.assertEqual(exp.win_rate, 0.0)

    def test_win_rate(self):
        exp = Experiment(edge_id="abc", wins=3, losses=1, num_trades=4)
        self.assertAlmostEqual(exp.win_rate, 0.75)

    def test_avg_pnl(self):
        exp = Experiment(edge_id="abc", num_trades=4, total_pnl=2.40)
        self.assertAlmostEqual(exp.avg_pnl, 0.60)


class TestEdgeStore(unittest.TestCase):
    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmpfile.close()
        self.store = EdgeStore(db_path=self.tmpfile.name)

    def tearDown(self):
        self.store.close()
        os.unlink(self.tmpfile.name)

    def test_add_and_get_edge(self):
        edge = EdgeCard(name="Test Edge", hypothesis="H1")
        self.store.add_edge(edge)
        got = self.store.get_edge(edge.id)
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "Test Edge")

    def test_list_edges_filter(self):
        self.store.add_edge(EdgeCard(name="A", hypothesis="H", status=EdgeStatus.BACKLOG))
        self.store.add_edge(EdgeCard(name="B", hypothesis="H", status=EdgeStatus.PROMOTED))
        all_edges = self.store.list_edges()
        self.assertEqual(len(all_edges), 2)
        backlog = self.store.list_edges(status=EdgeStatus.BACKLOG)
        self.assertEqual(len(backlog), 1)
        self.assertEqual(backlog[0].name, "A")

    def test_promote_demote(self):
        edge = EdgeCard(name="Test", hypothesis="H")
        self.store.add_edge(edge)
        self.store.update_edge_status(edge.id, EdgeStatus.PROMOTED)
        got = self.store.get_edge(edge.id)
        self.assertEqual(got.status, EdgeStatus.PROMOTED)
        self.store.update_edge_status(edge.id, EdgeStatus.DEMOTED)
        got = self.store.get_edge(edge.id)
        self.assertEqual(got.status, EdgeStatus.DEMOTED)

    def test_experiment_lifecycle(self):
        edge = EdgeCard(name="Test", hypothesis="H")
        self.store.add_edge(edge)

        exp = Experiment(edge_id=edge.id)
        self.store.start_experiment(exp)

        # Edge should be in testing
        got_edge = self.store.get_edge(edge.id)
        self.assertEqual(got_edge.status, EdgeStatus.TESTING)

        # Log results
        self.store.log_result(exp.id, won=True, pnl=0.60)
        self.store.log_result(exp.id, won=True, pnl=0.80)
        self.store.log_result(exp.id, won=False, pnl=-2.00)

        got = self.store.get_experiment(exp.id)
        self.assertEqual(got.num_trades, 3)
        self.assertEqual(got.wins, 2)
        self.assertEqual(got.losses, 1)
        self.assertAlmostEqual(got.total_pnl, -0.60)

        # Complete
        self.store.complete_experiment(exp.id, notes="Decent edge")
        got = self.store.get_experiment(exp.id)
        self.assertEqual(got.status, ExperimentStatus.COMPLETED)
        self.assertIsNotNone(got.ended_at)

    def test_abort_experiment(self):
        edge = EdgeCard(name="Test", hypothesis="H")
        self.store.add_edge(edge)
        exp = Experiment(edge_id=edge.id)
        self.store.start_experiment(exp)
        self.store.abort_experiment(exp.id, reason="Bad data")
        got = self.store.get_experiment(exp.id)
        self.assertEqual(got.status, ExperimentStatus.ABORTED)

    def test_no_trade_mode(self):
        # Default is True (safe default)
        self.assertTrue(self.store.no_trade_mode)
        self.store.no_trade_mode = False
        self.assertFalse(self.store.no_trade_mode)
        self.store.no_trade_mode = True
        self.assertTrue(self.store.no_trade_mode)

    def test_config(self):
        self.store.set_config("test_key", "test_value")
        self.assertEqual(self.store.get_config("test_key"), "test_value")
        self.assertEqual(self.store.get_config("missing", "default"), "default")


class TestMetrics(unittest.TestCase):
    def test_ev_buy_yes_positive(self):
        result = expected_value(
            win_prob=0.75, market_price=0.50, direction="buy_yes", order_size=2.0,
        )
        self.assertGreater(result["ev"], 0)
        self.assertGreater(result["edge_over_breakeven"], 0)

    def test_ev_buy_no(self):
        result = expected_value(
            win_prob=0.25, market_price=0.50, direction="buy_no", order_size=2.0,
        )
        # 75% chance NO wins, entry ~0.52
        self.assertGreater(result["ev"], 0)

    def test_ev_no_edge(self):
        result = expected_value(
            win_prob=0.50, market_price=0.50, direction="buy_yes", order_size=2.0,
        )
        # After fees and slippage, should be negative EV
        self.assertLess(result["ev"], 0)

    def test_kelly_fraction(self):
        k = kelly_fraction(0.75, 0.50, "buy_yes")
        self.assertGreater(k, 0)
        self.assertLessEqual(k, 0.20)  # Capped at 20%

    def test_kelly_no_edge(self):
        k = kelly_fraction(0.50, 0.50, "buy_yes")
        self.assertEqual(k, 0.0)

    def test_arr_estimate(self):
        result = arr_estimate(
            avg_ev_per_trade=0.30, trades_per_day=5, capital=75.0,
        )
        self.assertGreater(result["arr_pct"], 0)
        self.assertEqual(result["capital"], 75.0)

    def test_slippage_model(self):
        slip = SLIPPAGE_NORMAL.estimate(2.0, 0.50)
        self.assertGreater(slip, 0)
        self.assertLess(slip, 0.10)

        # Larger orders have more slippage
        slip_big = SLIPPAGE_NORMAL.estimate(50.0, 0.50)
        self.assertGreater(slip_big, slip)


if __name__ == "__main__":
    unittest.main()
