# BTC5 Command-Node Benchmark v1

Status: active
Classification: canonical frozen benchmark lane
Mutable surface: `btc5_command_node.md`

This package freezes the BTC5 command-node task suite and evaluator for one 24-hour benchmark epoch.
It scores planning packets against five BTC5 autoresearch dispatch tasks derived from the dual-autoresearch instance plan and workflow-mined handoff patterns.

## Frozen Inputs

- `manifest.json`
- `tasks.jsonl`
- the scoring weights and ledger schema in `benchmark.py`

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
- A benchmark win is research evidence only. It is not a live P&L claim.
