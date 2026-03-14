# Smart Wallet Flow Detection Engine — Implementation Spec v1.0

**Date:** March 7, 2026 | **Status:** Ready for Claude Code implementation
**Priority:** Highest-value strategy component (hardest to replicate)
**Target deploy:** Weeks 3-4 (March 17-30), after VPS migration + ensemble

---

## 1. What This Does

Monitors Polymarket's on-chain order flow on Polygon, identifies wallets with proven track records ("smart money"), and generates trading signals when multiple smart wallets converge on the same outcome. This is the highest-value proprietary edge because it's the hardest for competitors to replicate — it requires historical data, ML infrastructure, and real-time event processing.

```
Polygon Blockchain (Alchemy WebSocket)
      │
      ▼
┌─────────────────────────────┐
│   Event Listener             │  ← OrderFilled, OrdersMatched, TransferSingle
│   (WebSocket subscription)   │     from CTF Exchange + NegRisk Exchange
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Trade Parser               │  ← Extract: wallet, market, side, size, price
│   + Market Resolution Join   │     Join with Gamma API for market metadata
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Wallet Scoring Pipeline    │  ← Rolling stats: win rate, PnL, ROI,
│   (SQLite → daily refresh)   │     category specialization, trade frequency
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Smart Wallet Registry      │  ← Wallets passing: >60% win, 100+ trades,
│   (~200-500 wallets)         │     4+ months, positive 30d + 7d PnL
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Convergence Detector       │  ← When 3+ smart wallets take same side
│   (real-time, per-market)    │     on same market within 24h window
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   XGBoost Signal Scorer      │  ← Features: wallet agreement %, avg win
│   (inference <10ms)          │     rate of agreeing wallets, size delta,
│                              │     timing, market category
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│   Signal Output              │  ← direction, confidence, contributing
│   → Ensemble Merger          │     wallets, suggested position size
└─────────────────────────────┘
```

---

## 2. On-Chain Data Sources

### Primary: Alchemy Polygon WebSocket (Free Tier)

**Limits:** 300M compute units/month, 100 WebSocket connections, 1,000 subscriptions per connection. At ~40 CU per event, budget supports ~7.5M events/month — more than sufficient.

**Environment variable:**
```bash
ALCHEMY_POLYGON_WSS=wss://polygon-mainnet.g.alchemy.com/v2/{API_KEY}
ALCHEMY_POLYGON_HTTPS=https://polygon-mainnet.g.alchemy.com/v2/{API_KEY}
```

### Contracts to Monitor

| Contract | Address | Events |
|----------|---------|--------|
| CTF Exchange | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` | OrderFilled, OrdersMatched |
| NegRisk CTF Exchange | `0xC5d563A36AE78145C45a50134d48A1215220f80a` | OrderFilled, OrdersMatched |
| Conditional Tokens (ERC1155) | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` | TransferSingle, TransferBatch |
| NegRisk Adapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` | PositionSplit, PositionsMerge, PositionsConverted |

### Event Signatures

```python
# CTF Exchange events
ORDER_FILLED_TOPIC = Web3.keccak(text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)")
ORDERS_MATCHED_TOPIC = Web3.keccak(text="OrdersMatched(bytes32,address,uint256,uint256,uint256,uint256)")

# ERC1155 events
TRANSFER_SINGLE_TOPIC = Web3.keccak(text="TransferSingle(address,address,address,uint256,uint256)")
TRANSFER_BATCH_TOPIC = Web3.keccak(text="TransferBatch(address,address,address,uint256[],uint256[])")
```

**Key insight:** Use `OrdersMatched` for accurate volume (not `OrderFilled` which double-counts). One OrdersMatched event per trade with one taker and at least one maker.

### Secondary: The Graph Polymarket Subgraph

**Endpoint:** `https://gateway.thegraph.com/api/{key}/subgraphs/id/Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp`
**Free tier:** 100K queries/month
**Use for:** Historical backfill of wallet trade history, bulk market resolution data

```graphql
# Example: Get trade history for a specific wallet
{
  trades(
    where: { trader: "0xabc..." }
    orderBy: timestamp
    orderDirection: desc
    first: 1000
  ) {
    id
    market { id question }
    side
    size
    price
    timestamp
    outcome
  }
}
```

### Tertiary: Gamma API (Already integrated)

**Use for:** Market metadata — question text, category, resolution status, outcome prices.
**Already working** in jj_live.py's scanner module.

---

## 3. Database Schema (SQLite)

```sql
-- Wallet performance tracking
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    first_seen_at TEXT,          -- ISO timestamp
    last_trade_at TEXT,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    total_pnl_usdc REAL DEFAULT 0.0,
    pnl_30d REAL DEFAULT 0.0,
    pnl_7d REAL DEFAULT 0.0,
    win_rate REAL DEFAULT 0.0,
    avg_trade_size REAL DEFAULT 0.0,
    primary_category TEXT,       -- Most traded category
    category_concentration REAL, -- % of trades in top 2 categories
    is_smart INTEGER DEFAULT 0,  -- 1 if passes smart wallet criteria
    smart_score REAL DEFAULT 0.0,-- Composite quality score (0-1)
    updated_at TEXT
);

-- Individual trades (for wallet scoring)
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,          -- tx_hash + log_index
    wallet_address TEXT NOT NULL,
    market_id TEXT NOT NULL,
    market_question TEXT,
    category TEXT,
    side TEXT NOT NULL,           -- 'yes' or 'no'
    size_usdc REAL NOT NULL,
    price REAL NOT NULL,          -- Entry price
    timestamp TEXT NOT NULL,
    resolved INTEGER DEFAULT 0,
    outcome TEXT,                 -- 'yes', 'no', or NULL if unresolved
    pnl_usdc REAL,              -- Profit/loss when resolved
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);
CREATE INDEX IF NOT EXISTS idx_trades_wallet ON trades(wallet_address);
CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);

-- Smart wallet signals (convergence events)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    market_question TEXT,
    direction TEXT NOT NULL,      -- 'yes' or 'no'
    num_smart_wallets INTEGER,
    agreement_pct REAL,           -- % of smart wallets on same side
    avg_wallet_win_rate REAL,
    avg_wallet_score REAL,
    xgboost_confidence REAL,
    signal_strength TEXT,         -- 'strong', 'moderate', 'weak'
    created_at TEXT,
    acted_on INTEGER DEFAULT 0,
    outcome TEXT                  -- For backtesting: did this signal win?
);

-- Market resolution cache (for PnL calculation)
CREATE TABLE IF NOT EXISTS market_resolutions (
    market_id TEXT PRIMARY KEY,
    question TEXT,
    outcome TEXT,                 -- 'yes' or 'no'
    resolved_at TEXT,
    final_price_yes REAL,
    final_price_no REAL
);
```

---

## 4. Wallet Scoring Algorithm

### Smart Wallet Criteria (from SystemDesignResearch)

A wallet qualifies as "smart money" if ALL of:
- Win rate > 60% across 100+ resolved trades
- Active for 4+ months (first_seen_at > 120 days ago)
- Positive 30-day AND 7-day PnL
- Category concentration > 70% (specialist, not spray-and-pray)
- < 100 predictions/month (thoughtful, not high-frequency)

### Exclusions

Automatically exclude:
- Wallets with > 50% of trades in 5-min/15-min crypto markets (speed bots, not signal)
- Wallets with > 500 trades/month (likely bots/market makers)
- One-hit wonders: < 100 total trades regardless of win rate
- Wallets with win rate > 60% but negative PnL (lucky on small trades, big losers)

### Composite Smart Score (0-1)

```python
def compute_smart_score(wallet: dict) -> float:
    """Composite quality score for ranking smart wallets."""
    # Weighted components (sum to 1.0)
    wr_score = min(1.0, (wallet["win_rate"] - 0.50) / 0.30)   # 0 at 50%, 1 at 80%
    pnl_score = min(1.0, max(0, wallet["total_pnl_usdc"]) / 10000)  # 0-$10K scale
    age_score = min(1.0, wallet["days_active"] / 365)           # 0 at 0 days, 1 at 1 year
    consistency = 1.0 if wallet["pnl_7d"] > 0 and wallet["pnl_30d"] > 0 else 0.5
    specialization = min(1.0, wallet["category_concentration"])

    return (
        0.30 * wr_score +
        0.25 * pnl_score +
        0.15 * age_score +
        0.15 * consistency +
        0.15 * specialization
    )
```

### Refresh Schedule

- **Full rescore:** Daily at 00:00 UTC (batch job, ~5 minutes)
- **Incremental PnL update:** Every market resolution event
- **Smart wallet registry:** ~200-500 wallets expected (based on Polymarket's 7.6% profitability rate across ~1.3M total wallets)

---

## 5. Convergence Detection

The core signal: when multiple independent smart wallets take the same side on the same market within a time window.

```python
class ConvergenceDetector:
    """Detects when smart wallets converge on the same market outcome."""

    def __init__(self, db, min_wallets=3, window_hours=24):
        self.db = db
        self.min_wallets = min_wallets
        self.window_hours = window_hours

    def check_convergence(self, market_id: str) -> Optional[dict]:
        """Check if enough smart wallets agree on a market direction."""
        cutoff = datetime.utcnow() - timedelta(hours=self.window_hours)

        # Get recent smart wallet trades on this market
        trades = self.db.execute("""
            SELECT t.wallet_address, t.side, t.size_usdc, t.price,
                   w.win_rate, w.smart_score
            FROM trades t
            JOIN wallets w ON t.wallet_address = w.address
            WHERE t.market_id = ? AND t.timestamp > ? AND w.is_smart = 1
            ORDER BY t.timestamp DESC
        """, (market_id, cutoff.isoformat())).fetchall()

        if len(trades) < self.min_wallets:
            return None

        # Count directions
        yes_wallets = [t for t in trades if t["side"] == "yes"]
        no_wallets = [t for t in trades if t["side"] == "no"]

        dominant_side = "yes" if len(yes_wallets) >= len(no_wallets) else "no"
        dominant_trades = yes_wallets if dominant_side == "yes" else no_wallets
        total_smart = len(set(t["wallet_address"] for t in trades))
        agreement = len(set(t["wallet_address"] for t in dominant_trades)) / total_smart

        if agreement < 0.75:  # Need 75%+ agreement
            return None

        return {
            "market_id": market_id,
            "direction": dominant_side,
            "num_smart_wallets": len(set(t["wallet_address"] for t in dominant_trades)),
            "total_smart_wallets_active": total_smart,
            "agreement_pct": agreement,
            "avg_wallet_win_rate": sum(t["win_rate"] for t in dominant_trades) / len(dominant_trades),
            "avg_wallet_score": sum(t["smart_score"] for t in dominant_trades) / len(dominant_trades),
            "total_volume_usdc": sum(t["size_usdc"] for t in dominant_trades),
        }
```

### Signal Strength Tiers

| Tier | Criteria | Action |
|------|----------|--------|
| **Strong** | 5+ smart wallets agree, 90%+ agreement, avg score > 0.7 | Full position (Kelly sizing) |
| **Moderate** | 3-4 smart wallets agree, 75%+ agreement, avg score > 0.5 | Half position |
| **Weak** | 2 smart wallets agree, or low scores | Log only, don't trade |

---

## 6. XGBoost Signal Scorer

### Features (per convergence event)

```python
FEATURE_COLUMNS = [
    "num_smart_wallets",       # Count of agreeing smart wallets
    "agreement_pct",           # % of active smart wallets on same side
    "avg_wallet_win_rate",     # Average historical win rate
    "avg_wallet_score",        # Average composite smart score
    "total_volume_usdc",       # Total $ volume from smart wallets
    "market_volume_usdc",      # Total market volume (from Gamma)
    "smart_vol_pct",           # Smart volume / total volume
    "market_price",            # Current YES price
    "hours_to_resolution",     # Time until market resolves (if known)
    "category_encoded",        # One-hot: politics, geopolitical, economic, etc.
    "avg_entry_timing",        # How early smart wallets entered vs market creation
    "size_delta",              # Smart wallet trade size vs their historical average
    "cross_market_momentum",   # Are smart wallets buying across category?
]
```

### Training Pipeline

**Phase 1 (Historical backfill):**
1. Use The Graph subgraph to pull all trades from the last 6 months
2. Join with market resolution data to compute wallet PnL
3. Score all wallets, identify smart wallets retroactively
4. Generate convergence events from historical data
5. Label each convergence event as win/loss based on market resolution
6. Train XGBoost on labeled dataset

**Phase 2 (Live inference):**
1. When convergence is detected, compute features
2. Run XGBoost inference (<10ms)
3. Output: probability that this convergence signal leads to a profitable trade
4. Combine with ensemble LLM signal (weighted average)

```python
import xgboost as xgb

# Training (run once, then monthly retrain)
model = xgb.XGBClassifier(
    n_estimators=100,
    max_depth=6,
    learning_rate=0.1,
    objective="binary:logistic",
    eval_metric="logloss",
)
model.fit(X_train, y_train, eval_set=[(X_val, y_val)], early_stopping_rounds=10)
model.save_model("data/xgboost_wallet_flow.json")

# Inference (per convergence event)
model = xgb.XGBClassifier()
model.load_model("data/xgboost_wallet_flow.json")
prob = model.predict_proba(features.reshape(1, -1))[0][1]
```

### Training Data Requirements

- Minimum 500 labeled convergence events before deploying live
- Expected from 6-month backfill: 2,000-5,000 events (estimated from Polymarket's ~362 daily markets × 6 months × ~5% convergence rate)
- Monthly retrain with expanding window

---

## 7. Event Listener Implementation

```python
"""Real-time Polygon event listener for Polymarket trade flow."""

import asyncio
import json
from web3 import AsyncWeb3, WebSocketProvider

CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEGRISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

class PolygonEventListener:
    def __init__(self, wss_url: str, db, convergence_detector):
        self.wss_url = wss_url
        self.db = db
        self.detector = convergence_detector
        self.running = True

    async def start(self):
        """Connect to Alchemy WebSocket and subscribe to events."""
        while self.running:
            try:
                w3 = AsyncWeb3(WebSocketProvider(self.wss_url))

                # Subscribe to logs from CTF Exchange + NegRisk Exchange
                filter_params = {
                    "address": [CTF_EXCHANGE, NEGRISK_EXCHANGE],
                    # OrdersMatched topic
                    "topics": [[ORDERS_MATCHED_TOPIC]]
                }

                sub_id = await w3.eth.subscribe("logs", filter_params)

                async for log in w3.socket.process_subscriptions():
                    if not self.running:
                        break
                    await self._process_log(log)

            except Exception as e:
                print(f"WebSocket error: {e}, reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _process_log(self, log):
        """Parse an OrdersMatched event and update the database."""
        # Decode event data
        trade = self._decode_orders_matched(log)
        if not trade:
            return

        # Store trade
        self.db.execute("""
            INSERT OR IGNORE INTO trades
            (id, wallet_address, market_id, side, size_usdc, price, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (trade["id"], trade["taker"], trade["market_id"],
              trade["side"], trade["size"], trade["price"],
              trade["timestamp"]))
        self.db.commit()

        # Check convergence on this market
        signal = self.detector.check_convergence(trade["market_id"])
        if signal:
            await self._emit_signal(signal)

    def _decode_orders_matched(self, log) -> dict:
        """Decode OrdersMatched event into a trade dict."""
        # Implementation: ABI-decode the log data
        # taker_order_hash (indexed), taker_order_maker (indexed),
        # maker_asset_id, taker_asset_id, maker_amount_filled, taker_amount_filled
        pass

    async def _emit_signal(self, signal: dict):
        """Store signal and notify the trading engine."""
        self.db.execute("""
            INSERT INTO signals
            (market_id, market_question, direction, num_smart_wallets,
             agreement_pct, avg_wallet_win_rate, avg_wallet_score,
             xgboost_confidence, signal_strength, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (...))
        self.db.commit()

        # Send Telegram alert
        await alert(f"🎯 Smart wallet convergence: {signal['direction'].upper()} "
                    f"on {signal['market_question'][:50]} "
                    f"({signal['num_smart_wallets']} wallets, "
                    f"{signal['agreement_pct']:.0%} agreement)")
```

### Reconnection Logic (Critical — Issue #292)

The py-clob-client WebSocket has a known silent freeze bug. Same pattern applies to Alchemy WebSocket. Implement:

```python
class ResilientWebSocket:
    """WebSocket with heartbeat monitoring and auto-reconnect."""

    def __init__(self, url, no_data_timeout=60):
        self.url = url
        self.no_data_timeout = no_data_timeout
        self.last_data_at = time.time()

    async def monitor_health(self):
        """Kill and reconnect if no data received within timeout."""
        while True:
            await asyncio.sleep(10)
            if time.time() - self.last_data_at > self.no_data_timeout:
                raise ConnectionError("WebSocket silent freeze detected")
```

---

## 8. Integration with Ensemble + JJ Live

The smart wallet signal feeds into the trading decision alongside the LLM ensemble:

```python
# In jj_live.py trading loop:

async def evaluate_market(market, ensemble, wallet_engine):
    # 1. LLM ensemble signal
    llm_signal = await ensemble.analyze_market(
        market["question"], market["price"], market.get("context", "")
    )

    # 2. Smart wallet signal (if available)
    wallet_signal = wallet_engine.get_signal(market["id"])

    # 3. Combine signals
    if wallet_signal and wallet_signal["signal_strength"] == "strong":
        # Strong wallet convergence overrides LLM if they agree
        if wallet_signal["direction"] == llm_signal["direction"]:
            # Double conviction — increase position size by 50%
            combined_edge = max(llm_signal["edge"], 0.10)
            position_multiplier = 1.5
        else:
            # Disagreement — reduce position or skip
            combined_edge = llm_signal["edge"] * 0.5
            position_multiplier = 0.5
    elif wallet_signal and wallet_signal["signal_strength"] == "moderate":
        # Moderate wallet signal adds confidence to LLM signal
        if wallet_signal["direction"] == llm_signal["direction"]:
            combined_edge = llm_signal["edge"] * 1.2
            position_multiplier = 1.2
        else:
            combined_edge = llm_signal["edge"]
            position_multiplier = 1.0
    else:
        # No wallet signal — rely on LLM ensemble alone
        combined_edge = llm_signal["edge"]
        position_multiplier = 1.0

    return {
        "direction": llm_signal["direction"],
        "edge": combined_edge,
        "position_multiplier": position_multiplier,
        "llm_signal": llm_signal,
        "wallet_signal": wallet_signal,
    }
```

---

## 9. Implementation Plan (for Claude Code sessions)

### Session 1: Historical Backfill (Week 3, ~2 hours)
1. Create `src/wallet_tracker.py` with SQLite schema
2. Write The Graph backfill script — pull 6 months of trades
3. Score all wallets, identify smart wallet registry
4. Generate labeled convergence events

### Session 2: XGBoost Training (Week 3, ~1 hour)
1. Train XGBoost on backfilled convergence events
2. Evaluate: accuracy, precision, recall on held-out test set
3. Save model to `data/xgboost_wallet_flow.json`

### Session 3: Event Listener (Week 4, ~2 hours)
1. Create `src/event_listener.py` with Alchemy WebSocket subscription
2. Implement OrdersMatched event decoder
3. Add reconnection logic with health monitoring
4. Test on live Polygon events

### Session 4: Integration (Week 4, ~1 hour)
1. Wire wallet engine into jj_live.py trading loop
2. Add Telegram alerts for convergence events
3. Deploy to Dublin VPS

### Dependencies to install:
```bash
pip install xgboost web3 aiohttp
# web3 for Polygon event decoding
# xgboost for signal scoring
# aiohttp for async HTTP (already needed by ensemble)
```

### New environment variables:
```bash
ALCHEMY_API_KEY=...            # Get from alchemy.com (free tier)
THEGRAPH_API_KEY=...           # Get from thegraph.com/studio (free: 100K queries/month)
```

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Alchemy free tier exhausted | Lose real-time events | Monitor CU usage. Fallback: poll every 15s via HTTP instead of WebSocket. |
| Smart wallet registry too small (<50 wallets) | Weak convergence signals | Lower criteria temporarily (50 trades, 55% win rate). Re-evaluate monthly. |
| Smart wallets change strategy or go inactive | Signal degrades | Monthly rescore. Require positive 7d PnL for active status. |
| XGBoost overfits on small training set | Poor live performance | Minimum 500 labeled events. Use 5-fold cross-validation. Start with rule-based convergence (no ML) until enough data. |
| WebSocket silent freeze | Miss trades | Health monitoring with 60s timeout auto-reconnect (see Section 7). |
| Event decoding bugs | Wrong trade data | Validate against Polygonscan for first 100 events. Unit tests for decoder. |

---

## 11. Phase 1 Simplification (Rule-Based, No ML)

If historical backfill doesn't yield enough labeled data for XGBoost training, start with a pure rule-based system:

```python
# Phase 1: Rule-based convergence (no XGBoost needed)
def evaluate_convergence_rule_based(signal: dict) -> str:
    """Simple rule-based signal strength, no ML required."""
    if (signal["num_smart_wallets"] >= 5 and
        signal["agreement_pct"] >= 0.90 and
        signal["avg_wallet_win_rate"] >= 0.65):
        return "strong"
    elif (signal["num_smart_wallets"] >= 3 and
          signal["agreement_pct"] >= 0.75 and
          signal["avg_wallet_win_rate"] >= 0.60):
        return "moderate"
    else:
        return "weak"
```

This gives immediate value while collecting labeled data for the XGBoost upgrade.

---

*This spec is ready for Claude Code implementation. Drop into session with: "Read ~/Desktop/elastifund/docs/strategy/smart_wallet_build_spec.md and implement Session 1 (historical backfill) on the Dublin VPS."*
