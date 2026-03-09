# 05 Non-Trading Workers
Version: 1.2.0
Date: 2026-03-09
Source: `research/elastic_vision_document.md`, `research/platform_vision_document.md`, `docs/NON_TRADING_EARNING_AGENT_DESIGN.md`, `reports/jjn_phase0_20260309T013819Z.json`, `nontrading/README.md`
Purpose: Define the JJ-N strategy, operating model, implementation status, and staged rollout.
Related docs: `02_ARCHITECTURE.md`, `03_METRICS_AND_LEADERBOARDS.md`, `07_FORECASTS_AND_CHECKPOINTS.md`, `09_GOVERNANCE_AND_SAFETY.md`, `12_MANAGED_SERVICE_BOUNDARY.md`

## Why JJ-N Exists

The first broadly shareable use case for Elastifund should be a non-trading worker, not a broad autonomous company.
JJ-N exists to prove one repeatable revenue loop that is measurable, safe, and instrumented.
The current strategic recommendation is unchanged:
start with a revenue-operations worker for one narrow, high-ticket service offer.

## Current Repo Status

As of 2026-03-09, JJ-N is still a Phase 0 system.
The repo has the safe substrate, not the revenue loop.

Verified repo truth:

- `make test-nontrading` now passes with `53` JJ-N tests green under `nontrading/tests`
- the repo-root `tests/nontrading` surface is not green: it currently fails `1` of `49` tests on persisted registry ranking after reload
- the CRM schema, compliance rails, telemetry bridge, Elastic index template, unified approval gate, and five engine modules exist
- the Website Growth Audit offer, three message templates, follow-up sequence, dashboard asset, and `RevenuePipeline` module now exist in code
- the opportunity registry has SQLite-backed work in progress, but it is not trustworthy enough to call finished yet
- `nontrading/main.py` still runs the legacy campaign harness instead of the pipeline

## First Wedge

The first production offer remains the Website Growth Audit plus a recurring monitor.
This is the correct wedge because it keeps the first non-trading lane evidence-first, bounded, and measurable.

Planned service definition:

- customer: SMBs with public websites and visible growth or conversion issues
- acquisition surface: one narrow channel with explicit approval and compliance guardrails
- initial deliverable: an evidence-backed audit, not bespoke agency work
- follow-on offer: recurring monitoring once the audit path is stable

Status:
the wedge now exists in code as `nontrading/offers/website_growth_audit.py` with a `$500-$2,500` price range, `5` delivery days, and hybrid fulfillment.
It is still not launched:
there is no checkout surface, no verified sending domain, and the runnable CLI still does not execute the pipeline.

## The Five-Engine Model

| Engine | Job | Typical outputs |
|---|---|---|
| Account Intelligence | Find, enrich, and score targets | account records, target lists, fit scores, notes |
| Outreach | Draft, queue, and sequence messages | message variants, send decisions, follow-up schedules |
| Interaction | Handle replies and meeting prep | reply classes, calendar holds, briefs, next actions |
| Proposal | Turn discovery into scoped offers | proposal drafts, pricing bands, scope recommendations |
| Learning | Compare predictions to outcomes | template changes, score updates, prompt revisions |

Current repo truth:
the engine modules still preserve their Phase 0 `process()` compatibility stubs, but they now also expose real stage methods used by the pipeline.

## RevenuePipeline Status

The intended autonomy loop is:

```text
Lead import or public prospect discovery
  -> Account Intelligence
  -> Outreach
  -> Interaction
  -> Proposal
  -> Learning
```

Gate points:

- opportunity scoring before advancement
- compliance checks before any message can be queued
- approval routing before any live send
- telemetry emission at every stage

Current repo truth:
`nontrading/pipeline.py` now defines `RevenuePipeline` and `CycleReport`.
What is still missing is the operational handoff:
`nontrading/main.py` still runs the legacy campaign harness instead of the pipeline entrypoint.

## Opportunity Registry

Before JJ-N works a new opportunity, it should be scored in a registry.
The criteria remain:

- time to first dollar
- gross margin
- automation fraction
- data exhaust
- compliance simplicity
- capital required
- sales-cycle length

The purpose of the registry is to stop the project from becoming an undisciplined idea machine.
Current repo truth:
the weighted scoring rubric exists and SQLite persistence is partially implemented through `RevenueStore`, but the repo-root regression surface still catches a reload-order bug.

## Phase Plan

### Phase 0 - Foundations

Build the safe substrate:

- opportunity registry
- CRM schema
- telemetry and dashboards
- domain and authentication setup
- templates
- approval classes
- paper mode

### Phase 0 Checklist

| Capability | Status | Notes |
|---|---|---|
| Opportunity registry | Done | rubric exists and registry objects can persist through `RevenueStore` |
| CRM schema | Done | account, contact, opportunity, message, meeting, proposal, and outcome records exist |
| Telemetry bridge | Done | ECS-shaped JSONL telemetry exists and the Elastic index template is present |
| Dashboards | Done | `infra/kibana_dashboards/nontrading-revenue-funnel.ndjson` exists |
| Domain authentication | Not started | defaults still point to `example.invalid` placeholders |
| Templates | Done | three Website Growth Audit templates now exist under `nontrading/email/templates/` |
| Approval classes | Done | AUTO / REVIEW / ESCALATE classes exist |
| Paper mode | Done | outreach remains safe-by-default |
| Registry SQLite backing | In progress | implemented, but repo-root test `tests/nontrading/test_opportunity_registry.py` still fails on reload ranking |
| Unified approval pipeline | Done | `nontrading/approval_gate.py` is now a re-export of the unified gate in `nontrading/approval.py` |
| RevenuePipeline | Built, not wired | `nontrading/pipeline.py` exists, but `nontrading/main.py` still runs the legacy harness |

### Phase 1 - Assisted Pilot

Run a constrained live workflow with human approvals:

- curated lead list
- three message angles
- follow-up engine
- meeting booking flow
- weekly review

### Phase 1 Prerequisites

Required before claiming Phase 1 readiness:

- verified sending domain and DNS authentication
- registry reload-order regression fixed on the repo-root test surface
- `RevenuePipeline` wired into the CLI `--run-once` / `--daemon` path
- a curated lead list for one ICP
- explicit approval before any real message send

### Phase 2 - Partial Autonomy

Automate low-risk actions only after evidence exists:

- auto-queue approved sequences
- reply classifier
- meeting briefs
- proposal drafting
- confidence-based approvals

### Phase 3 - Repeatability

Prove one loop is stable enough to expand:

- documented win-loss patterns
- stable funnel metrics
- published worker leaderboard
- explicit go or no-go decision on the next wedge

## Approval And Compliance Principles

JJ-N is not allowed to behave like a shadowy outbound bot.
It must operate with:

- authenticated domains
- accurate sender identity
- suppression and unsubscribe handling
- rate limits
- message approval in early phases
- no autonomous pricing commitments
- no autonomous contract execution
- no autonomous spend or deliverability changes

In short: move fast in experimentation, move slowly in permission.

## What Success Looks Like

Success for the first ninety days is not "general business autonomy."
Success means the system can answer:

- who the best target accounts are
- which messages convert
- which objections recur
- which meetings turn into proposals
- where human intervention still matters most

## Current Implementation Direction

Repo-wide messaging now treats JJ-N as a first-class front door.
That is directionally correct.
The maturity claim must stay narrower:
JJ-N has a good Phase 0 substrate, but it does not yet have a live offer, a production dashboard, or a working autonomy loop.

## Managed-Service Implication

If JJ-N proves one repeatable loop, the open-source system can remain public while a hosted layer later handles premium templates, deliverability operations, and customer-specific configuration.
That boundary is described in `12_MANAGED_SERVICE_BOUNDARY.md`.

Last verified: 2026-03-09 against repo code, `reports/jjn_phase0_20260309T013819Z.json`, and `docs/NON_TRADING_EARNING_AGENT_DESIGN.md`.
Next review: 2026-06-09.
