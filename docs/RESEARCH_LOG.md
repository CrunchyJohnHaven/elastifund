# Research Log

This file summarizes the core Elastifund dispatch program and the findings it produced. The indexed dispatch set in [research/dispatches/README.md](../research/dispatches/README.md) covers the original research waves, and the repo now contains follow-on dispatches beyond that first corpus. The point of this log is not to list every prompt verbatim. It is to make the resulting map legible.

## Dispatch Program Summary

| Phase | Primary focus | What it produced |
| --- | --- | --- |
| Dispatches 01-24 | forecasting, calibration, backtesting, risk, infrastructure | the first working LLM pipeline, baseline backtests, and initial risk controls |
| Dispatches 25-48 | validation, external reporting, fee realism, live-readiness | scorecards, fee studies, Monte Carlo stress work, and reporting discipline |
| Dispatches 49-60 | systematic edge discovery and self-improving workflow | broader strategy search, automation concepts, scanner upgrades, and execution studies |
| Dispatches 61-74 | confidence and ARR sprint | agentic RAG, category-specific calibration, polling and trend signals, live-vs-backtest checks |
| Dispatches 75+ | structural alpha reprioritization | tighter focus on maker execution, A-6 guaranteed-dollar constructions, and B-1 templated dependency violations |

The operating docs refer to a 76-dispatch core research program. The repo has since grown beyond that initial index, but the conclusions below are the through-line that survived the extra work.

## What The Research Found

- Maker execution matters more than most signal tweaks. Taker fees kill a large share of otherwise plausible fast strategies.
- The most durable directional result is NO-side strength. Internal research notes that NO outperforms YES at 69 of 99 price levels, which fits the favorite-longshot bias literature.
- Category choice matters. Politics, weather, and some economic markets were materially more promising for the predictive LLM lane than sports, crypto, fed-rate, or precise price-target markets.
- Calibration is mandatory. Raw model confidence was too optimistic for direct sizing.
- Signal density is a hard constraint. Many elegant ideas fail simply because they do not generate enough resolved trades to validate.
- Structural alpha looks more promising than pattern mining. The surviving high-priority paths are market-structure violations, not conventional technical signals.
- Comparative benchmarking is useful, but as a distribution and authority moat rather than direct alpha. The imported bot-inventory work strengthens the website lane, not the live trading priority stack.

## Strategies Tested And Rejected

The failure diary is not side content. It is the main map of the territory.

| Strategy family | Why it failed |
| --- | --- |
| Residual horizon fair value | not enough signal density and no measurable edge after costs |
| Volatility regime mismatch | equity-style regime logic did not transfer to binary markets |
| Cross-timeframe constraint violation | the supposed constraint did not exist in practice |
| Chainlink-Binance taker lag | the edge was smaller than the taker fee |
| Mean reversion after extreme move | extreme moves were too rare to validate |
| Time-of-day session effects | 24/7 prediction markets did not show reliable session structure |
| Raw order-book imbalance | data quality was partial and the inferred mechanism was wrong |
| Brute-force feature discovery | overfit in-sample, collapsed out of sample |
| Crypto latency arbitrage with takers | fee economics made the setup unusable |
| Kalshi weather bracket rounding | discretization error destroyed the apparent forecast edge |

Current headline from the fast-trade engine: [FAST_TRADE_EDGE_ANALYSIS.md](../FAST_TRADE_EDGE_ANALYSIS.md) says `REJECT ALL`.

That is not marketing copy. It is the honest result.

## What Survived Triage

The current hypothesis pipeline is narrower and more realistic than the early search space.

- A-6 guaranteed-dollar and sum-violation style structural arbitrage remains a top-priority lane because it exploits event construction rather than prediction skill alone.
- B-1 templated dependency monitoring remains viable in principle, but live density is sparse and promotion is gated behind empirical evidence.
- Fill-rate measurement, stale-order handling, and position-merging work moved up because execution quality is now recognized as a first-class research problem.
- Forecasting improvements such as category routing, agentic RAG, and ensemble disagreement remain useful, but they are not enough by themselves on short-dated markets.
- The external benchmark harness moved into the P2 website lane: useful for comparative authority, recruiting, and methodology credibility, but not a reason to defer current alpha validation.

## Honest Bottom Line

The repo does not claim that a general-purpose AI predictor is already printing money. The research record says something narrower and more useful:

- naive fast trading has mostly failed
- fee realism changes verdicts
- calibration changes sizing decisions
- market structure beats theory-first pattern importing
- documentation of failure is a competitive asset

The flywheel is working when it kills bad ideas quickly and makes the surviving ideas more concrete.
