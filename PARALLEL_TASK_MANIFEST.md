# PARALLEL TASK MANIFEST — Elastifund Systems
## Generated: 2026-03-07 | Author: JJ (Autonomous Execution Layer)

---

**Principle:** Most workstreams below are independent and should run in parallel. The only material coupling is that Stream 4 benefits from Stream 2's market-depth WebSocket before it graduates from shadow mode.

**Capital:** $247.51 USDC (Polymarket) + $100 USD (Kalshi) = $347.51 total
**Infrastructure:** Dublin VPS (AWS Lightsail eu-west-1, 52.208.155.0), jj-live.service STOPPED
**Bot Status:** 14 modules, 9 ready, 5 blocked on package installs
**Edge Status:** REJECT ALL — zero validated alpha

---

## EXECUTION UPDATE — STREAM 4 (2026-03-07)

Instance 3 (A-6 sum-violation scanner) and the current B-1 graph/runtime were executed on March 7, 2026 against live public Polymarket data. The combinatorial-arb deep dive is now integrated into the repo, tests, and manifest.

| Task | Status | Evidence |
|---|---|---|
| 4.1 Upgrade A-6 discovery to `/events` | COMPLETE | [`bot/sum_violation_scanner.py`](bot/sum_violation_scanner.py) now pages Gamma `GET /events` and flattens watchlist-safe neg-risk event groups via [`strategies/a6_sum_violation.py`](strategies/a6_sum_violation.py) |
| 4.2 Add market-depth WebSocket support | COMPLETE | [`infra/clob_ws.py`](infra/clob_ws.py) now provides chunked market/user channel clients and a shared best-bid/ask store for A-6/B-1 |
| 4.3 Handle CLOB 404 bootstrap cleanly | COMPLETE | A-6 quote fetch quarantines missing order books as suspended legs/events instead of crashing the scan |
| 4.4 Compute sum violations | COMPLETE | Live run: `events=100`, `candidates=2`, `selected=11`, `quotes=11`, `blocked=0`, `violations=2` |
| 4.5 Fee-adjusted / execution-aware edge scoring | COMPLETE | `ConstraintArbEngine.scan_sum_violations()` now logs `a6_mode=neg_risk_sum`, settlement-path metadata, per-leg tick sizes, and A-6 episode ids alongside `maker_sum_bid`, spreads, fill risk, score, and execute readiness |
| 4.6 Build B-1 candidate pruning | COMPLETE | [`strategies/b1_dependency_graph.py`](strategies/b1_dependency_graph.py) now applies category/subcategory gates, time windows, and top-K semantic neighbor pruning |
| 4.7 Build B-1 classifier + cache | COMPLETE | [`strategies/b1_dependency_graph.py`](strategies/b1_dependency_graph.py) now ships the exact JSON prompt scaffold plus sqlite caching in `state/arb_graph.db` |
| 4.8 Run live B-1 monitor | EXECUTED | Public-data slice runs completed on 200 and 500 active markets. Result: `edges=344` then `edges=1059`, all `same_event_sum`, `violations=0` in both runs |
| 4.9 Historical backtest / gold set / weekly audit | IN PROGRESS | Validation harness exists; next gate is 50 human-labeled pairs with >=85% precision, not just graph volume |
| 4.10 Integrate into `jj_live.py` | PENDING | Structural-arb execution routing, linked-leg posting, and rollback posting are still not wired into the live trader |
| 4.11 Kill gate at day 14 | IN PROGRESS | Scanner/reporting path is ready; the 14-day observation window now tracks maker-fill, violation half-life, and settlement-path evidence in addition to capture |
| 4.12 Research ingest + telemetry schema | COMPLETE | Dedicated `arb_scan_snapshot`, `a6_violation_episode`, `arb_order_group`, `arb_order_leg`, `arb_settlement_op`, and `arb_latency_sample` tables landed with upgraded empirical reporting |

Artifacts generated:
- [`logs/sum_violation_events.jsonl`](logs/sum_violation_events.jsonl)
- [`reports/constraint_arb_shadow_report.md`](reports/constraint_arb_shadow_report.md)
- [`reports/arb_empirical_snapshot.md`](reports/arb_empirical_snapshot.md)
- [`data/constraint_arb.db`](data/constraint_arb.db)

## REPRIORITIZATION UPDATE — STRUCTURAL ARB (2026-03-07)

The March 7 execution-validity review changes the work order materially. We are no longer treating Stream 4 as “build the broad combinatorial stack, then measure later.”

Observed live-public-data gate:
- A-6 allowed neg-risk universe audited: **92** events after current category filters.
- Cheapest-construction mix in that slice: **71 two-leg straddles**, **21 neg-risk-conversion variants**, **0 full-basket winners**.
- Events under the initial executable threshold (`cost < 0.95`): **0**.
- B-1 deterministic template audit across **1,000** active allowed markets found **0** template-compatible pairs.

Implication:
- The immediate bottleneck is **execution validity**, not architecture.
- A-6 stays first, but as a **Guaranteed Dollar Scanner** measuring top-of-book cost, fill rate, and dwell time.
- B-1 narrows to a **Templated Dependency Engine** and should not expand into a broad graph until one event family proves live density.

New mandatory Phase 0 gate:
1. Measure top-of-book and fill outcomes for the allowed neg-risk universe.
2. Record cheapest guaranteed-dollar construction type by event.
3. Record dwell time and passive fill behavior at actual `$5/leg` size.
4. Kill the lane early if the cheapest construction almost never clears the `$0.05 on the dollar` threshold.

---

## STREAM 1: LIVE TRADING RESTART
**Priority:** CRITICAL — Everything else is academic without live data
**Owner:** John (VPS access required)
**Duration:** 2 hours

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 1.1 | SSH into Dublin VPS | `ssh -i ~/.ssh/jj-dublin.pem ubuntu@52.208.155.0` | Connected |
| 1.2 | Install blocked packages | `pip install py-clob-client anthropic websockets httpx structlog` | All 5 install clean |
| 1.3 | Verify .env configuration | Confirm POLYMARKET_API_KEY, ANTHROPIC_API_KEY, CLOB_API_KEY, TELEGRAM_BOT_TOKEN all set | `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.getenv('POLYMARKET_API_KEY')[:8])"` returns non-None |
| 1.4 | Lower position size to $0.50 | Edit jj_live.py: `MAX_POSITION_USD = 0.50`, `MAX_DAILY_LOSS_USD = 5`, `KELLY_FRACTION = 0.25` | Config confirmed in logs |
| 1.5 | Set PAPER_TRADING = False | We need real resolved trades for calibration data | Config change committed |
| 1.6 | Restart jj-live.service | `sudo systemctl restart jj-live.service && journalctl -u jj-live -f` | Target service status after restart: active (running) |
| 1.7 | Verify first scan cycle | Watch logs for market scan → probability estimation → order placement | First maker order placed or "no qualifying markets" logged |
| 1.8 | Confirm Telegram notifications | Verify trade alerts arrive in Telegram channel | At least one notification received |

**Success metric:** 20 orders placed within 48 hours. 100 resolved trades within 7 days.

**Why this matters:** The edge discovery pipeline rejected everything for insufficient data. We cannot validate ANY strategy without live resolved outcomes. Every day we delay is a day of zero learning.

---

## STREAM 2: WEBSOCKET INFRASTRUCTURE (SA-001)
**Priority:** HIGH — Enables VPIN, OFI, lead-lag, and all latency-sensitive strategies
**Owner:** Claude Code agent (can run on local dev while VPS trades)
**Duration:** 3-4 days

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 2.1 | Implement ws_trade_stream.py connection logic | Persistent WebSocket to `wss://ws-subscriptions-clob.polymarket.com/ws/` with reconnect + heartbeat | Unit test: connect → receive → disconnect → auto-reconnect |
| 2.2 | Wire trade stream into VPIN calculator | Real-time volume bucket updates from WebSocket ticks → VPINManager | VPIN value updates on each incoming trade |
| 2.3 | Wire trade stream into OFI calculator | 5-level weighted order flow imbalance from book snapshots | OFI signal emits on book update |
| 2.4 | Add circuit breaker | If WebSocket disconnects > 3 times in 5 min, fall back to REST polling | Fallback triggers and logs warning |
| 2.5 | Latency benchmarking | Measure tick-to-signal latency; target < 50ms | p99 latency logged per session |
| 2.6 | Integration test with jj_live.py | WebSocket layer feeds toxicity vetoes and execution-quality metrics into the main loop | jj_live.py logs VPIN + OFI values alongside structural-arb state |

**Depends on:** Nothing. This is pure infrastructure. Can develop and test locally, deploy to VPS later.

---

## STREAM 3: ADAPTIVE PLATT CALIBRATION (D-12)
**Priority:** HIGH — Current static params may be overfit to historical window
**Owner:** Claude Code agent
**Duration:** 1 day

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 3.1 | Implement rolling window Platt re-fit | Sliding window of N most recent resolved markets, re-estimate A and B | Function: `rolling_platt_fit(resolved_markets, window=100)` returns (A, B) |
| 3.2 | Walk-forward validation | Test on 532 historical markets: train on first 400, validate on last 132 | Out-of-sample Brier score reported |
| 3.3 | Compare static vs adaptive | Static (A=0.5914, B=-0.3977) vs rolling (window=50, 100, 200) | Table of Brier scores per variant |
| 3.4 | If adaptive wins: update jj_live.py | Replace static PLATT_A / PLATT_B with rolling recalibration on each new resolved trade | Calibration params logged per trade cycle |
| 3.5 | If static wins: document why and move on | Write finding to research/dispatches/ | Dispatch filed, backlog updated |

**Depends on:** Nothing. Uses existing historical data in SQLite.

---

## STREAM 4: COMBINATORIAL ARBITRAGE DEPLOYMENT (A-6 + B-1)
**Priority:** HIGH — But now explicitly gated by live executable density
**Owner:** Claude Code agent
**Duration:** 10-14 days

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 4.1 | Phase 0 A-6 universe audit | Measure the current allowed neg-risk universe, cheapest construction mix, and top-of-book costs | COMPLETE — see `reports/guaranteed_dollar_audit.*` |
| 4.2 | A-6 top-of-book instrumentation | Track YES and NO token top-of-book quotes, optional sizes, and batch `/prices` refresh | COMPLETE — `infra/clob_ws.py`, `signals/sum_violation/sum_discovery.py` |
| 4.3 | A-6 guaranteed-dollar ranking | Rank `YES+NO`, neg-risk-conversion, and full-basket constructions by executable cost | COMPLETE — `signals/sum_violation/guaranteed_dollar.py` |
| 4.4 | A-6 fill-rate / dwell study | Keep the scope narrow: dwell time, passive fill rate, and one-leg loss at `$5/leg` | PENDING — needs multi-hour live collection, not more architecture |
| 4.5 | A-6 live execution state machine | Enforce maker-only TTL, rollback, unwind timeout, and linked-leg tracking | IN PROGRESS — `execution/multileg_executor.py` is wired; live posting remains partial |
| 4.6 | B-1 template-density audit | Measure whether deterministic template families even exist in the live allowed universe | COMPLETE — `reports/b1_template_audit.*` currently shows `0` pairs in 1,000 markets |
| 4.7 | B-1 templated dependency engine | Restrict initial scope to deterministic families and compatibility matrices | IN PROGRESS — `strategies/b1_templates.py` landed; live family-specific gold set still pending |
| 4.8 | B-1 broad graph expansion gate | Only expand past templates if one event family shows real density and good precision | BLOCKED — current live audit does not justify broad expansion |
| 4.9 | Integrate into `jj_live.py` | Route only after the empirical gate says the lane is worth trading | BLOCKED — premature until Phase 0 fill/dwell data exists |
| 4.10 | Shadow mode attribution | Run 14-day paper mode with fill simulation, capture ratio, and rollback-loss metrics | PENDING |
| 4.11 | Enforce kill switches | Halt on poor capture, sparse density, classifier drift, or negative live P&L | IN PROGRESS |

**Depends on:** Stream 2 for the WebSocket data plane. Everything else is local implementation work.

---

## STREAM 5: CROSS-PLATFORM ARBITRAGE ACTIVATION
**Priority:** MEDIUM — Code complete, needs operational activation
**Owner:** John (Kalshi account verification) + Claude Code agent
**Duration:** 2-3 days

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 5.1 | Verify Kalshi account status | Confirm $100 USD balance, API access enabled, trading permissions | API call returns account balance |
| 5.2 | Run cross_platform_arb.py market matching | Execute full Polymarket ↔ Kalshi scan | Matched markets list with similarity scores |
| 5.3 | Identify live arb opportunities | Filter for YES_ask + NO_ask < $1.00 after fees | Opportunity list (may be empty — that's data) |
| 5.4 | If opportunities exist: paper trade 5 | Execute on paper to verify fill rates and timing | Paper P&L logged |
| 5.5 | Document findings | Even if zero arbs found, document why (fee structure, spread too wide, etc.) | Dispatch filed |

**Depends on:** Nothing. Module is READY status with 29 passing tests.

---

## STREAM 6: ENSEMBLE DISAGREEMENT SIGNAL (D-9)
**Priority:** MEDIUM — Trivial to implement, improves position sizing immediately
**Owner:** Claude Code agent
**Duration:** 4 hours

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 6.1 | Add std() calculation to ensemble_estimator.py | After all models return estimates, compute `np.std(estimates)` | Function returns (mean, std) tuple |
| 6.2 | Wire disagreement into Kelly sizing | High disagreement (std > 0.15) → reduce position to 1/32 Kelly. Low disagreement (std < 0.05) → allow full quarter-Kelly | Sizing modifier logged per trade |
| 6.3 | Backtest on 532 historical markets | Compare: flat sizing vs disagreement-adjusted sizing | Simulated P&L comparison |
| 6.4 | If positive: deploy | Update jj_live.py to use disagreement-adjusted sizing | Config change on VPS |

**Depends on:** Nothing. Pure computation on existing ensemble output.

---

## STREAM 7: POSITION MERGING (G-8)
**Priority:** MEDIUM — Operational necessity, frees locked capital
**Owner:** Claude Code agent
**Duration:** 1 day

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 7.1 | Audit current open positions | Query Polymarket for all positions held by proxy wallet | Position list with size, entry price, current price |
| 7.2 | Implement poly_merger integration | Use open-source position merging to consolidate fragmented positions | Merged positions confirmed on-chain |
| 7.3 | Calculate freed capital | Before vs after merge: how much USDC released? | Dollar amount logged |
| 7.4 | Update neg_risk_inventory.py | Reflect merged state in local tracking | Inventory matches on-chain state |

**Depends on:** Nothing. Uses existing neg_risk_inventory.py (READY status).

---

## STREAM 8: EDGE DISCOVERY PIPELINE — CONTINUOUS DATA COLLECTION
**Priority:** HIGH — Background process, feeds all strategy validation
**Owner:** Claude Code agent (or cron on VPS)
**Duration:** Ongoing (14+ days minimum)

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 8.1 | Restart edge discovery daemon | `src/main.py` in continuous mode, 15-min BTC candle collection | Process running, logging to edge_discovery.db |
| 8.2 | Fix CLOB 404 errors | Some token IDs return 404 on order book endpoint — identify and exclude or fix | Zero 404s in 24-hour window |
| 8.3 | Expand market coverage | Currently 13 markets on 15-min. Target: 50+ markets across categories | Market count in pipeline > 50 |
| 8.4 | Accumulate 25+ resolved signals | Pipeline needs ≥25 resolved outcomes per hypothesis family | FAST_TRADE_EDGE_ANALYSIS.md shows ≥25 signals |
| 8.5 | Re-run kill battery weekly | Every 7 days, execute full kill_rules.py battery on accumulated data | Weekly dispatch with CONTINUE/KILL verdicts |
| 8.6 | Re-evaluate Chainlink basis lag (RE1) | Maker-only eliminates taker fee — does edge survive under new cost model? | Verdict: PROMOTE to BUILDING or KILL |

**Depends on:** Nothing. Independent data collection process.

---

## STREAM 9: DOCUMENTATION & PUBLISHING
**Priority:** MEDIUM — Serves dual mission (education + credibility)
**Owner:** Claude Code agent
**Duration:** Ongoing, 2-3 hours per cycle

| # | Task | Detail | Done When |
|---|------|--------|-----------|
| 9.1 | Refresh agent docs | Keep `AGENTS.md`, `docs/REPO_MAP.md`, and `ProjectInstructions.md` aligned with the current architecture, module inventory, and capital state | Canonical context docs all current |
| 9.2 | Write Dispatch #79 | Document this task manifest and the parallel execution decision | Dispatch filed in research/dispatches/ |
| 9.3 | Update edge_backlog_ranked.md | Re-rank based on maker-only pivot impact, remove stale entries | Backlog reflects current reality |
| 9.4 | Push to GitHub | All code changes, documentation updates, new dispatches | `git push` succeeds, CI green |
| 9.5 | Update README.md | Current capital, strategy count, test count, honest status | README matches reality |
| 9.6 | Write "What Doesn't Work" diary entry | Document all 10 rejected strategies with specific failure modes | Published to research/ |

**Depends on:** Results from other streams (but can start immediately with current state).

---

## DEPENDENCY MATRIX

```
Stream 1 (Live Trading)      ──→ independent
Stream 2 (WebSocket)         ──→ independent
Stream 3 (Platt Calibration) ──→ independent
Stream 4 (Combinatorial Arb) ──→ depends on Stream 2 for the low-latency WebSocket data plane
Stream 5 (Cross-Platform)    ──→ independent
Stream 6 (Disagreement)      ──→ independent
Stream 7 (Position Merge)    ──→ independent
Stream 8 (Data Collection)   ──→ independent
Stream 9 (Documentation)     ──→ can start now, incorporates results as they arrive
```

Eight streams remain independent. Stream 4 benefits materially from Stream 2, but can still progress on discovery, validation, and execution-state work before the market-depth stream is finished. Stream 9 absorbs outputs from all others and can begin immediately.

---

## TIMELINE

| Day | Stream 1 | Stream 2 | Stream 3 | Stream 4 | Stream 5 | Stream 6 | Stream 7 | Stream 8 | Stream 9 |
|-----|----------|----------|----------|----------|----------|----------|----------|----------|----------|
| 1 | DEPLOY | Start | Start | Start | Start | COMPLETE | Start | Start | Start |
| 2 | Monitor | Build | COMPLETE | A-6 data plane | Verify | — | COMPLETE | Collect | Write |
| 3 | Monitor | Build | — | A-6 execution | Scan | — | — | Collect | Push |
| 4 | 20 orders | Build | — | B-1 gold set | COMPLETE | — | — | Collect | — |
| 7 | 50 trades | COMPLETE | — | B-1 live monitor | — | — | — | Collect | Update |
| 14 | 100 trades | — | — | SHADOW GO/KILL | — | — | — | 25 signals | Update |

---

## KILL RULES (Per Stream)

- **Stream 1:** If zero fills after 48 hours of live orders, diagnose order placement (price too aggressive? wrong side of spread? API error?)
- **Stream 2:** If WebSocket connection cannot maintain 5 min uptime after 3 days of debugging, fall back to optimized REST polling
- **Stream 3:** If adaptive Platt shows worse OOS Brier than static, keep static. No sunk cost.
- **Stream 4:** If A-6 never clears the initial `$0.05 on the dollar` gate in the allowed universe, or if B-1 template density stays effectively zero, KILL or freeze the lane immediately.
- **Stream 4:** If A-6 capture falls below 50% of theoretical over 20 events, or B-1 false-positive rate exceeds 5%, KILL the affected lane immediately.
- **Stream 5:** If zero arb opportunities across 100+ matched markets, document and deprioritize. Fee structures may have eliminated this.
- **Stream 6:** If disagreement signal shows zero correlation with trade outcome after 50 trades, remove the modifier
- **Stream 7:** If position merging fails on-chain, escalate to John for manual intervention
- **Stream 8:** If CLOB 404s persist across >30% of markets, switch to Gamma API snapshots (lower fidelity but reliable)
- **Stream 9:** No kill rule. Documentation never stops.

---

## RESOURCE ALLOCATION

| Resource | Streams Using It | Contention Risk |
|----------|-----------------|-----------------|
| Polymarket API (REST) | 1, 4, 5, 7, 8 | LOW — rate limits are generous |
| Polymarket WebSocket | 2, 4 | LOW — shared feed, but same infra class |
| Kalshi API | 5 | NONE — dedicated |
| Anthropic API (Claude) | 1, 3, 4, 6 | LOW — B-1 adds cheap classification traffic |
| Dublin VPS CPU | 1, 2, 4, 8 | MEDIUM — monitor load after WebSocket + live trading |
| SQLite (edge_discovery.db / constraint_arb.db) | 1, 3, 4, 8 | LOW — write-ahead logging handles concurrent reads |
| John's attention | 1, 5 | HIGH — these two need human action |

---

*Nine streams. Only one meaningful dependency: Stream 4 wants Stream 2's market-depth WebSocket before promotion out of shadow mode. The only human blockers remain package installation on the VPS (Stream 1, task 1.2) and Kalshi account verification (Stream 5, task 5.1).*

*Stop planning. Start executing.*
