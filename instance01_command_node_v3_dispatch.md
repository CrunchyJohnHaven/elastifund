# Instance 01 - Command-Node v3 Dispatch

## Scope

Cut a new frozen benchmark at `benchmarks/command_node_btc5/v3/`, keep `command_node_btc5_v1` and `command_node_btc5_v2` untouched and runnable, reopen scoring headroom in the command-node lane, and switch the default mutable packet plus runner defaults to v3 only after the new proof suite passes.

## What Changed

- Added `command_node_btc5_v3` under `benchmarks/command_node_btc5/v3/` with its own `manifest.json`, `tasks.jsonl`, `README.md`, package init, and evaluator wrapper.
- Registered v3 in `benchmarks/index.manifest.json` without modifying the frozen v1 or v2 packages.
- Replaced the mutable packet in `btc5_command_node.md` so the active lane now targets `task_suite_id=command_node_btc5_v3`.
- Switched `scripts/run_btc5_command_node_autoresearch.py` defaults from v2 to v3 while preserving explicit manifest override support for v1 and v2.
- Expanded the proof suite so v1, v2, and v3 are all validated, the default runner path is v3, and the headroom regression is pinned.

## v3 Task Coverage

1. Agent lane headroom and v3 runner selection
2. Ops truth cleanup with champion-delta rendering
3. Overnight closeout artifact with improved versus null-result reporting
4. VPS burn-in with supervised lane services and exact blocker reporting

The scalar objective is unchanged:

- source or path correctness: 30
- dependency correctness: 25
- dispatch completeness: 25
- judge clarity: 20

`agent_loss = 100 - total_score`, lower is better.

## Acceptance Evidence

- The live v3 mutable packet at `btc5_command_node.md` evaluates to `total_score=100.0` and `loss=0.0` against `benchmarks/command_node_btc5/v3/manifest.json`.
- A ported v2-style baseline packet evaluates to `total_score=29.2334` and `loss=70.7666` under v3, so the old saturated baseline is decisively below the `<95.0` target.
- Runner defaults now target `command_node_btc5_v3`, while explicit overrides still keep v1 and v2 runnable.
- The Karpathy-style progress chart code path is unchanged; `tests/test_render_btc5_command_node_progress.py` still passes as-is.

## Verification

```bash
pytest -q tests/test_btc5_command_node_benchmark.py tests/test_run_btc5_command_node_autoresearch.py tests/test_render_btc5_command_node_progress.py
make hygiene
```

Observed results:

- `30 passed in 2.47s`
- `make hygiene` passed
