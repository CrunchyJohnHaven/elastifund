# Combinatorial Arb Implementation Deep Dive

**Updated:** 2026-03-07  
**Scope:** A-6 guaranteed-dollar ranking in neg-risk events and B-1 templated dependency arbitrage  
**Status:** The stack is explicitly gated by live executable density. Broad buildout is paused behind the empirical gate.

## Lane definition

- **Current A-6 lane:** guaranteed-dollar inside neg-risk events. The scanner ranks full-event YES baskets against two-leg YES+NO straddles and keeps augmented events only when unsafe `Other` legs can be filtered out.
- **Current B-1 lane:** implication / exclusion monitoring for narrow deterministic families first. Conditional chains and broad open-world graph expansion remain out of scope until the gold set is labeled and live density is proven.

## Landed in this pass

- A-6 discovery is event-based through [`bot/sum_violation_scanner.py`](/Users/johnbradley/Desktop/Elastifund/bot/sum_violation_scanner.py) and reusable watchlist logic in [`strategies/a6_sum_violation.py`](/Users/johnbradley/Desktop/Elastifund/strategies/a6_sum_violation.py).
- The shared quote store in [`infra/clob_ws.py`](/Users/johnbradley/Desktop/Elastifund/infra/clob_ws.py) now preserves `tick_size_change` events instead of only best bid/ask.
- Structural-arb persistence in [`bot/constraint_arb_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/constraint_arb_engine.py) includes dedicated telemetry tables for scan snapshots, A-6 episodes, order groups/legs, settlement ops, and latency samples.
- The empirical snapshot runner in [`scripts/arb_empirical_analysis.py`](/Users/johnbradley/Desktop/Elastifund/scripts/arb_empirical_analysis.py) consumes the telemetry and emits execution tasks tied to actual gating metrics.
- Quote ingestion remains WebSocket-first, with REST `/prices` fallback and hard 404 no-orderbook blocking in the scanner.
- Top-of-book guaranteed-dollar ranking now lives in [`signals/sum_violation/guaranteed_dollar.py`](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/guaranteed_dollar.py).
- Repo-level A-6 execution gating now also lives in [`bot/execution_readiness.py`](/Users/johnbradley/Desktop/Elastifund/bot/execution_readiness.py) and the scanner surfaces straddles vs baskets directly from [`bot/a6_sum_scanner.py`](/Users/johnbradley/Desktop/Elastifund/bot/a6_sum_scanner.py).
- B-1 graph cache and residual LLM scaffolding remain in place, while deterministic family matching now lives in [`strategies/b1_templates.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_templates.py) and [`bot/b1_template_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/b1_template_engine.py).
- Gold-set generation now emits template-family compatibility matrices through [`scripts/build_b1_gold_set.py`](/Users/johnbradley/Desktop/Elastifund/scripts/build_b1_gold_set.py).

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
| A-6 watchlist + augmented filtering | [`strategies/a6_sum_violation.py`](/Users/johnbradley/Desktop/Elastifund/strategies/a6_sum_violation.py) | Landed |
| A-6 guaranteed-dollar ranker | [`signals/sum_violation/guaranteed_dollar.py`](/Users/johnbradley/Desktop/Elastifund/signals/sum_violation/guaranteed_dollar.py) | Landed |
| A-6 execution readiness | [`bot/execution_readiness.py`](/Users/johnbradley/Desktop/Elastifund/bot/execution_readiness.py) | Landed |
| Structural-arb scoring + telemetry schema | [`bot/constraint_arb_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/constraint_arb_engine.py) | Landed |
| Empirical gating report | [`scripts/arb_empirical_analysis.py`](/Users/johnbradley/Desktop/Elastifund/scripts/arb_empirical_analysis.py) | Landed |
| B-1 graph cache + prompt scaffold | [`strategies/b1_dependency_graph.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_dependency_graph.py) | Landed |
| B-1 live violation monitor | [`strategies/b1_violation_monitor.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_violation_monitor.py) | Landed |
| B-1 deterministic template engines | [`strategies/b1_templates.py`](/Users/johnbradley/Desktop/Elastifund/strategies/b1_templates.py), [`bot/b1_template_engine.py`](/Users/johnbradley/Desktop/Elastifund/bot/b1_template_engine.py) | Landed |
| Live structural-arb routing | [`bot/jj_live.py`](/Users/johnbradley/Desktop/Elastifund/bot/jj_live.py) | Pending |

## Empirical gate status

- The live-public-data A-6 audit in [`reports/guaranteed_dollar_audit.md`](/Users/johnbradley/Desktop/Elastifund/reports/guaranteed_dollar_audit.md) found **92** allowed neg-risk events and **0** constructions below the initial `0.95` cost gate.
- The live-public-data B-1 audit in [`reports/b1_template_audit.md`](/Users/johnbradley/Desktop/Elastifund/reports/b1_template_audit.md) found **0** deterministic template pairs in the first **1,000** active allowed markets.

## What this pass explicitly did not claim

- It did **not** prove the maker-fill curve. The proxy is better instrumented, but actual order-queue outcomes still need a timed shadow run.
- It did **not** prove settlement. The schema and reporting are ready, but the repo still needs confirmed merge / redeem / convert rows in `arb_settlement_op`.
- It did **not** promote B-1. The default implication threshold is now more conservative, but the gold set and precision gate remain incomplete.

## Remaining blockers before live promotion

- `bot/jj_live.py` still logs structural-arb baskets as shadow or blocked records; live order-group and per-leg persistence are not fully wired.
- The user-channel websocket path exists, but the missing proof is fill behavior, not code volume. We need a narrow fill/dwell study first.
- The B-1 graph builder has prompt/cache infrastructure, but current live density does not justify broad expansion. One family-specific gold set is the correct next step.
- Neg-risk conversion/merge plumbing for capital recycling is still pending contract/fee verification, and merge economics only matter if the entry gate is ever passed.

## Verification

- Targeted suite after the research-ingest changes:
  `PYTHONPATH=. pytest -q tests/test_clob_ws.py tests/test_a6_strategy.py tests/test_constraint_graph.py tests/test_arb_empirical_analysis.py tests/test_sum_violation_scanner.py`
