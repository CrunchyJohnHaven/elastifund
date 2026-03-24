# Deep Research Packet 07: Simulation Flywheel Overdrive

**As of:** 2026-03-23  
**Prepared for:** ChatGPT Deep Research  
**Goal:** Find the most credible hidden money edge in this repo's reachable design space, then design the math, architecture, simulation lab, and rollout plan to turn Elastifund into a much faster edge-discovery and money-making machine.  
**Instruction priority:** Current machine artifacts beat stale prose. Be critical. Do not protect the current architecture from attack.

**Executed result:** [08_DEEP_RESEARCH_EXECUTION_MEMO_PRIMARY_EDGE_AND_SIMULATION_ARCHITECTURE.md](./08_DEEP_RESEARCH_EXECUTION_MEMO_PRIMARY_EDGE_AND_SIMULATION_ARCHITECTURE.md)

---

## 1. Use This Packet As The Prompt

You are acting as a hybrid of:

- principal quant researcher
- market microstructure engineer
- simulation architect
- event-sourced systems designer
- skeptical technical auditor

Your job is not to admire the existing system. Your job is to figure out:

1. what the highest-upside real edge is that this stack can plausibly exploit,
2. what architecture changes are required to validate and compound that edge,
3. how to turn the local MacBook into a heavy simulation/research engine while the VPS remains the execution surface,
4. and which parts of the current architecture are wasting time, creating false confidence, or suppressing real edge discovery.

I do **not** want a generic "improve data quality and backtesting" answer.

I want a concrete research document that is:

- blunt about what is broken,
- quantitative about what might work,
- opinionated about what to stop doing,
- and explicit about the fastest path to bigger money-making velocity.

If the answer is that the current stack cannot realistically "make big money fast" without first fixing truth, fill modeling, and experiment architecture, say that directly and quantify the ceiling under the current design.

Do not give me 100 fluffy ideas. I want:

- one primary edge thesis,
- two secondary edge theses,
- one simulation-flywheel redesign,
- one architecture plan,
- and one rollout plan that maps to this repo.

---

## 2. System Mission In Plain English

Elastifund is an agent-run prediction market trading lab with a public research flywheel. The repo contains:

- live-trading code,
- backtesting and simulation code,
- research and dispatches,
- promotion and gating logic,
- wallet reconciliation,
- and architecture docs that try to define a proof-carrying runtime.

The trading thesis is not "let a chatbot guess markets."

The deeper thesis is:

- find edge,
- test edge under real costs,
- deploy at tiny size,
- learn from outcomes,
- compound what survives,
- kill what does not.

The current priority is fast-feedback trading, especially short-resolution lanes where evidence arrives quickly enough to improve the system.

The primary live-ish surface is the BTC 5-minute maker sleeve and adjacent fast-flow/microstructure lanes. There are also slower and broader lanes:

- LLM-calibrated event trading,
- wallet flow,
- LMSR/Bayesian pricing,
- cross-platform arb,
- Kalshi expansion,
- resolution/rule-driven edges,
- and a large research backlog.

There is also a non-trading revenue lane in the repo, but this packet is mainly about trading edge and the simulation flywheel unless you believe non-trading changes are necessary to fund the research/data stack.

---

## 3. Current Machine Truth And Important Contradictions

Treat the newest machine-readable artifacts as more authoritative than older narrative docs.

### 3.1 Authoritative Files To Prefer

- `config/remote_cycle_status.json`
- `improvement_velocity.json`
- `reports/runtime_truth_latest.json` if present
- `reports/public_runtime_snapshot.json` if present
- `reports/remote_cycle_status.json` if present
- `FAST_TRADE_EDGE_ANALYSIS.md` only with its staleness caveat
- `research/edge_backlog_ranked.md`
- `docs/architecture/*.md`

### 3.2 Snapshot Highlights From The Repo As Of 2026-03-23

Current artifact signals include:

- `config/remote_cycle_status.json` still reflects a March 14 posture centered on capital preservation, BTC5 hold-at-$5, and unresolved promotion.
- `improvement_velocity.json` is fresher and says the system is still in a low-confidence, hold posture.
- `improvement_velocity.json` reports:
  - `launch_posture = blocked`
  - `service_status = running`
  - `btc5_live_filled_rows_total = 25`
  - `btc5_live_filled_pnl_usd_total = -54.1415`
  - `deploy_recommendation = hold`
  - `forecast_confidence_label = low`
  - `closed_trades = 50`
  - `total_trades = 55`
  - `open_positions = 5`
- The same file also contains obviously unstable headline metrics:
  - `active_forecast_arr_pct = -6103322.7089`
  - `best_package_forecast_arr_pct = -957443.8801`
  - `realized_btc5_sleeve_run_rate_pct = 1278.8043`
- `polymarket_tie_out` in `improvement_velocity.json` reports a fresh wallet export and a much larger wallet than the older March 14 packet:
  - `portfolio_total_usd = 1139.8091`
  - `free_collateral_usd = 1067.703032`
  - `closed_positions = 50`
  - `open_positions = 5`

### 3.3 Why This Matters

There are at least two competing "truth eras" in the repo:

- a March 14 truth surface centered on wallet reconciliation and +$207.31 realized net,
- and a March 23 truth surface centered on low-confidence BTC5 forecasts, blocked launch posture, 25 live-filled rows, and negative BTC5 live-filled PnL.

That contradiction is not a side issue. It is the core architecture problem.

Deep Research should assume:

- truth fragmentation is real,
- some docs are stale,
- live state and research state can diverge,
- and any serious edge-discovery redesign must start by fixing truth and attribution, not by inventing prettier dashboards.

---

## 4. Repo Surfaces That Matter Most

These are the major code and doc surfaces relevant to the edge hunt and simulation redesign.

### 4.1 Live Trading And Execution Surfaces

- `bot/jj_live.py`
- `bot/btc_5min_maker.py`
- `bot/polymarket_runtime.py`
- `bot/polymarket_clob.py`
- `bot/fill_tracker.py`
- `bot/wallet_reconciliation.py`
- `bot/wallet_poller.py`
- `bot/promotion_manager.py`
- `bot/auto_promote.py`
- `bot/parameter_evolution.py`
- `bot/event_tape.py`

### 4.2 Research, Backtest, And Simulation Surfaces

- `src/main.py`
- `src/hypothesis_manager.py`
- `src/backtest.py`
- `src/models/mc_engine.py`
- `backtest/monte_carlo_advanced.py`
- `backtest/run_expanded_pipeline.py`
- `simulator/engine.py`
- `simulator/run_sim.py`
- `simulator/sizing.py`

### 4.3 Architecture, Kernel, And Deployment Surfaces

- `docs/architecture/proof_carrying_kernel.md`
- `docs/architecture/event_sourced_tape.md`
- `docs/architecture/intelligence_harness.md`
- `docs/architecture/promotion_ladder.md`
- `docs/architecture/deployment_blueprint.md`
- `docs/architecture/strike_desk.md`
- `docs/architecture/temporal_edge_memory.md`
- `scripts/run_local_twin.py`
- `scripts/run_kernel_cycle.py`
- `scripts/run_intelligence_harness.py`
- `scripts/write_remote_cycle_status.py`

### 4.4 Current Research And Status Surfaces

- `FAST_TRADE_EDGE_ANALYSIS.md`
- `research/edge_backlog_ranked.md`
- `research/btc5_simulation_engine_week_plan.md`
- `research/high_frequency_substrate_phase2_blueprint_2026-03-11.md`
- `research/deep_research_prompt_100_strategies_full.md`
- `docs/strategy/edge_discovery_system.md`
- `docs/strategy/flywheel_strategy.md`

---

## 5. Blunt Critique Of The Current Architecture

This section is intentionally sharp. Treat it as a starting hypothesis. Confirm or overturn it with evidence, but do not ignore it.

### 5.1 Decision Authority Is Fragmented

The proof-carrying kernel doc explicitly says the repo has overlapping decision authority. It names conflicts across:

- `jj_live.py`
- `enhanced_pipeline.py`
- `auto_promote.py`
- `parameter_evolution.py`
- `btc_5min_maker.py`
- `auto_stage_gate.py`

That means the repo itself knows it has no single clean proof-to-capital path.

Deep Research should assume the current runtime can still leak behavior changes through multiple side doors even if the docs describe a future clean kernel.

### 5.2 Truth Is Fragmented Across Too Many Surfaces

The repo has:

- wallet truth,
- local SQLite truth,
- runtime artifact truth,
- public metrics truth,
- stale markdown truth,
- and design-doc truth.

This is a major failure mode because it lets the system:

- think a lane is blocked while it is executing,
- think PnL is one number while a fresher export says another,
- and think a strategy is rejected while a different lane is live.

### 5.3 Research And Live Execution Are Not Tightly Coupled

`FAST_TRADE_EDGE_ANALYSIS.md` can say `REJECT ALL` while BTC5 operates as an effectively separate trading organism.

That means the research flywheel is not fully steering live capital.

This can create two bad outcomes:

- the research pipeline becomes a side theater that does not matter,
- or the live system trades edges that the research stack cannot explain, audit, or improve.

### 5.4 The Simulation Stack Is Duplicated And Not Canonical

There is no obvious single canonical simulation engine.

Instead there are several overlapping layers:

- `simulator/engine.py` for paper-trade replay,
- `src/models/mc_engine.py` for lightweight Monte Carlo path generation,
- `backtest/monte_carlo_advanced.py` for a richer but separate regime-switching engine,
- multiple backtest entrypoints,
- and a growing set of architecture docs describing an even broader future simulation kernel.

That suggests:

- duplicated assumptions,
- different fill/cost models in different places,
- unclear ownership of "the" truth model,
- and a higher chance of overfitting one engine while live behavior follows another.

### 5.5 Fill Modeling Is Still The Core Unknown

The repo repeatedly points at maker-first economics as the path to survive fees.

But maker alpha only matters if the system can answer:

- what gets filled,
- when,
- at what queue position,
- under which toxicity regime,
- with what adverse-selection cost,
- and how often "no fill" destroys apparent edge.

Right now, the fill problem looks under-modeled relative to how important it is.

### 5.6 Metric Design Is Creating False Precision

The presence of numbers like:

- `-6103322.7089%` forecast ARR,
- `-957443.8801%` best-package forecast ARR,
- and `1278.8043%` realized BTC5 sleeve run rate

strongly suggests the system is annualizing tiny, unstable windows into absurd headline metrics.

This is not just ugly reporting. It can distort optimization itself.

Deep Research should assume the top-line objective function is not yet robust enough for serious capital allocation.

### 5.7 The Repo Has More Design Than Enforced Runtime

The architecture docs are ambitious and often excellent.

But many major components are still explicitly labeled design or not yet implemented:

- event-sourced tape,
- local twin vs Lightsail split,
- strike desk,
- temporal edge memory graph.

That means the repo currently risks living in an in-between state:

- too complex for a simple empirical loop,
- not yet coherent enough for a true proof-carrying runtime.

### 5.8 Compute Is Not Yet Weaponized As A Research Advantage

The user's desired future state is clear:

- the MacBook should be busy,
- the system should be constantly replaying,
- counterfactuals should be cheap,
- and simulation should directly improve live trading.

The current repo has many simulation and research components, but it does not yet obviously operate like a local quant lab that aggressively uses all available CPU/GPU/memory bandwidth to compress the idea-to-evidence loop.

### 5.9 The Search Space Has Been Wide But Not Yet Ruthlessly Narrow

The repo has a huge backlog, many design directions, and many clever ideas.

That is good for discovery, but dangerous for compounding. The system now needs a sharper answer to:

- what exact edge family is most likely to make meaningful money next,
- what exact evidence would promote it,
- and what exact surfaces should stop receiving attention until that thesis is proven or killed.

---

## 6. What Already Looks Promising And What Already Looks Dead

Use these as priors, not commandments.

### 6.1 What Looks Structurally Promising

- Maker-first execution economics on Polymarket.
- Fast-feedback BTC markets where many experiments can resolve quickly.
- Public wallet-flow data if it can be modeled without naive copy-trading.
- Hybrid signals that combine market microstructure, public wallet flow, regime state, and price/oracle dynamics.
- Cross-venue or cross-resolution mismatches if execution and matching are realistic.
- Resolution/rule/tail edges where the market structurally misprices discrete boundaries or longshot buckets.

### 6.2 What Looks Fragile Or Suspicious

- Anything requiring taker economics in fee-heavy fast markets.
- Any edge whose headline performance is driven by tiny windows and ARR annualization.
- Any architecture that assumes research outputs are automatically controlling live behavior.
- Any edge that cannot survive real fill modeling and queue priority.

### 6.3 What Is Already Killed Or Effectively Deprioritized

- A-6 Guaranteed Dollar Scanner: killed for zero executable density.
- B-1 Templated Dependency Engine: killed for zero deterministic density.

Do not spend much time resurrecting dead structural-alpha lanes unless you have a specific argument that the prior scans were measuring the wrong universe or the wrong executable threshold.

---

## 7. The Research Question I Actually Need Answered

Answer this as directly as possible:

> Given the current codebase, truth fragmentation, fee structure, live evidence quality, and reachable infrastructure, what is the single most credible path to an outsized money-making edge that others are likely underestimating, and what exact simulation + system architecture will let Elastifund discover, validate, and compound that edge faster than it does now?

Break that into five sub-questions:

1. **Primary edge thesis**
   - What one edge family deserves the next serious push?
   - Why this one instead of the others?
   - What is the actual mechanism?

2. **Simulation-flywheel architecture**
   - How should local simulation, replay, and parameter search be redesigned so the system learns much faster from the same data?

3. **Truth and attribution repair**
   - What minimal architecture is required so every live fill can be traced back to a thesis, evidence set, and promotion decision?

4. **Math stack**
   - Which models are worth the complexity now?
   - Which models are seductive but should wait?

5. **Rollout**
   - What should be built in 72 hours, 7 days, 30 days, and 90 days?

---

## 8. The Kind Of Math I Want You To Consider

Do not throw math buzzwords at the wall. Choose the techniques that actually fit this system.

But I want you to think ambitiously and technically. Consider whether the right answer should include some combination of:

- hierarchical Bayesian models for edge strength by regime, hour, side, venue, price bucket, and signal family,
- hidden Markov models or BOCPD-style changepoint detection for market regimes,
- Hawkes-process or self-excitation models for wallet and order-flow clustering,
- VPIN/OFI/toxicity models for maker adverse selection,
- queue-position and fill-hazard models,
- conformal calibration or uncertainty sets for decision confidence,
- doubly robust or other off-policy evaluation methods for shadow-to-live policy estimation,
- block bootstrap or nested walk-forward replay for fragile short-horizon markets,
- transfer entropy / lead-lag graphs where they actually add predictive power,
- Kelly sizing under posterior uncertainty and drawdown constraints,
- multi-armed bandits or Thompson sampling to allocate experimentation budget,
- evolutionary search / Bayesian optimization for parameter surfaces,
- agent-based or event-driven market simulators if the simpler models are insufficient,
- and event-sourced counterfactual replay so every live window can be re-run across hundreds or thousands of alternate policies.

Also be honest about complexity:

- if a simple queue-aware fill model beats a giant RL stack, say that.
- if the current sample sizes are too small for fancy methods, say that.
- if a lightweight Polars/DuckDB + multiprocessing stack beats a distributed framework, say that.

---

## 9. The "MacBook Chugging" Target State

Design for this future state:

- The local MacBook is the research cluster and simulation factory.
- The VPS is the low-latency execution hand.
- Live and shadow events are mirrored into a local event tape quickly enough for daily or intraday replay.
- Every new live or shadow window automatically triggers many counterfactual experiments locally.
- The system constantly updates:
  - fill models,
  - regime slices,
  - parameter frontiers,
  - edge attribution,
  - and promotion candidates.

I want a design that can saturate local compute in a useful way, not performative way.

Deep Research should specify:

- which workloads should run on local CPU,
- whether local GPU or Apple Silicon acceleration is worth using,
- how data should be stored for fast replay,
- how experiment batches should be prioritized,
- and how to avoid burning compute on low-information experiments.

I especially want a plan for:

- massively parallel counterfactual replays,
- parameter sweeps over maker/fill/risk assumptions,
- regime-sliced simulations,
- queue/fill sensitivity analysis,
- and candidate ranking based on expected information gain, not just raw backtest PnL.

---

## 10. Specific Problems You Should Solve

### 10.1 Primary Edge Selection

Choose the top edge family from among options like:

- BTC fast-market maker microstructure,
- wallet-flow plus microstructure hybrid,
- cross-platform or cross-resolution structural mismatch,
- resolution/tail/longshot mispricing,
- event-market LLM plus market-structure hybrid,
- or some other edge class you believe the repo is structurally positioned to own.

I want:

- the primary thesis,
- the runner-up theses,
- and a hard explanation for why the losers should wait.

### 10.2 Canonical Simulation Architecture

Propose the minimal canonical simulation stack that should exist after cleanup.

For example, I want you to answer questions like:

- Should the repo consolidate around one event-driven simulator?
- Should `simulator/engine.py`, `src/models/mc_engine.py`, and `backtest/monte_carlo_advanced.py` be merged, wrapped, or clearly separated?
- What is the canonical input format?
- What is the canonical output artifact?
- Where should fill models live?
- Where should regime models live?
- How should shadow alternatives be stored and replayed?

### 10.3 Truth Unification

Give the minimal viable design to make these agree:

- wallet truth,
- trade ledger truth,
- research verdict truth,
- promotion-gate truth,
- and public metrics truth.

I care more about one brutally reliable truth loop than five semi-elegant ones.

### 10.4 Fill And Queue Reality

I want a real answer to the following:

- Is the best edge in this system being hidden by bad fill assumptions?
- Is the best edge actually fake once queue position and adverse selection are modeled properly?
- Which fill metrics need to be measured live before further thesis expansion?
- What is the simplest realistic fill model that would materially improve ranking quality?

### 10.5 Objective Function Repair

Current ARR-style artifacts look unstable. Design a better objective stack.

I want a ranking framework that balances:

- expected PnL,
- confidence,
- capital turnover,
- drawdown risk,
- fill probability,
- model uncertainty,
- and information gain.

If you think the system needs separate objectives for:

- research ranking,
- shadow promotion,
- and live scaling,

say so and define them.

### 10.6 What To Stop Doing

Do not just tell me what to build.

Tell me what to stop doing, such as:

- running duplicate simulation surfaces,
- optimizing nonsense annualizations,
- chasing low-density edge families,
- or keeping doc-level architecture that is not enforced anywhere real.

---

## 11. Required Output Format

Return one integrated research memo with these sections in this order:

### Section A: Executive Verdict

- State the single best edge thesis.
- State whether the current architecture can exploit it today.
- State the highest-probability blocker.
- State the realistic money-making ceiling in the next 30 days under current constraints.

### Section B: Brutal Architecture Review

- Name the top 5 architecture failures.
- Explain how each one suppresses money-making velocity or creates false confidence.
- Be explicit about which docs describe future architecture versus enforced runtime.

### Section C: Primary Edge Thesis

For the top thesis include:

- mechanism,
- why competitors may still underexploit it,
- exact data needed,
- exact fee/fill assumptions,
- expected frequency,
- expected post-cost edge,
- capacity estimate,
- likely failure mode,
- and clear kill criteria.

### Section D: Runner-Up Theses

Give two secondary theses with the same structure, but shorter.

### Section E: Simulation Flywheel Overdrive Design

Design the target architecture for:

- local event tape,
- incremental replay,
- simulation scheduling,
- parameter search,
- fill-model updates,
- regime slicing,
- promotion frontier generation.

Include a concrete recommendation on whether to use:

- plain multiprocessing,
- Polars,
- DuckDB,
- Parquet,
- Ray/Dask,
- JAX/PyTorch/NumPy,
- or some other stack.

Do not recommend complexity without explaining why simpler options lose.

### Section F: Quant Model Stack

Give a prioritized list of models or math components to build:

- now,
- next,
- later,
- never or not yet.

### Section G: Repo Mapping

Map the proposed changes onto existing repo paths.

Be file-level where possible.

Example format:

- `simulator/engine.py`: keep / refactor / replace / wrap
- `src/models/mc_engine.py`: keep / merge / retire
- `bot/event_tape.py`: promote to canonical or replace with new tape writer
- `scripts/run_local_twin.py`: extend to drive local research cluster

### Section H: 72-Hour Plan, 7-Day Plan, 30-Day Plan, 90-Day Plan

Each phase should include:

- objective,
- concrete tasks,
- evidence produced,
- promotion or kill decision unlocked,
- and what success/failure would look like.

### Section I: Metric Contract

Define the minimum set of metrics that should govern:

- research ranking,
- shadow promotion,
- live scaling,
- and system health.

Include formulas, not just names.

### Section J: What To Stop Doing

Give a short list of activities, metrics, or architectural habits to kill immediately.

### Section K: Confidence And Unknowns

- what you are confident about,
- what needs measurement,
- and what would most change your mind.

---

## 12. Constraints You Must Respect

- Do not invent a fantasy edge that requires data or infrastructure far beyond this repo's realistic reach.
- Do not assume taker fees can be ignored.
- Do not assume maker fill is free money.
- Do not assume stale markdown is current truth.
- Do not propose widening live risk just to make the numbers look exciting.
- Do not recommend duplicating control planes when the repo already suffers from too many authorities.
- Do not give "train a giant RL agent" as a lazy default answer.
- Do not hide behind "need more data" without specifying which data, how much, and why.

If you think the correct answer is to narrow the edge search drastically and spend a week on truth/fill infrastructure before any bigger edge hunt, say that.

---

## 13. Canonical Context Summary You Should Carry Into The Analysis

### 13.1 The Repo Already Knows Its Biggest Problems

The architecture docs explicitly acknowledge:

- overlapping decision authority,
- missing canonical tape,
- local vs VPS drift,
- insufficient replayability,
- and the need for proof-carrying promotion.

This means your job is not to discover that the system needs structure.

Your job is to decide what structure actually matters for making money faster.

### 13.2 The Edge Hunt Should Probably Favor Fast Feedback

The repo's fastest proving ground remains short-resolution markets, especially BTC 5-minute and other short-horizon contracts where:

- many decisions can be observed quickly,
- fill quality can be measured frequently,
- and parameter updates can be evaluated without waiting weeks.

But you should only stay in that lane if the expected learning velocity and capacity are still superior after realistic fill modeling.

### 13.3 Maker Economics Matter A Lot

The repo repeatedly treats maker-first behavior as a central economic edge because fee drag destroys many taker strategies.

That likely means the true opportunity is not "predict better" alone. It may be:

- predict enough,
- understand fill and queue better,
- and place quotes only when the microstructure odds are favorable.

### 13.4 The Research Flywheel Is Valuable Only If It Controls Capital

If the simulation and research stack cannot directly improve:

- which trades get taken,
- how they get sized,
- when they get cancelled,
- and when a lane gets promoted or killed,

then it is not a real flywheel. It is documentation theater.

### 13.5 The System Needs One Stronger Thesis Before It Needs More Breadth

The repo has plenty of idea generation already.

It now needs a narrower, higher-conviction theory of where the next real compounding comes from.

---

## 14. File Index For Optional Deeper Inspection

If you have access to the repo or attached files, prioritize these:

### 14.1 Runtime Truth And Posture

- `config/remote_cycle_status.json`
- `improvement_velocity.json`
- `FAST_TRADE_EDGE_ANALYSIS.md`
- `research/edge_backlog_ranked.md`
- `PROJECT_INSTRUCTIONS.md`
- `COMMAND_NODE.md`

### 14.2 Core Architecture

- `docs/architecture/proof_carrying_kernel.md`
- `docs/architecture/event_sourced_tape.md`
- `docs/architecture/intelligence_harness.md`
- `docs/architecture/promotion_ladder.md`
- `docs/architecture/deployment_blueprint.md`
- `docs/architecture/strike_desk.md`
- `docs/architecture/temporal_edge_memory.md`

### 14.3 Simulation And Research

- `docs/strategy/edge_discovery_system.md`
- `research/btc5_simulation_engine_week_plan.md`
- `src/main.py`
- `src/hypothesis_manager.py`
- `src/backtest.py`
- `src/models/mc_engine.py`
- `backtest/monte_carlo_advanced.py`
- `simulator/engine.py`
- `simulator/run_sim.py`

### 14.4 Live Trading And Learning

- `bot/jj_live.py`
- `bot/btc_5min_maker.py`
- `bot/wallet_reconciliation.py`
- `bot/fill_tracker.py`
- `bot/event_tape.py`
- `bot/parameter_evolution.py`
- `bot/promotion_manager.py`
- `scripts/run_local_twin.py`
- `scripts/run_intelligence_harness.py`

---

## 15. Final Instruction

Be extremely honest.

If the current architecture is still too incoherent to support "big money fast," say so.

If the right play is:

- first unify truth,
- then fix fill modeling,
- then turn the MacBook into a counterfactual replay factory,
- then narrow onto one edge family,

say that clearly and quantify the payoff.

But if you see a genuinely underexploited edge class that this repo can realistically own, make the case hard, with math, architecture, and a build path that this codebase can actually absorb.
