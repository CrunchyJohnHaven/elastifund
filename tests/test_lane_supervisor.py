"""Tests for bot/lane_supervisor.py"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bot.lane_supervisor import (
    _route_weather_candidates,
    _select_per_lane,
    run_supervisor,
)

_NOW = datetime(2026, 3, 22, 14, 25, 0, tzinfo=timezone.utc)


def _thesis(*, lane: str, edge: float, mode: str = "shadow", ticker: str = "T1") -> dict:
    return {
        "thesis_id": f"{lane}:kalshi:{ticker}",
        "lane": lane,
        "venue": "kalshi",
        "ticker": ticker,
        "event_ticker": f"EV-{ticker}",
        "side": "no",
        "rank_score": edge,
        "spread_adjusted_edge": edge,
        "model_probability": 0.65,
        "execution_mode": mode,
        "city": "NYC",
        "target_date": "2026-03-23",
    }


def _thesis_payload(candidates: list[dict]) -> dict:
    return {
        "artifact": "thesis_candidates.v1",
        "thesis_count": len(candidates),
        "candidates": candidates,
    }


class TestSelectPerLane:
    def test_empty(self):
        assert _select_per_lane([]) == {}

    def test_weather_above_threshold_selected(self):
        candidates = [_thesis(lane="weather", edge=0.08)]
        result = _select_per_lane(candidates)
        assert "weather" in result
        assert len(result["weather"]) == 1

    def test_weather_below_threshold_excluded(self):
        candidates = [_thesis(lane="weather", edge=0.02)]
        result = _select_per_lane(candidates)
        assert "weather" not in result

    def test_live_mode_always_included_regardless_of_edge(self):
        candidates = [_thesis(lane="btc5", edge=0.001, mode="live")]
        result = _select_per_lane(candidates)
        assert "btc5" in result

    def test_max_three_per_lane(self):
        candidates = [_thesis(lane="weather", edge=0.1 - i * 0.01, ticker=f"T{i}") for i in range(5)]
        result = _select_per_lane(candidates)
        assert len(result["weather"]) == 3

    def test_sorted_by_edge_descending(self):
        candidates = [_thesis(lane="weather", edge=e, ticker=f"T{i}") for i, e in enumerate([0.06, 0.09, 0.04])]
        result = _select_per_lane(candidates)
        edges = [t["rank_score"] for t in result["weather"]]
        assert edges == sorted(edges, reverse=True)

    def test_multi_lane(self):
        candidates = [
            _thesis(lane="weather", edge=0.08, ticker="W1"),
            _thesis(lane="btc5", edge=0.05, mode="live", ticker="B1"),
        ]
        result = _select_per_lane(candidates)
        assert "weather" in result
        assert "btc5" in result


class TestRouteWeatherCandidates:
    def test_empty_candidates(self, tmp_path: Path):
        n = _route_weather_candidates([], tmp_path / "queue.jsonl", _NOW)
        assert n == 0
        assert not (tmp_path / "queue.jsonl").exists()

    def test_appends_to_queue(self, tmp_path: Path):
        candidates = [_thesis(lane="weather", edge=0.07)]
        queue = tmp_path / "queue.jsonl"
        n = _route_weather_candidates(candidates, queue, _NOW)
        assert n == 1
        assert queue.exists()
        rows = [json.loads(line) for line in queue.read_text().splitlines()]
        assert len(rows) == 1
        assert rows[0]["ticker"] == "T1"
        assert rows[0]["source"] == "lane_supervisor"
        assert rows[0]["execution_mode"] == "shadow"

    def test_appends_multiple_times(self, tmp_path: Path):
        candidates = [_thesis(lane="weather", edge=0.07)]
        queue = tmp_path / "queue.jsonl"
        _route_weather_candidates(candidates, queue, _NOW)
        _route_weather_candidates(candidates, queue, _NOW)
        rows = [json.loads(l) for l in queue.read_text().splitlines()]
        assert len(rows) == 2

    def test_creates_parent_dirs(self, tmp_path: Path):
        candidates = [_thesis(lane="weather", edge=0.07)]
        queue = tmp_path / "sub" / "dir" / "queue.jsonl"
        _route_weather_candidates(candidates, queue, _NOW)
        assert queue.exists()


class TestRunSupervisor:
    def _write_thesis(self, path: Path, candidates: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_thesis_payload(candidates)))

    def test_missing_thesis_file(self, tmp_path: Path):
        result = run_supervisor(
            thesis_path=tmp_path / "missing.json",
            output_path=tmp_path / "out.json",
            weather_queue_path=tmp_path / "queue.jsonl",
            now=_NOW,
            route_weather=False,
        )
        assert result["thesis_count_evaluated"] == 0
        assert result["lanes_with_selections"] == []

    def test_weather_lane_routed(self, tmp_path: Path):
        candidates = [_thesis(lane="weather", edge=0.09, ticker="W1")]
        thesis_path = tmp_path / "thesis.json"
        self._write_thesis(thesis_path, candidates)
        queue = tmp_path / "queue.jsonl"

        result = run_supervisor(
            thesis_path=thesis_path,
            output_path=tmp_path / "out.json",
            weather_queue_path=queue,
            now=_NOW,
            route_weather=True,
        )
        assert result["weather_candidates_routed"] == 1
        assert queue.exists()

    def test_output_written(self, tmp_path: Path):
        candidates = [_thesis(lane="weather", edge=0.09, ticker="W1")]
        thesis_path = tmp_path / "thesis.json"
        self._write_thesis(thesis_path, candidates)
        out = tmp_path / "out.json"

        run_supervisor(
            thesis_path=thesis_path,
            output_path=out,
            weather_queue_path=tmp_path / "queue.jsonl",
            now=_NOW,
        )

        assert out.exists()
        payload = json.loads(out.read_text())
        assert payload["artifact"] == "supervisor_selection.v1"
        assert "weather" in payload["lanes_with_selections"]

    def test_no_route_weather(self, tmp_path: Path):
        candidates = [_thesis(lane="weather", edge=0.09)]
        thesis_path = tmp_path / "thesis.json"
        self._write_thesis(thesis_path, candidates)
        queue = tmp_path / "queue.jsonl"

        result = run_supervisor(
            thesis_path=thesis_path,
            output_path=tmp_path / "out.json",
            weather_queue_path=queue,
            now=_NOW,
            route_weather=False,
        )
        assert result["weather_candidates_routed"] == 0
        assert not queue.exists()

    def test_lane_actions_populated(self, tmp_path: Path):
        candidates = [
            _thesis(lane="weather", edge=0.10, ticker="W1"),
            _thesis(lane="btc5", edge=0.05, mode="live", ticker="B1"),
        ]
        thesis_path = tmp_path / "thesis.json"
        self._write_thesis(thesis_path, candidates)

        result = run_supervisor(
            thesis_path=thesis_path,
            output_path=tmp_path / "out.json",
            weather_queue_path=tmp_path / "queue.jsonl",
            now=_NOW,
        )
        assert "weather" in result["lane_actions"]
        assert "btc5" in result["lane_actions"]
        assert result["lane_actions"]["weather"]["top_edge"] == pytest.approx(0.10, abs=1e-6)
