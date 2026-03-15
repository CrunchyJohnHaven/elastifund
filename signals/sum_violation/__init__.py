"""A-6 signal helpers: discovery, ranking, and execution planning.

This package is intentionally component-level:
- discovery/state modules gather and normalize market inputs.
- planning modules convert opportunities into executable leg plans.

Orchestration belongs in `bot/` and policy logic belongs in `strategies/`.
"""
