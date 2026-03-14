# Cross-Market Arbitrage Scanner

Arbitrage detection and execution framework for Elastifund trading bot. Identifies and routes profitable opportunities across Polymarket and Kalshi prediction markets.

## Architecture Overview

The scanner operates on four core principles:

1. **Claims, not markets** — Normalize markets into semantic claims (e.g., "Will BTC close above $70,000 by Dec 31?")
2. **Relationships, not prices** — Build a graph of logical relationships between claims (equivalence, implication, complement, etc.)
3. **Executable costs, not midpoints** — Walk order books to discover realistic execution prices, avoiding false edges from display prices
4. **Capital-days efficiency** — Score opportunities by ARR, accounting for holding period and capital locked

## Core Components

### `claim_graph.py` — Normalization & Relationship Discovery

**Dataclasses:**
- `Claim` — Unified representation of a market across venues
- `ParsedPredicate` — Deterministic decomposition (subject, metric, comparator, threshold, horizon)
- `Relation` — Semantic connection between two claims
- `RelationType` (Enum) — Seven relationship types

**Key Functions:**
- `normalize_polymarket_claim(event, market)` — Convert Polymarket data to Claim
- `normalize_kalshi_claim(market)` — Convert Kalshi data to Claim
- `parse_predicate(question, description)` — Deterministic parser for BTC thresholds, dates, votes, etc.
- `build_relation_candidates(claims)` — Cascade: same-event deterministic → cross-event rule-based → embedding shortlist → LLM verification

**RelationType enum:**
- `EQUIVALENT` — Same outcome (e.g., "BTC > $70k" on two venues)
- `COMPLEMENT` — YES + NO = $1 (exhaustive outcomes)
- `IMPLIES` — If A true, B must be true
- `REVERSE_IMPLIES` — If B true, A must be true
- `DISJOINT` — Cannot both be true (mutually exclusive)
- `PARTITION_PEER` — Member of exhaustive partition (e.g., outcome 1 of 3)
- `NEG_RISK_PEER` — Linked under neg-risk rule
- `UNRELATED` — No meaningful connection

**Graph Queries:**
- `add_claim(claim)` — Register a claim
- `add_relation(relation)` — Register a relationship
- `get_connected_component(claim)` — All reachable claims via any path
- `find_implications_chain(claim_a, claim_b)` — Path of IMPLIES edges from A to B

---

### `opportunity_engine.py` — Arbitrage Templates & Detection

**Seven arbitrage templates** (inherit from `ArbTemplate`):

1. **ComplementBoxArb** — Buy YES + NO simultaneously, merge for $1
   - Sell Box: YES bid + NO bid > $1 (synthetic short)
   - Buy Box: YES ask + NO ask < $1 (cash arbitrage)
   - Instant payout

2. **UnderroundArb** — Buy all outcomes of exhaustive partition for < $1 total
   - Example: {BTC>70k, BTC 60-70k, BTC<60k} sum to $1 at resolution
   - One must be true; lock in profit

3. **NegRiskConversionArb** — In neg-risk markets, buy NO and convert to YES basket
   - NO holder receives YES portfolio on loss
   - Exploit mispricing in basket value

4. **ImplicationArb** — If A ⟹ B, buy YES(B) + NO(A) for < $1
   - Guaranteed payout: min($1, outcome at resolution)
   - Holds until resolution

5. **TemporalArb** — Jun event implies Dec event (nested dates)
   - Earlier event ⟹ Later event on same metric
   - Time value decay as earlier event resolves

6. **MutualExclusionArb** — If A ∨ B (one must be true), buy NO(A) + NO(B) for < $1
   - Example: "Trump wins" ∨ "Biden wins"
   - Guaranteed payout: $1

7. **CrossPlatformArb** — Same claim trades at different prices on Polymarket vs Kalshi
   - Buy cheap venue, sell expensive venue
   - Settlement risk: same-day execution

**Main API:**

```python
from arb_scanner import (
    ClaimGraph, normalize_polymarket_claim, normalize_kalshi_claim,
    build_relation_candidates, OrderBook, FeeModel, evaluate_all_opportunities
)

# Build graph
graph = ClaimGraph()
for pm_event in polymarket_events:
    for pm_market in pm_event.markets:
        claim = normalize_polymarket_claim(pm_event, pm_market)
        graph.add_claim(claim)

# Build relations (cascade: deterministic → rule-based → LLM)
relations = build_relation_candidates(list(graph.claims.values()))
for rel in relations:
    graph.add_relation(rel)

# Create order books for all tokens
books = {}  # token_id -> OrderBook

# Scan for opportunities
opportunities = evaluate_all_opportunities(
    graph=graph,
    books=books,
    fees=FeeModel(),  # Taker rates, transform costs
    min_edge=0.01  # 1% minimum edge threshold
)

# Sort by annualized return (capital-days ARR)
opportunities.sort(key=lambda x: x.arr_pct(), reverse=True)
```

**Capital-Days Scoring:**

```
Expected PnL/day = Σ λ_r * p_r * S_r * e_r * (1 - m_r)
Capital-days/day = Σ λ_r * p_r * S_r * h_r
Capital-efficiency ARR = 365 * Expected PnL/day / Capital-days/day
```

Where:
- `λ_r` = arrival rate (trades/day)
- `p_r` = execution probability
- `S_r` = position size
- `e_r` = edge per trade
- `m_r` = fee rate
- `h_r` = holding period (days)

**ArbOpportunity fields:**
- `route` — Template name + market identifiers
- `size_q` — Share units
- `net_locked_edge` — Expected profit ($)
- `executable_cost` — All-in cost including slippage & fees ($)
- `guaranteed_payout` — Minimum payout at resolution ($)
- `legs` — List of execution steps
- `holding_period_estimate` — Days until resolution
- `capital_days_return` — Daily ROI normalized for holding period
- `roi_pct()` — Simple ROI percentage
- `arr_pct()` — Annualized return

---

### `execution_router.py` — Order Routing & Position Management

**Position Lifecycle:**
```
DISCOVERED → ENTERING → PARTIALLY_FILLED → LOCKED → UNWINDING → HELD_TO_RESOLUTION → REDEEMED → CLOSED
```

**ExecutionLeg** — Single order on one venue:
- Venue, token_id, side (BUY/SELL), size
- Limit price, TIF (FOK/FAK/GTC)
- Fill tracking: filled, avg_fill_price, order_id

**ArbPosition** — Complete position with state tracking:
- position_id, opportunity_route, state
- All legs, fills, P&L
- created_at, locked_at, resolution_at, closed_at
- kill_switch, max_loss_tolerance, partial_fill_timeout_sec
- realized_pnl, unrealized_pnl

**ExecutionRouter** — Central orchestrator:
- `execute_immediate_transform()` — Complement/neg-risk boxes (instant merge/convert)
- `execute_cross_platform()` — Thin leg first, thick leg second (same-day settlement)
- `execute_hold_to_resolution()` — Implication/mutual-exclusion (30+ day holds)
- `emergency_unwind()` — Close at any price (partial fill recovery, kill switch, loss cap)
- `monitor_and_close()` — Market resolution triggers, timeout enforcement
- `get_position()`, `list_positions()`, `total_exposure()`, `total_pnl()`

**Risk Management:**
- Per-position kill switch
- Per-position max loss tolerance
- Partial fill timeout → auto-unwind if not locked within N seconds
- Venue-level kill switch (stub)
- Max concurrent exposure cap (router-level)
- Daily loss cap with automatic floor (router-level)

---

## Usage Example

```python
from arb_scanner import (
    ClaimGraph, normalize_polymarket_claim,
    OrderBook, FeeModel, evaluate_all_opportunities,
    ExecutionRouter, PositionState
)

# 1. Build claim graph
graph = ClaimGraph()
for market in get_all_markets():
    claim = normalize_polymarket_claim(market.event, market)
    graph.add_claim(claim)

# 2. Find opportunities
books = {}
for token in get_all_tokens():
    books[token.id] = OrderBook(
        venue=token.venue,
        token_id=token.id,
        bids=token.order_book.bids,
        asks=token.order_book.asks
    )

opportunities = evaluate_all_opportunities(
    graph, books, min_edge=0.01
)

# 3. Execute top opportunity
if opportunities:
    top_opp = opportunities[0]
    router = ExecutionRouter(
        max_concurrent_exposure=10000.0,
        daily_loss_cap=500.0,
        position_timeout_sec=60.0
    )

    if top_opp.route.startswith("ComplementBox"):
        position = router.execute_immediate_transform(top_opp, quantity=10.0)
    elif top_opp.route.startswith("Implication"):
        position = router.execute_hold_to_resolution(top_opp, quantity=10.0)
    elif top_opp.route.startswith("CrossPlatform"):
        position = router.execute_cross_platform(top_opp, quantity=10.0)

    print(f"Position {position.position_id}: {position.state.value}")
    print(f"Expected P&L: ${position.target_edge:.2f}")
    print(f"Capital locked: ${position.execution_cost:.2f}")
    print(f"ARR: {position.target_edge / (position.execution_cost * (30/365)):.1%}")

# 4. Monitor positions
router.monitor_and_close()
for pos in router.list_positions(PositionState.CLOSED):
    print(f"Position {pos.position_id} closed: ${pos.realized_pnl:.2f}")
```

---

## Fee Model

**Polymarket:**
- Taker: 2% (varies by token; dynamic from fee-rate endpoint)
- Maker: 0%
- Split/Merge: gasless via relayer (0.05% transform cost)

**Kalshi:**
- Taker: 1% (varies by series)
- Maker: 0%
- No transform cost (USDC settlement)

**Transform costs** (split, merge, convert in neg-risk markets):
- ~0.05% of size (rate limit cost, no gas)

---

## Design Principles

### Think in Claims, Not Markets

Raw markets are noisy. Normalize into claims with semantic meaning:

```python
# Raw Polymarket market
{
  "id": "0x123abc",
  "question": "Will Bitcoin close above $70,000 on Dec 31 2024?",
  "tokens": {"1": "YES_0x123", "0": "NO_0x456"}
}

# Normalized to Claim
Claim(
  venue="polymarket",
  event_id="...event_id...",
  market_id="0x123abc",
  question="...",
  parsed_predicate=ParsedPredicate(
    subject="BTC",
    metric="price",
    comparator=">",
    threshold=70000.0,
    horizon="2024-12-31"
  )
)
```

### Use Executable Book Prices, Never Midpoints

Midpoints lie. Walk the book:

```python
book.walk_book_buy(size=100.0)  # Cost to buy 100 shares at market
book.walk_book_sell(size=100.0)  # Proceeds to sell 100 shares at market
```

### Prefer Immediate Transforms Over Hold-to-Resolution

Complement boxes resolve in seconds. Hold the certainty, not the time.

### Never Trade on Unnamed Neg-Risk Placeholders

Neg-risk "Other" definitions change. Only trade named outcomes.

### LLM Proposes, Deterministic Solver Authorizes

LLM can suggest relations; deterministic rules must verify before trading.

### Capital-Days Scoring Over Raw Cents

$100 edge held 30 days = $100 edge held 1 day / 30. Score by ARR, not absolute profit.

---

## Testing

All modules pass `python3 -c "import ast; ast.parse(open(file).read())"` syntax check.

Run tests in a standard Python environment:

```bash
cd /tmp/arb_scanner
python3 -c "import __init__; from claim_graph import *; from opportunity_engine import *; from execution_router import *; print('Syntax OK')"
```

---

## Deployment

1. Copy to repo: `cp -r /tmp/arb_scanner/* /path/to/repo/research/arb_scanner/`
2. Install in bot: `from research.arb_scanner import evaluate_all_opportunities, ExecutionRouter`
3. Wire into trading loop: query claim graph, scan for opps, execute via router

---

## Future Enhancements

- **LLM relation verification** — Call Claude to validate borderline propositions
- **Embedding similarity** — Vector search for near-equivalent claims across venues
- **Real-time market data** — Live order book streaming instead of snapshot books
- **Partial fill recovery** — Smarter unwinding logic (don't sell at worst prices)
- **Kalshi integration** — Full API support for market fetch, order submission, balance tracking
- **Stablecoin arbitrage** — Cross-USDC/USDT flows between venues
- **AMM interaction** — Uniswap-style pool pricing for less-traded tokens
- **Risk attribution** — Decompose position P&L by market, relation, and execution step

---

## References

- **Polymarket API** — https://clob.polymarket.com/docs (order book, trades, markets)
- **Kalshi API** — https://trading-api.kalshi.com (markets, orders, portfolio)
- **Kelly Criterion** — Position sizing for maximum long-term growth
- **Stale Price Theory** — Why midpoints are stale; executable prices matter
