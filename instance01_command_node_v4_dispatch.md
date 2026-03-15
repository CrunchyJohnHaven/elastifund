# Instance 01 - Command-Node v4 Dispatch

## Scope

Cut a new frozen benchmark at `benchmarks/command_node_btc5/v4/`, keep `command_node_btc5_v1` through `command_node_btc5_v3` untouched and runnable, redesign the command-node suite so the v3-saturating baseline no longer scores `100.0`, and switch the mutable packet plus runner defaults to v4 only after the proof suite passes.

## What Changed

- Added `command_node_btc5_v4` under `benchmarks/command_node_btc5/v4/` with its own `manifest.json`, `tasks.jsonl`, `README.md`, package init, and frozen evaluator wrapper.
- Registered v4 in `benchmarks/index.manifest.json` without modifying the frozen v1, v2, or v3 packages.
- Replaced the mutable packet in `btc5_command_node.md` so the active lane now targets `task_suite_id=command_node_btc5_v4`.
- Switched `scripts/run_btc5_command_node_autoresearch.py` defaults from v3 to v4 while preserving explicit manifest override support for v1 through v3.
- Expanded the proof suite so v1 through v4 all validate, the default runner path is v4, and the old v3-perfect packet is pinned below saturation under the new suite.

## v4 Task Coverage

1. Command-node headroom v4 cutover with model choice under ambiguity and conflicting-artifact ordering
2. Honest overnight gate with benchmark-versus-live labeling and unattended-window triage
3. Real VPS burn-in with repo-tracked systemd units and exact blocker naming

The scalar objective is unchanged:

- source or path correctness: 30
- dependency correctness: 25
- dispatch completeness: 25
- judge clarity: 20

`agent_loss = 100 - total_score`, lower is better.

## Acceptance Evidence

- The active v4 mutable packet at `btc5_command_node.md` evaluates to `total_score=100.0` and `loss=0.0` against `benchmarks/command_node_btc5/v4/manifest.json`.
- A ported v3-perfect baseline packet evaluates to `total_score=57.6392` and `loss=42.3608` under v4, so the previous saturated packet is decisively below the `<95.0` target.
- Runner defaults now target `command_node_btc5_v4`, while explicit manifest overrides still keep v1, v2, and v3 runnable.
- The Karpathy-style progress chart code path is unchanged; `tests/test_render_btc5_command_node_progress.py` still passes without modification.

## Verification

```bash
python3 -m pytest -q tests/test_btc5_command_node_benchmark.py tests/test_run_btc5_command_node_autoresearch.py tests/test_render_btc5_command_node_progress.py
make hygiene
```

Observed results:

- `40 passed in 3.06s`
- `make hygiene` passed
