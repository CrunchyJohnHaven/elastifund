# P1-43: Cross-Platform Arbitrage Monitoring (Polymarket vs Kalshi vs Others)
**Tool:** CHATGPT_DEEP_RESEARCH
**Status:** READY
**Priority:** P1 — Low-hanging fruit if price divergences exist between platforms
**Expected ARR Impact:** +10-30% (risk-free or near-risk-free returns if opportunities exist)

## Background
GPT-4.5 research mentioned Oddpool and PolyRouter as cross-platform arbitrage signal detectors. With Polymarket's US relaunch (Dec 2025) and Kalshi's CFTC-regulated platform, there may be persistent price differences between platforms for identical or near-identical events. This is different from within-Polymarket arbitrage (Strategy C, which we deprioritized due to latency). Cross-platform arb may persist longer because it requires capital on both platforms.

## Research Questions

```
Research cross-platform prediction market arbitrage opportunities as of March 2026:

1. PLATFORM LANDSCAPE:
   - Which prediction market platforms are currently operating in the US? (Polymarket, Kalshi, PredictIt, Metaculus, Manifold, others?)
   - Which platforms share overlapping markets? (e.g., "Will the Fed cut rates in June?" on both Polymarket and Kalshi)
   - What are the fee structures on each platform?
   - What are the liquidity levels on each platform vs Polymarket?

2. PRICE DIVERGENCE:
   - Do the same events trade at different prices across platforms? How often?
   - What's the typical divergence? (1%? 5%? 10%?)
   - How long do divergences persist? (seconds? hours? days?)
   - What causes divergences? (different user bases, different fee structures, different liquidity)

3. ARBITRAGE MECHANICS:
   - Can you actually arbitrage across platforms? (different settlement mechanisms, different contract structures)
   - Capital requirements: need funded accounts on multiple platforms simultaneously
   - Settlement risk: one platform resolves YES, another resolves differently?
   - Timing risk: different resolution dates for "same" event?

4. TOOLS:
   - Oddpool (oddpool.com): What does it offer? Is it useful for our strategy?
   - PolyRouter: What is this? API access?
   - Verso: Cross-platform aggregation — details?
   - Are there other cross-platform monitoring tools?
   - Can we build our own price feed aggregator with public APIs?

5. IMPLEMENTATION FEASIBILITY:
   - APIs for Kalshi, Manifold, etc. — documentation and access requirements?
   - Do we need accounts on all platforms? KYC requirements?
   - At $75 capital split across 2-3 platforms — is this viable?
   - Minimum capital for cross-platform arb to cover fees and generate profit?

6. REGULATORY:
   - Any issues with holding accounts on multiple prediction market platforms?
   - Is cross-platform arbitrage explicitly allowed/prohibited on any platform?
   - Tax implications of multi-platform trading?
```

## Expected Outcome
- Map of which platforms share overlapping markets
- Quantified price divergence data (if available)
- Decision: build cross-platform monitoring now, or defer
- If build: architecture for price feed aggregation across platforms
