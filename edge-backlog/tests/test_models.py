"""Unit tests for edge backlog models."""

import json
import tempfile
from pathlib import Path

import pytest

from edge_backlog.models import Edge, EdgeStore, Experiment, Status


@pytest.fixture
def tmp_store(tmp_path):
    return EdgeStore(tmp_path / "edges.json")


@pytest.fixture
def sample_edge():
    return Edge(
        id="abc123",
        name="Mean Reversion",
        hypothesis="Markets overcorrect on news events",
        status=Status.IDEA,
        created="2026-01-01T00:00:00+00:00",
        updated="2026-01-01T00:00:00+00:00",
    )


class TestStatus:
    def test_ordered(self):
        assert Status.ordered() == [
            Status.IDEA, Status.BACKTEST, Status.PAPER, Status.SHADOW, Status.LIVE
        ]

    def test_next(self):
        assert Status.IDEA.next() == Status.BACKTEST
        assert Status.SHADOW.next() == Status.LIVE
        assert Status.LIVE.next() is None

    def test_prev(self):
        assert Status.LIVE.prev() == Status.SHADOW
        assert Status.IDEA.prev() is None


class TestEdge:
    def test_promote(self, sample_edge):
        new = sample_edge.promote()
        assert new == Status.BACKTEST
        assert sample_edge.status == Status.BACKTEST

    def test_promote_chain(self, sample_edge):
        sample_edge.promote()  # BACKTEST
        sample_edge.promote()  # PAPER
        sample_edge.promote()  # SHADOW
        assert sample_edge.status == Status.SHADOW

    def test_promote_to_live_blocked(self, sample_edge):
        sample_edge.status = Status.SHADOW
        with pytest.raises(ValueError, match="LIVE is blocked"):
            sample_edge.promote()

    def test_demote(self, sample_edge):
        sample_edge.status = Status.PAPER
        new = sample_edge.demote()
        assert new == Status.BACKTEST

    def test_demote_below_idea(self, sample_edge):
        with pytest.raises(ValueError, match="Cannot demote below"):
            sample_edge.demote()

    def test_set_score(self, sample_edge):
        sample_edge.set_score(7.5, "Looks promising")
        assert sample_edge.score == 7.5
        assert sample_edge.score_notes == "Looks promising"
        assert len(sample_edge.history) == 1

    def test_start_experiment(self, sample_edge):
        exp = sample_edge.start_experiment("Backtest v1")
        assert exp.name == "Backtest v1"
        assert exp.status == "running"
        assert len(sample_edge.experiments) == 1

    def test_experiment_add_result(self, sample_edge):
        exp = sample_edge.start_experiment("Test")
        r = exp.add_result("win_rate", 0.65, "Good")
        assert r.metric == "win_rate"
        assert r.value == 0.65
        assert len(exp.results) == 1

    def test_history_tracked(self, sample_edge):
        sample_edge.promote()
        sample_edge.set_score(5.0)
        sample_edge.start_experiment("e1")
        assert len(sample_edge.history) == 3


class TestEdgeStore:
    def test_save_and_get(self, tmp_store, sample_edge):
        tmp_store.save(sample_edge)
        loaded = tmp_store.get("abc123")
        assert loaded.name == "Mean Reversion"
        assert loaded.status == Status.IDEA

    def test_get_missing(self, tmp_store):
        with pytest.raises(KeyError):
            tmp_store.get("nonexistent")

    def test_list_all(self, tmp_store, sample_edge):
        tmp_store.save(sample_edge)
        e2 = Edge(
            id="def456", name="Momentum", hypothesis="Trend following",
            status=Status.BACKTEST, created="2026-01-02T00:00:00+00:00",
            updated="2026-01-02T00:00:00+00:00",
        )
        tmp_store.save(e2)
        all_edges = tmp_store.list_all()
        assert len(all_edges) == 2

    def test_list_filtered(self, tmp_store, sample_edge):
        tmp_store.save(sample_edge)
        e2 = Edge(
            id="def456", name="Momentum", hypothesis="Trend following",
            status=Status.BACKTEST, created="2026-01-02T00:00:00+00:00",
            updated="2026-01-02T00:00:00+00:00",
        )
        tmp_store.save(e2)
        ideas = tmp_store.list_all(status=Status.IDEA)
        assert len(ideas) == 1
        assert ideas[0].id == "abc123"

    def test_delete(self, tmp_store, sample_edge):
        tmp_store.save(sample_edge)
        tmp_store.delete("abc123")
        assert tmp_store.list_all() == []

    def test_delete_missing(self, tmp_store):
        with pytest.raises(KeyError):
            tmp_store.delete("nope")

    def test_roundtrip_with_experiments(self, tmp_store, sample_edge):
        exp = sample_edge.start_experiment("bt1")
        exp.add_result("pnl", 100.5, "nice")
        tmp_store.save(sample_edge)
        loaded = tmp_store.get("abc123")
        assert len(loaded.experiments) == 1
        assert loaded.experiments[0].results[0].value == 100.5
