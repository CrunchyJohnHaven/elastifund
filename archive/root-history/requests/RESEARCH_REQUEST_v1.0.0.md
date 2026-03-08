# RESEARCH REQUEST v1.0.0 — Beat the Current Strategy

**Date:** 2026-03-07 | **Owner:** John Bradley | **Project:** Elastifund / Predictive Alpha Fund
**Objective:** Define the current strategy baseline with honest ARR estimates, then conduct deep research to find superior approaches.

---

## Part 1: Current Strategy — Full Description

### 1.1 What We Are

An AI-powered prediction market trading fund operating on **Polymarket** ($247.51 USDC live) and **Kalshi** ($100 USD connected). We scan markets, estimate probabilities, detect mispricings, and execute trades automatically from a Dublin VPS.

### 1.2 Architecture: Three Signal Sources + Confirmation Layer

```
┌─────────────────────────────────────────────────────────────────┐
│                    JJ HYBRID TRADING ENGINE                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SIGNAL SOURCE 1: LLM Analyzer                                 │
│  ├── Markets: Politics, weather, geopolitical, economic         │
│  ├── Resolution: 12h – 7 days                                  │
│  ├── Method: Claude Haiku probability estimate                  │
│  │   → Platt calibration (A=0.5914, B=-0.3977)                 │
│  │   → Asymmetric thresholds (YES: 15% edge, NO: 5% edge)      │
│  ├── Anti-anchoring: Market price hidden from LLM               │
│  ├── Sizing: Quarter-Kelly (0.25)                               │
│  ├── Cycle: Every 5 minutes                                     │
│  └── Backtest: 71.2% win rate, Brier 0.217, Sharpe 16.43       │
│                                                                 │
│  SIGNAL SOURCE 2: Smart Wallet Flow Detector                    │
│  ├── Markets: BTC/ETH 5-min and 15-min candles                  │
│  ├── Resolution: 5 min – 1 hour                                 │
│  ├── Method: Monitor top wallets via data-api.polymarket.com     │
│  │   → Score wallets by 5-factor composite (freq, diversity,     │
│  │     crypto specialization, volume, size consistency)          │
│  │   → Consensus detection: 3+ of top-K wallets same side       │
│  │     within 30-min window, >$15 combined size                  │
│  ├── Sizing: 1/16 Kelly (0.0625)                                │
│  ├── Cycle: Every 15 seconds                                    │
│  └── Target: 74% win rate, 20-50 trades/day, +8-15%/month       │
│                                                                 │
│  SIGNAL SOURCE 3: LMSR Bayesian Engine                          │
│  ├── Markets: Any with trade flow data                          │
│  ├── Method: Sequential Bayesian posterior (log-space)           │
│  │   → LMSR softmax pricing from trade flow quantities          │
│  │   → Blend: 60% posterior + 40% LMSR flow price               │
│  │   → Signal when |blended - CLOB mid| > 5% threshold          │
│  ├── Sizing: 1/16 Kelly (always fast-market treatment)           │
│  ├── Cycle: Target 828ms avg, 1776ms p99                        │
│  └── Status: Built, 45 unit tests passing, not yet live-tested   │
│                                                                 │
│  CONFIRMATION LAYER                                              │
│  ├── Group signals by (market_id, direction)                    │
│  ├── 2+ sources agree → boosted Kelly (quarter-Kelly)            │
│  ├── LLM alone + resolution > 12h → quarter-Kelly               │
│  ├── Wallet flow alone + resolution < 1h → 1/16 Kelly           │
│  ├── LMSR alone → 1/16 Kelly                                    │
│  └── Telegram alerts with source tags + [CONFIRMED]              │
│                                                                 │
│  EXECUTION                                                       │
│  ├── Maker/post-only orders (zero fees, +rebates on crypto)     │
│  ├── Max $5/trade (Phase 1), $5 daily loss limit                │
│  ├── 5 max open positions                                       │
│  └── CLOB via py_clob_client, signature_type=1 (POLY_PROXY)     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 Edge Sources (Why We Think This Works)

| Edge Source | Mechanism | Evidence | Deployed? |
|-------------|-----------|----------|-----------|
| **Favorite-longshot bias** | NO outperforms YES at 69/99 price levels | 72.1M trades (jbecker.dev) | YES — asymmetric thresholds |
| **Maker advantage** | Makers earn +1.12% excess vs takers at -1.12% | 72.1M trades | YES — post-only orders |
| **LLM calibration** | Platt scaling reduces overconfidence (90%→71%) | 532 resolved markets, Brier 0.217 | YES |
| **Category gaps** | World Events 7.32pp, Media 7.28pp mispricing | 72.1M trades | YES — category filter |
| **Smart wallet alpha** | Top wallets have persistent, copyable edge | Academic + practitioner evidence | Built, not live |
| **LMSR mispricing** | Bayesian posterior vs CLOB divergence | Research paper QR-PM-2026-0041 | Built, not live |
| **Anti-anchoring** | Hiding market price prevents Claude bias | Forecasting literature | YES |
| **Velocity scoring** | Fast-resolving markets = faster compounding | Capital efficiency math | YES |

### 1.4 What We Know Doesn't Work

| Approach | Why It Fails |
|----------|-------------|
| **LLM on crypto price prediction** | Zero edge — markets are efficient for short-term prices |
| **LLM on sports** | Zero edge — too much smart money, odds already optimal |
| **Taker orders on thin edges** | 0.44% fee eats 5-10% edges entirely |
| **Long-dated positions** | Capital lockup kills annualized returns |
| **Full Kelly sizing** | Ruin risk unacceptable on 5-min markets |
| **Single-model prediction** | Overconfidence without calibration or ensemble |

---

## Part 2: Honest ARR Estimate

### 2.1 Backtest Performance (Optimistic Upper Bound)

| Metric | Value | Notes |
|--------|-------|-------|
| Calibrated win rate | 71.2% | 532 markets, Platt + asymmetric + category filter |
| NO-only win rate | 76.2% | Highest Sharpe variant (21.62) |
| Avg P&L per trade | $0.84 | Combined strategy, $1 position size baseline |
| Monte Carlo median (12mo) | $75 → $918 | 10,000 paths, 5 trades/day, 0% ruin |
| Monte Carlo 5th percentile | $75 → $786 | Worst 5% of paths still profitable |
| Backtest ARR | +1,124% | Annualized from Monte Carlo median |
| Max drawdown (Monte Carlo) | 10.4% avg, 19.6% p95 | Manageable at small scale |

### 2.2 Reality Adjustments (Why Live Will Be Worse)

| Factor | Estimated Impact | Rationale |
|--------|-----------------|-----------|
| **Execution slippage** | -15% to -25% of edge | Backtest assumes instant fills at mid price |
| **Alpha decay** | -10% to -20% per year | Polymarket adding fees, latency limits, more bots |
| **Overfit** | -20% to -30% of win rate edge | 532 markets is thin; Platt coefficients may not generalize |
| **Liquidity constraints** | Negligible at $247 | Becomes material at $50K+ |
| **Adverse selection** | -5% to -10% of edge | Maker orders get picked off by faster traders |
| **Model staleness** | -5% to -10% annually | LLM training data ages, new event types emerge |

### 2.3 Realistic ARR Projections

**Starting capital: $247.51 USDC**

| Scenario | Monthly Return | Annual Return | 12-Month Capital | Method |
|----------|---------------|---------------|------------------|--------|
| **Pessimistic** | +3%/mo | +43% | $353 | 60% win rate, 3 trades/day, heavy alpha decay |
| **Conservative** | +6%/mo | +101% | $497 | 64% win rate, 5 trades/day, moderate decay |
| **Base case** | +10%/mo | +214% | $776 | 68% win rate, 5 trades/day, some execution drag |
| **Optimistic** | +15%/mo | +435% | $1,324 | 71% win rate, 8 trades/day, minimal decay |
| **Backtest replay** | +22%/mo | +987% | $2,684 | Backtest numbers hold (unlikely) |

**Honest best estimate: +6% to +10% monthly, or +100% to +214% annualized.**

This assumes:
- Hybrid engine running 24/7 on Dublin VPS
- All three signal sources active
- $2K capital injection on March 10 (raises base to ~$2,250)
- Maker orders exclusively (zero fees)
- No catastrophic bugs or API changes

### 2.4 The Uncomfortable Truths

1. **We have zero live P&L.** Three orders placed and cancelled. No completed trades.
2. **Backtest ≠ live.** Every quant fund in history has seen backtest-to-live degradation.
3. **$247 is too small.** Polymarket minimums ($1-5/trade) mean poor position granularity.
4. **Alpha decays.** Polymarket is adding more fees and latency throttles. The window closes.
5. **Smart wallet flow is unproven.** Expected 74% win rate is a target, not a measurement.
6. **LMSR engine has no live data.** Math is sound but real-world performance is unknown.
7. **Single exchange risk.** Polymarket regulatory or technical failure = total loss.

---

## Part 3: Research Brief — Beat This Strategy

### 3.1 Research Objective

Find strategies, techniques, data sources, or architectural changes that could **materially improve** one or more of:

- **Win rate** (currently 71.2% backtest, probably 63-68% live)
- **Edge size** (currently 5-15% per trade)
- **Trade frequency** (currently 5-50 trades/day depending on source)
- **Capital efficiency** (currently limited by resolution time)
- **Risk-adjusted returns** (currently Sharpe ~16 backtest, probably ~3-5 live)
- **Robustness** (currently single-exchange, single-model, single-calibration)

### 3.2 Specific Research Questions

#### A. Probability Estimation Improvements
1. **What is the state of the art for LLM probability calibration in 2026?** Beyond Platt scaling — isotonic regression, temperature scaling, Venn prediction, conformal calibration?
2. **Multi-model ensemble architectures:** What's the optimal way to combine Claude + GPT-4.5 + Grok + Gemini for prediction markets? Weighted average? Mixture of experts? Which model is best for which category?
3. **Agentic RAG for prediction markets:** Our research says this gives -0.06 to -0.15 Brier improvement (best single technique). What are the latest implementations? What retrieval sources work best?
4. **Can we use reasoning models (o1/o3, Claude with extended thinking) for better calibration?** Cost vs. improvement tradeoff?

#### B. Alternative Signal Sources
5. **Order book imbalance signals:** Beyond LMSR — what does academic literature say about using limit order book shape to predict short-term price movements on prediction markets?
6. **Cross-market arbitrage:** Are there systematic mispricings between Polymarket vs Kalshi vs Metaculus vs Manifold? How to exploit them?
7. **News sentiment for prediction markets:** Real-time news APIs (NewsAPI, GDELT, Google Alerts) — has anyone built a working sentiment→probability pipeline for prediction markets?
8. **Social media signals:** Twitter/X, Reddit, Telegram group sentiment as leading indicators for prediction market movements?

#### C. Execution Improvements
9. **Optimal market making on Polymarket:** Two-sided quoting with inventory management. What's the expected return vs our current directional strategy?
10. **Latency arbitrage:** BTC spot price leads Polymarket 5-min candle markets. What infrastructure is needed to exploit this? Has anyone quantified the lag?
11. **MEV/front-running on Polygon:** Is there a DeFi-style extraction strategy specific to Polymarket's on-chain settlement?

#### D. Risk & Portfolio
12. **Correlation between prediction market positions:** How correlated are our positions? Should we hedge?
13. **Optimal Kelly for non-independent bets:** Our markets are partially correlated (political events cluster). What's the correct sizing?
14. **Drawdown-conditional strategies:** Academic work on reducing position sizes after drawdowns — does it help or hurt with our edge profile?

#### E. Competition & Alpha Decay
15. **Who are the top Polymarket traders in 2026 and what strategies do they use?** Public wallet analysis, forum posts, open-source bots.
16. **How fast is alpha decaying on Polymarket?** Fee increases, new competitors, latency throttling — what's the half-life of our edge?
17. **What prediction market strategies have been published in 2025-2026?** Academic papers, blog posts, open-source projects.

#### F. Alternative Platforms
18. **Kalshi vs Polymarket:** Which has better edge opportunities for AI? Fee structures, market types, API capabilities, regulatory status.
19. **Metaculus/Manifold/PredictIt:** Are there untapped opportunities on less-competitive platforms?
20. **Sports betting markets as prediction markets:** Is there cross-pollination with quantitative sports betting approaches?

### 3.3 Success Criteria

A research finding is valuable if it:
1. **Identifies a strategy with >5% higher win rate** than our current 71.2% (backtest) or likely 65% (live)
2. **Identifies a new edge source** with independent alpha (not correlated with our existing signals)
3. **Reduces alpha decay** by improving robustness or diversifying across platforms
4. **Increases trade frequency** without reducing win rate (more opportunities = more compounding)
5. **Provides concrete implementation guidance** — not just "use ML" but specific models, datasets, APIs, code

### 3.4 What We've Already Researched (Don't Repeat)

- Platt scaling calibration (deployed)
- Favorite-longshot bias / NO-side advantage (deployed)
- Maker vs taker fee advantage (deployed)
- Category-specific mispricing (deployed)
- Base-rate-first prompting (deployed)
- Smart wallet flow copying (built)
- LMSR Bayesian pricing (built)
- Monte Carlo simulation with regime switching (completed)
- Binary options pricing / Greeks (completed)
- Sentiment/contrarian "fade the dumb money" (researched, not built)
- Market making strategy (researched, not built)
- Kelly criterion optimization (deployed)

### 3.5 Deliverable Format

For each finding, provide:
```
## Finding: [Title]
- **Edge type:** [Calibration / Signal source / Execution / Risk / Platform]
- **Expected improvement:** [Quantified: +X% win rate, or +Y% monthly return, or -Z Brier]
- **Implementation effort:** [Hours/days to build]
- **Data requirements:** [APIs, datasets, subscriptions needed]
- **Evidence quality:** [Academic paper / Practitioner blog / Open-source project / Theoretical]
- **Priority:** [P0 immediate / P1 this month / P2 next quarter / P3 someday]
- **How to build it:** [Concrete steps, not hand-waving]
```

---

## Part 4: Meta-Strategy Question

If you were building a prediction market trading fund from scratch today with $2,500 in capital, access to Claude/GPT/Grok APIs, a VPS in Ireland, and the Polymarket + Kalshi APIs — **what would you build differently than what we've built?**

We want the brutally honest answer. What are we doing wrong? What are we over-engineering? What obvious thing are we missing? What would a hedge fund quant do that we're not doing?

---

*v1.0.0 — 2026-03-07. First research request. Baseline ARR: +100% to +214% annually (honest estimate). Challenge: beat it.*
