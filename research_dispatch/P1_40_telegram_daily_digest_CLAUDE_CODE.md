# P1-40: Telegram Daily P&L Digest & Trade Alerts
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P1 — Operational necessity for monitoring live system + investor reporting
**Expected ARR Impact:** Indirect — operational awareness prevents missed problems

## Background
The bot sends basic Telegram notifications per cycle, but we need a comprehensive daily digest for:
1. Personal monitoring (are we making money?)
2. Investor updates (monthly summary sourced from daily data)
3. Anomaly detection (catch problems before they compound)

## Task

1. **Daily digest message (send at 9:00 AM EST daily):**
   ```
   📊 DAILY REPORT — March 10, 2026

   💰 P&L Summary
   ├ Realized P&L (today): +$4.20
   ├ Realized P&L (all-time): +$28.40
   ├ Unrealized P&L: ~+$12.00 (est.)
   ├ Portfolio value: $115.40
   └ ROI since inception: +53.9%

   📈 Trading Activity (24h)
   ├ Markets scanned: 2,880 (288 cycles)
   ├ Signals generated: 412
   ├ Trades entered: 38
   ├ Trades resolved: 12 (9W / 3L = 75.0%)
   └ Avg edge on new trades: 18.2%

   🎯 Win Rate Tracker
   ├ Last 10 trades: 80.0%
   ├ Last 50 trades: 68.0%
   ├ All-time: 66.2% (n=142)
   └ Backtest target: 64.9%

   📋 Open Positions: 24 ($48.00 deployed)
   ├ Buy YES: 8 positions
   ├ Buy NO: 16 positions
   └ Cash available: $67.40

   ⚠️ Alerts
   └ Win rate ABOVE backtest target ✅
   ```

2. **Real-time trade alerts (on every fill):**
   ```
   🔔 TRADE FILLED
   Market: "Will Fed cut rates in June 2026?"
   Direction: BUY NO @ $0.38
   Size: $3.50 (Kelly: 0.25×, edge: 22.1%)
   Category: Economics
   Claude est: 28% YES → Calibrated: 35% → Ensemble: 37%
   ```

3. **Resolution alerts:**
   ```
   ✅ TRADE WON
   Market: "Will it rain in NYC on March 8?"
   Direction: BUY NO @ $0.25 → Resolved NO
   P&L: +$1.50 (+60.0%)
   Running: 67.1% WR (n=143)

   ❌ TRADE LOST
   Market: "Will Bitcoin hit $100K by March 15?"
   Direction: BUY NO @ $0.62 → Resolved YES
   P&L: -$2.00 (-100.0%)
   Running: 66.4% WR (n=144)
   ```

4. **Weekly summary (Sundays at 9 AM):**
   - Weekly P&L, win rate, best/worst trades
   - Win rate trend (rolling 50 vs all-time)
   - Category breakdown (which categories are profitable?)
   - Comparison vs backtest expectations
   - Auto-generated 3-sentence summary suitable for investor update

5. **Anomaly alerts (immediate):**
   - 🔴 3+ consecutive losses → "LOSING STREAK: 3 consecutive losses. Consider pausing."
   - 🔴 Daily loss > $15 → "DAILY LOSS LIMIT: $15 loss triggered. Bot paused."
   - 🟡 Win rate drops below 55% (rolling 50) → "WIN RATE WARNING: 54.0% over last 50 trades"
   - 🟡 No trades in 6+ hours → "ACTIVITY WARNING: No trades in 6h. Check bot status."
   - 🔴 Bot crash/restart → "BOT RESTARTED at [time]. Checking positions..."

6. **Implementation:**
   - Modify `src/telegram.py` to support scheduled messages (use APScheduler or systemd timer)
   - Add `daily_digest()` function that aggregates from `paper_trades.json` / `live_trades.json`
   - Add trade-level hooks in `paper_trader.py` / `trader.py` for fill and resolution alerts
   - Store daily snapshots in `metrics_history.json` for historical charting

## Files to Modify
- `src/telegram.py` — add digest, alerts, and anomaly detection
- `src/paper_trader.py` or `src/trader.py` — add hooks for trade events
- `improvement_loop.py` — add daily digest scheduler
- NEW: `src/reporting.py` — P&L calculation, win rate tracking, anomaly detection

## Expected Outcome
- Full operational awareness of bot performance at all times
- Automatic anomaly detection prevents compounding losses
- Weekly summaries feed directly into investor reporting
- Professional monitoring setup that scales to live trading
