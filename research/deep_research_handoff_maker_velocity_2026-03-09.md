# Maker Velocity Deep Research Handoff

**As-of timestamp:** 2026-03-09T11:32:19Z  
**Prepared for:** ChatGPT Deep Research  
**Prepared by:** Codex execution lane  
**Scope:** Continuous trading-data flywheel with paper + live markets, Polymarket + Kalshi, always-on <=24h edge detection and execution readiness.

## 1. Mission and Non-Negotiables

- Primary mission: maximize improvement velocity toward first durable positive expectancy in short-resolution markets.
- Primary execution track: `maker_velocity_all_in` runtime profile for high-frequency maker-first discovery.
- Hard scope for this phase:
  - Markets resolving in **24 hours or less**.
  - Venues: **Polymarket and Kalshi**.
  - Modes: paper and shadow now, micro-live/live only after explicit operator approval.
- System requirement: both bots should be continuously prepared to invest when edge conditions pass gates.
- Process requirement: continuous evaluate-update loop using Claude loop functionality (flywheel cycles + empirical gate decisions).

## 2. Current Machine Truth (Use This, Not Stale Prose)

Canonical artifacts:

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `reports/state_improvement_latest.json`

Snapshot highlights (2026-03-09):

- Root verification: **passing** (`1096 passed` + `25 passed`) at `2026-03-09T11:31:50Z`.
- Runtime profile in state-improvement report: `maker_velocity_all_in`.
- Active thresholds: YES `0.05`, NO `0.02`, max resolution `24h`.
- Service status: `jj-live.service` is **running** (`active`) but launch posture remains **blocked**.
- Drift flag present: running service while launch remains blocked; remote mode must be explicitly confirmed as paper or shadow.
- Capital tracked: `$347.51` total (`$247.51` Polymarket + `$100` Kalshi).
- Trades: `5` total in db, `0` closed trades, `open_positions=4`, realized pnl flat.
- Fast-flow restart readiness: `true`.
- Structural lanes A-6/B-1: still blocked by empirical gates.

## 3. Runtime Posture to Assume

Runtime profile file:

- `config/runtime_profiles/maker_velocity_all_in.json`

Key values currently set:

- `execution_mode=shadow`
- `paper_trading=false`
- `allow_order_submission=true`
- `fast_flow_only=true`
- `enable_wallet_flow=true`
- `enable_lmsr=true`
- `enable_llm_signals=false`
- `max_position_usd=247.51`
- `max_daily_loss_usd=247.51`
- `max_exposure_pct=1.0`
- `max_open_positions=1`
- `kelly_fraction=1.0`
- `max_resolution_hours=24`
- `scan_interval_seconds=15`

Interpretation: this is intentionally aggressive for rapid evidence generation; it increases risk and must be treated as controlled experimentation posture, not production-safe default.

## 4. What We Need Deep Research to Produce

Deliver a practical research package that can be executed immediately in this repo:

1. **Continuous Data Flywheel Design**
- A closed loop for ingest -> feature compute -> signal score -> route decision -> execution outcome -> recalibration.
- Separate lanes for paper, shadow, and live; shared metrics schema.
- How to keep both venue bots always ready without overtrading noise.

2. **Polymarket + Kalshi Unified Opportunity Model**
- Comparable market representation for <=24h contracts.
- Venue-specific execution constraints (fees, tick size, maker eligibility, latency, fill behavior).
- Cross-venue prioritization logic when only one side has executable edge.

3. **Edge Readiness Framework (24h or Less)**
- Quantitative checklist to classify opportunities into:
  - `execute_now`
  - `paper_only`
  - `shadow_only`
  - `reject`
- Must include minimum sample requirements and confidence bounds.

4. **Maker Velocity Research Track Optimization**
- Highest-ROI experiments for first 7, 14, and 30 days.
- Explicit hypotheses and stop/continue criteria.
- Expected information gain per experiment hour.

5. **Claude Loop Operational Blueprint**
- How Claude loop should run continuously with machine-checkable outputs.
- Required artifacts every cycle (JSON + markdown summary).
- Promotion/demotion rules for lanes and thresholds.

6. **Risk and Kill-Rule Upgrade Plan**
- Keep current mission velocity while avoiding hidden blow-up modes.
- Specific controls for all-in concentration (`max_open_positions=1`, full Kelly, full exposure).
- Clear downgrade path from all-in to guarded mode when empirical edge degrades.

## 5. Required Output Format From Deep Research

Ask Deep Research to return:

- A ranked implementation backlog (P0/P1/P2) with effort, risk, and expected edge impact.
- A one-week execution plan with daily checkpoints.
- A metric contract (definitions + formulas + file paths) for flywheel scoring.
- A minimal experiment matrix covering wallet-flow, LMSR, cross-venue opportunities, and calibration updates.
- Concrete pseudocode or architecture decisions that map onto existing paths:
  - `bot/`
  - `signals/`
  - `strategies/`
  - `orchestration/`
  - `scripts/write_remote_cycle_status.py`

## 6. Key Constraints Deep Research Must Respect

- No invented runtime APIs if existing JSON handoff artifacts already carry state.
- Live-trading-sensitive paths require test evidence (`bot/`, `execution/`, `strategies/`, `signals/`, `infra/`).
- Runtime truth must prefer machine artifacts over stale markdown claims.
- Structural alpha (A-6/B-1) remains blocked unless empirical gates are proven.
- Any recommendation that spends real money must include explicit guardrails and rollback criteria.

## 7. Open Problems Needing High-Quality Answers

- Why edge reachability remains near zero even at wide-open thresholds.
- Whether stale/overfit calibration is suppressing real opportunities.
- How to separate “no market edge exists” from “pipeline cannot detect edge in time.”
- Whether maker-only execution assumptions are realistic on both venues for <=24h windows.
- Optimal data cadence for rapid iteration without overfitting to microbursts.

## 8. Immediate Execution Context for Next Agent

Already completed in this run:

- Local tests now pass (`make test` green).
- Runtime truth artifacts refreshed with passing verification.
- Maker-velocity profile and deployment contract are in place.

Still unresolved:

- Remote drift reconciliation: service running while launch posture is blocked.
- No closed trades yet for calibration promotion.
- A-6/B-1 empirical gates remain blocked.

## 9. Suggested Prompt Stub for Deep Research

"Using the attached repo context and machine-truth artifacts, design an execution-ready, continuous data flywheel for a dual-venue (Polymarket + Kalshi) maker-velocity system focused on <=24h markets. Assume `maker_velocity_all_in` posture is active for research velocity, but provide safe downgrade controls. Produce a ranked implementation plan, explicit metric contract, experiment matrix, and Claude-loop operating protocol that can be applied directly to this codebase. Prioritize actions that maximize information gain and time-to-first-repeatable edge, not theoretical elegance."

## 10. Source Index

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `reports/state_improvement_latest.json`
- `config/runtime_profiles/maker_velocity_all_in.json`
- `docs/ops/TRADING_LAUNCH_CHECKLIST.md`
- `research/edge_backlog_ranked.md`
