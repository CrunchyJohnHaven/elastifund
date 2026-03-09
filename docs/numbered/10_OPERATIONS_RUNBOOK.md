# 10 Operations Runbook
Version: 1.0.0
Date: 2026-03-09
Source: `README.md`, `docs/FORK_AND_RUN.md`, `CONTRIBUTING.md`, `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, `reports/runtime_truth_latest.json`
Purpose: Document how to boot, inspect, verify, and recover the system without losing operational clarity.
Related docs: `02_ARCHITECTURE.md`, `04_TRADING_WORKERS.md`, `07_FORECASTS_AND_CHECKPOINTS.md`, `09_GOVERNANCE_AND_SAFETY.md`

## First Rule

Prefer machine truth over memory.
Before acting on runtime posture, read the current artifacts.
Before changing a service, know whether it is running, stopped, or drifting.

## Canonical Truth Sources

Inspect these first:

- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/remote_cycle_status.json`
- `reports/remote_service_status.json`
- `reports/root_test_status.json`
- `research/edge_backlog_ranked.md`

These files should beat stale prose every time.

## Local Boot Paths

For a fresh repo boot, the simplest path is:

```bash
python3 scripts/doctor.py
python3 scripts/quickstart.py
```

For a prepare-only path:

```bash
python3 scripts/quickstart.py --prepare-only
```

For fuller developer verification:

```bash
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
make verify
```

## Standard Verification Commands

Run the narrowest relevant target first, then broaden as needed:

```bash
make hygiene
make test
make test-polymarket
make test-nontrading
make smoke-nontrading
```

## March 9, 2026 Runtime Posture

The current synced runtime truth is:

- `jj-live.service` is `stopped`
- cycles completed: `314`
- total trades: `0`
- launch posture: `blocked`
- wallet-flow: `ready`
- root verification: `956 passed in 18.77s; 22 passed in 3.69s`

That means the next operator action is still to resume `jj_live` in paper or shadow with conservative caps and collect evidence, not to claim launch is live.

## Deployment Checklist

Before any deploy or restart:

1. read the current runtime truth artifacts
2. confirm current service status
3. confirm risk and launch posture
4. confirm the relevant tests are green
5. confirm runtime profiles and deploy manifests agree

If any of those checks fail, do not treat the deploy as routine.

## Recovery Checklist

When something looks wrong:

1. stop or pause unsafe execution first
2. capture logs and current artifact snapshots
3. compare `runtime_truth_latest.json` to `remote_service_status.json`
4. rerun the narrowest verification command that matches the suspected failure
5. update the evidence docs if the truth changed

## Remote Runtime Notes

The active host remains the Dublin VPS.
Service mode and launch posture should be validated from synced artifacts, not assumed from older notes.
A running service while launch is blocked counts as drift.
A stopped service while launch is blocked may be the intended safe posture.

## Documentation Maintenance

Operations changes are not complete until the relevant operator docs and artifacts agree.
If a command path, startup flow, or runtime truth source changes, update the docs that point people into the system.

## Minimum Handoff Contract

Every meaningful operations pass should leave behind:

- files changed
- commands run
- what was verified
- what remains unverified
- whether the next agent can safely edit the same path

Last verified: 2026-03-09 against `docs/FORK_AND_RUN.md`, `CONTRIBUTING.md`, and `reports/runtime_truth_latest.json`.
Next review: 2026-06-09.
