# Instance 02 - Honest Overnight Gate

Generated at: 2026-03-11T21:16:23Z

## Deliverable Outcome

Hardened `build_overnight_closeout()` so `overall_status=green` now requires a real unattended benchmark window instead of any recent audit growth.

Green now requires all of the following:

- objective-lane service-audit span of at least 8 hours
- at least 4 supervised `run` rows for `market` in the window
- at least 4 supervised `run` rows for `command_node` in the window
- fresh `market` and `command_node` latest artifacts
- zero lane crashes, including failed supervised runs

`policy` remains in the report, but it no longer blocks green for this objective unless it crashes.
`no_better_candidate` remains a valid lane outcome.

## Files Changed

- `scripts/btc5_dual_autoresearch_ops.py`
- `tests/test_btc5_dual_autoresearch_ops.py`

## Implementation Notes

- Added service-audit helpers that distinguish actual supervised `event_type=run` rows from skips and blocked states.
- Closeout packets now record:
  - per-lane supervised run counts
  - per-lane failed run counts
  - objective-lane audit span in hours and seconds
  - first/last supervised run timestamps
- Closeout lane outcomes still report `improved`, `no_better_candidate`, `no_experiments`, or `crash`, but failed supervised runs now upgrade the lane outcome to `crash`.
- Markdown output now exposes the audit span plus run/failure counts so the benchmark-vs-live framing stays explicit and inspectable.

## Test Coverage Added

- False-green prevention: a short local window with fresh artifacts but only 2 market runs, 2 command-node runs, and a sub-8-hour span now returns `red`.
- Valid null-result night: a real 8+ hour window with 4 market runs and 4 command-node runs can still return `green` when no better candidate appears.
- Crash night: an otherwise valid overnight window still returns `red` when the command-node runner fails once.

## Verification

Commands executed:

```bash
pytest -q tests/test_btc5_dual_autoresearch_ops.py
pytest -q tests/test_btc5_dual_autoresearch_ops.py \
  tests/test_btc5_autoresearch_service.py \
  tests/test_btc5_dual_autoresearch_services.py \
  tests/test_btc5_dual_autoresearch_e2e_integration.py \
  tests/test_btc5_market_model_benchmark.py \
  tests/test_btc5_command_node_benchmark.py \
  tests/test_run_btc5_market_model_autoresearch.py \
  tests/test_run_btc5_command_node_autoresearch.py \
  tests/test_run_btc5_policy_autoresearch.py
```

Observed:

- `tests/test_btc5_dual_autoresearch_ops.py`: `12 passed`
- wider autoresearch proof slice in the current worktree: `57 passed`

## Objective Status

Instance 2 is complete in code and tests.
The original overall objective is still not achieved until Instance 3 completes a real unattended VPS burn-in under this hardened gate.
