# P2-45: Continuous Backtest Evaluator (Auto-Updating ARR)
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P2 — Important for keeping investor materials current without manual work
**Expected ARR Impact:** Indirect — keeps all numbers fresh, catches performance degradation early

## Background
Currently our backtest is a one-shot: 532 markets, run once, numbers hardcoded into reports. As new markets resolve on Polymarket daily, we should be continuously collecting them and re-running the backtest to keep our numbers up to date.

## Task

Build a daily auto-evaluator that runs on the VPS:

1. **Daily market collector (expand `backtest/collector.py`):**
   - Fetch all newly resolved markets from Gamma API since last collection
   - Filter: binary Yes/No, has resolution, min $100 volume
   - Append to `backtest/data/historical_markets.json`
   - Log: "{n} new resolved markets collected. Total: {total}"

2. **Daily backtest re-run:**
   - After collecting new markets, re-run backtest engine on full dataset
   - Compare today's results vs yesterday's: win rate, Brier score, total P&L
   - If win rate changes by >2% or Brier changes by >0.01, flag in Telegram alert

3. **Rolling performance tracker:**
   ```json
   {
     "2026-03-05": {"total_markets": 532, "win_rate": 0.649, "brier": 0.239},
     "2026-03-06": {"total_markets": 547, "win_rate": 0.651, "brier": 0.237},
     "2026-03-07": {"total_markets": 563, "win_rate": 0.648, "brier": 0.240},
     ...
   }
   ```

4. **Auto-update STRATEGY_REPORT.md:**
   - After each daily run, update the key numbers in the strategy report
   - Update: total markets tested, win rate, Brier score, total P&L, ARR projections
   - Git commit the changes (if repo is set up) or just overwrite the file

5. **Weekly chart regeneration:**
   - Re-generate all backtest charts (calibration plot, equity curve, etc.) weekly
   - Include new data points in equity curve and calibration analysis

6. **Systemd timer on VPS:**
   ```
   [Timer]
   OnCalendar=*-*-* 06:00:00 UTC
   Persistent=true
   ```

## Files to Create/Modify
- MODIFY: `backtest/collector.py` — add incremental collection mode
- NEW: `backtest/daily_evaluator.py` — orchestrates collect + backtest + report
- NEW: `ops/polymarket-evaluator.service` and `.timer` — systemd units
- MODIFY: `backtest/engine.py` — support incremental mode (skip cached estimates)

## Expected Outcome
- Backtest numbers always reflect latest available data
- Performance degradation caught within 24 hours
- Investor materials can always cite "as of yesterday" numbers
- Growing dataset strengthens statistical significance over time
