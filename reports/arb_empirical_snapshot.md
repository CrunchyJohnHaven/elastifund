# Arb Empirical Snapshot

- Generated: 2026-03-09T11:55:20+00:00
- Live cycles: 3
- Scan interval seconds: 20
- Book sample events per cycle: 60

## Measured Facts

- Public A-6 audit: 0 executable constructions below the 0.95 gate across 510 allowed neg-risk events
- Public B-1 audit: 0 deterministic template pairs in the first 1000 allowed markets
- Active multi-outcome events: latest 148; avg 148.0
- Active multi-outcome markets: latest 962; avg 962.0
- Complete-book A-6 event observations: 66/180
- Token-404 rate: 0.397
- Incomplete-book leg rate: 0.4078

## Explicit Lane Status

- A-6 status: **blocked**
- A-6 evidence: maker_fill_proxy_rate=None, violation_half_life_seconds=76.5, settlement_evidence_count=0, classification_accuracy=None, false_positive_rate=None
- A-6 blocked reasons: ('maker_fill_proxy_unmeasured', 'public_audit_zero_executable_constructions_below_0.95_gate')
- B-1 status: **blocked**
- B-1 evidence: maker_fill_proxy_rate=None, violation_half_life_seconds=None, settlement_evidence_count=0, classification_accuracy=None, false_positive_rate=None
- B-1 blocked reasons: ('classification_accuracy_unmeasured', 'false_positive_rate_unmeasured', 'public_audit_zero_deterministic_pairs_in_first_1000_allowed_markets')

## A-6

- Replay rows: 62 across 14 unique events
- A-6 modes observed: {'neg_risk_sum': 41}
- Settlement paths observed: {'hold_to_resolution': 34}
- Episode count: 41
- Qualified live A-6 observations: 53 (0 underround / 53 overround)
- YES-sum deviation median: 0.0915
- YES-sum deviation p90: 0.716
- A-6 persistence lower bound from replay: 76.5s
- Actual capture rate: 0.0
- Modeled capture rate: 0.3942

## Spread Buckets

| Bucket | Count | Median Spread | P90 Spread |
| --- | ---: | ---: | ---: |
| core_35_65pct | 66 | 0.22 | 0.39 |
| favorite_65_100pct | 108 | 0.2 | 0.353 |
| mid_15_35pct | 192 | 0.11 | 0.43 |
| tail_0_5pct | 264 | 0.005 | 0.0318 |
| tail_5_15pct | 189 | 0.028 | 0.17 |

## Fill Proxy

- Eligible probes: 0
- Full $5 fill proxy rate: None
- Wilson 95% interval: None to None
- Notes: No eligible probes. The current Gamma /events A-6 watchlist flattening does not preserve conditionId for 819 otherwise-quotable legs, so the live trade tape cannot be joined back to those markets.

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
- Violation half-life gate: **pass** (76.5s)
- Settlement path gate: **untested**
- Kill decision: **kill** (upper_confidence_bound=0.0583<0.50 over 62 completed cycles)
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
