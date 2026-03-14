# HFT Refactor Blueprint (Maker-First, Truth-First)

Status: active plan
Last updated: 2026-03-11
Category: active plan
Canonical: yes
Source research: `research/imports/HFT_ARCHITECTURAL_ANALYSIS_REFACTOR_BLUEPRINT_2026-03-11.md`
Machine task contract: `reports/hft_refactor/latest.json`

## Objective

Unblock live trading posture by fixing runtime truth drift, enforcing maker economics, and staging a safe migration of latency-critical hot paths without breaking policy gates.

## Program Guardrails

1. Wallet and runtime artifacts override narrative summaries when they conflict.
2. No live-capital scaling while launch posture is blocked or reconciliation is incoherent.
3. Maker-only remains mandatory for fee-bearing fast markets.
4. A-6/B-1/NegRisk promotion remains gate-driven and evidence-driven.
5. Infra changes must pass legal/compliance constraints and platform policy.

## Phase Plan

| Phase | Name | Goal | Exit Gate |
|---|---|---|---|
| P0 | Runtime Truth Hardening | Eliminate state drift as a blocker | `reconciliation.status=reconciled` and launch contract fields agree |
| P1 | Maker Economics Hardening | Keep execution aligned with fee/rebate microstructure | 100% `post_only` in audited fills |
| P2 | Rust Hot-Path Prototype | Prove low-latency path without rewriting whole stack | replay parity + bounded latency report |
| P3 | Microstructure Defense | Add OFI/VPIN toxicity controls to execution router | toxicity gate metrics visible in runtime artifacts |
| P4 | STE Cross-Asset Signal | Add non-linear lead-lag signal lane in shadow mode | shadow signal quality exceeds baseline thresholds |
| P5 | NegRisk/A-6/B-1 Completion | Close blocked structural lanes or kill on schedule | lane-specific gates pass or explicit kill filed |
| P6 | Deployment Topology + Promotion | Promote only after policy-compliant operational readiness | launch posture clear + rollout checks green |

## Methodical Task List

### P0 - Runtime Truth Hardening

| ID | Task | Primary Paths | Acceptance | Verification |
|---|---|---|---|---|
| RT-01 | Enforce remote-wallet precedence for position truth | `bot/wallet_reconciliation.py`, `scripts/write_remote_cycle_status.py` | Drift resolution path always favors remote wallet when conflicts exist | `pytest tests/test_wallet_reconciliation.py tests/test_remote_cycle_status.py -q` |
| RT-02 | Tighten reconciliation run artifacts (`latest` + timestamped snapshots) | `scripts/reconcile_polymarket_wallet.py`, `reports/wallet_reconciliation/` | Each run writes deterministic summary payload with recommendation and mismatch deltas | `pytest tests/test_wallet_reconciliation.py -q` |
| RT-03 | Add explicit mismatch reason taxonomy for open/closed/capital deltas | `scripts/write_remote_cycle_status.py` | Block reasons classify count-drift vs capital-attribution drift separately | `pytest tests/test_remote_cycle_status.py -q` |
| RT-04 | Add stale-source guard for wallet export vs probe precedence | `scripts/write_remote_cycle_status.py` | Reporting precedence cannot select stale source when fresher source exists | `pytest tests/test_remote_cycle_status.py tests/test_render_public_metrics.py -q` |
| RT-05 | Add automatic reconcile-then-retry hook in fast-flow restart path | `bot/jj_live_fast_flow_restart.py`, `scripts/reconcile_polymarket_wallet.py` | Restart path executes reconciliation before declaring blocked steady state | `pytest tests/test_jj_live_fast_flow_restart.py -q` |
| RT-06 | Publish one-cycle operator digest for truth drift | `reports/runtime_truth_latest.json`, `reports/remote_cycle_status.json` | Digest includes one-next-cycle action that is executable, not generic | `pytest tests/test_remote_cycle_status.py tests/test_edge_scan_report.py -q` |

### P1 - Maker Economics Hardening

| ID | Task | Primary Paths | Acceptance | Verification |
|---|---|---|---|---|
| MK-01 | Audit all order submission paths for `post_only` invariants | `bot/jj_live.py`, `execution/`, `strategies/` | No fee-bearing path can submit taker-crossing orders | `pytest tests/test_a6_executor_live_orders.py tests/test_a6_jj_live_integration.py tests/test_maker_velocity_blitz.py -q` |
| MK-02 | Add rebate-aware expected value accounting | `scripts/run_btc5_autoresearch_cycle.py`, `scripts/write_remote_cycle_status.py` | EV includes maker rebate assumptions and logs the assumptions used | `pytest tests/test_run_btc5_autoresearch_cycle.py tests/test_remote_cycle_status.py -q` |
| MK-03 | Add cancel/replace cadence controls with stale-quote risk bounds | `bot/btc_5min_maker.py`, `infra/clob_ws.py` | Quote freshness windows and cancel TTL are explicit config controls | `pytest tests/test_maker_velocity_blitz_script.py tests/test_gamma_market_cache.py -q` |
| MK-04 | Record post-only failure/retry rates as first-class metrics | `scripts/btc5_monte_carlo.py`, `reports/` | Runtime packet exposes retry-failure drag with stage impact | `pytest tests/test_btc5_monte_carlo.py -q` |

### P2 - Rust Hot-Path Prototype

| ID | Task | Primary Paths | Acceptance | Verification |
|---|---|---|---|---|
| RX-01 | Define Rust boundary contract (book delta ingest, OFI/VPIN compute, quote intents out) | `docs/ops/hft_refactor_blueprint.md`, `execution/` | Contract is explicit about inputs, outputs, and failure modes | design review + docs check |
| RX-02 | Create `execution/rust_engine/` prototype crate with ring-buffer event pipeline | `execution/rust_engine/` | Deterministic replay works from captured feed files | replay harness run artifact |
| RX-03 | Add Python bridge stub (PyO3/memoryview-oriented payload transfer) | `execution/rust_bridge.py`, `execution/rust_engine/` | Python can consume snapshot payloads without schema drift | integration smoke in local loop |
| RX-04 | Add parity harness comparing Python vs Rust OFI/VPIN outputs | `tests/`, `scripts/` | Numerical parity within configured tolerance on same tape | `pytest` target for parity harness |
| RX-05 | Add latency benchmark artifact to reports | `reports/hft_refactor/` | p50/p95/p99 end-to-end hot-path latency recorded per build | benchmark report generated |
| RX-06 | Keep fallback path: if Rust module unavailable, Python path remains safe | `bot/jj_live.py`, `execution/` | Runtime degrades gracefully instead of failing closed | `pytest tests/test_jj_live_runtime_profile.py -q` |

### P3 - Microstructure Defense (OFI + VPIN)

| ID | Task | Primary Paths | Acceptance | Verification |
|---|---|---|---|---|
| MD-01 | Normalize OFI stream and publish score in runtime telemetry | `infra/clob_ws.py`, `scripts/write_remote_cycle_status.py` | OFI is visible with freshness metadata | `pytest tests/test_signal_source_audit.py tests/test_remote_cycle_status.py -q` |
| MD-02 | Compute VPIN in volume-time buckets from live trade stream | `bot/`, `signals/`, `src/` | VPIN bucket state survives reconnects and resets safely | `pytest tests/test_runtime_profile.py tests/test_signal_source_audit.py -q` |
| MD-03 | Add toxicity gate actions: pull quotes, widen thresholds, halt lane | `bot/jj_live.py`, `execution_readiness` logic | Gate actions trigger deterministically at configured thresholds | `pytest tests/test_execution_readiness.py tests/test_jj_live_sum_violation.py -q` |
| MD-04 | Track toxicity-veto performance vs ungated baseline in shadow | `reports/`, `scripts/run_btc5_autoresearch_cycle.py` | Side-by-side attribution output exists per cycle | `pytest tests/test_run_btc5_autoresearch_cycle.py -q` |
| MD-05 | Add kill criterion for toxicity misconfiguration | `scripts/write_remote_cycle_status.py` | Over-sensitive or under-sensitive gate generates explicit block reason | `pytest tests/test_remote_cycle_status.py -q` |

### P4 - STE Cross-Asset Signal Lane

| ID | Task | Primary Paths | Acceptance | Verification |
|---|---|---|---|---|
| STE-01 | Build symbolic transform for BTC leader and follower assets | `signals/`, `src/` | Symbolization process deterministic with fixed window params | `pytest` target for symbolization module |
| STE-02 | Implement streaming STE estimator in shadow mode | `signals/`, `bot/` | STE score updated per window with bounded compute time | shadow run artifact under `reports/` |
| STE-03 | Add STE confidence gate into candidate ranking (shadow only) | `scripts/run_signal_source_audit.py`, `scripts/run_btc5_autoresearch_cycle.py` | STE source appears in confirmation coverage output | `pytest tests/test_signal_source_audit.py tests/test_run_btc5_autoresearch_cycle.py -q` |
| STE-04 | Define promotion threshold and false-positive controls | `docs/strategy/`, `reports/` | Lane stays blocked until threshold evidence collected | checklist in cycle status packet |

### P5 - NegRisk / A-6 / B-1 Completion

| ID | Task | Primary Paths | Acceptance | Verification |
|---|---|---|---|---|
| NR-01 | Ensure `negRisk` payload behavior is explicit and audited | `strategies/`, `execution/`, `tests/` | Every NegRisk-capable order path records lane and settlement intent | `pytest tests/test_neg_risk_filters.py tests/test_a6_strategy.py -q` |
| NR-02 | Complete live leg-group telemetry for multi-leg execution | `execution/multileg_executor.py`, `reports/arb_empirical_snapshot.json` | Group-level fill, rollback, and outcome fields are complete | `pytest tests/test_a6_executor_state_machine.py tests/test_constraint_arb_engine.py -q` |
| NR-03 | Finish B-1 gold-set precision audit before any promotion | `strategies/b1_dependency_graph.py`, `reports/` | Precision and false-positive metrics populated from labeled set | `pytest tests/test_execution_readiness.py tests/test_structural_alpha_decision.py -q` |
| NR-04 | Enforce scheduled kill-if-unchanged decision gate | `scripts/write_remote_cycle_status.py`, `reports/structural_alpha_decision.md` | No silent drift past deadline; either promote with evidence or kill lane | `pytest tests/test_structural_alpha_decision.py tests/test_remote_cycle_status.py -q` |

### P6 - Deployment Topology, Compliance, Promotion

| ID | Task | Primary Paths | Acceptance | Verification |
|---|---|---|---|---|
| DT-01 | Measure current end-to-end latency from active runtime region(s) | `scripts/`, `reports/` | Baseline latency artifact exists with p50/p95/p99 and packet loss | benchmark script output |
| DT-02 | Build deployment decision matrix with compliance gate | `docs/ops/`, `deploy/` | Region/proxy/topology options include explicit policy and legal checks | documented sign-off gate |
| DT-03 | Require launch-contract coherence before any live promotion | `scripts/write_remote_cycle_status.py`, `config/runtime_profiles/` | `agent_run_mode`, `execution_mode`, submission flags, and posture cannot conflict | `pytest tests/test_runtime_profile.py tests/test_remote_cycle_status.py -q` |
| RG-01 | Publish rollout ladder for this program | `reports/hft_refactor/latest.json` | Each phase has status and blockers | artifact refresh check |
| RG-02 | Add weekly checkpoint packet for this program | `reports/hft_refactor/` | One machine-readable and one markdown summary per checkpoint | checkpoint files present |
| RG-03 | Add explicit rollback conditions | `scripts/write_remote_cycle_status.py`, `docs/ops/` | Rollback triggers classify data drift, toxicity, and execution anomalies | `pytest tests/test_remote_cycle_status.py -q` |
| RG-04 | Keep finance gate constraints bound to all promotions | `nontrading/finance/`, `reports/finance/` | Promotions do not bypass autonomy caps or reserve floor | `pytest nontrading/tests -q` |

## Promotion Gates For This Program

1. `truth_gate`: wallet reconciliation and launch contract coherent.
2. `economics_gate`: post-only enforcement and rebate-aware EV validated.
3. `toxicity_gate`: OFI/VPIN controls active with measurable benefit.
4. `execution_gate`: hot-path latency and fallback behavior validated.
5. `structural_gate`: A-6/B-1/NegRisk evidence gate passed or explicitly killed.
6. `finance_gate`: all changes remain within finance policy limits.

No gate bypass is allowed through narrative confidence alone.
