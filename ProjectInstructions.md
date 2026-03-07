# Elastifund — Project Instructions
**Version:** 3.1.0 | **Updated:** 2026-03-07 | **Owner:** John Bradley
**Paste this into any new ChatGPT, Claude web, Claude Code, or Cowork session.**

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

**Elastifund** is an AI-powered prediction market trading fund. AI persona: **JJ**. We trade on **Polymarket** (USDC, live) and **Kalshi** (USD, API connected). 20% of net trading profits fund veteran suicide prevention.

**Status (March 7, 2026):** Bot deployed to Dublin VPS. Service STOPPED while the structural alpha stack is integrated: smart wallet flow for fast markets plus combinatorial arbitrage (A-6 first, then B-1). Three long-dated orders were placed and cancelled. Velocity filter confirmed that pure LLM forecasting cannot be the only lane on Polymarket.

**Primary goal: Make the first dollar.** Fast feedback loops. Trade markets that resolve within hours, not months.

---

## 2. Funded Accounts

| Platform | Balance | Status | API |
|----------|---------|--------|-----|
| **Polymarket** | USDC | Live, service stopped for upgrade | py_clob_client, Gamma API |
| **Kalshi** | USD | API connected, trading not built | kalshi-python SDK, RSA auth |

Polymarket proxy wallet: `0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5`
Kalshi API Key ID: [stored in .env — see .env.example]

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

SIGNAL 5: Sum Violation Scanner (A-6) [SHADOW MODE, UPGRADE IN PROGRESS]
  Markets: Multi-outcome / neg-risk event groups
  Edge: sum(YES asks) < 0.97 or sum(YES bids) > 1.03
  Sizing: Execution-risk-adjusted, capped at $5/leg
  Status: bot/sum_violation_scanner.py exists; WebSocket depth + batch execution pending

SIGNAL 6: Dependency Graph Arb (B-1) [BUILDING]
  Markets: Logically linked markets in same resolution window
  Edge: implication / exclusion / complement violations > 3%
  Sizing: Execution-risk-adjusted, capped at $5/leg
  Status: bot/constraint_arb_engine.py exists; gold set + Haiku cache + live monitor pending

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
- Service: `jj-live.service` (systemd, currently STOPPED)
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
├── ProjectInstructions.md      ← YOU ARE HERE (paste to any AI session)
├── COMMAND_NODE_v1.0.2.md      ← Deep technical reference (764 lines)
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
├── research/                   ← Strategy research
│   ├── dispatches/             ← 79 research prompts (P0-P3, by tool target)
│   ├── prompts/                ← Original research prompt docs
│   └── *.md                    ← Research findings
│
├── docs/
│   ├── strategy/               ← SMART_WALLET_SPEC, LLM_ENSEMBLE_SPEC, etc.
│   ├── ops/                    ← Deploy guides, checklists, audits
│   └── templates/              ← Report templates
│
├── fund/
│   ├── investor/               ← Investor reports, pitch sheets, task lists
│   └── legal/                  ← PPM, subscription agreements, credentials
│
└── archive/                    ← Superseded files (Replit builds, old handoffs)
```

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

> **UPDATED 2026-03-07:** Canonical implementation spec now lives in `docs/strategy/combinatorial_arb_implementation_deep_dive.md`. Primary lane is structural alpha: A-6 first, B-1 second.

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
14. [ ] Add resolved-market dependency audit and manual 50-pair validation loop for B-1.
15. [ ] Integrate A-6 and B-1 into the live confirmation/execution stack in `bot/jj_live.py` once the multi-leg routing path is ready.

Other completed modules still available for parallel promotion work:

- `bot/btc_5min_maker.py` plus `bot/tests/test_btc_5min_maker.py`
- `kalshi/weather_arb.py`
- Rolling adaptive Platt selector and ensemble disagreement sizing in `bot/jj_live.py` + `bot/llm_ensemble.py`
- Validation coverage in `tests/test_kalshi_weather_arb.py` and `bot/tests/test_llm_ensemble.py`

### P1 — 14-Day Execution Order (Do In Sequence)
1. **Days 1-3 (A-6 data plane):** Move discovery to Gamma `/events`, stream live market-depth over WebSocket, and keep per-token best-bid/best-ask state in memory.
2. **Days 4-5 (A-6 execution):** Batch multi-leg maker orders, enforce `postOnly + GTC` only, add 3000ms partial-fill rollback timer, and start linked-leg persistence.
3. **Days 6-8 (B-1 graph build):** Build the 50-pair gold set, add resolution-window/tag/embedding prefilter, run Haiku classification, and cache graph edges.
4. **Days 9-10 (B-1 live monitor):** Monitor implication, mutual-exclusion, and complement violations at `tau = 0.03`; defer conditional chains.
5. **Days 11-12 (integration):** Route A-6/B-1 into the live confirmation/execution stack, wire execution-risk sizing, and finalize kill switches.
6. **Days 13-14 (shadow mode):** Paper trade the combined arb stack, simulate realistic maker fills, and publish capture-rate / rollback-loss attribution.

### P2 — Hard Kill Rules (Non-Negotiable)
1. **A-6 kill:** reject if realized capture `<50%` of theoretical over a trailing 20-event window.
2. **A-6 kill:** reject if zero qualifying events are detected over 4 weeks.
3. **B-1 kill:** reject if relation accuracy drops below `80%` on the 50-pair gold set.
4. **B-1 kill:** reject if resolved false-positive rate exceeds `5%` or if 3 consecutive signals lose money due to rollback/spread collapse.
5. **Global kill:** decommission both strategies if combined cumulative P&L is negative after 30 live days.
6. **Program kill:** reject live promotion if partial-basket rollback loss exceeds `30%` of gross edge.
7. **Program kill:** reject immediately on any augmented-neg-risk rule violation (`Other` traded, placeholder leakage, broken resolution-equivalence gate).
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

**Market-data contract:** A-6/B-1 require market WebSocket depth. REST orderbook calls are bootstrap and recovery only. A `GET /book` 404 means "suspend this leg until liquidity appears," not "crash the scan."

**Merge contract:** Only merge complete baskets above `$20`. Do not hardcode old contract addresses from research notes; `0x2791...` is the Polygon `USDC.e` collateral token, not the CTF contract.

---

*v3.1.0 — Updated 2026-03-07. Integrated the combinatorial arbitrage deep dive, promoted A-6/B-1 into the active priority queue, and added explicit execution contracts for WebSocket depth, linked-leg state, rollback, and merge handling. This document supersedes COMMAND_NODE for quick-start context in new AI sessions. See COMMAND_NODE_v1.0.2.md for deep technical reference.*
