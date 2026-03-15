# Elastic Leadership Pitch Readiness Plan
Date: 2026-03-11
Owner: Codex working session
Audience: John Bradley, future implementation passes, Elastic leadership prep

## Objective

Make `elastifund.io`, the GitHub repo, and the repo entry docs ready for an Elastic leadership audience this week.

The end state is not "better marketing."
The end state is a public proof surface where an Elastic employee can understand three things within 30 seconds:

1. what Elastifund is
2. why Elastic is central to it
3. how they can inspect, run, and improve it safely

## North-Star Message

Use this as the governing message for the homepage, `/elastic/`, README, and the presentation narrative:

> Elastifund is an open-source, self-improving operating system for agents that do real economic work.
> Trading is the first proof lane.
> Non-trading is the broader company-wide opportunity.
> Elastic is the system memory, evaluation, observability, and workflow substrate that makes the agents improve instead of drift.

Internal shorthand can still be "the best open-source make-me-money self-improving agent."
Public-facing copy should translate that into calmer language:

- "real economic work"
- "economic outcomes"
- "self-improving agents"
- "artifact-backed improvement"

That preserves the ambition without sounding unserious.

## Immediate Diagnosis

The current public surfaces are not ready for leadership review.

### What is working

- The repo already has a strong underlying idea: self-improving workers plus an Elastic-backed evidence layer.
- The Elastic story already exists in the docs and `/elastic/`, even if it is not the first thing a visitor understands.
- The repo already has a runnable paper-mode path and a shared-hub collaboration pattern.

### What is hurting credibility

1. Extreme annualized forecast numbers dominate the story.
   - `+2.28M%` and similar figures read as unserious, even when technically derived from short windows.
   - They cause a smart reader to distrust the rest of the page.
2. Public surfaces mix realized, simulated, blocked, and internal operator metrics.
   - The audience has to reverse-engineer what is live, what is forecast, and what is still blocked.
3. The homepage still reads too much like a trading-system status board.
   - It does not immediately communicate the larger Elastic-relevant platform thesis.
4. The README is trying to be a public landing page, an operator snapshot, and a research handoff at the same time.
5. Sensitive capital clues remain too visible.
   - Wallet value, collateral, and sleeve P&L in dollars are not needed for the leadership pitch.
6. The onboarding story is still more operator-centric than employee-centric.
   - The safe path for "clone, run, and improve in paper mode" needs to be more obvious than the live stack.

## Non-Negotiable Messaging Rules

These rules should govern every public-facing edit in this pass.

### Keep

- The claim that Elastifund is self-improving
- The claim that Elastic is the shared substrate
- The separation between trading, non-trading, and finance
- The paper-mode-safe contribution path
- The distinction between live proof and blocked claims

### Remove Or Demote

- Any homepage or README headline built around annualized forecast percentages over short windows
- Wallet balances, free collateral, bankroll size, or any number that exposes capital scale
- Absolute P&L dollar headlines when the real point is return quality or improvement velocity
- Any phrasing that makes the project sound like a pure trading bot
- Any metrics that require a long explanation before they sound credible

### Replace With

- Realized return percentages
- Improvement velocity metrics
- Verification and reproducibility metrics
- Clear labels for "live", "experimental", "blocked", and "paper-mode-safe"
- A short explanation of why non-trading is the broader opportunity for Elastic

## Public Metric Policy For This Pitch

### Approved headline metrics

Use only metrics that are legible in one line.

Candidate headline set:

1. realized return percentage over a clearly defined window
2. live win rate only if the sample and source are explicit
3. validated backtest win rate only if labeled as historical validation, not live trading
4. improvement velocity:
   - cycles completed
   - tests passing
   - strategies evaluated or rejected
   - time-to-iteration improvements
5. non-trading implementation readiness:
   - wedge chosen
   - delivery path exists
   - approval-gated and paper-mode safe

### Forbidden headline metrics

- best-package forecast ARR
- raw selected BTC5 forecast ARR
- P05 ARR
- annualized continuation ARR
- wallet value
- free collateral
- deployable capital
- absolute bankroll

### Required labels

- `Live proof`
- `Historical validation`
- `Experimental forecast`
- `Blocked claim`
- `Paper mode default`

If a metric cannot be labeled cleanly, it should not be on the homepage or top of README.

## Target Story Architecture

The public narrative should be structured like this:

### Layer 1: What this is

Elastifund is an open-source, self-improving operating system for economic agents.

### Layer 2: Why Elastic matters

Elastic is the substrate for memory, evaluation, observability, and workflow control.
Without that substrate, the agents do not improve reliably.

### Layer 3: Why this matters beyond trading

Trading is the first proof lane because feedback is fast.
Non-trading is the broader platform opportunity because any employee can improve customer-facing economic workflows, not just market strategies.

### Layer 4: What is proven now

- a live proof lane exists
- a self-improvement loop exists
- a paper-mode contribution path exists
- a non-trading wedge exists and is moving toward launch

### Layer 5: How an Elastic employee can participate

- clone the repo
- run in paper mode
- inspect evidence
- improve one lane
- optionally join a shared paper-mode hub

## Recommended Surface Changes

## 1. Homepage (`/`)

### Goal

Make the first screen answer:

- What is Elastifund?
- Why should Elastic care?
- What is live today?
- Why is this more than trading?

### Required changes

- Replace the current trading-heavy hero with a platform-first hero.
- Move "Elastic is the system memory..." into the hero or immediate next section.
- Remove extreme ARR forecast numbers from all top-of-page stats.
- Replace dollar-denominated wallet or P&L stats with return percentages and improvement metrics.
- Add a simple three-lane frame:
  - trading proof
  - non-trading growth engine
  - Elastic evidence layer
- Add an explicit employee CTA:
  - "Clone in paper mode"
  - "See why Elastic matters"
  - "Inspect live proof"

### Acceptance criteria

- A first-time visitor can explain the product after reading only the hero and first two sections.
- The page no longer requires the user to understand BTC5 or ARR math to trust it.
- The words "trading" and "forecast" no longer overpower the platform story.

## 2. Elastic Route (`/elastic/`)

### Goal

Turn `/elastic/` into the cleanest employee-facing articulation of why this project belongs at Elastic.

### Required changes

- Lead with the company-wide thesis, not just the repo architecture.
- Add a section titled like "Why this is strategically bigger than trading."
- Make the non-trading opportunity explicit:
  - the same self-improvement substrate can power revenue operations, research, support, GTM, and workflow automation
- Add a contribution map by Elastic-relevant domain:
  - Search AI
  - memory / retrieval
  - observability / traces
  - evaluation
  - workflow automation
  - public publishing
- Keep the route paper-mode safe and explicit about checked-in artifacts only.

### Acceptance criteria

- An Elastic PM or engineer can see exactly where Elastic products fit.
- A non-technical employee can understand that the project is about self-improving economic agents, not "John's trading bot."

## 3. GitHub README

### Goal

Make the repo root credible, calm, and easy to route from.

### Required changes

- Rewrite the top third around the north-star message.
- Replace the current noisy operator snapshot with a cleaner "What to believe right now" section.
- Add a short "Why Elastic should care" section above the fold.
- Add a "Why non-trading is the bigger platform opportunity" section.
- Keep detailed runtime truth lower on the page or route it to `/live/`.
- Add a fast employee-friendly run path:
  - clone
  - prepare
  - paper mode
  - inspect artifacts
- Add a "What we are not claiming yet" box.

### Acceptance criteria

- The first screen on GitHub reads like a serious open-source system, not a private lab notebook.
- A leadership reader does not trip over wallet values, forecast inflation, or launch-state contradictions.

## 4. Public Metrics Contract

### Goal

Stop contradictory artifacts from leaking into public messaging.

### Required changes

- Choose one public truth precedence for homepage and README.
- Remove or demote raw annualized forecast figures from the public contract consumed by the site.
- Publish only sanitized metrics needed for the pitch.
- Keep operator truth and public truth separate, but not contradictory.

### Preferred policy

- Public site:
  - realized returns in percentage terms
  - improvement velocity
  - worker readiness
  - verification status
- Operator artifacts:
  - full internal diagnostics
  - runtime drift
  - detailed sleeve math
  - capital reconciliation

### Acceptance criteria

- No public page headline depends on a metric that needs a technical defense.
- `README.md`, `/`, and `/elastic/` agree on the same top-level claims.

## 5. Employee Onboarding And Infra Posture

### Goal

Make "clone and contribute" obviously safe.

### Policy recommendation

Do not invite employees to piggyback on your live trading infra or personal Lightsail instance.
That creates unnecessary trust, security, and narrative problems.

Instead:

1. Default path: local paper-mode clone
2. Optional shared path: a separate paper-mode demo hub
3. Never share live exchange keys, wallet credentials, or live treasury access

### Required changes

- Update onboarding copy so paper mode is the default story everywhere.
- Add a dedicated "Elastic employee quickstart" path that uses no trading credentials.
- Reuse the existing shared-hub pattern only for a sanitized paper-mode demo environment.
- Document exactly which secrets are optional and which are never required for contribution.

### Acceptance criteria

- An employee can boot the project without asking for private keys.
- The collaboration story does not depend on your personal live environment.

## 6. Leadership Demo And Presentation Assets

### Goal

Support a live presentation this week without improvising.

### Required deliverables

- A leadership-facing one-page brief
- A five-minute demo script
- A one-slide architecture view
- A "what is real vs experimental vs blocked" appendix
- A short FAQ for predictable objections:
  - Why trading first?
  - Why is non-trading more important long term?
  - Why Elastic instead of a pile of SaaS tools?
  - Why open source?
  - How can employees contribute safely?

## 7. Trust Test: Cold Clone Validation

### Goal

Prove that the repo is actually runnable by an outsider.

### Required test

Run a clean-room validation after the messaging pass:

1. clone A into a fresh directory
2. clone B into a second fresh directory
3. follow the public docs only
4. confirm both can boot in paper mode
5. if using a shared paper-mode hub, confirm both register cleanly
6. record every friction point

### Acceptance criteria

- No undocumented secrets are needed for paper-mode setup.
- Two independent copies can run side-by-side.
- The docs match reality closely enough that an LLM can follow them without private context.

## Ordered Execution Backlog

### P0: Message and metric lock

- [ ] Approve the north-star message
- [ ] Approve the list of forbidden metrics
- [ ] Decide the realized return methodology to disclose publicly
- [ ] Decide whether the 71.2% number survives as labeled historical validation or gets demoted
- [ ] Decide whether public surfaces show any dollar values at all

### P1: Public surface rewrite

- [ ] Rewrite homepage hero and top sections
- [ ] Rewrite `/elastic/` around Elastic relevance and non-trading upside
- [ ] Rewrite the top third of `README.md`
- [ ] Align titles, descriptions, CTA labels, and first-screen language

### P2: Artifact and metric cleanup

- [ ] Update the public JSON contract used by the site
- [ ] Remove extreme ARR headlines from site-generated copy
- [ ] Remove capital-scale disclosure from public routes
- [ ] Ensure labels are consistent across all public surfaces

### P3: Employee onboarding hardening

- [ ] Add or revise the employee quickstart path
- [ ] Document paper-mode shared-hub setup as the only hosted demo path
- [ ] Clarify secret requirements in `.env.example` and onboarding docs

### P4: Presentation packaging

- [ ] Create the leadership brief
- [ ] Create the demo script
- [ ] Create the FAQ / objections appendix

### P5: Cold-clone validation

- [ ] Run the two-clone setup test
- [ ] Fix documentation gaps discovered in the test
- [ ] Capture the final "safe for company-wide sharing" checklist

## Recommended Position On Specific Open Questions

### Should the extreme forecast numbers stay anywhere public?

No, not in the leadership pass.
They can survive in internal research artifacts, but not as public-facing headlines.

### Should the real trading size stay private?

Yes.
Public surfaces should emphasize return percentages, improvement velocity, and artifact-backed validation, not bankroll size.

### Should employees piggyback on your infrastructure?

Not on the live stack.
If a hosted path is useful, create a separate paper-mode demo hub with no live credentials and no treasury hooks.

### Should trading stay the main story?

No.
Trading should stay the proof lane.
The bigger story is the self-improving economic-agent substrate, especially the non-trading lane.

## Definition Of Done For This Readiness Pass

This pitch-readiness effort is done when:

1. the homepage is platform-first and credibility-safe
2. the Elastic route is company-relevant and non-trading-forward
3. the README is calm, clear, and leadership-appropriate
4. public metrics no longer leak confusing forecast math or capital scale
5. the paper-mode contribution path is obvious
6. a cold clone can run twice side-by-side without private help

