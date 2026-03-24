#!/usr/bin/env python3
"""Typed contracts for the structural edge research pipeline.

candidate_spec.v1 — every strategy candidate must be expressed as this before
it can enter simulation or promotion consideration.

simulation_result.v1 — canonical output of every local simulation run.

March 2026 — Elastifund / JJ
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class EdgeMechanism(str, Enum):
    PAIR_COMPLETION = "pair_completion"
    NEG_RISK_BASKET = "neg_risk_basket"
    MONOTONE_THRESHOLD = "monotone_threshold_spread"
    RESOLUTION_SNIPER = "resolution_sniper"
    STALE_QUOTE = "stale_quote"
    WEATHER_SETTLEMENT = "weather_settlement_timing"
    WEATHER_DST = "weather_dst_window"
    QUEUE_DOMINANCE = "queue_dominance"
    SEMANTIC_DUPLICATE = "semantic_duplicate_market"
    CROSS_PLATFORM_NONFUNGIBILITY = "cross_platform_semantic_nonfungibility"
    DIRECTIONAL_BTC5 = "directional_btc5"


class CapitalStyle(str, Enum):
    LOCKED_PAIR = "locked_pair"          # Both sides bought, guaranteed payout
    BASKET_ARB = "basket_arb"            # Multi-leg, guaranteed if taxonomy correct
    DIRECTIONAL = "directional"          # One-sided, outcome risk
    TIME_DECAY = "time_decay"            # Edge from settlement timing
    QUEUE_POSITION = "queue_position"    # Edge from being first in queue


class FillModel(str, Enum):
    MAKER_ONLY = "maker_only"
    MAKER_FIRST_TAKER_HEDGE = "maker_first_taker_hedge"
    TAKER_ONLY = "taker_only"
    QUEUE_AWARE = "queue_aware"


class SimulationTier(str, Enum):
    HISTORICAL_REPLAY = "historical_replay"
    QUEUE_FILL_SIM = "queue_fill_sim"
    COUNTERFACTUAL_STRESS = "counterfactual_stress"


@dataclass
class CandidateSpec:
    """v1 research-to-simulation contract.

    Every strategy candidate must be expressed as this typed spec before
    it can enter simulation, promotion, or live consideration.
    No freeform notes. No untyped ideas. This or nothing.
    """

    # Identity
    strategy_id: str
    version: int = 1
    created_at: float = field(default_factory=time.time)

    # Classification
    market_family: str = ""          # e.g., "crypto_5min", "politics", "weather_temperature"
    edge_mechanism: str = ""         # EdgeMechanism value
    capital_style: str = ""          # CapitalStyle value
    fill_model: str = ""             # FillModel value

    # Requirements
    required_sources: list[str] = field(default_factory=list)   # e.g., ["gamma_api", "clob_book", "binance_price"]
    required_freshness_seconds: int = 300                        # max age of evidence before stale

    # Parameters (the mutation surface)
    parameters: dict[str, Any] = field(default_factory=dict)

    # Kill condition — when to stop testing this candidate
    kill_condition: str = ""         # e.g., "negative_pnl_after_50_fills"
    kill_threshold: dict[str, float] = field(default_factory=dict)  # e.g., {"min_pf": 0.8, "max_dd_pct": 0.3}

    # Gates
    simulation_gate: str = ""       # SimulationTier value required before promotion
    promotion_gate: str = ""        # e.g., "structural_fast_track" or "generic_ladder"

    # Evidence
    evidence_summary: str = ""      # One paragraph: why this edge exists
    evidence_hash: str = ""         # Hash of the evidence bundle that generated this spec

    # Moonshot score components
    estimated_edge_per_trade: float = 0.0
    estimated_turnover_per_day: float = 0.0
    estimated_capital_efficiency: float = 0.0  # 0-1, how much capital is working vs locked
    estimated_persistence_days: int = 0        # how long the edge lasts

    @property
    def moonshot_score(self) -> float:
        """moonshot_score = edge * turnover * capital_efficiency * persistence"""
        return (
            self.estimated_edge_per_trade
            * self.estimated_turnover_per_day
            * self.estimated_capital_efficiency
            * min(self.estimated_persistence_days, 365)  # cap at 1 year
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["moonshot_score"] = self.moonshot_score
        d["schema"] = "candidate_spec.v1"
        return d

    def to_json(self, path: Path | str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CandidateSpec":
        d = {k: v for k, v in d.items() if k not in ("moonshot_score", "schema")}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SimulationResult:
    """v1 canonical output of a local simulation run.

    Every simulation — replay, shadow, stress test — must produce this
    shape. Promotion decisions consume this, not raw logs.
    """

    # Identity
    strategy_id: str
    simulation_tier: str = ""       # SimulationTier value
    scenario_set: str = ""          # e.g., "march_15_replay", "pair_completion_sweep"
    run_id: str = field(default_factory=lambda: f"sim_{int(time.time())}")
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    # Core metrics
    fills_simulated: int = 0
    wins: int = 0
    losses: int = 0
    gross_pnl_usd: float = 0.0
    fees_usd: float = 0.0
    net_pnl_after_fees: float = 0.0
    edge_after_fees_usd: float = 0.0
    opportunity_half_life_ms: float = 0.0
    truth_dependency_status: str = "unknown"
    promotion_fast_track_ready: bool = False
    execution_realism_score: float = 0.0

    # Execution quality
    capital_turnover: float = 0.0           # total traded / average capital
    partial_fill_breach_rate: float = 0.0   # fraction of paired trades where one leg failed
    max_trapped_capital_usd: float = 0.0    # worst-case capital locked in incomplete positions
    avg_fill_time_seconds: float = 0.0
    cancel_replace_count: int = 0

    # Risk
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0

    # Parameters tested
    parameters_tested: dict[str, Any] = field(default_factory=dict)

    # Verdict
    promotion_recommendation: str = "shadow"  # "shadow", "micro_live", "blocked", "killed"
    recommendation_reasons: list[str] = field(default_factory=list)
    truth_regressions: int = 0
    stale_evidence_executions: int = 0

    @property
    def fill_adjusted_expectancy(self) -> float:
        if self.fills_simulated == 0:
            return 0.0
        return self.net_pnl_after_fees / self.fills_simulated

    @property
    def edge_per_trade(self) -> float:
        return self.fill_adjusted_expectancy

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fill_adjusted_expectancy"] = self.fill_adjusted_expectancy
        d["schema"] = "simulation_result.v1"
        return d

    def to_json(self, path: Path | str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SimulationResult":
        d = {k: v for k, v in d.items() if k not in ("fill_adjusted_expectancy", "schema")}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
