# 03 Metrics And Leaderboards

Purpose: define the public scorecards, graph rules, update cadence, and confidence requirements for Elastifund.

## Metrics Philosophy

Public metrics should make the system more legible, not more flattering. Every graph and scorecard must answer three questions:

1. What is being measured?
2. What source artifact produced the number?
3. What confidence should a reader assign to it?

If a metric cannot be defined simply, sourced cleanly, and updated honestly, it should not be on a public leaderboard.

## The Four Essential Public Graphs

| Graph | Definition | Why it matters | Guardrail |
| --- | --- | --- | --- |
| Estimated run-rate annualized return | Forward-looking estimate derived from the currently active strategy set | Shows what the system believes the active stack can do now | Must never be presented as realized live return |
| Improvement velocity | Rate of validated improvement over 7, 30, and 90 days | Shows whether the system is learning faster | Must disclose the count of experiments behind the slope |
| Commit velocity | Code changes, merged experiments, and validated improvements over time | Shows contribution health and implementation throughput | Raw commit count cannot stand in for quality |
| Feature and checkpoint forecast | Expected milestones, dates, and confidence revisions | Makes the roadmap legible and falsifiable | Missed forecasts must remain visible, not be rewritten away |

## Trading Scoreboard Rules

Trading metrics should separate four states:

- Research only
- Paper performance
- Live performance
- Forecast or estimated run rate

No chart may merge those categories into one line without explicit labels.

Core trading public metrics:

- current system ARR
- runtime cycles completed
- live trades executed
- deployed versus blocked strategies
- current launch posture
- service state
- test status
- structural gate status for A-6 and B-1

## Non-Trading Worker Panel

The non-trading leaderboard should report operational funnel metrics, not vanity activity counts alone.

Required panel metrics:

- accounts researched
- qualified leads generated
- messages sent
- reply rate
- meetings booked
- show rate
- proposals sent
- pipeline value created
- revenue won
- gross margin estimate
- time to first dollar
- annualized contribution margin

## Current Baseline Snapshot

The canonical March 9, 2026 baseline pulled from the current admin files is:

| Metric | Current baseline |
| --- | --- |
| Current system ARR | `0%` realized |
| Runtime cycles | `303` |
| Live trades | `0` |
| Service state | `jj-live.service` observed `running` at `2026-03-09T00:48:05Z` |
| Launch posture | blocked |
| Wallet-flow readiness | `ready` with `80` scored wallets |
| Strategy catalog | `131` total (`7` deployed, `6` building, `2` structural alpha, `1` re-evaluating, `10` rejected, `8` pre-rejected, `97` pipeline) |
| Current root verification | `867 passed in 18.83s; 22 passed in 3.56s` |
| Last full multi-surface green baseline | `1,256` total tests (`849 + 22` root, `374` polymarket, `11` non-trading) |
| Dispatch inventory | `11` work-orders and `95` dispatch markdown files |
| Structural gates | A-6: `0` executable constructions below `0.95`; B-1: `0` deterministic pairs in first `1,000` allowed markets |

This baseline is intentionally unglamorous. That is the point. The public system should show reality as it is.

## Source Artifacts

Public metrics should preferentially read from these artifacts:

- `reports/public_runtime_snapshot.json`
- `reports/runtime_truth_latest.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `research/edge_backlog_ranked.md`
- `improvement_velocity.json`
- `FAST_TRADE_EDGE_ANALYSIS.md`

Narrative docs may summarize the numbers, but these artifacts should remain the machine-readable sources of truth.

## Update Cadence

| Surface | Cadence | Notes |
| --- | --- | --- |
| Runtime and service status | Per cycle or on state change | Pull from runtime artifacts |
| Trading leaderboards | At least once per flywheel cycle | More often only if source data changed |
| Non-trading leaderboards | At least once per flywheel cycle | Include zero states honestly while lanes are forming |
| Improvement velocity charts | Once per cycle | Keep revision history visible |
| Executive summary and README scorecards | When headline numbers change materially | Do not leave stale metrics in public copy |

## Confidence Band Requirements

Every public graph should declare a confidence posture:

- Forecast metrics require a confidence band or confidence label.
- Improvement velocity should state sample size or experiment count.
- Live-performance charts require a clear note when the sample is too small for confidence.
- Non-trading funnel forecasts should disclose whether they are based on real outcomes, synthetic planning assumptions, or mixed evidence.

Suggested confidence labels:

- High: based on direct observed outcomes with sufficient sample
- Medium: based on partial evidence or mixed live and historical inputs
- Low: based on early-stage estimates, sparse samples, or planning assumptions

## Governance Rule

Leaderboards are not for hype. They are the public evaluation layer. Their job is to make progress, stalling, and failure legible enough that the next cycle gets smarter.

## Source Inputs

This document is derived from `research/elastic_vision_document.md`, `README.md`, `PROJECT_INSTRUCTIONS.md`, and `COMMAND_NODE.md`.
