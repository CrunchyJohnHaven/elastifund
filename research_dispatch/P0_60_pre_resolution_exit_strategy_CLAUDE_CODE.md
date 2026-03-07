# P0-60: Pre-Resolution Exit Strategy & Position Management
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Currently no way to exit positions before resolution. Dead capital problem.
**Expected ARR Impact:** +20-40% from capital velocity improvement

## Problem
Currently the bot enters positions and WAITS for resolution. No exit strategy. Problems:
1. If our estimate changes (new information), we're locked in
2. If a position is unrealized profit, we can't take profit early
3. Capital is frozen in slow-resolving markets
4. No loss-cutting: if we're clearly wrong, we ride it to zero

On Polymarket, you CAN sell positions before resolution by placing a sell order on the CLOB. This is equivalent to exiting a trade early.

## Task

1. **Position re-evaluation system:**
   ```python
   class PositionManager:
       def reevaluate_positions(self, positions: list, current_prices: dict):
           """Every cycle, re-evaluate all open positions."""
           for pos in positions:
               current_price = current_prices[pos.market_id]
               entry_price = pos.entry_price
               current_edge = self.compute_current_edge(pos, current_price)

               # Case 1: Edge has disappeared or reversed
               if current_edge < 0.02:  # edge below 2%
                   self.recommend_exit(pos, reason="edge_eroded")

               # Case 2: Significant unrealized profit (>30% of position)
               unrealized_pnl = self.compute_unrealized_pnl(pos, current_price)
               if unrealized_pnl > pos.size * 0.30:
                   self.recommend_exit(pos, reason="take_profit")

               # Case 3: Position is old and capital is needed
               age_hours = (now - pos.entry_time).total_seconds() / 3600
               if age_hours > 168 and unrealized_pnl < pos.size * 0.05:  # 7 days, <5% gain
                   self.recommend_exit(pos, reason="capital_recycling")

               # Case 4: Stop loss (position down >50%)
               if unrealized_pnl < -pos.size * 0.50:
                   self.recommend_exit(pos, reason="stop_loss")
   ```

2. **Exit execution:**
   - Place sell limit order at current price (or slightly better)
   - If not filled in one cycle (5 min), adjust price
   - Log exit reason, P&L, and time held

3. **Re-investment queue:**
   - When a position is exited, freed capital goes back to the pool
   - Immediately scan for new opportunities to deploy the capital
   - Priority: fast-resolving markets with high edge

4. **Dynamic position sizing adjustment:**
   - If market price has moved in our favor: our effective edge is now SMALLER
   - If market price has moved against us: our effective edge is LARGER (but we may be wrong)
   - Re-evaluate Kelly position size. Consider adding to winning positions (pyramid) or reducing losing positions

5. **Paper trading integration:**
   - For paper trading: simulate exits by marking positions as "exited at [price]"
   - Track: avg hold time, exit reasons, P&L from early exits vs hold-to-resolution
   - Compare: "what would P&L be if we always held to resolution?" vs "with exit strategy"

## Files to Modify
- NEW: `src/position_manager.py`
- MODIFY: `src/paper_trader.py` — add position re-evaluation every cycle
- MODIFY: `src/broker/` — add sell order functionality
- MODIFY: `improvement_loop.py` — run position review in each cycle

## Expected Outcome
- Active position management instead of buy-and-hold-to-resolution
- Capital recycled faster (shorter effective hold times)
- Losses cut before they become full position losses
- Profits locked in when edge erodes
- Dramatically improved capital velocity at $75 scale
