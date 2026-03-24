"""Tests for bot/learning_loops.py"""
import json
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bot.learning_loops import (
    LearningLoopManager,
    LoopAction,
    LoopResult,
    LoopSpeed,
)


@pytest.fixture
def tmp_state_dir(tmp_path):
    return str(tmp_path / "learning_loops")


@pytest.fixture
def manager(tmp_state_dir):
    return LearningLoopManager(state_dir=tmp_state_dir)


class TestLoopSpeed:
    def test_enum_values(self):
        assert LoopSpeed.FAST.value == "fast"
        assert LoopSpeed.MEDIUM.value == "medium"
        assert LoopSpeed.SLOW.value == "slow"


class TestLearningLoopManager:
    def test_init_creates_db(self, manager, tmp_state_dir):
        db_path = Path(tmp_state_dir) / "loop_history.db"
        assert db_path.exists()

    def test_default_actions_registered(self, manager):
        assert "volatility_scaling" in manager.actions
        assert "platt_recalibration" in manager.actions
        assert "new_feature_family" in manager.actions
        assert len(manager.actions) == 12  # 4 fast + 5 medium + 3 slow
        # Actually count them
        fast = [a for a in manager.actions.values() if a.speed == LoopSpeed.FAST]
        medium = [a for a in manager.actions.values() if a.speed == LoopSpeed.MEDIUM]
        slow = [a for a in manager.actions.values() if a.speed == LoopSpeed.SLOW]
        assert len(fast) == 4
        assert len(medium) == 5
        assert len(slow) == 3

    def test_register_custom_action(self, manager):
        action = LoopAction(
            name="custom_test",
            speed=LoopSpeed.FAST,
            description="Test action",
        )
        manager.register_action(action)
        assert "custom_test" in manager.actions

    def test_get_due_actions_all_due_initially(self, manager):
        """All actions should be due on first run (no last_run set)."""
        due_fast = manager.get_due_actions(LoopSpeed.FAST)
        assert len(due_fast) == 4

    def test_get_due_actions_none_due_after_recent_run(self, manager):
        """Actions run recently should not be due again."""
        now = datetime.now(timezone.utc).isoformat()
        for action in manager.actions.values():
            if action.speed == LoopSpeed.FAST:
                action.last_run = now
        due_fast = manager.get_due_actions(LoopSpeed.FAST)
        assert len(due_fast) == 0

    def test_get_due_actions_respects_enabled_flag(self, manager):
        manager.actions["volatility_scaling"].enabled = False
        due = manager.get_due_actions(LoopSpeed.FAST)
        names = [a.name for a in due]
        assert "volatility_scaling" not in names

    def test_record_run(self, manager):
        result = LoopResult(
            action_name="volatility_scaling",
            speed="fast",
            success=True,
            timestamp=datetime.now(timezone.utc).isoformat(),
            changes_made=["updated vol estimate"],
            notes="Test run",
        )
        manager.record_run(result)

        history = manager.get_run_history("volatility_scaling")
        assert len(history) == 1
        assert history[0]["action_name"] == "volatility_scaling"
        assert history[0]["success"] == 1

    def test_record_run_updates_last_run(self, manager):
        ts = datetime.now(timezone.utc).isoformat()
        result = LoopResult(
            action_name="volatility_scaling",
            speed="fast",
            success=True,
            timestamp=ts,
        )
        manager.record_run(result)
        assert manager.actions["volatility_scaling"].last_run == ts
        assert manager.actions["volatility_scaling"].last_result == "success"

    def test_record_failed_run(self, manager):
        result = LoopResult(
            action_name="platt_recalibration",
            speed="medium",
            success=False,
            timestamp=datetime.now(timezone.utc).isoformat(),
            notes="Failed: connection error",
        )
        manager.record_run(result)
        assert manager.actions["platt_recalibration"].last_result == "failed"

    def test_get_run_history_all(self, manager):
        for name in ["volatility_scaling", "platt_recalibration"]:
            result = LoopResult(
                action_name=name,
                speed="fast",
                success=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            manager.record_run(result)

        history = manager.get_run_history()
        assert len(history) == 2

    def test_run_fast_loop(self, manager):
        results = manager.run_fast_loop()
        assert len(results) == 4
        assert all(r.success for r in results)

    def test_run_fast_loop_with_callable(self, manager):
        mock_fn = MagicMock()
        manager.actions["volatility_scaling"].execute = mock_fn
        results = manager.run_fast_loop()
        mock_fn.assert_called_once()

    def test_run_fast_loop_handles_exception(self, manager):
        def failing_fn():
            raise RuntimeError("boom")

        manager.actions["volatility_scaling"].execute = failing_fn
        results = manager.run_fast_loop()
        vol_result = [r for r in results if r.action_name == "volatility_scaling"][0]
        assert not vol_result.success
        assert "boom" in vol_result.notes

    def test_run_medium_loop(self, manager):
        results = manager.run_medium_loop()
        assert len(results) == 5
        assert all(r.success for r in results)

    def test_check_slow_loop_candidates(self, manager):
        candidates = manager.check_slow_loop_candidates()
        assert len(candidates) == 3
        assert all(c.requires_approval for c in candidates)

    def test_idempotent_fast_loop(self, manager):
        """Running fast loop twice in a row should only execute on first call."""
        results1 = manager.run_fast_loop()
        assert len(results1) == 4
        results2 = manager.run_fast_loop()
        assert len(results2) == 0  # Nothing due anymore

    def test_get_due_after_interval(self, manager):
        """Actions should become due again after the interval passes."""
        old_time = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat()
        for action in manager.actions.values():
            if action.speed == LoopSpeed.FAST:
                action.last_run = old_time
        due = manager.get_due_actions(LoopSpeed.FAST)
        assert len(due) == 4
