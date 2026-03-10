---
id: BTC5_DRP_005
title: Small-Size Maker Execution Under Changing Spread and Queue Depth
tool: CHATGPT_DEEP_RESEARCH
priority: P1
status: READY
created: 2026-03-09
---

# Small-Size Maker Execution Under Changing Spread and Queue Depth

## Context

The BTC5 maker bot trades at $5 per window (configurable, considering $10). At these
sizes, the bot is a small participant on the Polymarket CLOB. The minimum order is
5 shares, and the CLOB has a $0.01 tick size. Current fill rate is ~57% (56/99 windows
attempted) with 3 cancelled-unfilled events.

The scaling question is whether moving from $5 to $10 per trade materially changes
execution quality, and whether the current maker approach remains viable as the bot
scales or as market conditions change.

## Research Questions

1. **Size-dependent fill probability**: On prediction market CLOBs, does a larger
   resting order have a higher, lower, or equal fill probability compared to a
   smaller order at the same price? Consider:
   - Full-fill vs partial-fill dynamics
   - Whether takers preferentially hit larger resting orders
   - Whether the matching engine fills pro-rata or FIFO at the same price

2. **Spread dynamics on Polymarket 5-min BTC markets**: What is the typical
   bid-ask spread on these contracts at various times during the 5-minute window?
   How does the spread behave as close approaches? Does it widen (less liquidity)
   or narrow (more informed quoting)?

3. **Queue depth characterization**: At the best bid level on a typical 5-min BTC
   market, how much resting size is there? How does this compare to the bot's
   $5-$10 order? Is the bot typically first in queue, middle, or back?

4. **Scaling from $5 to $10 to $25**: What changes at each size threshold?
   Consider:
   - Minimum share constraints becoming non-binding
   - Notional becoming large enough to move the book
   - Fill quality degradation from information leakage
   - Position P&L variance increase (Kelly sizing implications)

5. **Adverse selection at small size**: Is a $5 maker order adversely selected
   differently than a $50 order? In traditional markets, small orders face less
   adverse selection because informed traders prefer size. Does this hold on
   prediction market CLOBs?

## Formulas Required

- **Fill probability vs size**: P(fill | size, price, queue_ahead, time_window)
  For FIFO matching: P(fill) = P(total_taker_volume ≥ queue_ahead + size)
  For pro-rata: P(fill) ≈ min(1, size/total_resting × E[taker_volume])

- **Optimal sizing given Kelly**: f* = (p(1-a) - (1-p)a) / ((1-a)a) where
  p = win probability, a = price paid. With execution uncertainty:
  f*_adjusted = f* × P(fill) × (1 - adverse_selection_cost/edge)

- **Break-even fill rate**: P(fill)_min = fixed_cost / (E[PnL|fill] × windows_per_day)
  At $5/trade, E[PnL|fill] ≈ $1.64 (live average), 288 windows/day:
  P(fill)_min = 0 if no fixed cost, but opportunity cost of capital matters.

- **Variance of daily PnL**:
  Var[daily_PnL] = N_windows × P(fill) × Var[PnL_per_fill]
  At $5/trade: Var[PnL_per_fill] ≈ ($5)² × p(1-p) where p ≈ 0.7

- **Information leakage threshold**: Size at which the bot's order represents
  >10% of the typical taker flow per window. If taker flow ≈ F per window,
  then leakage threshold ≈ 0.1 × F.

## Measurable Hypotheses

H1: Doubling trade size from $5 to $10 does NOT reduce fill rate by more than
    5 percentage points (from ~57% to ≥52%).

H2: At $5 trade size, the bot's order represents <5% of total resting size at
    best bid, meaning queue position is the dominant fill determinant, not size.

H3: The bid-ask spread on 5-min BTC candle markets widens by >$0.02 in the
    last 30 seconds vs the prior 4.5 minutes (liquidity withdrawal near close).

H4: Adverse selection cost per fill is <$0.10 at $5 size and <$0.15 at $10 size
    (small enough that the +$1.64 average fill PnL absorbs it).

H5: At $25 per trade, the bot's fill probability drops below 40% due to
    queue effects, making the strategy unviable at that size.

## Failure Modes

- **Market regime change**: If BTC 5-min candle markets become more popular
  (more volume), the competitive dynamics change. The bot might face more
  sophisticated makers. Specify signals that would indicate increased competition.
- **Polymarket fee changes**: If maker fees change from 0% to any positive value,
  the edge calculation changes materially. Specify break-even maker fee.
- **Minimum order size changes**: If Polymarket increases minimums from 5 shares,
  smaller positions become impossible. Specify the bot's response.
- **Book data lag**: The bot reads book state via REST API, which may be stale
  compared to WebSocket feeds. If staleness is >500ms, the fill probability
  model needs a staleness discount.

## Direct Repo Integration Targets

- `bot/btc_5min_maker.py`: `BTC5Config.max_trade_usd` — inform the $5→$10 decision
- `bot/btc_5min_maker.py`: `clob_min_order_size()` — verify minimum constraints
  are correctly handled at larger sizes
- `bot/btc_5min_maker.py`: Add `queue_depth_at_quote` to persisted decisions
- `scripts/btc5_hypothesis_lab.py` — add size-variant hypothesis families
- `scripts/run_scale_comparison.py` — incorporate execution quality vs size analysis
- New: `scripts/btc5_size_scaling_analysis.py` — offline analysis using persisted
  fill data to test size-fill-rate relationship
