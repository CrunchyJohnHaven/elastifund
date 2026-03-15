"""Execution primitives for multi-leg structural arbitrage.

Boundary:
- `execution/` owns fill/state transitions and lifecycle modeling.
- It does not decide if a strategy should trade; it executes submitted plans.
"""
