# Tweet 09 — Volatility Regime Mismatch Autopsy
**Pillar:** Strategy Autopsies
**Priority:** Medium (detailed failure analysis, educational)

---

Strategy autopsy: Volatility Regime Mismatch

Hypothesis: When implied vol (from prediction market spread) diverges from realized vol (from Binance), there's a tradeable mispricing.

Result: 32.35% win rate across 34 signals.

It looked clean in-sample. Three reasons it failed:

1. 34 signals is statistically meaningless (needed 300+ for validation)
2. Positive EV pre-cost collapsed to negative post-taker-fee (1.56%)
3. Vol regime detection lagged — by the time we identified the regime, the market had repriced

Lesson: if your edge requires taker execution on crypto markets, you need >1.5% raw edge just to break even.

---

**Notes:** Detailed strategy autopsy. The specific numbers (32.35%, 34 signals, 1.56% fee) add credibility. Shows we test rigorously and publish honest results.
