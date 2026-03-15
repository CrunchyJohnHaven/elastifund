# Instance 02 Agent Mutation Loop

Status: complete
Date: 2026-03-11
Project: BTC5 Karpathy-style autoresearch finish line

## Outcome

`benchmarks/command_node_btc5/v4/` was recut so the command-node lane has real headroom again, and the mutation loop now operates against that harder frozen suite without immediately collapsing back to a `0.0`-loss champion.

## What Changed

- Hardened `benchmarks/command_node_btc5/v4/tasks.jsonl`, `manifest.json`, and `README.md` so `v4` now requires:
  - temp-workspace proposal evidence
  - overnight-closeout truth
  - exact mutation-cycle entrypoint naming for the AWS handoff
- Left `v1` through `v3` frozen and runnable.
- Kept the perfect-packet contract intact: synthetic packets generated directly from the frozen `v4` task suite still score `100.0`.
- Preserved the command-node mutation runner in `scripts/run_btc5_command_node_autoresearch.py`:
  - one mutable surface only: `btc5_command_node.md`
  - temp-workspace proposal generation
  - same-suite frontier comparison
  - keep-only overwrite
  - proposer metadata in run packet, latest summary, champion registry, and append-only ledger
- Kept the stable supervised entrypoint at `scripts/run_btc5_command_node_mutation_cycle.py`.

## Headroom Proof

- The pre-refresh checked-in mutable surface scored `84.7029` with loss `15.2971` on the hardened `v4` suite.
- After resetting stale `v4` lane artifacts and running one fresh mutation cycle, the lane kept a new same-suite champion at `89.1563` total score with loss `10.8437`.
- Headroom is still real after that keep:
  - current `btc5_command_node.md` remains below `95`
  - perfect synthetic packet remains `100`
  - later unattended runs can continue hill-climbing instead of tying or discarding forever

## Refreshed Artifacts

- `reports/autoresearch/command_node/results.jsonl`
- `reports/autoresearch/command_node/champion.json`
- `reports/autoresearch/command_node/latest.json`
- `research/btc5_command_node_progress.svg`

The refreshed latest summary records:

- `proposal_id=proposal_0001`
- `parent_champion_id=null`
- `proposer_model=command-node-routine-proposer`
- `estimated_llm_cost_usd=0.35`
- `mutation_type=targeted_task_repair`
- `baseline_total_score=84.7029`
- `latest_total_score=89.1563`

## Verification

```bash
pytest -q tests/test_btc5_command_node_benchmark.py tests/test_run_btc5_command_node_autoresearch.py tests/test_render_btc5_command_node_progress.py
```

Result: `42 passed in 5.16s`

## Follow-On Boundary

- The command-node lane is ready for Instance 3 budget surfacing and Instance 5 AWS burn-in wiring.
- The repo now shows a live same-suite frontier below saturation instead of a misleading `v4` perfect champion.
