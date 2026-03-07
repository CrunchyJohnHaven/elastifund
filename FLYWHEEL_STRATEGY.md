# Elastifund: The Flywheel
**Version:** 2.0.0 | **Date:** March 7, 2026 | **Author:** John Bradley
**Repo:** github.com/CrunchyJohnHaven/elastifund (PUBLIC)

---

## What This Document Is

This is the master strategy for Elastifund. Not the trading strategy — the *project* strategy. It describes a repeating cycle that continuously searches for trading edges in prediction markets, tests them rigorously, publishes the results openly, and uses that published research to build the most comprehensive educational resource on agentic trading systems in the world.

The trading is real. The capital is real. But the primary output isn't returns — it's knowledge. The goal is to become the definitive source on what happens when you point AI agents at financial markets and measure every outcome rigorously.

**The thesis:** The fastest way to build a world-class trading system is to build it in public. Open-source attracts talent. Transparency builds trust. Documentation forces rigor. And the flywheel of research, test, publish, attract collaborators, improve, repeat creates compounding advantages that a closed system can't match.

**The open-source bet:** The value of attracting smart collaborators, building public credibility, and forcing ourselves to be rigorous exceeds the value of whatever specific edge might leak. The architecture, research methodology, and educational content are the moat — not any single trading signal.

---

## The Core Frame: An Agent-Run Company

Elastifund is not a fund where a human makes trading decisions with AI assistance. It's the opposite: **the AI agent makes every trade decision autonomously** — what to trade, when to trade, how much to bet. But be precise about what that means. The human (John Bradley) designs the system architecture, selects platforms, sets risk parameters (Kelly fractions, daily loss limits, category filters), writes prompts, and defines safety boundaries. The agent operates within those constraints. John never overrides individual trade decisions. If the agent is wrong, John improves the system, not the trade.

The agent is not encouraged to pursue any particular strategy. Its only mandate is: **maximize risk-adjusted returns within defined safety boundaries.** Not "make as much money as possible" unconstrained — the safety rails exist because unconstrained optimization is reckless. There is no strategy preference. No pet theory. No ego. If the agent determines that the highest-EV use of capital is to sit in cash and wait, it sits in cash and waits. If it finds an edge in weather markets, it trades weather.

**John's role:** Build the decision infrastructure. Improve the machine. Set safety constraints. Document what the machine does. Share the machine with the world.

**The agent's role:** Find edges. Test edges. Trade edges. Report results. Reject bad ideas. Continuously adapt. All within John's constraints.

This is what "agentic trading" actually means — not "AI-assisted trading" but "AI-directed trading with human infrastructure support." John builds the decision architecture; the agent operates within it. The distinction matters because it's the future of quantitative finance and almost nobody is building this way in public.

---

## The Flywheel (6 Phases, Repeating)

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   PHASE 1          PHASE 2          PHASE 3                 │
│   RESEARCH  ───►  IMPLEMENT  ───►  TEST                     │
│   Generate         Update code      Run hypothesis           │
│   hypotheses       & task list      through pipeline         │
│                                                              │
│       ▲                                         │            │
│       │                                         ▼            │
│                                                              │
│   PHASE 6          PHASE 5          PHASE 4                 │
│   REPEAT    ◄───  PUBLISH    ◄───  RECORD                   │
│   Feed results     Update website   Write findings           │
│   into next        & command nodes  to top-level docs        │
│   research cycle                                             │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Phase 1: RESEARCH — Generate New Hypotheses

**What happens:** We use Claude Deep Research, ChatGPT Deep Research, Gemini, and manual investigation to generate batches of trading strategy hypotheses. Each batch targets a specific category (microstructure, information latency, behavioral bias, etc.) and produces 10-100 concrete, testable ideas.

**Input:** Previous cycle's findings, current market conditions, new data sources discovered, competitor analysis.

**Output:** A ranked list of strategy hypotheses in the standard format (signal definition, data source, expected alpha, implementation plan).

**Key document:** `research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md` (the 100-strategy prompt template).

**Where results go:** New hypotheses filed in `research/dispatches/` with priority tags (P0-P3) and added to `research/edge_backlog_ranked.md`.

### Phase 2: IMPLEMENT — Update Code & Task List

**What happens:** The top 3-5 hypotheses from each research batch are turned into code. Each strategy gets a module in `src/strategies/`, a data feed integration if needed, and integration with the hypothesis testing pipeline.

**Input:** Ranked hypothesis list from Phase 1.

**Output:** Working code committed to GitHub, updated task list, new data collection running.

**Key document:** `ProjectInstructions.md` Section 9 (Priority Queue) updated to reflect current build targets.

**Where results go:** GitHub commits on `main`. Each strategy implementation gets a PR with the hypothesis write-up in the description.

### Phase 3: TEST — Run Through the Pipeline

**What happens:** The Edge Discovery System (`src/main.py`) runs the new strategy through its gauntlet: data collection, feature engineering, backtesting with realistic costs, statistical validation, automated kill rules. This is the moment of truth.

**Input:** Implemented strategy code + accumulated market data.

**Output:** Pass/fail verdict with detailed metrics (win rate, EV, Sharpe, drawdown, calibration error, regime stability).

**Key document:** `FastTradeEdgeAnalysis.md` auto-updated after each pipeline run.

**Where results go:** `reports/run_<timestamp>_summary.md` and `reports/run_<timestamp>_metrics.json`.

### Phase 4: RECORD — Write Findings to Top-Level Documents

**What happens:** Whether the strategy passed or failed, we record EVERYTHING. What we tested, what the data showed, why it worked or didn't, what we learned. This is the most important phase for the educational mission.

**Input:** Test results from Phase 3.

**Documents updated:**
- `FastTradeEdgeAnalysis.md` — Current status of all tested strategies
- `EDGE_DISCOVERY_SYSTEM.md` — Updated with new strategy families or pipeline changes
- `COMMAND_NODE_v1.0.2.md` — Updated with latest findings, deployed strategies, lessons learned
- `research/edge_backlog_ranked.md` — Re-ranked based on test results
- `README.md` — Updated metrics if any strategy is promoted to live

**The recording discipline:** Every strategy we test gets a permanent entry. We never delete a failed strategy from the record. The diary of failures is MORE valuable than the diary of successes — it maps the territory of what doesn't work, which is the real contribution to the field.

### Phase 5: PUBLISH — Update Website & Command Nodes

**What happens:** Top-level documents are copied to our command nodes (ChatGPT web, Claude web) so all AI agents have current context. The website (future: johnbradleytrading.com) is updated with the latest research diary entries, strategy analyses, and system architecture documentation. The GitHub repo is public — anyone can see the code.

**The copy sequence:**
1. Push updated docs to GitHub (`git push origin main`)
2. Copy `COMMAND_NODE_v1.0.2.md` into new ChatGPT and Claude web sessions
3. Copy `ProjectInstructions.md` into new Claude Code sessions
4. Update website with new diary entries and strategy analyses

### Phase 6: REPEAT — Feed Results Into Next Research Cycle

**What happens:** The findings from this cycle become the input for the next research prompt. Strategies that failed reveal *why* they failed, which points toward what might work instead. The research prompt is refined based on what we've learned.

**The compounding effect:** Each cycle makes the next cycle better. We accumulate data, eliminate dead ends, and narrow the search space. After 10 cycles, we've tested 50+ strategies and our understanding of prediction market dynamics is deeper than anyone who hasn't done this systematic work.

---

## What We're Really Doing (The Meta-Strategy)

Here's the thing I want to be explicit about:

**We are interested in something very fundamental.** We are interested in creating the most comprehensive, publicly available resource on agentic trading systems that has ever existed. A massive website that teaches you absolutely everything you could ever want to know about what happens when you point AI agents at financial markets and measure every outcome.

Think about it this way: I'm actually not focused on finding successful agentic trading algorithms. I'm interested in establishing myself as an expert in agentic trading. So the solution is to host a website at johnbradleytrading.com that an experienced trader visits and says: "This is the best resource I have ever seen on this subject. It has something to teach anyone who visits — from complete beginners to seasoned quants. This must be made by a leading expert in this space. I want to work with him."

When my dad sees it he should say: "I really understand this, it's incredibly clear and impressive. I want to invest in this project."

It should be a daily read for anyone in the space — demonstrating the sophisticated ideas we're testing on a daily basis.

**We are not primarily trying to find profitable trading algorithms.** We might find some. The system is designed to give us the best possible chance. But the probability of a solo operator consistently beating the market is low. The edges are thin, the competition is real.

**What we ARE doing is building the most rigorous, comprehensive, publicly documented exploration of agentic trading systems ever assembled.** Every strategy we test, every failure we document, every piece of infrastructure we build — this is the real asset. The trading is the laboratory. The research is the product. The public GitHub repo is the proof of work.

Here's what we don't say enough: this exploration is addictive. There's an intellectual high that comes from building these systems — the moment you see a potential edge in the data, the rabbit holes of market microstructure research, the satisfaction of a clean backtest even when it kills your hypothesis. The diary should convey this. The website should make visitors feel the pull of the work itself, the artform of building autonomous trading systems. When a quant trader reads our diary, she should feel the same itch we feel — the "what if I tried THIS" impulse that makes you stay up until 3am coding a new strategy module. That contagious enthusiasm, combined with rigorous methodology, is what turns visitors into contributors.

Why this works:

1. **There is no existing "textbook" on agentic trading.** The field is brand new. Nobody has published a running, open-source diary of "here's what we built, here's what we tested, here's exactly what happened."

2. **The diary of failures is as valuable as any success.** When we test 100 strategies and find that 95 don't survive realistic cost assumptions — that IS the finding. It maps the territory.

3. **Expertise is demonstrated, not claimed.** Anyone can say "I'm an expert in agentic trading." Very few people can point to a public record of 50+ systematically tested strategy hypotheses with full methodology, code, and results. The website IS the credential.

4. **The GitHub repo is the moat.** A public, well-documented, working system that anyone can fork and run. This attracts contributors, creates accountability, and builds trust.

5. **The network effects compound.** As the site becomes more comprehensive, it attracts visitors, some of whom become contributors, some of whom become investors, some of whom become collaborators with real trading experience.

---

## About John Bradley

John Bradley is building agentic moneymaking machines. Not trading — building *systems that trade.* The distinction matters.

John doesn't pick stocks, doesn't read charts, doesn't have "market intuition." He builds AI agents, gives them a mandate ("make as much money as possible with these resources"), and documents every decision the system makes. His job is to improve the machine, not to be the machine.

Background: Builder. Not a trader. No finance degree, no Wall Street experience. Self-taught in machine learning, LLM systems, and quantitative methods. Started this project in February 2026 with $0 and an API key. Built everything you see in the repo in 3 weeks. The question isn't "does John have the right credentials?" — it's "can anyone else show you a public record of this much systematic work in this space?"

What he's building: The world's most comprehensive open-source system for AI-directed prediction market trading, and the most thorough public research diary on what works and what doesn't in agentic trading.

Mission: 20% of all net trading profits go to veteran suicide prevention. Non-negotiable.

---

## The Website: johnbradleytrading.com

### Who Visits and What They Experience

**John's dad (curious layperson):**
Arrives at the homepage and immediately understands: "My son built an AI system that trades prediction markets, and he's documenting the entire journey publicly." The homepage has a clear, jargon-free explanation of what prediction markets are, what an agentic trading system is, and why this project exists. He can follow the research diary like a blog. He leaves thinking: "This is impressive and I understand it."

**A junior developer interested in AI:**
Finds the architecture documentation and can trace exactly how the system works, from market scanning to order execution. The GitHub repo is well-documented. She can clone the repo and run a paper-trading version locally within an hour. She learns something about prediction markets, API integration, position sizing, and AI agent design that she couldn't find anywhere else in one place.

**An experienced quantitative trader:**
Goes straight to the strategy taxonomy and finds the most comprehensive public catalog of prediction market trading strategies he's ever seen. The backtest methodology is rigorous. The failure documentation is honest. He sees edge cases he hadn't considered and wants to contribute. He says: "This person understands the design space deeply. I want to work with them."

**A potential investor:**
Sees the live performance dashboard showing real trades with real money. Reads the risk documentation and is impressed by the honesty about what doesn't work. The transparency and systematic approach are exactly what they'd want from someone managing their money.

### Content Principles

1. **Layered depth.** Every topic has a 30-second version (for dad), a 5-minute version (for a curious developer), and a 30-minute version (for an expert). Nobody feels lost; nobody feels bored.
2. **Failures are features.** The failed strategies section is as detailed as the successful ones. An expert learns more from honest failure analysis than from cherry-picked wins.
3. **Show the work.** Every claim links to evidence — a backtest result, an academic paper, raw data. The code is on GitHub. The math is in the documents. Anyone can verify.
4. **Update constantly.** New diary entries multiple times per week. Strategy library grows with every flywheel rotation. Staleness kills credibility.
5. **20% to veterans.** Prominently featured. Not marketing — a genuine commitment. The website shows cumulative amount allocated even at $0 profit, because stating the commitment publicly creates accountability.

### Content Structure

```
johnbradleytrading.com/
├── /                           ← Homepage: thesis, live stats, start here
├── /about                      ← John's bio, the agent-run company concept
├── /diary                      ← Daily research diary (the running log)
│   ├── /2026-03-07             ← Today's entry
│   └── ...
├── /strategies                 ← The Strategy Encyclopedia
│   ├── /tested                 ← Strategies run through pipeline (pass or fail)
│   ├── /backlog                ← Strategies queued for testing
│   └── /rejected               ← Strategies rejected (with detailed reasons)
├── /system                     ← Technical architecture
│   ├── /pipeline               ← Hypothesis testing pipeline
│   ├── /data-feeds             ← Every data source, with code examples
│   ├── /execution              ← Order placement and management
│   └── /infrastructure         ← VPS, deployment, monitoring
├── /education                  ← Learning resources for all levels
│   ├── /prediction-markets-101
│   ├── /agentic-trading-101
│   ├── /calibration
│   ├── /kelly-criterion
│   └── /market-microstructure
├── /research                   ← Deep research outputs
├── /performance                ← Live trading results (when live)
├── /mission                    ← 20% to veteran suicide prevention
├── /github                     ← Link to public repo
└── /contribute                 ← How to get involved
```

### The Daily Diary Format

```markdown
# Day [N]: [Date] — [One-Line Summary]

## What the Agent Did Today
[What the system decided, what it traded, what it tested]

## What I (John) Did Today
[Infrastructure improvements, research cycles, system upgrades]

## Strategy Updates
- [Strategy X]: [Status, test results, lessons]

## Key Numbers
| Metric | Value |
|--------|-------|
| Strategies tested to date | X |
| Capital deployed | $X |
| Paper/Live P&L today | +/-$X |

## What We Learned
[The most important insight, written so anyone can understand it]

## Tomorrow's Plan
[What's next]
```

---

## Current System Status (March 7, 2026)

### What We've Built (Real, Working)
- **Live Trading Bot:** Deployed to Dublin VPS (AWS Lightsail), placing real orders on Polymarket since March 7, 2026
- **4 Signal Sources:** LLM Ensemble + Smart Wallet Flow + LMSR Bayesian + Cross-Platform Arb Scanner
- **Edge Discovery Pipeline:** 10 strategy families, automated kill rules, auto-generated reports, 83 features
- **LLM Prediction Bot:** 100+ markets every 3 min, Platt calibration, 71.2% backtest win rate
- **345 Passing Tests:** Full test suite across all modules
- **74 Research Dispatches:** Original research across calibration, ensemble, microstructure
- **30-Strategy Ranked Backlog:** Scored and prioritized for implementation
- **Public GitHub Repo:** All code, docs, research publicly available

### What We Haven't Proven (Honest)
- Live trading just started — no resolved positions yet
- All 9 edge discovery hypotheses currently show REJECT ALL (insufficient data)
- Small initial bankroll — months needed for statistical significance
- Website doesn't exist yet — it's markdown files in a repo
- No external contributors yet

### The Honest Path Forward
1. Keep running the pipeline. More data = more strategies properly testable.
2. Start publishing the diary immediately. Failures are content.
3. Go live with tiny capital the moment any strategy passes validation.
4. Use every research cycle to generate website content.
5. Make the GitHub repo the best-documented agentic trading system in existence.

---

## Success Metrics

### For the Trading System
- Strategies tested: 50+ within 60 days
- Validated edge found: at least 1 surviving all kill rules
- Live P&L: any positive P&L from real trading

### For the Website / Educational Platform
- Daily diary entries published continuously
- 100 unique visitors within first month
- 50 GitHub stars within 3 months
- At least 1 external contributor
- At least 1 experienced trader says "this is impressive"
- Dad reads the homepage and understands it

### For the Mission
- 20% of net profits to veteran suicide prevention (when profitable)
- All financial results published openly

---

## Pipeline Per Cycle (3-5 Days)

**Day 1: Research** — Run Deep Research prompt, rank hypotheses, update backlog, write diary
**Day 2-3: Implement & Test** — Code top 3 strategies, run pipeline, write diary
**Day 4: Record & Publish** — Update all top-level docs, push to GitHub, update website, write diary
**Day 5: Review & Plan** — Assess cycle, refine next research prompt, write diary

---

## Document Hierarchy

```
ALWAYS UPDATED (every cycle):
├── FastTradeEdgeAnalysis.md
├── research/edge_backlog_ranked.md
└── Diary entry on website

UPDATED ON MEANINGFUL CHANGES:
├── COMMAND_NODE_v1.0.2.md
├── ProjectInstructions.md
├── EDGE_DISCOVERY_SYSTEM.md
└── README.md

UPDATED MONTHLY:
├── docs/strategy/STRATEGY_REPORT.md
└── Fund investor update
```

---

*This document is the north star. Everything we build serves the flywheel. Every line of code generates a diary entry. Every diary entry teaches someone something. Every lesson makes the next cycle better. The machine runs. The machine learns. The machine publishes. Repeat.*
