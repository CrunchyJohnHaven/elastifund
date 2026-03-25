# BTC5 Proving-Ground Scale Checklist

**Created:** 2026-03-14
**Profile:** `config/runtime_profiles/btc5_scale_v1.json`

## Pre-Conditions (Must All Pass)

- [ ] **Fills confirmed at current size** — BTC5 has produced live fills after the 2026-03-14 guardrail fix (delta=0.0040, UP live, min_buy=0.42). Check: `journalctl -u btc-5min-maker --since "4 hours ago" | grep -c order_placed`
- [ ] **Trailing P&L positive** — Last 12 live fills have cumulative positive P&L. Check: `sqlite3 data/btc_5min_maker.db "SELECT SUM(pnl_usd) FROM fills WHERE filled=1 ORDER BY created_at DESC LIMIT 12"`
- [ ] **Order fail rate below 25%** — Recent orders aren't being rejected at high rate. Check: `sqlite3 data/btc_5min_maker.db "SELECT ROUND(1.0*SUM(CASE WHEN order_status='failed' THEN 1 ELSE 0 END)/COUNT(*),3) FROM cycles WHERE created_at > datetime('now','-6 hours')"`
- [ ] **Wallet balance sufficient** — Portfolio has enough free USDC for scaled positions. Need >$50 free. Check: Polymarket portfolio page or wallet API.
- [ ] **No competing guardrail blocks** — Bad_book, toxic_order_flow skips are below 80% of cycles during active hours.

## Configuration Already In Place

The BTC5 maker's proving-ground reset now defaults to $5/trade at stage 1:
- `BTC5_CAPITAL_STAGE=1` (default)
- `BTC5_STAGE1_MAX_TRADE_USD=5` (default during the reset)
- `BTC5_STAGE2_MAX_TRADE_USD=10`
- `BTC5_STAGE3_MAX_TRADE_USD=20`
- Do not widen size beyond stage 1 unless the shared launch contract and stage gate are green

The 2026-03-14 guardrail fixes are in `config/btc5_strategy.env`:
- `BTC5_MAX_ABS_DELTA=0.0040` (widened from 0.00015)
- `BTC5_UP_MAX_BUY_PRICE=0.52`
- `BTC5_DOWN_MAX_BUY_PRICE=0.53`

## Deploy Command

```bash
cd /Users/johnbradley/Desktop/Elastifund && ./scripts/deploy.sh --clean-env --profile shadow_fast_flow --restart --btc5
```

## Post-Deploy Verification

1. Confirm service running:
   ```bash
   ssh ubuntu@34.244.34.108 "systemctl status btc-5min-maker.service"
   ```

2. Watch for fills (wait for active US trading hours, 14:00-23:00 UTC):
   ```bash
   ssh ubuntu@34.244.34.108 "journalctl -u btc-5min-maker -f --no-pager | grep -E 'order_placed|filled|skip_reason'"
   ```

3. Check P&L after 2 hours:
   ```bash
   ssh ubuntu@34.244.34.108 "cd /home/ubuntu/polymarket-trading-bot && python3 -c \"
   import sqlite3, json
   db = sqlite3.connect('data/btc_5min_maker.db')
   db.row_factory = sqlite3.Row
   rows = db.execute('SELECT direction, won, pnl_usd, trade_size_usd FROM fills WHERE filled=1 ORDER BY created_at DESC LIMIT 20').fetchall()
   for r in rows: print(dict(r))
   print(f'Total P&L last 20: {sum(r[\"pnl_usd\"] or 0 for r in rows):.2f}')
   \""
   ```

4. If cumulative P&L drops below -$50 in 24h, investigate immediately.

## Rollback

If fills are consistently losing even at $5/trade:
```bash
# Revert to $5 base with no stage system
ssh ubuntu@34.244.34.108 "cd /home/ubuntu/polymarket-trading-bot && echo 'BTC5_CAPITAL_STAGE=' >> .env && sudo systemctl restart btc-5min-maker"
```

## Scaling Beyond Stage 1

Stage 2 ($10/trade) unlocks automatically when:
- 12+ trailing live fills with positive cumulative P&L
- 40+ trailing live fills with positive cumulative P&L
- Order fail rate < 25%
- Fresh probe telemetry within 6 hours

Stage 3 ($20/trade) requires all stage 2 gates PLUS 120+ trailing positive fills.
