# Instance 1 Launch Packet Dispatch

## Canonical Verdict
- Posture: blocked
- Allow execution: False
- Live launch blocked: True
- Cycle lock: `hold_repair` until snapshot is `available` and cutover validation passes

## Four Statuses
- `snapshot_pending`: true (AWS CLI unavailable here; snapshot state not yet verified as `available`)
- `ready_for_cutover`: false
- `manual_close_ready_now`: true (from `reports/nontrading_cycle_packet.json`)
- `parked_lane`: true (`kalshi_weather_bracket` parked)

## Old-Box Lock
- Keep old box blocked: no service restart, no package load, no live trading, no partial-recovery work

## Cutover Checklist (strict)
1. `snapshot_gate` (`snapshot_state == available`)
2. `firewall_recreation` (required custom firewall rules present)
3. `static_ip_attach` (static IP bound to new instance)
4. `disk_headroom` (`root_free_gb >= 30` and `root_use_percent < 82`)
5. `service_start` (`jj-live.service` active, no crash loop)
6. `runtime_truth_regeneration` (`reports/runtime_truth_latest.json` and `reports/public_runtime_snapshot.json` regenerate cleanly)
7. `package_load_confirmation` (`runtime_package_load_pending=false` and `runtime_package_loaded=true`)

## Durable Disk Guardrail
- If `root_free_gb < 30` or `root_use_percent >= 82`, launch must self-block again and emit `hold_repair` with `+10m` retry

## Required Outputs
- `candidate_delta_arr_bps`: 248262402.09
- `expected_improvement_velocity_delta`: 0.0
- `arr_confidence_score`: 0.49
- `finance_gate_pass`: true
- `one_next_cycle_action`: hold_repair: keep old box blocked, verify snapshot reaches available, then run cutover checks (firewall -> static IP -> disk headroom -> service start -> runtime truth regen -> package load) with +10m retry cadence until clear.

Machine artifact: `reports/parallel/instance1_launch_packet_latest.json`
