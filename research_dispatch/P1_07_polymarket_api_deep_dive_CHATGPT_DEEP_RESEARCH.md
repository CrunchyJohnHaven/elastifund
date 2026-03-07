# P1-07: Polymarket CLOB API — Order Book Analysis & Execution Edge
**Tool:** CHATGPT_DEEP_RESEARCH
**Status:** READY
**Expected ARR Impact:** +5-15% (execution improvement)

## Prompt for ChatGPT Deep Research

```
I'm building an automated trading bot for Polymarket's CLOB (Central Limit Order Book). I need deep technical research on:

1. POLYMARKET CLOB ARCHITECTURE:
   - How does the order matching engine work?
   - What are the fee tiers (maker vs taker)?
   - What is typical bid-ask spread by market category?
   - How does the NegRisk framework work?
   - What are the API rate limits?

2. ORDER EXECUTION STRATEGY:
   - Maker orders (limit orders) vs taker orders (market orders)
   - What fill rate can a retail bot expect on maker orders?
   - Optimal order placement: how far from mid-price to place limit orders?
   - Should we use IOC (immediate-or-cancel) or GTC (good-til-cancel)?
   - How to minimize slippage on a $2-$25 order?

3. MARKET MICROSTRUCTURE:
   - What is the typical order book depth on Polymarket by market type?
   - Are there market makers providing liquidity? Who are the major participants?
   - What is the typical time-to-fill for different order sizes?
   - Is there a pattern to when markets are most liquid (time of day, day of week)?

4. TECHNICAL IMPLEMENTATION:
   - Polymarket API documentation for order placement
   - WebSocket vs REST for price monitoring
   - How to implement real-time order book monitoring
   - Best practices for order management and position tracking

5. COMPETITIVE LANDSCAPE:
   - What other automated trading bots operate on Polymarket?
   - What strategies do professional market makers use?
   - Is there evidence of front-running or MEV on Polymarket?
   - How have API changes affected bot performance?

6. REGULATORY:
   - Current US regulatory status of Polymarket
   - CFTC position on prediction markets
   - Any legal risks for automated trading on Polymarket?

Provide specific numbers, API endpoints, and implementation recommendations.
```
