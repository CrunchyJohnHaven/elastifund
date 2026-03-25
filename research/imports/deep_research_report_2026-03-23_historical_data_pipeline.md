# Deep Research Dispatch: Historical Data Pipeline for Edge Discovery Simulation
**Date:** 2026-03-23
**Source:** `/Users/johnbradley/Downloads/deep-research-report (12).md`
**Status:** INTEGRATED into `research/dispatches/DISPATCH_113_HISTORICAL_DATA_PIPELINE_INGESTION.md`, `research/dispatches/DEEP_RESEARCH_PROMPT_005_simulation_data_pipeline.md`, and `src/README.md`
**Relevance:** HIGH -- defines the venue-history contract for Polymarket, Kalshi, and Alpaca ingestion, including settlement-truth caveats, normalized SQLite schema, and calibration sample-size requirements

---

## Summary

The attached March 23, 2026 deep-research report answers the repo's open simulation-data question directly: the historical ingestion layer should normalize Polymarket, Kalshi, and Alpaca into one SQLite truth store while treating settlement outcome as a separate contract from pre-resolution market price.

The strongest repo-level implication is that "last traded price" is not enough for backtesting. Every venue ingest must preserve both:

- pre-resolution implied probability observations, and
- post-resolution ground-truth outcome.

Without that split, favorite-longshot calibration, walk-forward validation, and execution-aware replay all become structurally unreliable.

## Key Findings Integrated

### 1. Outcome truth must be stored separately from price history

- The report is explicit that resolved outcome is not the same as the final trade price.
- The normalized store should therefore keep market metadata, probability time series, and resolution facts in separate tables.
- Repo implication: any future simulation lane should treat `market_yes_price` and `market_resolution` as different contracts, not infer one from the other.

### 2. Polymarket historical ingestion needs a split-source design

- Gamma is the discovery and market-metadata surface.
- CLOB `prices-history` is the cleanest official price-history surface for YES-token time series.
- Data API `/trades` is useful but not robust enough to serve as the sole full-depth historical source because of pagination constraints.
- Resolution truth may require an on-chain or subgraph-backed extraction step when Gamma status fields are incomplete or ambiguous.
- Repo implication: do not design Polymarket historical ingest as "Gamma-only" or "Data-API-only."

### 3. Kalshi requires cutoff-aware routing and fee-true replay

- The report identifies Kalshi's live versus historical cutoff model as a core ingestion rule.
- Settled-market truth can come from market-level fields such as `result`, `settlement_value_dollars`, and `settlement_ts`.
- The current fee contract that matters for replay is the 2026 parabolic fee model with maker/taker parameters plus centicent rounding behavior.
- Repo implication: Kalshi replay should preserve raw fee parameters and compute exact fees in backtests rather than using a flat approximation.

### 4. Alpaca is useful for bars, but not a full historical options-greeks source

- Historical stocks, crypto, and options bars are available through Alpaca's market-data endpoints.
- Historical options bars are OHLCV-style aggregates, not historical IV/Greeks snapshots.
- Repo implication: if the simulation engine needs historical Greeks or IV, the system must either sample Alpaca snapshots over time into its own store or add a separate vendor later.

### 5. The report provides a concrete normalized SQLite contract

- The proposed core tables are `markets`, `market_resolution`, `market_yes_price`, `trades`, and `ingestion_state`.
- The report also includes explicit SQL quality checks for impossible prices, missing resolutions, bad time ordering, and duplicate market identities.
- Repo implication: the simulation-data lane already has a workable first schema and should not start with ad hoc per-venue tables.

### 6. Calibration and walk-forward requirements are now quantified

- Detecting a 2 percentage point miscalibration in the `1-5c` bin at 90% power requires about `942` resolved contracts in-bin, or `1,475` under a 12-bin Bonferroni correction.
- Recommended fixed bins are:
  - `[0.01, 0.05]`
  - `(0.05, 0.10]`
  - `(0.10, 0.20]`
  - `(0.20, 0.30]`
  - `(0.30, 0.40]`
  - `(0.40, 0.50]`
  - `(0.50, 0.60]`
  - `(0.60, 0.70]`
  - `(0.70, 0.80]`
  - `(0.80, 0.90]`
  - `(0.90, 0.95]`
  - `(0.95, 0.99]`
- A `30d` train / `7d` test / `3` non-overlapping test-period walk-forward requires a minimum contiguous history of `51` days.
- Repo implication: calibration claims and longshot-bias tests should be held to these numbers instead of hand-wavy sample targets.

## Repo Action Translation

- Build future shared ingestion code under `src/data/` or `data_layer/`, but normalize into one venue-agnostic SQLite contract.
- Treat Polymarket resolution extraction as a dedicated outcome-truth step, not a side effect of market discovery.
- Encode Kalshi cutoff routing and fee-true replay into the ingestion design from day one.
- Treat Alpaca historical options-greeks as unsupported unless the repo explicitly samples and stores snapshots.
- Start with one pre-close snapshot per resolved market for laptop-friendly calibration work, then add denser time series or trade-level ingestion only where a strategy actually needs it.

---

This file preserves the external research as an imported note. The adopted implementation posture for the repo lives in `research/dispatches/DISPATCH_113_HISTORICAL_DATA_PIPELINE_INGESTION.md`.
