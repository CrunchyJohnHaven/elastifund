# P0-36: Switch from Paper Trading to Live Trading
**Tool:** CLAUDE_CODE
**Status:** READY (execute when paper WR > 55% over 2 weeks OR after combined backtest re-run confirms edge)
**Priority:** P0 — A real track record is worth more than any backtest
**Expected ARR Impact:** Infinite — only live P&L matters for investors

## Background
The bot has been paper trading since March 5. Paper trading confirms the system works mechanically (signal generation, trade logging, market scanning). But paper trading:
- Doesn't test real execution (order book depth, fill rates, slippage)
- Doesn't generate a verifiable track record
- Doesn't test the system under real market microstructure conditions
- Doesn't let us learn from real execution failures

We have $75 USDC ready. At $2/trade, worst case is losing $75. The educational value of live execution data is worth more than that.

## Task

1. **Pre-flight checklist — verify all of these before flipping live:**
   - [ ] Wallet funded: $75 USDC on Polygon
   - [ ] API credentials tested: place a tiny test order ($1) and cancel it
   - [ ] Order placement code works: `src/broker/` can submit limit orders to Polymarket CLOB
   - [ ] Order monitoring: system detects fills, partial fills, and rejections
   - [ ] P&L tracking: separate live trades from paper trades in logging
   - [ ] Kill switch: ability to cancel all open orders and halt the bot via Telegram command or VPS flag file
   - [ ] Position limits: max 25% bankroll per trade, max 80% total deployed
   - [ ] Category filters active: no crypto/sports/fed markets
   - [ ] Calibration layer active: temperature scaling applied to raw estimates
   - [ ] Taker fees deducted from edge calculations
   - [ ] Logging: every trade decision (signal, estimate, edge, position size, order ID, fill price) logged to `live_trades.json`

2. **Modify the bot for live mode:**
   - Add a `TRADING_MODE` env var: `paper` or `live`
   - In `live` mode, route trades to actual Polymarket CLOB API instead of paper log
   - Keep paper trading running in parallel for comparison (shadow mode)
   - Use LIMIT orders (maker, 0% fee) not market orders — place at the price we calculated, let it fill or expire
   - Set order expiration: 5 minutes (one cycle). If not filled, cancel and re-evaluate next cycle.

3. **Risk controls for live trading:**
   ```python
   LIVE_RISK_LIMITS = {
       "max_position_usd": 5.00,          # start small, increase after validation
       "max_total_deployed_pct": 0.60,     # 60% max deployed (conservative start)
       "max_daily_loss_usd": 15.00,        # circuit breaker: stop if down $15 in a day
       "max_positions": 20,                # max concurrent positions
       "min_edge_after_fees": 0.03,        # 3% minimum net edge
       "allowed_categories": ["politics", "weather", "economics", "tech", "entertainment", "science", "geopolitics"],
       "blocked_categories": ["crypto", "sports", "fed_rates"],
       "order_type": "limit",              # maker orders only (0% fee)
       "order_ttl_seconds": 300,           # cancel unfilled orders after 5 min
   }
   ```

4. **Monitoring & alerting:**
   - Telegram notification on every live trade fill (direction, market, price, size, estimated edge)
   - Telegram alert on every trade resolution (win/loss, P&L, running totals)
   - Daily summary: positions open, cash deployed, cash available, unrealized P&L, realized P&L
   - Hourly heartbeat: confirm bot is running, last scan time, positions count

5. **Gradual ramp-up plan:**
   - Week 1: $2 max per trade, 10 max positions ($20 max deployed)
   - Week 2: $3 max per trade, 15 max positions ($45 max deployed)
   - Week 3: $5 max per trade, 20 max positions ($100 deployed — need more capital)
   - Gate: increase only if live win rate > 55% at each stage

6. **Shadow comparison:** Keep paper trading running alongside live. Log both. After 2 weeks, compare:
   - Do paper and live have the same signal generation? (they should)
   - Do fill rates match? (paper assumes 100% fill, live may be lower)
   - Is slippage measurable? (paper assumes exact price)

## Files to Modify
- `src/paper_trader.py` → generalize to `src/trader.py` with paper/live mode
- `src/broker/` → add live order submission via Polymarket CLOB API
- `src/main.py` or `improvement_loop.py` → read TRADING_MODE env var
- `src/telegram.py` → add live trade notifications
- `.env` → add TRADING_MODE=live
- Add `live_trades.json` logging

## Expected Outcome
- Bot placing real trades on Polymarket with $2 positions
- Real fill rate data, slippage data, execution timing data
- Foundation for a verifiable track record
- Shadow comparison showing backtest-vs-live divergence (if any)
