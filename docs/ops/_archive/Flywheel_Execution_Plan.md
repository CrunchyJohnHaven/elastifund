# Flywheel Execution Plan

**Status:** active
**Last Updated:** 2026-03-07

## Goal

Build a control-plane MVP that makes the repo operate more like an autonomous trading company:

- a persistent strategy registry
- deployment tracking by environment
- promotion and kill decisions based on explicit metrics
- generated task queues after every cycle
- report artifacts that downstream automations can consume

## Sequential Work Order

### Phase 1: Contracts And Data

1. Add the flywheel control-plane schema to the synchronous data layer.
2. Add CRUD helpers for strategy versions, deployments, daily snapshots, and promotion decisions.
3. Extend the CLI so the control plane can be initialized and inspected.

### Phase 2: Policy And Orchestration

4. Implement a promotion policy engine with clear reason codes.
5. Implement a scorecard builder that summarizes environment health and strategy readiness.
6. Implement a cycle runner that:
   - reads input payloads
   - writes daily snapshots
   - evaluates promotions
   - writes task lists
   - writes JSON and markdown artifacts

### Phase 3: Validation

7. Add tests for schema creation and CRUD behavior.
8. Add tests for promotion policy decisions.
9. Add an end-to-end cycle test that proves the sequential flywheel works.

## Deliverables

- new control-plane tables
- new CRUD helpers
- live-bot SQLite bridge into flywheel payloads
- peer bulletin export/import for cross-fork discovery sharing
- new cycle runner
- new CLI commands
- generated artifacts under `reports/flywheel/`
- tests passing

## Deferred Items

These are intentionally out of MVP scope:

- direct live-bot mutation from code agents
- automatic PR creation
- automatic `core_live` promotion
- replacing the live bot database with the control-plane store
- external schedulers or hosted workflow engines

The MVP should be strong enough that any scheduler, automation, or agent can call one deterministic cycle command and receive reliable state plus artifacts.
