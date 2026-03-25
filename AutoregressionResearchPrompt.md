# Autoregression Research Prompt

Use this file as the root handoff prompt for deep research runs focused on code-level improvements to the BTC5 autoresearch system.

This is not a generic trading prompt. It is a machine-truth, code-first systems-improvement prompt for a live autoresearch stack that already exists in this repo.

Your job is to help improve the actual implementation so that:

1. the BTC5 market simulator becomes a stronger judge,
2. the command-node agent becomes a better search and dispatch engine,
3. the policy lane stages and promotes the correct runtime package under the current market-model champion,
4. local and AWS loops search continuously and efficiently,
5. the operator surfaces tell the truth about benchmark progress, expected outcomes, and live deployability,
6. the system finds more validated edge per unit of LLM and compute spend,
7. live trading resumes only when the evidence is strong enough.

Do not answer from intuition alone. Read the repo files and machine-truth artifacts named below.

## Core Objective

We are building a Karpathy-style autoresearch system for BTC5 with a real closed loop:

1. the market model mutates,
2. a frozen benchmark keeps or discards it,
3. the best market model judges runtime packages,
4. the policy lane stages or promotes the best runtime package,
5. live trading produces new evidence,
6. that evidence updates the next benchmark epoch,
7. the command-node agent mutates to search and operate the whole system better.

We want a system that can run continuously on local infrastructure and AWS, wake up with fresh benchmark charts and outcome surfaces, and only move live capital when the evidence is good enough.

## Current Architecture

We have four coupled lanes.

### 1. Market-model lane
- Mutable surface: `btc5_market_model_candidate.py`
- Judge: frozen BTC5 market benchmark
- Output: keep/discard/crash ledger and Karpathy-style benchmark chart

### 2. Agent lane
- Mutable surface: `btc5_command_node.md`
- Judge: frozen command-node benchmark
- Output: keep/discard/crash ledger and Karpathy-style benchmark chart

### 3. Policy lane
- Inputs: runtime-package candidates produced by the BTC5 cycle
- Judge: current market-model champion replay benchmark
- Output: keep/discard decisions, shadow staging, live activation, rollback, policy ledger

### 4. Ops lane
- Runs the other lanes locally and on AWS
- Produces morning packet, overnight closeout, service audit, benchmark charts, and outcome charts

We also run a local continuous improvement loop because it is cheaper and faster to discover and validate improvements locally before letting AWS run longer unattended searches.

## What Has Already Been Fixed

Do not spend most of your answer rediscovering bugs that are now repaired.

The highest-leverage selection bug has already been fixed in code.

### Fixed selection-path defects

The standard BTC5 cycle now treats the market-backed frontier as authoritative for runtime-package selection.

The relevant fixes are already implemented:

- `scripts/run_btc5_autoresearch_cycle_core.py`
  - loads `reports/btc5_market_policy_frontier/latest.json`
  - joins candidates by `package_hash`
  - uses frontier `policy_loss` as the primary selection signal
  - reduces probe feedback to a bounded penalty instead of a hard veto
  - emits `selection_source`, `selected_package_hash`, `selected_policy_loss`, `selected_market_model_version`, `frontier_gap_vs_best`, and `frontier_gap_vs_incumbent`

- `scripts/btc5_policy_benchmark.py`
  - emits `market_model_version` with policy evaluations and market handoff payloads

- `scripts/btc5_market_policy_frontier.py`
  - filters policy evaluations to the current market-model version
  - exports current and best market-model version metadata

- `scripts/run_btc5_policy_autoresearch.py`
  - adds frontier-best elitist pass-through
  - stages the frontier-best candidate when it is version-valid and materially better than the incumbent
  - records `frontier_best_package_hash`, `frontier_best_policy_id`, `frontier_improvement_vs_incumbent`, and `staged_because`

- `scripts/run_btc5_local_improvement_search.py`
  - warm-starts local search from frontier seeds instead of using only cold-start mutation

### Result of the fixed selection path

The system now correctly converges on `active_profile` as the best current runtime package under the market-backed judge.

From current machine truth:

- `reports/btc5_autoresearch/latest.json`
  - `selected_best_runtime_package.profile.name = active_profile`
  - `best_runtime_package.profile.name = active_profile`
  - `runtime_package_selection.selection_source = frontier_policy_loss`
  - `runtime_package_selection.selected_policy_loss = -55389.7504`
  - `runtime_package_selection.frontier_gap_vs_best = 0.0`
  - `runtime_package_selection.frontier_gap_vs_incumbent = 1246.7435`

- `reports/btc5_market_policy_frontier/latest.json`
  - `best_market_policy_id = active_profile`
  - `selected_policy_id = active_profile`
  - `best_market_policy_loss = -55389.7504`
  - `selected_policy_loss = -55389.7504`
  - `loss_improvement_vs_incumbent = 1246.7435`
  - `selected_loss_gap_vs_best = 0.0`

- `reports/autoresearch/btc5_policy/latest.json`
  - `champion_id = active_profile`
  - `loss = -55389.7504`
  - `latest_experiment.promotion_state = shadow_updated`
  - `latest_experiment.decision_reason = champion_policy_loss_improved_shadow_stage`
  - `latest_experiment.staged_because = frontier_best`

So the old misselection problem is no longer the main question.

## Current Machine Truth As Of March 12, 2026

This section is the current operational truth and should anchor your analysis.

### What is working

- The market benchmark lane exists and emits a Karpathy-style chart.
- The command-node benchmark lane exists and emits a Karpathy-style chart.
- The policy lane is judged by the market-model champion rather than legacy ARR-only heuristics.
- The cycle, frontier, and policy lane now agree on the same best runtime package.
- The best current market-backed candidate has already been shadow-staged.
- Baseline BTC5 stage-1 live trading is not approved until runtime truth, wallet truth, and launch posture all agree. Treat `shadow_fast_flow` / shadow execution as the default unless the latest runtime truth explicitly says otherwise.
- Local continuous search exists, but the active command-node and BTC5 market mutation budgets are exhausted, so the next queue should wait for fresh live evidence before spending again.
- ARR and USD/day outcome surfaces exist.
- The AWS services and timers exist and run the autoresearch stack.

### What has already improved

The command-node lane has already produced at least one real local improvement:

- champion `2 -> 3`
- loss `7.3532 -> 2.6667`
- improvement `4.6865`
- improvement percent `63.734157%`
- score `92.6468 -> 97.3333`

The market-model lane has also already produced a small but real benchmark improvement:

- champion `83 -> 84`
- loss `5.16662 -> 5.166391`
- improvement `0.000229`
- improvement percent `0.004432%`

The BTC5 impossible-band defect is also repaired:

- `BTC5_MIN_DELTA=0.00005` is now loaded on the live path
- the residual live blocker is no longer contradictory gating
- the singular active blocker is now `BTC5_MAX_ABS_DELTA_TOO_TIGHT_FOR_CURRENT_VOLATILITY`

### What is still blocked

The system is now live-capable at the baseline, but it is not stage-upgrade-ready.

From `reports/runtime_truth_latest.json`, `reports/parallel/instance03_live_order_path_diagnosis.json`, `reports/autoresearch/command_node/latest.json`, and `reports/autoresearch/btc5_market/latest.json`:

- `launch_posture = clear`
- `allow_order_submission = true`
- `finance_gate_pass = true`
- `btc5_stage_readiness.allowed_stage = stage_0`
- `btc5_stage_readiness.can_trade_now = false`
- `executed_notional_usd = 0.0`
- `candidate_to_trade_conversion = 0.0`
- residual live blocker: `BTC5_MAX_ABS_DELTA_TOO_TIGHT_FOR_CURRENT_VOLATILITY`
- `BTC5_UP_LIVE_MODE = shadow_only` should remain secondary until the DOWN-side path proves itself
- command-node and BTC5 market mutation lanes are both at `daily_budget_exhausted`

So the system now has baseline live permission, but stage progression, capital expansion, and new search spend should remain blocked until repaired windows produce fresh conversion evidence.

### Outcome surfaces are still unfavorable for the current live package

From `reports/autoresearch/outcomes/latest.json`:

- current live expected ARR: `-312655.6717%`
- current live expected USD/day: `-208.1321`
- current live expected fills/day: `92.0297`
- best validated expected USD/day: `38.185`

Important: these are outcome estimates, not realized P&L, and not benchmark loss metrics.

### Current frontier winner

The current frontier winner is:

- package: `active_profile`
- policy loss: `-67316.4395`
- incumbent package: `current_live_profile`
- quantified improvement vs incumbent: `709.9664`

This means the selection layer is now aligned with the current judge. The remaining questions are about judge quality, search efficiency, statistical validity, and the path from shadow edge to safe live deployment.

### March 12 Queue Reset

The fast-market search thesis is now explicitly maker-first.

- `dual_sided_btc5_maker_spread_capture` is the new primary fast-market hypothesis
- directional wallet copying moves to a confirmation overlay, not the primary fast lane
- do not let budget-fallback local search churn drive the next cycle while live evidence is still zero-fill
- the next queue should prioritize maker shadow validation, fill/toxicity/queue modeling, and the first repaired live submit/rest/cancel/executed windows

### March 12 Live Runtime And Maker Shadow Read

Two new machine-truth facts now matter:

- the repaired directional BTC5 lane is truly runtime-live on AWS
- the first executable maker-shadow read says current BTC 5-minute books are still too tight for the strict spread-capture threshold

From `reports/runtime_truth_latest.json`, `reports/remote_cycle_status.json`, `reports/autoresearch/btc5_policy/latest.json`, `reports/autoresearch/maker_shadow/latest.json`, and the latest VPS `window_trades` rows:

- runtime package loaded:
  - `active_profile_probe_d0_00075`
- top-level launch truth:
  - `launch_posture = clear`
  - `execution_mode = live`
  - `allow_order_submission = true`
  - `btc5_baseline_live_allowed = true`
- current live directional reality:
  - still `0` fresh executed BTC5 notional on this rollout
  - recent windows are now failing on real market conditions, not config contradictions
  - recent observed statuses include:
    - `skip_delta_too_large`
    - `skip_delta_too_small`
    - `skip_bad_book`
- recent 60-window summary on the live VPS:
  - `29/60` windows were within `abs(delta) <= 0.00075`
  - `44/60` windows were within `abs(delta) <= 0.00150`
  - current validated live package remains the `0.00075` probe variant

The first corrected maker-shadow read now exists in:

- `scripts/run_btc5_dual_sided_maker_shadow.py`
- `reports/autoresearch/maker_shadow/latest.json`
- `reports/autoresearch/maker_shadow/latest.md`

Current maker-shadow machine truth:

- eligible BTC 5-minute markets observed: `6`
- strict maker shadow cap:
  - `YES + NO <= 0.97`
- result under the strict cap:
  - `ranked_candidate_count = 0`
  - `block_reasons = ["no_shadow_candidates_with_combined_cost_edge", "combined_bid_cost_above_cap"]`
- actual current books:
  - all sampled BTC 5-minute markets had `combined_bid_cost = 0.99`
  - that is above the current strict shadow cap, so there is no validated spread-capture candidate at the conservative threshold right now

Cap-sensitivity read:

- at `combined_cost_cap = 0.99`
  - `ranked_candidate_count = 6`
  - gross locked spread is only about `1%`
  - this is not yet strong enough to call a validated edge because timeout risk, queue position, adverse selection, and scratch losses can erase it
- at `combined_cost_cap = 1.00`
  - the same `6` markets remain eligible
  - this is a structural-shadow signal only, not a deployment-grade edge

Interpretation:

- the maker thesis remains strategically correct
- the repo now has an executable maker-shadow surface
- but the current books do not yet justify live spread capture under the strict conservative threshold
- the next improvement step is not “go live maker now”
- the next improvement step is:
  - keep the directional baseline live
  - keep maker spread capture shadow-only
  - model threshold sensitivity, fill probability, scratch loss, and queue/toxicity effects before any live maker tranche

### March 12 Fast-Wallet Research Update

Treat the following as a strong new external research input for the fast-market queue:

- the top Polymarket fast-market crypto wallets appear to be predominantly maker-side spread-capture or hybrid market-making systems, not pure directional forecasters
- dual-sided inventory patterns are the strongest public clue
- wallet-flow directional copying should therefore move to a confirmation overlay, not remain the primary short-horizon alpha thesis

Research-backed takeaways to incorporate:

- best fast-wallet study target for absolute-scale hybrid behavior:
  - `k9Q2mX4L8A7ZP3R`
- best clone target for a small bankroll:
  - `vidarx`
- best publicly documented strategy family:
  - `gabagool22` / `Arbigab` style inventory-skewed spread capture

Operational implications for this repo:

- prioritize a BTC-only, 5-minute, dual-sided, maker-first lane
- prefer post-only resting orders on both YES and NO
- enter only when combined cost is meaningfully below 1.00
- use strict timeout / scratch discipline when one side fills and the hedge does not
- treat Binance or wallet-flow data as confirmation or adverse-selection protection, not as the primary fast-market edge
- do not spend the next cycle trying to copy high-win-rate directional wallets as if they were pure predictors

Recommended shadow-lane defaults for research and implementation:

- market universe:
  - BTC 5-minute Polymarket up/down markets only
- execution:
  - maker-only, post-only
  - no live taker momentum mode
- combined-cost cap:
  - start with `YES + NO <= 0.97`
- timeout:
  - start with `120` seconds for 5-minute markets
- bankroll sizing for the current book:
  - target `$5-$10` total notional per market
  - keep `6-8` concurrent markets max
  - reserve cash rather than deploying the full bankroll
- wallet-flow usage:
  - `overlay_only`
- live rollout:
  - shadow-only until the lane has its own validation surface and fill/toxicity evidence

Important refinement from the first corrected live shadow run:

- `0.97` remains the conservative default shadow cap
- treat `0.99` as a threshold-sensitivity probe only, not as a validated live threshold
- any research recommendation that promotes `0.99` or wider must explicitly account for:
  - timeout/scratch losses
  - queue priority
  - adverse selection
  - real maker fill probability
  - current fee/rebate regime

The repo already contains maker-side substrate that should be reused rather than replaced:

- `bot/maker_velocity_blitz.py`
- `scripts/maker_velocity_blitz.py`
- `src/maker_fill_model.py`
- `bot/polymarket_clob.py`
- `bot/btc_5min_maker_core.py`

The next deep-research loop should evaluate how to turn that substrate into:

1. a dual-sided spread-capture shadow lane,
2. a fill / toxicity / queue-model validation surface,
3. a maker-first operator packet that explains when spread capture is structurally available,
4. a wallet-flow overlay that confirms or suppresses maker deployment rather than driving it directly.

### March 12 Instance 6 Benchmark Contract (Mirror-Wallet Outperform Queue)

The next fast-market queue must optimize for outperforming mirror-wallet maker mechanics, not copying directional wallet entries.

Required next-cycle benchmark outputs:

- combined-cost distribution by market for dual-sided BTC5 maker candidates
- dual-sided inventory overlap between our candidate set and mirror-wallet cohort
- fill-to-scratch loss ratio for maker intents by threshold regime
- maker candidate availability counts under `0.97`, `0.98`, and `0.99` combined-cost caps
- directional conversion comparison on identical windows:
  - live baseline `active_profile_probe_d0_00075`
  - shadow comparator `d0_00150`

Queue freeze policy:

- keep mutation-led local search frozen while command-node and market daily budgets are exhausted
- only unfreeze mutation work after budget reset and fresh live evidence
- exception: if a new live blocker indicates an operator miss (not a market-regime miss), allow one bounded diagnostic command-node pass

### March 12 Mirror-Wallet Promote Contract

Treat mirror-wallet research as a reference-class input, not as a deployment artifact.

Promotion states for the maker lane:

- `green`
  - non-zero validated candidates exist at the live threshold `0.97`
  - fill-to-scratch evidence is measured and within target
  - toxicity-adjusted EV and improvement-per-dollar are positive after costs
  - lane becomes eligible for bounded finance review, not auto-live
- `yellow`
  - shadow candidates exist only at sensitivity thresholds such as `0.99`
  - fill-to-scratch or toxicity evidence is still incomplete
  - live maker capital stays at `0`
- `red`
  - `0.97` has zero candidates or the measurement is stale
  - mirror-wallet outputs are design context only
  - no artifact may imply maker live readiness

Current state as of March 12, 2026:

- `reports/autoresearch/maker_shadow/latest.json` is `red` for live promotion
- `ranked_candidate_count = 0`
- `candidate_delta_arr_bps = 0.0`
- `arr_confidence_score = 0.1`
- `block_reasons = ["no_shadow_candidates_with_combined_cost_edge", "combined_bid_cost_above_cap"]`
- `reports/autoresearch/maker_shadow_cap099/latest.json` only provides a `yellow` sensitivity read and must remain shadow-only

Operator rule:

- mirror-wallet artifacts may rank hypotheses, guide cap-ladder measurement, and shape fill-model design
- mirror-wallet artifacts may not justify live maker capital, threshold widening, or a promotion claim by themselves
- keep live maker capital at `0` until the maker validation surface is genuinely `green`

## The Main Research Problem Now

Do not optimize for rediscovering the fixed selection bug.

The main question is now:

How should we improve the BTC5 autoresearch system from this point so that:

1. the market-model judge becomes more faithful to real BTC5 market behavior,
2. the policy lane becomes more statistically trustworthy and more deployment-relevant,
3. local and AWS search loops find improvements faster per dollar of LLM and compute spend,
4. the command-node lane continues to produce real headroom instead of saturating,
5. the operator surfaces make benchmark truth, expected outcomes, and live blockers legible,
6. we convert shadow improvements into a validated live edge without over-promoting simulator artifacts?
7. and the fast-market queue prioritizes dual-sided maker spread capture ahead of directional wallet-copying until fresh live evidence proves otherwise?
8. and we use the wallet/MM research to converge toward the same strategy family that appears to dominate the best public Polymarket fast-market accounts?

## What To Read First

Read these files in roughly this order.

### Operator and repo context
- `AGENTS.md`
- `README.md`
- `docs/FORK_AND_RUN.md`
- `COMMAND_NODE.md`
- `PROJECT_INSTRUCTIONS.md`

### Karpathy/autoresearch framing
- `research/karpathy_autoresearch_report.md`

### Core BTC5 cycle and policy logic
- `scripts/run_btc5_autoresearch_cycle_core.py`
- `scripts/run_btc5_policy_autoresearch.py`
- `scripts/btc5_policy_benchmark.py`
- `scripts/btc5_market_policy_frontier.py`

### Market and agent mutation / benchmark lanes
- `scripts/run_btc5_market_model_autoresearch.py`
- `scripts/run_btc5_market_model_mutation_cycle.py`
- `scripts/run_btc5_command_node_autoresearch.py`
- `scripts/run_btc5_command_node_mutation_cycle.py`
- `scripts/render_btc5_market_model_progress.py`
- `scripts/render_btc5_command_node_progress.py`

### Local search and continuous iteration
- `scripts/run_btc5_local_improvement_search.py`

### Ops and deployment
- `scripts/btc5_dual_autoresearch_ops.py`
- `deploy/btc5-market-model-autoresearch.service`
- `deploy/btc5-command-node-autoresearch.service`
- `deploy/btc5-policy-autoresearch.service`
- `deploy/btc5-autoresearch.service`

### Current machine-truth artifacts
- `reports/btc5_autoresearch/latest.json`
- `reports/btc5_market_policy_frontier/latest.json`
- `reports/autoresearch/btc5_policy/latest.json`
- `reports/autoresearch/btc5_policy/promotion_decision.json`
- `reports/autoresearch/btc5_market/latest.json`
- `reports/autoresearch/command_node/latest.json`
- `reports/runtime_truth_latest.json`
- `reports/autoresearch/outcomes/latest.json`
- `reports/autoresearch/morning/latest.json`
- `reports/autoresearch/overnight_closeout/latest.json`

### Behavior-locking tests
- `tests/test_run_btc5_autoresearch_cycle.py`
- `tests/test_run_btc5_policy_autoresearch.py`
- `tests/test_btc5_market_policy_frontier.py`
- `tests/test_run_btc5_local_improvement_search.py`
- `tests/test_run_btc5_market_model_autoresearch.py`
- `tests/test_run_btc5_command_node_autoresearch.py`
- `tests/test_btc5_dual_autoresearch_ops.py`

## What We Need Deep Research To Focus On Next

The remaining work is about quality of the judge, efficiency of the search, and truthfulness of the deployment bridge.

### Priority 1: Make the market-model lane a stronger judge

The market-model lane is the most important component in the stack because it judges policy candidates.

Research concrete code-level changes to:

- rolling-origin or time-series-split evaluation with explicit temporal gap
- stronger probability calibration on held-out data
- regime-aware evaluation and reporting
- better fill-rate realism
- better slippage modeling
- stronger drawdown realism
- benchmark drift detection
- statistical checks for Goodharting the simulator

We want changes that are incrementally deployable and benchmarkable, not giant rewrites.

### Priority 2: Improve policy-lane statistical trustworthiness

Now that selection correctness is fixed, the next question is whether the frontier winner is genuinely robust.

Research code-level changes to:

- add fold-level outputs rather than only one aggregate policy scalar
- bootstrap confidence intervals on candidate vs incumbent deltas
- compare candidate vs incumbent on contiguous time folds
- guard against multiple-testing bias as candidate counts grow
- consider SPA, Model Confidence Set, Deflated Sharpe Ratio, or a simpler staged approximation that fits this codebase
- distinguish benchmark winner from deployment-ready candidate

The goal is to reduce false promotions without slowing the system to a halt.

### Priority 3: Improve local search efficiency

The local loop is the cheapest path to improvement and should be much more sample-efficient.

Research code-level changes to:

- warm-start search more aggressively from frontier seeds
- add content-hash dedup
- add smoke / medium / full fidelity stages
- use Hyperband or ASHA-style pruning
- preserve mutation memory so we do not keep exploring the same dead regions
- use cheap models for routine mutation and stronger models only after stagnation
- measure `improvement_per_dollar` and `improvement_per_hour` per lane

We want more validated keeps per unit time and per unit LLM spend.

### Priority 4: Keep the command-node lane improving

The agent lane should remain useful and not saturate prematurely.

Research code-level changes to:

- benchmark design
- eval-bucket decomposition
- recent-failure injection into task suites
- use of different judge vs proposer models
- avoiding benchmark saturation
- mutation strategies for `btc5_command_node.md`

We want the command-node lane to improve operational usefulness:

- better diagnosis,
- better prioritization,
- better dependency ordering,
- better dispatch quality,
- better morning reports,
- better budget discipline.

### Priority 5: Tighten the bridge from benchmark edge to live edge

Right now we have:

- benchmark charts,
- a frontier winner,
- shadow staging,
- outcome charts,
- blocked live posture.

Research code-level changes to make the bridge clearer and safer:

- better operator reports that explain the difference between live package, selected package, and frontier-best package
- explicit shadow-to-live validation logic
- cleaner mapping from benchmark gains to expected USD/day and ARR
- automatic detection when simulator predictions and shadow results diverge
- live gating that is strict without being arbitrary

We want a system that says clearly:

- what won the benchmark,
- what is staged,
- what is live,
- why they differ,
- whether the simulated edge is holding up in shadow,
- what exact blocker still prevents live deployment.

## External Research Threads To Incorporate

The following external ideas are in scope and should be mapped into exact repo integration points.

Do not repeat them as generic advice. Translate them into file-level implementation proposals.

### 1. Time-series evaluation discipline

Use rolling-origin or time-series splits rather than generic validation.

Relevant implications:

- train/test order must respect time
- use explicit `gap` to avoid leakage
- compare candidate and incumbent over the same contiguous windows
- expose fold-level results, not just one scalar

### 2. Execution realism

The simulator should price fills and slippage more conservatively.

Relevant implications:

- slippage should depend on spread, volatility, participation, and liquidity state
- fill assumptions should be state-dependent rather than static
- thin-book or stressed-regime conditions should cap optimistic fills
- partial-fill realism matters if candidate performance depends on high trade frequency

### 3. Multiple-testing and false-discovery control

Repeatedly selecting the best backtest candidate creates data-snooping risk.

Relevant implications:

- bootstrap confidence on candidate vs incumbent deltas
- Deflated Sharpe Ratio or related adjustments when many candidates are tested
- SPA / Model Confidence Set style logic once candidate counts justify it
- a research path that starts with simpler confidence machinery and evolves toward stronger statistical controls

### 4. Multi-fidelity and budget-aware search

The local loop should act like a resource allocator, not a flat exhaustive evaluator.

Relevant implications:

- cheap early screening
- medium replay for survivors
- full replay only for top survivors
- prune early when candidates are clearly bad
- separate cheap proposer tier from strong proposer tier
- escalate model cost only when stagnation is real

### 5. Judge/proposer separation

The agent lane and possibly other lanes should use a separate judge surface from the proposer surface where practical.

Relevant implications:

- avoid the same model family both proposing and unilaterally grading champion flips
- require stronger evidence for flips that come from noisy eval buckets
- keep human review optional for large, unusual benchmark jumps if model grading confidence is weak

### 6. Benchmark-to-outcome linkage

We need to prevent benchmark drift and business-outcome hallucination.

Relevant implications:

- track the path from benchmark winner to shadow performance to live performance
- explicitly measure the gap between simulated return and shadow/live return
- trigger simulator recalibration when benchmark/outcome divergence persists

## Constraints

Respect these constraints.

- Do not recommend breaking the single-mutable-surface contract for the market or agent lanes unless you justify it rigorously.
- Do not recommend live deployment of unvalidated candidates.
- Do not confuse benchmark improvement with realized live profit.
- Do not propose changing multiple benchmark definitions at once in a way that destroys comparability.
- Do not recommend giant framework churn when smaller, testable file-level changes can capture most of the benefit.
- Do not recommend hand-wavy "use a better model" answers without integration points, cost, and expected value.
- Do not assume the repo is globally clean outside the BTC5 lanes.
- Do not ask the system to trust stale probe or stale frontier artifacts.
- Treat AWS as the long-running executor and local loops as the fast iteration layer.

## Current Contracts And Anchors

When discussing expected impact or proposing scoring changes, work from the current contracts unless you explicitly argue for a contract change.

### Market-model objective

`simulator_loss = 0.40*pnl_window_mae_pct + 0.25*fill_rate_mae_pct + 0.20*side_brier + 0.15*p95_drawdown_mae_pct`

Lower is better.

### Policy objective

`policy_loss = (-p05_30d_return_pct) + 0.25*(-median_30d_return_pct) + 2.0*loss_limit_hit_probability + 1.0*non_positive_path_probability + 0.05*p95_drawdown_pct`

Lower is better.

### Current market-backed anchor

From `reports/btc5_market_policy_frontier/latest.json`:

- frontier best package: `active_profile`
- frontier best loss: `-55389.7504`
- incumbent loss: `-54143.0069`
- improvement vs incumbent: `1246.7435`

Use this as a real anchor when discussing selection, staging, and expected impact.

## Failure Modes You Must Address Explicitly

Be explicit about these failure modes:

- benchmark overfitting
- simulator Goodharting
- stale artifact selection
- stale market-model-version reuse
- false suppressions from probe or staging logic
- package identity collisions or join bugs
- repeated testing optimism / false discovery
- command-node benchmark saturation
- high LLM spend without corresponding benchmark headroom
- shadow performance diverging from simulated performance
- confusing expected outcomes with realized outcomes

## What Good Answers Look Like

A strong answer should return:

1. a precise diagnosis of the highest-leverage remaining bottlenecks,
2. exact file-level changes,
3. tests to add or modify,
4. quantified hypotheses:
   - expected delta in policy loss,
   - expected delta in keep rate,
   - expected delta in simulator fidelity,
   - expected delta in ARR or USD/day only when the mapping is justified,
   - expected delta in improvement velocity per hour or per dollar,
5. a sequencing plan that preserves comparability,
6. LLM spend guidance:
   - what should use cheap proposer models,
   - what needs stronger models,
   - what should run locally,
   - what should stay on AWS.

## What Bad Answers Look Like

Reject answers that are mostly:

- generic trading advice,
- generic machine learning advice,
- "get more data" with no code path,
- "improve the benchmark" with no exact file or function,
- "use reinforcement learning" with no integration path,
- "deploy the best candidate now" without explaining live blockers and shadow requirements,
- rediscovery of the already-fixed selection bug without acknowledging the current machine truth.

## Deliverable Format We Want Back

Return the answer in this structure.

### 1. Executive Diagnosis
- 5 to 10 bullet points, sorted by leverage

### 2. Exact Code Changes
- file path
- function or class name
- what to change
- why it helps
- how to test it

### 3. Search Strategy Improvements
- local loop improvements
- AWS loop improvements
- proposer-budget improvements

### 4. Benchmark and Validation Improvements
- market lane
- agent lane
- policy lane
- outcome surfaces

### 5. Quantified Expected Impact
- estimated best-case
- estimated base-case
- estimated downside risk

### 6. Ordered Implementation Plan
- step 1
- step 2
- step 3

## Direct Repo Integration Targets

These are the most likely files where code-level improvements will matter next.

- `scripts/run_btc5_autoresearch_cycle_core.py`
- `scripts/run_btc5_policy_autoresearch.py`
- `scripts/btc5_policy_benchmark.py`
- `scripts/btc5_market_policy_frontier.py`
- `scripts/run_btc5_market_model_autoresearch.py`
- `scripts/run_btc5_market_model_mutation_cycle.py`
- `scripts/run_btc5_command_node_autoresearch.py`
- `scripts/run_btc5_command_node_mutation_cycle.py`
- `scripts/run_btc5_local_improvement_search.py`
- `scripts/btc5_dual_autoresearch_ops.py`
- `deploy/btc5-market-model-autoresearch.service`
- `deploy/btc5-command-node-autoresearch.service`
- `deploy/btc5-policy-autoresearch.service`
- `deploy/btc5-autoresearch.service`

## Concrete Hypotheses To Evaluate

Evaluate and improve these hypotheses.

1. The selection layer is now fixed, so the next bottleneck is judge quality rather than winner selection.
2. `active_profile` is a real current frontier winner under the present market-model champion, but it still needs a stronger bridge from benchmark edge to live edge.
3. The current market-model lane is still the main bottleneck to better live policy discovery.
4. Fold-level and confidence-aware policy benchmarking will reduce false promotions more than it reduces useful search throughput.
5. Multi-fidelity local search can increase validated keeps per dollar by at least `2x` relative to flat evaluation.
6. Better simulator realism around fills, slippage, and regime behavior will change policy rankings in meaningful ways.
7. Better linkage between benchmark frontier, shadow performance, and outcome surfaces will improve operator decision quality.
8. The command-node lane still has room to improve operational usefulness if eval buckets and recent-failure injection are improved.

## Final Instruction

Do not treat this as a writing exercise.

Treat it as a code audit and systems-improvement task on a live BTC5 autoresearch stack.

The selection-path repair is already in place. The next wave is about making the system better in the places that still matter:

- a better judge,
- a faster and cheaper search loop,
- stronger statistical trust,
- better operator truth,
- a clearer shadow-to-live bridge,
- more validated edge per LLM dollar,
- more live trading only when justified by evidence.
