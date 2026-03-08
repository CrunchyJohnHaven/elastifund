# Calibration Lane Contract

## Purpose

This lane imports the core autoresearch pattern into Elastifund without touching live execution. The lane exists to improve calibration quality on a frozen historical benchmark, not to optimize live profitability directly.

## Mutable Surface

- [`bot/adaptive_platt.py`](../../bot/adaptive_platt.py)

Only this file may be mutated during the first calibration wave.

## Immutable Evaluator

- Benchmark package: [`benchmarks/calibration_v1/README.md`](../../benchmarks/calibration_v1/README.md)
- Manifest: [`benchmarks/calibration_v1/manifest.json`](../../benchmarks/calibration_v1/manifest.json)
- Command: `python scripts/run_calibration_benchmark.py`

The evaluator, manifest, dataset snapshot, split definition, and scoring formula are read-only for the duration of an experiment wave.

## Objective

- Primary objective: `benchmark_score = -(brier + 0.25 * ece)`
- Diagnostics: `brier`, `ece`, `log_loss`, confidence-band drift
- Tie-break rule: prefer the simpler implementation if `benchmark_score` is effectively unchanged

## Keep, Discard, Crash

- `keep`: successful benchmark run that sets a new high-water mark on `benchmark_score`
- `discard`: successful run that does not beat the current frontier
- `crash`: mutation or benchmark execution fails, or the benchmark packet is invalid

All outcomes must be appended to [`research/results/calibration/results.tsv`](../results/calibration/results.tsv).

## Safety Boundaries

- Do not modify `bot/jj_live.py`, deployment scripts, or control-plane policy files inside this lane
- Do not rewrite the evaluator, manifest, or split during an active wave
- Do not label a calibration benchmark win as a live-trading win
- Do not auto-promote any retained change into paper, shadow, or live capital

## Promotion Path

1. Retained benchmark improvement enters flywheel review as a task.
2. A human reviews the patch and replay evidence outside the mutation loop.
3. Only then can the change be considered for paper or shadow validation.
