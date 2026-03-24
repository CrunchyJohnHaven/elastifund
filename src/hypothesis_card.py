"""Hypothesis card: the canonical record for every trading strategy under evaluation.

Every strategy entering the pipeline gets a hypothesis card. The card captures
the full chain of reasoning from economic mechanism through live validation,
and computes the Validated Net Edge scorecard that determines whether the
strategy is worth deploying capital to.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
import json
import time


class ProofStatus(Enum):
    """Status of a single proof dimension."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass
class ValidatedNetEdge:
    """Scorecard that determines whether a strategy is worth deploying.

    Validated Net Edge = lower_confidence_bound_gross_alpha
                       - all_in_execution_cost
                       - financing_funding
                       - model_error_buffer
                       - tail_risk_penalty

    A strategy is only interesting if this number is positive.
    """

    lower_confidence_bound_gross_alpha: float = 0.0
    all_in_execution_cost: float = 0.0
    financing_funding: float = 0.0
    model_error_buffer: float = 0.0
    tail_risk_penalty: float = 0.0

    @property
    def net_edge(self) -> float:
        return (
            self.lower_confidence_bound_gross_alpha
            - self.all_in_execution_cost
            - self.financing_funding
            - self.model_error_buffer
            - self.tail_risk_penalty
        )

    @property
    def is_interesting(self) -> bool:
        return self.net_edge > 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["net_edge"] = self.net_edge
        d["is_interesting"] = self.is_interesting
        return d


@dataclass
class HypothesisCard:
    """Complete hypothesis card for a trading strategy.

    Required fields capture the full chain of reasoning: what edge exists,
    who is paying you, how you exploit it, what could go wrong, and how
    you validate each proof dimension.
    """

    # Identity
    hypothesis_name: str
    hypothesis_id: str = ""
    family: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Scope
    market_and_universe: str = ""
    horizon: str = ""

    # Economic mechanism -- the core question: who is paying you and why
    economic_mechanism: str = ""

    # Signal and execution
    signal_definition: str = ""
    execution_style: str = ""
    expected_costs: str = ""

    # Risk
    risk_exposures: str = ""
    failure_modes: list[str] = field(default_factory=list)

    # Validation plan
    validation_plan: str = ""
    retirement_criteria: str = ""

    # 5-proof status
    mechanism_proof_status: ProofStatus = ProofStatus.NOT_STARTED
    mechanism_proof_notes: str = ""
    data_proof_status: ProofStatus = ProofStatus.NOT_STARTED
    data_proof_notes: str = ""
    statistical_proof_status: ProofStatus = ProofStatus.NOT_STARTED
    statistical_proof_notes: str = ""
    execution_proof_status: ProofStatus = ProofStatus.NOT_STARTED
    execution_proof_notes: str = ""
    live_proof_status: ProofStatus = ProofStatus.NOT_STARTED
    live_proof_notes: str = ""

    # Validated Net Edge scorecard
    validated_net_edge: ValidatedNetEdge = field(default_factory=ValidatedNetEdge)

    # Metadata
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def proof_statuses(self) -> dict[str, ProofStatus]:
        """Return all five proof statuses as a dict."""
        return {
            "mechanism": self.mechanism_proof_status,
            "data": self.data_proof_status,
            "statistical": self.statistical_proof_status,
            "execution": self.execution_proof_status,
            "live": self.live_proof_status,
        }

    def all_proofs_passed(self) -> bool:
        """True only if every proof dimension is PASSED."""
        return all(s == ProofStatus.PASSED for s in self.proof_statuses().values())

    def any_proof_failed(self) -> bool:
        """True if any proof dimension has FAILED."""
        return any(s == ProofStatus.FAILED for s in self.proof_statuses().values())

    def passed_proof_count(self) -> int:
        return sum(1 for s in self.proof_statuses().values() if s == ProofStatus.PASSED)

    def update_proof(self, proof_name: str, status: ProofStatus, notes: str = "") -> None:
        """Update a proof dimension status and notes."""
        valid = {"mechanism", "data", "statistical", "execution", "live"}
        if proof_name not in valid:
            raise ValueError(f"Unknown proof: {proof_name}. Must be one of {valid}")
        setattr(self, f"{proof_name}_proof_status", status)
        if notes:
            setattr(self, f"{proof_name}_proof_notes", notes)
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON/SQLite storage."""
        d = asdict(self)
        # Convert enums to their string values
        for key in list(d.keys()):
            if isinstance(d[key], ProofStatus):
                d[key] = d[key].value
        # Fix nested enum in validated_net_edge -- asdict handles dataclasses
        d["validated_net_edge"] = self.validated_net_edge.to_dict()
        # Convert proof statuses
        for proof in ("mechanism", "data", "statistical", "execution", "live"):
            status_key = f"{proof}_proof_status"
            d[status_key] = getattr(self, status_key).value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HypothesisCard:
        """Deserialize from dict."""
        d = dict(d)  # shallow copy
        # Restore proof status enums
        for proof in ("mechanism", "data", "statistical", "execution", "live"):
            key = f"{proof}_proof_status"
            if key in d and isinstance(d[key], str):
                d[key] = ProofStatus(d[key])
        # Restore ValidatedNetEdge
        vne = d.get("validated_net_edge")
        if isinstance(vne, dict):
            # Remove computed properties
            vne.pop("net_edge", None)
            vne.pop("is_interesting", None)
            d["validated_net_edge"] = ValidatedNetEdge(**vne)
        return cls(**d)
