# CODEX TASK 05: Service Health Monitoring + Daily Summary

## MACHINE TRUTH (2026-03-09)
- Bot ran 314 cycles producing nothing — nobody noticed for hours
- Telegram module exists but "not available" on VPS (import issue?)
- Log: "Telegram module not available — notifications disabled"
- No heartbeat check — service can silently fail
- No daily summary of activity

## TASK
1. **Fix Telegram import on VPS path:**
   - Read `bot/jj_live.py` Telegram initialization section
   - Read `bot/polymarket_runtime.py` and `polymarket-bot/src/telegram.py`
   - Identify why TelegramBot/TelegramNotifier import fails
   - Fix the import chain so Telegram works when TELEGRAM_TOKEN is set
   - If TELEGRAM_TOKEN is missing, gracefully degrade (current behavior, but log clearly)

2. **Add heartbeat file:**
   - After each cycle completes in jj_live.py, write `data/heartbeat.json`:
     ```json
     {"last_cycle": 316, "timestamp": "ISO", "signals_found": 1, "trades_placed": 0}
     ```
   - This is a 3-line addition to the cycle completion handler

3. **Create health check script:**
   - `scripts/health_check.sh`:
     - Reads `data/heartbeat.json`
     - If timestamp > 10 minutes old: send Telegram alert (if configured) and exit 1
     - If timestamp fresh: exit 0
     - Designed to run as cron job every 5 minutes

4. **Create daily summary script:**
   - `scripts/daily_summary.py`:
     - Reads jj_state.json for today's trades
     - Reads data/heartbeat.json for cycle count
     - Formats a summary: cycles, signals, trades, errors, P&L
     - Sends via Telegram (or prints to stdout if no token)
     - Designed to run as cron job at 00:00 UTC

## FILES
- `bot/jj_live.py` (MODIFY — add heartbeat write after each cycle, fix Telegram import)
- `scripts/health_check.sh` (CREATE)
- `scripts/daily_summary.py` (CREATE)
- `tests/test_health_monitoring.py` (CREATE)

## CONSTRAINTS
- Heartbeat write must be fast (<1ms) — don't slow the cycle
- Health check must work without Python (pure bash + jq)
- Daily summary must work without Telegram (fallback to stdout)
- `make test` must pass

## DO NOT
- Install new monitoring frameworks (Prometheus, Grafana, etc.)
- Create new systemd services — use cron
- Change the main cycle timing or logic
