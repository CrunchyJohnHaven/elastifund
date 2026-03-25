"""
Tests for scripts/btc5_mutation_tracker.py

Covers:
- promote_mutation creates a valid record
- record_cap_breach sets auto_revert_triggered
- record_up_order_attempt sets auto_revert_triggered
- check_auto_revert_needed returns True when cap_breach_count > 0
- check_auto_revert_needed returns False for a clean record
- win_rate after 5W/5L is 0.5
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Make the scripts package importable regardless of working directory
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import btc5_mutation_tracker as tracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_state(tmp_path, monkeypatch):
    """Point the tracker's STATE_FILE at a temp path for isolation."""
    state_file = tmp_path / "btc5_active_mutation.json"
    monkeypatch.setattr(tracker, "STATE_FILE", state_file)
    return state_file


# ---------------------------------------------------------------------------
# Test: promote_mutation creates a valid record
# ---------------------------------------------------------------------------

def test_promote_mutation_creates_valid_record(tmp_state):
    config_snapshot = {"BTC5_DOWN_MAX_BUY_PRICE": "0.48", "BTC5_UP_ENABLED": "false"}
    config_hash = tracker.hash_config(config_snapshot)

    mutation = tracker.promote_mutation(
        mutation_id="test_v1",
        config_hash=config_hash,
        config_snapshot=config_snapshot,
        notes="unit test",
    )

    assert mutation["mutation_id"] == "test_v1"
    assert mutation["config_hash"] == config_hash
    assert mutation["config_snapshot"] == config_snapshot
    assert mutation["verification_status"] == "pending"
    assert mutation["fills_since_promotion"] == 0
    assert mutation["wins_since_promotion"] == 0
    assert mutation["losses_since_promotion"] == 0
    assert mutation["cap_breach_count"] == 0
    assert mutation["up_order_attempt_count"] == 0
    assert mutation["config_hash_mismatch_count"] == 0
    assert mutation["auto_revert_triggered"] is False
    assert mutation["auto_revert_reason"] is None
    assert mutation["auto_revert_at"] is None
    assert mutation["notes"] == "unit test"

    # Persisted correctly
    assert tmp_state.exists()
    on_disk = json.loads(tmp_state.read_text())
    assert on_disk["mutation_id"] == "test_v1"


# ---------------------------------------------------------------------------
# Test: record_cap_breach sets auto_revert_triggered
# ---------------------------------------------------------------------------

def test_record_cap_breach_sets_auto_revert(tmp_state):
    tracker.promote_mutation("breach_test", "abc123", {})
    result = tracker.record_cap_breach()

    assert result["auto_revert_triggered"] is True
    assert result["cap_breach_count"] == 1
    assert result["verification_status"] == "reverted"
    assert result["auto_revert_reason"] is not None
    assert "cap_breach" in result["auto_revert_reason"]

    # Persisted on disk
    on_disk = json.loads(tmp_state.read_text())
    assert on_disk["auto_revert_triggered"] is True
    assert on_disk["cap_breach_count"] == 1


# ---------------------------------------------------------------------------
# Test: record_up_order_attempt sets auto_revert_triggered
# ---------------------------------------------------------------------------

def test_record_up_order_attempt_sets_auto_revert(tmp_state):
    tracker.promote_mutation("up_test", "def456", {})
    result = tracker.record_up_order_attempt()

    assert result["auto_revert_triggered"] is True
    assert result["up_order_attempt_count"] == 1
    assert result["verification_status"] == "reverted"
    assert result["auto_revert_reason"] is not None
    assert "up_order_attempt" in result["auto_revert_reason"]

    on_disk = json.loads(tmp_state.read_text())
    assert on_disk["auto_revert_triggered"] is True
    assert on_disk["up_order_attempt_count"] == 1


# ---------------------------------------------------------------------------
# Test: check_auto_revert_needed returns True when cap_breach_count > 0
# ---------------------------------------------------------------------------

def test_check_auto_revert_needed_true_on_cap_breach():
    mutation = {
        "cap_breach_count": 1,
        "up_order_attempt_count": 0,
        "config_hash_mismatch_count": 0,
        "fills_since_promotion": 0,
        "wins_since_promotion": 0,
    }
    should_revert, reason = tracker.check_auto_revert_needed(mutation)
    assert should_revert is True
    assert "cap_breach" in reason


# ---------------------------------------------------------------------------
# Test: check_auto_revert_needed returns False for a clean record
# ---------------------------------------------------------------------------

def test_check_auto_revert_needed_false_for_clean_record():
    mutation = {
        "cap_breach_count": 0,
        "up_order_attempt_count": 0,
        "config_hash_mismatch_count": 0,
        "fills_since_promotion": 10,
        "wins_since_promotion": 6,
    }
    should_revert, reason = tracker.check_auto_revert_needed(mutation)
    assert should_revert is False
    assert reason == ""


# ---------------------------------------------------------------------------
# Test: win_rate after 5W/5L is 0.5
# ---------------------------------------------------------------------------

def test_win_rate_after_five_wins_five_losses(tmp_state):
    tracker.promote_mutation("wr_test", "aaa", {})

    for _ in range(5):
        tracker.record_fill(won=True)
    for _ in range(5):
        tracker.record_fill(won=False)

    mutation = tracker.load_active_mutation()
    assert mutation is not None

    fills = mutation["fills_since_promotion"]
    wins = mutation["wins_since_promotion"]
    losses = mutation["losses_since_promotion"]

    assert fills == 10
    assert wins == 5
    assert losses == 5
    assert wins / fills == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test: check_auto_revert_needed with low win rate after sufficient fills
# ---------------------------------------------------------------------------

def test_check_auto_revert_needed_true_on_low_win_rate():
    mutation = {
        "cap_breach_count": 0,
        "up_order_attempt_count": 0,
        "config_hash_mismatch_count": 0,
        "fills_since_promotion": 20,
        "wins_since_promotion": 5,  # 25% win rate — below 30% threshold
    }
    should_revert, reason = tracker.check_auto_revert_needed(mutation)
    assert should_revert is True
    assert "win_rate" in reason


# ---------------------------------------------------------------------------
# Test: check_auto_revert_needed with high mismatch count
# ---------------------------------------------------------------------------

def test_check_auto_revert_needed_true_on_hash_mismatch():
    mutation = {
        "cap_breach_count": 0,
        "up_order_attempt_count": 0,
        "config_hash_mismatch_count": 4,  # above limit of 3
        "fills_since_promotion": 0,
        "wins_since_promotion": 0,
    }
    should_revert, reason = tracker.check_auto_revert_needed(mutation)
    assert should_revert is True
    assert "config_hash_mismatch" in reason
