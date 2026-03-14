# Instance 3 - Overnight Closeout Artifact

Generated at: 2026-03-11T20:42:09Z

## Deliverable Outcome

Added a dedicated overnight closeout artifact to the dual-autoresearch ops surface.

- Machine-readable packet: `reports/autoresearch/overnight_closeout/latest.json`
- Human-readable packet: `reports/autoresearch/overnight_closeout/latest.md`

The packet reports, per lane:

- `champion_before`
- `champion_after`
- `changed`
- `improved`
- `experiment_count`
- `keep_count`
- `crash_count`
- `fresh`

It also records the explicit null-result case with `outcome=no_better_candidate` and `outcome_note=no candidate beat the incumbent`, so a no-improvement night is still a valid, evidenced result instead of an ambiguous silence.

## Wiring

The closeout now writes from the existing ops entrypoint in `scripts/btc5_dual_autoresearch_ops.py`.

- `python3 scripts/btc5_dual_autoresearch_ops.py overnight-closeout --window-hours 12`
- `python3 scripts/btc5_dual_autoresearch_ops.py refresh --write-morning-report`
- `python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane <lane> --write-morning-report`
- `python3 scripts/btc5_dual_autoresearch_ops.py morning-report`

That keeps Instance 4’s overnight burn-in path compatible with the existing `refresh --write-morning-report` shim.

## Files Changed

- `scripts/btc5_dual_autoresearch_ops.py`
- `tests/test_btc5_dual_autoresearch_ops.py`

## Verification Run

Commands executed locally:

```bash
pytest -q tests/test_btc5_dual_autoresearch_ops.py tests/test_btc5_autoresearch_service.py tests/test_btc5_dual_autoresearch_services.py tests/test_btc5_dual_autoresearch_e2e_integration.py
python3 scripts/btc5_dual_autoresearch_ops.py overnight-closeout --window-hours 12
```

Observed:

- Combined proof pass: `19 passed`
- Closeout artifact written successfully to both JSON and Markdown targets
- Current repo closeout status: `green`
- Current repo overnight result: null-result night recorded explicitly for `market`, `policy`, and `command_node`
- Service audit evidence in the generated packet: `rows_in_window=5`
- Crash evidence in the generated packet: `crashed_lanes=[]`

## Current Artifact Readout

Latest generated closeout summary:

- Benchmark progress only, not realized P&L
- Overall overnight status: `green`
- `market`: `no_better_candidate`
- `policy`: `no_better_candidate`
- `command_node`: `no_better_candidate`

This is the intended null-result contract for a night where no candidate displaced the incumbent but the supervised benchmark lanes still ran, stayed fresh, and did not crash.
