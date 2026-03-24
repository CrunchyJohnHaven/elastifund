# DISPATCH 103: Deploy Spread-Capture Mode

**Paste this into your VPS Claude Code session (`claude --dangerously-skip-permissions`)**

---

## Instructions for Claude Code

Execute these steps in order. Do not ask for confirmation. Do not skip steps.

### Step 1: Pull latest code

```bash
cd /home/ubuntu/polymarket-trading-bot
git pull origin main
```

If there are merge conflicts, stash local changes first:
```bash
git stash && git pull origin main && git stash pop
```

### Step 2: Verify the spread-capture code landed

```bash
grep -n "enable_spread_capture" bot/btc_5min_maker.py
```

You should see two matches:
- Line ~791: `enable_spread_capture: bool = _env_flag("BTC5_ENABLE_SPREAD_CAPTURE", False)`
- Line ~2534: `if direction is None and self.cfg.enable_spread_capture:`

If you don't see both, the pull failed. Stop and report.

### Step 3: Add spread-capture env var

```bash
echo '' >> .env
echo '# --- Spread-capture mode (DISPATCH_103, 2026-03-14) ---' >> .env
echo '# Bypass delta gate when BTC is flat; trade the spread instead' >> .env
echo 'BTC5_ENABLE_SPREAD_CAPTURE=true' >> .env
```

Verify it's there:
```bash
grep SPREAD_CAPTURE .env
```

### Step 4: Confirm all critical env vars are set

```bash
grep -E 'POLY_SIGNATURE_TYPE|BTC5_MIN_DELTA|BTC5_ENABLE_SPREAD_CAPTURE|BTC5_ENFORCE_LT049|BTC5_MAKER_IMPROVE_TICKS|BTC5_TOXIC_FLOW' .env | grep -v '^#'
```

Expected output (all must be present):
```
POLY_SIGNATURE_TYPE=1
BTC5_MIN_DELTA=0.0001
BTC5_ENABLE_SPREAD_CAPTURE=true
BTC5_ENFORCE_LT049_SKIP_BASELINE=false
BTC5_MAKER_IMPROVE_TICKS=0
BTC5_TOXIC_FLOW_IMBALANCE_THRESHOLD=0.80
```

### Step 5: Restart the service

```bash
sudo systemctl restart btc-5min-maker.service
sleep 3
sudo systemctl is-active btc-5min-maker.service
```

Must show `active`.

### Step 6: Verify spread-capture is enabled in startup log

```bash
sudo journalctl -u btc-5min-maker.service --since "30 seconds ago" --no-pager | head -30
```

Look for `enable_spread_capture=True` or `spread_capture=True` in the config dump.

### Step 7: Wait for first window and monitor

```bash
# Wait for the next 5-minute window boundary, then check results
sleep 330
sudo journalctl -u btc-5min-maker.service --since "6 min ago" --no-pager | grep -E 'Spread-capture|Window result|live_order|status'
```

What you should see:
- `Spread-capture mode: delta=X.XXXXXX below threshold, forcing direction=UP/DOWN` — the bypass is working
- `skip_delta_too_small` should be GONE
- If the book is valid, you should see order placement attempts

### Step 8: Monitor for 30 minutes

```bash
sudo journalctl -u btc-5min-maker.service -f | grep -iE 'spread-capture|live_order|live_filled|skip_bad_book|skip_price|error'
```

Report back:
1. How many windows processed
2. How many hit spread-capture bypass
3. How many reached order placement
4. Any fills

### If something goes wrong

Kill switch — disable spread-capture without code changes:
```bash
sed -i 's/BTC5_ENABLE_SPREAD_CAPTURE=true/BTC5_ENABLE_SPREAD_CAPTURE=false/' .env
sudo systemctl restart btc-5min-maker.service
```

---

## Context

The bot has 553+ window evaluations and 0 fills. Every flat-BTC window hits `skip_delta_too_small` because `BTC5_MIN_DELTA=0.0003` requires BTC to move >= 0.03% per 5-minute window. During low-volatility periods this blocks ALL trading.

Spread-capture mode bypasses this gate. When delta is below threshold, it forces a direction (alternating UP/DOWN each window for statistical neutrality) and proceeds to maker order placement. The maker rebate (20% of taker fee at ~1.56% near 50c) provides positive EV even when direction is arbitrary.

The code change is 11 lines: 1 config field + 1 bypass block with logging. All downstream logic (book quality, price guardrails, edge tier, size gates) is unchanged.
