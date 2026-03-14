# COMMAND NODE - Deep Research Handoff

**Version:** 3.3.0
**Updated:** 2026-03-14
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

## 4. Canonical Machine Truth (March 14, 2026)

> **WARNING — ARTIFACT TRUST POLICY (added 2026-03-09):**
> `reports/runtime_truth_latest.json` and local ledger data have proven unreliable. They reported "0 closed trades" and "0% realized ARR" while the live Polymarket wallet showed active positions being filled and resolved with real P&L. **Always verify capital, position, and P&L claims against the live Polymarket portfolio and Kalshi account before citing them.** If wallet data contradicts local artifacts, the wallet wins.

### Live Wallet Truth (verified 2026-03-13 from remote_cycle_status.json)

| Area | Current truth | Why it matters |
|---|---|---|
| Polymarket portfolio | $390.90 total, $373.32 free collateral, $17.58 reserved (2 live NO-side maker orders) | Wallet grew from $333.18 (Mar 9) to $390.90 (Mar 13). |
| Kalshi | $100 USD | Unchanged. |
| Total capital | ~$490.90 | Polymarket $390.90 + Kalshi $100. |
| Capital accounting delta | +$140.90 | Local ledger tracks $250 base; wallet shows $390.90. Known drift, not a loss. |
| Deployment confidence | 0.6024, label "medium" | Raw formula yields 0.6024; stage_readiness_score is 0.15 due to 6 active blockers. |
| BTC5 stage | Stage 0, 6 blockers active | wallet_export_stale, trailing_12_not_positive, insufficient_fills, forecast_not_promote, reconciliation_not_ready, confirmation_insufficient |
| Deploy recommendation | shadow_only | Autoresearch 25.2h stale; will not recommend "promote" until fresh cycle with fills. |

### Local Artifact Truth (KNOWN STALE — use with caution)

| Area | Local artifact says | Why it's wrong |
|---|---|---|
| Runtime accounting | `565` cycles, `5` trade-db trades, `4` open, `0` closed | Wallet shows 28+ open, 9+ closed historically. Local ledger massively understates activity. |
| Pipeline verdict | `REJECT ALL` | Wallet is actively trading and filling orders. The scan is stale or mis-scoped. |
| System ARR | `0%` realized | **FALSE.** System has real P&L from live fills and resolutions. |
| Effective mode | `agent_run_mode=shadow`, `order_submit_enabled=false` | Contradicted by real fills in the wallet. Orders ARE being submitted. |

### Unchanged Status

| Area | Current truth | Why it matters |
|---|---|---|
| Structural alpha A-6 | **KILLED** 2026-03-13; `0` executable constructions below `0.95` after 5-day watch | Zero density in 563 neg-risk events. Engineering capacity reallocated to BTC5 optimization. |
| Structural alpha B-1 | **KILLED** 2026-03-13; `0` deterministic template pairs after 5-day watch | Zero density in 1,000+ markets. Engineering capacity reallocated to Kalshi integration. |
| BTC 5-minute maker | `542` total rows, `0` current live fills; historical closed: +$131.52 on 128 contracts (75W/53L, PF 1.49) | Guardrail fixes deployed 2026-03-14: delta 0.0040, UP live, min_buy 0.42. Awaiting US-hours fill validation. |
| Root verification | 50 tests failing in `test_btc_5min_maker_process_window_core.py`; 1961 passing | Guardrail regression; all other surfaces green. |
| JJ-N repo truth | `RevenuePipeline` builds; tests green at `61` + `49` | Implemented but not revenue-live. |
| First non-trading wedge | Website Growth Audit, $500-$2500, 5-day delivery | Best path to first non-trading dollars. |

Strategy catalog truth from `research/edge_backlog_ranked.md`:

- `7` deployed or ready
- `6` building
- `0` structural-alpha lanes (A-6/B-1 killed 2026-03-13, moved to rejected)
- `1` re-evaluating
- `12` rejected (includes A-6 and B-1 killed 2026-03-13)
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

5. **Wallet polling loop (NEW — 2026-03-14)**
   `bot/wallet_poller.py` now runs as a continuous daemon (`deploy/wallet-poller.service`) that polls the Polymarket wallet every 60 seconds, auto-patches the local trade-db via `PolymarketWalletReconciler`, and writes drift snapshots to `data/wallet_snapshots/`. This closes the primary ledger-drift gap. Wallet remains authoritative; the poller enforces that.

Conclusion:

The current bottleneck is not only "find better strategies." It is also "make one runtime truth coherent enough that strategy evidence can be trusted." The wallet poller addresses drift problem #1 above by keeping the local ledger continuously synchronized with the live wallet.

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
   - ~~A-6~~ (KILLED 2026-03-13)
   - ~~B-1~~ (KILLED 2026-03-13)

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
- A-6 and B-1 are KILLED as of 2026-03-13. Do not invest further engineering effort in either lane.
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

1. **Validate BTC5 fills after guardrail fix.** Three blockers fixed 2026-03-14 (delta, UP direction, min_buy_price). Confirm fills during US trading hours. If still zero fills by 20:00 UTC, investigate bad_book and toxic_order_flow thresholds.
2. **Fix the 50 test failures in `test_btc_5min_maker_process_window_core.py`.** Guardrail changes broke the test expectations. Repair tests to match new live config, not the other way around.
3. **Reconcile runtime truth drift.** Local ledger still massively understates activity. Build or run wallet reconciliation to close the gap.
4. **Scale BTC5 to $10/trade once fills confirmed.** Already configured in capital_stage.env. Need positive trailing P&L from live fills first.
5. **Build the minimum JJ-N live-launch package for Website Growth Audit.** Best path to first non-trading dollar. Blocking: verified sending domain, curated leads, explicit approval for live sends.

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
