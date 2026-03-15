# Instance 4 - Overnight Burn-in Ops

Generated at: 2026-03-11T19:49:30Z

## Deliverable Outcome

Deployment units are now aligned to the lane supervisor entrypoints in `scripts/btc5_dual_autoresearch_ops.py`.

- `deploy/btc5-market-model-autoresearch.service` -> `python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane market --write-morning-report`
- `deploy/btc5-policy-autoresearch.service` -> `python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane policy --write-morning-report`
- `deploy/btc5-command-node-autoresearch.service` -> `python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane command_node --write-morning-report`
- `deploy/btc5-autoresearch.service` (compatibility shim) -> `python3 scripts/btc5_dual_autoresearch_ops.py refresh --write-morning-report`

Cadence alignment:

- Market timer: hourly (`OnUnitActiveSec=60min`)
- Policy timer: every 15 minutes (`OnUnitActiveSec=15min`)
- Command-node timer: hourly (`OnUnitActiveSec=60min`)
- Compatibility refresh timer: every 15 minutes (`OnUnitActiveSec=15min`)

## Files Changed

- `deploy/btc5-autoresearch.service`
- `deploy/btc5-autoresearch.timer`
- `tests/test_btc5_autoresearch_service.py`

## Verification Run

Commands executed locally:

```bash
pytest -q tests/test_btc5_autoresearch_service.py tests/test_btc5_dual_autoresearch_services.py
pytest -q tests/test_btc5_dual_autoresearch_ops.py
python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane market --write-morning-report
python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane policy --write-morning-report
python3 scripts/btc5_dual_autoresearch_ops.py run-lane --lane command_node --write-morning-report
python3 scripts/btc5_dual_autoresearch_ops.py refresh --write-morning-report
```

Observed:

- Targeted tests passed: `10 passed`.
- Lane runs succeeded (`status=ok`) for market, policy, and command-node.
- Service audit trail present and non-empty: `reports/autoresearch/ops/service_audit.jsonl` now contains 3 run rows for all lanes.
- Fresh lane latest artifacts after run:
  - `reports/autoresearch/btc5_market/latest.json`
  - `reports/autoresearch/btc5_policy/latest.json`
  - `reports/autoresearch/command_node/latest.json`
- Fresh surface artifacts after refresh:
  - `reports/autoresearch/latest.json`
  - `reports/autoresearch/morning/latest.json`
- Fresh benchmark charts required by this wave:
  - `research/btc5_market_model_progress.svg`
  - `research/btc5_command_node_progress.svg`
- Fresh policy decision packet:
  - `reports/autoresearch/btc5_policy/promotion_decision.json`

## Overnight Burn-in Readiness Assessment

Current status: **not yet proven** for unattended overnight operation.

Concrete blockers observed from generated artifacts:

1. `reports/autoresearch/latest.json` reports `overall_status=degraded`.
2. Policy lane blocker: `stale_chart:research/btc5_arr_progress.svg`.
3. Runtime posture blocker in `reports/runtime_truth_latest.json`: `launch_posture=blocked` with finance gate block reasons.
4. No true overnight window evidence yet (current service audit sample is immediate spot-run validation, not multi-hour unattended durability).

## Acceptance Checklist (Instance 4)

- Every lane has a real runnable systemd command tied to ops supervisor: **PASS**
- Service audit trail grows during burn-in: **PASS (spot-run evidence)**
- Morning packets, ledgers, and charts are fresh after overnight window: **PARTIAL (fresh now; overnight duration not yet executed)**
- Failures reported as concrete blockers: **PASS**
- Benchmark progress clearly labeled as benchmark (not realized P&L): **PASS**

## Required Next Step To Close Instance 4

Run the VPS timers through a full overnight window (minimum one unattended multi-hour cycle), then re-evaluate against the same artifacts with timestamped evidence from the overnight interval.
