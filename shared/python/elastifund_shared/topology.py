from __future__ import annotations

ELASTIFUND_INDICES = (
    "elastifund-strategies",
    "elastifund-metrics",
    "elastifund-trades",
    "elastifund-knowledge",
    "elastifund-agents",
)

ELASTIFUND_TOPICS = (
    "strategy.fingerprints",
    "strategy.updates.trading",
    "strategy.updates.non_trading",
    "performance.attestations",
    "market.regime.changes",
    "risk.alerts",
    "knowledge.discoveries",
)

ELASTIFUND_KNOWLEDGE_SHARING_TIERS = (
    {"tier": "public", "shares": ("strategy_categories", "market_regimes")},
    {"tier": "network", "shares": ("aggregated_performance", "signal_direction")},
    {"tier": "trusted", "shares": ("federated_model_updates", "differential_privacy_noise")},
    {"tier": "private", "shares": ("exact_parameters", "entry_exit_logic", "position_sizing")},
)

ELASTIFUND_PRIVATE_BOUNDARY = (
    "Exact model parameters, order entry logic, and account-level sizing never leave the local agent."
)
