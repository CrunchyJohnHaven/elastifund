# next_tasks.md

## Status

The containment sprint is done.

Atomic window reservation, the execution-layer cap block, fail-closed defaults, the startup safety log, the filter ledger, the mutation tracker, the single effective env, the health snapshot, the truth bundle, and the JJ/BTC5 ownership boundary all landed in the March 25 P0-P2 sprint. Do not reopen that work unless a live failure proves it is still broken.

The next sprint is simpler:

**run one clean post-fix validation cohort, prove DOWN-only edge fast, or kill BTC5 cleanly.**

That is the whole job.

---

## What the last sprint actually changed

The previous task file was executed in the right spirit. The system now has the right primitives:

- duplicate-window protection before order submission
- a hard oversize block before CLOB submission
- fail-closed defaults for UP, direction mode, and hour filters
- one generated runtime contract
- one health surface
- one mutation state file
- one truth bundle

That means the bottleneck is no longer architecture.

The bottleneck is **decision-quality evidence**.

And there is one important lesson from how the tasks were executed:

**the current truth bundle is still too contaminated to judge the post-fix strategy.**

It currently recommends `kill` because it still sees recent UP live fills from pre-fix rows. That is useful as a safety warning, but it is not a valid verdict on the fixed DOWN-only cohort. The next sprint must therefore start by defining a clean validation cohort and refusing to judge BTC5 from mixed pre-fix + post-fix history.

---

## Core objective

Answer one question with controlled live data:

**Does BTC5 DOWN-only, capped at $5 max trade, 0.48 max buy price, and ET suppression for hours 0, 1, 2, 8, and 9 produce positive net P&L after estimated rebates with zero safety failures?**

If yes, keep BTC5 alive at the same size and run a second confirmation cohort.

If no, kill BTC5 and reallocate the proving-ground lane to Kalshi weather arb.

No scaling before that answer exists.

---

## Non-negotiables for this sprint

1. **VPS runtime truth wins.** If local artifacts disagree with the VPS DB or VPS runtime contract, the VPS wins.
2. **The sample must be cohort-based.** Count only post-fix, DOWN-only, live, resolved fills from the active mutation/config hash.
3. **No new BTC5 mutations during the 50-fill proof window.** The loop is paused while the strategy is being judged.
4. **No size increases.** Stay at the current $5 cap.
5. **Any safety failure ends the sample immediately.** That means any UP live attempt, cap breach, config hash mismatch, duplicate-window symptom, or restart-loop.

---

## P0 — First 24 hours

### P0.1 — Freeze one clean validation cohort

Create one explicit validation contract before counting a single fill.

Record these fields in one place:

- `post_fix_validation_start_ts`
- `validation_mutation_id`
- `validation_config_hash`
- `validation_profile_name`
- `validation_effective_max_trade_usd=5`
- `validation_down_max_buy_price=0.48`
- `validation_direction_mode=down_only`
- `validation_up_live_mode=shadow_only`
- `validation_hour_filter_enabled=true`
- `validation_suppress_hours_et=0,1,2,8,9`

The 50-fill sample only counts rows that are:

- live, not paper
- direction = `DOWN`
- resolved
- `decision_ts >= post_fix_validation_start_ts`
- tied to `validation_mutation_id`
- tied to `validation_config_hash`

Do not judge BTC5 from all-history rows.

### P0.2 — Deploy once, verify once, then start counting

Use the already-generated effective env and runtime contract. Do not change parameters during deployment.

Immediately after deploy:

1. restart the BTC5 service
2. run `python scripts/render_btc5_effective_env.py`
3. run `python scripts/render_btc5_truth_bundle.py`
4. run `python scripts/render_btc5_health_snapshot.py`
5. run `python scripts/verify_btc5_mutation.py`

The cohort does **not** begin until mutation verification returns `MUTATION_VERIFY_OK`.

Interpret `verify_btc5_mutation.py` exactly this way:

- exit `0` = valid deploy, sample may start
- exit `1` = invalid deploy, stop and fix the hash mismatch
- exit `2` = unknown deploy state, do not count fills yet

### P0.3 — Use a cohort surface, not the all-history truth bundle, for the verdict

Do not rebuild the truth system. Add one narrow cohort view on top of it.

Create or generate one report such as:

- `reports/btc5_validation_cohort_latest.json`

It should answer only the post-fix question and should include:

- `cohort_start_ts`
- `mutation_id`
- `config_hash`
- `resolved_down_fills`
- `wins`
- `losses`
- `win_rate`
- `gross_pnl_usd`
- `estimated_maker_rebate_usd`
- `net_pnl_after_estimated_rebate_usd`
- `avg_entry_price`
- `price_bucket_slice`
- `hour_slice_et`
- `fill_rate`
- `order_failed_rate`
- `cap_breach_events`
- `up_live_attempts`
- `config_hash_mismatch_count`
- `recommendation`

The all-history truth bundle remains the broad safety surface.
The cohort report becomes the decision surface for this sprint.

### P0.4 — Pass/fail checklist for the deployment itself

A valid post-fix deploy must pass all of these before the sample starts:

- service is active and not restart-looping
- `verify_btc5_mutation.py` returns OK
- startup logs show the safe config, not permissive fallbacks
- health snapshot shows the exact deployed params
- runtime contract hash matches the mutation state hash
- UP live attempts after cohort start = 0
- cap breach events after cohort start = 0
- no more than one live sequence exists per BTC5 window
- `pending_reservation` rows do not accumulate past a single active window

If any of these fail, the strategy is not “under test.” It is still broken.

---

## P1 — Days 1 to 7: collect the 50-fill proof sample

### P1.1 — Sampling rules

Count only:

- post-fix cohort rows
- live rows
- resolved rows
- DOWN rows

Do not count:

- paper fills
- shadow rows
- pre-fix rows
- UP rows
- unresolved rows
- rows from a different mutation or config hash

Checkpoint the sample at:

- 10 fills
- 20 fills
- 30 fills
- 50 fills

### P1.2 — Metrics that matter at every checkpoint

At each checkpoint, update the cohort report with:

- resolved fills
- wins / losses
- win rate
- gross P&L
- estimated maker rebate
- net P&L after estimated rebate
- average entry price
- average trade size
- price bucket mix: `<0.49`, `0.49`, `0.50`, `0.51+`
- ET hour mix
- live fill rate
- order failure rate
- partial-fill and cancel counts
- cap breach count
- UP live attempt count
- config hash mismatch count

Win rate alone is not enough.

The strategy is only alive if the **net dollars** are positive under the fixed rules.

### P1.3 — The only kill rules during the sample

There are two kill classes.

#### Safety kill — immediate

Kill the sample immediately on any of these:

- any UP live attempt
- any cap breach event
- any config hash mismatch that survives redeploy verification
- service restart-loop
- evidence of duplicate live orders in one window

#### Economic kill — at 50 resolved fills

If the first **50 resolved DOWN-only cohort fills** still produce **non-positive net P&L after estimated rebates**, kill BTC5.

Do not negotiate with that result.

### P1.4 — If the first 50 fills are positive

Do **not** scale.

If the first 50-fill cohort is positive and clean, the correct next move is:

1. keep the same $5 cap
2. keep DOWN-only
3. keep the same hour filter
4. keep the same 0.48 price cap
5. run a second confirmation cohort of 50 resolved fills

The first positive cohort proves survival.
The second proves repeatability.

---

## P2 — Filter economics: learn, do not mutate yet

`reports/btc5_filter_economics_latest.json` now matters, but only after some post-fix data exists.

Use it to answer exactly these questions:

1. **Did the hour filter save money, or only reduce volume?**
2. **Did DOWN-only protect capital the way the packet says it should?**
3. **Is the 0.48 cap the actual source of the remaining edge?**
4. **Which blocked price buckets were genuinely bad?**
5. **Which ET hours remain positive after the fixed filters?**
6. **Is any current filter creating more opportunity cost than prevented loss?**

Decision rules for this sprint:

- keep a filter if `net_filter_value_usd >= 0`
- keep a filter if it is a hard safety rule even when opportunity cost looks high
- do **not** relax any filter during the first 50-fill cohort
- the direction filter is not a candidate for relaxation; UP remains dead
- only consider a future relaxation after the cohort is complete and only if the blocked sample is large enough to trust

The point of filter economics is not to add more filters.
The point is to learn which existing filters actually create money.

---

## DOWN-only proof standard

BTC5 DOWN-only is only considered provisionally viable if all of these are true:

1. 50 resolved DOWN-only cohort fills exist
2. zero safety kills fired during the cohort
3. mutation hash stayed valid through the cohort
4. net P&L after estimated rebates is positive
5. the positive result is not explained by one freak outlier trade
6. the profitable slice is still concentrated in allowed hours and disciplined entry prices

If those are not true, the honest conclusion is that DOWN-only still does not have durable edge under controlled reality.

Then BTC5 dies.

---

## Kalshi activation plan if BTC5 is killed

Kalshi is not the parallel sprint. It is the fallback lane.

Trigger it only if BTC5 hits an economic kill or a safety kill.

### Sequence

1. disable BTC5 live trading
2. preserve the final BTC5 cohort report and truth bundle
3. move the proving-ground lane to `bot/kalshi/`
4. resolve the current Kalshi mode contradiction: `weather arb mode=live` but `paper_trading=true`
5. deploy Kalshi weather only, not a broad multi-strategy bundle
6. keep capital tiny at first
7. create the same basic truth contract for Kalshi before any scaling discussion

### What Kalshi activation must verify

- auth works
- balances are real
- paper/live mode is unambiguous
- weather markets only
- first small live cohort is captured in a machine-readable report

Do not drag BTC5 uncertainty into Kalshi.
Kill one lane cleanly, then start the next one cleanly.

---

## Config hash verification workflow

This sprint should treat config-hash verification as mandatory, not optional.

### On every deploy

1. generate the effective env and runtime contract
2. deploy and restart
3. run `python scripts/verify_btc5_mutation.py`
4. read the exit code
5. record the result in the cohort report and the deployment log

### Interpretation

- `MUTATION_VERIFY_OK` → valid runtime, sample can continue
- `MUTATION_VERIFY_FAIL` → runtime is not the intended strategy, sample invalid
- `MUTATION_VERIFY_UNKNOWN` → missing state or contract file, sample invalid

No fill should count toward the proof window unless the deploy hash is valid.

---

## Autoresearch loop reactivation

Not yet.

The loop should stay out of the live path until the strategy has earned the right to mutate again.

### Required conditions before reactivation

1. one full 50-fill cohort completed
2. cohort net P&L after estimated rebates is positive
3. zero safety kills in that cohort
4. `verify_btc5_mutation.py` passes across normal service restarts
5. the cohort report is stable and trusted
6. filter economics has enough data to explain where the edge is coming from
7. mutation auto-revert is tested deliberately and proven to work

### Rules when it comes back

- one mutation at a time
- no overlapping verification windows
- no direct writes to the live base env during an active validation cohort
- every mutation must produce a new `mutation_id` and `config_hash`
- every promoted mutation must either pass its verification window or revert automatically

Autoresearch is allowed to propose only after reality says the base lane is worth improving.

---

## Acceptance criteria

This sprint is done only when all of these are true:

### Safety

- 0 UP live attempts in the post-fix cohort
- 0 cap breaches in the post-fix cohort
- 0 duplicate live executions for one BTC5 window
- service remains stable during the proof window

### Truth

- the active mutation hash matches the runtime contract hash
- the cohort report is filtered to post-fix rows only
- the VPS is the authority for what counted
- health snapshot continues updating during the proof window

### Trading

- 50 resolved DOWN-only cohort fills are collected
- the verdict is made on net P&L after estimated rebates
- if net is non-positive, BTC5 is killed
- if net is positive, BTC5 remains at $5 and runs a second confirmation cohort

### Research

- filter economics can explain whether the hour and price filters are helping
- the system knows which slice is making or losing money
- autoresearch remains paused until the proof gate is passed

---

## Non-goals

- no size increase
- no new BTC5 direction experiment
- no investor narrative work
- no simulator expansion during the proof window
- no new strategy family unless BTC5 is killed

---

## Final instruction

Do not let the system hide in architecture work.

The architecture sprint is over.

This sprint is a reality sprint:

1. **define one clean cohort**
2. **verify the live runtime**
3. **collect 50 real DOWN-only fills**
4. **prove edge or kill the lane**

That is the shortest path to truth.
