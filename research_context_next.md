# Research Context Next

## Purpose

This file is the starting context for the next deep research run.

The goal is not to produce another abstract architecture memo. The goal is to:

1. Make the self-improvement system actually functional end-to-end.
2. Find the fastest credible path to real live trading profits on an approximately `$1K` portfolio.
3. Push hard for weird, overlooked, public-data, market-structure, and execution edges that others are not exploiting well.
4. Improve the system in a way that compounds, not just patch one bad day.

This brief is intentionally opinionated. Treat it as a high-signal operating context, not a neutral summary.

---

## North Star

Build a proof-carrying, self-improving trading system that:

- turns fresh evidence into typed theses,
- promotes only validated edge into live capital,
- learns from every outcome,
- and compounds a small bankroll through high-turnover, high-confidence, low-capital structural opportunities.

For this phase, optimize for:

- realized dollars,
- clean proof-to-capital flow,
- high turnover on small capital,
- fast rejection of bad ideas,
- and weird structural alpha over generic prediction.

Do not optimize for:

- fancy prompts,
- more overlapping control planes,
- another generic multi-agent architecture,
- or direction-prediction hype without post-cost proof.

---

## Current System Snapshot

### Live and control-plane reality as of 2026-03-22

Use these artifacts as the current truth surface:

- `reports/runtime_truth_latest.json`
- `reports/live_pnl_scoreboard/latest.json`
- `reports/evidence_bundle.json`
- `reports/thesis_bundle.json`
- `reports/promotion_bundle.json`
- `reports/capital_lab/latest.json`
- `reports/learning_bundle/latest.json`
- `reports/autoresearch/research_os/latest.json`
- `reports/autoresearch/providers/moonshot/latest.json`
- `reports/trade_proof/latest.json`

### What the system is actually saying right now

- `runtime_truth_latest.json`
  - `status`: `blocked`
  - `execution_mode`: `shadow`
  - `allow_order_submission`: `false`
  - `verification_status`: `failing`
  - explicit blockers exist around trade-count divergence and wallet export conflicts

- `live_pnl_scoreboard/latest.json`
  - schema: `btc5_daily_pnl.v1`
  - ET-day realized BTC5 live PnL: `-21.6707`
  - rolling-24h realized BTC5 live PnL: `-21.6707`
  - fill count: `5`
  - latest fill timestamp present
  - this is currently the cleanest operator-facing one-day BTC5 loss surface

- `evidence_bundle.json`
  - `status`: `stale`
  - summary says only `3` evidence items from `3` sources
  - stale blockers include:
    - `stale_source:novelty_discovery`
    - `stale_source:weather_divergence`

- `thesis_bundle.json`
  - `status`: `fresh`
  - `4` theses compiled
  - this means thesis compilation exists, but it is being fed partially stale evidence

- `promotion_bundle.json`
  - `status`: `fresh`
  - summary: `0 approved, 4 held, 0 killed, capital=0.00`
  - promotion logic exists, but it is not producing capitalized live action

- `capital_lab/latest.json`
  - `status`: `fresh`
  - summary: proving ground active for `btc5` and `weather`
  - `self_improving`: `false`
  - current lane metrics:
    - `btc5`
      - cumulative PnL: `-28.6661`
      - fills: `23`
      - win rate: `43.48%`
      - profit factor: `0.415`
      - promotion gate: `pass=false`
    - `weather`
      - unique days: `3`
      - executed_count: `10`
      - promotion gate: `pass=false`

- `trade_proof/latest.json`
  - `status`: `blocked`
  - `proof_status`: `no_fill_yet`
  - `fill_confirmed`: `false`

- `learning_bundle/latest.json`
  - candidate generation exists
  - Kimi section says:
    - `status`: `not_configured`
    - `model`: `moonshot-v1-8k`
    - `calls_this_run`: `0`
  - meaning: learning ideas exist, but low-cost external breadth is not being used in practice

- `autoresearch/research_os/latest.json`
  - `status`: `fresh`
  - health: `degraded`
  - lanes healthy: `0/3`

- `reports/parallel/instance04_weather_divergence_shadow.json`
  - generated `2026-03-12`
  - stale by about ten days

- `reports/opportunity_exchange/latest.json`
  - missing

### Bottom-line diagnosis

The system is architecture-forward but operationally incomplete.

It has:

- evidence,
- thesis,
- promotion,
- learning,
- capital lab,
- daily PnL,
- and architecture docs.

But it does not yet have a clean, reliable, always-fresh, capitalized proof-to-execution loop.

Today it is best described as:

**a blocked proving-ground machine with useful architecture, incomplete truth, stale evidence, and no approved capitalized edge.**

---

## What Already Exists and Should Be Reused

Do not reinvent these.

### Canonical architecture

Read these first:

- `docs/architecture/proof_carrying_kernel.md`
- `docs/architecture/strike_desk.md`
- `docs/architecture/intelligence_harness.md`
- `docs/architecture/promotion_ladder.md`
- `docs/architecture/event_sourced_tape.md`
- `docs/architecture/temporal_edge_memory.md`
- `docs/architecture/qd_thesis_repertoire.md`

### Important existing modules

- `bot/strike_desk.py`
  - already encodes priority ordering for:
    - negative risk
    - cross-platform arb
    - resolution sniper
    - whale copy
    - semantic lead-lag
    - LLM tournament

- `bot/maker_velocity_blitz.py`
  - already contains dual-sided structural logic:
    - `rank_dual_sided_spread_markets`
    - `allocate_dual_sided_spread_notional`
    - `build_dual_sided_spread_intents`
  - current defaults imply a structural pair-completion path:
    - `combined_cost_cap = 0.97`
    - toxicity and liquidity filters
    - small per-market caps

- `bot/neg_risk_scanner.py`
- `bot/resolution_sniper.py`
- `bot/cross_platform_arb_scanner.py`
- `bot/whale_tracker.py`
- `scripts/btc5_daily_pnl.py`
- `scripts/capital_lab.py`
- `scripts/intelligence_harness.py`
- `scripts/write_remote_cycle_status.py`
- `scripts/remote_cycle_status_core.py`
- `bot/wallet_reconciliation.py`

### Strong current architectural idea

The repo already converged on the right shape:

- append-only facts and event tape,
- typed evidence,
- typed thesis,
- promotion bundle as the only path to capital,
- learning bundle as mutation-only,
- intelligence harness as the acceptance gate,
- strike desk as the monetization layer.

The job now is not more architecture invention.
The job is to make this architecture actually function.

---

## Hard Truths We Should Not Ignore

### 1. Directional BTC5 is not currently validated edge

Current BTC5 proving-ground stats are not good enough:

- cumulative PnL: `-28.6661`
- profit factor: `0.415`
- win rate: `43.48%`
- promotion gate: fail

This means directional BTC5 should be treated as:

- a research/proving-ground lane,
- a shadow or micro-live lane,
- not the center of gravity for live capital.

### 2. The current daily loss was real and came from directional exposure

The ET-day BTC5 live scoreboard is currently red at `-21.6707`.

That matters because it means the live sleeve is still behaving like:

- a directional micro-betting loop,

not like:

- a structural alpha engine,
- a locked-edge desk,
- or a validated promotion-based capital allocator.

### 3. The self-improvement loop is not yet genuinely self-improving

Right now:

- evidence can be stale,
- learning can generate candidates without changing capital allocation,
- promotion can hold everything,
- Kimi can sit idle,
- weather can be stale,
- and opportunity exchange can be missing.

That is not a clean flywheel.

### 4. Truth is still too fragile

The system currently allows a state where:

- runtime truth is blocked,
- live PnL exists in a separate scoreboard,
- trade proof is blocked,
- wallet truth can disagree,
- and capital remains in hold.

That should be impossible.

### 5. We should be skeptical of generic indicator strategy marketing

The repo has already rejected multiple strategy families that sounded plausible and failed after costs or evidence gates.

Read:

- `research/what_doesnt_work_diary_v1.md`
- `docs/diary/2026-03-06-twelve-strategies-rejected.md`

Important prior lessons:

- generic post-extreme mean reversion was rejected
- latency/taker-style crypto candle strategies were cost-killed
- signal count and post-cost discipline matter more than surface cleverness

Do not let the research run get seduced by:

- RSI/VWAP/MACD indicator soup,
- unverifiable copy-trading claims,
- or another prediction-first architecture.

---

## What "Making Money Fast" Should Mean Here

For a `$1K` portfolio, "making money fast" should mean:

- high-confidence, low-capital, high-turnover opportunities,
- small but repeatable structural alpha,
- maker-first or low-cost execution,
- low trapped capital,
- and opportunities where a small bankroll is an advantage rather than a handicap.

That means prioritizing:

- mispricings,
- stale quotes,
- pair completion,
- negative-risk baskets,
- resolution timing,
- queue-position advantage,
- market lifecycle quirks,
- and public source timing edges.

It does **not** mean:

- taking more naked directional risk,
- levering conviction without proof,
- or trying to out-forecast everyone on noisy 5-minute binaries.

---

## Highest-Priority Research Targets

These are the places where the next deep research run should push hard.

### A. Structural alpha that can work with small capital now

#### 1. Dual-sided pair completion

Research the strongest version of:

- buying both sides only when `YES + NO < 1.00` after all costs and execution risk,
- exploiting temporary incoherence in short-horizon binaries,
- using maker-first quoting and cancel/replace discipline,
- and closing the loop with merge/redeem mechanics where applicable.

Questions:

- How often do combined-cost violations happen in our target markets?
- Are they real after latency, partial fills, and queue priority?
- What is the best execution policy for tiny bankroll pair completion?
- Can this become the first live structural lane?

#### 2. Resolution sniper / known-outcome lag

Research:

- how often public truth sources move before the market reprices,
- how often stale resting quotes remain after the outcome is functionally known,
- and whether this is repeatable enough to be the first revenue lane.

Push for weird variants:

- official source publication cadence quirks,
- exchange lifecycle lags,
- overnight or low-attention windows,
- and market types where retail resting liquidity lingers longest.

#### 3. Negative-risk baskets

Research:

- same-event, multi-market, or duplicate semantics where the payout structure guarantees profit or near-guaranteed profit,
- how frequently the scanner can find these,
- whether our current merge/unwind path is enough,
- and how to operationalize this with tiny capital and low complexity.

#### 4. Queue dominance on small tickets

Research maker-only edge from:

- small order size,
- selective quoting,
- low footprint,
- queue awareness,
- and tiny-ticket execution where large players do not care.

Push beyond generic "market making":

- identify specific situations where tiny tickets and fast cancel discipline produce an edge that larger actors ignore.

### B. Weird edges others may have missed

This is where creativity should go.

Research weird but legal public-data edges such as:

- market birth and listing dislocations
- fast newly listed market mispricings
- correlated market incoherence after a source update
- stale low-liquidity brackets or temperature buckets
- settlement-source rounding or threshold quirks
- duplicate or near-duplicate event semantics across platforms
- time-to-resolution versus price inertia mismatches
- retail "anchoring" around round numbers in binaries
- quote staleness in thin overnight windows
- abandoned or low-attention markets with public truth drift
- public whale-following only when supported by structural filters
- cross-market pair relationships where one leg updates faster than the other
- edges caused by platform UX, not by forecasting genius

Important:

- prefer edges that are annoying, operational, or too small for others
- prefer edges where public data plus clean execution beats better prediction
- prefer edges that can turn over quickly on a small bankroll

### C. Self-improvement loop repairs that actually matter for returns

Research how to make the loop functional in practice:

1. fresh evidence in,
2. typed thesis out,
3. promotion ticket issued or held,
4. execution and proof captured,
5. outcome written to memory,
6. learning mutation only kept if it improves harness outcomes.

Push for improvements in:

- evidence freshness contracts and SLAs,
- truth-source precedence,
- mutation acceptance criteria,
- event-tape write coverage,
- strategy ranking,
- and capital routing.

The research run should not just say "improve the loop."
It should say exactly which changes most increase:

- approved promotions,
- clean live execution,
- and realized dollars.

---

## Current Bottlenecks to Fix First

If a proposed research path ignores these bottlenecks, it is probably not actionable.

### 1. Truth fragmentation

Need one authoritative chain:

- wallet truth
- fill ledger
- daily PnL
- runtime truth
- trade proof
- capital lab

Today these can disagree or degrade separately.

### 2. Stale evidence

Current evidence bundle is stale because critical sources are stale.

Research should specify:

- which evidence surfaces are mandatory for each lane,
- how stale they are allowed to become,
- and what should happen when they go stale.

### 3. Promotion without proof

Promotion exists but holds everything.

Research must answer:

- what minimum proof is required for the first structural live lane,
- how to get there quickly,
- and what evidence is currently missing.

### 4. Learning without capital impact

The learning bundle is generating ranked candidates, but the live system is not moving because of them.

Research must force the question:

- what mutations are actually worth keeping if they do not improve approval or profits?

### 5. Kimi / Moonshot underutilization

Current state:

- Moonshot artifact exists
- model shows as `moonshot-v1-8k`
- not active in practice

Research should decide one of two things:

1. activate Kimi with a specific, measurable role in failure clustering, candidate triage, and cheap breadth research, or
2. remove it from the critical path and stop pretending it is helping.

### 6. Missing opportunity exchange surface

The opportunity exchange report is missing.

Research should decide:

- is it truly needed as a first-class artifact,
- or should its role collapse into promotion bundle and capital lab?

No new parallel authority should be introduced.

---

## What the Research Run Must Produce

The research run should output a decision-complete packet, not a brainstorm.

### Required outputs

#### 1. Ranked edge table

At least `15` candidate edges ranked by:

- expected post-cost edge
- required fill quality
- time to first live dollar
- capital efficiency on `$1K`
- data availability
- implementation difficulty
- expected turnover
- failure modes
- why the edge is likely overlooked

Each row should say explicitly whether the edge is:

- structural
- predictive
- execution
- cross-market
- or self-improvement infrastructure

#### 2. Top 3 near-term revenue plays

Pick the three most credible paths to live profits in the next `7-14` days.

For each one:

- exact mechanism
- why it should work
- why others may not be exploiting it
- required code paths to reuse
- minimum evidence/proof needed
- recommended micro-live deployment shape

#### 3. Self-improvement repair plan

Specify exactly how to turn the current kernel into a real flywheel:

- evidence freshness
- thesis authority
- promotion gating
- event tape coverage
- learning acceptance
- capital routing

Must include:

- what to delete or demote
- what to make authoritative
- what artifacts must exist every cycle

#### 4. Harness expansion

Add concrete new replay scenarios and acceptance gates for:

- daily PnL truth mismatch
- stale evidence
- structural edge success/failure
- partial-fill pair completion
- stale quote opportunity decay

#### 5. Revenue-first implementation order

Give a strict launch order with:

- first lane
- second lane
- third lane
- what stays shadow
- what is explicitly deferred

---

## Strong Defaults and Biases for the Research Run

Use these defaults unless strong evidence says otherwise.

### Prefer

- structure over prediction
- maker-first over taker-first
- public truth over social noise
- tiny-ticket execution over large-ticket ambition
- repeatable dollars over elegant theory
- one authoritative control path over many overlapping loops
- typed artifacts over prose memory
- weird operational edges over standard TA

### Avoid

- naive generic mean reversion as the main path
- RSI/VWAP/MACD indicator stacking unless it beats structural baselines post-cost
- another top-level orchestration system
- capital expansion for BTC5 directional before proof
- ideas that require deep liquidity to work
- ideas with no realistic path to fill-aware replay

---

## Files the Research Run Should Read First

Read these in roughly this order:

1. `docs/architecture/proof_carrying_kernel.md`
2. `docs/architecture/strike_desk.md`
3. `docs/architecture/intelligence_harness.md`
4. `docs/architecture/promotion_ladder.md`
5. `docs/architecture/event_sourced_tape.md`
6. `reports/runtime_truth_latest.json`
7. `reports/live_pnl_scoreboard/latest.json`
8. `reports/evidence_bundle.json`
9. `reports/promotion_bundle.json`
10. `reports/capital_lab/latest.json`
11. `reports/learning_bundle/latest.json`
12. `reports/autoresearch/research_os/latest.json`
13. `reports/trade_proof/latest.json`
14. `research/what_doesnt_work_diary_v1.md`
15. `bot/strike_desk.py`
16. `bot/maker_velocity_blitz.py`
17. `scripts/btc5_daily_pnl.py`
18. `scripts/capital_lab.py`
19. `scripts/intelligence_harness.py`
20. `bot/wallet_reconciliation.py`

---

## Questions the Research Run Must Answer Clearly

1. What are the best three ways to make money with this system in the next two weeks?
2. Which current lanes should get capital, and which should be demoted?
3. What is the best weird edge that likely exists in our markets but is still underexploited?
4. What part of the self-improvement loop is most responsible for the system not compounding yet?
5. What exact changes would make the loop genuinely self-improving rather than candidate-generating?
6. Which opportunities are real enough to deploy with `$5-$25` tickets immediately after proof?
7. Which existing modules are underused and should become first-class?
8. Which modules or artifacts are noise and should be deleted, collapsed, or ignored?
9. Is there a route to a structural desk that can generate small daily profits with low trapped capital?
10. If the answer is "stop trading most current directional flow and focus on two structural lanes," say that directly.

---

## Final Instruction to the Deep Research Run

Be brutally empirical.

Do not sell optimism.
Do not produce another generic "multi-agent trading architecture."
Do not assume forecasting is the moat.
Do not optimize for elegance over dollars.

Find:

- the fastest path to real validated edge,
- the cleanest way to make the self-improvement loop actually govern capital,
- and the weirdest credible structural opportunities that a small, disciplined system can exploit better than bigger, lazier competitors.

If the best answer is:

- cut half the loops,
- freeze directional BTC5,
- and turn the repo into a structural strike desk with a real proof gate,

then say that clearly.

