# Combinatorial Arb Implementation Deep Dive

**Updated:** 2026-03-07  
**Scope:** A-6 multi-outcome sum violations and B-1 dependency-graph arbitrage  
**Status:** Research ingest landed; live `jj_live.py` routing is still pending

## Lane definition

- **Current A-6 lane:** `neg_risk_sum` only. This repo currently targets multi-condition neg-risk YES baskets that are held to resolution or later conversion. It does **not** yet implement the separate binary YES+NO Dutch-book merge lane.
- **Current B-1 lane:** implication / exclusion monitoring only. Conditional chains and full complement routing remain out of scope until the gold set is labeled and the live monitor proves violation frequency.

## Landed in this pass

- A-6 discovery is event-based through [`bot/sum_violation_scanner.py`](/Users/johnbradley/Desktop/Elastifund/bot/sum_violation_scanner.py) and reusable watchlist logic in [`strategies/a6_sum_violation.py`](/Users/johnbradley/Desktop/Elastifund/strategies/a6_sum_violation.py).
- The shared quote store in [`infra/clob_ws.py`](/Users/johnbradley/Desktop/Elastifund/infra/clob_ws.py) now preserves `tick_size_change` events instead of only best bid/ask.
- Structural-arb persistence in [`bot/constraint_arb_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/constraint_arb_engine.py) now includes dedicated telemetry tables for scan snapshots, A-6 episodes, order groups/legs, settlement ops, and latency samples.
- The empirical snapshot runner in [`scripts/arb_empirical_analysis.py`](/Users/johnbradley/Desktop/Elastifund/scripts/arb_empirical_analysis.py) now consumes the new telemetry and emits execution tasks tied to the actual gating metrics.

## Research-driven gating model

Promotion is now defined around three measurements, not generic "shadow mode" language:

1. **Maker-fill curve:** can small passive orders complete often enough to make multi-leg baskets viable?
2. **Violation half-life:** do A-6/B-1 mispricings persist long enough for the routing path to matter?
3. **Settlement path:** can merge / redeem / convert operations actually be executed and confirmed?

If those three are not measured, the lane is still research, even if the scanner looks clean.

## Current repo mapping

| Concern | Repo file | State |
| --- | --- | --- |
| A-6 event discovery | [`bot/sum_violation_scanner.py`](/Users/johnbradley/Desktop/Elastifund/bot/sum_violation_scanner.py) | Landed |
| A-6 watchlist + liquidity gates | [`strategies/a6_sum_violation.py`](/Users/johnbradley/Desktop/Elastifund/strategies/a6_sum_violation.py) | Landed |
| Shared market/user quote transport | [`infra/clob_ws.py`](/Users/johnbradley/Desktop/Elastifund/infra/clob_ws.py) | Landed |
| Shared multi-leg state machine | [`execution/multileg_executor.py`](/Users/johnbradley/Desktop/Elastifund/execution/multileg_executor.py) | Landed |
| Structural-arb scoring + telemetry schema | [`bot/constraint_arb_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/constraint_arb_engine.py) | Landed |
| Empirical gating report | [`scripts/arb_empirical_analysis.py`](/Users/johnbradley/Desktop/Elastifund/scripts/arb_empirical_analysis.py) | Landed |
| B-1 graph cache + prompt scaffold | [`strategies/b1_dependency_graph.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_dependency_graph.py) | Landed |
| B-1 live violation monitor | [`strategies/b1_violation_monitor.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_violation_monitor.py) | Landed |
| Live structural-arb routing | [`bot/jj_live.py`](/Users/johnbradley/Desktop/Elastifund/bot/jj_live.py) | Pending |

## What this pass explicitly did not claim

- It did **not** prove the maker-fill curve. The proxy is better instrumented, but actual order-queue outcomes still need a timed shadow run.
- It did **not** prove settlement. The schema and reporting are ready, but the repo still needs confirmed merge / redeem / convert rows in `arb_settlement_op`.
- It did **not** promote B-1. The default implication threshold is now more conservative, but the gold set and precision gate remain incomplete.

## Remaining blockers before live promotion

- `bot/jj_live.py` still logs structural-arb baskets as shadow or blocked records; live order-group and per-leg persistence are not wired.
- The user-channel websocket path exists, but live fill/cancel events are not yet feeding the new `arb_order_group` / `arb_order_leg` tables.
- The B-1 graph builder still needs the hand-labeled 50-pair gold set plus an 85% precision gate before promotion.
- Binary Dutch-book A-6 remains a separate backlog item until the CTF merge path is implemented and tested as its own lane.

## Verification

- Targeted suite after the research-ingest changes:
  `PYTHONPATH=. pytest -q tests/test_clob_ws.py tests/test_a6_strategy.py tests/test_constraint_graph.py tests/test_arb_empirical_analysis.py tests/test_sum_violation_scanner.py`
