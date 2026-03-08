"""Tests for the weekly kill battery runner script.

Verifies:
- Strategy stats loading from signal_shadow table
- Kill battery verdict generation
- Report generation in FAST_TRADE_EDGE_ANALYSIS.md format
"""

import sqlite3
import time
from pathlib import Path

import pytest

from scripts.run_kill_battery import (
    StrategyStats,
    _format_strategy_name,
    generate_report,
    load_strategy_stats,
    run_battery_on_strategy,
)


@pytest.fixture
def db_with_signals(tmp_path):
    """Create a test DB with signal_shadow data."""
    db_path = tmp_path / "test_edge.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE signal_shadow (
            track_id TEXT PRIMARY KEY,
            signal_group TEXT NOT NULL,
            signal_key TEXT NOT NULL,
            signal_label TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            timestamp_ts INTEGER NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            confidence REAL NOT NULL,
            edge_estimate REAL NOT NULL,
            metadata_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            resolved_outcome TEXT,
            win INTEGER,
            pnl_maker REAL,
            pnl_taker REAL,
            created_at_ts INTEGER NOT NULL,
            updated_at_ts INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_shadow_group_key ON signal_shadow(signal_group, signal_key)")

    now = int(time.time())

    # Strategy A: 5 signals, 3 resolved (2 wins, 1 loss)
    for i in range(5):
        status = "resolved" if i < 3 else "open"
        win = 1 if (i < 2) else 0
        pnl_maker = 0.05 if (i < 2) else -0.03
        conn.execute(
            """INSERT INTO signal_shadow
            (track_id, signal_group, signal_key, signal_label, condition_id,
             timestamp_ts, side, entry_price, confidence, edge_estimate,
             metadata_json, status, win, pnl_maker, pnl_taker,
             created_at_ts, updated_at_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"strat_a_{i}", "residual_horizon", f"key_{i}", "Residual Horizon",
                f"cond_{i}", now - (5 - i) * 900, "YES", 0.50, 0.7, 0.05,
                "{}", status, win if status == "resolved" else None,
                pnl_maker if status == "resolved" else None,
                pnl_maker * 0.9 if status == "resolved" else None,
                now - (5 - i) * 900, now,
            ),
        )

    # Strategy B: 2 signals, 0 resolved
    for i in range(2):
        conn.execute(
            """INSERT INTO signal_shadow
            (track_id, signal_group, signal_key, signal_label, condition_id,
             timestamp_ts, side, entry_price, confidence, edge_estimate,
             metadata_json, status, win, pnl_maker, pnl_taker,
             created_at_ts, updated_at_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"strat_b_{i}", "volatility_mismatch", f"key_{i}", "Vol Mismatch",
                f"cond_{i}", now - (2 - i) * 900, "NO", 0.60, 0.5, 0.03,
                "{}", "open", None, None, None, now - (2 - i) * 900, now,
            ),
        )

    conn.commit()
    conn.close()
    return db_path


class TestLoadStrategyStats:
    def test_loads_strategies(self, db_with_signals):
        stats = load_strategy_stats(db_with_signals)
        assert len(stats) == 2

    def test_counts_correct(self, db_with_signals):
        stats = load_strategy_stats(db_with_signals)
        # Sorted by total_signals desc
        strat_a = next(s for s in stats if s.signal_group == "residual_horizon")
        assert strat_a.total_signals == 5
        assert strat_a.resolved_signals == 3
        assert strat_a.wins == 2
        assert strat_a.losses == 1

    def test_win_rate(self, db_with_signals):
        stats = load_strategy_stats(db_with_signals)
        strat_a = next(s for s in stats if s.signal_group == "residual_horizon")
        assert strat_a.win_rate == pytest.approx(2 / 3)

    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE signal_shadow (
                track_id TEXT PRIMARY KEY,
                signal_group TEXT, signal_key TEXT, signal_label TEXT,
                condition_id TEXT, timestamp_ts INTEGER, side TEXT,
                entry_price REAL, confidence REAL, edge_estimate REAL,
                metadata_json TEXT, status TEXT, resolved_outcome TEXT,
                win INTEGER, pnl_maker REAL, pnl_taker REAL,
                created_at_ts INTEGER, updated_at_ts INTEGER
            )
        """)
        conn.close()
        stats = load_strategy_stats(db_path)
        assert stats == []

    def test_no_signal_shadow_table(self, tmp_path):
        db_path = tmp_path / "no_shadow.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE ping(id integer)")
        conn.close()
        stats = load_strategy_stats(db_path)
        assert stats == []


class TestRunBattery:
    def test_zero_signals_killed(self):
        stats = StrategyStats(name="Empty", signal_group="empty", total_signals=0)
        verdict, results = run_battery_on_strategy(stats)
        assert verdict == "KILL"

    def test_few_signals_killed(self):
        stats = StrategyStats(
            name="Few", signal_group="few",
            total_signals=5, resolved_signals=3,
            wins=2, losses=1,
            total_pnl_maker=0.10, total_pnl_taker=0.08,
            avg_confidence=0.7, avg_edge=0.05, avg_entry_price=0.5,
        )
        verdict, results = run_battery_on_strategy(stats)
        # Should be KILL due to insufficient signals (need 100)
        assert verdict == "KILL"


class TestFormatName:
    def test_underscore_to_title(self):
        assert _format_strategy_name("residual_horizon") == "Residual Horizon"

    def test_hyphen_to_title(self):
        assert _format_strategy_name("vol-regime-mismatch") == "Vol Regime Mismatch"


class TestReportGeneration:
    def test_generates_markdown(self, db_with_signals):
        stats = load_strategy_stats(db_with_signals)
        verdicts = {}
        for s in stats:
            verdict, results = run_battery_on_strategy(s)
            verdicts[s.signal_group] = (verdict, results)

        report = generate_report(stats, verdicts, db_with_signals)
        assert "# Fast Trade Edge Analysis" in report
        assert "REJECT ALL" in report
        assert "REJECTED" in report
        assert "Residual Horizon" in report

    def test_report_has_detail_section(self, db_with_signals):
        stats = load_strategy_stats(db_with_signals)
        verdicts = {}
        for s in stats:
            verdict, results = run_battery_on_strategy(s)
            verdicts[s.signal_group] = (verdict, results)

        report = generate_report(stats, verdicts, db_with_signals)
        assert "KILL BATTERY DETAIL" in report
        assert "| Rule | Passed | Detail |" in report
