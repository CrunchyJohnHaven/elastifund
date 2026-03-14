# DISPATCH 103: Deploy Spread-Capture Mode to Break Zero-Fill Deadlock

**Date**: 2026-03-14 19:30 UTC
**Priority**: CRITICAL
**Author**: JJ (via Cowork session)
**Target**: VPS btc-5min-maker service

## Problem Statement

The BTC5 maker bot has placed **zero fills** despite 553+ window evaluations. The
deadlock-breaking env var overrides (DISPATCH_100) fixed the config funnel, but the
bot still requires BTC to move >= 0.03% per 5-minute window (`BTC5_MIN_DELTA=0.0003`).
During low-volatility periods, **every window** hits `skip_delta_too_small`.

The profitable BTC5 wallets discovered by our wallet intelligence pipeline are
market-makers who earn the spread, not directional traders who need BTC to move.
Our bot is designed around the wrong edge.

## Solution: Spread-Capture Mode

A new config flag `BTC5_ENABLE_SPREAD_CAPTURE=true` that:
1. Bypasses the delta gate when `abs(delta) < min_delta`
2. Alternates UP/DOWN direction each window (`window_start_ts // 300 % 2`) for
   statistical neutrality
3. Proceeds to order placement using the existing book-driven maker logic
4. Everything downstream is unchanged: price guardrails, edge tier, size gates

## Code Change (Already Committed)

The change is in `bot/btc_5min_maker.py`:
- Line 791: New config field `enable_spread_capture: bool = _env_flag("BTC5_ENABLE_SPREAD_CAPTURE", False)`
- Lines 2532-2541: New bypass block that forces a direction when delta is too small
  and spread-capture mode is enabled

## Deployment Steps

### 1. Pull latest code on VPS
```bash
cd /home/ubuntu/polymarket-trading-bot
git pull origin main
```

### 2. Add spread-capture env var
```bash
echo '' >> .env
echo '# --- Spread-capture mode (DISPATCH_103, 2026-03-14) ---' >> .env
echo '# Bypass delta gate when BTC is flat; trade the spread instead' >> .env
echo 'BTC5_ENABLE_SPREAD_CAPTURE=true' >> .env
```

### 3. Restart service
```bash
sudo systemctl restart btc-5min-maker.service
```

### 4. Monitor for first fill
```bash
sudo journalctl -u btc-5min-maker.service -f | grep -E 'Spread-capture|live_order|live_filled|skip_'
```

## Expected Behavior After Deploy

- `skip_delta_too_small` count drops to **ZERO** (spread-capture catches all flat windows)
- Log lines show `Spread-capture mode: delta=X.XXXXXX below threshold, forcing direction=UP/DOWN`
- Orders reach placement stage for every window that has a valid book
- Fill rate depends on book liquidity and price guardrails

## Remaining Skip Reasons (All Legitimate)

| Status | Meaning | Action |
|--------|---------|--------|
| skip_bad_book | No valid bid/ask | Wait for market creation |
| skip_price_outside_guardrails | Price can't be computed | Check max/min buy price configs |
| skip_loss_cluster_suppressed | Historical loss pattern | May need to clear loss clusters |
| live_order_failed | Placement error | Check error message |

## Risk Assessment

- **Downside**: Bot places orders in flat markets where direction is arbitrary.
  Alternating UP/DOWN neutralizes directional risk over time.
- **Upside**: First live fills. Stage gate can bootstrap from real data.
  Maker rebate (20% of taker fee) provides positive EV even on random direction.
- **Kill switch**: Set `BTC5_ENABLE_SPREAD_CAPTURE=false` to revert to delta-gated mode.

## Success Criteria

- [ ] At least 1 `live_order_placed` within 30 minutes of deploy
- [ ] At least 1 `live_filled` within 2 hours
- [ ] No `invalid_signature` errors (already fixed in DISPATCH_100)
- [ ] Daily loss limit not triggered

## Env Var Summary (Full Current State)

```
BTC5_MIN_DELTA=0.0001
BTC5_MAX_ABS_DELTA=0.0040
BTC5_ENFORCE_LT049_SKIP_BASELINE=false
BTC5_MAKER_IMPROVE_TICKS=0
BTC5_TOXIC_FLOW_IMBALANCE_THRESHOLD=0.80
BTC5_MIDPOINT_GUARDRAIL_SHADE_TICKS=1
BTC5_ENABLE_SPREAD_CAPTURE=true        # NEW
BTC5_MAX_TRADE_USD=10
BTC5_DAILY_LOSS_LIMIT_USD=100
POLY_SIGNATURE_TYPE=1
```
