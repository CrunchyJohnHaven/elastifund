# Current Cycle Loss Recovery - 2026-03-11

## Operator Summary

The current BTC5 sleeve is still positive overall, but the latest March 11 loss cluster is real and concentrated.

- Sleeve-level runtime truth: `223` live-filled rows, `+43.0575 USD` live-filled PnL.
- Recent cluster: latest five live-filled rows at about `-6.98 USD`.
- Best live edge: `DOWN` and bucket `0.50`.
- Worst live buckets: `0.49` and `<0.49`.
- Worst export session: BTC windows in the `08:00-09:59 ET` range, plus non-BTC leakage such as XRP.

## Exact Fix To Load

- Keep the global cap pair: `UP <= 0.48`, `DOWN <= 0.51`.
- Suppress or strictly reprice BTC5 quotes in the `08:00 ET` and `09:00 ET` sessions when the target order would land in `0.49` or `<0.49`.
- Keep the `0.50` bucket tradable.
- Keep stage at `stage_1`.
- Keep higher-notional deployment parked.

## What Not To Say

- Do not say the strategy is dead.
- Do not say the system is ready for higher notional.
- Do not say finance has cleared expansion.
- Do not blend long-dated discretionary inventory into BTC5 edge diagnosis.

## Rollback Path

Revert to the last safe stage-1 baseline if any of these happen:

1. The morning-session profile suppresses all BTC5 candidates for two consecutive cycles.
2. The next `20` live fills are worse than the current baseline.
3. Truth-precedence repair lands, but public artifacts still disagree with runtime truth.

If rollback triggers fire:

- remove the morning-session suppression overlay
- keep the proven cap pair `UP <= 0.48`, `DOWN <= 0.51`
- keep higher-notional expansion parked
- keep the truth-precedence repair in place

## Machine-Readable Cycle Statement

- `candidate_delta_arr_bps`: `0`
- `expected_improvement_velocity_delta`: `0.05`
- `arr_confidence_score`: `0.80`
- `block_reasons`: `["operator_packet_stale_vs_latest_csv","higher_notional_expansion_not_ready"]`
- `one_next_cycle_action`: `Publish the refreshed loss-recovery packet and hold expansion until the bounded guardrail profile proves out`

## Human Handoff

The trading lane is not collapsing everywhere. The damage is concentrated in a bad morning BTC cluster and a small set of non-BTC leaks. The fix is to keep the proven BTC5 caps, add morning-session suppression around the bad buckets, and roll back immediately if that bounded profile either kills candidate flow or underperforms over the next 20 live fills.
