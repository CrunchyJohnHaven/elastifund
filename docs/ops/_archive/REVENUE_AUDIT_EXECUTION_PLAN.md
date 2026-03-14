# Revenue Audit Execution Plan

**Status:** active recommendation  
**Last Updated:** 2026-03-07

## Purpose

Integrate the current repo with a new non-trading recommendation:

- keep the trading lane intact
- keep `orchestration/` as the budget allocator
- keep Elastic as the shared evidence and observability backbone
- pivot the first production non-trading wedge away from outbound-first lead routing
- build a one-sided, self-serve website audit and recurring monitor engine first

This is a repo-specific plan, not a greenfield rewrite.

## What Already Exists

The current repository already contains the main pieces this plan should reuse:

- trading execution and research loops in `bot/`, `src/`, `polymarket-bot/`, and `simulator/`
- a shared allocator in `orchestration/`
- a SQLite-backed control plane and exchange artifacts in `data_layer/` and `flywheel/`
- a hub gateway and Elastic bootstrap layer in `hub/` and `hub/elastic/`
- a non-trading compliance and outbound substrate in `nontrading/`
- a second non-trading research lane in `nontrading/digital_products/`

What does **not** exist yet:

- a shared engine contract across trading and non-trading
- a website-audit engine under `nontrading/`
- customer-facing offer pages and checkout
- a shared event schema for trading and non-trading outcomes
- knowledge-pack publishing shaped around sanitized revenue learnings

## Design Decisions

1. Add, do not rewrite.
2. The first production non-trading engine is `revenue_audit`, not outbound lead routing.
3. The existing outbound lane becomes a phase-2 engine for explicit customer authorization and follow-up.
4. Use `hub/app/` as the first API surface for offer pages and webhooks unless a stronger existing surface is discovered.
5. Keep local raw data SQLite-first where that is already the repo pattern, but emit Elastic-shaped documents and templates from day one.
6. Use sanitized knowledge packs and leaderboard documents for federation. Do not design around shared multi-writer raw indices.

## Target Architecture

Shared lifecycle for both families:

```text
discover -> score -> plan -> execute -> settle -> learn
```

Repo mapping:

- `discover`
  - trading: existing market scanners and detectors
  - non-trading: new public-web prospect discovery under `nontrading/revenue_audit/`
- `score`
  - trading: calibration and edge scoring
  - non-trading: issue severity, purchase probability, expected margin, compliance risk
- `plan`
  - trading: sizing and execution plan
  - non-trading: offer type, price, fulfillment recipe, optional follow-up path
- `execute`
  - trading: broker/API order flow
  - non-trading: checkout creation, fulfillment queueing, optional shadow outbound
- `settle`
  - trading: fills, slippage, P&L
  - non-trading: revenue, refunds, churn, delivery events, complaints
- `learn`
  - trading: flywheel and allocator observations
  - non-trading: detector results, template outcomes, pricing outcomes, knowledge packs

## Path Layout Recommendation

Recommended additive modules:

- `nontrading/revenue_audit/`
- `nontrading/revenue_audit/discovery.py`
- `nontrading/revenue_audit/detectors.py`
- `nontrading/revenue_audit/scoring.py`
- `nontrading/revenue_audit/fulfillment.py`
- `nontrading/revenue_audit/models.py`
- `nontrading/revenue_audit/store.py`
- `nontrading/revenue_audit/checkout.py`
- `nontrading/revenue_audit/monitor.py`

Recommended shared surfaces:

- `orchestration/` for allocation and engine selection
- `hub/elastic/` for templates, mappings, transforms, and validation
- `hub/app/` for API endpoints, hosted-checkout creation, and webhook handling
- `flywheel/` for knowledge-pack publishing, leaderboard inputs, and ops artifacts

## Rollout Order

Run in this order:

1. shared engine contract
2. event schema and Elastic templates
3. discovery, scoring, and simulator in parallel
4. checkout and fulfillment
5. allocator, knowledge packs, and dashboards
6. documentation
7. phase-2 buyer-finder engine only after the audit engine works end to end

## Execution-Ready Claude Code Instances

These prompts are written for this repo as it exists today. They explicitly point Claude Code at the folders already present here so the work stays additive.

### Instance 1 — Shared engine contract

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Create a shared MoneyEngine-style contract that unifies trading and non-trading engines without breaking the current trading lane.

Repo anchors:
- `orchestration/`
- `nontrading/`
- `src/`
- `bot/`
- `simulator/`

Tasks:
1. Inspect the current trading and non-trading entrypoints and identify the smallest additive contract that fits both.
2. Implement shared models and interfaces for `Opportunity`, `Evaluation`, `ActionPlan`, `ExecutionRecord`, `OutcomeRecord`, `CashflowRecord`, `ComplianceDecision`, `BudgetRequest`, `BudgetAllocation`, and `RunMode`.
3. Add an engine registry/factory that can resolve engine implementations by config.
4. Add compatibility shims so the current trading path can expose the shared lifecycle without invasive rewrites.
5. Add a no-risk `revenue_audit` skeleton under `nontrading/`.
6. Add tests and a short ADR or design note.

Constraints:
- additive only
- default everything to `sim` or dry-run
- do not change live trading behavior

Deliverables:
- changed files
- tests run
- assumptions and blockers

### Instance 2 — Shared event schema and Elastic templates

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Create the shared event schema for trading and non-trading engines and wire it into the existing Elastic bootstrap layer.

Repo anchors:
- `hub/elastic/bootstrap.py`
- `hub/elastic/specs.py`
- `data_layer/`
- `flywheel/`

Tasks:
1. Inspect current Elastic alias, template, and data-stream conventions.
2. Add templates or mappings for:
   - `opportunity_event`
   - `execution_event`
   - `outcome_event`
   - `cashflow_event`
   - `compliance_event`
   - `knowledge_pack`
   - `allocator_snapshot`
   - `leaderboard_daily`
   - `prospect_raw`
   - `prospect_profile_latest`
3. Add application-level schema objects for those documents.
4. Add serialization helpers so both trading and non-trading engines can emit events consistently.
5. Define transforms or transform-ready specs for:
   - `prospect_profile_latest`
   - `engine_scoreboard_latest`
   - `campaign_rollup_daily`
6. Add tests and a README.

Constraints:
- keep this Elasticsearch-native
- do not add Enterprise Search-only dependencies
- preserve the existing bootstrap flow in `hub/elastic/`

### Instance 3 — Prospect discovery from public websites

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Build the first discovery worker for the `revenue_audit` engine using public web data only.

Repo anchors:
- `nontrading/`
- `hub/`
- `shared/python/`

Tasks:
1. Inspect whether existing importer, worker, or queue abstractions can be reused.
2. Implement a pluggable discovery worker that accepts seed domains, seed CSVs, or vertical configs.
3. Restrict discovery to public pages and respect robots, rate limits, and retry policy.
4. Capture raw page evidence, metadata, and normalized business entities.
5. Extract clearly public contact channels, but do not send anything.
6. Persist raw and normalized outputs through the shared schema.
7. Add fixtures and normalization tests.

Constraints:
- no authenticated scraping
- no private data access
- deterministic and inspectable output

### Instance 4 — Issue detection, scoring, and evidence bundles

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Turn discovered prospects into scored revenue-audit opportunities with transparent evidence.

Repo anchors:
- new `nontrading/revenue_audit/`
- `simulator/`
- `orchestration/`

Tasks:
1. Build deterministic detectors for public website issues such as missing metadata, weak CTA structure, broken schema, missing contact affordances, and obvious performance or content gaps where the evidence is public.
2. Produce an evidence bundle with issue list, snippets, URLs, severity, confidence, and missing-data flags.
3. Implement a transparent scoring model for `purchase_probability`, `expected_margin`, `expected_payback_days`, `confidence_score`, and `compliance_risk_score`.
4. Add an explanation object that can be stored and rendered.
5. Keep any LLM summary or reranking step optional and secondary.
6. Add fixtures and stability tests.

Constraints:
- deterministic evidence is primary
- outputs must serialize into the shared schema
- no live outreach

### Instance 5 — Offer pages, checkout, and provisioning

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Create the purchase surface for the one-time audit and recurring monitor products.

Repo anchors:
- `hub/app/`
- `hub/app/main.py`
- `hub/app/server.py`
- `nontrading/`

Tasks:
1. Inspect the existing FastAPI surfaces and extend the one that is most suitable for public offer pages and webhook handling.
2. Implement endpoints or lightweight pages for:
   - one-time website growth audit
   - recurring monitor subscription
3. If no billing integration exists, add a hosted-checkout integration with Stripe Checkout and webhook verification.
4. On successful purchase, create a fulfillment job and write payment events through the shared schema.
5. Add a simple post-purchase status endpoint.
6. Add tests for checkout creation, webhook verification, and provisioning.

Constraints:
- hosted checkout only
- webhook-driven provisioning only
- pricing must be config-based
- do not invent a second web framework unless the repo already requires it

### Instance 6 — Automated fulfillment and recurring monitor

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Automate audit delivery and recurring monitor reruns.

Repo anchors:
- new `nontrading/revenue_audit/`
- `reports/`
- `flywheel/`

Tasks:
1. Build an async fulfillment pipeline that produces:
   - audit summary
   - prioritized issues
   - concrete recommendations
   - optional CTA or copy suggestions
   - optional patch snippets or schema suggestions
2. Emit delivery artifacts in Markdown or HTML first.
3. Add a recurring monitor job that reruns discovery and detection and emits delta reports.
4. Write fulfillment and monitor events into the shared schema.
5. Add tests and fixture-based example artifacts.

Constraints:
- reproducible and inspectable
- no manual intervention on the happy path
- avoid PDF unless the existing stack already supports it cleanly

### Instance 7 — Optional follow-up and compliance rails

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Reuse the existing outbound substrate only for policy-approved follow-up flows after the audit product exists.

Repo anchors:
- `nontrading/email/`
- `nontrading/campaigns/`
- `nontrading/risk.py`
- `nontrading/store.py`

Tasks:
1. Inspect current suppression, unsubscribe, and quota logic.
2. Add run-mode distinctions for `sim`, `shadow`, and `live` that map cleanly onto the new shared engine contract.
3. Add policy checks so outbound follow-up is blocked unless:
   - the customer explicitly authorized it, or
   - the follow-up path is otherwise allowed by stored policy
4. Extend event ingestion for bounce, complaint, and reply-classification outcomes.
5. Add tests proving cold-send defaults remain disabled.

Constraints:
- do not make outbound the primary purchase path
- live sending must remain disabled by default
- preserve existing compliance rails

### Instance 8 — Non-trading simulator and experiment evaluator

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Make the audit engine compete fairly with trading through a simulation layer shaped like the existing trading evaluation stack.

Repo anchors:
- `simulator/`
- `orchestration/`
- `nontrading/`

Tasks:
1. Reuse existing simulator conventions where possible.
2. Model discovery volume, site-quality hit rate, checkout conversion, refunds, churn, compute costs, optional follow-up costs, and payback period.
3. Add scenario analysis and Monte Carlo runs.
4. Emit scorecard-ready outputs for the allocator and dashboards.
5. Add tests and one sample config.

Constraints:
- simulation first
- assumptions must be explicit and configurable

### Instance 9 — Joint allocator upgrade

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Extend the current allocator so it reasons over trading plus the new `revenue_audit` engine family.

Repo anchors:
- `orchestration/resource_allocator.py`
- `orchestration/models.py`
- `orchestration/store.py`

Tasks:
1. Preserve the current layered allocator structure.
2. Add engine-family-aware inputs including `expected_net_cash_30d`, `confidence`, `required_budget`, `capacity_limits`, `refund_penalty`, `fulfillment_penalty`, `domain_health_penalty`, and `compliance_status`.
3. Hard-block any engine with failing compliance.
4. Emit richer explanation objects and snapshot docs for Elastic.
5. Add tests and dry-run CLI examples.

Constraints:
- explainable decisions only
- advisory-by-default
- preserve current allocator behavior for existing lanes where inputs are absent

### Instance 10 — Knowledge packs and leaderboard

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Extend the existing flywheel exchange artifacts into sanitized knowledge packs for the new audit engine.

Repo anchors:
- `flywheel/federation.py`
- `flywheel/improvement_exchange.py`
- `flywheel/kibana_pack.py`
- `data_layer/`

Tasks:
1. Add a knowledge-pack schema for sanitized shared learnings:
   - engine metadata
   - detector summaries
   - template variants
   - aggregated outcomes
   - proof references and hashes
2. Add signing and verification for publish and pull flows.
3. Keep raw customer identities, inbox content, and payment details out of published packs.
4. Generate leaderboard-ready documents using observed outcomes and penalty metrics.
5. Add tests for sanitize, sign, verify, publish, and pull.

Constraints:
- no multi-writer raw replication model
- separate public and private data by design

### Instance 11 — Dashboards, alerts, and kill switches

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Make the audit engine operable inside the existing Elastic-first control-plane story.

Repo anchors:
- `hub/elastic/`
- `flywheel/kibana_pack.py`
- `docs/ops/ELASTIC_HUB_BOOTSTRAP.md`

Tasks:
1. Add dashboards or dashboard specs for:
   - engine performance
   - prospect pipeline
   - checkout funnel
   - fulfillment status
   - refunds and churn
   - allocator decisions
   - knowledge-pack activity
2. Add alert specs for:
   - checkout webhook failures
   - fulfillment stalls
   - refund spikes
   - complaint spikes if outbound follow-up is enabled
   - missing worker activity
   - negative ROI regimes
3. Add kill switches for global non-trading and per-engine shutdown.
4. Add validation tests or scripts.

Constraints:
- actionable alerts only
- shared schema alignment required

### Instance 12 — Documentation and positioning update

You are Claude Code working inside the Elastifund repository. Execute this instance now.

Goal:
Align public docs with the new architecture without claiming features that do not exist yet.

Repo anchors:
- `README.md`
- `docs/`
- `docs/launch/`
- `docs/adr/`

Tasks:
1. Update the README and architecture docs to explain the new phase-1 non-trading wedge.
2. Update non-trading docs so the audit engine is the first production path and outbound becomes phase 2.
3. Keep positioning anchored to an autonomous revenue research platform, not guaranteed income.
4. Document what remains implemented, what is planned, and what is disabled by default.

Constraints:
- no deceptive earnings language
- no aspirational fiction presented as current capability

### Instance 13 — Phase-2 buyer-finder engine

You are Claude Code working inside the Elastifund repository. Execute this instance now, but only after the audit engine works end to end.

Goal:
Build the second non-trading engine for explicit customer authorization and outbound-on-behalf workflows.

Repo anchors:
- `nontrading/`
- `orchestration/`
- `flywheel/`

Tasks:
1. Create a `buyer_finder` engine using the shared contract.
2. Accept onboarded customer profile, approved offer description, allowed segments, allowed channels, and campaign constraints.
3. Reuse existing suppression, throttle, evidence, and outcome infrastructure.
4. Start with simulation and shadow mode only.
5. Keep live outbound blocked unless explicit customer authorization is present.
6. Add tests and docs.

Constraints:
- disabled by default
- no live outbound without explicit authorization
- no guaranteed-results language

## Immediate Dispatch Order

Run:

1. Instance 1
2. Instance 2

Then in parallel:

3. Instance 3
4. Instance 4
5. Instance 8

Then:

6. Instance 5
7. Instance 6
8. Instance 9

Then:

9. Instance 10
10. Instance 11
11. Instance 12

Finally:

12. Instance 7 when follow-up flows are needed
13. Instance 13 only after the phase-1 engine is stable

## Bottom Line

The correct repo-specific path is:

- preserve the trading stack
- preserve the allocator
- preserve the Elastic hub direction
- add a shared engine contract
- make `revenue_audit` the first production non-trading engine
- treat outbound as a later, opt-in engine instead of the first monetization story
