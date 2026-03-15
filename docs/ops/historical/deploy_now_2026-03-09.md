# DEPLOY NOW — Paper Aggressive Profile

**Date:** 2026-03-09
**Profile:** `paper_aggressive`
**Purpose:** Generate the first 100 paper trades for live calibration data

---

## What Changed

New runtime profile: `config/runtime_profiles/paper_aggressive.json`

| Setting | Old (blocked_safe) | New (paper_aggressive) | Why |
|---------|-------------------|----------------------|-----|
| YES threshold | 0.15 | **0.08** | Pipeline shows 0→8 tradeable markets at this level |
| NO threshold | 0.05 | **0.03** | Proportional reduction |
| Crypto priority | 0 (blocked) | **2** (enabled) | All 8 tradeable markets are BTC crypto |
| Min category priority | 1 | **0** | Opens all categories |
| Sports priority | 0 (blocked) | **1** | Fee asymmetry edge (3.5x cheaper than crypto) |
| Execution mode | blocked | **shadow** | Logs trades without submitting to CLOB |
| Launch gate | blocked | **none** | No gate — paper mode is the safety rail |
| Order submission | false | **false** | PAPER ONLY — no real orders |
| Wallet flow | disabled | **enabled** | 80 scored wallets ready |
| LMSR | disabled | **enabled** | 45 tests passing |
| A6 shadow | disabled | **enabled** | Shadow scan alongside live |
| B1 shadow | disabled | **enabled** | Shadow scan alongside live |
| Scan interval | 300s | **120s** | 2x faster scan for fast markets |
| Min edge | 0.05 | **0.03** | Aligned with NO threshold |
| Kelly fraction | 0.125 | **0.25** | Quarter-Kelly as designed |

---

## Commands to Run on VPS

```bash
# 1. SSH to Dublin VPS
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0

# 2. Pull latest code (includes paper_aggressive profile)
cd /home/ubuntu/polymarket-trading-bot/
git pull origin main

# 3. Verify the profile loaded
python3 -c "
from config.runtime_profile import load_runtime_profile
p = load_runtime_profile('paper_aggressive')
print(f'YES: {p.signal_thresholds.yes_threshold}')
print(f'NO: {p.signal_thresholds.no_threshold}')
print(f'Crypto: {p.market_filters.category_priorities[\"crypto\"]}')
print(f'Paper: {p.mode.paper_trading}')
print(f'Orders: {p.mode.allow_order_submission}')
"

# 4. Set the profile in .env
echo 'JJ_RUNTIME_PROFILE=paper_aggressive' >> .env

# 5. Verify .env has the profile set
grep JJ_RUNTIME_PROFILE .env

# 6. Run tests to confirm green
python3 -m pytest tests/ -x -q --tb=short

# 7. Restart the service
sudo systemctl restart jj-live.service

# 8. Verify it's running
sudo systemctl status jj-live.service --no-pager

# 9. Watch first few cycles for trade signals
sudo journalctl -u jj-live.service -f --no-pager
```

---

## What to Watch For

After restart, the bot should:
1. Load `paper_aggressive` profile (check logs for "Profile: paper_aggressive")
2. Scan every 120 seconds instead of 300
3. Accept crypto markets (BTC 5min/15min/4h candles)
4. Fire signals at 0.08/0.03 thresholds
5. Log paper trades to `paper_trades.json` and `jj_state.json`
6. NOT submit real orders (allow_order_submission=false)

**First trade signal should appear within 10-20 minutes** if any BTC candle market is in the 0.10-0.90 price window with >0.08 estimated edge.

---

## Escalation to Live

When 100 paper trades are logged with stable calibration:
1. Create `live_aggressive` profile (copy paper_aggressive, set `allow_order_submission: true`, `execution_mode: "shadow"` → keep shadow first)
2. Then create `live_production` (set `paper_trading: false`)
3. John approves the switch — this is a spending-real-money escalation

---

## Risk Controls (Unchanged)

- $5 max position, $5 daily loss cap, 5 max open positions
- Quarter-Kelly sizing
- Post-only maker orders (0% fees + rebates)
- All kill rules active
- Telegram alerts on every signal
