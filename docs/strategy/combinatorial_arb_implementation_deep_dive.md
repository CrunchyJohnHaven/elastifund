# Combinatorial Arbitrage Implementation Deep Dive

**Updated:** 2026-03-07  
**Scope:** A-6 multi-outcome sum violations and B-1 dependency-graph arbitrage  
**Status:** Core scaffolding landed; live `jj_live.py` routing is still pending

## Landed in this pass

- A-6 event discovery is now first-class and reusable through [signals/sum_violation/sum_discovery.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_discovery.py).
- A-6 404 handling is now persisted in [data/a6_quarantine_tokens.json](/Users/johnbradley/Desktop/Elastifund/data/a6_quarantine_tokens.json) via [signals/sum_violation/sum_state.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_state.py).
- A-6 monitoring and execution planning now exist as separate modules:
  [signals/sum_violation/sum_monitor.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_monitor.py)
  [signals/sum_violation/sum_executor.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_executor.py)
- Shared market/user websocket cache wrappers now exist in:
  [infra/ws_market_cache.py](/Users/johnbradley/Desktop/Elastifund/infra/ws_market_cache.py)
  [infra/ws_user_orders.py](/Users/johnbradley/Desktop/Elastifund/infra/ws_user_orders.py)
- B-1 candidate pruning, cache, validation, monitoring, and planning now exist in:
  [signals/dep_graph/dep_candidate_pairs.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_candidate_pairs.py)
  [signals/dep_graph/dep_graph_store.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_graph_store.py)
  [signals/dep_graph/dep_haiku_classifier.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_haiku_classifier.py)
  [signals/dep_graph/dep_validation.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_validation.py)
  [signals/dep_graph/dep_monitor.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_monitor.py)
  [signals/dep_graph/dep_executor.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_executor.py)
- Linked-leg persistence now lives in [bot/jj_live.py](/Users/johnbradley/Desktop/Elastifund/bot/jj_live.py) and [jj_state.json](/Users/johnbradley/Desktop/Elastifund/jj_state.json).

## Current repo mapping

| Concern | Repo file | State |
| --- | --- | --- |
| A-6 event discovery + batched `/prices` | [signals/sum_violation/sum_discovery.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_discovery.py) | Landed |
| A-6 quarantine persistence | [signals/sum_violation/sum_state.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_state.py) | Landed |
| A-6 monitor | [signals/sum_violation/sum_monitor.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_monitor.py) | Landed |
| Shared multi-leg state machine | [execution/multileg_executor.py](/Users/johnbradley/Desktop/Elastifund/execution/multileg_executor.py) | Landed before this pass |
| A-6 basket planning | [signals/sum_violation/sum_executor.py](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/sum_executor.py) | Landed |
| Shared market quote cache | [infra/ws_market_cache.py](/Users/johnbradley/Desktop/Elastifund/infra/ws_market_cache.py) | Landed |
| Shared user order cache | [infra/ws_user_orders.py](/Users/johnbradley/Desktop/Elastifund/infra/ws_user_orders.py) | Landed |
| B-1 candidate pruning | [signals/dep_graph/dep_candidate_pairs.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_candidate_pairs.py) | Landed |
| B-1 graph cache | [signals/dep_graph/dep_graph_store.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_graph_store.py) | Landed |
| B-1 prompt contract | [signals/dep_graph/dep_haiku_classifier.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_haiku_classifier.py) | Landed |
| B-1 validation harness | [signals/dep_graph/dep_validation.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_validation.py) | Landed |
| B-1 live monitor | [signals/dep_graph/dep_monitor.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_monitor.py) | Landed |
| B-1 execution planner | [signals/dep_graph/dep_executor.py](/Users/johnbradley/Desktop/Elastifund/signals/dep_graph/dep_executor.py) | Landed |
| Live structural-arb routing | [bot/jj_live.py](/Users/johnbradley/Desktop/Elastifund/bot/jj_live.py) | Still pending |

## Immediate task list

- [x] Use Gamma `/events` as the canonical A-6 discovery surface.
- [x] Prefer batched CLOB `/prices` with `/book` fallback only when quotes are missing.
- [x] Persist 404/no-orderbook failures with exponential backoff.
- [x] Add shared websocket cache wrappers for market quotes and user-order events.
- [x] Reuse the shared multi-leg state machine for A-6 and B-1 planning.
- [x] Extend `jj_state.json` with `linked_legs`, `a6_state`, and `b1_state`.
- [x] Add deterministic B-1 candidate pruning, cache, prompt contract, and validation harness.
- [ ] Wire A-6/B-1 into `bot/jj_live.py` as actual signal sources with order posting.
- [ ] Add live batch order posting with `postOnly=true`, `OrderType.GTC`, and rollback handling.
- [ ] Build and label the 50-pair B-1 gold set.
- [ ] Add merge/conversion plumbing for complete neg-risk baskets after contract verification.

## Remaining blockers before live promotion

- `bot/jj_live.py` still operates on single-market posting paths; the structural-arb planners are not yet connected to live order placement.
- The B-1 classifier module has the prompt/parser contract and cache, but not a live Anthropic transport wired into the runtime loop.
- The validation harness exists, but the actual 50-pair reviewed gold set has not been produced.
- Merge/redeem capital-release logic is still absent.

## Verification

- Targeted arbitrage test slice passed on 2026-03-07:
  `python3 -m pytest tests/test_a6_runtime_components.py tests/test_dep_graph_components.py tests/test_sum_violation_scanner.py tests/test_constraint_graph.py tests/test_arb_execution_partial_fill.py tests/test_neg_risk_filters.py tests/test_constraint_runtime.py -q`
