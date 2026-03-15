# Structural Alpha Sprint — Updated Task List

Task queue aligned to the "Agentic Semantic Lead-Lag + Microstructure Toxicity Defense" directive.
Primary objective is structural alpha under strict maker-only execution.

---

## P0 — Mandatory Build Sequence (Execute First)

### SA-001: WebSocket-First Core and Polling Deprecation
**Objective:** make all critical execution decisions event-driven.
**Implementation:**
- Run persistent market + user WebSocket channels with reconnect and heartbeat.
- Route toxicity and fill events directly to execution layer.
- Keep REST only for bootstrap/fallback snapshots.
**Deliverable:** no critical trade path depends on periodic polling.

### SA-002: Tick Data and Volume-Clock Storage
**Objective:** persist high-frequency state needed for structural features.
**Implementation:**
- Store top-5 order book levels, trades, and volume bucket boundaries.
- Persist features for OFI, VPIN, lead-lag confidence, and inventory skew.
**Deliverable:** replayable dataset for deterministic backtest and incident review.

### SA-003: Statistical Lead-Lag Screener
**Objective:** identify directed leader-follower candidates with causal evidence.
**Implementation:**
- Apply log-odds transform to prices before econometric tests.
- Run bidirectional VAR/Granger across clustered markets.
- Keep direction with strongest statistical evidence (lowest p-value).
**Deliverable:** ranked directed pair list with lag and significance metrics.

### SA-004: Semantic Risk-Manager Layer
**Objective:** remove spurious statistical links before execution.
**Implementation:**
- LLM checks contract resolution criteria and transmission mechanism.
- Force sign output (`+1` aligned, `-1` inverse) and semantic confidence score.
- Reject incoherent pairs automatically.
**Deliverable:** approved semantic pair book for execution authorization.

### SA-005: Multi-Level OFI Defense
**Objective:** detect latent pressure and avoid stale-quote adverse selection.
**Implementation:**
- Use top-5 weights `[1.0, 0.5, 0.25, 0.125, 0.0625]`.
- Normalize OFI with rolling 5-minute Z-score.
- Cancel vulnerable-side quotes at >60% directional skew or 3:1 dominance.
**Deliverable:** live OFI kill-switch events feeding execution controls.

### SA-006: VPIN Toxicity Defense
**Objective:** adapt quoting during informed-flow bursts.
**Implementation:**
- Build equal-volume bucket pipeline with probabilistic buy/sell split.
- Compute rolling VPIN and trigger defense above rolling 80th percentile.
- On breach, widen spread and reduce size; on normalization, restore quoting.
**Deliverable:** auditable toxicity regime transitions with quote policy changes.

### SA-007: Hybrid Agentic + Deterministic Runtime
**Objective:** separate cognition from millisecond execution.
**Implementation:**
- LLM orchestration outputs only strategic state commands.
- Deterministic layer computes spreads, sizes, and cancel/replace timing.
- Enforce protocol actions: `AUTHORIZE_PAIR`, `HALT_MARKET`, `REDUCE_SIZE`, `LIQUIDATE_PAIR`.
**Deliverable:** zero direct LLM price placement in the order path.

### SA-008: Calibration and Cost Gates
**Objective:** block overconfident and cost-blind execution.
**Implementation:**
- Hard-enforce Platt scaling (`A=0.5914`, `B=-0.3977`) before Kelly sizing.
- Model polynomial fee stress and include 5ms latency penalty in validation.
- Auto-reject uncalibrated or negative post-cost candidates.
**Deliverable:** strict pre-trade calibration/cost compliance checks.

### SA-009: Maker-Only Execution Protocol Upgrade
**Objective:** preserve structural maker edge and stale-order safety.
**Implementation:**
- Use post-only Good-Til-Date limits only.
- Use batch endpoint (up to 15 orders) for multi-level quote placement.
- Add stale-quote expiry and global cancel safety hooks.
**Deliverable:** production maker stack with deterministic stale-order cleanup.

### SA-010: Inventory and Token Logistics
**Objective:** rebalance inventory without fee bleed.
**Implementation:**
- Implement inventory-skew-aware bid/ask adjustments.
- Integrate split/merge relayer flow for gasless collateral management.
**Deliverable:** inventory control without forced taker exits.

### SA-011: Oracle Dispute Arbitrage Module
**Objective:** exploit deterministic convergence in premature proposal disputes.
**Implementation:**
- Detect "too-early" proposal states via resolution rule checks.
- Authorize panic-liquidity bids only when eventual outcome is criteria-deterministic.
- Halt when wording ambiguity cannot be machine-verified.
**Deliverable:** dispute-state strategy with explicit enter/halt playbook.

### SA-012: Structural Kill Rules and Promotion Gate
**Objective:** enforce rejection discipline before live capital.
**Implementation:**
- Enforce semantic decay, toxicity survival, polynomial cost stress, and calibration gates.
- Run top-decile VPIN fill stress tests in backtest.
- Require 72h paper burn with positive post-cost EV and drawdown improvement.
**Deliverable:** binary go/no-go report with machine-readable failure reasons.

---

## P1 — Secondary (Only If P0 Is On Track)

### SA-013: Sports Oracle Pilot (Pinnacle/OddsAPI)
Maintain as secondary module. No capital until SA-001 through SA-012 pass.

### SA-014: Weather/Kalshi Maintenance
Keep lightweight R&D only; do not consume core engineering budget.

---

## P2 — Hold / Deprecated

### SA-015: Pause Legacy Directional Standalone Strategies
No new work on generic mean-reversion or momentum variants outside structural framework.

### SA-016: Keep Watchlist Queued
Research ideas remain queued but blocked unless they pass structural kill rules.
