# Research Dispatch System

## How to Use
Each prompt file is tagged with the tool to dispatch it to:
- **CLAUDE_CODE** → Paste into Claude Code for implementation
- **CLAUDE_DEEP_RESEARCH** → Paste into Claude.ai with Deep Research enabled
- **CHATGPT_DEEP_RESEARCH** → Paste into ChatGPT with Deep Research/browsing (or GPT-5.4)
- **COWORK** → Paste into Claude Cowork for collaborative analysis
- **GROK** → Paste into Grok for real-time data analysis

## Priority Levels
- **P0** — Do immediately, highest ARR impact
- **P1** — Do this week, significant ARR impact
- **P2** — Do when P0/P1 are running, moderate impact
- **P3** — Background research, long-term improvement

## Tracking
Update status in each file header as you dispatch:
- READY → DISPATCHED → COMPLETED → INTEGRATED

## Standard Operating Procedure
All new research must trigger a full review of every project document to check for stale information or missing insights. Do not stop work until every document has been reviewed and all improvements have been made. This is enforced by the weekly `research-review-and-document-sync` scheduled task (Wednesdays 10am).

---

## Full Task Index (as of 2026-03-05)

### P0 — Critical / Immediate (Do NOW)

| # | Task | Tool | Status | ARR Impact |
|---|------|------|--------|------------|
| 01 | Calibration fix (temperature scaling) | CLAUDE_CODE | READY | +30-50% |
| 02 | Multi-model ensemble architecture | CLAUDE_CODE | READY | +20-40% |
| 03 | Market selection optimization | CHATGPT_DEEP_RESEARCH | READY | +15% |
| 04 | Prompt engineering research | CLAUDE_DEEP_RESEARCH | READY | +10-20% |
| 05 | NO-bias exploit implementation | CLAUDE_CODE | READY | +20% |
| 25 | Investor agreement | COWORK | READY | — |
| 26 | Backtest validation framework | CLAUDE_DEEP_RESEARCH | COMPLETE | — |
| 27 | Taker fee impact analysis | CLAUDE_CODE | READY | Critical |
| 28 | Weather multi-model consensus | CLAUDE_CODE | READY | +10% |
| **32** | **Combined backtest re-run (ALL improvements)** | **CLAUDE_CODE** | **READY** | **Determines real performance** |
| **33** | **Live vs backtest scorecard** | **COWORK** | **READY** | **Validation** |
| **34** | **Kelly criterion integration into bot** | **CLAUDE_CODE** | **READY** | **+40-80%** |
| **35** | **Monte Carlo stress test** | **COWORK** | **READY** | **Investor credibility** |
| **36** | **Switch paper → live trading** | **CLAUDE_CODE** | **READY** | **Infinite (only live P&L matters)** |
| **37** | **News sentiment data pipeline** | **CLAUDE_CODE** | **READY** | **+15-30%** |
| **49** | **Systematic edge discovery** | **CLAUDE_DEEP_RESEARCH** | **READY** | **Unknown — potentially massive** |
| **50** | **Superforecaster techniques pipeline** | **CLAUDE_DEEP_RESEARCH** | **READY** | **+15-30%** |
| **51** | **Automated self-improving architecture** | **CLAUDE_CODE** | **READY** | **Compounding** |
| **52** | **Five-day sprint plan** | **COWORK** | **READY** | **Meta — orchestrates all work** |
| **53** | **Position deduplication / correlation** | **CLAUDE_CODE** | **READY** | **Risk reduction** |
| **54** | **Enhanced market scanner** | **CLAUDE_CODE** | **READY** | **+10-20%** |
| **55** | **Resolution time optimizer (capital velocity)** | **CLAUDE_CODE** | **READY** | **+50-100%** |
| **56** | **Order book analysis & execution intelligence** | **CLAUDE_CODE** | **READY** | **Prevents slippage** |
| **57** | **Category-specific model configs** | **CLAUDE_CODE** | **READY** | **+15-25%** |
| **59** | **Government data pipeline (FRED, BLS)** | **CLAUDE_CODE** | **READY** | **+10-20%** |
| **60** | **Pre-resolution exit strategy** | **CLAUDE_CODE** | **READY** | **+20-40%** |

### P1 — This Week (Significant Impact)

| # | Task | Tool | Status | ARR Impact |
|---|------|------|--------|------------|
| 06 | Kelly optimization research | COWORK | COMPLETE | +40% |
| 07 | Polymarket API deep dive | CHATGPT_DEEP_RESEARCH | READY | — |
| 08 | Superforecasting techniques | CLAUDE_DEEP_RESEARCH | READY | +15% |
| 09 | Backtest expansion | CLAUDE_CODE | READY | +10% |
| 10 | Investor report generation | COWORK | READY | — |
| 11 | Grok API integration | CLAUDE_CODE | READY | +10% |
| 12 | OpenAI API integration | CLAUDE_CODE | READY | +10% |
| 29 | Foresight-32B evaluation | CLAUDE_DEEP_RESEARCH | READY | +20-40% |
| 30 | Market-making strategy research | CHATGPT_DEEP_RESEARCH | READY | New revenue |
| 31 | LLM + market consensus ensemble | CLAUDE_CODE | READY | +15-30% |
| **38** | **Polling data pipeline** | **CLAUDE_CODE** | **READY** | **+10-20%** |
| **39** | **Multi-model ensemble implementation** | **CLAUDE_CODE** | **READY** | **+20-40%** |
| **40** | **Telegram daily P&L digest** | **CLAUDE_CODE** | **READY** | **Operational** |
| **41** | **Informed market-making bot** | **CLAUDE_CODE** | **READY** | **New revenue 2-5×** |
| **42** | **Social sentiment research** | **CHATGPT_DEEP_RESEARCH** | **READY** | **+10-20%** |
| **43** | **Cross-platform arbitrage research** | **CHATGPT_DEEP_RESEARCH** | **READY** | **+10-30%** |
| **58** | **ChatGPT 5.4 ensemble integration** | **CLAUDE_CODE** | **READY** | **+10-25%** |

### P2 — When P0/P1 Running (Moderate Impact)

| # | Task | Tool | Status | ARR Impact |
|---|------|------|--------|------------|
| 13 | Historical price analysis | CHATGPT_DEEP_RESEARCH | READY | +5% |
| 14 | Risk management framework | COWORK | READY | — |
| 15 | Prompt A/B testing | CLAUDE_CODE | READY | +5-15% |
| 16 | Time decay analysis | CLAUDE_CODE | READY | +5% |
| 17 | Liquidity analysis | CLAUDE_CODE | READY | +5% |
| 18 | Monte Carlo portfolio sim | CLAUDE_CODE | READY | — |
| 19 | Web scraping edge | CHATGPT_DEEP_RESEARCH | READY | +5-10% |
| 20 | Competitor analysis | GROK | READY | — |
| 24 | Advanced simulation | CLAUDE_CODE | READY | +5% |
| **44** | **Prompt A/B testing framework** | **CLAUDE_CODE** | **READY** | **+5-15%** |
| **45** | **Continuous backtest evaluator** | **CLAUDE_CODE** | **READY** | **Keeps numbers fresh** |
| **46** | **Scaling analysis (AUM capacity)** | **COWORK** | **READY** | **Investor readiness** |
| **47** | **Competitive benchmarking** | **GROK** | **READY** | **Strategic intel** |
| **48** | **Investor report refresh** | **COWORK** | **READY** | **Investor readiness** |

### P0 — NEW SPRINT (2026-03-06): Push Return Confidence & ARR

| # | Task | Tool | Status | ARR Impact |
|---|------|------|--------|------------|
| **61** | **Agentic RAG — real-time web search in prediction pipeline** | **CLAUDE_CODE** | **READY** | **+30–60% (single largest Brier improvement in literature)** |
| **62** | **Category-specific Platt calibration** | **CLAUDE_CODE** | **READY** | **+10–20%** |
| **63** | **Wikipedia pageview + Google Trends signal pipeline** | **CLAUDE_CODE** | **READY** | **+5–15% (free data, 4–24h leading indicator)** |
| **64** | **Polling aggregator integration (FiveThirtyEight + RCP)** | **CLAUDE_CODE** | **READY** | **+8–15% on political markets** |
| **65** | **Live vs backtest scorecard with statistical significance** | **COWORK** | **READY** | **Confidence validation** |
| **66** | **Monte Carlo v2 — stress-tested ensemble projections** | **COWORK** | **READY** | **Investor-grade confidence intervals** |
| **67** | **Fee drag deep analysis — maker vs taker optimization** | **COWORK** | **READY** | **+15–40% from fee elimination** |
| **68** | **ChatGPT 5.4 head-to-head probability benchmark** | **CHATGPT 5.4** | **READY** | **+10–25% (determines ensemble composition)** |
| **69** | **ChatGPT 5.4 optimal forecasting prompt discovery** | **CHATGPT 5.4** | **READY** | **+5–15%** |
| **70** | **Agentic RAG best practices — API/architecture research** | **CHATGPT_DEEP_RESEARCH** | **READY** | **Informs P0-61** |
| **71** | **News sentiment API evaluation + social signal research** | **CHATGPT_DEEP_RESEARCH** | **READY** | **Informs P0-37** |
| **72** | **Master forecasting prompt v2 (with RAG integration)** | **CLAUDE (conversational)** | **READY** | **+10–20%** |
| **73** | **LLM calibration frontier 2026 — techniques survey** | **CLAUDE_DEEP_RESEARCH** | **READY** | **+20–50% (roadmap from 0.245 → 0.10 Brier)** |
| **74** | **Ensemble + market price integration (Bridgewater method)** | **CLAUDE_DEEP_RESEARCH** | **READY** | **+15–30%** |

### P3 — Background / Long-Term

| # | Task | Tool | Status | ARR Impact |
|---|------|------|--------|------------|
| 21 | Advanced ML features | CLAUDE_DEEP_RESEARCH | READY | Long-term |
| 22 | Scaling analysis | COWORK | READY | Long-term |
| 23 | Legal structure deep dive | CHATGPT_DEEP_RESEARCH | READY | — |

---

## Dispatch Summary by Tool

| Tool | Ready Tasks | Highest Priority |
|------|-------------|-----------------|
| **CLAUDE_CODE** | 01, 02, 05, 09, 11, 12, 27, 28, 31, 32, 34, 36, 37, 38, 39, 40, 41, 44, 45, 51, 53, 54, 55, 56, 57, 58, 59, 60, **61, 62, 63, 64** | **P0-61 (agentic RAG)**, P0-36 (live switch), P0-62 (category calibration) |
| **CLAUDE (conversational)** | **72** | **P0-72 (master prompt v2 with RAG)** |
| **CLAUDE_DEEP_RESEARCH** | 04, 08, 26, 29, 49, 50, **73, 74** | **P0-73 (calibration frontier)**, **P0-74 (market price integration)** |
| **CHATGPT 5.4** | **68, 69** | **P0-68 (head-to-head benchmark)**, **P0-69 (optimal prompt discovery)** |
| **CHATGPT_DEEP_RESEARCH** | 03, 07, 13, 19, 30, 42, 43, **70, 71** | **P0-70 (agentic RAG research)**, **P0-71 (news API evaluation)** |
| **COWORK** | 06, 10, 14, 25, 33, 35, 46, 48, 52, **65, 66, 67** | **P0-65 (live scorecard)**, **P0-66 (Monte Carlo v2)**, **P0-67 (fee analysis)** |
| **GROK** | 20, 47 | P2-47 (competitive benchmarking) |

**DISPATCH ORDER (maximum parallelism):**
1. **Immediately (parallel):** P0-61 + P0-62 + P0-64 → Claude Code | P0-68 + P0-69 → ChatGPT 5.4 | P0-70 + P0-71 → ChatGPT DR | P0-73 + P0-74 → Claude DR | P0-65 + P0-66 → Cowork
2. **After research returns:** P0-72 → Claude (uses P0-73 findings) | P0-63 → Claude Code (lower priority)
3. **After Wave 1 integration:** P0-67 → Cowork (needs live data)
