# ADR 0005: Make the First Production Non-Trading Engine a Self-Serve Website Audit and Monitor

- Status: Accepted
- Date: 2026-03-07

## Context

The repo already has the first pieces of a dual-lane architecture:

- trading execution and research loops in `bot/`, `src/`, `polymarket-bot/`, and `simulator/`
- a shared allocator in `orchestration/`
- a hub-and-spoke Elastic scaffold in `hub/`, `shared/`, and `deploy/`
- an outbound-compliance lane in `nontrading/`
- a digital-product niche-discovery lane in `nontrading/digital_products/`

The remaining open question is the first production non-trading wedge.

The earlier non-trading design leaned toward outbound lead routing. That remains useful as a compliance harness, but it is not the best first production lane for this repo because it adds inbox, consent, deliverability, and coordination risk before the system has proven a clean self-serve purchase and fulfillment loop.

## Decision

Adopt a one-sided, self-serve website growth audit plus recurring monitor as the first production non-trading engine.

Implications:

- `revenue_audit` becomes the phase-1 non-trading engine family
- the existing outbound lane becomes a phase-2 engine for explicit customer opt-in or outbound-on-behalf workflows
- Elastic remains the shared evidence and knowledge plane
- the allocator remains the authority for budget competition between trading and non-trading
- public and private data remain separated through sanitized knowledge packs rather than multi-writer shared raw indices

## Consequences

Positive:

- simpler, cleaner purchase path than a two-sided marketplace
- lower legal and deliverability exposure in phase 1
- more direct measurement of conversion, refunds, fulfillment quality, and payback period
- better fit for the repo's existing control-plane, simulation, and evidence-first architecture

Negative:

- the repo's existing outbound lane is no longer the primary product story
- customer-facing offer pages, checkout, and fulfillment now become near-term priorities
- the project must support public-web crawling and deterministic issue detection to make the audit credible

## Follow-up

Implementation should be additive:

- introduce a shared engine contract across trading and non-trading
- add `nontrading/revenue_audit/`
- reuse `nontrading/email/` only for explicit, policy-approved follow-up paths
- wire the new engine into `orchestration/`, `hub/elastic/`, and `flywheel/`
