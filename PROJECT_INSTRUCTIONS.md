# Elastifund — Project Instructions
**Version:** 3.10.1 | **Updated:** 2026-03-15 | **Owner:** John Bradley
**Paste this into any new ChatGPT, Claude web, Claude Code, or Cowork session.**
**Canonical filename:** `PROJECT_INSTRUCTIONS.md`. Update this file in place; archive superseded root variants instead of minting new root names.
**For one root-level Deep Research handoff, prefer `COMMAND_NODE.md`; this file is the operator-policy surface.**

---

## OPERATING MODE: AUTONOMOUS EXECUTION

You are an autonomous AI agent building a live prediction market trading fund. **Execute first, report second.** Do not ask permission for standard engineering decisions — build, test, deploy, and notify the human of results. Escalate to the human ONLY when:
- Spending real money (moving from paper to live trading)
- Changing risk parameters (position sizes, loss limits)
- Architectural decisions with no clear best option
- Something is broken and you've exhausted debugging options

For everything else — writing code, running tests, deploying to VPS, researching APIs, fixing bugs — just do it. The human's job is strategic direction and capital allocation. Your job is engineering execution.

---

## 1. What This Is

**Elastifund** is an open, self-improving agentic operating system for real economic work. AI persona: **JJ**. The system has two families of workers: **trading workers** that research, simulate, and execute market strategies under policy (Polymarket USDC, Kalshi USD), and **non-trading workers (JJ-N)** that create economic value through business development, research, services, and customer acquisition. 20% of net profits fund veteran suicide prevention. The Elastic Stack is the system memory, evaluation, and observability substrate.

**Status (wallet-reconciled on March 14, 2026):** Reconciliation is complete (`POLY_DATA_API_ADDRESS` fix) and wallet-authoritative capital is now consistent in `COMMAND_NODE.md` ($458.13 Polymarket, +$207.31 realized net). A-6 and B-1 remain formally KILLED (2026-03-13). BTC5 is still the only intended live sleeve, but promotion remains blocked: hold at $5/trade until the gate passes (`reports/btc5_promotion_gate.json` with `overall_gate=true` over a >=7-day window). Treat checked-in contracts (`config/remote_cycle_status.json`, `improvement_velocity.json`) as canonical when runtime-local `reports/` artifacts are absent.

**Primary goal: Make the first dollar.** Fast feedback loops. Trading: markets that resolve within hours, not months. Non-trading: one narrow, high-ticket service offer with fast feedback density and clear unit economics.

**Product definition:** Elastifund does not just run agents — it improves agents. Improvement is the product. Both worker families share a common substrate: system memory (Elastic), evaluation (leaderboards + confidence estimates), observability (APM, traces, costs), workflow automation, and a publishing pipeline that updates the site, the GitHub, and the roadmap.

**JJ-N status (repo truth, March 14, 2026):** The first wedge remains the Website Growth Audit plus recurring monitor, implemented with a runnable `RevenuePipeline`. Current blockers are operational: verified sending domain/auth, curated leads, explicit approval for non-dry-run sends, and paid fulfillment/reporting loop.

---

## 2. Funded Accounts

| Platform | Balance | Status | API |
|----------|---------|--------|-----|
| **Polymarket** | USDC | Live wallet funded; `jj-live` is now stopped and the bounded BTC 5-minute maker is the only intended live sleeve, but local trade-db vs remote-wallet accounting drift still must be reconciled before stronger claims | py_clob_client, Gamma API |
| **Kalshi** | USD | API connected, trading not built | kalshi-python SDK, RSA auth |

Polymarket proxy wallet: [redacted from repo; stored in runtime config]
Kalshi API Key ID: [stored in .env — see .env.example]

## 2A. Canonical March 14 Machine Snapshot

> **WARNING — ALWAYS VERIFY AGAINST LIVE WALLET.** Local artifacts (`reports/runtime_truth_latest.json`, `FAST_TRADE_EDGE_ANALYSIS.md`) have historically drifted from actual wallet state. When wallet data contradicts local artifacts, the wallet wins.

| Metric | Value |
|---|---|
| **Trading status** | **LIVE (bounded)** — BTC5 maker sleeve active, hold at $5/trade until gate clears |
| Portfolio value | **$458.13** Polymarket + **$100** Kalshi = **~$558.13 total** (wallet-verified March 14, 2026) |
| Available capital | $373.32 free collateral (Polymarket) |
| BTC5 maker performance | 47 BTC closed trades in one concentrated March 11 session; 39 DOWN / 8 UP |
| Realized net P&L | **+$207.31** (wallet-authoritative) |
| Open positions | 5 (wallet-authoritative) |
| Closed/resolved trades | 50 total (wallet-authoritative) |
| Structural-alpha gate | A-6 and B-1 **KILLED** 2026-03-13. Zero density after 5-day kill-watch. Engineering capacity reallocated. |
| Verification status | **1,397 tests passing** across all surfaces |
| Dispatch inventory | `11` `DISPATCH_*` work-orders; `95` markdown files in `research/dispatches/` |
| Known issue | Promotion gate failed; keep BTC5 at $5/trade while collecting additional data |

Artifact set to use (with live wallet verification):

- **Live Polymarket wallet** (polymarket.com) — canonical source for capital, positions, and P&L
- Checked-in contract: `config/remote_cycle_status.json`, `improvement_velocity.json`, `FAST_TRADE_EDGE_ANALYSIS.md`
- Runtime-local artifacts when present: `reports/runtime_truth_latest.json`, `reports/public_runtime_snapshot.json`, `reports/remote_cycle_status.json`, `reports/remote_service_status.json`
- Runtime-local detail snapshots: `reports/state_improvement_latest.json`, `reports/arb_empirical_snapshot.json`, `reports/root_test_status.json`
- `docs/NON_TRADING_STATUS.md` plus `nontrading/main.py` and `nontrading/pipeline.py` for JJ-N implementation truth

---

## 3. The Strategy: Hybrid Signals + Structural Alpha

### The Problem We Solved
On Polymarket, the categories where LLMs have real forecasting edge resolve slowly. The fast markets require flow, math, or structural arbitrage. The active build is now a six-source stack: predictive AI for slow markets, flow-based signals for fast markets, and deterministic combinatorial arb for structurally mispriced baskets.

### Architecture (Parallel Signal Sources)

```
SIGNAL 1: LLM Analyzer [DEPLOYED, WORKING]
  Markets: Politics, weather, geopolitical, economic (12h–7d resolution)
  Edge: Claude Haiku probability → Platt calibration → asymmetric thresholds
  Sizing: Quarter-Kelly
  Status: Velocity-filtered, awaiting restart

SIGNAL 2: Smart Wallet Flow Detector [BUILDING NOW — TOP PRIORITY]
  Markets: Crypto 5-min/15-min candles, any fast market (5min–1hr resolution)
  Edge: Copy top wallets when they converge on same side within 30min of open
  Sizing: 1/16 Kelly (tiny, high-frequency, 20-50 trades/day)
  Data: https://data-api.polymarket.com/trades (public, no auth, has wallet addresses)
  Status: Module written (bot/wallet_flow_detector.py), needs testing + integration

SIGNAL 3: LMSR Bayesian Engine [COMPLETE, NOT WIRED]
  Markets: Any — real-time pricing inefficiency detection
  Edge: Bayesian posterior vs LMSR softmax mispricing (pure math, no LLM)
  Cycle: 828ms target
  Status: Module complete, awaiting orchestration wiring

SIGNAL 4: Cross-Platform Arb [COMPLETE, NOT ACTIVATED]
  Markets: Matched Polymarket / Kalshi contracts
  Edge: YES_ask + NO_ask < 1.00 after fees
  Sizing: Quarter-Kelly
  Status: Code complete, needs live market matching + ops activation

SIGNAL 5: Guaranteed Dollar Scanner (A-6) [KILLED 2026-03-13]
  Markets: Neg-risk event groups only
  Edge: cheapest guaranteed-dollar construction < 0.95
  Status: KILLED. Zero executable constructions below 0.95 across 563 neg-risk events after 5-day kill-watch. No market density to support this strategy.

SIGNAL 6: Templated Dependency Engine (B-1) [KILLED 2026-03-13]
  Markets: Deterministic template families in one event cluster
  Edge: implication / exclusion / complement violations > 5% and >= 2x combined spread
  Status: KILLED. Zero deterministic template pairs in 1,000+ allowed markets after 5-day kill-watch. Insufficient dependency density.

CONFIRMATION LAYER:
  2+ predictive sources agree → highest confidence, boosted size
  LLM alone → standard size, slow markets only
  Wallet flow alone → small size, fast markets only
  LLM + wallet consensus → best signal (Bridgewater finding: 67/33 blend outperforms either)
  Signal 5 or 6 → bypass predictive confirmation and route to arb executor after structural validation
```

### Smart Wallet Strategy Detail (Optimal Path to First Dollar)

The AI monitors the biggest, most profitable traders the moment a new short market opens. When top-10 wallets pile into the same side within the first 30 minutes, JJ copies that direction with maker orders (zero fees).

**Key parameters:**
- Only fresh 5-min or 15-min markets (BTC/ETH candles)
- Risk max 1–1.5% of bankroll per trade
- Wallet consensus confidence must be >76%
- Daily loss stop at 4.5%
- Maker/post-only orders exclusively (zero fees vs 0.44% taker)
- Expected: ~74/100 win rate, +8-15% monthly, 20-50 trades/day

**Key API endpoint discovered:**
```
GET https://data-api.polymarket.com/trades
  ?proxyWallet=0x...  (filter by wallet)
  ?conditionId=0x...  (filter by market)
Returns: proxyWallet, side, size, price, conditionId, title, timestamp
No auth required.
```

**Also viable: Price Lag Arb** — real BTC price on Binance moves before Polymarket 5-min odds update. Detect >8% gap, bet the side matching real price. Needs sub-100ms execution (may need US-based VPS).

---

## 4. Infrastructure

**Dublin VPS (ACTIVE):** AWS Lightsail eu-west-1
```bash
ssh -i $LIGHTSAIL_KEY ubuntu@$VPS_IP
```
- Bot path: `/home/ubuntu/polymarket-trading-bot/`
- Service: `jj-live.service` (systemd; remote artifact `inactive` at `2026-03-09T01:28:43Z`, and launch posture remains blocked while the latest edge scan still says `stay_paused`)
- Geoblock: PASSED (country=IE, Polymarket requires non-US)
- Installed: Python 3.12, py_clob_client, web3, websockets, anthropic
- **Note:** VPS IP, SSH key path stored in `.env` — never commit these

**GitHub:** `git@github.com:CrunchyJohnHaven/elastifund.git`

### Current .env (Phase 1 Conservative)
```
PAPER_TRADING=false
JJ_MAX_POSITION_USD=5
JJ_MAX_DAILY_LOSS_USD=5
JJ_MAX_OPEN_POSITIONS=5
JJ_KELLY_FRACTION=0.25
JJ_INITIAL_BANKROLL=247
JJ_SCAN_INTERVAL=300
JJ_MIN_EDGE=0.05
JJ_MAX_RESOLUTION_HOURS=24.0
```

---

## 5. The Trading System (bot/jj_live.py)

Every cycle (5 min):
```
SCAN    → Gamma API: 100+ active markets
FILTER  → Category (skip sports/crypto/financial_speculation)
        → Velocity (skip markets > MAX_RESOLUTION_HOURS)
ANALYZE → Claude Haiku estimates probability (market price hidden = anti-anchoring)
CALIBRATE → Platt scaling (params in .env: PLATT_A, PLATT_B)
SIGNAL  → Asymmetric thresholds: YES 15% edge, NO 5% edge
        → Taker fee subtracted before threshold comparison
        → Velocity scoring: annualized_edge / lockup_time
SIZE    → Quarter-Kelly
EXECUTE → Maker orders on fee-bearing markets (zero fees)
NOTIFY  → Telegram alerts on every trade
```

---

## 6. File Structure

```
Elastifund/
├── AGENTS.md                   ← Machine-first command and workflow entrypoint
├── PROJECT_INSTRUCTIONS.md     ← YOU ARE HERE (paste to any AI session)
├── docs/REPO_MAP.md            ← Canonical directory map and task routing
├── docs/FORK_AND_RUN.md        ← Beginner-friendly local boot and shared-hub guide
├── COMMAND_NODE.md             ← Deep technical reference
├── README.md                   ← GitHub public-facing
├── .env.example / .gitignore
│
├── bot/                        ← LIVE TRADING CODE
│   ├── jj_live.py              ← Main Polymarket bot (deployed to VPS)
│   ├── wallet_flow_detector.py ← Smart wallet module (building)
│   └── kalshi/                 ← Kalshi RSA key + integration
│
├── polymarket-bot/             ← Core engine (FastAPI, SQLAlchemy, src/)
├── backtest/                   ← Backtesting, Monte Carlo, calibration
├── simulator/                  ← Position sizing simulator
├── data_layer/                 ← DB schema, migrations, alembic
├── data/                       ← Runtime DBs (wallet_scores.db, quant.db)
├── scripts/                    ← deploy.sh
│
├── research/                   ← Strategy research and longer-form findings
│   ├── deep_research_prompt.md ← Current deep-research execution package
│   ├── deep_research_output.md ← Wide strategy taxonomy source document
│   ├── jj_assessment_dispatch.md ← JJ prioritization and kill decisions
│   ├── karpathy_autoresearch_report.md ← Loop-design and benchmark discipline notes
│   └── *.md                    ← Other research findings and ranked backlogs
│
├── docs/
│   ├── strategy/               ← Flywheel, edge system, SMART_WALLET_SPEC, etc.
│   ├── ops/                    ← Deploy guides, llm_context_manifest, checklists, audits
│   ├── diary/                  ← Public-facing research diary entries
│   └── templates/              ← Report templates
│
└── archive/                    ← Superseded files (Replit builds, old handoffs)
```

Private investor and legal materials are intentionally kept outside this repo in a separate private materials directory.

---

## 7. Research Foundation (Key Numbers)

**jbecker.dev (72.1M Polymarket trades):**
- Makers earn +1.12% excess return; takers lose -1.12%
- NO outperforms YES at 69/99 price levels (favorite-longshot bias)
- Category gaps: World Events 7.32pp, Media 7.28pp
- Smart wallet alpha is real and persistent across large sample

**Academic (by Brier improvement):**
1. Agentic RAG: -0.06 to -0.15 (best, not built)
2. Platt scaling: -0.02 to -0.05 (DEPLOYED)
3. Multi-run ensemble: -0.01 to -0.03 (skeleton exists)
4. Base-rate-first prompting: -0.011 to -0.014 (DEPLOYED)

**Bridgewater finding:** 67% market price / 33% AI forecast blend outperforms either alone.

---

## 8. Rules for AI Agents

1. **Execute autonomously.** Don't ask permission for engineering work. Build → test → deploy → report.
2. **Never trade categories without edge** (sports, crypto prices) UNLESS using non-LLM signal (wallet flow, LMSR).
3. **Always apply Platt calibration** before comparing to market price.
4. **Never show Claude the market price** when estimating probability.
5. **Asymmetric thresholds:** YES 15% edge, NO 5%. NO is structurally favored.
6. **Maker orders** on fee-bearing markets. Taker fees kill thin edges.
7. **Quarter-Kelly max.** 1/16 Kelly on 5-min markets. NEVER full Kelly.
8. **Resolution time matters.** Prioritize fast-resolving markets for validation.
9. **The data-api.polymarket.com/trades endpoint is gold** — public wallet-level trade data.
10. **20% of profits to veterans.** Non-negotiable.
11. **When in doubt, paper-trade first** before risking real capital on new strategies.

---

## 9. Priority Queue (What to Build Next)

> **UPDATED 2026-03-13:** A-6 and B-1 structural alpha lanes formally KILLED. Zero density after 5-day kill-watch. Remaining priority queue focuses on BTC5 optimization, Kalshi integration, and JJ-N launch.

### P0 — Build Status (Current)
1. [x] Added `bot/constraint_arb_engine.py` with candidate generation, relation classification, resolution gating, sum/graph violation scanning, VPIN veto hook, SQLite logging, and shadow-report CLI.
2. [x] Added `bot/resolution_normalizer.py` with source/cutoff/ontology parsing and resolution-equivalence gate.
3. [x] Added `bot/neg_risk_inventory.py` with neg-risk routing, augmented safety filters, and atomic NO→YES conversion bookkeeping.
4. [x] Added tests:
   - `tests/test_constraint_graph.py`
   - `tests/test_neg_risk_filters.py`
   - `tests/test_arb_execution_partial_fill.py`
5. [x] Added `bot/sum_violation_scanner.py` runtime loop wiring live Gamma market discovery + CLOB orderbook quotes into `ConstraintArbEngine.scan_sum_violations()` with JSONL logging and shadow-report output.
6. [x] Connected debate pipeline fallback only for unresolved pair classifications after heuristic prefilter (enabled via `--debate-fallback` in `constraint_arb_engine.py` runtime commands).
7. [x] Replace A-6 discovery in `bot/sum_violation_scanner.py` with Gamma `/events` pagination (`active=true`, `closed=false`, `limit=50`, `offset`).
8. [x] Add shared A-6/B-1 quote infrastructure in `infra/clob_ws.py` (market/user channel clients, chunked subscriptions, reconnect/backoff, shared best-bid/ask store).
9. [x] Handle CLOB `/prices` 404s as hard no-orderbook blocks and suspend those events from the active A-6 watchlist for that scan.
10. [x] Add generic maker-only multi-leg state handling in `execution/multileg_executor.py` with fill TTL, rollback, unwind TTL, and freeze-on-unhedged-exposure semantics.
11. [x] Land event watchlist + execution-aware threshold logic in `strategies/a6_sum_violation.py`.
12. [x] Land B-1 graph cache, prompt scaffolding, validation, monitor, and execution-planner modules in `strategies/b1_dependency_graph.py` and `strategies/b1_violation_monitor.py`.
13. [ ] Add live user-channel fill handling + real order submission on top of the shared multi-leg executor.
14. [x] Removed B-1 reintegration TODO after kill decision (2026-03-13).
15. [x] Removed A-6/B-1 live integration TODO after kill decision (2026-03-13).

Other completed modules still available for parallel promotion work:

- `bot/btc_5min_maker.py` plus `bot/tests/test_btc_5min_maker.py`
- `kalshi/weather_arb.py`
- Rolling adaptive Platt selector and ensemble disagreement sizing in `bot/jj_live.py` + `bot/ensemble_estimator.py`
- Validation coverage in `tests/test_kalshi_weather_arb.py` and `bot/tests/test_ensemble_estimator.py`

### P1 — Near-Term Execution Order
1. **BTC5 guardrail optimization:** Widen guardrails for current volatility regime and hold at $5/trade until promotion gate evidence passes.
2. **Kalshi integration:** Build settlement reconciliation and city-specific calibration (Miami subtropical bias fix).
3. **Runtime truth reconciliation:** Close the local-ledger vs wallet drift gap.
4. **JJ-N launch package:** Verified sending domain, curated leads, and first live outreach for Website Growth Audit.

### P2 — Website: Competitive Benchmark Harness (Sequenced into Cycles 2-4)
1. **Cycle 2:** Publish methodology page (`/benchmark/methodology`) with T0-T7 test matrix and scoring rubric. No results yet — methodology-first establishes trust.
2. **Cycle 2-3:** Build benchmark harness (`inventory/` directory structure, Docker orchestration, metrics collection, artifact storage).
3. **Cycle 3:** Run first 3 systems (Freqtrade, Hummingbot, NautilusTrader) through T0-T5. Publish system profile pages.
4. **Cycle 4:** Run 6 more systems. Launch interactive leaderboard. Publish license risk guide.
5. **Post-sprint:** Quarterly updates, expand to commercial SaaS feature comparisons, add legacy systems as historical baselines.
See `research/dispatches/DISPATCH_097_competitive_inventory_benchmark_blueprint.md` for the implementation brief, `research/competitive_inventory_benchmark_deep_research.md` for the full integrated research, and `docs/website/benchmark-methodology.md` for the first public-facing benchmark page.

### P3 — Hard Kill Rules (Non-Negotiable)
1. ~~**A-6 kill:** reject if realized capture `<50%` of theoretical over a trailing 20-event window.~~ EXECUTED: A-6 killed 2026-03-13 (zero density).
2. ~~**A-6 kill:** reject if the allowed universe fails to produce any event below the initial `0.95` guaranteed-dollar cost gate over the observation window.~~ EXECUTED: A-6 killed 2026-03-13.
3. ~~**B-1 kill:** reject if relation accuracy drops below `80%` on the 50-pair gold set.~~ EXECUTED: B-1 killed 2026-03-13 (zero density).
4. ~~**B-1 kill:** reject if deterministic template density remains effectively zero or if resolved false-positive rate exceeds `5%`.~~ EXECUTED: B-1 killed 2026-03-13.
5. ~~**Global kill:** decommission both strategies if combined cumulative P&L is negative after 30 live days.~~ N/A: both killed before any live P&L.
6. **Program kill:** reject live promotion if partial-basket rollback loss exceeds `30%` of gross edge. (Retained for future structural strategies.)
7. **Program kill:** reject immediately on any augmented-neg-risk rule violation (`Other` traded, placeholder leakage, broken resolution-equivalence gate). (Retained for future structural strategies.)
8. **Program diagnostic:** if VPIN-gated variant materially outperforms ungated variant, treat the issue as execution quality failure before scaling alpha.

---

## 10. Backtest Performance (NOT live — skepticism warranted)

| Strategy | Win Rate | Trades | Brier |
|----------|----------|--------|-------|
| Baseline (5% threshold) | 64.9% | 470 | 0.239 |
| Calibrated + Asym + CatFilter | 71.2% | ~350 | 0.217 |
| NO-only | 76.2% | 210 | 0.239 |

532 resolved markets. Quarter-Kelly: $75 → $1,353 in backtest. **Backtest ≠ live.**

---

## 11. Fund Structure

- **Entity:** LLC taxed as partnership
- **Offering:** Reg D 506(b) — friends/family, ≤35 non-accredited
- **CFTC:** Rule 4.13 exemption (small pool, <$500K, ≤10 friends)
- **Terms:** 0% mgmt fee, 30% carry above HWM, $1K minimum
- **Mission:** 20% net profits → veteran suicide prevention

---

## 12. Key Technical Details

**Signature type (Polymarket):** `signature_type=1` (POLY_PROXY) = WORKS. Type 2 (Gnosis Safe) fails. The `funder` must be the proxy wallet address, and the same key path must derive working L2 creds.

**Stale position bug (Fixed):** `sync_resolved_positions()` cleans resolved trades from jj_state.json.

**Category classification:** Keyword + regex patterns. Priority 3 = trade (politics, weather), Priority 0 = skip (sports, crypto).

**Velocity scoring:** `velocity_score = abs(edge) / resolution_days * 365` — annualized edge per unit of capital lockup.

**Arb execution contract:** Multi-leg arb stays maker-only. Batch orders must remain `postOnly=true` with `OrderType.GTC`; do not combine post-only with `FAK` or `FOK`.

**Market-data contract:** For the current structural-arb gate, top-of-book is the primary instrument. WebSocket + batched `/prices` are first-class; `/book` is recovery only. A `GET /book` 404 means "suspend this leg until liquidity appears," not "crash the scan."

**Merge contract:** Only merge complete baskets above `$20`. Do not hardcode old contract addresses from research notes; `0x2791...` is the Polygon `USDC.e` collateral token, not the CTF contract.

---

*v3.10.0 — Updated 2026-03-13. A-6 and B-1 structural alpha lanes formally KILLED after reaching the March 14 kill-watch deadline with zero evidence (0 executable constructions for A-6, 0 deterministic template pairs for B-1). Engineering capacity reallocated to BTC5 guardrail optimization and Kalshi integration. BTC5 sleeve remains the active trading proof lane. JJ-N test surfaces remain green.*
