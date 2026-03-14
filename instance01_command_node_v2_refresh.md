# Instance 01 - Command-Node v2 Refresh

## Scope

Cut a new frozen benchmark at `benchmarks/command_node_btc5/v2/`, keep `command_node_btc5_v1` untouched, and switch the default command-node mutable packet plus runner defaults to v2.

## What Changed

- Added a versioned `command_node_btc5_v2` manifest, task suite, README, and evaluator wrapper under `benchmarks/command_node_btc5/v2/`.
- Refreshed the frozen task suite so it benchmarks the current bridge and ops shape instead of the older scaffold.
- Updated `btc5_command_node.md` so the only mutable surface now targets `task_suite_id=command_node_btc5_v2`.
- Switched `scripts/run_btc5_command_node_autoresearch.py` to default to the v2 manifest while keeping explicit manifest override support for v1.

## Frozen v2 Task Coverage

1. Market to policy handoff integrity
2. Policy promotion decision and rollback triage
3. Overnight burn in and stale artifact triage
4. Morning packet and benchmark versus live labeling review

The scalar objective and scoring weights are unchanged:

- source or path correctness: 30
- dependency correctness: 25
- dispatch completeness: 25
- judge clarity: 20

`agent_loss = 100 - total_score`, lower is better.

## Compatibility Notes

- `command_node_btc5_v1` remains frozen and still runs through explicit manifest selection.
- The mutable surface remains `btc5_command_node.md`.
- Ledger and chart behavior remain unchanged apart from the default manifest and task suite switch.

## Verification

Run:

```bash
pytest -q tests/test_btc5_command_node_benchmark.py tests/test_render_btc5_command_node_progress.py tests/test_run_btc5_command_node_autoresearch.py
```

The test coverage now checks:

- v2 manifest checksum and frozen task count
- v2 as the default runner path
- explicit v1 manifest override remains runnable
