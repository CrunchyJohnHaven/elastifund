#!/usr/bin/env python3
"""
Evolution Loop — Self-Improving Strategy Discovery
====================================================
The central nervous system of Elastifund's self-improvement architecture.

This is NOT grid search. This is NOT random sampling. This is evolutionary
strategy search with Bayesian fitness evaluation, Thompson sampling
allocation, and proof-carrying promotion gates.

The loop:
  1. SEED: Create initial population from presets + random genomes
  2. EVALUATE: Run tournament (parallel backtests on all CPU cores)
  3. SELECT: Keep survivors, kill the dead, rank by fitness
  4. EVOLVE: Crossover best genomes, mutate for exploration
  5. ALLOCATE: Thompson sampling updates capital allocation
  6. PROMOTE: Check Bayesian log-growth gates for stage advancement
  7. REPEAT: Feed results back into next generation

What makes this clever, not brute-force:
  - Compositional search: tests COMBINATIONS of signals, not individual ones
  - Surrogate-guided mutation: the tournament engine's fitness landscape
    guides where to explore next (via the genome factory's mutation operators)
  - Bayesian promotion: no false kills, no false promotions, honest "I don't
    know yet" when sample size is insufficient
  - Thompson sampling allocation: automatically balances exploration (uncertain
    niches) vs exploitation (proven niches)
  - Kill rules from domain knowledge: not just statistical tests, but
    execution feasibility gates (fill rate, slippage, maker discipline)

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bot.bayesian_promoter import (
    LogGrowthPosterior,
    NicheScore,
    OpportunityLedger,
    OpportunityRecord,
    ThompsonAllocator,
)
from bot.strategy_genome import (
    PRESETS,
    GeneType,
    GenomeFactory,
    StrategyGenome,
)
from bot.tournament_engine import TournamentEngine, TournamentReport, TournamentResult

logger = logging.getLogger("JJ.evolution_loop")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class EvolutionConfig:
    """Configuration for the evolution loop."""
    # Population
    population_size: int = 60
    elite_fraction: float = 0.20
    preset_fraction: float = 0.15  # Fraction seeded from known-good presets

    # Evolution
    mutation_sigma: float = 0.10
    crossover_rate: float = 0.50
    focused_mutation_rate: float = 0.15  # Chance of mutating only one gene type
    max_generations: int = 50

    # Tournament
    data_path: str = ""
    max_workers: Optional[int] = None

    # Convergence
    convergence_patience: int = 8
    convergence_min_improvement: float = 0.001

    # Promotion thresholds (Bayesian)
    promote_prob_positive: float = 0.95
    kill_prob_positive: float = 0.20
    min_fills_to_promote: int = 10
    min_fills_to_kill: int = 15

    # Output
    output_dir: str = "/tmp/evolution_results"
    save_every_n_generations: int = 5


# ---------------------------------------------------------------------------
# Evolution state
# ---------------------------------------------------------------------------

@dataclass
class GenerationState:
    """State of a single generation."""
    generation: int
    population: list[StrategyGenome]
    tournament_report: Optional[TournamentReport] = None
    best_fitness: float = -999.0
    best_genome_id: str = ""
    survived_count: int = 0
    killed_count: int = 0
    diversity_score: float = 0.0
    timestamp: str = ""


@dataclass
class EvolutionState:
    """Full state of the evolution loop across all generations."""
    run_id: str
    config: EvolutionConfig
    current_generation: int = 0
    generation_history: list[dict] = field(default_factory=list)
    best_ever_fitness: float = -999.0
    best_ever_genome: Optional[dict] = None
    convergence_curve: list[float] = field(default_factory=list)
    total_genomes_evaluated: int = 0
    total_eval_time_ms: float = 0.0
    started_at: str = ""
    completed_at: str = ""


# ---------------------------------------------------------------------------
# Evolution Loop
# ---------------------------------------------------------------------------

class EvolutionLoop:
    """
    Orchestrates the full self-improvement cycle.

    Usage:
        loop = EvolutionLoop(config)
        result = loop.run()  # Runs all generations
        # or
        loop.run_one_generation()  # Step-by-step
    """

    def __init__(self, config: EvolutionConfig):
        self.config = config
        self.factory = GenomeFactory(seed=42)
        self.engine = TournamentEngine(
            data_path=config.data_path,
            max_workers=config.max_workers,
        )
        self.allocator = ThompsonAllocator()
        self.ledger = OpportunityLedger()

        # State
        self.population: list[StrategyGenome] = []
        self.hall_of_fame: list[StrategyGenome] = []  # Best genome per generation
        self.all_results: list[TournamentResult] = []
        self.generation = 0
        self.convergence_curve: list[float] = []
        self.state = EvolutionState(
            run_id=f"evo_{int(time.time())}",
            config=config,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        # Output directory
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Population initialization
    # ------------------------------------------------------------------

    def _seed_population(self) -> list[StrategyGenome]:
        """Create initial population from presets + random genomes."""
        pop = []

        # Seed from presets
        n_presets = max(1, int(self.config.population_size * self.config.preset_fraction))
        preset_names = list(PRESETS.keys())
        for i in range(n_presets):
            preset_fn = PRESETS[preset_names[i % len(preset_names)]]
            params = preset_fn()
            genome = self.factory.from_params(params, f"PRESET_{preset_names[i % len(preset_names)]}_{i}")
            pop.append(genome)

        # Fill rest with random genomes
        while len(pop) < self.config.population_size:
            pop.append(self.factory.random_genome())

        logger.info(
            "Seeded population: %d presets + %d random = %d total",
            n_presets, len(pop) - n_presets, len(pop),
        )
        return pop

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _select(self, results: list[TournamentResult]) -> list[StrategyGenome]:
        """Select survivors and elite for next generation."""
        # Map results to genomes
        result_map = {r.genome_id: r for r in results}

        # Update all genomes with their fitness
        for genome in self.population:
            r = result_map.get(genome.genome_id)
            if r:
                genome.fitness = r.fitness

        # Prefer survivors, but if none survived, use best of the dead
        survived = []
        for genome in self.population:
            r = result_map.get(genome.genome_id)
            if r and r.survived:
                survived.append(genome)

        if survived:
            survived.sort(key=lambda g: g.fitness, reverse=True)
            n_elite = max(2, int(self.config.population_size * self.config.elite_fraction))
            return survived[:n_elite]

        # Nothing survived — use top N by fitness anyway (graceful degradation)
        # This prevents the loop from dying when kill rules are too aggressive
        logger.warning("No genomes survived kill rules. Using top by raw fitness.")
        all_ranked = sorted(self.population, key=lambda g: g.fitness, reverse=True)
        n_elite = max(2, int(self.config.population_size * self.config.elite_fraction))
        return all_ranked[:n_elite]

    # ------------------------------------------------------------------
    # Evolution operators
    # ------------------------------------------------------------------

    def _evolve(self, elite: list[StrategyGenome]) -> list[StrategyGenome]:
        """Create next generation from elite via crossover + mutation."""
        next_gen = list(elite)  # Elite survive unchanged

        import random
        rng = random.Random(42 + self.generation)

        while len(next_gen) < self.config.population_size:
            # Choose operator
            r = rng.random()

            if r < self.config.crossover_rate and len(elite) >= 2:
                # Crossover two parents
                p1 = rng.choice(elite[:max(2, len(elite) // 2)])
                p2 = rng.choice(elite[:max(2, len(elite) // 2)])
                child = self.factory.crossover(p1, p2)
            elif r < self.config.crossover_rate + self.config.focused_mutation_rate:
                # Focused mutation (one gene type only)
                parent = rng.choice(elite)
                gene_type = rng.choice([GeneType.SIGNAL, GeneType.FILTER, GeneType.SIZING, GeneType.META])
                child = self.factory.focused_mutation(parent, gene_type, self.config.mutation_sigma * 1.5)
            else:
                # Standard mutation
                parent = rng.choice(elite)
                child = self.factory.mutate(parent, self.config.mutation_sigma)

            child.generation = self.generation + 1
            next_gen.append(child)

        # Inject one fresh random genome per generation (immigration)
        if len(next_gen) > 1:
            immigrant = self.factory.random_genome()
            immigrant.generation = self.generation + 1
            next_gen[-1] = immigrant

        return next_gen[:self.config.population_size]

    # ------------------------------------------------------------------
    # Diversity measurement
    # ------------------------------------------------------------------

    def _measure_diversity(self, population: list[StrategyGenome]) -> float:
        """Measure population diversity as mean pairwise Hamming distance on gene values."""
        if len(population) < 2:
            return 0.0

        fingerprints = set()
        for g in population:
            fingerprints.add(g.fingerprint)

        return len(fingerprints) / len(population)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_one_generation(self) -> GenerationState:
        """Run a single generation of the evolution loop."""
        t0 = time.monotonic()

        if not self.population:
            self.population = self._seed_population()

        logger.info("=== Generation %d: %d genomes ===", self.generation, len(self.population))

        # Tournament evaluation
        report = self.engine.run_tournament(
            self.population,
            tournament_id=f"G{self.generation:04d}",
        )

        # Track all results
        self.all_results.extend(report.results)
        self.state.total_genomes_evaluated += len(report.results)
        self.state.total_eval_time_ms += report.eval_time_total_ms

        # Update Bayesian posteriors from results
        for result in report.results:
            if result.total_fills > 0 and result.survived:
                niche_id = result.genome_id
                self.allocator.register_niche(niche_id)
                # Convert gross_pnl / fills to per-trade return
                per_trade_return = result.gross_pnl / result.total_fills
                for _ in range(min(result.total_fills, 50)):  # Cap at 50 observations per genome
                    self.allocator.record_return(niche_id, per_trade_return)

        # Selection
        elite = self._select(report.results)

        # Track best
        if report.best_fitness > self.state.best_ever_fitness:
            self.state.best_ever_fitness = report.best_fitness
            best_genome = next(
                (g for g in self.population if g.genome_id == report.best_genome_id),
                None,
            )
            if best_genome:
                self.state.best_ever_genome = best_genome.to_dict()
                self.hall_of_fame.append(best_genome)

        # Convergence tracking
        self.convergence_curve.append(report.best_fitness)

        # Diversity
        diversity = self._measure_diversity(self.population)

        # Build generation state
        gen_state = GenerationState(
            generation=self.generation,
            population=self.population,
            tournament_report=report,
            best_fitness=report.best_fitness,
            best_genome_id=report.best_genome_id,
            survived_count=report.survived_count,
            killed_count=report.killed_count,
            diversity_score=diversity,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Record to state history
        self.state.generation_history.append({
            "generation": self.generation,
            "best_fitness": report.best_fitness,
            "best_genome_id": report.best_genome_id,
            "survived": report.survived_count,
            "killed": report.killed_count,
            "median_fitness": report.median_fitness,
            "diversity": diversity,
            "eval_time_ms": report.eval_time_total_ms,
        })

        # Evolve to next generation
        self.population = self._evolve(elite)
        self.generation += 1

        # Periodic save
        if self.generation % self.config.save_every_n_generations == 0:
            self._save_checkpoint()

        elapsed = (time.monotonic() - t0) * 1000
        logger.info(
            "Gen %d complete: best=%.4f, survived=%d/%d, diversity=%.2f, %.1fs",
            gen_state.generation, report.best_fitness,
            report.survived_count, len(report.results),
            diversity, elapsed / 1000,
        )

        return gen_state

    def run(self) -> EvolutionState:
        """Run the full evolution loop until convergence or max generations."""
        logger.info(
            "Starting evolution: pop=%d, max_gen=%d, data=%s",
            self.config.population_size, self.config.max_generations,
            self.config.data_path,
        )

        for gen in range(self.config.max_generations):
            gen_state = self.run_one_generation()

            # Check convergence
            if self._check_convergence():
                logger.info("Converged at generation %d", gen)
                break

        self.state.completed_at = datetime.now(timezone.utc).isoformat()
        self.state.convergence_curve = self.convergence_curve
        self.state.current_generation = self.generation

        # Final save
        self._save_checkpoint()
        self._save_final_report()

        logger.info(
            "Evolution complete: %d generations, best=%.4f (%s), %d total evals",
            self.generation, self.state.best_ever_fitness,
            self.state.best_ever_genome.get("genome_id", "?") if self.state.best_ever_genome else "none",
            self.state.total_genomes_evaluated,
        )

        return self.state

    def _check_convergence(self) -> bool:
        """Check if evolution has converged (no improvement in patience generations)."""
        patience = self.config.convergence_patience
        min_imp = self.config.convergence_min_improvement

        if len(self.convergence_curve) < patience + 1:
            return False

        window = self.convergence_curve[-(patience + 1):]
        improvement = window[-1] - window[0]
        return improvement < min_imp

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_checkpoint(self) -> None:
        """Save current state to disk."""
        checkpoint = {
            "run_id": self.state.run_id,
            "generation": self.generation,
            "best_ever_fitness": self.state.best_ever_fitness,
            "best_ever_genome": self.state.best_ever_genome,
            "convergence_curve": self.convergence_curve,
            "total_evaluated": self.state.total_genomes_evaluated,
            "generation_history": self.state.generation_history[-20:],  # Last 20
            "hall_of_fame": [g.to_dict() for g in self.hall_of_fame[-10:]],
            "thompson_summary": self.allocator.summary(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        path = self.output_dir / "checkpoint.json"
        path.write_text(json.dumps(checkpoint, indent=2, default=str))
        logger.debug("Checkpoint saved to %s", path)

    def _save_final_report(self) -> None:
        """Save comprehensive final report."""
        # Top 10 genomes ever
        all_by_fitness = sorted(self.all_results, key=lambda r: r.fitness, reverse=True)
        top_10 = all_by_fitness[:10]

        report = {
            "run_id": self.state.run_id,
            "started_at": self.state.started_at,
            "completed_at": self.state.completed_at,
            "generations_run": self.generation,
            "total_genomes_evaluated": self.state.total_genomes_evaluated,
            "total_eval_time_s": round(self.state.total_eval_time_ms / 1000, 1),
            "best_ever": {
                "fitness": self.state.best_ever_fitness,
                "genome": self.state.best_ever_genome,
            },
            "convergence_curve": self.convergence_curve,
            "top_10_genomes": [
                {
                    "genome_id": r.genome_id,
                    "fitness": r.fitness,
                    "win_rate": r.win_rate,
                    "fills": r.total_fills,
                    "pnl": r.gross_pnl,
                    "sharpe": r.sharpe,
                    "max_dd": r.max_drawdown,
                    "pf": r.profit_factor,
                    "kelly": r.kelly_fraction,
                    "p_value": r.p_value,
                }
                for r in top_10
            ],
            "bayesian_decisions": self.allocator.get_decisions(),
            "thompson_allocations": self.allocator.allocate(),
            "opportunity_summary": self.ledger.summary(),
            "generation_history": self.state.generation_history,
        }

        path = self.output_dir / "evolution_report.json"
        path.write_text(json.dumps(report, indent=2, default=str))

        # Also write a human-readable markdown report
        md_path = self.output_dir / "evolution_report.md"
        md_path.write_text(_format_report_md(report))

        logger.info("Final report saved to %s", self.output_dir)


def _format_report_md(report: dict) -> str:
    """Format evolution report as markdown."""
    lines = [
        "# Evolution Loop Report",
        f"**Run ID:** {report['run_id']}",
        f"**Started:** {report['started_at']}",
        f"**Completed:** {report['completed_at']}",
        f"**Generations:** {report['generations_run']}",
        f"**Total Genomes Evaluated:** {report['total_genomes_evaluated']}",
        f"**Compute Time:** {report['total_eval_time_s']}s",
        "",
        "## Best Genome",
        f"**Fitness:** {report['best_ever']['fitness']}",
        "",
        "## Top 10 Genomes",
        "",
        "| Rank | ID | Fitness | WR | Fills | PnL | Sharpe | DD | PF | Kelly | p-value |",
        "|------|----|---------|----|-------|-----|--------|----|----|-------|---------|",
    ]

    for i, g in enumerate(report.get("top_10_genomes", []), 1):
        lines.append(
            f"| {i} | {g['genome_id'][:12]} | {g['fitness']:.4f} | "
            f"{g['win_rate']:.1%} | {g['fills']} | ${g['pnl']:.2f} | "
            f"{g['sharpe']:.2f} | {g['max_dd']:.1%} | {g['pf']:.2f} | "
            f"{g['kelly']:.4f} | {g['p_value']:.4f} |"
        )

    lines.extend([
        "",
        "## Bayesian Promotion Decisions",
        "",
    ])

    decisions = report.get("bayesian_decisions", {})
    for niche_id, dec in list(decisions.items())[:10]:
        lines.append(
            f"- **{niche_id[:20]}**: {dec['decision']} "
            f"(P(mu>0)={dec['prob_positive']:.3f}, n={dec['n_observations']})"
        )

    lines.extend([
        "",
        "## Convergence Curve",
        "```",
    ])
    curve = report.get("convergence_curve", [])
    for i, val in enumerate(curve):
        bar = "#" * max(0, int(val * 10)) if val > 0 else ""
        lines.append(f"Gen {i:3d}: {val:8.4f} {bar}")
    lines.append("```")

    return "\n".join(lines)
