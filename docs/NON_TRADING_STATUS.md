# Non-Trading Status

**Status Date:** 2026-03-08

## Executive Read

The non-trading lane is ahead of the public repo narrative but behind the monetization plan.

Current reality:

- the codebase already contains a working compliance-first revenue-agent harness
- the codebase already contains a working digital-product niche discovery lane
- both lanes have passing local tests and deterministic smoke coverage
- the recommended first production wedge, a self-serve website growth audit plus recurring monitor, is still design-only

That means the project is not stalled, but it is not revenue-ready either.

## What Exists Today

### Revenue-Agent Harness

Path:

- `nontrading/main.py`
- `nontrading/campaigns/`
- `nontrading/email/`
- `nontrading/store.py`

Implemented:

- CSV lead import
- per-campaign send loop
- role-address and geo-policy gating
- suppression and unsubscribe handling
- dry-run sender plus provider adapter scaffolding
- deliverability and kill-switch rails
- SQLite audit store

Current mode:

- locally runnable
- safe by default
- not a launched revenue engine

### Digital-Product Discovery Lane

Path:

- `nontrading/digital_products/`

Implemented:

- normalized niche candidate ingestion
- deterministic ranking formula
- embedding generation
- SQLite persistence
- Elastic bulk export generation

Current mode:

- locally runnable research lane
- useful for prioritization and packaging
- not wired to checkout, listing, or fulfillment

### Shared Allocation Direction

Path:

- `orchestration/resource_allocator.py`
- [NON_TRADING_ALLOCATOR_SPEC.md](/Users/johnbradley/Desktop/Elastifund/docs/NON_TRADING_ALLOCATOR_SPEC.md)

Implemented direction:

- non-trading is already a first-class lane in the allocator model
- budget competition between trading and non-trading is designed and partially implemented at the orchestration layer

Missing:

- production non-trading metrics strong enough to justify allocator-driven scaling

## Evidence Run On March 8, 2026

Commands executed:

```bash
python3 -m pytest nontrading/tests -q
python3 -m nontrading.digital_products.main --run-once --source-file nontrading/tests/fixtures/sample_product_niches.json --top 3
python3 -m nontrading.main --run-once --import-csv nontrading/tests/fixtures/sample_leads.csv
```

Observed:

- `11` non-trading tests passed
- digital-product discovery ranked `ADHD Planner System` first from the fixture set
- the revenue-agent harness enforced policy filters and stayed in safe dry-run mode

## Main Gap

The biggest gap is not code quality. It is product path mismatch.

The design doc says the recommended first production non-trading wedge is:

- a self-serve website growth audit
- plus a recurring monitor

The code that exists today is instead:

- a compliance-first outbound harness
- a digital-product discovery research lane

Those are useful building blocks, but they are not the first monetization surface described in the plan.

## Development Stage

| Area | Stage | Notes |
|---|---|---|
| Revenue-agent harness | prototype / dry-run capable | strong safety posture, not yet productized |
| Digital-product discovery | research-ready | ranking and export path exist |
| Checkout and billing | not started | no hosted checkout or webhook provisioning |
| Fulfillment engine for website audits | not started | still design-only |
| Public GitHub visibility | weak before this pass | root README did not surface the lane cleanly |

## Recommended Next Steps

1. Keep the existing non-trading harnesses visible and runnable.
   This pass does that by adding `nontrading/README.md`, a deterministic smoke script, and README coverage.

2. Treat outbound as compliance infrastructure, not the launch wedge.
   Do not spend the next cycle polishing cold outbound copy or volume controls as the primary business.

3. Build the phase-1 revenue audit engine next.
   First milestone:
   - public website fetch
   - deterministic issue detection
   - evidence bundle artifact
   - paid-audit deliverable skeleton

4. Add payments and fulfillment before allocation scaling.
   Without checkout, provisioning, refunds, and fulfillment metrics, the allocator has nothing reliable to scale.

## Immediate Forward Motion Landed In This Pass

- public docs now expose the non-trading lane
- a deterministic `make smoke-nontrading` path can verify both current subsystems
- the repo now has a durable status doc for the lane instead of hiding it inside planning notes
