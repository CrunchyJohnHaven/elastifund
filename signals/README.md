# Signals Package Map

`signals/` contains reusable signal components shared by orchestrators.

## Subpackages

- `signals/sum_violation/`: A-6 discovery, state tracking, and execution-plan
  builders for sum-violation and guaranteed-dollar opportunities.
- `signals/dep_graph/`: B-1 candidate generation, relation scaffolding, graph
  storage, and validation helpers.
- `signals/tail_bins.py`: pre-registered tail-bin definitions, posterior shrinkage,
  and robust Kelly helpers for tail-calibration experiments.
- `signals/fee_models.py`: venue fee math for Kalshi and Polymarket so strategies
  can reason about tradable, fee-adjusted probabilities.
- `signals/resolution_risk.py`: objective-rule and settlement-risk scoring for
  tail and near-certain strategies.

## Boundary Rules

- `signals/` computes and transforms market-derived signal data.
- `signals/` should not own runtime loops, order submission, or treasury policy.
- Strategy thresholds and promotion policy belong in `strategies/`.
