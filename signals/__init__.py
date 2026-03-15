"""Signal computation packages used by trading orchestrators.

Boundary:
- `signals/` computes reusable, market-derived signal state.
- It does not own strategy policy thresholds or order-routing side effects.

Entrypoints:
- `signals.sum_violation`: A-6 sum/guaranteed-dollar signal components.
- `signals.dep_graph`: B-1 dependency-graph signal components.
"""
