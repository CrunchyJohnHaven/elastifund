# 09 Governance And Safety
Version: 1.0.0
Date: 2026-03-09
Source: `CLAUDE.md`, `COMMAND_NODE.md`, `research/elastic_vision_document.md`, `research/platform_vision_document.md`, `PROJECT_INSTRUCTIONS.md`
Purpose: Define autonomy levels, approvals, security boundaries, compliance rules, and incident policy.
Related docs: `00_MISSION_AND_PRINCIPLES.md`, `04_TRADING_WORKERS.md`, `05_NON_TRADING_WORKERS.md`, `10_OPERATIONS_RUNBOOK.md`, `12_MANAGED_SERVICE_BOUNDARY.md`

## Governance Principle

Elastifund uses policy-governed autonomy.
The system is allowed to act quickly inside defined boundaries.
It is not allowed to redefine those boundaries silently.

## Escalation Rules

Human escalation is required for:

- spending real money
- changing risk parameters
- architectural decisions with no clear best option
- unresolved legal or compliance questions
- failures that remain blocked after normal debugging

Everything else should bias toward execution and evidence generation.

## Autonomy Levels

| Level | Description | Examples |
|---|---|---|
| Level 0 | Observe only | read data, summarize state, no outward action |
| Level 1 | Simulate and draft | paper trading, draft outreach, prepare proposals |
| Level 2 | Execute low-risk actions with policy | queue approved sequences, run tests, publish artifacts |
| Level 3 | Supervised real-world execution | limited live routing or approved outbound actions |
| Level 4 | Strategic changes | risk changes, capital deployment changes, compliance shifts; human approval required |

Most of the repo should live in Levels 0 through 2 by default.

## Safety Boundaries For Trading

- paper mode by default
- explicit caps on size and loss
- maker-first execution on fee-bearing markets
- kill-switch support
- launch blocked until evidence gates clear
- live, paper, and forecast results kept separate

## Safety Boundaries For JJ-N

- authenticated sending only
- clear sender identity
- unsubscribe and suppression handling
- no autonomous pricing commitments in v1
- no autonomous contract execution
- no domain or deliverability changes without approval
- no budget or ad-spend changes without approval

## Secrets And Private Material

Open-source guardrails are explicit.
Architecture, methodology, code structure, tests, and failure logs stay public.
Secrets stay in `.env` and ignored paths.
That includes API keys, wallet credentials, signing secrets, and live-edge sensitive parameters.

## Merge And Change Control

The repo should not accept high-risk changes without evidence.
At minimum:

- run the narrowest relevant test target
- keep file ownership explicit in parallel sessions
- avoid simultaneous edits in the same path
- require review or explicit sign-off for sensitive runtime or policy changes
- record runtime-affecting changes in canonical docs or artifacts

## Incident Policy

An incident includes any of the following:

- unexpected live-money execution
- kill-rule breach
- runtime mode confusion
- secrets exposure
- unsafe outbound behavior
- persistent divergence between docs and runtime truth

Incident response should follow this order:

1. stop unsafe execution
2. capture state and logs
3. identify the active artifact sources
4. restore a known safe posture
5. update the evidence trail

## Compliance Notes

The repo should avoid language or behavior that implies:

- absent oversight
- guaranteed returns
- deceptive commercial messaging
- regulated activity without proper controls

For non-trading work, sender identity, unsubscribe handling, and approval policy are core product rules.
For trading work, risk controls and launch gates are core product rules.

## Documentation Rule

If the runtime truth changes, the safety story must change with it.
If the docs say a service is running but the latest synced artifact says it is stopped, the docs are wrong until updated.
Governance includes narrative discipline.

Last verified: 2026-03-09 against `CLAUDE.md`, `PROJECT_INSTRUCTIONS.md`, and `reports/runtime_truth_latest.json`.
Next review: 2026-06-09.
