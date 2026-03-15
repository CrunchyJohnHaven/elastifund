# COMMAND NODE - Deep Research Handoff

| Metadata | Value |
|---|---|
| Canonical file | `COMMAND_NODE.md` |
| Role | Root **Operator Packet** for deep research and execution handoff |
| Audience | Existing operators and coding/research agents |
| Last updated | 2026-03-12 |
| Primary rule | Wallet truth for capital and realized cash movement; machine artifacts for runtime truth |

Use this when you want one root-level document to hand to Deep Research, ChatGPT, Claude, Cowork, or any coding agent.

## Root Cross-Reference (Canonical)

| Need | Canonical file |
|---|---|
| Start Here | `docs/FORK_AND_RUN.md` |
| Operator packet | `COMMAND_NODE.md` |
| Operator policy | `PROJECT_INSTRUCTIONS.md` |
| Machine workflow guardrails | `AGENTS.md` |
| Contribution rules | `CONTRIBUTING.md` |

---

## 1. Purpose

This is the single root handoff for improving Elastifund's money-making velocity across all three operator surfaces:

- Trading workers: prediction-market research, execution, calibration, and post-trade attribution
- Non-trading workers (JJ-N): revenue operations, service delivery, and customer acquisition
- Finance control plane: subscriptions, treasury, tool spend, experiment budgets, and capital allocation

Current optimization target:

1. Make runtime truth coherent enough that live trading decisions, postmortems, and public claims refer to the same reality.
2. Separate genuine edge from attribution noise by grounding research in the attached Polymarket history export plus fresh live market data.
3. Increase expected 30-day value and expected information gain without widening policy risk.
4. Keep the repo-root handoff packet current enough that a new research session can start cold.

If you only pass one root document into Deep Research, use this one.

---

## 2. Attach This Packet

When handing Elastifund to Deep Research, attach this file plus these artifacts:

- wallet-export summary notes and handoff packet
- `research/high_frequency_substrate_phase2_blueprint_2026-03-11.md`
- `docs/ops/high_frequency_substrate_task_manifest_20260311.md`
- `improvement_velocity.json`
- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `reports/finance/model_budget_plan.json`
- `reports/btc5_autoresearch/latest.json`
- `reports/autoprompting/latest.json`
- `reports/autoprompting/human_queue/latest.json`
- `reports/autoprompting/telegram/latest.json`
- `reports/autoprompting/telegram/escalation_matrix.json`
- `reports/autoprompting/operator_summary/latest.json`
- `reports/signal_source_audit.json`
- `reports/strategy_scale_comparison.json`
- `reports/pipeline_refresh_20260311T092035Z.json`
- `research/edge_backlog_ranked.md`
- `docs/NON_TRADING_STATUS.md`

Off-repo source truth used for this March 11 packet:

- attached wallet export: `<WALLET_EXPORT_PATH>/Polymarket-History-2026-03-11.csv`

Do not commit the raw wallet export. Summaries derived from it belong in the root handoff docs, not the repo history.

Autoprompt continuity note for Instance 6:

- `scripts/run_autoprompt_human_queue_cycle.py` writes low-noise escalation and queue artifacts under `reports/autoprompting/`.
- Telegram remains action-required only; informational updates stay in artifacts.

---

## 3. Truth Precedence

Use this precedence order when facts conflict:

1. **Live wallet and attached wallet export** for capital, positions, and realized cash movement.
2. **`reports/runtime_truth_latest.json` and `reports/public_runtime_snapshot.json`** for launch posture, runtime mode, wallet reconciliation status, and BTC5 probe truth.
3. **Fresh live market pulls** for current opportunity structure:
   - `reports/pipeline_refresh_20260311T092035Z.json`
   - direct Gamma active-market pulls performed on March 11, 2026
4. **`improvement_velocity.json`** for the sanitized public metric contract.
5. **`jj_state.json`** only as a local runtime seed. Do not use it as wallet or P&L truth.

---

## 4. March 11 Machine Truth

### 4A. Attached Polymarket History Export

The attached export covers **2026-03-07 07:03:53 ET** through **2026-03-11 04:54:19 ET**.

| Metric | Value |
|---|---|
| Rows | **479** |
| Distinct markets | **193** |
| Buy notional | **1277.301646 USDC** |
| Redeem cash flow | **1327.617592 USDC** |
| Maker rebates | **1.240900 USDC** |
| Net trading cash flow excluding deposits | **+51.556846 USDC** |
| Buy-side mix | **245** `DOWN/NO` buys for **1099.821865 USDC** vs **39** `UP/YES` buys for **177.479781 USDC** |
| BTC contribution | **445** rows, **+76.867593 USDC** net |
| ETH contribution | **16** rows, **+33.974196 USDC** net |
| SOL contribution | **3** rows, **-12.361643 USDC** net |

Overnight ET window for **Wednesday, March 11, 2026**:

| Metric | Value |
|---|---|
| Rows after 12:00 AM ET | **98** |
| Buy notional | **475.935792 USDC** |
| Redeem cash flow | **476.263141 USDC** |
| Net cash flow | **+0.327349 USDC** |
| Zero-value redeem rows | **20** |
| Closed-like markets | **17** markets, **+243.289167 USDC** net |
| Openish / unresolved markets | **20** markets, **-242.961818 USDC** net |

Highest-net overnight winners from the export:

- `Bitcoin Up or Down - March 11, 3:10AM-3:15AM ET`: **+25.1328 USDC**
- `Bitcoin Up or Down - March 11, 3:15AM-3:20AM ET`: **+24.15 USDC**
- `Ethereum Up or Down - March 11, 2:55AM-3:00AM ET`: **+15.930596 USDC**

Largest unresolved overnight exposures:

- `Bitcoin Up or Down - March 11, 2:50AM-2:55AM ET`: **-24.15 USDC**
- `Solana Up or Down - March 11, 2:20AM-2:25AM ET`: **-12.361643 USDC**
- `Bitcoin Up or Down - March 11, 12:40AM-12:45AM ET`: **-12.079 USDC**

Interpretation:

- The export does **not** support a simple "overnight blowup" narrative.
- Realized winners exist, and they are concentrated in BTC and ETH short-duration markets.
- The real problem is attribution and unresolved inventory: closed-like markets were net positive, but that gain was offset by openish exposures plus export quirks like zero-value redeems.

### 4B. Current Runtime / Public Truth

Latest checked-in runtime/public contract generated at **2026-03-11T09:22:17Z**:

| Area | Current truth | Why it matters |
|---|---|---|
| Launch posture | **blocked** | The system is not in a clean promote-ready live posture. |
| Effective runtime profile | **`shadow_fast_flow`** | Effective mode does not match the intended live marketing story. |
| Execution mode | **`shadow`** | Runtime is not in clean live-submit mode. |
| Wallet reconciliation status | **reconciled** | Local and remote now both show **50 closed** and **9 open** positions. |
| Current wallet value | **$490.3064** total, **$363.2486** free collateral | This is the current capital truth surface. |
| Capital accounting delta | **-157.3178 USD** | Position counts are fixed, but capital accounting is still incoherent. |
| BTC5 live sleeve | **175** live-filled rows, **-$24.9467** live-filled P&L | The public BTC5 sleeve is no longer cleanly positive. |
| Recent BTC5 realized window | trailing **12** live fills: **-$2.5441** | Short-window realized performance is currently negative. |
| Strongest BTC5 structure | **DOWN +$10.4017** overall; **0.50 bucket +$39.1564** | Directional structure still exists, but it is narrower and noisier than earlier docs implied. |
| Selected forecast posture | **shadow_only / high confidence** | Forecast engine is not promoting capital expansion. |
| Verification summary | **1641 passed, 5 warnings in 37.10s; 25 passed, 1 warning in 4.56s** | The worktree is test-green even though launch truth is not. |

The one-next-cycle instruction from runtime truth is explicit:

> Repair launch-contract mismatches in service/mode/posture/order-submission fields, rerun `python3 scripts/write_remote_cycle_status.py`, then retry when `launch_posture=clear`.

Interpretation:

- The old March 9 bottleneck was "local ledger vs wallet count drift."
- The March 11 bottleneck is "launch-contract mismatch plus capital attribution drift."
- Strategy research that ignores the launch contract will misdiagnose the failure mode.

### 4C. Fresh Live Market Data

Fresh broad-universe pull from **2026-03-11T09:59:42Z** (`reports/pipeline_refresh_20260311T095942Z.json`):

| Metric | Value |
|---|---|
| Open events pulled | **500** |
| Open markets pulled | **7014** |
| Broad category mix | Politics **2860**, Sports **3048**, Economic **390**, Crypto **111**, Weather **10**, Other **595** |
| Fresh broad recommendation | **REJECT ALL** |

Fresh repaired fast-market registry / direct Gamma multi-plan pull for crypto markets resolving within 24 hours:

| Metric | Count |
|---|---|
| Eligible fast crypto markets | **650** |
| Total discovered fast-crypto candidates | **790** |
| BTC rows | **175** |
| ETH rows | **171** |
| SOL rows | **152** |
| XRP rows | **152** |
| Candle rows | **547** |
| Threshold rows | **30** |
| Range rows | **20** |

Highest-volume active threshold/range markets from the March 11 pull:

- `Will the price of Bitcoin be above $64,000 on March 11?`  
  Volume **585,413.929**, liquidity **37,049.214**, price **0.9975 / 0.0025**
- `Will the price of Ethereum be between $2,200 and $2,300 on March 11?`  
  Volume **731,662.263**, liquidity **24,793.000**, price **0.006 / 0.994**
- `Will the price of Bitcoin be above $68,000 on March 11?`  
  Volume **265,261.758**, liquidity **34,349.088**, price **0.915 / 0.085**
- `Will the price of Bitcoin be between $68,000 and $70,000 on March 11?`  
  Volume **124,164.617**, liquidity **29,374.292**, price **0.535 / 0.465**

Live short-duration candle examples from the same pull:

- `Bitcoin Up or Down - March 11, 1:55PM-2:00PM ET`  
  Liquidity **23,527.632**, price **0.505 / 0.495**
- `Solana Up or Down - March 11, 12:30PM-12:45PM ET`  
  Liquidity **12,920.514**, price **0.5 / 0.5**
- `XRP Up or Down - March 11, 7PM ET`  
  Liquidity **13,218.868**, price **0.5 / 0.5**

Registry status after repair:

- `python3 scripts/run_pm_fast_market_registry.py --no-quotes --json-only` now produces `eligible_count=650`.
- A separate direct Gamma validation pull matched the repaired registry exactly: `650` eligible rows, with BTC/ETH/SOL/XRP all present and threshold/range lanes restored.
- `improvement_velocity.json` now exposes `registry_health` so the next cycle can flag "Gamma reachable but registry empty" as a broken state instead of silently accepting it.

---

## 5. What Changed Since The Old Narrative

These are the material corrections Deep Research should internalize:

1. **Position-count drift is no longer the primary problem.** Counts now reconcile at **50 closed / 9 open**.
2. **The public BTC5 sleeve is no longer the clean +$85 proof surface.** The latest public contract shows **175 live-filled rows and -$24.95 P&L**.
3. **The attached wallet export is still positive at the transaction-cash-flow level.** That means the live story is "mixed realized wins plus unresolved/open exposures," not "everything is losing."
4. **The launch contract is broken.** Runtime says `agent_run_mode=live`, `execution_mode=shadow`, `allow_order_submission=false`, and `launch_posture=blocked`.
5. **Market discovery tooling is partially stale.** Broad market pulls work; the fast-market registry does not.

Conclusion:

The highest-value research problem is no longer "invent another strategy first." It is "make launch truth, execution truth, and wallet truth line up well enough to know which existing lane is actually working."

---

## 6. Ranked Research Priorities

1. **Repair launch-contract truth.**  
   Make `agent_run_mode`, `execution_mode`, `allow_order_submission`, service target, and public posture agree.

2. **Reconcile wallet-export cash flow against BTC5 probe attribution.**  
   Explain why the March 7-11 export is **+51.56 USDC** while the checked-in BTC5 public sleeve is **-24.95 USD**.

3. **Audit the current BTC5 directional structure.**  
   DOWN still leads overall, but the latest negative drag is concentrated in the **0.49** bucket. Verify whether the live edge survives after excluding that bucket or respecifying quote limits.

4. **Compare threshold/range crypto markets against 5-minute candles.**  
   The active live universe now contains more than candles. Research should test whether daily threshold/range contracts offer better fill quality or cleaner attribution than 5-minute candle markets.

5. **Fix the fast-market registry.**  
   The current registry runner failing with `eligible_count=0` is itself a research blocker because it obscures the live opportunity set.

6. **Kill or park structural-alpha lanes on schedule.**  
   A-6 and B-1 remain blocked and should not keep consuming attention without fresh evidence before **March 14, 2026**.

7. **Keep JJ-N and finance visible but secondary.**  
   They remain part of the system objective, but the immediate trading bottleneck is truth plumbing, not non-trading implementation.

---

## 7. Relevant Implementation Surfaces

Trading and truth surfaces:

- `bot/jj_live.py`
- `bot/btc_5min_maker.py`
- `bot/wallet_reconciliation.py`
- `scripts/write_remote_cycle_status.py`
- `scripts/render_public_metrics.py`
- `scripts/run_pm_fast_market_registry.py`
- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/pipeline_refresh_20260311T092035Z.json`

Research and ranking surfaces:

- wallet-export summary and handoff packet
- `research/high_frequency_substrate_phase2_blueprint_2026-03-11.md`
- `docs/ops/high_frequency_substrate_task_manifest_20260311.md`
- `improvement_velocity.json`
- `research/edge_backlog_ranked.md`
- `reports/btc5_autoresearch/latest.json`
- `reports/signal_source_audit.json`
- `reports/strategy_scale_comparison.json`

Non-trading and finance surfaces:

- `nontrading/main.py`
- `nontrading/pipeline.py`
- `docs/NON_TRADING_STATUS.md`
- `docs/ops/finance_control_plane.md`

---

## 8. Prompt Shape To Use

Use this prompt shape for the next Deep Research pass:

> Use `COMMAND_NODE.md`, `research/high_frequency_substrate_phase2_blueprint_2026-03-11.md`, and `docs/ops/high_frequency_substrate_task_manifest_20260311.md` as the root handoff. Treat the attached Polymarket wallet export summary as capital and realized-cash-flow truth, and treat `reports/runtime_truth_latest.json`, `reports/public_runtime_snapshot.json`, and the March 11 live market pull as canonical runtime and market-state context. Diagnose the smallest set of changes that would make runtime truth, wallet truth, and strategy attribution coherent enough to improve the trading system with confidence. Give explicit rollout gates, evidence requirements, and file-level implementation targets.

---

## 9. Short Bottom Line

Elastifund did not fail because "there is no live data" or because "the wallet only lost money overnight."

It failed at the truth layer:

- the wallet export says there is real realized cash movement and it is net positive over March 7-11,
- the BTC5 public sleeve is currently negative,
- position counts are reconciled again,
- capital attribution is still not,
- and the runtime is still blocked by a live-vs-shadow launch mismatch.

That is the system-improvement problem to solve next.
