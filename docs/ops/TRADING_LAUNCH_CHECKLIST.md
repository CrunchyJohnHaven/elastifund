# Trading Launch Checklist

This document is commentary-only. It must not override machine truth.
Any prose snapshots in this file are historical context only.

## Canonical Launch Contract

Use this source order only:

1. `reports/launch_packet_latest.json` (canonical launch verdict and mandatory output contract)
2. `reports/runtime_truth_latest.json`
3. `reports/remote_cycle_status.json`
4. `reports/remote_service_status.json`

If prose disagrees with those artifacts, prose is stale by definition.
Launch posture authority lives in `reports/launch_packet_latest.json` only.

## Launch-State Bundle Requirement

Every launch packet must include a single normalized launch-state bundle with:

- `service.state`
- `storage.state`
- `package_load.state`
- `stage.allowed_stage_label`

Do not split these across multiple operator sources for decision-making.

## Required Refresh

Run from repo root before any launch decision:

```bash
python3 scripts/write_remote_cycle_status.py
```

Then read:

- `reports/launch_packet_latest.json`
- `reports/runtime_truth_latest.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`

## Drift-Kill Gate

The cycle is an automatic fail when any launch-contract check fails:

- service state vs launch posture disagreement
- mode alignment disagreement (`agent_run_mode` vs `execution_mode`)
- posture vs order-submission disagreement
- order-submission enabled while `allow_order_submission=false`

When triggered, `launch_packet_latest.json` must report:

- `launch_verdict.posture="blocked"`
- `launch_verdict.drift_kill_gate_triggered=true`
- `mandatory_outputs.one_next_cycle_action` with a concrete repair step

If storage is blocked or remote runtime validation is incomplete, the next action must be
`hold_repair` with a `+10m` retry window.

## Blocker Taxonomy

Blockers are typed only as:

- `truth`
- `candidate`
- `confirmation`
- `capital`

No untyped generic hold is allowed. If blocked, the packet must include
`mandatory_outputs.block_reasons` and a repair action.

## Mandatory Output Contract

Every cycle packet must include:

- `candidate_delta_arr_bps`
- `expected_improvement_velocity_delta`
- `arr_confidence_score`
- `block_reasons`
- `finance_gate_pass`
- `one_next_cycle_action`

## Post-Upgrade Docs/Public Sync Contract

README and website/runtime copy are refreshable only after one clean post-upgrade artifact cycle.

Required refresh artifacts from the same cycle:

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/launch_packet_latest.json`

If any are missing, stale, or contradictory:

- emit `hold_repair`
- set retry timing to `+30m` for docs/public sync
- keep public copy in `upgrade_blocked` posture

When JJ-N status is referenced in launch/public docs, split status explicitly:

- `manual_close_now` (from `reports/nontrading_launch_summary.json`)
- `automated_checkout_after_upgrade` (requires `PUBLIC_BASE_URL`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`)

Do not publish copy that collapses those two states into one generic "blocked" label.

## Canonical Deep-Research Bundle

Every operator dispatch packet must include this fixed five-file paste-target bundle:

1. `research/deep_research_prompt.md`
2. `research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md`
3. `research/dispatches/DISPATCH_076_CLAUDE_DEEP_RESEARCH_100_strategies.md`
4. `research/dispatches/P0_69_chatgpt54_master_prompt_optimization_CHATGPT54.md`
5. `research/dispatches/P0_77_hft_binary_options_chainlink_barrier_GEMINI_DEEP_RESEARCH.md`

## Stage Discipline

Stage order remains fixed:

1. `paper`
2. `shadow`
3. `micro-live`
4. `live`

Do not skip stages. A `clear` launch posture is necessary but not sufficient for live promotion.
