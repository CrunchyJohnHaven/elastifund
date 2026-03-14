# Instance 2: Policy Decision Packet

## Scope Executed
Implemented an authoritative per-cycle policy decision artifact at:

- `reports/autoresearch/btc5_policy/promotion_decision.json`

The packet is now written on every cycle outcome, including:

- `keep`
- `discard`
- `shadow_updated`
- `live_promoted`
- `live_activated`
- `rollback_triggered`
- `crash`

## Contract Added
`promotion_decision.json` includes:

- `generated_at`, `experiment_id`, `status`, `action`, `decision_reason`
- `launch_posture`, `safety_gates`
- `candidate`, `incumbent`, `champion_after`, `live_after`, `staged_after`
- `policy_loss_contract_version`, `policy_loss_formula`, `evaluation_source`
- `simulator_champion_id`, `market_epoch_id`
- `artifact_paths.results_ledger`, `artifact_paths.run_json`, `artifact_paths.champion_registry`, `artifact_paths.market_policy_handoff`, `artifact_paths.market_latest_json`

## Authoritative Wiring
Policy action metadata in the run ledger now mirrors the decision packet:

- `results.jsonl` run rows include `decision.status`, `decision.action`, `decision.reason`
- These are derived from the same branch result used to write champion/live/staged registry state
- Crash path writes `promotion_decision.json` before exit with available lineage and artifact references

`btc5_portfolio_expectation/latest.json` remains diagnostic-only; no decision branch depends on it.

## Tests Extended
`tests/test_run_btc5_policy_autoresearch.py` now asserts decision packet content and lineage for:

- blocked -> `shadow_updated`
- clear posture activation -> `live_activated`
- discard path -> `discard`
- rollback path -> `rollback_triggered`
- direct live promotion -> `live_promoted`
- crash path (missing candidate payload) -> `crash`

## Verification
- `pytest -q tests/test_run_btc5_policy_autoresearch.py` -> `5 passed`
- `pytest -q tests/test_btc5_dual_autoresearch_ops.py` -> `4 passed`
