# Ops Docs Index

Status: canonical index  
Last updated: 2026-03-11  
Scope: `docs/ops/` only

## Naming Convention

- Canonical runbooks and checklists: keep stable, descriptive names.
- New docs should use lowercase `snake_case`.
- Existing mixed-case legacy filenames remain in place when they are already widely referenced or when case-only rename compatibility is unsafe on case-insensitive filesystems.
- Historical one-off plans and briefings belong under `docs/ops/_archive/`.

## Rename Debt

- Case-only conversions like `TRADING_LAUNCH_CHECKLIST.md` -> `trading_launch_checklist.md` are deferred to a dedicated convergence pass that can update all references in one coordinated change.

## Taxonomy

| File | Classification | Canonical status | Notes |
|---|---|---|---|
| `finance_control_plane.md` | canonical runbook | canonical | Treasury/control-plane policy contract. |
| `cross_asset_lane.md` | canonical runbook | canonical | Cross-asset rollout contract and artifact mapping. |
| `runtime_profile_contract.md` | canonical runbook | canonical | Runtime profile selector and launch gating contract. |
| `hft_refactor_blueprint.md` | active plan | canonical | Active phased refactor plan tied to machine artifact contract. |
| `high_frequency_substrate_task_manifest_20260311.md` | active plan | canonical | File-level backlog + acceptance gates for current HFT phase. |
| `TRADING_LAUNCH_CHECKLIST.md` | checklist | canonical | Launch posture checklist; commentary only. |
| `OPEN_SOURCE_CHECKLIST.md` | checklist | canonical | Publication/hygiene checklist tied to repo hygiene gate. |
| `REVENUE_AUDIT_FULFILLMENT_RUNBOOK.md` | canonical runbook | canonical | Paid-order fulfillment flow for Website Growth Audit. |
| `ELASTIC_HUB_BOOTSTRAP.md` | canonical runbook | canonical | Elastic control-plane bootstrap procedure. |
| `Flywheel_Control_Plane.md` | canonical runbook | canonical | Flywheel policy, promotion boundaries, and control-plane interfaces. |
| `Flywheel_Incentive_System.md` | canonical runbook | canonical | Incentive layer specification for flywheel collaboration. |
| `Flywheel_Improvement_Exchange.md` | canonical runbook | canonical | Cross-fork improvement exchange contract. |
| `llm_context_manifest.md` | canonical index | canonical | LLM context-package naming and canonical context surfaces. |
| `CODEX_PLANNING_PROMPT.md` | checklist | canonical | Reusable planning prompt template for path-isolated dispatches. |
| `replit_share_manifest_20260311.md` | checklist | canonical | Replit handoff manifest with stable outward naming labels. |
| `dispatch_instructions.md` | historical briefing | non-canonical | Preserved for provenance; do not use as current operator source. |
| `high_frequency_refactor_revision_log_20260311.md` | historical briefing | non-canonical | Point-in-time implementation log for 2026-03-11 pass. |
| `REMOTE_DEV_CYCLE_STANDARD.md` | canonical runbook | canonical | Local scheduler + remote AWS cycle standard. |

## Ops Doc Template

Use this header for new docs under `docs/ops/`:

```md
# <Title>

Status: <canonical runbook|active plan|historical briefing|checklist|canonical index>
Last updated: YYYY-MM-DD
Category: <same as status category>
Canonical: <yes|no>
Purpose: <one line>
```

Rules:

- Canonical docs use `Canonical: yes`.
- Historical snapshots use `Canonical: no` and should move to `_archive/` once superseded.
- Keep one primary purpose per file.

## Archive

Historical and superseded one-off plans, handoffs, and deployment packets are kept in [`docs/ops/_archive/`](./_archive/README.md).
