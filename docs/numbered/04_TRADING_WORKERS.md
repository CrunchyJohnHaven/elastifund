# 04 Trading Workers
Version: 1.0.0
Date: 2026-03-09
Source: `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, `research/edge_backlog_ranked.md`, `reports/runtime_truth_latest.json`, `reports/arb_empirical_snapshot.json`
Purpose: Describe the trading worker catalog, execution policy, promotion gates, and current blocked state.
Related docs: `02_ARCHITECTURE.md`, `03_METRICS_AND_LEADERBOARDS.md`, `07_FORECASTS_AND_CHECKPOINTS.md`, `09_GOVERNANCE_AND_SAFETY.md`, `10_OPERATIONS_RUNBOOK.md`

## Mandate

Trading workers exist to test market edges under policy.
They do not exist to force trades when evidence is weak.
The system should prefer no trade over unjustified trade.

## Current Machine Truth

As of `2026-03-09T01:35:13+00:00`, the runtime shows:

- `314` cycles completed.
- `0` total trades.
- `$347.51` tracked capital with `$0` deployed.
- wallet-flow `ready` with `80` scored wallets.
- `jj-live.service` currently `stopped`.
- launch posture `blocked`.
- A-6 blocked.
- B-1 blocked.

That means the trading lane is still in evidence collection and launch gating, not in active profit extraction.

## The Seven Signal Families

### 1. Ensemble Estimator And Agentic RAG

This is the slower-market predictive lane.
It estimates probabilities without showing the market price, applies calibration, scores velocity, and routes only when thresholds are met.
It is strongest in slower categories where reasoning can matter more than raw speed.

### 2. Smart Wallet Flow Detector

This is the top fast-market path to first dollar.
It monitors Polymarket trade flow, scores wallets, and looks for convergence among stronger wallets in fresh short-duration markets.
The current runtime truth says this lane is technically ready, but not yet promoted past the broader launch block.

### 3. LMSR Bayesian Engine

This lane uses trade flow and LMSR-style pricing logic to detect mispricing.
It is a math-first fast-market lane and is intentionally sized small when acting alone.

### 4. Cross-Platform Arbitrage

This worker compares Polymarket and Kalshi pricing for matched contracts.
When it finds a sufficient post-fee gap, it can route high-confidence arbitrage logic.
It remains operationally gated by market matching, execution quality, and launch posture.

### 5. A-6 Multi-Outcome Sum Violation

This structural lane looks for executable guaranteed-dollar constructions in negative-risk event groups.
The March 9 empirical snapshot still shows `0` executable A-6 constructions below the `0.95` gate, so promotion remains blocked.
The next requirement is maker-fill, persistence, and settlement evidence, not broader buildout.

### 6. B-1 Dependency Graph Arbitrage

This lane looks for deterministic implication, exclusion, or complement violations in related markets.
The March 9 audit still found `0` deterministic template pairs in the first `1,000` allowed markets.
That means the density gate failed and promotion remains blocked.

### 7. Elastic ML Anomaly Consumer

This is a caution lane, not a primary edge lane.
It consumes anomaly signals such as VPIN, OFI, spread stress, and confidence drift, then reduces size or pauses routing when the environment looks toxic.
It must always fail soft.

## Confirmation And Sizing Rules

The confirmation layer exists so not every signal is treated the same.
The current rules are:

- Two or more compatible primary signals can boost confidence and size within policy.
- LLM-only signals stay in slower markets with calibration applied.
- Wallet-flow or LMSR alone stay in the small-size fast bucket.
- Structural lanes can bypass predictive confirmation after structural validation.
- Anomaly feedback can reduce size or pause a market without becoming a hard dependency.

## Risk Boundaries

The current repo-level risk frame is conservative:

- paper mode by default
- maker-first execution on fee-bearing markets
- explicit daily loss caps
- per-trade sizing caps
- launch gates before live promotion
- manual escalation for risk changes and real-money transitions

The system is allowed to do nothing when the edge is not there.

## Promotion Gates

Every worker family needs evidence before promotion.
The key current gates are:

- closed trades must exist before calibration and launch claims become meaningful
- deployed capital must move off zero before live performance language changes
- A-6 needs executable constructions below `0.95` plus maker-fill and settlement evidence
- B-1 needs a validated gold set, precision evidence, and non-zero deterministic density
- the broader flywheel must remain green

## Strategy Catalog Status

`research/edge_backlog_ranked.md` currently tracks `131` strategies:

- `7` deployed
- `6` building
- `2` structural alpha
- `1` re-evaluating
- `10` rejected
- `8` pre-rejected
- `97` in the research pipeline

The public rule is simple:
catalog size is not proof of edge.
Only validated, policy-cleared lanes count toward promotion.

## What Needs To Happen Next

The next trading milestone is not broader strategy expansion.
It is narrower:

- confirm safe runtime mode,
- resume evidence collection in paper or shadow,
- record the first closed trades,
- and clear or kill the blocked structural lanes with data instead of narrative.

Last verified: 2026-03-09 against `reports/runtime_truth_latest.json`, `reports/arb_empirical_snapshot.json`, and `research/edge_backlog_ranked.md`.
Next review: 2026-06-09.
