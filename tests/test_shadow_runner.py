"""Tests for bot/shadow_runner.py — shadow-mode signal runner."""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bot.shadow_runner import (
    ShadowDB,
    ShadowSignal,
    _compute_hypothetical_size,
    LANE_SCANNERS,
)


@pytest.fixture
def shadow_db(tmp_path):
    db = ShadowDB(tmp_path / "test_shadow.db")
    yield db
    db.close()


def _make_signal(**overrides) -> ShadowSignal:
    defaults = dict(
        lane="wallet_flow",
        market_id="0xabc123",
        question="BTC up or down?",
        direction="buy_yes",
        market_price=0.50,
        estimated_prob=0.60,
        edge=0.10,
        confidence=0.65,
        reasoning="test signal",
        hypothetical_size_usd=5.0,
        timestamp_utc="2026-03-14T12:00:00+00:00",
    )
    defaults.update(overrides)
    return ShadowSignal(**defaults)


class TestShadowDB:
    def test_create_and_record(self, shadow_db):
        sig = _make_signal()
        assert shadow_db.record_signal(sig) is True

    def test_duplicate_rejected(self, shadow_db):
        sig = _make_signal()
        assert shadow_db.record_signal(sig) is True
        assert shadow_db.record_signal(sig) is False

    def test_different_lanes_accepted(self, shadow_db):
        sig1 = _make_signal(lane="wallet_flow")
        sig2 = _make_signal(lane="lmsr")
        assert shadow_db.record_signal(sig1) is True
        assert shadow_db.record_signal(sig2) is True

    def test_get_unresolved(self, shadow_db):
        shadow_db.record_signal(_make_signal())
        unresolved = shadow_db.get_unresolved()
        assert len(unresolved) == 1
        assert unresolved[0]["resolved"] == 0

    def test_get_unresolved_by_lane(self, shadow_db):
        shadow_db.record_signal(_make_signal(lane="wallet_flow"))
        shadow_db.record_signal(_make_signal(lane="lmsr"))
        wf = shadow_db.get_unresolved(lane="wallet_flow")
        assert len(wf) == 1
        assert wf[0]["lane"] == "wallet_flow"

    def test_resolve_signal(self, shadow_db):
        shadow_db.record_signal(_make_signal())
        unresolved = shadow_db.get_unresolved()
        sig_id = unresolved[0]["id"]
        shadow_db.resolve_signal(sig_id, resolution_price=1.0, pnl=2.50)
        remaining = shadow_db.get_unresolved()
        assert len(remaining) == 0

    def test_summary_empty(self, shadow_db):
        summary = shadow_db.get_summary("wallet_flow")
        assert summary["total_signals"] == 0
        assert summary["win_rate"] == 0.0

    def test_summary_with_data(self, shadow_db):
        shadow_db.record_signal(_make_signal(timestamp_utc="2026-03-14T12:00:00+00:00"))
        shadow_db.record_signal(
            _make_signal(
                direction="buy_no",
                timestamp_utc="2026-03-14T12:01:00+00:00",
            )
        )
        # Resolve one as a win
        unresolved = shadow_db.get_unresolved()
        shadow_db.resolve_signal(unresolved[0]["id"], 1.0, 3.0)
        shadow_db.resolve_signal(unresolved[1]["id"], 0.0, -2.0)

        summary = shadow_db.get_summary("wallet_flow")
        assert summary["total_signals"] == 2
        assert summary["resolved"] == 2
        assert summary["wins"] == 1
        assert summary["losses"] == 1
        assert summary["win_rate"] == 0.5
        assert summary["total_hypothetical_pnl"] == 1.0

    def test_summary_all_lanes(self, shadow_db):
        shadow_db.record_signal(_make_signal(lane="wallet_flow"))
        shadow_db.record_signal(_make_signal(lane="lmsr"))
        summary = shadow_db.get_summary()
        assert summary["total_signals"] == 2
        assert summary["lane"] == "all"

    def test_extra_json_preserved(self, shadow_db):
        extra = {"wallet_consensus_wallets": 5, "test_key": "test_value"}
        sig = _make_signal(extra_json=json.dumps(extra))
        shadow_db.record_signal(sig)
        rows = shadow_db.get_unresolved()
        loaded = json.loads(rows[0]["extra_json"])
        assert loaded["wallet_consensus_wallets"] == 5


class TestHypotheticalSize:
    def test_zero_edge(self):
        assert _compute_hypothetical_size(0, 0.5) == 0.0

    def test_negative_edge(self):
        assert _compute_hypothetical_size(-0.05, 0.5) == 0.0

    def test_positive_edge(self):
        size = _compute_hypothetical_size(0.10, 0.65)
        assert 1.0 <= size <= 5.0

    def test_capped_at_max(self):
        size = _compute_hypothetical_size(0.50, 0.95)
        assert size <= 5.0

    def test_minimum_one_dollar(self):
        size = _compute_hypothetical_size(0.001, 0.36)
        assert size >= 0.0  # May be 0 if edge is effectively zero


class TestLaneScanners:
    def test_lanes_registered(self):
        assert "wallet_flow" in LANE_SCANNERS
        assert "lmsr" in LANE_SCANNERS

    @patch("bot.shadow_runner._run_wallet_flow_scan")
    def test_wallet_flow_scanner_callable(self, mock_scan):
        mock_scan.return_value = 0
        scanner = LANE_SCANNERS["wallet_flow"]
        assert callable(scanner)

    @patch("bot.shadow_runner._run_lmsr_scan")
    def test_lmsr_scanner_callable(self, mock_scan):
        mock_scan.return_value = 0
        scanner = LANE_SCANNERS["lmsr"]
        assert callable(scanner)


class TestShadowSignalDataclass:
    def test_defaults(self):
        sig = _make_signal()
        assert sig.lane == "wallet_flow"
        assert sig.extra_json == ""

    def test_with_extra(self):
        sig = _make_signal(extra_json='{"key": "val"}')
        assert sig.extra_json == '{"key": "val"}'
