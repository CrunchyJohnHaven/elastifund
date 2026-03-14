# Instance 4: VPS Services, Morning Report, and Operator-Surface Wiring

## Scope
This dispatch wires the BTC5 market-model lane, BTC5 policy lane, and BTC5 command-node lane into supervised VPS timers with bounded cadence, crash backoff, stale-artifact alarms, and append-only audits.

Benchmark progress is labeled as benchmark progress only. It is not realized profitability.

## Required Inputs Read
1. `CLAUDE.md`
2. `docs/ops/REMOTE_DEV_CYCLE_STANDARD.md`
3. `scripts/btc5_rollout.py`
4. `scripts/render_public_metrics.py`
5. `instance01_btc5_dual_autoresearch_contract.md` (market-lane handoff artifact present in repo)
6. `btc5_policy_autopromote.md` (policy-lane handoff artifact present in repo)
7. `btc5_command_node.md` (command-node handoff artifact present in repo)

## Services and Timers
Lane services are supervised through `scripts/btc5_dual_autoresearch_ops.py`.

- `deploy/btc5-market-model-autoresearch.service`
  - Runs: `run-lane --lane market --write-morning-report`
  - Timer: `deploy/btc5-market-model-autoresearch.timer`
  - Cadence: every 60 minutes
  - Timeout: 900s
- `deploy/btc5-policy-autoresearch.service`
  - Runs: `run-lane --lane policy --write-morning-report`
  - Timer: `deploy/btc5-policy-autoresearch.timer`
  - Cadence: every 15 minutes
  - Timeout: 600s
- `deploy/btc5-command-node-autoresearch.service`
  - Runs: `run-lane --lane command_node --write-morning-report`
  - Timer: `deploy/btc5-command-node-autoresearch.timer`
  - Cadence: every 60 minutes
  - Timeout: 900s
- `deploy/btc5-dual-autoresearch-morning.service`
  - Runs: `morning-report --window-hours 24`
  - Timer: `deploy/btc5-dual-autoresearch-morning.timer`
  - Cadence: daily 09:05

## Backoff, Stale Alarms, and Audit Trail
Implemented in `scripts/btc5_dual_autoresearch_ops.py`.

- Exponential backoff per lane after failures, with max caps per lane.
- Daily runtime budget guardrails per lane.
- Stale and missing artifact alarms at lane and surface level.
- Append-only service audit ledger:
  - `reports/autoresearch/ops/service_audit.jsonl`
- Append-only benchmark/policy ledgers consumed by the surface:
  - `reports/autoresearch/btc5_market/results.jsonl`
  - `reports/autoresearch/btc5_policy/results.jsonl`
  - `reports/autoresearch/command_node/results.jsonl`

## Morning Report Contract
Now emitted on every lane cycle and also on the daily morning timer.

- Human-readable: `reports/autoresearch/morning/latest.md`
- Machine-readable: `reports/autoresearch/morning/latest.json`

Contents are decision-oriented:
- experiments run and kept improvements
- promotion events
- crashes
- blockers
- current lane champions

## Operator-Surface Integration
The unified surface is written to `reports/autoresearch/latest.json` and includes:

- per-lane health and blockers
- stale artifact alarms
- runtime safety context
- current champions for market, policy, and command-node lanes
- required progress charts:
  - `research/btc5_market_model_progress.svg`
  - `research/btc5_command_node_progress.svg`

`render_public_metrics.py` consumes this surface and publishes it into the operator/public metrics contract while preserving benchmark-progress labeling.

## Verification
Focused tests:
- `tests/test_btc5_dual_autoresearch_services.py`
- `tests/test_btc5_dual_autoresearch_ops.py`
- `tests/test_render_public_metrics.py`

This dispatch updates service wiring and service tests so morning report artifacts are refreshed each lane cycle.
