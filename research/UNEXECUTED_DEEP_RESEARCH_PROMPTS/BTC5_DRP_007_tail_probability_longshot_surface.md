---
id: BTC5_DRP_007
title: Tail Probability and Longshot Mispricing Across Polymarket, Kalshi, and Alpaca
tool: CHATGPT_DEEP_RESEARCH
priority: P0
status: READY
created: 2026-03-23
---

# Tail Probability and Longshot Mispricing Across Polymarket, Kalshi, and Alpaca

## Context

The current repo already explored several structural-arbitrage surfaces and formally
killed A-6 and B-1 after zero-density evidence. That matters because we do NOT want
another prompt that simply re-asks the market for a dead edge.

What is still open is a different class of question:

**Are there specific contract families where unlikely outcomes happen more often than
the market price implies, or where tail probabilities are systematically misread by
participants, and can that be exploited with disciplined small-size convex bets or
paired hedges?**

This repo already has components that could absorb a good answer:

- `bot/lmsr_engine.py` for alternate pricing anchors
- `bot/jj_live.py` for calibrated event-market routing
- `bot/kalshi_intraday_parity.py` and `bot/cross_platform_arb.py` for cross-venue comparison
- `bot/proof_types.py` and `bot/promotion_manager.py` for proof-carrying promotion
- `docs/architecture/promotion_ladder.md` and `docs/architecture/intelligence_harness.md`
  for gates and replay discipline

What is missing is a mathematically serious answer about low-probability bins,
favorite-longshot bias, resolution-lag convexity, and whether Alpaca-tradable
instruments can act as reference or hedge markets for prediction-market tails.

## Core Question

Find the most credible tail-probability edge that can start small, be falsified
quickly, and scale if it survives proof.

This may come from:

- favorite-longshot bias in prediction markets
- discrete-threshold / tie-band convexity
- manual-resolution lag and stale near-certain pricing
- cross-venue disagreement on rare outcomes
- options-implied or market-implied probabilities visible through Alpaca-linked data
- public official data that sharpens tail priors

If no such edge survives realistic assumptions, say so.

## Research Questions

1. **Where are tails systematically mispriced?**
   Identify concrete market classes where the tails are likely wrong:
   - very low-probability YES outcomes
   - very high-probability NO outcomes
   - threshold contracts with discrete rule convexity
   - manual or delayed-resolution markets
   - event families where crowd behavior overpays for vivid narratives

2. **Does favorite-longshot bias exist here in a tradeable way?**
   Not in theory, but net of:
   - fees
   - spread
   - fill uncertainty
   - resolution rules
   - capital lockup
   Determine whether the bias is strongest on Polymarket, Kalshi, or in cross-venue
   comparison, and in which categories.

3. **Can Alpaca improve tail calibration?**
   Determine whether Alpaca-accessible market data or tradable instruments help with:
   - extracting options-implied probabilities
   - reading equity / crypto / ETF reactions as priors
   - hedging directional exposure while holding convex prediction-market tails
   If Alpaca is not useful here, say so bluntly.

4. **What mathematics best handles tiny-tail sample sizes?**
   We need methods that do not hallucinate certainty from sparse data.
   Compare:
   - Beta-Binomial and hierarchical Bayes shrinkage
   - isotonic or beta calibration
   - extreme-bin calibration curves
   - survival / hazard models for resolution lag
   - robust Kelly under probability uncertainty

5. **What is the right trade construction?**
   Compare:
   - tiny convex outright positions
   - tail baskets
   - prediction-market plus Alpaca hedge
   - near-certain stale-quote sniping
   - threshold/tie-band constructions
   Which structure maximizes expected log growth without unacceptable blow-up risk?

6. **What should be killed immediately?**
   Explicitly identify tail ideas that sound seductive but are probably dead:
   - lottery-ticket outcome hunting without calibration
   - manual-resolution markets with unbounded dispute risk
   - options-transfer fantasies that cannot map cleanly to prediction contracts

## Formulas Required

Provide explicit formulas or primary-source references for:

- **Bayesian tail posterior**
  `posterior = Beta(alpha + wins, beta + losses)` or hierarchical equivalent

- **Miscalibration score by probability bin**
  `bin_error = observed_frequency - implied_probability`

- **Brier / log loss / ECE for extreme bins**
  with special treatment for sparse tails

- **Robust Kelly under uncertainty**
  e.g. using lower-bound probability:
  `f_robust = max(0, (b * p_lower - q_upper) / b)`
  or a better uncertainty-adjusted equivalent

- **Resolution-lag EV**
  `EV = p_resolution * (1 - entry_price) - (1 - p_resolution) * entry_price - carry_cost`

- **Tail basket EV**
  `EV_basket = sum_i w_i * EV_i - correlation_penalty - fee_drag`

- **Hedge-adjusted tail EV**
  prediction-market payoff minus hedge cost and basis risk

## Measurable Hypotheses

The research must test these or stronger replacements:

H1. At least one low-probability or high-probability contract family shows repeatable
    miscalibration of at least 2-3 percentage points after shrinkage and cost stress.

H2. At least one tail edge survives realistic execution and resolution-risk assumptions
    with positive expected value and acceptable capital velocity.

H3. A robust-Kelly or lower-confidence sizing scheme materially outperforms naive
    fixed sizing for these tail trades.

H4. Alpaca-linked reference data or hedges either materially improve the tail setup
    or are not worth the extra architecture; the research must decide.

H5. If the apparent longshot edge disappears after hierarchical shrinkage, spread
    stress, or rule review, it should be explicitly rejected.

## Required Deliverables

Return all of the following:

1. A ranked list of the top 10 tail-mispricing families with:
   - mechanism
   - venue
   - horizon
   - estimated recurrence
   - capacity
   - required data
   - honest P(works)

2. A "best first tail experiment" with:
   - contract family
   - exact entry logic
   - exact exit / hold-to-resolution logic
   - size logic
   - kill condition after the first small sample

3. A calibration plan:
   - minimum sample size for extreme bins
   - best shrinkage method
   - confidence-interval method
   - how to avoid fooling ourselves

4. A hedge verdict:
   - whether Alpaca should be used as hedge, truth source, both, or neither

5. A repo-mapped implementation backlog with suggested modules and artifacts

## Failure Modes To Address Explicitly

- Sparse-sample overconfidence
- Contract-rule mismatch across venues
- Illiquid tails that never fill
- Manual-resolution or dispute risk
- Convexity that looks great in theory but fails under carry/lockup
- Data snooping from hand-picked dramatic outcomes

## Direct Repo Integration Targets

- `bot/lmsr_engine.py`
- `bot/jj_live.py`
- `bot/kalshi_intraday_parity.py`
- `bot/cross_platform_arb.py`
- `bot/proof_types.py`
- `bot/promotion_manager.py`
- `docs/architecture/promotion_ladder.md`
- `docs/architecture/intelligence_harness.md`
- Potential new modules under `signals/` or `strategies/` for tail calibration

## Hard Constraints

- No cheating via hindsight-labeled examples
- No private data requirements for the first phase
- No recommendation that depends on giant capital or leverage fantasy
- If the true answer is "the tails are not mispriced enough," say that clearly
