# P0-34: Kelly Criterion Integration into Live Bot
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Research complete, implementation pending. Flat $2 sizing is leaving money on the table.
**Expected ARR Impact:** +40-80% (dynamic sizing captures more from high-edge trades)

## Background
Kelly criterion research is complete (see STRATEGY_REPORT.md "Position Sizing" section). The math is done. Quarter-Kelly (0.25×) with asymmetric NO-bias scaling is the recommendation. This just needs to be wired into the live bot.

## Task

Modify the paper trader in the polymarket-bot to use Kelly criterion instead of flat $2:

1. **Read the existing code:**
   ```
   /Users/johnbradley/Desktop/Quant/polymarket-bot/src/paper_trader.py
   /Users/johnbradley/Desktop/Quant/polymarket-bot/src/claude_analyzer.py
   ```

2. **Implement the Kelly sizing function:**
   ```python
   def kelly_position_size(
       estimated_prob: float,      # calibrated probability
       market_price: float,        # current market price (our cost basis)
       bankroll: float,            # current available capital
       direction: str,             # "buy_yes" or "buy_no"
       category: str = "general",  # for correlated position haircut
       active_positions: int = 0,  # positions in same category
   ) -> float:
       """Quarter-Kelly with asymmetric NO-bias and correlation haircut."""

       # Kelly fraction for binary bet
       if direction == "buy_yes":
           b = (1 - market_price) / market_price  # payout odds
           p = estimated_prob
           base_fraction = 0.25  # conservative for YES (55.8% WR)
       else:  # buy_no
           b = market_price / (1 - market_price)
           p = 1 - estimated_prob
           base_fraction = 0.35  # more aggressive for NO (76.2% WR)

       q = 1 - p
       f_star = (b * p - q) / b  # raw Kelly fraction

       if f_star <= 0:
           return 0  # no bet — negative edge

       # Apply fraction and edge uncertainty shrinkage
       edge = abs(estimated_prob - market_price)
       sigma = 0.10  # estimation uncertainty
       alpha = edge**2 / (edge**2 + sigma**2)  # ~0.90 for our avg edge
       position = base_fraction * f_star * alpha * bankroll

       # Correlation haircut: 50% reduction if >3 positions in same category
       if active_positions >= 3:
           position *= 0.50

       # Constraints
       position = max(position, 0)     # no negative
       position = min(position, bankroll * 0.25)  # max 25% bankroll per trade
       if position < 1.0:
           return 0  # below minimum viable stake
       position = round(position, 2)    # tick size

       return position
   ```

3. **Wire it into the trading pipeline:**
   - In `paper_trader.py`: Replace the hardcoded `$2.00` with `kelly_position_size()`
   - Pass current bankroll (cash + unrealized positions value)
   - Track positions by category for correlation haircut
   - Log the Kelly fraction and position size for each trade

4. **Dynamic scaling tiers:**
   - Bankroll < $150 → 0.25× Kelly (as above)
   - Bankroll ≥ $300 → increase base_fraction to 0.50×
   - Bankroll ≥ $500 → increase to 0.75×

5. **Safety checks:**
   - Never risk more than 25% of bankroll on a single trade
   - Never deploy more than 80% of bankroll total (keep 20% reserve)
   - Skip any trade where Kelly suggests < $1 (below Polymarket minimum)
   - After taker fee deduction, recheck if edge is still positive

6. **Backtest the Kelly sizing** against the 532-market dataset to confirm it outperforms flat $2.

## Files to Modify
- `src/paper_trader.py` — position sizing logic
- `src/claude_analyzer.py` — pass edge + direction to sizing function
- `src/core/` or `src/strategy/` — wherever the trade decision lives
- Add `kelly.py` utility if cleaner as standalone module

## Expected Outcome
- Dynamic position sizing deployed in paper trading
- Larger positions on high-edge NO trades, smaller on marginal YES trades
- Backtest showing improved total P&L and Sharpe vs flat sizing
- Growth projection: $75 → $500 in ~26 median bets (vs ~150+ bets at flat $2)
