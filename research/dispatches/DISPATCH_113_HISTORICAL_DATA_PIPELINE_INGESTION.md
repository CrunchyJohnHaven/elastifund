# Dispatch 113 - Historical Data Pipeline Ingestion

**Date:** 2026-03-23
**Imported source:** `research/imports/deep_research_report_2026-03-23_historical_data_pipeline.md`

## Purpose

Preserve the external simulation-data research inside the repo and integrate only the parts that improve the existing research/runtime design without prematurely locking the codebase into a full multi-venue rewrite.

## Source Disposition

The imported report is useful because it is concrete, implementation-oriented, and already scoped to the repo's actual edge-discovery problem.

It mixes three kinds of value:

- venue-specific source-of-truth rules,
- a practical normalized SQLite schema,
- and statistical thresholds for calibration and walk-forward sufficiency.

This ingestion keeps those pieces explicit and avoids treating the raw report as code or as a premature platform commitment.

## Accepted And Integrated Now

### 1. Normalize venue history into one research truth store

Accepted as the default design direction for future simulation-data work.

Why:

- the repo already spans Polymarket, Kalshi, and Alpaca-adjacent research,
- and the report gives a sane contract that separates market metadata, price observations, and resolution truth.

Integrated into:

- `src/README.md`
- `research/dispatches/DEEP_RESEARCH_PROMPT_005_simulation_data_pipeline.md`

Required effect:

- new shared historical-ingest code should land under `src/data/`,
- and it should target a normalized SQLite contract rather than per-venue one-offs.

### 2. Outcome truth is a separate contract from market price

Accepted as a hard requirement for calibration and replay work.

Why:

- favorite-longshot tests, walk-forward calibration, and resolution-aware replay all break if "last price" is treated as ground truth,
- and the report makes that failure mode explicit across venues.

Integrated into:

- `research/imports/deep_research_report_2026-03-23_historical_data_pipeline.md`
- `research/dispatches/DEEP_RESEARCH_PROMPT_005_simulation_data_pipeline.md`

Required effect:

- future ingest must persist both probability observations and realized outcome,
- and Polymarket resolution extraction must not rely on market-discovery metadata alone.

### 3. Kalshi cutoff-aware routing and fee-true replay

Accepted as a core simulation-data rule for any Kalshi lane.

Why:

- the historical/live cutoff split is an actual API contract, not an implementation detail,
- and the 2026 fee formulas plus rounding behavior materially affect replay realism.

Integrated into:

- `research/imports/deep_research_report_2026-03-23_historical_data_pipeline.md`
- `research/dispatches/DEEP_RESEARCH_PROMPT_005_simulation_data_pipeline.md`

Required effect:

- Kalshi ingestion must query the cutoff endpoint and route older pulls to `/historical/*`,
- and backtests must store raw fee parameters instead of using a flat fee stub.

### 4. Alpaca options history limitation is now explicit

Accepted as a scope boundary.

Why:

- the report clearly distinguishes historical bars from latest snapshot Greeks,
- which prevents the repo from quietly assuming it already has historical IV/Greeks when it does not.

Integrated into:

- `research/imports/deep_research_report_2026-03-23_historical_data_pipeline.md`

Required effect:

- if a future strategy requires historical options Greeks or IV, that requirement must trigger either snapshot sampling or a new vendor decision.

### 5. Calibration and walk-forward gates should use the report's numbers

Accepted as the default statistical starting contract for the simulation-data lane.

Why:

- the repo has had repeated ambiguity around "enough data,"
- and the imported report gives exact sample-size and horizon numbers that are good enough to serve as default gates.

Integrated into:

- `research/imports/deep_research_report_2026-03-23_historical_data_pipeline.md`
- `research/dispatches/DEEP_RESEARCH_PROMPT_005_simulation_data_pipeline.md`

Required effect:

- low-price-bin calibration claims should cite required in-bin sample counts,
- and walk-forward plans should justify any horizon shorter than `51` contiguous days.

## Deferred Until Built

These ideas are useful but should not become repo truth from the report alone:

- full Polymarket on-chain indexing as the default first implementation,
- universal trade-level ingestion for every venue and every market,
- historical order-book reconstruction as an MVP requirement,
- or any assumption that Alpaca alone can satisfy a historical options-volatility research lane.

Those remain build-time decisions once the first shared ingest path exists.

## Practical Outcome

This report does not force a full data-platform implementation immediately.

It does tighten the repo's future simulation-data contract in five places:

1. one normalized SQLite shape should be the default,
2. outcome truth must be stored separately from price history,
3. Polymarket resolution needs a dedicated truth path,
4. Kalshi cutoff and fee rules are first-class replay inputs,
5. and calibration sufficiency should be expressed with explicit sample counts.

That is the useful delta.
