# Combinatorial Arb Implementation Deep Dive

**Updated:** 2026-03-07  
**Scope:** A-6 multi-outcome sum violations and B-1 dependency-graph arbitrage  
**Status:** Core scaffolding landed; live `jj_live.py` routing is still pending

## Landed in this pass

- A-6 discovery is event-based through [`bot/sum_violation_scanner.py`](/Users/johnbradley/Desktop/Elastifund/bot/sum_violation_scanner.py) and reusable watchlist logic in [`strategies/a6_sum_violation.py`](/Users/johnbradley/Desktop/Elastifund/strategies/a6_sum_violation.py).
- Quote ingestion is WebSocket-first through [`infra/clob_ws.py`](/Users/johnbradley/Desktop/Elastifund/infra/clob_ws.py), with REST `/prices` fallback and hard 404 no-orderbook blocking in the scanner.
- Execution-aware sum violations now log `maker_sum_bid`, `sum_yes_ask`, liquidity gates, complete-basket status, and execute readiness through [`bot/constraint_arb_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/constraint_arb_engine.py).
- Shared maker-only multi-leg state handling now lives in [`execution/multileg_executor.py`](/Users/johnbradley/Desktop/Elastifund/execution/multileg_executor.py).
- B-1 graph cache, candidate pruning, and prompt scaffolding now live in [`strategies/b1_dependency_graph.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_dependency_graph.py) with live maker-executable checks in [`strategies/b1_violation_monitor.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_violation_monitor.py).

## Current repo mapping

| Concern | Repo file | State |
| --- | --- | --- |
| A-6 event discovery | [`bot/sum_violation_scanner.py`](/Users/johnbradley/Desktop/Elastifund/bot/sum_violation_scanner.py) | Landed |
| A-6 watchlist + liquidity gates | [`strategies/a6_sum_violation.py`](/Users/johnbradley/Desktop/Elastifund/strategies/a6_sum_violation.py) | Landed |
| Shared market/user quote transport | [`infra/clob_ws.py`](/Users/johnbradley/Desktop/Elastifund/infra/clob_ws.py) | Landed |
| Shared multi-leg state machine | [`execution/multileg_executor.py`](/Users/johnbradley/Desktop/Elastifund/execution/multileg_executor.py) | Landed |
| Structural-arb scoring + shadow reporting | [`bot/constraint_arb_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/constraint_arb_engine.py) | Landed |
| B-1 graph cache + prompt scaffold | [`strategies/b1_dependency_graph.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_dependency_graph.py) | Landed |
| B-1 live violation monitor | [`strategies/b1_violation_monitor.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_violation_monitor.py) | Landed |
| Live structural-arb routing | [`bot/jj_live.py`](/Users/johnbradley/Desktop/Elastifund/bot/jj_live.py) | Pending |

## Remaining blockers before live promotion

- `bot/jj_live.py` still posts single-market orders; structural-arb orders are not yet routed through the live execution path.
- The user-channel websocket client exists, but live fill/cancel handling is not yet wired into the multi-leg executor.
- The B-1 graph builder has the prompt/cache contract, but not a live classifier transport or a hand-labeled 50-pair gold set.
- Neg-risk conversion/merge plumbing for capital recycling is still pending contract/fee verification.

## Verification

- Targeted strategy/infrastructure suite passed on 2026-03-07:
  `PYTHONPATH=. pytest -q tests/test_sum_violation_scanner.py tests/test_clob_ws.py tests/test_multileg_executor.py tests/test_a6_strategy.py tests/test_b1_dependency_graph.py tests/test_b1_violation_monitor.py tests/test_constraint_graph.py tests/test_neg_risk_filters.py tests/test_arb_execution_partial_fill.py`
