# Replit Build Prompt — Predictive Alpha Fund: Open-Source Dashboard

## What to Build

Build a **badass, dark-mode, real-time trading dashboard** for an AI-powered prediction market trading system called **Predictive Alpha Fund**. This is a public-facing web app that open-sources our entire methodology, research, backtesting results, and (optionally) live system metrics. Think Bloomberg terminal meets research paper meets open-source project page.

**Stack:** Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts or D3 for charts, Framer Motion for animations. Dark mode by default with an optional light toggle.

**Deployment:** Replit with a custom domain. Should be fast, responsive, mobile-friendly.

---

## Design Philosophy

- **Dark mode first.** Deep blacks (#0a0a0a), charcoal grays, with electric accent colors (green for profit, red for loss, cyan/blue for neutral data, amber for warnings).
- **Data-dense but not cluttered.** Think Bloomberg terminal: lots of information, but organized in clear grid panels.
- **Animated number counters** for key metrics (count up on scroll-into-view).
- **Glassmorphism cards** with subtle borders and backdrop blur.
- **Monospace fonts** for numbers/data (JetBrains Mono or similar). Clean sans-serif (Inter) for prose.
- **Subtle grid background** pattern on hero sections.
- **Smooth scroll** between sections. Sticky navigation.
- **Code blocks** styled like VS Code (for methodology sections).
- **"Fellow enthusiasts" energy** — technical, transparent, not salesy. We're sharing what we've built, not selling snake oil.

---

## Page Structure

### Page 1: Dashboard (Home — `/`)

The landing page IS the dashboard. No marketing fluff. You land directly on live-ish data.

#### Hero Section
- Large title: **"Predictive Alpha Fund"** with a subtle animated gradient underline
- Subtitle: *"An AI-powered prediction market trading system. Open-source methodology. Real data."*
- Three big animated counter cards in a row:
  - **68.5% Win Rate** (calibrated backtest)
  - **532 Markets Tested**
  - **0.0% Probability of Ruin** (Monte Carlo)
- Below: a subtle banner — *"⚠️ All performance data is from backtesting, not live trading. Past performance does not guarantee future results."*

#### Live System Status Panel (top-right or below hero)
This panel attempts to fetch from the live VPS API. If unreachable, show "System Offline" gracefully.

**API Base:** `http://161.35.24.142:8000` (FastAPI on VPS)

**Endpoints to poll:**
- `GET /health` → system uptime, version
- `GET /status` → current cycle count, markets scanned, signals generated, cash balance, positions open
- `GET /metrics` → historical metrics (win rate, P&L, Brier score)
- `GET /risk` → kill switch status, daily P&L, drawdown, cooldown status
- `GET /execution` → fill rates, slippage, fee drag

Display as a status card grid:
```
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ 🟢 System Live  │ │ Cycle #1,247    │ │ Markets Scanned │
│ Uptime: 14d 6h  │ │ Last: 2m ago    │ │ 100 / cycle     │
└─────────────────┘ └─────────────────┘ └─────────────────┘
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Signals: 18/cyc │ │ Cash: $75.00    │ │ Positions: 34   │
│ Avg Edge: 25.7% │ │ Deployed: $68   │ │ Realized P&L: $ │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

If the API is down, show all cards as "Offline" with a pulsing gray dot instead of green.

#### Backtest Performance Section

**Strategy Comparison Table** (interactive, sortable):

| Strategy | Win Rate | Trades | Net P&L | Brier | Sharpe | ARR @5/day |
|----------|----------|--------|---------|-------|--------|-----------|
| Baseline (5% symmetric) | 64.9% | 470 | $275.30 | 0.2391 | 10.89 | +1,086% |
| NO-only | 76.2% | 210 | $217.90 | 0.2391 | 21.62 | +2,170% |
| Calibrated (5% symmetric) | 68.5% | 372 | $272.28 | 0.2171 | 13.99 | +1,437% |
| Calibrated + Asymmetric | 68.6% | 354 | $260.46 | 0.2171 | 14.07 | +1,446% |
| Calibrated + NO-only | 70.2% | 282 | $225.18 | 0.2171 | 15.49 | +1,596% |
| **Cal + CatFilter + Asym** | **71.2%** | **264** | **$221.36** | **0.2138** | **16.43** | **+1,692%** |
| Cal + Asym + Conf + CatFilter | 71.2% | 264 | $219.68 | 0.2138 | 17.01 | +1,677% |
| High Threshold (10% symmetric) | 65.3% | 426 | $255.74 | 0.2391 | 11.19 | +1,121% |

Highlight the best variant row. Add a bar chart visualization next to the table comparing Win Rate and Sharpe across variants.

**Monte Carlo Fan Chart:**
An interactive area chart showing 10,000 simulated portfolio paths over 12 months.
- Shaded bands: 5th-95th percentile (light), 25th-75th (medium), median line (bright cyan)
- Starting capital: $75
- Key callouts on the chart:
  - Median 12mo: $918 (+1,124%)
  - 5th percentile: $782 (+942%)
  - 95th percentile: $1,054 (+1,305%)
  - P(total loss): 0.0%

**At $10K investor scenario** (toggle button to switch views):
  - Median: $36,907 (+269%)
  - 5th: $33,507 (+235%)
  - 95th: $40,207 (+302%)

**Capital Velocity Chart:**
Bar chart showing win rate by resolution time bucket:

| Bucket | Trades | Win Rate | Avg P&L |
|--------|--------|----------|---------|
| <24h | 111 | 72.1% | $0.88 |
| 1-3 days | 11 | 81.8% | $1.27 |
| 1-4 weeks | 264 | 59.9% | $0.39 |
| >1 month | 84 | 69.0% | $0.76 |

Highlight the insight: fast-resolving markets (<24h) win 72% vs 60% for 1-4 week markets.

---

### Page 2: Methodology (`/methodology`)

This is the deep-dive. Technical readers will spend the most time here. Use a left-sidebar table of contents with scroll-spy highlighting.

#### Section 2.1: System Architecture

Animated or static diagram showing the bot's architecture:

```
VPS: DigitalOcean Frankfurt
systemd: polymarket-bot.service

improvement_loop.py (every 5 min)
├── SCAN:    Gamma API → 100 active markets (min $100 liquidity)
├── FILTER:  Actionable candidates (YES price 10-90%, scored by proximity to 50/50)
├── ANALYZE: Claude Haiku estimates true probability (anti-anchoring: NO market price shown)
├── WEATHER: NOAA 6-city forecasts (NY, LA, Chicago, Miami, Seattle, Denver)
├── TRADE:   Paper/Live trader (quarter-Kelly sizing)
├── TUNE:    Auto-adjust every 20 cycles
└── REPORT:  Telegram + metrics JSON

Data stores:
├── paper_trades.json     (position log)
├── metrics_history.json  (cycle metrics)
├── strategy_state.json   (tuning state)
└── bot.db                (SQLite — orders, fills, positions, risk events)
```

Use a styled code block or an interactive flow diagram (D3 or Mermaid).

#### Section 2.2: The Probability Estimation Engine

Explain how Claude estimates probabilities:

1. **Anti-Anchoring Design**: Claude NEVER sees the market price. This prevents anchoring bias. Without this fix, Claude's estimates were within 3% of market price (useless). After the fix, average divergence is 25.7%.

2. **The Master Prompt**: Display the full 6-step prompt template in a code block:
   - Step 1: Outside View (base rate analysis)
   - Step 2: Arguments FOR (YES) — 3-5 reasons, rated weak/moderate/strong
   - Step 3: Arguments AGAINST (NO) — 3-5 reasons, rated weak/moderate/strong
   - Step 4: Initial Estimate
   - Step 5: Calibration Check (critical self-examination)
   - Step 6: Final Probability (precise, XX.X%)

3. **Why this prompt structure**: Based on synthesis of 12+ academic papers (2024-2026). Schoenegger et al. (2025) tested 38 prompt variants — only base-rate-first prompting showed significant improvement (-0.014 Brier). Chain-of-thought, Bayesian reasoning, and elaborate prompts HURT calibration.

4. **Category Routing**:
   - Priority 3 (trade): Politics, Weather
   - Priority 2 (trade): Economic, Unknown
   - Priority 1 (reduced size): Geopolitical
   - Priority 0 (skip): Crypto, Sports, Fed Rates

   Explain WHY: LLMs have zero edge on crypto/sports (speed-dependent), politics is their best category (Lu 2025, RAND).

#### Section 2.3: Calibration System

This is critical. Show the calibration problem and solution visually.

**The Problem: Claude is Overconfident**

Display a reliability diagram (predicted vs actual probability):
- Before calibration: 90% predictions → only 63% correct (massive overconfidence)
- After Platt scaling: 90% → 71% (corrected)

**Platt Scaling (CalibrationV2)**:
- Method: Logistic regression in logit space
- Parameters: A=0.5914, B=-0.3977
- Fitted on 70% of data (372 markets), validated on 30% (160 markets)

**Calibration Map** (show as a styled table with color gradient):

| Claude Raw | Platt-Calibrated | Direction |
|-----------|-----------------|-----------|
| 5% | 10.5% | Pulled up (underconfident on NO) |
| 20% | 22.8% | ~correct |
| 50% | 40.2% | Pulled down |
| 70% | 52.6% | Pulled down significantly |
| 90% | 71.1% | Major correction |
| 95% | 79.3% | Major correction |

**Out-of-Sample Validation**:

| Metric | Train (372) | Test (160) |
|--------|------------|-----------|
| Brier (raw) | 0.2188 | 0.2862 |
| Brier (Platt) | 0.2050 | 0.2451 |
| Improvement | +0.0138 | +0.0411 |

Key insight: The old 0.239 Brier was overfit. Out-of-sample raw Brier is actually 0.286. Platt scaling genuinely improves it to 0.245 on held-out data.

**Confidence-Weighted Sizing**: Probability buckets with <10 training samples get 0.5x position size (30-40%, 60-70%, 80-90% ranges). We don't trust thin data.

#### Section 2.4: Position Sizing — Kelly Criterion

Explain Kelly criterion for binary prediction markets:

**Buy YES**: `f* = (p_true - p_market) / (1 - p_market)`
**Buy NO**: `f* = (p_market - p_true) / p_market`

**Why Quarter-Kelly:**

| Kelly Fraction | Median Growth | P(50% Drawdown) | Ruin Risk | Sharpe |
|----------------|--------------|-----------------|-----------|--------|
| Full (1×) | ~10¹⁶× | 100% | 36.9% | 0.37 |
| Half (0.5×) | ~10¹¹× | 94.7% | ~0% | 0.57 |
| **Quarter (0.25×)** | **~10⁶×** | **8.0%** | **0%** | **0.64** |
| Tenth (0.1×) | ~10²× | 0% | 0% | 0.68 |

**Asymmetric sizing** (leveraging the NO-bias structural edge):
- buy_yes: 0.25× Kelly (55.8% historical win rate — conservative)
- buy_no: 0.35× Kelly (76.2% win rate — structural edge deserves more allocation)

**Dynamic scaling** based on bankroll:
- <$150 → 0.25× Kelly
- ≥$300 → 0.50× Kelly
- ≥$500 → 0.75× Kelly

**Backtest validation:**
- Flat $2: $75 → $330.60 (341% return)
- Quarter-Kelly: $75 → $1,353.18 (1,704% return)
- Kelly outperformance: +309%

#### Section 2.5: Risk Management

**Safety Rails (Non-Negotiable):**
- Limit orders ONLY — market orders permanently blocked (maker = zero fees)
- Buy price = market - $0.01 — get filled or miss, never overpay
- Order timeout: 60s — unfilled orders auto-cancelled
- Daily loss limit: $10 — auto kill switch on breach
- Per-trade max: $5 — even if Kelly says more
- Exposure cap: 80% — always keep 20% cash reserve
- Cooldown: 3 consecutive losses → 1 hour pause
- Kill switch: /kill cancels ALL open orders immediately
- Telegram alert on: every trade, every error, kill switch, cooldown

**Gradual Rollout Plan:**

| Week | Max/Trade | Trades/Day | Kelly |
|------|-----------|------------|-------|
| 1 | $1.00 | 3 | OFF |
| 2 | $2.00 | 5 | OFF |
| 3 | $5.00 | Unlimited | ON |

**Correlated Position Management:**
- Cluster caps: 15% of bankroll per category cluster
- Scenario caps: 10% of bankroll per event scenario
- Category haircut: >3 positions in same category → 50% size reduction
- Multivariate Kelly: `f = κ · Σ⁻¹ · e` as sanity check

**Drawdown Controls:**
- Daily loss limit: 7% of start-of-day bankroll
- At 15% drawdown: halve all position sizes
- At 25% drawdown: HALT all trading, full model review

#### Section 2.6: Capital Velocity Optimization

Explain the concept: A trade resolving in 2 days generates 15x more annualized return than one resolving in 30 days.

**Velocity Score** = `edge / estimated_days * 365`

Bot ranks all signals by velocity score and takes only top 5 per cycle.

**Resolution estimation** uses:
1. API `endDate` (primary — high confidence)
2. Question text parsing ("by March 15", "today", "tomorrow")
3. Weather/category heuristics
4. Default: 14 days for unknown

**Backtest Results:**

| Metric | Baseline | Velocity Top-5 | Improvement |
|--------|----------|---------------|-------------|
| Win rate | 64.9% | 71.7% | +6.8% |
| Avg P&L/trade | $0.60 | $0.87 | +44% |
| Avg resolution | 35.1 days | 4.7 days | 7.5x faster |
| ARR | +1,130% | +6,007% | +432% |

#### Section 2.7: The NO Bias — Favorite-Longshot Exploitation

Explain the structural edge: prediction markets systematically overprice YES outcomes (people want to bet on things happening). This is the well-documented "favorite-longshot bias."

- Buy NO win rate: 76.2%
- Buy YES win rate: 55.8%
- Asymmetric thresholds: YES needs 15% edge, NO only needs 5%

Academic validation: Whelan 2025, Becker 2025 — contracts at 5¢ win only 2-4%, not 5%.

#### Section 2.8: Taker Fee Awareness

Polymarket introduced taker fees: `fee(p) = p*(1-p)*r` where r=0.02.

At p=0.50, need 3.13% edge just to break even. Fees are worst at 50/50 markets.

Our system deducts taker fees from edge calculations before making trade decisions. Total fee impact on baseline strategy: 1.7% of gross P&L ($4.70 on $280 gross).

---

### Page 3: Research (`/research`)

Display the academic research that shapes the strategy. Make this feel like an academic literature review, but accessible.

#### Section 3.1: Evidence Hierarchy

Display as a ranked visual list (think leaderboard):

| Rank | Technique | Brier Δ | Source |
|------|-----------|---------|--------|
| 1 | Agentic RAG (web search) | -0.06 to -0.15 | AIA Forecaster (Bridgewater, 2025) |
| 2 | Platt scaling / extremization | -0.02 to -0.05 | AIA Forecaster (2025) |
| 3 | Multi-run ensemble (3-7 runs) | -0.01 to -0.03 | Halawi et al. (2024, NeurIPS) |
| 4 | Base-rate-first prompting | -0.011 to -0.014 | Schoenegger et al. (2025) |
| 5 | Structured scratchpad | -0.005 to -0.010 | Halawi (2024), Lu (2025) |
| 6 | Two-step confidence elicitation | -0.005 to -0.010 | Xiong et al. (2024, ICLR) |
| 7 | Granular probability output | -0.002 to -0.005 | GJP data |
| 8 | Superforecaster persona | ~0 | Schoenegger (2025) |
| ❌ | Bayesian reasoning prompts | +0.005 to +0.015 (HARMFUL) | Schoenegger (2025) |
| ❌ | Narrative framing | HARMFUL | Lu (2025) |
| ❌ | Propose-Evaluate-Select | HARMFUL | Schoenegger (2025) |

Use red/crossed-out styling for harmful techniques.

#### Section 3.2: Key Research Findings

Present each as an expandable card with a summary and "Read more" that expands to the full finding:

1. **Prompt engineering mostly doesn't help** (Schoenegger 2025): Only base-rate-first works. 38 prompts tested, no significance after Benjamini-Hochberg correction.

2. **Calibration is #1** (Bridgewater AIA, 2025): Without search, Brier = 0.36 (worse than random). With agentic search: 0.10. A 3.6× improvement from architecture alone.

3. **Ensemble + market consensus beats both** (Bridgewater 2025): System + market price → Brier 0.075, vs 0.096 for market alone, 0.100 for system alone.

4. **Category routing matters** (Lu 2025, RAND): Politics = best LLM category. Weather = structural arbitrage. Crypto/sports = zero LLM edge.

5. **LLMs anchor on market prices** (Lou & Sun 2024, ForecastBench 2025): GPT-4.5 copies market prices with 0.994 correlation when shown them. Anti-anchoring is essential.

6. **Multi-model ensembles work** (Halawi et al. 2024, NeurIPS): "LLM crowd" statistically equivalent to human crowd.

7. **Superforecasters update frequently but modestly**: 7.8 predictions/question (vs 1.4 average), avg update magnitude 3.5% (vs 5.9%). "Perpetual beta" 3× more predictive than raw intelligence.

8. **LLM-superforecaster parity projected ~Nov 2026** (ForecastBench, Karger 2025): Improvement rate ~0.016 Brier points/year.

9. **Acquiescence bias**: Claude skews YES systematically. Must never show prior estimates when re-estimating (SACD drift).

10. **Polymarket is exploitable**: Clinton & Huang (2025) — political markets only ~67% correct. Only 0.5% of users earn >$1K.

#### Section 3.3: Competitive Landscape

- **OpenClaw**: Agent framework, reportedly $115K in one week
- **Open-source bots**: Discountry (gasless, flash-crash), PolyScripts (arb), Aule Gabriel (BTC up/down)
- **Institutional**: Susquehanna hiring prediction market traders
- **Key insight**: Successful bots use arbitrage, not forecasting. Our approach is differentiated but must be validated.

#### Section 3.4: The Frontier

Where the best systems are today:
- ForecastBench leaderboard: Superforecasters at 0.081 Brier, best LLM (GPT-4.5) at 0.101
- Lightning Rod Labs' Foresight-32B: Led all LLMs on Brier, ECE, and profit despite being 10-100× smaller than frontier models
- Our system: 0.217 Brier (calibrated) — substantial room for improvement
- Target: 0.075-0.10 (requires agentic RAG + ensemble + market price combination)

---

### Page 4: Risk & Transparency (`/risk`)

#### Honest Risk Assessment

Present each risk factor as a card with severity indicator (🟢 🟡 🔴):

1. 🔴 **Backtest ≠ Live** — All numbers are simulated. Zero resolved live trades.
2. 🔴 **AI Overconfidence** — Brier 0.217 is better than random (0.25) but far from good. Calibration is backtest-fit.
3. 🟡 **NO-bias dependency** — 76% edge from buy_no could erode as AI traders enter. It's structural (favorite-longshot bias) but not guaranteed permanent.
4. 🟡 **Competitive pressure** — OpenClaw bots, open-source proliferation. Only 0.5% of users earn >$1K.
5. 🟡 **Arbitrage dominates** — Most profitable bots use arbitrage, not forecasting. Our approach is unproven.
6. 🟡 **Taker fees** — Eat 1-3% of edge. Market making (limit orders) is the emerging dominant strategy.
7. 🟡 **Platform risk** — Polymarket has CFTC history, is crypto-based.
8. 🟢 **Capital concentration** — Mitigated by cluster caps and scenario limits.
9. 🟢 **Resolution timing** — Mitigated by velocity optimization (+432% ARR improvement).
10. 🟢 **API costs** — ~$20/mo, manageable.

#### Monte Carlo Risk Metrics

Display the key risk outputs:

**At $75 starting capital (10,000 simulations):**
- P(total loss): 0.0%
- P(negative return at 12mo): 0.0%
- Median max drawdown: ~8%
- 95th percentile max drawdown: ~18%

**Kelly Fraction Risk Comparison** (visual bar chart):

| Fraction | Ruin Risk | P(50% DD) | Sharpe |
|----------|-----------|-----------|--------|
| Full Kelly | 36.9% | 100% | 0.37 |
| Half Kelly | ~0% | 94.7% | 0.57 |
| Quarter Kelly (ours) | 0% | 8.0% | 0.64 |
| Tenth Kelly | 0% | 0% | 0.68 |

#### Market Impact Model

Show how edge erodes at scale:

| Order Size | Slippage | Round-Trip Cost | Net Edge |
|-----------|----------|-----------------|----------|
| $2 | 0.51% | 1.02% | 30.7% |
| $1,000 | 0.71% | 1.43% | 30.3% |
| $5,000 | 0.97% | 1.95% | 29.8% |
| $25,000 | 1.56% | 3.12% | 28.6% |

Strategy capacity estimate: ~$1-5M practical capacity (edge erodes to zero at ~$5.2M per trade).

---

### Page 5: Roadmap (`/roadmap`)

Show what's been done and what's next. Use a Kanban-style or timeline visualization.

**Completed ✅:**
- 532-market backtest
- Anti-anchoring prompt design
- CalibrationV2 (Platt scaling, out-of-sample)
- Quarter-Kelly position sizing
- Asymmetric thresholds (YES 15% / NO 5%)
- Category routing
- Capital velocity optimization
- Taker fee awareness
- Safety rails + kill switch
- Live trading infrastructure
- Ensemble skeleton (Claude working, GPT/Grok placeholders)
- Superforecaster methods playbook
- Resolution rule edge playbook
- Correlated position risk framework
- Monte Carlo simulation (10,000 paths)

**In Progress 🔄:**
- Paper → live trading transition (checklist ready)
- Gradual rollout (Week 1: $1/trade, 3 trades/day)

**Planned 📋 (Priority Order):**
1. P0: Agentic RAG pipeline (news search per market) — expected Brier Δ: -0.06 to -0.15
2. P0: Multi-model ensemble (Claude + GPT + Grok) — expected Brier Δ: -0.01 to -0.03
3. P1: Weather multi-model consensus (GFS + ECMWF + HRRR)
4. P1: Market-making strategy (limit orders, zero fees)
5. P1: LLM + market consensus ensemble (Bridgewater approach)
6. P1: News sentiment data pipeline (NewsData.io)
7. P2: Foresight-32B evaluation (fine-tuned forecasting model)
8. P2: Social sentiment monitor (Twitter/X + Reddit)
9. P2: Cross-platform monitoring (Oddpool, PolyRouter)
10. P3: Category-specific calibration curves
11. P3: Continuous backtest evaluator on VPS

---

### Page 6: Suggest & Contribute (`/contribute`)

#### Community Feedback Section

**Header:** "Help Us Improve — We're Building in Public"

**Subheader:** *"We believe prediction market AI should be open. If you see something we're missing, have research to share, or want to challenge our methodology — we want to hear it."*

**Feedback Form** (store submissions in a database — Replit DB, Supabase, or a simple JSON store):

Fields:
- **Name** (optional)
- **Email** (optional — for follow-up)
- **Category** dropdown:
  - "Strategy Improvement"
  - "Bug Report / Data Error"
  - "Research Paper / Reference"
  - "New Feature Idea"
  - "Risk Factor We're Missing"
  - "General Feedback"
  - "I Want to Collaborate"
- **Your Suggestion** (large text area, markdown supported)
- **Expertise Level** (optional radio):
  - "Prediction market trader"
  - "Quant / data scientist"
  - "AI/ML researcher"
  - "Finance professional"
  - "Curious enthusiast"
  - "Other"

**Submit button** with a confirmation animation.

#### Open Questions Section

Display a list of questions we're actively seeking input on:

1. **Calibration**: Is Platt scaling optimal, or should we move to isotonic regression with 532 markets of data? What about category-specific calibration?
2. **Ensemble design**: What's the best aggregation method? Trimmed mean, weighted by historical accuracy, or a supervisor model?
3. **Market making vs taking**: With taker fees at p*(1-p)*r, should we pivot entirely to maker strategy?
4. **Agentic RAG**: What news/data APIs give the best real-time context for prediction markets? AskNews? Perplexity? Direct RSS?
5. **Edge decay**: How fast will our edge erode as more AI bots enter? What's the half-life?
6. **Resolution rules**: Has anyone systematically cataloged Polymarket's resolution precedents?
7. **Cross-platform arbitrage**: Is there meaningful edge between Polymarket and Kalshi/Metaculus?

#### Advisory Board / Collaborators

A section for listing people who've contributed advice or improvements (empty initially, populated as people contribute).

#### Recent Suggestions Feed

Display the most recent 10 submissions (moderated — don't show until approved). Shows category, date, and the suggestion text.

---

## Technical Implementation Details

### API Integration (Live Data)

```typescript
// lib/api.ts
const VPS_BASE = 'http://161.35.24.142:8000';

interface SystemStatus {
  alive: boolean;
  uptime_seconds: number;
  cycle_count: number;
  markets_scanned: number;
  signals_generated: number;
  cash_balance: number;
  positions_open: number;
  kill_switch: boolean;
  daily_pnl: number;
  mode: 'paper' | 'live';
}

export async function fetchSystemStatus(): Promise<SystemStatus | null> {
  try {
    const [health, status, risk] = await Promise.all([
      fetch(`${VPS_BASE}/health`, { next: { revalidate: 30 } }),
      fetch(`${VPS_BASE}/status`, { next: { revalidate: 30 } }),
      fetch(`${VPS_BASE}/risk`, { next: { revalidate: 30 } }),
    ]);
    // merge responses
    return { /* merged data */ };
  } catch {
    return null; // system offline
  }
}
```

Poll every 30 seconds when the dashboard tab is active. Use `visibilitychange` API to pause polling when tab is hidden.

### Static Data

All backtest data should be embedded as JSON constants in the codebase (not fetched from an API). This data changes rarely and should be version-controlled.

```typescript
// data/backtest.ts
export const STRATEGY_COMPARISON = [
  { name: 'Baseline (5% symmetric)', winRate: 0.649, trades: 470, netPnl: 275.30, brier: 0.2391, sharpe: 10.89, arr: 1086 },
  { name: 'NO-only', winRate: 0.762, trades: 210, netPnl: 217.90, brier: 0.2391, sharpe: 21.62, arr: 2170 },
  // ... all 8 variants
];

export const MONTE_CARLO = {
  starting_capital: 75,
  simulations: 10000,
  months: 12,
  results_75: { median: 918, p5: 782, p95: 1054, p_loss: 0 },
  results_10k: { median: 36907, p5: 33507, p95: 40207, p_loss: 0 },
};

export const CALIBRATION_MAP = [
  { raw: 0.05, calibrated: 0.105 },
  { raw: 0.20, calibrated: 0.228 },
  { raw: 0.50, calibrated: 0.402 },
  { raw: 0.70, calibrated: 0.526 },
  { raw: 0.90, calibrated: 0.711 },
  { raw: 0.95, calibrated: 0.793 },
];

export const VELOCITY_BUCKETS = [
  { bucket: '<24h', trades: 111, winRate: 0.721, avgPnl: 0.88 },
  { bucket: '1-3 days', trades: 11, winRate: 0.818, avgPnl: 1.27 },
  { bucket: '1-4 weeks', trades: 264, winRate: 0.599, avgPnl: 0.39 },
  { bucket: '>1 month', trades: 84, winRate: 0.690, avgPnl: 0.76 },
];

export const KELLY_COMPARISON = [
  { fraction: 'Full (1×)', medianGrowth: '~10¹⁶×', p50dd: 1.00, ruinRisk: 0.369, sharpe: 0.37 },
  { fraction: 'Half (0.5×)', medianGrowth: '~10¹¹×', p50dd: 0.947, ruinRisk: 0, sharpe: 0.57 },
  { fraction: 'Quarter (0.25×)', medianGrowth: '~10⁶×', p50dd: 0.08, ruinRisk: 0, sharpe: 0.64 },
  { fraction: 'Tenth (0.1×)', medianGrowth: '~10²×', p50dd: 0, ruinRisk: 0, sharpe: 0.68 },
];
```

### Feedback Storage

Use Replit's built-in database or set up a simple Supabase table:

```sql
CREATE TABLE suggestions (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMP DEFAULT NOW(),
  name VARCHAR(255),
  email VARCHAR(255),
  category VARCHAR(50),
  suggestion TEXT NOT NULL,
  expertise VARCHAR(50),
  approved BOOLEAN DEFAULT FALSE,
  response TEXT
);
```

### SEO & Meta

- Title: "Predictive Alpha Fund — Open-Source AI Prediction Market Trading System"
- Description: "An AI-powered automated trading system for Polymarket. 68.5% win rate on 532 backtested markets. Open-source methodology, real data, transparent risk."
- OG image: Auto-generated card with key metrics
- Structured data for the research papers section

### Performance

- Use Next.js static generation for methodology/research pages
- Client-side polling only for live data on dashboard
- Lazy-load charts below the fold
- Image optimization for any backtest chart PNGs
- Code-split per page

---

## Key Numbers Reference

Keep these in a single constants file so they're easy to update:

```typescript
export const KEY_METRICS = {
  // Backtest
  markets_tested: 532,
  win_rate_uncalibrated: 0.649,
  win_rate_calibrated: 0.685,
  best_variant_win_rate: 0.712,
  brier_raw: 0.2391,
  brier_calibrated: 0.2171,
  brier_oos: 0.2451,
  buy_yes_win_rate: 0.633,
  buy_no_win_rate: 0.702,
  avg_pnl_per_trade: 0.74,

  // Monte Carlo
  mc_simulations: 10000,
  mc_p_loss: 0,
  mc_median_75: 918,
  mc_median_10k: 36907,

  // System
  starting_capital: 75,
  monthly_infra: 20,
  scan_interval_seconds: 300,
  markets_per_scan: 100,
  signals_per_cycle: 18,

  // Strategy
  edge_threshold_yes: 0.15,
  edge_threshold_no: 0.05,
  kelly_fraction: 0.25,
  taker_fee_rate: 0.02,

  // Velocity
  velocity_win_rate: 0.717,
  velocity_arr_improvement: 432,
  velocity_avg_resolution_days: 4.7,

  // Risk
  daily_loss_limit: 10,
  per_trade_max: 5,
  exposure_cap: 0.80,

  // Calibration
  platt_a: 0.5914,
  platt_b: -0.3977,

  // Competitive
  polymarket_accuracy: 0.67, // Clinton & Huang 2025
  pct_users_earning_1k: 0.005,
};
```

---

## Disclaimer (Footer on Every Page)

> **Disclaimer:** All performance figures presented on this site are from backtesting against historical data and do not represent live trading results. Past performance, whether simulated or actual, does not guarantee future results. Prediction market trading involves substantial risk of loss. This site is for informational and educational purposes only. It does not constitute financial advice or an offer to sell securities. The system described is experimental and unproven in live markets. You should only trade with money you can afford to lose entirely.

---

## Update Protocol

This dashboard should be designed to be easily updatable. When new backtest runs complete or live data accumulates:

1. Update the constants in `data/backtest.ts`
2. Add new research findings to the research page
3. Update the roadmap (move items from Planned → In Progress → Completed)
4. Approve and display community suggestions
5. If live trading begins, the live status panel will automatically start showing real data

The goal is that this site becomes the living, breathing documentation of the system — updated weekly, transparent about failures, and useful to anyone building something similar.
