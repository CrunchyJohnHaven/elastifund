# Deep Research Execution Memo: Primary Edge And Simulation Architecture

**As of:** 2026-03-23  
**Built from:** [07_DEEP_RESEARCH_SIMULATION_FLYWHEEL_OVERDRIVE.md](./07_DEEP_RESEARCH_SIMULATION_FLYWHEEL_OVERDRIVE.md)  
**Purpose:** Execution-ready synthesis of the external research and the repo's current architecture.

This is the result of executing the deep-research brief against:

- current repo docs and machine-truth artifacts,
- official Polymarket documentation,
- official Kalshi documentation,
- and recent primary/academic sources on prediction-market calibration, market microstructure, arbitrage, and semantic relationship trading.

The conclusion is blunt:

- The best near-term edge is **not** "forecast better in general."
- The best near-term edge is **selective maker execution in fast markets**, conditioned on exogenous anchor divergence, queue/fill reality, and toxicity control.
- The repo's biggest blocker is **not idea scarcity**. It is the combination of **truth fragmentation, weak fill modeling, duplicated simulation surfaces, and unstable objective metrics**.

If those are fixed, the system can become a real local replay factory.

If those are not fixed, "big money fast" remains fantasy theater.

---

## Section A: Executive Verdict

### Primary Edge Thesis

The highest-conviction near-term edge for this repo is:

**Queue-aware selective maker provision on short-horizon markets, especially crypto-fast markets, using exogenous anchor divergence plus microstructure filters.**

In plain English:

- Use official real-time external anchors such as crypto price feeds and venue-native real-time sockets.
- Quote only when the external anchor, book state, and flow state agree.
- Model fill probability and adverse selection explicitly.
- Optimize for **net filled expectancy**, not raw signal accuracy and not annualized fantasy ARR.

### Can The Current Architecture Exploit It Today?

Only partially.

The repo already has many of the pieces:

- BTC5 execution lane,
- event tape writer,
- local twin,
- parameter evolution,
- wallet reconciliation,
- promotion docs,
- research stack,
- and explicit interest in VPIN, OFI, wallet flow, and RTDS-style signals.

But the system does **not** yet have:

- one canonical truth loop,
- one canonical replay/simulation engine,
- one canonical fill-hazard model,
- or one robust objective function that survives small-sample noise.

### Highest-Probability Blocker

The biggest blocker is not prediction quality.

It is this:

**The system does not yet know, with enough rigor, when a maker order is likely to fill profitably versus get adversely selected or never fill.**

### Realistic 30-Day Ceiling

With the current bankroll and current architecture, the realistic 30-day target is:

- not "make big money,"
- but to prove a positive filled-trade edge with trustworthy attribution and enough fill-quality evidence to scale.

A realistic good outcome in the next 30 days is:

- positive net expectancy on filled trades,
- fill-rate and queue metrics that justify scaling,
- and maybe low hundreds of dollars of realized PnL while still in a constrained research posture.

Without that proof, large-money scaling would be reckless.

---

## Section B: Brutal Architecture Review

### 1. There Is No Single Authoritative Truth Loop Yet

The repo still has too many partially authoritative surfaces:

- wallet truth,
- local SQLite truth,
- runtime artifact truth,
- research markdown truth,
- and future-architecture truth.

This suppresses money-making velocity because:

- capital allocation decisions can be based on stale or contradictory numbers,
- research can optimize the wrong state,
- and post-trade learning can be attached to the wrong ledger.

### 2. Simulation Is Spread Across Multiple Incomplete Centers Of Gravity

Right now the repo has:

- `simulator/engine.py` for paper-trade replay,
- `src/models/mc_engine.py` for path generation,
- `backtest/monte_carlo_advanced.py` for richer but separate Monte Carlo,
- and architectural docs describing an even broader future replay kernel.

This creates:

- duplicated assumptions,
- inconsistent cost/fill logic,
- unclear ownership of canonical outputs,
- and too many ways to get a flattering answer.

### 3. Fill Modeling Is Still Too Weak For A Maker-First Strategy

The entire economics of the current likely edge depend on:

- queue position,
- fill probability,
- adverse selection,
- and liquidity/taker behavior.

Yet the current stack still looks stronger on signal generation than on fill realism.

That is backwards for a maker-first system.

### 4. Current Objective Metrics Are Too Easy To Corrupt

The repo currently produces million-percent forecast ARR numbers from tiny and unstable windows.

That is a red flag that the optimization target is too brittle.

A system optimizing unstable annualizations can:

- overfit tiny sample windows,
- rank the wrong strategies,
- and promote bad behavior while looking mathematically sophisticated.

### 5. Research And Execution Still Behave Like Cousins, Not One Organism

`FAST_TRADE_EDGE_ANALYSIS.md` can be stale or decoupled while BTC5 behavior continues elsewhere.

That means the research flywheel is still not the direct control plane for live capital.

Until every filled trade can be traced back to:

- evidence,
- thesis,
- promotion logic,
- execution event,
- and realized outcome,

the repo will keep confusing activity with learning.

---

## Section C: Primary Edge Thesis

### Name

**Selective Exogenous-Anchor Maker**

### Mechanism

This is not raw directional forecasting.

This is a **market making / limit-order selection** problem:

1. Use an exogenous anchor to estimate which side is actually favorable right now.
2. Observe the live book and flow to decide whether resting liquidity is likely to be filled by uninformed or slower flow.
3. Quote only when expected filled-trade value remains positive after:
   - taker fee environment,
   - queue position,
   - fill delay,
   - adverse selection,
   - and order-cancel latency.

For Polymarket specifically, the official docs matter here:

- RTDS officially streams comments and crypto prices via `wss://ws-live-data.polymarket.com`.  
  Source: [RTDS docs](https://docs.polymarket.com/market-data/websocket/rtds)
- The market channel officially streams order book, price, and trade events via `wss://ws-subscriptions-clob.polymarket.com/ws/market`.  
  Source: [Market channel docs](https://docs.polymarket.com/market-data/websocket/market-channel)
- Market/user channels require heartbeats every 10 seconds.  
  Source: [WebSocket overview](https://docs.polymarket.com/market-data/websocket/overview)
- On 2026-03-23, Polymarket's current fee structure says only Crypto and Sports markets have taker fees enabled, with peak effective rates of 1.56% and 0.44% respectively, and crypto maker rebates at 20%.  
  Source: [Fees](https://docs.polymarket.com/trading/fees)

That means the current edge should be framed as:

- **maker-only or maker-dominant on short-horizon crypto and possibly sports**,
- not fee-blind taking,
- and not broad-market prediction as the first engine.

### Why Competitors Still Underexploit It

Many builders stop at one of these:

- latency,
- directional signal,
- wallet copying,
- or spread capture.

Fewer systems do all of these together:

- event-sourced fill measurement,
- queue-aware quoting,
- toxicity filters,
- exogenous anchor divergence,
- and local counterfactual replay.

The edge is therefore not "having RTDS" or "having a wallet-flow signal."

The edge is:

**turning live fills into a continuously improving limit-order policy.**

### External Evidence Supporting The Thesis

Recent and official sources point in the same direction:

- Polymarket's docs show official low-latency websocket surfaces for both RTDS and market-channel order book/trade data.  
  Sources: [RTDS docs](https://docs.polymarket.com/market-data/websocket/rtds), [market channel docs](https://docs.polymarket.com/market-data/websocket/market-channel), [WebSocket overview](https://docs.polymarket.com/market-data/websocket/overview)
- Polymarket's fee docs show that the cost wedge is highly state-dependent and peaks near 50c, which means fee-aware price-bucket selection matters.  
  Source: [Fees](https://docs.polymarket.com/trading/fees)
- The arXiv paper *Optimal Market Making in the Presence of Latency* shows positive maker profit requires enough uninformed flow relative to price jumps, and latency hurts performance.  
  Source: [arXiv:1806.05849](https://arxiv.org/abs/1806.05849)
- The arXiv paper *Limit Order Strategic Placement with Adverse Selection Risk and the Role of Latency* shows liquidity imbalance can be used to control limit orders, with adverse selection central to the problem.  
  Source: [arXiv:1610.00261](https://arxiv.org/abs/1610.00261)
- Kalshi's official docs now expose queue positions for resting orders, which is strong evidence that queue-aware fill modeling is operationally important enough to be first-class exchange data.  
  Source: [Kalshi queue positions API](https://docs.kalshi.com/api-reference/orders/get-queue-positions-for-orders)

### Exact Data Needed

- Polymarket RTDS feed
- Polymarket market-channel book/trade feed
- Polymarket user-channel fill lifecycle
- wallet reconciliation outputs
- local event tape with per-window correlation IDs
- BTC reference prices and candle opens
- queue/fill outcomes by side, hour, price bucket, and regime

### Expected Frequency

High enough to learn quickly in crypto-fast lanes.

The point of this thesis is not just eventual edge magnitude. It is also:

- high feedback density,
- frequent fill/no-fill observations,
- and repeated opportunities to retrain the fill policy.

### Expected Post-Cost Edge

I do **not** think the clean edge should be modeled as a huge per-trade directional edge.

A more realistic target is:

- small but repeatable net expectancy per filled trade,
- enhanced by maker rebate economics,
- and improved further by avoiding bad fills rather than chasing more fills.

### Capacity Estimate

Near-term capacity is modest because:

- bankroll is still small,
- fill quality is still uncertain,
- and the promotion gates are not yet trustworthy enough to justify aggressive scale.

Capacity can expand only after the system proves:

- consistent positive filled expectancy,
- stable fill rate,
- and robust queue-aware behavior across regimes.

### Likely Failure Mode

The likely failure mode is not "signal wrong."

It is:

- quotes fill mostly when toxic,
- good quotes rarely fill,
- and the apparent edge vanishes once fill selection is measured correctly.

### Kill Criteria

Kill or demote the thesis if, after a meaningful live/shadow evidence window:

- filled-trade expectancy is non-positive after fees and rebates,
- fill-rate collapses below a practical threshold,
- queue-aware features add no predictive lift over simple quoting,
- or adverse selection dominates the gross signal.

---

## Section D: Runner-Up Theses

### Runner-Up 1: Favorite-Longshot And Calibration Compression Exploitation

This is the best medium-horizon thesis.

Why:

- The George Washington University working paper *Makers or Takers: The Economics of the Kalshi Prediction Market* finds low-price contracts lose badly, high-price contracts have small positive returns, and makers outperform takers.  
  Source: [GWU working paper PDF](https://www2.gwu.edu/~forcpgm/2026-001.pdf)
- The paper reports that contracts below 10c lose over 60% of money, while contracts above 50c show small positive returns, with the favorite-longshot pattern more pronounced for takers.
- The recent calibration paper on 292 million trades across Kalshi and Polymarket finds persistent underconfidence in political markets, with prices chronically compressed toward 50%, and says this generalizes across both exchanges.  
  Source: [arXiv:2602.19520](https://arxiv.org/abs/2602.19520)

Thesis:

- Focus event markets where domain-specific calibration is misread,
- enter via maker or fee-light resting orders,
- and specialize by category, horizon, and price bucket instead of trying to predict everything.

Why it is not primary:

- feedback is slower than crypto-fast lanes,
- and the repo is currently better positioned to learn quickly in fast markets.

### Runner-Up 2: Semantic Relationship Trading Across Overlapping Markets

This is the best "next frontier" thesis once the canonical replay substrate exists.

Why:

- The 2025 paper *Semantic Trading* reports roughly 60-70% accuracy and about 20% average returns over week-long horizons from AI-discovered dependent market relationships on Polymarket.  
  Source: [arXiv:2512.02436](https://arxiv.org/abs/2512.02436)

This is attractive because the repo already has adjacent surfaces:

- semantic alignment,
- leader-follower ideas,
- dependency graphs,
- and event-tape ambitions.

Why it is not primary:

- it is less direct than the maker microstructure thesis,
- requires stronger data hygiene and tape replay to trust,
- and probably belongs after the canonical simulation lab exists.

### Why Hard Structural Arbitrage Is Still Tertiary

The 2025 paper *Unravelling the Probabilistic Forest* shows Polymarket does contain real arbitrage and reports large total extracted profit across its measurement window, with crypto showing some of the biggest outliers. But it also notes that many inter-market opportunities appear in lower-liquidity moments and often at limited absolute size.  
Source: [arXiv:2508.03474](https://arxiv.org/abs/2508.03474)

That lines up with the repo's own kill history:

- structural arbitrage exists,
- but executable density and operational simplicity still favor selective maker microstructure first.

---

## Section E: Simulation Flywheel Overdrive Design

### Verdict

Use a **local-first, event-sourced, multiprocessing-friendly stack**.

Do **not** jump to distributed complexity first.

### Recommended Stack

- **Event tape storage:** JSONL + SQLite immediately, Parquet partitions for replay
- **Analytical substrate:** DuckDB + Polars
- **Numerical layer:** NumPy
- **Parallelism:** Python multiprocessing / process pools
- **GPU usage:** optional and narrow, mainly for embedding or batch model tasks, not for core replay
- **Scheduling:** extend `scripts/run_local_twin.py` and reuse its `heavy_local` profile

### Why Not Ray Or Dask First

Current repo evidence suggests the bigger problem is architecture coherence, not cluster management.

A MacBook can handle a lot if the data layout is right:

- Parquet partitions by date/lane/window,
- vectorized feature extraction,
- multiprocessing over windows or parameter bundles,
- and incremental replay instead of full cold starts.

Ray/Dask add coordination cost before the repo has a canonical simulation substrate.

### Canonical Four-Layer Simulation Design

#### Layer 1: Event Capture

Promote `bot/event_tape.py` into the real append-only capture surface.

Every important unit should emit:

- market observation,
- external anchor value,
- proposed trade,
- rejected trade with reason,
- order placement,
- fill lifecycle event,
- cancel event,
- wallet reconciliation event,
- and realized outcome.

#### Layer 2: Replay Store

Add a local derived-store step:

- read tape SQLite or JSONL,
- normalize into partitioned Parquet,
- register with DuckDB,
- expose replay-friendly tables keyed by:
  - date,
  - lane,
  - market,
  - correlation_id,
  - regime bucket,
  - side,
  - price bucket.

#### Layer 3: Policy Lab

Build one canonical policy-evaluation interface:

- input: event windows + fill model + policy parameters
- output: replay metrics + attribution + promotion frontier row

This policy lab should evaluate:

- deterministic replay,
- fill-hazard adjusted replay,
- regime-sliced replay,
- queue-aware cancel/replace strategies,
- and block-bootstrap stress tests.

#### Layer 4: Frontier Writer

Each batch writes a frontier artifact with:

- expected net PnL,
- realized filled expectancy,
- fill rate,
- adverse selection score,
- drawdown,
- calibration error,
- information gain,
- and promotion recommendation.

This frontier should replace ARR-heavy hype metrics as the main internal ranking surface.

### Apple Silicon Guidance

Use Apple Silicon acceleration only where it matters:

- semantic embeddings,
- optional Bayesian model fitting,
- optional relation clustering.

Do **not** make GPU usage a prerequisite for the replay engine.

The replay engine should be:

- CPU-saturating,
- cache-friendly,
- deterministic,
- and easy to diff against live outcomes.

---

## Section F: Quant Model Stack

### Build Now

- Queue/fill hazard model
- Price-bucket and side-bucket expectancy model
- Regime slicing by hour, volatility, and microstructure state
- Block-bootstrap replay for short-horizon windows
- Utility-based objective replacing ARR headline optimization

### Build Next

- Hierarchical Bayesian model for filled expectancy by lane, hour, side, price bucket, and regime
- Conformal uncertainty intervals for decision confidence
- Selective wallet-flow augmentation once it improves filled expectancy rather than raw signal accuracy
- Semantic relationship mining for week-horizon secondary lanes

### Build Later

- More advanced Hawkes or queue-reactive models
- Market-graph relationship models that feed live routing
- Apple Silicon accelerated embedding and semantic clustering batch jobs

### Not Yet

- full RL-first market-making stack
- distributed compute frameworks
- giant foundation-model loops in the hot path
- complex agent-based simulation before event tape and fill models are trustworthy

---

## Section G: Repo Mapping

### `bot/event_tape.py`

**Decision:** Promote to canonical capture surface.

Needed changes:

- emit from `bot/jj_live.py`
- emit from `bot/btc_5min_maker.py`
- emit from `bot/fill_tracker.py`
- emit from wallet reconciliation paths
- add correlation-friendly helpers for one window / one trade decision

### `simulator/engine.py`

**Decision:** Keep, but narrow its role.

It should become the deterministic event-policy replay engine, not the entire research universe.

### `src/models/mc_engine.py`

**Decision:** Keep as a library, not a top-level truth surface.

Use it for probabilistic overlays and scenario generation, not as the canonical simulation entrypoint.

### `backtest/monte_carlo_advanced.py`

**Decision:** Mine and refactor, not promote as-is.

Useful components:

- regime switching,
- drawdown-aware sizing ideas,
- edge decay,
- liquidity and impact stress concepts.

Bad outcome to avoid:

- leaving it as a separate universe with different assumptions from live replay.

### `bot/parameter_evolution.py`

**Decision:** Change objective function.

Current objective is too narrow:

- `fill_rate × edge_per_fill`

Replace with a score that includes:

- realized filled expectancy,
- calibration penalty,
- drawdown penalty,
- adverse-selection penalty,
- and information-gain bonus.

### `scripts/run_local_twin.py`

**Decision:** Turn it into the local research scheduler.

It already has a `heavy_local` profile and a good lane registry.

Extend it with:

- replay batch lane,
- frontier write lane,
- tape-to-parquet compaction lane,
- and semantic batch lane later.

### `scripts/run_intelligence_harness.py`

**Decision:** Keep as acceptance gate, but feed it better artifacts.

It should consume:

- frontier outputs,
- filled-trade edge metrics,
- and explicit queue/fill regressions.

### `improvement_velocity.json` And Public Metric Writers

**Decision:** Stop using unstable ARR-like annualizations as the main internal objective.

Keep them only as derived reporting fields if absolutely needed.

Do not optimize them directly.

---

## Section H: 72-Hour Plan, 7-Day Plan, 30-Day Plan, 90-Day Plan

### First 72 Hours

Objective:

- make truth and fill measurement less fake.

Tasks:

- wire `bot/event_tape.py` into BTC5 and main execution paths,
- emit fill lifecycle and rejected-trade events,
- build one Parquet compaction script for tape partitions,
- create one replay runner that replays a single day across a parameter grid,
- replace ARR-first ranking with a filled-edge frontier artifact.

Evidence produced:

- tape events for live/shadow windows,
- first replay frontier table,
- first queue/fill bucket report.

Unlocks:

- ability to compare candidate policies on the same windows.

### First 7 Days

Objective:

- prove or kill the primary edge on measured fills.

Tasks:

- add simple fill-hazard model,
- add regime slicing by hour and volatility,
- run local counterfactual sweeps every day,
- refactor parameter evolution objective,
- start writing top-5 daily policy frontier candidates.

Evidence produced:

- filled expectancy by side/hour/price bucket,
- fill-rate by quote style,
- adverse-selection cost estimates,
- first stable frontier history.

Unlocks:

- real promotion logic based on fill-adjusted edge.

### First 30 Days

Objective:

- promote one queue-aware maker policy or kill it decisively.

Tasks:

- accumulate enough filled-trade evidence,
- compare simple quoting policy against queue-aware policy,
- add conformal confidence or Bayesian shrinkage on filled expectancy,
- test one medium-horizon secondary thesis in shadow.

Evidence produced:

- promotion or kill memo for primary edge,
- stable fill-hazard model,
- measured 30-day ceiling estimate,
- trustworthy attribution.

Unlocks:

- disciplined size-up or disciplined pivot.

### First 90 Days

Objective:

- become a real simulation-driven trading system.

Tasks:

- fully normalize tape-to-replay flow,
- integrate semantic relationship trading as secondary lane,
- launch category-specific calibration lane for event markets,
- and turn the local twin into a daily counterfactual research factory.

Success looks like:

- every live fill explainable,
- every promotion explainable,
- one primary edge proved or killed on hard evidence,
- and a much tighter loop from live event to local batch learning.

---

## Section I: Metric Contract

Replace unstable ARR obsession with this metric stack.

### Research Ranking

- `filled_edge_usd_per_order = expected_filled_pnl_usd / submitted_orders`
- `filled_edge_usd_per_fill = realized_pnl_usd / filled_orders`
- `info_gain_per_window = change_in_posterior_uncertainty / compute_cost`
- `fill_adjusted_score = expected_filled_pnl - adverse_selection_penalty - drawdown_penalty`

### Shadow Promotion

- `shadow_fill_rate`
- `shadow_net_expectancy`
- `queue_position_advantage`
- `time_to_fill_distribution`
- `regime_stability_score`

### Live Scaling

- `realized_filled_expectancy`
- `rolling_drawdown_pct`
- `rolling_fill_rate`
- `cancel_to_fill_ratio`
- `adverse_selection_bps`
- `pnl_attribution_coverage`

### System Health

- `truth_consistency_rate`
- `event_tape_coverage`
- `stale_artifact_incidents`
- `replay_lag_minutes`
- `policy_frontier_freshness`

### What To Stop Optimizing Directly

- unstable annualized ARR from tiny windows
- gross signal count without fill context
- paper-mode hit rate without fill reality

---

## Section J: What To Stop Doing

- Stop treating ARR annualizations from tiny windows as a primary optimization target.
- Stop maintaining multiple semi-authoritative truth surfaces.
- Stop evaluating maker strategies without queue, fill, and adverse-selection metrics.
- Stop broad strategy sprawl until the primary edge is either promoted or killed.
- Stop letting live behavior drift away from research artifacts.
- Stop evolving parameters on narrow objectives that ignore drawdown and selection bias.

---

## Section K: Confidence And Unknowns

### High Confidence

- The repo's best near-term edge is maker-first and microstructure-heavy, not generic LLM forecasting.
- Fill and queue measurement are the most underbuilt parts of the system relative to their importance.
- The local MacBook should become the replay and counterfactual engine, not the live execution box.
- Polars + DuckDB + multiprocessing is the right first local simulation stack.

### Medium Confidence

- Semantic relationship trading is the best secondary thesis after the primary maker loop is stabilized.
- Calibration compression / favorite-longshot exploitation is a real medium-horizon opportunity, especially in selected categories and price buckets.

### Main Unknowns

- true fill hazard by price bucket and regime,
- adverse-selection cost of resting quotes in BTC-fast lanes,
- whether current live signal quality survives once fill selection is modeled correctly,
- and whether the primary edge has enough capacity to matter before bankroll scale increases.

---

## Sources

- [Polymarket fees](https://docs.polymarket.com/trading/fees)
- [Polymarket maker rebates](https://docs.polymarket.com/market-makers/maker-rebates)
- [Polymarket RTDS docs](https://docs.polymarket.com/market-data/websocket/rtds)
- [Polymarket market channel docs](https://docs.polymarket.com/market-data/websocket/market-channel)
- [Polymarket WebSocket overview](https://docs.polymarket.com/market-data/websocket/overview)
- [Polymarket API rate limits](https://docs.polymarket.com/api-reference/rate-limits)
- [Kalshi API docs](https://docs.kalshi.com/)
- [Kalshi rate limits](https://docs.kalshi.com/getting_started/rate_limits)
- [Kalshi queue positions API](https://docs.kalshi.com/api-reference/orders/get-queue-positions-for-orders)
- [Kalshi fees help article](https://help.kalshi.com/en/articles/13823805-fees)
- [Kalshi limit orders help article](https://help.kalshi.com/en/articles/13823811-limit-orders)
- [Kalshi liquidity incentive program](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program)
- [Kalshi market maker program](https://help.kalshi.com/en/articles/13823819-how-to-become-a-market-maker-on-kalshi)
- [Optimal Market Making in the Presence of Latency](https://arxiv.org/abs/1806.05849)
- [Limit Order Strategic Placement with Adverse Selection Risk and the Role of Latency](https://arxiv.org/abs/1610.00261)
- [Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics in Prediction Markets](https://arxiv.org/abs/2602.19520)
- [Semantic Trading: Agentic AI for Clustering and Relationship Discovery in Prediction Markets](https://arxiv.org/abs/2512.02436)
- [Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets](https://arxiv.org/abs/2508.03474)
- [Makers or Takers: The Economics of the Kalshi Prediction Market](https://www2.gwu.edu/~forcpgm/2026-001.pdf)
