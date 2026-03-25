# next_tasks.md

## Status

Elastifund is not in optimization mode. It is in containment mode.

The March 25 packet shows a fund-level loss of **-$1,347.84 (-55.2%)** on **$2,441.90** of deposits, with **BTC5 responsible for 95.8% of deployed capital**. The system is not suffering from a normal drawdown. It is suffering from a broken control plane, a broken sizing contract, and a strategy sleeve that was allowed to trade while its edge was unproven.

The right objective for the next sprint is not “make BTC5 bigger.” It is:

1. **Stop repeatable loss mechanisms.**
2. **Make one BTC5 control plane authoritative.**
3. **Prove whether DOWN-only BTC5 has real edge after price and hour filters.**
4. **Auto-improve only after the loop can safely auto-revert.**

---

## Current failure mode

### 1. The main loss is structural, not random

- **BTC5 UP is dead.** It lost roughly **-$1,060** on **$1,492** deployed. This sleeve should not be tuned. It should stay dead.
- **BTC5 DOWN is fragile, not proven.** The packet says it is negative overall, but approximately **+$10.72 ex-March-15 violation**, and specifically positive when entries are capped near **0.48**.
- **The March 15 oversized windows are the dominant loss event.** The packet attributes roughly **$1,257** of losses to two single-window violations.

### 2. The exact BTC5 cap enforcement hole is in the execution path

The relevant path is:

`jj_live.py` → excludes dedicated BTC5 markets → `btc_5min_maker.py` owns BTC5 execution → `polymarket_clob.py` submits the order.

In `bot/btc_5min_maker.py`, the dangerous sequence is:

1. `_process_window()` checks `self.db.window_exists(window_start_ts)`.
2. It computes `effective_max_trade_usd` and sizes the trade.
3. It calls `self.clob.place_post_only_buy(...)`.
4. **Only after network submission** does it call `_persist(...)`.
5. `_persist(...)` calls `TradeDB.upsert_window(...)`, which uses `ON CONFLICT(window_start_ts) DO UPDATE`.

That means the window is **not reserved before order submission**.

If two processes, two restarts, or a restart-loop hit the same `window_start_ts`, both can see “window not processed,” both can place live orders, and the DB will later **collapse multiple live orders into one row** because the upsert overwrites by `window_start_ts`.

That is the clearest code-level explanation in this packet for how the wallet can show a huge single-window deployment while the local BTC5 DB still looks much cleaner than reality.

### 3. The configuration chain is fail-open

The BTC5 service loads env in this order:

1. `config/btc5_strategy.env`
2. `state/btc5_autoresearch.env`
3. `state/btc5_capital_stage.env`
4. `.env`

Later files win.

That means runtime truth is file-order dependent, not object-based. The mutation is not a single thing. It is a rumor moving through four env files.

Worse, code defaults are still unsafe in `bot/btc_5min_maker.py` if overlays fail:

- `stage1_max_trade_usd` default: **10**
- `stage2_max_trade_usd` default: **20**
- `stage3_max_trade_usd` default: **50**
- `daily_loss_limit_usd` default: **247**
- `direction_filter_enabled` default: **false**
- `hour_filter_enabled` default: **false**
- `up_live_mode` default: **live_enabled**

So the current system does not fail closed. It fails back to permissive runtime behavior.

### 4. The repo still has split truth surfaces

Today BTC5 truth is split across:

- wallet export / portfolio screenshot
- `data/btc_5min_maker.db`
- `jj_state.json`
- `data/jj_trades.db`
- runtime truth JSON
- remote service status JSON
- stale pipeline markdown
- env overlays
- systemd state

That is why the system can be “launch blocked,” “paper false,” “allow order submission true,” and “service running” at the same time.

### 5. The filter system is incomplete economically

The code now logs some counterfactual filter decisions (`hour_filter_status`, `direction_filter_status`), but skip economics are still spread across:

- `order_status`
- `reason`
- `decision_reason_tags`
- filter-specific columns

This is enough to debug by hand. It is not enough to let the bot learn which filters create real P&L.

---

## BTC5 DOWN fee-adjusted diagnosis

### Gross edge

The packet already gives the important answer:

- **DOWN overall:** negative.
- **DOWN ex-March-15 oversized violation:** slightly positive.
- **DOWN at 0.48 entry:** expected value is positive.

For a binary contract bought at price `p_entry`, expected P&L per share is approximately:

`EV/share = win_prob - p_entry`

Using the packet’s DOWN win rate of about **52.2%**:

- At **0.48** entry: `0.522 - 0.48 = +0.042/share` → about **+8.75% on notional**.
- At **0.53** entry: `0.522 - 0.53 = -0.008/share` → about **-1.5% on notional**.

That means **entry price discipline matters more than trade size**.

### Fees

Under the current maker-only design, **maker fee drag is effectively zero**. The live economic floor is not “cover maker fees.” It is:

- **Polymarket minimum order floor:** 5 shares / about **$5 notional**.
- **Tiny maker rebate:** positive but negligible at small size.

So the practical answer is:

- **Break-even trade size against maker fees:** not meaningful, because maker fees are zero.
- **Practical minimum viable trade size:** about **$5 notional** because of the exchange minimum.

Conclusion: **fix price and hour selection before touching size.**

---

## Target BTC5 control plane

BTC5 should become a **small bounded subsystem**, not a wandering branch of the larger repo.

### Owner boundary

- `jj_live.py` should **never** own dedicated BTC5 markets.
- `btc_5min_maker.py` should be the **only** live owner of BTC5.
- `scripts/run_btc5_autoresearch_cycle_core.py` should be allowed to propose mutations, but **not** to create runtime ambiguity.

### Single runtime contract

Create exactly one generated runtime artifact for BTC5:

- `state/btc5_effective.env`
- `reports/btc5_runtime_contract.json`

These should contain:

- deployed config hash
- mutation id
- effective max trade size
- effective daily loss limit
- hour suppression set
- direction mode
- price caps
- service state
- last fill timestamp
- last 50-fill win rate
- auto-revert status

The service should load **one** effective env file, not four layered env sources.

---

## P0: tasks for the next 24 hours

### P0.1 — Make the BTC5 window lock atomic

**Files**
- `bot/btc_5min_maker.py`
- `bot/btc_5min_maker_core.py` only if shared logic is being migrated
- `bot/fill_tracker.py` only if needed for status handoff

**Change**

Add a `reserve_window(window_start_ts, slug, status='pending')` DB write that occurs **before** any network order submission.

Then change the flow to:

1. try to reserve window
2. if reservation fails, skip immediately
3. compute trade
4. submit order
5. update reserved row with final order state

**Critical rule:** replace the current “check then submit then upsert” flow.

**Also add a hard assert:** before any network call, if `size_usd > effective_max_trade_usd + 0.01`, skip and alert.

**Why**

This is the highest-value fix in the entire packet. The current `window_exists()` + later `upsert_window()` sequence is the atomicity hole most consistent with the March 15 oversize event.

**Estimate**: 4–6 hours

**Expected dollar impact**: prevents another catastrophic repeat of the observed **~$1,257** multi-window oversize loss mechanism.

---

### P0.2 — Add a second cap check in the order submission layer

**Files**
- `bot/polymarket_clob.py`
- `bot/btc_5min_maker.py`

**Change**

Change the BTC5 order call contract from:

- `place_post_only_buy(token_id, price, shares)`

to something like:

- `place_post_only_buy(token_id, price, shares, max_notional_usd, window_start_ts)`

Then reject any order where:

`round(price * shares, 2) > max_notional_usd + 0.01`

This is belt-and-suspenders protection.

**Why**

Sizing discipline should be enforced at both:

- the strategy layer
- the final execution layer

If either is wrong, the order still must not go out.

**Estimate**: 2–3 hours

**Expected dollar impact**: large downside avoided; low upside impact.

---

### P0.3 — Kill UP in code defaults, not just env overlays

**Files**
- `bot/btc_5min_maker.py`
- `config/btc5_strategy.env`
- `tests/test_btc_5min_maker*.py`

**Change**

Make these fail-closed defaults in code:

- `direction_filter_enabled = True`
- `direction_mode = 'down_only'`
- `up_live_mode = 'shadow_only'`

Keep the env values aligned:

- `BTC5_DIRECTION_FILTER_ENABLED=true`
- `BTC5_DIRECTION_MODE=down_only`
- `BTC5_UP_LIVE_MODE=shadow_only`

Add tests that UP live orders cannot be placed even if one env layer disappears.

**Why**

Right now the code defaults are permissive and rely on overlays to become safe. That is backwards.

**Estimate**: 1–2 hours

**Expected dollar impact**: prevents recurrence of the observed **-$1,060** UP sleeve damage.

---

### P0.4 — Lock the hour filter into the live path

**Files**
- `bot/btc_5min_maker.py`
- `config/btc5_strategy.env`
- tests

**Change**

Make the BTC5 maker itself authoritative for hour suppression using America/New_York time:

- suppress ET hours: `0,1,2,8,9`
- keep counterfactual logging on skipped windows

Do **not** rely on the separate `jj_live.py` time-of-day kill for BTC5.

**Why**

The BTC5 maker already has the cleaner hour filter implementation. The main live loop’s separate time-of-day filter is broader and duplicates logic.

**Estimate**: 1–2 hours

**Expected dollar impact**: medium; likely moves the DOWN sleeve closer to its ex-violation breakeven/positive regime.

---

### P0.5 — Tighten the DOWN price cap and fail closed if the overlay is missing

**Files**
- `config/btc5_strategy.env`
- `bot/btc_5min_maker.py`
- deploy verification scripts/tests

**Change**

Set and verify:

- `BTC5_DOWN_MAX_BUY_PRICE=0.48`
- `BTC5_MIN_BUY_PRICE=0.30` (or keep stricter if validated)

Then add startup logging that prints the actual effective caps and exits non-zero if they differ from the approved mutation contract.

**Why**

The packet’s own economics say 0.48 is the live line between slight edge and no edge.

**Estimate**: 1 hour

**Expected dollar impact**: medium-high; improves expectancy directly.

---

## P1: tasks for the next 72 hours

### P1.1 — Replace four env layers with one generated effective env

**Files**
- `deploy/btc-5min-maker.service`
- `scripts/run_btc5_autoresearch_cycle_core.py`
- new `scripts/render_btc5_effective_env.py`
- new `state/btc5_effective.env`
- new `reports/btc5_runtime_contract.json`

**Change**

Generate one authoritative BTC5 env file from:

- approved base strategy
- approved mutation
- approved capital stage

Then point the service to **only that file**.

Remove `.env` as a BTC5 behavior override surface.

**Why**

Right now mutation application is implicit. That makes rollback and audit weak.

**Estimate**: 5–7 hours

**Expected dollar impact**: indirect but high; this is the control-plane simplification that prevents future silent misconfiguration.

---

### P1.2 — Create one authoritative BTC5 health contract every 30 minutes

**Files**
- `bot/health_monitor.py`
- `scripts/health_check.sh`
- new `scripts/render_btc5_health_snapshot.py`
- `reports/btc5_health_latest.json`

**The health contract must answer exactly five questions**

1. Is the bot running?
2. When was the last fill?
3. What is rolling win rate over the last 50 resolved fills?
4. What exact parameters are currently deployed?
5. Does deployed config match the latest approved mutation?

Also send Telegram only for:

- service down
- oversize-order attempted
- config hash mismatch
- last fill stale beyond threshold
- auto-revert triggered

**Estimate**: 4–6 hours

**Expected dollar impact**: indirect but high; reduces blind trading.

---

### P1.3 — Add mutation verification with auto-revert

**Files**
- `scripts/run_btc5_autoresearch_cycle_core.py`
- `bot/auto_promote.py`
- `bot/promotion_manager.py`
- new `state/btc5_active_mutation.json`

**Change**

Every promoted BTC5 mutation must:

1. write mutation id + config hash
2. deploy
3. wait for N windows / M resolved fills
4. compare against incumbent
5. either keep or revert automatically

**Keep criteria**

- no cap breaches
- no config hash mismatch
- fill rate not worse than threshold
- net P&L after estimated rebates not worse than incumbent by a defined margin

**Revert immediately** on:

- oversize order attempt
- UP live order attempt
- service restart-loop
- config hash mismatch

**Estimate**: 6–8 hours

**Expected dollar impact**: medium-high; this is how self-improvement becomes real rather than theatrical.

---

### P1.4 — Normalize filter economics

**Files**
- `bot/btc_5min_maker.py`
- `data/btc_5min_maker.db` migration
- new `reports/btc5_filter_economics_latest.json`

**Change**

Create one structured schema for every skip/trade decision:

- `filter_name`
- `filter_state` (allowed / blocked / shadow-only)
- `counterfactual_trade_size_usd`
- `counterfactual_entry_price`
- `counterfactual_direction`
- `realized_if_taken` (when later resolvable)
- `estimated_ev_if_taken`
- `prevented_loss_usd`
- `opportunity_cost_usd`
- `net_filter_value_usd`

Then compute keep/soften/kill decisions for filters.

**Why**

You do not find edge by stacking more filters. You find edge by learning which filters actually create money.

**Estimate**: 6–10 hours

**Expected dollar impact**: medium; this is the research engine for BTC5 DOWN.

---

## P2: tasks for days 4–14

### P2.1 — Make `jj_live.py` and BTC5 ownership explicit and testable

**Files**
- `bot/jj_live.py`
- tests around `is_dedicated_btc5_market()` and execution skip

**Change**

Codify the rule:

- `jj_live.py` may scan fast-flow markets
- `jj_live.py` may not execute dedicated BTC5 windows
- `btc_5min_maker.py` is sole BTC5 executor

Add tests so this cannot drift.

**Estimate**: 2–3 hours

---

### P2.2 — Unify simulation authority or freeze one simulator

**Files**
- `simulator/engine.py`
- `simulator/simulator.py`
- `src/maker_fill_model.py`
- docs naming the authoritative simulator

**Change**

Pick one simulator as authoritative for BTC5 policy search.

Requirements:

- same calibration contract as live
- same price-cap logic as live
- same fill model as live, or explicitly conservative
- same direction/hour filters as live

Archive or freeze the non-authoritative simulator.

**Estimate**: 8–12 hours

**Expected dollar impact**: indirect but important; prevents the system from optimizing against contradictory worlds.

---

### P2.3 — Build a narrow BTC5 truth bundle for research and investor-safe summaries

**Files**
- new `reports/btc5_truth_bundle_latest.json`
- docs / summary scripts

**Contents**

- wallet-authoritative BTC5 P&L
- BTC5 DB P&L
- discrepancy field
- current mutation id
- config hash
- last 50 resolved fills
- hour / price / direction slice table
- current recommendation: continue, hold, or kill

**Why**

No more hand-built narratives. One file should tell the truth.

**Estimate**: 4–6 hours

---

## Prioritized task table

| Priority | Task | Files | Est. hours | Expected impact |
|---|---|---:|---:|---|
| P0 | Atomic window reservation before order placement | `bot/btc_5min_maker.py`, DB write path | 4–6 | Prevents repeat of catastrophic oversize duplicate-window behavior |
| P0 | Execution-layer notional cap assert | `bot/polymarket_clob.py`, BTC5 caller | 2–3 | Prevents any oversize order from reaching venue |
| P0 | UP hard kill in code defaults + tests | `bot/btc_5min_maker.py`, config, tests | 1–2 | Removes the sleeve that already lost ~$1,060 |
| P0 | TOD filter live enforcement | BTC5 maker + config + tests | 1–2 | Removes documented losing hours |
| P0 | DOWN price cap = 0.48 with startup verification | config + startup checks | 1 | Enforces the only price band with documented positive EV |
| P1 | Single generated `btc5_effective.env` | deploy + autoresearch + generated artifact | 5–7 | Removes silent env drift |
| P1 | 30-minute BTC5 health contract | health monitor + scripts + Telegram | 4–6 | Makes operation inspectable and fail-fast |
| P1 | Mutation verify / auto-revert | promotion / autoresearch state machine | 6–8 | Turns research into governed self-improvement |
| P1 | Filter economics ledger | BTC5 DB + reports | 6–10 | Finds real edge faster |
| P2 | Explicit JJ/BTC5 ownership boundary | `jj_live.py` + tests | 2–3 | Prevents cross-surface drift |
| P2 | Simulator unification / freeze | simulator modules + docs | 8–12 | Stops optimizing against contradictions |
| P2 | BTC5 truth bundle | reports + scripts | 4–6 | Gives one summary surface for decisions |

---

## What to delete or archive

Do not start with a repo-wide purge. Start with narrow subtraction.

### Archive now

- any BTC5 docs or profiles still implying UP is live-worthy
- any docs still implying stage-1 size is above $5
- any public or internal summary still quoting stale positive fund-level P&L
- stale `FAST_TRADE_EDGE_ANALYSIS.md` claims as an execution authority

### Freeze now

- non-authoritative BTC5 simulator after choosing the winner
- any BTC5 mutation path that writes directly to multiple env files without generating a single effective contract

### Keep but demote

- broader `jj_live.py` research surfaces
- non-BTC5 strategy modules

The near-term goal is not deleting half the repo. It is **making BTC5 small enough to reason about**.

---

## Rollout plan

### First 24 hours

1. Patch atomic window reservation.
2. Add execution-layer cap assert.
3. Make UP fail-closed in code.
4. Turn hour filter and 0.48 DOWN cap into verified startup config.
5. Deploy.
6. Watch one full trading session.

### First 3 days

1. Generate single effective BTC5 env.
2. Add 30-minute health contract.
3. Add mutation id + config hash tracking.
4. Turn on auto-revert for safety failures only.
5. Collect first post-fix sample.

### First 2 weeks

1. Build filter economics.
2. Decide whether DOWN-only survives.
3. If DOWN-only remains negative after the post-fix sample, **kill BTC5 entirely**.
4. Only then consider reallocating effort to Kalshi weather or structural lanes.

---

## Acceptance criteria

A task is not done unless all of these are true:

### Safety

- No live order can be submitted above `effective_max_trade_usd`.
- No more than one BTC5 live order sequence can exist per `window_start_ts`.
- UP orders cannot go live, even if one env overlay is missing.

### Truth

- One generated BTC5 config hash exists and matches the running service.
- Health artifact updates every 30 minutes.
- Health artifact answers the five operator questions.

### Research

- Filter economics report shows value by hour, direction, and price bucket.
- Mutation id is attached to every post-promotion fill.
- Auto-revert works on deliberate test mismatch.

### Trading

- 50 resolved post-fix DOWN-only fills collected with no cap breaches.
- If net P&L after estimated rebates is still non-positive over that controlled sample, BTC5 is paused or killed.

---

## Risks and non-goals

### Risks

- The exact March 15 oversize mechanism cannot be proven from this packet alone; the atomicity hole is the strongest code-level explanation, but direct March 15 runtime logs are still missing.
- DOWN-only may still fail even after price and hour filters. That is acceptable. The system’s job is to discover that fast.
- Env simplification touches deployment behavior, so rollout must be staged.

### Non-goals

- No new investor narrative.
- No scaling of size.
- No broad platform rewrite.
- No new strategy family until BTC5 is either proven under the fixed control plane or killed.

---

## Final instruction

Do not treat this as a research wishlist.

Treat it as a kill/fix/prove sequence:

1. **Kill the broken behavior.**
2. **Fix the control plane.**
3. **Prove the remaining edge.**
4. **If the edge does not survive controlled reality, kill BTC5 and move on.**
