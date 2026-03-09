# COMMAND NODE - Deep Research Handoff

**Version:** 3.0.0  
**Updated:** 2026-03-09  
**Canonical filename:** `COMMAND_NODE.md`  
**Use this when:** you want one root-level document to hand to Deep Research, ChatGPT, Claude, Cowork, or any coding agent.  
**Primary rule:** if prose and machine artifacts disagree, machine artifacts win.

---

## 1. Purpose

This is the single root handoff for improving Elastifund's money-making velocity across both worker families:

- Trading workers: prediction-market research, execution, and calibration.
- Non-trading workers (JJ-N): revenue operations, service delivery, and customer acquisition.

Current optimization target:

1. Reach the first repeatable dollar faster.
2. Increase information gain per cycle.
3. Remove system-truth drift so strategy decisions are based on the same reality everywhere.

If you only pass one root document into Deep Research, use this one.

---

## 2. How To Use This Packet

When handing Elastifund to Deep Research, attach this file plus these machine-truth artifacts:

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `reports/state_improvement_latest.json`
- `reports/arb_empirical_snapshot.json`
- `research/edge_backlog_ranked.md`
- `docs/NON_TRADING_STATUS.md`

Prompt shape to use:

> Use `COMMAND_NODE.md` as the root handoff. Treat the attached JSON artifacts as canonical machine truth. Design the shortest path to higher money-making velocity across both trading and non-trading, with explicit rollout gates, metric contracts, and file-level implementation guidance.

---

## 3. System Objective

Elastifund is a self-improving operating system for real economic work.

- Trading lane: find, validate, and execute prediction-market edge under policy.
- Non-trading lane: build a narrow, measurable revenue loop that can reach cash flow before broad automation.
- Shared substrate: memory, telemetry, evaluation, and operator-readable evidence.

Primary operating principle:

`research -> implement -> test -> record -> publish -> repeat`

Mission constraint:

20% of net trading profits are reserved for veteran suicide prevention.

---

## 4. Canonical Machine Truth (March 9, 2026)

As of `reports/runtime_truth_latest.json` generated at `2026-03-09T16:19:45.682469+00:00`:

| Area | Current truth | Why it matters |
|---|---|---|
| Runtime selector | `maker_velocity_all_in` | This is the selected runtime profile, but the effective runtime differs from the checked-in profile defaults. |
| Effective mode | `agent_run_mode=shadow`, `execution_mode=shadow`, `paper_trading=false`, `allow_order_submission=true`, `order_submit_enabled=false` | The bot is not in plain paper mode, but it also is not in a clean launch-ready state. |
| Service posture | `jj-live.service` is now `stopped`; the dedicated BTC 5-minute maker is the only intended live sleeve | Service-state drift has been resolved, but broader launch posture remains blocked. |
| Runtime accounting | `565` cycles, `5` trade-db trades, `4` local open positions, `0` local closed trades, `25.00` executed notional total | The local runtime ledger still looks thin and incomplete. |
| Remote Polymarket wallet | `28` open positions, `9` closed positions, and wallet-versus-ledger drift still unresolved | Wallet truth is materially ahead of local accounting and must be reconciled before making claims. |
| BTC 5-minute maker evidence | `51` total rows, `32` `live_filled`, positive cumulative filled outcomes, latest guardrail recommendation `max_abs_delta=0.00015`, `UP max=0.51`, `DOWN max=0.51` | There is real short-horizon trading evidence in the remote SQLite surface, and it now informs bounded guardrails. |
| Candidate generation now | `0` Polymarket, `0` Kalshi, `0` total | Current edge reachability is still zero in the latest improvement report. |
| Latest pipeline verdict | `REJECT ALL` | The older scan says nothing is tradeable, which conflicts with later BTC maker evidence. |
| Structural alpha A-6 | `blocked`; `53` qualified live-surface events, `0` executable constructions below `0.95` | No promotion. The lane still lacks executable evidence. |
| Structural alpha B-1 | `blocked`; `0` deterministic template pairs in first `1,000` allowed markets | No promotion. Density remains too low. |
| Current system ARR | `0%` realized | This is the public-safe current ARR from `improvement_velocity.json`; target and theoretical references stay separate from realized performance. |
| Root verification artifact | `1140 passed in 25.88s; 25 passed in 4.47s` | The root suite is green in the latest artifact set. |
| JJ-N repo truth | `nontrading/main.py` builds and runs `RevenuePipeline`; `make test-nontrading` is green at `61`; repo-root JJ-N tests are green at `49` | The non-trading lane is implemented and safety-gated, but not revenue-live. |
| First non-trading wedge | Website Growth Audit exists in code, priced at `$500-$2500`, `5` delivery days, fulfillment type `hybrid` | This is the best current path to first non-trading dollars. |

Strategy catalog truth from `research/edge_backlog_ranked.md`:

- `7` deployed or ready
- `6` building
- `2` building structural-alpha lanes
- `1` re-evaluating
- `10` rejected
- `8` pre-rejected
- `97` research-pipeline items
- `131` total tracked

---

## 5. The Real Problem: Runtime Truth Drift

Deep Research should treat the following as first-class system problems, not footnotes:

1. Local-ledger vs wallet drift
   Local runtime accounting says `4` open positions and `0` local closed trades. The remote wallet surface says `28` open positions and `9` closed positions.

2. Profile-vs-effective drift
   The checked-in `config/runtime_profiles/maker_velocity_all_in.json` says:
   - fast crypto only
   - `max_resolution_hours=1.0`
   - YES and NO thresholds `0.01 / 0.01`
   - `max_position_usd=50`

   The effective runtime captured in `reports/runtime_truth_latest.json` says:
   - `max_resolution_hours=24.0`
   - YES and NO thresholds `0.05 / 0.02`
   - `max_position_usd` is effectively set to the full available cap in the checked-in runtime truth

3. Signal-lane drift
   The selected maker-velocity posture says fast-flow only with LLM disabled, but `jj_state.json` still shows five LLM-dominant trades on non-fast markets.

4. Scan-vs-execution drift
   The latest checked pipeline verdict is `REJECT ALL`, while the remote BTC 5-minute maker database shows `32` live-filled rows and positive cumulative filled outcomes.

Conclusion:

The current bottleneck is not only "find better strategies." It is also "make one runtime truth coherent enough that strategy evidence can be trusted."

---

## 6. What Is Actually Implemented

### Trading lane

| Path | Current role |
|---|---|
| `bot/jj_live.py` | Main live loop, signal routing, sizing, risk gates, and order flow. |
| `bot/edge_scan_report.py` | Candidate scan, restart-readiness reporting, and structural-lane summary. |
| `bot/wallet_flow_detector.py` | Wallet scoring, bootstrap readiness, and fast-flow signal generation. |
| `bot/lmsr_engine.py` | Bayesian/LMSR microstructure signal generation for fast markets. |
| `bot/cross_platform_arb.py` | Polymarket/Kalshi title matching and arb opportunity detection. |
| `signals/sum_violation/guaranteed_dollar.py` | A-6 guaranteed-dollar ranking for neg-risk events. |
| `bot/b1_template_engine.py` | Narrow deterministic template matching for B-1 dependency families. |
| `scripts/write_remote_cycle_status.py` | Canonical remote-status and drift-report generator. |
| `config/runtime_profiles/maker_velocity_all_in.json` | Selected runtime profile defaults; do not confuse with effective runtime truth. |
| `research/edge_backlog_ranked.md` | Canonical strategy inventory and status counts. |

### What appears active in practice

- Remote evidence suggests a maker-velocity BTC 5-minute lane has real filled trades.
- The selected profile keeps `wallet_flow` and `lmsr` on.
- The checked-in selected profile keeps `llm`, `cross_platform_arb`, `a6`, and `b1` off.
- Local runtime state still contains LLM-sourced positions that do not match the selected fast-flow thesis.

### Non-trading lane

| Path | Current role |
|---|---|
| `nontrading/main.py` | CLI entrypoint; builds runtime and runs `RevenuePipeline`. |
| `nontrading/pipeline.py` | The five-engine JJ-N loop: Account Intelligence -> Outreach -> Interaction -> Proposal -> Learning. |
| `nontrading/offers/website_growth_audit.py` | The first concrete service offer and pricing envelope. |
| `nontrading/approval.py` | Approval gating for safe outbound behavior. |
| `nontrading/compliance.py` | Compliance checks and sending-domain constraints. |
| `docs/NON_TRADING_STATUS.md` | Current repo-truth status for JJ-N. |
| `nontrading/digital_products/` | Separate deterministic niche-discovery lane. |

### What is revenue-ready vs not revenue-live

Implemented now:

- Runnable `RevenuePipeline`
- Safety-gated send path
- Website Growth Audit offer
- CRM/store/telemetry foundation
- Deterministic smoke path and green JJ-N tests

Still blocking revenue launch:

- Verified sending domain and DNS auth
- Curated leads
- Explicit approval for live sends
- Paid fulfillment/reporting loop
- Recurring KPI loop for qualified leads, replies, calls, proposals, and collected revenue

---

## 7. What Deep Research Should Optimize For

### Trading

1. Unify runtime truth
   Design the shortest path to one authoritative surface for positions, closed trades, realized PnL, and active mode.

2. Decide the real trading thesis
   Determine whether the canonical near-term lane is:
   - sub-1h crypto maker velocity
   - <=24h mixed-market maker velocity
   - or a split system with separate evidence contracts

3. Explain candidate scarcity
   Why do current candidate counts stay at zero even while filled BTC maker trades exist? Is the scan stale, mis-scoped, or measuring the wrong market universe?

4. Upgrade promotion rules
   Specify promotion, demotion, and kill criteria for:
   - wallet flow
   - LMSR
   - cross-platform arb
   - A-6
   - B-1

5. Turn filled-trade evidence into decision-quality evidence
   Recommend the minimum closed-trade and fill-quality contract needed before changing capital, thresholds, or automation level.

6. Clarify Kalshi's role
   Decide whether Kalshi should be:
   - a pure hedge/arb venue
   - a separate candidate source
   - or deprioritized until Polymarket truth is stable

### Non-trading

1. Reach first cash fast
   Use the Website Growth Audit as the default wedge unless research finds a clearly better lane on time-to-first-dollar and automation fraction.

2. Build a measurable go-to-market loop
   Define the best outbound channel, lead source, qualification rubric, pricing motion, and follow-up sequence.

3. Productize the recurring monitor
   Turn the one-off audit into a recurring service with clean deliverables and retention logic.

4. Keep risk low
   Maintain compliance-first approvals and avoid expanding autonomy until the funnel is instrumented.

5. Share evaluation logic
   Specify a common metric contract so trading and non-trading can be ranked by improvement velocity and dollars learned per calendar day.

---

## 8. Required Output From Deep Research

Deep Research should return:

1. A ranked backlog (`P0`, `P1`, `P2`) mapped to exact repo paths.
2. A 7-day execution plan with daily checkpoints.
3. A metric contract with formulas, artifact names, and source-of-truth file paths.
4. An experiment matrix for wallet flow, LMSR, BTC maker fills, cross-platform arb, and JJ-N outreach.
5. Promotion, demotion, and kill rules for each active lane.
6. A runtime-truth reconciliation plan before any wider live rollout.
7. A first-dollar plan for JJ-N using the Website Growth Audit unless a better wedge clearly wins on evidence.
8. Guardrails and rollback criteria for any recommendation that could spend real money or send real outbound messages.

Preferred framing:

- maximize expected dollars learned per day
- maximize time-to-first-repeatable-dollar
- minimize truth drift
- minimize irreversible risk

---

## 9. Constraints

- Do not invent new runtime APIs when existing JSON artifacts already carry state.
- Treat `bot/`, `execution/`, `strategies/`, `signals/`, and `infra/` as live-trading-sensitive paths.
- Treat A-6 and B-1 as blocked until their empirical gates are actually cleared.
- Distinguish clearly between:
  - local trade-db truth
  - remote wallet truth
  - profile defaults
  - effective runtime truth
- Any recommendation that changes real-money behavior must include guardrails, downgrade logic, and verification steps.
- Prefer implementation plans that end in scripts, tests, and machine-readable artifacts, not only prose.

---

## 10. Recommended Immediate Priorities

If no other instruction is given, this is the order that maximizes money-making improvement velocity:

1. Reconcile runtime truth drift.
2. Prove or kill the active BTC maker-velocity lane with a clean closed-trade and fill-quality contract.
3. Decide the canonical market universe and thresholds.
4. Build the minimum JJ-N live-launch package for Website Growth Audit.
5. Keep A-6 and B-1 blocked unless the evidence changes materially.

---

## 11. Source Index

Use these files as the canonical supporting evidence:

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/runtime_mode_reconciliation_20260309T154637Z.md`
- `reports/root_test_status.json`
- `reports/state_improvement_latest.json`
- `reports/arb_empirical_snapshot.json`
- `jj_state.json`
- `config/runtime_profiles/maker_velocity_all_in.json`
- `research/edge_backlog_ranked.md`
- `docs/NON_TRADING_STATUS.md`
- `nontrading/offers/website_growth_audit.py`

For repo navigation:

- `README.md`
- `AGENTS.md`
- `docs/REPO_MAP.md`
- `PROJECT_INSTRUCTIONS.md`

---

## 12. Bottom Line

The best single root document to hand to Deep Research is `COMMAND_NODE.md`.

The highest-value research target is not just "find more edges." It is:

1. make runtime truth coherent,
2. turn the active maker-velocity evidence into trustworthy promotion criteria,
3. launch one narrow non-trading revenue loop that can reach cash quickly and teach the system something useful.
