# Constraint Arb Shadow Report

Requested window: last 14 day(s)

## Summary

- Violations logged: 12
- Unique events: 4
- Actual observed span: 2026-03-22T23:30:14+00:00 -> 2026-03-22T23:31:23+00:00 (0.0008 day(s))
- A-6 lane definition: neg_risk_sum only (current settlement path: hold_to_resolution)
- A-6 episode count: 4
- A-6 episode median duration: 69.0s
- Settlement ops: 0/0 successful
- Avg settlement cost (if any): 0.0000
- Theoretical PnL: 0.979000
- Realized PnL: 0.000000
- Capture ratio: 0.00%
- Avg semantic confidence: 0.560
- Avg gross edge: 0.0816
- Avg slippage estimate: 0.0195
- Avg VPIN at decision: 0.0000
- VPIN veto count: 0

## Sum-Violation Backtest

- Basis: shadow captures only. Modeled net edge uses `score = gross_edge - slippage_est - fill_risk - semantic_penalty`.
- Episode modes observed: neg_risk_sum=4
- Same-event sum observations: 12 raw / 5 tradable after coverage filter
- Complete-basket underrounds: 0
- Modeled net-positive opportunities: 0/5 (0.00%)
- Avg modeled net edge: -0.4012

| gross_edge bin | observations | unique events | modeled net-positive | avg gross_edge | avg modeled net edge |
| --- | ---: | ---: | ---: | ---: | ---: |
| <5% | 3 | 2 | 0 | 0.0373 | -0.4683 |
| 10-20% | 2 | 2 | 0 | 0.1255 | -0.3005 |

## Kill Gate

- Rule: kill A-6 on day 14 if fewer than 5 unique qualifying same-event sum events are detected.
- Status: IN PROGRESS
- Qualifying events so far: 0
- Observation progress: 0.0008/14.0 day(s)

## Attribution Table

| violation_id | event_id | relation_type | semantic_confidence | gross_edge | score | slippage_est | vpin | action | sum_yes_ask | complete_basket | theoretical_pnl | realized_pnl |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: |
| 2beea63d836119a99049 | 48298 | same_event_sum | 0.600 | 0.1310 | -0.2950 | 0.0180 | 0.0000 | unwind_basket | 1.1310 | True | 0.131000 | 0.000000 |
| 1fb6f3f9616a01f230cb | 24383 | same_event_sum | 0.600 | 0.1200 | -0.3060 | 0.0180 | 0.0000 | unwind_basket | 1.1200 | True | 0.120000 | 0.000000 |
| 59cd12cddaeef204bd0d | 48295 | same_event_sum | 0.520 | 0.0360 | -0.4680 | 0.0210 | 0.0000 | unwind_basket | 1.0360 | True | 0.036000 | 0.000000 |
| 13173d849c42608e978b | 48300 | same_event_sum | 0.520 | 0.0380 | -0.4710 | 0.0210 | 0.0000 | unwind_basket | 1.0380 | True | 0.038000 | 0.000000 |
| 375c9b34f5e900ebf57f | 48298 | same_event_sum | 0.600 | 0.1310 | -0.2950 | 0.0180 | 0.0000 | unwind_basket | 1.1310 | True | 0.131000 | 0.000000 |
| 2ca8feba7fd9527c241a | 24383 | same_event_sum | 0.600 | 0.1200 | -0.3060 | 0.0180 | 0.0000 | unwind_basket | 1.1200 | True | 0.120000 | 0.000000 |
| e4b44452c15c60784c86 | 48295 | same_event_sum | 0.520 | 0.0380 | -0.4660 | 0.0210 | 0.0000 | unwind_basket | 1.0380 | True | 0.038000 | 0.000000 |
| c68febb8ca42244cb5f1 | 48300 | same_event_sum | 0.520 | 0.0380 | -0.4710 | 0.0210 | 0.0000 | unwind_basket | 1.0380 | True | 0.038000 | 0.000000 |
| 5c3c87c57a6a2b9079e7 | 48298 | same_event_sum | 0.600 | 0.1310 | -0.2950 | 0.0180 | 0.0000 | unwind_basket | 1.1310 | True | 0.131000 | 0.000000 |
| f942da7ff3c74653ad55 | 24383 | same_event_sum | 0.600 | 0.1200 | -0.3060 | 0.0180 | 0.0000 | unwind_basket | 1.1200 | True | 0.120000 | 0.000000 |
| 4bb230a14aac79c7fb97 | 48295 | same_event_sum | 0.520 | 0.0380 | -0.4660 | 0.0210 | 0.0000 | unwind_basket | 1.0380 | True | 0.038000 | 0.000000 |
| 82012b6931888f1b74e1 | 48300 | same_event_sum | 0.520 | 0.0380 | -0.4710 | 0.0210 | 0.0000 | unwind_basket | 1.0380 | True | 0.038000 | 0.000000 |
