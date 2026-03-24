# Deep Research Dispatch: BTC5 Probability Model and Fill-Conditioned Maker Execution
**Date:** 2026-03-23
**Source:** `/Users/johnbradley/Downloads/deep-research-report (10).md`
**Status:** INTEGRATED into `research/rtds_maker_edge_implementation_full.md`, `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md`, `research/edge_backlog_ranked.md`, and `research/dispatches/DISPATCH_112_btc5_down_maker_execution_fix.md`
**Relevance:** HIGH — corrects the BTC5 contract/label definition and upgrades the maker-execution modeling spec

---

## Summary

The attached March 23, 2026 deep-research report changes the BTC5 modeling contract in one decisive way: Polymarket 5-minute BTC `DOWN` must be labeled from the Chainlink settlement series as `S1 < S0`, while ties resolve `UP` because `UP` wins on `S1 >= S0`.

That means the repo should treat Chainlink BTC/USD as the settlement truth for candle open, price-to-beat, intra-candle delta, and model labeling. Binance remains useful, but only as an auxiliary microstructure and basis signal. The report also argues that maker trading needs a separate fill model and fill-conditioned outcome adjustment; raw `P(DOWN)` alone is not enough for execution.

## Key Findings Integrated

### 1. Contract and oracle alignment come before edge search

- Settlement rule: `UP` if end price `>=` start price, else `DOWN`.
- Ties are an `UP` outcome, not `DOWN`.
- The primary resolution source is Chainlink BTC/USD, not Binance spot.
- Repo implication: any BTC5 feature or label path that keys to Binance alone is structurally wrong for settlement modeling.

### 2. The recommended production model is compact, fast, and calibration-first

- Baseline model: diffusion-style probability on Chainlink `{delta_from_open, time_remaining, EWMA_volatility}`.
- Residual model: small microstructure and seasonality correction layer rather than a large standalone classifier.
- Calibration: beta calibration is the recommended default.
- Repo implication: the first production target is not a large feature zoo; it is a well-calibrated baseline plus a narrow residual layer.

### 3. Maker execution needs its own fill and adverse-selection model

- Outcome information and execution information are separate curves.
- Expected value should be optimized on `EV_submit = P(fill) * (q_fill - p + rebate - costs)`.
- Fill-conditioned probability matters because maker fills are selected, not random.
- Repo implication: deterministic queue replay from Polymarket `book`, `price_change`, and `last_trade_price` should be treated as required research plumbing, not optional simulation polish.

### 4. The useful predictive signal is small and bucketed

- The report frames the edge as fragile and calibration-sensitive, not as a large raw directional advantage.
- Time-to-close, time-of-day, minute-of-hour, and 15-minute-boundary effects should be measured explicitly.
- Repo implication: bucketed reporting by `tau`, price bucket, and quote type is more important than a single aggregate win-rate.

### 5. Default operating recommendations are narrower than the older RTDS spec

- Recommended default maker window: `T-30s` to `T-10s`.
- `T-60s` to `T-30s` should be opportunistic only when displacement and fill odds are both strong.
- Go-live should require stable bucketed calibration, positive fill-conditioned edge, and no oracle/feed mismatch events.

## Concrete Claims To Preserve As Report-Sourced

These should stay attached to the attached report until independently reverified in-repo:

- 5-minute BTC returns can show negative first-order autocorrelation, including one cited estimate around `-0.1016`.
- Intraday activity, volatility, and liquidity can peak around `16:00–17:00 UTC`.
- Minute-of-hour effects may concentrate around `0`, `15`, `30`, and `45`.
- Starter maker filter recommendation: `P(fill) >= 0.20` and `q_fill - p >= 1.0pp`, tightened to `1.5pp` inside the last 15 seconds.
- Starter adverse-selection priors: `-0.5pp` for join, `-1.0pp` for improve-by-1-tick, `-2.0pp` for improve-by-2+-ticks.
- Rough sample-size requirement for proving a 3 percentage point edge: `~2,200` independent resolved samples.

## Repo Action Translation

- Audit BTC5 resolution extraction against Chainlink RTDS open/close timestamps and tie handling before any further promotion work.
- Treat Chainlink oracle delta/time/vol as the canonical baseline feature set.
- Treat Binance and Polymarket microstructure as residual/execution features, not settlement truth.
- Keep maker fill replay and fill-conditioned adjustment on the critical path for BTC5 validation.
- Report validation by time-to-close and price buckets, not only aggregate hit rate or PnL.

---

This file records the external research as an import note. The canonical strategy spec remains `research/rtds_maker_edge_implementation_full.md`, with `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md` kept aligned as a compatibility surface.
