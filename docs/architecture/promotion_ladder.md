# Proof-to-Capital Promotion Ladder

## Design Principle

No strategy trades live money without carrying proof that it deserves to. Every stage transition requires passing all four proof surfaces (Section 5). The system is designed so that a learning-layer change (new model, new signal, new parameter) cannot widen live risk without clearing every gate. Hope is not a position size.

---

## 1. Promotion Ladder

### Stage 0: HYPOTHESIS

**Entry:** Idea exists in `research/edge_backlog_ranked.md` or autoresearch output.

**Required artifacts:**
- Written thesis: what market structure produces the edge, why it persists, what would kill it
- Named kill condition (falsifiable, measurable)
- Estimated time horizon and market type

**Gate to Stage 1:** Thesis is internally consistent and the kill condition is testable with available data. No quantitative bar — this is a research quality gate.

**Capital at risk:** $0.

---

### Stage 1: BACKTESTED

**Entry:** Hypothesis has been replayed against historical data.

**Required artifacts:**
- Deterministic replay on >= 200 historical events (or all available if fewer exist)
- Replay log with timestamps, decisions, simulated fills, simulated P&L
- Replay must use realistic fill assumptions: maker-only, no look-ahead, 500ms latency penalty

**Quantitative gates (all must pass):**
| Metric | Threshold |
|--------|-----------|
| Sample size | >= 200 replay events |
| Win rate | > 51% |
| Profit factor | > 1.00 |
| Max drawdown | < 30% of simulated bankroll |
| Edge vs. random baseline | Positive (bootstrap p < 0.10) |

**Gate to Stage 2:** Pass all quantitative gates AND the Replay proof surface (Section 5.1) AND the World-League proof surface (Section 5.3).

**Capital at risk:** $0.

---

### Stage 2: SHADOW

**Entry:** Strategy runs in production pipeline, sees live data, generates decisions, but places no orders.

**Required artifacts:**
- Shadow trade log: every decision the strategy would have made, with timestamp, market_id, side, size, price, probability estimate
- Shadow P&L computed using actual market outcomes
- Minimum 7 calendar days of shadow operation OR 100 shadow decisions, whichever comes later
- Latency log: time from signal to hypothetical order, proving the strategy could have executed in time

**Quantitative gates (all must pass):**
| Metric | Threshold |
|--------|-----------|
| Shadow decisions | >= 100 |
| Calendar days | >= 7 |
| Win rate | > 51% |
| Profit factor | > 1.02 |
| Max drawdown | < 25% of simulated allocation |
| Signal-to-order latency | p99 < 2000ms |

**Gate to Stage 3:** Pass all quantitative gates AND the Off-Policy proof surface (Section 5.2) — shadow period data must be disjoint from backtest training data.

**Capital at risk:** $0.

---

### Stage 3: MICRO-LIVE

**Entry:** Real orders, minimal size. This is the execution-quality proving ground.

**Position size:** $2-5 per trade (configurable, default $5).

**Allocation cap:** 10% of total bankroll reserved for all Stage 3 strategies combined.

**Required artifacts:**
- Fill log: every order submitted, every fill received, slippage vs. expected price
- Minimum 50 filled trades (not submitted — filled)
- Minimum 14 calendar days at this stage
- Fill rate: what fraction of submitted orders actually execute

**Quantitative gates (all must pass):**
| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Filled trades | >= 50 | Minimum for binomial significance |
| Win rate | > 52% | Binomial test p < 0.05 one-tailed at n=50, k=26 gives p=0.44 — we need 30/50 (60%) for p<0.05 at 50 fills. At 200 fills, 52% clears. Use exact binomial: require p < 0.05 against H0: WR=50% |
| Profit factor | > 1.05 | Covers fees and slippage |
| Max drawdown | < 20% of Stage 3 allocated capital |
| Sharpe ratio | > 0.5 (annualized) |
| Fill rate | > 30% of submitted orders | Below this, the strategy has an execution problem, not an edge |
| Slippage | Median < 1% of position size | Execution quality check |

**Binomial gate (precise definition):** Given N fills with K wins, compute one-tailed binomial p-value against H0: true_win_rate = 0.50. Require p < 0.05. At N=50, this requires K >= 32 (64%). At N=100, K >= 59 (59%). At N=200, K >= 112 (56%). The win rate threshold in the table above is a necessary but not sufficient condition; the binomial test is the actual gate.

**Gate to Stage 4:** Pass all quantitative gates AND all four proof surfaces (Section 5).

**Capital at risk:** Max $250 total across all Stage 3 strategies (adjustable via `STAGE3_CAPITAL_CAP` env var).

---

### Stage 4: SEED

**Entry:** Proven execution quality. Scaling position size to find the strategy's real capacity.

**Position size:** $5-25 per trade.

**Allocation cap:** 20% of total bankroll reserved for all Stage 4 strategies combined.

**Required artifacts:**
- Full trade log with fill quality metrics
- Minimum 200 filled trades
- Minimum 30 calendar days at this stage
- Capacity analysis: does P&L per trade degrade as size increases?

**Quantitative gates (all must pass):**
| Metric | Threshold |
|--------|-----------|
| Filled trades | >= 200 |
| Win rate | > 53% |
| Profit factor | > 1.10 |
| Kelly fraction | > 0.02 (non-trivial edge) |
| Max drawdown | < 15% of Stage 4 allocated capital |
| No single-day loss | > 10% of Stage 4 allocated capital |
| Sharpe ratio | > 1.0 (annualized) |
| Capacity signal | Profit-per-trade does not decline > 20% from Stage 3 level |

**Gate to Stage 5:** Pass all quantitative gates. Four proof surfaces must have been passed at Stage 3 entry; re-run World-League pass (Section 5.3) with Stage 4 data to confirm edge persists at scale.

**Capital at risk:** Max 20% of bankroll.

---

### Stage 5: SCALE

**Entry:** Edge is proven, sized, and stable. Full operational deployment with continuous monitoring.

**Position size:** $25-100 per trade (or up to Kelly-optimal, whichever is smaller).

**Allocation cap:** 50% of total bankroll for all Stage 5 strategies combined.

**Continuous monitoring (checked every 24 hours):**
| Metric | Demotion trigger |
|--------|-----------------|
| Rolling 50-trade win rate | < 50% |
| Rolling 50-trade profit factor | < 1.00 |
| 7-day drawdown | > 10% of allocated capital |
| 3 consecutive losing calendar days | Trigger review (not automatic demotion) |
| Fill rate collapse | < 20% of submitted orders over 48 hours |

No gate to Stage 6 — Stage 6 promotion requires explicit human approval (John).

**Capital at risk:** Max 50% of bankroll.

---

### Stage 6: CORE

**Entry:** Human-approved. Full Kelly sizing. The strategy has survived months of live trading and is a proven, permanent edge.

**Position size:** Full Kelly (quarter-Kelly default, adjustable by John).

**Allocation cap:** No fixed cap — Kelly sizing self-limits.

**Continuous monitoring:** Same as Stage 5, but demotion goes to Stage 5 (not further) unless catastrophic.

**Promotion requirement:** John explicitly approves. This is the one gate that cannot be automated. The agent presents the evidence; the human signs off.

**Capital at risk:** Full bankroll exposure allowed (Kelly-limited).

---

## 2. Rollback Rules

### Automatic Demotion Triggers

| Trigger | From Stage | To Stage | Speed |
|---------|-----------|----------|-------|
| Max drawdown breached | Any >= 3 | Stage - 1 | Immediate. All open positions at that stage are closed within 60 seconds. |
| Single-day loss > 10% of stage capital | 4, 5, 6 | Stage - 1 | Immediate. |
| Rolling 50-trade profit factor < 0.90 | Any >= 3 | Stage - 2 | Immediate. PF below 0.90 means the strategy is losing money after fees — skip one stage. |
| Rolling 50-trade win rate < 48% | Any >= 3 | Stage - 1 | End of day. Allows for intra-day recovery. |
| Fill rate < 15% over 72 hours | Any >= 3 | Stage 2 (SHADOW) | Immediate. The strategy has an execution problem, not an edge problem. Demote to shadow until execution is fixed. |
| 5 consecutive losing calendar days | 5, 6 | Stage 4 | End of 5th day. |
| Regime transition detected | 5, 6 | Freeze (no new trades, existing positions held) | Immediate. Resume when regime returns to stable. |
| Kill condition met | Any | Stage 0 (HYPOTHESIS) | Immediate. Strategy is dead. Must re-enter from scratch with new thesis. |

### Demotion Mechanics

1. **Position closure:** On immediate demotion, the system cancels all pending orders for the demoted strategy and submits market-rate exits for open positions. If exits would exceed daily loss limits, positions are held and closed over 24-48 hours.

2. **Data preservation:** All trade logs, fill data, P&L records, and proof-surface artifacts are preserved permanently in `reports/strategy_promotions/{strategy_id}/`. Demotion does not delete evidence.

3. **Cool-off period:** After demotion, a strategy cannot attempt re-promotion for:
   - Stage 3 -> 2: 7 calendar days
   - Stage 4 -> 3: 14 calendar days
   - Stage 5 -> 4: 21 calendar days
   - Stage 5 -> 2 (execution failure): 14 calendar days after execution fix is verified
   - Stage any -> 0 (kill condition): No re-promotion. New thesis required.

4. **Re-promotion:** After cool-off, the strategy must pass ALL gates for the target stage using ONLY data collected after the demotion event. Pre-demotion data does not count toward re-promotion. This prevents a strategy from coasting on historical performance that no longer holds.

---

## 3. Proving-Ground Stages (Technical Design)

### 3.1 Shadow Trading

Shadow trading runs inside `EnhancedPipeline` as a parallel decision path.

**Implementation:**
- `ShadowTracker` class receives the same `PipelineSignal` that the live path receives
- Shadow tracker computes: would I trade this? At what size? At what price?
- Shadow decisions are logged to `shadow_trades.db` (SQLite) with schema:
  ```
  strategy_id TEXT, market_id TEXT, timestamp REAL,
  side TEXT, size_usd REAL, expected_price REAL,
  actual_outcome TEXT, shadow_pnl REAL, latency_ms REAL
  ```
- Shadow P&L is computed when markets resolve, using actual resolution prices
- No orders are submitted. No capital is at risk.
- Shadow tracker runs as a post-decision hook in the pipeline — it sees the same data, at the same time, with the same latency

**Anti-gaming:** Shadow results cannot be edited retroactively. The database uses append-only writes with monotonic timestamps. The promotion gate reads directly from the database, not from any intermediate report.

### 3.2 Micro-Live vs. Shadow

| Property | Shadow (Stage 2) | Micro-Live (Stage 3) |
|----------|------------------|---------------------|
| Orders submitted | No | Yes (real maker orders) |
| Capital at risk | $0 | $2-5 per trade |
| Fill uncertainty | None (assumed fills) | Real (orders may not fill) |
| Slippage measurement | Impossible | Measured per fill |
| Execution latency | Simulated | Real |
| Market impact | Zero | Negligible at this size, but measured |

The transition from Shadow to Micro-Live is the critical moment where theory meets reality. Many strategies that look good in shadow fail in micro-live because:
- Their orders don't fill (maker orders at the wrong price)
- Slippage eats the edge
- The strategy is too slow (latency kills the signal)
- Market conditions have shifted since the shadow period

### 3.3 Anti-Gaming Provisions

The promotion system is designed to resist the following failure modes:

1. **Cherry-picking periods:** All gates require minimum calendar days, not just minimum trades. A strategy cannot game the gate by trading only on favorable days.

2. **Overfitting to the gate:** The binomial test uses H0: WR=50%, not the strategy's own historical win rate. Meeting the gate proves you're better than random, not better than your own past.

3. **Parameter snooping:** The Off-Policy proof surface (Section 5.2) requires performance on data the strategy has never seen. If parameters were tuned to the backtest data, they will fail on out-of-sample.

4. **Survivorship bias in shadow:** Shadow decisions are logged at decision time, not at resolution time. You cannot retroactively add winning trades or remove losing ones.

5. **Size-dependent edge decay:** The capacity check at Stage 4 explicitly tests whether the edge degrades as position size increases. Strategies that only work at micro-size are caught here.

6. **Constraint engine integration:** The `ConstraintEngine` in `bot/agent_constraints.py` enforces stage-appropriate position caps at runtime. A Stage 3 strategy physically cannot submit a Stage 5 order — the constraint engine will BLOCK or MODIFY it down. The promotion stage is stored in `TradingState.metadata` and checked by a stage-aware constraint.

---

## 4. Capital-Allocation Policy

### 4.1 Stage-Based Allocation

Total bankroll is partitioned across stages. These are hard caps enforced by the constraint engine.

| Stage | Allocation % of Bankroll | Purpose |
|-------|-------------------------|---------|
| Stage 2 (Shadow) | 0% | No capital required |
| Stage 3 (Micro-Live) | 10% | Proving ground — small bets, many strategies |
| Stage 4 (Seed) | 20% | Scaling test — fewer strategies, larger bets |
| Stage 5 (Scale) | 50% | Proven edges — bulk of capital |
| Stage 6 (Core) | Remainder (up to 100%) | Full Kelly — bankroll-limited |
| Reserve | 10% minimum | Never deployed — buffer against correlated drawdowns |

**Constraint:** Stage 3 + Stage 4 + Stage 5 + Stage 6 + Reserve = 100%. If a stage is empty (no strategies at that level), its allocation flows to Reserve.

### 4.2 Intra-Stage Allocation

When multiple strategies occupy the same stage:
- **Stage 3:** Equal allocation per strategy, capped at `STAGE3_CAPITAL_CAP / num_stage3_strategies`
- **Stage 4:** Proportional to each strategy's rolling Sharpe ratio (higher Sharpe gets more capital)
- **Stage 5+:** Kelly-optimal sizing per strategy, subject to the stage cap

### 4.3 New Deposits

When new capital is deposited:
1. 10% goes to Reserve (always)
2. Remaining 90% is allocated proportionally to existing stage weights
3. If no strategies exist at Stage 5+, new deposits go 100% to Reserve until at least one strategy is promoted

### 4.4 Profit Reinvestment

- Profits from Stage 3-4 strategies: 100% reinvested into their own stage allocation (compound the proving ground)
- Profits from Stage 5-6 strategies: 50% reinvested, 50% to Reserve (build the buffer)
- Reserve is rebalanced monthly: excess above 15% of bankroll is redistributed to Stage 5+ strategies

### 4.5 Loss Handling

- Losses at any stage reduce that stage's allocation
- If a stage's capital drops below 50% of its target allocation, no new strategies can enter that stage until capital is replenished from Reserve or profits
- If Reserve drops below 5% of bankroll: all Stage 3-4 position sizes are halved, and no new Stage 3 entries are allowed

---

## 5. Proof Surfaces

Every promotion from Stage N to Stage N+1 (for N >= 1) requires passing all four proof surfaces. These are independent checks — passing three of four is a FAIL.

### 5.1 Replay Pass

**What it proves:** The strategy produces positive expectancy on historical data under realistic execution assumptions.

**Method:**
1. Collect historical market data: prices, outcomes, timestamps
2. Replay the strategy's decision logic deterministically — same code path, same parameters
3. Simulate fills with: maker-only execution, 500ms latency penalty, no look-ahead
4. Compute: win rate, profit factor, max drawdown, Sharpe

**Pass criteria:**
- Profit factor > 1.00
- Max drawdown < 30% of simulated bankroll
- Minimum 200 replayed events

**Artifact:** `reports/strategy_promotions/{strategy_id}/replay_pass_{timestamp}.json`

### 5.2 Off-Policy Pass

**What it proves:** The strategy generalizes beyond its training data. It works on data it has never seen.

**Method:**
1. Split available data into train (60%) and holdout (40%) by time — holdout is ALWAYS the more recent period
2. Fit/tune parameters on train only
3. Evaluate on holdout with identical replay methodology
4. Holdout performance must meet minimum thresholds independently

**Pass criteria:**
- Holdout profit factor > 1.00
- Holdout win rate within 5 percentage points of train win rate (stability check)
- Holdout Sharpe > 0 (the strategy makes money out-of-sample)

**Artifact:** `reports/strategy_promotions/{strategy_id}/offpolicy_pass_{timestamp}.json`

### 5.3 World-League Pass

**What it proves:** The strategy outperforms naive baselines. It is not merely tracking market noise.

**Method:** Run the strategy against three baselines on identical data:
1. **Random baseline:** Buy YES or NO with equal probability, same position sizing
2. **Always-YES baseline:** Buy YES on every signal, same sizing
3. **Always-NO baseline:** Buy NO on every signal, same sizing

Compute each baseline's P&L over the same period.

**Pass criteria:**
- Strategy profit factor > max(baseline profit factors) + 0.05
- Strategy Sharpe > max(baseline Sharpes)
- Strategy max drawdown < min(baseline max drawdowns) * 1.5

**Artifact:** `reports/strategy_promotions/{strategy_id}/worldleague_pass_{timestamp}.json`

### 5.4 Micro-Live Execution-Quality Pass

**What it proves:** Orders actually fill at expected prices in the real market.

**Method:** Analyze Stage 3 (or Stage 4) fill data:
1. Compute fill rate: filled orders / submitted orders
2. Compute slippage: abs(fill_price - expected_price) / expected_price per fill
3. Compute latency: time from signal to order submission

**Pass criteria:**
- Fill rate > 30%
- Median slippage < 1.0%
- p99 signal-to-order latency < 2000ms
- No evidence of systematic adverse selection (wins and losses should not cluster by time-of-day or market type in a way that suggests the strategy is being picked off)

**Artifact:** `reports/strategy_promotions/{strategy_id}/execution_pass_{timestamp}.json`

---

## 6. Implementation Integration

### 6.1 Constraint Engine Extension

Add a new constraint to `bot/agent_constraints.py`:

```python
# Stage-aware position cap
def _stage_position_cap(proposal: TradeProposal, state: TradingState) -> bool:
    stage = state.metadata.get("strategy_stages", {}).get(proposal.strategy_id, 0)
    caps = {0: 0, 1: 0, 2: 0, 3: 5, 4: 25, 5: 100, 6: float("inf")}
    return proposal.amount_usd > caps.get(stage, 0)
```

### 6.2 Database Schema

```sql
CREATE TABLE promotion_events (
    id INTEGER PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    from_stage INTEGER NOT NULL,
    to_stage INTEGER NOT NULL,
    event_type TEXT NOT NULL,  -- 'promotion', 'demotion', 'freeze', 'kill'
    timestamp REAL NOT NULL,
    evidence_path TEXT,        -- path to proof surface artifacts
    gate_results TEXT,         -- JSON of all gate metric values
    reason TEXT
);

CREATE TABLE stage_allocations (
    stage INTEGER PRIMARY KEY,
    target_pct REAL NOT NULL,
    current_usd REAL NOT NULL,
    last_updated REAL NOT NULL
);
```

### 6.3 File Layout

```
reports/strategy_promotions/
  {strategy_id}/
    replay_pass_{timestamp}.json
    offpolicy_pass_{timestamp}.json
    worldleague_pass_{timestamp}.json
    execution_pass_{timestamp}.json
    promotion_log.jsonl          # append-only event log
    shadow_trades.db             # shadow period data
    microlive_fills.db           # Stage 3 fill data
```

---

## 7. Safety Guarantee

The design satisfies the acceptance criterion: **it is impossible for a learning-layer change to widen live risk without passing the proof surfaces.**

Here is why:

1. **Position caps are enforced at runtime by the constraint engine**, not by the strategy itself. A strategy cannot override its own stage cap. The `ConstraintEngine.evaluate()` method checks stage membership on every trade proposal, every cycle.

2. **Promotion requires all four proof surfaces.** A new model or parameter change resets the strategy's proof status. The off-policy pass specifically catches overfitting. The execution pass catches strategies that look good on paper but fail in practice.

3. **Stage transitions are logged immutably.** Every promotion and demotion event is written to `promotion_events` with the full gate results. Auditing is trivial.

4. **Capital allocation is partitioned.** Even if a Stage 3 strategy somehow evades its position cap (which the constraint engine prevents), it can only access 10% of bankroll. Correlated failures across all Stage 3 strategies cost at most 10% of total capital.

5. **Demotion is automatic and immediate for severe triggers.** The system does not wait for human review to cut risk. Drawdown breaches, loss-limit hits, and fill-rate collapses trigger instant demotion with position closure.

6. **Cool-off periods prevent rapid re-promotion.** A demoted strategy cannot immediately re-enter with the same parameters and ride a mean-reversion bounce back through the gate.

7. **Stage 6 (Core) requires human approval.** The highest capital allocation level cannot be reached autonomously. This is the ultimate safety valve.

---

*Authored: 2026-03-22. Supersedes ad-hoc DISPATCH_102 promotion gate. This document is the canonical reference for all strategy promotion decisions.*
