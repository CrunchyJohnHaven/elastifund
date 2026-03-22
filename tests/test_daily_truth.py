"""Tests for bot.daily_truth — authoritative daily P&L tracker.

Covers: fill recording, ET-day bucketing, rolling 24h, source priority,
staleness, promotion/deploy blocking, scoreboard formatting,
multi-strategy breakdown, wallet reconciliation, edge cases.
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Handle zoneinfo import for tests
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from bot.daily_truth import (
    ET,
    SOURCE_COMPAT_ALIAS,
    SOURCE_FILL_LEDGER,
    SOURCE_LABELS,
    SOURCE_WALLET_RECON,
    UTC,
    DailyPnL,
    DailyTruthTracker,
    _et_date_for_utc,
)


@pytest.fixture
def tracker(tmp_path: Path) -> DailyTruthTracker:
    """Create a fresh tracker with a temp DB."""
    db = tmp_path / "test_daily_truth.sqlite"
    t = DailyTruthTracker(db_path=db)
    yield t
    t.close()


@pytest.fixture
def now_utc() -> datetime:
    return datetime(2026, 3, 22, 15, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------
# DailyPnL dataclass
# ---------------------------------------------------------------

class TestDailyPnLDataclass:
    def test_defaults(self):
        p = DailyPnL(date_et="2026-03-22", date_utc="2026-03-22")
        assert p.fills == 0
        assert p.wins == 0
        assert p.losses == 0
        assert p.gross_pnl == 0.0
        assert p.net_pnl == 0.0
        assert p.max_intraday_drawdown == 0.0
        assert p.strategies == {}
        assert p.source_priority == SOURCE_FILL_LEDGER
        assert p.is_authoritative is True

    def test_source_label(self):
        p = DailyPnL(date_et="2026-03-22", date_utc="2026-03-22", source_priority=SOURCE_WALLET_RECON)
        assert p.source_label == "wallet_recon"

    def test_win_rate_no_fills(self):
        p = DailyPnL(date_et="2026-03-22", date_utc="2026-03-22")
        assert p.win_rate == 0.0

    def test_win_rate_with_fills(self):
        p = DailyPnL(date_et="2026-03-22", date_utc="2026-03-22", wins=7, losses=3)
        assert abs(p.win_rate - 0.7) < 1e-9


# ---------------------------------------------------------------
# ET-day bucketing
# ---------------------------------------------------------------

class TestETDayBucketing:
    def test_utc_afternoon_same_et_day(self):
        """15:00 UTC on Mar 22 is 11:00 ET — still Mar 22."""
        ts = datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)
        assert _et_date_for_utc(ts) == "2026-03-22"

    def test_utc_early_morning_previous_et_day(self):
        """03:00 UTC on Mar 22 is 23:00 ET on Mar 21."""
        ts = datetime(2026, 3, 22, 3, 0, 0, tzinfo=timezone.utc)
        assert _et_date_for_utc(ts) == "2026-03-21"

    def test_utc_exactly_midnight_et(self):
        """05:00 UTC (during EDT) = 00:00 ET on Mar 22."""
        # EDT offset is UTC-4, so 04:00 UTC = 00:00 ET
        ts = datetime(2026, 3, 22, 4, 0, 0, tzinfo=timezone.utc)
        assert _et_date_for_utc(ts) == "2026-03-22"

    def test_naive_timestamp_treated_as_utc(self):
        ts = datetime(2026, 3, 22, 15, 0, 0)
        assert _et_date_for_utc(ts) == "2026-03-22"

    def test_dst_transition_spring_forward(self):
        """March 8 2026 is spring-forward. 06:59 UTC = 01:59 EST = Mar 8.
        07:00 UTC = 03:00 EDT = Mar 8."""
        before = datetime(2026, 3, 8, 6, 59, 0, tzinfo=timezone.utc)
        after = datetime(2026, 3, 8, 7, 0, 0, tzinfo=timezone.utc)
        assert _et_date_for_utc(before) == "2026-03-08"
        assert _et_date_for_utc(after) == "2026-03-08"

    def test_dst_transition_fall_back(self):
        """Nov 1 2026 is fall-back. 05:59 UTC = 01:59 EDT = Nov 1.
        06:00 UTC = 01:00 EST = Nov 1."""
        before = datetime(2026, 11, 1, 5, 59, 0, tzinfo=timezone.utc)
        after = datetime(2026, 11, 1, 6, 0, 0, tzinfo=timezone.utc)
        assert _et_date_for_utc(before) == "2026-11-01"
        assert _et_date_for_utc(after) == "2026-11-01"


# ---------------------------------------------------------------
# Fill recording
# ---------------------------------------------------------------

class TestFillRecording:
    def test_record_single_fill(self, tracker: DailyTruthTracker):
        ts = datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)
        tracker.record_fill("btc5", 2.50, fee=0.10, timestamp=ts)

        conn = tracker._get_conn()
        rows = conn.execute("SELECT * FROM daily_truth_fills").fetchall()
        assert len(rows) == 1
        assert rows[0]["strategy"] == "btc5"
        assert rows[0]["pnl"] == 2.50
        assert rows[0]["fee"] == 0.10
        assert rows[0]["date_et"] == "2026-03-22"

    def test_record_multiple_fills(self, tracker: DailyTruthTracker):
        ts = datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            tracker.record_fill("btc5", 1.0 + i * 0.5, timestamp=ts + timedelta(minutes=i))

        conn = tracker._get_conn()
        count = conn.execute("SELECT COUNT(*) as cnt FROM daily_truth_fills").fetchone()["cnt"]
        assert count == 5

    def test_fill_default_timestamp(self, tracker: DailyTruthTracker):
        tracker.record_fill("btc5", 1.0)
        conn = tracker._get_conn()
        rows = conn.execute("SELECT * FROM daily_truth_fills").fetchall()
        assert len(rows) == 1
        assert rows[0]["timestamp_utc"] is not None

    def test_fill_naive_timestamp(self, tracker: DailyTruthTracker):
        ts = datetime(2026, 3, 22, 15, 0, 0)  # naive
        tracker.record_fill("btc5", 1.0, timestamp=ts)
        conn = tracker._get_conn()
        rows = conn.execute("SELECT * FROM daily_truth_fills").fetchall()
        assert rows[0]["date_et"] == "2026-03-22"

    def test_fill_with_source_priority(self, tracker: DailyTruthTracker):
        ts = datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)
        tracker.record_fill("btc5", 1.0, timestamp=ts, source_priority=SOURCE_WALLET_RECON)
        conn = tracker._get_conn()
        rows = conn.execute("SELECT * FROM daily_truth_fills").fetchall()
        assert rows[0]["source_priority"] == SOURCE_WALLET_RECON

    def test_et_day_bucketing_across_midnight(self, tracker: DailyTruthTracker):
        """Fill at 03:00 UTC = 23:00 ET previous day."""
        ts_before = datetime(2026, 3, 22, 3, 0, 0, tzinfo=timezone.utc)
        ts_after = datetime(2026, 3, 22, 5, 0, 0, tzinfo=timezone.utc)
        tracker.record_fill("btc5", 1.0, timestamp=ts_before)
        tracker.record_fill("btc5", 2.0, timestamp=ts_after)

        conn = tracker._get_conn()
        rows = conn.execute("SELECT * FROM daily_truth_fills ORDER BY timestamp_utc").fetchall()
        assert rows[0]["date_et"] == "2026-03-21"
        assert rows[1]["date_et"] == "2026-03-22"


# ---------------------------------------------------------------
# get_today_pnl
# ---------------------------------------------------------------

class TestGetTodayPnl:
    def test_no_fills_today(self, tracker: DailyTruthTracker):
        pnl = tracker.get_today_pnl()
        assert pnl.fills == 0
        assert pnl.is_authoritative is False
        assert pnl.staleness_seconds == float("inf")

    def test_with_fills(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 2.0, fee=0.10, timestamp=now)
        tracker.record_fill("btc5", -1.0, fee=0.05, timestamp=now + timedelta(seconds=30))

        pnl = tracker.get_today_pnl()
        assert pnl.fills == 2
        assert pnl.wins == 1
        assert pnl.losses == 1
        assert pnl.gross_pnl == 1.0  # 2.0 + (-1.0)
        assert pnl.net_pnl == 0.85  # 1.0 - 0.15 fees
        assert pnl.is_authoritative is True

    def test_strategy_breakdown(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 3.0, fee=0.10, timestamp=now)
        tracker.record_fill("eth5", -1.0, fee=0.05, timestamp=now)

        pnl = tracker.get_today_pnl()
        assert "btc5" in pnl.strategies
        assert "eth5" in pnl.strategies
        assert pnl.strategies["btc5"] == 2.90  # 3.0 - 0.10
        assert pnl.strategies["eth5"] == -1.05  # -1.0 - 0.05

    def test_max_intraday_drawdown(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        # Sequence: +5, -3, -2, +4 → peak=5, lowest from peak = 5-0=5 at fill 3
        tracker.record_fill("btc5", 5.0, timestamp=now)
        tracker.record_fill("btc5", -3.0, timestamp=now + timedelta(seconds=1))
        tracker.record_fill("btc5", -2.0, timestamp=now + timedelta(seconds=2))
        tracker.record_fill("btc5", 4.0, timestamp=now + timedelta(seconds=3))

        pnl = tracker.get_today_pnl()
        assert pnl.max_intraday_drawdown == 5.0  # peak 5 → trough 0


# ---------------------------------------------------------------
# get_rolling_24h_pnl
# ---------------------------------------------------------------

class TestRolling24h:
    def test_rolling_excludes_old(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=25)
        tracker.record_fill("btc5", 10.0, timestamp=old)
        tracker.record_fill("btc5", 2.0, timestamp=now)

        pnl = tracker.get_rolling_24h_pnl()
        assert pnl.fills == 1
        assert pnl.gross_pnl == 2.0

    def test_rolling_includes_recent(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 1.0, timestamp=now - timedelta(hours=12))
        tracker.record_fill("btc5", 2.0, timestamp=now - timedelta(hours=1))

        pnl = tracker.get_rolling_24h_pnl()
        assert pnl.fills == 2
        assert pnl.gross_pnl == 3.0


# ---------------------------------------------------------------
# get_pnl_history
# ---------------------------------------------------------------

class TestPnlHistory:
    def test_history_returns_correct_days(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        # Insert fills over 3 days
        for day_offset in range(3):
            ts = now - timedelta(days=day_offset)
            tracker.record_fill("btc5", 1.0 + day_offset, timestamp=ts)

        history = tracker.get_pnl_history(days=3)
        assert len(history) >= 2  # at least 2 unique ET days
        assert all(isinstance(p, DailyPnL) for p in history)

    def test_history_empty_db(self, tracker: DailyTruthTracker):
        history = tracker.get_pnl_history(days=7)
        assert len(history) >= 1
        assert all(p.fills == 0 for p in history)


# ---------------------------------------------------------------
# Source priority
# ---------------------------------------------------------------

class TestSourcePriority:
    def test_fill_ledger_beats_wallet_recon(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 2.0, timestamp=now, source_priority=SOURCE_FILL_LEDGER)
        tracker.record_fill("btc5", 1.0, timestamp=now, source_priority=SOURCE_WALLET_RECON)

        pnl = tracker.get_today_pnl()
        assert pnl.source_priority == SOURCE_FILL_LEDGER  # 1 beats 2

    def test_all_wallet_recon_fills(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 2.0, timestamp=now, source_priority=SOURCE_WALLET_RECON)

        pnl = tracker.get_today_pnl()
        assert pnl.source_priority == SOURCE_WALLET_RECON

    def test_compat_alias_lowest_priority(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 1.0, timestamp=now, source_priority=SOURCE_COMPAT_ALIAS)

        pnl = tracker.get_today_pnl()
        assert pnl.source_priority == SOURCE_COMPAT_ALIAS


# ---------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------

class TestStaleness:
    def test_stale_no_fills(self, tracker: DailyTruthTracker):
        assert tracker.is_stale(max_age_seconds=3600) is True

    def test_stale_old_fills(self, tracker: DailyTruthTracker):
        old_ts = datetime.now(timezone.utc) - timedelta(hours=2)
        tracker.record_fill("btc5", 1.0, timestamp=old_ts)
        assert tracker.is_stale(max_age_seconds=3600) is True

    def test_not_stale_recent_fill(self, tracker: DailyTruthTracker):
        tracker.record_fill("btc5", 1.0, timestamp=datetime.now(timezone.utc))
        assert tracker.is_stale(max_age_seconds=3600) is False

    def test_staleness_seconds_in_pnl(self, tracker: DailyTruthTracker):
        ts = datetime.now(timezone.utc) - timedelta(minutes=30)
        tracker.record_fill("btc5", 1.0, timestamp=ts)
        pnl = tracker.get_today_pnl()
        # Should be ~1800 seconds
        assert 1700 < pnl.staleness_seconds < 2000


# ---------------------------------------------------------------
# Promotion blocking
# ---------------------------------------------------------------

class TestPromotionBlocking:
    def test_blocks_when_no_fills(self, tracker: DailyTruthTracker):
        assert tracker.blocks_promotion() is True

    def test_blocks_when_not_authoritative(self, tracker: DailyTruthTracker):
        # No fills → not authoritative → blocks
        assert tracker.blocks_promotion() is True

    def test_does_not_block_with_fills(self, tracker: DailyTruthTracker):
        tracker.record_fill("btc5", 1.0, timestamp=datetime.now(timezone.utc))
        assert tracker.blocks_promotion() is False


# ---------------------------------------------------------------
# Deploy blocking
# ---------------------------------------------------------------

class TestDeployBlocking:
    def test_does_not_block_empty_db(self, tracker: DailyTruthTracker):
        """Empty DB = no historical fills = no evidence of pipeline breakage."""
        assert tracker.blocks_deploy() is False

    def test_blocks_when_historical_fills_but_none_today(self, tracker: DailyTruthTracker):
        """Historical fills exist but none today — pipeline may be broken."""
        old_ts = datetime.now(timezone.utc) - timedelta(days=2)
        tracker.record_fill("btc5", 1.0, timestamp=old_ts)

        assert tracker.blocks_deploy() is True

    def test_does_not_block_with_today_fills(self, tracker: DailyTruthTracker):
        tracker.record_fill("btc5", 1.0, timestamp=datetime.now(timezone.utc))
        assert tracker.blocks_deploy() is False


# ---------------------------------------------------------------
# Scoreboard formatting
# ---------------------------------------------------------------

class TestScoreboard:
    def test_no_fills_scoreboard(self, tracker: DailyTruthTracker):
        sb = tracker.format_scoreboard()
        assert "NO FILLS" in sb
        assert "stale" in sb

    def test_with_fills_scoreboard(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 5.0, fee=0.10, timestamp=now)
        tracker.record_fill("btc5", 3.0, fee=0.05, timestamp=now + timedelta(seconds=1))
        tracker.record_fill("btc5", -1.0, fee=0.02, timestamp=now + timedelta(seconds=2))

        sb = tracker.format_scoreboard()
        assert "ET " in sb
        assert "2W/1L" in sb
        assert "PF" in sb
        assert "DD" in sb
        assert "$" in sb

    def test_scoreboard_positive_sign(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 10.0, timestamp=now)
        sb = tracker.format_scoreboard()
        assert "+$" in sb

    def test_scoreboard_negative_pnl(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", -5.0, timestamp=now)
        sb = tracker.format_scoreboard()
        assert "-$" in sb


# ---------------------------------------------------------------
# emit_metrics
# ---------------------------------------------------------------

class TestEmitMetrics:
    def test_metrics_keys(self, tracker: DailyTruthTracker):
        m = tracker.emit_metrics()
        expected_keys = {
            "date_et", "fills", "wins", "losses", "gross_pnl", "net_pnl",
            "max_intraday_drawdown", "profit_factor", "win_rate", "strategies",
            "source_priority", "source_label", "staleness_seconds",
            "is_authoritative", "is_stale", "blocks_promotion",
            "blocks_deploy", "scoreboard",
        }
        assert set(m.keys()) == expected_keys

    def test_metrics_with_fills(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 2.0, fee=0.10, timestamp=now)
        m = tracker.emit_metrics()
        assert m["fills"] == 1
        assert m["wins"] == 1
        assert m["net_pnl"] == 1.90
        assert m["is_authoritative"] is True
        assert m["blocks_promotion"] is False


# ---------------------------------------------------------------
# Wallet reconciliation
# ---------------------------------------------------------------

class TestWalletReconciliation:
    def test_recon_no_tape(self, tracker: DailyTruthTracker):
        result = tracker.reconcile_from_wallet(
            wallet_balance=390.0,
            deposit_total=247.51,
            timestamp=datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc),
        )
        assert result["wallet_pnl"] == pytest.approx(142.49, abs=0.01)
        assert result["tape_pnl"] is None
        assert result["drift"] is None

    def test_recon_with_tape(self, tracker: DailyTruthTracker):
        now = datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)
        tracker.record_fill("btc5", 5.0, fee=0.10, timestamp=now)
        result = tracker.reconcile_from_wallet(
            wallet_balance=252.41,
            deposit_total=247.51,
            timestamp=now,
        )
        assert result["tape_pnl"] == pytest.approx(4.90, abs=0.01)
        assert result["drift"] is not None

    def test_recon_drift_warning(self, tracker: DailyTruthTracker):
        now = datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc)
        tracker.record_fill("btc5", 1.0, timestamp=now)
        # Wallet says PnL is 100.0, tape says 1.0 → drift of 99.0
        result = tracker.reconcile_from_wallet(
            wallet_balance=347.51,
            deposit_total=247.51,
            timestamp=now,
        )
        assert abs(result["drift"]) > 1.0

    def test_recon_stored_in_db(self, tracker: DailyTruthTracker):
        tracker.reconcile_from_wallet(
            wallet_balance=300.0,
            deposit_total=247.51,
            timestamp=datetime(2026, 3, 22, 15, 0, 0, tzinfo=timezone.utc),
        )
        conn = tracker._get_conn()
        rows = conn.execute("SELECT * FROM daily_truth_recon").fetchall()
        assert len(rows) == 1
        assert rows[0]["wallet_balance"] == 300.0


# ---------------------------------------------------------------
# Multi-strategy breakdown
# ---------------------------------------------------------------

class TestMultiStrategy:
    def test_multiple_strategies(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 3.0, fee=0.10, timestamp=now)
        tracker.record_fill("btc5", -1.0, fee=0.05, timestamp=now)
        tracker.record_fill("eth5", 2.0, fee=0.08, timestamp=now)
        tracker.record_fill("main_jj", 5.0, fee=0.20, timestamp=now)

        pnl = tracker.get_today_pnl()
        assert len(pnl.strategies) == 3
        assert pnl.strategies["btc5"] == pytest.approx(1.85, abs=0.01)
        assert pnl.strategies["eth5"] == pytest.approx(1.92, abs=0.01)
        assert pnl.strategies["main_jj"] == pytest.approx(4.80, abs=0.01)

    def test_strategy_isolation(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", -10.0, timestamp=now)
        tracker.record_fill("eth5", 20.0, timestamp=now)

        pnl = tracker.get_today_pnl()
        assert pnl.strategies["btc5"] == -10.0
        assert pnl.strategies["eth5"] == 20.0
        assert pnl.net_pnl == 10.0


# ---------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------

class TestEdgeCases:
    def test_zero_pnl_fill(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 0.0, timestamp=now)
        pnl = tracker.get_today_pnl()
        assert pnl.fills == 1
        assert pnl.losses == 1  # 0.0 counts as loss
        assert pnl.net_pnl == 0.0

    def test_large_number_of_fills(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        for i in range(200):
            tracker.record_fill("btc5", 0.50, timestamp=now + timedelta(seconds=i))
        pnl = tracker.get_today_pnl()
        assert pnl.fills == 200
        assert pnl.gross_pnl == pytest.approx(100.0, abs=0.01)

    def test_db_persistence(self, tmp_path: Path):
        db = tmp_path / "persist_test.sqlite"
        t1 = DailyTruthTracker(db_path=db)
        t1.record_fill("btc5", 5.0, timestamp=datetime.now(timezone.utc))
        t1.close()

        t2 = DailyTruthTracker(db_path=db)
        pnl = t2.get_today_pnl()
        assert pnl.fills == 1
        assert pnl.gross_pnl == 5.0
        t2.close()

    def test_midnight_et_boundary(self, tracker: DailyTruthTracker):
        """Fills just before and after midnight ET go to different days."""
        # 03:59 UTC = 23:59 ET (Mar 21)
        before = datetime(2026, 3, 22, 3, 59, 0, tzinfo=timezone.utc)
        # 04:01 UTC = 00:01 ET (Mar 22)
        after = datetime(2026, 3, 22, 4, 1, 0, tzinfo=timezone.utc)

        tracker.record_fill("btc5", 1.0, timestamp=before)
        tracker.record_fill("btc5", 2.0, timestamp=after)

        conn = tracker._get_conn()
        rows = conn.execute(
            "SELECT date_et, pnl FROM daily_truth_fills ORDER BY timestamp_utc"
        ).fetchall()
        assert rows[0]["date_et"] == "2026-03-21"
        assert rows[1]["date_et"] == "2026-03-22"

    def test_concurrent_db_access(self, tmp_path: Path):
        """Two tracker instances on the same DB don't corrupt data."""
        db = tmp_path / "concurrent_test.sqlite"
        t1 = DailyTruthTracker(db_path=db)
        t2 = DailyTruthTracker(db_path=db)

        now = datetime.now(timezone.utc)
        t1.record_fill("btc5", 1.0, timestamp=now)
        t2.record_fill("eth5", 2.0, timestamp=now)

        pnl1 = t1.get_today_pnl()
        pnl2 = t2.get_today_pnl()

        assert pnl1.fills == 2
        assert pnl2.fills == 2
        t1.close()
        t2.close()

    def test_negative_fee(self, tracker: DailyTruthTracker):
        """Maker rebate = negative fee."""
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 2.0, fee=-0.05, timestamp=now)
        pnl = tracker.get_today_pnl()
        assert pnl.net_pnl == 2.05  # 2.0 - (-0.05) = 2.05

    def test_db_directory_auto_created(self, tmp_path: Path):
        deep = tmp_path / "a" / "b" / "c" / "test.sqlite"
        t = DailyTruthTracker(db_path=deep)
        t.record_fill("btc5", 1.0)
        t.close()
        assert deep.exists()

    def test_close_and_reopen(self, tmp_path: Path):
        db = tmp_path / "reopen.sqlite"
        t = DailyTruthTracker(db_path=db)
        t.record_fill("btc5", 1.0, timestamp=datetime.now(timezone.utc))
        t.close()
        # After close, should be able to reopen
        t2 = DailyTruthTracker(db_path=db)
        assert t2.get_today_pnl().fills == 1
        t2.close()

    def test_profit_factor_all_wins(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 5.0, timestamp=now)
        tracker.record_fill("btc5", 3.0, timestamp=now)
        pnl = tracker.get_today_pnl()
        pf = getattr(pnl, "_real_pf", None)
        assert pf == float("inf")

    def test_profit_factor_mixed(self, tracker: DailyTruthTracker):
        now = datetime.now(timezone.utc)
        tracker.record_fill("btc5", 10.0, timestamp=now)
        tracker.record_fill("btc5", -5.0, timestamp=now + timedelta(seconds=1))
        pnl = tracker.get_today_pnl()
        pf = getattr(pnl, "_real_pf", None)
        assert pf is not None
        assert pf == pytest.approx(2.0, abs=0.01)
