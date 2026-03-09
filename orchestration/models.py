"""Dataclasses and enums for standalone resource allocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Mapping

TRADING_AGENT = "trading"
NON_TRADING_AGENT = "non_trading"
VALID_AGENT_NAMES = frozenset({TRADING_AGENT, NON_TRADING_AGENT})
REVENUE_AUDIT_ENGINE = "revenue_audit"
VALID_ENGINE_FAMILIES = frozenset({TRADING_AGENT, REVENUE_AUDIT_ENGINE})


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


class ComplianceStatus(str, Enum):
    """Compliance state for one engine family."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    UNKNOWN = "unknown"

    @classmethod
    def normalize(cls, value: "ComplianceStatus | str | None") -> "ComplianceStatus":
        if isinstance(value, cls):
            return value
        normalized = str(value or cls.UNKNOWN.value).strip().lower().replace("-", "_")
        aliases = {
            "green": cls.PASS,
            "ok": cls.PASS,
            "review": cls.WARNING,
            "warn": cls.WARNING,
            "yellow": cls.WARNING,
            "red": cls.FAIL,
            "blocked": cls.FAIL,
        }
        normalized_value = aliases.get(normalized)
        if normalized_value is not None:
            return normalized_value
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(f"Unsupported compliance status: {value}")


def validate_agent_name(agent_name: str) -> str:
    normalized = str(agent_name).strip().lower()
    if normalized not in VALID_AGENT_NAMES:
        raise ValueError(f"Unsupported agent name: {agent_name}")
    return normalized


def normalize_engine_family_name(engine_family: str | None) -> str:
    normalized = str(engine_family or REVENUE_AUDIT_ENGINE).strip().lower().replace("-", "_")
    aliases = {
        NON_TRADING_AGENT: REVENUE_AUDIT_ENGINE,
        "audit": REVENUE_AUDIT_ENGINE,
        "revenue": REVENUE_AUDIT_ENGINE,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_ENGINE_FAMILIES:
        raise ValueError(f"Unsupported engine family: {engine_family}")
    return normalized


def default_agent_for_engine_family(engine_family: str | None) -> str:
    normalized = normalize_engine_family_name(engine_family)
    if normalized == TRADING_AGENT:
        return TRADING_AGENT
    return NON_TRADING_AGENT


def _clamp_probability(value: float | None, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class EngineCapacityLimits:
    """Optional active-capacity caps for one engine family."""

    budget_usd: float | None = None
    send_quota: int | None = None
    llm_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "budget_usd",
            None if self.budget_usd is None else max(0.0, float(self.budget_usd)),
        )
        object.__setattr__(
            self,
            "send_quota",
            None if self.send_quota is None else max(0, int(self.send_quota)),
        )
        object.__setattr__(
            self,
            "llm_tokens",
            None if self.llm_tokens is None else max(0, int(self.llm_tokens)),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "EngineCapacityLimits":
        data = dict(payload or {})
        return cls(
            budget_usd=data.get("budget_usd"),
            send_quota=data.get("send_quota", data.get("non_trading_send_quota")),
            llm_tokens=data.get("llm_tokens", data.get("non_trading_llm_token_budget")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_usd": self.budget_usd,
            "send_quota": self.send_quota,
            "llm_tokens": self.llm_tokens,
        }


@dataclass(frozen=True)
class EngineFamilyInput:
    """Optional engine-family metrics layered on top of the lane allocator."""

    engine_family: str
    agent_name: str
    expected_net_cash_30d: float | None = None
    confidence: float | None = None
    required_budget: float | None = None
    capacity_limits: EngineCapacityLimits = field(default_factory=EngineCapacityLimits)
    refund_penalty: float = 0.0
    fulfillment_penalty: float = 0.0
    domain_health_penalty: float = 0.0
    compliance_status: ComplianceStatus = ComplianceStatus.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_engine = normalize_engine_family_name(self.engine_family)
        object.__setattr__(self, "engine_family", normalized_engine)
        object.__setattr__(
            self,
            "agent_name",
            validate_agent_name(self.agent_name or default_agent_for_engine_family(normalized_engine)),
        )
        object.__setattr__(
            self,
            "expected_net_cash_30d",
            None
            if self.expected_net_cash_30d is None
            else float(self.expected_net_cash_30d),
        )
        object.__setattr__(self, "confidence", _clamp_probability(self.confidence))
        object.__setattr__(
            self,
            "required_budget",
            None if self.required_budget is None else max(0.0, float(self.required_budget)),
        )
        object.__setattr__(
            self,
            "capacity_limits",
            self.capacity_limits
            if isinstance(self.capacity_limits, EngineCapacityLimits)
            else EngineCapacityLimits.from_mapping(self.capacity_limits),
        )
        object.__setattr__(
            self,
            "refund_penalty",
            _clamp_probability(self.refund_penalty, default=0.0),
        )
        object.__setattr__(
            self,
            "fulfillment_penalty",
            _clamp_probability(self.fulfillment_penalty, default=0.0),
        )
        object.__setattr__(
            self,
            "domain_health_penalty",
            _clamp_probability(self.domain_health_penalty, default=0.0),
        )
        object.__setattr__(
            self,
            "compliance_status",
            ComplianceStatus.normalize(self.compliance_status),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_mapping(
        cls,
        engine_family: str,
        payload: Mapping[str, Any] | None,
    ) -> "EngineFamilyInput":
        data = dict(payload or {})
        normalized_engine = normalize_engine_family_name(
            data.get("engine_family", engine_family)
        )
        return cls(
            engine_family=normalized_engine,
            agent_name=data.get("agent_name", default_agent_for_engine_family(normalized_engine)),
            expected_net_cash_30d=data.get("expected_net_cash_30d"),
            confidence=data.get("confidence"),
            required_budget=data.get("required_budget"),
            capacity_limits=EngineCapacityLimits.from_mapping(data.get("capacity_limits")),
            refund_penalty=data.get("refund_penalty", 0.0),
            fulfillment_penalty=data.get("fulfillment_penalty", 0.0),
            domain_health_penalty=data.get("domain_health_penalty", 0.0),
            compliance_status=data.get("compliance_status"),
            metadata=data.get("metadata") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_family": self.engine_family,
            "agent_name": self.agent_name,
            "expected_net_cash_30d": self.expected_net_cash_30d,
            "confidence": self.confidence,
            "required_budget": self.required_budget,
            "capacity_limits": self.capacity_limits.to_dict(),
            "refund_penalty": self.refund_penalty,
            "fulfillment_penalty": self.fulfillment_penalty,
            "domain_health_penalty": self.domain_health_penalty,
            "compliance_status": self.compliance_status.value,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EngineFamilyRecommendation:
    """Allocator recommendation for one engine family."""

    engine_family: str
    agent_name: str
    advisory_only: bool = True
    eligible: bool = False
    blocked_reason: str | None = None
    compliance_status: ComplianceStatus = ComplianceStatus.UNKNOWN
    expected_net_cash_30d: float | None = None
    confidence: float | None = None
    required_budget: float | None = None
    capacity_limits: EngineCapacityLimits = field(default_factory=EngineCapacityLimits)
    refund_penalty: float = 0.0
    fulfillment_penalty: float = 0.0
    domain_health_penalty: float = 0.0
    penalty_multiplier: float = 1.0
    score: float = 0.0
    target_share: float | None = None
    lane_share: float = 0.0
    lane_budget_ceiling_usd: float = 0.0
    lane_send_quota_ceiling: int = 0
    lane_llm_token_ceiling: int = 0
    recommended_budget_usd: float = 0.0
    recommended_send_quota: int = 0
    recommended_llm_token_budget: int = 0
    explanation: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine_family", normalize_engine_family_name(self.engine_family))
        object.__setattr__(self, "agent_name", validate_agent_name(self.agent_name))
        object.__setattr__(
            self,
            "compliance_status",
            ComplianceStatus.normalize(self.compliance_status),
        )
        object.__setattr__(
            self,
            "expected_net_cash_30d",
            None
            if self.expected_net_cash_30d is None
            else float(self.expected_net_cash_30d),
        )
        object.__setattr__(self, "confidence", _clamp_probability(self.confidence))
        object.__setattr__(
            self,
            "required_budget",
            None if self.required_budget is None else max(0.0, float(self.required_budget)),
        )
        object.__setattr__(
            self,
            "capacity_limits",
            self.capacity_limits
            if isinstance(self.capacity_limits, EngineCapacityLimits)
            else EngineCapacityLimits.from_mapping(self.capacity_limits),
        )
        object.__setattr__(
            self,
            "refund_penalty",
            _clamp_probability(self.refund_penalty, default=0.0),
        )
        object.__setattr__(
            self,
            "fulfillment_penalty",
            _clamp_probability(self.fulfillment_penalty, default=0.0),
        )
        object.__setattr__(
            self,
            "domain_health_penalty",
            _clamp_probability(self.domain_health_penalty, default=0.0),
        )
        object.__setattr__(
            self,
            "penalty_multiplier",
            _clamp_probability(self.penalty_multiplier, default=1.0),
        )
        object.__setattr__(self, "score", max(0.0, float(self.score)))
        object.__setattr__(self, "target_share", _clamp_probability(self.target_share))
        object.__setattr__(self, "lane_share", max(0.0, float(self.lane_share)))
        object.__setattr__(
            self,
            "lane_budget_ceiling_usd",
            max(0.0, float(self.lane_budget_ceiling_usd)),
        )
        object.__setattr__(
            self,
            "lane_send_quota_ceiling",
            max(0, int(self.lane_send_quota_ceiling)),
        )
        object.__setattr__(
            self,
            "lane_llm_token_ceiling",
            max(0, int(self.lane_llm_token_ceiling)),
        )
        object.__setattr__(
            self,
            "recommended_budget_usd",
            max(0.0, float(self.recommended_budget_usd)),
        )
        object.__setattr__(
            self,
            "recommended_send_quota",
            max(0, int(self.recommended_send_quota)),
        )
        object.__setattr__(
            self,
            "recommended_llm_token_budget",
            max(0, int(self.recommended_llm_token_budget)),
        )
        object.__setattr__(self, "explanation", tuple(str(item) for item in self.explanation))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_family": self.engine_family,
            "agent_name": self.agent_name,
            "advisory_only": self.advisory_only,
            "eligible": self.eligible,
            "blocked_reason": self.blocked_reason,
            "compliance_status": self.compliance_status.value,
            "expected_net_cash_30d": self.expected_net_cash_30d,
            "confidence": self.confidence,
            "required_budget": self.required_budget,
            "capacity_limits": self.capacity_limits.to_dict(),
            "refund_penalty": self.refund_penalty,
            "fulfillment_penalty": self.fulfillment_penalty,
            "domain_health_penalty": self.domain_health_penalty,
            "penalty_multiplier": self.penalty_multiplier,
            "score": self.score,
            "target_share": self.target_share,
            "lane_share": self.lane_share,
            "lane_budget_ceiling_usd": self.lane_budget_ceiling_usd,
            "lane_send_quota_ceiling": self.lane_send_quota_ceiling,
            "lane_llm_token_ceiling": self.lane_llm_token_ceiling,
            "recommended_budget_usd": self.recommended_budget_usd,
            "recommended_send_quota": self.recommended_send_quota,
            "recommended_llm_token_budget": self.recommended_llm_token_budget,
            "explanation": list(self.explanation),
            "metadata": dict(self.metadata),
        }


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
