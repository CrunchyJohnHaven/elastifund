# Instance 3 - E2E Lane Integration

## Scope Executed
- Added deterministic end-to-end integration coverage for the BTC5 market -> policy -> ops chain.
- Added a failure-path integration case that forces a stale market handoff safety-gate veto in policy.
- Hardened policy promotion logic so `launch_posture=clear` with non-green safety gates is a veto (`discard`) instead of shadow-stage.

## Files Changed
- `tests/test_btc5_dual_autoresearch_e2e_integration.py`
  - New deterministic success-path integration test:
    - Runs market lane runner to produce `latest.json` and `policy_handoff.json`.
    - Runs policy lane twice: blocked posture -> `shadow_updated`, then clear posture -> `live_activated`.
    - Asserts `promotion_decision.json` contents and lineage (`simulator_champion_id`).
    - Seeds command-node artifacts as fixtures (no live dependency).
    - Builds ops surface + morning packet and asserts champions, promotions, benchmark labels/charts.
  - New deterministic failure-path integration test:
    - Mutates handoff freshness to stale.
    - Asserts policy veto behavior (`discard`, `non_posture_safety_interlocks_not_green`).
    - Asserts `promotion_decision.json` records veto and safety-gate state.
- `scripts/run_btc5_policy_autoresearch.py`
  - Updated decision logic so an otherwise better candidate is vetoed when posture is clear but safety gates are not all green.
  - Behavior now matches stale-handoff veto expectations for integration and ops confidence checks.

## Verification Run
- `pytest -q tests/test_btc5_dual_autoresearch_e2e_integration.py`
  - Result: `2 passed`
- `pytest -q tests/test_run_btc5_policy_autoresearch.py tests/test_btc5_dual_autoresearch_ops.py tests/test_run_btc5_market_model_autoresearch.py`
  - Result: `11 passed`

## Quality Checklist Mapping
- Champion lineage asserted from market handoff (`market_champion.id`) into policy decision packet (`simulator_champion_id`) and through ops morning/surface outputs.
- Blocked-to-shadow then clear-to-live behavior proven via deterministic two-cycle policy sequence.
- Stale-handoff failure path proven as explicit safety-gate veto with authoritative decision packet evidence.
- Command-node lane is fixture-seeded only; no live command-node execution dependency in the e2e test.
- Tests are deterministic and fast (sub-1s for new integration file in this environment).
