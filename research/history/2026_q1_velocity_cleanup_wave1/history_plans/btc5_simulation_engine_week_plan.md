# BTC5 Simulation Engine: Next 7 Days

## Goal

Move the BTC5 autoresearch lane from guardrail-only tuning toward a higher-fidelity execution and regime simulator while keeping the promotion contract simple:

- primary score: continuation ARR delta
- safety gates: profit probability, P05 ARR, loss-hit probability, drawdown
- promotion action: update strategy baseline and push tracked ARR artifacts

## Day 1: Lock the ARR contract

- Freeze `continuation_arr_pct` as the top-line optimization metric for the BTC5 lane.
- Record exactly how the metric is annualized from 5-minute windows and average deployed capital.
- Add a benchmark fixture with known ARR outputs so the metric cannot drift silently.

## Day 2: Model order-status paths explicitly

- Split replay outcomes into `live_filled`, `skip_price_outside_guardrails`, `live_order_failed`, and post-only retry outcomes.
- Teach the simulator to estimate expected fills from observed order-status frequencies instead of assuming replay rows map cleanly to future fills.
- Report ARR both before and after execution-quality drag.

## Day 3: Add regime-conditioned simulation slices

- Partition the BTC5 tape by hour-of-day, volatility bucket, and recent direction regime.
- Run separate Monte Carlo profiles for each slice.
- Export where ARR comes from, not just the aggregate number.

## Day 4: Walk-forward validation

- Replace one-sample ranking with rolling train/validation windows.
- Promote only if ARR improves out of sample, not just on the full observed tape.
- Track walk-forward keep/discard outcomes in the ARR ledger.

## Day 5: Trade-size and queue realism

- Fit fill-size distributions from actual BTC5 fills instead of fixed average trade size.
- Penalize promoted candidates if their ARR depends on unrealistic fill density or better-than-observed quote priority.
- Add sensitivity runs for one-tick worse execution.

## Day 6: Policy frontier export

- Render a frontier table of `ARR`, `P05 ARR`, `profit probability`, and `loss-hit probability`.
- Keep the chart percentage-only, but publish the policy frontier so promotion decisions are auditable.
- Rank candidate families by improvement velocity, not just by one-cycle score.

## Day 7: Promotion review and rollback drills

- Re-run the full local loop on the latest tape.
- Verify the autopush hook only stages the allowlist and refuses unrelated dirty worktrees.
- Simulate a bad promotion and confirm rollback to the last tracked baseline is one command.

## Success Criteria

- ARR is the visible top-line metric in tracked artifacts.
- The simulator distinguishes signal edge from execution drag.
- Promotions are based on out-of-sample ARR improvement, not in-sample replay dollars.
- GitHub history becomes a clean ledger of kept ARR improvements rather than manual status updates.
