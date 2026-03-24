# Docs Index

Canonical docs root index for durable operator and contributor guidance.

- Type: canonical documentation lane.
- Route entrypoints:
  - `docs/README.md`: machine-first markdown index.
  - `docs/index.html`: public website docs route.
  - `docs/ROOT_SURFACE_MAP.md`: root file classification map (canonical/pointer/archive).

## Start Surfaces

- Start here: `docs/FORK_AND_RUN.md`
- Operator packet: `COMMAND_NODE.md`
- Active policy: `PROJECT_INSTRUCTIONS.md`
- Machine workflow guardrails: `AGENTS.md`
- Repo map and ownership boundaries: `docs/REPO_MAP.md`
- Root surface classification map: `docs/ROOT_SURFACE_MAP.md`

## Core Subdirectories

- `docs/ops/`: runbooks, operator checklists, runtime contracts.
- `docs/ops/historical/`: archived operational snapshots and migrated root handoff material.
- `docs/strategy/`: strategy design, lane-level architecture, background references.
- `docs/numbered/`: canonical governance and public-messaging manual (`00` through `12`).
- `docs/api/`: API surface and schema docs.
- `docs/adr/`: architecture decision records.
- `docs/launch/`: launch artifacts; historical material belongs in `docs/launch/historical/`.
- `docs/website/`: website build and publishing guidance.

## Root Surface Classification

The repo root should stay narrow. Current classifications:

- `README.md`: canonical onboarding surface.
- `COMMAND_NODE.md`: canonical operator handoff packet.
- `PROJECT_INSTRUCTIONS.md`: canonical policy/context.
- `AGENTS.md`: canonical machine workflow contract.
- `REPLIT_NEXT_BUILD.md`: canonical website build contract.
- `CODEX_DISPATCH.md`: historical snapshot (non-canonical reference only).
- `CODEX_MASTER_PLAN.md`: historical snapshot (non-canonical reference only).
- `DEPLOY_MAKER_VELOCITY.md`: cycle-specific deployment snapshot (historical/compatibility).
- `DEPLOY_NOW.md`: cycle-specific deployment snapshot (historical/compatibility).
- `FAST_TRADE_EDGE_ANALYSIS.md`: historical edge-analysis snapshot (historical/compatibility).

When adding new durable docs, prefer `docs/` or `research/` over new root files.
