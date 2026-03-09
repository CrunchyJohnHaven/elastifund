# Elastifund Platform Vision Document

## Purpose and North Star

Elastifund’s platform vision is to become a **self-improving, open-source agentic system** whose prime directive is to **compound value (financial and real-world)** while continuously improving its own capability to do so. This is not positioned as “a bot,” but as a **rigorous, measurable improvement machine** where the “product” is the *system’s compounding capability* and the “UX” is *how quickly a new human (technical or non-technical) can understand, run, and contribute*.  

The strategic wedge is **data advantage through simplicity**: the system should make it obvious that **better agents require better data, better evaluation, and better feedback loops**—and that the Elastic Stack is an unusually strong substrate for that. Elastic explicitly positions itself as powered by “Search AI,” and as “The Search AI Company,” which provides a natural narrative anchor and a language the entire Elastic employee base can recognize and repeat. citeturn8search0turn8search3turn8search7  

A key inspiration is the “agent runs the loop while you sleep” model popularized by entity["known_celebrity","Andrej Karpathy","ai researcher"]’s *autoresearch* concept: a compact arena where an agent modifies code, runs short experiments, keeps improvements, and logs the full chain of evidence so a human can review outcomes in the morning. citeturn0search1 This “arena + loop + evidence” framing maps cleanly to Elastifund: the system can run trading and non-trading experiments, measure outcomes, and only promote changes that improve defined metrics.

Success is therefore not defined by “we have a trading strategy.” It is defined by:

- A **single, understandable story** that makes the system legible in 60 seconds.  
- A **single command path** that gets a new person from zero → running → contributing.  
- A **measurement spine** that outputs four continuously-updating public graphs: performance, improvement velocity, code velocity, and roadmap forecast.  
- A **governance spine** that guarantees rigor: decisions, prompts, forecasts, and evidence are versioned and reviewable.

## Product story and messaging system

The top-of-funnel is messaging. Your transcript is right: if visitors experience confusion at the homepage, the Elastic landing page, the developer guide, or the repo README, you lose them.

### Messaging goals

The messaging must do three things immediately:

First, explain **why this exists** in plain language and with a concrete mental model.  

Second, explain **why Elastic should care**: this is a living demonstration of Search AI + observability + governance powering agentic infrastructure (i.e., the exact domains Elastic sells into). Elastic’s public platform narrative already frames Elastic as an open-source platform for search, observability, and security, which can be directly echoed. citeturn8search3turn8search1  

Third, explain **how a non-technical contributor participates**, without pretending there is zero complexity. A non-technical workflow must be *real*—ideally: “clone/fork, run one installer, click one ‘connect’ flow, watch dashboards, accept auto-generated contribution tasks.” This aligns with open-source onboarding best practice: a README should tell people why the project matters and how to use it, and a “getting started” guide should be task-oriented and achievable quickly. citeturn11search18turn11search8  

### A recommended “message architecture” for the site and repo

Keep the top-level canonical entry points conceptually simple (paths shown rather than full URLs):

```
/              (homepage)
/elastic        (Elastic exec + employee landing page)
/develop        (step-by-step run + contribute)
/leaderboards/trading
/leaderboards/worker
(GitHub repo README)
```

Across all pages, reuse a shared spine of nine short blocks. This produces “perfect messaging” by ensuring consistency:

- **One-line promise**  
- **Who it’s for** (Elastic employees, contributors, observers)  
- **What it is** (“self-improving agentic system”)  
- **What it does today** (the smallest credible set)  
- **How it improves** (the loop + evidence)  
- **What’s measurable** (the four graphs)  
- **What’s safe by default** (paper mode, guardrails, merge gating)  
- **How to participate** (run / contribute / fork)  
- **What’s next** (roadmap forecast)

### Suggested headline positioning for the Elastic landing page

Your initial instinct is strategically aligned with Elastic corporate language: Elastic already uses “Search AI” and “The Search AI Company” as its platform framing. citeturn8search0turn8search3 The landing page can therefore lead with a line that rhymes with Elastic’s own message while still being distinct:

**Option A (most aligned with Elastic positioning)**  
**“Good agents need better data. Elastifund is a live, open-source demonstration of Search AI powering a self-improving agent system.”** citeturn8search7turn8search1  

**Option B (more provocative, still defensible)**  
**“Elastic is the Search AI company. Elastifund is a system that proves it: agents that improve via data, evaluation, and transparent evidence.”** citeturn8search3turn8search7  

**Option C (if you want the simplest “why”)**  
**“An open-source agent that improves itself—measured in public—built on the Elastic Stack.”** citeturn8search1turn8search4  

### Suggested homepage framing

The homepage should not be a pitch to a specific executive. It should frame the project as a public open-source platform:

- **What it is:** a self-improving agent system that runs experiments and publishes results  
- **What results look like:** the four live graphs + leaderboards  
- **What makes it different:** contribution is guided; rigor is versioned; evaluation is continuous  
- **What makes it credible:** explicit integration with real prediction market infrastructures and real observability tooling, paired with strict defaults and safeties  

Because prediction markets increasingly serve as real-time probability signals in media and analytics contexts, it’s credible to position these markets as a “data substrate” for forecasting and agent evaluation. For example, entity["company","Kalshi","prediction market exchange"] has publicly partnered with a major newsroom to integrate real-time prediction data via an API interface, demonstrating mainstream interest in prediction market probabilities as inputs to information products. citeturn7news39  

### Suggested GitHub README framing

The README is the friction point most likely to kill adoption. GitHub’s own guidance is clear: a README exists to tell people why it’s useful and how to use it. citeturn11search18 The repo README should be aggressively short at the top, with depth below:

- 15–25 lines max before the first “Run it” section  
- A single “Quickstart” path that works with paper-trading and demo environments  
- A “What gets measured” section that links to the four graphs  
- A “Contribution modes” section: observer / runner / builder  
- A “Safety & compliance” section that sets expectations: this is research infrastructure, not financial advice, and real-money execution is gated

## Reference architecture and data model

This system must feel elegant. Elegance here means: **one canonical event stream, one canonical state machine, one canonical evaluation harness, and one canonical publishing pipeline.** Everything else is modular.

image_group{"layout":"carousel","aspect_ratio":"16:9","query":["Elastic Stack architecture diagram Elasticsearch Kibana","Kibana dashboard time series visualization example","Polymarket CLOB architecture diagram","Kalshi API architecture diagram"],"num_per_query":1}

### External integration realities

The trading side integrates with two distinct market infrastructures:

- entity["company","Polymarket","prediction market platform"] exposes a CLOB (central limit order book) architecture described as “hybrid-decentralized”—offchain matching with onchain settlement; orders are EIP-712 signed messages and settlement occurs on Polygon. citeturn7search0turn7search6  
- Kalshi provides an Exchange API for market data and trade execution, and its documentation explicitly references a developer agreement, authentication setup, and a demo environment for safer integration testing. citeturn7search1turn7search19  

This matters for architecture: you cannot treat “execution” as a simple function call. The platform must isolate exchange adapters, credential management, rate limiting, and failure handling as first-class surfaces.

### The core platform components

A minimal-but-complete architecture that supports your vision:

**Orchestrator**  
Owns schedules, experiment definitions, and “what to do next.” This is the “JJ brain” that decides: run backtests, run paper strategies, run outreach tasks, propose code changes, or generate a PR.

**Agent runtime(s)**  
At least two categories:

- Trading agents, each a strategy runner + research loop  
- Non-trading agents (the “worker” class), each an outcome-driven system (e.g., SDR agent for a real business)  

**Evaluation harness**  
A deterministic replay / simulator surface for “paper mode,” plus live paper trading and (eventually) live trading. This is where you mirror the spirit of *autoresearch*: modify → run → measure → keep/discard → log. citeturn0search1  

Prediction-market-specific benchmarking research is emerging and supports the need for deterministic, event-driven replay and fee-aware simulation rather than naive backtests. citeturn3academia12 This reinforces the architectural requirement: “leaderboards” must be grounded in reproducible episodes, not just cherry-picked PnL screenshots.

**Data plane**  
Elastic Stack as the event store + search layer + observability layer:

- Ingest all agent events (decisions, orders, fills, errors, evaluations) as structured logs / traces  
- Index documents for explainability (“why did the agent do this?”)  
- Store vector data if you implement retrieval for research and prompt memory (Elastic frames Elasticsearch as supporting structured, unstructured, and vector data for AI applications). citeturn8search4turn0search5  

**Publishing plane**  
A pipeline that turns internal events into public artifacts:

- The four graphs on the site  
- README badges / summary blocks  
- Leaderboards pages

### Deployment posture

Your vision includes an always-on remote instance and many contributor instances. The simplest low-friction start for contributors is “local-only, paper-only.” For the always-on instance, your transcript mentions an Ubuntu container on AWS Lightsail; Lightsail is explicitly positioned as a simplified VPS-like service designed for quick deployment, which fits the simplicity goal. citeturn13search0turn13search1  

For any cloud deployment, key management and least-privilege access must be non-negotiable. AWS IAM best practices explicitly recommend least privilege, MFA, and preferring temporary credentials (roles) over long-term access keys. citeturn13search3turn13search11  

## Measurement, dashboards, and leaderboards

The platform’s credibility will be proportional to the credibility of its measurement. The four graphs you described are the correct backbone, but they must be defined precisely and be resistant to gaming.

### The performance graph

**Goal:** “Estimated run-rate annual % rate of return” should behave like an annualized return estimator and should be paired with risk measures so it cannot be misread as guaranteed performance.

A standard way to speak about annualized compounding is CAGR (compound annual growth rate), which is defined as the annual rate required to grow from a starting value to an ending value across a time interval assuming reinvestment. citeturn12search0turn12search4  

**Proposed approach:** publish:

- Estimated annualized return (rolling window, explicitly labeled as an estimate)  
- Maximum drawdown, which measures the greatest peak-to-trough decline over a period citeturn12search2turn12search6  
- A risk-adjusted metric such as Sharpe ratio (excess return divided by volatility), described in widely used finance references citeturn12search1turn12search12  

This makes the chart harder to hype and easier to defend.

### The improvement velocity graph

This is the “Karpathy mirror” concept: the system is valuable if it improves reliably. *autoresearch* formalizes this: the agent runs many experiments autonomously, keeps only improvements, and reports a log of trials. citeturn0search1  

**Define “improvement velocity” as an explicit derivative:**  
Δ(estimated annualized performance metric) / Δ(time), measured on a rolling basis.

To prevent metric-hacking, this should be tied to a **benchmark suite** (deterministic replay episodes + paper runs). Emerging prediction market benchmarking research reinforces that fee modeling, execution realism, and settlement mechanics can dominate naive performance claims. citeturn3academia12  

### The code commits graph

This should be a literal chart of code velocity, sourced from entity["company","GitHub","software hosting platform"] rather than hand-logged.

GitHub provides a “last year of commit activity” endpoint grouped by week (with per-day breakdown), via repository statistics. citeturn10search0 This gives you a clean, automatable source for the “commits graph” and can be ingested into the Elastic Stack for visualization.

### The feature forecast graph

This is your “diary + forecast” mechanism: a public, continuously-updated timeline containing:

- Features in progress  
- Next checkpoints  
- Forecasted delivery windows  
- “Confidence” indicators (based on tests passing + velocity trends)  
- A changelog of forecast revisions

The most important property is that forecasts are *versioned* and *auditable*, so the project develops a reputation for intellectual honesty.

### The leaderboards

Leaderboards are central to the “best open source system” claim. They must be framed as **a benchmarking layer**, not as investment advice.

A defensible design:

**Trading leaderboard:** ranked by a primary risk-adjusted metric, with filters by market domain (crypto, macro, politics, etc.), and explicit separation between:

- Deterministic backtest episodes  
- Paper trading campaign results  
- Real-money campaigns (hard-gated, with additional warning text)

Because research shows prediction market prices can have structured, domain-specific calibration biases, and therefore can be misinterpreted if treated as literal probabilities without context. citeturn3academia11 This supports the need for methodology transparency and domain-by-domain reporting.

**Worker leaderboard:** ranked by objective financial output or verified value created (e.g., “pipeline generated,” “meetings booked,” “revenue closed”), but only if you can define verification and avoid incentivizing spam. This aligns with your desire for a non-trading agent economy, but requires strong guardrails.

## Contribution flywheel and documentation governance

The platform wins if contributors keep showing up. That depends on **friction**, **clarity**, and **trust**.

### The minimum viable contributor experience

If onboarding is to work for non-technical contributors, it should be structured as three modes:

- **Observer:** watch dashboards, read the diary, vote or comment on priorities  
- **Runner:** run the system locally in safe mode; contribute data and test results  
- **Builder:** allow agents (or humans) to propose code changes, run test suites, and open PRs

Open-source maintainer guidance emphasizes documenting processes and “bringing in the robots” to scale community contribution. citeturn11search2 That maps directly to your “agents guide the work” goal.

### Docs-as-code and the “numbered documents at root” concept

Your idea—“a master architecture” plus a set of numbered root documents updated with each change—is strategically correct, but it must be done in a way that doesn’t become bureaucracy.

A strong pattern is to formalize architecture decisions using ADRs (Architecture Decision Records): short documents that capture a decision, context, and consequences. citeturn11search0  

For broader project documentation, a Docs-as-Code approach is explicitly valued for integrating documentation into the same version-controlled workflow as code. citeturn11search1turn11search4  

**Proposed root document set (versioned, numbered, lightweight):**

- `00_VISION.md` — the unchanging “why,” audience, and north star  
- `01_ARCHITECTURE.md` — the canonical diagram + system boundaries  
- `02_EVALUATION.md` — how leaderboards, tests, and metrics are computed  
- `03_SAFETY.md` — defaults, kill switches, and forbidden actions  
- `04_ROADMAP.md` — current forecast + revision log  
- `05_PROMPTS.md` — the prompt system and how it is updated with rigor  
- `06_CHANGELOG.md` — human-readable release notes  
- `07_ADR/` — ADR log directory (each ADR small and atomic)

This structure keeps “rigor” and “simplicity” from becoming opposites: rigor is enforced by standardized documents, but each document stays short and modular.

### The self-improving prompt system

Your transcript states that “one key to success will be the rigor with which we update our prompts to drive research and launch new features.” This is correct, but prompts must be treated like code:

- Versioned  
- Reviewed  
- Tested (does the prompt produce the intended artifacts?)  
- Tracked (prompt changes linked to metric changes)

Elastic’s positioning around Search AI and its platform emphasis on real-time analysis creates a natural narrative: Elastifund uses Search AI not only for user-facing search, but as the memory and evidence backbone for agents. citeturn8search7turn0search5  

## Operating model and roadmap

The operating model should look like a disciplined research lab, not a chaotic “AI bot playground.”

### Release rhythm and “evidence gates”

Every update should ship with:

- Updated diary entry  
- Updated forecast  
- Updated evaluation results  
- Updated graphs  
- A clear statement of what changed and why

This can be enforced via branch protection and required status checks: GitHub branch protection rules can require passing status checks before merging, ensuring contributions don’t land without validation. citeturn10search3turn10search6  

### Integration strategy for “best open source agents”

The “we run the best open source systems alongside ours” claim will only be credible if your project has:

- A standard adapter interface (so external agents plug in cleanly)  
- A standard evaluation harness (so comparisons are apples-to-apples)  
- A standard publishing contract (so results flow to leaderboards automatically)

For prediction-market integration specifically, Polymarket provides official open-source clients (TypeScript, Python, Rust) for interacting with the CLOB API. citeturn7search24turn7search13 Polymarket also publishes an “agents” framework positioned as utilities for building AI agents for Polymarket, suggesting a natural starting point for “best open components” on the trading side. citeturn7search16  

### Non-trading agent roadmap discipline

The non-trading agent class (“worker” agents) is both a differentiator and a reputational risk. A minimal roadmap that stays aligned with credibility:

- Start with a single “worker” use case (e.g., the SDR/consulting business case described in your transcript)  
- Define explicit outcome metrics (meetings booked, revenue generated, churn reduced)  
- Require consent, identity, and compliance constraints before outbound actions  
- Publish only aggregate, anonymized performance summaries unless explicit permission exists

This keeps the worker leaderboard meaningful, not spammy.

## Risk, compliance, and trust

To attract serious contributors and any executive sponsor, you must be direct about risks and how the system limits them.

### Regulatory reality

Kalshi explicitly states it is regulated by the US Commodity Futures Trading Commission as a Designated Contract Market (DCM). citeturn9search0turn9search4 This is relevant because it means trading behaviors, market surveillance, and reporting expectations exist beyond “normal app building.”

Polymarket’s own terms distinguish between a CFTC-regulated U.S. venue and an international platform that is not regulated by the CFTC, and explicitly warns that trading involves substantial risk of loss. citeturn7search2 This makes it essential that your public messaging avoids implying guaranteed returns or encouraging prohibited participation.

### Insider trading, ethics, and incentives

Prediction markets have faced rising scrutiny for potential insider trading risks and ethically sensitive contracts, and regulators have issued public enforcement / advisory communications tied to misuse of material non-public information. citeturn9news25turn9search1  

This has two implications for Elastifund:

- The platform must include strong “no MNPI” policies and monitoring/flagging in its own contexts.  
- The project must avoid incentive designs that encourage contributors to seek inside information or trade on sensitive topics.

### Security and supply-chain risk

A platform that auto-merges changes found by distributed agents invites obvious supply-chain attacks. The only defensible posture is:

- “No direct merge” to main without tests + review gates  
- Required status checks before merge citeturn10search3turn10search6  
- Strict secrets handling (keys never in repos; least privilege; rotate credentials) citeturn13search3turn13search11  

### Trust-building through transparency

Your differentiator is that results are “real time data updating the site and the README.” That can become trust-building rather than hype if you commit to:

- Publishing methodology  
- Publishing risk metrics (drawdown, volatility) alongside return charts citeturn12search2turn12search1  
- Publishing forecast revision logs (admitting misses, explaining why)  
- Maintaining a strong separation between paper results and live money results

Done correctly, Elastifund becomes a public demonstration of how **Search AI + observability + disciplined governance** can make agentic systems less mysterious and more auditable—precisely the kind of story the Elastic ecosystem is built to tell. citeturn8search7turn8search1