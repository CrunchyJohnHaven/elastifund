# Instance 02 Agent Mutator Dispatch

## Objective

Cut a real `command_node_btc5/v4` frontier with measurable headroom, then replace the evaluator-only command-node lane with a mutation cycle that proposes one new `btc5_command_node.md` packet in a temp workspace, benchmarks it against frozen `v4`, and overwrites the mutable surface only on a keep.

## Implemented

- Recut `benchmarks/command_node_btc5/v4/tasks.jsonl` and `manifest.json` so the checked-in `btc5_command_node.md` is now a stale baseline instead of a saturated champion.
- Verified the new frozen suite still scores a perfect synthetic packet at `100.0`, while the current checked-in baseline now scores `48.0815` with loss `51.9185`.
- Replaced `scripts/run_btc5_command_node_autoresearch.py` with a mutation-cycle runner that:
  - loads the current champion, same-suite ledger history, recent discard packets, and recent crash packets
  - chooses routine versus escalated proposer tiers from discard streak and time-since-keep policy
  - enforces the `$5/day` command-node proposer budget in metadata
  - generates one candidate packet in a temp workspace
  - benchmarks the proposed packet against frozen `v4`
  - writes through to the mutable surface only when the proposed packet beats the same-suite frontier
  - persists `proposal_id`, `parent_champion_id`, `proposer_model`, `estimated_llm_cost_usd`, `mutation_summary`, and `mutation_type` into the run packet, champion registry, latest summary, and append-only ledger
- Hardened suite-specific frontier handling so legacy `v1` through `v3` champions no longer block `v4` keeps.
- Kept the existing Karpathy-style chart contract unchanged.

## Verification

```bash
pytest -q tests/test_btc5_command_node_benchmark.py tests/test_run_btc5_command_node_autoresearch.py tests/test_render_btc5_command_node_progress.py
```

Result: `42 passed in 7.92s`

## Follow-on

- The lane is ready for unattended `v4` hill-climbing. The first live `v4` run will roll its own same-suite champion even if older command-node artifacts still point at legacy suites.
- AWS burn-in wiring should now point the command-node service at this mutation-cycle runner rather than the old evaluator-only behavior.
