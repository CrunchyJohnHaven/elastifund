# DISPATCH 105: Smart Direction — Use BTC Spot vs Strike Instead of Alternating

**Apply AFTER DISPATCH_104 is live and stable. Not urgent — DISPATCH_104 alone fixes the bleeder.**

---

## Problem

Spread-capture mode alternates UP/DOWN each window blindly:
```python
direction = "UP" if (window_start_ts // 300) % 2 == 0 else "DOWN"
```

This is statistically neutral but dumb. BTC5 markets have a STRIKE PRICE. If current BTC spot is above the strike, the UP token is near-certain. If below, the DOWN token is near-certain. We should buy whichever token is winning, not alternate randomly.

## The Fix

When spread-capture fires (delta below threshold), pick the direction based on which token is MORE likely to win — i.e., which token is priced higher. The book already tells us this: if UP token bid > DOWN token bid, buy UP.

But we can do better: check the ACTUAL BTC spot price vs the market's strike price.

## Code Change

In `bot/btc_5min_maker.py`, replace the spread-capture bypass block:

**Find:**
```python
        if direction is None and self.cfg.enable_spread_capture:
            # Spread-capture mode: bypass delta gate when BTC is flat.
            # Alternate UP/DOWN each window for statistical neutrality.
            direction = "UP" if (window_start_ts // 300) % 2 == 0 else "DOWN"
            delta = (current_price - open_price) / open_price if open_price > 0 else 0.0
            logger.info(
                "Spread-capture mode: delta=%.6f below threshold, "
                "forcing direction=%s for window %d",
                abs(delta), direction, window_start_ts,
            )
```

**Replace with:**
```python
        if direction is None and self.cfg.enable_spread_capture:
            # Spread-capture mode: bypass delta gate when BTC is flat.
            # Pick whichever direction has the near-certain token.
            # If BTC spot > open (even slightly), UP is winning.
            # If BTC spot <= open, DOWN is winning.
            # At worst this is a coin flip; at best it's informed.
            if current_price > open_price:
                direction = "UP"
            elif current_price < open_price:
                direction = "DOWN"
            else:
                # Exactly equal: alternate for neutrality
                direction = "UP" if (window_start_ts // 300) % 2 == 0 else "DOWN"
            delta = (current_price - open_price) / open_price if open_price > 0 else 0.0
            logger.info(
                "Spread-capture mode: delta=%.6f below threshold, "
                "forcing direction=%s (spot-informed) for window %d",
                abs(delta), direction, window_start_ts,
            )
```

## Why This Matters

Combined with DISPATCH_104 (min_buy_price=0.85), this means:
1. We pick the direction BTC is actually leaning (even by $1)
2. We only buy the token if it's priced >= 0.85 (near-certain)
3. If the "winning" token is only at 0.60, it gets rejected by the price floor
4. If it's at 0.95, we buy it and earn the spread

This is not prediction. This is observation. BTC already moved (even slightly). The market already priced the tokens. We just buy the cheap end of the near-certain token and earn the maker rebate.

## Apply

```bash
cd /home/ubuntu/polymarket-trading-bot
# Make the edit (use your preferred method — sed, python, or manual)
# Then:
sudo systemctl restart btc-5min-maker.service
```

## Verification

```bash
sudo journalctl -u btc-5min-maker.service -f | grep 'Spread-capture'
```

Should show `spot-informed` in the log message.
