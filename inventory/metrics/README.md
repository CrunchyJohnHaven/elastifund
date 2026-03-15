# Metrics Contract

| Metadata | Value |
|---|---|
| Canonical file | `inventory/metrics/README.md` |
| Role | Evidence-plane normalization contract index |
| Scope | `inventory/metrics/` only |
| Last updated | 2026-03-11 |

Every benchmarked system should normalize into the same evidence surface.

## Canonical Contract

The canonical comparison packet schema is implemented in `inventory/metrics/evidence_plane.py`.

## Expected Evidence

- Order lifecycle ledger.
- Market-data snapshot ledger.
- Reliability counters.
- Latency metrics.
- CPU and memory usage.
- Security scan results.

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

Any external-system benchmark packet that could touch live funds must set:

- `comparison_mode = "comparison_only"`
- `allocator_eligible = false`
- `isolation.wallet_access = "none"`
- `isolation.shared_state_access = "none"`

## Why This Exists

The public leaderboard, when it exists, should rank operational quality before profitability claims.
