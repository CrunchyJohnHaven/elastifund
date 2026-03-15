# Non-Trading Earning Agent Design

## Objective

Build a second agent family inside Elastifund that can produce cashflow without bespoke human sales work, while staying inside hard legal, deliverability, and billing constraints.

This is not a generic "make money somehow" agent. It is a bounded revenue system with:

- constrained acquisition channels
- explicit jurisdiction rules
- auditable suppression and consent handling
- deliverability kill rails
- billing-dispute kill rails
- a shared allocator that competes with trading for budget

Update, March 7, 2026:

- the repo now contains two non-trading lanes
- the existing outbound lead-routing lane should be treated as a compliance harness and future phase-2 engine, not the first production wedge
- `nontrading/digital_products/` adds a digital-product niche discovery lane for Etsy/Gumroad-style research before any listing automation is turned on
- the recommended first production non-trading engine is now a one-sided, self-serve website growth audit plus recurring monitor
- Elastic remains the shared evidence and memory plane, while `orchestration/` remains the allocator boundary between trading and non-trading spend

## Recommended Launch Model

Launch the non-trading lane as a one-sided, self-serve website growth audit business, not a general marketplace and not an outbound-on-behalf service.

Recommended launch defaults:

- one ICP
- one productized audit offer
- one recurring monitor offer
- one hosted checkout flow
- no calls, no bespoke scoping, no manual sales handoff
- public-web evidence only for the first fulfillment loop

Why this is the launch model:

- it keeps the system evidence-first and inspectable
- it removes the hardest coordination problem from day one: finding and qualifying buyers for a customer
- it reduces legal and deliverability exposure compared with cold outbound as the primary monetization path
- it creates cleaner allocator inputs because discovery, conversion, fulfillment, refunds, and churn can be measured directly
- it reuses the repo's existing strengths: scoring, simulation, event logging, control-plane thinking, and Elastic exports

The existing outbound lane still matters, but later:

- phase 1: sell and fulfill an automated audit and monitor directly
- phase 2: after purchase and explicit customer authorization, allow outbound-on-behalf workflows behind the existing compliance rails

This keeps the first production non-trading engine closer to a software product than to a cold-email operation.

## Hard Defaults

These are not optional policy notes. They are operating constraints.

- Discovery policy: public websites only for the first audit engine. No authenticated scraping, no private data access, no hidden login walls.
- Fulfillment policy: deterministic checks and evidence bundles are primary. Any LLM step is optional, secondary, and auditable.
- Billing policy: use hosted checkout plus webhook-driven provisioning rather than custom card handling.
- Outreach policy: live cold outbound is disabled by default. If enabled later, it inherits the existing suppression, unsubscribe, and geo-policy rails in `nontrading/`.
- Claims policy: no guaranteed-income, passive-income, or unverifiable outcome language anywhere in product copy or templates.
- Data-sharing policy: raw PII, raw inbox contents, raw payment details, and private prompts stay local. Only sanitized knowledge packs are publishable.
- Default execution mode: `sim` or `shadow` until payment, fulfillment, and compliance gates are green.

## System Architecture

The non-trading lane should mirror the trading lane through one shared lifecycle:

```text
discover -> score -> plan -> execute -> settle -> learn
```

For trading:

- discover = market scan
- score = edge and confidence estimation
- plan = position sizing and routing
- execute = broker action
- settle = fills, fees, slippage, PnL
- learn = strategy updates and allocator observations

For the first non-trading engine:

- discover = prospect scan from public websites
- score = purchase probability, margin, compliance risk, and confidence
- plan = offer, price, fulfillment bundle, and optional follow-up path
- execute = checkout session creation, fulfillment job dispatch, and delivery
- settle = cash collected, refunds, churn, delivery latency, and complaints
- learn = better detectors, pricing, ICP filters, and packaging

### Shared Core

Shared with trading:

- config and secrets management
- structured logging and append-only event records
- SQLite audit stores plus Elastic-shaped export payloads
- experiment registry
- kill-switch framework
- allocator interface in `orchestration/`
- hub-facing schemas in `hub/elastic/` and `flywheel/`

### Phase-1 Revenue Audit Services

1. Prospect Discovery
   Purpose: identify businesses with objective, publicly visible website and conversion issues.

   Inputs:

   - seed domains, lists, or target verticals
   - public crawl and fetch workers
   - robots and rate-limit policy
   - canonical prospect normalization rules

   Output:

   - canonical prospect records with evidence URLs, timestamps, and contact-channel candidates

2. Issue Detection and Evidence Bundling
   Purpose: turn raw prospect pages into transparent, evidence-backed problems worth fixing.

   Required artifacts:

   - issue list
   - supporting snippets and source URLs
   - severity
   - confidence
   - missing-data flags
   - explanation object for every score

3. Offer and Checkout Surface
   Purpose: convert a prospect or inbound visitor into a purchase without human intervention.

   Required invariants:

   - hosted checkout only
   - pricing lives in config, not hardcoded templates
   - provisioning happens from verified webhook events
   - every payment action produces a structured event

4. Automated Fulfillment and Recurring Monitor
   Purpose: deliver the paid audit and rerun it for subscribers without manual project work.

   Required records:

   - payment event
   - fulfillment job
   - delivery artifact
   - monitor rerun and delta report
   - refund events
   - support and failure events

5. Knowledge-Pack Export
   Purpose: share learnings without sharing private customer data.

   Publishable outputs:

   - detector summaries
   - aggregated conversion or refund outcomes
   - template variants
   - pricing experiment results
   - proof hashes and metadata

### Phase-2 Buyer-Finder Services

The existing outbound lane remains useful after phase 1, but only behind explicit authorization and the already-documented compliance rails.

Allowed phase-2 use:

- follow-up or nurture for customers who explicitly opt in
- outbound-on-behalf campaigns for paying customers who authorize the workflow
- reply classification and scheduling for those authorized campaigns

Disallowed phase-2 use:

- unsupervised cold-email scaling as the first product wedge
- hidden identity switching between Elastifund and customer senders
- unverifiable consent claims or hand-waved list provenance

## Risk Rails

The earning agent needs risk rails that are as explicit as trading drawdown limits.

### Compliance Rails

Immediate red-state triggers:

- outbound to a non-allowlisted jurisdiction
- missing suppression enforcement
- missing unsubscribe mechanism
- missing lawful basis where the selected policy requires it
- attempts to send from unsupported data provenance

Launch default:

- no outbound required for the phase-1 product path
- if outbound is turned on later, keep it US-only first
- explicit opt-in remains globally acceptable where the system supports it
- role-based business-address outreach remains the narrow outbound exception for US contacts if the later buyer-finder engine is enabled

### Deliverability Rails

Deliverability is a survival metric, not a growth metric.

Suggested internal thresholds:

- complaint rate yellow at `0.0008`, red at `0.0010`
- bounce rate yellow at `0.015`, red at `0.020`
- unsubscribe backlog red if any opt-out processing exceeds 24 hours
- provider or mailbox warning event is immediate yellow
- blocklist hit or authentication failure is immediate red

Scaling rule:

- no send-volume increase unless deliverability is green
- no shift from audit-only into outbound-on-behalf unless deliverability is green for a sustained window

### Billing Rails

Payment disputes are the non-trading analog of toxic flow.

Suggested internal thresholds:

- dispute rate yellow at `0.0075`, red at `0.0100`
- refund rate yellow when it indicates message-quality or qualification drift
- repeated "descriptor confusion" disputes are red even below numeric thresholds

Scaling rule:

- no new customer or budget scaling while billing health is yellow or red

### Funnel-Economics Rails

Positive activity is not enough. The lane must produce contribution margin.

Required tracked metrics:

- revenue per audit
- revenue per monitored account
- tooling and compute cost per audit
- refund-adjusted gross margin
- bad-detection and rework rate
- time-to-cash

Scale only when:

- contribution margin is positive after refunds and failed collections
- the lane remains green on compliance, deliverability, and billing

## Experiment Loop

The self-improvement loop should be statistical and bounded.

Unit of experimentation:

- `segment x audit bundle x price x fulfillment recipe x follow-up path`

Mechanism:

- fixed sample launch budget
- explicit stop-losses
- posterior update after each batch
- Thompson Sampling or fixed-split-plus-exploration for scaling winners

Kill losers quickly when:

- refund or dispute behavior implies offer mismatch
- detector precision is too low to justify automation
- fulfillment latency or failure rate breaks the happy path
- optional outbound follow-up creates complaints or unsubscribe stress

## Allocator Contract

The non-trading lane competes with trading for budget through `orchestration/`.

The allocator should treat non-trading as eligible for increased budget only when all of the following are true:

- non-trading risk is green
- contribution margin is positive
- minimum observation thresholds are met
- there is no unresolved billing or compliance alert
- the current engine family is explicitly allowed to scale by policy

If the lane is yellow or red:

- budget cannot increase
- send quota cannot increase
- LLM token budget cannot increase

This mirrors trading kill discipline: survival first, optimization second.

The allocator should eventually compare at least two non-trading engine families:

- `revenue_audit`: self-serve audit and monitor
- `buyer_finder`: opt-in outbound-on-behalf, disabled by default

## Go / No-Go Gates Before First External Send

All of these must be true before the first real outbound send:

- authenticated sending setup is verified
- unsubscribe flow works end to end
- suppression list is enforced before queue and send
- mailing address footer is present
- geo-fencing is active
- lead provenance is stored
- dispute and refund logging exists
- dry-run messages are auditable

If any are false, the lane stays in dry-run.

## Suggested Repository Roadmap

The next implementation steps should follow this order:

1. Add a shared engine contract so trading and non-trading both implement `discover -> score -> plan -> execute -> settle -> learn`.
2. Add Elastic-native event schemas for opportunities, execution, outcomes, cashflow, compliance, and knowledge packs.
3. Implement `nontrading/revenue_audit/` as the first production non-trading engine.
4. Keep `nontrading/email/` and `nontrading/campaigns/` as the compliance substrate for later opt-in outbound, not as the phase-1 product wedge.
5. Extend allocator inputs from deliverability-only to composite engine health: compliance, refunds, fulfillment quality, and domain health where applicable.

## Design Summary

The correct Elastifund non-trading design is:

- compliance-first
- evidence-first
- productized rather than bespoke
- self-serve before service-heavy
- allocator-driven rather than manually scaled
- deliverability-constrained only where outbound actually exists
- billing-aware and refund-aware
- federated through sanitized knowledge packs rather than shared raw ledgers

That is the only version of "no-touch" that survives contact with real inboxes, real laws, and real payment rails.
