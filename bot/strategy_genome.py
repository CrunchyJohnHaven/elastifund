#!/usr/bin/env python3
"""
Strategy Genome — Composable Strategy Vectors for Evolutionary Search
=====================================================================
A strategy is no longer a monolithic class. It's a genome: a vector of
composable genes that control signal generation, filtering, sizing, and
timing. Genomes can be mutated, crossed, and selected by a tournament
engine that runs thousands of backtests in parallel.

The key insight: individual strategies are mediocre. Combinations of
signals with optimized filtering and weighting find edges that no single
strategy discovers alone. This is architectural creativity, not brute force.

Gene Categories:
  SIGNAL   — Which signal sources to include and how to weight them
  FILTER   — Entry conditions (time-of-day, VPIN, spread, regime)
  SIZING   — Kelly fraction, position cap, scaling rules
  EXIT     — TTL, stop-loss, take-profit thresholds
  META     — Direction bias, category filter, resolution window

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("JJ.strategy_genome")


# ---------------------------------------------------------------------------
# Gene definitions
# ---------------------------------------------------------------------------

class GeneType(str, Enum):
    SIGNAL = "signal"
    FILTER = "filter"
    SIZING = "sizing"
    EXIT = "exit"
    META = "meta"


@dataclass
class Gene:
    """Single gene in a strategy genome."""
    name: str
    gene_type: GeneType
    value: float
    lower: float
    upper: float
    discrete: bool = False
    description: str = ""

    def clamp(self) -> None:
        self.value = max(self.lower, min(self.upper, self.value))
        if self.discrete:
            self.value = round(self.value)

    def normalized(self) -> float:
        r = self.upper - self.lower
        return (self.value - self.lower) / r if r > 0 else 0.5

    def from_normalized(self, n: float) -> None:
        r = self.upper - self.lower
        self.value = self.lower + n * r
        self.clamp()


@dataclass
class StrategyGenome:
    """
    Complete strategy specification as a composable vector.

    A genome encodes everything needed to generate, filter, size, and
    manage a trading strategy. Two genomes can be crossed to produce
    offspring. Genomes can be mutated. The tournament engine evaluates
    genomes against historical data and ranks them by fitness.
    """
    genome_id: str
    genes: dict[str, Gene] = field(default_factory=dict)
    fitness: float = 0.0
    generation: int = 0
    parent_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Deterministic hash of gene values for deduplication."""
        vals = {k: round(g.value, 6) for k, g in sorted(self.genes.items())}
        return hashlib.sha256(json.dumps(vals).encode()).hexdigest()[:16]

    def to_params(self) -> dict[str, float]:
        return {k: g.value for k, g in self.genes.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "genome_id": self.genome_id,
            "genes": {
                k: {
                    "value": g.value,
                    "type": g.gene_type.value,
                    "range": [g.lower, g.upper],
                }
                for k, g in self.genes.items()
            },
            "fitness": self.fitness,
            "generation": self.generation,
            "parent_ids": self.parent_ids,
            "fingerprint": self.fingerprint,
        }

    def copy(self, new_id: str) -> StrategyGenome:
        new_genes = {}
        for k, g in self.genes.items():
            new_genes[k] = Gene(
                name=g.name, gene_type=g.gene_type,
                value=g.value, lower=g.lower, upper=g.upper,
                discrete=g.discrete, description=g.description,
            )
        return StrategyGenome(
            genome_id=new_id, genes=new_genes,
            generation=self.generation,
            parent_ids=[self.genome_id],
        )


# ---------------------------------------------------------------------------
# Gene catalog: the full search space
# ---------------------------------------------------------------------------

def build_gene_catalog() -> dict[str, Gene]:
    """
    Define the complete search space for strategy genomes.

    This is the architectural creativity: we don't search over arbitrary
    code. We search over MEANINGFUL combinations of proven signal sources,
    filters, and sizing rules. Each gene maps to a real trading decision.
    """
    genes = {}

    # === SIGNAL GENES: which sources to use and how to weight them ===

    # Signal source weights (0 = off, 1 = full weight)
    for source in [
        "mean_reversion", "time_of_day", "book_imbalance",
        "wallet_flow", "informed_flow", "cross_timeframe",
        "vol_regime", "residual_horizon", "ml_scanner",
        "indicator_consensus", "chainlink_basis",
    ]:
        genes[f"w_{source}"] = Gene(
            name=f"w_{source}", gene_type=GeneType.SIGNAL,
            value=0.5, lower=0.0, upper=1.0,
            description=f"Weight for {source} signal source",
        )

    # Minimum signals required to act (consensus threshold)
    genes["min_signals_active"] = Gene(
        name="min_signals_active", gene_type=GeneType.SIGNAL,
        value=2, lower=1, upper=6, discrete=True,
        description="Minimum signal sources that must agree before entry",
    )

    # Signal agreement threshold (what fraction of active signals must agree)
    genes["signal_agreement_pct"] = Gene(
        name="signal_agreement_pct", gene_type=GeneType.SIGNAL,
        value=0.6, lower=0.5, upper=1.0,
        description="Fraction of active signals that must agree on direction",
    )

    # Confidence floor (minimum weighted confidence to enter)
    genes["min_confidence"] = Gene(
        name="min_confidence", gene_type=GeneType.SIGNAL,
        value=0.55, lower=0.50, upper=0.85,
        description="Minimum weighted confidence across active signals",
    )

    # Edge floor (minimum estimated edge to enter)
    genes["min_edge"] = Gene(
        name="min_edge", gene_type=GeneType.SIGNAL,
        value=0.05, lower=0.01, upper=0.20,
        description="Minimum edge estimate to place a trade",
    )

    # === FILTER GENES: when to trade ===

    # Time-of-day filter (hours in ET)
    genes["hour_start_et"] = Gene(
        name="hour_start_et", gene_type=GeneType.FILTER,
        value=3, lower=0, upper=23, discrete=True,
        description="Start of active trading window (ET hour, inclusive)",
    )
    genes["hour_end_et"] = Gene(
        name="hour_end_et", gene_type=GeneType.FILTER,
        value=19, lower=0, upper=23, discrete=True,
        description="End of active trading window (ET hour, inclusive)",
    )

    # VPIN toxicity gate
    genes["max_vpin"] = Gene(
        name="max_vpin", gene_type=GeneType.FILTER,
        value=0.60, lower=0.30, upper=0.90,
        description="Maximum VPIN before blocking entry (toxic flow filter)",
    )

    # Spread filter
    genes["min_spread"] = Gene(
        name="min_spread", gene_type=GeneType.FILTER,
        value=0.02, lower=0.005, upper=0.10,
        description="Minimum bid-ask spread to trade (too tight = no edge)",
    )
    genes["max_spread"] = Gene(
        name="max_spread", gene_type=GeneType.FILTER,
        value=0.15, lower=0.05, upper=0.40,
        description="Maximum bid-ask spread (too wide = stale book)",
    )

    # Volatility regime gate
    genes["vol_regime_gate"] = Gene(
        name="vol_regime_gate", gene_type=GeneType.FILTER,
        value=0.5, lower=0.0, upper=1.0,
        description="0=trade all regimes, 1=only low-vol regimes",
    )

    # Book imbalance gate
    genes["min_book_imbalance"] = Gene(
        name="min_book_imbalance", gene_type=GeneType.FILTER,
        value=0.0, lower=0.0, upper=0.5,
        description="Minimum order book imbalance to act (0=no filter)",
    )

    # === SIZING GENES: how much to risk ===

    genes["kelly_fraction"] = Gene(
        name="kelly_fraction", gene_type=GeneType.SIZING,
        value=0.25, lower=0.05, upper=0.50,
        description="Kelly fraction multiplier for position sizing",
    )
    genes["max_position_usd"] = Gene(
        name="max_position_usd", gene_type=GeneType.SIZING,
        value=5.0, lower=1.0, upper=50.0,
        description="Maximum position size in USD",
    )
    genes["confidence_scaling"] = Gene(
        name="confidence_scaling", gene_type=GeneType.SIZING,
        value=1.0, lower=0.0, upper=2.0,
        description="How much confidence affects position size (0=flat, 2=aggressive)",
    )

    # === EXIT GENES: when to close ===

    genes["ttl_hours"] = Gene(
        name="ttl_hours", gene_type=GeneType.EXIT,
        value=24.0, lower=1.0, upper=168.0,
        description="Maximum hours to hold a position before forced exit",
    )
    genes["stop_loss_pct"] = Gene(
        name="stop_loss_pct", gene_type=GeneType.EXIT,
        value=0.20, lower=0.05, upper=0.50,
        description="Stop loss as fraction of position value",
    )
    genes["take_profit_pct"] = Gene(
        name="take_profit_pct", gene_type=GeneType.EXIT,
        value=0.30, lower=0.10, upper=0.80,
        description="Take profit as fraction of position value",
    )

    # === META GENES: strategic orientation ===

    genes["direction_bias"] = Gene(
        name="direction_bias", gene_type=GeneType.META,
        value=0.0, lower=-1.0, upper=1.0,
        description="Directional bias: -1=NO only, 0=neutral, +1=YES only",
    )
    genes["max_resolution_hours"] = Gene(
        name="max_resolution_hours", gene_type=GeneType.META,
        value=24.0, lower=0.5, upper=720.0,
        description="Maximum hours to resolution (velocity filter)",
    )
    genes["min_entry_price"] = Gene(
        name="min_entry_price", gene_type=GeneType.META,
        value=0.50, lower=0.30, upper=0.90,
        description="Minimum entry price (higher = more conservative)",
    )
    genes["max_entry_price"] = Gene(
        name="max_entry_price", gene_type=GeneType.META,
        value=0.95, lower=0.60, upper=0.99,
        description="Maximum entry price",
    )
    genes["maker_only"] = Gene(
        name="maker_only", gene_type=GeneType.META,
        value=1.0, lower=0.0, upper=1.0, discrete=True,
        description="1=maker orders only, 0=allow taker",
    )

    return genes


# ---------------------------------------------------------------------------
# Genome factory: create genomes from templates
# ---------------------------------------------------------------------------

class GenomeFactory:
    """
    Factory for creating, mutating, and crossing strategy genomes.

    Design philosophy: every genome in the population is a plausible
    trading strategy. We never create degenerate genomes (all weights zero,
    impossible filter combinations). The factory enforces structural validity.
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self._counter = 0
        self._catalog = build_gene_catalog()

    def _next_id(self, prefix: str = "G") -> str:
        self._counter += 1
        return f"{prefix}{self._counter:06d}"

    def random_genome(self) -> StrategyGenome:
        """Create a random valid genome using Latin Hypercube-inspired sampling."""
        gid = self._next_id()
        genes = {}
        for name, template in self._catalog.items():
            g = Gene(
                name=template.name, gene_type=template.gene_type,
                value=self._rng.uniform(template.lower, template.upper),
                lower=template.lower, upper=template.upper,
                discrete=template.discrete, description=template.description,
            )
            g.clamp()
            genes[name] = g

        genome = StrategyGenome(genome_id=gid, genes=genes)
        self._enforce_validity(genome)
        return genome

    def from_params(self, params: dict[str, float], genome_id: Optional[str] = None) -> StrategyGenome:
        """Create a genome from a parameter dictionary."""
        gid = genome_id or self._next_id("P")
        genes = {}
        for name, template in self._catalog.items():
            val = params.get(name, template.value)
            g = Gene(
                name=template.name, gene_type=template.gene_type,
                value=val, lower=template.lower, upper=template.upper,
                discrete=template.discrete, description=template.description,
            )
            g.clamp()
            genes[name] = g
        genome = StrategyGenome(genome_id=gid, genes=genes)
        self._enforce_validity(genome)
        return genome

    def mutate(self, genome: StrategyGenome, sigma: float = 0.10) -> StrategyGenome:
        """Gaussian mutation: perturb each gene by sigma * range."""
        child = genome.copy(self._next_id("M"))
        for name, gene in child.genes.items():
            if self._rng.random() < 0.7:  # 70% chance to mutate each gene
                noise = self._rng.gauss(0, sigma * (gene.upper - gene.lower))
                gene.value += noise
                gene.clamp()
        child.generation = genome.generation + 1
        self._enforce_validity(child)
        return child

    def crossover(self, parent1: StrategyGenome, parent2: StrategyGenome) -> StrategyGenome:
        """Uniform crossover with gene-type-aware blending."""
        child = parent1.copy(self._next_id("X"))
        child.parent_ids = [parent1.genome_id, parent2.genome_id]

        for name in child.genes:
            if name not in parent2.genes:
                continue
            g1 = parent1.genes[name]
            g2 = parent2.genes[name]

            if g1.gene_type == GeneType.SIGNAL:
                # Blend signal weights (arithmetic mean with noise)
                alpha = self._rng.uniform(0.3, 0.7)
                child.genes[name].value = alpha * g1.value + (1 - alpha) * g2.value
            else:
                # Uniform: pick from either parent
                if self._rng.random() < 0.5:
                    child.genes[name].value = g2.value

            child.genes[name].clamp()

        child.generation = max(parent1.generation, parent2.generation) + 1
        self._enforce_validity(child)
        return child

    def focused_mutation(self, genome: StrategyGenome, gene_type: GeneType, sigma: float = 0.15) -> StrategyGenome:
        """Mutate only genes of a specific type (for targeted exploration)."""
        child = genome.copy(self._next_id("F"))
        for name, gene in child.genes.items():
            if gene.gene_type == gene_type and self._rng.random() < 0.8:
                noise = self._rng.gauss(0, sigma * (gene.upper - gene.lower))
                gene.value += noise
                gene.clamp()
        child.generation = genome.generation + 1
        self._enforce_validity(child)
        return child

    def _enforce_validity(self, genome: StrategyGenome) -> None:
        """Ensure structural validity of a genome."""
        genes = genome.genes

        # At least 2 signal sources must be active (weight > 0.1)
        signal_genes = [g for k, g in genes.items() if k.startswith("w_")]
        active = sum(1 for g in signal_genes if g.value > 0.1)
        if active < 2:
            # Activate the two highest-weighted sources
            sorted_signals = sorted(signal_genes, key=lambda g: g.value, reverse=True)
            for g in sorted_signals[:2]:
                g.value = max(g.value, 0.3)

        # hour_start < hour_end (wrap-around not supported for simplicity)
        if genes["hour_start_et"].value >= genes["hour_end_et"].value:
            genes["hour_start_et"].value = 0
            genes["hour_end_et"].value = 23

        # min_spread < max_spread
        if genes["min_spread"].value >= genes["max_spread"].value:
            genes["min_spread"].value = genes["max_spread"].value * 0.3

        # min_entry < max_entry
        if genes["min_entry_price"].value >= genes["max_entry_price"].value:
            genes["min_entry_price"].value = max(genes["min_entry_price"].lower,
                                                  genes["max_entry_price"].value - 0.10)

        # Kelly fraction sanity
        genes["kelly_fraction"].value = max(0.05, min(0.50, genes["kelly_fraction"].value))


# ---------------------------------------------------------------------------
# Preset genomes: known-good starting points
# ---------------------------------------------------------------------------

def preset_btc5_down_bias() -> dict[str, float]:
    """BTC5 DOWN-biased strategy (from March 11 winning session)."""
    return {
        "w_mean_reversion": 0.8, "w_time_of_day": 0.7,
        "w_book_imbalance": 0.6, "w_wallet_flow": 0.3,
        "w_informed_flow": 0.4, "w_cross_timeframe": 0.2,
        "w_vol_regime": 0.5, "w_residual_horizon": 0.3,
        "w_ml_scanner": 0.1, "w_indicator_consensus": 0.2,
        "w_chainlink_basis": 0.4,
        "min_signals_active": 3, "signal_agreement_pct": 0.6,
        "min_confidence": 0.55, "min_edge": 0.05,
        "hour_start_et": 3, "hour_end_et": 6,  # Best hours from data
        "max_vpin": 0.60, "min_spread": 0.02, "max_spread": 0.15,
        "vol_regime_gate": 0.3, "min_book_imbalance": 0.05,
        "kelly_fraction": 0.25, "max_position_usd": 5.0,
        "confidence_scaling": 1.0,
        "ttl_hours": 1.0, "stop_loss_pct": 0.20, "take_profit_pct": 0.30,
        "direction_bias": -0.7,  # DOWN biased
        "max_resolution_hours": 1.0,
        "min_entry_price": 0.50, "max_entry_price": 0.95,
        "maker_only": 1,
    }


def preset_conservative_maker() -> dict[str, float]:
    """Conservative maker strategy for general prediction markets."""
    return {
        "w_mean_reversion": 0.5, "w_time_of_day": 0.6,
        "w_book_imbalance": 0.7, "w_wallet_flow": 0.5,
        "w_informed_flow": 0.6, "w_cross_timeframe": 0.4,
        "w_vol_regime": 0.6, "w_residual_horizon": 0.5,
        "w_ml_scanner": 0.3, "w_indicator_consensus": 0.4,
        "w_chainlink_basis": 0.3,
        "min_signals_active": 3, "signal_agreement_pct": 0.65,
        "min_confidence": 0.58, "min_edge": 0.08,
        "hour_start_et": 0, "hour_end_et": 23,
        "max_vpin": 0.55, "min_spread": 0.02, "max_spread": 0.20,
        "vol_regime_gate": 0.4, "min_book_imbalance": 0.0,
        "kelly_fraction": 0.20, "max_position_usd": 10.0,
        "confidence_scaling": 0.8,
        "ttl_hours": 48.0, "stop_loss_pct": 0.15, "take_profit_pct": 0.40,
        "direction_bias": 0.0,
        "max_resolution_hours": 72.0,
        "min_entry_price": 0.50, "max_entry_price": 0.95,
        "maker_only": 1,
    }


def preset_aggressive_no_bias() -> dict[str, float]:
    """Aggressive NO-biased strategy (NO outperforms YES at 69/99 price levels)."""
    return {
        "w_mean_reversion": 0.4, "w_time_of_day": 0.5,
        "w_book_imbalance": 0.8, "w_wallet_flow": 0.6,
        "w_informed_flow": 0.7, "w_cross_timeframe": 0.5,
        "w_vol_regime": 0.4, "w_residual_horizon": 0.6,
        "w_ml_scanner": 0.4, "w_indicator_consensus": 0.5,
        "w_chainlink_basis": 0.2,
        "min_signals_active": 2, "signal_agreement_pct": 0.55,
        "min_confidence": 0.52, "min_edge": 0.04,
        "hour_start_et": 0, "hour_end_et": 23,
        "max_vpin": 0.70, "min_spread": 0.01, "max_spread": 0.25,
        "vol_regime_gate": 0.2, "min_book_imbalance": 0.0,
        "kelly_fraction": 0.30, "max_position_usd": 10.0,
        "confidence_scaling": 1.5,
        "ttl_hours": 24.0, "stop_loss_pct": 0.25, "take_profit_pct": 0.50,
        "direction_bias": -0.5,  # NO biased
        "max_resolution_hours": 48.0,
        "min_entry_price": 0.50, "max_entry_price": 0.95,
        "maker_only": 1,
    }


PRESETS = {
    "btc5_down_bias": preset_btc5_down_bias,
    "conservative_maker": preset_conservative_maker,
    "aggressive_no_bias": preset_aggressive_no_bias,
}
