"""
Cross-market arbitrage scanner for Elastifund trading bot.

Provides claim graph normalization, opportunity detection, and execution routing
for arbitrage across Polymarket and Kalshi prediction markets.

Core components:
- claim_graph: Market claim normalization and relationship inference
- opportunity_engine: Arb detection (complement box, underround, neg-risk, etc.)
- execution_router: Order routing and position state management
"""

__version__ = "0.1.0"

from .claim_graph import (
    Claim,
    ParsedPredicate,
    RelationType,
    Relation,
    ClaimGraph,
    normalize_polymarket_claim,
    normalize_kalshi_claim,
    parse_predicate,
    build_relation_candidates,
)

from .opportunity_engine import (
    OrderBook,
    FeeModel,
    ArbTemplate,
    ComplementBoxArb,
    UnderroundArb,
    NegRiskConversionArb,
    ImplicationArb,
    TemporalArb,
    MutualExclusionArb,
    CrossPlatformArb,
    ArbOpportunity,
    evaluate_all_opportunities,
)

from .execution_router import (
    PositionState,
    TIF,
    ExecutionLeg,
    ArbPosition,
    ExecutionRouter,
)

__all__ = [
    # claim_graph
    "Claim",
    "ParsedPredicate",
    "RelationType",
    "Relation",
    "ClaimGraph",
    "normalize_polymarket_claim",
    "normalize_kalshi_claim",
    "parse_predicate",
    "build_relation_candidates",
    # opportunity_engine
    "OrderBook",
    "FeeModel",
    "ArbTemplate",
    "ComplementBoxArb",
    "UnderroundArb",
    "NegRiskConversionArb",
    "ImplicationArb",
    "TemporalArb",
    "MutualExclusionArb",
    "CrossPlatformArb",
    "ArbOpportunity",
    "evaluate_all_opportunities",
    # execution_router
    "PositionState",
    "TIF",
    "ExecutionLeg",
    "ArbPosition",
    "ExecutionRouter",
]
