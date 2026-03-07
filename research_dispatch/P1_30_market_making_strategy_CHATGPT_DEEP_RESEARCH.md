# P1-30: Market-Making Strategy Research (Post-Fee Landscape)
**Tool:** CHATGPT_DEEP_RESEARCH
**Status:** READY
**Expected ARR Impact:** New revenue stream — potentially higher than prediction-based trading

## Background (from P0-26 research)
Post-Feb 2026 Polymarket fee changes, the emerging winning strategy is market making:
- Post limit orders on both sides, earning spread + maker rebates
- OpenClaw bot earned $115K in one week across 47K trades as automated liquidity provider
- "Execution discipline, not prediction, is the primary source of edge"
- Taker fees create a structural advantage for makers

## Research Questions
```
Research prediction market market-making strategies, specifically for Polymarket:

1. MECHANICS:
   - How does Polymarket's CLOB (central limit order book) work technically?
   - What are maker rebates on Polymarket? Fee structure for limit vs market orders?
   - How does the order book depth look for different market categories?
   - What's the typical bid-ask spread on active markets?

2. STRATEGY:
   - How did OpenClaw bot earn $115K/week? What was the exact strategy?
   - What's a basic market-making algorithm for binary prediction markets?
   - How do you manage inventory risk (accumulating too much of one side)?
   - What spread should you quote? How does it relate to expected volatility?
   - How do you handle information asymmetry (informed traders picking you off)?

3. IMPLEMENTATION:
   - Polymarket API for limit order placement (REST + WebSocket)
   - Latency requirements — do you need co-location?
   - Minimum capital for viable market making
   - Risk controls: max inventory, delta hedging, kill switch

4. COMBINATION:
   - Can we combine our LLM prediction system with market making?
   - Idea: use Claude's estimate to bias our quotes (wider spread on the side we think is wrong)
   - This creates an "informed market maker" — is this viable?

5. COMPETITORS:
   - Who are the major market makers on Polymarket?
   - What percentage of Polymarket volume is market-maker driven?
   - Is the space getting crowded?
```

## Expected Outcome
- Architecture spec for a Polymarket market-making bot
- Decision: pure market-making vs informed market-making (LLM-biased quotes)
- Capital requirements and expected returns
