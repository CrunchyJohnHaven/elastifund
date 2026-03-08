"""Tests for CLOB 404 quarantine logic.

Verifies quarantine state machine: add, check, expire, escalate, release.
Also verifies SQLite persistence survives restarts.
"""

import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.market_quarantine import MarketQuarantine, QuarantineEntry


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary database path."""
    return tmp_path / "test_quarantine.db"


@pytest.fixture
def quarantine(tmp_db):
    """Create a fresh quarantine manager."""
    return MarketQuarantine(db_path=tmp_db, default_duration_seconds=3600)


class TestQuarantineBasics:
    def test_empty_quarantine_returns_false(self, quarantine):
        assert not quarantine.is_quarantined("some_token_id")

    def test_quarantine_then_check(self, quarantine):
        quarantine.quarantine("token_abc", id_type="token_id", reason="clob_404")
        assert quarantine.is_quarantined("token_abc")

    def test_quarantine_returns_entry(self, quarantine):
        entry = quarantine.quarantine("token_abc", id_type="token_id", reason="clob_404")
        assert isinstance(entry, QuarantineEntry)
        assert entry.identifier == "token_abc"
        assert entry.id_type == "token_id"
        assert entry.reason == "clob_404"
        assert entry.strikes == 1

    def test_unrelated_id_not_quarantined(self, quarantine):
        quarantine.quarantine("token_abc")
        assert not quarantine.is_quarantined("token_def")


class TestQuarantineExpiry:
    def test_expired_entry_returns_false(self, tmp_db):
        q = MarketQuarantine(db_path=tmp_db, default_duration_seconds=1)
        q.quarantine("token_abc")
        assert q.is_quarantined("token_abc")
        # Mock time to simulate expiry
        with patch("bot.market_quarantine.time.time", return_value=time.time() + 3602):
            assert not q.is_quarantined("token_abc")

    def test_cleanup_removes_expired(self, tmp_db):
        q = MarketQuarantine(db_path=tmp_db, default_duration_seconds=1)
        q.quarantine("token_a")
        q.quarantine("token_b")
        with patch("bot.market_quarantine.time.time", return_value=time.time() + 10):
            removed = q.cleanup_expired()
            assert removed == 2


class TestQuarantineEscalation:
    def test_strikes_escalate(self, quarantine):
        entry1 = quarantine.quarantine("token_abc")
        assert entry1.strikes == 1

        entry2 = quarantine.quarantine("token_abc")
        assert entry2.strikes == 2

        entry3 = quarantine.quarantine("token_abc")
        assert entry3.strikes == 3

    def test_escalation_extends_duration(self, quarantine):
        entry1 = quarantine.quarantine("token_abc")
        duration1 = entry1.expires_at - entry1.quarantined_at

        entry2 = quarantine.quarantine("token_abc")
        duration2 = entry2.expires_at - entry2.quarantined_at

        assert duration2 > duration1

    def test_max_escalation_capped(self, tmp_db):
        q = MarketQuarantine(db_path=tmp_db, default_duration_seconds=3600)
        # Strike 30 should cap at 24x
        for _ in range(30):
            entry = q.quarantine("token_abc")
        duration = entry.expires_at - entry.quarantined_at
        # 24 * 3600 = 86400 seconds (24 hours)
        assert duration == pytest.approx(86400, rel=0.01)


class TestQuarantineRelease:
    def test_release_removes_entry(self, quarantine):
        quarantine.quarantine("token_abc")
        assert quarantine.is_quarantined("token_abc")

        removed = quarantine.release("token_abc")
        assert removed is True
        assert not quarantine.is_quarantined("token_abc")

    def test_release_nonexistent_returns_false(self, quarantine):
        removed = quarantine.release("nonexistent")
        assert removed is False


class TestQuarantinePersistence:
    def test_survives_restart(self, tmp_db):
        q1 = MarketQuarantine(db_path=tmp_db, default_duration_seconds=3600)
        q1.quarantine("token_persist", reason="test_persist")

        # Create new instance (simulates restart)
        q2 = MarketQuarantine(db_path=tmp_db, default_duration_seconds=3600)
        assert q2.is_quarantined("token_persist")

    def test_expired_not_loaded_on_restart(self, tmp_db):
        q1 = MarketQuarantine(db_path=tmp_db, default_duration_seconds=1)
        q1.quarantine("token_short")

        with patch("bot.market_quarantine.time.time", return_value=time.time() + 10):
            q2 = MarketQuarantine(db_path=tmp_db, default_duration_seconds=1)
            assert not q2.is_quarantined("token_short")


class TestQuarantineFiltering:
    def test_get_quarantined_by_type(self, quarantine):
        quarantine.quarantine("token_a", id_type="token_id")
        quarantine.quarantine("market_b", id_type="market_id")
        quarantine.quarantine("token_c", id_type="token_id")

        tokens = quarantine.get_quarantined_ids(id_type="token_id")
        assert tokens == {"token_a", "token_c"}

        markets = quarantine.get_quarantined_ids(id_type="market_id")
        assert markets == {"market_b"}

    def test_get_all_quarantined(self, quarantine):
        quarantine.quarantine("id_a")
        quarantine.quarantine("id_b")
        all_ids = quarantine.get_quarantined_ids()
        assert all_ids == {"id_a", "id_b"}


class TestQuarantineStats:
    def test_stats_empty(self, quarantine):
        stats = quarantine.stats()
        assert stats["active_count"] == 0
        assert stats["token_ids"] == 0
        assert stats["market_ids"] == 0

    def test_stats_with_entries(self, quarantine):
        quarantine.quarantine("tok_1", id_type="token_id")
        quarantine.quarantine("tok_2", id_type="token_id")
        quarantine.quarantine("mkt_1", id_type="market_id")

        stats = quarantine.stats()
        assert stats["active_count"] == 3
        assert stats["token_ids"] == 2
        assert stats["market_ids"] == 1
        assert stats["max_strikes"] == 1
