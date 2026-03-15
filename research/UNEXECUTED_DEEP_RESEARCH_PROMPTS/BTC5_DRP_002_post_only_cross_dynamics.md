---
id: BTC5_DRP_002
title: Post-Only Cross Rejection Dynamics on Polymarket
tool: CHATGPT_DEEP_RESEARCH
priority: P0
status: READY
created: 2026-03-09
---

# Post-Only Cross Rejection Dynamics on Polymarket

## Context

The BTC5 maker bot experiences `live_order_failed` as its second-largest drag bucket
(19 events out of ~99 windows). A significant fraction of these failures are post-only
cross rejections — the CLOB rejects the order because the proposed price would
immediately match against a resting ask, violating the post-only constraint.

The bot already implements `_retry_post_only_cross()` which:
1. Detects "post-only crosses book" error strings
2. Refreshes the order book
3. Computes a safer price with `retry_post_only_safety_ticks` offset
4. Re-submits if the new price is still within guardrails

Despite this, cross rejections remain a major fill-rate drag.

## Research Questions

1. **Cross rejection mechanics**: What exactly triggers a post-only cross rejection
   on Polymarket's CLOB? Is it a strict best-ask comparison, or does it account for
   the full book? Does order size matter (would a large order cross deeper levels)?

2. **Book staleness window**: When the bot reads best_bid/best_ask at T-10 and places
   an order, how quickly can the book move such that the order crosses by the time it
   reaches the matching engine? What is the typical latency from API read to order
   acceptance on Polymarket?

3. **Retry effectiveness**: Is a single retry sufficient, or would multiple retries
   with progressive tick backing yield better results? What is the empirical latency
   of the retry cycle (read book + compute price + resubmit)?

4. **Pre-cross detection**: Can the bot predict cross likelihood from the book state?
   E.g., if spread is 1 tick, any aggression above 0 ticks will cross. What spread
   thresholds make post-only quoting viable vs impossible?

5. **Alternative order types**: Does Polymarket support any alternative order types
   (IOC with maker-only flag, etc.) that could achieve fills without crossing risk?

## Formulas Required

- **Cross probability**: P(cross | spread, aggression_ticks, latency)
  = P(ask moves down by ≥ (aggression_ticks - spread_ticks + 1) in latency_ms)
- **Retry success rate**: P(retry_fill | first_cross) as function of safety_ticks
  and book refresh latency
- **Effective fill rate after retry**:
  P(fill_total) = P(fill_first) + P(cross_first) × P(fill_retry)
- **Spread-conditional strategy**:
  optimal_aggression(spread) = max(0, spread_ticks - safety_margin)

## Measurable Hypotheses

H1: >60% of post-only cross rejections occur when the spread at quote time was
    ≤2 ticks (≤$0.02).

H2: Adding a second retry with 2× safety ticks would recover >30% of currently
    failed orders.

H3: Pre-filtering windows where spread < 3 ticks to use 0 aggression ticks
    (bid-match only) reduces cross rate by >50% with <10% fill rate loss.

H4: The median latency between book read and order acceptance on Polymarket is
    >200ms, sufficient for meaningful book movement on volatile 5-min close windows.

## Failure Modes

- **Polymarket CLOB documentation gap**: The matching engine behavior may not be
  publicly documented. If so, the research should specify empirical tests the bot
  can run to characterize cross behavior.
- **Latency measurement**: The bot currently does not measure round-trip order latency.
  If latency is a key variable, specify what instrumentation to add.
- **Adversarial book dynamics**: Near close, informed participants may move the book
  specifically to exploit passive makers. Address whether this is a realistic concern
  at $5-$10 order sizes.

## Direct Repo Integration Targets

- `bot/btc_5min_maker.py`: `_retry_post_only_cross()` — multi-retry logic
- `bot/btc_5min_maker.py`: `choose_maker_buy_price()` — spread-conditional aggression
- `bot/btc_5min_maker.py`: Add latency instrumentation (order_placed_at, order_acked_at)
- `bot/btc_5min_maker.py`: Add `spread_at_quote` to persisted decision rows
- `BTC5Config`: New field `min_spread_for_aggression` — skip aggression when spread is too tight
