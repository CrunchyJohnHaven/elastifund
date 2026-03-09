# COMMAND NODE — Predictive Alpha Fund

**Version:** 2.9.2
**Last Updated:** 2026-03-09
**Owner:** John Bradley (johnhavenbradley@gmail.com)
**Purpose:** Single source of truth for all AI instances (ChatGPT, Cowork, Claude Code, Grok) to operate with full project context. Paste this document (or relevant sections) into any new session so the AI can write prompts, make decisions, and build on prior work without re-discovery.
**Canonical filename:** `COMMAND_NODE.md`. Archived root variants belong under `archive/root-history/`, not at repo root.

---

## Version Log

| Version | Date | Change Summary |
|---------|------|----------------|
| 2.9.2 | 2026-03-09 | Resynced JJ-N to the newer worktree state: Website Growth Audit offer, templates, dashboard asset, unified approval gate, and `RevenuePipeline` now exist, `make test-nontrading` passes at `53` tests, but the repo-root JJ-N surface still fails one persisted-registry ranking test and `nontrading/main.py` is not wired to the pipeline. |
| 2.9.1 | 2026-03-09 | Synced JJ-N canonical docs to repo truth: `80` JJ-N tests across two surfaces, Elastic index template present, but the Website Growth Audit offer, JJ-N dashboard, SQLite registry backing, unified approval pipeline, and five-engine `RevenuePipeline` are still not built. |
| 2.9.0 | 2026-03-09 | Finalized the latest March 9 operator truth: `313` cycles, service `inactive` at `01:28:43Z`, local verification now at `962 + 22` root / `374` polymarket / `39` non-trading, the threshold refresh still found `0` tradeable markets at YES `0.15`, NO `0.05`; YES `0.08`, NO `0.03`; and YES `0.05`, NO `0.02`, deploy dry-run validated after the manifest fix, and JJ-N Phase 0 plus the 13-doc governance scaffold are now in repo. |
| 2.8.3 | 2026-03-09 | Finalized the command-node sync to the newest runtime artifacts: `313` cycles, service `inactive` at `01:28:43Z`, root verification back to `913 + 22` passing, fast-trade rerun at `01:23:49Z`, and launch blocked primarily by the stopped service plus first-trade/structural gates. |
| 2.8.2 | 2026-03-09 | Resynced to the newest runtime truth after the post-edit refresh: `311` cycles, service checked `inactive` at `01:26:48Z`, root-status artifact now failing on the `TelemetryBridge` import, fast-trade rerun at `01:23:49Z`, and launch still blocked with restart readiness revoked. |
| 2.8.1 | 2026-03-09 | Refreshed the command-node snapshot to the latest runtime truth: `308` cycles, service checked at `01:19:58Z`, fast-trade rerun at `01:19:40Z`, root verification `911 + 22` passing, and the latest deploy dry-run blocked on stale release-manifest checksums after snapshot refresh. |
| 2.8.0 | 2026-03-09 | Synced the latest stable runtime handoff after verification: `305` cycles, service checked at `01:06:09Z`, fast-trade rerun at `01:05:57Z`, full verification green, and the latest dry-run deploy blocked on a stale release-manifest path. |
| 2.7.0 | 2026-03-09 | Synced the latest stable public/runtime snapshots: `303` cycles, service checked at `00:48:05Z`, wallet-flow `ready`, root verification `passing`, and launch still blocked by first-trade/structural gates. |
| 2.6.0 | 2026-03-09 | Synced the stable public/runtime snapshot outputs: `301` runtime cycles, service checked at `00:44:19Z`, wallet-flow `ready` but `fast_flow_restart_ready=false`, and root verification currently failing. |
| 2.5.0 | 2026-03-09 | Synced the canonical March 9 artifact set: `298` runtime cycles, wallet-flow `ready`, refreshed fast-market/structural counts, and new doc/site snapshot wiring guidance. |
| 2.4.0 | 2026-03-09 | Integrated Elastic Vision Document and Platform Vision Document: added product definition (trading + non-trading workers on shared substrate), six-layer master architecture, non-trading five-engine architecture, numbered-docs governance plan, messaging system, opportunity scoring framework, JJ-N rollout plan, and vision-aligned Replit build priorities. |
| 2.3.0 | 2026-03-09 | Reconciled March 9 machine truth against the March 8 hold-state prose: the remote service artifact showed `active` while launch stayed blocked and no strategy promotion cleared. |
| 2.2.0 | 2026-03-08 | Synced Cycle 2 repo truth: verified test counts, paused-service posture, REJECT ALL pipeline status, dispatch inventory, and explicit no-promotion language for A-6/B-1. |
| 2.1.0 | 2026-03-08 | Added the Elastic observability lane: Kibana dashboards, APM instrumentation, ML anomaly feedback as signal source `#7`, and deployment notes for the new telemetry surface. |
| 2.0.0 | 2026-03-08 | Adopted stable canonical entrypoint naming, synced context references, and refreshed status counts to match the ranked backlog. |
| 1.1.1 | 2026-03-07 | Integrated A-6/B-1 combinatorial arbitrage build plan: Signal Sources 5/6, deterministic bypass routing, constraint-arb data stores, and repo-specific execution gates. |
| 1.1.0 | 2026-03-07 | Updated with JJ persona + prime directive, dual mission framing, 6-phase flywheel cycle, strategy status table (6 deployed / 5 building / 10 rejected / 30 pipeline), RTDS maker-edge and Dublin latency findings, refreshed document hierarchy, open-source guardrails, and website vision summary. |
| 1.0.2 | 2026-03-07 | Prior baseline with flywheel v2 framing, hybrid strategy architecture, and deployment context. |

---

## 1. What This Project Is

**Elastifund** is an agent-run trading company and an open-source research engine. John designs constraints, infrastructure, and research process; JJ executes trading and engineering decisions inside those boundaries. The system mandate is risk-adjusted returns plus rigorous public documentation.

### JJ Persona (3-Sentence Brief)
JJ is the principal execution layer of Elastifund: direct, evidence-driven, and intolerant of weak assumptions. JJ makes autonomous decisions on implementation and strategy iteration, then reports confidence, data, and next actions. John is the infrastructure engineer and constraint setter; JJ is the operator.

**Prime directive:** "John shares info, JJ decides."

**Dual mission:** (1) Generate trading returns from validated edges. (2) Build the world's best public resource on agentic trading at johnbradleytrading.com.

**Current status (machine truth reconciled on 2026-03-09):** Polymarket is funded ($247.51 USDC), Kalshi is connected ($100 USD), and the Dublin VPS remains the production host. `reports/public_runtime_snapshot.json` and `reports/runtime_truth_latest.json` are the stable runtime handoff artifacts. `reports/remote_service_status.json` checked at `2026-03-09T01:28:43Z` now shows `jj-live.service` `inactive`, and `jj_state.json` shows `0` live trades after `313` cycles. Launch remains blocked: wallet-flow is still `ready` with `80` scored wallets and `fast_flow_restart_ready=true`, the latest local `make test` run passed (`962 passed in 18.12s; 22 passed in 3.83s`), the latest checked-in fast-trade artifact at `2026-03-09T01:23:49+00:00` still says `REJECT ALL` across `75` observed markets with `3,047` trade records and `1,715` tracked wallets, the latest edge scan at `2026-03-09T01:26:04+00:00` still returned `stay_paused`, and the broader threshold-sensitivity refresh at `2026-03-09T01:32:09.884663+00:00` still found `0` tradeable markets at the current (YES `0.15`, NO `0.05`), aggressive (YES `0.08`, NO `0.03`), and wide-open (YES `0.05`, NO `0.02`) profiles. A-6/B-1 remain blocked with `0` executable A-6 opportunities below `0.95` and `0` deterministic B-1 template pairs in the first `1,000` allowed markets. On the non-trading side, JJ-N is now in a partial-completion state: the CRM schema, store-backed registry work, unified approval gate, Website Growth Audit offer, template selector, follow-up sequence, dashboard asset, telemetry bridge, Elastic index template, and `RevenuePipeline` exist. Verification is mixed: `make test-nontrading` passes with `53` tests, but the repo-root `tests/nontrading` surface currently fails one persisted-registry ranking test after reload, and `nontrading/main.py` still runs the legacy campaign harness instead of the pipeline. Governance scaffolding also landed: `13` numbered docs under `docs/numbered/` and a passing messaging lint. The deploy handoff pair in `reports/deploy_20260309T012910Z.json` and `reports/deploy_20260309T013155Z.json` validated the release manifest and dry-run path without restarting `jj-live.service`, but remote mode remains unknown because the VPS env only surfaced `PAPER_TRADING=false` with no explicit runtime profile or agent run mode.

| Strategy Status | Count | Source |
|-----------------|-------|--------|
| Deployed (live/ready) | 7 | `research/edge_backlog_ranked.md` |
| Building (code complete) | 6 | `research/edge_backlog_ranked.md` |
| Building — Structural Alpha | 2 | `research/edge_backlog_ranked.md` |
| Re-Evaluating | 1 | `research/edge_backlog_ranked.md` |
| Tested & Rejected | 10 | `research/edge_backlog_ranked.md` |
| Pre-Rejected | 8 | `research/edge_backlog_ranked.md` |
| Research Pipeline | 97 | `research/edge_backlog_ranked.md` |
| Total Tracked | 131 | `research/edge_backlog_ranked.md` |

**Cycle 2 verification status (2026-03-09 source set):**
- `make hygiene` passed.
- `make test` passed (`962 passed in 18.12s; 22 passed in 3.83s`).
- `make test-polymarket` passed (`374 passed in 2.97s`).
- `make test-nontrading` passed (`39 passed in 0.36s`).
- `python3 -m pytest tests/ -x -q --tb=short` passed during the final sync pass (`421 passed in 14.01s`).
- The current full multi-surface green baseline is `1,397` total tests (`962 + 22` root, `374` polymarket, `39` non-trading).

**Dispatch inventory:** `11` `DISPATCH_*` work-orders and `95` markdown files in `research/dispatches/`.

**Promotion status:** No promotion this cycle. Launch is blocked by the stopped remote service, no closed trades, no deployed capital, and the A-6/B-1 evidence gates.

**Last operator action:** `reports/deploy_20260309T013155Z.json` recorded the manifest fix and passing dry-run after the detailed validation pass in `reports/deploy_20260309T012910Z.json`; `jj-live.service` remained stopped throughout.

**Next operator action:** Confirm the remote mode as paper or shadow. Do not treat deploy readiness as a restart signal: the latest edge scan still says `stay_paused`, and the threshold-sensitivity refresh still found `0` tradeable markets even at YES `0.05`, NO `0.02`. If this merged repo state is the intended release, use the validated no-restart `--apply` path only for paper/shadow evidence collection.

**The Flywheel:** Research -> Implement -> Test -> Record -> Publish -> Repeat in 3-5 day cycles.

### Product Definition (Vision-Aligned, March 9 2026)

Elastifund is an open, self-improving platform for agentic capital allocation and agentic labor. It has two families of workers sharing a common substrate:

- **Trading workers:** agents that research, simulate, rank, and optionally execute market strategies under policy.
- **Non-trading workers (JJ-N):** agents that create economic value through business development, research, services, operations, and customer acquisition. The first wedge is a revenue-operations worker for a single high-ticket service business.

The unifying principle: the project does not just run agents — it improves agents. Improvement is the product.

### Master Architecture (Six-Layer)

| Layer | Purpose | What lives here |
|---|---|---|
| 1. Experience | Human-facing surfaces | Homepage, /elastic, /develop, README, dashboards, leaderboards, diary, roadmap |
| 2. Control | Policy and orchestration | Scheduling, approvals, budgets, task queues, retries, permissions, autonomy levels |
| 3. Worker | Specialized agents | Trading workers, revenue workers, research workers, proposal workers, coding workers |
| 4. Evaluation | Judgment and ranking | Experiment scoring, leaderboards, confidence estimates, forecasts, improvement velocity |
| 5. Memory | Shared context | Leads, messages, market data, prompts, outcomes, code diffs, notes, templates, forecasts |
| 6. Data / Telemetry | Ground truth | Events, logs, metrics, traces, costs, errors, artifacts, commits, model usage |

Design discipline: every important action creates an event, every event is queryable, every query supports a judgment, every judgment updates both a worker and a public surface.

### Non-Trading Architecture (Five-Engine Model)

| Engine | Purpose | Outputs |
|---|---|---|
| 1. Account Intelligence | Find, enrich, and score targets | Target lists, contact records, fit scores, opportunity notes |
| 2. Outreach | Draft, queue, and send compliant messages | Sequences, variants, send decisions, follow-up schedules |
| 3. Interaction | Handle replies, scheduling, and meeting prep | Reply classifications, calendar holds, briefs, next actions |
| 4. Proposal | Turn discovery into scoped offers | Proposal drafts, scope recommendations, pricing bands, follow-up assets |
| 5. Learning | Evaluate outcomes and revise playbooks | Template changes, score updates, prompt revisions, experiment decisions |

All five engines write into the same Elastic-backed memory. Observability tracks latency, errors, model costs, handoff frequency, reply classification accuracy, proposal turnaround, and policy events. Phase 0 repo truth now includes the CRM schema, an in-memory opportunity registry, two approval-gate paths, a telemetry event writer, an Elastic index template, and the five engine stubs under `nontrading/`.

### JJ-N Repo Status (March 9)

- Runnable today: the legacy campaign harness in `nontrading/main.py`, the digital-product discovery lane, and a built but not CLI-wired `RevenuePipeline`
- Verified today: `53` JJ-N tests pass in `nontrading/tests`
- Open regression: the repo-root `tests/nontrading` surface currently fails on persisted registry ranking after reload
- Still missing for launch: verified domain auth, curated leads, explicit approval for real sends, and CLI wiring into the pipeline

### First Wedge

The planned first production wedge remains the Website Growth Audit plus recurring monitor.
Target customer:
SMBs with public websites and visible growth or conversion issues.
Current status:
implemented in code with a `$500-$2,500` price band, `5` delivery days, and hybrid fulfillment, but not launched as a live product path.

### Planned RevenuePipeline

The intended JJ-N autonomy loop is:

```text
Account Intelligence -> Outreach -> Interaction -> Proposal -> Learning
```

Required gates:

- opportunity scoring before advancement
- compliance checks before queueing outreach
- approval routing before live sends
- telemetry at every stage

Current repo truth:
the pipeline is built in `nontrading/pipeline.py`, but `nontrading/main.py` still runs the legacy campaign harness instead.

### Non-Trading Opportunity Scoring Framework

| Criterion | Question | Weight |
|---|---|---|
| Time to first dollar | Can this opportunity generate cash quickly? | 25 |
| Gross margin | Is the profit pool attractive after delivery costs? | 20 |
| Automation fraction | How much of the workflow can the system own now? | 20 |
| Data exhaust | Will the workflow produce strong signals for learning? | 15 |
| Compliance simplicity | Can it be operated safely and legally? | 10 |
| Capital required | How much cash before evidence exists? | 5 |
| Sales-cycle length | Will feedback arrive fast enough to improve? | 5 |

Any opportunity scoring below threshold remains in research only.

### JJ-N Rollout Plan (0 to 90 Days)

| Phase | Days | Goal | Deliverables |
|---|---|---|---|
| 0 — Foundations | 1-14 | Create a safe, measurable system | Opportunity registry, CRM schema, telemetry, dashboards, domain/auth setup, templates, approval classes, paper mode |
| 1 — Assisted pilot | 15-30 | Run live outreach with human approvals | Curated lead list, message angles, follow-up engine, meeting booking flow, weekly review |
| 2 — Partial autonomy | 31-60 | Automate low-risk actions, strengthen learning | Auto-queue sequences, reply classifier, meeting briefs, proposal drafting, confidence-based approvals |
| 3 — Repeatability | 61-90 | Prove one repeatable lane | Documented win-loss patterns, stable funnel metrics, published worker leaderboard, go/no-go on expansion |

Success criterion: "prove one revenue loop that can be measured, improved, and explained."

### Numbered Documents (Governance Plan)

The canonical numbered operating-manual lane now lives under `docs/numbered/`. Update those files in place every time the system materially changes:

| File | Purpose |
|---|---|
| `docs/numbered/00_MISSION_AND_PRINCIPLES.md` | Why the project exists, what it optimizes, and what it will not do |
| `docs/numbered/01_EXECUTIVE_SUMMARY.md` | Plain-language explanation for non-technical readers and leadership |
| `docs/numbered/02_ARCHITECTURE.md` | System map, data flow, layers, and design constraints |
| `docs/numbered/03_METRICS_AND_LEADERBOARDS.md` | Definitions for all public graphs and scorecards |
| `docs/numbered/04_TRADING_WORKERS.md` | Trading system overview, policies, risk boundaries, paper vs live |
| `docs/numbered/05_NON_TRADING_WORKERS.md` | Revenue-worker strategy, workflows, evaluation, and rollout |
| `docs/numbered/06_EXPERIMENT_DIARY.md` | Chronological change log of experiments, outcomes, and lessons |
| `docs/numbered/07_FORECASTS_AND_CHECKPOINTS.md` | Current forecasts, expected milestones, and confidence changes |
| `docs/numbered/08_PROMPT_LIBRARY.md` | Canonical prompts, prompt variants, and prompt-review process |
| `docs/numbered/09_GOVERNANCE_AND_SAFETY.md` | Autonomy levels, approvals, security, compliance, and incident policy |
| `docs/numbered/10_OPERATIONS_RUNBOOK.md` | How to run the system, recover failures, and update components |
| `docs/numbered/11_PUBLIC_MESSAGING.md` | Approved copy blocks for the site, GitHub, and outreach |
| `docs/numbered/12_MANAGED_SERVICE_BOUNDARY.md` | What stays open source and what is offered as hosted infrastructure |

These documents create narrative stability and make it possible for any agent or contributor to know where truth lives.

### Messaging System (Approved Language)

**Use:** "self-improving," "policy-governed autonomy," "agentic work," "economic work," "evidence," "benchmarks," "run in paper mode by default."

**Never use:** "self-modifying binary," "remove the human from the loop," "agent swarm that makes money."

**Homepage hero:** "A self-improving agentic operating system for real economic work."

**/elastic hero:** "Open-source agents need a system memory. Elastic is the Search AI platform that makes them reliable."

---

## 2. How the Bot Works (Technical)

### Architecture

```
VPS: 52.208.155.0 (AWS Lightsail Dublin, eu-west-1)
systemd: jj-live.service (remote artifact: `inactive` at `2026-03-09T01:28:43Z`; launch posture still blocked)
Bot file: bot/jj_live.py (local) → /home/ubuntu/polymarket-trading-bot/jj_live.py (VPS)

SIGNAL SOURCE 1: Ensemble Estimator + Agentic RAG (bot/ensemble_estimator.py, every 5 min)
├── SCAN:      Gamma API → 100+ active markets
├── FILTER:    Category (skip sports/crypto/financial_speculation)
│              Velocity (skip markets > MAX_RESOLUTION_HOURS)
├── RAG:       DuckDuckGo web search → recent context injected into prompt
├── ENSEMBLE:  Claude Haiku + GPT-4.1-mini + Groq Llama 3.3 (parallel)
│              Trimmed mean aggregation, consensus gating (75%+ agree)
├── CALIBRATE: Platt scaling (A=0.5914, B=-0.3977) on ensemble mean
├── BRIER:     Live accuracy tracking in SQLite (per-model + category)
├── SIGNAL:    Asymmetric thresholds (YES 15%, NO 5%) + velocity scoring
├── SIZE:      Quarter-Kelly (boosted if models_agree=True)
├── EXECUTE:   Maker orders on fee-bearing, taker on fee-free
├── NOTIFY:    Telegram alerts
└── TESTS:     34 unit tests passing

SIGNAL SOURCE 2: Smart Wallet Flow Detector (bot/wallet_flow_detector.py, COMPLETE)
├── MONITOR:   Poll data-api.polymarket.com/trades for top wallet activity
├── SCORE:     Rank wallets by 5-factor activity score (data/wallet_scores.db)
├── DETECT:    Flag when N of top-K wallets converge on same side
├── SIGNAL:    Consensus > 76% confidence → trade
├── SIZE:      1/16 Kelly (tiny, high-frequency)
└── EXECUTE:   Maker orders (zero fees on crypto markets)

SIGNAL SOURCE 3: LMSR Bayesian Engine (bot/lmsr_engine.py, COMPLETE)
├── POLL:      data-api.polymarket.com/trades (same endpoint as wallet flow)
├── POSTERIOR:  Sequential Bayesian update in log-space per market
├── LMSR:      Softmax pricing from trade flow quantities
├── BLEND:     60% Bayesian posterior + 40% LMSR flow price
├── SIGNAL:    |blended_price - clob_price| > threshold → trade
├── SIZE:      1/16 Kelly (always treated as fast market)
├── CYCLE:     Target 828ms avg, 1776ms p99
└── TESTS:     45 unit tests passing

SIGNAL SOURCE 4: Cross-Platform Arb Scanner (bot/cross_platform_arb.py, COMPLETE)
├── FETCH:     Polymarket Gamma API (300 markets) + Kalshi SDK (3000+ markets)
├── FILTER:    Skip sports/esports via KALSHI_SKIP_PREFIXES, zero-liquidity markets
├── MATCH:     SequenceMatcher + Jaccard keyword similarity (threshold 70%)
├── DETECT:    YES_ask + NO_ask < $1.00 after fees → risk-free arb
├── FEES:      Kalshi taker = 0.07·p·(1-p), Polymarket maker = 0%
├── SIGNAL:    Net profit > MIN_PROFIT_PCT → trade on Polymarket side
├── SIZE:      Quarter-Kelly (arb = high confidence)
└── TESTS:     29 unit tests passing

SIGNAL SOURCE 5: Multi-Outcome Sum Violation Scanner (A-6, SHADOW MODE)
├── DISCOVER:  Gamma `/events` active universe → grouped multi-outcome events
├── STREAM:    Market WebSocket `book` + `price_change` → shared LOB state
├── DETECT:    `sum(YES asks) < 0.97` or `sum(YES bids) > 1.03`
├── EXECUTE:   Batch post-only GTC orders + 3000ms partial-fill rollback timer
├── MERGE:     Complete baskets only, `$20+` threshold before on-chain merge
└── STATUS:    REST shadow scanner exists; WebSocket book + batch execution pending

SIGNAL SOURCE 6: LLM Dependency Graph Arb (B-1, BUILDING)
├── PREFILTER: Resolution window ±72h, shared tags/slug overlap, embedding cosine > 0.60
├── CLASSIFY:  Claude Haiku deterministic relation labels cached in `graph_edges`
├── MONITOR:   Implication / exclusion / complement violations with `tau = 0.03`
├── VALIDATE:  50-pair gold set + weekly resolved-market false-positive audit
├── SIZE:      Execution-risk-adjusted, hard-capped at `$5` per leg
└── STATUS:    Heuristic engine exists; LLM edge cache and live monitor pending

OBSERVABILITY LAYER: Elastic Stack (target paths under `infra/`)
├── INGEST:    `infra/filebeat.yml` ships structured logs from `/var/log/elastifund/`
├── TRACE:     `bot/apm_setup.py` sends critical-path transactions and spans to APM
├── INDEX:     `bot/elastic_client.py` writes trades, signals, kills, orderbook, and latency docs
├── VIEW:      Kibana dashboards cover trading overview, signal quality, kill rules, and orderbook health
└── DETECT:    Elastic ML jobs score VPIN, OFI, spread, confidence drift, and kill-rule frequency

SIGNAL SOURCE 7: Elastic ML Anomaly Consumer (bot/anomaly_consumer.py, FEEDBACK LANE)
├── POLL:      `.ml-anomalies-*` every 60s
├── REACT:     VPIN / OFI anomalies reduce position size by anomaly_score / 100
├── PAUSE:     Spread anomalies can pause new order placement on one market
├── FLAG:      Confidence drift is surfaced for human review and backlog triage
└── RULE:      Failures in this lane log warnings and continue; Elastic must never be a hard dependency

CONFIRMATION LAYER (jj_live.py, WIRED):
├── Sources 1-6 produce the primary trade thesis when their data planes are active
├── Source 7 applies caution modifiers and temporary pauses when anomaly jobs are live
├── Signals grouped by (market_id, direction)
├── 2+ sources agree → boosted size (quarter-Kelly)
├── LLM alone + res > 12h → standard quarter-Kelly
├── Wallet flow alone + res < 1h → 1/16 Kelly
├── LMSR alone → 1/16 Kelly
├── Signals 5/6 bypass predictive confirmation and route straight to arb execution
├── Structural checks still apply: resolution normalization, VPIN veto, linked-leg integrity, bankroll cap
├── Arb alone → execution-risk sizing, hard-capped at `$5` per leg
└── Telegram: source tag + [CONFIRMED] on multi-source signals

Data stores:
├── paper_trades.json     (position log)
├── metrics_history.json  (cycle metrics)
├── strategy_state.json   (tuning state)
├── bot.db                (SQLite — orders, fills, positions, risk events, execution_stats)
├── data/constraint_arb.db (graph_edges, constraint_violations, capture stats)
├── logs/sum_violation_events.jsonl
└── jj_state.json         (live state; extend with linked_legs for multi-leg arb)
```

Repo-specific build spec: `docs/strategy/combinatorial_arb_implementation_deep_dive.md`

### Elastic Integration Modules

| File | Purpose |
|------|---------|
| `bot/elastic_client.py` | Singleton Elasticsearch client, async bulk writer, and graceful no-op surface when `ES_ENABLED=false` |
| `bot/elastic_dashboards.py` | Kibana Saved Objects importer for dashboard packs under `infra/kibana_dashboards/` |
| `bot/apm_setup.py` | Elastic APM bootstrap for critical-path transactions, external API spans, and custom latency metrics |
| `bot/log_config.py` | ECS-style structured JSON logging with file output for Filebeat pickup |
| `bot/latency_tracker.py` | Shared decorator for timing, structured logging, APM spans, and latency event indexing |
| `bot/elastic_ml_setup.py` | Elasticsearch ML job and datafeed bootstrap for order-flow and signal-drift anomaly detection |
| `bot/anomaly_consumer.py` | Signal source `#7`, which consumes high-score anomalies and feeds caution back into trading decisions |
| `infra/docker-compose.elastic.yml` | Single-node Elasticsearch, Kibana, Filebeat, and APM Server for local or VPS deployment |
| `infra/index_templates/` | Index templates for trades, signals, kills, and orderbook documents |
| `infra/kibana_dashboards/` | Versioned NDJSON dashboard exports for trading, signals, kill rules, orderbook health, APM, and ML views |

### Bot Source Files (polymarket-bot/src/)

| File | Purpose |
|------|---------|
| `claude_analyzer.py` | Claude probability estimation — anti-anchoring prompt, calibration layer, category routing, taker fee awareness |
| `scanner.py` | Gamma API market scanner — fetches active markets, filters actionable candidates, adds resolution estimates |
| `resolution_estimator.py` | Resolution time estimator + capital velocity scoring (velocity = edge/days; top-5 per cycle) |
| `paper_trader.py` | Paper trading execution engine (legacy standalone loop) |
| `safety.py` | **Safety rails: daily loss limit, per-trade cap, exposure cap, cooldown, rollout tiers** |
| `sizing.py` | Quarter-Kelly position sizing (kelly_fraction, position_size) |
| `src/pricing/binary_options.py` | Binary option pricing: BS, Greeks, jump-diffusion, mean-reversion, composite signals |
| `src/calibration/category_calibration.py` | Per-category Platt scaling, asymmetric edge thresholds, market ranking |
| `noaa_client.py` | NOAA weather data client for weather arbitrage |
| `telegram.py` | Telegram notifications |
| `main.py` | Entry point |
| `core/config.py` | Pydantic settings from .env |
| `core/logging.py` | Structlog JSON logging |
| `store/models.py` | SQLAlchemy ORM (Order, Fill, Position, BotState, RiskEvent) |
| `store/repository.py` | Repository pattern for all DB ops |
| `engine/loop.py` | Main trading loop |
| `app/dashboard.py` | FastAPI REST API (9 endpoints: /health, /status, /metrics, /risk, /kill, /unkill, /orders, /execution, /logs/tail) |

### Backtest Engine (backtest/)

| File | Purpose |
|------|---------|
| `collector.py` | Fetches resolved markets from Gamma API |
| `engine.py` | Runs Claude backtest + computes ARR |
| `strategy_variants.py` | Tests 10+ strategy variants |
| `monte_carlo.py` | Monte Carlo portfolio simulation (10,000 paths) |
| `monte_carlo_advanced.py` | Advanced MC: regime-switching, fat tails, correlation, dynamic Kelly, market impact, edge decay |
| `calibration.py` | Temperature scaling calibration from backtest data |
| `charts/` | Generated backtest visualizations |

### Key Environment Variables

```
POLYMARKET_PRIVATE_KEY=...
POLYMARKET_FUNDER_ADDRESS=...
ANTHROPIC_API_KEY=sk-...
DATABASE_URL=sqlite+aiosqlite:///bot.db
LIVE_TRADING=false
ENGINE_LOOP_SECONDS=300
MAX_POSITION_USD=100.0
MAX_DAILY_DRAWDOWN_USD=50.0
MAKER_MODE=false
MAKER_SANDBOX_SIZE_PCT=0.15
MAKER_SANDBOX_TIMEOUT_SECONDS=120
```

---

## 3. New Modules (v1.5.0)

### Advanced Monte Carlo (`backtest/monte_carlo_advanced.py`)
- 10 sophisticated features: regime-switching, fat tails, correlated movements, dynamic Kelly, drawdown-conditional scaling, market impact, edge decay, liquidity constraints, capital injections, confidence bands
- 4 scenario analysis: Conservative (+124% ARR), Moderate (+403%), Aggressive (+872%), Crisis stress test
- 10,000 paths with numpy vectorization
- Replaces basic `monte_carlo.py` for investor-grade simulation

### Binary Option Pricing Engine (`src/pricing/binary_options.py`)
- 9 pricing models: Black-Scholes binary, implied vol extraction, Greeks (Δ/Γ/Θ/ν), Merton jump-diffusion, OU mean-reversion, KL divergence edge scoring, volatility surface, risk-neutral pricing, composite signal generator
- CompositeSignal class blends all models → fair_value + signal_strength (0-10) + recommended_action
- Integrates with trading engine as supplementary signal to Claude AI estimates

### Category-Specific Calibration (`src/calibration/category_calibration.py`)
- Per-category Platt scaling (replaces single global calibration)
- Trained on 2,526 resolved markets with 70/30 split
- Brier improvement: 0.1561 → 0.1329 (+2.3% overall, +4.6% on geopolitical)
- Asymmetric edge thresholds: Politics YES=12%/NO=4%, Geopolitical YES=20%/NO=8%
- k-fold cross-validation framework
- Falls back to global calibration for categories with <30 samples

### Launch Readiness Checklist (`Checklist.md`)
- 200+ verification items across 15 sections
- Polymarket funding guide (4 methods: crypto exchange, MoonPay, MetaMask, Coinbase Pay)
- 10-gate launch decision matrix — ALL must pass before live trading
- Gradual rollout schedule (Week 1-3 escalation)

---

## 4. Strategy Details

### Strategy A: Claude AI Probability Analysis (Primary)

1. Scan 100 active markets from Gamma API (min $100 liquidity)
2. Filter to "actionable" candidates: YES price 10–90%, scored by proximity to 50/50, liquidity, volume
3. Claude Haiku estimates true probability from first principles — **market price NOT shown** (prevents anchoring)
4. Signal generated if |estimated - market| > edge threshold
5. Paper trade: $2 per position, skip low-confidence signals

**Current parameters:** Edge threshold 5% (lowered from 10% after 0-signal diagnosis), position size quarter-Kelly (avg ~$10 at $75 bankroll), max markets per scan 20, min confidence medium, scan interval 300s.

**Asymmetric thresholds (research-backed):** YES threshold 15%, NO threshold 5%. This exploits the 76% NO win rate vs 56% YES win rate — prediction markets structurally overprice YES outcomes (favorite-longshot bias).

**Category routing (priority 0–3):**
- Priority 3 (trade): Politics, Weather
- Priority 2 (trade): Economic, Unknown
- Priority 1 (reduced size): Geopolitical
- Priority 0 (skip): Crypto, Sports, Fed Rates

**Calibration layer:** Temperature scaling from 532-market backtest. Claude is systematically overconfident on YES side (says 90% → actual 63%). Calibration map applied post-estimation.

**Taker fee awareness:** Polymarket taker fees = p*(1-p)*r. Edge must exceed fee to be profitable. Fees worst at p=0.50.

### Strategy B: NOAA Weather Arbitrage (Supplemental)

Scans markets for weather keywords → fetches 48-hour NOAA forecasts for 6 cities → trades when NOAA diverges >15% from market. Currently no active weather markets detected.

### Strategy C: Resolution Rule Edge (Manual Overlay)

A systematic playbook for identifying markets where traders misread resolution criteria. Scoring system: Edge × Dispute Probability × Time-to-Resolution. See `resolution-rule-edge-playbook.md`.

### Position Sizing: Kelly Criterion (INTEGRATED)

**Status: LIVE** — Quarter-Kelly sizing implemented in `src/sizing.py`, wired into both `paper_trader.py` and `engine/loop.py`. Replaces flat $2.00 sizing.

| Kelly Fraction | Median Growth | P(50% Drawdown) | Ruin Risk | Sharpe |
|----------------|--------------|-----------------|-----------|--------|
| Full (1×) | ~10¹⁶× | 100% | 36.9% | 0.37 |
| Half (0.5×) | ~10¹¹× | 94.7% | ~0% | 0.57 |
| **Quarter (0.25×)** | **~10⁶×** | **8.0%** | **0%** | **0.64** |
| Tenth (0.1×) | ~10²× | 0% | 0% | 0.68 |

**Implementation details (`src/sizing.py`):**
- `kelly_fraction(p_estimated, p_market, side)` → raw Kelly f* with 2% winner fee
- `position_size(bankroll, kelly_f, side, category, category_counts)` → USD size
- Asymmetric: buy_yes 0.25× Kelly, buy_no 0.35× Kelly (NO-bias structural edge)
- Bankroll scaling: <$150 → 0.25×, ≥$300 → 0.50×, ≥$500 → 0.75×
- Category haircut: >3 positions in same category → 50% size reduction
- Floor: $0.50 minimum, Cap: $10 default (MAX_POSITION_USD from .env overrides)
- kelly_f ≤ 0 → trade skipped entirely
- WARNING logged if Kelly suggests >$5 on any single trade

**Backtest validation (532 markets, compounding):**
- Flat $2: $75 → $330.60 (341% return, 9.8% max DD)
- Quarter-Kelly: $75 → $1,353.18 (1,704% return, 18.4% max DD)
- **Kelly outperformance: +309% over flat sizing**
- Monte Carlo (100-path quick): Kelly median $4,694 vs flat $831 (+465%)

---

## 5. Performance Data (Backtest — NOT Live)

### 532-Market Backtest (2026-03-05, updated with CalibrationV2)

| Metric | Uncalibrated | Calibrated v2 (Platt) |
|--------|-------------|----------------------|
| Resolved markets tested | 532 | 532 |
| Markets with signal (>5% edge) | 470 (88%) | 372 (70%) |
| Win rate | 64.9% | **68.5%** |
| Brier score | 0.2391 | **0.2171** |
| Total simulated P&L | +$280.00 | +$276.00 |
| Avg P&L per trade | +$0.60 | +$0.74 |
| Buy YES win rate | 55.8% | 63.3% |
| Buy NO win rate | 76.2% | 70.2% |

### CalibrationV2 — Out-of-Sample Validation

**Method:** Platt scaling (logistic regression in logit space), 70/30 train/test split, stratified by outcome.

| Metric | Train (372) | Test (160) |
|--------|------------|-----------|
| Brier (raw) | 0.2188 | 0.2862 |
| Brier (Platt) | 0.2050 | **0.2451** |
| Brier (isotonic) | 0.2053 | 0.2482 |
| Improvement | +0.0138 | **+0.0411** |

**Platt params:** A=0.5914, B=-0.3977. Maps: 90%→71%, 80%→60%, 70%→53%, 50%→40%.

**Confidence-weighted sizing:** Buckets with <10 training samples → 0.5x position size (30-40%, 60-70%, 80-90% ranges).

### Strategy Variant Performance (CalibrationV2)

| Strategy | Win Rate | Trades | Brier | ARR @5/day |
|----------|----------|--------|-------|-----------|
| Baseline (5% threshold) | 64.9% | 470 | 0.2391 | +1,110% |
| NO-only | 76.2% | 210 | 0.2391 | +2,194% |
| **Calibrated v2 (5% sym)** | **68.5%** | **372** | **0.2171** | **+1,461%** |
| Calibrated v2 + NO-only | 70.2% | 282 | 0.2171 | +1,620% |
| Cal v2 + Asym + Confidence | 68.6% | 354 | 0.2171 | +1,476% |

**Current benchmark framing:** `71.2%` is the strongest calibrated selective variant used for public scorecards, `68.5%` is the older broad calibrated reference, and `64.9%` is the raw uncalibrated baseline.

### Ensemble Skeleton (Added 2026-03-05)

`polymarket-bot/src/ensemble.py` — multi-model probability estimation framework:
- `ClaudeEstimator` — fully implemented, uses existing prompt
- `GPTEstimator` — placeholder (needs OpenAI API key)
- `GrokEstimator` — placeholder (needs xAI API key)
- `EnsembleAggregator` — averages N estimators, signals only when stdev < 0.15

### Monte Carlo (10,000 Paths, 12 Months)

**At $75 starting capital:**
| Scenario | Value | Return |
|----------|-------|--------|
| 5th percentile | $782 | +942% |
| Median | $918 | +1,124% |
| 95th percentile | $1,054 | +1,305% |
| P(total loss) | **0.0%** | |

**At $10,000 starting capital:**
| Scenario | Value | Return |
|----------|-------|--------|
| 5th percentile | $33,507 | +235% |
| Median | $36,907 | +269% |
| 95th percentile | $40,207 | +302% |
| P(total loss) | **0.0%** | |

### Current Runtime Snapshot (2026-03-09 machine truth)

| Metric | Value |
|--------|-------|
| Runtime cycles completed | 313 |
| Live trades executed | 0 |
| Open positions | 0 |
| Deployed capital | $0.00 |
| Service state | `reports/remote_service_status.json` shows `jj-live.service` `stopped` at `2026-03-09T01:28:43Z` |
| Launch posture | `reports/public_runtime_snapshot.json` still marks launch `blocked`; blocked checks now include `service_not_running`, no closed trades, no deployed capital, A-6, B-1, and flywheel hold |
| Wallet-flow readiness | `ready` with `80` scored wallets and `fast_flow_restart_ready=true`, but the latest edge scan still returned `stay_paused` and the service remains stopped |
| Fast-market pipeline | Latest checked-in artifact is `FAST_TRADE_EDGE_ANALYSIS.md` at `2026-03-09T01:23:49+00:00`, still `REJECT ALL` across `75` observed markets with `3,047` trade records and `1,715` tracked wallets; the broader threshold refresh also found `0` tradeable markets at YES `0.15`, NO `0.05`; YES `0.08`, NO `0.03`; and YES `0.05`, NO `0.02` |
| A-6 gate | March 9 edge scan found `0` executable opportunities below the `0.95` threshold |
| B-1 gate | March 9 template audit found `0` deterministic template pairs in the first `1,000` allowed markets |
| Verification status | Latest local verification shows root passing (`962 passed in 18.12s; 22 passed in 3.83s`); current full multi-surface green baseline is `1,397` total verified |
| Promotion status | No promotion; structural gates remain blocked and launch is still hold-state |
| Last operator action | `reports/deploy_20260309T013155Z.json` recorded the manifest fix and passing dry-run after the detailed validation pass in `reports/deploy_20260309T012910Z.json` |
| Next operator action | Confirm remote mode; if `--apply` is approved, keep it paper/shadow only because the latest edge scan still says `stay_paused` and the threshold refresh still found `0` tradeable markets even at YES `0.05`, NO `0.02` |

---

## 6. Research Findings That Shape Strategy

### Academic Research (12+ papers, 2024–2026)

1. **Prompt engineering mostly doesn't help** (Schoenegger 2025): Only base-rate-first prompting works (−0.014 Brier). Chain-of-thought, Bayesian reasoning, elaborate prompts HURT calibration. Our prompt uses base-rate-first + explicit debiasing only.

2. **Calibration is #1 priority:** Bridgewater's AIA Forecaster used Platt-scaling to match superforecasters. Lightning Rod Labs' Foresight-32B achieved ECE 0.062 via RL fine-tuning.

3. **Ensemble + market consensus beats both alone** (Bridgewater 2025): LLM estimate combined with market price outperforms either. Two-stage pipeline planned: Claude estimates blind → combine calibrated estimate with market price.

4. **Category routing matters** (Lu 2025, RAND): Politics = best LLM category. Weather = structural arbitrage. Crypto/sports = zero LLM edge. Fed rates = worst.

5. **Taker fees kill taker strategies** (Feb 18, 2026): fee(p) = p*(1-p)*r. At p=0.50, need 3.13% edge to break even. Market making (limit orders) is emerging dominant strategy.

6. **Asymmetric thresholds validated:** 76% NO win rate consistent with documented favorite-longshot bias (Whelan 2025, Becker 2025).

7. **Multi-model ensembles work:** Halawi et al. (2024, NeurIPS) showed "LLM crowd" statistically equivalent to human crowd. Validates planned Claude + GPT + Grok ensemble.

8. **Superforecaster methods playbook** (Schoenegger 2025, Alur/Bridgewater 2025, Halawi 2024, Lu 2025, Karger/ForecastBench 2025, Lightning Rod Labs 2025): Comprehensive evidence hierarchy ranked by Brier Δ: (1) Agentic RAG −0.06 to −0.15, (2) Platt scaling −0.02 to −0.05, (3) Multi-run ensemble 3–7 runs −0.01 to −0.03, (4) Base-rate-first −0.011 to −0.014, (5) Structured scratchpad −0.005 to −0.010, (6) Two-step confidence elicitation −0.005 to −0.010. **HARMFUL techniques to avoid:** Bayesian reasoning prompts (+0.005 to +0.015 worse), narrative/fiction framing, propose-evaluate-select. Frontier Brier = 0.075–0.10 (system + market price). LLM-superforecaster parity projected ~Nov 2026. Master prompt template provided with 6-step reasoning (outside view → for/against → calibration check → final). Key insight: acquiescence bias (Claude skews YES) + SACD drift (never show Claude its own priors when re-estimating).

9. **Market making mechanics confirmed (Deep Research 2026-03-05):** CLOB two-sided quoting via split/merge of USDC.e into YES/NO tokens. Maker orders pay 0% fee (+ 20-25% rebate from taker fees). Inventory skewing essential: lean quotes against imbalance, merge excess pairs back to USDC.e. Realistic MM returns: $50-200/mo at $1-5K, scaling to $1-5K/mo at $25-100K. Fee-bearing markets limited to new crypto (Mar 6, 2026) and select sports (Feb 18, 2026) — all other markets remain fee-free. Breakeven edge vs taker fees: ~0.78% at p=0.50 (crypto), ~0.35% (sports). No further fee changes announced for Q2 2026.

10. **Update discipline matters:** Superforecasters made 7.8 predictions/question (vs 1.4 average), avg update magnitude 3.5% (vs 5.9%). "Perpetual beta" 3× more predictive than raw intelligence. LLMs fail at Bayesian updating — must generate fresh estimates each time, never iterative. Cap position changes at 5–10% per cycle. Regenerate from scratch every 3–5 cycles.

11. **Sentiment/Contrarian "Dumb Money Fade" (2026-03-06):** Retail-emotional trades inversely predict returns — SentimenTrader's "Dumb Money" index is bullish at peaks, bearish at troughs. Reddit/WSB sentiment is a contrarian predictor (high bullish chatter → lower future returns). Signal sources: social media (Reddit, Twitter, StockTwits), retail flow (FXCM/IB positioning, unusual options volume), surveys (AAII, Investors Intelligence), indexes (CNN Fear & Greed, put/call ratios). Execution: fade extreme retail sentiment, boost confidence when Claude estimate is contrarian to herd, reduce confidence when Claude agrees with herd. Composite edge score 3.5 — ranks ~#11-15 in edge backlog. Best in crypto/meme markets, moderate in politics. Risk: sentiment can stay irrational longer than expected, use tight stops.

12. **RTDS maker edge implementation path (2026-03-07):** New spec in `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md` defines a fast-market engine that replaces 5-minute REST polling with three live WebSocket feeds (Polymarket RTDS, Polymarket CLOB, Binance), computes signal confidence in the final 60 seconds of each candle using Binance-vs-open direction plus RTDS oracle divergence, and submits maker-only post-only orders to avoid taker fees. It is a concrete implementation of the previously known oracle-lag idea with explicit risk caps (micro sizing, daily loss limits, kill criteria) and a paper-first validation path.

13. **Latency geography corrected (2026-03-07):** `research/LatencyEdgeResearch.md` confirms Polymarket CLOB is in AWS London (eu-west-2), not US infrastructure; Dublin is already in the competitive band at roughly 5-10ms to CLOB. The bottleneck is stale data ingestion (REST polling) rather than server location, so upgrading to WebSockets and RTDS matters more than moving to US hosts (which would usually worsen CLOB latency).

### Competitive Landscape (Updated 2026-03-05, Deep Research)

- **OpenClaw** agent framework reportedly earned $115K in one week; account 0x8dxd executed ~20,000 trades earning ~$1.7M profit
- **Fredi9999** all-time P&L: $16.62M, ~$9.7M in active positions — multi-million-dollar scale
- Open-source bots proliferating: Poly-Maker (warproxxx, comprehensive Python MM), Discountry (flash-crash arb), lorine93s MM bot, gigi0500 (0.50% spread default), Polymarket Agents (official SDK)
- Susquehanna actively recruiting prediction-market traders to "build real-time models"
- Only ~0.5% of Polymarket users earn >$1K; $40M went to arbitrageurs in one year
- Successful bots primarily use **arbitrage and speed**, not narrative analysis — "biggest edge is knowing news before others and acting in milliseconds"
- **Alpha decay accelerating:** Polymarket added fees + random latency delays to curb arb bots; simple strategies yield diminishing returns
- Estimated **tens of millions USD** under automated trading on Polymarket
- Clinton & Huang (2025): Polymarket political markets only ~67% correct — room for our system
- **Market making P&L estimates:** $50–200/mo on $1–5K capital; $200–$1K/mo on $5–25K; $1–5K/mo on $25–100K (assumes active volume + liquidity incentives)

### Data Feeds for Edge (Priority Integration List)

- News APIs (Reuters, Bloomberg, NewsData.io sentiment) — fastest movers
- Polling data (FiveThirtyEight, RCP) — strong baseline for political markets
- Social media (Twitter/X, Reddit) — precedes PM moves
- Google Trends / Wikipedia pageviews — search spikes predate market moves
- Government data (FRED, BLS, NOAA) — partially implemented
- Odds aggregators (TheOddsAPI, Oddpool) — benchmark for sports
- PM aggregators (Verso, PolyRouter) — cross-platform arbitrage signals

---

## 7. Fund Structure & Legal

**Entity:** LLC taxed as partnership (simplest for small fund). File IRS Form 1065, issue K-1s.

**Offering:** Reg D 506(b) — unlimited accredited investors, up to 35 non-accredited, no general solicitation. File SEC Form D within 15 days of first sale. Section 3(c)(1) exemption for <100 investors.

**CFTC:** Event contracts = swaps under CEA. CFTC Rule 4.13 exempts "family, friends, small" pools (<$500K, ≤10 friends/colleagues). File notice with NFA.

**Tax:** Unsettled — could be gambling income (worst), capital gains (better), or Section 1256 60/40 treatment (best). Track all trades, consult tax advisor.

**Proposed terms:** 0% management fee, 30% carry above high-water mark, $1,000 minimum, 90-day lock-up, 30-day withdrawal notice, quarterly withdrawals.

---

## 8. Risk Factors (Be Honest With These)

1. **Backtest ≠ live.** Simulated entry prices don't capture slippage, fill rates, timing.
2. **Claude overconfidence.** Brier 0.239 barely beats random. Calibration helps but is backtest-fit.
3. **NO-bias dependency.** 76% edge from buy_no could erode as AI traders enter.
4. **Capital concentration.** 34 positions × $2 = $68 deployed from $75.
5. **Resolution timing.** Far-future events lock capital for months.
6. **API costs.** ~$20–30/mo for 20 Claude calls per 5-min cycle.
7. **Taker fees.** Eat 1–3% of edge on crypto/sports. Now instrumented — `/execution` endpoint tracks per-trade fee drag, slippage, fill rate, cancel rate.
8. **Competitive pressure intensifying.** OpenClaw bots, open-source proliferation.
9. **Arbitrage dominates bot profits, not forecasting.** Our approach is unproven at scale.
10. **Category routing reduces opportunity set.**
11. **Platform risk.** Polymarket CFTC history, crypto-based, regulatory exposure.
12. **Execution quality now measured.** `execution_stats` table in bot.db tracks: quoted mid, expected fee, expected edge after fee, slippage vs mid at fill, fill time, cancel rate per order. Dashboard `/execution` endpoint exposes aggregates + per-trade detail.
13. **Maker sandbox (phase-1).** `MAKER_MODE=true` places small limit orders (10–20% of normal size) at conservative prices. Auto-cancel on timeout, at most 1 reprice, respects all safety rails + kill switch. Shadow-only by default — no "smart market making" yet.

---

## 9. Research Dispatch System

### How It Works

Each prompt file in `research_dispatch/` is tagged with the tool to dispatch it to:
- **CLAUDE_CODE** → Paste into Claude Code for implementation
- **CLAUDE_DEEP_RESEARCH** → Paste into Claude.ai with Deep Research enabled
- **CHATGPT_DEEP_RESEARCH** → Paste into ChatGPT with Deep Research/browsing (or GPT-5.4)
- **COWORK** → Paste into Claude Cowork for collaborative analysis
- **GROK** → Paste into Grok for real-time data analysis

### Priority Levels

- **P0** — Do immediately, highest ARR impact
- **P1** — Do this week, significant ARR impact
- **P2** — Do when P0/P1 are running, moderate impact
- **P3** — Background research, long-term improvement

### Status Tracking

READY → DISPATCHED → COMPLETED → INTEGRATED

### SOP

1. **ALWAYS update COMMAND_NODE and increment the version number** when storing any new report, research output, or significant finding. No exceptions. The Command Node is the single source of truth — if new information exists and the Command Node doesn't reflect it, the Command Node is stale.
2. All new research must trigger a full review of every project document to check for stale information or missing insights. Do not stop work until every document has been reviewed and all improvements have been made.
3. When dispatching tasks to any AI, include the SOP reminder: "After completing this task, update COMMAND_NODE.md (increment version) and review all project documents for staleness."

### Current Task Counts by Tool

| Tool | Ready Tasks | Highest Priority |
|------|-------------|-----------------|
| CLAUDE_CODE | 28 | P0-32 (combined backtest), P0-34 (Kelly), P0-36 (live switch) |
| CLAUDE_DEEP_RESEARCH | 6 | P0-49 (edge discovery), P0-50 (superforecaster) |
| CHATGPT_DEEP_RESEARCH | 4 | P1-43 (cross-platform arb) — P1-30 (market making) COMPLETED, P0-32 competitive COMPLETED, P1-42 social sentiment COMPLETED |
| COWORK | 9 | P0-33 (live scorecard), P0-35 (Monte Carlo stress) |
| GROK | 2 | P2-47 (competitive benchmarking) |

### Top P0 Tasks (Do NOW)

| # | Task | Tool | ARR Impact |
|---|------|------|------------|
| 32 | Combined backtest re-run (ALL improvements) | CLAUDE_CODE | Determines real performance |
| 34 | Kelly criterion integration into bot | CLAUDE_CODE | +40–80% |
| 36 | Switch paper → live trading | CLAUDE_CODE | Infinite (only live P&L matters) |
| 37 | News sentiment data pipeline | CLAUDE_CODE | +15–30% |
| 49 | Systematic edge discovery | CLAUDE_DEEP_RESEARCH | Potentially massive |
| 50 | ~~Superforecaster techniques pipeline~~ **COMPLETED** — playbook stored in `research/superforecaster_methods_llm_playbook.md` | CLAUDE_DEEP_RESEARCH | +15–30% |
| 51 | Automated self-improving architecture | CLAUDE_CODE | Compounding |
| 53 | Position deduplication / correlation | CLAUDE_CODE | Risk reduction |
| 55 | Resolution time optimizer (capital velocity) | CLAUDE_CODE | **DONE: +432% ARR** |
| 60 | Pre-resolution exit strategy | CLAUDE_CODE | +20–40% |
| 77 | HFT Shadow Validator — 72h empirical data capture for Chainlink barrier mispricing (maker-only). Validates R4 re-evaluation. See dispatch #77. | CLAUDE_CODE | Revives crypto candle edge (potentially +$50-150/day) |
| 78 | Integrate polynomial fee model into execution engine — exact formula: `C × p × 0.25 × (p(1-p))^2`. All crypto durations now fee-bearing (March 6 expansion). | CLAUDE_CODE | Required for any crypto market trading |

---

## 10. Document Hierarchy

| Document | Role | Update Cadence |
|----------|------|----------------|
| `COMMAND_NODE.md` | Full context handoff for new AI sessions (single source of truth) | Every flywheel cycle |
| `PROJECT_INSTRUCTIONS.md` | Quick-start operating context + active priority queue | When priorities change |
| `CLAUDE.md` | JJ persona + prime directive + execution rules | Rarely (process changes only) |
| `REPLIT_NEXT_BUILD.md` | Canonical build instructions for the next website iteration | Every flywheel cycle |
| `docs/strategy/flywheel_strategy.md` | Master strategy, flywheel design, website direction | On strategic shifts |
| `README.md` | Public-facing framing and live status | When metrics/change narrative updates |
| `research/edge_backlog_ranked.md` | Canonical strategy status and ranked pipeline | Every flywheel cycle |
| `FAST_TRADE_EDGE_ANALYSIS.md` | Current pipeline verdicts and kill-rule outcomes | After each pipeline run |
| `research/elastic_vision_document.md` | Strategic vision: Elastic positioning, messaging, non-trading strategy, governance | On strategic shifts |
| `research/platform_vision_document.md` | Platform vision: architecture, metrics, contribution flywheel, compliance | On strategic shifts |
| `research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md` | 100-strategy generation prompt + composite scoring | When prompt improves |
| `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md` | Fast-market RTDS maker execution spec | As implementation evolves |
| `research/LatencyEdgeResearch.md` | Infrastructure latency map and execution implications | On infra findings |

---

## 11. Prompt-Writing Context for AI Instances

When writing prompts to dispatch to ChatGPT, Cowork, Claude Code, or Grok, every prompt should:

1. **Reference this document** — Tell the AI to read `COMMAND_NODE.md` first for full context
2. **State the specific task** — What exactly should be produced
3. **Reference relevant files** — Point to the specific .md, .docx, or .py files in the workspace
4. **Specify the output format** — .docx for investor materials, .md for internal docs, code changes for Claude Code
5. **Include success criteria** — What does "done" look like
6. **Include the SOP reminder** — After completing the task, review all project documents for stale information

### Template for Dispatching to Any AI

```
Read COMMAND_NODE.md in the selected folder for full project context.

TASK: [What to do]

RELEVANT FILES:
- [List specific files to read]

OUTPUT: [Format and location]

DONE WHEN: [Success criteria]

SOP: After completing this task, UPDATE COMMAND_NODE.md (increment version number, add version log entry) and review all affected canonical docs for staleness.
```

### Tool-Specific Notes

**Claude Code:** Best for implementation tasks. Has terminal access. Can modify bot source code, run backtests, deploy to VPS. Point it at specific files in `polymarket-bot/src/` or `backtest/`.

**Cowork:** Best for analysis, document creation, research synthesis. Can create .docx, .xlsx, .pdf. Use for investor materials, Monte Carlo analysis, competitive landscape.

**ChatGPT Deep Research:** Best for web-sourced research with citations. Use for competitive landscape, academic paper synthesis, regulatory updates, market data.

**Grok:** Best for real-time data analysis. Use for live market monitoring, X/Twitter sentiment, competitive benchmarking against public bot performance.

---

## 12. Key Numbers to Know

| Metric | Value | Source |
|--------|-------|--------|
| Tracked capital | $347.51 tracked / $0.00 deployed | `PROJECT_INSTRUCTIONS.md` |
| Strategy statuses | 7 deployed / 6 building / 2 structural alpha / 1 re-evaluating / 10 rejected / 8 pre-rejected / 97 research pipeline | `research/edge_backlog_ranked.md` |
| Total tracked strategies | 131 | `research/edge_backlog_ranked.md` |
| Current pipeline verdict | REJECT ALL (no validated edge yet) | `FAST_TRADE_EDGE_ANALYSIS.md` |
| Data coverage (latest run) | 3,047 trade records, 1,715 wallets tracked | `FAST_TRADE_EDGE_ANALYSIS.md` |
| Live trading state | Remote artifact shows service stopped; launch is blocked pending no closed trades, no deployed capital, the A-6/B-1 gates, and flywheel hold | `PROJECT_INSTRUCTIONS.md` |
| Verification status | Root suite passing (`962 passed in 18.12s; 22 passed in 3.83s`); current full green baseline `1,397` total | `PROJECT_INSTRUCTIONS.md` |
| Dispatch work-orders | 11 `DISPATCH_*` files | `research/dispatches/` |
| Dispatch library | 95 markdown files | `research/dispatches/` |
| Flywheel cycle speed | 3-5 days | `docs/strategy/flywheel_strategy.md` |
| Dublin latency to CLOB | ~5-10ms to London (eu-west-2) | `research/LatencyEdgeResearch.md` |
| Primary fast-market infra target | WebSockets + RTDS + maker-only execution | `research/RTDS_MAKER_EDGE_IMPLEMENTATION.md` |

---

## 13. Live Deployment Checklist

### Architecture: Paper-to-Live Toggle

```
LIVE_TRADING=false → PaperBroker (simulated fills, no real money)
LIVE_TRADING=true  → PolymarketBroker (py-clob-client, real USDC on Polygon)

Safety gate chain (ALL must pass):
  ┌─ NO_TRADE_MODE=false ─────── Global kill-gate (Broker base class)
  ├─ LIVE_TRADING=true ────────── Broker selection (main.py)
  ├─ Safety rails ─────────────── Daily loss, per-trade cap, exposure, cooldown, rollout
  ├─ Risk manager ─────────────── Position limits, rate limits, drawdown
  └─ Kill switch OFF ──────────── DB-level emergency stop
```

### Live Trading Rules (NON-NEGOTIABLE)

- **Limit orders ONLY** — market orders permanently blocked (maker = zero fees)
- **Buy price = market - $0.01** — get filled or miss, never overpay
- **Order timeout: 60s** — unfilled orders auto-cancelled
- **Daily loss limit: $10** — auto kill switch on breach
- **Per-trade max: $5** — even if Kelly says more
- **Exposure cap: 80%** — always keep 20% cash reserve
- **Cooldown: 3 consecutive losses → 1 hour pause**
- **Kill switch: /kill cancels ALL open orders immediately**
- **Telegram alert on: every trade, every error, kill switch, cooldown**

### Gradual Rollout Plan

| Week | Max/Trade | Trades/Day | Kelly | Config Change Required |
|------|-----------|------------|-------|----------------------|
| 1 | $1.00 | 3 | OFF | Default (.env.live.template) |
| 2 | $2.00 | 5 | OFF | `ROLLOUT_MAX_PER_TRADE_USD=2.0`, `ROLLOUT_MAX_TRADES_PER_DAY=5` |
| 3 | $5.00 | Unlimited | ON | `ROLLOUT_MAX_PER_TRADE_USD=5.0`, `ROLLOUT_MAX_TRADES_PER_DAY=-1`, `ROLLOUT_KELLY_ACTIVE=true` |

**Each escalation requires a manual .env change and systemd restart. Not automatic.**

### Pre-Go-Live Checklist

```
[ ] 1. SSH into VPS: ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0
[ ] 2. cd /home/ubuntu/polymarket-trading-bot
[ ] 3. pip install py-clob-client --break-system-packages
[ ] 4. Copy .env.live.template to .env and fill in ALL credentials
[ ] 5. Verify CLOB connectivity:
       python -c "
       from py_clob_client.client import ClobClient
       c = ClobClient('https://clob.polymarket.com', key='YOUR_PK', chain_id=137)
       print(c.get_server_time())
       "
[ ] 6. Verify API auth:
       python -c "
       from py_clob_client.client import ClobClient
       from py_clob_client.clob_types import ApiCreds
       c = ClobClient('https://clob.polymarket.com', key='YOUR_PK', chain_id=137)
       c.set_api_creds(ApiCreds(api_key='...', api_secret='...', api_passphrase='...'))
       print(c.get_api_keys())
       "
[ ] 7. Check USDC balance on Polymarket (should be >= $247)
[ ] 8. Set in .env:
       NO_TRADE_MODE=false
       LIVE_TRADING=true
       ROLLOUT_MAX_PER_TRADE_USD=1.0
       ROLLOUT_MAX_TRADES_PER_DAY=3
[ ] 9. Restart bot: sudo systemctl restart jj-live
[ ] 10. Monitor logs: journalctl -u jj-live -f
[ ] 11. Check Telegram for startup notification (should say "💰 Live Trading")
[ ] 12. Watch first trade cycle — verify:
        - Order appears on Polymarket CLOB
        - Telegram alert received
        - bot.db order record created
        - Order auto-cancelled after 60s if unfilled
[ ] 13. Test kill switch: curl -X POST http://localhost:8000/kill \
          -H "Authorization: Bearer YOUR_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"reason": "test kill"}'
[ ] 14. Verify kill switch:
        - Telegram alert received
        - All open orders cancelled
        - Engine loop pauses
[ ] 15. Un-kill: curl -X POST http://localhost:8000/unkill \
          -H "Authorization: Bearer YOUR_TOKEN"
```

### Elastic Observability Checklist

Run this when the Elastic lane is enabled:

```text
[ ] 1. Start the stack: bash infra/setup.sh
[ ] 2. Confirm Elasticsearch health and open Kibana at http://127.0.0.1:5601
[ ] 3. Store the generated elastic password outside the repo and export ES_* env vars
[ ] 4. Verify Filebeat is shipping /var/log/elastifund/*.log and *.json files
[ ] 5. Confirm APM transactions exist for the signal evaluation cycle and order path
[ ] 6. Import dashboard packs from infra/kibana_dashboards/
[ ] 7. Check elastifund-trades, elastifund-signals, elastifund-kills, and elastifund-orderbook in Discover
[ ] 8. If ML is enabled, create/open jobs and verify anomaly_consumer remains fail-soft when no anomalies exist
```

### Key Files (Updated File Structure — 2026-03-08)

```
Elastifund/
├── AGENTS.md                   ← Machine-first entrypoint and root guardrails
├── PROJECT_INSTRUCTIONS.md     ← Quick-start for any AI session (paste this first)
├── COMMAND_NODE.md             ← THIS FILE (deep reference)
├── README.md                   ← Public-facing overview
│
├── bot/                        ← LIVE TRADING CODE
│   ├── jj_live.py              ← Main bot + confirmation layer (→ VPS)
│   ├── elastic_client.py       ← Async Elastic writer, health checks, fail-soft telemetry
│   ├── elastic_dashboards.py   ← Kibana saved-object importer
│   ├── apm_setup.py            ← Elastic APM bootstrap + transaction wiring
│   ├── log_config.py           ← Structured ECS-style logging
│   ├── latency_tracker.py      ← Decorator for latency events, spans, and reports
│   ├── anomaly_consumer.py     ← Signal source #7: ML anomaly feedback lane
│   ├── elastic_ml_setup.py     ← ML job creation and anomaly status tooling
│   ├── lmsr_engine.py          ← LMSR Bayesian pricing + inefficiency detector
│   ├── wallet_flow_detector.py ← Smart wallet consensus signals (complete)
│   ├── ensemble_estimator.py   ← Canonical multi-model estimator + RAG + Brier
│   ├── llm_ensemble.py         ← Legacy compatibility surface for older ensemble flows
│   ├── cross_platform_arb.py   ← Polymarket↔Kalshi arb scanner (29 tests)
│   ├── tests/                  ← Unit tests (108 passing: 34 ensemble + 29 arb + 45 LMSR)
│   └── kalshi/                 ← Kalshi RSA key + integration
│
├── polymarket-bot/             ← Core engine (FastAPI, SQLAlchemy)
├── backtest/                   ← Backtesting, Monte Carlo, calibration
├── simulator/                  ← Position sizing simulator
├── data_layer/                 ← DB schema, migrations
├── infra/                      ← Elastic compose, Filebeat/APM config, index templates, dashboards
├── data/                       ← Runtime DBs (wallet_scores.db, quant.db)
├── scripts/                    ← deploy.sh
│
├── research/
│   ├── deep_research_prompt.md ← Current deep-research execution package
│   ├── deep_research_output.md ← Wide strategy taxonomy source document
│   ├── jj_assessment_dispatch.md ← JJ prioritization and kill decisions
│   ├── karpathy_autoresearch_report.md ← Loop-design and benchmark discipline notes
│   └── *.md                    ← Other research findings and ranked backlogs
│
├── docs/
│   ├── strategy/               ← Flywheel, edge system, SMART_WALLET_SPEC, etc.
│   ├── ops/                    ← Deploy guides, llm_context_manifest, checklists, audits
│   ├── diary/                  ← Public-facing research diary entries
│   └── templates/              ← Report templates
│
└── archive/                    ← Superseded files
```

### Funded Accounts (machine truth reconciled on 2026-03-09)

| Platform | Balance | Wallet/Key | Status |
|----------|---------|------------|--------|
| Polymarket | $247.51 USDC | Proxy 0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5 | Live wallet funded; remote service artifact is `stopped`, the dry-run deploy path is validated, remote mode is still unknown, and launch posture remains blocked pending service-not-running, no closed trades, no deployed capital, and the A-6/B-1 gates |
| Kalshi | $100.00 USD | Key ID b20ab9fa-b387-4aac-b160-c22d58705935 | API connected, trading not built |

### VPS Access

```bash
# Dublin (ACTIVE)
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0
# Bot: /home/ubuntu/polymarket-trading-bot/
# Service: sudo systemctl start jj-live

# Frankfurt (DECOMMISSIONED — 161.35.24.142 unreachable)
```

---

## 14. The Flywheel: Research → Build → Test → Record → Publish → Repeat

### Vision

Elastifund is an **agent-run company**. John sets constraints and infrastructure; JJ executes inside those boundaries to maximize risk-adjusted return. The trading engine is the laboratory and the documentation engine is the product.

The project's dual mission:
1. **Find profitable edges** on prediction markets using AI agents
2. **Build the world's most comprehensive public resource** on agentic trading systems

The second mission is at least as important as the first. The website (johnbradleytrading.com) and the public GitHub repo are primary outputs.

**Website vision (1 paragraph):** Build a layered learning surface where a curious layperson can understand the system in minutes, a developer can reproduce the stack quickly, and an experienced quant can audit methods, failures, and assumptions in depth. Every cycle contributes new diary entries, strategy autopsies, and architecture updates so the site becomes the most complete public record of agentic trading development, not a marketing shell with cherry-picked wins. The credibility moat is transparent process plus honest failure documentation.

### The 6-Phase Cycle (3-5 Days Per Rotation)

```
PHASE 1: RESEARCH    — Run research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md, rank hypotheses, update edge_backlog_ranked.md
PHASE 2: IMPLEMENT   — Code top 3-5 strategies, commit to GitHub, update task list
PHASE 3: TEST        — Run edge discovery pipeline (src/main.py), apply kill rules
PHASE 4: RECORD      — Update FAST_TRADE_EDGE_ANALYSIS.md, COMMAND_NODE, edge_backlog_ranked.md
PHASE 5: PUBLISH     — Push to GitHub, copy top docs to command nodes (ChatGPT/Claude web), update website
PHASE 6: REPEAT      — Feed results into next research prompt, refine hypotheses
```

### The Copy Sequence (Phase 5)

After every cycle:
1. `git push origin main` — public GitHub updated
2. Copy `COMMAND_NODE.md` into new ChatGPT and Claude web sessions
3. Copy `PROJECT_INSTRUCTIONS.md` into new Claude Code sessions
4. Update Replit website with new diary entries and strategy analyses
5. Write diary entry for the website

### Document Update Frequency

| Tier | Documents |
|------|-----------|
| Always (every cycle) | `FAST_TRADE_EDGE_ANALYSIS.md`, `research/edge_backlog_ranked.md`, website diary entry |
| On meaningful changes | `COMMAND_NODE.md` (version bump required), `PROJECT_INSTRUCTIONS.md`, `docs/strategy/edge_discovery_system.md`, `README.md` |
| Infrequent / strategic | `CLAUDE.md`, `docs/strategy/flywheel_strategy.md`, investor materials |

### Open-Source Guardrails

| Public by Default | Private in `.env` / `.gitignore` |
|-------------------|----------------------------------|
| Architecture, code structure, strategy methodology, backtest framework, failure logs, flywheel process, educational content | API keys (Anthropic/OpenAI/Polymarket/Kalshi/Telegram), private keys/wallet credentials, signing secrets, live-edge sensitive runtime parameters |

### Key Files for the Flywheel

| File | Purpose |
|------|---------|
| `research/DEEP_RESEARCH_PROMPT_100_STRATEGIES.md` | 100-strategy research prompt (paste into deep research sessions) |
| `docs/strategy/flywheel_strategy.md` | Master project strategy — the north star document |
| `REPLIT_DASHBOARD_v3.md` | Full website specification for Replit build |
| `docs/strategy/edge_discovery_system.md` | Technical spec for continuous edge research pipeline |
| `FAST_TRADE_EDGE_ANALYSIS.md` | Auto-generated current status of all tested strategies |
| `research/edge_backlog_ranked.md` | Ranked list of strategy hypotheses to test |

### Success Metrics

**Trading:** 50+ strategies tested within 60 days. At least 1 validated edge. Any positive live P&L.
**Website:** Daily diary entries. 100 unique visitors in month 1. 50 GitHub stars in 3 months. 1 external contributor. Dad understands the homepage. A quant trader says "this is impressive."
**Mission:** 20% of net profits to veteran suicide prevention. All results published openly.

---

*This document is the single source of truth. When in doubt, read PROJECT_INSTRUCTIONS.md first (quick-start), then this file for deep reference. **MANDATORY:** When storing ANY new report or research output, bump the version number and add to the Version Log BEFORE finishing. Per SOP: every research completion triggers (1) a Command Node version increment, and (2) a review of all project documents for staleness.*
