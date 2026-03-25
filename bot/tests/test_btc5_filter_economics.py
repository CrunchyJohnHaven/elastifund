#!/usr/bin/env python3
"""Tests for P1.4 Filter Economics Ledger (filter_decisions table and render script)."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker import TradeDB  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path) -> TradeDB:
    """Return a fresh TradeDB backed by a temp file."""
    db = TradeDB(tmp_path / "test_filter.db")
    return db


@pytest.fixture()
def existing_db(tmp_path) -> Path:
    """Return a pre-existing DB that lacks the filter_decisions table."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start_ts INTEGER NOT NULL UNIQUE,
            window_end_ts INTEGER NOT NULL,
            slug TEXT NOT NULL,
            decision_ts INTEGER NOT NULL,
            order_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# DB schema tests
# ---------------------------------------------------------------------------


class TestFilterDecisionsTable:
    def test_table_created_on_init(self, tmp_db):
        """filter_decisions table must exist after TradeDB init."""
        conn = sqlite3.connect(str(tmp_db.db_path))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='filter_decisions'"
        ).fetchone()
        conn.close()
        assert row is not None, "filter_decisions table was not created"

    def test_index_created_on_init(self, tmp_db):
        """idx_filter_decisions_window index must exist."""
        conn = sqlite3.connect(str(tmp_db.db_path))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_filter_decisions_window'"
        ).fetchone()
        conn.close()
        assert row is not None, "idx_filter_decisions_window index was not created"

    def test_backward_compatible_with_existing_db(self, existing_db):
        """TradeDB must gracefully create filter_decisions on an existing DB without it."""
        # This should not raise
        db = TradeDB(existing_db)
        conn = sqlite3.connect(str(db.db_path))
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='filter_decisions'"
        ).fetchone()
        conn.close()
        assert row is not None, "filter_decisions table not created on legacy DB"


# ---------------------------------------------------------------------------
# record_filter_decision tests
# ---------------------------------------------------------------------------


class TestRecordFilterDecision:
    def test_record_inserted_correctly(self, tmp_db):
        """A single record is inserted with all fields populated."""
        tmp_db.record_filter_decision(
            window_start_ts=1700000000,
            slug="btc-5min-2024-01-01T00:00:00Z",
            filter_name="hour_filter",
            filter_state="blocked",
            direction="UP",
            counterfactual_entry_price=0.52,
            counterfactual_direction="UP",
            counterfactual_trade_size_usd=5.0,
            hour_et=2,
            notes="test note",
        )
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM filter_decisions LIMIT 1").fetchone()
        conn.close()

        assert row is not None
        assert row["window_start_ts"] == 1700000000
        assert row["filter_name"] == "hour_filter"
        assert row["filter_state"] == "blocked"
        assert row["direction"] == "UP"
        assert abs(row["counterfactual_entry_price"] - 0.52) < 1e-9
        assert row["counterfactual_direction"] == "UP"
        assert abs(row["counterfactual_trade_size_usd"] - 5.0) < 1e-9
        assert row["hour_et"] == 2
        assert row["notes"] == "test note"
        assert row["recorded_at"] is not None

    def test_multiple_records_same_window_allowed(self, tmp_db):
        """Multiple filter decisions for the same window_start_ts are all stored."""
        ts = 1700000300
        tmp_db.record_filter_decision(
            window_start_ts=ts,
            slug="test-slug",
            filter_name="hour_filter",
            filter_state="blocked",
            direction="DOWN",
            counterfactual_entry_price=None,
            counterfactual_direction="DOWN",
            counterfactual_trade_size_usd=None,
        )
        tmp_db.record_filter_decision(
            window_start_ts=ts,
            slug="test-slug",
            filter_name="direction_filter",
            filter_state="blocked",
            direction="UP",
            counterfactual_entry_price=0.48,
            counterfactual_direction="UP",
            counterfactual_trade_size_usd=5.0,
        )
        conn = sqlite3.connect(str(tmp_db.db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM filter_decisions WHERE window_start_ts = ?", (ts,)
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_direction_filter_records_queryable_by_filter_name(self, tmp_db):
        """Records for direction_filter can be queried by filter_name."""
        for ts_offset in range(3):
            tmp_db.record_filter_decision(
                window_start_ts=1700000000 + ts_offset * 300,
                slug="test-slug",
                filter_name="direction_filter",
                filter_state="blocked",
                direction="UP",
                counterfactual_entry_price=0.51,
                counterfactual_direction="UP",
                counterfactual_trade_size_usd=5.0,
            )
        # Insert a different filter to ensure we filter correctly
        tmp_db.record_filter_decision(
            window_start_ts=1700009000,
            slug="test-slug",
            filter_name="hour_filter",
            filter_state="blocked",
            direction="UP",
            counterfactual_entry_price=None,
            counterfactual_direction="UP",
            counterfactual_trade_size_usd=None,
        )

        conn = sqlite3.connect(str(tmp_db.db_path))
        count = conn.execute(
            "SELECT COUNT(*) FROM filter_decisions WHERE filter_name = 'direction_filter'"
        ).fetchone()[0]
        conn.close()
        assert count == 3

    def test_nullable_fields_accept_none(self, tmp_db):
        """Records with None for optional fields are stored without error."""
        tmp_db.record_filter_decision(
            window_start_ts=1700000600,
            slug="test-slug",
            filter_name="up_live_mode",
            filter_state="shadow_only",
            direction=None,
            counterfactual_entry_price=None,
            counterfactual_direction=None,
            counterfactual_trade_size_usd=None,
            hour_et=None,
            notes=None,
        )
        conn = sqlite3.connect(str(tmp_db.db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM filter_decisions WHERE window_start_ts = 1700000600"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["direction"] is None
        assert row["counterfactual_entry_price"] is None
        assert row["hour_et"] is None


# ---------------------------------------------------------------------------
# Render script smoke test
# ---------------------------------------------------------------------------


class TestRenderScript:
    def test_render_script_runs_without_error(self, tmp_path):
        """render_btc5_filter_economics.py runs and produces valid JSON."""
        # Create a fresh DB with some data
        db = TradeDB(tmp_path / "smoke.db")
        db.record_filter_decision(
            window_start_ts=1700000000,
            slug="test-slug",
            filter_name="hour_filter",
            filter_state="blocked",
            direction="UP",
            counterfactual_entry_price=None,
            counterfactual_direction="UP",
            counterfactual_trade_size_usd=5.0,
            hour_et=2,
        )
        db.record_filter_decision(
            window_start_ts=1700000300,
            slug="test-slug",
            filter_name="direction_filter",
            filter_state="blocked",
            direction="UP",
            counterfactual_entry_price=0.51,
            counterfactual_direction="UP",
            counterfactual_trade_size_usd=5.0,
            hour_et=14,
        )
        db.record_filter_decision(
            window_start_ts=1700000600,
            slug="test-slug",
            filter_name="cap_breach",
            filter_state="blocked",
            direction="UP",
            counterfactual_entry_price=0.49,
            counterfactual_direction="UP",
            counterfactual_trade_size_usd=250.0,
            hour_et=10,
        )

        script_path = Path(__file__).parent.parent.parent / "scripts" / "render_btc5_filter_economics.py"
        output_path = tmp_path / "out.json"

        result = subprocess.run(
            [sys.executable, str(script_path), "--db-path", str(tmp_path / "smoke.db"), "--output", str(output_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        assert output_path.exists(), "Output file not created"
        with open(output_path) as f:
            data = json.load(f)

        assert "total_filter_decisions" in data
        assert data["total_filter_decisions"] == 3
        assert "by_filter" in data
        assert "direction_filter" in data["by_filter"]
        assert "hour_filter" in data["by_filter"]
        assert "up_live_mode" in data["by_filter"]
        assert "cap_breach" in data["by_filter"]

        assert data["by_filter"]["direction_filter"]["total_blocked"] == 1
        assert data["by_filter"]["cap_breach"]["total_blocked"] == 1
        assert abs(data["by_filter"]["cap_breach"]["worst_breach_usd"] - 250.0) < 0.01

    def test_render_script_handles_missing_db(self, tmp_path):
        """render_btc5_filter_economics.py handles a missing DB gracefully."""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "render_btc5_filter_economics.py"
        output_path = tmp_path / "out_missing.json"
        missing_db = tmp_path / "does_not_exist.db"

        result = subprocess.run(
            [sys.executable, str(script_path), "--db-path", str(missing_db), "--output", str(output_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Script should not crash on missing DB: {result.stderr}"
        with open(output_path) as f:
            data = json.load(f)
        assert "error" in data
