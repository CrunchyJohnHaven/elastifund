# Calibration Benchmark Packet

- Benchmark: `calibration_v1`
- Generated at: 2026-03-08T08:21:02Z
- Mutable surface: `bot/adaptive_platt.py`
- Working tree dirty: True
- Git SHA: `32a452964b7e461ac82d408c82c6b3fee53d98ee`
- Holdout rows: 160
- Selected variant: `rolling_100`
- Benchmark score: -0.235722
- Brier: 0.222686
- ECE: 0.052142
- Log loss: 0.635115

Calibration benchmark wins are research artifacts. They do not imply paper, shadow, or live trading readiness.

## Variant Results

| Variant | Window | Predictions | Fallbacks | Benchmark Score | Brier | ECE | Log Loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| static | static | 160 | 0 | -0.241256 | 0.217883 | 0.093491 | 0.624732 |
| expanding | all | 160 | 0 | -0.236810 | 0.226111 | 0.042795 | 0.642587 |
| rolling_100 | 100 | 160 | 0 | -0.235722 | 0.222686 | 0.052142 | 0.635115 |
| rolling_200 | 200 | 160 | 0 | -0.236006 | 0.224103 | 0.047611 | 0.637987 |

## Confidence Bands

| Band | Count | Avg Confidence | Win Rate | Abs Gap |
|---|---:|---:|---:|---:|
| 0.1-0.2 | 8 | 0.1574 | 0.1250 | 0.0324 |
| 0.2-0.3 | 6 | 0.2625 | 0.3333 | 0.0708 |
| 0.3-0.4 | 19 | 0.3424 | 0.2105 | 0.1319 |
| 0.4-0.5 | 41 | 0.4526 | 0.3902 | 0.0624 |
| 0.5-0.6 | 58 | 0.5465 | 0.5345 | 0.0120 |
| 0.6-0.7 | 17 | 0.6376 | 0.6471 | 0.0095 |
| 0.7-0.8 | 7 | 0.7256 | 0.5714 | 0.1542 |
| 0.8-0.9 | 4 | 0.8355 | 1.0000 | 0.1645 |
