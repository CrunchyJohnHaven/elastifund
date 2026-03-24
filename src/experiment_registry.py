"""Experiment registry with hard state transitions.

Tracks every experiment from initial idea through live deployment and retirement.
State machine enforces that experiments can only move forward through defined
transitions -- no skipping steps, no going backwards without explicit override.

States:
    Idea -> Scoped -> Implemented -> Backtested -> Validated -> Shadow -> Paper -> Micro-live -> Live -> Retired

Each experiment entry stores reproducibility metadata: code commit hash,
data snapshot hash, config hash, random seed, result artifacts, and review notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from .hypothesis_card import HypothesisCard


class ExperimentState(Enum):
    """Hard experiment lifecycle states. Order matters."""
    IDEA = "idea"
    SCOPED = "scoped"
    IMPLEMENTED = "implemented"
    BACKTESTED = "backtested"
    VALIDATED = "validated"
    SHADOW = "shadow"
    PAPER = "paper"
    MICRO_LIVE = "micro_live"
    LIVE = "live"
    RETIRED = "retired"


# Allowed forward transitions. Key: current state, Value: set of reachable next states.
ALLOWED_TRANSITIONS: dict[ExperimentState, set[ExperimentState]] = {
    ExperimentState.IDEA: {ExperimentState.SCOPED, ExperimentState.RETIRED},
    ExperimentState.SCOPED: {ExperimentState.IMPLEMENTED, ExperimentState.RETIRED},
    ExperimentState.IMPLEMENTED: {ExperimentState.BACKTESTED, ExperimentState.RETIRED},
    ExperimentState.BACKTESTED: {ExperimentState.VALIDATED, ExperimentState.RETIRED},
    ExperimentState.VALIDATED: {ExperimentState.SHADOW, ExperimentState.RETIRED},
    ExperimentState.SHADOW: {ExperimentState.PAPER, ExperimentState.RETIRED},
    ExperimentState.PAPER: {ExperimentState.MICRO_LIVE, ExperimentState.RETIRED},
    ExperimentState.MICRO_LIVE: {ExperimentState.LIVE, ExperimentState.RETIRED},
    ExperimentState.LIVE: {ExperimentState.RETIRED},
    ExperimentState.RETIRED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when an experiment attempts an illegal state transition."""


@dataclass
class StateTransition:
    """Record of a single state transition."""
    from_state: str
    to_state: str
    timestamp: float
    reason: str
    reviewer: str


@dataclass
class ExperimentEntry:
    """Complete experiment record with reproducibility metadata."""

    experiment_id: str
    hypothesis_id: str
    state: ExperimentState = ExperimentState.IDEA
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Reproducibility
    code_commit_hash: str = ""
    data_snapshot_hash: str = ""
    config_hash: str = ""
    random_seed: int = 0
    config_json: str = "{}"

    # Results
    result_artifacts: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    # Review
    reviewer: str = ""
    accepted: bool | None = None
    rejection_reason: str = ""
    notes: str = ""

    # Hypothesis card reference
    hypothesis_card: HypothesisCard | None = None

    # Transition history
    transitions: list[StateTransition] = field(default_factory=list)

    # Family (for kill propagation)
    family: str = ""
    tags: list[str] = field(default_factory=list)

    def can_transition_to(self, target: ExperimentState) -> bool:
        """Check if transition is allowed without performing it."""
        return target in ALLOWED_TRANSITIONS.get(self.state, set())

    def transition_to(
        self,
        target: ExperimentState,
        reason: str = "",
        reviewer: str = "system",
    ) -> None:
        """Perform a state transition with validation.

        Raises InvalidTransitionError if the transition is not allowed.
        """
        if not self.can_transition_to(target):
            raise InvalidTransitionError(
                f"Cannot transition from {self.state.value} to {target.value}. "
                f"Allowed: {', '.join(s.value for s in ALLOWED_TRANSITIONS.get(self.state, set()))}"
            )
        transition = StateTransition(
            from_state=self.state.value,
            to_state=target.value,
            timestamp=time.time(),
            reason=reason,
            reviewer=reviewer,
        )
        self.transitions.append(transition)
        self.state = target
        self.updated_at = time.time()

    def retire(self, reason: str, reviewer: str = "system") -> None:
        """Retire from any state (always allowed except from RETIRED)."""
        if self.state == ExperimentState.RETIRED:
            return
        self.transition_to(ExperimentState.RETIRED, reason=reason, reviewer=reviewer)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "code_commit_hash": self.code_commit_hash,
            "data_snapshot_hash": self.data_snapshot_hash,
            "config_hash": self.config_hash,
            "random_seed": self.random_seed,
            "config_json": self.config_json,
            "result_artifacts": self.result_artifacts,
            "metrics": self.metrics,
            "reviewer": self.reviewer,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "notes": self.notes,
            "family": self.family,
            "tags": self.tags,
            "transitions": [asdict(t) for t in self.transitions],
        }
        if self.hypothesis_card:
            d["hypothesis_card"] = self.hypothesis_card.to_dict()
        return d


class ExperimentRegistry:
    """SQLite-backed experiment registry with hard state transitions.

    Stores experiments, enforces state machine transitions, and provides
    query capabilities for experiment management.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                hypothesis_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'idea',
                family TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                data_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_experiments_state
                ON experiments(state);
            CREATE INDEX IF NOT EXISTS idx_experiments_family
                ON experiments(family);
            CREATE INDEX IF NOT EXISTS idx_experiments_hypothesis
                ON experiments(hypothesis_id);

            CREATE TABLE IF NOT EXISTS experiment_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                from_state TEXT NOT NULL,
                to_state TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                reviewer TEXT NOT NULL DEFAULT 'system',
                timestamp REAL NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
            );
            """
        )
        conn.commit()
        conn.close()

    def register(self, entry: ExperimentEntry) -> None:
        """Register a new experiment."""
        conn = self._connect()
        conn.execute(
            "INSERT INTO experiments (experiment_id, hypothesis_id, state, family, created_at, updated_at, data_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.experiment_id,
                entry.hypothesis_id,
                entry.state.value,
                entry.family,
                entry.created_at,
                entry.updated_at,
                json.dumps(entry.to_dict()),
            ),
        )
        conn.commit()
        conn.close()

    def get(self, experiment_id: str) -> ExperimentEntry | None:
        """Retrieve an experiment by ID."""
        conn = self._connect()
        row = conn.execute(
            "SELECT data_json FROM experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._from_json(row["data_json"])

    def transition(
        self,
        experiment_id: str,
        target_state: ExperimentState,
        reason: str = "",
        reviewer: str = "system",
    ) -> ExperimentEntry:
        """Transition an experiment to a new state. Raises InvalidTransitionError on failure."""
        entry = self.get(experiment_id)
        if entry is None:
            raise KeyError(f"Experiment not found: {experiment_id}")

        entry.transition_to(target_state, reason=reason, reviewer=reviewer)
        self._update(entry)

        # Record transition in separate table for fast queries
        conn = self._connect()
        conn.execute(
            "INSERT INTO experiment_transitions (experiment_id, from_state, to_state, reason, reviewer, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                experiment_id,
                entry.transitions[-1].from_state,
                entry.transitions[-1].to_state,
                reason,
                reviewer,
                entry.transitions[-1].timestamp,
            ),
        )
        conn.commit()
        conn.close()

        return entry

    def retire(self, experiment_id: str, reason: str, reviewer: str = "system") -> ExperimentEntry:
        """Retire an experiment from any state."""
        return self.transition(experiment_id, ExperimentState.RETIRED, reason=reason, reviewer=reviewer)

    def list_by_state(self, state: ExperimentState) -> list[ExperimentEntry]:
        """List all experiments in a given state."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT data_json FROM experiments WHERE state = ? ORDER BY updated_at DESC",
            (state.value,),
        ).fetchall()
        conn.close()
        return [self._from_json(r["data_json"]) for r in rows]

    def list_by_family(self, family: str) -> list[ExperimentEntry]:
        """List all experiments in a strategy family."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT data_json FROM experiments WHERE family = ? ORDER BY updated_at DESC",
            (family,),
        ).fetchall()
        conn.close()
        return [self._from_json(r["data_json"]) for r in rows]

    def list_all(self) -> list[ExperimentEntry]:
        """List all experiments."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT data_json FROM experiments ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
        return [self._from_json(r["data_json"]) for r in rows]

    def count_by_state(self) -> dict[str, int]:
        """Count experiments grouped by state."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT state, COUNT(*) as cnt FROM experiments GROUP BY state"
        ).fetchall()
        conn.close()
        return {r["state"]: r["cnt"] for r in rows}

    def family_kill_count(self, family: str) -> int:
        """Count retired experiments in a family (for kill propagation)."""
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM experiments WHERE family = ? AND state = 'retired'",
            (family,),
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0

    def _update(self, entry: ExperimentEntry) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE experiments SET state = ?, family = ?, updated_at = ?, data_json = ? "
            "WHERE experiment_id = ?",
            (
                entry.state.value,
                entry.family,
                entry.updated_at,
                json.dumps(entry.to_dict()),
                entry.experiment_id,
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _from_json(data_json: str) -> ExperimentEntry:
        d = json.loads(data_json)
        transitions = [
            StateTransition(**t) for t in d.pop("transitions", [])
        ]
        d.pop("hypothesis_card", None)
        state_val = d.pop("state", "idea")
        result_artifacts = d.pop("result_artifacts", [])
        metrics = d.pop("metrics", {})
        tags = d.pop("tags", [])

        entry = ExperimentEntry(
            experiment_id=d["experiment_id"],
            hypothesis_id=d["hypothesis_id"],
            state=ExperimentState(state_val),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            code_commit_hash=d.get("code_commit_hash", ""),
            data_snapshot_hash=d.get("data_snapshot_hash", ""),
            config_hash=d.get("config_hash", ""),
            random_seed=d.get("random_seed", 0),
            config_json=d.get("config_json", "{}"),
            result_artifacts=result_artifacts,
            metrics=metrics,
            reviewer=d.get("reviewer", ""),
            accepted=d.get("accepted"),
            rejection_reason=d.get("rejection_reason", ""),
            notes=d.get("notes", ""),
            family=d.get("family", ""),
            tags=tags,
            transitions=transitions,
        )
        return entry

    @staticmethod
    def compute_config_hash(config: dict[str, Any]) -> str:
        """Deterministic hash of a config dict for reproducibility tracking."""
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]
