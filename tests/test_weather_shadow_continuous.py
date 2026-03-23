"""Tests for scripts/weather_shadow_continuous.py"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.weather_shadow_continuous import (
    _is_scan_window,
    _seconds_until_next_window,
    run_once,
)


def _utc(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 3, 22, hour, minute, second, tzinfo=timezone.utc)


class TestScanWindow:
    def test_exactly_at_25(self):
        assert _is_scan_window(_utc(14, 25)) is True

    def test_exactly_at_55(self):
        assert _is_scan_window(_utc(14, 55)) is True

    def test_within_window_25(self):
        assert _is_scan_window(_utc(14, 23)) is True  # 25 - 2 = within 4-min window
        assert _is_scan_window(_utc(14, 29)) is True  # 25 + 4

    def test_outside_window(self):
        assert _is_scan_window(_utc(14, 30)) is False
        assert _is_scan_window(_utc(14, 10)) is False

    def test_exactly_at_55_boundary(self):
        assert _is_scan_window(_utc(14, 51)) is True  # 55 - 4
        assert _is_scan_window(_utc(14, 59)) is True  # 55 + 4


class TestSecondsUntilNextWindow:
    def test_returns_float(self):
        result = _seconds_until_next_window(_utc(14, 0))
        assert isinstance(result, float)
        assert result >= 0.0

    def test_before_25_window(self):
        # At 14:20 — 5 minutes until :25 center
        result = _seconds_until_next_window(_utc(14, 20))
        assert 250 <= result <= 320  # roughly 5 minutes

    def test_inside_window_returns_zero_or_small(self):
        result = _seconds_until_next_window(_utc(14, 25))
        assert result == 0.0 or result < 1801  # either now or next window


class TestRunOnce:
    """run_once requires live Kalshi API; test file I/O in isolation."""

    def _make_shadow_artifact(self) -> dict:
        return {
            "artifact": "instance4_weather_divergence_shadow.v1",
            "generated_at": "2026-03-22T14:25:00Z",
            "market_scan": {"candidate_count": 2, "candidate_rows": []},
            "source_mapping_summary": {"clean_city_count": 3, "clean_cities": ["NYC", "CHI", "MIA"]},
            "block_reasons": ["shadow_only_cycle_no_live_capital"],
            "finance_gate_pass": True,
        }

    def test_writes_output_and_history(self, tmp_path: Path, monkeypatch):
        artifact = self._make_shadow_artifact()

        def fake_build(**_kwargs):
            return artifact

        import scripts.weather_shadow_continuous as module
        monkeypatch.setattr(module, "build_instance4_weather_lane_artifact", fake_build)
        monkeypatch.setattr(module, "render_markdown", lambda _p: "# md\n")

        output_path = tmp_path / "shadow.json"
        markdown_path = tmp_path / "shadow.md"
        history_path = tmp_path / "history.jsonl"

        result = run_once(
            history_path=history_path,
            output_path=output_path,
            markdown_path=markdown_path,
        )

        assert output_path.exists()
        assert markdown_path.exists()
        assert history_path.exists()

        written = json.loads(output_path.read_text())
        assert written["artifact"] == artifact["artifact"]

        history_rows = [json.loads(line) for line in history_path.read_text().splitlines()]
        assert len(history_rows) == 1
        assert history_rows[0]["candidate_count"] == 2
        assert history_rows[0]["finance_gate_pass"] is True
        assert result["artifact"] == artifact["artifact"]

    def test_history_appends(self, tmp_path: Path, monkeypatch):
        artifact = self._make_shadow_artifact()

        def fake_build(**_kwargs):
            return artifact

        import scripts.weather_shadow_continuous as module
        monkeypatch.setattr(module, "build_instance4_weather_lane_artifact", fake_build)
        monkeypatch.setattr(module, "render_markdown", lambda _p: "# md\n")

        history_path = tmp_path / "history.jsonl"

        for _ in range(3):
            run_once(
                history_path=history_path,
                output_path=tmp_path / "out.json",
                markdown_path=tmp_path / "out.md",
            )

        rows = history_path.read_text().strip().splitlines()
        assert len(rows) == 3
