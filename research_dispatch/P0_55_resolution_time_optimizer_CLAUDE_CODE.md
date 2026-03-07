# P0-55: Resolution Time Optimizer — Maximize Capital Velocity
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Capital velocity is the biggest constraint at $75. Faster resolution = more trades = more P&L.
**Expected ARR Impact:** +50-100% (if we can 2× our trade frequency by targeting fast-resolving markets)

## Problem
At $75, we can hold ~35 positions at $2 each. Currently, many positions are on far-future events that won't resolve for weeks or months. That capital is sitting dead. If we targeted markets resolving in 1-7 days instead, we could cycle the same $75 through 4-5× more trades per month.

## Task

1. **Parse resolution dates from Gamma API:**
   ```python
   def get_resolution_timeline(market: dict) -> dict:
       """Extract and categorize resolution timeline.
       Returns:
       {
           "end_date": datetime,
           "hours_to_resolution": 48,
           "category": "fast" | "medium" | "slow" | "unknown",
           "confidence": 0.9  # how confident are we in the end date?
       }
       """
   ```

2. **Capital allocation by resolution speed:**
   - Fast (< 48 hours): Allocate up to 40% of bankroll (high capital velocity)
   - Medium (2-7 days): Allocate up to 40% of bankroll (good balance)
   - Slow (7-30 days): Allocate up to 20% of bankroll (only high-conviction)
   - Very slow (> 30 days): Allocate 0% (skip entirely at our capital level)

3. **Position exit strategy for slow markets:**
   - If a position has been open > 7 days with no resolution in sight, evaluate:
     - Can we sell the position on the order book? (even at a small loss)
     - Is the capital better deployed elsewhere?
   - Implement a "stale position" check: if position age > 7 days AND unrealized P&L < 5%, flag for manual review

4. **Capital velocity tracker:**
   ```python
   def capital_velocity_report() -> dict:
       """Track how efficiently capital is being deployed.
       Returns:
       {
           "avg_position_duration_hours": 72,
           "capital_turns_per_month": 4.2,  # times the full bankroll is recycled
           "idle_capital_pct": 15%,  # cash sitting unused
           "estimated_monthly_trades": 150,
           "vs_target": "+20%"  # compared to target velocity
       }
       """
   ```

5. **Resolution date monitoring:**
   - For each open position, track expected resolution date
   - Alert when positions are approaching resolution (last 24 hours)
   - Alert when positions are past expected resolution (may indicate market extension)

6. **Priority queuing by capital velocity impact:**
   - When choosing between two signals with similar edge:
     - Prefer the one resolving sooner (higher capital velocity)
     - Weighted score: `priority = edge * (1 / sqrt(hours_to_resolution))`

## Files to Modify
- MODIFY: `src/scanner.py` — add resolution time to market data
- MODIFY: `src/paper_trader.py` — add capital allocation by speed tier
- NEW: `src/capital_velocity.py` — velocity tracking and optimization
- MODIFY: `improvement_loop.py` — add velocity metrics to cycle reporting

## Expected Outcome
- 2-3× more trades per month from the same $75
- Capital rarely sitting idle
- Faster feedback loop (resolved trades provide data for calibration)
- Higher absolute returns even if per-trade edge is the same
