# RTDS Maker Edge — Strategy Explanation & Implementation Instructions
**Version:** 1.0.0 | **Date:** 2026-03-07 | **Author:** JJ/Claude | **For:** Claude Code on Dublin VPS

---

## 2026-03-23 Probability-Model Addendum

The March 23, 2026 attached deep-research report materially tightens the modeling contract for this lane.

- Settlement truth is Chainlink BTC/USD, not Binance spot. `DOWN` must be labeled as `S1 < S0`; ties resolve `UP` because `UP` wins on `S1 >= S0`.
- Chainlink open price, price-to-beat, intra-candle delta, and time-remaining state should be the primary model inputs. Binance stays in the stack as a microstructure and basis feature, not the settlement label.
- The recommended production model is two-layer: a fast diffusion-style baseline on `{delta_from_open, time_remaining, EWMA_volatility}` plus a small residual model for microstructure and seasonality, then beta calibration.
- Maker execution requires a separate fill model and a fill-conditioned adverse-selection adjustment using Polymarket `book`, `price_change`, and `last_trade_price` data.
- Default maker window should start narrow at `T-30s` to `T-10s` until the information curve and fill curve are measured on our own logs.

This means the RTDS/WebSocket architecture below still matters, but the older “Binance is the answer key” framing is no longer sufficient and should not guide label construction or promotion decisions.

---

## PART 1: WHAT WE'RE PROPOSING (Plain English)

### The Core Idea

Right now our bot polls Polymarket's REST API every 5 minutes, looks at stale data, and tries to make decisions. Meanwhile, other bots are connected to Polymarket's **real-time WebSocket feeds**, watching Binance BTC prices update every 100ms, seeing the Chainlink oracle price lag behind, and placing maker orders on the winning side of 5-minute crypto candle markets before our bot even knows the candle moved.

We're proposing a **complete rewrite of the crypto candle market trading path** — replacing REST polling with three simultaneous WebSocket connections and a maker-order placement engine that acts in the final 60 seconds of each candle.

This is NOT a new strategy concept. It's the same oracle latency edge we've already researched. What's new is the **specific implementation path** based on infrastructure we didn't know we had access to:

1. **Polymarket's RTDS feed** (`wss://ws-live-data.polymarket.com`) streams BOTH the real Binance price AND the Chainlink oracle price, side by side, for free, no auth required. The trading signal comes from how those streams diverge, but the contract itself resolves on the Chainlink series.

2. **Our Dublin VPS is 5–10ms from Polymarket's CLOB** (which runs in AWS London, not the US). We don't need to move servers.

3. **Maker orders are 0% fees.** The Feb 18 fee changes killed taker-based arb (3.15% fees at 50/50 odds), but maker orders are free. We post limit orders on the winning side and wait for someone else to take them.

### How It Works, Step by Step

**Setup phase (runs once on boot):**
- Connect WebSocket to Polymarket RTDS → subscribe to `crypto_prices` (Binance real-time) and `crypto_prices_chainlink` (oracle prices)
- Connect WebSocket to Polymarket CLOB market channel → subscribe to active crypto candle markets for order book updates and trade flow
- Connect WebSocket to Binance → subscribe to BTC/USDT, ETH/USDT, SOL/USDT kline streams as a cross-check
- Discover active crypto candle markets via Gamma API on startup, refresh every 2 minutes

**Each candle cycle (runs continuously):**

1. **T-300s to T-60s (observation window):** Stream prices from all three sources. Track the candle open price on the Chainlink series, the current Chainlink price-to-beat, Binance spot for basis and flow context, and the Polymarket market odds. Do nothing. Just watch.

2. **T-60s to T-10s (decision window):** Compare the current Chainlink price to the Chainlink open price, and standardize that displacement by time remaining and local volatility. Use Binance spot and RTDS divergence as auxiliary evidence about microstructure and basis, not as the settlement label. If the Chainlink series still trails the faster price path, the order book may be mispricing the actual resolution state.

3. **T-60s to T-10s (order placement):** If confidence is high after the outcome model and fill model agree on positive fill-conditioned edge, post aggressive maker limit orders on the winning outcome. "Aggressive" means pricing at or near the current best ask (for buying) — we want to be at the front of the FIFO queue. We do NOT cross the spread (that would be a taker order with fees).

4. **T-10s to T-0s (hold or cancel):** If the price reverses, cancel unfilled orders. If orders are filled, hold to resolution. The candle resolves, we collect $1/share on correct predictions minus our entry cost.

5. **Post-resolution:** Log outcome, update running P&L, check daily loss limits, move to next candle.

### What Makes This Different From What We Have

| Aspect | Current Bot | Proposed System |
|--------|------------|-----------------|
| Data source | REST poll every 5 min | 3 WebSocket streams, sub-second updates |
| Crypto strategy | None (skips crypto markets) | RTDS dual-stream divergence + maker orders |
| Order type | Taker orders | Maker-only (0% fees) |
| Latency to CLOB | ~5000ms (REST round-trip + poll interval) | ~15-35ms (WebSocket + EIP-712 sign + submit) |
| Signal source | Claude LLM probability | Chainlink delta-to-open + RTDS/Binance/Polymarket microstructure |
| Decision timing | Whenever poll happens | Final 60 seconds of each candle |

**This does NOT replace the LLM analyzer for slow markets.** The LLM path (politics, weather, geopolitical) stays exactly as-is. This is a parallel system for the crypto candle markets we currently skip entirely.

---

## PART 2: HONEST ASSESSMENT OF SUCCESS PROBABILITY

### What I think works (70% confident)

**The signal is real, but the contract truth is Chainlink.** Chainlink BTC/USD is the series Polymarket uses to resolve these 5-minute candles. Binance spot is still useful because it can move faster and reveal short-horizon microstructure pressure, but the answer key is the Chainlink open/close rule, with ties resolving Up. The RTDS feed literally gives us both prices simultaneously, which is why the divergence is valuable.

**Maker orders at 0% fees are a structural advantage.** The Feb 18 fee change made taker arb unprofitable but left maker orders untouched. This is confirmed by multiple sources. The math works: if we enter at $0.60 on the winning side with maker orders, we pay $0.60 and receive $1.00 at resolution = $0.40 profit per share, zero fees.

**Dublin to London latency is fine.** 5–10ms to the CLOB. We're not competing at microsecond timescales — we're competing at "can we get an order posted within the 60-second window." Yes, easily.

### What concerns me (the real risks)

**Fill rate is the #1 unknown.** Maker orders only work if someone takes the other side. In the final 60 seconds of a 5-minute candle, when the outcome is becoming obvious, who is selling the losing side? Answer: slower bots, retail traders checking in late, and automated market makers that haven't updated. But we don't know how much liquidity is available to take. If we post a $5 maker order and nobody fills it, we earn nothing. The research estimates $50-150/day with $10K capital, but acknowledges fill rate is the binding constraint.

**We're not alone.** The research mentions 5–10 other bots running similar strategies. We're not discovering a secret — we're joining a known game and hoping to be fast enough and smart enough to get fills. Our advantage is that most documented bots are still doing taker orders (paying fees) or are US-based (70-80ms latency vs our 5-10ms).

**5-minute candle markets have thin liquidity.** These are not deep markets. A few hundred dollars per candle period is typical. With our $247 bankroll, position sizing at 1-1.5% ($2.50-3.75 per trade), we're small enough that fill rate may actually be better for us than for bigger players.

**The edge can disappear.** If Polymarket updates their RTDS feed, changes the oracle, or introduces maker fees, this strategy dies overnight. Prediction market edges are inherently fragile and temporary.

### My overall probability estimate

| Outcome | Probability | Reasoning |
|---------|------------|-----------|
| **System works, makes $5-20/day** | **30%** | Signal is real, we get enough fills at small size, competition is manageable |
| **System works technically but breaks even** | **35%** | Signal is real but fill rate is too low or competition squeezes out profit |
| **System works but loses money** | **15%** | We get adversely selected (filled on wrong-side orders, not filled on right-side) |
| **System doesn't work at all** | **20%** | WebSocket feeds behave differently than documented, or we hit rate limits/bugs that prevent execution |

**Net expected value: Mildly positive.** The downside is capped (we can set a $5/day loss limit), the upside is meaningful relative to our bankroll, and even in the failure case we learn a huge amount about Polymarket's real-time infrastructure that makes everything else we build better.

**My honest recommendation: Build it.** The infrastructure work (WebSocket connections, real-time data streaming) is valuable regardless of whether this specific edge pans out. It's foundational for every other fast-market strategy (wallet flow, LMSR, cross-platform arb). And at $2.50 per trade with a $5/day loss limit, the maximum downside over a week of testing is $35 — worth it for what we learn.

---

## PART 3: IMPLEMENTATION INSTRUCTIONS FOR CLAUDE CODE

### Context for the AI Agent

You are building a new module for the Elastifund trading system. The codebase lives at `/home/ubuntu/polymarket-trading-bot/` on an AWS Lightsail VPS in Dublin (eu-west-1). Python 3.12 is installed. The existing bot (`bot/jj_live.py`) handles slow markets via LLM analysis. You are building a parallel system for crypto candle markets.

The existing `bot/wallet_flow_detector.py` shows the codebase patterns — dataclasses for signals, SQLite for state, logging conventions, and integration points with `jj_live.py`.

### Prerequisites (install first)

```bash
pip install websockets aiohttp python-dotenv py-clob-client web3
```

Verify `py-clob-client` version is ≥0.34 (has fee handling):
```bash
python3 -c "import py_clob_client; print(py_clob_client.__version__)"
```

### File Structure to Create

```
bot/
├── rtds_candle_engine.py        ← Main engine (this is the big one)
├── ws_feeds/
│   ├── __init__.py
│   ├── rtds_feed.py             ← Polymarket RTDS WebSocket client
│   ├── clob_feed.py             ← Polymarket CLOB market WebSocket client
│   └── binance_feed.py          ← Binance kline WebSocket client
├── maker_order_manager.py       ← Order placement, cancellation, tracking
└── candle_state.py              ← Per-candle state machine
```

---

### FILE 1: `bot/ws_feeds/rtds_feed.py` — Polymarket RTDS Client

**Purpose:** Connect to Polymarket's Real-Time Data Stream and subscribe to both `crypto_prices` (Binance real-time) and `crypto_prices_chainlink` (oracle prices). This is the primary signal source.

**WebSocket endpoint:** `wss://ws-live-data.polymarket.com`

**Protocol:** JSON messages. Subscribe by sending:
```json
{"type": "subscribe", "channel": "crypto_prices"}
```
and separately:
```json
{"type": "subscribe", "channel": "crypto_prices_chainlink"}
```

**Expected incoming message format** (based on research — you may need to adapt field names after connecting):
```json
{
  "channel": "crypto_prices",
  "data": {
    "symbol": "BTC/USDT",
    "price": 68523.45,
    "timestamp": 1709825432000
  }
}
```

**Implementation requirements:**
- Use `websockets` library with asyncio
- Set `TCP_NODELAY` on the socket: after connecting, call `ws.transport.get_extra_info('socket').setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)` (wrap in try/except, not all transports expose this)
- Send ping every 8 seconds (Polymarket requires activity within 10 seconds or disconnects)
- Implement auto-reconnect with exponential backoff (1s, 2s, 4s, max 30s)
- Known bug: Polymarket WS has a "silent freeze" issue where the connection stays open but stops sending data. Implement a staleness detector: if no message received for 15 seconds, force reconnect.
- Store latest prices in a shared `dict` that the main engine reads. Use a lock or `asyncio.Queue` for thread safety.
- Log every reconnect event. Log price updates at DEBUG level only (they're very frequent).
- Track and expose the divergence: `divergence = abs(binance_price - chainlink_price) / binance_price`

**Class interface:**
```python
class RTDSFeed:
    def __init__(self):
        self.binance_prices: Dict[str, float] = {}       # {"BTC/USDT": 68523.45}
        self.chainlink_prices: Dict[str, float] = {}     # {"BTC/USDT": 68520.10}
        self.last_update_ts: Dict[str, float] = {}       # per-channel timestamps
        self.connected: bool = False

    async def connect(self): ...
    async def _listen(self): ...
    async def _heartbeat(self): ...

    def get_divergence(self, symbol: str) -> Optional[float]:
        """Returns (binance - chainlink) / binance, or None if stale."""

    def get_binance_price(self, symbol: str) -> Optional[float]: ...
    def get_chainlink_price(self, symbol: str) -> Optional[float]: ...
    def is_fresh(self, max_age_seconds: float = 5.0) -> bool: ...
```

**CRITICAL NOTE:** The exact message format from RTDS is not 100% documented. After connecting, log the first 20 raw messages at INFO level so we can see the actual schema. Build the parser to be defensive — if fields are missing or named differently, log a warning and skip rather than crash.

---

### FILE 2: `bot/ws_feeds/clob_feed.py` — Polymarket CLOB Market Feed

**Purpose:** Subscribe to trade execution data on active crypto candle markets. Used for order flow analysis (detecting large informed trades) and monitoring our own order fills.

**WebSocket endpoint:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`

**Protocol:** Subscribe by sending:
```json
{
  "auth": {},
  "type": "subscribe",
  "channel": "market",
  "markets": ["<condition_id_1>", "<condition_id_2>"]
}
```

No authentication needed for market data (auth is empty object). Authentication IS needed if subscribing to user-specific channels (we'll add that later).

**Expected message types:**
- `trade`: executed trade with price, size, side, timestamp
- `price_change`: orderbook update
- `market`: general market events including resolution

**Implementation requirements:**
- Same reconnect/heartbeat logic as RTDS feed
- Accept a list of condition IDs to subscribe to (these change as new candle markets open)
- Must support dynamic resubscription: when new markets are discovered, subscribe without disconnecting
- Track large trades (>$500 in a single execution) separately — these are potential "informed flow" signals
- Expose a method to get recent large trades for a given condition ID

**Class interface:**
```python
class CLOBFeed:
    def __init__(self):
        self.recent_trades: Dict[str, List[dict]] = {}  # condition_id -> last 100 trades
        self.large_trades: Dict[str, List[dict]] = {}   # condition_id -> trades > $500
        self.connected: bool = False

    async def connect(self): ...
    async def subscribe_markets(self, condition_ids: List[str]): ...
    async def _listen(self): ...

    def get_flow_bias(self, condition_id: str, window_seconds: int = 60) -> Optional[float]:
        """Returns buy_volume - sell_volume over recent window. Positive = bullish."""

    def get_large_trade_signal(self, condition_id: str, window_seconds: int = 120) -> Optional[str]:
        """Returns 'Up' or 'Down' if large informed trades lean one direction, else None."""
```

---

### FILE 3: `bot/ws_feeds/binance_feed.py` — Binance Kline Feed

**Purpose:** Direct Binance price feed as cross-check and primary price truth source.

**WebSocket endpoint:** `wss://stream.binance.com:9443/ws`

**Subscribe to streams:**
```json
{
  "method": "SUBSCRIBE",
  "params": ["btcusdt@kline_1m", "ethusdt@kline_1m", "solusdt@kline_1m"],
  "id": 1
}
```

**Implementation requirements:**
- Parse kline messages to extract: open price, current close (real-time), high, low, volume, candle start time, candle close time, is_closed flag
- Track the 5-minute candle open price by computing from 1-minute klines (open of the first 1m kline in the 5m window)
- Expose a method that returns: current price, 5m candle open, seconds remaining in current 5m candle, and direction (above/below open)
- Binance kline timestamps are milliseconds since epoch, UTC

**Class interface:**
```python
class BinanceFeed:
    def __init__(self):
        self.current_prices: Dict[str, float] = {}          # {"BTCUSDT": 68523.45}
        self.candle_opens: Dict[str, Dict[str, float]] = {} # {"BTCUSDT": {"5m": 68400.0}}
        self.connected: bool = False

    async def connect(self): ...

    def get_candle_status(self, symbol: str = "BTCUSDT", interval: str = "5m") -> Optional[dict]:
        """Returns {
            'current_price': 68523.45,
            'candle_open': 68400.0,
            'direction': 'Up',  # or 'Down'
            'pct_move': 0.18,   # percent from open
            'seconds_remaining': 42,
            'confidence': 0.85  # based on magnitude of move and time remaining
        }"""
```

**NOTE on 5-minute candle alignment:** Polymarket's 5-minute BTC candles align to clock times (00:00, 00:05, 00:10, etc. UTC). Binance 5m klines also align to these boundaries. Confirm this by checking the first few kline `t` (open time) values — they should be divisible by 300000 (5 minutes in ms).

---

### FILE 4: `bot/candle_state.py` — Per-Candle State Machine

**Purpose:** Track the lifecycle of each 5-minute candle market from discovery through resolution.

**States:**
```
DISCOVERED → OBSERVING → DECISION_WINDOW → ORDERS_PLACED → AWAITING_RESOLUTION → RESOLVED
```

**Implementation:**
```python
@dataclass
class CandleMarket:
    condition_id: str
    token_id_up: str        # token for "Up" outcome
    token_id_down: str      # token for "Down" outcome
    asset: str              # "BTC", "ETH", "SOL"
    candle_interval: str    # "5m", "15m"
    candle_open_time: datetime  # UTC
    candle_close_time: datetime # UTC
    state: str = "DISCOVERED"

    # Signal data (populated during DECISION_WINDOW)
    binance_direction: Optional[str] = None     # "Up" or "Down"
    binance_confidence: Optional[float] = None  # 0.0 to 1.0
    rtds_divergence: Optional[float] = None     # abs pct divergence
    flow_bias: Optional[float] = None           # from CLOB feed
    large_trade_signal: Optional[str] = None    # from CLOB feed

    # Order tracking
    orders_placed: List[dict] = field(default_factory=list)
    fills: List[dict] = field(default_factory=list)
    total_filled_usd: float = 0.0

    # Outcome
    resolved_outcome: Optional[str] = None  # "Up" or "Down"
    pnl: Optional[float] = None
```

**State transition logic:**
- `DISCOVERED → OBSERVING`: Immediately on discovery. Start watching prices.
- `OBSERVING → DECISION_WINDOW`: When `seconds_remaining <= 60` on the Binance feed.
- `DECISION_WINDOW → ORDERS_PLACED`: When signal confidence exceeds threshold AND we're within position limits. Place maker orders.
- `ORDERS_PLACED → AWAITING_RESOLUTION`: When candle close time passes. Cancel any unfilled orders.
- `AWAITING_RESOLUTION → RESOLVED`: When Polymarket reports resolution via CLOB feed or RTDS `market_resolved` event.

---

### FILE 5: `bot/maker_order_manager.py` — Order Execution

**Purpose:** Place and manage maker (post-only) limit orders on Polymarket's CLOB.

**Critical details:**
- Use `py_clob_client` for order creation and signing
- Orders MUST be `PostOnly` type — this ensures 0% fees. If the order would immediately fill (crossing the spread), it's rejected rather than converted to a taker order.
- EIP-712 signature is required. The existing bot already handles this via `py_clob_client` — reuse the same credential loading pattern from `jj_live.py`.
- Batch orders: up to 15 orders per request, 60 orders/second sustained
- Always set an expiration on orders: `expiration = candle_close_time + 30_seconds` (give a buffer for resolution)

**Order pricing strategy:**
- To get filled as a maker, we need to offer attractive prices
- If we think the candle resolves "Up" and the current best ask for "Up" is $0.62:
  - Post a buy limit at $0.60-0.62 (at or slightly below the ask)
  - We want to be near the top of the book but NOT cross the spread
  - If the market is moving in our direction, our order will get swept by takers
- Position size: 1/16 Kelly based on confidence, capped at `JJ_MAX_POSITION_USD` (currently $5)
- Never exceed 1.5% of bankroll per candle

**Implementation:**
```python
class MakerOrderManager:
    def __init__(self, clob_client):
        self.client = clob_client
        self.active_orders: Dict[str, List[str]] = {}  # condition_id -> [order_ids]

    async def place_maker_order(
        self,
        token_id: str,
        side: str,          # "BUY"
        price: float,       # e.g., 0.62
        size: float,        # number of shares
        expiration: int,    # unix timestamp
    ) -> Optional[str]:
        """Place a PostOnly order. Returns order_id or None on failure."""

    async def cancel_orders(self, condition_id: str) -> int:
        """Cancel all active orders for a candle market. Returns count cancelled."""

    async def cancel_all(self) -> int:
        """Emergency: cancel everything."""

    def get_fill_status(self, condition_id: str) -> dict:
        """Returns {'filled_usd': float, 'pending_usd': float, 'orders': list}"""
```

**From `jj_live.py`, reuse this credential pattern:**
```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

host = "https://clob.polymarket.com"
chain_id = 137  # Polygon mainnet
client = ClobClient(
    host,
    key=os.environ["POLY_PRIVATE_KEY"],
    chain_id=chain_id,
    signature_type=1,  # POLY_PROXY — this is critical, type 2 fails
    funder=os.environ.get("POLY_SAFE_ADDRESS"),
    api_creds=ClobClient.derive_api_key(
        os.environ["POLY_PRIVATE_KEY"],
        chain_id=chain_id
    ) if not os.environ.get("POLY_BUILDER_API_KEY") else {
        "apiKey": os.environ["POLY_BUILDER_API_KEY"],
        "secret": os.environ["POLY_BUILDER_API_SECRET"],
        "passphrase": os.environ["POLY_BUILDER_API_PASSPHRASE"],
    }
)
```

---

### FILE 6: `bot/rtds_candle_engine.py` — Main Engine (Orchestrator)

**Purpose:** This is the main entry point. It starts all WebSocket feeds, discovers markets, runs the candle state machine, and coordinates order placement.

**Startup sequence:**
1. Load environment variables and initialize CLOB client
2. Start all three WebSocket feeds concurrently (`asyncio.gather`)
3. Discover active crypto candle markets via Gamma API:
   ```
   GET https://gamma-api.polymarket.com/markets?closed=false&tag=crypto&limit=100
   ```
   Filter for: BTC/ETH/SOL 5-minute and 15-minute candle markets. Look for keywords in the title like "BTC", "Bitcoin", "5 Min", "15 Min", "candle", "Up or Down".
4. Subscribe CLOB feed to discovered market condition IDs
5. Enter main event loop

**Main event loop (runs every 1 second):**
```python
async def run_loop(self):
    while True:
        # 1. Refresh market discovery every 120 seconds
        if time.time() - self.last_discovery > 120:
            await self.discover_markets()

        # 2. Update all candle states
        for candle in self.active_candles.values():
            self.update_candle_state(candle)

        # 3. For candles in DECISION_WINDOW: compute signal and maybe place orders
        for candle in self.get_candles_in_state("DECISION_WINDOW"):
            signal = self.compute_signal(candle)
            if signal.confidence >= self.min_confidence and self.within_limits():
                await self.place_orders(candle, signal)

        # 4. For candles past close time: cancel unfilled orders
        for candle in self.get_candles_in_state("ORDERS_PLACED"):
            if datetime.now(timezone.utc) > candle.candle_close_time:
                await self.order_manager.cancel_orders(candle.condition_id)
                candle.state = "AWAITING_RESOLUTION"

        # 5. For resolved candles: log P&L
        for candle in self.get_candles_in_state("AWAITING_RESOLUTION"):
            if candle.resolved_outcome:
                self.record_outcome(candle)

        # 6. Clean up old candles (resolved > 5 minutes ago)
        self.cleanup_old_candles()

        await asyncio.sleep(1)
```

**Signal computation (`compute_signal`):**
```python
def compute_signal(self, candle: CandleMarket) -> Signal:
    # Primary signal: Binance price vs candle open
    binance = self.binance_feed.get_candle_status(
        symbol=f"{candle.asset}USDT",
        interval=candle.candle_interval
    )
    if not binance:
        return Signal(confidence=0)

    direction = binance['direction']  # "Up" or "Down"
    base_confidence = binance['confidence']

    # Boost 1: RTDS divergence confirms oracle hasn't caught up
    divergence = self.rtds_feed.get_divergence(f"{candle.asset}/USDT")
    if divergence and divergence > 0.001:  # >0.1% divergence
        base_confidence *= 1.15  # 15% confidence boost

    # Boost 2: Large informed trades on CLOB agree with our direction
    flow_signal = self.clob_feed.get_large_trade_signal(
        candle.condition_id, window_seconds=120
    )
    if flow_signal == direction:
        base_confidence *= 1.10  # 10% boost

    # Boost 3: CLOB flow bias agrees
    flow_bias = self.clob_feed.get_flow_bias(
        candle.condition_id, window_seconds=60
    )
    if flow_bias and ((direction == "Up" and flow_bias > 0) or
                       (direction == "Down" and flow_bias < 0)):
        base_confidence *= 1.05  # 5% boost

    # Cap at 0.95
    confidence = min(base_confidence, 0.95)

    return Signal(
        direction=direction,
        confidence=confidence,
        entry_price=self._estimate_entry_price(candle, direction),
        position_size=self._compute_position_size(confidence),
    )
```

**Confidence thresholds for action:**
- `confidence >= 0.70`: Place maker orders (conservative)
- `confidence >= 0.80`: Slightly larger position (up to 1.5% of bankroll)
- `confidence < 0.70`: Skip this candle, no action
- `seconds_remaining < 10`: Too late, skip (orders may not fill)
- `seconds_remaining > 60`: Too early, wait

**Position sizing:**
```python
def _compute_position_size(self, confidence: float) -> float:
    """1/16 Kelly, capped at JJ_MAX_POSITION_USD."""
    edge = confidence - 0.50  # edge over coin flip
    if edge <= 0:
        return 0
    kelly = edge / (1.0 - confidence + 0.001)  # simplified Kelly
    fraction = kelly / 16  # 1/16 Kelly for high-frequency
    dollars = fraction * self.bankroll
    return min(dollars, float(os.environ.get("JJ_MAX_POSITION_USD", "5")))
```

**Daily loss limit enforcement:**
```python
def within_limits(self) -> bool:
    daily_loss = sum(c.pnl for c in self.resolved_today if c.pnl and c.pnl < 0)
    max_daily = float(os.environ.get("JJ_MAX_DAILY_LOSS_USD", "5"))
    return abs(daily_loss) < max_daily
```

**Logging requirements:**
- Log every order placement: `INFO: PLACED maker BUY 10 shares Up @ $0.62 on BTC-5m-1709825400`
- Log every fill: `INFO: FILLED 10 shares Up @ $0.62 on BTC-5m-1709825400`
- Log every resolution: `INFO: RESOLVED BTC-5m-1709825400 = Up, PnL = +$3.80`
- Log signal computation at DEBUG level
- Log WebSocket reconnects at WARNING level
- Log daily summary at midnight UTC: total trades, wins, losses, net P&L, fill rate

**Entry point:**
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper", action="store_true", help="Paper trading mode (no real orders)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    engine = RTDSCandleEngine(paper_mode=args.paper)
    asyncio.run(engine.start())
```

---

### DEPLOYMENT INSTRUCTIONS (for Dublin VPS)

**Step 1: Create the files locally, test with `--paper` mode first:**
```bash
cd /home/ubuntu/polymarket-trading-bot/bot
python3 rtds_candle_engine.py --paper --log-level DEBUG
```

Paper mode should: connect all WebSockets, discover markets, compute signals, and LOG what orders it WOULD place — but not actually submit anything to the CLOB.

**Step 2: Verify WebSocket connectivity:**
The first thing to check is whether the RTDS feed actually works as documented. Run the RTDS feed standalone:
```bash
python3 -c "
import asyncio, websockets, json
async def test():
    async with websockets.connect('wss://ws-live-data.polymarket.com') as ws:
        await ws.send(json.dumps({'type': 'subscribe', 'channel': 'crypto_prices'}))
        await ws.send(json.dumps({'type': 'subscribe', 'channel': 'crypto_prices_chainlink'}))
        for i in range(20):
            msg = await ws.recv()
            print(json.dumps(json.loads(msg), indent=2))
asyncio.run(test())
"
```

**If this doesn't work** (connection refused, different message format, authentication required), the RTDS approach needs to be rethought. Fall back to using Binance WebSocket as the sole price source and skip the oracle divergence signal.

**Step 3: Create systemd service:**
```ini
# /etc/systemd/system/jj-candle.service
[Unit]
Description=JJ RTDS Candle Engine
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket-trading-bot
ExecStart=/usr/bin/python3 bot/rtds_candle_engine.py --log-level INFO
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/home/ubuntu/polymarket-trading-bot/.env

[Install]
WantedBy=multi-user.target
```

**Step 4: Run alongside existing bot:**
```bash
sudo systemctl enable jj-candle
sudo systemctl start jj-candle
sudo journalctl -u jj-candle -f  # watch logs
```

This runs in parallel with `jj-live.service` (the LLM analyzer). They share the same wallet but trade different markets (candle engine trades crypto, LLM bot trades politics/weather), so there's no conflict.

---

### TESTING CHECKLIST (before going live with real money)

1. **WebSocket connectivity test:** Can we connect to all three feeds? Log raw messages for 5 minutes.
2. **RTDS schema verification:** Do the message fields match what we expect? Adapt parser if needed.
3. **Market discovery test:** Does Gamma API return active crypto candle markets? Can we extract condition IDs and token IDs?
4. **Candle alignment test:** Do our computed candle open/close times match Polymarket's actual market open/close times? Off-by-one errors here are fatal.
5. **Signal accuracy test (paper):** Run paper mode for 24 hours. Log predicted direction vs actual resolution. Target: >65% accuracy.
6. **Order placement test (paper):** Verify PostOnly order construction is correct — right token ID, right side, right price format, right expiration.
7. **Fill simulation:** Even in paper mode, check: would our limit orders have been fillable based on the actual order book state?
8. **Daily loss limit test:** Simulate a losing streak and confirm the bot stops trading.
9. **Reconnect test:** Kill a WebSocket connection and verify auto-reconnect works within 30 seconds.
10. **24-hour soak test (paper):** Full system running paper mode for 24 hours with no crashes, no memory leaks, no stale connections.

**Only after ALL 10 checks pass → switch to live with $2.50 max position size for the first 48 hours.**

---

### KNOWN UNKNOWNS (things Claude Code will need to figure out on the fly)

1. **RTDS message schema:** The exact field names and structure are not documented. You MUST connect and inspect raw messages before writing the parser.
2. **How Polymarket identifies candle markets:** The Gamma API may not have a clean `tag=crypto_candle` filter. You may need to parse market titles with regex like `r"BTC.*5\s*[Mm]in.*[Uu]p.*[Dd]own"`.
3. **Token ID mapping:** Each candle market has two tokens (Up and Down). The Gamma API should return these, but the field names vary. Look for `clobTokenIds`, `tokens`, or similar.
4. **Candle open price source:** Polymarket may publish the candle open price in the market description, or you may need to compute it from the first Binance kline after market open.
5. **PostOnly order rejection behavior:** If our price is too aggressive (would cross the spread), the CLOB rejects the order. We need to handle this gracefully and reprice.
6. **Rate limit behavior under Cloudflare:** Orders are queued, not rejected. This means we won't get explicit errors — we'll just see latency increase. Monitor order submission round-trip times.

---

### SUCCESS CRITERIA

**Week 1 (paper trading):**
- All three WebSocket feeds connected and stable for 24+ hours
- Signal accuracy >65% on 5-minute BTC candles (measured over 100+ candles)
- System handles market discovery, state transitions, and cleanup without crashes

**Week 2 (live, micro-size):**
- At least 20 real trades placed and filled
- Fill rate >30% (at least 30% of our maker orders get taken)
- Net P&L positive (even by $1)
- No unintended taker orders (all fills are maker, 0% fee)

**Week 3+ (scale up if working):**
- Increase position size to $5, then $10 if consistently profitable
- Add 15-minute candle markets
- Add ETH and SOL candle markets
- Integrate with wallet flow detector for confirmation signals

**Kill criteria (stop and reassess):**
- 3 consecutive days of losses
- Fill rate below 10% (orders are just expiring unfilled)
- WebSocket feeds become unreliable (>5 disconnects per hour)
- Polymarket introduces maker fees (edge disappears)
