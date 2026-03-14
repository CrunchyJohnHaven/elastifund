# Benchmark Packages

| Metadata | Value |
|---|---|
| Canonical file | `benchmarks/README.md` |
| Role | Index for frozen benchmark packages |
| Scope | `benchmarks/` only |
| Last updated | 2026-03-11 |

## Package Index

| Path | Status | Classification | Purpose |
|---|---|---|---|
| `calibration_v1/` | active | canonical frozen benchmark lane | Reproducible calibration evaluation on fixed historical slices |
| `btc5_market/v1/` | active | canonical frozen benchmark lane | Frozen BTC5 market-model benchmark on a 24-hour replay epoch |
| `command_node_btc5/v1/` | active | canonical frozen benchmark lane | Frozen BTC5 command-node dispatch planning benchmark and scorer |

Machine-readable lane index: `benchmarks/index.manifest.json`.

## Rules

- Each benchmark package should represent one frozen lane with a versioned manifest.
- Keep lane names lowercase snake_case (for example, `calibration_v1`, `strategy_v1`).
- A benchmark win is research evidence only, not automatic promotion to paper/shadow/live.
- Historical benchmark lanes should remain in `benchmarks/` and be marked with explicit `status` in their README instead of being silently repurposed.
