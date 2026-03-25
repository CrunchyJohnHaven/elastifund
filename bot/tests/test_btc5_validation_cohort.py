"""
Tests for the BTC5 post-fix validation cohort infrastructure.

Covers:
  1. cohort contract has all required fields
  2. cohort_status starts as "awaiting_deploy"
  3. render_cohort with empty DB returns recommendation == "awaiting_data"
  4. render_cohort counts only DOWN live resolved fills (excludes UP + paper)
  5. render_cohort recommendation == "kill" at 50 fills, all losses
  6. render_cohort recommendation == "positive_first_cohort" at 50 fills, all wins
  7. deploy checklist passes with all files correct
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — make scripts importable
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import render_btc5_validation_cohort as renderer
import btc5_deploy_checklist as checklist

_COHORT_JSON = _REPO_ROOT / "state" / "btc5_validation_cohort.json"


# ---------------------------------------------------------------------------
# Helper: build a minimal in-memory SQLite DB with the window_trades schema
# ---------------------------------------------------------------------------

def _create_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start_ts INTEGER,
            decision_ts INTEGER,
            direction TEXT,
            order_status TEXT,
            resolved_side TEXT,
            won INTEGER,
            pnl_usd REAL,
            order_price REAL,
            trade_size_usd REAL
        )
        """
    )
    conn.commit()
    return conn


def _insert_fill(
    conn: sqlite3.Connection,
    direction: str,
    order_status: str,
    resolved_side: str | None,
    pnl: float,
    decision_ts: int,
    order_price: float = 0.46,
    trade_size: float = 5.0,
) -> None:
    conn.execute(
        "INSERT INTO window_trades "
        "(direction, order_status, resolved_side, won, pnl_usd, decision_ts, order_price, trade_size_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            direction,
            order_status,
            resolved_side,
            1 if (resolved_side and resolved_side.upper() == direction.upper()) else 0,
            pnl,
            decision_ts,
            order_price,
            trade_size,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# 1. cohort contract has required fields
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    "cohort_id",
    "cohort_status",
    "cohort_start_ts",
    "cohort_activated_at",
    "validation_mutation_id",
    "validation_config_hash",
    "validation_profile_name",
    "validation_effective_max_trade_usd",
    "validation_down_max_buy_price",
    "validation_direction_mode",
    "validation_up_live_mode",
    "validation_hour_filter_enabled",
    "validation_suppress_hours_et",
    "target_resolved_fills",
    "checkpoint_fills",
    "notes",
    "safety_kill_triggered",
    "safety_kill_reason",
    "safety_kill_ts",
]


def test_cohort_contract_has_required_fields():
    assert _COHORT_JSON.exists(), f"Cohort contract not found: {_COHORT_JSON}"
    data = json.loads(_COHORT_JSON.read_text())
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    assert missing == [], f"Missing fields: {missing}"


# ---------------------------------------------------------------------------
# 2. cohort_status starts as "awaiting_deploy"
# ---------------------------------------------------------------------------

def test_cohort_status_starts_awaiting_deploy():
    data = json.loads(_COHORT_JSON.read_text())
    # Only assert this if the file has never been activated
    # (i.e., cohort_start_ts is null — pre-activation state)
    if data.get("cohort_start_ts") is None:
        assert data["cohort_status"] == "awaiting_deploy", (
            f"Expected 'awaiting_deploy', got {data['cohort_status']!r}"
        )
    else:
        # Once activated, status will be "active" — skip the check
        pytest.skip("Cohort already activated; status check not applicable")


# ---------------------------------------------------------------------------
# 3. render_cohort with empty DB returns awaiting_data
# ---------------------------------------------------------------------------

def test_render_cohort_with_empty_db_returns_awaiting_data(tmp_path):
    # Build a cohort contract in "active" state with a past start_ts
    cohort_path = tmp_path / "btc5_validation_cohort.json"
    output_path = tmp_path / "report.json"
    start_ts = int(time.time()) - 3600

    cohort_data = {
        "cohort_id": "test_v1",
        "cohort_status": "active",
        "cohort_start_ts": start_ts,
        "cohort_activated_at": "2026-01-01T00:00:00+00:00",
        "validation_mutation_id": "baseline_v1",
        "validation_config_hash": None,
        "safety_kill_triggered": False,
    }
    cohort_path.write_text(json.dumps(cohort_data))

    db_path = tmp_path / "test.db"
    conn = _create_db(db_path)
    conn.close()

    with (
        patch.object(renderer, "_COHORT_PATH", cohort_path),
        patch.object(renderer, "_OUTPUT_PATH", output_path),
        patch.object(renderer, "_DB_PROBE_PATHS", [db_path]),
    ):
        report = renderer.build_report()

    assert report["recommendation"] == "awaiting_data"
    assert report["resolved_down_fills"] == 0
    assert report["wins"] == 0
    assert report["losses"] == 0


# ---------------------------------------------------------------------------
# 4. render_cohort counts only DOWN live resolved fills
# ---------------------------------------------------------------------------

def test_render_cohort_counts_only_down_live_resolved_fills(tmp_path):
    cohort_path = tmp_path / "btc5_validation_cohort.json"
    output_path = tmp_path / "report.json"
    start_ts = int(time.time()) - 7200

    cohort_data = {
        "cohort_id": "test_v1",
        "cohort_status": "active",
        "cohort_start_ts": start_ts,
        "cohort_activated_at": "2026-01-01T00:00:00+00:00",
        "validation_mutation_id": "baseline_v1",
        "validation_config_hash": None,
        "safety_kill_triggered": False,
    }
    cohort_path.write_text(json.dumps(cohort_data))

    db_path = tmp_path / "test.db"
    conn = _create_db(db_path)

    ts = start_ts + 100

    # Should count: DOWN, live_filled, resolved
    _insert_fill(conn, "DOWN", "live_filled", "DOWN", pnl=0.50, decision_ts=ts)

    # Should NOT count: UP direction
    _insert_fill(conn, "UP", "live_filled", "UP", pnl=0.50, decision_ts=ts + 1)

    # Should NOT count: paper/shadow status
    _insert_fill(conn, "DOWN", "shadow_filled", "DOWN", pnl=0.50, decision_ts=ts + 2)

    # Should NOT count: paper fill
    _insert_fill(conn, "DOWN", "paper_filled", "DOWN", pnl=0.50, decision_ts=ts + 3)

    # Should NOT count: not resolved (resolved_side = None)
    _insert_fill(conn, "DOWN", "live_filled", None, pnl=0.0, decision_ts=ts + 4)

    # Should NOT count: before cohort_start_ts
    _insert_fill(conn, "DOWN", "live_filled", "DOWN", pnl=0.50, decision_ts=start_ts - 100)

    # Should NOT count: skip status
    _insert_fill(conn, "DOWN", "live_skipped", "DOWN", pnl=0.0, decision_ts=ts + 5)

    conn.close()

    with (
        patch.object(renderer, "_COHORT_PATH", cohort_path),
        patch.object(renderer, "_OUTPUT_PATH", output_path),
        patch.object(renderer, "_DB_PROBE_PATHS", [db_path]),
    ):
        report = renderer.build_report()

    assert report["resolved_down_fills"] == 1, (
        f"Expected 1 qualifying fill, got {report['resolved_down_fills']}"
    )
    assert report["wins"] == 1


# ---------------------------------------------------------------------------
# 5. recommendation == "kill" at 50 fills, all losses
# ---------------------------------------------------------------------------

def test_render_cohort_recommendation_kill_at_50_negative(tmp_path):
    cohort_path = tmp_path / "btc5_validation_cohort.json"
    output_path = tmp_path / "report.json"
    start_ts = int(time.time()) - 7200

    cohort_data = {
        "cohort_id": "test_v1",
        "cohort_status": "active",
        "cohort_start_ts": start_ts,
        "cohort_activated_at": "2026-01-01T00:00:00+00:00",
        "validation_mutation_id": "baseline_v1",
        "validation_config_hash": None,
        "safety_kill_triggered": False,
    }
    cohort_path.write_text(json.dumps(cohort_data))

    db_path = tmp_path / "test.db"
    conn = _create_db(db_path)

    # Insert 50 DOWN live_filled fills where DOWN resolves to UP (losses)
    for i in range(50):
        _insert_fill(
            conn,
            direction="DOWN",
            order_status="live_filled",
            resolved_side="UP",  # DOWN direction, UP resolved = loss
            pnl=-1.0,
            decision_ts=start_ts + 100 + i,
        )
    conn.close()

    with (
        patch.object(renderer, "_COHORT_PATH", cohort_path),
        patch.object(renderer, "_OUTPUT_PATH", output_path),
        patch.object(renderer, "_DB_PROBE_PATHS", [db_path]),
    ):
        report = renderer.build_report()

    assert report["resolved_down_fills"] == 50
    assert report["wins"] == 0
    assert report["losses"] == 50
    assert report["recommendation"] == "kill", (
        f"Expected 'kill', got {report['recommendation']!r}"
    )


# ---------------------------------------------------------------------------
# 6. recommendation == "positive_first_cohort" at 50 fills, all wins
# ---------------------------------------------------------------------------

def test_render_cohort_recommendation_positive_at_50_wins(tmp_path):
    cohort_path = tmp_path / "btc5_validation_cohort.json"
    output_path = tmp_path / "report.json"
    start_ts = int(time.time()) - 7200

    cohort_data = {
        "cohort_id": "test_v1",
        "cohort_status": "active",
        "cohort_start_ts": start_ts,
        "cohort_activated_at": "2026-01-01T00:00:00+00:00",
        "validation_mutation_id": "baseline_v1",
        "validation_config_hash": None,
        "safety_kill_triggered": False,
    }
    cohort_path.write_text(json.dumps(cohort_data))

    db_path = tmp_path / "test.db"
    conn = _create_db(db_path)

    # Insert 50 DOWN wins (DOWN direction resolves DOWN)
    for i in range(50):
        _insert_fill(
            conn,
            direction="DOWN",
            order_status="live_filled",
            resolved_side="DOWN",
            pnl=2.0,
            decision_ts=start_ts + 100 + i,
        )
    conn.close()

    with (
        patch.object(renderer, "_COHORT_PATH", cohort_path),
        patch.object(renderer, "_OUTPUT_PATH", output_path),
        patch.object(renderer, "_DB_PROBE_PATHS", [db_path]),
    ):
        report = renderer.build_report()

    assert report["resolved_down_fills"] == 50
    assert report["wins"] == 50
    assert report["losses"] == 0
    assert report["recommendation"] == "positive_first_cohort", (
        f"Expected 'positive_first_cohort', got {report['recommendation']!r}"
    )


# ---------------------------------------------------------------------------
# 7. deploy checklist passes with all files correct
# ---------------------------------------------------------------------------

def test_deploy_checklist_passes_clean_env(tmp_path, monkeypatch):
    """Mock all 10 check functions to return PASS and verify 10/10 output."""

    # Replace every individual check function with a passing stub
    check_names = [
        "_check_mutation_verify_ok",
        "_check_runtime_contract_exists",
        "_check_active_mutation_not_reverted",
        "_check_config_hash_match",
        "_check_effective_env_fresh",
        "_check_cohort_contract_defined",
        "_check_up_live_mode_shadow",
        "_check_direction_mode_down_only",
        "_check_down_price_cap",
        "_check_hour_filter_enabled",
    ]

    patches = []
    for name in check_names:
        p = patch.object(checklist, name, return_value=(True, "mocked OK"))
        patches.append(p)
        p.start()

    try:
        # Capture main() output and exit code
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = checklist.main()

        output = buf.getvalue()
        assert exit_code == 0, f"Expected exit 0, got {exit_code}. Output:\n{output}"
        assert "10/10 checks passed" in output, (
            f"Expected '10/10 checks passed' in output:\n{output}"
        )
        assert "DEPLOY VALID" in output

        # Verify all 10 lines show PASS
        pass_lines = [l for l in output.splitlines() if l.startswith("PASS")]
        assert len(pass_lines) == 10, f"Expected 10 PASS lines, got {len(pass_lines)}"

    finally:
        for p in patches:
            p.stop()
