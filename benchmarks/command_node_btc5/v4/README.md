# BTC5 Command-Node Benchmark v4

Status: active
Classification: canonical frozen benchmark lane
Mutable surface: `btc5_command_node.md`

This package freezes the agent-mutation wave needed to close the BTC5 autoresearch objective.
It keeps the same `agent_loss` objective and chart behavior as v1 through v3 while reopening headroom around three concrete gaps: the command-node mutation loop, suite-specific frontier artifacts, and the follow-on AWS burn-in handoff that must point at mutation loops instead of evaluator-only runs.
The checked-in mutable surface is intentionally stale under this v4 cut so the lane still has measurable hill-climb headroom after the first keep.

## Frozen Inputs

- `manifest.json`
- `tasks.jsonl`
- the inherited scoring logic in `benchmark.py`

## Objective

`agent_loss = 100 - total_score`

`total_score` is the average task score over:

- source or path correctness: 30
- dependency correctness: 25
- dispatch completeness: 25
- judge clarity: 20

Lower loss is better.

## Rules

- The task suite stays fixed within the epoch.
- `btc5_command_node.md` is the only mutable surface.
- Results append to `reports/autoresearch/command_node/results.jsonl`.
- A benchmark win is research evidence only. It is not a live P and L claim.
- `command_node_btc5_v1` through `command_node_btc5_v3` remain frozen for historical comparability.
- `v4` intentionally makes the checked-in baseline packet stale so the lane has measurable headroom again.
- `v4` also requires temp-workspace proposal evidence, overnight-closeout truth, and exact mutation-cycle entrypoint naming before the lane can score `100`.
