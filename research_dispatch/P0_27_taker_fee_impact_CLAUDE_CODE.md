# P0-27: Taker Fee Impact Analysis & Market-Making Pivot
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** Critical — prevents losses, opens new revenue stream

## Background (from P0-26 research)
On Feb 18, 2026, Polymarket introduced taker fees and removed the 500ms taker quote delay:
- Fee formula: `fee(p) = p × (1-p) × r`
- Crypto markets: r = 0.025 → max 1.56% effective at p=0.50
- Sports markets: r = 0.007 → max 0.44% effective at p=0.50
- At p=0.50, traders need 3.13% edge just to break even on crypto markets
- This killed taker-based arbitrage strategies

## Task
1. **Impact assessment:** Re-run our 532-market backtest with taker fees subtracted from edge calculations. How many of our winning trades would have been eaten by fees?
2. **Break-even analysis:** For each market category, what minimum edge is needed after fees?
3. **Market-making analysis:** Research Polymarket's maker rebate structure. Can we profit by posting limit orders on both sides?
4. **Implementation:** The claude_analyzer.py already has fee awareness added. Verify the fee calculations match Polymarket's actual fee schedule.
5. **Strategy adjustment:** Should we switch from taker (market order) to maker (limit order) strategy?

## Key Data
- Our avg edge: 25.7% (pre-fees)
- Taker fee at p=0.50: ~1.56% for crypto, ~0.44% for sports
- Most of our edge is in politics/weather where fees may be lower/zero
- OpenClaw bot earned $115K/week as a market maker (limit orders)

## Expected Outcome
- Quantified fee impact on historical trades
- Decision: taker vs maker strategy going forward
- If market-making: architecture spec for limit order system
