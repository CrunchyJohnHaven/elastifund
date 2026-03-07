# Constraint Arb Shadow Report

Requested window: last 14 day(s)

## Summary

- Violations logged: 44
- Unique events: 15
- Actual observed span: 2026-03-07T18:49:58+00:00 -> 2026-03-07T20:11:41+00:00 (0.0567 day(s))
- A-6 lane definition: neg_risk_sum only (current settlement path: hold_to_resolution)
- A-6 episode count: 5
- A-6 episode median duration: 0.0s
- Settlement ops: 0/0 successful
- Avg settlement cost (if any): 0.0000
- Theoretical PnL: 11.545002
- Realized PnL: 0.000000
- Capture ratio: 0.00%
- Avg semantic confidence: 0.932
- Avg gross edge: 0.2624
- Avg slippage estimate: 0.0506
- Avg VPIN at decision: 0.0909
- VPIN veto count: 0

## Sum-Violation Backtest

- Basis: shadow captures only. Modeled net edge uses `score = gross_edge - slippage_est - fill_risk - semantic_penalty`.
- Episode modes observed: neg_risk_sum=5
- Same-event sum observations: 44 raw / 24 tradable after coverage filter
- Complete-basket underrounds: 2
- Modeled net-positive opportunities: 10/24 (41.67%)
- Avg modeled net edge: 0.0877

| gross_edge bin | observations | unique events | modeled net-positive | avg gross_edge | avg modeled net edge |
| --- | ---: | ---: | ---: | ---: | ---: |
| <5% | 10 | 7 | 2 | 0.0394 | -0.1162 |
| 5-10% | 6 | 4 | 1 | 0.0607 | -0.1262 |
| 10-20% | 1 | 1 | 1 | 0.1290 | 0.0450 |
| 20%+ | 7 | 3 | 6 | 0.7369 | 0.5683 |

## Kill Gate

- Rule: kill A-6 on day 14 if fewer than 5 unique qualifying same-event sum events are detected.
- Status: IN PROGRESS
- Qualifying events so far: 6
- Observation progress: 0.0567/14.0 day(s)

## Attribution Table

| violation_id | event_id | relation_type | semantic_confidence | gross_edge | score | slippage_est | vpin | action | sum_yes_ask | complete_basket | theoretical_pnl | realized_pnl |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: |
| 3e42efb45abd2925c908 | 24383 | same_event_sum | 0.600 | 0.2630 | -0.1630 | 0.0180 | 0.0000 | unwind_basket | 1.2630 | True | 0.263000 | 0.000000 |
| 9d1e6458043c87326f03 | 48295 | same_event_sum | 0.520 | 0.0640 | -0.4450 | 0.0210 | 0.0000 | unwind_basket | 1.0640 | True | 0.064000 | 0.000000 |
| 31d95498710fadd6c2e6 | 48297 | same_event_sum | 0.440 | 0.0480 | -0.5390 | 0.0240 | 0.0000 | unwind_basket | 1.0480 | True | 0.048000 | 0.000000 |
| 6af8cae137775282b6b7 | 32228 | same_event_sum | 1.000 | 0.0320 | 0.0140 | 0.0150 | 0.0000 | unwind_basket | 1.0320 | True | 0.032001 | 0.000000 |
| ba59ea178bfe852d0510 | 48292 | same_event_sum | 0.520 | 0.0330 | -0.4710 | 0.0210 | 0.0000 | unwind_basket | 1.0330 | True | 0.033000 | 0.000000 |
| 8d4fcd37086e774e0aeb | 16167 | same_event_sum | 0.780 | 0.7970 | 0.5650 | 0.0090 | 0.0000 | watch_yes_basket | 0.2240 | False | 0.797000 | 0.000000 |
| 8b5ed9d3a56888e24076 | 16167 | same_event_sum | 0.780 | 0.7970 | 0.5650 | 0.0090 | 0.0000 | watch_yes_basket | 0.2240 | False | 0.797000 | 0.000000 |
| ae9c26f90b9cb2f49597 | 16167 | same_event_sum | 0.780 | 0.7970 | 0.5650 | 0.0090 | 0.0000 | watch_yes_basket | 0.2240 | False | 0.797000 | 0.000000 |
| 7c21fb2ee4c3caf5e588 | 24383 | same_event_sum | 0.600 | 0.4420 | 0.0160 | 0.0180 | 0.0000 | unwind_basket | 1.4420 | True | 0.442000 | 0.000000 |
| 649d7826d0a588dab34d | 32228 | same_event_sum | 1.000 | 0.0320 | 0.0140 | 0.0150 | 0.0000 | unwind_basket | 1.0320 | True | 0.032001 | 0.000000 |
| 2ec488cdeb8097c365ea | 24383 | same_event_sum | 1.000 | 0.4430 | 0.4220 | 0.0180 | 0.0000 | unwind_basket | 1.4430 | True | 0.443000 | 0.000000 |
| 56454f0c5d1449eb4d93 | 27829 | same_event_sum | 1.000 | 0.0490 | -0.0500 | 0.0960 | 0.0000 | unwind_basket | 1.0490 | True | 0.049000 | 0.000000 |
| dc255f75d73e9b615be5 | 27830 | same_event_sum | 1.000 | 0.0400 | -0.0530 | 0.0900 | 0.0000 | unwind_basket | 1.0400 | True | 0.040000 | 0.000000 |
| c39f69348ccf2c65f816 | 32228 | same_event_sum | 1.000 | 0.0330 | 0.0150 | 0.0150 | 0.0000 | unwind_basket | 1.0330 | True | 0.033000 | 0.000000 |
| 79327cb4113e17e430bb | 32755 | same_event_sum | 1.000 | 0.0440 | -0.0040 | 0.0450 | 0.0000 | unwind_basket | 1.0440 | True | 0.044000 | 0.000000 |
| 8e97aad83bb24500784f | 32756 | same_event_sum | 1.000 | 0.0390 | -0.0090 | 0.0450 | 0.0000 | unwind_basket | 1.0390 | True | 0.039000 | 0.000000 |
| 203dfd2fcb8b05ab89bf | 33506 | same_event_sum | 1.000 | 0.0680 | 0.0140 | 0.0510 | 0.0000 | unwind_basket | 1.0680 | True | 0.068000 | 0.000000 |
| 02ea1c36a159ea7f5b8e | 34436 | same_event_sum | 1.000 | 0.0670 | -0.1130 | 0.1770 | 0.0000 | unwind_basket | 1.0670 | True | 0.067000 | 0.000000 |
| d7235e39d48b04e65f1e | 34582 | same_event_sum | 1.000 | 0.7710 | 0.7380 | 0.0300 | 0.0000 | buy_yes_basket | 0.2290 | True | 0.771000 | 0.000000 |
| cf39bdda8baf98990c06 | 24383 | same_event_sum | 1.000 | 0.4430 | 0.4220 | 0.0180 | 0.0000 | unwind_basket | 1.4430 | True | 0.443000 | 0.000000 |
| 1d69c208bf749eed1ce6 | 27829 | same_event_sum | 1.000 | 0.0500 | -0.0490 | 0.0960 | 0.0000 | unwind_basket | 1.0500 | True | 0.050000 | 0.000000 |
| d7ff4c6c089061d022bf | 27830 | same_event_sum | 1.000 | 0.0400 | -0.0530 | 0.0900 | 0.0000 | unwind_basket | 1.0400 | True | 0.040000 | 0.000000 |
| 99774fad145858bea6fc | 31552 | same_event_sum | 1.000 | 0.1290 | 0.0450 | 0.0810 | 0.0000 | buy_yes_basket | 0.8710 | True | 0.129000 | 0.000000 |
| d6f8e618d9370b3b83c0 | 24383 | same_event_sum | 1.000 | 0.4740 | 0.4530 | 0.0180 | 0.0000 | unwind_basket | 1.4740 |  | 0.474000 | 0.000000 |
| b9e6b748301be734f96f | 27829 | same_event_sum | 1.000 | 0.0510 | -0.0480 | 0.0960 | 0.0000 | unwind_basket | 1.0510 |  | 0.051000 | 0.000000 |
| 46be45a22ef11c1a6ff3 | 27830 | same_event_sum | 1.000 | 0.0410 | -0.0520 | 0.0900 | 0.0000 | unwind_basket | 1.0410 |  | 0.041000 | 0.000000 |
| a7166713296b7dd64e5c | 31552 | same_event_sum | 1.000 | 0.1290 | 0.0450 | 0.0810 | 0.0000 | buy_yes_basket | 0.8710 |  | 0.129000 | 0.000000 |
| 69eeb649812ac6260ef5 | 24383 | same_event_sum | 1.000 | 0.4740 | 0.4530 | 0.0180 | 0.0000 | unwind_basket | 1.4740 |  | 0.474000 | 0.000000 |
| c81a83f9164a01d176cb | 27829 | same_event_sum | 1.000 | 0.0510 | -0.0480 | 0.0960 | 0.0000 | unwind_basket | 1.0510 |  | 0.051000 | 0.000000 |
| 38c02c94a11fa348a5e7 | 27830 | same_event_sum | 1.000 | 0.0410 | -0.0520 | 0.0900 | 0.0000 | unwind_basket | 1.0410 |  | 0.041000 | 0.000000 |
| 0d1e72156099ff52e928 | 32228 | same_event_sum | 1.000 | 0.0330 | 0.0150 | 0.0150 | 0.0000 | unwind_basket | 1.0330 |  | 0.033000 | 0.000000 |
| 2003e95f06508155a434 | 32755 | same_event_sum | 1.000 | 0.0440 | -0.0040 | 0.0450 | 0.0000 | unwind_basket | 1.0440 |  | 0.044000 | 0.000000 |
| d6eedb3b4b5f2ebc4d41 | 32756 | same_event_sum | 1.000 | 0.0350 | -0.0130 | 0.0450 | 0.0000 | unwind_basket | 1.0350 |  | 0.035000 | 0.000000 |
| bdae82e4fff32d13f498 | 33506 | same_event_sum | 1.000 | 0.0680 | 0.0140 | 0.0510 | 0.0000 | unwind_basket | 1.0680 |  | 0.068000 | 0.000000 |
| d0128762fe14a18d531f | 34436 | same_event_sum | 1.000 | 0.0640 | -0.1160 | 0.1770 | 0.0000 | unwind_basket | 1.0640 |  | 0.064000 | 0.000000 |
| bfda7304d8882c27a5fe | 34582 | same_event_sum | 1.000 | 0.7720 | 0.7390 | 0.0300 | 0.0000 | buy_yes_basket | 0.2280 |  | 0.772000 | 0.000000 |
| 4319a00d1cd090d57f65 | 24383 | same_event_sum | 1.000 | 1.9680 | 1.9470 | 0.0180 | 0.5000 | unwind_basket | 2.9680 |  | 1.968000 | 0.000000 |
| b90efaf7e6e8e325a879 | 24383 | same_event_sum | 1.000 | 0.4740 | 0.4530 | 0.0180 | 0.5000 | unwind_basket | 1.4740 |  | 0.474000 | 0.000000 |
| 3bfb48e18377712ffdd9 | 24383 | same_event_sum | 1.000 | 0.4740 | 0.4530 | 0.0180 | 0.5000 | unwind_basket | 1.4740 |  | 0.474000 | 0.000000 |
| 59f62fe270aea63c6f81 | 27829 | same_event_sum | 1.000 | 0.1340 | 0.0710 | 0.0600 | 0.5000 | buy_yes_basket | 0.8660 |  | 0.134000 | 0.000000 |
| c2035a21e87b3b72489d | 24383 | same_event_sum | 1.000 | 0.4740 | 0.4530 | 0.0180 | 0.5000 | unwind_basket | 1.4740 |  | 0.474000 | 0.000000 |
| c445239cc7f79168a333 | 27829 | same_event_sum | 1.000 | 0.0510 | -0.0480 | 0.0960 | 0.5000 | unwind_basket | 1.0510 |  | 0.051000 | 0.000000 |
| fc5a494ff89faca307a2 | 27830 | same_event_sum | 1.000 | 0.0410 | -0.0520 | 0.0900 | 0.5000 | unwind_basket | 1.0410 |  | 0.041000 | 0.000000 |
| 9fc3fb5449deebd05ed9 | 30615 | same_event_sum | 1.000 | 0.1310 | 0.0830 | 0.0450 | 0.5000 | buy_yes_basket | 0.8690 |  | 0.131000 | 0.000000 |
