# Constraint Arb Shadow Report

Requested window: last 14 day(s)

## Summary

- Violations logged: 73
- Unique events: 16
- Actual observed span: 2026-03-07T18:49:58+00:00 -> 2026-03-09T01:58:43+00:00 (1.2977 day(s))
- A-6 lane definition: neg_risk_sum only (current settlement path: hold_to_resolution)
- A-6 episode count: 19
- A-6 episode median duration: 66.0s
- Settlement ops: 0/0 successful
- Avg settlement cost (if any): 0.0000
- Theoretical PnL: 12.935009
- Realized PnL: 0.000000
- Capture ratio: 0.00%
- Avg semantic confidence: 0.813
- Avg gross edge: 0.1772
- Avg slippage estimate: 0.0381
- Avg VPIN at decision: 0.0548
- VPIN veto count: 0

## Sum-Violation Backtest

- Basis: shadow captures only. Modeled net edge uses `score = gross_edge - slippage_est - fill_risk - semantic_penalty`.
- Episode modes observed: neg_risk_sum=19
- Same-event sum observations: 73 raw / 36 tradable after coverage filter
- Complete-basket underrounds: 2
- Modeled net-positive opportunities: 11/36 (30.56%)
- Avg modeled net edge: -0.0676

| gross_edge bin | observations | unique events | modeled net-positive | avg gross_edge | avg modeled net edge |
| --- | ---: | ---: | ---: | ---: | ---: |
| <5% | 18 | 9 | 3 | 0.0401 | -0.2217 |
| 5-10% | 10 | 4 | 1 | 0.0693 | -0.2464 |
| 10-20% | 1 | 1 | 1 | 0.1290 | 0.0450 |
| 20%+ | 7 | 3 | 6 | 0.7369 | 0.5683 |

## Kill Gate

- Rule: kill A-6 on day 14 if fewer than 5 unique qualifying same-event sum events are detected.
- Status: IN PROGRESS
- Qualifying events so far: 6
- Observation progress: 1.2977/14.0 day(s)

## Attribution Table

| violation_id | event_id | relation_type | semantic_confidence | gross_edge | score | slippage_est | vpin | action | sum_yes_ask | complete_basket | theoretical_pnl | realized_pnl |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: |
| c3bd59905a7eff11bf75 | 48295 | same_event_sum | 0.520 | 0.0800 | -0.4290 | 0.0210 | 0.0000 | unwind_basket | 1.0800 | True | 0.080000 | 0.000000 |
| afb915b4dd652686e30c | 48297 | same_event_sum | 0.440 | 0.0460 | -0.5410 | 0.0240 | 0.0000 | unwind_basket | 1.0460 | True | 0.046000 | 0.000000 |
| b697b731b0daad8523be | 48299 | same_event_sum | 0.600 | 0.0350 | -0.3860 | 0.0180 | 0.0000 | unwind_basket | 1.0350 | True | 0.035000 | 0.000000 |
| 5ed783aefca0c6193a0b | 32228 | same_event_sum | 1.000 | 0.0310 | 0.0130 | 0.0150 | 0.0000 | unwind_basket | 1.0310 | True | 0.031001 | 0.000000 |
| f2eb1cb9bf842b871768 | 48295 | same_event_sum | 0.520 | 0.0850 | -0.4240 | 0.0210 | 0.0000 | unwind_basket | 1.0850 | True | 0.085000 | 0.000000 |
| 5ad22b5687f31c7d50e3 | 48297 | same_event_sum | 0.440 | 0.0460 | -0.5410 | 0.0240 | 0.0000 | unwind_basket | 1.0460 | True | 0.046000 | 0.000000 |
| 68428d7bfa1bef5481ce | 24383 | same_event_sum | 0.600 | 0.0390 | -0.3870 | 0.0180 | 0.0000 | unwind_basket | 1.0390 | True | 0.039000 | 0.000000 |
| ca8f698fd15fc292e4a4 | 48299 | same_event_sum | 0.600 | 0.0350 | -0.3860 | 0.0180 | 0.0000 | unwind_basket | 1.0350 | True | 0.035000 | 0.000000 |
| 6ad7a32c49c7b3c543fd | 32228 | same_event_sum | 1.000 | 0.0310 | 0.0130 | 0.0150 | 0.0000 | unwind_basket | 1.0310 | True | 0.031001 | 0.000000 |
| ff025a4dca950923ecd1 | 48295 | same_event_sum | 0.520 | 0.0850 | -0.4240 | 0.0210 | 0.0000 | unwind_basket | 1.0850 | True | 0.085000 | 0.000000 |
| 8d09e28201990f39c0e1 | 48297 | same_event_sum | 0.440 | 0.0460 | -0.5410 | 0.0240 | 0.0000 | unwind_basket | 1.0460 | True | 0.046000 | 0.000000 |
| 4607ca532a9db2dfdd6f | 48299 | same_event_sum | 0.600 | 0.0350 | -0.3860 | 0.0180 | 0.0000 | unwind_basket | 1.0350 | True | 0.035000 | 0.000000 |
| 0b6bd81990c5c916de55 | 32228 | same_event_sum | 1.000 | 0.0320 | 0.0140 | 0.0150 | 0.0000 | unwind_basket | 1.0320 | True | 0.032001 | 0.000000 |
| e2dfe4f775a0630a9b98 | 24383 | same_event_sum | 0.600 | 0.0410 | -0.3850 | 0.0180 | 0.0000 | unwind_basket | 1.0410 | True | 0.041000 | 0.000000 |
| bfa510e05d367e5c8eb6 | 48295 | same_event_sum | 0.520 | 0.0850 | -0.4240 | 0.0210 | 0.0000 | unwind_basket | 1.0850 | True | 0.085000 | 0.000000 |
| 07d69e588ea82d07ab37 | 48297 | same_event_sum | 0.440 | 0.0460 | -0.5410 | 0.0240 | 0.0000 | unwind_basket | 1.0460 | True | 0.046000 | 0.000000 |
| 9b591a5d420a50ea034f | 48299 | same_event_sum | 0.600 | 0.0350 | -0.3860 | 0.0180 | 0.0000 | unwind_basket | 1.0350 | True | 0.035000 | 0.000000 |
| c70851519841c01a8374 | 32228 | same_event_sum | 1.000 | 0.0320 | 0.0140 | 0.0150 | 0.0000 | unwind_basket | 1.0320 | True | 0.032001 | 0.000000 |
| e47927b6bc823f9c6b58 | 24383 | same_event_sum | 0.600 | 0.0420 | -0.3840 | 0.0180 | 0.0000 | unwind_basket | 1.0420 | True | 0.042000 | 0.000000 |
| dcc73fc7d4739f74caae | 48295 | same_event_sum | 0.520 | 0.0730 | -0.4360 | 0.0210 | 0.0000 | unwind_basket | 1.0730 | True | 0.073000 | 0.000000 |
| 032edc43c35d5b2822f6 | 48297 | same_event_sum | 0.440 | 0.0460 | -0.5410 | 0.0240 | 0.0000 | unwind_basket | 1.0460 | True | 0.046000 | 0.000000 |
| e9e5b12ea436e290ddc5 | 48299 | same_event_sum | 0.600 | 0.0350 | -0.3860 | 0.0180 | 0.0000 | unwind_basket | 1.0350 | True | 0.035000 | 0.000000 |
| 6ef27ea6905fe400f18d | 32228 | same_event_sum | 1.000 | 0.0320 | 0.0140 | 0.0150 | 0.0000 | unwind_basket | 1.0320 | True | 0.032001 | 0.000000 |
| ba33acf5b1212bb404c0 | 24383 | same_event_sum | 0.600 | 0.0450 | -0.3810 | 0.0180 | 0.0000 | unwind_basket | 1.0450 | True | 0.045000 | 0.000000 |
| 7a598b3ee7076afd5a40 | 48295 | same_event_sum | 0.520 | 0.0910 | -0.4180 | 0.0210 | 0.0000 | unwind_basket | 1.0910 | True | 0.091000 | 0.000000 |
| 182573b8d896cb217078 | 48299 | same_event_sum | 0.600 | 0.0350 | -0.3860 | 0.0180 | 0.0000 | unwind_basket | 1.0350 | True | 0.035000 | 0.000000 |
| b3b996b1d7323e81cfc3 | 48297 | same_event_sum | 0.440 | 0.0460 | -0.5410 | 0.0240 | 0.0000 | unwind_basket | 1.0460 | True | 0.046000 | 0.000000 |
| 1d6cef8b10b03e371e0d | 32228 | same_event_sum | 1.000 | 0.0320 | 0.0140 | 0.0150 | 0.0000 | unwind_basket | 1.0320 | True | 0.032001 | 0.000000 |
| 58d980ec0d74d530dd68 | 24383 | same_event_sum | 0.600 | 0.0480 | -0.3780 | 0.0180 | 0.0000 | unwind_basket | 1.0480 | True | 0.048000 | 0.000000 |
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
