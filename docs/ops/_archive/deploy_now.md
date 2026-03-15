# DEPLOY NOW — Get JJ Live on Dublin VPS

**Date:** 2026-03-07
**Goal:** Signal 1 (LLM ensemble) placing real $0.50 maker orders, accumulating resolved trades.
**Time required:** 15-20 minutes of your time, John.

---

## Pre-flight (your laptop)

```bash
# 1. Sync latest code to VPS
cd ~/Desktop/Elastifund
./scripts/deploy.sh
```

If deploy.sh needs your VPS IP, set it:
```bash
export VPS_IP=52.208.155.0
./scripts/deploy.sh
```

---

## On the VPS

```bash
# 2. SSH in
ssh -i ~/.ssh/lightsail.pem ubuntu@52.208.155.0

# 3. Go to bot directory
cd /home/ubuntu/polymarket-trading-bot

# 4. Install/upgrade all dependencies
pip install --upgrade py-clob-client anthropic openai httpx websockets structlog numpy duckduckgo-search python-dotenv 2>&1 | tail -5

# 5. Verify .env has required keys
python3 -c "
from dotenv import load_dotenv; load_dotenv()
import os
keys = ['POLY_PRIVATE_KEY', 'POLYMARKET_PK', 'POLY_BUILDER_API_KEY', 'ANTHROPIC_API_KEY']
for k in keys:
    v = os.getenv(k, '')
    print(f'{k}: {\"SET (\" + v[:8] + \"...)\" if v else \"MISSING\"}')"

# 6. Verify config is conservative
python3 -c "
import os; from dotenv import load_dotenv; load_dotenv()
print('=== JJ LIVE CONFIG ===')
print(f'MAX_POSITION_USD:  \${os.getenv(\"JJ_MAX_POSITION_USD\", \"0.50\")}')
print(f'MAX_DAILY_LOSS:    \${os.getenv(\"JJ_MAX_DAILY_LOSS_USD\", \"5\")}')
print(f'KELLY_FRACTION:    {os.getenv(\"JJ_KELLY_FRACTION\", \"0.25\")}')
print(f'SCAN_INTERVAL:     {os.getenv(\"JJ_SCAN_INTERVAL\", \"180\")}s')
print(f'MAX_RESOLUTION_H:  {os.getenv(\"JJ_MAX_RESOLUTION_HOURS\", \"48\")}h')
print(f'PAPER_TRADING:     {os.getenv(\"PAPER_TRADING\", \"false\")}')
print(f'A6_SHADOW:         {os.getenv(\"ENABLE_A6_SHADOW\", \"false\")}')
"

# Expected output:
# MAX_POSITION_USD:  $0.50
# MAX_DAILY_LOSS:    $5
# KELLY_FRACTION:    0.25
# PAPER_TRADING:     false
# A6_SHADOW:         false

# 7. Test single cycle (dry run — will scan markets, estimate probs, attempt orders)
cd /home/ubuntu/polymarket-trading-bot
python3 bot/jj_live.py 2>&1 | tail -40

# Watch for:
# - "Scanning X active markets..." (should be 50+)
# - "Found Y actionable markets" (should be >0)
# - "TRADE:" or "ORDER:" lines (actual order attempts)
# - Any errors (API failures, import errors, etc.)

# If single cycle works, proceed to daemon mode:

# 8. Enable A-6 shadow monitoring (optional but recommended)
# Add to .env:
echo "ENABLE_A6_SHADOW=true" >> .env

# 9. Start the service
sudo systemctl restart jj-live.service
sudo systemctl status jj-live.service

# 10. Watch the logs
journalctl -u jj-live -f --no-pager

# Watch for 5-10 minutes. You should see:
# - Market scans every 180 seconds
# - Probability estimates from Claude/GPT/Grok ensemble
# - Order placement attempts on qualifying markets
# - Telegram notifications (check your phone)
```

---

## Verify it's working

```bash
# Check positions after 30 minutes
python3 bot/jj_live.py --status

# Check trade database
python3 -c "
import sqlite3
conn = sqlite3.connect('data/jj_trades.db')
rows = conn.execute('SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10').fetchall()
print(f'Total trades: {len(rows)}')
for r in rows: print(r)
"

# Check state file
cat jj_state.json | python3 -m json.tool
```

---

## If something breaks

```bash
# Check logs for errors
journalctl -u jj-live --since "1 hour ago" | grep -i "error\|exception\|traceback"

# Common fixes:
# Import error → pip install <missing_package>
# API 403 → check POLY_BUILDER_API_KEY/SECRET/PASSPHRASE in .env
# No markets found → check MAX_RESOLUTION_HOURS (increase if too restrictive)
# Geoblock → confirm VPS IP is Dublin (curl ifconfig.me should show EU IP)

# Emergency stop
sudo systemctl stop jj-live.service
```

---

## What happens next

Once the bot is live and placing orders:
- The hourly Cowork task (`jj-hourly-ops`) will monitor performance every hour
- The daily deep review (`jj-daily-deep-review`) will run kill battery and update strategies at 6am
- You sync data back periodically: `scp ubuntu@52.208.155.0:/home/ubuntu/polymarket-trading-bot/data/*.db ~/Desktop/Elastifund/data/`
- Or set up a cron on VPS to git push data changes

**Data sync (add to VPS crontab):**
```bash
# Every 6 hours, commit and push data + state files
crontab -e
# Add:
0 */6 * * * cd /home/ubuntu/polymarket-trading-bot && git add data/ jj_state.json logs/ && git commit -m "auto: data sync $(date +\%Y-\%m-\%d-\%H\%M)" && git push origin main 2>/dev/null
```

This way the Cowork scheduled tasks can read fresh data from the repo.

---

**Bottom line:** Run these commands top to bottom. Takes 15 minutes. After that, JJ is live and learning. Every hour of delay is an hour of zero data. Go.**
