# Non-Trading Allocator Spec

## Purpose

`orchestration/` now contains the Phase 5.1 capital allocator for Elastifund's dual-lane system.

It produces one auditable daily decision across:

- trading capital in USD
- non-trading daily send quota
- non-trading daily LLM token budget
- cash reserve share
- per-lane Kelly guidance for downstream execution

The allocator persists both the decision record and Elastic-ready strategy documents so the control plane can audit, replay, and later sync them into `elastifund-strategies`.

## Storage

The allocator uses `data/allocator.db`.

Tables:

- `allocation_observations`: daily ROI observations by lane
- `allocation_decisions`: final budget decisions and rationale
- `allocation_strategy_snapshots`: Elastic-shaped strategy docs for each lane

This keeps allocation history isolated from the trading bot database and the non-trading operational ledger.

## Architecture

Files:

- `orchestration/models.py`: enums and dataclasses for observations, lane stats, and decisions
- `orchestration/store.py`: SQLite persistence plus local schema migration for new allocator fields
- `orchestration/resource_allocator.py`: allocation engine, layer reuse cadence, CUSUM decay detection, CLI

Execution flow:

1. Load the last 90 days of ROI observations for `trading` and `non_trading`.
2. Build lane analytics: average ROI, volatility, discounted win/loss counts, information ratio, CUSUM decay signal.
3. Apply the three-layer allocator:
   - Layer 1: monthly risk parity baseline from inverse 90-day volatility
   - Layer 2: weekly discounted Thompson Sampling tactical tilt, bounded to +/-35% around baseline
   - Layer 3: fractional Kelly tier assignment for downstream execution sizing
4. Enforce hard constraints:
   - 15% minimum and 85% maximum share per lane
   - 10% to 20% cash reserve
   - non-trading share cannot increase while deliverability risk is yellow or red
5. Persist the decision and per-lane strategy documents.

## Allocation Modes

### `three_layer`

This is the default production mode.

Behavior:

- uses trailing 90-day volatility for the monthly baseline
- uses discounted Thompson Sampling with `gamma=0.995` for tactical tilts
- stores Kelly tier guidance as:
  - `0.25` for bootstrapping
  - `0.333...` for medium confidence
  - `0.50` for high confidence
- raises the cash reserve to 20% when CUSUM detects decay or non-trading risk is red

### `fixed_split`

Legacy fallback mode.

- trading share defaults to `0.80`
- non-trading share defaults to `0.20`
- no cash reserve or strategy snapshots are added beyond the decision record

### `thompson_sampling`

Legacy single-layer bandit mode kept for fallback and comparison.

- positive ROI observations count as successes by default
- the lane share is determined directly from the sampled posteriors
- deliverability risk can still clamp non-trading growth

## Risk and Decay Handling

### Risk Parity

Monthly baseline:

- uses inverse volatility from the trailing 90-day observation window
- falls back to fixed split if the window has insufficient observations

### Discounted Thompson Tilt

Weekly tactical overlay:

- older observations decay by `gamma^age_days`
- the resulting target share is bounded so no lane can move more than 35% away from the baseline in one weekly update
- a decaying lane may not tilt above baseline even if its posterior sample is favorable

### CUSUM Decay Detection

Each lane runs a one-sided negative CUSUM over recent ROI.

- threshold: `3.0 sigma`
- effect:
  - forces the lane back to bootstrapping Kelly
  - increases the global cash reserve to 20%
  - records the decay alert in strategy snapshots

## Kelly Layer

Kelly is not used here to shrink the headline lane share. It is emitted as downstream execution guidance.

Tiering:

- bootstrapping: insufficient observations, non-positive ROI, or active decay alert -> `0.25`
- medium confidence: enough data for live allocation but not yet high-conviction -> `0.333...`
- high confidence: enough observations plus acceptable information ratio -> `0.50`

This keeps portfolio allocation and per-lane execution sizing separate.

## Elastic Strategy Snapshots

For each decision, the allocator writes two local strategy documents shaped for later indexing into `elastifund-strategies`.

Document fields include:

- `strategy_key`
- `agent_name`
- `baseline_share`
- `tilted_share`
- `final_share`
- `cash_reserve_share`
- `kelly_fraction`
- `confidence_tier`
- `volatility_90d`
- `avg_roi_90d`
- `cusum_score_sigma`
- `decay_detected`
- `rationale`

## Non-Trading Risk Contract

The allocator still expects a composite lane-health signal upstream. Today it accepts `deliverability_risk` as the conservative proxy.

The first production non-trading engine is now expected to be `revenue_audit`, which means the upstream composite signal needs to expand beyond email health alone.

Expected future upstream inputs:

- compliance health
- deliverability health
- billing and dispute health
- contribution margin quality
- fulfillment latency and failure rate
- detector precision or audit-quality drift

Until those are wired in, `deliverability_risk` remains the kill-rail for non-trading scaling.

## Standalone Usage

Default three-layer run:

```bash
python3 -m orchestration.resource_allocator \
  --decision-date 2026-03-07 \
  --deliverability-risk green
```

Legacy Thompson comparison run:

```bash
python3 -m orchestration.resource_allocator \
  --mode thompson_sampling \
  --decision-date 2026-03-07 \
  --deliverability-risk green \
  --seed 7
```

## Environment Variables

Core controls:

- `JJ_ALLOCATOR_MODE`
- `JJ_ALLOCATOR_ENABLE_THOMPSON_SAMPLING`
- `JJ_ALLOCATOR_TRADING_DAILY_BUDGET_USD`
- `JJ_ALLOCATOR_NON_TRADING_DAILY_SEND_QUOTA`
- `JJ_ALLOCATOR_NON_TRADING_DAILY_LLM_TOKENS`
- `JJ_ALLOCATOR_FIXED_TRADING_SHARE`
- `JJ_ALLOCATOR_MIN_NON_TRADING_SHARE`
- `JJ_ALLOCATOR_MIN_OBSERVATIONS_PER_ARM`
- `JJ_ALLOCATOR_OBSERVATION_LOOKBACK_DAYS`

Three-layer controls:

- `JJ_ALLOCATOR_RISK_PARITY_MIN_OBSERVATIONS`
- `JJ_ALLOCATOR_VOLATILITY_FLOOR`
- `JJ_ALLOCATOR_THOMPSON_DISCOUNT_GAMMA`
- `JJ_ALLOCATOR_THOMPSON_TILT_MAX_PCT`
- `JJ_ALLOCATOR_AGENT_MIN_SHARE`
- `JJ_ALLOCATOR_AGENT_MAX_SHARE`
- `JJ_ALLOCATOR_CASH_RESERVE_MIN_SHARE`
- `JJ_ALLOCATOR_CASH_RESERVE_YELLOW_SHARE`
- `JJ_ALLOCATOR_CASH_RESERVE_MAX_SHARE`
- `JJ_ALLOCATOR_KELLY_BOOTSTRAP_OBSERVATIONS`
- `JJ_ALLOCATOR_KELLY_HIGH_CONFIDENCE_OBSERVATIONS`
- `JJ_ALLOCATOR_KELLY_BOOTSTRAP_FRACTION`
- `JJ_ALLOCATOR_KELLY_MEDIUM_FRACTION`
- `JJ_ALLOCATOR_KELLY_HIGH_FRACTION`
- `JJ_ALLOCATOR_HIGH_CONFIDENCE_INFORMATION_RATIO`
- `JJ_ALLOCATOR_CUSUM_THRESHOLD_SIGMA`
- `JJ_ALLOCATOR_CUSUM_DRIFT_SIGMA`

See [NON_TRADING_EARNING_AGENT_DESIGN.md](NON_TRADING_EARNING_AGENT_DESIGN.md) for the broader non-trading lane design and upstream safety assumptions.
