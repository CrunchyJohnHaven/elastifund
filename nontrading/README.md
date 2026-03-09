# Non-Trading Lane

This directory holds Elastifund's second revenue lane: automation intended to generate cash flow outside prediction-market trading.

## Current Status

Two non-trading subsystems already exist:

- `nontrading/main.py`: a compliance-first revenue agent with lead import, policy gating, suppression handling, unsubscribe support, dry-run sending, and provider adapters
- `nontrading/digital_products/main.py`: a digital-product niche discovery pipeline that ranks opportunities and emits Elastic-ready knowledge documents

JJ-N is now beyond the original bare-substrate baseline, but it is still not launched.
The repo has the first service-offer and operator assets, not a production revenue loop.

Current repo truth verified on 2026-03-09:

- `make test-nontrading` is currently green in this worktree (`61` tests)
- `pytest -q tests/nontrading` is currently green in this worktree (`49` tests)
- the Website Growth Audit offer, templates, follow-up sequence, dashboard asset, and `RevenuePipeline` module exist
- `nontrading/main.py` now builds and runs `RevenuePipeline`
- live-provider startup is hard-blocked when sender domain/auth is placeholder or unverified

## What Exists Today

Phase 0 JJ-N foundations now exist for the planned revenue-operations worker:

- CRM schema in `nontrading/models.py` and `nontrading/store.py` for `Account`, `Contact`, `Opportunity`, `Message`, `Meeting`, `Proposal`, and `Outcome`
- `nontrading/opportunity_registry.py` with the 7-criterion opportunity rubric from the vision document
- `nontrading/approval.py` with store-backed paper-mode approval gating for outreach
- `nontrading/approval_gate.py` as a compatibility re-export of the unified approval gate
- `nontrading/compliance.py` with verified-domain, suppression, unsubscribe, sender-identity, and daily-rate-limit checks
- `nontrading/telemetry.py` plus `nontrading/engines/` stubs for the five-engine model and Elastic-ready Phase 0 events
- `infra/index_templates/elastifund-nontrading-events.json` with the JJ-N Elastic index template
- `nontrading/offers/website_growth_audit.py` with the first concrete service offer
- `nontrading/campaigns/template_selector.py` plus three templates under `nontrading/email/templates/`
- `nontrading/campaigns/sequences.py` with the three-step follow-up sequence
- `infra/kibana_dashboards/nontrading-revenue-funnel.ndjson` with the JJ-N dashboard asset
- `nontrading/pipeline.py` with the sequential five-engine pipeline

What is not built yet:

- a green repo-root JJ-N surface for persisted registry ranking after reload
- CLI wiring from `nontrading/main.py` into `RevenuePipeline`
- verified sending domain and DNS auth
- curated lead list plus explicit approval for real sends
- hosted checkout, billing webhooks, provisioning, and fulfillment reporting
- a production KPI dashboard for non-trading revenue

## Five-Engine Architecture

```text
Account Intelligence -> Outreach -> Interaction -> Proposal -> Learning
         |                  |            |             |            |
         +------------------+------------+-------------+------------+
                                  shared CRM + telemetry

CRM records: Account, Contact, Opportunity, Message, Meeting, Proposal, Outcome
Guardrails: approval gate (paper mode), CAN-SPAM checks, suppression list, rate limits
Telemetry events: account_researched, message_sent, reply_received, meeting_booked,
proposal_sent, outcome_recorded
```

Current repo truth:
the engine modules still keep their Phase 0 `process()` compatibility stubs, and the pipeline plus stage-specific methods are active.
`nontrading/main.py` builds and runs the pipeline path.

## Phase 0 Status

| Capability | State | Notes |
|---|---|---|
| CRM schema | Done | stable Phase 0 data model exists |
| Opportunity registry | Done | scoring exists, store-backed paths exist, and reload ranking tests are green in both test surfaces in this worktree |
| Approval classes | Done | AUTO / REVIEW / ESCALATE routing exists in a separate module |
| Paper mode | Done | safe default remains on |
| Telemetry | Done | ECS-shaped event output plus Elastic index template |
| Dashboards | Done | `infra/kibana_dashboards/nontrading-revenue-funnel.ndjson` exists |
| Domain auth | Missing | config defaults still use `example.invalid` placeholders |
| Templates | Done | three Website Growth Audit templates exist |
| Unified approval pipeline | Done | `nontrading/approval_gate.py` now re-exports the unified gate |
| RevenuePipeline | Wired | `nontrading/pipeline.py` exists and the CLI now runs the pipeline path |

## First Wedge

The first production wedge remains the Website Growth Audit plus recurring monitor described in [docs/NON_TRADING_EARNING_AGENT_DESIGN.md](/Users/johnbradley/Desktop/Elastifund/docs/NON_TRADING_EARNING_AGENT_DESIGN.md).

Planned service definition:

- customer: SMBs with public websites and visible growth issues
- deliverable: an evidence-backed audit artifact
- follow-on: recurring monitoring once the audit path is stable
- price range: `$500-$2,500`
- delivery: `5` days
- fulfillment type: `hybrid`
- status: implemented in code, not launched

## What Was Built This Cycle

- JJ-N CRM and opportunity-scoring primitives
- unified approval routing plus compatibility re-export
- Website Growth Audit offer definition, three templates, and a follow-up sequence
- ECS-shaped telemetry, Elastic index template, and a JJ-N dashboard asset
- the five-engine `RevenuePipeline` module
- green package-local JJ-N verification via `make test-nontrading`

## What Is Still Missing For Phase 1

- verified sending domain and DNS auth
- curated lead list plus approval to send real messages
- checkout, billing, provisioning, and fulfillment metrics for a real revenue loop

## Safe Defaults

- Revenue-agent sending defaults to `dry_run`.
- The current outbound lane should be treated as a compliance harness and future phase-2 engine, not the first production wedge.
- The digital-products lane is research and prioritization infrastructure, not listing automation.

## Commands

Targeted tests:

```bash
make test-nontrading
```

Deterministic smoke run for both non-trading lanes:

```bash
make smoke-nontrading
```

Run the revenue-agent harness directly:

```bash
python3 -m nontrading.main --run-once --import-csv nontrading/tests/fixtures/sample_leads.csv
```

JJ-N verification surfaces:

```bash
make test-nontrading
python3 -m pytest tests/nontrading -q
```

Run the digital-product niche discovery lane directly:

```bash
python3 -m nontrading.digital_products.main \
  --run-once \
  --source-file nontrading/tests/fixtures/sample_product_niches.json \
  --top 5
```

## Development Order

1. Keep the current harnesses green with tests and smoke runs.
2. Fix the repo-root registry persistence regression so the store-backed registry is actually reliable.
3. Wire `nontrading/main.py` into the five-engine `RevenuePipeline`.
4. Add the remaining launch blockers: domain auth, curated leads, and explicit approval for live sends.
5. Add checkout, fulfillment, and reporting before treating the non-trading lane as revenue-bearing.
