# Ops Archive Manifest

Status: archive manifest
Last updated: 2026-03-11
Purpose: classify archived `docs/ops` files by reason tag and replacement surface.

## Reason Tags

- `superseded_plan`: replaced by canonical runbook/plan elsewhere.
- `one_off_handoff`: single-session execution packet or handoff context.
- `historical_snapshot`: time-bound briefing/checklist preserved for provenance.

## Archive Inventory

| File | Reason tag | Replacement/canonical surface |
|---|---|---|
| `AUDIT_REPORT.md` | historical_snapshot | None; provenance only |
| `AUTORESEARCH_INTEGRATION_PLAN.docx` | one_off_handoff | None; provenance only |
| `CLAUDE_CODE_HANDOFF.md` | one_off_handoff | `COMMAND_NODE.md` + `PROJECT_INSTRUCTIONS.md` |
| `CONTRIBUTING.md` | historical_snapshot | Root `CONTRIBUTING.md` |
| `Checklist.md` | historical_snapshot | `TRADING_LAUNCH_CHECKLIST.md` |
| `Flywheel_Execution_Plan.md` | superseded_plan | `Flywheel_Control_Plane.md` |
| `JJ_CONTEXT.md` | one_off_handoff | `COMMAND_NODE.md` + `PROJECT_INSTRUCTIONS.md` |
| `JJ_DEPLOY.md` | historical_snapshot | `REMOTE_DEV_CYCLE_STANDARD.md` |
| `JJ_RESOURCE_INVENTORY.md` | historical_snapshot | `finance_control_plane.md` |
| `JJ_SYSTEM_v1.0.md` | historical_snapshot | `COMMAND_NODE.md` |
| `MAKER_VELOCITY_BLITZ_PLAYBOOK.md` | superseded_plan | `hft_refactor_blueprint.md` |
| `MIGRATION_BRIEFING.md` | historical_snapshot | `REMOTE_DEV_CYCLE_STANDARD.md` |
| `REVENUE_AUDIT_EXECUTION_PLAN.md` | superseded_plan | `REVENUE_AUDIT_FULFILLMENT_RUNBOOK.md` |
| `Report_Generation_Checklist.md` | historical_snapshot | None; provenance only |
| `deploy_now.md` | historical_snapshot | `REMOTE_DEV_CYCLE_STANDARD.md` |
| `elastic_leadership_pitch_readiness_plan_20260311.md` | one_off_handoff | Root entrypoint docs (`README.md`, `COMMAND_NODE.md`) |
| `parallel_task_manifest.md` | one_off_handoff | `CODEX_PLANNING_PROMPT.md` |
| `replit-homepage-vision-brief-2026-03-08.md` | historical_snapshot | `docs/website/` current docs |
| `website-updates.md` | historical_snapshot | `docs/website/` current docs |
