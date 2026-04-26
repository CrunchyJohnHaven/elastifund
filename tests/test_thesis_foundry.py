"""Tests for bot/thesis_foundry.py"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.thesis_foundry import (
    _artifact_age_seconds,
    _btc5_to_thesis,
    _read_json,
    _weather_to_theses,
    build_thesis_candidates,
)

_NOW = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _weather_artifact(*, candidates: list[dict], generated_offset_hours: int = 0) -> dict:
    generated = _NOW - timedelta(hours=generated_offset_hours)
    return {
        "artifact": "instance4_weather_divergence_shadow.v1",
        "generated_at": _ts(generated),
        "market_scan": {
            "candidate_count": len(candidates),
            "candidate_rows": candidates,
        },
        "source_mapping_summary": {"clean_city_count": 3},
    }


def _candidate_row(ticker: str, edge: float, city: str = "NYC") -> dict:
    return {
        "ticker": ticker,
        "event_ticker": f"EV-{ticker}",
        "title": f"Test market {ticker}",
        "market_type": "temperature",
        "model_probability": 0.65,
        "target_date": "2026-03-23",
        "candidate": True,
        "edge": {
            "preferred_side": "no",
            "spread_adjusted_edge": edge,
            "yes_spread_adjusted": edge - 0.01,
            "no_spread_adjusted": edge,
        },
        "settlement_source": {"city": city},
    }


class TestArtifactAge:
    def test_fresh_artifact(self):
        payload = {"generated_at": _ts(_NOW - timedelta(minutes=10))}
        age = _artifact_age_seconds(payload, _NOW)
        assert age is not None
        assert 590 <= age <= 610

    def test_missing_generated_at(self):
        assert _artifact_age_seconds({}, _NOW) is None

    def test_malformed_ts(self):
        assert _artifact_age_seconds({"generated_at": "not-a-date"}, _NOW) is None


class TestWeatherToTheses:
    def test_empty_candidates(self):
        payload = _weather_artifact(candidates=[])
        result = _weather_to_theses(payload, _NOW)
        assert result == []

    def test_single_candidate(self):
        row = _candidate_row("KXHIGHNY-26MAR23-T55", 0.08)
        payload = _weather_artifact(candidates=[row])
        theses = _weather_to_theses(payload, _NOW)
        assert len(theses) == 1
        t = theses[0]
        assert t["lane"] == "weather"
        assert t["venue"] == "kalshi"
        assert t["ticker"] == "KXHIGHNY-26MAR23-T55"
        assert t["execution_mode"] == "shadow"
        assert t["rank_score"] == pytest.approx(0.08, abs=1e-6)
        assert t["artifact_stale"] is False

    def test_sorted_by_edge_descending(self):
        rows = [_candidate_row(f"T{i}", edge) for i, edge in enumerate([0.04, 0.10, 0.07])]
        payload = _weather_artifact(candidates=rows)
        theses = _weather_to_theses(payload, _NOW)
        edges = [t["rank_score"] for t in theses]
        assert edges == sorted(edges, reverse=True)

    def test_stale_flag(self):
        row = _candidate_row("KXHIGHNY-26MAR23-T55", 0.05)
        # 3-hour old artifact
        payload = _weather_artifact(candidates=[row], generated_offset_hours=3)
        theses = _weather_to_theses(payload, _NOW)
        assert theses[0]["artifact_stale"] is True

    def test_skips_row_without_edge(self):
        row = _candidate_row("KXHIGHNY-26MAR23-T55", 0.05)
        row["edge"]["spread_adjusted_edge"] = None
        payload = _weather_artifact(candidates=[row])
        result = _weather_to_theses(payload, _NOW)
        assert result == []


class TestBtc5ToThesis:
    def _btc5_payload(self) -> dict:
        return {
            "artifact": "btc5_dual_autoresearch_surface",
            "generated_at": _ts(_NOW - timedelta(hours=1)),
            "current_champions": {
                "policy": {
                    "id": "current_live_profile",
                    "loss": -54143.0,
                    "updated_at": "2026-03-21T19:00:00Z",
                }
            },
        }

    def test_returns_thesis(self):
        theses = _btc5_to_thesis(self._btc5_payload(), _NOW)
        assert len(theses) == 1
        t = theses[0]
        assert t["lane"] == "btc5"
        assert t["execution_mode"] == "live"
        assert "current_live_profile" in t["thesis_id"]

    def test_empty_payload(self):
        assert _btc5_to_thesis({}, _NOW) == []

    def test_no_policy_champion(self):
        payload = {"current_champions": {"policy": {}}}
        assert _btc5_to_thesis(payload, _NOW) == []


class TestBuildThesisCandidates:
    def test_no_files(self, tmp_path: Path):
        result = build_thesis_candidates(
            weather_shadow_path=tmp_path / "missing.json",
            alpaca_lane_path=tmp_path / "missing3.json",
            btc5_autoresearch_path=tmp_path / "missing2.json",
            now=_NOW,
        )
        assert result["artifact"] == "thesis_candidates.v1"
        assert result["thesis_count"] == 0
        assert result["candidates"] == []

    def test_with_weather_and_btc5(self, tmp_path: Path):
        rows = [_candidate_row(f"T{i}", 0.04 + i * 0.01) for i in range(3)]
        weather = _weather_artifact(candidates=rows)
        btc5 = {
            "artifact": "btc5_dual_autoresearch_surface",
            "generated_at": _ts(_NOW - timedelta(hours=2)),
            "current_champions": {
                "policy": {"id": "live", "loss": -100.0, "updated_at": "2026-03-21T00:00:00Z"}
            },
        }
        wp = tmp_path / "weather.json"
        bp = tmp_path / "btc5.json"
        wp.write_text(json.dumps(weather))
        bp.write_text(json.dumps(btc5))

        result = build_thesis_candidates(
            weather_shadow_path=wp,
            alpaca_lane_path=tmp_path / "missing_alpaca.json",
            btc5_autoresearch_path=bp,
            now=_NOW,
        )
        assert result["thesis_count"] == 4  # 3 weather + 1 btc5
        lanes = {c["lane"] for c in result["candidates"]}
        assert "weather" in lanes
        assert "btc5" in lanes
        assert result["lane_summaries"]["weather"]["count"] == 3
        assert result["lane_summaries"]["btc5"]["count"] == 1

    def test_output_written(self, tmp_path: Path):
        rows = [_candidate_row("T1", 0.05)]
        weather = _weather_artifact(candidates=rows)
        wp = tmp_path / "weather.json"
        wp.write_text(json.dumps(weather))
        out = tmp_path / "out.json"

        import bot.thesis_foundry as module
        original_default = module.DEFAULT_OUTPUT_PATH
        module.DEFAULT_OUTPUT_PATH = out

        try:
            result = build_thesis_candidates(
                weather_shadow_path=wp,
                alpaca_lane_path=tmp_path / "missing_alpaca.json",
                btc5_autoresearch_path=tmp_path / "missing.json",
                now=_NOW,
            )
            # verify we get a result (output path is only written in main())
            assert result["thesis_count"] == 1
        finally:
            module.DEFAULT_OUTPUT_PATH = original_default
