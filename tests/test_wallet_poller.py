"""Tests for bot.wallet_poller — live wallet polling loop."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.wallet_poller import (
    PollerState,
    WalletSnapshot,
    _iso,
    _resolve_user_address,
    _write_heartbeat,
    _write_snapshot,
    run_single_poll,
    show_status,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_snapshot(**overrides) -> WalletSnapshot:
    defaults = dict(
        timestamp=_iso(),
        user_address="0xabc",
        open_position_count=3,
        closed_position_count=10,
        reconciliation_status="reconciled",
        recommendation="ready_for_launch_gate",
        matched_local_open=2,
        matched_local_closed=8,
        drift_open_delta=0,
        drift_closed_delta=0,
        phantom_count=0,
        fixes_applied={},
        error=None,
    )
    defaults.update(overrides)
    return WalletSnapshot(**defaults)


def _seed_trades_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                market_id TEXT,
                token_id TEXT,
                outcome TEXT,
                pnl REAL,
                resolved_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO trades (id, market_id, token_id, outcome, pnl, resolved_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("t1", "0xcond1", "0xtoken1", None, None, None),
                ("t2", "0xcond2", "0xtoken2", "won", 2.0, "2026-03-10T00:00:00Z"),
            ],
        )


class FakeReconciliationSummary:
    """Lightweight stand-in for ReconciliationSummary."""

    def __init__(self, **kwargs):
        defaults = dict(
            checked_at=_iso(),
            user_address="0xabc",
            open_positions_count=3,
            closed_positions_count=10,
            local_trade_count=2,
            matched_local_open_trades=1,
            matched_local_closed_trades=1,
            remote_closed_local_open_mismatches=0,
            phantom_local_open_trade_ids=[],
            matched_remote_open_positions=1,
            matched_remote_closed_positions=1,
            unmatched_remote_open_positions=0,
            unmatched_remote_closed_positions=0,
            snapshot_precision=1.0,
            classification_precision=1.0,
            status="reconciled",
            unmatched_open_positions={"delta_remote_minus_local": 0},
            unmatched_closed_positions={"delta_remote_minus_local": 0},
            remote_closed_local_open_trade_ids=[],
            local_fixes={"closed_trades_backfilled": 0, "phantom_open_trades_deleted": 0},
            recommendation="ready_for_launch_gate",
            report_path=None,
        )
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


class FakeReconciler:
    """Fake reconciler that returns a canned summary."""

    def __init__(self, summary=None, error=None):
        self._summary = summary or FakeReconciliationSummary()
        self._error = error
        self.reconcile_calls = []
        self.closed = False

    def reconcile_to_sqlite(self, **kwargs):
        self.reconcile_calls.append(kwargs)
        if self._error:
            raise self._error
        return self._summary

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWalletSnapshot:
    def test_snapshot_is_frozen(self):
        snap = _make_snapshot()
        with pytest.raises(AttributeError):
            snap.open_position_count = 99  # type: ignore[misc]

    def test_snapshot_asdict(self):
        snap = _make_snapshot(open_position_count=5)
        d = asdict(snap)
        assert d["open_position_count"] == 5
        assert d["user_address"] == "0xabc"

    def test_snapshot_with_error(self):
        snap = _make_snapshot(error="timeout", reconciliation_status="error")
        assert snap.error == "timeout"
        assert snap.reconciliation_status == "error"


class TestHeartbeatPersistence:
    def test_write_heartbeat_creates_file(self, tmp_path: Path):
        hb_path = tmp_path / "heartbeat.json"
        state = PollerState(started_at=_iso(), cycles_completed=3)
        snap = _make_snapshot()
        _write_heartbeat(hb_path, state=state, snapshot=snap)
        assert hb_path.exists()
        data = json.loads(hb_path.read_text())
        assert data["service"] == "wallet-poller"
        assert data["cycles_completed"] == 3
        assert "last_snapshot" in data

    def test_write_heartbeat_creates_parent_dir(self, tmp_path: Path):
        hb_path = tmp_path / "nested" / "deep" / "heartbeat.json"
        state = PollerState(started_at=_iso())
        _write_heartbeat(hb_path, state=state, snapshot=None)
        assert hb_path.exists()

    def test_write_heartbeat_without_snapshot(self, tmp_path: Path):
        hb_path = tmp_path / "heartbeat.json"
        state = PollerState(started_at=_iso())
        _write_heartbeat(hb_path, state=state, snapshot=None, status="starting")
        data = json.loads(hb_path.read_text())
        assert data["status"] == "starting"
        assert "last_snapshot" not in data


class TestSnapshotPersistence:
    def test_write_snapshot_creates_files(self, tmp_path: Path):
        snap = _make_snapshot()
        live_report = tmp_path / "reports" / "wallet_live_snapshot_latest.json"
        path = _write_snapshot(tmp_path, snap, live_snapshot_path=live_report)
        assert path.exists()
        latest = tmp_path / "latest.json"
        assert latest.exists()
        data = json.loads(latest.read_text())
        assert data["user_address"] == "0xabc"
        report = json.loads(live_report.read_text())
        assert report["artifact"] == "wallet_live_snapshot"
        assert report["status"] == "fresh"
        assert report["source_of_truth"]


class TestRunSinglePoll:
    def test_successful_poll_returns_reconciled_snapshot(self, tmp_path: Path):
        db_path = tmp_path / "data" / "trades.db"
        _seed_trades_db(db_path)
        rec = FakeReconciler()

        with patch("bot.wallet_poller._get_reconciler_module") as mock_mod:
            mock_mod.return_value.PolymarketWalletReconciler.return_value = rec
            snap = run_single_poll(
                user_address="0xabc",
                db_path=db_path,
                reconciler=rec,
            )

        assert snap.reconciliation_status == "reconciled"
        assert snap.open_position_count == 3
        assert snap.closed_position_count == 10
        assert snap.error is None

    def test_poll_with_drift(self, tmp_path: Path):
        db_path = tmp_path / "data" / "trades.db"
        _seed_trades_db(db_path)
        summary = FakeReconciliationSummary(
            status="drift_detected",
            recommendation="apply_local_closure_backfill",
            unmatched_open_positions={"delta_remote_minus_local": 5},
            unmatched_closed_positions={"delta_remote_minus_local": -2},
            phantom_local_open_trade_ids=["phantom_1"],
        )
        rec = FakeReconciler(summary=summary)
        snap = run_single_poll(
            user_address="0xabc",
            db_path=db_path,
            reconciler=rec,
        )
        assert snap.reconciliation_status == "drift_detected"
        assert snap.drift_open_delta == 5
        assert snap.drift_closed_delta == -2
        assert snap.phantom_count == 1

    def test_poll_error_returns_error_snapshot(self, tmp_path: Path):
        db_path = tmp_path / "data" / "trades.db"
        rec = FakeReconciler(error=RuntimeError("api_timeout"))
        snap = run_single_poll(
            user_address="0xabc",
            db_path=db_path,
            reconciler=rec,
        )
        assert snap.reconciliation_status == "error"
        assert "api_timeout" in snap.error

    def test_poll_with_fixes_applied(self, tmp_path: Path):
        db_path = tmp_path / "data" / "trades.db"
        _seed_trades_db(db_path)
        summary = FakeReconciliationSummary(
            status="reconciled",
            local_fixes={"closed_trades_backfilled": 2, "phantom_open_trades_deleted": 1},
        )
        rec = FakeReconciler(summary=summary)
        snap = run_single_poll(
            user_address="0xabc",
            db_path=db_path,
            apply_fixes=True,
            reconciler=rec,
        )
        assert snap.fixes_applied["closed_trades_backfilled"] == 2
        assert snap.fixes_applied["phantom_open_trades_deleted"] == 1

    def test_reconciler_close_called_when_not_injected(self, tmp_path: Path):
        db_path = tmp_path / "data" / "trades.db"
        _seed_trades_db(db_path)
        fake_rec = FakeReconciler()
        with patch("bot.wallet_poller._get_reconciler_module") as mock_mod:
            mock_mod.return_value.PolymarketWalletReconciler.return_value = fake_rec
            run_single_poll(user_address="0xabc", db_path=db_path)
        assert fake_rec.closed


class TestShowStatus:
    def test_status_when_no_heartbeat(self, tmp_path: Path):
        result = show_status(tmp_path / "nonexistent.json")
        assert result["status"] == "not_running"

    def test_status_reads_heartbeat(self, tmp_path: Path):
        hb_path = tmp_path / "heartbeat.json"
        hb_path.write_text(json.dumps({"status": "running", "cycles_completed": 42}))
        result = show_status(hb_path)
        assert result["status"] == "running"
        assert result["cycles_completed"] == 42

    def test_status_handles_corrupt_file(self, tmp_path: Path):
        hb_path = tmp_path / "heartbeat.json"
        hb_path.write_text("not json at all{{{")
        result = show_status(hb_path)
        assert result["status"] == "heartbeat_unreadable"


class TestPollerState:
    def test_default_state(self):
        state = PollerState()
        assert state.cycles_completed == 0
        assert state.consecutive_errors == 0
        assert state.last_snapshot is None

    def test_state_mutation(self):
        state = PollerState(started_at="2026-03-14T00:00:00Z")
        state.cycles_completed = 5
        state.consecutive_errors = 2
        assert state.cycles_completed == 5
        assert state.consecutive_errors == 2


def test_resolve_user_address_prefers_poly_data_api_address(monkeypatch) -> None:
    monkeypatch.setenv("POLY_DATA_API_ADDRESS", "0x123")
    monkeypatch.setenv("POLY_SAFE_ADDRESS", "0x456")
    monkeypatch.setenv("POLYMARKET_FUNDER", "0x789")

    assert _resolve_user_address() == "0x123"
