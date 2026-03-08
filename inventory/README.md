# Benchmark Inventory

This directory is the implementation scaffold for the methodology-first competitive benchmark lane.

It exists so Elastifund can compare other systems honestly, with evidence, instead of publishing a fake leaderboard before the runs exist.

## Current State

- methodology is published
- the initial catalog lives in `inventory/data/systems.json`
- planned Tier-1 runs live in `inventory/data/runs.json`
- no benchmark rankings are published yet because the clean-room T0-T5 runs have not started

## Directory Layout

| Path | Purpose |
|---|---|
| `data/` | versioned catalog and run metadata used by the hub API |
| `systems/` | per-system adapter and runbook home |
| `strategies/` | canonical translated strategies for apples-to-apples runs |
| `metrics/` | normalization rules and extraction contracts |
| `results/` | published benchmark artifacts and evidence |

## Ground Rule

This package is for benchmark methodology and benchmark evidence. It is not a marketing surface. Do not commit placeholder rankings or invented scores.
