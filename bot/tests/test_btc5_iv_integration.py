"""Tests for Deribit IV feed integration into BTC5 decision logging.

Verifies:
- IV snapshot is correctly captured as a dict
- Stale/disconnected snapshots produce empty dict
- None iv_feed produces empty dict
- IV columns are added to DB schema migration
- IV data flows through upsert_window correctly
"""

import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import TradeDB


# ---------------------------------------------------------------------------
# Mock IVSnapshot matching the real deribit_iv_feed.IVSnapshot API
# ---------------------------------------------------------------------------

@dataclass
class MockIVSnapshot:
    dvol: float = 55.0
    atm_iv_call: float = 52.0
    atm_iv_put: float = 54.0
    put_call_skew: float = 2.0
    rr_25d: float = 1.5
    bf_25d: float = 0.8
    underlying_price: float = 87500.0
    connected: bool = True
    authenticated: bool = False
    last_update_ts: float = 0.0
    error: str = None

    def age_seconds(self) -> float:
        if self.last_update_ts == 0.0:
            return float("inf")
        return time.time() - self.last_update_ts

    def is_stale(self, max_age_s: float = 30.0) -> bool:
        return self.age_seconds() > max_age_s


class MockDeribitIVFeed:
    """Mock DeribitIVFeed for testing."""

    def __init__(self, snapshot: MockIVSnapshot = None):
        self._snap = snapshot or MockIVSnapshot(last_update_ts=time.time())

    def snapshot(self) -> MockIVSnapshot:
        return self._snap

    async def run_forever(self):
        pass

    def stop(self):
        pass


# ---------------------------------------------------------------------------
# Tests: _snapshot_iv_data behavior
# ---------------------------------------------------------------------------

class TestSnapshotIVData:
    """Test the _snapshot_iv_data method behavior by simulating its logic."""

    def _snapshot_iv_data(self, iv_feed) -> dict:
        """Replicate the logic from BTC5MinMakerBot._snapshot_iv_data."""
        if iv_feed is None:
            return {}
        try:
            snap = iv_feed.snapshot()
            if not snap.connected or snap.is_stale(60.0):
                return {}
            return {
                "deribit_dvol": snap.dvol,
                "deribit_atm_iv_call": snap.atm_iv_call,
                "deribit_atm_iv_put": snap.atm_iv_put,
                "deribit_put_call_skew": snap.put_call_skew,
                "deribit_rr_25d": snap.rr_25d,
                "deribit_bf_25d": snap.bf_25d,
                "deribit_underlying": snap.underlying_price,
                "deribit_age_s": round(snap.age_seconds(), 1),
            }
        except Exception:
            return {}

    def test_fresh_connected_snapshot(self):
        feed = MockDeribitIVFeed(MockIVSnapshot(
            dvol=55.0,
            atm_iv_call=52.0,
            atm_iv_put=54.0,
            put_call_skew=2.0,
            rr_25d=1.5,
            bf_25d=0.8,
            underlying_price=87500.0,
            connected=True,
            last_update_ts=time.time(),
        ))
        result = self._snapshot_iv_data(feed)
        assert result["deribit_dvol"] == 55.0
        assert result["deribit_atm_iv_call"] == 52.0
        assert result["deribit_atm_iv_put"] == 54.0
        assert result["deribit_put_call_skew"] == 2.0
        assert result["deribit_rr_25d"] == 1.5
        assert result["deribit_bf_25d"] == 0.8
        assert result["deribit_underlying"] == 87500.0
        assert "deribit_age_s" in result

    def test_disconnected_returns_empty(self):
        feed = MockDeribitIVFeed(MockIVSnapshot(
            connected=False,
            last_update_ts=time.time(),
        ))
        result = self._snapshot_iv_data(feed)
        assert result == {}

    def test_stale_returns_empty(self):
        feed = MockDeribitIVFeed(MockIVSnapshot(
            connected=True,
            last_update_ts=time.time() - 120,  # 2 minutes old
        ))
        result = self._snapshot_iv_data(feed)
        assert result == {}

    def test_none_feed_returns_empty(self):
        result = self._snapshot_iv_data(None)
        assert result == {}

    def test_exception_returns_empty(self):
        feed = MagicMock()
        feed.snapshot.side_effect = RuntimeError("connection lost")
        result = self._snapshot_iv_data(feed)
        assert result == {}

    def test_none_values_in_snapshot(self):
        feed = MockDeribitIVFeed(MockIVSnapshot(
            dvol=None,
            atm_iv_call=None,
            atm_iv_put=None,
            put_call_skew=None,
            rr_25d=None,
            bf_25d=None,
            underlying_price=None,
            connected=True,
            last_update_ts=time.time(),
        ))
        result = self._snapshot_iv_data(feed)
        assert result["deribit_dvol"] is None
        assert result["deribit_underlying"] is None
        # All keys still present even when values are None
        assert len(result) == 8


# ---------------------------------------------------------------------------
# Tests: DB schema migration adds IV columns
# ---------------------------------------------------------------------------

class TestDBSchemaIVColumns:
    def test_iv_columns_exist_after_init(self, tmp_path):
        db = TradeDB(tmp_path / "test.db")
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()
        }
        conn.close()

        iv_columns = {
            "deribit_dvol",
            "deribit_atm_iv_call",
            "deribit_atm_iv_put",
            "deribit_put_call_skew",
            "deribit_rr_25d",
            "deribit_bf_25d",
            "deribit_underlying",
            "deribit_age_s",
        }
        for col in iv_columns:
            assert col in columns, f"Missing IV column: {col}"

    def test_idempotent_migration(self, tmp_path):
        """Running _init_db twice should not fail."""
        db = TradeDB(tmp_path / "test.db")
        db2 = TradeDB(tmp_path / "test.db")  # second init on same file
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()
        }
        conn.close()
        assert "deribit_dvol" in columns


# ---------------------------------------------------------------------------
# Tests: IV data flows through upsert_window
# ---------------------------------------------------------------------------

class TestUpsertWithIVData:
    def test_upsert_stores_iv_data(self, tmp_path):
        db = TradeDB(tmp_path / "test.db")

        now = int(time.time())
        row = {
            "window_start_ts": now,
            "window_end_ts": now + 300,
            "slug": "BTC-5MIN-UP-2026-03-23-00-00",
            "decision_ts": now + 290,
            "order_status": "placed",
            "deribit_dvol": 55.0,
            "deribit_atm_iv_call": 52.0,
            "deribit_atm_iv_put": 54.0,
            "deribit_put_call_skew": 2.0,
            "deribit_rr_25d": 1.5,
            "deribit_bf_25d": 0.8,
            "deribit_underlying": 87500.0,
            "deribit_age_s": 3.5,
        }
        db.upsert_window(row)

        # Read back
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            "SELECT * FROM window_trades WHERE window_start_ts = ?",
            (now,),
        ).fetchone()
        conn.close()

        assert result is not None
        assert result["deribit_dvol"] == 55.0
        assert result["deribit_atm_iv_call"] == 52.0
        assert result["deribit_put_call_skew"] == 2.0
        assert result["deribit_rr_25d"] == 1.5
        assert result["deribit_bf_25d"] == 0.8
        assert result["deribit_underlying"] == 87500.0
        assert result["deribit_age_s"] == 3.5

    def test_upsert_with_null_iv_data(self, tmp_path):
        db = TradeDB(tmp_path / "test.db")

        now = int(time.time())
        row = {
            "window_start_ts": now,
            "window_end_ts": now + 300,
            "slug": "BTC-5MIN-DOWN-2026-03-23-00-00",
            "decision_ts": now + 290,
            "order_status": "skip_delta_too_large",
            # No IV data at all
        }
        db.upsert_window(row)

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            "SELECT * FROM window_trades WHERE window_start_ts = ?",
            (now,),
        ).fetchone()
        conn.close()

        assert result is not None
        assert result["deribit_dvol"] is None
        assert result["deribit_underlying"] is None

    def test_upsert_updates_iv_on_conflict(self, tmp_path):
        db = TradeDB(tmp_path / "test.db")

        now = int(time.time())
        # First insert with no IV
        row1 = {
            "window_start_ts": now,
            "window_end_ts": now + 300,
            "slug": "test-slug",
            "decision_ts": now + 290,
            "order_status": "skip",
        }
        db.upsert_window(row1)

        # Second upsert with IV data
        row2 = {
            "window_start_ts": now,
            "window_end_ts": now + 300,
            "slug": "test-slug",
            "decision_ts": now + 290,
            "order_status": "placed",
            "deribit_dvol": 60.0,
            "deribit_underlying": 88000.0,
        }
        db.upsert_window(row2)

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            "SELECT * FROM window_trades WHERE window_start_ts = ?",
            (now,),
        ).fetchone()
        conn.close()

        assert result["deribit_dvol"] == 60.0
        assert result["deribit_underlying"] == 88000.0


# ---------------------------------------------------------------------------
# Tests: MockDeribitIVFeed behavior
# ---------------------------------------------------------------------------

class TestMockFeed:
    def test_mock_feed_returns_snapshot(self):
        feed = MockDeribitIVFeed()
        snap = feed.snapshot()
        assert snap.connected
        assert snap.dvol == 55.0

    def test_mock_feed_stop(self):
        feed = MockDeribitIVFeed()
        feed.stop()  # should not raise
