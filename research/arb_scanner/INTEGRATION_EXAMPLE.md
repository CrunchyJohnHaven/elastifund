# Integration Example — Cross-Market Arbitrage Scanner

Demonstrates how to integrate the arbitrage scanner into an existing trading bot.

## Quick Start

### 1. Import and Initialize

```python
from research.arb_scanner import (
    ClaimGraph, normalize_polymarket_claim, normalize_kalshi_claim,
    build_relation_candidates, OrderBook, FeeModel,
    evaluate_all_opportunities, ExecutionRouter, PositionState
)

# Create graph and router
graph = ClaimGraph()
router = ExecutionRouter(
    max_concurrent_exposure=10000.0,
    daily_loss_cap=500.0,
)
```

### 2. Populate Claims from API

```python
# Fetch Polymarket markets
polymarket_markets = fetch_from_polymarket_api()
for event in polymarket_markets:
    for market in event.get('markets', []):
        claim = normalize_polymarket_claim(event, market)
        graph.add_claim(claim)

# Fetch Kalshi markets
kalshi_markets = fetch_from_kalshi_api()
for market in kalshi_markets:
    claim = normalize_kalshi_claim(market)
    graph.add_claim(claim)

print(f"Loaded {len(graph.claims)} claims")
```

### 3. Build Relationships

```python
claims = list(graph.claims.values())
relations = build_relation_candidates(claims)

for rel in relations:
    graph.add_relation(rel)

print(f"Built {len(graph.relations)} relationships")
```

### 4. Fetch Order Books

```python
books = {}
for claim in claims:
    # Fetch YES token book
    yes_book_data = fetch_orderbook(claim.venue, claim.yes_token_id)
    books[claim.yes_token_id] = OrderBook(
        venue=claim.venue,
        token_id=claim.yes_token_id,
        bids=yes_book_data['bids'],
        asks=yes_book_data['asks']
    )

    # Fetch NO token book
    no_book_data = fetch_orderbook(claim.venue, claim.no_token_id)
    books[claim.no_token_id] = OrderBook(
        venue=claim.venue,
        token_id=claim.no_token_id,
        bids=no_book_data['bids'],
        asks=no_book_data['asks']
    )
```

### 5. Scan for Opportunities

```python
fees = FeeModel()
opportunities = evaluate_all_opportunities(
    graph=graph,
    books=books,
    fees=fees,
    min_edge=0.01  # 1% minimum edge
)

# Sort by annualized return
opportunities.sort(key=lambda x: x.arr_pct(), reverse=True)

print(f"\nFound {len(opportunities)} opportunities:")
for opp in opportunities[:10]:
    print(f"  {opp.route}")
    print(f"    Edge: ${opp.net_locked_edge:.4f} ({opp.roi_pct():.2f}% ROI)")
    print(f"    Cost: ${opp.executable_cost:.4f}")
    print(f"    ARR: {opp.arr_pct():.1%}")
    print()
```

### 6. Execute Top Opportunity

```python
if opportunities:
    top_opp = opportunities[0]

    # Route to appropriate executor
    if "ComplementBox" in top_opp.route or "NegRisk" in top_opp.route:
        # Immediate transforms (instant merge/convert)
        position = router.execute_immediate_transform(top_opp, quantity=1.0)

    elif "CrossPlatform" in top_opp.route:
        # Cross-platform arbs (thin leg first, thick leg second)
        position = router.execute_cross_platform(top_opp, quantity=1.0)

    elif "Implication" in top_opp.route or "MutualExclusion" in top_opp.route:
        # Hold-to-resolution baskets
        position = router.execute_hold_to_resolution(top_opp, quantity=1.0)

    else:
        # Fallback: hold to resolution
        position = router.execute_hold_to_resolution(top_opp, quantity=1.0)

    print(f"\n✓ Executed position {position.position_id}")
    print(f"  State: {position.state.value}")
    print(f"  Expected P&L: ${position.target_edge:.2f}")
```

### 7. Monitor Positions

```python
# Periodic monitoring loop (e.g., every 10 seconds)
def monitor_loop():
    router.monitor_and_close()

    # Report active positions
    locked = router.list_positions(PositionState.LOCKED)
    held = router.list_positions(PositionState.HELD_TO_RESOLUTION)
    closed = router.list_positions(PositionState.CLOSED)

    print(f"Positions: {len(locked)} locked, {len(held)} held, {len(closed)} closed")
    print(f"Total exposure: ${router.total_exposure():.2f}")
    print(f"Total P&L: ${router.total_pnl():.2f}")

    # Emergency unwind if daily loss cap exceeded
    if router.total_pnl() < -router.daily_loss_cap:
        print("Daily loss cap exceeded! Unwinding all positions...")
        for pos in locked + held:
            router.emergency_unwind(pos)
```

---

## Full Integration Example

```python
import time
from research.arb_scanner import *

class ArbTradingBot:
    def __init__(self, api_keys):
        self.graph = ClaimGraph()
        self.router = ExecutionRouter(
            max_concurrent_exposure=10000.0,
            daily_loss_cap=500.0,
        )
        self.fees = FeeModel()
        self.api_keys = api_keys

    def refresh_market_data(self):
        """Fetch latest markets and order books."""
        claims = []

        # Polymarket
        pm_events = self.fetch_polymarket_events()
        for event in pm_events:
            for market in event.get('markets', []):
                claim = normalize_polymarket_claim(event, market)
                self.graph.add_claim(claim)
                claims.append(claim)

        # Kalshi
        ks_markets = self.fetch_kalshi_markets()
        for market in ks_markets:
            claim = normalize_kalshi_claim(market)
            self.graph.add_claim(claim)
            claims.append(claim)

        return claims

    def build_relationships(self, claims):
        """Build semantic relationships between claims."""
        relations = build_relation_candidates(claims)
        for rel in relations:
            self.graph.add_relation(rel)
        return relations

    def fetch_order_books(self, claims):
        """Fetch live order books for all tokens."""
        books = {}
        for claim in claims:
            for token_id in [claim.yes_token_id, claim.no_token_id]:
                if token_id not in books:
                    book_data = self.fetch_book(claim.venue, token_id)
                    books[token_id] = OrderBook(
                        venue=claim.venue,
                        token_id=token_id,
                        bids=book_data['bids'],
                        asks=book_data['asks']
                    )
        return books

    def scan_and_execute(self):
        """Main scanning loop."""
        print("=" * 60)
        print(f"Scanning at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        print("=" * 60)

        # Refresh data
        claims = self.refresh_market_data()
        print(f"✓ Loaded {len(claims)} claims")

        # Build relations
        relations = self.build_relationships(claims)
        print(f"✓ Built {len(relations)} relationships")

        # Fetch order books
        books = self.fetch_order_books(claims)
        print(f"✓ Fetched {len(books)} order books")

        # Scan for opportunities
        opportunities = evaluate_all_opportunities(
            self.graph, books, self.fees, min_edge=0.01
        )
        opportunities.sort(key=lambda x: x.arr_pct(), reverse=True)
        print(f"✓ Found {len(opportunities)} opportunities\n")

        # Display top 5
        for i, opp in enumerate(opportunities[:5]):
            print(f"{i+1}. {opp.route}")
            print(f"   Edge: ${opp.net_locked_edge:.4f} | "
                  f"ROI: {opp.roi_pct():.1f}% | ARR: {opp.arr_pct():.0%}\n")

        # Execute top opportunity
        if opportunities and self.router.total_exposure() < self.router.max_concurrent_exposure:
            top_opp = opportunities[0]

            # Determine execution strategy
            if any(x in top_opp.route for x in ["ComplementBox", "NegRisk"]):
                pos = self.router.execute_immediate_transform(top_opp, quantity=1.0)
            elif "CrossPlatform" in top_opp.route:
                pos = self.router.execute_cross_platform(top_opp, quantity=1.0)
            else:
                pos = self.router.execute_hold_to_resolution(top_opp, quantity=1.0)

            print(f"EXECUTED: {pos.position_id} | {pos.opportunity_route}")
            print(f"  Expected P&L: ${pos.target_edge:.2f}")
            print(f"  Execution cost: ${pos.execution_cost:.2f}")
            print(f"  State: {pos.state.value}\n")

        # Monitor existing positions
        self.router.monitor_and_close()

        locked = self.router.list_positions(PositionState.LOCKED)
        held = self.router.list_positions(PositionState.HELD_TO_RESOLUTION)
        closed = self.router.list_positions(PositionState.CLOSED)

        print(f"Position summary:")
        print(f"  Active (locked): {len(locked)}")
        print(f"  Held to resolution: {len(held)}")
        print(f"  Closed: {len(closed)}")
        print(f"  Total exposure: ${self.router.total_exposure():.2f}")
        print(f"  Total P&L: ${self.router.total_pnl():.2f}\n")

    def run_continuous(self, scan_interval_sec=10):
        """Run continuous scanning loop."""
        try:
            while True:
                self.scan_and_execute()
                print(f"Next scan in {scan_interval_sec}s...\n")
                time.sleep(scan_interval_sec)
        except KeyboardInterrupt:
            print("Shutting down...")
            for pos in self.router.list_positions():
                if pos.state not in (PositionState.CLOSED, PositionState.REDEEMED):
                    self.router.emergency_unwind(pos)

    # Stub API methods (implement with real API calls)
    def fetch_polymarket_events(self):
        return []

    def fetch_kalshi_markets(self):
        return []

    def fetch_book(self, venue, token_id):
        return {"bids": [], "asks": []}


# Main entry point
if __name__ == "__main__":
    bot = ArbTradingBot(api_keys={
        "polymarket": "...",
        "kalshi": "...",
    })
    bot.run_continuous(scan_interval_sec=10)
```

---

## Architecture Notes

### Claim Normalization
- Converts raw Polymarket/Kalshi market data into semantically rich Claims
- Each Claim contains parsed structure (subject, metric, threshold, horizon)
- Enables cross-venue equivalence matching

### Graph Building
- Relations are discovered via cascade: deterministic → rule-based → LLM
- Complement pairs (YES/NO) are detected deterministically
- Implication chains (A ⟹ B) are detected via predicate comparison
- Cross-platform equivalence matches claims across venues

### Opportunity Scoring
- Capital-days ARR is the primary metric (365 * daily_pnl / daily_capital_locked)
- Executable costs (book walk) are used instead of midpoints
- Fees and transform costs reduce edge to ensure profitability

### Risk Management
- Per-position kill switch and max loss tolerance
- Partial fill timeout triggers auto-unwind
- Router-level concurrent exposure cap and daily loss floor
- Emergency unwind on any constraint violation

---

## Tuning Parameters

```python
# FeeModel
fees = FeeModel(
    polymarket_taker_rate=0.02,        # 2% typical
    polymarket_maker_rate=0.0,         # Maker discount
    kalshi_taker_rate=0.01,            # 1% typical
    kalshi_maker_rate=0.0,
    transform_cost_rate=0.0005,        # 0.05% for split/merge
)

# ExecutionRouter
router = ExecutionRouter(
    max_concurrent_exposure=10000.0,   # Max capital deployed
    daily_loss_cap=500.0,              # Hard stop at -$500/day
    position_timeout_sec=60.0,         # Hold timeout
)

# Opportunity scanning
opportunities = evaluate_all_opportunities(
    graph, books, fees,
    min_edge=0.01  # Only report >1% edges
)
```

---

## Performance Tips

1. **Cache claims aggressively** — Rebuilding the graph from scratch on every scan is expensive. Maintain incremental state.

2. **Use indices for token lookups** — OrderBooks are frequently accessed; use a dict (as provided) for O(1) lookup.

3. **Batch order submissions** — Instead of submitting one leg at a time, group fills by venue and submit in batches.

4. **Prioritize immediate transforms** — Complement boxes resolve in seconds; hold-to-resolution positions lock capital for days.

5. **Monitor fill rates** — Track which venues are responsive. Deprioritize consistently slow venues.

6. **Rate-limit API calls** — Don't fetch all order books every second. Use 10-30s scan intervals instead.

---

## Debugging

Enable verbose logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Then trace opportunities:
for opp in opportunities[:1]:
    print(f"Opportunity: {opp.route}")
    print(f"  Legs: {opp.legs}")
    print(f"  Edge: ${opp.net_locked_edge:.4f}")
    print(f"  Cost breakdown:")
    for leg in opp.legs:
        print(f"    {leg['side']} {leg['token_id']}: ${leg.get('price', 'market')} x {leg['size']}")
```

Check position state transitions:

```python
pos = router.execute_immediate_transform(opp, quantity=1.0)
print(f"State: {pos.state.value}")
print(f"Legs: {len(pos.legs)}")
for leg in pos.legs:
    print(f"  {leg.side} {leg.size} @ {leg.avg_fill_price} (filled: {leg.filled})")
print(f"P&L: ${pos.compute_pnl():.2f}")
```

---

## Known Limitations

1. **Neg-risk placeholders** — Named outcomes only; unnamed "Other" definitions change.
2. **Partial fill recovery** — Unwind logic is basic; doesn't optimize prices across orderings.
3. **LLM relations** — Deterministic only; LLM verification is stubbed.
4. **Temporal arbs** — Date-based implication matching not yet implemented.
5. **Kalshi API** — Full order submission integration not yet implemented.
6. **Stale data** — Order book snapshots can be 1-2 seconds old; micro-arbs may be front-run.

---

*Last updated: March 14, 2026*
