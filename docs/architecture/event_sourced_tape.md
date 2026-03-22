# Event-Sourced Intelligence Tape

**Status:** DESIGN
**Author:** JJ
**Date:** 2026-03-22
**Replaces:** ad-hoc SQLite tables scattered across `jj_trades.db`, `btc5_maker.db`, `shadow_signals.db`, `fill_tracker.db`, `wallet_reconciliation.db`

---

## Problem Statement

The system cannot replay past incidents. The March 11 winning session and March 15 concentration failure exist only as fragments: rows in six different SQLite databases, unstructured log lines, and CSV exports that disagree with wallet truth. When something goes wrong (or right), there is no single sequence of events that answers: what did the system see, what did it decide, and what would have happened if parameters were different?

The wallet-truth drift problem (wrong address in `.env` causing every reconciliation to query the wrong wallet for weeks) happened because derived state was never validated against its source events. There were no source events. There was only mutable state.

This design fixes that.

---

## Core Principle: Facts Are Immutable, Interpretations Are Derived

The tape is an append-only log of immutable events. Each event records something that happened: a price was observed, a decision was made, an order was placed, a fill came back. Events are never updated or deleted.

Everything else -- P&L, win rate, regime classification, portfolio concentration -- is a **materialized view** derived from the tape by a deterministic projection function. If a view drifts from reality, you rebuild it from the tape. You never patch the view directly.

---

## Tape Storage Format

### Physical Layout

```
data/tape/
  YYYY-MM-DD/
    tape_YYYYMMDD_HHMMSS_<seqno>.jsonl.zst   # zstd-compressed JSONL segments
  tape.db                                       # SQLite index + derived views
```

Each segment file is append-only JSONL, compressed with zstd when rotated. A new segment starts every 10 minutes or 50,000 events, whichever comes first. The SQLite index stores event metadata (sequence number, timestamp, event type, segment file) for fast querying without decompressing every segment.

### Event Envelope

Every event on the tape shares this envelope:

```python
@dataclass(frozen=True)
class TapeEvent:
    seq: int                    # Monotonically increasing, no gaps within a session
    ts: int                     # Unix microseconds (time.time_ns() // 1000)
    event_type: str             # Dot-namespaced: "market.discovered", "decision.trade_proposed"
    source: str                 # Component that emitted: "btc5_maker", "jj_live", "wallet_recon"
    session_id: str             # Runtime session UUID, set at process start
    payload: dict[str, Any]     # Event-type-specific fields (schemas below)
    causation_seq: int | None   # seq of the event that caused this one (causal chain)
    correlation_id: str | None  # Groups related events (e.g., all events for one BTC5 window)
```

The `seq` is process-local and monotonic. Cross-process ordering uses `ts` with tie-breaking by `(source, seq)`. The `causation_seq` field enables causal replay: given a `trade_approved` event, you can walk back to the `probability_estimated` that triggered it, the `book_snapshot` that provided pricing, and the `market_discovered` that started everything.

---

## Canonical Event Schemas

### 1. MarketLifecycle

Events tracking a market from discovery through resolution.

#### `market.discovered`
```
condition_id: str           # Polymarket condition ID
market_id: str              # Token-pair market ID
question: str               # Human-readable question text
slug: str                   # URL slug (e.g., "btc-5min-up-1711234800")
category: str               # "crypto_5min", "politics", "weather", etc.
end_date_ts: int            # Expected resolution timestamp (unix seconds)
tokens: list[{token_id: str, outcome: str}]
source_api: str             # "gamma_markets_api" | "clob_markets_api"
```

#### `market.updated`
```
condition_id: str
field: str                  # Which field changed: "end_date_ts", "active", "closed"
old_value: Any
new_value: Any
```

#### `market.resolved`
```
condition_id: str
market_id: str
winning_outcome: str        # "YES" | "NO"
resolution_price: float     # 1.0 or 0.0
resolved_at_ts: int         # Unix seconds
resolution_source: str      # "polymarket_api" | "uma_oracle" | "manual_check"
```

### 2. OrderbookTape

Observations of the CLOB order book state. These are the raw inputs the decision engine sees.

#### `book.snapshot`
```
market_id: str
token_id: str
best_bid: float | null
best_ask: float | null
bid_depth_usd: float        # Total USD within 5 ticks of best bid
ask_depth_usd: float
spread: float
midpoint: float
imbalance: float            # (bid_depth - ask_depth) / (bid_depth + ask_depth)
book_levels: int            # Number of price levels observed
```

#### `book.trade_observed`
```
market_id: str
token_id: str
side: str                   # "buy" | "sell"
price: float
size: float
maker_address: str | null   # If available from CLOB WebSocket
taker_address: str | null
```

#### `book.spread_changed`
```
market_id: str
token_id: str
old_spread: float
new_spread: float
old_midpoint: float
new_midpoint: float
trigger: str                # "trade" | "cancel" | "new_order"
```

### 3. SettlementSource

External data feeds that inform decisions. Critical for replay because the system's probability estimates depend on what external prices it saw.

#### `settlement.binance_price`
```
symbol: str                 # "BTCUSDT"
price: float
source: str                 # "binance_ws_trade" | "binance_rest_ticker"
exchange_ts: int             # Binance server timestamp (unix ms)
local_receive_ts: int        # When we received it (unix us)
latency_us: int              # local_receive_ts - (exchange_ts * 1000)
```

#### `settlement.candle_open`
```
symbol: str
window_start_ts: int
open_price: float
source: str                 # "binance_kline" | "computed_first_trade"
```

#### `settlement.oracle_update`
```
condition_id: str
oracle: str                 # "uma" | "reality_eth"
proposed_price: float
proposer: str               # On-chain address
dispute_window_end_ts: int
```

### 4. DecisionEvents

The core of the tape. Every decision the system makes is an event, including decisions not to trade.

#### `decision.probability_estimated`
```
market_id: str
question: str
estimator: str              # "ensemble_3model" | "single_claude" | "btc5_delta"
raw_probability: float      # Pre-calibration
calibrated_probability: float  # Post-Platt scaling
platt_a: float
platt_b: float
market_price: float | null  # null if anti-anchoring applied
edge: float                 # calibrated_prob - market_price (or inverse for NO)
confidence: float
model_details: list[{model: str, estimate: float, latency_ms: int}]  # Per-model breakdown
```

#### `decision.trade_proposed`
```
market_id: str
token_id: str
direction: str              # "buy_yes" | "buy_no"
proposed_price: float
proposed_size_usd: float
proposed_shares: float
edge: float
kelly_fraction: float
kelly_raw: float            # Full Kelly before fractional scaling
sizing_method: str          # "half_kelly" | "probe_2pct" | "graduated_ramp"
sizing_reason_tags: list[str]
risk_mode: str              # "normal" | "probe" | "drawdown_recovery"
capital_stage: int
session_policy_name: str | null
```

#### `decision.trade_approved`
```
market_id: str
token_id: str
direction: str
approved_price: float
approved_size_usd: float
approved_shares: float
approval_reason: str        # "edge_above_threshold" | "cascade_boost"
gates_passed: list[str]     # ["daily_loss_ok", "position_limit_ok", "concentration_ok", ...]
```

#### `decision.trade_rejected`
```
market_id: str
direction: str | null
rejection_reason: str       # Machine-parseable: "skip_delta_too_large", "skip_daily_loss_limit", etc.
rejection_detail: str       # Human-readable explanation
gate_that_failed: str       # "daily_loss_gate" | "delta_gate" | "book_quality_gate" | "time_of_day_gate"
parameters_at_rejection: dict  # Snapshot of thresholds that caused rejection
    # For delta gate: {delta: 0.0082, max_abs_delta: 0.0050, min_delta: 0.0005}
    # For daily loss: {today_pnl: -12.50, limit: -10.00}
    # For time kill: {hour_et: 2, kill_hours: [22,23,0,1,2,3,9,10,11]}
```

#### `decision.window_skipped`
```
window_start_ts: int
slug: str
skip_reason: str            # Canonical skip reason from BTC5 vocabulary
skip_category: str          # "market_quality" | "risk_limit" | "time_filter" | "already_processed"
parameters: dict            # Relevant thresholds at time of skip
```

### 5. ShadowAlternatives

Counterfactual events: what would have happened under different parameters. These are the key to post-hoc analysis of incidents like the March 15 concentration failure.

#### `shadow.trade_proposed`
```
correlation_id: str         # Links to the real decision for the same window
market_id: str
direction: str
shadow_config_name: str     # "wider_delta_0.008" | "down_only" | "no_time_kill"
shadow_parameters: dict     # The alternate parameter set
proposed_price: float
proposed_size_usd: float
proposed_shares: float
edge: float
would_have_traded: bool     # True if this config would have placed an order
real_decision: str          # What the live system actually did: "traded" | "skipped" | "rejected"
```

#### `shadow.outcome_attributed`
```
shadow_trade_id: str        # Links to shadow.trade_proposed
resolution_price: float
hypothetical_pnl: float
real_pnl: float | null      # null if live system did not trade
pnl_delta: float            # hypothetical minus real
shadow_config_name: str
```

### 6. Execution

The mechanical lifecycle of an order from placement through fill or cancellation.

#### `execution.order_placed`
```
order_id: str
market_id: str
token_id: str
side: str                   # "BUY" | "SELL"
price: float
size_shares: float
size_usd: float
order_type: str             # "GTC" | "GTD" | "FOK"
post_only: bool
signature_type: int         # 0=EOA, 1=POLY_PROXY
clob_response: dict         # Raw API response (order hash, etc.)
placement_latency_ms: float
```

#### `execution.order_status_changed`
```
order_id: str
old_status: str
new_status: str             # "open" | "partially_filled" | "filled" | "cancelled" | "expired"
matched_size: float
remaining_size: float
```

#### `execution.order_filled`
```
order_id: str
market_id: str
token_id: str
fill_price: float
fill_size_shares: float
fill_size_usd: float
cumulative_filled: float
is_complete: bool           # True if order fully filled
maker_fee: float            # Should be 0 or negative (rebate)
taker_fee: float
fill_latency_ms: float      # Time from order placement to this fill
```

#### `execution.order_cancelled`
```
order_id: str
cancel_reason: str          # "timeout_t_minus_2s" | "user_cancel" | "stale_cleanup" | "post_only_cross"
unfilled_shares: float
time_alive_ms: float        # How long the order was live before cancel
```

#### `execution.position_redeemed`
```
condition_id: str
market_id: str
token_id: str
shares_redeemed: float
payout_usd: float
cost_basis_usd: float
realized_pnl: float
redemption_tx: str | null   # On-chain tx hash if available
```

### 7. SystemEvents

Operational events that affect trading behavior.

#### `system.session_started`
```
session_id: str
process: str                # "btc5_maker" | "jj_live"
config_snapshot: dict       # Full config at startup (with secrets redacted)
git_sha: str | null
python_version: str
hostname: str
```

#### `system.config_changed`
```
field: str
old_value: Any
new_value: Any
source: str                 # "env_reload" | "runtime_profile" | "session_guardrail"
```

#### `system.wallet_reconciled`
```
wallet_address: str
total_value_usd: float
free_balance_usd: float
open_positions_count: int
closed_positions_count: int
realized_pnl: float
unrealized_pnl: float
reconciliation_source: str  # "polymarket_data_api"
discrepancies: list[{field: str, tape_value: Any, wallet_value: Any}]
```

---

## Retention and Replay Policy

### Tiered Retention

| Tier | Window | Granularity | What survives | Storage estimate |
|------|--------|-------------|---------------|-----------------|
| **Hot** | 0-7 days | Full tick-level: every `book.snapshot`, every `settlement.binance_price`, every `decision.*`, every `execution.*` | Everything | ~200 MB/day at current volume (288 BTC5 windows/day, ~50 events/window) |
| **Warm** | 7-30 days | 1-minute aggregates for `book.*` and `settlement.*`. Full fidelity for `decision.*`, `execution.*`, `shadow.*`, `market.*` | Decision events: full. Book/settlement: aggregated (OHLC per minute, max/min spread, volume-weighted midpoint) | ~30 MB/day |
| **Cold** | 30+ days (forever) | Decision events + outcomes only. No raw book data. No individual settlement ticks. | `decision.*`, `execution.*`, `shadow.*`, `market.resolved`, `system.wallet_reconciled` | ~2 MB/day |

### Compaction Process

A nightly compaction job (runs at 04:00 UTC, outside all BTC5 trading hours):

1. **Hot to Warm** (events older than 7 days): Aggregate `book.*` and `settlement.*` into 1-minute OHLC bars. Write aggregated events as `book.minute_bar` and `settlement.minute_bar`. Delete raw tick events from the index (compressed segment files are retained on disk for 30 days as disaster recovery).

2. **Warm to Cold** (events older than 30 days): Drop aggregated book/settlement bars. Retain only decision, execution, shadow, market resolution, and wallet reconciliation events. Compressed segment files for warm tier are deleted.

3. **Cold archival**: Cold-tier segments are stored indefinitely. At current trading volume, a full year of cold-tier data is under 1 GB.

### Deterministic Replay

Replay is deterministic if and only if the replay engine receives the same event sequence as the live system. The contract:

1. **Replay input:** An ordered sequence of tape events filtered by `correlation_id` (for single-window replay) or time range (for session replay).
2. **Replay engine:** A pure function `(config, events) -> decisions`. No network calls, no random seeds, no wall-clock reads. The engine reads `settlement.*` events for prices instead of calling Binance. It reads `book.*` events for order book state instead of querying the CLOB.
3. **Replay output:** A sequence of `decision.*` events that can be diff'd against the original tape.

**What makes replay deterministic:**
- All external data (prices, book state, wallet balance) is captured as events before the decision that depends on them.
- The `causation_seq` chain ensures correct ordering: a `decision.trade_proposed` always follows the `settlement.binance_price` and `book.snapshot` events it used.
- Config at decision time is captured in `system.session_started` and `system.config_changed`.

**What replay cannot reproduce:**
- Network latency (captured as metadata but not simulated).
- Fill probability (a placed order might fill in live but not in replay; replay marks fills as "assumed" based on book state at time of placement).
- Race conditions between concurrent processes.

### Replaying the March 15 Concentration Failure

To replay this incident:

```python
tape = TapeReader("data/tape/")
events = tape.range(
    start="2026-03-15T00:00:00Z",
    end="2026-03-15T23:59:59Z",
    sources=["btc5_maker"],
)

# Replay with actual config
actual_decisions = replay_engine.run(config=events.config_snapshot(), events=events)

# Replay with proposed fix (wider delta, time-of-day kill)
alt_config = events.config_snapshot()
alt_config["BTC5_MAX_ABS_DELTA"] = 0.0080
alt_config["BTC5_KILL_HOURS_ET"] = [22, 23, 0, 1, 2, 3]
shadow_decisions = replay_engine.run(config=alt_config, events=events)

# Diff: which trades would not have happened?
diff = replay_engine.diff(actual_decisions, shadow_decisions)
print(diff.summary())
# -> "Actual: 47 trades, $236.68 max DD. Alt: 31 trades, $94.12 max DD."
```

The tape contains every `settlement.binance_price` the system observed, every `book.snapshot` it read, every `decision.trade_rejected` with the exact threshold that triggered rejection. The replay engine feeds these same observations through the alternate config and produces the counterfactual decision sequence.

---

## Derived-State Policy

### Materialized Views

These views are rebuilt from the tape, never updated in place:

| View | Source events | Rebuild trigger | Staleness threshold |
|------|-------------|-----------------|---------------------|
| **P&L (realized)** | `execution.position_redeemed` | On each new redemption event | 0 (always current) |
| **P&L (unrealized)** | `execution.order_filled` + latest `book.snapshot` | Every 60 seconds | 5 minutes |
| **Win rate (rolling)** | `execution.position_redeemed` where `realized_pnl > 0` | On each new redemption | 0 |
| **Regime state** | `decision.window_skipped` + `decision.trade_rejected` patterns | Every 5 minutes | 10 minutes |
| **Portfolio concentration** | `execution.order_filled` grouped by `market_id` | On each fill | 0 |
| **Daily loss tracker** | `execution.position_redeemed` filtered by date | On each redemption | 0 |
| **Wallet truth** | `system.wallet_reconciled` | Every reconciliation run (hourly) | 2 hours |
| **Shadow P&L** | `shadow.outcome_attributed` | On each shadow resolution | 0 |
| **Skip distribution** | `decision.trade_rejected` + `decision.window_skipped` grouped by reason | Every 10 minutes | 30 minutes |

### Staleness Detection

Every materialized view carries a watermark: the `seq` of the last event it incorporated. A view is stale when `tape.latest_seq() - view.watermark > staleness_threshold_events`. The threshold varies by view criticality:

- **P&L, daily loss, concentration:** threshold = 0. Must be current before any trading decision.
- **Win rate, regime:** threshold = 50 events (~2-3 BTC5 windows). Tolerable lag.
- **Shadow P&L, skip distribution:** threshold = 500 events. Advisory, not safety-critical.

If a safety-critical view (P&L, daily loss, concentration) is stale at decision time, the system emits a `decision.trade_rejected` with `gate_that_failed = "stale_derived_state"` and refuses to trade until the view is rebuilt. This is the circuit breaker that prevents the wallet-truth drift problem.

### Preventing Wallet-Truth Drift

The specific failure mode that caused weeks of wrong reconciliation data:

1. **Root cause:** `.env` had the wrong wallet address. Every query returned zero data. Derived views showed $0 balance. The system kept trading because no gate checked wallet truth.

2. **Tape-based fix:** The `system.wallet_reconciled` event records both the address queried and the result. A projection function compares `wallet_reconciled.total_value_usd` against the sum of `execution.position_redeemed.payout_usd` minus `execution.order_filled.fill_size_usd` (the tape-derived wallet balance). If these diverge by more than 5%, the system emits `system.config_changed` with a `discrepancy_alert` and halts trading until a human investigates.

3. **Invariant:** `tape_derived_balance = sum(payouts) - sum(costs) + initial_deposit`. `wallet_api_balance = wallet_reconciled.total_value_usd`. If `abs(tape_derived - wallet_api) / max(tape_derived, wallet_api) > 0.05`, the reconciliation gate fires.

This invariant would have caught the wrong-address bug on the first reconciliation run: the tape would show trades being placed (costs going out) but the wallet API would return zero, triggering an immediate 100% divergence alert.

---

## Implementation Sequence

### Phase 1: Tape Writer (Week 1)
- `bot/tape/writer.py` -- Append-only JSONL writer with sequence numbering and zstd rotation.
- `bot/tape/envelope.py` -- `TapeEvent` dataclass and serialization.
- Instrument `btc_5min_maker.py._process_window()` to emit `decision.*` events at each gate.
- Instrument `fill_tracker.py` to emit `execution.*` events.

### Phase 2: Settlement + Book Capture (Week 2)
- Instrument `BinanceTradeFeed` and `BinanceDepthFeed` (both in `btc_5min_maker.py`) to emit `settlement.binance_price` and `book.snapshot` events.
- Instrument `MarketHttpClient` to emit `market.discovered` and `book.snapshot` on CLOB reads.

### Phase 3: Replay Engine (Week 3)
- `bot/tape/replay.py` -- Read tape segments, feed events through decision pipeline with injected config.
- `bot/tape/diff.py` -- Compare two decision sequences, report divergence.
- Validate: replay March 11-15 data, confirm decisions match original DB rows.

### Phase 4: Shadow + Derived Views (Week 4)
- `bot/tape/shadow.py` -- Run N alternate configs in parallel on each window's events, emit `shadow.*` events.
- `bot/tape/views.py` -- Materialized view projections with watermarks and staleness checks.
- Wire reconciliation gate into `_process_window()`: refuse to trade if wallet-truth divergence exceeds threshold.

### Phase 5: Compaction + Cold Storage (Week 5)
- `bot/tape/compaction.py` -- Nightly tier transitions.
- Retention policy enforcement.
- Backfill: convert existing `window_trades`, `trades`, `shadow_signals` tables into tape events for historical continuity.

---

## Migration from Current Schema

The existing SQLite tables are not deleted. They continue to function as before. The tape runs alongside them. Once the tape-derived views match the existing DB state for 7 consecutive days with zero divergence, the old tables become read-only archives and the tape becomes the source of truth.

### Backfill Strategy

The 302 rows in `btc5_maker.db/window_trades` and 50 closed positions in `wallet_reconciliation.db` can be converted to tape events with synthetic sequence numbers. These backfilled events carry a `source: "backfill_migration"` tag so they are distinguishable from live-captured events. Backfilled events have `causation_seq: null` because the causal chain was not captured in the old schema.

---

## Appendix: Event Type Registry

```
market.discovered
market.updated
market.resolved
book.snapshot
book.trade_observed
book.spread_changed
book.minute_bar              # Warm-tier aggregate
settlement.binance_price
settlement.candle_open
settlement.oracle_update
settlement.minute_bar        # Warm-tier aggregate
decision.probability_estimated
decision.trade_proposed
decision.trade_approved
decision.trade_rejected
decision.window_skipped
shadow.trade_proposed
shadow.outcome_attributed
execution.order_placed
execution.order_status_changed
execution.order_filled
execution.order_cancelled
execution.position_redeemed
system.session_started
system.config_changed
system.wallet_reconciled
```

Total: 24 event types across 7 families.
