# 02 Architecture

Purpose: define the canonical system map, data flow, worker model, and design constraints for Elastifund.

## System Shape

Elastifund is a shared substrate for two families of workers:

- Trading workers for prediction-market research and execution under policy
- Non-trading workers for revenue operations and other bounded economic workflows

Both families feed the same memory, evaluation, observability, and publishing loop.

## Six-Layer Master Architecture

| Layer | Purpose | What lives here |
| --- | --- | --- |
| 1. Experience | Human-facing surfaces | Website, README, leaderboards, dashboards, diary, roadmap |
| 2. Control | Policy and orchestration | Scheduling, approvals, budgets, task queues, retries, permissions, autonomy levels |
| 3. Worker | Specialized execution agents | Trading workers, revenue workers, research workers, proposal workers, coding workers |
| 4. Evaluation | Judgment and ranking | Experiment scoring, leaderboards, confidence estimates, forecasts, improvement velocity |
| 5. Memory | Shared context | Leads, messages, market data, prompts, outcomes, code diffs, notes, templates, forecasts |
| 6. Data And Telemetry | Ground truth | Events, logs, metrics, traces, costs, errors, artifacts, commits, model usage |

Design rule: every important action should create an event, every event should be queryable, every query should support a judgment, and every judgment should update both a worker and a public surface.

## Shared Substrate

The common substrate across the repo is:

- System memory for structured and unstructured evidence
- Evaluation for ranking strategies, prompts, and worker outcomes
- Observability for latency, costs, errors, and policy events
- Workflow automation for approvals, retries, and recurring jobs
- Publishing for docs, scorecards, reports, and public artifacts

Elastic is the intended system memory and observability spine for this substrate. The design goal is richer memory and better operator visibility without making execution hard-dependent on Elastic uptime.

## Trading Signal Stack

The current trading architecture uses multiple signal families plus a confirmation layer.

| Source | Function | Current role |
| --- | --- | --- |
| 1. Ensemble estimator + agentic RAG | Slow-market forecasting with calibration | Deployed predictive lane |
| 2. Smart wallet flow detector | Wallet convergence in short-duration markets | Fast-market lane; wallet-flow readiness is tracked separately |
| 3. LMSR Bayesian engine | Flow-based mispricing detection | Fast-market math lane |
| 4. Cross-platform arb scanner | Polymarket versus Kalshi pricing gaps | Structural arbitrage lane |
| 5. A-6 guaranteed-dollar scanner | Multi-outcome negative-risk constructions | Shadow-mode structural lane with empirical gate |
| 6. B-1 dependency engine | Deterministic implication/exclusion violations | Gated structural lane |
| 7. Elastic ML anomaly consumer | Toxicity and drift feedback | Caution and size-adjustment lane |

### Confirmation Layer

The confirmation layer decides how signals combine before execution:

- Two or more predictive sources agreeing increases confidence and can boost size within policy.
- LLM-only predictions stay limited to slower markets with calibration applied.
- Wallet-flow or LMSR alone stay in the small-size fast-market bucket.
- Structural arbitrage lanes can bypass predictive confirmation after structural validation.
- Anomaly feedback can reduce size, pause routing, or surface a lane for review.

## Non-Trading Five-Engine Model

The first non-trading worker family is organized as five cooperating engines:

| Engine | Purpose | Typical outputs |
| --- | --- | --- |
| 1. Account Intelligence | Find, enrich, and score targets | Account records, fit scores, research notes |
| 2. Outreach | Draft, queue, and send compliant messages | Sequences, variants, send decisions, follow-ups |
| 3. Interaction | Handle replies, scheduling, and meeting prep | Reply classes, calendar actions, briefs, next steps |
| 4. Proposal | Turn discovery into scoped offers | Proposal drafts, pricing bands, scope recommendations |
| 5. Learning | Compare predictions to outcomes and revise playbooks | Template changes, score updates, prompt revisions |

All five engines should write to the same memory and telemetry layer so the system can learn from every outreach, reply, meeting, proposal, and outcome.

## Core Flows

### Trading Flow

`research -> signal generation -> calibration -> execution checks -> routing -> outcome capture -> evaluation -> publish`

### Non-Trading Flow

`account research -> scoring -> draft outreach -> approval -> interaction -> proposal -> outcome capture -> evaluation -> publish`

## Design Constraints

- Run in paper mode by default.
- Keep human escalation for real-money deployment, risk changes, and unresolved legal or compliance questions.
- Separate paper, live, and forecasted performance everywhere.
- Treat telemetry as additive; core execution must fail soft when observability services degrade.
- Prefer one shared memory and evidence model over siloed worker histories.
- Keep every public claim traceable to a source artifact.

## Architectural Implication

Elastifund is not a collection of unrelated scripts. It is a looped system where memory, evaluation, and publishing are as important as the worker logic itself.

## Source Inputs

This architecture is extracted from `COMMAND_NODE.md` and `research/elastic_vision_document.md`, with signal-stack specifics grounded in the current `COMMAND_NODE.md` technical sections.
