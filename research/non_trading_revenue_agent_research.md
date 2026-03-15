# Non-Trading Revenue Agent Research

Status: research capture  
Captured: March 7, 2026  
Purpose: define a viable, no-touch, non-trading revenue lane for Elastifund that can coexist with the trading system under shared risk, budgeting, and operating discipline.

This document complements the implementation-facing design in `docs/NON_TRADING_EARNING_AGENT_DESIGN.md`. The focus here is not code structure first. It is the operational, legal, and economic shape of a lane that can survive contact with real inboxes, real customers, and real payment disputes.

Companion doc: `research/trading_bot_inventory_benchmark_blueprint.md`

## Bottom Line

A fully automated, self-improving revenue agent is only viable if "no touch" is interpreted narrowly and responsibly.

The practical version that can work is:

- a productized funnel
- bounded acquisition rules
- auditable routing and attribution
- automated collection of a defined fee or commission
- hard kill rails for compliance, deliverability, billing, and unit economics

The version that does not survive is obvious:

- scraped lists
- blast-style cold email at scale
- ambiguous consent
- unconstrained LLM negotiation
- no reputation or complaint controls

The correct design frame is not "AI closes bespoke deals over email." It is "AI operates a narrow rules-based revenue system with the same safety mindset as the trading lane."

## Why This Fits The Existing Elastifund Model

The current project already has the right mental model:

- Python services
- VPS deployment
- systemd discipline
- SQLite persistence
- explicit kill rules
- a scan -> score -> act -> record -> learn loop

The non-trading lane should not be a separate philosophy. It should be a second strategy family on the same substrate.

## Feasibility Constraints

The non-trading lane only makes sense if it stays inside hard constraints.

### Constraint 1: Commercial Email Compliance

If the system sends outreach, it is a compliance system by default.

Core implications:

- US outbound still requires CAN-SPAM compliance
- B2B email is not exempt from core commercial-email rules
- UK, EU, Canada, and Australia introduce materially stricter constraints around consent, personal data handling, and objections to direct marketing

Design consequence:

- jurisdiction gating must be a first-class system behavior
- lawful-basis or policy-class metadata must exist per lead
- suppression must be global, append-only, and enforced before queue and send

If those controls do not exist, the lane is automating liability rather than revenue.

### Constraint 2: Deliverability Is A Survival Metric

Modern mailbox providers enforce sender hygiene operationally.

That means the agent needs:

- authenticated sending:
  SPF, DKIM, DMARC
- unsubscribe compliance:
  both in-body and via standards-compliant headers
- complaint-rate monitoring
- bounce-rate monitoring
- hard stop behavior when health degrades

The right abstraction is a `Deliverability Health Gate`, not a marketing dashboard.

### Constraint 3: ESP Policy Enforcement

Mainstream providers will suspend senders who rely on bought or scraped lists, unverifiable third-party consent, or poor complaint hygiene.

Practical consequence:

- default acquisition cannot depend on scraping
- purchased lists should be disallowed by policy and config
- the lane should prefer opt-in capture and tightly bounded business-role-address outreach

## Recommended Launch Interpretation Of "No Touch"

The cleanest initial business model is:

- productized lead routing
- auditable consent or contact-policy provenance
- fixed offer structure
- bounded qualification logic
- automated fee collection

This keeps the system:

- rules-based
- measurable
- compatible with kill switches
- less exposed to open-ended human negotiation

Recommended launch defaults:

- one niche
- one buyer persona
- one offer
- one acquisition channel
- US-only outbound by default
- pay-per-qualified-meeting or similarly narrow monetization

## Operating Model

The non-trading lane should use four layers.

### Acquisition Layer

Allowed inputs:

- inbound opt-in forms
- partner-provided lists with provable rights to contact
- directories or datasets that fit the allowed contact policy
- tightly constrained B2B role-based outreach in allowed jurisdictions

Disallowed by default:

- purchased lists
- scraped email lists
- unverifiable third-party consent claims

### Decision Layer

The "brain" should rank opportunities in a form comparable to trading signals.

Canonical unit:

- `lead x offer x channel x sequence`

Scoring inputs:

- expected value
- send-budget cost
- deliverability risk
- reply likelihood
- qualification likelihood

This is structurally the same as a trading decision engine:

- signals
- budget
- expected value
- risk rails

### Execution Layer

Execution should use bounded actuators:

- email sender with dry-run default
- web funnel or landing page
- scheduling or booking links
- payment rail for automated collection

The system should avoid:

- free-form negotiation
- dynamic promises
- custom pricing invented in replies

### Learning Layer

Every send or routing action is an experiment.

Tracked outputs should include:

- delivered
- opened if tracked lawfully
- replied
- qualified
- booked
- paid
- refunded
- disputed

This allows posterior updates on which combinations deserve more budget.

## Self-Improvement Mechanism

Do not overcomplicate the first version with heavy ML.

The default allocator should be:

- fixed-split launch budget
- experimentation by batch
- Thompson Sampling or a similarly simple Bayesian bandit once minimum sample sizes are reached

Why this fits:

- it maps well to limited send quotas
- it handles uncertainty cleanly
- it has the same exploration-versus-exploitation shape as trading capital allocation

Canonical experiment arm:

- `niche x offer x source x sequence x CTA`

## How It Maps To Existing Architecture

The optimal pattern is an `Agent OS` substrate with two strategy families:

- trading
- non-trading revenue

## Shared Substrate

Shared components should include:

- config and secrets management
- scheduler loop
- SQLite persistence and migrations
- structured logging
- metrics and telemetry
- kill-switch framework
- allocator interface
- dashboard surface

## Trading Lane

The trading lane keeps its own:

- broker connectivity
- execution stack
- drawdown and position risk controls

## Non-Trading Lane

The revenue lane keeps its own:

- compliance risk manager
- deliverability health manager
- send-quota budgeting
- billing and dispute health manager

That is the direct analog of drawdown, exposure, and open-position limits on the trading side.

## Revenue Risk Manager

The revenue lane needs explicit rails, not vague operational preferences.

### Compliance Rails

Immediate red-state conditions:

- outbound to a blocked or unsupported jurisdiction
- missing lawful-basis or contact-policy metadata for the chosen mode
- missing unsubscribe mechanism
- suppression bypass
- unsupported provenance on a lead

Launch default:

- US-only outbound
- explicit opt-in accepted where provenance is stored
- role-based business addresses allowed only within the US launch policy

### Deliverability Rails

Deliverability is the reputation equivalent of capital preservation.

Suggested internal thresholds:

- complaint rate yellow at `0.0008`, red at `0.0010`
- bounce rate yellow at `0.015`, red at `0.020`
- opt-out processing older than 24 hours is red
- mailbox-provider warning events are immediate yellow
- authentication failure or blocklist hit is immediate red

Scaling rule:

- send volume cannot increase unless deliverability is green

### Billing Rails

Billing is the downstream analog of toxic flow.

Suggested thresholds:

- dispute rate yellow at `0.0075`, red at `0.0100`
- repeated descriptor confusion is red even below numeric thresholds
- refund spikes should block scaling when they indicate offer-quality drift

Scaling rule:

- no new spend expansion while billing health is yellow or red

### Funnel-Economics Rails

The lane should not scale on activity alone.

Required metrics:

- revenue per qualified meeting
- tooling cost per meeting
- lead cost per meeting
- refund-adjusted contribution margin
- bad-lead rate
- time-to-cash

Scale only when:

- contribution margin is positive after refunds and failed collections
- compliance is green
- deliverability is green
- billing is green

## Shared Allocation Across Trading And Non-Trading

To compete side-by-side for budget, both lanes need a common decision unit.

### Trading Lane Output

The trading lane naturally reports:

- expected dollar EV per unit of bankroll
- realized P&L
- drawdown
- capital efficiency

### Non-Trading Lane Output

The revenue lane should report:

- gross profit
- variable costs
- complaint and block events
- conversion lag
- profit per 100 sends
- profit per 100 leads evaluated

### Allocator Policy

Practical default:

- fixed split while samples are small
- Thompson Sampling once both lanes have minimum evidence
- hard override:
  if deliverability is yellow or red, non-trading allocation cannot increase

A persistent exploration floor should remain so that early noise does not permanently starve one lane.

## Build Strategy For The Repo

The existing repo structure and working style favor additive modules, standalone services, SQLite stores, and explicit tests. The clean way to build this is as a sequence of bounded implementation instances.

### Instance 1: Scaffolding, Persistence, And Kill Switch

Goal:

- create the minimal `nontrading/` service substrate without implementing outreach

Required outputs:

- `nontrading/main.py`
- `nontrading/config.py`
- `nontrading/store.py`
- `nontrading/models.py`
- `nontrading/risk.py`
- `nontrading/tests/test_scaffolding.py`

Scope rules:

- separate SQLite DB under `data/revenue_agent.db`
- CLI entrypoint with `--run-once` and `--daemon`
- additive only
- no edits to `bot/jj_live.py`

Verification:

- `pytest -q`
- dry-run of `python -m nontrading.main --run-once`

### Instance 2: Compliance-First Email Sending Substrate

Goal:

- implement sender infrastructure without sending real email by default

Required outputs:

- `nontrading/email/sender.py`
- `nontrading/email/headers.py`
- `nontrading/email/render.py`
- `nontrading/email/providers/sendgrid_adapter.py`
- `nontrading/email/providers/mailgun_adapter.py`
- `nontrading/email/validate.py`
- `nontrading/tests/test_email_compliance.py`

Hard requirements:

- dry-run sender by default
- mandatory mailing address footer
- unsubscribe URL in body
- `List-Unsubscribe` and `List-Unsubscribe-Post` header support
- suppression list checked before any send

### Instance 3: Campaign Engine For Opt-In Or US-Only B2B Role Addresses

Goal:

- create the first bounded campaign loop without adding scraping

Required outputs:

- `nontrading/campaigns/engine.py`
- `nontrading/campaigns/policies.py`
- `nontrading/importers/csv_import.py`
- `nontrading/tests/test_campaign_engine.py`

Required behaviors:

- default US-only jurisdiction gating
- only explicit opt-in leads or allowed role-based business emails
- daily send quota
- automatic suppression on unsubscribe

Verification:

- `pytest -q`
- `python -m nontrading.main --run-once` with a small sample CSV

### Instance 4: Shared Resource Allocator

Goal:

- add a budget allocator without touching the trading execution code

Required outputs:

- `orchestration/resource_allocator.py`
- `orchestration/models.py`
- `orchestration/store.py`
- `orchestration/tests/test_allocator.py`
- `docs/NON_TRADING_ALLOCATOR_SPEC.md`

Required behaviors:

- fixed-split mode by default
- Thompson Sampling behind a feature flag
- hard rule:
  non-trading allocation cannot increase when deliverability is yellow or red

## Critical Defaults To Encode In Config

These should be code defaults, not wishful policy notes.

- geography:
  US-only outbound at launch
- list policy:
  no purchased or scraped lists
- domain isolation:
  use a dedicated sending subdomain
- messaging policy:
  approved templates with bounded fields only
- suppression:
  append-only and enforced before queue and before send
- hard kill metrics:
  complaint rate, bounce rate, unsubscribe latency, billing disputes

## Working Conclusion

The non-trading lane is viable only as a bounded, compliance-first revenue engine with:

- productized offers
- controlled acquisition
- auditable suppression
- explicit deliverability kill rails
- billing risk controls
- shared budget allocation with the trading lane

That keeps the architecture coherent with the rest of Elastifund. The same core philosophy applies in both lanes: scan, score, act, record, learn, and kill the strategy quickly when survival metrics degrade.
