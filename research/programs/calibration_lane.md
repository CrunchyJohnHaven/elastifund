# Calibration Lane Program

## Purpose

Improve forecast calibration on a frozen resolved-market slice without changing
live execution behavior.

This is Elastifund's first bounded `autoresearch`-style lane. The goal is to
import the useful part of Karpathy's architecture: one mutable surface, one
immutable evaluator, one scalar objective, and a mechanical keep/discard/crash
decision.

## Optimization Target

Primary objective:

`benchmark_score = -(brier + 0.25 * ece)`

Lower Brier and lower expected calibration error are better. The sign inversion
keeps the decision rule simple: higher `benchmark_score` wins.

Diagnostic metrics to record but not optimize directly:

- `brier`
- `ece`
- `log_loss`
- per-band calibration drift

## Mutable Surface

Only this file is in scope for candidate changes:

- `bot/adaptive_platt.py`

Allowed mutation families:

- rolling vs expanding calibration windows
- minimum-sample thresholds
- smooth fallback policy between static and adaptive fits
- bounded shrinkage or priors that do not require new live data dependencies
- calibration-only parameterization changes

## Immutable Surface

The following must stay fixed during an experiment wave:

- the benchmark dataset or fixture snapshot
- train/validation/test split rules
- cost assumptions if any are included in the benchmark
- the evaluator entrypoint and reporting schema
- keep/discard/crash rules

Out of scope:

- `bot/jj_live.py`
- deployment or VPS scripts
- risk caps, position sizing policy, or credentials
- unrelated strategy modules
- benchmark weight changes during an active wave

## Experiment Unit

One experiment unit is one benchmark run against the frozen calibration
evaluator with one candidate state of `bot/adaptive_platt.py`.

Every candidate should produce a machine-readable result packet and one ledger
row. Do not rely on narrative summaries as the source of truth.

## Decision Rule

- `keep`: candidate beats the current best `benchmark_score`
- `discard`: candidate completes but does not beat the current best
- `crash`: benchmark run fails, emits invalid output, or violates the contract

Tie-break rule:

- if scores are effectively unchanged, prefer the simpler implementation

## Safety Boundary

Benchmark wins are research evidence only. They do not auto-promote code into
paper or live trading.

Any retained calibration change must be replayed outside the autonomous loop
before it can be considered for broader adoption.

## Human Owner Responsibilities

- freeze benchmark versions
- approve any widening of the mutable surface
- review retained changes before merge
- decide when a benchmark lane is mature enough to feed the flywheel
