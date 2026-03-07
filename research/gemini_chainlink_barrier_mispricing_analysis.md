# Gemini Research Dispatch: Chainlink Barrier Mispricing Analysis
**Date:** 2026-03-07
**Source:** Gemini Deep Research
**Status:** INTEGRATED into RTDS_MAKER_EDGE_IMPLEMENTATION.md and edge_backlog_ranked.md
**Relevance:** HIGH — validates and extends our existing RTDS maker edge research

---

## Summary

External Gemini research validates the structural edge hypothesis we identified in `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md`. The report independently arrives at the same conclusion: Polymarket 15-minute BTC markets are structurally mispriced because participants anchor to Binance spot feeds while resolution uses Chainlink oracle feeds.

## Key Findings Integrated

### 1. Polynomial Fee Formula (Confirmed)
```
Fee = C × p × feeRate × (p × (1-p))^exponent
- Crypto: feeRate=0.25, exponent=2, max 1.56% at p=0.50
- Sports: feeRate=0.0175, exponent=1, max 0.44% at p=0.50
- Maker fees: 0% + 20% rebate pool from taker fees
```
This matches our existing fee research. The formula is now recorded with exact parameters.

### 2. Tie-Band Convexity Thesis
The "Up" contract resolves favorably if terminal price >= opening price (greater than OR EQUAL TO). At 8-decimal Chainlink precision, there is a non-zero probability of exact tie, creating structural asymmetry favoring "Up" over "Down."

**JJ Assessment:** Mathematically correct but practically thin. Our R1 (Residual Horizon Fair Value) was essentially a simplified version of this thesis. It produced 8 signals with 50% win rate — insufficient for validation. The tie probability at BTC's 8-decimal precision is minuscule except in extremely low-vol micro-windows in final seconds. The edge is real but likely <10bps alone. Worth monitoring as a secondary signal enhancer, not a standalone strategy.

### 3. Shadow Validator Architecture
The report proposes a 72-hour paper trading validation framework with:
- Simulated taker execution at resting Ask/Bid with polynomial fee subtracted
- Simulated maker execution requiring trade-through fill (strict adverse selection filter)
- Millisecond-precision timestamping
- Post-resolution reconciliation

**JJ Assessment:** Good architecture. Similar to our existing hypothesis testing pipeline in `src/backtest.py` but with tighter execution simulation. The "trade-through for maker fills" requirement is the right level of conservatism. Should be incorporated into our pipeline's maker fill rate assumptions.

### 4. Latency Geography (Confirmed)
| Location | Latency to CLOB (eu-west-2) |
|----------|----------------------------|
| London (eu-west-2) | <1ms |
| Dublin (eu-west-1) | 10-15ms |
| New York | 70-80ms |
| Chicago | 85-95ms |

Matches our `research/LatencyEdgeResearch.md` findings exactly. Dublin is competitive.

## What This Changes

Nothing fundamental. The Gemini research independently validates our RTDS maker edge hypothesis and adds precision to the fee formula. The tie-band convexity is a marginal signal enhancer worth ~0-10bps, not a standalone edge.

**Action items already completed:**
- Fee formula parameters recorded in DEEP_RESEARCH_PROMPT_v3.md
- Tie-band assessment recorded in edge_backlog_ranked.md context
- Maker-first execution paradigm already central to our RTDS implementation spec
- Shadow validator architecture concept noted for pipeline improvements

---

*This dispatch is part of the Elastifund research flywheel. Research dispatch #75.*
