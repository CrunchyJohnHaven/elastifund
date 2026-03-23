#!/usr/bin/env python3
"""
Run Evolution — Launch the Self-Improving Strategy Discovery Loop
================================================================
Entry point for running the full evolution pipeline on local hardware.

Usage:
    python scripts/run_evolution.py                    # Full run (50 generations)
    python scripts/run_evolution.py --generations 10   # Quick test
    python scripts/run_evolution.py --pop 100          # Larger population
    python scripts/run_evolution.py --synthetic         # Use synthetic data

This script:
  1. Prepares tournament data (historical markets + signal features)
  2. Initializes the Evolution Loop with Bayesian promotion gates
  3. Runs N generations of parallel backtesting + selection + mutation
  4. Outputs ranked genomes with promote/hold/kill decisions
  5. Saves the best genomes for deployment consideration

March 2026 — Elastifund / JJ
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from multiprocessing import cpu_count
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bot.evolution_loop import EvolutionConfig, EvolutionLoop
from scripts.prepare_tournament_data import prepare_tournament_data

logger = logging.getLogger("JJ.run_evolution")


def main():
    parser = argparse.ArgumentParser(description="Run evolutionary strategy search")
    parser.add_argument("--generations", type=int, default=50, help="Max generations (default: 50)")
    parser.add_argument("--pop", type=int, default=60, help="Population size (default: 60)")
    parser.add_argument("--workers", type=int, default=None, help="CPU workers (default: all-1)")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic data")
    parser.add_argument("--data", type=str, default=None, help="Path to tournament data JSON")
    parser.add_argument("--output", type=str, default="/tmp/evolution_results", help="Output directory")
    parser.add_argument("--sigma", type=float, default=0.10, help="Mutation sigma (default: 0.10)")
    parser.add_argument("--elite", type=float, default=0.20, help="Elite fraction (default: 0.20)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(args.output) / "evolution.log", mode="w"),
        ] if Path(args.output).exists() else [logging.StreamHandler(sys.stdout)],
    )

    # Prepare output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cores = args.workers or max(1, cpu_count() - 1)
    logger.info("=" * 70)
    logger.info("ELASTIFUND EVOLUTION ENGINE")
    logger.info("=" * 70)
    logger.info("Population: %d | Generations: %d | Workers: %d/%d cores",
                args.pop, args.generations, cores, cpu_count())
    logger.info("Mutation sigma: %.2f | Elite fraction: %.0f%%",
                args.sigma, args.elite * 100)
    logger.info("Output: %s", args.output)

    # Step 1: Prepare data
    t0 = time.monotonic()
    if args.data:
        data_path = args.data
        logger.info("Using provided data: %s", data_path)
    else:
        logger.info("Preparing tournament data...")
        data_path = prepare_tournament_data(
            output_path=str(output_dir / "tournament_data.json"),
        )
    data_time = time.monotonic() - t0
    logger.info("Data prepared in %.1fs: %s", data_time, data_path)

    # Verify data
    with open(data_path) as f:
        data = json.load(f)
    logger.info("Tournament data: %d markets", len(data))

    if len(data) < 10:
        logger.error("Insufficient data (%d markets). Need at least 10.", len(data))
        sys.exit(1)

    # Step 2: Configure evolution
    config = EvolutionConfig(
        population_size=args.pop,
        elite_fraction=args.elite,
        mutation_sigma=args.sigma,
        max_generations=args.generations,
        data_path=data_path,
        max_workers=cores,
        output_dir=str(output_dir),
    )

    # Step 3: Run evolution
    logger.info("-" * 70)
    logger.info("STARTING EVOLUTION")
    logger.info("-" * 70)

    loop = EvolutionLoop(config)
    t_evo = time.monotonic()
    state = loop.run()
    evo_time = time.monotonic() - t_evo

    # Step 4: Report results
    logger.info("=" * 70)
    logger.info("EVOLUTION COMPLETE")
    logger.info("=" * 70)
    logger.info("Generations: %d", state.current_generation)
    logger.info("Total genomes evaluated: %d", state.total_genomes_evaluated)
    logger.info("Compute time: %.1fs (%.1f genomes/sec)",
                evo_time, state.total_genomes_evaluated / max(1, evo_time))
    logger.info("Best ever fitness: %.4f", state.best_ever_fitness)

    if state.best_ever_genome:
        logger.info("Best genome: %s", state.best_ever_genome.get("genome_id", "?"))
        # Print top genes
        genes = state.best_ever_genome.get("genes", {})
        signal_genes = {k: v for k, v in genes.items() if k.startswith("w_")}
        active = sorted(signal_genes.items(), key=lambda x: x[1].get("value", 0), reverse=True)
        logger.info("Top signal weights:")
        for name, info in active[:5]:
            logger.info("  %s: %.3f", name, info.get("value", 0))

    # Print Bayesian decisions
    decisions = loop.allocator.get_decisions()
    promote_count = sum(1 for d in decisions.values() if d["decision"] == "PROMOTE")
    kill_count = sum(1 for d in decisions.values() if d["decision"] == "KILL")
    hold_count = sum(1 for d in decisions.values() if d["decision"] == "HOLD")
    logger.info("Bayesian decisions: %d PROMOTE, %d HOLD, %d KILL",
                promote_count, hold_count, kill_count)

    # Print convergence
    curve = state.convergence_curve
    if len(curve) >= 2:
        improvement = curve[-1] - curve[0]
        logger.info("Fitness improvement: %.4f -> %.4f (%.1f%%)",
                    curve[0], curve[-1],
                    (improvement / abs(curve[0]) * 100) if curve[0] != 0 else 0)

    logger.info("-" * 70)
    logger.info("Reports saved to: %s", output_dir)
    logger.info("  - evolution_report.json (full results)")
    logger.info("  - evolution_report.md (human-readable)")
    logger.info("  - checkpoint.json (resumable state)")
    logger.info("  - tournament_data.json (input data)")

    # Return best genome params for potential deployment
    if state.best_ever_genome:
        best_params_path = output_dir / "best_genome_params.json"
        with open(best_params_path, "w") as f:
            json.dump(state.best_ever_genome, f, indent=2)
        logger.info("  - best_genome_params.json (deployment candidate)")

    return state


if __name__ == "__main__":
    main()
