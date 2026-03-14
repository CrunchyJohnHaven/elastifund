# Execution Package Map

`execution/` owns execution-state and lifecycle primitives for multi-leg orders.

## Modules

- `execution/multileg_executor.py`: basket state transitions, command planning,
  and fill application for coordinated multi-leg attempts.
- `execution/shadow_order_lifecycle.py`: shadow-mode order lifecycle tracking,
  dedupe windows, markout reporting, and status rollups.

## Boundary Rules

- `execution/` executes provided plans; it does not select opportunities.
- Signal discovery belongs in `signals/`.
- Strategy policy thresholds belong in `strategies/`.
- Runtime wiring and external side effects belong in `bot/`.
