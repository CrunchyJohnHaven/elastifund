# Dispatch 083: Combinatorial Research Ingest

**Date:** 2026-03-07  
**Source:** `/Users/johnbradley/Downloads/deep-research-report (2).md`  
**Scope:** A-6 / B-1 structural alpha research ingest, task generation, and first execution pass

## Core conclusion

The research report is directionally correct: the repo had already built most of the A-6 / B-1 scaffolding, but it was still missing the three measurements that actually decide whether structural alpha is tradable:

1. maker-fill curve  
2. violation half-life  
3. settlement-path proof

That means "shadow mode exists" was too vague. The ingest pass converted those ideas into explicit repo state.

## What changed in this pass

- Canonized the lane definition: current A-6 implementation is `neg_risk_sum` only, not binary YES+NO Dutch-book merge baskets.
- Added dedicated telemetry tables for scan snapshots, A-6 episodes, order groups, order legs, settlement ops, and latency samples.
- Upgraded the empirical snapshot script to read the new telemetry and emit a task list tied to the research gates.
- Added tick-size propagation to the shared quote store so A-6/B-1 consumers can see `tick_size_change` events.
- Raised the default B-1 implication threshold floor to `0.04` pending gold-set precision evidence.

## Tasks generated from the research

### Completed in this pass

1. Clarify A-6 lane semantics in code and docs.
2. Add combinatorial telemetry schema beyond `constraint_violations`.
3. Upgrade empirical reporting to show gating metrics instead of generic shadow language.
4. Preserve tick-size changes in the shared market-data layer.

### Next executable tasks

1. Run a 72-hour maker-fill curve measurement with actual queue outcomes, not just trade-through proxy.
2. Finish the 50-pair B-1 gold set and enforce the >=85% precision gate.
3. Wire live order groups / order legs / user-channel fills into the new telemetry tables.
4. Publish a 14-day GO / NO-GO report keyed on maker-fill, half-life, capture, and settlement evidence.

### Blocked on runtime data or credentials

1. Settlement-path validation: merge / redeem / convert operations need real confirmed rows in `arb_settlement_op`.
2. Binary Dutch-book A-6 lane: requires separate routing and merge plumbing, so it stays in backlog for now.

## Why this matters

The repo can now distinguish between:

- a scanner finding theoretical opportunities,
- a basket proving executable,
- and a lane proving promotable.

That is the actual contribution of this ingest pass. It tightened the project state around measurable execution reality instead of more strategy prose.
