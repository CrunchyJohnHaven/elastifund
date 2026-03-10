# Instance 02 Handoff - BTC5 Package Freeze

## Status
- Current status: `upgrade_blocked`
- Next status after the 8 GB / 2 vCPU / 160 GB SSD cutover validates: `shadow_ready_after_upgrade`

## Frozen Champion
- Champion lane: `btc_5m`
- Frozen post-upgrade shadow package: `btc5:grid_d0.00005_up0.48_down0.51`
- Why this wins: `reports/state_improvement_latest.json` ranks the tighter recovery candidate highest while the currently selected `open_et` package remains load-pending and short-window BTC5 quality is still negative.

## Comparison-Only Set
- Package held comparison-only: `policy_current_live_profile__open_et__grid_d0.00015_up0.51_down0.51`
- Comparison-only lanes: `btc_15m`, `eth_intraday`, `btc_4h`
- Size policy: `no_size_increase_beyond_current_proof_size`

## Post-Upgrade Shadow Sequence
1. `package_load`: load `btc5:grid_d0.00005_up0.48_down0.51` in shadow and confirm `runtime_package_loaded=true` in regenerated truth; current loaded=`False`
2. `candidate_scan`: run the first clean candidate scan with BTC5 as the champion lane; current seed count is `2` Polymarket candidates
3. `order_failure_check`: confirm `order_failed_rate_recent_40 <= 0.25`; current value is `0.025`
4. `executed_notional_check`: require `executed_notional_usd_last_hour > 0` and `candidate_to_trade_conversion_last_hour > 0` for two consecutive cycles; current values are `0.0` and `0.0`

## Capital Rule
- The executed `250 USD` trading allocation is enough for the next proof window.
- The incoming `2000 USD` stays in reserve.
- Extra capital stays parked because the service is blocked, the chosen package is not loaded, hourly executed notional is `0.0`, hourly candidate-to-trade conversion is `0.0`, and recent BTC5 windows are negative (`-8.5465` on the last 12 live fills, `-28.1442` on the last 20).

## Required Outputs
- `candidate_delta_arr_bps`: `248262402`
- `expected_improvement_velocity_delta`: `0.0`
- `arr_confidence_score`: `0.49`
- `finance_gate_pass`: `true`
- `one_next_cycle_action`: After the new 8 GB / 2 vCPU / 160 GB box validates cleanly, load btc5:grid_d0.00005_up0.48_down0.51 in shadow, regenerate runtime truth, run the first candidate scan, confirm order_failed_rate_recent_40 <= 0.25, and then require two consecutive cycles with executed_notional_usd > 0 and candidate_to_trade_conversion > 0 before any live-size change.
