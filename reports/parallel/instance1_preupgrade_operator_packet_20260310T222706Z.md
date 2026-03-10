# Instance 1 Pre-Upgrade Operator Packet

- `snapshot_pending`: true
- `ready_for_cutover`: false
- `manual_close_ready_now`: true
- `parked_lane`: true (`kalshi_weather_bracket`)

No deployment, no service restart, no live trading. Old box remains blocked until snapshot is explicitly `available` and cutover checks pass.
