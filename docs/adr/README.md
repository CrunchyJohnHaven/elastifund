# Architecture Decision Records

This directory captures the major architectural decisions behind the current Elastifund repo and the next-stage Elastifund.io buildout.

## Index

| ADR | Status | Decision |
|---|---|---|
| `0001` | Accepted | Separate live execution from research and control-plane automation |
| `0002` | Accepted | Keep evidence-first reporting and a strict public/private data boundary |
| `0003` | Accepted | Pursue a dual-lane revenue architecture with shared allocation and risk rails |
| `0004` | Proposed | Use Elastic Stack as the shared knowledge and observability backbone |
| `0005` | Accepted | Make the first production non-trading engine a self-serve website audit and monitor |

## When To Write An ADR

An ADR belongs here when it changes one of:

- capital risk boundaries
- system topology
- public/private data boundaries
- observability or storage architecture
- contributor-facing governance rules

Implementation details and one-off experiments belong in ordinary design docs or research notes instead.

## Suggested Workflow

1. State the decision.
2. Record the alternatives you rejected.
3. Be explicit about consequences and tradeoffs.
4. Link the ADR from the implementation PR or rollout doc that depends on it.
