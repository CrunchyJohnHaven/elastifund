# 11 Public Messaging
Version: 1.0.0
Date: 2026-03-09
Source: `COMMAND_NODE.md`, `research/elastic_vision_document.md`, `research/platform_vision_document.md`, `README.md`
Purpose: Define approved public framing, reusable copy blocks, and messaging review rules.
Related docs: `00_MISSION_AND_PRINCIPLES.md`, `01_EXECUTIVE_SUMMARY.md`, `03_METRICS_AND_LEADERBOARDS.md`, `08_PROMPT_LIBRARY.md`, `12_MANAGED_SERVICE_BOUNDARY.md`

## Messaging Objective

Public messaging should make the project legible in seconds.
It should explain what the system is, why it exists, why Elastic matters, and how someone can contribute.
It should not rely on hype or imply that governance is optional.

## Approved Framing

Use these phrases freely:

- self-improving
- policy-governed autonomy
- agentic work
- economic work
- evidence
- benchmarks
- run in paper mode by default

These phrases match the repo's actual operating model.

## Framing To Avoid

Avoid language that implies:

- absent human oversight
- unbounded autonomy
- automatic profit
- governance-free operation
- hidden risk boundaries

If the language would make an operator, contributor, or executive think the system acts outside policy, rewrite it.

## Canonical Hero Copy

Homepage hero:
`A self-improving agentic operating system for real economic work.`

Homepage subhead:
`Elastifund turns research, experiments, and execution into searchable evidence so trading and non-trading agents can improve with every run.`

Elastic page hero:
`Open-source agents need a system memory. Elastic is the Search AI platform that makes them reliable.`

## Audience-Specific Message Blocks

### Homepage

Lead with:

- what the project is
- why it matters
- current evidence
- how to run it

### GitHub README

Lead with:

- current status
- quick boot path
- architecture
- metrics and evidence
- contribution path

### Elastic Audience

Lead with:

- why Search AI, memory, and observability matter for agents
- why this repo is a useful public reference architecture
- why the project is safe by default
- how employees can participate in paper mode

### Contributor Onboarding

Lead with:

- one-command path
- default paper mode
- where truth lives
- what kinds of contributions are welcome

## Message House

The message hierarchy should stay consistent:

1. what this is
2. why it exists
3. what is measurable
4. how it improves
5. how it stays safe
6. how to contribute

## Proof Rules

Pair headline claims with evidence.
If a message mentions performance, pair it with source artifacts and labels.
If a message mentions autonomy, pair it with policy and approval context.
If a message mentions improvement, pair it with scorecards, tests, or diary evidence.
Public surfaces should report current system ARR and non-sensitive status counts, not portfolio balances or account-by-account wallet disclosures.

## Review Gate

Public-facing files should pass `scripts/lint_messaging.py`.
The lint is intentionally narrow.
It blocks obviously unsafe or misleading phrasing so the repo does not drift back into hype.

## Lint Scope

The automated lint targets the canonical public entry surfaces:

- `README.md`
- the repo homepage and public route-stub HTML
- `docs/numbered/*.md`

Historical diary entries and operator-facing docs are reviewed manually.
That keeps the lint deterministic on the current public story without forcing archival prose to follow homepage copy rules.

Last verified: 2026-03-09 against `COMMAND_NODE.md`, `research/elastic_vision_document.md`, and `README.md`.
Next review: 2026-06-09.
