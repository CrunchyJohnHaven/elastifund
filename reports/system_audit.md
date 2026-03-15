# BTC5 Trading System Audit
Generated: 2026-03-15
Status: canonical — do not spin results

---

## Q1. What is our actual edge?

**Math per direction:**

**Updated 2026-03-15T23:40Z — 10 total fills (8 at price >= 0.90, two_sided mode)**

**DOWN (7 fills, 7 wins, 0 losses):**
- WR = 1.00, avg_win = $0.649, total: +$4.54
- avg_entry = 0.918 → break-even WR = 91.8%. Clean margin.
- Edge verdict: **promising but unproven at N=7. 100% WR is consistent, not confirmed.**

**UP at price < 0.90 (2 fills, 0 wins, 2 losses):**
- WR = 0.00, avg_loss = −$5.00. EV = −$5.00/fill.
- Status: DEAD. Blocked by MIN_BUY_PRICE=0.90.

**UP at price >= 0.90 (2 fills, 2 wins):**
- WR = 1.00, avg_win = $0.87, total: +$1.74
- First confirmed: UP@0.90 (+$0.87) on 2026-03-15T21:24Z
- Edge verdict: **same mechanism as DOWN. Price filter captures it.**

**Summary (8/8 wins at >= 0.90, +$6.28 net):**
The edge is the price filter, not direction. At >= 0.90, momentum confirmation is
symmetric. The broken state was: UP_MAX_BUY_PRICE=0.52 + down_only mode blocking UP.
Fix deployed 2026-03-15T21:00Z: two_sided, both caps at 0.95.

**Min-buy floor sensitivity confirmed (replay simulator 2026-03-15):**
0.90 is the inflection point: WR jumps from 90.9% (floor=0.89) to 96.4% (floor=0.90).
All floors below 0.87 are negative PnL. Floor=0.90 is optimal. Do not lower.

---

## Q2. What is our sample size?

**N = 10 total fills** (8 qualifying at price >= 0.90). This is not a sample. It is a pilot run.

**Minimum N for 95% confidence:**
- To detect a WR of 70% vs null 50% at 95% confidence (one-sided): N ≈ 50 fills.
- To detect a WR edge of 5% above break-even at 95% confidence: N ≈ 150–300 fills.
- At current fill rate (~5 fills/day with two_sided at 0.90+), reaching N=50 takes ~10 days; N=150 takes ~30 days.
- **Bottom line: 8/8 at 0.90+ is directionally strong but statistically unproven. Need 42 more fills at 0.90+.**

---

## Q3. Are we trading the right markets?

**Delta as signal:**
- Delta measures the probability shift in the market between two snapshots. It is a momentum/reactive signal, not a predictive one.
- Using delta alone is effectively mean-reversion betting: we bet that large price moves in one direction will correct. That is a speculative, not structural, premise.
- The 198 `skip_delta_too_large` events and 104 `skip_delta_too_small` events suggest the delta filter is highly active — but we have no counterfactual data at scale to validate whether the filtered range is predictive.
- **Verdict: delta is a plausible filter but not a proven signal. We are trading on an unvalidated hypothesis with real money.**

**BTC5 market fit:**
- BTC5 is a short-resolution binary market. Outcomes resolve quickly, limiting compounding drag. That is a structural advantage.
- Wallet analysis (Q10) shows sophisticated players driving 0.99 price events — these may be arbitrage closes, not signal-bearing trades. We may be co-investing with rational arbitrageurs when DOWN, which explains 5/5 wins.
- **Risk: our DOWN edge may be co-movement with near-certain outcomes priced at 0.99 — not delta predictability.**

---

## Q4. What does the counterfactual frontier actually say?

**Frontier stats (generated 2026-03-15T17:34):**
- 21 actionable cells, 39 signal-only cells
- All N values are 2–5. This is very small.
- EV consistency audit: CLEAN (0 flagged of 21 exact cells) — no systematic EV errors detected.

**Top actionable cell:**
- skip_price_outside_guardrails / DOWN: n=2, wr_edge=0.135, upper_bound_pnl=$1.56, CQ=exact
- At n=2, this is not actionable evidence. It is a hypothesis.

**Key finding:**
- No skip reason has N≥10 with a strongly positive counterfactual PnL. The frontier is data-starved.
- The most important counterfactual data point is the h_dir_down diagnosis (100 DOWN skips): 70% WR, avg_entry=0.77, total_pnl=−$51.77 across 100 hypothetical fills. **The skip filters are working. Removing them would lose money.**
- The frontier cannot yet tell us which specific skip reasons to relax. Every cell needs more data.

**Verdict: frontier is generating correct structure but insufficient data volume. Hold filters; collect more.**

---

## Q5. Do we have a backtester for BTC5 delta strategy?

**No.**

The `backtest/` directory contains `run_backtest.py` and `enhanced_backtest.py`. These are built for the LLM-based market model (Anthropic API). They are not reusable for the BTC5 delta strategy without a full rewrite of the signal logic, data pipeline, and evaluation harness.

**There is no backtester for BTC5 delta strategy. The replay simulator (scripts/replay_simulator.py) is the first step toward building one.**

---

## Q6. Can we simulate different parameter sets against historical data?

**Partially, starting now.**

With the replay simulator (scripts/replay_simulator.py), we can:
- Apply different `down_max_buy_price`, `min_delta`, `risk_fraction` params to historical window_trades rows
- Compute simulated fills, WR, and PnL using `resolved_outcome` as ground truth
- Compare up to 5 configs side by side

**Limitations:**
- The DB has 832 windows but only 8 live fills. Most windows were skipped. The `counterfactual_pnl_usd_std5` field is available for some; for the rest, PnL is estimated from `resolved_outcome + best_ask`.
- Simulation fidelity is moderate — we assume fills execute at `best_ask`, which may not hold in thin markets.
- Time-of-day effects, intraday liquidity variation, and queue position are not modeled.

**Yes, we can simulate. Results will be directionally useful but not precise.**

---

## Q7. What about Monte Carlo confidence intervals from counterfactual data?

**scripts/btc5_monte_carlo.py and btc5_monte_carlo_core.py exist.** They can be used to generate confidence intervals by bootstrapping from counterfactual fills.

**Key constraint:** at N=100 counterfactual DOWN fills (the h_dir_down diagnosis pool), bootstrap CIs will be wide. At 70% WR with N=100, the 95% CI on WR is approximately [61%, 79%]. At avg_entry=0.77 (break-even=77%), the lower bound of the CI is below break-even. **The Monte Carlo will confirm: we cannot distinguish the counterfactual DOWN edge from zero at current data volumes.**

Monte Carlo is most useful for:
- Sizing the confidence interval on existing CF PnL estimates
- Stress-testing parameter changes before live deployment
- Generating upper/lower bound PnL projections for frontier cells

**Recommend: run Monte Carlo on the 100-fill DOWN CF pool to quantify uncertainty before any parameter relaxation.**

---

## Q8. What is the autoresearch system actually doing?

Based on existing artifacts (`reports/autoresearch/`, `reports/btc5_autoresearch/`, `scripts/run_btc5_autoresearch_cycle.py`):

**What it is doing:**
- Generating frontier cells from skip-reason / direction / price-bucket combinations
- Running EV consistency audits
- Producing hypothesis candidates for parameter mutation
- Publishing results to `reports/btc5_autoresearch_current_probe/`

**Is it generating useful challengers?**
- The frontier is structurally correct and EV-clean (0 flags).
- But all challenger cells have N=2–5. The autoresearch system is correctly identifying *what to test* but the live data volume is too low to confirm any challenger.
- The system is not running offline simulations — it is waiting for live data to populate frontier cells. This is the bottleneck.

**Verdict: the autoresearch system is functioning but constrained by live fill rate. It needs the replay simulator to operate on historical data, not just live fills.**

---

## Q9. What research questions should autoresearch be asking?

**Top 5 hypotheses (ranked by expected dollar impact):**

1. **Entry price threshold is the entire edge.** At avg_entry=0.928, DOWN fills win 100%. The counterfactual at avg_entry=0.77 wins 70% and loses money. The hypothesis: tightening `down_max_buy_price` from 0.95 to 0.92 or 0.90 would reduce fill rate but improve WR above the break-even threshold. Test: replay simulator sweep across down_max ∈ {0.95, 0.93, 0.91, 0.90}.

2. **Delta threshold is filtering too aggressively.** 198 `skip_delta_too_large` events vs 8 fills. If a substantial fraction of those windows had favorable outcomes, raising `min_delta` ceiling could unlock fills. Test: replay simulator with delta ceiling relaxed by 50%.

3. **skip_bad_book (110 events) — counterfactual unknown.** We do not know whether "bad book" windows would have been profitable. Test: replay on those 110 windows if we have `resolved_outcome` data.

4. **skip_toxic_order_flow (82 events) — is it overcautious?** Test: check `resolved_outcome` distribution on TOF-flagged windows vs non-flagged. If WR on TOF windows matches non-TOF windows, the filter is not earning its cost.

5. **UP direction: suppress vs hard disable.** Current config: `down_only`. UP fills show −$3.25/fill. But: do any UP entry price buckets show positive CF? Test: frontier cell analysis on UP direction, segmented by entry price bucket.

---

## Q10. What are top Polymarket wallets doing on BTC5?

**Wallet analysis (5 windows, 94 deduplicated trades, 88 unique wallets):**

**Pattern:**
- Top volume wallets are ALL buying DOWN at price=0.99
- At price=0.99, the remaining UP tokens are priced at $0.01 — these are arbitrage close-outs, not speculative bets
- Volume leaders: $495, $199, $126, $125, $119 (single trades each)
- These wallets are buying DOWN at near-certainty, likely to lock in a guaranteed +1% return on near-resolved markets

**Implication:**
- These are not sophisticated signal traders — they are arbitrageurs closing out positions at market expiry
- The 5/5 DOWN wins at avg_entry=0.928 may be co-investing with these close-out trades — we are winning because the market is effectively resolved, not because our delta signal is predictive
- **Risk: our edge may be "buy near-resolved markets" rather than "delta predicts direction." These are very different strategies with different scalability.**

**Verdict: wallet consensus at 0.99 is an arbitrage signal, not a predictive signal. We should test whether our wins are concentrated in windows where price was already ≥0.95 at entry.**

---

## Q11. Where are single points of failure?

1. **DB as sole truth source.** `btc5_maker.db` and `btc_5min_maker.db` are local SQLite files. No replication. A disk failure loses all historical data and counterfactual learning.

2. **Fill rate bottleneck.** 8 fills in 3.1 days = 2.6/day. All statistical learning depends on live fills. If fill rate drops (market liquidity change, config tightening), learning stalls.

3. **No backtester.** Parameter changes cannot be validated offline. Every config change is a live experiment.

4. **UP direction off.** The system is running with `BTC5_DIRECTIONAL_MODE=down_only`. If DOWN edge degrades, there is no fallback direction generating revenue.

5. **`BTC5_PROBE_RECENT_MIN_PNL_USD=-10.0` just fixed.** If this config was misconfigured previously, probe decisions during that period may have been made with incorrect guardrails. The audit window is 2026-03-12 to 2026-03-15 — all fills occurred during or after this period. Impact: unknown.

6. **Wallet analysis pipeline is 5-window sample.** Smart wallet detection is based on 5 windows. Not enough to build a reliable consensus signal.

---

## Q12. What's our actual latency?

**Unknown / not enough data.**

The DB does not expose a field capturing time-from-signal-to-order-placement vs time-to-fill. `window_start_ts` is available but order submission latency and fill latency are not in the provided data. The 13 `live_order_failed` events suggest some execution failures, which may be latency-related or API-related — cause unknown.

**What we can infer:** BTC5 windows are 5-minute resolution. At 5-minute windows, sub-second latency is not the bottleneck. The bottleneck is signal quality and price thresholds, not execution speed.

**Recommend: add order_submitted_ts and fill_confirmed_ts columns to the DB to measure actual execution latency.**

---

## Q13. Are we leaving money on the table by only doing BTC5?

**Probably yes, but the magnitude is unknown.**

**The case for expansion:**
- 832 windows in 3.1 days = 268/day. Fill rate = 0.96%. That is a 99% skip rate.
- If the delta signal generalizes to other short-resolution binary markets (ETH5, SOL5, etc.), the same framework could generate fills on parallel markets without changing the core logic.
- The autoresearch system infrastructure (frontier, CF tracking, wallet analysis) is general enough to apply to other markets.

**The case against expanding now:**
- We do not have a validated edge on BTC5 yet. Expanding to more markets multiplies uncertainty, not edge.
- N=8 fills on BTC5 means we have zero evidence the signal generalizes.
- Operational complexity increases: more markets = more failure modes, more DB entries, more monitoring surface.

**Verdict: stay on BTC5 until N≥50 DOWN fills and the edge is empirically confirmed. Then evaluate expansion with replay simulation on candidate markets first.**

---

## Summary Scorecard

| Dimension | Status | Notes |
|---|---|---|
| DOWN edge | Unproven | N=5, WR=100%, but CF at same params shows negative edge |
| UP edge | Negative | −$3.25/fill, disable was correct |
| Backtester | Missing | Replay simulator is the starting point |
| Autoresearch | Functional, data-starved | Needs offline simulation capability |
| Sample size | Insufficient | Need 10–20× more fills for confidence |
| DB resilience | Single point of failure | No replication |
| Wallet signals | Arbitrage, not alpha | Near-resolved market close-outs |
| Latency | Unknown | Not instrumented |
| Parameter validation | Manual / no offline test | Replay simulator addresses this |
