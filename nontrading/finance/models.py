"""Dataclasses used by the finance control plane."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _round_money(value: float) -> float:
    return round(float(value or 0.0), 6)


def _positive(value: float) -> float:
    return max(0.0, _round_money(value))


@dataclass(frozen=True)
class FinanceAccount:
    account_key: str = ""
    name: str = ""
    account_type: str = "cash"
    institution: str = ""
    currency: str = "USD"
    balance_usd: float = 0.0
    current_balance_usd: float | None = None
    available_cash_usd: float = 0.0
    liquidity_tier: str = "liquid"
    source: str = "manual"
    source_type: str = "manual"
    source_ref: str = ""
    external_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        normalized_key = self.account_key or self.external_id or self.name.lower().replace(" ", "-")
        object.__setattr__(self, "account_key", normalized_key)
        object.__setattr__(self, "external_id", self.external_id or normalized_key)
        object.__setattr__(self, "balance_usd", _round_money(self.balance_usd))
        current_balance = self.current_balance_usd
        if current_balance is None:
            current_balance = self.balance_usd
        if self.balance_usd == 0.0 and current_balance is not None:
            object.__setattr__(self, "balance_usd", _round_money(current_balance))
        object.__setattr__(self, "current_balance_usd", _round_money(current_balance))
        object.__setattr__(self, "available_cash_usd", _round_money(self.available_cash_usd))
        object.__setattr__(self, "source", self.source or self.source_type)


@dataclass(frozen=True)
class FinanceTransaction:
    transaction_key: str = ""
    account_key: str = ""
    posted_at: str = ""
    merchant: str = ""
    description: str = ""
    amount_usd: float = 0.0
    category: str = ""
    source: str = "manual"
    transaction_id: str = ""
    direction: str = "withdrawal"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        normalized_key = self.transaction_key or self.transaction_id or f"{self.posted_at}:{self.merchant}:{self.amount_usd}"
        object.__setattr__(self, "transaction_key", normalized_key)
        object.__setattr__(self, "transaction_id", self.transaction_id or normalized_key)
        object.__setattr__(self, "amount_usd", _round_money(self.amount_usd))
        if self.direction == "withdrawal" and self.amount_usd > 0:
            object.__setattr__(self, "direction", "deposit")


@dataclass(frozen=True)
class FinancePosition:
    position_key: str = ""
    account_key: str = ""
    symbol: str = ""
    name: str = ""
    asset_type: str = "security"
    asset_class: str = ""
    quantity: float = 0.0
    cost_basis_usd: float = 0.0
    market_value_usd: float = 0.0
    deployable_cash_usd: float = 0.0
    source: str = "manual"
    source_type: str = "manual"
    source_ref: str = ""
    external_id: str = ""
    liquidity_tier: str = "liquid"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        normalized_key = self.position_key or self.external_id or f"{self.account_key}:{self.symbol or self.name}"
        object.__setattr__(self, "position_key", normalized_key)
        object.__setattr__(self, "external_id", self.external_id or normalized_key)
        if not self.asset_class:
            object.__setattr__(self, "asset_class", self.asset_type)
        if self.asset_type == "security" and self.asset_class:
            object.__setattr__(self, "asset_type", self.asset_class)
        object.__setattr__(self, "quantity", float(self.quantity or 0.0))
        object.__setattr__(self, "cost_basis_usd", _round_money(self.cost_basis_usd))
        object.__setattr__(self, "market_value_usd", _round_money(self.market_value_usd))
        object.__setattr__(self, "deployable_cash_usd", _round_money(self.deployable_cash_usd))
        object.__setattr__(self, "source", self.source or self.source_type)


@dataclass(frozen=True)
class FinanceRecurringCommitment:
    commitment_key: str
    vendor: str
    category: str
    amount_usd: float
    monthly_cost_usd: float
    cadence: str = "monthly"
    essential: bool = False
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount_usd", _positive(self.amount_usd))
        object.__setattr__(self, "monthly_cost_usd", _positive(self.monthly_cost_usd))


@dataclass(frozen=True)
class FinanceSubscription:
    subscription_key: str
    vendor: str
    product_name: str
    category: str
    monthly_cost_usd: float
    billing_cycle: str = "monthly"
    usage_frequency: str = "unknown"
    status: str = "active"
    duplicate_group: str = ""
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "monthly_cost_usd", _positive(self.monthly_cost_usd))


@dataclass(frozen=True)
class FinanceExperiment:
    experiment_key: str
    name: str
    bucket: str = "buy_tool_or_data"
    status: str = "candidate"
    budget_usd: float = 0.0
    monthly_budget_usd: float = 0.0
    expected_net_value_30d: float = 0.0
    expected_information_gain_30d: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_usd", _positive(self.budget_usd))
        object.__setattr__(self, "monthly_budget_usd", _positive(self.monthly_budget_usd))
        object.__setattr__(self, "expected_net_value_30d", _round_money(self.expected_net_value_30d))
        object.__setattr__(self, "expected_information_gain_30d", _round_money(self.expected_information_gain_30d))


@dataclass(frozen=True)
class FinanceAction:
    action_key: str
    action_type: str
    bucket: str
    title: str
    status: str = "queued"
    amount_usd: float = 0.0
    monthly_commitment_usd: float = 0.0
    priority_score: float = 0.0
    destination: str = ""
    vendor: str = ""
    mode_requested: str = ""
    reason: str = ""
    rollback: str = ""
    idempotency_key: str = ""
    cooldown_until: str | None = None
    requires_whitelist: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    executed_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount_usd", _positive(self.amount_usd))
        object.__setattr__(self, "monthly_commitment_usd", _positive(self.monthly_commitment_usd))
        object.__setattr__(self, "priority_score", float(self.priority_score or 0.0))
        object.__setattr__(self, "requires_whitelist", bool(self.requires_whitelist))


@dataclass(frozen=True)
class AuditFinding:
    finding_id: str
    kind: str
    vendor: str
    category: str
    monthly_cost_usd: float
    confidence: float
    recommended_action: str
    estimated_savings_usd: float
    rollback: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "monthly_cost_usd", _positive(self.monthly_cost_usd))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        object.__setattr__(self, "estimated_savings_usd", _positive(self.estimated_savings_usd))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AllocationBucket:
    bucket: str
    expected_net_value_30d: float
    expected_information_gain_30d: float
    score: float
    recommended_amount_usd: float
    monthly_commitment_usd: float
    rationale: str
    action_type: str = ""
    destination: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "expected_net_value_30d", _round_money(self.expected_net_value_30d))
        object.__setattr__(self, "expected_information_gain_30d", _round_money(self.expected_information_gain_30d))
        object.__setattr__(self, "score", _round_money(self.score))
        object.__setattr__(self, "recommended_amount_usd", _positive(self.recommended_amount_usd))
        object.__setattr__(self, "monthly_commitment_usd", _positive(self.monthly_commitment_usd))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionResult:
    action_key: str
    status: str
    mode: str
    reason: str
    performed: bool
    idempotency_key: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
