# 02 Architecture
Version: 1.0.0
Date: 2026-03-09
Source: `COMMAND_NODE.md`, `research/elastic_vision_document.md`, `research/platform_vision_document.md`, `PROJECT_INSTRUCTIONS.md`
Purpose: Define the canonical system map, worker model, data flow, and architectural constraints.
Related docs: `00_MISSION_AND_PRINCIPLES.md`, `03_METRICS_AND_LEADERBOARDS.md`, `04_TRADING_WORKERS.md`, `05_NON_TRADING_WORKERS.md`, `10_OPERATIONS_RUNBOOK.md`

## System Shape

Elastifund is a shared substrate for trading workers and non-trading workers.
The architecture is designed so every meaningful action becomes evidence.
That evidence then feeds evaluation, publishing, and the next operating cycle.

## Six-Layer Architecture

| Layer | Purpose | Typical surfaces |
|---|---|---|
| 1. Experience | Human-facing surfaces | Website, README, numbered docs, dashboards, diary, roadmap |
| 2. Control | Policy and orchestration | Scheduling, approvals, budgets, retries, permissions, autonomy levels |
| 3. Worker | Specialized execution units | Trading workers, revenue workers, research workers, proposal workers, coding workers |
| 4. Evaluation | Judgment and ranking | Scorecards, leaderboards, confidence labels, forecasts, velocity charts |
| 5. Memory | Shared context | Leads, market data, prompts, notes, code diffs, outcomes, templates, forecasts |
| 6. Data And Telemetry | Ground truth | Events, logs, metrics, traces, costs, errors, artifacts, model usage |

The design rule is strict:
every important action should create an event,
every event should be queryable,
every query should support a judgment,
and every judgment should update both a worker and a public surface.

## Shared Substrate

Both worker families rely on the same core capabilities:

- System memory for structured and unstructured evidence.
- Evaluation for ranking strategies, prompts, workers, and experiments.
- Observability for latency, costs, errors, and policy events.
- Workflow automation for approvals, retries, and recurring jobs.
- Publishing for docs, scorecards, reports, and public evidence.

Elastic is the intended long-term memory and observability spine.
The system should still fail soft when Elastic is unavailable.

## Trading Architecture

The trading side is a multi-signal system with a confirmation layer.
The primary signal families currently tracked in canonical docs are:

1. Ensemble estimator and agentic RAG for slower markets.
2. Smart wallet flow detection for fast short-duration markets.
3. LMSR Bayesian pricing for flow-driven mispricing.
4. Cross-platform arbitrage across Polymarket and Kalshi.
5. A-6 multi-outcome sum-violation scanning.
6. B-1 dependency-graph arbitrage.
7. Elastic ML anomaly consumption as a caution lane.

Signals one through six can produce a trade thesis.
Signal seven modifies caution, size, or pause posture when anomaly data is present.

## Non-Trading Architecture

The non-trading side is intentionally narrower.
JJ-N is defined as a five-engine model:

1. Account Intelligence.
2. Outreach.
3. Interaction.
4. Proposal.
5. Learning.

Each engine should write to the same memory so the system can learn from every account, message, reply, meeting, proposal, and outcome.

## Core Operating Flows

### Trading Flow

`research -> signal generation -> calibration -> execution checks -> routing -> outcome capture -> evaluation -> publish`

### Non-Trading Flow

`account research -> scoring -> draft outreach -> approval -> interaction -> proposal -> outcome capture -> evaluation -> publish`

### Documentation Flow

`run -> capture artifacts -> reconcile machine truth -> update numbered docs and public surfaces -> hand off to the next cycle`

## Key Data Sources

The current runtime contract relies on machine-readable artifacts, not only prose.
The most important source files are:

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `FAST_TRADE_EDGE_ANALYSIS.md`
- `research/edge_backlog_ranked.md`

## Architectural Constraints

- Paper mode by default.
- Real money, risk changes, and irreversible actions require escalation.
- Public claims must separate live, paper, and forecast states.
- Telemetry must improve the system without becoming a single point of failure.
- Repo structure should stay legible to human contributors and coding agents.
- Durable documentation should live under `docs/` or `research/`, not as drifting root sprawl.

## Current March 9 Snapshot

The active runtime truth is still a blocked system:
`314` cycles, `0` total trades, `0%` realized current system ARR, wallet-flow `ready`, A-6 blocked, B-1 blocked, and `jj-live.service` currently `stopped`.
That snapshot matters because architecture is only useful when it matches reality.

## Architectural Implication

Elastifund is not a pile of scripts.
It is a looped system where memory, evaluation, and publishing are first-class components.
Any change that improves a worker but weakens the evidence loop is architecturally incomplete.

Last verified: 2026-03-09 against `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, and `reports/runtime_truth_latest.json`.
Next review: 2026-06-09.
