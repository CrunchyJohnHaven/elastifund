# Remote Dev Cycle Standard

Status: canonical runbook
Last updated: 2026-03-11
Category: canonical runbook
Canonical: yes
Previous status: active (2026-03-08)

## Purpose

This standard defines how local scheduled Claude Code tasks work against the AWS trading instance.

Every unattended run must close the loop:

`Pull -> Store -> Research -> System Update -> Deploy -> Validate`

A stage may end as `completed`, `skipped`, or `blocked`, but it may not be silently omitted.

## Scope

This applies to Mac-side automation and scheduled tasks that:

- pull runtime state from the AWS instance
- store it locally for analysis
- run the local flywheel or equivalent research pass
- patch the repo when evidence supports a change
- deploy a safe delta back to the instance
- validate the remote runtime after deployment

## Hard Rules

1. Pull before doing analysis, code generation, or deployment.
2. Never treat the AWS instance as a git checkout. The live bot directory is not a git repo today.
3. Never use unattended full-repo mirror pushes that rely on `rsync --delete` while the remote tree is not an audited mirror of the local tree.
4. Deploy only the narrowest validated delta.
5. Every run must refresh the compact status artifact:
   - `reports/remote_cycle_status.md`
   - `reports/remote_cycle_status.json`
6. Every run must leave behind enough evidence for the next agent to answer:
   - what changed
   - what was deployed
   - what was validated
   - what still blocks full deployment of capital

## Push/Pull Flow

The local machine is the control point. The AWS instance is the remote execution target.

Canonical direction of travel:

1. AWS instance -> local repo for runtime data and state
2. local repo -> AWS instance only for validated code or config deltas
3. AWS instance -> local repo again for post-deploy validation state

This is not a symmetric git workflow.

Current remote facts:

- the bot directory on AWS is reachable over SSH
- the remote bot directory is not a git checkout
- remote updates happen through `ssh`, `scp`, and `rsync`

That means `pull` and `push` must be documented as artifact sync operations, not as `git pull` / `git push` on the instance.

## Cycle Contract

### 1. Pull

Required outcome:

- latest runtime artifacts copied from AWS to the local repo

Approved path:

- `scripts/bridge.sh --pull-only`

Required pulled artifacts:

- `jj_state.json`
- `data/*.db`
- `data/*.json`
- `logs/*`
- the latest flywheel artifacts if they already exist locally

Pull failure means the cycle stops and records `blocked`.

## Cadence

### Default Cadence

- Pull remote data every `30` minutes.
- Run a full development cycle every `60` minutes.
- Refresh the compact remote-cycle status report on every cycle, even when no code changes occur.

### Mandatory Extra Pulls

- immediately before any deploy
- immediately after any deploy
- immediately after any service restart
- immediately after any runtime incident or kill event
- before publishing any daily, investor, or operator summary

### Faster-Than-Default Cadence

Do not make a faster unattended cadence the default.

Use a temporary manual cadence of `5-10` minutes only when:

- debugging a live incident
- confirming a remote restart
- validating a newly deployed fast-market path

### When We Expect The Next Data

Operationally, the next synced dataset should arrive on the next `30` minute pull.

Decision-grade data is a different question:

- if the runtime is active but no trades close, expect more scan and telemetry data but not better calibration evidence
- if the runtime is paused, the next material dataset is effectively blocked
- if a live or shadow sleeve resumes, the next material dataset is the first pull after new closed trades or structural-alpha samples appear

### 2. Store

Required outcome:

- pulled artifacts persist under repo-owned runtime paths
- local state is timestamped and reportable

Required paths:

- `data/`
- `logs/`
- `reports/`

Required report refresh:

- `python3 scripts/write_remote_cycle_status.py`

The status report is the compact answer to:

- how much capital is tracked
- how much capital is deployed right now
- when the next pull should happen
- whether the current data is stale
- what the latest flywheel decision says
- what blocks finishing deployment
- what our current best-guess velocity is

### 3. Research

Required outcome:

- one evidence-based review of the latest pulled state

Approved path:

- local flywheel run from pulled data via `scripts/run_flywheel_cycle.py`
- existing daily review/report flows when a material change occurred

Minimum artifact contract:

- `reports/flywheel/latest_sync.json`
- latest flywheel `summary.md`
- latest flywheel `scorecard.json`

Research must end with one of:

- `no_change`
- `local_patch_required`
- `deploy_candidate`
- `blocked`

### 4. System Update

Required outcome:

- smallest justified repo change based on the current evidence

Rules:

- no speculative repo-wide cleanup
- no silent risk-parameter changes
- no edits in live-trading-sensitive paths without narrow verification
- if no change is justified, record `skipped` and keep the evidence

Minimum local verification before deploy:

- narrowest relevant tests first
- `make hygiene` when docs, config, or workflow surfaces change

### 5. Deploy

Required outcome:

- either a safe deployment or an explicit `no deploy this cycle` decision

Approved unattended deploy paths:

- `scripts/deploy.sh`
- `scripts/deploy_ws.sh`
- narrower allowlisted `scp` or `ssh` steps tied to the touched files

Disallowed unattended deploy path:

- `scripts/bridge.sh` default push path while it still uses destructive `rsync --delete`

Deploy gate:

- latest pull succeeded
- local verification passed
- the change is actually required by the research output

If nothing changed locally, the deploy stage still records `skipped`.

### 6. Validate

Required outcome:

- confirmation that the remote runtime is in the expected state after the deploy decision

Minimum remote checks:

- remote directory still reachable over SSH
- `systemctl is-active jj-live.service`
- relevant import or startup check if bot code changed
- relevant WebSocket service check if infra or ws files changed

If deploy was skipped, validate the existing runtime state and record whether it remains:

- healthy
- intentionally stopped
- degraded

## Artifact Standard

Every completed cycle must leave behind:

- `reports/flywheel/latest_sync.json`
- `reports/remote_cycle_status.md`
- `reports/remote_cycle_status.json`

Optional when material findings exist:

- `reports/daily/YYYY-MM-DD.md`

## Capital And Deployment Tracking

`config/remote_cycle_status.json` is the tracked operator file for:

- non-VM capital balances such as Kalshi
- deployment ETA or `TBD`
- current blockers
- exit criteria for "deployment finished"

`jj_state.json` overrides the Polymarket runtime balance in the generated report when present.

Every cycle must answer these four questions in the status artifact:

1. How much capital is tracked across accounts?
2. How much capital is deployed right now?
3. What is the latest control-plane decision?
4. When do we expect deployment to finish, or why is the ETA still `TBD`?

## Velocity Forecast

The remote-cycle status report also carries a forward-looking velocity forecast.

Definition:

- `annualized_return_run_rate_pct`
- this means a best-guess annualized return run-rate on tracked capital
- this is not realized performance and not a public claim

Use it to answer:

- are we still effectively at `0%` run-rate?
- what is the next plausible run-rate target if current blockers are removed?
- how many more focused engineering hours do we think it will take?

This forecast must include:

- current run-rate percent
- next target run-rate percent
- estimated engineering hours to that target
- confidence
- assumptions
- invalidators

If the forecast is mostly intuition rather than evidence, label it `speculative` and keep confidence low.

## Current Deployment Finish Definition

As of 2026-03-08, "deployment finished" does not mean 100% of dollars are forced live.
It means the current strategy sleeve can be considered operational because:

- the runtime is back on
- structural alpha gates are no longer blocking promotion
- at least one live or shadow sleeve is collecting real calibration data
- the report can explain why undeployed capital still remains idle

## Recommended Prompt Contract For Scheduled Claude Runs

The scheduled task should be instructed to:

1. pull the latest AWS state
2. refresh the compact remote-cycle report
3. run the local flywheel evaluation
4. make only the smallest justified repo change
5. verify locally
6. deploy only through an approved safe path
7. validate the remote runtime
8. refresh the compact remote-cycle report again before finishing

That keeps each run grounded in fresh data instead of drifting into untethered local development.
