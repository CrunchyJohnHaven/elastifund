---
id: BTC5_DRP_004
title: One-Sided Regime Detection for Prediction-Market Candle Contracts
tool: CLAUDE_DEEP_RESEARCH
priority: P0
status: READY
created: 2026-03-09
---

# One-Sided Regime Detection for Prediction-Market Candle Contracts

## Context

The BTC5 maker bot has a `session_guardrail_reason()` function that can suppress or
tighten quoting for weaker directions based on recent fill history. Current logic uses
a simple fill-count and average-PnL comparison between UP and DOWN fills over a
configurable lookback. When one direction has a strong enough edge, the weaker
direction gets tighter max buy prices (quote tightening).

Live evidence strongly supports DOWN as the dominant direction: 41 fills / +$72.40
vs 15 UP fills / +$19.39. The question is whether the bot should go further and
suppress UP entirely in certain regimes, or whether the current soft tightening is
the right approach.

## Research Questions

1. **Regime detection methods for binary outcome sequences**: What statistical
   methods are appropriate for detecting persistent one-sided regimes in sequences
   of binary outcomes? Consider:
   - CUSUM (cumulative sum) charts
   - Bayesian changepoint detection
   - Hidden Markov Models with 2-3 states
   - Simple exponential moving average of direction outcomes
   Which method has the best tradeoff of detection speed vs false positive rate
   for sample sizes of 20-100 fills?

2. **Optimal suppression policy**: Given a detected regime, should the bot:
   a) Fully suppress the weaker direction (0 quotes)
   b) Tighten the weaker direction to very defensive prices only
   c) Reduce position size on the weaker direction
   d) Shorten the fill window for the weaker direction
   What is the expected PnL impact of each policy under realistic regime
   persistence assumptions?

3. **Regime persistence in BTC 5-min candles**: How long do directional regimes
   typically persist? If BTC is in a "down candle" regime (>55% down candles),
   what is the expected number of candles before reversion to 50/50? This determines
   how aggressively to act on regime detection.

4. **False regime detection cost**: What is the cost of incorrectly detecting a
   regime (suppressing a direction that is actually 50/50)? How many profitable
   fills are lost per false positive? Given the asymmetric payoff structure
   (cheap tokens pay more when they win), is it better to be conservative
   (slow to suppress) or aggressive (fast to suppress)?

5. **Adaptive vs fixed thresholds**: Should the regime detection threshold adapt
   to realized volatility of the direction ratio, or is a fixed threshold
   (e.g., >60% of recent fills in one direction) robust enough?

## Formulas Required

- **CUSUM statistic**: S_n = max(0, S_{n-1} + (x_n - k)) where x_n = 1 if
  DOWN wins, 0 otherwise, and k is the reference value (typically 0.5 for
  50/50 null). Signal when S_n > h (threshold).
  Specify optimal k and h for the BTC5 regime (ARL₀ ≥ 50, ARL₁ ≤ 10 at
  p_down = 0.65).

- **Bayesian posterior**: P(regime = DOWN | data) using Beta(α, β) prior on
  p_down. After n fills with d DOWN wins:
  P(p_down > 0.5 | d, n) = 1 - I_{0.5}(α + d, β + n - d)
  where I is the regularized incomplete beta function.

- **Expected cost of suppression error**:
  E[cost | false_suppress] = E[fills_lost] × E[pnl_per_fill | direction=UP]
  × E[regime_duration_in_windows]

- **HMM state probability**: Forward algorithm for P(state_t = "one-sided" | obs_{1:t})
  with transition matrix [[1-p, p], [q, 1-q]] and emission model Bernoulli(p_down_state).

## Measurable Hypotheses

H1: A CUSUM detector with k=0.5, h=4 detects the current DOWN regime within
    15 fills of regime onset, with <5% false positive rate on 50/50 data.

H2: Full UP suppression during detected DOWN regimes improves net PnL by >$0.50
    per 20 windows compared to the current soft-tightening approach.

H3: DOWN regimes in BTC 5-min candles persist for a median of >40 candles
    (>3 hours) before reverting, making regime detection actionable.

H4: The Bayesian posterior approach (Beta prior, threshold at P(p_down>0.55)>0.90)
    produces fewer false suppressions than CUSUM but detects later by 5-10 fills.

H5: Reducing weaker-direction position size to 50% (instead of full suppression)
    captures >70% of the PnL improvement with <30% of the missed-fill cost.

## Failure Modes

- **Overfitting to recent regime**: The current DOWN dominance may be a temporary
  BTC spot regime (March 2026 bearish drift). If BTC enters a bullish period,
  an overtrained suppression policy will miss UP fills. Specify safeguards.
- **Small sample detection**: With 56 total fills, regime detection statistics
  have wide confidence intervals. Specify minimum sample sizes for each method.
- **Latency of detection**: If regime detection takes 30+ fills to trigger, and
  regimes last ~50 fills, the bot only benefits for the last 20 fills. Quantify
  the detection-to-benefit window.
- **Asymmetric payoff interaction**: Suppressing UP in a DOWN regime means missing
  the occasional high-paying UP fill (cheap UP token pays well when it wins).
  The analysis must account for this convexity.

## Direct Repo Integration Targets

- `bot/btc_5min_maker.py`: `session_guardrail_reason()` — replace or augment with
  formal regime detector
- `bot/btc_5min_maker.py`: `BTC5Config` — add `regime_detection_method`,
  `regime_suppression_policy`, `regime_cusum_h`, `regime_cusum_k` fields
- `bot/btc_5min_maker.py`: `BTC5Db` — add `regime_state` column to decisions table
  for offline analysis
- `scripts/btc5_hypothesis_lab.py` — add regime-conditional hypothesis families
- `scripts/btc5_regime_policy_lab.py` — extend with formal regime detection backtests
