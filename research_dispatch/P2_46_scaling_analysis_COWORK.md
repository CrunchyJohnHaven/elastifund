# P2-46: Scaling Analysis — How Much Capital Before Edge Erodes?
**Tool:** COWORK
**Status:** READY
**Priority:** P2 — Critical for investor conversations ("how much can the fund manage?")
**Expected ARR Impact:** Indirect — determines fund capacity and investor sizing

## Background
Every strategy has a capacity limit. At some capital level, our trades start moving the market, slippage eats the edge, and returns degrade. For investor conversations, we need to answer: "What's the maximum AUM this strategy can handle?"

Research from P0-26 gives us slippage estimates:
- High-volume politics/crypto: 0.1-0.5% per $1K
- Major US city weather: 0.5-2% per $1K
- Niche/illiquid: 2-10%+ per $1K (untradeable at scale)

## Task

1. **Model returns as a function of capital:**
   - At $75: current projections (no market impact)
   - At $1,000: some orders may not fill at expected prices
   - At $10,000: meaningful slippage on weather/niche markets
   - At $50,000: limited to high-volume markets only
   - At $100,000: may need to be market maker, not taker

2. **For each capital level, estimate:**
   - Number of tradeable markets (liquidity-filtered)
   - Average position size (Kelly-adjusted)
   - Expected slippage per trade
   - Net edge after slippage and fees
   - Expected monthly returns ($ and %)
   - Expected annual ROI

3. **Build a "Returns vs AUM" curve:**
   - X-axis: AUM ($100 to $1M log scale)
   - Y-axis: Annual ROI %
   - Show the curve bending down as capital increases
   - Identify the "sweet spot" (maximum $ returns, not %) — this is likely $50K-$200K

4. **Strategy mix at each capital level:**
   - $75-$500: 100% prediction, flat sizing
   - $500-$5K: prediction + Kelly sizing
   - $5K-$50K: prediction + market making + ensemble
   - $50K-$200K: primarily market making with prediction overlay
   - $200K+: need multi-platform (Kalshi + Polymarket) + more strategies

5. **Output a .docx "Capacity Analysis" with:**
   - Returns vs AUM table
   - "Why returns decrease with scale" explanation (for investors)
   - Recommended fund size: minimum, optimal, maximum
   - How we plan to maintain edge as we scale (multi-model, market making, cross-platform)
   - Honest capacity limit: "This strategy can optimally manage $X to $Y"

## Expected Outcome
- Clear answer to "how much capital can this fund deploy?"
- Returns projections at investor-relevant capital levels ($10K, $50K, $100K)
- Realistic capacity limit for investor materials
- Scaling roadmap: what to build at each capital milestone
