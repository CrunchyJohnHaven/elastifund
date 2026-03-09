# Elastic Hub Bootstrap

## Purpose

`hub/elastic/` bootstraps the Elastic control plane for the Elastifund.io architecture. It creates:

- ILM policies for standard hub indices and TSDS metrics
- rollover-backed aliases for:
  - `elastifund-strategies`
  - `elastifund-trades`
  - `elastifund-knowledge`
  - `elastifund-agents`
- a TSDS data stream for `elastifund-metrics`
- verification checks for mappings, lifecycle bindings, and TSDS settings

This is the second build instance from the Elastifund.io architecture plan: the index and lifecycle layer for the knowledge hub.

## Current Bot Integration

The Polymarket bot can now publish directly into the resources this bootstrap creates:

- `elastifund-agents` for heartbeat and runtime status
- `elastifund-metrics` for per-cycle telemetry
- `elastifund-trades` for paper/live order snapshots

That makes the bootstrap operationally meaningful today instead of remaining a future-only hub artifact.

## Non-Trading Ops Contract

The non-trading control plane now assumes a shared schema contract for the audit-engine operating surface. The repo-side Kibana pack in [flywheel/kibana_pack.py](../../flywheel/kibana_pack.py) consumes that contract and renders dashboard specs for:

- engine performance
- prospect pipeline
- checkout funnel
- fulfillment status
- refunds and churn
- allocator decisions
- knowledge-pack activity

Alert specs are defined against the same contract for:

- checkout webhook failures
- fulfillment stalls
- refund spikes
- complaint spikes when outbound follow-up is enabled
- missing worker activity
- negative ROI regimes

Until the Elastic transforms land, the markdown-first pack can read an optional normalized repo snapshot at `reports/revenue_audit_ops.json`. The contract itself lives in [hub/elastic/specs.py](../../hub/elastic/specs.py) via `build_nontrading_control_plane_spec()`.

Kill-switch alignment:

- global non-trading shutdown remains the agent-level `global_kill_switch`
- per-engine shutdown now flows through `engine_states.kill_switch_active` in the non-trading store
- dashboards and alerts must read those fields directly rather than inferring shutdown from missing data

## Files

- [hub/elastic/bootstrap.py](../../hub/elastic/bootstrap.py)
- [hub/elastic/specs.py](../../hub/elastic/specs.py)
- [hub/elastic/client.py](../../hub/elastic/client.py)
- [tests/test_elastic_bootstrap.py](../../tests/test_elastic_bootstrap.py)

## Usage

Preview the generated plan:

```bash
python -m hub.elastic.bootstrap plan
```

Write the plan to disk for review:

```bash
python -m hub.elastic.bootstrap plan --write-plan reports/elastic_bootstrap_plan.json
```

Apply the policies, templates, aliases, and metrics data stream:

```bash
python -m hub.elastic.bootstrap apply
```

Verify an existing cluster:

```bash
python -m hub.elastic.bootstrap verify
```

For a local dev cluster with a self-signed certificate:

```bash
python -m hub.elastic.bootstrap apply --insecure
```

Generate and validate the Kibana pack that includes the non-trading ops dashboards:

```bash
python -m data_layer flywheel-kibana-pack --audit-ops reports/revenue_audit_ops.json
python scripts/validate_nontrading_kibana_pack.py --audit-ops reports/revenue_audit_ops.json
```

## Environment

Configure the bootstrap through `.env` or the shell:

- `ELASTICSEARCH_URL` or `ELASTIC_URL`
- `ELASTIC_API_KEY`
- `ELASTIC_USERNAME`
- `ELASTIC_PASSWORD`
- `ELASTIC_SNAPSHOT_REPOSITORY`
- `ELASTIC_VECTOR_DIMS`
- `ELASTIC_VERIFY_TLS`
- `ELASTIC_TIMEOUT_SECONDS`

API key behavior:

- If `ELASTIC_API_KEY` already contains the encoded value expected by Elasticsearch, it is used as-is.
- If it contains `id:api_key`, the bootstrap encodes it into the `Authorization: ApiKey ...` header.

## Lifecycle Design

Standard hub aliases use one ILM policy:

- hot: rollover at 7 days or 50 GB primary shard size
- warm: 7-day transition, read-only, force-merge to one segment
- cold: 30-day transition, searchable snapshots
- frozen: 90-day transition
- delete: 365-day transition while keeping the searchable snapshot

The metrics data stream uses TSDS settings with `agent_id` and `strategy_id` as routing and dimension fields, and `pnl_usd`, `drawdown_pct`, and `revenue_usd` as metric fields.

## Downsampling Caveat

The requested metrics rollups are:

- `10s -> 1m` at 7 days
- `1m -> 1h` at 30 days
- `1h -> 1d` at 90 days

The bootstrap wires the first two into ILM and emits the third as a maintenance-schedule entry in the generated plan. That split is deliberate: the frozen phase supports searchable snapshots, but not a further downsample action. The 90-day `1d` rollup therefore needs to run before the frozen cutover.

## Verification Contract

`verify` checks:

- ILM policies exist
- index templates exist
- rollover aliases are bound to the expected lifecycle policy
- vector fields keep the configured dimension count
- the metrics stream is in `time_series` mode with the expected routing path
- TSDS fields preserve `time_series_dimension` and `time_series_metric` flags
