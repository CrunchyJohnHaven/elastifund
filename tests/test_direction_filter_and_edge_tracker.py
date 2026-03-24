"""Tests for directional bias filter and rolling edge tracker (Instance 5)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from bot.btc_5min_maker import _direction_filter_status


# ---------------------------------------------------------------------------
# Part A: _direction_filter_status tests
# ---------------------------------------------------------------------------


class TestDirectionFilterStatus:
    def test_both_mode_allows_everything(self) -> None:
        assert _direction_filter_status("UP", mode="both", down_bias_threshold=0.6) == "allowed"
        assert _direction_filter_status("DOWN", mode="both", down_bias_threshold=0.6) == "allowed"

    def test_down_only_suppresses_up(self) -> None:
        assert _direction_filter_status("UP", mode="down_only", down_bias_threshold=0.6) == "suppressed"
        assert _direction_filter_status("DOWN", mode="down_only", down_bias_threshold=0.6) == "allowed"

    def test_up_only_suppresses_down(self) -> None:
        assert _direction_filter_status("DOWN", mode="up_only", down_bias_threshold=0.6) == "suppressed"
        assert _direction_filter_status("UP", mode="up_only", down_bias_threshold=0.6) == "allowed"

    def test_down_bias_always_allows_down(self) -> None:
        assert _direction_filter_status("DOWN", mode="down_bias", down_bias_threshold=0.6) == "allowed"

    def test_down_bias_blocks_low_confidence_up(self) -> None:
        assert _direction_filter_status(
            "UP", mode="down_bias", down_bias_threshold=0.6, confidence=0.5
        ) == "biased_block"

    def test_down_bias_passes_high_confidence_up(self) -> None:
        assert _direction_filter_status(
            "UP", mode="down_bias", down_bias_threshold=0.6, confidence=0.7
        ) == "biased_pass"

    def test_down_bias_blocks_none_confidence_up(self) -> None:
        assert _direction_filter_status(
            "UP", mode="down_bias", down_bias_threshold=0.6, confidence=None
        ) == "biased_block"

    def test_unknown_mode_defaults_allowed(self) -> None:
        assert _direction_filter_status("UP", mode="bogus", down_bias_threshold=0.6) == "allowed"

    def test_empty_direction(self) -> None:
        assert _direction_filter_status("", mode="down_only", down_bias_threshold=0.6) == "suppressed"

    def test_case_insensitive_direction(self) -> None:
        assert _direction_filter_status("up", mode="down_only", down_bias_threshold=0.6) == "suppressed"
        assert _direction_filter_status("down", mode="down_only", down_bias_threshold=0.6) == "allowed"


# ---------------------------------------------------------------------------
# Part B: rolling_edge_tracker tests
# ---------------------------------------------------------------------------


def _create_test_db(rows: list[dict]) -> Path:
    """Create a temporary SQLite DB with synthetic resolved fills."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start_ts INTEGER NOT NULL UNIQUE,
            window_end_ts INTEGER NOT NULL,
            slug TEXT NOT NULL,
            decision_ts INTEGER NOT NULL,
            direction TEXT,
            open_price REAL,
            current_price REAL,
            delta REAL,
            book_imbalance REAL,
            token_id TEXT,
            best_bid REAL,
            best_ask REAL,
            order_price REAL,
            trade_size_usd REAL,
            shares REAL,
            order_id TEXT,
            order_status TEXT NOT NULL,
            filled INTEGER,
            reason TEXT,
            risk_mode TEXT,
            edge_tier TEXT,
            sizing_reason_tags TEXT,
            loss_cluster_suppressed INTEGER,
            session_policy_name TEXT,
            effective_stage INTEGER,
            wallet_copy INTEGER,
            wallet_count INTEGER,
            wallet_notional REAL,
            realized_pnl_usd REAL,
            hour_filter_status TEXT,
            direction_filter_status TEXT,
            resolved_side TEXT,
            won INTEGER,
            pnl_usd REAL,
            resolved_ts INTEGER,
            time_to_resolution_sec REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    for i, row in enumerate(rows):
        conn.execute(
            """INSERT INTO window_trades
            (window_start_ts, window_end_ts, slug, decision_ts,
             direction, order_status, filled, won, pnl_usd,
             created_at, updated_at)
            VALUES (?, ?, 'test', ?, ?, ?, 1, ?, ?, '2026-01-01', '2026-01-01')""",
            (
                1000 + i * 300,
                1300 + i * 300,
                1000 + i * 300,
                row["direction"],
                "live_filled",
                row["won"],
                row.get("pnl_usd", 0.5 if row["won"] else -0.5),
            ),
        )
    conn.commit()
    conn.close()
    return db_path


class TestRollingEdgeTracker:
    def test_insufficient_data(self) -> None:
        from bot.rolling_edge_tracker import analyze

        rows = [{"direction": "DOWN", "won": 1}] * 10
        db = _create_test_db(rows)
        rec = analyze(db, min_fills=50)
        assert rec.recommended_mode == "both"
        assert rec.confidence == 0.0
        assert "insufficient" in rec.reason
        db.unlink()

    def test_down_dominant(self) -> None:
        from bot.rolling_edge_tracker import analyze

        # Interleave DOWN and UP so both appear in lookback window
        rows = []
        for i in range(120):
            if i % 2 == 0:
                # DOWN: 60% WR (36 of 60 win)
                idx = i // 2
                rows.append({"direction": "DOWN", "won": 1 if idx < 36 else 0})
            else:
                # UP: 40% WR (24 of 60 win)
                idx = i // 2
                rows.append({"direction": "UP", "won": 1 if idx < 24 else 0})
        db = _create_test_db(rows)
        rec = analyze(db, lookback=200, min_fills=50)
        assert rec.recommended_mode == "down_only"
        assert rec.down_wr > 0.55
        assert rec.up_wr < 0.48
        db.unlink()

    def test_up_dominant(self) -> None:
        from bot.rolling_edge_tracker import analyze

        rows = []
        for i in range(120):
            if i % 2 == 0:
                idx = i // 2
                rows.append({"direction": "UP", "won": 1 if idx < 36 else 0})
            else:
                idx = i // 2
                rows.append({"direction": "DOWN", "won": 1 if idx < 24 else 0})
        db = _create_test_db(rows)
        rec = analyze(db, lookback=200, min_fills=50)
        assert rec.recommended_mode == "up_only"
        db.unlink()

    def test_both_profitable(self) -> None:
        from bot.rolling_edge_tracker import analyze

        rows = []
        for i in range(120):
            if i % 2 == 0:
                idx = i // 2
                rows.append({"direction": "DOWN", "won": 1 if idx < 33 else 0})
            else:
                idx = i // 2
                rows.append({"direction": "UP", "won": 1 if idx < 33 else 0})
        db = _create_test_db(rows)
        rec = analyze(db, lookback=200, min_fills=50)
        assert rec.recommended_mode == "both"
        db.unlink()

    def test_both_losing(self) -> None:
        from bot.rolling_edge_tracker import analyze

        rows = []
        for i in range(120):
            if i % 2 == 0:
                idx = i // 2
                rows.append({"direction": "DOWN", "won": 1 if idx < 27 else 0})
            else:
                idx = i // 2
                rows.append({"direction": "UP", "won": 1 if idx < 27 else 0})
        db = _create_test_db(rows)
        rec = analyze(db, lookback=200, min_fills=50)
        assert rec.recommended_mode == "pause"
        db.unlink()

    def test_empty_db(self) -> None:
        from bot.rolling_edge_tracker import analyze

        db = _create_test_db([])
        rec = analyze(db, min_fills=50)
        assert rec.recommended_mode == "both"
        assert rec.confidence == 0.0
        db.unlink()

    def test_missing_db(self) -> None:
        from bot.rolling_edge_tracker import analyze

        rec = analyze(Path("/tmp/nonexistent_db_xyz.db"), min_fills=50)
        assert rec.recommended_mode == "both"
        assert rec.confidence == 0.0

    def test_log_recommendation(self) -> None:
        from bot.rolling_edge_tracker import analyze, log_recommendation, load_recent_recommendations

        db = _create_test_db([])
        rec = analyze(db)
        log_path = Path(tempfile.mktemp(suffix=".json"))
        log_recommendation(rec, log_path)
        entries = load_recent_recommendations(log_path)
        assert len(entries) == 1
        assert entries[0]["recommended_mode"] == "both"
        log_path.unlink()
        db.unlink()

    def test_log_max_entries(self) -> None:
        from bot.rolling_edge_tracker import analyze, log_recommendation, load_recent_recommendations

        db = _create_test_db([])
        rec = analyze(db)
        log_path = Path(tempfile.mktemp(suffix=".json"))
        for _ in range(10):
            log_recommendation(rec, log_path, max_entries=5)
        entries = load_recent_recommendations(log_path, limit=100)
        assert len(entries) == 5
        log_path.unlink()
        db.unlink()


# ---------------------------------------------------------------------------
# Part C: check_edge_recommendation script
# ---------------------------------------------------------------------------


class TestCheckEdgeScript:
    def test_script_runs_without_log(self) -> None:
        import subprocess
        result = subprocess.run(
            ["python3", "scripts/check_edge_recommendation.py", "--log-path", "/tmp/nonexistent_xyz.json"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "No edge tracker log" in result.stdout

    def test_script_with_matching_mode(self) -> None:
        import subprocess
        log_path = Path(tempfile.mktemp(suffix=".json"))
        log_path.write_text(json.dumps([{
            "down_wr": 0.55,
            "up_wr": 0.45,
            "down_fills": 60,
            "up_fills": 60,
            "down_pnl_usd": 10.0,
            "up_pnl_usd": -5.0,
            "recommended_mode": "both",
            "confidence": 0.3,
            "reason": "test",
            "timestamp": "2026-01-01T00:00:00",
        }]))
        result = subprocess.run(
            ["python3", "scripts/check_edge_recommendation.py",
             "--log-path", str(log_path), "--current-mode", "both"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        assert "matches recommendation" in result.stdout
        log_path.unlink()

    def test_script_with_mismatched_mode(self) -> None:
        import subprocess
        log_path = Path(tempfile.mktemp(suffix=".json"))
        log_path.write_text(json.dumps([{
            "down_wr": 0.60,
            "up_wr": 0.40,
            "down_fills": 60,
            "up_fills": 60,
            "down_pnl_usd": 20.0,
            "up_pnl_usd": -10.0,
            "recommended_mode": "down_only",
            "confidence": 0.8,
            "reason": "test",
            "timestamp": "2026-01-01T00:00:00",
        }]))
        result = subprocess.run(
            ["python3", "scripts/check_edge_recommendation.py",
             "--log-path", str(log_path), "--current-mode", "both"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
        assert "MISMATCH" in result.stdout
        log_path.unlink()
