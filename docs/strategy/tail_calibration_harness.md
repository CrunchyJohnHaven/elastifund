# Tail Calibration Harness

**Status:** Draft harness spec for the tail-mispricing line of research.
**Scope:** Prediction-market tails, low-probability contract families, and Alpaca-anchored reference/hedge checks.
**Architecture fit:** This harness is a concrete application of the proof-carrying kernel and promotion ladder. It does not create a parallel approval path.

## 1. Thesis

The thesis is narrow on purpose: some tail contracts may be mispriced because participants underweight rare outcomes, misread discrete rule thresholds, or price resolution lag incorrectly. The edge only counts if it survives fees, rule parsing, and realistic fills.

Promotable tail ideas must be framed as one of these:

- a small convex outright tail bet
- a tail basket with pre-registered bins
- a prediction-market plus Alpaca hedge/reference package
- a stale near-certain quote capture

If the edge disappears after cost stress or rule review, that is a valid result and should be recorded as such.

## 2. Pre-Registered Bins

Bins are fixed before backtesting and never re-cut after seeing outcomes.

| Bin | Implied probability |
|---|---|
| B0 | `0.00 <= p < 0.01` |
| B1 | `0.01 <= p < 0.03` |
| B2 | `0.03 <= p < 0.05` |
| B3 | `0.05 <= p < 0.10` |
| B4 | `0.10 <= p < 0.20` |
| B5 | `0.20 <= p < 0.40` |
| B6 | `0.40 <= p < 0.60` |
| B7 | `0.60 <= p < 0.80` |
| B8 | `0.80 <= p < 0.90` |
| B9 | `0.90 <= p < 0.95` |
| B10 | `0.95 <= p < 0.97` |
| B11 | `0.97 <= p < 0.99` |
| B12 | `0.99 <= p <= 1.00` |

Rules for the bins:

- Every market is assigned to exactly one bin at entry time.
- No bin merge, split, or relabel is allowed after outcomes are known.
- Bin-level claims need either enough direct sample or a shrinkage-backed posterior with a documented uncertainty bound.

## 3. Gates

### 3.1 Fee Gate

A tail thesis only survives if its expected value is still positive after all trading costs:

`edge_net = p_resolved * payout - entry_price - fees - spread - slippage - carry - hedge_cost`

Hard requirements:

- Use the venue-specific fee schedule, not a generic placeholder.
- Stress fees upward before promotion.
- If doubling fees flips the edge negative, the thesis stays in research.

### 3.2 Rule Gate

The contract rules must be pinned before entry.

- Resolution source must be explicit.
- Threshold language must be parsed into a deterministic outcome map.
- Dispute or manual-resolution risk must be documented.
- If the rule text admits two plausible outcomes, the bin is not promotable.

This gate is where the harness prevents pretty backtests from becoming live ambiguity.

### 3.3 Fill Gate

Tail edges are often thin. That makes execution part of the thesis, not an afterthought.

- Shadow or paper logic must log expected price, expected fill, actual fill, and latency.
- Micro-live promotion must satisfy the ladder's execution floor: fill rate above 30%, median slippage below 1%, and p99 signal-to-order latency below 2000ms.
- If the edge only exists at prices that never fill, it is not a tradable edge.

For this repo, the relevant promotion-ladder floor is the micro-live execution gate in `docs/architecture/promotion_ladder.md`, with the live execution-quality pass as the supporting artifact.

## 4. Kill Rules

The harness should kill or freeze a tail thesis when any of the following happen:

- The thesis depends on post-hoc binning or a changed probability cutoff.
- Rule interpretation changes after entry.
- Fees, spread, or carry erase the edge under stress.
- Fill rate collapses or slippage consumes a material share of the expected edge.
- The tail posterior stays non-positive after shrinkage in consecutive review windows.
- Alpaca reference data is stale or unavailable and the thesis was relying on it as a required anchor.
- The market becomes too ambiguous to map cleanly to the registered bin.

The kill condition must be falsifiable and written into the thesis before any live capital is risked.

## 5. Alpaca Role

Alpaca is a reference anchor, not the resolution oracle.

Use Alpaca for:

- fast external truth-checks on the underlying asset or related instrument
- options-implied or market-implied probability context when available
- hedge leg construction when the tail trade has a clean mapped proxy

Do not use Alpaca for:

- overriding contract rules
- deciding the market outcome
- hiding a weak prediction-market thesis behind an unrelated proxy

If Alpaca improves calibration, great. If it only adds complexity, the harness should say so.

## 6. Promotion Expectations

This harness should promote only through the repo's proof-carrying path:

1. Evidence is collected.
2. A thesis is written with a named kill condition.
3. The thesis is replayed against the pre-registered bins with temporal holdout and cost stress.
4. Rule, fee, and fill gates pass.
5. Shadow execution clears the ladder floor of 7 calendar days or 100 shadow decisions, whichever comes later.
6. Micro-live proves the fills and slippage still work under real execution pressure.
7. Only then does the strategy become a candidate for larger sizing under the promotion ladder.

Minimum proof expectation:

- replay or backtest evidence with cost stress
- off-policy or holdout evidence
- a world-league comparison against simple baselines
- execution-quality evidence from shadow or micro-live
- a durable artifact trail under `reports/strategy_promotions/{strategy_id}/`

For micro-live promotion, the harness should respect the ladder's Stage 3 floor: at least 50 filled trades, at least 14 calendar days, profit factor above 1.05, and the binomial win-rate gate described in `docs/architecture/promotion_ladder.md`.

If the best conclusion is `REJECT ALL`, that still counts as a good harness outcome.

## 7. Repo Mapping

This work belongs in the same ownership lanes as the rest of the proof-carrying stack:

- signal transforms and binning logic belong in `signals/`
- entry policy and promotion policy belong in `strategies/`
- execution, gating, and size enforcement remain under the kernel and promotion layers

The first helper modules already landed in the expected locations:

- `signals/tail_bins.py` for pre-registered bins, posterior summaries, and robust Kelly sizing
- `signals/fee_models.py` for venue-specific fee and breakeven math
- `signals/resolution_risk.py` for rule objectivity and settlement-risk scoring
- `strategies/kalshi_longshot_fade.py` for the first objective-rule longshot-fade policy

If this lane expands meaningfully, future refactors can group related helpers into a dedicated subpackage, but the ownership boundary should stay the same.

The goal is not a new lane. The goal is a tail-specific harness that plugs into the existing kernel cleanly.
