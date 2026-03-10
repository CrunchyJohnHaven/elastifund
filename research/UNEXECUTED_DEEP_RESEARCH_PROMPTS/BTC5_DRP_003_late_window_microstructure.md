---
id: BTC5_DRP_003
title: Late-Window Crypto Microstructure on 5-Minute Candle Markets
tool: CLAUDE_DEEP_RESEARCH
priority: P0
status: READY
created: 2026-03-09
---

# Late-Window Crypto Microstructure on 5-Minute Candle Markets

## Context

The BTC5 maker bot trades Polymarket 5-minute BTC candle contracts (UP/DOWN binary
outcomes). It enters at T-10 seconds before window close and cancels unfilled orders
at T-2 seconds. This 8-second execution window sits in a specific microstructural
regime: the Binance BTC spot price is still moving, the candle outcome is partially
but not fully determined, and the Polymarket CLOB reflects a mix of informed and
uninformed flow.

Current evidence shows DOWN direction strongly outperforms UP (41 fills / +$72.40
vs 15 fills / +$19.39). The best price bucket is <0.49 (19 fills / +$56.30).

## Research Questions

1. **Terminal price dynamics in 5-min BTC candles**: What is the distribution of
   BTC price movement in the last 10 seconds of a 5-minute candle? Is there
   mean reversion (price returns toward open) or momentum (price extends away
   from open)? How does this distribution change conditional on the candle being
   currently UP vs DOWN?

2. **Information arrival rate near close**: What fraction of the "surprise" in a
   5-minute candle outcome arrives in the last 10 seconds? The last 30? The last 60?
   This determines how much residual uncertainty exists when the bot quotes.

3. **DOWN dominance explanation**: Why would DOWN direction outperform UP on
   BTC 5-minute candles? Candidate explanations:
   a) Structural bias in BTC spot (more down candles than up in recent regime)
   b) Asymmetric pricing on Polymarket (DOWN tokens systematically underpriced)
   c) Different liquidity/book depth for UP vs DOWN tokens
   d) Behavioral bias: participants overweight UP outcomes

4. **Price bucket edge distribution**: Why does <0.49 (lower implied probability)
   produce better PnL than higher-priced buckets? Is this a convexity effect
   (cheap options pay more when they win) or a calibration effect (these events
   are genuinely underpriced)?

5. **Optimal entry timing**: Is T-10 the right entry time, or would T-15 or T-7
   materially change the fill rate and PnL? What is the tradeoff curve between
   earlier entry (more fill time, less information) and later entry (less fill
   time, more information)?

## Formulas Required

- **Terminal price distribution**: Let X(t) = BTC_spot(t) - BTC_open for a 5-min
  candle. Model X(300-s) | X(300-10) as the residual. What is the variance
  of X(300) - X(290)?
  σ²_residual = σ²_5min × (10/300) if Brownian, but likely non-Brownian near
  terminal. Derive or cite the empirical scaling factor.

- **Conditional win probability**: P(final_direction = D | current_delta, time_left)
  Under geometric Brownian motion with drift μ and vol σ:
  P(close > open | current = open + δ, t_left) =
    Φ((δ + μ·t_left) / (σ·√t_left))

- **Direction-conditional expected PnL**:
  E[PnL | direction=D, price=p] = P(win|D) × (1-p) × shares - P(loss|D) × p × shares

- **Optimal timing**: argmax_t { P(fill|entry_at_t) × E[PnL|fill, entry_at_t] }
  balancing information gain against fill probability decay.

## Measurable Hypotheses

H1: The variance of BTC price in the last 10 seconds of a 5-minute candle is
    <5% of the total 5-minute candle variance (supporting late entry as low-risk).

H2: DOWN candles on BTC in recent months (Jan-Mar 2026) are ≥52% of all
    non-flat candles, partially explaining the direction bias.

H3: Moving entry from T-10 to T-15 increases fill rate by >20% but decreases
    per-fill PnL by >10% (more fills, each less informed).

H4: The <0.49 bucket edge is primarily a convexity effect: at 0.45 price,
    winning pays 0.55 per share vs risking 0.45, a 1.22:1 reward-to-risk
    ratio that compounds small calibration edges.

H5: The DOWN/UP PnL gap narrows to <$5 per 20 fills if you restrict to windows
    where |delta| > 0.001 (i.e., the gap is partly driven by low-delta noise).

## Failure Modes

- **Non-stationarity**: BTC microstructure changes with volatility regime. Results
  from Jan-Mar 2026 may not hold in a different vol regime. Specify how to detect
  regime shifts.
- **Binance vs Polymarket clock sync**: The bot reads Binance spot and trades
  Polymarket. If there is clock drift, the T-10 entry is not actually T-10 in
  Binance's canonical time. Specify how to measure and correct for this.
- **Sample size**: 56 fills is small. Many of these hypotheses need >200 fills
  for statistical significance. Specify the sample size required for each hypothesis.

## Direct Repo Integration Targets

- `bot/btc_5min_maker.py`: `ENTRY_OFFSET_SECONDS` — currently hardcoded at 10,
  should become configurable with research-informed default
- `bot/btc_5min_maker.py`: `session_guardrail_reason()` — add direction-conditional
  timing offsets
- `bot/btc_5min_maker.py`: `_probe_mode()` — tighten probe conditions using
  terminal distribution knowledge
- `scripts/btc5_hypothesis_lab.py` — add hypothesis families for timing variants
- New analysis: `scripts/btc5_terminal_microstructure.py` — offline analysis of
  Binance 1-second klines to characterize terminal distribution
