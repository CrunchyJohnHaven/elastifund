# DEPLOY: Maker Velocity Live — Dublin VPS

**Date:** 2026-03-09
**Author:** JJ
**Profile:** `maker_velocity_live`
**Mode:** LIVE maker orders on Polymarket (crypto + politics + weather + economic)
**Capital at risk:** $247.51 Polymarket USDC, UNCAPPED daily loss (full deployment)

---

## What Changed (This Commit)

### 1. New Profile: `config/runtime_profiles/maker_velocity_live.json`
- Crypto category priority: 0 → 3 (unlocked for maker-only)
- Politics/weather/economic: enabled (3/3/2)
- Max position: $10, daily loss UNCAPPED, Kelly: 0.25
- Max 30 open positions, 90% exposure cap
- 24h max resolution, 30s scan interval
- VPIN defense: bucket 250, window 12, toxic threshold 0.70
- A6/B1: disabled (kill watch active, deadline March 14)
- LLM signals: ON, wallet flow: ON, LMSR: ON
- Fast-flow-only: ON (skip slow-resolving markets)

### 2. Fixed Profile: `config/runtime_profiles/maker_velocity_all_in.json`
- Kelly 1.0 → 0.25 (survivable sizing)
- Max position $247 → $10 (spread across 30 positions, not one)
- Daily loss cap $247 → $25 in all_in profile (conservative variant; maker_velocity_live is uncapped per principal's instruction)
- Max open positions 1 → 30

### 3. Fixed: `bot/btc_5min_maker.py`
- Default max_trade_usd: $2.50 → $5.00 (meets CLOB minimum)
- Default min_trade_usd: $0.25 → $5.00 (meets CLOB minimum)
- Default risk_fraction: 0.01 → 0.02 (2% per trade = $5 on $250)
- Default daily_loss_limit_usd: $5 → $10 (more room for data collection)

---

## Deployment Commands

### Step 1: Deploy Code + Switch Profile
```bash
# From repo root on local machine:
./scripts/deploy.sh --clean-env --profile maker_velocity_live --restart
```

This single command:
1. Syncs all bot/*.py files to VPS
2. Syncs all config/runtime_profiles/*.json to VPS
3. Cleans the remote .env to use the new profile
4. Sets `JJ_RUNTIME_PROFILE=maker_velocity_live`
5. Verifies imports and profile contract
6. Restarts jj-live.service

### Step 2: Verify Service Status (30 seconds after restart)
```bash
SSH_KEY="${LIGHTSAIL_KEY:-$HOME/.ssh/lightsail.pem}"
VPS="${VPS_USER:-ubuntu}@${VPS_IP}"

# Check service is running
ssh -i "$SSH_KEY" "$VPS" "sudo systemctl is-active jj-live.service"

# Check profile loaded correctly
ssh -i "$SSH_KEY" "$VPS" "sudo journalctl -u jj-live.service -n 50 --no-pager | grep -i 'profile\|crypto\|paper\|execution\|order'"

# Check state file
ssh -i "$SSH_KEY" "$VPS" "cat /home/ubuntu/polymarket-trading-bot/jj_state.json | python3 -m json.tool | head -30"
```

### Step 3: Monitor First Cycle (Watch for 5 minutes)
```bash
# Live log tail
ssh -i "$SSH_KEY" "$VPS" "sudo journalctl -u jj-live.service -f --no-pager"
```

**What to watch for:**
- `Profile: maker_velocity_live` in startup logs
- `Paper: False` confirmed
- `Order submission: True` confirmed
- `Crypto priority: 3` confirmed
- First scan completing and finding markets
- First order placement attempt
- Any error about API keys, signatures, or CLOB connectivity

### Step 4: Deploy BTC 5-Min Bot (Separate Instance)
```bash
# The BTC 5-min bot runs as a separate process/service
# Set environment on VPS:
ssh -i "$SSH_KEY" "$VPS" "cat >> /home/ubuntu/polymarket-trading-bot/.env << 'EOF'

# BTC 5-Min Maker (Instance 2)
BTC5_PAPER_TRADING=false
BTC5_BANKROLL_USD=247.51
BTC5_RISK_FRACTION=0.02
BTC5_MAX_TRADE_USD=5.00
BTC5_MIN_TRADE_USD=5.00
BTC5_MIN_DELTA=0.0003
BTC5_MAX_BUY_PRICE=0.95
BTC5_MIN_BUY_PRICE=0.90
BTC5_ENTRY_SECONDS_BEFORE_CLOSE=10
BTC5_CANCEL_SECONDS_BEFORE_CLOSE=2
BTC5_DAILY_LOSS_LIMIT_USD=10
BTC5_PAPER_FILL_PROBABILITY=0.20
BTC5_CLOB_FEE_RATE_BPS=0
EOF"

# Start BTC 5-min bot (run in screen/tmux or create a service)
ssh -i "$SSH_KEY" "$VPS" "cd /home/ubuntu/polymarket-trading-bot && \
  source venv/bin/activate && \
  export PYTHONPATH='/home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot' && \
  nohup python3 bot/btc_5min_maker.py --live > /tmp/btc5min.log 2>&1 &"
```

---

## Rollback

If something goes wrong:

```bash
# Emergency: switch back to blocked_safe (stops all trading immediately)
./scripts/deploy.sh --clean-env --profile blocked_safe --restart

# Or just stop the service
ssh -i "$SSH_KEY" "$VPS" "sudo systemctl stop jj-live.service"

# Kill BTC 5-min bot
ssh -i "$SSH_KEY" "$VPS" "pkill -f btc_5min_maker"
```

---

## Kalshi ($100 USD)

Kalshi runs as Instance 3 (separate from Polymarket). The weather arb bot is in `bot/kalshi/`.

```bash
# Check if Kalshi service exists
ssh -i "$SSH_KEY" "$VPS" "sudo systemctl status kalshi-weather-trader.service || echo 'Service not found'"

# If service exists, start it
ssh -i "$SSH_KEY" "$VPS" "sudo systemctl start kalshi-weather-trader.service"
```

Kalshi weather markets resolve daily. At $10/trade with $5 daily loss cap, expect 1-3 trades per day.

---

## Expected Data Collection Rate

| Source | Trades/Day | Resolution Time | Daily Risk |
|--------|-----------|----------------|------------|
| JJ main (crypto+politics+weather) | 5-15 | 4-24h | uncapped |
| BTC 5-min maker | 10-60 | 5 min | uncapped |
| Kalshi weather | 1-3 | 24h | uncapped |
| **Total** | **16-78** | — | **$347.51 max** |

**Target: 100 resolved trades in 5-7 days**
**All capital deployed. No daily loss caps. Kelly 0.25 and $10 position size provide natural risk distribution.**
**At $10/position with 30 max positions = $300 deployed, $47.51 reserve.**

---

## Post-Deployment Checklist

- [ ] Service running with `maker_velocity_live` profile
- [ ] First scan completes and finds eligible markets
- [ ] First maker order placed (check jj_state.json for order IDs without `paper-` prefix)
- [ ] VPIN WebSocket connection established (check logs for `ws_trade_stream`)
- [ ] Daily loss cap functioning (verify in logs after first loss)
- [ ] BTC 5-min bot running and logging to SQLite
- [ ] Kalshi service status confirmed
- [ ] Balance check: Polymarket USDC balance matches expected
- [ ] No drift flags in jj_state.json

---

*One command to go live: `./scripts/deploy.sh --clean-env --profile maker_velocity_live --restart`*

— JJ
