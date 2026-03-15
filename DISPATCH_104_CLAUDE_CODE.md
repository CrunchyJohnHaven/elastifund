# DISPATCH 104: Price-Band Filter — Stop the Mid-Range Bleeder

**Paste this into your VPS Claude Code session. Execute immediately.**

---

## Problem

First 5 fills show the pattern clearly:

| Price | Direction | PnL | Why |
|-------|-----------|-----|-----|
| 0.64 | UP | -$5.00 | Mid-range: outcome genuinely uncertain, we lost the coin flip |
| 0.74 | UP | -$5.00 | Mid-range: same problem |
| 0.95 | UP | +$0.26 | Near-certain: outcome resolved as expected |
| 0.98 | DOWN | +$0.10 | Near-certain: same |
| 0.96 | DOWN | +$0.21 | Near-certain: same |

**The two $5 losses came from buying tokens at 0.64 and 0.74 — prices where the binary outcome is genuinely uncertain.** That's not spread-capture, that's a coin flip. The three wins came from prices above 0.90 where the outcome was near-certain.

## The Fix

Raise `BTC5_MIN_BUY_PRICE` so the bot ONLY trades near-certain outcomes where spread-capture actually works.

## Execute These Steps

### 1. Update .env

```bash
cd /home/ubuntu/polymarket-trading-bot

# Remove old min buy price line if it exists
sed -i '/^BTC5_MIN_BUY_PRICE=/d' .env

# Add new constraint: only buy tokens priced 0.85 or higher
echo '# DISPATCH_104: Only trade near-certain outcomes (price >= 0.85)' >> .env
echo 'BTC5_MIN_BUY_PRICE=0.85' >> .env
```

### 2. Verify

```bash
grep BTC5_MIN_BUY_PRICE .env
```

Should show: `BTC5_MIN_BUY_PRICE=0.85`

### 3. Restart

```bash
sudo systemctl restart btc-5min-maker.service
sleep 3
sudo journalctl -u btc-5min-maker.service -n 10 --no-pager | grep -i 'min_buy'
```

Confirm min_buy_price=0.85 in startup config dump.

### 4. Monitor

```bash
sudo journalctl -u btc-5min-maker.service -f | grep -iE 'live_|skip_price|Spread-capture|Window result.*status'
```

## Expected Behavior

- Tokens priced 0.50-0.84: SKIPPED (skip_price_outside_guardrails) — these are coin flips, we don't want them
- Tokens priced 0.85-0.99: TRADED — near-certain outcomes where we earn $0.01-$0.15 per fill with high win rate
- Fill rate will drop (fewer eligible windows) but win rate should jump to 80%+
- Expected PnL per fill: +$0.05 to +$0.26

## Why This Works

At price >= 0.85, the binary outcome is 85%+ likely to resolve in our favor. We're paying $0.85-$0.99 for a token worth $1.00 at resolution. Even with the occasional loss ($0.85 * loss_rate), the math is:

- At 0.90 buy price, 90% win rate: EV = 0.90 * $0.10 - 0.10 * $0.90 = $0.00 (breakeven before fees)
- But we're a MAKER (0% fee + rebate), so we have positive edge from the rebate alone
- At 0.95 buy price, 95% win rate: EV = 0.95 * $0.05 - 0.05 * $0.95 = $0.00 + rebate = positive

The maker rebate IS the edge at near-certain prices. We don't need directional skill. We need to stay away from 50/50 outcomes.

## Kill Switch

```bash
sed -i 's/BTC5_MIN_BUY_PRICE=0.85/BTC5_MIN_BUY_PRICE=0.04/' .env
sudo systemctl restart btc-5min-maker.service
```
