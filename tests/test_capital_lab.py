"""Tests for scripts/capital_lab.py"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.capital_lab import (
    _analyze_btc5_fills,
    _analyze_weather_decisions,
    _build_proving_ground,
    _check_btc5_daily_pnl_gate,
    run_capital_lab,
    BTC5_DAILY_PNL_EXPANSION_BLOCK_USD,
    BTC5_ROLLING_PNL_EXPANSION_BLOCK_USD,
)

_NOW = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def _write_decisions(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _make_db(path: Path, fills: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS window_trades (
            pnl_usd REAL, won INTEGER, order_status TEXT
        )"""
    )
    for fill in fills:
        conn.execute(
            "INSERT INTO window_trades(pnl_usd, won, order_status) VALUES(?,?,?)",
            (fill["pnl_usd"], fill["won"], fill.get("order_status", "filled")),
        )
    conn.commit()
    conn.close()


class TestAnalyzeWeatherDecisions:
    def test_missing_file(self, tmp_path: Path):
        result = _analyze_weather_decisions(tmp_path / "missing.jsonl")
        assert result["status"] == "missing"
        assert result["decision_count"] == 0

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "decisions.jsonl"
        path.write_text("")
        result = _analyze_weather_decisions(path)
        assert result["status"] == "ok"
        assert result["decision_count"] == 0

    def test_counts_decisions(self, tmp_path: Path):
        path = tmp_path / "decisions.jsonl"
        rows = [
            {"city": "NYC", "execution_result": "rejected", "execution_mode": "live",
             "notional_usd": 0.0, "timestamp": _ts(_NOW - timedelta(days=i)),
             "reason_code": "already_ordered"}
            for i in range(5)
        ]
        _write_decisions(path, rows)
        result = _analyze_weather_decisions(path)
        assert result["decision_count"] == 5
        assert result["rejected_count"] == 5
        assert result["executed_count"] == 0

    def test_executed_notional(self, tmp_path: Path):
        path = tmp_path / "decisions.jsonl"
        rows = [
            {"city": "NYC", "execution_result": "placed", "execution_mode": "live",
             "notional_usd": 5.0, "timestamp": _ts(_NOW)}
        ]
        _write_decisions(path, rows)
        result = _analyze_weather_decisions(path)
        assert result["executed_count"] == 1
        assert result["total_notional_usd"] == pytest.approx(5.0)

    def test_doctrine_candidate_needs_enough_decisions_and_days(self, tmp_path: Path):
        path = tmp_path / "decisions.jsonl"
        # 50 decisions over 7 days = doctrine candidate
        rows = []
        for i in range(50):
            day = i % 7  # spread across 7 days
            rows.append({
                "city": "NYC",
                "execution_result": "rejected",
                "execution_mode": "shadow",
                "notional_usd": 0.0,
                "timestamp": _ts(_NOW - timedelta(days=day, hours=i % 24)),
                "reason_code": "already_ordered",
            })
        _write_decisions(path, rows)
        result = _analyze_weather_decisions(path)
        assert result["doctrine_candidate"] is True
        assert result["promotion_gate"]["pass"] is True

    def test_not_doctrine_candidate_too_few_days(self, tmp_path: Path):
        path = tmp_path / "decisions.jsonl"
        rows = [
            {"city": "NYC", "execution_result": "rejected", "execution_mode": "shadow",
             "notional_usd": 0.0, "timestamp": _ts(_NOW)}
            for _ in range(100)
        ]
        _write_decisions(path, rows)
        result = _analyze_weather_decisions(path)
        # 100 decisions but all same day = only 1 unique day
        assert result["unique_days"] == 1
        assert result["doctrine_candidate"] is False


class TestAnalyzeBtc5Fills:
    def test_missing_db(self, tmp_path: Path):
        result = _analyze_btc5_fills(tmp_path / "missing.db")
        assert result["status"] == "missing"
        assert result["fills"] == 0

    def test_empty_db(self, tmp_path: Path):
        path = tmp_path / "btc.db"
        _make_db(path, [])
        result = _analyze_btc5_fills(path)
        assert result["status"] == "ok"
        assert result["fills"] == 0
        assert result["win_rate"] is None

    def test_all_wins(self, tmp_path: Path):
        path = tmp_path / "btc.db"
        fills = [{"pnl_usd": 1.0, "won": 1} for _ in range(25)]
        _make_db(path, fills)
        result = _analyze_btc5_fills(path)
        assert result["fills"] == 25
        assert result["win_rate"] == pytest.approx(1.0)
        assert result["profit_factor"] is None  # no losses

    def test_doctrine_candidate_threshold(self, tmp_path: Path):
        path = tmp_path / "btc.db"
        # 20 fills, 12 wins (60% WR), PF > 1.1
        fills = (
            [{"pnl_usd": 2.0, "won": 1} for _ in range(12)]
            + [{"pnl_usd": -1.0, "won": 0} for _ in range(8)]
        )
        _make_db(path, fills)
        result = _analyze_btc5_fills(path)
        assert result["fills"] == 20
        assert result["win_rate"] == pytest.approx(0.6)
        assert result["doctrine_candidate"] is True
        assert result["promotion_gate"]["pass"] is True

    def test_not_doctrine_candidate_below_threshold(self, tmp_path: Path):
        path = tmp_path / "btc.db"
        fills = [{"pnl_usd": 1.0, "won": 1} for _ in range(10)]  # only 10 fills
        _make_db(path, fills)
        result = _analyze_btc5_fills(path)
        assert result["doctrine_candidate"] is False


class TestBuildProvingGround:
    def test_shadow_lane(self):
        metrics = {
            "weather": {
                "status": "ok",
                "executed_count": 0,
                "doctrine_candidate": False,
                "promotion_gate": {"pass": False},
            }
        }
        pg = _build_proving_ground(metrics, _NOW)
        assert "weather" in pg["lanes_shadow"]
        assert pg["self_improving"] is False

    def test_active_lane(self):
        metrics = {
            "weather": {
                "status": "ok",
                "executed_count": 5,
                "doctrine_candidate": True,
                "promotion_gate": {"pass": True},
            }
        }
        pg = _build_proving_ground(metrics, _NOW)
        assert "weather" in pg["lanes_active"]
        assert "weather" in pg["doctrine_candidates"]
        assert "weather" in pg["promotion_gates_passing"]
        assert pg["self_improving"] is True

    def test_blocked_on_missing(self):
        metrics = {"btc5": {"status": "missing", "fills": 0, "doctrine_candidate": False, "promotion_gate": {"pass": False}}}
        pg = _build_proving_ground(metrics, _NOW)
        assert "btc5" in pg["lanes_blocked"]


class TestRunCapitalLab:
    def test_all_missing(self, tmp_path: Path):
        result = run_capital_lab(
            weather_decisions_path=tmp_path / "missing.jsonl",
            btc5_db_path=tmp_path / "missing.db",
            output_path=tmp_path / "out.json",
            now=_NOW,
        )
        assert result["artifact"] == "capital_lab.v1"
        assert result["status"] == "blocked"
        assert (tmp_path / "out.json").exists()
        pg = result["proving_ground"]
        assert "weather" in pg["lanes_blocked"]
        assert "btc5" in pg["lanes_blocked"]

    def test_writes_output(self, tmp_path: Path):
        out = tmp_path / "out.json"
        run_capital_lab(
            weather_decisions_path=tmp_path / "missing.jsonl",
            btc5_db_path=tmp_path / "missing.db",
            output_path=out,
            now=_NOW,
        )
        payload = json.loads(out.read_text())
        assert payload["artifact"] == "capital_lab.v1"
        assert payload["status"] in {"fresh", "stale", "blocked"}
        assert "source_of_truth" in payload
        assert "proving_ground" in payload
        assert "lane_metrics" in payload

    def test_btc5_daily_pnl_gate_in_output(self, tmp_path: Path):
        out = tmp_path / "out.json"
        run_capital_lab(
            weather_decisions_path=tmp_path / "missing.jsonl",
            btc5_db_path=tmp_path / "missing.db",
            output_path=out,
            now=_NOW,
        )
        payload = json.loads(out.read_text())
        assert "btc5_daily_pnl_gate" in payload

    def test_negative_daily_pnl_blocks_promotion(self, tmp_path: Path):
        """When daily PnL is materially negative, promotion gate must fail."""
        db = tmp_path / "btc.db"
        # Create fills with negative PnL in the current ET day
        conn = sqlite3.connect(str(db))
        conn.execute(
            """CREATE TABLE window_trades (
                pnl_usd REAL, won INTEGER, order_status TEXT,
                trade_size_usd REAL, window_start_ts REAL, direction TEXT
            )"""
        )
        # 25 fills to meet doctrine_candidate threshold, but heavy losses today
        for i in range(12):
            conn.execute(
                "INSERT INTO window_trades VALUES(?,?,?,?,?,?)",
                (2.0, 1, "live_filled", 5.0, _NOW.timestamp() - (i * 300 + 3600), "DOWN"),
            )
        for i in range(13):
            conn.execute(
                "INSERT INTO window_trades VALUES(?,?,?,?,?,?)",
                (-3.0, 0, "live_filled", 5.0, _NOW.timestamp() - (i * 300 + 600), "DOWN"),
            )
        conn.commit()
        conn.close()

        result = run_capital_lab(
            weather_decisions_path=tmp_path / "missing.jsonl",
            btc5_db_path=db,
            output_path=tmp_path / "out.json",
            now=_NOW,
        )
        btc5 = result["lane_metrics"]["btc5"]
        gate = btc5.get("daily_pnl_gate", {})
        # Net PnL is 12*2 - 13*3 = 24 - 39 = -15, well below threshold
        assert gate.get("rolling_24h_pnl_usd", 0) < BTC5_ROLLING_PNL_EXPANSION_BLOCK_USD
        # Promotion gate blocked by daily PnL
        assert btc5["promotion_gate"]["pass"] is False


def _make_db_with_ts(path: Path, fills: list[dict]) -> None:
    """Create DB with timestamp column for daily PnL tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS window_trades (
            pnl_usd REAL, won INTEGER, order_status TEXT,
            trade_size_usd REAL, window_start_ts REAL, direction TEXT
        )"""
    )
    for fill in fills:
        conn.execute(
            "INSERT INTO window_trades(pnl_usd, won, order_status, trade_size_usd, window_start_ts, direction) "
            "VALUES(?,?,?,?,?,?)",
            (
                fill.get("pnl_usd", 0.0),
                fill.get("won", 0),
                fill.get("order_status", "live_filled"),
                fill.get("trade_size_usd", 5.0),
                fill.get("window_start_ts", 0.0),
                fill.get("direction", "DOWN"),
            ),
        )
    conn.commit()
    conn.close()


class TestCheckBtc5DailyPnlGate:
    def test_missing_db_passes(self, tmp_path: Path):
        gate = _check_btc5_daily_pnl_gate(tmp_path / "missing.db", _NOW)
        assert gate["pass"] is True
        assert gate["et_day_fills"] == 0

    def test_positive_pnl_passes(self, tmp_path: Path):
        db = tmp_path / "btc.db"
        fills = [
            {"pnl_usd": 5.0, "won": 1, "order_status": "live_filled",
             "trade_size_usd": 5.0, "window_start_ts": _NOW.timestamp() - 3600,
             "direction": "DOWN"},
        ]
        _make_db_with_ts(db, fills)
        gate = _check_btc5_daily_pnl_gate(db, _NOW)
        assert gate["pass"] is True
        assert gate["et_day_pnl_usd"] > 0

    def test_materially_negative_et_day_blocks(self, tmp_path: Path):
        db = tmp_path / "btc.db"
        fills = [
            {"pnl_usd": -6.0, "won": 0, "order_status": "live_filled",
             "trade_size_usd": 5.0, "window_start_ts": _NOW.timestamp() - 3600,
             "direction": "DOWN"},
        ]
        _make_db_with_ts(db, fills)
        gate = _check_btc5_daily_pnl_gate(db, _NOW)
        assert gate["pass"] is False
        assert any("et_day_pnl" in b for b in gate["blockers"])

    def test_materially_negative_rolling_blocks(self, tmp_path: Path):
        db = tmp_path / "btc.db"
        # Several losing fills spread over the past 24h
        fills = []
        for i in range(5):
            fills.append({
                "pnl_usd": -3.0, "won": 0, "order_status": "live_filled",
                "trade_size_usd": 5.0,
                "window_start_ts": _NOW.timestamp() - (i * 3600 + 1800),
                "direction": "DOWN",
            })
        _make_db_with_ts(db, fills)
        gate = _check_btc5_daily_pnl_gate(db, _NOW)
        # Total = -15, below rolling threshold of -10
        assert gate["pass"] is False
        assert any("rolling_24h_pnl" in b for b in gate["blockers"])
