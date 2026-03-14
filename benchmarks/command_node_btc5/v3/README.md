# BTC5 Command-Node Benchmark v3

Status: active
Classification: canonical frozen benchmark lane
Mutable surface: `btc5_command_node.md`

This package freezes the current four-move BTC5 command-node dispatch wave.
It keeps the same `agent_loss` objective and chart behavior as v1 and v2 while making the suite more discriminative around the live operator surface: v3 runner selection, conflicting dependency order, benchmark-versus-live labeling, overnight closeout reporting, and burn-in triage.

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
- `command_node_btc5_v1` and `command_node_btc5_v2` remain frozen for historical comparability.
