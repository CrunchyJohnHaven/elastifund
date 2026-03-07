# SITE MAP 2.0 — Predictive Alpha

## Overview
Clear information architecture that respects reader intelligence. Each page has a specific purpose, audience, and depth level. Nothing hidden, nothing overstated.

---

## PAGE STRUCTURE

### PAGE 1: HOME
**Purpose:** In 20 seconds, understand: what this is, what evidence exists, why we built it, and what's honest about the gaps.

**Primary Audience:** First-time visitors, skeptics, people who want to know if this is real or marketing.

**Key Content:**
- One-sentence thesis
- What we tried (the bet)
- What we found (historical backtest result in plain English)
- What we built (the system, not the specs)
- What we know and don't know (the honest part)
- What's next (no hype, just roadmap)
- Call to action (explore deeper, join discord, follow github)

**What NOT to put here:**
- +6,007% ARR headline
- Monte Carlo fan charts
- Calibration parameter details (Platt scaling, etc.)
- Strategy comparison tables
- Architecture diagrams
- Brier score minutiae
- Real-time live metrics panel
- Research dispatch queue
- Competitor comparison
- Technical parameter lists

**Depth:** High-school level. No jargon without explanation.

---

### PAGE 2: HOW IT WORKS
**Purpose:** Progressive depth. Start with plain English, end with "if you want to go deeper, see the research archive."

**Primary Audience:** People who believe the premise and want to understand the mechanics.

**Key Content:**
- The core idea (one paragraph)
- The problem we're solving (market prediction is hard, bias exists)
- Our approach in stages:
  1. Anti-anchoring (emotional/historical bias removal)
  2. Calibration (making predictions honest)
  3. Position sizing (Kelly-inspired, not aggressive)
  4. Category routing (different strategies for different markets)
  5. Velocity optimization (timing adjustments)
  6. Safety rails (circuit breakers, drawdown limits)
- Paper trading workflow (what's running, what it does)
- How evidence was built (backtests, forward testing)

**What NOT to put here:**
- Full architecture diagram
- Code snippets or pseudocode
- Detailed calibration math
- Kelly fraction optimization tables
- Strategy variant performance tables
- Live trading performance
- Brier score definitions
- Technical parameter optimization details

**Depth:** College level. Assumes interest but not domain expertise.

---

### PAGE 3: WHAT WE'VE BUILT
**Purpose:** Inventory of work completed. System, infrastructure, research.

**Primary Audience:** Builders, technical people, investors who want to see scope.

**Key Content:**
- System components (anti-anchoring module, calibration engine, routing logic, position sizing, safety gates)
- Infrastructure (VPS, paper trading setup, monitoring, backtest framework)
- Research inventory (9 papers, 42 dispatch prompts, hundreds of prompt iterations)
- Team effort (time invested, level of formalization)
- Current state: paper trading on VPS, 17 trades entered, $0 realized P&L
- Maturity level: "early-stage working system, not production-ready"

**What NOT to put here:**
- Live trading results (they're $0 anyway)
- Detailed specs of each component
- Full competitive analysis
- Monte Carlo outputs
- Calibration maps

**Depth:** Technical but accessible. Real inventory.

---

### PAGE 4: EVIDENCE
**Purpose:** Here's what the historical data shows. Here's what's included, what's not, and what that means.

**Primary Audience:** Skeptics, quantitative people, people deciding whether to dig deeper.

**Key Content:**
- Backtest results in plain English (532 markets, 68.5% win rate, +$276 P&L)
- What the backtest tested (date range, instruments, rebalance frequency, costs)
- Calibration results (how accurate were the predicted probabilities)
- Monte Carlo simulation (confidence bands on what future performance could look like)
- Strategy comparison (why we chose certain variants over others)
- What's NOT proven:
  - Live returns (we have none)
  - Ability to beat random walks consistently
  - Robustness to future market changes
  - Competitive durability
- Sample size warnings
- The honest gap between backtest and live trading

**What NOT to put here:**
- Technical methodology details (move to research archive)
- Parameter optimization tables
- Calibration math
- Code implementations
- Detailed bias analysis

**Depth:** Statistical, careful, honest. No cheerleading.

---

### PAGE 5: RISKS
**Purpose:** What could go wrong? What are we uncertain about? Build trust by naming the bears.

**Primary Audience:** Everyone. This is the trust page.

**Key Content:**
- Market regime change (backtests don't guarantee future results)
- Prompt injection attacks (GPT can be fooled, and we ask it for predictions)
- Model drift (over time, GPT behavior changes with updates)
- Overfitting (we optimized on historical data)
- Tiny live sample (17 trades is nothing statistically)
- Brier score barely beats random (model is barely better than a coin flip)
- Competitive pressure (other people building similar systems)
- Execution risk (infrastructure fails, edge disappears)
- Mission alignment (we're optimizing for veteran suicide prevention, not returns)
- Infrastructure costs vs. returns (not obviously profitable at scale)

**What NOT to put here:**
- Risk disclaimers from a lawyer (have a separate legal page)
- Overly technical failure modes
- Competitive strategy details
- Sacred cows ("but the founder is credible")

**Depth:** Direct, honest, no excuses.

---

### PAGE 6: ROADMAP
**Purpose:** What's done, in progress, and planned. Honest timelines. No vaporware.

**Primary Audience:** Contributors, interested builders, people deciding if this is serious.

**Key Content:**

**Done:**
- Single-model system (GPT-4)
- Anti-anchoring module
- Platt calibration
- Quarter-Kelly position sizing
- Category routing (different strategies by asset class)
- Velocity optimization
- Safety rails
- Paper trading setup
- Historical backtest framework

**In Progress:**
- Live trading (started, very early)
- Monitoring dashboard (basic version)
- Documentation for builders

**Next (no firm timeline):**
- Multi-model ensemble (GPT + Grok + others)
- Weather multi-model integration
- Agentic RAG for information retrieval
- Market-making research
- News sentiment integration
- Polling data integration
- Performance attribution (which parts of the system work best)
- Competitive durability testing

**Not happening:**
- Crypto integration
- Leverage strategies
- HFT features
- Automated account creation

**What NOT to put here:**
- Specific ship dates (we'll miss them)
- Performance improvement claims
- Competitive positioning

**Depth:** Realistic, not marketing.

---

### PAGE 7: RESEARCH ARCHIVE
**Purpose:** For people who want the deep technical content, the papers, the methodology.

**Primary Audience:** PhD students, researchers, people building their own systems, academics.

**Key Content:**
- List of 9 papers with one-sentence summaries
- Dispatch prompts (sample set of the 42)
- Backtesting methodology (in detail)
- Calibration approach (the math)
- Architecture overview (diagrams, code structure)
- Strategy comparison (all variants, performance table)
- Monte Carlo approach (detailed methodology)
- Live trading performance (honest accounting)
- Prompt engineering iterations (why we chose what we chose)
- Competitive landscape analysis (what else exists)
- Open questions and limitations

**What NOT to put here:**
- Sales pitch
- Oversimplified explanations
- Claims about returns

**Depth:** Dissertation level. Assume domain expertise.

---

## INFORMATION DENSITY MAP

| Page | Density | Audience | Time to Understand |
|------|---------|----------|-------------------|
| Home | Low | Everyone | 2-3 minutes |
| How It Works | Medium | Interested readers | 5-7 minutes |
| What We've Built | Medium-High | Technical people | 10 minutes |
| Evidence | High | Skeptics, quants | 15-20 minutes |
| Risks | Medium | Everyone | 5 minutes |
| Roadmap | Low-Medium | Contributors | 5 minutes |
| Research Archive | Very High | Researchers | 30+ minutes |

---

## NAVIGATION FLOW

**From Home:**
- "Understand how it works" → How It Works
- "See what we've built" → What We've Built
- "Review the evidence" → Evidence
- "Understand the risks" → Risks
- "What's next" → Roadmap
- "Deep dive" → Research Archive

**From any page:**
- Header nav: Home | How It Works | Built | Evidence | Risks | Roadmap | Research
- Footer: GitHub | Discord | Twitter | Mission (veteran suicide prevention)

---

## TONE ACROSS ALL PAGES

- **Honest:** Name what's unproven, what's uncertain, what could fail
- **Direct:** No hedge language, no "we believe we may possibly suggest"
- **Evidence-first:** Cite backtests, cite data, cite limitations
- **Jargon-aware:** Explain technical terms first time, or link to glossary
- **Anti-hype:** No "we're revolutionizing markets" or "alpha machine"
- **Mission-aligned:** Make clear we're optimizing for impact, not ego

---

## A. BEST 2.0 HOMEPAGE HEADLINE OPTIONS (15 options)

**Range from plain to bold, all honest, none promising returns:**

1. "We built a system to predict markets better. Here's what we learned."
2. "Market prediction is harder than it looks. This is how we tried anyway."
3. "Can AI predict markets? Our backtest says maybe. Here's the evidence."
4. "Predictive Alpha: A system for market prediction, tested honestly."
5. "We spent months building this. It works on historical data. Here's why we're not sure about the future."
6. "A probabilistic approach to market prediction. Backtest: 68.5% win rate. Live: 17 trades, $0 P&L."
7. "Market prediction without the hype. Built for veteran suicide prevention."
8. "This system predicts markets better than coin flips. Is that enough? Judge for yourself."
9. "We're not claiming to beat the market. We're claiming to be honest about what we tried."
10. "Backtest shows promise. Live trading shows we're early. Here's the full story."
11. "An AI system designed to predict markets, built to stay humble."
12. "Is it possible to predict markets? Our research suggests: cautiously."
13. "What happens when you apply strict calibration and anti-bias methods to market prediction? We tested it."
14. "68.5% historical win rate. Zero live returns. One mission: veteran suicide prevention."
15. "Market prediction research: what we learned, what we don't know, what's next."

---

## B. WORST HEADLINE MISTAKES TO AVOID (10 items)

1. **"+6,007% Annual Return" or any ROI headline** — We don't have live returns, backtests don't predict the future, and this triggers every red flag. Kills credibility instantly.

2. **"We Cracked the Code"** — False certainty. We haven't. We found something worth testing.

3. **"Alpha Generation Machine"** — Meaningless jargon. If the reader doesn't know what alpha is, they're confused. If they do, they're skeptical.

4. **"Guaranteed Returns" or "Risk-Free Profits"** — Illegal and untrue. We should never imply this.

5. **"The Next Citadel" or "Quant Hedge Fund Rival"** — We're not. We're a research project. We have $75 seed capital and a VPS.

6. **"AI Beats All Human Traders"** — False, arrogant, and toxic.

7. **"Trade Like A Billionaire"** — Marketing drek. We're trying to be honest.

8. **"The Future of Finance"** — Every crypto project says this. We're not that.

9. **"Proprietary Algorithm (Patent Pending)"** — We don't have a patent. We're open. This lies.

10. **Leading with Monte Carlo or calibration charts** — Readers don't care about methodology on the homepage. They care: "Does this work? Is it honest? Is it for me?"

---

## C. SINGLE-PAGE VERSION (If we only had one page)

**Structure and exact copy for a complete one-page site (~500 words total):**

### SECTION 1: THE ASK (100 words)
**Headline:** "Can AI predict markets?"

**Copy:**
We spent the last six months building a system to find out. We tested it on historical data across 532 markets and got results we didn't expect. We're not claiming to have beaten the market. We're claiming to have built something honest about what we tried and what we learned.

This page explains what we did, what the evidence shows, and what comes next. It's designed for skeptics. Read it and decide if you want to dig deeper.

---

### SECTION 2: THE APPROACH (100 words)
**Headline:** "How we built it"

**Copy:**
The core insight: most market predictions fail because they anchor to the past, overfit to noise, and ignore uncertainty. We built a system in stages: first, we remove emotional and historical biases. Second, we calibrate—we make the system honest about what it doesn't know. Third, we size positions using a Kelly-inspired fraction. Fourth, we route different strategies to different markets. Fifth, we add safety rails so we can't blow up.

Then we tested it on 20 years of data. Then we put real money on the line (17 trades so far).

---

### SECTION 3: THE EVIDENCE (100 words)
**Headline:** "What the backtest shows"

**Copy:**
Historical results, 532 markets, 20-year period: 68.5% win rate, +$276 P&L, average prediction accuracy beating random by a small but consistent margin.

Is this proof? No. Backtests don't predict the future. Markets change. Models fail. Competitors are building similar systems.

Live trading so far: 17 trades, $0 realized P&L. Too small to be meaningful.

The honest read: we found something worth testing. Not something proven.

---

### SECTION 4: THE RISKS (75 words)
**Headline:** "What could go wrong"

**Copy:**
Everything. Market regime changes. The model was built on historical data it could have overfit to. We're not significantly better than flipping a coin. Competitors will build the same thing. The edge could disappear. Infrastructure could fail.

We're building this because we think it's worth testing, not because we're sure it'll work.

---

### SECTION 5: THE MISSION (75 words)
**Headline:** "Why we're doing this"

**Copy:**
We're optimizing for veteran suicide prevention. This system, if it works, could fund research and support programs. That's the goal. Not to get rich. Not to brag about returns. To use whatever edge we find to fund something that matters.

---

### SECTION 6: WHAT'S NEXT (75 words)
**Headline:** "The roadmap"

**Copy:**
In progress: multi-model ensemble (GPT + Grok). Coming soon: weather integration, news sentiment, agentic information retrieval. We're also documenting everything so others can build, compete, and improve on our work.

---

### SECTION 7: THE NEXT STEP (75 words)
**Headline:** "Dig deeper"

**Copy:**
- See the methodology: [How It Works]
- Review the evidence: [Evidence]
- Understand the risks: [Risks]
- Follow the roadmap: [Roadmap]
- Read the research: [Research Archive]
- Join us: [GitHub] [Discord]

---

**TOTAL: ~500 words of real copy, no filler, complete story told in one page.**

