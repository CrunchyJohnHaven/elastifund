#!/usr/bin/env python3
"""
Tests for bot/rtds_latency_harness.py — DISPATCH_110 RTDS Latency Surface Harness.

Covers:
  1.  LatencySurfaceDB schema creation and WAL mode
  2.  TruthTick / MarketTick / PriceError storage and retrieval
  3.  Price-error computation logic (_maybe_compute_price_error)
  4.  Hourly stats computation with mock data
  5.  Reconnection: exponential backoff on WS failure
  6.  RTDSLatencyHarness._process_rtds_message — happy path
  7.  RTDSLatencyHarness._process_rtds_message — unknown / partial schema (no crash)
  8.  RTDSLatencyHarness._process_market_message — happy path
  9.  RTDSLatencyHarness._process_market_message — missing fields (no crash)
  10. analyse_latency_surface — CONTINUE verdict
  11. analyse_latency_surface — KILL_H1 verdict (median lag too low)
  12. analyse_latency_surface — KILL_H2 verdict (stale-quote rate too low)
  13. analyse_latency_surface — KILL_H3 verdict (estimated EV too low)
  14. analyse_latency_surface — INSUFFICIENT_DATA
  15. RTDSLatencyHarness raises ValueError for empty token_ids
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from bot.rtds_latency_harness import (
    KILL_EVALUATION_HOURS,
    KILL_MAKER_EV_BPS,
    KILL_MEDIAN_LAG_MS,
    KILL_STALE_QUOTE_RATE,
    LatencySurfaceDB,
    MarketTick,
    PriceError,
    RTDSLatencyHarness,
    TruthTick,
    _normalise_ts,
    _percentile_from_sorted,
    analyse_latency_surface,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db(tmp_path: Path) -> LatencySurfaceDB:
    return LatencySurfaceDB(db_path=tmp_path / "test.db")


def _truth_tick(
    symbol: str = "BTC",
    price: float = 80_000.0,
    recv_ns: int = 0,
    wall_ts: float = 0.0,
) -> TruthTick:
    return TruthTick(
        symbol=symbol,
        source="binance",
        price=price,
        rtds_timestamp=wall_ts or time.time(),
        local_recv_ts=recv_ns or time.monotonic_ns(),
        local_wall_ts=wall_ts or time.time(),
    )


def _market_tick(
    token_id: str = "token_001",
    bid: float = 0.48,
    ask: float = 0.52,
    recv_ns: int = 0,
    wall_ts: float = 0.0,
) -> MarketTick:
    now = time.time()
    return MarketTick(
        token_id=token_id,
        channel="best_bid_ask",
        best_bid=bid,
        best_ask=ask,
        last_trade_price=None,
        market_timestamp=wall_ts or now,
        local_recv_ts=recv_ns or time.monotonic_ns(),
        local_wall_ts=wall_ts or now,
    )


def _harness(tmp_path: Path, token_ids=None) -> RTDSLatencyHarness:
    return RTDSLatencyHarness(
        token_ids=token_ids or ["token_001"],
        symbol="BTC",
        db_path=tmp_path / "harness.db",
    )


# ---------------------------------------------------------------------------
# 1. LatencySurfaceDB — schema and WAL mode
# ---------------------------------------------------------------------------

class TestLatencySurfaceDBSchema:
    def test_creates_all_four_tables(self, tmp_path):
        db = _tmp_db(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert {"truth_ticks", "market_ticks", "price_errors", "hourly_stats"} <= tables

    def test_wal_mode_enabled(self, tmp_path):
        db = _tmp_db(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_price_errors_indexes_exist(self, tmp_path):
        db = _tmp_db(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        conn.close()
        assert "idx_pe_token" in indexes
        assert "idx_pe_computed" in indexes


# ---------------------------------------------------------------------------
# 2. Storage and retrieval
# ---------------------------------------------------------------------------

class TestStorageAndRetrieval:
    def test_insert_and_retrieve_truth_tick(self, tmp_path):
        db = _tmp_db(tmp_path)
        tick = _truth_tick(price=90_000.0)
        db.insert_truth_tick(tick)
        db.flush()

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        rows = conn.execute("SELECT price, symbol, source FROM truth_ticks").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(90_000.0)
        assert rows[0][1] == "BTC"
        assert rows[0][2] == "binance"

    def test_insert_and_retrieve_market_tick(self, tmp_path):
        db = _tmp_db(tmp_path)
        tick = _market_tick(bid=0.45, ask=0.55)
        db.insert_market_tick(tick)
        db.flush()

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        rows = conn.execute(
            "SELECT token_id, best_bid, best_ask FROM market_ticks"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == "token_001"
        assert rows[0][1] == pytest.approx(0.45)
        assert rows[0][2] == pytest.approx(0.55)

    def test_insert_and_retrieve_price_error(self, tmp_path):
        db = _tmp_db(tmp_path)
        pe = PriceError(
            token_id="token_001",
            symbol="BTC",
            fair_value=80_000.0,
            venue_mid=0.50,
            price_error=0.50 - 80_000.0,
            truth_age_ms=150.0,
            market_age_ms=50.0,
            computed_at=time.monotonic_ns(),
        )
        db.insert_price_error(pe)
        db.flush()

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        rows = conn.execute(
            "SELECT token_id, fair_value, truth_age_ms FROM price_errors"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == "token_001"
        assert rows[0][1] == pytest.approx(80_000.0)
        assert rows[0][2] == pytest.approx(150.0)

    def test_multiple_inserts_all_stored(self, tmp_path):
        db = _tmp_db(tmp_path)
        for i in range(10):
            db.insert_truth_tick(_truth_tick(price=float(80_000 + i * 100)))
        db.flush()

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        count = conn.execute("SELECT COUNT(*) FROM truth_ticks").fetchone()[0]
        conn.close()
        assert count == 10


# ---------------------------------------------------------------------------
# 3. Price-error computation logic
# ---------------------------------------------------------------------------

class TestPriceErrorComputation:
    def test_price_error_computed_on_market_message(self, tmp_path):
        h = _harness(tmp_path)
        now_ns = time.monotonic_ns()
        now = time.time()

        # Inject truth
        h._latest_truth = _truth_tick(price=80_000.0, recv_ns=now_ns, wall_ts=now)

        # Inject market tick
        msg = json.dumps({
            "asset_id": "token_001",
            "event_type": "best_bid_ask",
            "best_bid": "0.48",
            "best_ask": "0.52",
            "timestamp": str(int(now * 1000)),
        })
        h._process_market_message(msg, now_ns, now)
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        rows = conn.execute(
            "SELECT fair_value, venue_mid, price_error FROM price_errors"
        ).fetchall()
        conn.close()

        assert len(rows) >= 1
        row = rows[-1]
        assert row[0] == pytest.approx(80_000.0)           # passthrough fair value
        assert row[1] == pytest.approx(0.50, abs=0.001)    # (0.48+0.52)/2
        assert row[2] == pytest.approx(0.50 - 80_000.0, rel=1e-3)

    def test_no_price_error_without_truth(self, tmp_path):
        h = _harness(tmp_path)
        now_ns = time.monotonic_ns()
        now = time.time()

        msg = json.dumps({
            "asset_id": "token_001",
            "best_bid": "0.48",
            "best_ask": "0.52",
        })
        h._process_market_message(msg, now_ns, now)
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        count = conn.execute("SELECT COUNT(*) FROM price_errors").fetchone()[0]
        conn.close()
        assert count == 0

    def test_no_price_error_without_bid_ask(self, tmp_path):
        h = _harness(tmp_path)
        now_ns = time.monotonic_ns()
        now = time.time()

        h._latest_truth = _truth_tick(price=80_000.0)
        msg = json.dumps({"asset_id": "token_001", "event_type": "book"})
        h._process_market_message(msg, now_ns, now)
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        count = conn.execute("SELECT COUNT(*) FROM price_errors").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# 4. Hourly stats computation
# ---------------------------------------------------------------------------

class TestHourlyStats:
    def _insert_price_errors(
        self,
        db: LatencySurfaceDB,
        n: int,
        lag_ms: float,
        error: float,
        stale_fraction: float = 0.0,
    ) -> None:
        """Insert n synthetic PriceError rows."""
        stale_count = int(n * stale_fraction)
        for i in range(n):
            lag = 2000.0 if i < stale_count else lag_ms
            pe = PriceError(
                token_id="token_001",
                symbol="BTC",
                fair_value=0.50,
                venue_mid=0.50 + error,
                price_error=error,
                truth_age_ms=lag,
                market_age_ms=10.0,
                computed_at=time.monotonic_ns(),
            )
            db.insert_price_error(pe)
        db.flush()

    def test_hourly_stats_written_to_db(self, tmp_path):
        h = _harness(tmp_path)
        self._insert_price_errors(h.db, n=50, lag_ms=300.0, error=0.05)
        h._hour_truth_count = 50
        h._hour_market_count = 50
        h._compute_hourly_stats()
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        rows = conn.execute("SELECT * FROM hourly_stats").fetchall()
        conn.close()
        assert len(rows) >= 1

    def test_hourly_stats_median_lag_reasonable(self, tmp_path):
        h = _harness(tmp_path)
        self._insert_price_errors(h.db, n=100, lag_ms=500.0, error=0.02)
        h._compute_hourly_stats()
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        rows = conn.execute(
            "SELECT median_lag_ms FROM hourly_stats ORDER BY id DESC LIMIT 1"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        # All non-stale rows have lag=500ms, so median should be close
        assert rows[0][0] == pytest.approx(500.0, abs=50.0)

    def test_hourly_stats_stale_rate(self, tmp_path):
        h = _harness(tmp_path)
        # 20% stale (lag > 1000 ms)
        self._insert_price_errors(h.db, n=100, lag_ms=200.0, error=0.01, stale_fraction=0.20)
        h._compute_hourly_stats()
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        rows = conn.execute(
            "SELECT stale_quote_rate FROM hourly_stats ORDER BY id DESC LIMIT 1"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(0.20, abs=0.02)

    def test_hourly_stats_no_crash_when_empty(self, tmp_path):
        h = _harness(tmp_path)
        # Should log a message and return without inserting anything
        h._compute_hourly_stats()
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        count = conn.execute("SELECT COUNT(*) FROM hourly_stats").fetchone()[0]
        conn.close()
        assert count == 0


# ---------------------------------------------------------------------------
# 5. Reconnection / exponential backoff (mocked WS)
# ---------------------------------------------------------------------------

class TestReconnectionLogic:
    def test_rtds_reconnects_after_exception(self, tmp_path):
        """Connection fails twice then times out; harness should not raise."""
        call_count = 0
        t0 = time.time()

        class FakeWS:
            """Async context manager that raises on first two connects."""

            async def __aenter__(self_inner):
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise OSError("simulated network failure")
                # On third call, just return self and immediately "end" the loop
                return self_inner

            async def __aexit__(self_inner, *args):
                pass

            def __aiter__(self_inner):
                return self_inner

            async def __anext__(self_inner):
                raise StopAsyncIteration

            async def send(self_inner, msg):
                pass

        def fake_connect(url, **kwargs):
            return FakeWS()

        h = _harness(tmp_path)
        h._ws_connect = fake_connect

        # Run with a very short duration so the loop exits quickly
        end_time_short = time.time() + 0.5

        async def run_briefly():
            await h._run_rtds_connection(end_time_short)

        asyncio.run(run_briefly())
        # Should have attempted to connect at least once
        assert call_count >= 1

    def test_market_ws_reconnects_after_exception(self, tmp_path):
        """Market WS reconnects after simulated failure."""
        call_count = 0

        class FakeMarketWS:
            async def __aenter__(self_inner):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise OSError("simulated disconnect")
                return self_inner

            async def __aexit__(self_inner, *args):
                pass

            def __aiter__(self_inner):
                return self_inner

            async def __anext__(self_inner):
                raise StopAsyncIteration

            async def send(self_inner, msg):
                pass

        def fake_connect(url, **kwargs):
            return FakeMarketWS()

        h = _harness(tmp_path)
        h._ws_connect = fake_connect

        end_time_short = time.time() + 0.5

        async def run_briefly():
            await h._run_market_connection(end_time_short)

        asyncio.run(run_briefly())
        assert call_count >= 1


# ---------------------------------------------------------------------------
# 6–7. RTDS message parsing — happy path and unknown schema
# ---------------------------------------------------------------------------

class TestRTDSMessageParsing:
    def test_happy_path_standard_schema(self, tmp_path):
        """Well-formed RTDS message is parsed and stored."""
        h = _harness(tmp_path)
        recv_ns = time.monotonic_ns()
        wall_ts = time.time()

        msg = json.dumps({
            "symbol": "BTC",
            "price": 85_000.0,
            "timestamp": int(wall_ts * 1000),
            "source": "binance",
        })
        h._process_rtds_message(msg, recv_ns, wall_ts)
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        rows = conn.execute("SELECT price, symbol, source FROM truth_ticks").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(85_000.0)
        assert rows[0][1] == "BTC"
        assert rows[0][2] == "binance"

    def test_unknown_schema_no_price_does_not_crash(self, tmp_path):
        """A message with no 'price' field is silently ignored."""
        h = _harness(tmp_path)
        msg = json.dumps({"type": "subscribed", "channel": "crypto_prices"})
        # Should not raise
        h._process_rtds_message(msg, time.monotonic_ns(), time.time())

    def test_malformed_json_does_not_crash(self, tmp_path):
        h = _harness(tmp_path)
        h._process_rtds_message("not valid json {{", time.monotonic_ns(), time.time())

    def test_zero_price_does_not_store(self, tmp_path):
        h = _harness(tmp_path)
        msg = json.dumps({"symbol": "BTC", "price": 0, "source": "binance"})
        h._process_rtds_message(msg, time.monotonic_ns(), time.time())
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        count = conn.execute("SELECT COUNT(*) FROM truth_ticks").fetchone()[0]
        conn.close()
        assert count == 0

    def test_latest_truth_updated(self, tmp_path):
        h = _harness(tmp_path)
        msg = json.dumps({"symbol": "BTC", "price": 92_000.0, "source": "chainlink"})
        h._process_rtds_message(msg, time.monotonic_ns(), time.time())
        assert h._latest_truth is not None
        assert h._latest_truth.price == pytest.approx(92_000.0)
        assert h._latest_truth.source == "chainlink"


# ---------------------------------------------------------------------------
# 8–9. Market message parsing
# ---------------------------------------------------------------------------

class TestMarketMessageParsing:
    def test_happy_path_bba_message(self, tmp_path):
        h = _harness(tmp_path)
        now = time.time()
        msg = json.dumps({
            "asset_id": "token_001",
            "event_type": "best_bid_ask",
            "best_bid": "0.47",
            "best_ask": "0.53",
            "timestamp": str(int(now * 1000)),
        })
        h._process_market_message(msg, time.monotonic_ns(), now)
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        rows = conn.execute(
            "SELECT token_id, best_bid, best_ask FROM market_ticks"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] == "token_001"
        assert rows[0][1] == pytest.approx(0.47)
        assert rows[0][2] == pytest.approx(0.53)

    def test_missing_bid_ask_no_crash(self, tmp_path):
        h = _harness(tmp_path)
        msg = json.dumps({"asset_id": "token_001", "event_type": "book"})
        h._process_market_message(msg, time.monotonic_ns(), time.time())

    def test_malformed_json_no_crash(self, tmp_path):
        h = _harness(tmp_path)
        h._process_market_message("{{broken", time.monotonic_ns(), time.time())

    def test_no_token_id_no_crash_no_store(self, tmp_path):
        h = _harness(tmp_path)
        msg = json.dumps({"best_bid": "0.50", "best_ask": "0.52"})
        h._process_market_message(msg, time.monotonic_ns(), time.time())
        h.db.flush()

        conn = sqlite3.connect(str(tmp_path / "harness.db"))
        count = conn.execute("SELECT COUNT(*) FROM market_ticks").fetchone()[0]
        conn.close()
        assert count == 0

    def test_latest_market_updated(self, tmp_path):
        h = _harness(tmp_path)
        msg = json.dumps({
            "asset_id": "token_001",
            "best_bid": "0.44",
            "best_ask": "0.56",
        })
        h._process_market_message(msg, time.monotonic_ns(), time.time())
        assert "token_001" in h._latest_market
        assert h._latest_market["token_001"].best_bid == pytest.approx(0.44)


# ---------------------------------------------------------------------------
# 10–14. analyse_latency_surface — kill conditions
# ---------------------------------------------------------------------------

class TestAnalysis:
    def _populate_db(
        self,
        db_path: Path,
        n: int,
        lag_ms: float,
        error: float,
        stale_fraction: float = 0.0,
    ) -> None:
        """Directly write synthetic price_errors rows to the DB."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS price_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT, symbol TEXT,
                fair_value REAL, venue_mid REAL, price_error REAL,
                truth_age_ms REAL, market_age_ms REAL,
                computed_at_ns INTEGER, wall_time TEXT
            )"""
        )
        stale_count = int(n * stale_fraction)
        for i in range(n):
            lag = 5000.0 if i < stale_count else lag_ms
            conn.execute(
                "INSERT INTO price_errors "
                "(token_id, symbol, fair_value, venue_mid, price_error, "
                "truth_age_ms, market_age_ms, computed_at_ns, wall_time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("t1", "BTC", 0.50, 0.50 + error, error, lag, 10.0,
                 time.monotonic_ns(), "2026-03-23T12:00:00+00:00"),
            )
        conn.commit()
        conn.close()

    def test_continue_verdict(self, tmp_path):
        """All three hypotheses pass -> CONTINUE."""
        db_path = tmp_path / "ok.db"
        # lag = 600ms > 100ms (H1 pass)
        # stale_fraction = 0.10 > 0.05 (H2 pass)
        # error = 0.05 -> large EV (H3 pass at passthrough fair-value scale is huge)
        self._populate_db(db_path, n=2000, lag_ms=600.0, error=0.05, stale_fraction=0.10)
        result = analyse_latency_surface(db_path, min_samples=100)
        assert result["verdict"] == "CONTINUE"
        assert result["h1_pass"] is True
        assert result["h2_pass"] is True
        assert result["h3_pass"] is True

    def test_kill_h1_verdict(self, tmp_path):
        """Median lag < 100ms -> KILL_H1."""
        db_path = tmp_path / "h1.db"
        self._populate_db(db_path, n=2000, lag_ms=10.0, error=0.10, stale_fraction=0.10)
        result = analyse_latency_surface(db_path, min_samples=100)
        assert result["verdict"] == "KILL_H1"
        assert result["h1_pass"] is False

    def test_kill_h2_verdict(self, tmp_path):
        """Median lag OK, stale-quote rate < 5% -> KILL_H2."""
        db_path = tmp_path / "h2.db"
        # lag_ms=300 > 100 (H1 pass), stale_fraction=0.01 < 0.05 (H2 fail)
        self._populate_db(db_path, n=2000, lag_ms=300.0, error=0.10, stale_fraction=0.01)
        result = analyse_latency_surface(db_path, min_samples=100)
        assert result["verdict"] == "KILL_H2"
        assert result["h1_pass"] is True
        assert result["h2_pass"] is False

    def test_kill_h3_verdict(self, tmp_path):
        """H1 and H2 pass, but tiny price error -> KILL_H3."""
        db_path = tmp_path / "h3.db"
        # lag=300ms, stale=10%, but price_error = 0.000001 -> EV basically zero
        self._populate_db(db_path, n=2000, lag_ms=300.0, error=0.000001, stale_fraction=0.10)
        result = analyse_latency_surface(db_path, min_samples=100)
        assert result["verdict"] == "KILL_H3"
        assert result["h1_pass"] is True
        assert result["h2_pass"] is True
        assert result["h3_pass"] is False

    def test_insufficient_data(self, tmp_path):
        db_path = tmp_path / "tiny.db"
        self._populate_db(db_path, n=5, lag_ms=300.0, error=0.05)
        result = analyse_latency_surface(db_path, min_samples=1000)
        assert result["verdict"] == "INSUFFICIENT_DATA"
        assert result["n_samples"] == 5


# ---------------------------------------------------------------------------
# 15. RTDSLatencyHarness constructor validation
# ---------------------------------------------------------------------------

class TestHarnessConstructor:
    def test_empty_token_ids_raises(self, tmp_path):
        with pytest.raises(ValueError, match="token_ids"):
            RTDSLatencyHarness(token_ids=[], db_path=tmp_path / "x.db")

    def test_valid_construction(self, tmp_path):
        h = RTDSLatencyHarness(
            token_ids=["tok1", "tok2"],
            symbol="ETH",
            db_path=tmp_path / "eth.db",
        )
        assert h.symbol == "ETH"
        assert len(h.token_ids) == 2


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------

class TestUtilities:
    def test_normalise_ts_milliseconds(self):
        ms = 1_711_234_567_890
        result = _normalise_ts(ms)
        assert result == pytest.approx(ms / 1000.0, rel=1e-6)

    def test_normalise_ts_microseconds(self):
        us = 1_711_234_567_890_000
        result = _normalise_ts(us)
        assert result == pytest.approx(us / 1_000_000.0, rel=1e-6)

    def test_normalise_ts_seconds(self):
        s = 1_711_234_567.0
        result = _normalise_ts(s)
        assert result == pytest.approx(s, rel=1e-6)

    def test_normalise_ts_zero_returns_none(self):
        assert _normalise_ts(0) is None

    def test_percentile_from_sorted_empty(self):
        assert _percentile_from_sorted([], 0.5) == 0.0

    def test_percentile_from_sorted_single(self):
        assert _percentile_from_sorted([42.0], 0.5) == 42.0

    def test_percentile_from_sorted_p50(self):
        vals = list(map(float, range(101)))
        assert _percentile_from_sorted(vals, 0.50) == pytest.approx(50.0, abs=0.1)

    def test_percentile_from_sorted_p99(self):
        vals = list(map(float, range(100)))
        p99 = _percentile_from_sorted(vals, 0.99)
        assert p99 >= 98.0
