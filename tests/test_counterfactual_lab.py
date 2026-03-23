"""Tests for scripts/counterfactual_lab.py"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.counterfactual_lab import (
    _analyze_weather_counterfactuals,
    _verdict,
    run_counterfactual_lab,
)

_NOW = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)


def _write_decisions(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _rejected(reason_code: str, edge: float) -> dict:
    return {
        "execution_result": "rejected",
        "reason_code": reason_code,
        "edge": edge,
        "city": "NYC",
        "ticker": "T1",
        "side": "no",
        "order_probability": 0.1,
        "execution_mode": "live",
        "timestamp": "2026-03-22T14:00:00",
    }


class TestVerdict:
    def test_positive_relax(self):
        assert _verdict(0.05) == "RELAX"

    def test_negative_tighten(self):
        assert _verdict(-0.05) == "TIGHTEN"

    def test_zero_keep(self):
        assert _verdict(0.0) == "KEEP"

    def test_epsilon_keep(self):
        assert _verdict(1e-10) == "KEEP"


class TestAnalyzeWeatherCounterfactuals:
    def test_missing_file(self, tmp_path: Path):
        result = _analyze_weather_counterfactuals(tmp_path / "missing.jsonl")
        assert result["status"] == "missing"
        assert result["total_rejected"] == 0

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "d.jsonl"
        path.write_text("")
        result = _analyze_weather_counterfactuals(path)
        assert result["status"] == "ok"
        assert result["total_rejected"] == 0
        assert result["table"] == []

    def test_only_rejected_counted(self, tmp_path: Path):
        path = tmp_path / "d.jsonl"
        rows = [
            _rejected("already_ordered", 0.08),
            {"execution_result": "placed", "reason_code": "placed_ok", "edge": 0.0},
        ]
        _write_decisions(path, rows)
        result = _analyze_weather_counterfactuals(path)
        assert result["total_rejected"] == 1

    def test_positive_edge_relax(self, tmp_path: Path):
        path = tmp_path / "d.jsonl"
        rows = [_rejected("already_ordered", 0.10) for _ in range(5)]
        _write_decisions(path, rows)
        result = _analyze_weather_counterfactuals(path)
        assert result["table"][0]["verdict"] == "RELAX"
        assert result["overall"]["avg_edge"] == pytest.approx(0.10, abs=1e-4)

    def test_negative_edge_tighten(self, tmp_path: Path):
        path = tmp_path / "d.jsonl"
        rows = [_rejected("low_edge_filter", -0.05) for _ in range(5)]
        _write_decisions(path, rows)
        result = _analyze_weather_counterfactuals(path)
        assert result["table"][0]["verdict"] == "TIGHTEN"

    def test_sorted_by_edge_descending(self, tmp_path: Path):
        path = tmp_path / "d.jsonl"
        rows = (
            [_rejected("reason_a", 0.05) for _ in range(3)]
            + [_rejected("reason_b", 0.12) for _ in range(3)]
        )
        _write_decisions(path, rows)
        result = _analyze_weather_counterfactuals(path)
        edges = [r["avg_edge"] for r in result["table"]]
        assert edges == sorted(edges, reverse=True)


class TestRunCounterfactualLab:
    def test_all_missing(self, tmp_path: Path):
        result = run_counterfactual_lab(
            db_paths=[],
            weather_decisions_path=tmp_path / "missing.jsonl",
            output_path=tmp_path / "out.json",
            now=_NOW,
        )
        assert result["artifact"] == "counterfactual_lab.v1"
        assert "btc5" in result["lane_verdicts"]
        assert "weather" in result["lane_verdicts"]

    def test_writes_output(self, tmp_path: Path):
        out = tmp_path / "out.json"
        run_counterfactual_lab(
            db_paths=[],
            weather_decisions_path=tmp_path / "missing.jsonl",
            output_path=out,
            now=_NOW,
        )
        assert out.exists()
        payload = json.loads(out.read_text())
        assert payload["artifact"] == "counterfactual_lab.v1"
        assert "lane_verdicts" in payload

    def test_weather_counterfactuals_in_output(self, tmp_path: Path):
        decisions_path = tmp_path / "decisions.jsonl"
        rows = [_rejected("already_ordered", 0.08) for _ in range(5)]
        _write_decisions(decisions_path, rows)

        result = run_counterfactual_lab(
            db_paths=[],
            weather_decisions_path=decisions_path,
            output_path=tmp_path / "out.json",
            now=_NOW,
        )
        weather = result["weather"]
        assert weather["status"] == "ok"
        assert weather["total_rejected"] == 5
        assert result["lane_verdicts"]["weather"]["overall_avg_edge"] == pytest.approx(0.08, abs=1e-4)

    def test_relax_reason_surfaces_in_verdicts(self, tmp_path: Path):
        decisions_path = tmp_path / "decisions.jsonl"
        rows = [_rejected("already_ordered", 0.15) for _ in range(5)]
        _write_decisions(decisions_path, rows)

        result = run_counterfactual_lab(
            db_paths=[],
            weather_decisions_path=decisions_path,
            output_path=tmp_path / "out.json",
            now=_NOW,
        )
        assert "already_ordered" in result["lane_verdicts"]["weather"]["top_relax_reasons"]
