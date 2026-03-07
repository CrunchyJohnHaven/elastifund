# Dispatch 083 — Structural Alpha Gating Reset

**Date:** 2026-03-07  
**Status:** Executed in repo  
**Priority:** P0

## Why this dispatch exists

v7 was still optimizing architecture before proving executable density. The real bottleneck is execution validity:

- fill rate
- violation frequency
- non-atomic execution loss
- market density after category filters
- live Polymarket/CLOB operational constraints

The repo is now reordered around falsifying or unlocking a statistically defensible edge quickly.

## Adopted conclusions

### A-6 is no longer framed as a pure sum scanner

A-6 is now treated as a **guaranteed-dollar lane** inside neg-risk events:

1. Prefer `YES_i + NO_i` binary straddles when they are cheapest.
2. Only use full-event YES baskets when they are actually the cheapest guaranteed construction.
3. Track neg-risk conversion discount versus the rest-of-book, but do not assume atomic basket fills.
4. Allow augmented neg-risk events only after filtering `Other` / catch-all legs out of the tradable set.

### B-1 is no longer “classify arbitrary pairs”

B-1 is now narrowed to a **templated dependency engine**:

- winner ↔ margin
- winner ↔ popular vote / electoral college composite
- winner ↔ balance-of-power composite
- state winner ↔ state margin
- composite “wins both” ↔ components

The deliverable is a compatibility matrix per template, not a single free-form label.

### Execution readiness is a first-class gate

Every structural signal must clear:

- feed healthy
- tick size usable
- quote surface complete
- one-leg loss below threshold
- outside Polymarket maintenance window
- neg-risk order routing configured
- Builder relayer check when explicitly required

## Repo tasks generated from this dispatch

1. Store the research in repo docs and command context.
2. Replace “sum violation” priority language with “guaranteed-dollar” priority language.
3. Add an execution-readiness module.
4. Extend A-6 scanner output to rank cheapest guaranteed-dollar constructions.
5. Route A-6 orders with `neg_risk` enabled.
6. Narrow B-1 gold-set generation through deterministic template families and compatibility matrices.
7. Keep full-book / broad-graph buildout deferred until live gating data exists.

## Implemented in this pass

- Added `bot/execution_readiness.py`
- Extended `bot/a6_sum_scanner.py` to rank `binary_straddle` vs `full_event_basket`
- Updated `strategies/a6_sum_violation.py` to filter augmented `Other` outcomes instead of discarding the whole event
- Updated `bot/a6_executor.py`, `bot/a6_command_router.py`, and `bot/jj_live.py` for guaranteed-dollar routing
- Added `bot/b1_template_engine.py`
- Updated `scripts/build_b1_gold_set.py` to emit template families + compatibility matrices

## Explicit defer list

These remain intentionally deferred until empirical gates pass:

- full-book infrastructure
- broad open-ended dependency graph expansion
- merge/redeem optimization as a primary path
- capital scaling before 20+ completed structural cycles or a statistically credible kill
