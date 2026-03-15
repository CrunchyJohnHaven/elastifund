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

Canonical runtime contract (checked into git):

- `config/remote_cycle_status.json`
- `improvement_velocity.json`
- `FAST_TRADE_EDGE_ANALYSIS.md`
- `research/edge_backlog_ranked.md`
- `docs/NON_TRADING_STATUS.md`

Runtime-local artifacts (generated on operator machines; may be absent in a clone):

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `reports/state_improvement_latest.json`
- `reports/arb_empirical_snapshot.json`

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

> **RECONCILIATION COMPLETED 2026-03-14 15:26 UTC.**
> Root cause of all prior drift identified and fixed: `.env` had `POLY_SAFE_ADDRESS` set to EOA signer (`0x28C5AedA...`), but Polymarket data API keys positions by proxy wallet (`0xb2fef31c...`). Every prior reconciliation queried the wrong address and got zero results. New `POLY_DATA_API_ADDRESS` env var added; reconciliation now returns correct data. See `reports/reconciliation_20260314.md` for full details.

### Live Wallet Truth (verified 2026-03-14 15:25 UTC via Polymarket data API)

| Area | Current truth | Source |
|---|---|---|
| Polymarket wallet value | $458.13 total | data-api.polymarket.com/positions (proxy wallet), March 14 |
| Free collateral | $373.32 | CLOB balance query |
| Reserved (pending orders) | $84.81 | Wallet total minus free collateral |
| Open positions | 5 positions, $63.10 cost, $66.41 mark-to-market | data API (proxy wallet) |
| Closed positions | 50 total (47 BTC, 3 ETH) | data API (proxy wallet) |
| Realized net P&L | **+$207.31** (wallet $458.13 - deposit $247.51 - unrealized $3.31) | Wallet economics |
| Unrealized P&L (open) | +$3.31 | Mark-to-market on 5 open positions |
| Kalshi | $100 USD | Unchanged |
| Total capital | ~$558.13 | Polymarket $458.13 + Kalshi $100 |

### BTC Sleeve Performance (47 closed trades, all March 11)

| Metric | Value |
|---|---|
| Closed trades | 47 (39 DOWN, 8 UP) |
| Win rate | 100% (all positions resolved with positive cashflow) |
| Gross BTC cashflow | $786.33 |
| DOWN direction cashflow | $663.99 (39 trades) |
| UP direction cashflow | $122.35 (8 trades) |
| Trading window | March 11, ~3:10 AM - 8:05 AM ET (single session) |

### Open Position Book (5 positions)

| Outcome | Market | Cost | Mark | Unrealized |
|---|---|---|---|---|
| Yes | Weinstein sentenced to no prison time? | $28.04 | $26.47 | -$1.57 |
| No | Akhannouch out as Morocco PM by Dec 31 | $5.12 | $7.95 | +$2.84 |
| No | Wizards worst NBA record? | $20.00 | $22.12 | +$2.12 |
| Yes | US strikes Yemen by Mar 31 | $4.95 | $5.19 | +$0.25 |
| Yes | Russia no key rate change (April) | $5.00 | $4.67 | -$0.33 |

### Local Artifact Status (post-reconciliation)

| Area | Status | Notes |
|---|---|---|
| Reconciliation script | Fixed | Now queries proxy wallet via `POLY_DATA_API_ADDRESS` |
| Runtime truth JSON | Updated | `reports/runtime_truth_latest.json` patched with wallet data |
| Local jj_trades.db | Still empty | 0 rows; trades went through BTC5 maker path, not jj_live |
| BTC5 local DB | 302 rows, ALL skips, 0 live fills | skip_delta_too_large: 164 (54%), skip_shadow_only: 56 (19%), skip_toxic: 42 (14%). Last entry: 2026-03-13 18:24 UTC. |
| BTC5 VPS DB | 553+ rows, signature fix deployed | DISPATCH_100: funder address fixed. Delta cap 0.0040, UP live, lt049 skip disabled. VPS service running but local sync stale. |
| Pipeline verdict | REJECT ALL (stale) | 5+ days old; decoupled from actual fills |
| Wallet export CSV | 48h+ stale | Last: 2026-03-13 (data through 2026-03-12); partially useful |

### Unchanged Status

| Area | Current truth | Why it matters |
|---|---|---|
| Structural alpha A-6 | **KILLED** 2026-03-13; `0` executable constructions below `0.95` after 5-day watch | Zero density in 563 neg-risk events. Engineering capacity reallocated to BTC5 optimization. |
| Structural alpha B-1 | **KILLED** 2026-03-13; `0` deterministic template pairs after 5-day watch | Zero density in 1,000+ markets. Engineering capacity reallocated to Kalshi integration. |
| BTC 5-minute maker (VPS) | `553+` total rows, signature fix deployed 2026-03-14 16:05 UTC | DISPATCH_100: 4th blocker found (invalid signature from wrong funder address). All 4 blockers now fixed. Remaining skips are legitimate market conditions. Fills expected during active BTC trading hours. |
| JJ-N repo truth | `RevenuePipeline` builds; tests green | Implemented but not revenue-live. |
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

## 5. Runtime Truth Status (Post-Reconciliation)

### Root cause identified and fixed (2026-03-14)

The entire runtime truth drift was caused by a single configuration bug: `.env` set `POLY_SAFE_ADDRESS` and `POLYMARKET_FUNDER` to the EOA signer address (`0x28C5AedA...`), but the Polymarket data API returns positions keyed by the proxy wallet address (`0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5`). Every reconciliation attempt queried the wrong address and returned zero results, making the system believe the wallet was empty while it held $390.90 and had 55 historical positions.

**Fix:** New `POLY_DATA_API_ADDRESS` env var added to both local and VPS `.env`. `default_user_address()` in `bot/position_merger.py` checks this first. Reconciliation script `_load_env_defaults()` also updated.

### Remaining drift items

1. **Local jj_trades.db still empty** — Trades were placed through the BTC5 maker path (`data/btc_5min_maker.db`), not `jj_live.py`. The main trade ledger has 0 rows. Structural issue: two separate code paths write to two separate databases.

2. **Profile-vs-effective drift** — The checked-in `maker_velocity_live` profile and the effective runtime may still diverge. Verify by comparing profile JSON against VPS runtime state.

3. **Pipeline verdict stale** — `FAST_TRADE_EDGE_ANALYSIS.md` says REJECT ALL (5+ days old). Pipeline and execution layer are fully decoupled.

4. **Wallet export CSV stale** — Last export 2026-03-12 (62+ hours). Blocks stage gate progression.

5. **Wallet polling loop** — `bot/wallet_poller.py` exists as a daemon design. If running, keeps local ledger in sync. VPS status needs verification.

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

1. **MONITOR: Confirm BTC5 fills during active trading hours.** DISPATCH_100 deployed 2026-03-14 16:05 UTC. All 4 blockers fixed (signature, delta, UP shadow, lt049 skip). Zero `invalid signature` errors since fix. Remaining skips are legitimate market conditions. Check `journalctl -u btc-5min-maker --since "1 hour ago" | grep order_placed` after 18:00 UTC Mon-Fri.
2. **HOLD BTC5 at $5/trade. Do not scale yet.** Promotion gate currently fails; keep data collection running until `reports/btc5_promotion_gate.json` reports `overall_gate=true` across a >=7-day window.
3. **Fix test failures in `test_btc_5min_maker_process_window_core.py`.** Guardrail changes broke test expectations. Repair tests to match new live config (delta 0.0040, buy prices 0.52/0.53, lt049 skip disabled).
4. **Download fresh wallet export CSV.** Last export 2026-03-12 (62+ hours stale). Blocks stage gate progression. Export from https://polymarket.com/portfolio.
5. **Build the minimum JJ-N live-launch package for Website Growth Audit.** Best path to first non-trading dollar. Blocking: verified sending domain, curated leads, explicit approval.

---

## 11. Source Index

Use these files as the canonical supporting evidence:

Checked-in artifacts:

- `config/remote_cycle_status.json`
- `improvement_velocity.json`
- `FAST_TRADE_EDGE_ANALYSIS.md`
- `config/runtime_profiles/maker_velocity_all_in.json`
- `research/edge_backlog_ranked.md`
- `docs/NON_TRADING_STATUS.md`
- `nontrading/offers/website_growth_audit.py`

Runtime-local artifacts (optional attachments when present):

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/runtime_mode_reconciliation_20260309T154637Z.md`
- `reports/root_test_status.json`
- `reports/state_improvement_latest.json`
- `reports/arb_empirical_snapshot.json`

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
