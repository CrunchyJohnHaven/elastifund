# 03 Metrics And Leaderboards
Version: 1.0.0
Date: 2026-03-09
Source: `COMMAND_NODE.md`, `research/elastic_vision_document.md`, `research/platform_vision_document.md`, `README.md`, `reports/runtime_truth_latest.json`
Purpose: Define the public scorecards, graph rules, source artifacts, and confidence requirements.
Related docs: `01_EXECUTIVE_SUMMARY.md`, `02_ARCHITECTURE.md`, `04_TRADING_WORKERS.md`, `05_NON_TRADING_WORKERS.md`, `07_FORECASTS_AND_CHECKPOINTS.md`

## Metrics Philosophy

Public metrics should make the system more legible, not more flattering.
Every chart and scorecard must answer three questions:

1. What exactly is being measured?
2. Which artifact produced the number?
3. How much confidence should a reader assign to it?

If a metric fails any of those tests, it should not be public.

## The Four Core Public Graphs

| Graph | Definition | Why it matters | Guardrail |
|---|---|---|---|
| Estimated run-rate annualized return | Forward-looking estimate derived from active strategy state | Shows what the system believes the current stack could do | Must never be presented as realized live return |
| Improvement velocity | Rate of validated improvement over time | Shows whether the system is learning faster | Must disclose sample size and evidence basis |
| Code or commit velocity | Validated implementation throughput | Shows contribution health and execution pace | Raw commit count cannot stand in for quality |
| Feature and checkpoint forecast | Expected milestones and confidence shifts | Makes the roadmap falsifiable | Missed forecasts stay visible |

## Trading Scoreboard Rules

Trading metrics must separate four categories:

- Research only
- Paper performance
- Live performance
- Forecast or estimated run rate

No chart should merge those categories into one unlabeled line.

Core public trading metrics are:

- current system ARR
- cycles completed
- total trades
- closed trades
- launch posture
- service state
- wallet-flow readiness
- structural gate status for A-6 and B-1
- current verification status

## Non-Trading Worker Panel

The worker leaderboard should report operational funnel metrics, not vanity activity alone.
Required metrics are:

- accounts researched
- qualified leads generated
- messages sent
- reply rate
- meetings booked
- proposals sent
- pipeline value created
- revenue won
- gross margin estimate
- time to first dollar
- annualized contribution margin

## Source Of Truth Priority

Use machine-readable artifacts before narrative summaries.
The preferred sources are:

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `improvement_velocity.json`
- `research/edge_backlog_ranked.md`
- `FAST_TRADE_EDGE_ANALYSIS.md`

If prose and runtime artifacts disagree, the artifacts win.

## Current Baseline On March 9, 2026

| Metric | Current value | Source |
|---|---|---|
| Current system ARR | `0%` realized | `improvement_velocity.json` |
| Cycles completed | `314` | `reports/runtime_truth_latest.json` |
| Total trades | `0` | `reports/runtime_truth_latest.json` |
| Service state | `stopped` at `2026-03-09T01:34:47.856921+00:00` | `reports/remote_service_status.json` |
| Launch posture | `blocked` | `reports/runtime_truth_latest.json` |
| Wallet-flow readiness | `ready` with `80` wallets | `reports/runtime_truth_latest.json` |
| Root verification | `956 passed in 18.77s; 22 passed in 3.69s` | `reports/root_test_status.json` |
| Strategy catalog | `131` tracked | `research/edge_backlog_ranked.md` |
| Structural gates | A-6 blocked, B-1 blocked | `reports/arb_empirical_snapshot.json` |

## Confidence Labels

Every public graph should declare a confidence posture:

- High: backed by direct runtime artifacts with current timestamps.
- Medium: backed by validated reports or repeatable benchmark runs.
- Low: forecasted from sparse evidence or early planning.
- Speculative: useful for planning, not for external claims.

## Update Cadence

| Surface | Cadence | Notes |
|---|---|---|
| Runtime and service status | On state change or each remote pull | Prefer synced runtime artifacts |
| Trading leaderboards | Once source data changes materially | Never leave stale live claims in place |
| Worker leaderboards | Per flywheel cycle or funnel milestone | Zero states should remain visible |
| Improvement velocity charts | Per cycle | Preserve revision history |
| Forecast graphs | On checkpoint movement | Keep prior misses visible |

## Metrics Review Rule

When a metric moves, update the chart only after the source artifact exists.
When a metric is uncertain, say so in the chart note or supporting doc.
When a metric is outdated, remove or relabel it instead of letting it drift into fiction.

Last verified: 2026-03-09 against `reports/runtime_truth_latest.json`, `reports/public_runtime_snapshot.json`, and `reports/root_test_status.json`.
Next review: 2026-06-09.
