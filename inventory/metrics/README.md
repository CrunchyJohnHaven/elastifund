# Metrics Contract

Every benchmarked system should normalize into the same evidence surface.

## Expected Evidence

- order lifecycle ledger
- market-data snapshot ledger
- reliability counters
- latency metrics
- CPU and memory usage
- security scan results

For sibling comparison systems that are not allocator candidates, the evidence packet must also publish:

- `comparison_mode`
- `allocator_eligible`
- `telemetry.decision_count`
- `telemetry.avg_cycle_time_ms`
- `telemetry.p95_cycle_time_ms`
- `telemetry.total_cost_usd`
- `outcome_comparisons[]`
- `isolation.wallet_access`
- `isolation.shared_state_access`

The comparison-only contract lives in `inventory/metrics/evidence_plane.py`. Any external system benchmark that could touch live funds must set:

- `comparison_mode = "comparison_only"`
- `allocator_eligible = false`
- `isolation.wallet_access = "none"`
- `isolation.shared_state_access = "none"`

## Why This Exists

The public leaderboard, when it exists, should rank operational quality before profitability claims. This directory is where that normalization contract lives.
