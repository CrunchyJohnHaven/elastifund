---
id: BTC5_DRP_001
title: Maker Queue Priority and Passive Fill Optimization on Polymarket CLOB
tool: CHATGPT_DEEP_RESEARCH
priority: P0
status: READY
created: 2026-03-09
---

# Maker Queue Priority and Passive Fill Optimization

## Context

Elastifund's BTC 5-minute candle maker (`bot/btc_5min_maker.py`) places post-only
BUY orders on Polymarket's CLOB within the last 10 seconds of each 5-minute window.
Current live evidence: 56 fills out of ~99 windows attempted. The largest drag bucket
is `skip_price_outside_guardrails` (20 events) followed by `live_order_failed` (19).
Of successful fills, DOWN direction dominates (41 fills, +$72.40) and the best price
bucket is <0.49 (19 fills, +$56.30).

The system uses `choose_maker_buy_price()` which picks a price N ticks above best bid
(aggression ticks) with a post-only safety offset. When the order crosses the book,
it retries at a safer price. When no fill occurs by T-2 seconds, the order is cancelled.

## Research Questions

1. **Queue position dynamics on Polymarket CLOB**: How does queue priority work for
   post-only limit orders? Is it pure price-time priority? Does order size affect
   fill probability at the same price level?

2. **Optimal aggression tick selection**: Given a 8-second fill window (T-10 to T-2),
   what is the empirically optimal number of aggression ticks above best bid to
   maximize fill rate while remaining passive? Is there a closed-form approximation
   relating aggression ticks to fill probability given typical book depth?

3. **Book depth profile near close**: What does the Polymarket CLOB order book
   typically look like for 5-minute BTC candle markets in the last 30 seconds?
   How thin or thick is the book? How volatile is the top-of-book in this window?

4. **Partial fill handling**: Does Polymarket's CLOB support partial fills on limit
   orders? If so, what is the typical partial fill rate for small ($5) orders at
   various price levels?

## Formulas Required

- **Fill probability model**: P(fill | aggression_ticks, book_depth, time_to_close)
  — derive or cite an empirical/theoretical model.
- **Expected PnL per window**: E[PnL] = P(fill) × P(win|fill) × (1 - price) × shares
  - P(loss|fill) × price × shares - (1 - P(fill)) × opportunity_cost
- **Optimal aggression**: argmax_{ticks} E[PnL(ticks)] subject to post-only constraint
- **Queue position decay**: If placed at time T-10, what fraction of the queue is
  ahead at typical Polymarket volumes?

## Measurable Hypotheses

H1: Increasing aggression from 0 to 2 ticks above best bid increases fill rate by
    >15 percentage points on 5-minute BTC candle markets.

H2: Orders placed at T-10 achieve >50% fill rate when best bid is below 0.49 for
    DOWN direction markets.

H3: The marginal PnL impact of moving from 1 to 2 aggression ticks is negative
    (crossing into adverse selection territory).

H4: Queue position within the T-10 to T-2 window is dominated by price level,
    not time priority, for typical book depths of <$500 at best bid.

## Failure Modes

- **Data availability**: Polymarket may not publish historical book snapshots. If so,
  specify what data collection the bot should add to answer these questions empirically.
- **Regime dependence**: Queue dynamics may differ between low-vol and high-vol BTC
  periods. Research should address whether the model needs regime conditioning.
- **Minimum size constraints**: At $5 trade size, the bot may be in a regime where
  CLOB minimums (5 shares) dominate the fill dynamics. Address whether the analysis
  changes materially at $5 vs $10 vs $25 trade sizes.

## Direct Repo Integration Targets

- `bot/btc_5min_maker.py`: `choose_maker_buy_price()` — aggression tick selection
- `bot/btc_5min_maker.py`: `BTC5Config.aggression_ticks` — parameterize per-direction
- `bot/btc_5min_maker.py`: `_retry_post_only_cross()` — retry logic improvement
- `data/btc_5min_maker.db`: `decisions` table — add book depth snapshot columns
- New: consider adding a `book_depth_at_quote` field to persisted decisions
