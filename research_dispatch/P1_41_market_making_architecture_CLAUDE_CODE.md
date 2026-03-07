# P1-41: Informed Market-Making Bot Architecture
**Tool:** CLAUDE_CODE
**Status:** READY (depends on P1-30 research completion for strategy parameters)
**Priority:** P1 — Post-fee landscape favors makers. OpenClaw earned $115K/week as market maker.
**Expected ARR Impact:** New revenue stream — potentially 2-5× prediction-only strategy

## Background
Post-Feb 2026 Polymarket fee changes, taker fees eat 1-3% of edge. Market makers (limit orders) pay 0% fees and earn the spread. This is the dominant profitable strategy on Polymarket per competitive research.

The key insight: we can combine our LLM probability estimates with market making to create an "informed market maker" — quoting tighter spreads on the side we believe is correct, wider on the side we think is wrong.

## Task

Build an informed market-making module alongside the existing prediction strategy:

1. **Core market-making logic:**
   ```python
   class InformedMarketMaker:
       def __init__(self, base_spread: float = 0.04, max_inventory: int = 20):
           self.base_spread = base_spread
           self.max_inventory = max_inventory

       def compute_quotes(self, market_price: float, claude_estimate: float,
                         current_inventory: dict) -> dict:
           """Generate bid/ask quotes biased by Claude's estimate.

           If Claude thinks YES is underpriced:
             - Tighter bid (more aggressive buying YES)
             - Wider ask (less aggressive selling YES)
           If Claude thinks YES is overpriced:
             - Wider bid (less aggressive buying YES)
             - Tighter ask (more aggressive selling YES)
           """
           bias = claude_estimate - market_price  # positive = YES underpriced

           # Asymmetric spread
           half_spread = self.base_spread / 2
           bid = market_price - half_spread + (bias * 0.3)  # shift bid toward estimate
           ask = market_price + half_spread + (bias * 0.3)  # shift ask toward estimate

           # Inventory skew: if we hold too much YES, lower bid / raise ask
           yes_inventory = current_inventory.get("yes", 0)
           no_inventory = current_inventory.get("no", 0)
           inventory_skew = (yes_inventory - no_inventory) * 0.005
           bid -= inventory_skew
           ask -= inventory_skew

           # Clamp to valid range
           bid = max(0.01, min(bid, 0.99))
           ask = max(0.01, min(ask, 0.99))

           return {"bid": round(bid, 2), "ask": round(ask, 2),
                   "spread": round(ask - bid, 4)}
   ```

2. **Market selection for MM:**
   - Only make markets on high-liquidity events ($10K+ daily volume)
   - Prefer markets near 50/50 (widest natural spread, most trading activity)
   - Avoid markets about to resolve (last 24 hours — inventory risk)
   - Start with politics and economics categories (our best-calibrated)

3. **Risk controls:**
   - Max inventory per market: $10 (one side)
   - Max total inventory: $50 across all markets
   - Kill switch: cancel all orders if portfolio drops 20%
   - Order refresh: cancel and re-quote every cycle (5 min) to track price changes

4. **Revenue model:**
   - Spread capture: 2-4¢ per round trip on a $2 position = $0.04-0.08
   - At 20 round trips/day = $0.80-$1.60/day = $24-48/month
   - PLUS: directional edge from informed quotes (when Claude is right, we accumulate the winning side)
   - Combined: potentially $50-100/month at $75 capital

5. **Coexistence with prediction strategy:**
   - Prediction strategy: high-conviction directional bets (>15% YES edge, >5% NO edge)
   - Market making: low-conviction spread capture (markets where Claude edge is 2-10%)
   - Shared capital pool but separate position tracking
   - Capital allocation: 60% prediction, 40% market making

## Files to Create
- NEW: `src/market_maker.py` — InformedMarketMaker class
- NEW: `src/order_manager.py` — limit order placement, cancellation, tracking
- MODIFY: `improvement_loop.py` — add MM cycle alongside prediction cycle
- MODIFY: `src/broker/` — add limit order support (place, cancel, amend)

## Expected Outcome
- Dual-strategy bot: prediction + market making
- Revenue diversification (not 100% dependent on directional bets)
- Better capital utilization (MM uses capital that prediction strategy leaves idle)
- Foundation for scaling beyond $75 (MM scales more linearly with capital)
