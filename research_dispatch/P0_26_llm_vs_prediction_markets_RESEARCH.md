# P0-26: LLMs vs. Prediction Markets — Comprehensive Research Summary
**Tool:** REFERENCE DOCUMENT (research synthesis)
**Status:** COMPLETED
**Date:** 2026-03-05
**Source:** Deep research across 9 major academic papers (2024-2025)

---

## Executive Summary

LLMs have crossed crowd-level forecasting but cannot consistently beat prediction market prices alone. The real alpha lies in: (1) structural arbitrage in thin markets (especially weather), (2) ensemble combination of LLM + market consensus, and (3) market making (execution, not prediction). Prompt engineering matters far less than retrieval infrastructure, calibration, and ensembling.

---

## Key Findings by Category

### 1. LLM Forecasting Performance (Academic Benchmarks)
- **Halawi et al. (NeurIPS 2024):** RAG GPT-4 system achieved Brier 0.179 vs crowd 0.149 on 914 questions. Without retrieval: Brier ~0.25 (random). LLMs reluctant to assign extreme probs (<5% or >95%).
- **Schoenegger et al. (Science Advances, Nov 2024):** Ensemble of 12 LLMs ("silicon crowd") achieved Brier 0.20, matching 925 human forecasters. Individual models failed to beat 50% baseline.
- **ForecastBench (Karger et al., ICLR 2025):** Superforecasters: 0.081, GPT-4.5: 0.101, median public: 0.121. LLMs improving ~0.016 Brier/year. Superforecaster parity projected: Nov 2026 (95% CI: Dec 2025 – Jan 2028).
- **Lu (2025):** o3 model achieved 0.1352 on 464 Metaculus questions — beat crowd (0.149), drastically short of superforecaster (0.023) on 41-question subset.
- **Bridgewater AIA Forecaster (Nov 2025):** Multi-agent system matched superforecaster performance on ForecastBench. Underperformed liquid market consensus on MarketLiquid benchmark (1,610 questions). **Critical finding: ensemble of AIA + market consensus outperformed consensus alone.**

### 2. Prompt Engineering (Mostly Doesn't Help)
- **Schoenegger et al. (2025):** 38 prompts × 4 models × 100 questions. After correction, only 3 prompts beat minimal control:
  - **Frequency-based reasoning ("historical frequency of similar events?"):** −0.014 Brier (BEST)
  - **Base-rate-first prompting:** −0.011 Brier
  - **Step-back prompting:** −0.011 Brier
- **Everything else statistically insignificant:** Chain-of-thought, adversarial debiasing, pros-and-cons, superforecaster persona — all produced no significant improvement.
- **Two prompts HURT performance:**
  - Bayesian reasoning: +0.030 Brier (p < 0.001)
  - Propose-evaluate-select: +0.033 Brier
- **Lu (2025):** Narrative/extended reasoning made Claude "extremely underconfident" (predicted ~50% for ~80% events)

### 3. What Actually Works (Beyond Prompting)
1. **RAG with quality news sources:** Halawi: Brier 0.25 → 0.179 (massive gain)
2. **RL fine-tuning with Brier rewards:** Foresight-32B (fine-tuned Qwen3-32B) achieved Brier 0.190 on 1,265 Polymarket questions, ECE 0.062. Outperformed all frontier models at 10-100× smaller.
3. **Ensemble aggregation:** Consistently largest gains at lowest cost
4. **Platt-scaling calibration:** Used by Bridgewater's AIA system
5. **Access to human crowd forecasts:** GPT-4.5 copies market forecasts with 0.994 correlation when given them

### 4. Category-by-Category LLM Edge
| Category | LLM Edge | Notes |
|----------|----------|-------|
| **Politics/elections** | Approaches crowd, trails experts | Best Brier scores across all models |
| **Weather** | Structural arbitrage | NOAA 24h: 95-96% accuracy; market lag documented |
| **Sports** | Minimal | Sportsbook lines set by quant teams |
| **Crypto** | None | Latency arb dead post-Feb 2026 taker fees |
| **Geopolitical** | ~30% worse than experts | Sparse base rates, judgment-heavy (RAND) |
| **Policy/Fed rates** | Worst category | Systematic overconfidence; ECE 0.12-0.40 |

### 5. Polymarket Taker Fees (CRITICAL — Feb 18, 2026)
- Removed 500ms taker quote delay
- Introduced taker fees: `fee(p) = p × (1−p) × r`
- Crypto markets: max effective 1.56% at p=0.50
- Sports markets: 0.44%
- **At p=0.50, need 3.13% edge just to break even after fees**
- Killed dominant taker-arbitrage strategy
- **Emerging winner: market making (limit orders, earning spread + maker rebates)**

### 6. Weather Arbitrage Details
- NOAA accuracy: 24h: 95-96%, 48h: 90-93%, 72h: 85-90%, 5d: ~80%
- Daily high temp MAE at 24h: 2-3°F (within typical 2°F Polymarket bucket)
- Multi-model consensus recommended: GFS + ECMWF + HRRR
- HRRR updates hourly, 3km resolution — best for US cities
- NWS API (api.weather.gov) is free, no API key needed
- **Favorite-longshot bias confirmed:** Contracts at 5¢ win only 2-4% (not 5%); contracts above 50¢ consistently outperform implied odds (Whelan 2025, Becker 2025)

### 7. Kelly Criterion
- Standard formula for binary markets: f* = (p − p_m) / (1 − p_m)
- Universal recommendation: quarter-Kelly (25% of optimal fraction)
- Full Kelly: 33% probability of halving bankroll before doubling
- **Kelly is only as good as probability input — LLM overconfidence = catastrophic overbetting**

### 8. Profitable Polymarket Strategies (Documented)
- **Latency arb (dead post-Feb 2026):** "0x8dxd" turned $313 → $438K in one month on crypto markets
- **Spread capture:** "Gabagool22" accumulated $200K+ buying YES+NO when combined < $1.00
- **Market making:** OpenClaw bot earned $115K/week across 47K trades as liquidity provider
- **Only 0.5% of Polymarket users earn >$1K profit**

---

## Implications for Our System

### IMMEDIATE ACTIONS (Based on Research)
1. **Fix prompt:** Use base-rate-first prompting ONLY. Remove any chain-of-thought or elaborate reasoning. Add explicit debiasing ("You systematically overestimate YES by 20-30%").
2. **Add calibration layer:** Temperature scaling (Bridgewater validated) or Platt scaling as primary. Isotonic regression as secondary.
3. **Account for taker fees:** Our edge calculations must subtract `p*(1-p)*r` for taker orders. At 5% edge and p=0.50, fees eat ~1.5% of our edge.
4. **Category routing:** Prioritize politics and weather markets. Deprioritize or skip crypto, sports, geopolitical.
5. **Asymmetric thresholds:** Research validates our NO-bias finding — favorite-longshot bias is structural in prediction markets.

### MEDIUM-TERM ACTIONS
6. **Multi-model ensemble:** "Silicon crowd" of diverse models is the single highest-impact improvement (Brier 0.20 for 12-model ensemble).
7. **Weather multi-model consensus:** Use GFS + ECMWF + HRRR, not just NOAA alone.
8. **Kelly criterion with quarter-Kelly:** Implement but ONLY after calibration fix (overconfident inputs = overbetting).
9. **Market-making pivot:** Post-fee landscape favors limit orders over taker orders. Investigate maker rebates.

### LONG-TERM RESEARCH
10. **Evaluate Foresight-32B:** Fine-tuned 32B model outperformed all frontier models. Could we run locally or via API?
11. **Ensemble + market consensus:** Bridgewater showed LLM + market price ensemble beats either alone. Consider hybrid approach.
12. **RL fine-tuning:** Train our own calibrated model on Polymarket resolution data.

---

## Priority Stack (ROI-Ranked)
| Rank | Improvement | Expected Impact | Effort | ROI |
|------|------------|----------------|--------|-----|
| 1 | Calibration fix (temperature scaling) | +30-50% ARR | 2h | Extreme |
| 2 | Base-rate-first prompt rewrite | +10-15% ARR | 30min | Extreme |
| 3 | Taker fee awareness | Prevents losses | 1h | High |
| 4 | NO-bias exploitation | +20-35% ARR | 2h | High |
| 5 | Category routing | +10-20% ARR | 2h | High |
| 6 | Multi-model ensemble | +20-40% ARR | 4h | High |
| 7 | Quarter-Kelly sizing | +10-20% ARR | 2h | Medium |
| 8 | Weather multi-model | +5-15% ARR | 3h | Medium |
| 9 | Market-making strategy | New revenue stream | 8h | Medium |
| 10 | RL fine-tuning | +20-40% ARR | 20h+ | Low (effort) |
