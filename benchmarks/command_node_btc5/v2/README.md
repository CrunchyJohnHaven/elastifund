# BTC5 Command-Node Benchmark v2

Status: active
Classification: canonical frozen benchmark lane
Mutable surface: `btc5_command_node.md`

This package freezes the refreshed BTC5 command-node task suite for the current market to policy to ops bridge.
It keeps the same `agent_loss` objective and scoring weights as v1 while replacing the legacy pre-bridge tasks with four tasks that benchmark the current system shape.

## Frozen Inputs

- `manifest.json`
- `tasks.jsonl`
- the inherited scoring logic in `benchmark.py`

## Objective

`agent_loss = 100 - total_score`

`total_score` is the average task score over:

- source/path correctness: 30 points
- dependency correctness: 25 points
- dispatch completeness: 25 points
- judge clarity: 20 points

Lower loss is better.

## Rules

- The task suite stays fixed within the epoch.
- `btc5_command_node.md` is the only mutable surface.
- Results append to `reports/autoresearch/command_node/results.jsonl`.
- A benchmark win is research evidence only. It is not a live P and L claim.
- `command_node_btc5_v1` remains frozen for historical comparability.
