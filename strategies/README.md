# Strategies Package Map

`strategies/` defines strategy policy objects and domain semantics.

## Modules

- `strategies/a6_sum_violation.py`: A-6 watchlist parsing and opportunity model.
- `strategies/b1_dependency_graph.py`: B-1 dependency graph construction model.
- `strategies/b1_templates.py`: template pairing helpers for B-1 lanes.
- `strategies/b1_violation_monitor.py`: B-1 violation-monitor strategy policy.
- `strategies/alpaca_crypto_momentum.py`: first-trade Alpaca crypto momentum lane with
  bootstrap sizing, posterior gating, and learning-state helpers.
- `strategies/kalshi_longshot_fade.py`: tail-calibration policy for objective-rule
  Kalshi longshot-fade baskets, paired with `docs/strategy/tail_calibration_harness.md`.

## Boundary Rules

- Strategy modules define what qualifies as an opportunity.
- Runtime orchestration and scheduler loops belong in `bot/`.
- Fill state machines and order lifecycle transitions belong in `execution/`.
