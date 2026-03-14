# Cross-Market Arbitrage Scanner: Design Specification

**Source**: ChatGPT Pro research session (Prompt 5), March 14, 2026
**Status**: Reference document for implementation

## Architecture Overview

The scanner thinks in claims and transformations, not markets. A Polymarket binary market is one claim. A complement pair can be transformed back into $1 via merge. Cross-market arb becomes: find a set of claims whose worst-case payout is known, price the cheapest executable way to assemble that payout, and trade only when the locked edge exceeds all-in costs plus a safety buffer.

## Data Sources

- **Gamma API**: Market discovery via `GET /events` (primary crawler). Market objects expose `question`, `conditionId`, `outcomes`, `outcomePrices`, `active`, `closed`, `clobTokenIds`, `enableOrderBook`, `negRisk`.
- **CLOB WebSocket**: Public market channel with `custom_feature_enabled: true`. Streams `book`, `price_change`, `last_trade_price`, `best_bid_ask`, `market_resolved`.
- **CLOB REST**: `/books` supports batch orderbook requests for up to 500 tokens per call.
- **Kalshi API**: Public orderbook returns bids only. Reciprocal mapping: YES bid at x = NO ask at 1-x.

## Relationship Graph

Nodes = claims, edges = logical relations:
- `complement(A, not A)`
- `implies(A, B)`
- `disjoint(A, B)`
- `equivalent(A, B)`
- `partition_peer(A, event E)`
- `neg_risk_peer(A, event E)`

## Seven Arb Types

### Type 1: Complement Box
- Long box: Buy q YES + q NO, merge into USDC. Arb if q - Cost > delta.
- Short box: Split $q into YES+NO, sell both. Arb if Proceeds - q > delta.

### Type 2: Exhaustive Multi-Outcome Underround
- Buy YES in every named outcome. Cost = sum of asks. Payout = $1. Arb if 1 - Cost > delta.
- Exclude unnamed placeholders and "Other" in augmented neg-risk events.

### Type 3: Neg-Risk Conversion
- Buy No_i, convert to Yes_j for all j != i, sell the Yes basket.
- Arb if B_yes_basket(q) - A_no_i(q) - F - O_convert > delta.

### Type 4: Logical Implication
- If A implies B: buy YES(B) + NO(A). Min payout = $1.
- Arb if A_yes(B,q) + A_no(A,q) + F < q - delta.

### Type 5: Temporal Implication
- "X by June" implies "X by Dec". Same basket as implication.

### Type 6: Mutual Exclusion
- If A and B can't both be true: buy NO(A) + NO(B). Min payout = $1.

### Type 7: Cross-Platform Equivalence
- Same contract on Polymarket vs Kalshi. Buy cheap, sell expensive.
- Kalshi normalization: ask_yes = 1 - best_no_bid, ask_no = 1 - best_yes_bid.

## Matching Algorithm (Cascade)

1. **Deterministic parsing**: entities, thresholds, comparators, horizons, resolution sources
2. **Candidate generation**: same event, same category, same subject/metric, embedding ANN
3. **Relation classification**: LLM on shortlist, forced output with confidence
4. **Theorem checker**: Convert relations to feasible-state lattice, verify min payoff

## Execution Strategy

- Prefer routes that lock immediately (merge/convert > hold-to-resolution)
- FOK for mandatory full fills, FAK for partial-fill-tolerant legs
- Thin leg first, thick leg second for cross-platform
- Emergency unwind on hedge failure

## Cost Model

```
all_in_cost = taker_fees + slippage + split_merge_convert_cost + bridge_cost + gas_cost + latency_reserve
```

## Capital-Days ARR Framework

```
Expected PnL/day = sum_r lambda_r * p_r * S_r * e_r * (1 - m_r)
Capital-days/day = sum_r lambda_r * p_r * S_r * h_r
Capital-efficiency ARR = 365 * Expected_PnL/day / Capital-days/day
```

## Key Risks

- Partial-fill risk (one leg fills, one doesn't)
- Semantic risk (same headline, different settlement rule)
- Placeholder drift in augmented neg-risk events
- Latency/stale-book risk
- Capital lock until resolution for non-immediate arbs
- Cross-platform settlement mismatch
