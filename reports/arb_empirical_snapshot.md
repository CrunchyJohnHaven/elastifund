# Arb Empirical Snapshot

- Generated: 2026-03-07T20:12:03+00:00
- Live cycles: 1
- Scan interval seconds: 0
- Book sample events per cycle: 20

## Measured Facts

- Active multi-outcome events: latest 9; avg 9.0
- Active multi-outcome markets: latest 58; avg 58.0
- Complete-book A-6 event observations: 9/9
- Token-404 rate: 0.0
- Incomplete-book leg rate: 0.0

## A-6

- Replay rows: 44 across 15 unique events
- A-6 modes observed: {'neg_risk_sum': 5}
- Settlement paths observed: {'hold_to_resolution': 5}
- Episode count: 5
- Qualified live A-6 observations: 5 (0 underround / 5 overround)
- YES-sum deviation median: 0.033
- YES-sum deviation p90: 0.1038
- A-6 persistence lower bound from replay: 0.0s
- Actual capture rate: 0.0
- Modeled capture rate: 0.5431

## Spread Buckets

| Bucket | Count | Median Spread | P90 Spread |
| --- | ---: | ---: | ---: |
| core_35_65pct | 4 | 0.015 | 0.02 |
| favorite_65_100pct | 5 | 0.02 | 0.0364 |
| mid_15_35pct | 4 | 0.09 | 0.2232 |
| tail_0_5pct | 36 | 0.003 | 0.015 |
| tail_5_15pct | 9 | 0.006 | 0.0734 |

## Fill Proxy

- Eligible probes: 0
- Full $5 fill proxy rate: None
- Wilson 95% interval: None to None
- Notes: No eligible probes. The current Gamma /events A-6 watchlist flattening does not preserve conditionId for 58 otherwise-quotable legs, so the live trade tape cannot be joined back to those markets.

## Recommendations

- Provisional global A-6 underround threshold: 0.9315
- Provisional B-1 implication threshold: 0.04

| Leg Bucket | Samples | Recommended Gross Edge | Recommended Sum Threshold | Basis |
| --- | ---: | ---: | ---: | --- |
| 3_5_legs | 0 | None | None | no_samples |
| 6_10_legs | 1 | 0.043 | 0.957 | thin_sample_execution_drag_plus_buffer |
| 11_20_legs | 0 | None | None | no_samples |
| 21_plus_legs | 1 | 0.094 | 0.906 | thin_sample_execution_drag_plus_buffer |

## B-1

- Historical graph edges: 0
- Historical violation rows: 0
- Measurement status: insufficient_live_samples

## Settlement

- Logged settlement ops: 0/0 successful
- Success rate: None
- Ops by type: {}
- Avg effective cost USD: None

## Shadow-to-Live Gating Metrics

- Fill probability gate: **insufficient_data** (Wilson lower=None)
- Violation half-life gate: **fail** (0.0s)
- Settlement path gate: **untested**
- Kill decision: **kill** (upper_confidence_bound=0.0803<0.50 over 44 completed cycles)
- Promotion eligible: **False**

## Unknowns

- B-1 live correction half-life remains unmeasured until the live monitor writes non-sum violations to `constraint_arb.db`.
- Fill proxy is not the same as actual queue-position fill rate; it only measures whether recent trade-through volume was sufficient to fully fill a $5 passive YES order at one-tick improvement.
- Actual realized capture is still zero because the current dataset is shadow-only.

## Execution Tasks

| Status | Task | Why |
| --- | --- | --- |
| done_in_this_pass | Clarify A-6 lane as neg-risk YES-basket only | The current implementation targets neg-risk sum rebalancing, not binary YES+NO merge baskets. |
| done_in_this_pass | Add combinatorial telemetry schema and A-6 episode tracking | Maker-fill, half-life, settlement, and basket telemetry now have dedicated tables instead of only generic violation rows. |
| done_in_this_pass | Upgrade empirical snapshot reporting | The report now exposes A-6 mode, episode counts, settlement coverage, and a research-derived task list. |
| done_in_this_pass | Propagate tick-size changes through the shared quote store | Tick-size changes are now preserved alongside best bid/ask updates for A-6 and B-1 consumers. |
| next | Run a 72h maker-fill curve measurement | Promotion still depends on measured joint fill probability, not the current trade-through proxy. |
| blocked_external | Execute settlement-path validation | No confirmed merge/redeem/convert operations are logged yet, so settlement remains unproven. |
| next | Finish the 50-pair B-1 gold set and precision audit | B-1 promotion should be gated on validated precision, not only graph size or classifier confidence. |
| next | Route live order groups and legs into executor telemetry | The new order-group tables exist, but live jj_live routing and user-channel fill persistence are still pending. |
| backlog | Split binary Dutch-book A-6 into a separate lane | The research report treats YES+NO merge baskets as a distinct settlement path and risk model. |
