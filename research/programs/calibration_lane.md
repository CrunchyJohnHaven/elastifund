# Calibration Lane Contract

## Purpose

This lane imports the useful core of Karpathy-style `autoresearch` into Elastifund without touching live execution. The goal is to improve forecast calibration on a frozen resolved-market benchmark, not to optimize live profitability directly.

## Mutable Surface

- [`bot/adaptive_platt.py`](../../bot/adaptive_platt.py)

Only this file may be mutated during the first calibration wave.

Allowed mutation families:

- rolling vs expanding calibration windows
- minimum-sample thresholds
- smooth fallback policy between static and adaptive fits
- bounded shrinkage or priors that do not require new live data dependencies
- calibration-only parameterization changes

## Immutable Evaluator

- Benchmark package: [`benchmarks/calibration_v1/README.md`](../../benchmarks/calibration_v1/README.md)
- Manifest: [`benchmarks/calibration_v1/manifest.json`](../../benchmarks/calibration_v1/manifest.json)
- Command: `python scripts/run_calibration_benchmark.py`

The evaluator, manifest, dataset snapshot, split definition, scoring formula, and keep/discard/crash rules are read-only for the duration of an experiment wave.

## Objective

- Primary objective: `benchmark_score = -(brier + 0.25 * ece)`
- Diagnostics: `brier`, `ece`, `log_loss`, confidence-band drift
- Tie-break rule: prefer the simpler implementation if `benchmark_score` is effectively unchanged

## Experiment Unit

One experiment unit is one benchmark run against the frozen evaluator with one candidate state of [`bot/adaptive_platt.py`](../../bot/adaptive_platt.py).

Every candidate should emit a machine-readable result packet and one ledger row. Do not rely on narrative summaries as the source of truth.

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
