# COMMAND NODE — Predictive Alpha Fund

**Version:** 1.2.0
**Last Updated:** 2026-03-07
**Owner:** John Bradley (johnhavenbradley@gmail.com)
**Purpose:** Single source of truth for all AI instances (ChatGPT, Cowork, Claude Code, Grok) to operate with full project context. Paste this document (or relevant sections) into any new session so the AI can write prompts, make decisions, and build on prior work without re-discovery.

---

## Version Log

| Version | Date | Change Summary |
|---------|------|----------------|
| 1.2.1 | 2026-03-07 | Structural alpha gating reset executed in code: A-6 now ranks straddles vs baskets with execution-readiness gates, augmented neg-risk `Other` legs are filtered instead of dropping whole events, and B-1 gold-set generation now emits deterministic compatibility matrices first. |
| 1.2.0 | 2026-03-07 | Parallel execution sprint: full module inventory (27 modules), A-6/B-1 architecture section, updated strategy counts (7 deployed / 6 building / 10 rejected / 8 pre-rejected / 100 pipeline), 223 tests passing, 82 dispatches, "What Doesn't Work" diary v1, document hierarchy refresh. |
| 1.1.1 | 2026-03-07 | Integrated A-6/B-1 combinatorial arbitrage build plan: Signal Sources 5/6, deterministic bypass routing, constraint-arb data stores, and repo-specific execution gates. |
| 1.1.0 | 2026-03-07 | Updated with JJ persona + prime directive, dual mission framing, 6-phase flywheel cycle, strategy status table (6 deployed / 5 building / 10 rejected / 30 pipeline), RTDS maker-edge and Dublin latency findings, refreshed document hierarchy, open-source guardrails, and website vision summary. |
| 1.0.2 | 2026-03-07 | Prior baseline with flywheel v2 framing, hybrid strategy architecture, and deployment context. |

---

## 1. What This Project Is

**Elastifund** is an agent-run trading company and an open-source research engine. John designs constraints, infrastructure, and research process; JJ executes trading and engineering decisions inside those boundaries. The system mandate is risk-adjusted returns plus rigorous public documentation.

### JJ Persona (3-Sentence Brief)
JJ is the principal execution layer of Elastifund: direct, evidence-driven, and intolerant of weak assumptions. JJ makes autonomous decisions on implementation and strategy iteration, then reports confidence, data, and next actions. John is the infrastructure engineer and constraint setter; JJ is the operator.

**Prime directive:** "John shares info, JJ decides."

**Dual mission:** (1) Generate trading returns from validated edges. (2) Build the world's best public resource on agentic trading at johnbradleytrading.com.

**Current status (2026-03-07):** Polymarket funded ($247.51 USDC), Kalshi connected ($100 USD), Dublin VPS active (AWS eu-west-1). Structural alpha is now gated by live executable density: A-6 first as a guaranteed-dollar/top-of-book lane, B-1 only as a deterministic template lane until density proves otherwise.

| Strategy Status | Count | Source |
|-----------------|-------|--------|
| Deployed (live/ready) | 7 | `research/edge_backlog_ranked.md` |
| Building (code complete) | 6 + A-6/B-1 | `research/edge_backlog_ranked.md` |
| Tested & Rejected | 10 | `research/what_doesnt_work_diary_v1.md` |
| Pre-Rejected (v3) | 8 | `research/edge_backlog_ranked.md` |
| Research Pipeline | 100 | `research/edge_backlog_ranked.md` |
| **Total Tracked** | **131** | |

**The Flywheel:** Research -> Implement -> Test -> Record -> Publish -> Repeat in 3-5 day cycles.

---

## 2. How the Bot Works (Technical)

### Architecture

```
VPS: 52.208.155.0 (AWS Lightsail Dublin, eu-west-1)
systemd: jj-live.service (ACTIVE)
Bot file: bot/jj_live.py (local) → /home/ubuntu/polymarket-trading-bot/jj_live.py (VPS)

SIGNAL SOURCE 1: LLM Ensemble + Agentic RAG (bot/llm_ensemble.py, every 5 min)
├── SCAN:      Gamma API → 100+ active markets
├── FILTER:    Category (skip sports/crypto/financial_speculation)
│              Velocity (skip markets > MAX_RESOLUTION_HOURS)
├── RAG:       DuckDuckGo web search → recent context injected into prompt
├── ENSEMBLE:  Claude Haiku + GPT-4.1-mini + Groq Llama 3.3 (parallel)
│              Trimmed mean aggregation, consensus gating (75%+ agree)
├── CALIBRATE: Platt scaling (A=0.5914, B=-0.3977) on ensemble mean
├── BRIER:     Live accuracy tracking in SQLite (per-model + category)
├── SIGNAL:    Asymmetric thresholds (YES 15%, NO 5%) + velocity scoring
├── SIZE:      Quarter-Kelly (boosted if models_agree=True)
├── EXECUTE:   Post-only maker orders on all markets
├── NOTIFY:    Telegram alerts
└── TESTS:     34 unit tests passing

SIGNAL SOURCE 2: Smart Wallet Flow Detector (bot/wallet_flow_detector.py, COMPLETE)
├── MONITOR:   Poll data-api.polymarket.com/trades for top wallet activity
├── SCORE:     Rank wallets by 5-factor activity score (data/wallet_scores.db)
├── DETECT:    Flag when N of top-K wallets converge on same side
├── SIGNAL:    Consensus > 76% confidence → trade
├── SIZE:      1/16 Kelly (tiny, high-frequency)
└── EXECUTE:   Maker orders (zero fees on crypto markets)

SIGNAL SOURCE 3: LMSR Bayesian Engine (bot/lmsr_engine.py, COMPLETE)
├── POLL:      data-api.polymarket.com/trades (same endpoint as wallet flow)
├── POSTERIOR:  Sequential Bayesian update in log-space per market
├── LMSR:      Softmax pricing from trade flow quantities
├── BLEND:     60% Bayesian posterior + 40% LMSR flow price
├── SIGNAL:    |blended_price - clob_price| > threshold → trade
├── SIZE:      1/16 Kelly (always treated as fast market)
├── CYCLE:     Target 828ms avg, 1776ms p99
└── TESTS:     45 unit tests passing

SIGNAL SOURCE 4: Cross-Platform Arb Scanner (bot/cross_platform_arb.py, COMPLETE)
├── FETCH:     Polymarket Gamma API (300 markets) + Kalshi SDK (3000+ markets)
├── FILTER:    Skip sports/esports via KALSHI_SKIP_PREFIXES, zero-liquidity markets
├── MATCH:     SequenceMatcher + Jaccard keyword similarity (threshold 70%)
├── DETECT:    YES_ask + NO_ask < $1.00 after fees → risk-free arb
├── FEES:      Kalshi taker = 0.07·p·(1-p), Polymarket maker = 0%
├── SIGNAL:    Net profit > MIN_PROFIT_PCT → trade on Polymarket side
├── SIZE:      Quarter-Kelly (arb = high confidence)
└── TESTS:     29 unit tests passing

SIGNAL SOURCE 5: Guaranteed Dollar Scanner (A-6, EMPIRICAL GATE)
├── DISCOVER:  Gamma `/events` active universe → grouped multi-outcome events
├── STREAM:    Top-of-book YES/NO quotes first; `/book` is recovery, not the default scan path
├── DETECT:    rank cheapest of `YES+NO`, neg-risk-conversion, and full-basket constructions
├── GATE:      initial threshold = guaranteed-dollar cost `< 0.95`
├── EXECUTE:   maker quotes must rest inside the book; fill/dwell data matters more than more buildout
├── MERGE:     defer merge optimization unless entry density/fills justify it
├── MODULES:   constraint_arb_engine.py, sum_violation_scanner.py, a6_sum_scanner.py,
│              a6_executor.py, neg_risk_inventory.py, resolution_normalizer.py,
│              signals/sum_violation/guaranteed_dollar.py
└── STATUS:    Live-public-data audit: 92 allowed neg-risk events, 0 constructions below the initial 0.95 gate.

SIGNAL SOURCE 6: Templated Dependency Engine (B-1, GATED)
├── PREFILTER: deterministic family matcher first; broad graph expansion is blocked behind density
├── CLASSIFY:  compatibility matrix for winner↔margin / composite families; LLM only for residual ambiguity
├── MONITOR:   implication / exclusion / complement violations with gross edge `>= 0.05` and `>= 2x spread`
├── VALIDATE:  one family-specific gold set before any broad ontology work
├── SIZE:      Execution-risk-adjusted, hard-capped at `$5` per leg
├── MODULES:   dependency_graph.py, relation_classifier.py, b1_executor.py,
│              b1_monitor.py, relation_cache.py, strategies/b1_templates.py
└── STATUS:    Live-public-data audit found 0 deterministic template pairs in the first 1,000 allowed markets.

CONFIRMATION LAYER (jj_live.py, WIRED):
├── All 6 sources run in parallel when their data planes are active
├── Signals grouped by (market_id, direction)
├── 2+ sources agree → boosted size (quarter-Kelly)
├── LLM alone + res > 12h → standard quarter-Kelly
├── Wallet flow alone + res < 1h → 1/16 Kelly
├── LMSR alone → 1/16 Kelly
├── Signals 5/6 bypass predictive confirmation and route straight to arb execution
├── Structural checks still apply: resolution normalization, VPIN veto, linked-leg integrity, bankroll cap
├── Arb alone → execution-risk sizing, hard-capped at `$5` per leg
└── Telegram: source tag + [CONFIRMED] on multi-source signals

Data stores:
├── paper_trades.json     (position log)
├── metrics_history.json  (cycle metrics)
├── strategy_state.json   (tuning state)
├── bot.db                (SQLite — orders, fills, positions, risk events, execution_stats)
├── data/constraint_arb.db (graph_edges, constraint_violations, capture stats)
├── logs/sum_violation_events.jsonl
└── jj_state.json         (live state; extend with linked_legs for multi-leg arb)
```

---

## 3. Module Inventory (27 Modules, March 7 2026)

### Core Trading Engine
| Module | Purpose |
|--------|---------|
| `bot/jj_live.py` | Autonomous trading loop — bridges signal finding with CLOB order execution. Dublin VPS systemd service. |
| `bot/clob_ws_client.py` | Shared CLOB market-channel client for structural arb book state. HTTP/WebSocket to Polymarket order books. |
| `bot/ws_trade_stream.py` | WebSocket market-depth stream → VPIN + Multi-Level OFI (5-level weighted). |

### Structural Arbitrage (A-6 Guaranteed Dollar)
| Module | Purpose |
|--------|---------|
| `bot/constraint_arb_engine.py` | Resolution-normalized constraint arb engine. YES-sum violation detection, edge scoring. |
| `bot/sum_violation_scanner.py` | Event-based A-6 scanner. Streams violations from Gamma API, maintains watchlist. |
| `bot/a6_sum_scanner.py` | Phase-1 executable YES-sum scanner. Outputs A6MarketSnapshot and A6Opportunity. |
| `bot/a6_executor.py` | Multi-leg state machine (DETECTED → QUOTING → PARTIAL → HEDGED → COMPLETE/ROLLED_BACK). |
| `bot/execution_readiness.py` | Feed, maintenance-window, Builder, neg-risk, and one-leg-loss gating for structural alpha. |
| `bot/neg_risk_inventory.py` | Inventory and safety for neg-risk baskets. ConversionRecord, EventTradability, safety gates. |
| `bot/resolution_normalizer.py` | Resolution normalization across protocols (AP, DDHQ, Court, NWS). NormalizedMarket. |
| `signals/sum_violation/guaranteed_dollar.py` | Cheapest-construction ranker. Compares YES+NO, neg-risk-conversion, and full-basket paths. |

### Dependency Graph (B-1 Templated)
| Module | Purpose |
|--------|---------|
| `bot/dependency_graph.py` | Top-level B-1 pipeline and CLI. CandidatePairGenerator → DepExecutionPlanner → MultiLegAttempt. |
| `bot/b1_monitor.py` | Live monitor for implication/exclusion violations. P(A)<=P(B) and P(A)+P(B)<=1. |
| `bot/b1_executor.py` | Two-leg shadow executor with deterministic rollback. BasketState machine. |
| `bot/relation_classifier.py` | Claude Haiku relation classifier with caching. Outputs: implies, exclusive, complementary, subset, conditional. |
| `bot/relation_cache.py` | Persistent SQLite cache + API cost counters for relation classification. |
| `bot/b1_template_engine.py` | Deterministic template matcher and compatibility-matrix helper for the initial B-1 scope. |
| `strategies/b1_templates.py` | Narrow deterministic family matcher + compatibility-matrix output for initial B-1 scope. |

### Integration & Risk
| Module | Purpose |
|--------|---------|
| `bot/combinatorial_integration.py` | Feature-flagged integration for A-6/B-1 lanes. Loads constraint_arb.db, dep_graph.sqlite. |
| `bot/kill_rules.py` | Six kill criteria: semantic decay, toxicity survival, cost stress, calibration enforcement, signal count, regime decay. |

### Microstructure & Signal Sources
| Module | Purpose |
|--------|---------|
| `bot/lead_lag_engine.py` | Semantic Lead-Lag Arbitrage. Granger causality + LLM semantic verification. Signal #6. |
| `bot/vpin_toxicity.py` | VPIN toxicity detector. FlowRegime: TOXIC (>0.75, pull quotes) / SAFE (<0.25). |
| `bot/wallet_flow_detector.py` | Smart wallet consensus signals. Signal #2. |
| `bot/llm_ensemble.py` | Multi-model estimation: Claude Haiku + GPT-4.1-mini + Groq. Agentic RAG. Signal #1. |
| `bot/lmsr_engine.py` | LMSR Bayesian pricing. Signal #3. Target cycle: 828ms avg. |
| `bot/debate_pipeline.py` | Multi-Agent Debate: GPT-5.1 vs Claude 4.5, Gemini 3 Pro judge. |

### Market Data
| Module | Purpose |
|--------|---------|
| `bot/gamma_market_cache.py` | Async Gamma `/events` cache for market discovery. |

### Specialized Strategies
| Module | Purpose |
|--------|---------|
| `bot/btc_5min_maker.py` | BTC 5m maker bot (T-10s execution). |
| `bot/hft_shadow_validator.py` | HFT shadow validator for Chainlink/Binance basis experiments. |
| `bot/cross_platform_arb.py` | Polymarket-Kalshi arb scanner. Signal #4. |
| `bot/position_merger.py` | Audit and execute Polymarket position merges. |

---

## 4. Strategy Details

### Strategy A: Claude AI Probability Analysis (Primary)

1. Scan 100 active markets from Gamma API (min $100 liquidity)
2. Filter to "actionable" candidates: YES price 10-90%, scored by proximity to 50/50, liquidity, volume
3. Claude Haiku estimates true probability from first principles -- **market price NOT shown** (prevents anchoring)
4. Signal generated if |estimated - market| > edge threshold
5. Quarter-Kelly sizing, maker orders only

**Current parameters:** Edge threshold 5% (lowered from 10% after 0-signal diagnosis), position size quarter-Kelly (avg ~$10 at $75 bankroll), max markets per scan 20, min confidence medium, scan interval 300s.

**Asymmetric thresholds (research-backed):** YES threshold 15%, NO threshold 5%. This exploits the 76% NO win rate vs 56% YES win rate -- prediction markets structurally overprice YES outcomes (favorite-longshot bias).

**Category routing (priority 0-3):**
- Priority 3 (trade): Politics, Weather
- Priority 2 (trade): Economic, Unknown
- Priority 1 (reduced size): Geopolitical
- Priority 0 (skip): Crypto, Sports, Fed Rates

**Calibration layer:** Platt scaling from 532-market backtest. Claude is systematically overconfident on YES side (says 90% -> actual 63%). Calibration map: A=0.5914, B=-0.3977.

### Strategy B: Structural Alpha (A-6 + B-1)

**A-6 (Guaranteed Dollar):** Rank the cheapest executable dollar across neg-risk events. Prefer `YES+NO`, then neg-risk-conversion-equivalent paths, then full baskets. The live-public-data audit found 92 allowed events and 0 constructions below the initial 0.95 cost gate, so the next step is fill/dwell measurement, not more architecture.

**B-1 (Templated Dependency):** Markets with deterministic logical constraints in one narrow family. Broad graph work is paused until density exists. The first 1,000 allowed active markets produced 0 deterministic template pairs in the current audit.

### Position Sizing: Kelly Criterion (INTEGRATED)

Quarter-Kelly sizing implemented and live. Backtest: $75 -> $1,353.18 (1,704% return) vs flat $2: $75 -> $330.60 (341%). Kelly outperformance: +309%.

---

## 5. Performance Data (Backtest -- NOT Live)

### 532-Market Backtest

| Metric | Uncalibrated | Calibrated v2 (Platt) |
|--------|-------------|----------------------|
| Resolved markets tested | 532 | 532 |
| Markets with signal (>5% edge) | 470 (88%) | 372 (70%) |
| Win rate | 64.9% | **68.5%** |
| Brier score | 0.2391 | **0.2171** |
| Buy YES win rate | 55.8% | 63.3% |
| Buy NO win rate | 76.2% | 70.2% |

### Edge Discovery Pipeline (Latest Run)

**Current Recommendation:** REJECT ALL
- 15-min markets observed: 21 (16 resolved)
- 5-min markets observed: 30
- Trade records: 2,615
- Unique wallets tracked: 1,513
- 9 strategies formally rejected, 0 validated

---

## 6. Research Findings That Shape Strategy

1. **Prompt engineering mostly doesn't help** (Schoenegger 2025): Only base-rate-first prompting works. Chain-of-thought, Bayesian reasoning HURT calibration.
2. **Calibration is #1 priority:** Platt-scaling matches superforecasters (Bridgewater AIA).
3. **Ensemble + market consensus beats both alone** (Bridgewater 2025).
4. **Category routing matters:** Politics = best LLM category. Crypto/sports = zero LLM edge.
5. **Taker fees kill taker strategies** (Feb 18, 2026): At p=0.50, need 3.13% edge to break even.
6. **Asymmetric thresholds validated:** 76% NO win rate = documented favorite-longshot bias.
7. **Multi-model ensembles work:** Halawi et al. (2024, NeurIPS).
8. **Superforecaster methods playbook:** Agentic RAG (-0.06 to -0.15 Brier), Platt scaling (-0.02 to -0.05), Multi-run ensemble (-0.01 to -0.03).
9. **Market making mechanics:** Maker orders = 0% fee + 20-25% rebate. Realistic MM returns: $50-200/mo at $1-5K.
10. **Dublin latency confirmed:** 5-10ms to London CLOB (eu-west-2). WebSocket upgrade > server relocation.

---

## 7. Kill Rule Battery

Six automated rejection criteria in `bot/kill_rules.py`:

| Kill Rule | Threshold | Strategies Killed |
|-----------|-----------|-------------------|
| Insufficient Signals | N < 50 (prelim), < 100 (candidate), < 300 (validated) | R1, R3, R5, R2, R7 |
| Negative OOS Expectancy | EV <= 0 after costs | R1, R2, R3, R7, R8 |
| Cost Stress Collapse | Net EV flips sign under fee + 5ms latency | R1, R2, R3, R7, R9, R10 |
| Poor Calibration | Error > 0.2 | R1, R2, R3, R6, R7 |
| Semantic Decay | LLM confidence < 0.3 | Monitoring (none triggered) |
| Regime Performance Decay | Monotonic decline across batches | R2 |

Full rejection details: `research/what_doesnt_work_diary_v1.md`

---

## 8. Key Numbers

| Metric | Value | Source |
|--------|-------|--------|
| Capital deployed | $247.51 Polymarket + $100 Kalshi = **$347.51** | Live accounts |
| Strategy statuses | 7 deployed / 6+2 building / 10 rejected / 8 pre-rejected / 100 pipeline | `research/edge_backlog_ranked.md` |
| Total tracked strategies | **131** | `research/edge_backlog_ranked.md` |
| Current pipeline verdict | **REJECT ALL** (no validated edge yet) | `FastTradeEdgeAnalysis.md` |
| Tests passing | **223** (19 test files) | `bot/tests/` + `tests/` |
| Bot modules | **27** | `bot/*.py` |
| Research dispatches | **82** | `research/dispatches/` |
| Dublin latency to CLOB | ~5-10ms to London (eu-west-2) | `research/LatencyEdgeResearch.md` |

---

## 9. Document Hierarchy

| Document | Role | Update Cadence |
|----------|------|----------------|
| `COMMAND_NODE_v1.1.0.md` | Full context handoff for new AI sessions (single source of truth) | Every flywheel cycle |
| `ProjectInstructions.md` | Quick-start operating context + active priority queue | When priorities change |
| `CLAUDE.md` | JJ persona + prime directive + execution rules | Rarely (process changes only) |
| `FLYWHEEL_STRATEGY.md` | Master strategy, flywheel design, website direction | On strategic shifts |
| `README.md` | Public-facing framing and live status | When metrics update |
| `research/edge_backlog_ranked.md` | Canonical strategy status and ranked pipeline | Every flywheel cycle |
| `FastTradeEdgeAnalysis.md` | Current pipeline verdicts and kill-rule outcomes | After each pipeline run |
| `research/what_doesnt_work_diary_v1.md` | Comprehensive failure documentation | Every flywheel cycle |
| `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md` | Fast-market RTDS maker execution spec | As implementation evolves |

---

## 10. Funded Accounts

| Platform | Balance | Wallet/Key | Status |
|----------|---------|------------|--------|
| Polymarket | $247.51 USDC | Proxy 0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5 | Live, jj-live.service ACTIVE |
| Kalshi | $100.00 USD | Key ID b20ab9fa-b387-4aac-b160-c22d58705935 | API connected, arb scanner built |

### VPS Access

```bash
# Dublin (ACTIVE)
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0
# Bot: /home/ubuntu/polymarket-trading-bot/
# Service: sudo systemctl start jj-live

# Frankfurt (DECOMMISSIONED)
```

---

## 11. Risk Factors

1. **Backtest != live.** 68.5% win rate is backtest. Zero validated live P&L.
2. **0% survival rate on tested strategies.** All 10 strategies failed kill rules.
3. **Competition intensifying.** OpenClaw, Susquehanna, proliferating open-source bots.
4. **Fee structure risk.** Polymarket changed fees Feb 18 and Mar 6. Could change again.
5. **Capital constraints.** $347.51 limits position sizing and diversification.
6. **Structural alpha unproven.** A-6 and B-1 are theoretical. Fill rates and real capture unknown.
7. **Platform risk.** Polymarket CFTC history, crypto-based, regulatory exposure.

---

## 12. What To Paste Into New Sessions

**For any AI session:** Paste this entire document.

**For Claude Code:** Paste `ProjectInstructions.md` (quick-start). CLAUDE.md is auto-loaded.

**For research prompts:** Use templates from `research/dispatches/` with tool tags (CLAUDE_CODE, CLAUDE_DEEP_RESEARCH, CHATGPT_DEEP_RESEARCH, COWORK, GROK).

**SOP:** After completing any significant task, update this COMMAND_NODE (increment version) and review all affected documents for staleness.

---

*Version 1.2.0. Filed by JJ, Instance 6, Parallel Execution Sprint.*
