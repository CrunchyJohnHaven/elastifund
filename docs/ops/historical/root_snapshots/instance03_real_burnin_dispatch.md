# Instance 3 - Real VPS Burn-In

Status: blocked
Generated at: 2026-03-11T21:10:00Z
Objective achieved: no
Output artifact: `instance03_real_burnin_dispatch.md`

## Result

I did not start or certify a real unattended burn-in from this tree.

That would be untrustworthy for two separate reasons that are still present in the repo:

1. the command-node lane is still saturated at `100.0`
2. the overnight closeout still returns `green` for a short local run

Per the stated acceptance criteria, Instance 3 cannot be closed until both of those are fixed and the corrected code is what the VPS services are running.

## Exact Blockers

### Blocker 1 - Command-node lane still has no headroom

Current evidence from `reports/autoresearch/command_node/latest.json`:

- `champion_total_score=100.0`
- `latest_total_score=100.0`
- `champion_loss=0.0`
- mutable surface: `btc5_command_node.md`

Files/services responsible:

- `scripts/run_btc5_command_node_autoresearch.py`
  - still imports `benchmarks.command_node_btc5.v3.benchmark`
  - still defaults to `benchmarks/command_node_btc5/v3/manifest.json`
  - still identifies the lane as `command_node_btc5_v3`
- `btc5_command_node.md`
  - still declares `task_suite_id = command_node_btc5_v3`
- `deploy/btc5-command-node-autoresearch.service`
  - runs `scripts/btc5_dual_autoresearch_ops.py run-lane --lane command_node --write-morning-report`
  - which resolves to the still-saturated command-node runner above

Why this blocks burn-in:

- the acceptance criteria require "command-node lane shows non-saturated benchmark behavior"
- the current lane still reports a perfect baseline, so an overnight run would not prove improvement headroom

### Blocker 2 - Overnight closeout still false-greens short local runs

Current evidence from `reports/autoresearch/overnight_closeout/latest.json`:

- `overall_status=green`
- `service_audit_rows_in_window=5`
- service-audit window: `2026-03-11T19:48:23.032111+00:00` to `2026-03-11T20:36:08.138068+00:00`
- measured audit span: `0.796` hours

Current evidence from `reports/autoresearch/ops/service_audit.jsonl`:

- market supervised runs in window: `2`
- command-node supervised runs in window: `2`
- policy supervised runs in window: `1`
- lane crashes in window: `0`

Files/services responsible:

- `scripts/btc5_dual_autoresearch_ops.py`
  - `build_overnight_closeout()` still treats `service_audit_grew_during_window` as sufficient audit evidence
  - it still sets `overall_status = "green" if all(overall_checks.values()) else "red"` without enforcing:
    - minimum 8-hour unattended window
    - at least 4 market runs
    - at least 4 command-node runs
    - policy non-blocking unless crashed
- `deploy/btc5-autoresearch.service`
  - runs `scripts/btc5_dual_autoresearch_ops.py refresh --write-morning-report`
- `deploy/btc5-market-model-autoresearch.service`
  - runs the market lane that feeds the same closeout logic
- `deploy/btc5-command-node-autoresearch.service`
  - runs the command-node lane that feeds the same closeout logic

Why this blocks burn-in:

- the required green gate is not the one currently implemented
- a run certified by the current closeout would not satisfy the "trustworthy under the hardened gate" requirement

### Blocker 3 - No local systemd target to run the repo units here

Current environment fact:

- `systemctl` is not present on this machine

Why this matters:

- the requested burn-in must use the repo-tracked systemd units
- that means the real execution target is the VPS, not this local host
- even with VPS access, it would still be incorrect to start the burn-in before Blocker 1 and Blocker 2 are fixed and deployed

## Acceptance Check Against Current State

Required for completion vs current evidence:

- overnight closeout returns green under hardened gate: fail
- command-node lane shows non-saturated benchmark behavior: fail
- market latest artifact fresh in the morning: not yet eligible to certify
- command-node latest artifact fresh in the morning: not yet eligible to certify
- morning packet present: currently yes, but produced under the wrong gate
- overnight closeout present: currently yes, but produced under the wrong gate
- burn-in lasts at least 8 hours wall-clock: fail
- audit trail shows repeated supervised runs: partial only, `2` market and `2` command-node runs

## Conclusion

The original objective is not achieved.

The exact unblock path is:

1. land Instance 1 so the default command-node lane is no longer saturated
2. land Instance 2 so `build_overnight_closeout()` enforces the real overnight gate
3. deploy those changes to the VPS services
4. run the repo-tracked systemd timers for at least 8 hours wall-clock
5. pull back:
   - `reports/autoresearch/ops/service_audit.jsonl`
   - `reports/autoresearch/morning/latest.json`
   - `reports/autoresearch/overnight_closeout/latest.json`
   - `reports/autoresearch/btc5_market/latest.json`
   - `reports/autoresearch/command_node/latest.json`
6. only then decide whether the objective is achieved
