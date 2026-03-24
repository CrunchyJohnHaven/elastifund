# Strategy Docs Index

This index is the canonical entrypoint for `docs/strategy/`.

## Naming Convention

- Canonical strategy docs use lowercase `snake_case`.
- Suffixes indicate purpose:
  - `_build_spec.md` = active implementation spec
  - `_acceptance_criteria.md` = promotion and gate rules
  - `_background.md` = research context, not execution contract
  - `_historical.md` = superseded planning/history
- Legacy mixed-case or hyphenated filenames are kept as compatibility pointers when needed.

## Active Build Spec

- `edge_discovery_system.md` (canonical pipeline build spec)
- `llm_ensemble_build_spec.md`
- `smart_wallet_build_spec.md`
- `combinatorial_arb_implementation_deep_dive.md`
- `risk_framework_correlated_binaries.md`
- `resolution_rule_edge_playbook.md`
- `tail_calibration_harness.md`

## Acceptance Criteria

- `edge_promotion_acceptance_criteria.md`

## Background Research

- `flywheel_strategy.md`
- `market_selection_map_background.md`
- `llm_probability_calibration_background.md`
- `monte_carlo_simulation_background.md`
- `polymarket_llm_bot_background.md`
- `polymarket_backtesting_background.md`
- `prediction_market_fund_background.md`
- `system_design_research_v1_0_0_background.md`

## Historical Analysis

- `STRATEGY_REPORT.md` (legacy path kept for script compatibility)
- `polymarket_bot_build_plan_historical.md`

## Artifact Contracts Used By Active Strategy Docs

- `FAST_TRADE_EDGE_ANALYSIS.md` (human-readable current edge status)
- `reports/run_<timestamp>_metrics.json` and `reports/run_<timestamp>_summary.md` (per-run outputs)
- `reports/remote_cycle_status.json` and `reports/remote_service_status.json` (live posture machine truth)
- `research/edge_backlog_ranked.md` (current backlog ranking)
