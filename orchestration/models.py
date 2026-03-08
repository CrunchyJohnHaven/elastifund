"""Dataclasses and enums for standalone resource allocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

TRADING_AGENT = "trading"
NON_TRADING_AGENT = "non_trading"
VALID_AGENT_NAMES = frozenset({TRADING_AGENT, NON_TRADING_AGENT})


class AllocationMode(str, Enum):
    """Supported allocation algorithms."""

    FIXED_SPLIT = "fixed_split"
    THOMPSON_SAMPLING = "thompson_sampling"
    THREE_LAYER = "three_layer"

    @classmethod
    def normalize(cls, value: "AllocationMode | str | None") -> "AllocationMode":
        if isinstance(value, cls):
            return value
        normalized = str(value or cls.FIXED_SPLIT.value).strip().lower().replace("-", "_")
        if normalized in {"fixed", "fixed_split"}:
            return cls.FIXED_SPLIT
        if normalized in {"thompson", "thompson_sampling", "bandit"}:
            return cls.THOMPSON_SAMPLING
        if normalized in {"three_layer", "layered", "capital_allocator"}:
            return cls.THREE_LAYER
        raise ValueError(f"Unsupported allocation mode: {value}")


class DeliverabilityRisk(str, Enum):
    """Operational risk state for the non-trading lane."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"

    @classmethod
    def normalize(cls, value: "DeliverabilityRisk | str | None") -> "DeliverabilityRisk":
        if isinstance(value, cls):
            return value
        normalized = str(value or cls.GREEN.value).strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unsupported deliverability risk: {value}")


def validate_agent_name(agent_name: str) -> str:
    normalized = str(agent_name).strip().lower()
    if normalized not in VALID_AGENT_NAMES:
        raise ValueError(f"Unsupported agent name: {agent_name}")
    return normalized


@dataclass(frozen=True)
class ArmStats:
    """Bernoulli-style summary used by the Thompson sampler."""

    agent_name: str
    observations: int = 0
    successes: int = 0
    failures: int = 0
    avg_roi: float = 0.0
    volatility: float = 0.0
    latest_roi: float | None = None
    discounted_successes: float = 0.0
    discounted_failures: float = 0.0
    information_ratio: float = 0.0
    confidence_tier: str = "bootstrapping"
    kelly_fraction: float = 0.25
    cusum_score_sigma: float = 0.0
    decay_detected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_name", validate_agent_name(self.agent_name))
        object.__setattr__(self, "volatility", float(self.volatility))
        object.__setattr__(self, "avg_roi", float(self.avg_roi))
        object.__setattr__(
            self,
            "latest_roi",
            None if self.latest_roi is None else float(self.latest_roi),
        )
        object.__setattr__(
            self,
            "discounted_successes",
            float(self.discounted_successes),
        )
        object.__setattr__(
            self,
            "discounted_failures",
            float(self.discounted_failures),
        )
        object.__setattr__(
            self,
            "information_ratio",
            float(self.information_ratio),
        )
        object.__setattr__(self, "kelly_fraction", float(self.kelly_fraction))
        object.__setattr__(
            self,
            "cusum_score_sigma",
            float(self.cusum_score_sigma),
        )
        object.__setattr__(self, "decay_detected", bool(self.decay_detected))


@dataclass(frozen=True)
class PerformanceObservation:
    """Observed ROI for one agent on one reporting date."""

    agent_name: str
    observed_on: date
    roi: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_name", validate_agent_name(self.agent_name))
        object.__setattr__(self, "roi", float(self.roi))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class AllocationDecision:
    """Concrete budget decision written to the allocator DB."""

    decision_date: date
    mode: AllocationMode
    trading_share: float
    non_trading_share: float
    trading_budget_usd: float
    non_trading_send_quota: int
    non_trading_llm_token_budget: int
    deliverability_risk: DeliverabilityRisk
    rationale: str
    cash_reserve_share: float = 0.0
    risk_override_applied: bool = False
    bandit_sample_trading: float | None = None
    bandit_sample_non_trading: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    strategy_documents: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    decision_id: int | None = None
    created_at_ts: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", AllocationMode.normalize(self.mode))
        object.__setattr__(
            self,
            "deliverability_risk",
            DeliverabilityRisk.normalize(self.deliverability_risk),
        )
        object.__setattr__(self, "trading_share", round(float(self.trading_share), 6))
        object.__setattr__(self, "non_trading_share", round(float(self.non_trading_share), 6))
        object.__setattr__(
            self,
            "cash_reserve_share",
            round(max(0.0, min(1.0, float(self.cash_reserve_share))), 6),
        )
        object.__setattr__(self, "trading_budget_usd", float(self.trading_budget_usd))
        object.__setattr__(self, "non_trading_send_quota", int(self.non_trading_send_quota))
        object.__setattr__(
            self,
            "non_trading_llm_token_budget",
            int(self.non_trading_llm_token_budget),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(
            self,
            "strategy_documents",
            tuple(dict(document) for document in self.strategy_documents),
        )
