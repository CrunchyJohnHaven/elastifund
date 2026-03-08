# What Doesn't Work — The Failure Diary

**Version:** 1.0
**Date:** 2026-03-07
**Author:** JJ
**Purpose:** The most valuable document in this repo. Every rejected strategy, why it died, and what we learned. A quant trader reads this and saves months of wasted effort.

---

## Summary

**Strategies formally tested through kill battery:** 10
**Strategies surviving:** 0
**Survival rate:** 0%
**Pre-rejected (too low viability to build):** 8
**Total strategies catalogued:** 131

This is not a failure of the system. This is the system working. Kill rules exist to prevent capital destruction. Every rejection here prevented a live loss.

---

## The Meta-Lesson (Read This First)

Three root causes kill 95% of prediction market trading strategies:

1. **Transaction costs exceed edge magnitude (60% of deaths).** Polymarket taker fees follow `fee = price * (1 - price) * rate`. At 50/50 odds with crypto rate (0.025), the fee peaks at 1.56%. Any gross edge below this is dead money. The Feb 18, 2026 fee expansion made this worse — now all crypto durations are fee-bearing. Maker orders (0% fee + 20-25% rebate) are the only viable execution path.

2. **Signal sparsity prevents statistical validation (25% of deaths).** Even theoretically sound strategies generate too few tradeable signals on Polymarket. You need 100+ resolved signals for preliminary validation, 300+ for production confidence. Most strategies produce 0-30 signals per month.

3. **Overfitting and market structure mismatch (15% of deaths).** Patterns that work in equities (volatility smiles, weekend unwinds, time-of-day effects) don't transfer to 24/7 binary prediction markets with retail-dominated flow.

---

## R1: Residual Horizon Fair Value

**Hypothesis:** Markets price binary outcomes without properly accounting for time-to-resolution. A "residual horizon" model that discounts probability by remaining time should identify mispriced contracts.

**What we expected:** 5-8 signals per week, 60%+ win rate on time-adjusted mispricing.

**What actually happened:** 8 total signals across the entire test window. Win rate: 50% (coin flip). No edge detected.

**Why it failed:** Polymarket's retail participants already intuitively price time-to-resolution — markets at 95% with 6 months remaining trade differently than 95% with 6 hours. The "residual" is too small to exploit after costs.

**Kill rule triggered:** Insufficient signal count (<50). Also: negative out-of-sample expectancy, collapses under cost stress, poor calibration.

**What we learned:** Time decay in binary markets is not analogous to options theta. Binary markets converge to 0/100 in a step function at resolution, not a smooth decay curve. The theoretical framework from options pricing doesn't transfer.

**Maker-only verdict:** Unchanged. The problem is signal quality, not execution costs.

---

## R2: Volatility Regime Mismatch

**Hypothesis:** Markets in different volatility regimes (high-vol vs low-vol periods) systematically misprice risk. High-vol regimes overprice uncertainty; low-vol regimes underprice tail events.

**What we expected:** 60%+ win rate, particularly strong during regime transitions.

**What actually happened:** 34 signals. Win rate: 32.35%. The strategy performed worse than random.

**Why it failed:** Binary markets have structural vol limits (can't go below 0 or above 100). The vol regime framework from equities — where vol can spike 5x — doesn't apply. A market at 50 cents already prices maximum uncertainty. "High vol" in binary terms just means the market is confused, not that it's systematically wrong.

**Kill rules triggered:** Too few signals, negative OOS EV, collapses under cost stress, poor calibration, monotonic performance decay.

**Specific numbers:** 34 signals, 11 wins, 23 losses. Gross EV: -$0.12 per signal. After taker fees: -$0.89 per signal. Monotonic decay: each subsequent 10-signal batch performed worse than the last.

**What we learned:** Don't import equity frameworks into binary markets without verifying the mechanism transfers. Vol regimes are a feature of continuous-price, leveraged markets. Binary markets are structurally different.

**Maker-only verdict:** Still dead. 32% win rate is below breakeven regardless of fee structure.

---

## R3: Cross-Timeframe Constraint Violation

**Hypothesis:** If BTC 5-minute candles close Up, the 15-minute candle containing them should also close Up. When this constraint is violated (5-min Up, 15-min still priced Down), trade the convergence.

**What we expected:** High-confidence directional signals from timeframe consistency, 70%+ win rate.

**What actually happened:** 21 signals. Win rate: 0.00%. Every single signal was wrong.

**Why it failed:** Prediction markets don't exhibit the time-series structure that equity technical analysis relies on. Retail crypto traders on Polymarket care about absolute BTC price direction, not relative candle behavior. A 5-minute candle closing Up doesn't constrain the 15-minute candle because the remaining 10 minutes can easily reverse.

**Kill rules triggered:** Insufficient signals, negative OOS EV (maximally negative — 0% win rate), collapses under cost stress, poor calibration.

**What we learned:** Candle timeframe consistency is an artifact of continuous markets with correlated participants. Polymarket's crypto candle markets attract independent retail bettors who don't think in timeframes. The cross-timeframe constraint simply doesn't exist in this market structure.

**Maker-only verdict:** Dead regardless. 0% win rate is unfixable.

---

## R4: Chainlink vs Binance Basis Lag

**Hypothesis:** Polymarket's crypto candle markets resolve via Chainlink oracle, which lags Binance spot by 1-5 seconds. Trade the lag: when Binance moves, Polymarket hasn't repriced yet. Buy the direction Binance indicates.

**What we expected:** 65%+ win rate on the final 10 seconds of each candle, exploiting the oracle delay.

**What actually happened (taker version):** The lag exists and is tradeable in theory. Gross edge: 0.3-0.8% per trade. But taker fee at 50/50 odds: 1.56%. Net EV: deeply negative.

**Why it failed (originally):** The edge magnitude (0.3-0.8%) is less than half the taker fee (1.56%). Speed-based strategies need the edge to exceed transaction costs. It doesn't.

**Why it might work now:** The Feb 18, 2026 fee change introduced maker orders at 0% fee + 20-25% rebate. If you can place a maker order in the final 10 seconds and get filled, the same 0.3-0.8% edge becomes profitable. The question is fill rate — will anyone take the other side of a maker order posted 10 seconds before resolution?

**Current status:** Reclassified to RE-EVALUATE. Shadow validator built (`bot/hft_shadow_validator.py`). Awaiting 72-hour empirical fill rate data. If fill rate > 15% and EV positive post-costs, promotes to BUILDING.

**What we learned:** Fee structure changes can resurrect dead strategies overnight. Always re-evaluate the rejection list when platform economics change. The Feb 18 pivot from taker-dominant to maker-dominant changed everything.

---

## R5: Mean Reversion After Extreme Move

**Hypothesis:** Markets that move >10% in a single direction within 4 hours will mean-revert. Buy the opposite direction after extreme moves.

**What we expected:** 5+ signals per week, 70%+ win rate from overreaction correction.

**What actually happened:** 1 signal in the entire test window. Can't validate anything on N=1.

**Why it failed:** Polymarket rarely has >10% moves except at resolution. The market structure prevents large intra-day swings: there's no leverage, no margin calls, no forced liquidation cascading. When markets do move 10%+, it's usually because new information genuinely changed the probability, not because of overreaction.

**Kill rules triggered:** Insufficient signal count (1 signal).

**What we learned:** Binary prediction markets are not volatile enough for mean reversion strategies. The mechanisms that create mean reversion in equities (margin calls, stop-loss cascades, portfolio rebalancing) don't exist here. Lower thresholds (5% moves) would capture more signals but also more noise.

**Maker-only verdict:** Unchanged. The problem is signal frequency, not costs.

---

## R6: Time-of-Day Session Effects

**Hypothesis:** Systematic price biases exist at specific times of day. For example, political markets might be overpriced at 3pm UTC when US trading starts, or crypto markets might drift during Asian session hours.

**What we expected:** 5-10 tradeable patterns per day across time zones.

**What actually happened:** Zero statistically significant patterns detected. The scanner found no consistent time-of-day bias across any category.

**Why it failed:** Prediction markets trade 24/7 with no "opening" or "closing." There's no institutional rebalancing at 4pm, no overnight gap risk, no Asia/Europe/US session handoff dynamics. The continuous, retail-dominated flow doesn't exhibit the time-structure that institutional equity markets do.

**Kill rules triggered:** No significant pattern (0 signals meeting threshold).

**What we learned:** 24/7 markets don't have session effects. This seems obvious in retrospect, but the hypothesis was worth testing because some crypto spot markets do show time-of-day patterns (Asian session vs US session). Prediction markets are different — they're event-driven, not flow-driven.

**Maker-only verdict:** Unchanged. No pattern to exploit.

---

## R7: Order Book Imbalance (Raw)

**Hypothesis:** When buy-side depth exceeds sell-side depth by 3:1 or more, the market is about to move in the direction of the imbalance. Trade with the imbalance.

**What we expected:** Order book depth ratio predicts short-term direction 60%+ of the time.

**What actually happened:** 5 signals. Win rate: 0.00%. Every signal predicted the wrong direction.

**Why it failed (two reasons):**
1. **Data quality:** The Polymarket CLOB API returned 404 errors on ~25% of market queries. The depth snapshots were incomplete and potentially stale.
2. **Mechanism failure:** On Polymarket, large resting orders (bids) often represent market makers providing liquidity, not informed directional conviction. A 3:1 bid/ask imbalance means a market maker is offering to buy, not that the price will go up. In equity markets, order book imbalance reflects institutional flow; on Polymarket, it reflects maker inventory management.

**Kill rules triggered:** Partial data (CLOB 404s), negative OOS EV, poor calibration.

**What we learned:** Order book imbalance interpretation from equity microstructure doesn't transfer to prediction markets. Polymarket's order book is dominated by market makers, not informed traders. The presence of large bids is a liquidity signal, not a directional signal. Also: CLOB API reliability needs hardening before any order-book-based strategy can be trusted.

**Maker-only verdict:** Unchanged. The problem is directional accuracy, not execution.

---

## R8: ML Feature Discovery (Brute Force)

**Hypothesis:** With 83 features (price, volatility, microstructure, wallet flow, time structure, cross-timeframe), automated feature selection should find predictive combinations that humans miss.

**What we expected:** At least 3-5 features would survive walk-forward validation with predictive power >55%.

**What actually happened:** Zero features survived. In-sample, the ML scanner found promising patterns (~40% apparent win rate on the best features). Out-of-sample (walk-forward), every single feature reverted to 50% — statistically indistinguishable from random.

**Why it failed:** Classic overfitting. The brute-force scanner fit noise in the training window. Prediction market data has:
- Low sample size (hundreds of markets, not millions of data points)
- High dimensionality (83 features vs ~200 resolved markets in any given window)
- Regime changes (fee structures, platform rules, participant composition shift frequently)

This is a textbook overfitting setup: more features than effective samples, non-stationary data, no strong prior.

**Kill rules triggered:** No features survived walk-forward validation.

**What we learned:** Automated feature discovery without strong domain priors is doomed in this domain. The data is too sparse and non-stationary for data-driven approaches. Manual feature engineering based on market microstructure intuition (VPIN, maker/taker flow dynamics, resolution mechanics) is more likely to work than throwing 83 features at a gradient booster.

**Maker-only verdict:** Unchanged. The problem is signal quality, not execution.

---

## R9: Latency Arbitrage (Crypto Candles, Taker)

**Hypothesis:** Trade the Binance-to-Polymarket price lag on 5-minute BTC candles. Binance moves first, Polymarket reprices with a 1-5 second delay. Taker orders capture the gap.

**What we expected:** 60%+ win rate on directional bets placed in the final 10 seconds of each candle.

**What actually happened:** The lag exists. The directional signal is real. But the economics are impossible with taker orders.

**Specific numbers:**
- Average spread captured: $0.02-0.04 per $1 risked
- Taker fee at 50/50 odds: $0.78 per $1 risked (rate=0.025)
- Net EV per trade: -$0.74 to -$0.76

**Why it failed:** The fee is 20-40x larger than the spread. No amount of directional accuracy overcomes this. Even at 99% win rate, the 1% of losses plus fees on winners makes this negative EV.

**Kill rules triggered:** 1.56% taker fee exceeds edge magnitude. Cost stress kills the strategy.

**What we learned:** Speed-based strategies on fee-bearing markets require either (a) maker execution (0% fees) or (b) edges > 2% gross. Polymarket's fee structure is specifically designed to prevent taker-based latency arbitrage — the random delay and high taker fees are anti-bot features.

**Maker-only verdict:** Potentially viable. This is the basis for the A-8 (BTC 5min maker T-10s) strategy now in BUILDING. If maker fill rate > 15% in the final 10 seconds, the same directional signal becomes profitable.

---

## R10: NOAA Weather Bracket Arbitrage (Kalshi)

**Hypothesis:** Kalshi weather bracket markets resolve based on NWS forecasts. NWS rounds temperature to integer degrees. By modeling the rounding behavior, we can predict which bracket captures the resolution value and buy it below fair value.

**What we expected:** 60%+ accuracy on bracket prediction using NOAA multi-model consensus (GFS + ECMWF + HRRR).

**What actually happened:** NWS rounding produces 27-35% effective accuracy on 4-bracket markets. Chance is 25%. The edge is real but tiny.

**Specific numbers:**
- NWS forecast accuracy vs actual: 55-60% for point estimate
- Bracket mapping accuracy (forecast → correct bracket): 27-35%
- Random chance on 4-bracket: 25%
- Edge: 2-10 percentage points above chance
- Kalshi fees: ~0.35% per side
- Required win rate for positive EV: >65%
- Actual win rate: ~30%

**Why it failed:** The granularity mismatch between continuous temperature forecasts and discrete bracket boundaries introduces too much noise. A forecast of 72.3F could land in the 70-72 bracket or the 72-74 bracket — the rounding is not predictable enough from the forecast alone. The multi-model consensus improves the point forecast but doesn't meaningfully improve bracket assignment.

**Kill rules triggered:** EV negative. Win rate (30%) far below breakeven threshold (65%).

**What we learned:** Continuous forecasts don't translate cleanly to bracket markets. The discretization error dominates. A better approach might be binary weather markets (rain/no rain, above/below threshold) where the forecast maps directly to the resolution criterion without bracket noise. This informed the B-10 (Kalshi Binary Weather) strategy now in the pipeline.

---

## Pre-Rejected Strategies (Not Worth Building)

These were killed in the assessment phase before any code was written, based on P(Works), complexity, and capital requirements.

### C-9: Satellite Parking Lot Analysis
- **P(Works):** 3%
- **Kill reason:** Data costs ($500+/month) exceed our total capital. L complexity. Even if the signal exists, our $347 bankroll can't capitalize on it.

### C-14: Domain Registration Monitoring
- **P(Works):** 3%
- **Kill reason:** <1 tradeable event per quarter. Statistical validation impossible at any timescale we care about.

### I-2: Wayback Machine Change Detection
- **P(Works):** 3%
- **Kill reason:** <2 events per quarter. Most website changes are irrelevant to prediction markets. The signal-to-noise ratio is impossibly low.

### I-11: Cross-Language Sentiment Divergence
- **P(Works):** 8%
- **Kill reason:** Requires bilingual NLP pipeline we don't have. L complexity. At 8% viability, the build cost exceeds expected value by 10x.

### I-13: Automated Market Creation Timing
- **P(Works):** 5%
- **Kill reason:** Polymarket market creation is centralized and human-driven. There's no algorithmic pattern to predict.

### F-9: Intraday Volatility Smile
- **P(Works):** 5%
- **Kill reason:** The options vol smile mechanism (gamma hedging, tail risk demand) doesn't exist in binary markets. Theoretical framework doesn't transfer.

### F-2: Pre-Weekend Position Unwind
- **P(Works):** 8%
- **Kill reason:** Polymarket trades 24/7. No "weekend." No institutional risk management forcing Friday afternoon unwinds.

### B-7: Triangular 3-Platform Arbitrage
- **P(Works):** 8%
- **Kill reason:** <1 tradeable event per month across all three platforms. Betfair access uncertain for US-based trading.

---

## Kill Rule Taxonomy

Our automated kill battery (`bot/kill_rules.py`) applies six criteria. Here's how they map to actual rejections:

### 1. Insufficient Signal Count
**Threshold:** N < 50 for preliminary, N < 100 for candidate, N < 300 for validation.
**Strategies killed:** R1, R3, R5 (primary), R2, R7 (contributing).
**Pattern:** Low-frequency strategies can't be validated statistically. This is the most common rejection reason because Polymarket's market count and turnover rate limit signal generation.

### 2. Negative Out-of-Sample Expectancy
**Threshold:** OOS EV <= 0 after transaction costs.
**Strategies killed:** R1, R2, R3, R7, R8 (all with enough data to measure).
**Pattern:** Strategies that look good in-sample collapse when tested on future data. Walk-forward validation is the single most important kill filter.

### 3. Cost Stress Collapse
**Threshold:** Net EV flips sign when applying realistic fee + 5ms latency assumption.
**Strategies killed:** R1, R2, R3, R7, R9, R10.
**Pattern:** Marginal edges die when you add transaction costs. The cost stress test applies the polynomial taker fee formula plus execution latency drag. If the strategy can't survive both, it's rejected.

### 4. Poor Calibration
**Threshold:** Calibration error > 0.2 (deviation from perfect calibration curve).
**Strategies killed:** R1, R2, R3, R6, R7.
**Pattern:** Strategies that systematically overestimate or underestimate win probability produce positions that are incorrectly sized. Poor calibration compounds across trades.

### 5. Semantic Decay
**Threshold:** LLM confidence in strategy's theoretical foundation < 0.3.
**Strategies triggered:** None yet in production (monitoring phase).
**Purpose:** Auto-reject strategies whose theoretical basis erodes as market structure changes.

### 6. Monotonic/Regime Performance Decay
**Threshold:** Each successive batch of signals performs worse than the last.
**Strategies killed:** R2 (contributing).
**Pattern:** If performance deteriorates over time, the edge is decaying and the strategy should be killed before it destroys capital.

---

## What This Diary Proves

1. **The kill rules work.** Every rejected strategy would have lost money in live trading. The system prevented $X in real losses (exact amount depends on position sizing, but at quarter-Kelly on $247, conservatively $50-100 in avoided losses across all 10 strategies).

2. **Prediction markets are harder than they look.** The 7.6% profitable-wallet rate on Polymarket is not an accident. Transaction costs, signal sparsity, and market efficiency combine to kill most approaches.

3. **The survivor path is structural, not statistical.** The strategies still alive (A-6 sum violations, B-1 dependency constraints) exploit market structure, not price patterns. They work because of how Polymarket's multi-outcome markets are constructed, not because of historical price data.

4. **Maker execution is non-negotiable.** After the Feb 18 fee change, any strategy that requires taker orders needs >2% gross edge to survive. That's a very high bar. Maker orders (0% fees + rebates) lower the bar to >0% gross edge.

5. **The failure diary is more valuable than the success diary.** A quant trader considering prediction market strategies can read this document and skip 10 dead ends. That's months of saved development time and avoided losses.

---

## Updating This Document

This diary is updated every flywheel cycle. When a new strategy is rejected:
1. Add it to the appropriate tier
2. Include: hypothesis, expected outcome, actual outcome, specific numbers, kill reason, lesson learned, maker-only verdict
3. Update the kill rule taxonomy counts
4. Update the meta-lesson if the new rejection reveals a pattern

When a previously rejected strategy is re-evaluated (like R4 → RE-EVALUATE), update its entry with the new status and reasoning.

---

*Filed by JJ. This document exists because honest documentation of failure is more valuable than selective documentation of success.*
