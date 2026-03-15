# DISPATCH 106: Fair Value Integration — The Real Edge

**Strategic dispatch. Apply when DISPATCH_104 and 105 are stable and generating fills.**

---

## Context

DISPATCHes 103-105 get us from zero fills to positive-EV trading by:
- 103: Bypassing the delta gate (spread-capture mode)
- 104: Only trading near-certain outcomes (min_buy_price=0.85)
- 105: Picking the right direction using BTC spot vs open

But the REAL edge — the one that scales — comes from fair value pricing. We built a complete pricing engine in `research/wallet_intelligence/btc5_fair_value_spec.py` that computes theoretically correct BTC5 token prices using:
- GBM (Geometric Brownian Motion) base probability
- EWMA + GARCH(1,1) volatility estimation
- Student-t heavy tails for BTC's fat-tailed distribution
- Merton jump-diffusion overlay
- Cross-venue reference pricing (Binance + Coinbase)
- Fill probability and adverse-selection-adjusted maker EV

## The Integration Plan

### Phase 1: Shadow Fair Value (no trading changes)

Add fair value computation to every window evaluation. Log it alongside the existing decision. Don't change any trading logic yet.

```python
# In _process_window, after getting open_price and current_price:
from research.wallet_intelligence.btc5_fair_value_spec import (
    compute_fair_value, FairValueInputs
)

fv_inputs = FairValueInputs(
    btc_spot=current_price_usd,  # actual BTC spot, not BTC5 price
    strike=strike_price_usd,
    time_remaining_sec=window_end_ts - int(time.time()),
    volatility_1m=recent_1m_vol,  # from Binance feed
)
fair_value = compute_fair_value(fv_inputs)

logger.info("Fair value: UP=%.4f DOWN=%.4f | Market: UP_bid=%.2f DOWN_bid=%.2f | Edge: %.4f",
    fair_value.up_prob, fair_value.down_prob,
    up_best_bid, down_best_bid,
    fair_value.up_prob - up_best_ask)  # positive = we should buy
```

### Phase 2: Fair-Value-Informed Direction

Replace the spread-capture direction logic with fair value:
- If `fair_value.up_prob > market_up_ask + min_edge`: buy UP
- If `fair_value.down_prob > market_down_ask + min_edge`: buy DOWN
- If neither: skip (no edge)

This is strictly better than "buy whichever token is more expensive" because it accounts for volatility, time decay, and jump risk.

### Phase 3: Fair-Value-Informed Sizing

Kelly criterion on the fair value edge:
```
f* = (p * b - q) / b
```
Where:
- p = fair_value probability
- q = 1 - p
- b = (1 / market_price) - 1  (odds)

Scale position size by Kelly fraction instead of fixed $5/$10.

### Phase 4: Full Integration

Wire the pricing engine into the main loop:
1. Compute fair value every window
2. Compare to executable book prices (not midpoints)
3. Trade only when edge > fees + spread + safety buffer
4. Size by Kelly
5. Track fair_value_edge vs realized_pnl for calibration

## Implementation Notes

The fair value engine (`btc5_fair_value_spec.py`) is already committed to the repo at:
```
research/wallet_intelligence/btc5_fair_value_spec.py
```

It needs these inputs per window:
- BTC spot price (from Binance WebSocket — already connected)
- Strike price (derived from market question parsing)
- Time remaining in seconds (trivial to compute)
- Recent realized volatility (from Binance 1m klines — already fetched)

The engine outputs:
- `up_probability`, `down_probability`
- `model_uncertainty` (from GARCH)
- `jump_adjustment` (from Merton)
- `recommended_direction`
- `expected_edge_cents`

## Dependencies

- `research/wallet_intelligence/btc5_fair_value_spec.py` must be on VPS
- numpy must be installed (already is)
- No other external dependencies

## Timeline

- Phase 1 (shadow logging): Deploy after 24h of stable DISPATCH_104/105 fills
- Phase 2 (direction): Deploy after 48h of shadow data confirms fair value is calibrated
- Phase 3 (sizing): Deploy after Phase 2 shows positive edge
- Phase 4 (full): After 1 week of Phase 2/3 validation

## Success Criteria

- Phase 1: Fair value logs show >60% directional accuracy vs resolution
- Phase 2: Win rate improves from ~60% to ~70%+
- Phase 3: Average PnL per fill increases 2x+
- Phase 4: Positive daily PnL with <$50 max drawdown
