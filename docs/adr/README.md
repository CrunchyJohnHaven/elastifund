# Architecture Decision Records (ADR)

- Status: Active index
- Last reviewed: 2026-03-11
- Scope: durable architecture decisions that affect risk boundaries, topology, and governance

## Current State (30 seconds)

ADRs `0001` through `0005` are the current decision set for this lane.
Each file is canonical in-place and uses the same metadata keys: `Status` and `Date`.

## ADR Index

| ADR | Status | Decision |
|---|---|---|
| `0001` | Accepted | Separate live execution from research and control-plane automation |
| `0002` | Accepted | Keep evidence-first reporting and a strict public/private data boundary |
| `0003` | Accepted | Pursue a dual-lane revenue architecture with shared allocation and risk rails |
| `0004` | Proposed | Use Elastic Stack as the shared knowledge and observability backbone |
| `0005` | Accepted | Make the first production non-trading engine a self-serve website audit and monitor |

## Classification Rules

- `Accepted`: active architectural constraint.
- `Proposed`: candidate decision awaiting full operational adoption.
- `Superseded`: historical ADR retained only for traceability (none currently).

## When To Add A New ADR

Add an ADR when a change alters one of:

- capital-risk boundaries
- package/service responsibilities
- public/private data boundaries
- observability or storage architecture
- contributor-facing governance rules

Implementation details and one-off experiments belong in ordinary design or research docs.

## Naming Convention

- Format: `NNNN-short-kebab-case-title.md`
- Keep ADR numbers immutable after merge.
