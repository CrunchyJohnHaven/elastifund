# Constraint Arb Shadow Report

Requested window: last 14 day(s)

## Summary

- Violations logged: 4
- Unique events: 4
- Actual observed span: 2026-03-09T12:30:48+00:00 -> 2026-03-09T12:30:48+00:00 (0.0000 day(s))
- A-6 lane definition: neg_risk_sum only (current settlement path: hold_to_resolution)
- A-6 episode count: 4
- A-6 episode median duration: 0.0s
- Settlement ops: 0/0 successful
- Avg settlement cost (if any): 0.0000
- Theoretical PnL: 0.302000
- Realized PnL: 0.000000
- Capture ratio: 0.00%
- Avg semantic confidence: 0.540
- Avg gross edge: 0.0755
- Avg slippage estimate: 0.0203
- Avg VPIN at decision: 0.0000
- VPIN veto count: 0

## Sum-Violation Backtest

- Basis: shadow captures only. Modeled net edge uses `score = gross_edge - slippage_est - fill_risk - semantic_penalty`.
- Episode modes observed: neg_risk_sum=4
- Same-event sum observations: 4 raw / 4 tradable after coverage filter
- Complete-basket underrounds: 0
- Modeled net-positive opportunities: 0/4 (0.00%)
- Avg modeled net edge: -0.4103

| gross_edge bin | observations | unique events | modeled net-positive | avg gross_edge | avg modeled net edge |
| --- | ---: | ---: | ---: | ---: | ---: |
| <5% | 1 | 1 | 0 | 0.0330 | -0.3880 |
| 5-10% | 2 | 2 | 0 | 0.0675 | -0.4805 |
| 10-20% | 1 | 1 | 0 | 0.1340 | -0.2920 |

## Kill Gate

- Rule: kill A-6 on day 14 if fewer than 5 unique qualifying same-event sum events are detected.
- Status: IN PROGRESS
- Qualifying events so far: 0
- Observation progress: 0.0000/14.0 day(s)

## Attribution Table

| violation_id | event_id | relation_type | semantic_confidence | gross_edge | score | slippage_est | vpin | action | sum_yes_ask | complete_basket | theoretical_pnl | realized_pnl |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: |
| 463728d9b3c33c0381cb | 24383 | same_event_sum | 0.600 | 0.1340 | -0.2920 | 0.0180 | 0.0000 | unwind_basket | 1.1340 | True | 0.134000 | 0.000000 |
| 92f5077f73ad09d6af84 | 48295 | same_event_sum | 0.520 | 0.0760 | -0.4330 | 0.0210 | 0.0000 | unwind_basket | 1.0760 | True | 0.076000 | 0.000000 |
| be64a413dea454c8570a | 48297 | same_event_sum | 0.440 | 0.0590 | -0.5280 | 0.0240 | 0.0000 | unwind_basket | 1.0590 | True | 0.059000 | 0.000000 |
| 246343d9c7f315d19bf0 | 48299 | same_event_sum | 0.600 | 0.0330 | -0.3880 | 0.0180 | 0.0000 | unwind_basket | 1.0330 | True | 0.033000 | 0.000000 |
