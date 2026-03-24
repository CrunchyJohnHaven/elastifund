"""Tests for the experiment registry with hard state transitions."""

import tempfile
from pathlib import Path

import pytest

from src.experiment_registry import (
    ALLOWED_TRANSITIONS,
    ExperimentEntry,
    ExperimentRegistry,
    ExperimentState,
    InvalidTransitionError,
)


def _make_entry(experiment_id: str = "exp_001", **kwargs) -> ExperimentEntry:
    defaults = {
        "experiment_id": experiment_id,
        "hypothesis_id": "hyp_001",
        "family": "btc5",
    }
    defaults.update(kwargs)
    return ExperimentEntry(**defaults)


def _make_registry() -> tuple[ExperimentRegistry, Path]:
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "experiments.db"
    return ExperimentRegistry(db_path), db_path


class TestExperimentState:
    def test_all_states_have_transitions(self):
        for state in ExperimentState:
            assert state in ALLOWED_TRANSITIONS

    def test_retired_is_terminal(self):
        assert ALLOWED_TRANSITIONS[ExperimentState.RETIRED] == set()

    def test_every_state_can_retire(self):
        for state in ExperimentState:
            if state != ExperimentState.RETIRED:
                assert ExperimentState.RETIRED in ALLOWED_TRANSITIONS[state]


class TestExperimentEntry:
    def test_default_state_is_idea(self):
        entry = _make_entry()
        assert entry.state == ExperimentState.IDEA

    def test_valid_forward_transition(self):
        entry = _make_entry()
        entry.transition_to(ExperimentState.SCOPED, reason="Requirements defined")
        assert entry.state == ExperimentState.SCOPED
        assert len(entry.transitions) == 1
        assert entry.transitions[0].from_state == "idea"
        assert entry.transitions[0].to_state == "scoped"

    def test_invalid_skip_transition(self):
        entry = _make_entry()
        with pytest.raises(InvalidTransitionError):
            entry.transition_to(ExperimentState.BACKTESTED)

    def test_cannot_go_backwards(self):
        entry = _make_entry()
        entry.transition_to(ExperimentState.SCOPED)
        with pytest.raises(InvalidTransitionError):
            entry.transition_to(ExperimentState.IDEA)

    def test_retire_from_any_state(self):
        for state in ExperimentState:
            if state == ExperimentState.RETIRED:
                continue
            entry = _make_entry()
            entry.state = state  # force state for testing
            entry.retire("Test retirement")
            assert entry.state == ExperimentState.RETIRED

    def test_retire_already_retired_is_noop(self):
        entry = _make_entry()
        entry.state = ExperimentState.RETIRED
        entry.retire("Double retire")
        assert entry.state == ExperimentState.RETIRED

    def test_full_lifecycle(self):
        entry = _make_entry()
        states = [
            ExperimentState.SCOPED,
            ExperimentState.IMPLEMENTED,
            ExperimentState.BACKTESTED,
            ExperimentState.VALIDATED,
            ExperimentState.SHADOW,
            ExperimentState.PAPER,
            ExperimentState.MICRO_LIVE,
            ExperimentState.LIVE,
            ExperimentState.RETIRED,
        ]
        for target in states:
            entry.transition_to(target, reason=f"Moving to {target.value}")
        assert entry.state == ExperimentState.RETIRED
        assert len(entry.transitions) == len(states)

    def test_can_transition_to_check(self):
        entry = _make_entry()
        assert entry.can_transition_to(ExperimentState.SCOPED) is True
        assert entry.can_transition_to(ExperimentState.LIVE) is False

    def test_to_dict_serialization(self):
        entry = _make_entry()
        entry.transition_to(ExperimentState.SCOPED, reason="test")
        d = entry.to_dict()
        assert d["state"] == "scoped"
        assert len(d["transitions"]) == 1
        assert d["family"] == "btc5"


class TestExperimentRegistry:
    def test_register_and_get(self):
        reg, _ = _make_registry()
        entry = _make_entry()
        reg.register(entry)

        retrieved = reg.get("exp_001")
        assert retrieved is not None
        assert retrieved.experiment_id == "exp_001"
        assert retrieved.state == ExperimentState.IDEA

    def test_get_nonexistent_returns_none(self):
        reg, _ = _make_registry()
        assert reg.get("nope") is None

    def test_transition_via_registry(self):
        reg, _ = _make_registry()
        entry = _make_entry()
        reg.register(entry)

        updated = reg.transition("exp_001", ExperimentState.SCOPED, reason="Ready")
        assert updated.state == ExperimentState.SCOPED

        # Verify persisted
        retrieved = reg.get("exp_001")
        assert retrieved.state == ExperimentState.SCOPED

    def test_transition_invalid_raises(self):
        reg, _ = _make_registry()
        reg.register(_make_entry())

        with pytest.raises(InvalidTransitionError):
            reg.transition("exp_001", ExperimentState.LIVE)

    def test_transition_nonexistent_raises(self):
        reg, _ = _make_registry()
        with pytest.raises(KeyError):
            reg.transition("nope", ExperimentState.SCOPED)

    def test_retire(self):
        reg, _ = _make_registry()
        reg.register(_make_entry())
        result = reg.retire("exp_001", reason="Dead end")
        assert result.state == ExperimentState.RETIRED

    def test_list_by_state(self):
        reg, _ = _make_registry()
        reg.register(_make_entry("exp_001"))
        reg.register(_make_entry("exp_002"))
        reg.transition("exp_002", ExperimentState.SCOPED)

        ideas = reg.list_by_state(ExperimentState.IDEA)
        scoped = reg.list_by_state(ExperimentState.SCOPED)
        assert len(ideas) == 1
        assert len(scoped) == 1

    def test_list_by_family(self):
        reg, _ = _make_registry()
        reg.register(_make_entry("exp_001", family="btc5"))
        reg.register(_make_entry("exp_002", family="btc5"))
        reg.register(_make_entry("exp_003", family="eth5"))

        btc5 = reg.list_by_family("btc5")
        assert len(btc5) == 2

    def test_count_by_state(self):
        reg, _ = _make_registry()
        reg.register(_make_entry("exp_001"))
        reg.register(_make_entry("exp_002"))
        reg.retire("exp_002", reason="test")

        counts = reg.count_by_state()
        assert counts.get("idea", 0) == 1
        assert counts.get("retired", 0) == 1

    def test_family_kill_count(self):
        reg, _ = _make_registry()
        reg.register(_make_entry("exp_001", family="btc5"))
        reg.register(_make_entry("exp_002", family="btc5"))
        reg.retire("exp_001", reason="killed")

        assert reg.family_kill_count("btc5") == 1

    def test_compute_config_hash_deterministic(self):
        config = {"alpha": 0.5, "beta": 1.0, "gamma": [1, 2, 3]}
        h1 = ExperimentRegistry.compute_config_hash(config)
        h2 = ExperimentRegistry.compute_config_hash(config)
        assert h1 == h2
        assert len(h1) == 16

    def test_compute_config_hash_order_independent(self):
        h1 = ExperimentRegistry.compute_config_hash({"a": 1, "b": 2})
        h2 = ExperimentRegistry.compute_config_hash({"b": 2, "a": 1})
        assert h1 == h2
