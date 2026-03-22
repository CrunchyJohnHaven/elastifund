# Aggressive Structural Strike Desk

**Author:** JJ (autonomous)
**Date:** 2026-03-22
**Status:** DESIGN — not yet wired into execution layer
**Capital base:** $1,178 wallet (~$1,331 deposited, -$152 net)

---

## 1. Strike Desk Architecture

### The Problem

Six money-making modules exist as standalone Python classes. None produce revenue because none connect to the execution layer (`jj_live.py`'s `place_order` method). The modules scan, detect, score — then the signals evaporate. This document defines exactly how those signals become filled orders.

### Module Inventory and Execution Coupling

| Module | File | Signal Type | Current State | Wiring Needed |
|--------|------|-------------|---------------|---------------|
| **NegRiskScanner** | `bot/neg_risk_scanner.py` | `ArbitrageOpportunity` | Standalone `scan_all()` | Adapter: opportunity -> execution packets (one per leg) |
| **WhaleTracker** | `bot/whale_tracker.py` | `ConsensusSignal` | Standalone, polls gamma-api trades | Adapter: consensus -> single execution packet |
| **CrossPlatformArbScanner** | `bot/cross_platform_arb_scanner.py` | `CrossPlatformOpportunity` | Standalone `scan_all()` | Adapter: opportunity -> two execution packets (one per platform) |
| **ResolutionSniper** | `bot/resolution_sniper.py` | `ResolutionTarget` / `StaleQuote` | Standalone `detect_stale_quotes()` | Adapter: target -> single execution packet |
| **LLMTournament** | `bot/llm_tournament.py` | Agreement+divergence score | Standalone, requires 3 API calls | Adapter: tournament result -> execution packet if consensus divergence > threshold |
| **SemanticLeaderFollower** | `bot/semantic_leader_follower.py` | Lead-lag pair signal | Standalone, TF-IDF similarity | Adapter: follower-market signal -> single execution packet |

### Signal Flow: Scanner -> Desk -> Execution

```
                    +-----------------+
                    |  jj_live.py     |
                    |  run_cycle()    |
                    +--------+--------+
                             |
                    +--------v--------+
                    |  STRIKE DESK    |
                    |  (new module)   |
                    |  strike_desk.py |
                    +--------+--------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v--+  +--------v--+  +-------v----+
     | Neg-Risk  |  | Whale     |  | Resolution |
     | Scanner   |  | Tracker   |  | Sniper     |
     +-----------+  +-----------+  +------------+
     +--------v--+  +--------v--+  +-------v----+
     | Cross-Plat|  | LLM       |  | Semantic   |
     | Arb       |  | Tournament|  | Lead-Lag   |
     +-----------+  +-----------+  +------------+
```

The Strike Desk is a single new module (`bot/strike_desk.py`) that:
1. Runs all six scanners concurrently via `asyncio.gather`
2. Collects raw signals into a priority queue
3. Applies conflict resolution and concentration checks
4. Emits `ExecutionPacket` objects to `jj_live.place_order()`

### Priority Ordering

When multiple signals fire simultaneously, the desk processes them in this strict order:

| Priority | Lane | Rationale |
|----------|------|-----------|
| **P0** | Neg-Risk | Guaranteed profit. No model risk. Execute immediately. |
| **P1** | Cross-Platform Arb | Near-guaranteed after fee analysis. Two-platform execution. |
| **P2** | Resolution Sniper | Known outcome, sub-$0.97, minimal model risk. |
| **P3** | Stale Quote Sniper | Mispriced book orders — time-critical, first-come. |
| **P4** | Whale Copy | Consensus signal from tracked wallets — decays fast. |
| **P5** | Semantic Lead-Lag | Statistical edge, moderate confidence, needs volume. |
| **P6** | LLM Tournament | Highest cost per signal (3 API calls), slowest to generate. |
| **P7** | BTC5 Maker | Existing strategy, runs independently on Instance 2. |

### Conflict Resolution

When two lanes produce opposing signals on the same market:

1. **Higher-priority lane wins.** If neg-risk says buy YES and whale says sell YES on the same market, neg-risk executes and whale is suppressed for that market.
2. **Same-priority conflict: neither executes.** Log the conflict, move on. Two lanes disagreeing at the same priority means the signal is ambiguous.
3. **BTC5 is isolated.** BTC5 runs on its own service (`btc-5min-maker.service`) and its own execution path. The strike desk does not interfere with BTC5 signals and BTC5 does not interfere with the desk.
4. **Exposure check trumps all.** If total desk exposure would exceed the concentration cap, the lowest-priority pending signal gets dropped first.

### Exposure Management

```
TOTAL_CAPITAL = wallet_balance (currently $1,178)
MAX_DESK_EXPOSURE_PCT = 0.60  (60% of capital available to desk)
MAX_SINGLE_MARKET_PCT = 0.10  (no single market gets >10% of capital)
MAX_SINGLE_LANE_PCT   = 0.30  (no lane gets >30% of capital)
BTC5_RESERVE_PCT      = 0.25  (25% reserved for BTC5 instance)
CASH_BUFFER_PCT       = 0.15  (15% always in cash)
```

At $1,178 capital:
- Desk budget: $706
- Max per market: $117
- Max per lane: $353
- BTC5 reserve: $294
- Cash buffer: $176

---

## 2. Execution Packet Design

### Standard Packet

```python
@dataclass
class ExecutionPacket:
    strategy_id: str          # "neg_risk", "whale_copy", "resolution_sniper", etc.
    market_id: str            # Polymarket condition_id or Kalshi ticker
    platform: str             # "polymarket" or "kalshi"
    direction: str            # "YES" or "NO"
    token_id: str             # CLOB token ID for the chosen side
    size_usd: float           # Dollar amount to risk
    edge_estimate: float      # Expected edge after fees (0.0 to 1.0)
    confidence: float         # Signal confidence (0.0 to 1.0)
    evidence_hash: str        # SHA256 of the evidence payload (for audit)
    max_slippage: float       # Max price movement tolerated (e.g., 0.02 = 2 cents)
    ttl_seconds: int          # Time-to-live: cancel if not filled within this window
    order_type: str           # "maker" or "taker" (always try maker first)
    priority: int             # P0-P7 from the priority table
    linked_packets: list[str] # For multi-leg trades (neg-risk baskets, cross-plat arb)
    timestamp: float          # Unix timestamp of signal generation
    metadata: dict            # Lane-specific data (whale addresses, arb spread, etc.)
```

### Packet Lifecycle

```
SIGNAL DETECTED
    |
    v
[1] VALIDATE — Check: market still active? Price still within max_slippage
    |           of signal price? Exposure limits not breached?
    |           If validation fails -> DROP (log reason)
    v
[2] SIZE — Apply Kelly fraction to edge_estimate.
    |       Cap at MAX_SINGLE_MARKET_PCT of capital.
    |       Floor at platform minimum ($1 Polymarket, $1 Kalshi).
    |       If sized to zero -> DROP
    v
[3] MAKER ATTEMPT — Post limit order at signal price.
    |                Set TTL timer.
    |                Log order_id to fill_tracker.
    v
[4] MONITOR — Check fill status every 15 seconds.
    |          If filled -> [6] RECONCILE
    |          If TTL expired -> [5] TAKER DECISION
    v
[5] TAKER DECISION — Is edge still > min_edge after taker fees (1.5%)?
    |                  If yes and priority <= P2 -> submit market order
    |                  If no or priority > P2 -> ABANDON (log as "maker_timeout")
    v
[6] RECONCILE — Confirm fill via CLOB API.
                Update position tracker, daily PnL, exposure map.
                Notify via Telegram.
                For multi-leg (neg-risk, cross-plat): check all legs filled.
                If partial fill on multi-leg: attempt to unwind unfilled legs.
```

### Retry Logic

- **Maker order rejected (price moved):** Re-price at new best bid/ask. Retry up to 3 times within TTL.
- **API error (rate limit, 5xx):** Exponential backoff: 2s, 4s, 8s. Max 3 retries.
- **CLOB 404 (market delisted):** Quarantine market for 24 hours. No retry.
- **Partial fill:** Accept partial. Do not chase the remainder unless it is a multi-leg arb (in which case, attempt to unwind).
- **Multi-leg incomplete:** If one leg of a neg-risk or cross-platform arb fills but another does not within 60 seconds, sell the filled leg at market to unwind. Log the slippage as a cost of doing business.

---

## 3. Queue-Dominance Requirements

### Maker-First Execution

Every execution packet starts as a maker (post-only) order. This is non-negotiable for Polymarket where maker fee is 0% and taker fee is 1.5-3.15%. The taker path only activates when:
- The maker TTL has expired, AND
- The edge after taker fees still exceeds `JJ_MIN_EDGE`, AND
- The signal priority is P0, P1, or P2 (guaranteed/near-guaranteed profit)

For P3+ signals, if the maker order does not fill within TTL, the signal is abandoned.

### Cancel/Replace Discipline

```
STALE_ORDER_THRESHOLD = 60 seconds
PRICE_DRIFT_THRESHOLD = 0.01 (1 cent)
```

Every cycle (180s default, configurable), the desk:
1. Queries all open orders via `clob.get_orders()`
2. For each open order older than `STALE_ORDER_THRESHOLD`:
   - Fetch current best bid/ask
   - If price has drifted more than `PRICE_DRIFT_THRESHOLD` from our order: cancel and re-place at new price
   - If price has moved against us beyond `max_slippage`: cancel and abandon
3. Orders that have been replaced 5+ times are abandoned (the market is too volatile for maker execution)

### Book Awareness

Before placing any order, the desk checks:
1. **Our order size vs. book depth at our price level.** If our order would be >50% of the visible size at that level, reduce size to 30% of visible depth. Rationale: being the majority of a price level signals intent and invites front-running.
2. **Spread check.** If bid-ask spread is >5 cents, the market is too thin. Only P0-P1 signals (guaranteed profit) proceed in thin markets.
3. **Self-crossing prevention.** Never place a buy order above our existing sell order or vice versa on the same market.

### Concentration Caps

| Constraint | Limit | Enforcement |
|-----------|-------|-------------|
| Single market | 10% of capital ($117) | Reject packet if would breach |
| Single lane | 30% of capital ($353) | Queue excess packets, execute when space frees |
| Total desk exposure | 60% of capital ($706) | Hard stop on all new packets until exposure drops |
| Correlated markets | 20% of capital ($235) | Markets on same underlying (e.g., "BTC > $90k" and "BTC > $95k") share a correlation bucket |

---

## 4. Lane-Specific Rollout

### Lane 1: BTC5 (EXISTING — Instance 2)

**Status:** Running on VPS as `btc-5min-maker.service`. Zero fills locally, some fills on VPS.
**Changes needed:**
- **Time-of-day filter:** Suppress trading 00:00-02:00 ET and 08:00-09:00 ET. These hours showed negative PnL in DISPATCH_102 analysis. Profitable window: 03:00-06:00 ET and 12:00-19:00 ET.
- **DOWN-only mode:** DOWN side showed +$52.80 PnL vs UP -$38.18. Force DOWN-only until 100+ fills prove UP is viable.
- **Wider delta:** Current `BTC5_MAX_ABS_DELTA` is too tight (54% of entries skip as `delta_too_large`). Widen to 0.0050 minimum.
- **Aggressive sizing during golden hours:** During 03:00-06:00 ET, increase position size from $5 to $10 (requires promotion gate pass on subset data).

**Expected daily revenue:** $2-8/day at $5/trade (based on 51.4% WR, PF 1.01 overall, but filtered hours should improve to ~54% WR, PF ~1.15).
**Activation:** Immediate. Config change only on VPS.

### Lane 2: Neg-Risk (NEW)

**Status:** `NegRiskScanner.scan_all()` implemented. Returns `ArbitrageOpportunity` objects with `is_profitable_after_fees` check.
**How it works:** Scans multi-outcome markets where the sum of YES prices across all outcomes is less than $1.00. Buy one YES share of every outcome. Guaranteed $1.00 payout regardless of result.
**Integration:**
1. Strike desk calls `scanner.scan_all()` every cycle
2. For each opportunity where `is_profitable_after_fees` is True:
   - Create one `ExecutionPacket` per outcome leg
   - Link all packets via `linked_packets` field
   - Execute all legs within 30 seconds or unwind
3. Sizing: divide available neg-risk budget equally across legs. Minimum $5 per leg (platform minimum). Maximum $50 per leg initially.

**Expected daily revenue:** $0-5/day. These opportunities are rare (most get arbitraged away within seconds by sophisticated bots) and small (typical spread after fees: 0.5-2%). At $1,178 capital, a 1% guaranteed profit on a $100 basket = $1. Realistic expectation: 0-3 opportunities per day, $0.50-2.00 each.
**Activation:** 2-3 days. Need to wire `scan_all()` into strike desk cycle, build the multi-leg execution adapter, test basket unwinding.

### Lane 3: Resolution Sniper (NEW)

**Status:** `ResolutionSniper` implemented with price-band classification. Detects markets where YES > $0.94 or NO < $0.06 (outcomes near certain).
**How it works:** Finds markets where the real-world outcome is effectively known but the market has not formally resolved. Buy the near-certain side at $0.95-0.98, collect $1.00 on resolution.
**Integration:**
1. Strike desk scans all markets each cycle
2. Filter for `_BAND_NEAR_CERTAIN_HIGH` (YES > $0.94) or `_BAND_NEAR_CERTAIN_LOW` (NO < $0.06)
3. Additional filter: resolution expected within 48 hours (capital lockup cost matters)
4. Exclude markets with political/subjective keywords (dispute risk)
5. Place maker order at current price or 1 cent better

**Expected daily revenue:** $1-4/day. Polymarket has ~20-50 markets in the near-certain band at any time. After filtering for dispute risk and capital lockup, expect 5-15 actionable per day. Average profit per share: $0.02-0.05. At $10-20 per position: $0.20-1.00 per trade, 5-15 trades/day.
**Activation:** 1-2 days. The sniper module already classifies markets. Need adapter to convert `ResolutionTarget` to `ExecutionPacket` and wire into the cycle.

### Lane 4: Whale Copy (NEW)

**Status:** `WhaleTracker` implemented. Monitors gamma-api trades endpoint for anomalous patterns. Generates `ConsensusSignal` when multiple tracked wallets agree.
**How it works:** Fresh wallets making large bets in niche markets often have information. When 2+ such wallets bet the same direction on the same market within 30 minutes, copy the trade.
**Integration:**
1. Strike desk maintains a background polling task (every 60 seconds) fetching recent trades
2. `WhaleTracker` profiles each wallet and scores for freshness, concentration, size
3. When `ConsensusSignal` fires (2+ wallets agree), create `ExecutionPacket`
4. TTL is short (120 seconds) because whale-copy edge decays fast
5. Size: 1/4 Kelly on the consensus confidence score

**Expected daily revenue:** $0-3/day. Whale signals are intermittent. Expect 0-2 consensus signals per day. Win rate depends entirely on wallet selection quality. Conservative estimate: 55% WR on $10-20 positions. This lane needs 30+ days of data before trusting it.
**Activation:** 3-5 days. Needs background polling task, wallet profiling warmup period, and consensus threshold tuning.

### Lane 5: Cross-Platform Arb (BLOCKED)

**Status:** `CrossPlatformArbScanner` implemented with Jaccard question matching.
**How it works:** Same event on Polymarket and Kalshi. If YES on Poly + NO on Kalshi < $1.00 after fees, guaranteed profit.
**Blocker:** Kalshi integration is incomplete. $100 funded but no order placement wired. Kalshi API uses RSA authentication which is implemented but untested in production.
**Integration (when unblocked):**
1. Match markets across platforms using question similarity
2. For each `CrossPlatformOpportunity`, create two linked packets (one per platform)
3. Execute both legs within 15 seconds. If one fails, unwind the other.
4. Fee awareness: Polymarket taker ~1.5%, Kalshi taker ~7% on some markets. Only arb if net profit > combined fees.

**Expected daily revenue:** $0-2/day (when activated). Cross-platform arb on prediction markets is thin because the platforms list different events, resolution criteria differ, and fee structures differ. Real opportunities exist but are sparse.
**Activation:** 7-14 days. Kalshi order placement must be built and tested. Resolution matching needs validation. This is the hardest lane to activate.

### Lane 6: Semantic Lead-Lag (NEW)

**Status:** `SemanticLeaderFollower` implemented with TF-IDF pair discovery.
**How it works:** When market A moves significantly and market B is semantically related but has not moved yet, trade B in the predicted direction. Based on the IBM/Columbia paper showing ~20% returns.
**Integration:**
1. Strike desk maintains a price snapshot of all markets
2. Each cycle, compute price deltas from prior snapshot
3. For markets with >5% price movement, query the leader-follower graph for related followers
4. If follower market has not moved, create `ExecutionPacket` for follower
5. Size: 1/8 Kelly (lower confidence than structural lanes)

**Expected daily revenue:** $0-5/day. Depends on market volatility creating leader moves. In active news cycles (elections, geopolitics), expect 2-5 leader events per day. In quiet periods, 0-1. Win rate from the paper: ~57%. At $10-20 positions, ~$1-2 per winning trade.
**Activation:** 3-5 days. Needs price snapshot infrastructure, pair graph warmup, and backtesting against historical Polymarket price data.

### Lane 7: LLM Tournament (EXPENSIVE — LOW PRIORITY)

**Status:** `LLMTournament` implemented. Runs Claude + GPT + Gemini independently on same question.
**How it works:** When all three models agree with each other (std < 0.05) but disagree with the market price by >10%, that consensus divergence is a trading signal.
**Integration:** Called on-demand for markets that pass other filters. Not called every cycle (too expensive).
**Cost:** ~$0.10-0.30 per tournament (3 LLM calls). At 10 tournaments/day: $1-3/day in API costs.

**Expected daily revenue:** $0-3/day net of API costs. The edge here is real but the signal is slow and expensive. Reserve for high-value markets (>$50k volume) where the potential position size justifies the API cost.
**Activation:** 5-7 days. Needs cost tracking, selective triggering, and integration with the ensemble estimator already in jj_live.py.

---

## 5. How Dollars Are Made Faster

### Revenue Model by Lane

| Lane | Daily Revenue (Low) | Daily Revenue (High) | Activation Time | Capital Needed |
|------|--------------------|--------------------|-----------------|----------------|
| BTC5 (filtered) | $2 | $8 | Immediate | $294 reserved |
| Resolution Sniper | $1 | $4 | 1-2 days | $100-200 |
| Neg-Risk | $0 | $5 | 2-3 days | $100-300 |
| Whale Copy | $0 | $3 | 3-5 days | $50-150 |
| Semantic Lead-Lag | $0 | $5 | 3-5 days | $100-200 |
| LLM Tournament | -$1 (net of API) | $3 | 5-7 days | $50-100 |
| Cross-Platform Arb | $0 | $2 | 7-14 days | $100 (on Kalshi) |
| **TOTAL** | **$2** | **$30** | | |

**Realistic daily expectation with all lanes active:** $5-12/day.

### Break-Even Timeline

Current net loss: -$152.

At $5/day (conservative, BTC5 filtered + Resolution Sniper only): **30 days to break even.**
At $8/day (BTC5 + Sniper + Neg-Risk): **19 days to break even.**
At $12/day (all structural lanes active): **13 days to break even.**

### Activation Sequence (What to Build First)

**Week 1 (Days 1-3): Immediate Revenue**
1. Deploy BTC5 time-of-day filter and DOWN-only mode to VPS. Config change only. Expected: +$2-8/day.
2. Build `bot/strike_desk.py` skeleton with `ExecutionPacket` dataclass and the priority queue.
3. Wire Resolution Sniper into strike desk. This is the fastest new revenue lane because the module already classifies markets and the integration is a simple adapter.

**Week 2 (Days 4-7): Structural Lanes**
4. Wire Neg-Risk Scanner with multi-leg execution and basket unwinding.
5. Wire Whale Tracker with background polling and consensus detection.
6. Wire Semantic Lead-Lag with price snapshot infrastructure.

**Week 3 (Days 8-14): Optimization**
7. Wire LLM Tournament as selective trigger for high-value markets.
8. Begin Kalshi order placement integration for cross-platform arb.
9. Tune concentration caps and exposure limits based on first week of live data.

### What Makes This Different From "More Elegant Architecture"

This desk makes dollars faster because:

1. **Resolution Sniper is near-zero-risk revenue.** Buying YES at $0.96 on a market that has already happened is not a prediction. It is picking up money that is locked behind a resolution delay. The only risk is UMA dispute, which the module already filters by excluding political and subjective markets.

2. **Neg-Risk is guaranteed profit (when it appears).** The scanner already checks `is_profitable_after_fees`. The desk just needs to execute the basket trade. The limiting factor is opportunity frequency, not model quality.

3. **BTC5 is already running and losing money on known-bad hours.** The time-of-day filter is a config change that immediately stops the bleed during 00:00-02:00 and 08:00-09:00 ET. This is not new revenue, it is plugging a known leak.

4. **Whale copy is information arbitrage, not prediction.** We are not predicting the outcome. We are observing that people with apparent information are betting, and piggybacking. The edge is in wallet selection and speed, not in market analysis.

5. **The priority queue prevents self-sabotage.** Without the desk, if neg-risk and the LLM tournament both fire on the same market, the system might take conflicting positions. The priority queue ensures structural (guaranteed) edges always execute before speculative (model-dependent) ones.

### Honest Assessment

The $5-12/day range assumes all lanes function correctly and opportunities exist. Several risks:

- **Neg-risk opportunities may be zero.** Sophisticated MEV bots on Polygon may arbitrage these away before our 180-second scan cycle even sees them. We may need sub-second scanning to compete, which requires WebSocket infrastructure.
- **Resolution Sniper competes with other bots.** We are not the only ones buying YES at $0.96. The edge shrinks as more participants enter.
- **Whale copy can lose money.** Not all whale wallets are informed. Some are manipulators. The 30-day warmup period is real, not optional.
- **API costs for LLM Tournament may exceed revenue.** If tournaments do not generate sufficient edge, this lane runs at a loss.
- **The -$152 hole happened because BTC5 bought DOWN and BTC went UP.** No amount of structural desk architecture prevents directional losses on the BTC5 lane. The time-of-day filter mitigates but does not eliminate this risk.

The fastest path to profitability is: fix BTC5 leaks (immediate) + Resolution Sniper (2 days) + patience.

---

## Appendix: strike_desk.py Interface Contract

```python
class StrikeDesk:
    """Aggregates signals from all money-making modules into a priority-ordered
    execution queue and routes them to jj_live.place_order()."""

    def __init__(self, config: StrikeDeskConfig, jj_engine: JJLiveEngine):
        self.neg_risk = NegRiskScanner()
        self.whale = WhaleTracker()
        self.arb = CrossPlatformArbScanner()
        self.sniper = ResolutionSniper()
        self.tournament = LLMTournament()
        self.leader_follower = SemanticLeaderFollower()
        self.queue: list[ExecutionPacket] = []
        self.exposure: ExposureTracker = ExposureTracker(config)
        self.engine = jj_engine

    async def run_scan(self) -> list[ExecutionPacket]:
        """Run all scanners concurrently. Return priority-sorted packets."""
        results = await asyncio.gather(
            self._scan_neg_risk(),
            self._scan_sniper(),
            self._scan_whale(),
            self._scan_leader_follower(),
            # arb and tournament are conditional
            return_exceptions=True,
        )
        packets = []
        for result in results:
            if isinstance(result, list):
                packets.extend(result)
        packets.sort(key=lambda p: p.priority)
        return self._apply_exposure_limits(packets)

    async def execute_queue(self, packets: list[ExecutionPacket]) -> dict:
        """Execute packets in priority order. Returns fill summary."""
        fills = 0
        abandoned = 0
        for packet in packets:
            if self.exposure.would_breach(packet):
                abandoned += 1
                continue
            success = await self._execute_packet(packet)
            if success:
                fills += 1
                self.exposure.record(packet)
            else:
                abandoned += 1
        return {"fills": fills, "abandoned": abandoned, "total": len(packets)}
```

This interface integrates into `jj_live.run_cycle()` after the existing market scan and before the LLM analysis step. The desk runs its own scanners in parallel with the existing pipeline, and its packets take priority over LLM-generated signals when they exist.
