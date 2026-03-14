# Instance 3 - Command-Node Autoresearch Lane

## Scope

Freeze and run the BTC5 command-node benchmark lane under `benchmarks/command_node_btc5/v1/` with one mutable surface only: `btc5_command_node.md`.

## Frozen Contract

- Task suite: `benchmarks/command_node_btc5/v1/tasks.jsonl`
- Manifest: `benchmarks/command_node_btc5/v1/manifest.json`
- Scoring objective: `agent_loss = 100 - total_score` (lower is better)
- Score components:
  - source/path correctness: 30
  - dependency correctness: 25
  - dispatch completeness: 25
  - judge clarity: 20

## Dispatch Quality Target

The benchmark rewards dispatch packets that choose the correct model owner, maximize parallelism without path conflicts, preserve dependency order, and emit worker-ready output-file contracts.

## Artifacts Emitted

- Append-only ledger: `reports/autoresearch/command_node/results.jsonl`
- Champion registry: `reports/autoresearch/command_node/champion.json`
- Latest summary: `reports/autoresearch/command_node/latest.json`
- Karpathy-style progress chart: `research/btc5_command_node_progress.svg`

## Verification

Run:

```bash
pytest -q tests/test_btc5_command_node_benchmark.py tests/test_render_btc5_command_node_progress.py tests/test_run_btc5_command_node_autoresearch.py
```

## Notes

Benchmark progress is benchmark progress, not live profitability.
