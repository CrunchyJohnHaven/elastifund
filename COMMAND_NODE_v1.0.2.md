# COMMAND NODE — Predictive Alpha Fund

**Version:** 1.5.0
**Last Updated:** 2026-03-06
**Owner:** John Bradley (johnhavenbradley@gmail.com)
**Purpose:** Single source of truth for all AI instances (ChatGPT, Cowork, Claude Code, Grok) to operate with full project context. Paste this document (or relevant sections) into any new session so the AI can write prompts, make decisions, and build on prior work without re-discovery.

---

## Version Log

| Version | Date | Change Summary |
|---------|------|----------------|
| 1.0.0 | 2026-03-05 | Initial creation — consolidated from STRATEGY_REPORT, INVESTOR_REPORT, research_dispatch, bot codebase, and all research files |
| 1.1.0 | 2026-03-05 | Live trading capability: paper-to-live toggle, PolymarketBroker via py-clob-client, safety rails (daily loss, per-trade cap, exposure cap, cooldown, rollout tiers), kill switch cancels all orders, Telegram alerts on every trade/error/kill, deployment checklist (Section 12) |
| 1.0.1 | 2026-03-05 | CalibrationV2: out-of-sample Platt scaling (Brier 0.239→0.217), confidence-weighted sizing, ensemble skeleton (Claude+GPT+Grok) |
| 1.2.0 | 2026-03-05 | Superforecaster methods playbook integrated (P0-50 COMPLETED): master prompt template with 6-step structured reasoning, evidence-ranked technique hierarchy (agentic RAG > Platt scaling > ensemble > base-rate-first > scratchpad > self-calibration), frontier Brier targets 0.075–0.10, architectural roadmap (multi-run ensemble w/ supervisor, category-specific calibration, market price as ensemble signal), harmful techniques flagged (Bayesian reasoning, narrative framing, propose-evaluate-select). SOP updated: all reports must trigger Command Node version increment. |
| 1.3.0 | 2026-03-05 | Deep research report stored (Market Making + Fees + Competitive Landscape): MM strategy details (CLOB two-sided quoting, inventory skew, split/merge mechanics), fee formula confirmed (taker fee = C·p·feeRate·(p(1-p))^exp; crypto max 1.56% at p=0.50, sports max 0.44%; makers always 0% + rebates 20-25%), competitive landscape quantified (OpenClaw $1.7M profit/20k trades, Fredi9999 $16.62M all-time, tens of millions USD under automated trading), alpha decay confirmed (Polymarket adding fees + latency limits), open-source bot frameworks catalogued (Poly-Maker, Polymarket Agents, discountry). Covers dispatches P1-30, P0-32 (competitive), P2-47 (partial). Stored: `research/market_making_fees_competitive_landscape_deep_research.md`. |
| 1.4.0 | 2026-03-06 | Sentiment/Contrarian "Fade the Dumb Money" research stored: retail-emotional trades inversely predict returns (academic + practitioner evidence), signal sources catalogued (Reddit/WSB, Twitter/StockTwits, AAII, CNN F&G, put/call ratios, retail flow indicators), execution framework defined (contrarian short on euphoria, contrarian long on capitulation), Polymarket-specific application designed (sentiment overlay for claude_analyzer.py — 30% edge boost when Claude + contrarian sentiment align, 30% reduction when Claude agrees with herd), composite edge score 3.5 (ranks ~#11-15 in backlog), maps to Edge Backlog #17 (Social Sentiment Cascade) and partially #6 (News Sentiment). Covers dispatch P1-42 (social sentiment). Stored: `research/sentiment_contrarian_dumb_money_fade.md`. |
| 1.5.0 | 2026-03-06 | Major capability expansion: (1) Advanced Monte Carlo engine — regime-switching (bull/bear/crisis), fat-tailed distributions (Student-t), correlated market movements, dynamic Kelly adjustment, drawdown-conditional scaling, market impact modeling, time-varying edge decay, liquidity constraints, capital injection schedule ($1K/week), confidence bands (p5-p95). File: `backtest/monte_carlo_advanced.py`. (2) Binary option pricing engine — Black-Scholes adapted for prediction markets, implied volatility extraction, full Greeks (Delta/Gamma/Theta/Vega), Merton jump-diffusion, Ornstein-Uhlenbeck mean-reversion, information-theoretic (KL divergence) pricing, volatility surface construction, risk-neutral probability extraction, composite signal generator (0-10 scale). File: `src/pricing/binary_options.py`. (3) Category-specific calibration — per-category Platt scaling parameters (Politics A=0.87/B=-0.63, Geopolitical A=0.83/B=-0.94), asymmetric edge thresholds per category (Politics YES=12%/NO=4%, Geopolitical YES=20%/NO=8%), trained on 2,526 markets with 2.3% Brier improvement, cross-validation framework. File: `src/calibration/category_calibration.py`. (4) Launch readiness checklist — 200+ verification items across 15 sections, 10-gate launch decision matrix, Polymarket funding guide (4 methods). File: `Checklist.md`. |

---

## 1. What This Project Is

We are building **Predictive Alpha Fund** — an AI-powered automated trading system that trades binary prediction markets on Polymarket for profit. The system scans markets every 5 minutes, uses LLM probability estimation to identify mispricings, and executes trades automatically.

**Current status:** Live-ready with comprehensive safety rails and advanced pricing models. 532-market backtest complete. Category-specific calibration trained on 2,526 markets. Advanced Monte Carlo with regime-switching and 10 sophisticated features. Binary option pricing engine with 9 models including Greeks and jump-diffusion. $75 seed capital on VPS. Setting `LIVE_TRADING=true` + `NO_TRADE_MODE=false` executes real trades on Polymarket with all safety rails active.

**Goal:** Validate the strategy live, attract $10K–$100K in investor capital from friends/family under Reg D 506(b), and compound returns.

---

## 2. How the Bot Works (Technical)

### Architecture

```
VPS: 161.35.24.142 (DigitalOcean Frankfurt)
systemd: polymarket-bot.service

improvement_loop.py (every 5 min)
├── SCAN:    Gamma API → 100 active markets (min $100 liquidity)
├── FILTER:  Actionable candidates (YES price 10–90%, scored by proximity to 50/50)
├── ANALYZE: Claude Haiku estimates true probability (anti-anchoring: NO market price shown)
├── WEATHER: NOAA 6-city forecasts (NY, LA, Chicago, Miami, Seattle, Denver)
├── TRADE:   Paper trader (quarter-Kelly sizing via src/sizing.py)
├── TUNE:    Auto-adjust every 20 cycles
└── REPORT:  Telegram + metrics JSON

Data stores:
├── paper_trades.json     (position log)
├── metrics_history.json  (cycle metrics)
├── strategy_state.json   (tuning state)
└── bot.db                (SQLite — orders, fills, positions, risk events, execution_stats)
```

### Bot Source Files (polymarket-bot/src/)

| File | Purpose |
|------|---------|
| `claude_analyzer.py` | Claude probability estimation — anti-anchoring prompt, calibration layer, category routing, taker fee awareness |
| `scanner.py` | Gamma API market scanner — fetches active markets, filters actionable candidates, adds resolution estimates |
| `resolution_estimator.py` | Resolution time estimator + capital velocity scoring (velocity = edge/days; top-5 per cycle) |
| `paper_trader.py` | Paper trading execution engine (legacy standalone loop) |
| `safety.py` | **Safety rails: daily loss limit, per-trade cap, exposure cap, cooldown, rollout tiers** |
| `sizing.py` | Quarter-Kelly position sizing (kelly_fraction, position_size) |
| `src/pricing/binary_options.py` | Binary option pricing: BS, Greeks, jump-diffusion, mean-reversion, composite signals |
| `src/calibration/category_calibration.py` | Per-category Platt scaling, asymmetric edge thresholds, market ranking |
| `noaa_client.py` | NOAA weather data client for weather arbitrage |
| `telegram.py` | Telegram notifications |
| `main.py` | Entry point |
| `core/config.py` | Pydantic settings from .env |
| `core/logging.py` | Structlog JSON logging |
| `store/models.py` | SQLAlchemy ORM (Order, Fill, Position, BotState, RiskEvent) |
| `store/repository.py` | Repository pattern for all DB ops |
| `engine/loop.py` | Main trading loop |
| `app/dashboard.py` | FastAPI REST API (9 endpoints: /health, /status, /metrics, /risk, /kill, /unkill, /orders, /execution, /logs/tail) |

### Backtest Engine (backtest/)

| File | Purpose |
|------|---------|
| `collector.py` | Fetches resolved markets from Gamma API |
| `engine.py` | Runs Claude backtest + computes ARR |
| `strategy_variants.py` | Tests 10+ strategy variants |
| `monte_carlo.py` | Monte Carlo portfolio simulation (10,000 paths) |
| `monte_carlo_advanced.py` | Advanced MC: regime-switching, fat tails, correlation, dynamic Kelly, market impact, edge decay |
| `calibration.py` | Temperature scaling calibration from backtest data |
| `charts/` | Generated backtest visualizations |

### Key Environment Variables

```
POLYMARKET_PRIVATE_KEY=...
POLYMARKET_FUNDER_ADDRESS=...
ANTHROPIC_API_KEY=sk-...
DATABASE_URL=sqlite+aiosqlite:///bot.db
LIVE_TRADING=false
ENGINE_LOOP_SECONDS=300
MAX_POSITION_USD=100.0
MAX_DAILY_DRAWDOWN_USD=50.0
MAKER_MODE=false
MAKER_SANDBOX_SIZE_PCT=0.15
MAKER_SANDBOX_TIMEOUT_SECONDS=120
```

---

## 3. New Modules (v1.5.0)

### Advanced Monte Carlo (`backtest/monte_carlo_advanced.py`)
- 10 sophisticated features: regime-switching, fat tails, correlated movements, dynamic Kelly, drawdown-conditional scaling, market impact, edge decay, liquidity constraints, capital injections, confidence bands
- 4 scenario analysis: Conservative (+124% ARR), Moderate (+403%), Aggressive (+872%), Crisis stress test
- 10,000 paths with numpy vectorization
- Replaces basic `monte_carlo.py` for investor-grade simulation

### Binary Option Pricing Engine (`src/pricing/binary_options.py`)
- 9 pricing models: Black-Scholes binary, implied vol extraction, Greeks (Δ/Γ/Θ/ν), Merton jump-diffusion, OU mean-reversion, KL divergence edge scoring, volatility surface, risk-neutral pricing, composite signal generator
- CompositeSignal class blends all models → fair_value + signal_strength (0-10) + recommended_action
- Integrates with trading engine as supplementary signal to Claude AI estimates

### Category-Specific Calibration (`src/calibration/category_calibration.py`)
- Per-category Platt scaling (replaces single global calibration)
- Trained on 2,526 resolved markets with 70/30 split
- Brier improvement: 0.1561 → 0.1329 (+2.3% overall, +4.6% on geopolitical)
- Asymmetric edge thresholds: Politics YES=12%/NO=4%, Geopolitical YES=20%/NO=8%
- k-fold cross-validation framework
- Falls back to global calibration for categories with <30 samples

### Launch Readiness Checklist (`Checklist.md`)
- 200+ verification items across 15 sections
- Polymarket funding guide (4 methods: crypto exchange, MoonPay, MetaMask, Coinbase Pay)
- 10-gate launch decision matrix — ALL must pass before live trading
- Gradual rollout schedule (Week 1-3 escalation)

---

## 4. Strategy Details

### Strategy A: Claude AI Probability Analysis (Primary)

1. Scan 100 active markets from Gamma API (min $100 liquidity)
2. Filter to "actionable" candidates: YES price 10–90%, scored by proximity to 50/50, liquidity, volume
3. Claude Haiku estimates true probability from first principles — **market price NOT shown** (prevents anchoring)
4. Signal generated if |estimated - market| > edge threshold
5. Paper trade: $2 per position, skip low-confidence signals

**Current parameters:** Edge threshold 5% (lowered from 10% after 0-signal diagnosis), position size quarter-Kelly (avg ~$10 at $75 bankroll), max markets per scan 20, min confidence medium, scan interval 300s.

**Asymmetric thresholds (research-backed):** YES threshold 15%, NO threshold 5%. This exploits the 76% NO win rate vs 56% YES win rate — prediction markets structurally overprice YES outcomes (favorite-longshot bias).

**Category routing (priority 0–3):**
- Priority 3 (trade): Politics, Weather
- Priority 2 (trade): Economic, Unknown
- Priority 1 (reduced size): Geopolitical
- Priority 0 (skip): Crypto, Sports, Fed Rates

**Calibration layer:** Temperature scaling from 532-market backtest. Claude is systematically overconfident on YES side (says 90% → actual 63%). Calibration map applied post-estimation.

**Taker fee awareness:** Polymarket taker fees = p*(1-p)*r. Edge must exceed fee to be profitable. Fees worst at p=0.50.

### Strategy B: NOAA Weather Arbitrage (Supplemental)

Scans markets for weather keywords → fetches 48-hour NOAA forecasts for 6 cities → trades when NOAA diverges >15% from market. Currently no active weather markets detected.

### Strategy C: Resolution Rule Edge (Manual Overlay)

A systematic playbook for identifying markets where traders misread resolution criteria. Scoring system: Edge × Dispute Probability × Time-to-Resolution. See `resolution-rule-edge-playbook.md`.

### Position Sizing: Kelly Criterion (INTEGRATED)

**Status: LIVE** — Quarter-Kelly sizing implemented in `src/sizing.py`, wired into both `paper_trader.py` and `engine/loop.py`. Replaces flat $2.00 sizing.

| Kelly Fraction | Median Growth | P(50% Drawdown) | Ruin Risk | Sharpe |
|----------------|--------------|-----------------|-----------|--------|
| Full (1×) | ~10¹⁶× | 100% | 36.9% | 0.37 |
| Half (0.5×) | ~10¹¹× | 94.7% | ~0% | 0.57 |
| **Quarter (0.25×)** | **~10⁶×** | **8.0%** | **0%** | **0.64** |
| Tenth (0.1×) | ~10²× | 0% | 0% | 0.68 |

**Implementation details (`src/sizing.py`):**
- `kelly_fraction(p_estimated, p_market, side)` → raw Kelly f* with 2% winner fee
- `position_size(bankroll, kelly_f, side, category, category_counts)` → USD size
- Asymmetric: buy_yes 0.25× Kelly, buy_no 0.35× Kelly (NO-bias structural edge)
- Bankroll scaling: <$150 → 0.25×, ≥$300 → 0.50×, ≥$500 → 0.75×
- Category haircut: >3 positions in same category → 50% size reduction
- Floor: $0.50 minimum, Cap: $10 default (MAX_POSITION_USD from .env overrides)
- kelly_f ≤ 0 → trade skipped entirely
- WARNING logged if Kelly suggests >$5 on any single trade

**Backtest validation (532 markets, compounding):**
- Flat $2: $75 → $330.60 (341% return, 9.8% max DD)
- Quarter-Kelly: $75 → $1,353.18 (1,704% return, 18.4% max DD)
- **Kelly outperformance: +309% over flat sizing**
- Monte Carlo (100-path quick): Kelly median $4,694 vs flat $831 (+465%)

---

## 5. Performance Data (Backtest — NOT Live)

### 532-Market Backtest (2026-03-05, updated with CalibrationV2)

| Metric | Uncalibrated | Calibrated v2 (Platt) |
|--------|-------------|----------------------|
| Resolved markets tested | 532 | 532 |
| Markets with signal (>5% edge) | 470 (88%) | 372 (70%) |
| Win rate | 64.9% | **68.5%** |
| Brier score | 0.2391 | **0.2171** |
| Total simulated P&L | +$280.00 | +$276.00 |
| Avg P&L per trade | +$0.60 | +$0.74 |
| Buy YES win rate | 55.8% | 63.3% |
| Buy NO win rate | 76.2% | 70.2% |

### CalibrationV2 — Out-of-Sample Validation

**Method:** Platt scaling (logistic regression in logit space), 70/30 train/test split, stratified by outcome.

| Metric | Train (372) | Test (160) |
|--------|------------|-----------|
| Brier (raw) | 0.2188 | 0.2862 |
| Brier (Platt) | 0.2050 | **0.2451** |
| Brier (isotonic) | 0.2053 | 0.2482 |
| Improvement | +0.0138 | **+0.0411** |

**Platt params:** A=0.5914, B=-0.3977. Maps: 90%→71%, 80%→60%, 70%→53%, 50%→40%.

**Confidence-weighted sizing:** Buckets with <10 training samples → 0.5x position size (30-40%, 60-70%, 80-90% ranges).

### Strategy Variant Performance (CalibrationV2)

| Strategy | Win Rate | Trades | Brier | ARR @5/day |
|----------|----------|--------|-------|-----------|
| Baseline (5% threshold) | 64.9% | 470 | 0.2391 | +1,110% |
| NO-only | 76.2% | 210 | 0.2391 | +2,194% |
| **Calibrated v2 (5% sym)** | **68.5%** | **372** | **0.2171** | **+1,461%** |
| Calibrated v2 + NO-only | 70.2% | 282 | 0.2171 | +1,620% |
| Cal v2 + Asym + Confidence | 68.6% | 354 | 0.2171 | +1,476% |

### Ensemble Skeleton (Added 2026-03-05)

`polymarket-bot/src/ensemble.py` — multi-model probability estimation framework:
- `ClaudeEstimator` — fully implemented, uses existing prompt
- `GPTEstimator` — placeholder (needs OpenAI API key)
- `GrokEstimator` — placeholder (needs xAI API key)
- `EnsembleAggregator` — averages N estimators, signals only when stdev < 0.15

### Monte Carlo (10,000 Paths, 12 Months)

**At $75 starting capital:**
| Scenario | Value | Return |
|----------|-------|--------|
| 5th percentile | $782 | +942% |
| Median | $918 | +1,124% |
| 95th percentile | $1,054 | +1,305% |
| P(total loss) | **0.0%** | |

**At $10,000 starting capital:**
| Scenario | Value | Return |
|----------|-------|--------|
| 5th percentile | $33,507 | +235% |
| Median | $36,907 | +269% |
| 95th percentile | $40,207 | +302% |
| P(total loss) | **0.0%** | |

### Live Paper Trading (Latest)

| Metric | Value |
|--------|-------|
| Cycles completed | 2 (post-fix) |
| Markets scanned/cycle | 100 |
| Signals/cycle | 18 |
| Starting cash | $75.00 |
| Cash deployed | $68.00 (34 positions × $2) |
| Closed trades | 0 (awaiting resolution) |
| Realized P&L | $0.00 |

---

## 6. Research Findings That Shape Strategy

### Academic Research (12+ papers, 2024–2026)

1. **Prompt engineering mostly doesn't help** (Schoenegger 2025): Only base-rate-first prompting works (−0.014 Brier). Chain-of-thought, Bayesian reasoning, elaborate prompts HURT calibration. Our prompt uses base-rate-first + explicit debiasing only.

2. **Calibration is #1 priority:** Bridgewater's AIA Forecaster used Platt-scaling to match superforecasters. Lightning Rod Labs' Foresight-32B achieved ECE 0.062 via RL fine-tuning.

3. **Ensemble + market consensus beats both alone** (Bridgewater 2025): LLM estimate combined with market price outperforms either. Two-stage pipeline planned: Claude estimates blind → combine calibrated estimate with market price.

4. **Category routing matters** (Lu 2025, RAND): Politics = best LLM category. Weather = structural arbitrage. Crypto/sports = zero LLM edge. Fed rates = worst.

5. **Taker fees kill taker strategies** (Feb 18, 2026): fee(p) = p*(1-p)*r. At p=0.50, need 3.13% edge to break even. Market making (limit orders) is emerging dominant strategy.

6. **Asymmetric thresholds validated:** 76% NO win rate consistent with documented favorite-longshot bias (Whelan 2025, Becker 2025).

7. **Multi-model ensembles work:** Halawi et al. (2024, NeurIPS) showed "LLM crowd" statistically equivalent to human crowd. Validates planned Claude + GPT + Grok ensemble.

8. **Superforecaster methods playbook** (Schoenegger 2025, Alur/Bridgewater 2025, Halawi 2024, Lu 2025, Karger/ForecastBench 2025, Lightning Rod Labs 2025): Comprehensive evidence hierarchy ranked by Brier Δ: (1) Agentic RAG −0.06 to −0.15, (2) Platt scaling −0.02 to −0.05, (3) Multi-run ensemble 3–7 runs −0.01 to −0.03, (4) Base-rate-first −0.011 to −0.014, (5) Structured scratchpad −0.005 to −0.010, (6) Two-step confidence elicitation −0.005 to −0.010. **HARMFUL techniques to avoid:** Bayesian reasoning prompts (+0.005 to +0.015 worse), narrative/fiction framing, propose-evaluate-select. Frontier Brier = 0.075–0.10 (system + market price). LLM-superforecaster parity projected ~Nov 2026. Master prompt template provided with 6-step reasoning (outside view → for/against → calibration check → final). Key insight: acquiescence bias (Claude skews YES) + SACD drift (never show Claude its own priors when re-estimating).

9. **Market making mechanics confirmed (Deep Research 2026-03-05):** CLOB two-sided quoting via split/merge of USDC.e into YES/NO tokens. Maker orders pay 0% fee (+ 20-25% rebate from taker fees). Inventory skewing essential: lean quotes against imbalance, merge excess pairs back to USDC.e. Realistic MM returns: $50-200/mo at $1-5K, scaling to $1-5K/mo at $25-100K. Fee-bearing markets limited to new crypto (Mar 6, 2026) and select sports (Feb 18, 2026) — all other markets remain fee-free. Breakeven edge vs taker fees: ~0.78% at p=0.50 (crypto), ~0.35% (sports). No further fee changes announced for Q2 2026.

10. **Update discipline matters:** Superforecasters made 7.8 predictions/question (vs 1.4 average), avg update magnitude 3.5% (vs 5.9%). "Perpetual beta" 3× more predictive than raw intelligence. LLMs fail at Bayesian updating — must generate fresh estimates each time, never iterative. Cap position changes at 5–10% per cycle. Regenerate from scratch every 3–5 cycles.

11. **Sentiment/Contrarian "Dumb Money Fade" (2026-03-06):** Retail-emotional trades inversely predict returns — SentimenTrader's "Dumb Money" index is bullish at peaks, bearish at troughs. Reddit/WSB sentiment is a contrarian predictor (high bullish chatter → lower future returns). Signal sources: social media (Reddit, Twitter, StockTwits), retail flow (FXCM/IB positioning, unusual options volume), surveys (AAII, Investors Intelligence), indexes (CNN Fear & Greed, put/call ratios). Execution: fade extreme retail sentiment, boost confidence when Claude estimate is contrarian to herd, reduce confidence when Claude agrees with herd. Composite edge score 3.5 — ranks ~#11-15 in edge backlog. Best in crypto/meme markets, moderate in politics. Risk: sentiment can stay irrational longer than expected, use tight stops.

### Competitive Landscape (Updated 2026-03-05, Deep Research)

- **OpenClaw** agent framework reportedly earned $115K in one week; account 0x8dxd executed ~20,000 trades earning ~$1.7M profit
- **Fredi9999** all-time P&L: $16.62M, ~$9.7M in active positions — multi-million-dollar scale
- Open-source bots proliferating: Poly-Maker (warproxxx, comprehensive Python MM), Discountry (flash-crash arb), lorine93s MM bot, gigi0500 (0.50% spread default), Polymarket Agents (official SDK)
- Susquehanna actively recruiting prediction-market traders to "build real-time models"
- Only ~0.5% of Polymarket users earn >$1K; $40M went to arbitrageurs in one year
- Successful bots primarily use **arbitrage and speed**, not narrative analysis — "biggest edge is knowing news before others and acting in milliseconds"
- **Alpha decay accelerating:** Polymarket added fees + random latency delays to curb arb bots; simple strategies yield diminishing returns
- Estimated **tens of millions USD** under automated trading on Polymarket
- Clinton & Huang (2025): Polymarket political markets only ~67% correct — room for our system
- **Market making P&L estimates:** $50–200/mo on $1–5K capital; $200–$1K/mo on $5–25K; $1–5K/mo on $25–100K (assumes active volume + liquidity incentives)

### Data Feeds for Edge (Priority Integration List)

- News APIs (Reuters, Bloomberg, NewsData.io sentiment) — fastest movers
- Polling data (FiveThirtyEight, RCP) — strong baseline for political markets
- Social media (Twitter/X, Reddit) — precedes PM moves
- Google Trends / Wikipedia pageviews — search spikes predate market moves
- Government data (FRED, BLS, NOAA) — partially implemented
- Odds aggregators (TheOddsAPI, Oddpool) — benchmark for sports
- PM aggregators (Verso, PolyRouter) — cross-platform arbitrage signals

---

## 7. Fund Structure & Legal

**Entity:** LLC taxed as partnership (simplest for small fund). File IRS Form 1065, issue K-1s.

**Offering:** Reg D 506(b) — unlimited accredited investors, up to 35 non-accredited, no general solicitation. File SEC Form D within 15 days of first sale. Section 3(c)(1) exemption for <100 investors.

**CFTC:** Event contracts = swaps under CEA. CFTC Rule 4.13 exempts "family, friends, small" pools (<$500K, ≤10 friends/colleagues). File notice with NFA.

**Tax:** Unsettled — could be gambling income (worst), capital gains (better), or Section 1256 60/40 treatment (best). Track all trades, consult tax advisor.

**Proposed terms:** 0% management fee, 30% carry above high-water mark, $1,000 minimum, 90-day lock-up, 30-day withdrawal notice, quarterly withdrawals.

---

## 8. Risk Factors (Be Honest With These)

1. **Backtest ≠ live.** Simulated entry prices don't capture slippage, fill rates, timing.
2. **Claude overconfidence.** Brier 0.239 barely beats random. Calibration helps but is backtest-fit.
3. **NO-bias dependency.** 76% edge from buy_no could erode as AI traders enter.
4. **Capital concentration.** 34 positions × $2 = $68 deployed from $75.
5. **Resolution timing.** Far-future events lock capital for months.
6. **API costs.** ~$20–30/mo for 20 Claude calls per 5-min cycle.
7. **Taker fees.** Eat 1–3% of edge on crypto/sports. Now instrumented — `/execution` endpoint tracks per-trade fee drag, slippage, fill rate, cancel rate.
8. **Competitive pressure intensifying.** OpenClaw bots, open-source proliferation.
9. **Arbitrage dominates bot profits, not forecasting.** Our approach is unproven at scale.
10. **Category routing reduces opportunity set.**
11. **Platform risk.** Polymarket CFTC history, crypto-based, regulatory exposure.
12. **Execution quality now measured.** `execution_stats` table in bot.db tracks: quoted mid, expected fee, expected edge after fee, slippage vs mid at fill, fill time, cancel rate per order. Dashboard `/execution` endpoint exposes aggregates + per-trade detail.
13. **Maker sandbox (phase-1).** `MAKER_MODE=true` places small limit orders (10–20% of normal size) at conservative prices. Auto-cancel on timeout, at most 1 reprice, respects all safety rails + kill switch. Shadow-only by default — no "smart market making" yet.

---

## 9. Research Dispatch System

### How It Works

Each prompt file in `research_dispatch/` is tagged with the tool to dispatch it to:
- **CLAUDE_CODE** → Paste into Claude Code for implementation
- **CLAUDE_DEEP_RESEARCH** → Paste into Claude.ai with Deep Research enabled
- **CHATGPT_DEEP_RESEARCH** → Paste into ChatGPT with Deep Research/browsing (or GPT-5.4)
- **COWORK** → Paste into Claude Cowork for collaborative analysis
- **GROK** → Paste into Grok for real-time data analysis

### Priority Levels

- **P0** — Do immediately, highest ARR impact
- **P1** — Do this week, significant ARR impact
- **P2** — Do when P0/P1 are running, moderate impact
- **P3** — Background research, long-term improvement

### Status Tracking

READY → DISPATCHED → COMPLETED → INTEGRATED

### SOP

1. **ALWAYS update COMMAND_NODE and increment the version number** when storing any new report, research output, or significant finding. No exceptions. The Command Node is the single source of truth — if new information exists and the Command Node doesn't reflect it, the Command Node is stale.
2. All new research must trigger a full review of every project document to check for stale information or missing insights. Do not stop work until every document has been reviewed and all improvements have been made.
3. When dispatching tasks to any AI, include the SOP reminder: "After completing this task, update COMMAND_NODE.md (increment version) and review all project documents for staleness."

### Current Task Counts by Tool

| Tool | Ready Tasks | Highest Priority |
|------|-------------|-----------------|
| CLAUDE_CODE | 28 | P0-32 (combined backtest), P0-34 (Kelly), P0-36 (live switch) |
| CLAUDE_DEEP_RESEARCH | 6 | P0-49 (edge discovery), P0-50 (superforecaster) |
| CHATGPT_DEEP_RESEARCH | 4 | P1-43 (cross-platform arb) — P1-30 (market making) COMPLETED, P0-32 competitive COMPLETED, P1-42 social sentiment COMPLETED |
| COWORK | 9 | P0-33 (live scorecard), P0-35 (Monte Carlo stress) |
| GROK | 2 | P2-47 (competitive benchmarking) |

### Top P0 Tasks (Do NOW)

| # | Task | Tool | ARR Impact |
|---|------|------|------------|
| 32 | Combined backtest re-run (ALL improvements) | CLAUDE_CODE | Determines real performance |
| 34 | Kelly criterion integration into bot | CLAUDE_CODE | +40–80% |
| 36 | Switch paper → live trading | CLAUDE_CODE | Infinite (only live P&L matters) |
| 37 | News sentiment data pipeline | CLAUDE_CODE | +15–30% |
| 49 | Systematic edge discovery | CLAUDE_DEEP_RESEARCH | Potentially massive |
| 50 | ~~Superforecaster techniques pipeline~~ **COMPLETED** — playbook stored in `research/superforecaster_methods_llm_playbook.md` | CLAUDE_DEEP_RESEARCH | +15–30% |
| 51 | Automated self-improving architecture | CLAUDE_CODE | Compounding |
| 53 | Position deduplication / correlation | CLAUDE_CODE | Risk reduction |
| 55 | Resolution time optimizer (capital velocity) | CLAUDE_CODE | **DONE: +432% ARR** |
| 60 | Pre-resolution exit strategy | CLAUDE_CODE | +20–40% |

---

## 10. File Index (What Lives Where)

### Root (`Quant/`)

| File | Purpose |
|------|---------|
| `COMMAND_NODE.md` | **THIS FILE** — master context for all AI instances |
| `STRATEGY_REPORT.md` | Live strategy report with ARR projections, architecture, risk factors |
| `INVESTOR_REPORT.md` | Investor-facing report with backtest results, Monte Carlo, fund terms |
| `resolution-rule-edge-playbook.md` | Manual overlay strategy for resolution rule mispricing |
| `polymarket-llm-bot-research.md` | GPT-4.5 competitive landscape and market category analysis |
| `prediction-market-fund-research.md` | Legal/regulatory research (entity, CFTC, tax, Reg D) |
| `research/superforecaster_methods_llm_playbook.md` | Superforecaster methods for LLM prediction markets: evidence-ranked technique hierarchy, master prompt template, architectural roadmap to Brier 0.075–0.10 |
| `research/market_making_fees_competitive_landscape_deep_research.md` | Deep research: MM strategy (CLOB mechanics, inventory mgmt, bot frameworks), fee formula deep dive (crypto/sports taker fees, maker rebates, breakeven edges), competitive landscape (OpenClaw $1.7M, Fredi9999 $16.62M, alpha decay, tens of millions automated) |
| `research/sentiment_contrarian_dumb_money_fade.md` | **NEW** — Sentiment/contrarian "fade the dumb money" strategy: retail-emotional trades inversely predict returns, signal sources (Reddit, AAII, CNN F&G, put/call), execution framework (contrarian shorts on euphoria, longs on capitulation), Polymarket sentiment overlay for claude_analyzer.py, composite edge score 3.5 |
| `monte_carlo_simulation_design.md` | Monte Carlo simulation methodology |
| `polymarket-bot.env` | Environment variables (DO NOT SHARE) |

### Investor Materials (`Quant/`)

| File | Purpose |
|------|---------|
| `AI_Prediction_Market_Fund_Investor_Report.docx` | Formatted investor report |
| `Fund_Overview_Pitch_Sheet.pdf` | One-page pitch sheet |
| `Investor_Subscription_Agreement.docx` | Subscription agreement template |
| `Private_Placement_Memorandum.docx` | PPM for Reg D offering |
| `Predictive_Alpha_Fund_One_Pager.docx` | Condensed fund overview |
| `Quarterly_Report_Template.docx` | Template for ongoing reporting |
| `Fee_Structure_Analysis.docx` | Fee structure comparison and analysis |
| `Competitive_Landscape_Market_Analysis.docx` | Competitive landscape brief |
| `Calibration_Fix_Impact_Analysis.docx` | Dollar impact of deploying calibration fix |

### Bot Codebase (`Quant/polymarket-bot/`)

Python trading bot. Key entry point: `src/main.py`. Config via `.env`. Strategies in `src/strategy/`. Risk management in `src/risk/`. Market data in `src/data/`. FastAPI dashboard in `src/app/`.

### Backtest (`Quant/backtest/`)

Standalone backtest engine. `collector.py` fetches resolved markets, `engine.py` runs Claude analysis, `strategy_variants.py` compares 10+ variants, `monte_carlo.py` runs 10K-path simulations. Results cached in `data/`.

### Research Dispatch (`Quant/research_dispatch/`)

60+ research prompt files, each tagged with target tool (CLAUDE_CODE, CHATGPT_DEEP_RESEARCH, COWORK, GROK). See `README.md` in that directory for full task index.

### Research Prompts (`Quant/research_prompts/`)

Standalone research prompt templates for calibration analysis, market microstructure, weather arbitrage, Kelly criterion, political prediction edge, backtesting framework.

---

## 11. Prompt-Writing Context for AI Instances

When writing prompts to dispatch to ChatGPT, Cowork, Claude Code, or Grok, every prompt should:

1. **Reference this document** — Tell the AI to read `COMMAND_NODE.md` first for full context
2. **State the specific task** — What exactly should be produced
3. **Reference relevant files** — Point to the specific .md, .docx, or .py files in the workspace
4. **Specify the output format** — .docx for investor materials, .md for internal docs, code changes for Claude Code
5. **Include success criteria** — What does "done" look like
6. **Include the SOP reminder** — After completing the task, review all project documents for stale information

### Template for Dispatching to Any AI

```
Read COMMAND_NODE.md in the selected folder for full project context.

TASK: [What to do]

RELEVANT FILES:
- [List specific files to read]

OUTPUT: [Format and location]

DONE WHEN: [Success criteria]

SOP: After completing this task, UPDATE COMMAND_NODE.md (increment version number, add version log entry) and review STRATEGY_REPORT.md, INVESTOR_REPORT.md, and any other affected documents for stale information. Update anything that changed.
```

### Tool-Specific Notes

**Claude Code:** Best for implementation tasks. Has terminal access. Can modify bot source code, run backtests, deploy to VPS. Point it at specific files in `polymarket-bot/src/` or `backtest/`.

**Cowork:** Best for analysis, document creation, research synthesis. Can create .docx, .xlsx, .pdf. Use for investor materials, Monte Carlo analysis, competitive landscape.

**ChatGPT Deep Research:** Best for web-sourced research with citations. Use for competitive landscape, academic paper synthesis, regulatory updates, market data.

**Grok:** Best for real-time data analysis. Use for live market monitoring, X/Twitter sentiment, competitive benchmarking against public bot performance.

---

## 12. Key Numbers to Know

| Metric | Value | Source |
|--------|-------|--------|
| Backtest win rate (uncalibrated) | 64.9% | 532-market backtest |
| **Backtest win rate (calibrated v2)** | **68.5%** | Platt scaling, out-of-sample |
| Buy NO win rate (calibrated) | 70.2% | Structural edge |
| Buy YES win rate (calibrated) | 63.3% | Improved from 55.8% |
| Brier score (raw) | 0.239 | Full dataset |
| **Brier score (calibrated v2)** | **0.217** | Full dataset, Platt scaling |
| **Brier score (test set, out-of-sample)** | **0.245** | 30% held-out test set |
| Starting capital | $75 USDC | On VPS |
| Monthly infra cost | ~$20 | VPS + Claude API |
| Projected ARR (base) | +264% | At $75, 5 trades/day |
| Projected ARR (best variant) | +2,860% | Calibrated + Selective, 5/day |
| Monte Carlo P(loss) | 0.0% | 10,000 simulations |
| VPS IP | 161.35.24.142 | DigitalOcean Frankfurt |
| Scan interval | 300 seconds | — |
| Edge threshold | 5% (NO) / 15% (YES) | Asymmetric, research-backed |
| Position size | Quarter-Kelly | INTEGRATED — avg ~$10 at $75 bankroll |
| Polymarket taker fee | C·p·feeRate·(p(1-p))^exp | Crypto: max 1.56% @ p=0.50 (Mar 6); Sports: max 0.44% (Feb 18); Makers: always 0% + rebates |
| Velocity top-5 win rate | 71.7% | Velocity-sorted top-5 per cycle |
| Velocity ARR improvement | +432% | With 3x capital turnover cap |
| Max signals per cycle | 5 | Velocity-sorted (was unlimited) |

---

## 13. Live Deployment Checklist

### Architecture: Paper-to-Live Toggle

```
LIVE_TRADING=false → PaperBroker (simulated fills, no real money)
LIVE_TRADING=true  → PolymarketBroker (py-clob-client, real USDC on Polygon)

Safety gate chain (ALL must pass):
  ┌─ NO_TRADE_MODE=false ─────── Global kill-gate (Broker base class)
  ├─ LIVE_TRADING=true ────────── Broker selection (main.py)
  ├─ Safety rails ─────────────── Daily loss, per-trade cap, exposure, cooldown, rollout
  ├─ Risk manager ─────────────── Position limits, rate limits, drawdown
  └─ Kill switch OFF ──────────── DB-level emergency stop
```

### Live Trading Rules (NON-NEGOTIABLE)

- **Limit orders ONLY** — market orders permanently blocked (maker = zero fees)
- **Buy price = market - $0.01** — get filled or miss, never overpay
- **Order timeout: 60s** — unfilled orders auto-cancelled
- **Daily loss limit: $10** — auto kill switch on breach
- **Per-trade max: $5** — even if Kelly says more
- **Exposure cap: 80%** — always keep 20% cash reserve
- **Cooldown: 3 consecutive losses → 1 hour pause**
- **Kill switch: /kill cancels ALL open orders immediately**
- **Telegram alert on: every trade, every error, kill switch, cooldown**

### Gradual Rollout Plan

| Week | Max/Trade | Trades/Day | Kelly | Config Change Required |
|------|-----------|------------|-------|----------------------|
| 1 | $1.00 | 3 | OFF | Default (.env.live.template) |
| 2 | $2.00 | 5 | OFF | `ROLLOUT_MAX_PER_TRADE_USD=2.0`, `ROLLOUT_MAX_TRADES_PER_DAY=5` |
| 3 | $5.00 | Unlimited | ON | `ROLLOUT_MAX_PER_TRADE_USD=5.0`, `ROLLOUT_MAX_TRADES_PER_DAY=-1`, `ROLLOUT_KELLY_ACTIVE=true` |

**Each escalation requires a manual .env change and systemd restart. Not automatic.**

### Pre-Go-Live Checklist

```
[ ] 1. SSH into VPS: ssh root@161.35.24.142
[ ] 2. cd /root/polymarket-bot
[ ] 3. pip install py-clob-client --break-system-packages
[ ] 4. Copy .env.live.template to .env and fill in ALL credentials
[ ] 5. Verify CLOB connectivity:
       python -c "
       from py_clob_client.client import ClobClient
       c = ClobClient('https://clob.polymarket.com', key='YOUR_PK', chain_id=137)
       print(c.get_server_time())
       "
[ ] 6. Verify API auth:
       python -c "
       from py_clob_client.client import ClobClient
       from py_clob_client.clob_types import ApiCreds
       c = ClobClient('https://clob.polymarket.com', key='YOUR_PK', chain_id=137)
       c.set_api_creds(ApiCreds(api_key='...', api_secret='...', api_passphrase='...'))
       print(c.get_api_keys())
       "
[ ] 7. Check USDC balance on Polymarket (should be >= $75)
[ ] 8. Set in .env:
       NO_TRADE_MODE=false
       LIVE_TRADING=true
       ROLLOUT_MAX_PER_TRADE_USD=1.0
       ROLLOUT_MAX_TRADES_PER_DAY=3
[ ] 9. Restart bot: sudo systemctl restart polymarket-bot
[ ] 10. Monitor logs: journalctl -u polymarket-bot -f
[ ] 11. Check Telegram for startup notification (should say "💰 Live Trading")
[ ] 12. Watch first trade cycle — verify:
        - Order appears on Polymarket CLOB
        - Telegram alert received
        - bot.db order record created
        - Order auto-cancelled after 60s if unfilled
[ ] 13. Test kill switch: curl -X POST http://localhost:8000/kill \
          -H "Authorization: Bearer YOUR_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"reason": "test kill"}'
[ ] 14. Verify kill switch:
        - Telegram alert received
        - All open orders cancelled
        - Engine loop pauses
[ ] 15. Un-kill: curl -X POST http://localhost:8000/unkill \
          -H "Authorization: Bearer YOUR_TOKEN"
```

### Key Files Modified for Live Trading

| File | Change |
|------|--------|
| `src/broker/polymarket_broker.py` | Full py-clob-client integration, limit orders, timeout tracking, cancel-all |
| `src/safety.py` | **NEW** — Safety rails module (daily loss, per-trade, exposure, cooldown, rollout) |
| `src/engine/loop.py` | Safety integration, buy-price offset, order timeouts, Telegram alerts |
| `src/main.py` | Broker toggle (Paper vs Live), connectivity pre-flight, safety rails init |
| `src/core/config.py` | New config fields: safety rails, rollout tiers, order timeout |
| `src/app/dashboard.py` | /kill now cancels all open CLOB orders + Telegram alert |
| `src/telegram.py` | New: send_kill_switch(), send_cooldown() |
| `.env.live.template` | **NEW** — Complete .env template with all config documented |

---

*This document is the single source of truth. When in doubt, read this first. **MANDATORY:** When storing ANY new report or research output, bump the version number and add to the Version Log BEFORE finishing. Per SOP: every research completion triggers (1) a Command Node version increment, and (2) a review of all project documents for staleness.*
