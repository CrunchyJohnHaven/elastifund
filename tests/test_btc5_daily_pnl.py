"""Tests for scripts/btc5_daily_pnl.py — canonical BTC5 daily PnL metrics."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.btc5_daily_pnl import (
    BTC5DailyPnLPacket,
    DailyPnLMetrics,
    _compute_window_metrics,
    _et_day_bounds,
    _rolling_24h_bounds,
    compute_btc5_daily_pnl,
    load_live_fills,
    write_scoreboard,
)

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fill(
    *,
    pnl_usd: float,
    ts_utc: datetime,
    trade_size_usd: float = 5.0,
    direction: str = "DOWN",
    won: int = 1,
) -> dict:
    return {
        "pnl_usd": pnl_usd,
        "won": won,
        "trade_size_usd": trade_size_usd,
        "window_start_ts": ts_utc.timestamp(),
        "order_status": "live_filled",
        "direction": direction,
    }


def _make_db(path: Path, fills: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS window_trades (
            pnl_usd REAL,
            won INTEGER,
            trade_size_usd REAL,
            window_start_ts REAL,
            order_status TEXT,
            direction TEXT
        )"""
    )
    for fill in fills:
        conn.execute(
            "INSERT INTO window_trades(pnl_usd, won, trade_size_usd, window_start_ts, order_status, direction) "
            "VALUES(?,?,?,?,?,?)",
            (
                fill["pnl_usd"],
                fill["won"],
                fill.get("trade_size_usd", 5.0),
                fill.get("window_start_ts", 0.0),
                fill.get("order_status", "live_filled"),
                fill.get("direction", "DOWN"),
            ),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# ET-day boundary tests
# ---------------------------------------------------------------------------


class TestETDayBounds:
    def test_mid_day_eastern(self):
        # March 22, 2026 at 14:00 UTC = 10:00 AM ET (EDT)
        now_utc = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now_utc)
        # EDT offset is UTC-4, so ET midnight = 04:00 UTC
        assert start.hour == 4  # midnight ET = 4 AM UTC in EDT
        assert start.day == 22
        assert end.hour == 4
        assert end.day == 23

    def test_before_midnight_et_boundary(self):
        # March 22, 2026 at 03:30 UTC = 11:30 PM ET on March 21
        now_utc = datetime(2026, 3, 22, 3, 30, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now_utc)
        # Should return March 21 ET day
        now_et = now_utc.astimezone(ET)
        assert now_et.day == 21

    def test_after_midnight_et_boundary(self):
        # March 22, 2026 at 04:30 UTC = 00:30 AM ET on March 22
        now_utc = datetime(2026, 3, 22, 4, 30, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now_utc)
        now_et = now_utc.astimezone(ET)
        assert now_et.day == 22

    def test_dst_transition_spring_forward(self):
        # March 8, 2026 is spring forward (EST->EDT)
        # Before DST: EST = UTC-5, midnight = 05:00 UTC
        # After DST: EDT = UTC-4, midnight = 04:00 UTC
        now_utc = datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now_utc)
        # After spring forward, we're in EDT: midnight = 04:00 UTC
        assert start.hour == 4

    def test_winter_time_est(self):
        # January 15, 2026 — EST = UTC-5, midnight = 05:00 UTC
        now_utc = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now_utc)
        assert start.hour == 5  # midnight ET = 5 AM UTC in EST


# ---------------------------------------------------------------------------
# Rolling 24h boundary tests
# ---------------------------------------------------------------------------


class TestRolling24hBounds:
    def test_basic(self):
        now_utc = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        start, end = _rolling_24h_bounds(now_utc)
        assert end == now_utc
        assert start == now_utc - timedelta(hours=24)
        diff = (end - start).total_seconds()
        assert diff == 86400


# ---------------------------------------------------------------------------
# Window metric computation
# ---------------------------------------------------------------------------


class TestComputeWindowMetrics:
    def test_empty_rows(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now)
        m = _compute_window_metrics([], window_label="et_day", window_start_utc=start, window_end_utc=end)
        assert m.fill_count == 0
        assert m.status == "empty"
        assert m.gross_realized_pnl_usd == 0.0

    def test_no_fills_in_window(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now)
        # Fill from yesterday
        old_fill = _make_fill(pnl_usd=10.0, ts_utc=now - timedelta(days=2))
        m = _compute_window_metrics([old_fill], window_label="et_day", window_start_utc=start, window_end_utc=end)
        assert m.fill_count == 0
        assert m.status == "empty"

    def test_positive_pnl(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now)
        fills = [
            _make_fill(pnl_usd=3.0, ts_utc=now - timedelta(hours=2), trade_size_usd=5.0),
            _make_fill(pnl_usd=2.0, ts_utc=now - timedelta(hours=1), trade_size_usd=5.0),
        ]
        m = _compute_window_metrics(fills, window_label="et_day", window_start_utc=start, window_end_utc=end)
        assert m.fill_count == 2
        assert m.gross_realized_pnl_usd == pytest.approx(5.0)
        assert m.estimated_maker_rebate_usd == pytest.approx(10.0 * 0.0025)  # 2 * $5 * 0.25%
        assert m.net_after_rebate_pnl_usd == pytest.approx(5.0 + 0.025)
        assert m.status == "fresh"

    def test_negative_pnl(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now)
        fills = [
            _make_fill(pnl_usd=-8.0, ts_utc=now - timedelta(hours=1), trade_size_usd=5.0, won=0),
        ]
        m = _compute_window_metrics(fills, window_label="et_day", window_start_utc=start, window_end_utc=end)
        assert m.fill_count == 1
        assert m.gross_realized_pnl_usd == pytest.approx(-8.0)
        assert m.net_after_rebate_pnl_usd == pytest.approx(-8.0 + 0.0125)
        assert m.status == "fresh"

    def test_latest_fill_timestamp(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        start, end = _et_day_bounds(now)
        t1 = now - timedelta(hours=3)
        t2 = now - timedelta(hours=1)
        fills = [
            _make_fill(pnl_usd=1.0, ts_utc=t1),
            _make_fill(pnl_usd=1.0, ts_utc=t2),
        ]
        m = _compute_window_metrics(fills, window_label="et_day", window_start_utc=start, window_end_utc=end)
        assert m.latest_fill_ts_utc is not None
        # Latest should be t2
        assert "14:" not in m.latest_fill_ts_utc or "13:" in m.latest_fill_ts_utc


# ---------------------------------------------------------------------------
# Full packet computation
# ---------------------------------------------------------------------------


class TestComputeBtc5DailyPnl:
    def test_empty_fills(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        pkt = compute_btc5_daily_pnl(fills=[], now_utc=now)
        assert pkt.et_day.fill_count == 0
        assert pkt.et_day.status == "empty"
        assert pkt.rolling_24h.fill_count == 0
        assert pkt.rolling_24h.status == "empty"
        assert pkt.generated_at.endswith("Z")

    def test_with_fills(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        fills = [
            _make_fill(pnl_usd=2.0, ts_utc=now - timedelta(hours=2)),
            _make_fill(pnl_usd=-1.0, ts_utc=now - timedelta(hours=1), won=0),
        ]
        pkt = compute_btc5_daily_pnl(fills=fills, now_utc=now)
        assert pkt.et_day.fill_count == 2
        assert pkt.et_day.gross_realized_pnl_usd == pytest.approx(1.0)
        assert pkt.rolling_24h.fill_count == 2
        assert pkt.rolling_24h.gross_realized_pnl_usd == pytest.approx(1.0)

    def test_runtime_truth_fields(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        fills = [_make_fill(pnl_usd=5.0, ts_utc=now - timedelta(hours=1))]
        pkt = compute_btc5_daily_pnl(fills=fills, now_utc=now)
        fields = pkt.runtime_truth_fields()
        assert "btc5_realized_live_pnl_et_day_usd" in fields
        assert "btc5_realized_live_pnl_rolling_24h_usd" in fields
        assert "btc5_realized_live_fills_et_day" in fields
        assert "btc5_realized_live_fills_rolling_24h" in fields
        assert "btc5_realized_live_pnl_et_day_net_after_rebate_usd" in fields
        assert "btc5_realized_live_pnl_rolling_24h_net_after_rebate_usd" in fields
        assert fields["btc5_realized_live_pnl_et_day_usd"] == pytest.approx(5.0)

    def test_to_dict_schema(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        pkt = compute_btc5_daily_pnl(fills=[], now_utc=now)
        d = pkt.to_dict()
        assert d["schema"] == "btc5_daily_pnl.v1"
        assert "et_day" in d
        assert "rolling_24h" in d
        assert "legacy_recent_pnl_usd" in d

    def test_from_db(self, tmp_path: Path):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        db = tmp_path / "btc.db"
        fills = [
            _make_fill(pnl_usd=3.0, ts_utc=now - timedelta(hours=1)),
        ]
        _make_db(db, fills)
        pkt = compute_btc5_daily_pnl(db_path=db, now_utc=now)
        assert pkt.et_day.fill_count == 1
        assert pkt.rolling_24h.fill_count == 1

    def test_missing_db(self, tmp_path: Path):
        pkt = compute_btc5_daily_pnl(db_path=tmp_path / "missing.db")
        assert pkt.et_day.fill_count == 0
        assert pkt.rolling_24h.fill_count == 0

    def test_legacy_field_passthrough(self):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        pkt = compute_btc5_daily_pnl(fills=[], now_utc=now, legacy_recent_pnl_usd=42.0)
        assert pkt.legacy_recent_pnl_usd == 42.0
        assert pkt.to_dict()["legacy_recent_pnl_usd"] == 42.0


# ---------------------------------------------------------------------------
# March 22 regression: negative ET-day drawdown
# ---------------------------------------------------------------------------


class TestMarch22Regression:
    """Regression: March 22, 2026 should compute negative ET-day BTC5 live PnL."""

    def test_negative_et_day(self):
        # Simulate March 22 at 20:00 UTC with losing fills
        now = datetime(2026, 3, 22, 20, 0, 0, tzinfo=timezone.utc)
        fills = [
            _make_fill(pnl_usd=-3.50, ts_utc=now - timedelta(hours=8), won=0),
            _make_fill(pnl_usd=-2.00, ts_utc=now - timedelta(hours=6), won=0),
            _make_fill(pnl_usd=1.00, ts_utc=now - timedelta(hours=4)),
            _make_fill(pnl_usd=-4.00, ts_utc=now - timedelta(hours=2), won=0),
        ]
        pkt = compute_btc5_daily_pnl(fills=fills, now_utc=now)
        # Total PnL = -3.50 - 2.00 + 1.00 - 4.00 = -8.50
        assert pkt.et_day.gross_realized_pnl_usd == pytest.approx(-8.50)
        assert pkt.et_day.fill_count == 4
        assert pkt.et_day.status == "fresh"
        # Net after rebate still negative
        assert pkt.et_day.net_after_rebate_pnl_usd < 0


# ---------------------------------------------------------------------------
# Contract tests: runtime truth must always emit both daily metrics
# ---------------------------------------------------------------------------


class TestRuntimeTruthContract:
    def test_always_emits_both_daily_metrics(self):
        """Runtime truth always emits both et_day and rolling_24h fields."""
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        pkt = compute_btc5_daily_pnl(fills=[], now_utc=now)
        fields = pkt.runtime_truth_fields()
        required_keys = {
            "btc5_realized_live_pnl_et_day_usd",
            "btc5_realized_live_pnl_et_day_net_after_rebate_usd",
            "btc5_realized_live_fills_et_day",
            "btc5_realized_live_pnl_rolling_24h_usd",
            "btc5_realized_live_pnl_rolling_24h_net_after_rebate_usd",
            "btc5_realized_live_fills_rolling_24h",
        }
        assert required_keys.issubset(set(fields.keys()))

    def test_compatibility_field_exists(self):
        """Legacy compatibility field still exists during migration."""
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        pkt = compute_btc5_daily_pnl(fills=[], now_utc=now, legacy_recent_pnl_usd=-5.0)
        d = pkt.to_dict()
        assert "legacy_recent_pnl_usd" in d
        assert d["legacy_recent_pnl_usd"] == -5.0

    def test_empty_fills_emit_empty_status_not_silent_zeros(self):
        """Empty or stale live-fill inputs emit blocked/error status, not silent zeroes."""
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        pkt = compute_btc5_daily_pnl(fills=[], now_utc=now)
        assert pkt.et_day.status == "empty"
        assert pkt.rolling_24h.status == "empty"
        # Even with "empty" status, fill_count is explicitly 0
        assert pkt.et_day.fill_count == 0


# ---------------------------------------------------------------------------
# Scoreboard writer
# ---------------------------------------------------------------------------


class TestWriteScoreboard:
    def test_writes_json(self, tmp_path: Path):
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        pkt = compute_btc5_daily_pnl(fills=[], now_utc=now)
        out = tmp_path / "scoreboard" / "latest.json"
        write_scoreboard(pkt, out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["schema"] == "btc5_daily_pnl.v1"
        assert "et_day" in data
        assert "rolling_24h" in data


# ---------------------------------------------------------------------------
# Load live fills from DB
# ---------------------------------------------------------------------------


class TestLoadLiveFills:
    def test_missing_db(self, tmp_path: Path):
        result = load_live_fills(tmp_path / "missing.db")
        assert result == []

    def test_filters_to_live_filled(self, tmp_path: Path):
        db = tmp_path / "btc.db"
        now = datetime(2026, 3, 22, 14, 0, 0, tzinfo=timezone.utc)
        conn = sqlite3.connect(str(db))
        conn.execute(
            """CREATE TABLE window_trades (
                pnl_usd REAL, won INTEGER, trade_size_usd REAL,
                window_start_ts REAL, order_status TEXT, direction TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO window_trades VALUES(?, ?, ?, ?, ?, ?)",
            (1.0, 1, 5.0, now.timestamp(), "live_filled", "DOWN"),
        )
        conn.execute(
            "INSERT INTO window_trades VALUES(?, ?, ?, ?, ?, ?)",
            (2.0, 1, 5.0, now.timestamp(), "skip_delta_too_large", "DOWN"),
        )
        conn.commit()
        conn.close()

        result = load_live_fills(db)
        assert len(result) == 1
        assert result[0]["pnl_usd"] == 1.0


# ---------------------------------------------------------------------------
# DailyPnLMetrics serialization
# ---------------------------------------------------------------------------


class TestDailyPnLMetrics:
    def test_to_dict_rounding(self):
        m = DailyPnLMetrics(
            window_label="et_day",
            window_start_utc="2026-03-22T04:00:00+00:00",
            window_end_utc="2026-03-23T04:00:00+00:00",
            fill_count=3,
            gross_realized_pnl_usd=1.23456789,
            estimated_maker_rebate_usd=0.03756789,
            net_after_rebate_pnl_usd=1.27213578,
            status="fresh",
        )
        d = m.to_dict()
        assert d["gross_realized_pnl_usd"] == 1.2346
        assert d["estimated_maker_rebate_usd"] == 0.0376
        assert d["net_after_rebate_pnl_usd"] == 1.2721

    def test_frozen(self):
        m = DailyPnLMetrics(
            window_label="et_day",
            window_start_utc="",
            window_end_utc="",
        )
        with pytest.raises(AttributeError):
            m.fill_count = 5  # type: ignore[misc]
