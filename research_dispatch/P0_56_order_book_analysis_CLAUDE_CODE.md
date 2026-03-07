# P0-56: Real-Time Order Book Analysis & Execution Intelligence
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Understanding order book depth is critical for live trading execution
**Expected ARR Impact:** Prevents slippage losses, enables smarter order placement

## Problem
We're about to go live but have zero understanding of the actual order books on our target markets. Paper trading assumes instant fills at exact prices. Live trading requires understanding depth, spread, and optimal order placement.

## Task

1. **Build an order book monitor:**
   ```python
   class OrderBookMonitor:
       def __init__(self):
           self.ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/"

       async def subscribe_to_books(self, market_ids: list[str]):
           """Subscribe to L2 order book updates via WebSocket."""

       def analyze_book(self, book: dict) -> dict:
           """Analyze a market's order book.
           Returns:
           {
               "bid_ask_spread": 0.03,
               "midpoint": 0.52,
               "best_bid": 0.505,
               "best_ask": 0.535,
               "bid_depth_5pct": 150.00,  # $ available within 5% of midpoint
               "ask_depth_5pct": 200.00,
               "imbalance": 0.25,  # (bid_vol - ask_vol) / total_vol
               "estimated_fill_price_2usd": 0.535,  # what price for $2 market buy
               "estimated_slippage_2usd": 0.015,
               "recommendation": "limit_at_0.52"  # optimal order placement
           }
           ```

2. **Slippage estimation before every trade:**
   - Before placing any trade, fetch the order book
   - Estimate actual fill price for our intended position size
   - If slippage > 2% of position, use limit order instead of market order
   - If slippage > 5%, skip the trade entirely
   - Log estimated vs actual fill prices for post-hoc analysis

3. **Order book recording for future analysis:**
   - Record order book snapshots for all markets we trade (every 5 minutes)
   - Store in `data/orderbook_snapshots/` — compressed JSON
   - Use for future backtest improvements (real slippage data instead of estimates)

4. **Smart order placement:**
   ```python
   class SmartOrderPlacer:
       def compute_optimal_order(self, signal: dict, book: dict) -> dict:
           """Determine optimal order type and price.

           Logic:
           1. If spread is tight (<2¢) and depth is good: limit at midpoint
           2. If spread is wide: limit at favorable side of spread
           3. If urgency is high (market resolving soon): limit just behind best bid/ask
           4. Never use market orders (taker fees + slippage)
           """
   ```

5. **Order book-based confidence signal:**
   - Large bid imbalance (more buyers than sellers) → market likely to move up
   - Large ask imbalance → market likely to move down
   - If order book direction agrees with Claude's signal → higher confidence → larger position
   - If order book direction disagrees → lower confidence → smaller position or skip

## Files to Create
- NEW: `src/orderbook_monitor.py` — WebSocket L2 book subscriber
- NEW: `src/smart_order.py` — intelligent order placement logic
- MODIFY: `src/broker/` — integrate order book analysis before order submission
- MODIFY: `src/paper_trader.py` → `src/trader.py` — use real order book data

## Expected Outcome
- Real understanding of execution conditions on our target markets
- Slippage prevented or minimized on every trade
- Order book data enhances signal quality (confirmation/contradiction)
- Foundation for market-making strategy (need book data for quoting)
