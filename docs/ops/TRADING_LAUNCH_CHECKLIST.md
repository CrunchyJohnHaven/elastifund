# Trading Launch Checklist

**Status date:** March 9, 2026

This is the operator checklist for moving `jj_live` from research posture into a staged trading rollout.

Related execution package:
- `docs/ops/MAKER_VELOCITY_BLITZ_PLAYBOOK.md` for the single-lane maker-velocity full-capital runbook and machine contracts.

Machine-truth reconciliation:

- The March 8 prose that said the service was intentionally stopped is no longer the authoritative service-state fact.
- `reports/remote_service_status.json` shows `jj-live.service` `running` at `2026-03-09T00:06:56Z`.
- `reports/remote_cycle_status.json` still marks launch `blocked`, wallet-flow `not_ready`, and the next action as paper/shadow-only after wallet-flow bootstrap.
- Treat the running service as drift requiring follow-up, not as launch approval.

Current repo truth:

- Tracked capital: `$347.51`
- Deployed capital: `$0.00`
- Runtime cycles completed: `294`
- Total trades: `0`
- Open positions: `0`
- Remote service state: `running` at `2026-03-09T00:06:56Z`
- Latest flywheel decision: `hold`
- Wallet-flow readiness: `not_ready` (`missing_data/smart_wallets.json`, `missing_data/wallet_scores.db`, `no_scored_wallets`)
- Latest fast-market pipeline verdict: checked-in artifact still `REJECT ALL`
- Structural-alpha promotion status: blocked (`0` March 9 A-6 executable opportunities below `0.95`; `0` March 9 B-1 deterministic template pairs in the first `1,000` allowed markets)
- Local verification baseline: `make hygiene` passed; root suite `849 + 22`; `make test-polymarket` `374`; `make test-nontrading` `11`
- Current live-launch posture: `blocked`

## Conservative Caps

Keep these caps unchanged through this pass:

- `JJ_MAX_POSITION_USD=5`
- `JJ_MAX_DAILY_LOSS_USD=5`
- `JJ_MAX_OPEN_POSITIONS=5`
- `JJ_KELLY_FRACTION=0.25`
- `JJ_INITIAL_BANKROLL=247`
- A-6 and B-1 per-leg cap: `$5`

Do not widen risk during this checklist.

## Hard Preconditions

Before any runtime restart:

- Pull remote state first with `./scripts/bridge.sh --pull-only`
- Refresh status with `python3 scripts/write_remote_cycle_status.py`
- Confirm the local regression baseline is still green before interpreting remote state
- If the remote service is already active without explicit paper/shadow confirmation, stop at validation and treat that as drift
- Confirm wallet-flow bootstrap is ready
- Confirm the status report still shows A-6 and B-1 as gated research unless new empirical evidence says otherwise

## Required Sequence

The rollout order is fixed:

1. `paper`
2. `shadow`
3. `micro-live`
4. `live`

Do not skip a stage.

## Phase 1: Paper

Goal: verify that the fast-flow loop runs cleanly with conservative caps and no launch-surface regressions.

Checklist:

- Root checks are green: `make hygiene`, `make test`, `make test-polymarket`
- Remote mode is explicitly confirmed as paper, or the service is stopped before a controlled paper restart
- Wallet bootstrap exists and status is ready
- Runtime starts without import or startup failures
- Fast-flow lanes only:
  - wallet-flow and LMSR are allowed restart candidates
  - A-6 stays blocked unless maker-fill and half-life gates pass
  - B-1 stays blocked unless precision is at least `85%` and false positives are at most `5%`
- If Instance #3 is merged, set `JJ_FAST_FLOW_ONLY=true`
- Keep `PAPER_TRADING=true`

Exit criteria:

- First clean paper cycles complete
- First closed paper trades or structural samples are recorded
- Remote status report stays coherent and non-stale

## Phase 2: Shadow

Goal: prove that the same fast-flow routing behaves correctly against live remote conditions without committing real capital.

Checklist:

- Service is stable on the VPS
- Status report shows root tests passing and wallet-flow ready
- Closed paper trades exist and are reviewable
- A-6 and B-1 remain blocked unless their explicit empirical gate status improves

Exit criteria:

- Shadow telemetry matches expected lane health
- No unexpected kill events or startup regressions
- Operator review agrees the loop is ready for a tiny real-money sleeve

## Phase 3: Micro-Live

Goal: place the first tiny live trades under the existing `$5` envelope.

Checklist:

- Explicit operator approval is given for real-money deployment
- Service health is `running`
- Root regression status is `passing`
- Wallet-flow bootstrap is `ready`
- First target sleeve remains wallet-flow and/or LMSR
- A-6 and B-1 are still blocked unless empirical status explicitly upgrades them

Exit criteria:

- First closed live trades are recorded
- Fill quality, fee drag, and operator controls look sane
- No risk cap changes were required to get the first data

## Phase 4: Live

Goal: move from a tiny validation sleeve to a normal live posture only after the earlier stages are green.

Checklist:

- Micro-live results are reviewed, not assumed
- Remote status report is green enough to explain why any undeployed capital still remains idle
- Operator explicitly approves widening the live posture

`live` is a separate approval step. A green status report is necessary, not sufficient.

## Blockers That Still Matter Today

As of March 9, 2026:

- The service was observed `running` in the latest remote artifact, but launch is still blocked
- The blocker is no longer local tests; the blocker is missing execution-validity evidence and unresolved runtime drift despite the green local baseline
- Wallet-flow bootstrap readiness must be explicit, not inferred
- Public-data audits still show:
  - `0` executable A-6 opportunities below the `0.95` gate
  - `0` deterministic B-1 template pairs in the first `1,000` allowed markets

Those facts block live promotion of the structural lanes. They do not block a paper or shadow restart of wallet-flow and LMSR once the restart rails are green, but a running remote service does not count as clearance. Reconcile the remote mode first, then restart only in paper or shadow.
