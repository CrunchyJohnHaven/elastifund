# flywheel

## Responsibility
- Owns control-plane policy execution from cycle packet input to stored findings/tasks and report artifacts.
- Translates deployment snapshots into promotion decisions under policy and guardrails.
- Handles cross-peer improvement exchange, incentives, resilience checks, and scorecard reporting.

## Canonical Naming
- `cycle_packet`: input JSON for one control-plane cycle (`cycle_key` + `strategies`).
- `snapshot`: deployment evidence attached to one strategy deployment in the packet.
- `decision`: policy outcome (promote/demote/hold/kill) persisted as a promotion decision row.
- `finding` and `task`: structured outputs for operator follow-up.

## Compatibility Aliases
- `build_payload_from_bot_db` -> `build_cycle_packet_from_bot_db`.
- `write_payload` -> `write_cycle_packet`.
- `build_payload_from_config` -> `build_cycle_packet_from_config`.
- `load_payload` -> `load_cycle_packet`.

## Naming Guard
- Run `python3 -m data_layer flywheel-naming-check` to enforce that cycle-packet paths avoid ambiguous `payload` identifiers outside compatibility aliases.

## Boundary Contract
- Uses `data_layer/` for persistence.
- Consumes candidate/routing outputs produced by `orchestration/`.
- Exposes results through `hub/` APIs and report artifacts.
