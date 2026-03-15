"""Unit tests for CLI commands."""

import json
import tempfile
from pathlib import Path

import pytest

from edge_backlog.cli import main
from edge_backlog.models import EdgeStore, Status


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "test_edges.json")


def run_cli(*args, store_path=None):
    """Helper to run CLI with a temp store."""
    argv = list(args)
    if store_path:
        argv = ["--store", store_path] + argv
    main(argv)


def add_edge(store_path, name="TestEdge", hypo="Test hypothesis"):
    run_cli("add-edge", name, hypo, store_path=store_path)
    store = EdgeStore(Path(store_path))
    edges = store.list_all()
    return edges[-1].id


class TestAddEdge:
    def test_add(self, store_path, capsys):
        run_cli("add-edge", "MyEdge", "Some hypothesis", store_path=store_path)
        out = capsys.readouterr().out
        assert "Created edge" in out
        assert "MyEdge" in out
        assert "[IDEA]" in out

    def test_add_with_tags(self, store_path):
        run_cli("add-edge", "Tagged", "Hypo", "--tags", "momentum,mean-rev", store_path=store_path)
        store = EdgeStore(Path(store_path))
        edge = store.list_all()[0]
        assert edge.tags == ["momentum", "mean-rev"]


class TestListEdges:
    def test_list_empty(self, store_path, capsys):
        run_cli("list-edges", store_path=store_path)
        assert "No edges found" in capsys.readouterr().out

    def test_list_shows_edges(self, store_path, capsys):
        add_edge(store_path, "Edge1")
        add_edge(store_path, "Edge2")
        run_cli("list-edges", store_path=store_path)
        out = capsys.readouterr().out
        assert "Edge1" in out
        assert "Edge2" in out

    def test_list_filter_status(self, store_path, capsys):
        eid = add_edge(store_path, "OnlyIdea")
        add_edge(store_path, "AlsoIdea")
        # Promote first one
        run_cli("promote", eid, store_path=store_path)
        capsys.readouterr()  # clear
        run_cli("list-edges", "--status", "IDEA", store_path=store_path)
        out = capsys.readouterr().out
        assert "AlsoIdea" in out
        assert "OnlyIdea" not in out


class TestScoreEdge:
    def test_score(self, store_path, capsys):
        eid = add_edge(store_path)
        run_cli("score-edge", eid, "8.5", "--notes", "High EV", store_path=store_path)
        out = capsys.readouterr().out
        assert "Scored" in out
        assert "8.5" in out
        store = EdgeStore(Path(store_path))
        edge = store.get(eid)
        assert edge.score == 8.5

    def test_score_missing_edge(self, store_path):
        with pytest.raises(KeyError):
            run_cli("score-edge", "bad_id", "5", store_path=store_path)


class TestStartExperiment:
    def test_start(self, store_path, capsys):
        eid = add_edge(store_path)
        run_cli("start-experiment", eid, "Backtest Run 1", store_path=store_path)
        out = capsys.readouterr().out
        assert "Started experiment" in out
        store = EdgeStore(Path(store_path))
        edge = store.get(eid)
        assert len(edge.experiments) == 1
        assert edge.experiments[0].name == "Backtest Run 1"


class TestLogResult:
    def test_log(self, store_path, capsys):
        eid = add_edge(store_path)
        run_cli("start-experiment", eid, "BT1", store_path=store_path)
        store = EdgeStore(Path(store_path))
        exp_id = store.get(eid).experiments[0].id
        capsys.readouterr()
        run_cli("log-result", eid, exp_id, "win_rate", "0.65", "--notes", "Good", store_path=store_path)
        out = capsys.readouterr().out
        assert "Logged win_rate=0.65" in out
        edge = store.get(eid)
        assert edge.experiments[0].results[0].value == 0.65

    def test_log_bad_experiment(self, store_path):
        eid = add_edge(store_path)
        with pytest.raises(SystemExit):
            run_cli("log-result", eid, "bad_exp", "x", "1", store_path=store_path)


class TestPromote:
    def test_promote_idea_to_backtest(self, store_path, capsys):
        eid = add_edge(store_path)
        capsys.readouterr()
        run_cli("promote", eid, store_path=store_path)
        out = capsys.readouterr().out
        assert "IDEA" in out
        assert "BACKTEST" in out
        store = EdgeStore(Path(store_path))
        assert store.get(eid).status == Status.BACKTEST

    def test_promote_to_live_blocked(self, store_path):
        eid = add_edge(store_path)
        store = EdgeStore(Path(store_path))
        edge = store.get(eid)
        edge.status = Status.SHADOW
        store.save(edge)
        with pytest.raises(SystemExit):
            run_cli("promote", eid, store_path=store_path)


class TestDemote:
    def test_demote(self, store_path, capsys):
        eid = add_edge(store_path)
        run_cli("promote", eid, store_path=store_path)
        capsys.readouterr()
        run_cli("demote", eid, store_path=store_path)
        out = capsys.readouterr().out
        assert "BACKTEST" in out
        assert "IDEA" in out

    def test_demote_below_idea(self, store_path):
        eid = add_edge(store_path)
        with pytest.raises(SystemExit):
            run_cli("demote", eid, store_path=store_path)
