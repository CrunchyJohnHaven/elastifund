# 11 Public Messaging
Version: 1.1.0
Date: 2026-03-10
Source: `COMMAND_NODE.md`, `research/elastic_vision_document.md`, `README.md`, `REPLIT_NEXT_BUILD.md`, `docs/ELASTIC_INTEGRATION.md`
Purpose: Define approved public framing, reusable copy blocks, audience guidance, and review rules for GitHub, the public site, and numbered docs.
Related docs: `00_MISSION_AND_PRINCIPLES.md`, `01_EXECUTIVE_SUMMARY.md`, `03_METRICS_AND_LEADERBOARDS.md`, `08_PROMPT_LIBRARY.md`, `12_MANAGED_SERVICE_BOUNDARY.md`

## Messaging Objective

Public messaging should make the repo legible in seconds.
Every primary surface should answer four questions quickly:

1. what this system is
2. why Elastic matters here
3. what is measurable now
4. how someone can inspect or contribute safely

Three routing rules stay fixed:

- `README.md` still leads with proof and current system status
- `/elastic/` is the dedicated Elastic-facing route
- public browser surfaces read sanitized checked-in artifacts only

## Core Message House

Keep the hierarchy consistent across `README.md`, `/`, `/live/`, `/elastic/`, and numbered docs:

1. what this is
2. why Elastic matters here
3. what is measurable now
4. how the system stays safe
5. how contributors can participate

If a surface cannot answer those five points cleanly, simplify it.

## Approved Framing

Use these phrases freely:

- self-improving
- policy-governed autonomy
- agentic work
- economic work
- Search AI
- system memory
- agent observability
- evaluation
- workflow automation
- evidence
- proof
- artifact-backed
- run in paper mode by default

Approved story:

- Elastifund is a self-improving, policy-governed operating system for real economic work.
- Elastic is the shared substrate for system memory, evaluation, observability, workflow automation, and publishing.
- Trading workers, JJ-N, and the finance control plane are separate operator surfaces that write into one evidence layer.
- Public routes and GitHub lead with proof labels, blocked claims, freshness labels, and source artifacts instead of broad manifesto copy.
- The public experience is paper-mode safe and artifact-backed by default.

## Elastic Employee Audience

Primary audience: Elastic employees first.  
Secondary audience: leadership, partners, and builders who need the same calm technical story.

The Elastic-facing story should answer these questions immediately:

- Why is Elastic a strong substrate for agentic AI?
- What is Elastic already doing inside this repo?
- How can an employee inspect or contribute without private data access?

### Approved Claims

- Elastic helps make prompts, traces, reports, dashboards, notes, and runtime artifacts searchable in one place.
- Elastic supports agent observability across logs, metrics, traces, costs, and operator dashboards.
- Elastic supports evaluation by keeping outcomes, scorecards, promotion decisions, and blocked-claim boundaries tied to evidence.
- Elastic supports workflow automation by giving recurring tasks, approvals, and publishing steps a shared memory and trace surface.
- Trading workers and JJ-N both feed the same Elastic-backed evidence layer even though their public proof boards remain separate.
- The public site and GitHub surfaces read sanitized checked-in artifacts; they do not depend on live browser access to private Elastic data.
- The safe contribution path is fork, run, inspect artifacts, and contribute in paper mode.

### Prohibited Overclaims

- Do not imply Elastic has endorsed, sponsored, or internally adopted this repo unless that is explicitly public and documented.
- Do not imply browser visitors are querying Elasticsearch, Kibana, or other private operator surfaces directly in this pass.
- Do not collapse trading proof, forecast surfaces, and JJ-N readiness into one blended success number.
- Do not describe Elastic as only a dashboard add-on. The approved story is broader: search, memory, observability, evaluation, workflow, and publishing.
- Do not imply policy rails, approval gates, or paper-mode defaults disappear for convenience.
- Do not use trading performance as proof that every worker lane is already production-ready.
- Do not turn `/elastic/` into a generic vendor pitch or a manifesto.

## Surface Contracts

### Homepage

Lead with:

- what the project is
- why it matters
- current proof
- how to run it

### GitHub README

Lead with:

- current status
- proof and blocked-claim labels
- a short "Why Elastic Matters Here" section in the top half
- architecture and run path
- contribution path

README must:

- keep ARR and trading proof labels intact
- keep fund-level blocked-claim language intact
- link to `/elastic/`
- link to `docs/ELASTIC_INTEGRATION.md`
- link to the repo run path

### Elastic Route

Lead with:

- why Search AI, memory, observability, evaluation, and workflow control matter for agents
- what Elastic already does inside Elastifund today
- what an Elastic employee can inspect or contribute
- why the route is paper-mode safe

`/elastic/` must:

- stay employee-facing first and leadership-compatible second
- show how trading and JJ-N meet in one evidence layer
- keep trading as one proof lane, not the whole story
- state that the route reads checked-in artifacts only

### Elastic Integration Guide

`docs/ELASTIC_INTEGRATION.md` is the master reference for the Elastic story.
It should connect architecture, operator setup, public-scope boundaries, and contribution guidance so `README.md` and `/elastic/` can point at one approved explanation.

## Reusable Copy Blocks

Use these short blocks where needed.

### Why Elastic Matters Here

`Elastic is the shared substrate for system memory, evaluation, observability, workflow automation, and publishing in Elastifund. Trading workers and JJ-N both write into the same evidence layer, so claims stay tied to searchable artifacts instead of drifting into prose.`

### Elastic Employee Relevance

`This repo is a public proof surface for why agentic AI needs more than a model. It needs context engineering, durable memory, observability, evaluation, and governed workflow control.`

### Public-Scope Guardrail

`Public browser surfaces read sanitized checked-in artifacts. They do not query private Elastic data directly in this pass.`

## Proof Rules

Pair every headline claim with evidence.

- Performance claims stay tied to the existing ARR, BTC5, and blocked-claim labels.
- Autonomy claims stay tied to policy, approval, and paper-mode context.
- Improvement claims stay tied to scorecards, tests, reports, or experiment logs.
- Public surfaces should report current system ARR and non-sensitive status counts, not wallet-level private data.
- If a visual is not backed by a checked-in export or checked-in artifact, label it as conceptual rather than live evidence.

## Tone And Style

Keep the public tone:

- calm
- technical
- specific
- paper-mode safe
- free of hype shortcuts

Good public messaging reads like an operator note with a clear point of view, not a fundraising memo and not a product brochure.

## Review Gate

Public-facing files should pass `python3 scripts/lint_messaging.py`.
The lint is intentionally narrow.
It blocks a small set of obviously unsafe phrases so the repo does not drift back into autonomy theater.

## Lint Scope

The automated lint targets the canonical public entry surfaces:

- `README.md`
- the repo homepage and public route HTML
- `docs/numbered/*.md`

Historical research notes and operator-facing docs are reviewed manually.
That keeps the lint deterministic on the current public story without forcing archival prose to match homepage copy.

Last verified: 2026-03-10 against `README.md`, `REPLIT_NEXT_BUILD.md`, and `docs/ELASTIC_INTEGRATION.md`.
Next review: 2026-06-10.
