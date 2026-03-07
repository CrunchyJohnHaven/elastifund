# Strategy Autopsy: R4 — Chainlink vs Binance Basis Lag

*Status: REJECTED | Tested: March 6, 2026 | Kill Reason: Taker fee exceeds spread*

---

## The Hypothesis

**Testable statement:** Polymarket crypto candle markets resolve using Chainlink oracle prices, which lag behind Binance spot prices by 1-30 seconds. By monitoring the Binance price in real-time and trading before the Chainlink oracle updates, we can predict the resolution outcome and trade profitably.

## The Mechanism

This is a classic oracle latency arbitrage. Two price feeds exist:

- **Binance spot price:** Updates every ~100ms. The "true" real-time price.
- **Chainlink oracle price:** Updates every ~15 seconds (or on 0.5% deviation). The price Polymarket ACTUALLY uses for resolution.

When Binance moves but Chainlink hasn't updated yet, you know where Chainlink is going. If a 5-minute candle market resolves based on whether BTC closes above the open, and Binance is already $200 above the open with 30 seconds left, Chainlink will almost certainly update to a price above the open too. Buy "Up" before the market prices this in.

## What We Expected

The Binance-Chainlink lag creates a 1-30 second window where the resolution outcome is nearly certain but the market hasn't fully adjusted. We expected to capture this window, particularly in the final 60 seconds of each candle.

## What Actually Happened

The strategy never generated a single trade. Kill reason: arithmetic.

**The fee calculation that killed it:**

Polymarket crypto market taker fee at mid-range prices (p ≈ 0.50):
```
Fee = feeRate × price × (1-price)^exponent
Fee = 0.25 × 0.50 × (0.50 × 0.50)^2
Fee ≈ 1.56%
```

The maximum observed Binance-Chainlink basis spread: 0.3-0.8%.

**0.8% edge - 1.56% fee = -0.76% net. Negative.**

The strategy is dead before testing because the fee exceeds any possible spread.

## The Transferable Insight

**Always compute the fee floor before writing a single line of code.** This strategy was killed by 30 seconds of arithmetic, not 30 hours of backtesting. The taker fee on crypto markets is the highest hurdle any speed-based strategy must clear, and most can't.

This is a universal lesson: in any market with transaction costs, the first question is "how much edge do I need just to break even?" If your expected edge is smaller than the transaction cost, stop. Don't build. Don't test. Don't hope.

**The follow-up question:** Can this strategy be executed with MAKER orders (0% fee)?

Yes — and that's exactly what we're building in our RTDS Maker Edge implementation (Dispatch #078). The same oracle latency thesis, but executed with limit orders posted before the candle resolves. The maker-only variant doesn't need to overcome the 1.56% taker fee hurdle. It needs to overcome only: fill risk (will someone take our limit order?) and adverse selection (does our order get filled only when we're wrong?).

The maker variant is fundamentally different from the taker variant. Same insight, completely different economics.

## The Fee Landscape (Why This Matters Beyond One Strategy)

The Polymarket fee structure creates a binary divide in strategy viability:

| Execution Mode | Fee | Strategies That Work | Strategies That Don't |
|---------------|-----|---------------------|----------------------|
| **Maker** | 0% + rebate | Almost any edge > 0.5% | None (it's free) |
| **Taker** | 1.0-1.56% | Only edges > 2% (rare) | Most speed/arb strategies |

An analysis of 72.1 million Polymarket trades (jbecker.dev) confirmed this divide empirically: makers earn +1.12% excess return, takers lose -1.12%. The fee structure is the single largest determinant of profitability.

Our architectural response: every strategy in the Elastifund system defaults to maker execution. The only exception is cross-platform arbitrage where execution speed matters and the edge is large enough (>3%) to survive taker fees.

## Code

Strategy implementation: `src/strategies/chainlink_basis_lag.py` (killed pre-signal)
Fee analysis: `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md`
Maker variant: `bot/fast_market_signal.py` (in development)

---

*This autopsy is part of the Elastifund Strategy Encyclopedia. The lesson here — compute fee breakeven before building — applies to every prediction market strategy.*
