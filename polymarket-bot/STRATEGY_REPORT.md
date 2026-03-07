# Polymarket Trading Bot — Strategy Analysis Report

> **NOTE:** The primary, up-to-date strategy report is at the project root: `../STRATEGY_REPORT.md`. This file is the original pre-deployment analysis. For latest backtest results, competitive intelligence, academic research integration, and research-driven improvements, see the root-level report.

**Date:** March 2026
**Starting Capital:** $75 USDC
**Infrastructure Cost:** $9–29/month (VPS + API costs)

---

## Strategy A: Weather Arbitrage (NOAA)

### Parameters
- Buy below $0.15, sell above $0.45
- Max $2 per position, 6 cities
- Scan every 2 minutes
- NOAA 48-hour forecast accuracy: ~93%

### Realistic Edge Analysis

**Market availability:** Polymarket runs weather markets sporadically — typically temperature bracket markets for major US cities. At any given time there may be 5–15 active weather outcome buckets across a few cities. These are NOT always available.

**Liquidity:** Weather markets are among the lowest-liquidity markets on Polymarket. Typical volume is $500–$5,000 per market. Order books are thin — $50–$200 of depth at any given price level. With a $2 max position, fills are achievable, but:

- **Maker orders (0% fee):** Fill rate is poor. Estimate 20–40% of limit orders fill before the market moves or resolves.
- **Taker orders (up to 1.56% fee at midpoint):** Guaranteed fill but the fee eats a significant portion of the edge on $2 positions.

**The actual edge:** NOAA is 93% accurate at 48 hours, but Polymarket weather markets typically price obvious outcomes correctly (90°F+ in Miami in July already prices at $0.85+). The mispricing opportunity exists only when:
1. The market is pricing an outcome at <$0.15 that NOAA says is likely (or >$0.85 that NOAA says is unlikely)
2. The forecast shifts between market updates

Realistic mispricing frequency: 1–3 actionable signals per day across all 6 cities.

### Expected Returns

| Metric | Estimate |
|--------|----------|
| Actionable signals/day | 1–3 |
| Avg position size | $2.00 |
| Fill rate (maker orders) | 30% |
| Trades executed/day | 0.3–0.9 |
| Avg edge per trade | 8–15% of position |
| Avg profit per filled trade | $0.16–$0.30 |
| Daily expected profit | $0.05–$0.27 |
| Monthly expected profit | $1.50–$8.10 |
| Annual expected profit | $18–$97 |
| **Annualized ROI** | **24–129%** |

### Honest Assessment

The ROI percentage looks decent, but the absolute dollar returns are tiny: **$1.50–$8.10/month** on $75 capital. This is because position sizes are capped at $2 and opportunities are scarce.

**Re: the viral claim of $38.7K from $150 in one month:** This is almost certainly fabricated or deeply misleading. At $2 max per position with weather markets, you would need ~19,350 winning trades in a month (645/day) with 100% hit rate and ~$2 profit each. Weather markets don't have the volume, liquidity, or frequency to support this. The claim is not credible.

---

## Strategy B: News/Sentiment with Claude AI

### Parameters
- Claude Haiku ($1/$5 per MTok input/output)
- Screen ~50 markets/day
- Trade when Claude's estimate diverges >10% from market price
- Half-Kelly position sizing, max $25/position

### Cost Analysis

| Item | Monthly Cost |
|------|-------------|
| Claude API (50 analyses/day × 30 days) | $5–$12 |
| ~500 tokens input + ~10 tokens output per call | |
| 1,500 calls/month × ~$0.005/call | ~$7.50 |

### Edge Analysis

**AI-assisted prediction accuracy:** Claude (or any LLM) is good at synthesizing publicly available information. On well-known events (elections, Fed decisions), markets are highly efficient — Claude adds little edge. On niche/obscure markets, Claude may identify mispricings, but these are also lower-liquidity.

**Realistic win rate:** 53–58% on binary markets where a signal is generated. This is above breakeven (50% at fair odds) but not dramatically so.

**Signal frequency:** Of 50 markets screened daily, expect 3–8 to show >10% divergence from Claude's estimate. Of those, perhaps 2–5 are genuinely mispriced (the rest are Claude being miscalibrated).

### Expected Returns

| Metric | Estimate |
|--------|----------|
| Markets screened/day | 50 |
| Signals generated/day | 3–8 |
| Trades taken/day | 2–5 |
| Avg position size (half-Kelly) | $5–$15 |
| Win rate | 55% |
| Avg payout on win | 1.8:1 (at 10% mispricing) |
| Expected value per trade | +$0.40–$1.20 |
| Daily expected profit | $0.80–$6.00 |
| Monthly expected profit | $24–$180 |
| Monthly API cost | -$7.50 |
| **Net monthly profit** | **$16.50–$172.50** |
| **Annualized ROI** | **264–2,760%** |

### Honest Assessment

This is the most promising strategy, but the wide range reflects uncertainty. The optimistic case ($172/month) assumes Claude is well-calibrated and markets are inefficient. The pessimistic case ($16/month) is more realistic for early operation. Key risks:

- **Claude calibration:** LLMs are not inherently well-calibrated probability estimators. The bot needs extensive backtesting before trusting Claude's estimates.
- **Capital constraints:** With $75, half-Kelly sizing on a 55% edge limits average position to ~$5–8. You can't take many concurrent positions.
- **Market efficiency:** Polymarket's most liquid markets are already efficiently priced. Edge exists mainly in smaller, niche markets.

---

## Strategy C: Cross-Market Arbitrage (YES + NO < $1.00)

### Parameters
- Scan NegRisk multi-outcome markets
- Look for probability sums ≠ 100%
- Risk-free profit when YES + NO < $1.00

### Edge Analysis

**Theoretical edge:** When a multi-outcome market (e.g., "Who wins the election?") has outcome probabilities summing to less than 100%, you can buy all outcomes and guarantee a profit. Similarly, if YES + NO for a binary market totals less than $1.00, buying both locks in risk-free return.

**Reality check:**
- **Competition:** Professional market makers and arbitrage bots with sub-second latency already monitor these opportunities 24/7. They have funded wallets, co-located infrastructure, and custom smart contracts.
- **Frequency:** On Polymarket, genuine arbitrage opportunities last seconds, not minutes. By the time a retail bot scans and submits orders, the opportunity is gone.
- **Execution risk:** You need both legs to fill atomically. If only one leg fills, you have directional exposure, not arbitrage.
- **Minimum profit:** Typical inefficiency when it exists is 0.1–0.5% — on $75 capital, that's $0.075–$0.375 per opportunity.

### Expected Returns

| Metric | Estimate |
|--------|----------|
| Opportunities detected/day | 0–2 |
| Successfully captured/day | 0–0.5 |
| Avg profit per arb | $0.10–$0.50 |
| Daily expected profit | $0.00–$0.25 |
| Monthly expected profit | $0–$7.50 |
| **Annualized ROI** | **0–120%** |

### Honest Assessment

Cross-market arbitrage is effectively unviable for a retail bot with $75 capital and standard latency. The opportunities exist but are captured by faster, better-capitalized participants within milliseconds. This strategy should be deprioritized.

---

## Bottom Line

### Combined Expected Returns (All Strategies)

| Scenario | Monthly Gross | Monthly Infra Cost | Monthly Net | Annual Net |
|----------|--------------|-------------------|-------------|------------|
| **Pessimistic** | $18 | $16 (VPS $9 + API $7) | +$2 | +$24 |
| **Realistic** | $45 | $20 (VPS $12 + API $8) | +$25 | +$300 |
| **Optimistic** | $150 | $25 (VPS $15 + API $10) | +$125 | +$1,500 |

### Key Metrics

- **Break-even point:** Need ~$20/month in gross profit to cover infrastructure. Achievable in the realistic scenario.
- **Time to double capital:** 3–12 months depending on scenario.
- **ROI timeline:** At the realistic rate ($25/month net), the bot pays for itself immediately and grows capital slowly.

### Honest Verdict

**Is this worth running?**

- **At $9/month VPS (cheapest tier):** Yes, marginally. The Claude AI strategy alone should generate enough to cover costs and produce small profits. But we're talking about $10–30/month in net profit — this is a learning project, not a business.

- **At $29/month VPS:** Risky. You need the optimistic scenario to consistently clear that overhead. At $75 starting capital, the margin of safety is thin.

**Recommendation:**
1. Start with **Strategy B (Claude AI)** only — it has the best risk/reward ratio
2. Run on the **cheapest VPS tier** ($9/month) or even locally first
3. Use **Strategy A (Weather)** as supplemental income, not primary
4. **Skip Strategy C** (arbitrage) — you can't compete with professional market makers
5. Paper trade for at least 2 weeks before committing real capital
6. Set a strict **stop-loss**: if net P&L is negative after 30 days of live trading, shut down and reassess

**The math is clear:** With $75, this bot can potentially pay for its own infrastructure and produce modest returns. It will NOT make you rich. The real value is in learning quantitative trading, API integration, and risk management. Treat infrastructure costs as education expenses, not a business investment.
