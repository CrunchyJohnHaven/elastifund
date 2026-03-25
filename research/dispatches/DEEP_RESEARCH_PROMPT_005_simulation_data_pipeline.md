# Deep Research Prompt 005: Historical Data Pipeline for Edge Discovery Simulation

**Run this on:** ChatGPT Deep Research or Claude with web access
**Purpose:** Get the exact specifications needed to build the data ingestion layer for our 24/7 edge discovery simulation engine
**Status:** COMPLETED -> INTEGRATED on 2026-03-23
**Imported result:** `research/imports/deep_research_report_2026-03-23_historical_data_pipeline.md`
**Integration note:** `research/dispatches/DISPATCH_113_HISTORICAL_DATA_PIPELINE_INGESTION.md`

---

## Prompt (copy-paste this into the deep research tool)

---

I'm building an automated edge discovery simulation engine that runs 24/7 on a MacBook, testing trading hypotheses against historical prediction market data. The engine needs historical data from three venues: Polymarket, Kalshi, and Alpaca. I need you to research the exact data access methods, historical data availability, and build a concrete data pipeline specification.

### What I need you to research:

**1. Polymarket historical data access (critical)**

Research every available method to get historical Polymarket data:
- The Polymarket CLOB API (clob.polymarket.com) — what historical endpoints exist? Can I query past trades, order books, resolved markets?
- The Polymarket Gamma API (gamma-api.polymarket.com) — market discovery, historical prices, resolution outcomes
- The Polymarket Data API — historical trade data, user positions
- Third-party sources: Dune Analytics dashboards for Polymarket on-chain data, TheGraph/subgraph queries, direct blockchain reads
- Academic datasets: any published Polymarket datasets (e.g., from research papers)
- What is the maximum historical depth available from each source?
- Rate limits and authentication requirements for each

I specifically need: resolved market outcomes with final prices, historical order book snapshots or trade-level data, and market metadata (category, rules, resolution source, fee category).

**2. Kalshi historical data access (critical)**

Research every available method to get historical Kalshi data:
- Kalshi public REST API (api.elections.kalshi.com) — what historical market data endpoints exist? Can I query resolved markets, historical prices, trade history?
- Kalshi's public market data: what fields are available without authentication?
- Academic datasets: the 2026 paper analyzing 300k+ Kalshi contracts — where is this dataset? Is it public?
- Any Kalshi data export or download tools
- Settlement outcomes: how to systematically get the resolved outcome for every past market
- Fee schedule: confirm the current (March 2026) fee formulas for taker and maker, including rounding rules

I specifically need: every resolved Kalshi market with its final YES price, outcome (YES/NO), category, settlement source, and time-to-resolution.

**3. Alpaca historical data access**

- Alpaca market data API: historical bars, quotes, trades for stocks, crypto, and options
- What's available on the free tier vs Algo Trader Plus ($99/month)?
- Historical options data: availability, depth, Greeks/IV snapshots
- Can I get historical crypto OHLCV going back at least 1 year?

**4. Data pipeline architecture specification**

Given the data sources above, design a concrete pipeline that:
- Runs on a MacBook Pro (M-series, 16GB+ RAM)
- Downloads and normalizes historical data from all three venues into a unified SQLite database
- Schema must support: market_id, venue, category, yes_price_at_time_t, outcome, fees, time_to_resolution, settlement_source, rule_type
- Incremental updates (daily pulls of new resolved markets)
- Handles rate limits gracefully
- Includes data quality checks (missing fields, impossible prices, duplicate markets)

**5. Calibration dataset for favorite-longshot bias testing**

I need to test the favorite-longshot bias hypothesis specifically. Research:
- What is the minimum dataset needed to detect a 2-3 percentage point miscalibration in the 1-5¢ YES price bin with 90% confidence?
- Sample size calculations for binary outcome calibration testing with sparse tails
- What probability bins should I use (provide exact boundaries and minimum samples per bin)?
- How should I handle the multiple-testing problem when testing calibration across many bins simultaneously?

**6. Walk-forward backtesting data requirements**

For a walk-forward backtest with:
- 30-day training windows, 7-day test windows
- At least 3 non-overlapping test periods
- Minimum 15 trades per window

Calculate: how many months of historical data do I need, and approximately how many resolved markets per month exist on Polymarket and Kalshi?

### Output format

For each data source, provide:
1. Exact API endpoint URLs
2. Authentication requirements
3. Example API calls (curl or Python requests)
4. Response format / schema
5. Rate limits
6. Historical depth available
7. Known limitations or gotchas

For the pipeline, provide:
1. SQLite schema (CREATE TABLE statements)
2. Python pseudocode for the ingestion pipeline
3. Incremental update logic
4. Data quality checks
5. Estimated storage requirements

For the statistics:
1. Exact sample size formulas with worked examples
2. Recommended probability bins with boundaries
3. Multiple-testing correction procedure
4. Minimum viable dataset specification (how many markets, what time range)

Be precise. Give me numbers, not ranges. Give me code, not descriptions. I will be implementing this directly.

---

## Expected output usage

The output of this research run will be used to:
1. Build `src/data/historical_ingest.py` — the data pipeline feeding the edge discovery engine (DISPATCH_108)
2. Build `src/data/calibration_dataset.py` — the calibration testing infrastructure for Kalshi longshot fade (DISPATCH_109)
3. Determine whether we need paid data subscriptions (Alpaca Algo Trader Plus, etc.)
4. Set minimum viable data collection timeline before we can run meaningful simulations
