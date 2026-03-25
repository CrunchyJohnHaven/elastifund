# Elastifund

**An open-source, self-improving operating system for agents that do real economic work.**

| Metadata | Value |
|---|---|
| Canonical file | `README.md` |
| Role | Public overview and **Start Here** path |
| Operator packet | `COMMAND_NODE.md` |
| Operator policy | `PROJECT_INSTRUCTIONS.md` |
| Last updated | 2026-03-14 |

Elastifund is building a governed system where agents do work, record what happened, learn from outcomes, and improve through shared memory, evaluation, observability, and workflow control.

Trading is the first proof lane because feedback is fast.
Non-trading is the broader platform opportunity because the same self-improvement substrate can improve revenue, research, support, and workflow execution across many kinds of economic work.

Elastic is the shared substrate for system memory, evaluation, observability, workflow automation, and public publishing across the trading workers, JJ-N, and the finance control plane.

**Website:** [elastifund.io](https://elastifund.io)

---

## Root Cross-Reference (Canonical)

| Need | Canonical file | Notes |
|---|---|---|
| **Start Here** (new contributor) | [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md) | shortest paper-mode path |
| **Operator Packet** (existing operator / deep research) | [COMMAND_NODE.md](COMMAND_NODE.md) | single root handoff packet |
| Active operating policy | [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md) | execution and policy contract |
| Machine-first workflow rules | [AGENTS.md](AGENTS.md) | commands, guardrails, path ownership |
| Canonical architecture index | [docs/architecture/README.md](docs/architecture/README.md) | proof kernel, event tape, strike desk, promotion, deploy split |
| Canonical deploy / shadow split | [docs/architecture/deployment_blueprint.md](docs/architecture/deployment_blueprint.md) | local twin vs Lightsail role boundary |
| Contribution and PR requirements | [CONTRIBUTING.md](CONTRIBUTING.md) | setup, tests, DCO |

### Start Here Path

`README.md` -> `docs/FORK_AND_RUN.md`

### Operator Packet Path

`COMMAND_NODE.md` (packet) + `PROJECT_INSTRUCTIONS.md` (policy)

## Posture Terms (Canonical)

- **Launch posture**: policy gate for whether live submission is permitted (`clear` or `blocked`).
- **Live posture**: observed runtime mode/profile (`live`, `shadow`, or paper equivalents).
- When they disagree, treat launch posture as the allow/deny gate and resolve the mismatch before promoting.

---

## What To Believe Right Now (March 14, 2026)

- **Live proof:** the BTC5 sleeve is the active trading proof lane. Historical closed batch: +$131.52 on 128 contracts (75W/53L, PF 1.49). Broader fund-level claims stay blocked until reconciliation and attribution are consistent.
- **Structural alpha killed:** A-6 (Guaranteed Dollar) and B-1 (Templated Dependency) formally killed 2026-03-13 after 5-day kill-watch with zero evidence. Engineering capacity reallocated to BTC5 optimization and Kalshi integration.
- **Historical validation:** `71.2%` is the strongest labeled calibrated validation result on `532` resolved markets. It is historical validation, not a live-performance headline.
- **Non-trading wedge:** JJ-N's first offer is the Website Growth Audit. It is built in code, explicitly gated, and not yet presented as launched revenue.
- **Contribution posture:** public routes read sanitized checked-in artifacts and the default contribution path is paper mode. No live exchange credentials are required to inspect or improve the system.
- **Verification:** `1961 passed, 50 failed, 5 warnings` (root suite). The 50 failures are isolated to `test_btc_5min_maker_process_window_core.py` — a regression from recent guardrail changes. All other surfaces green.

We are deliberately not leading this README with annualized forecast math, bankroll disclosure, or blended performance claims. Those numbers create more confusion than trust in the current public pass.

---

## Why Elastic Should Care

The important claim is not "Elastic can monitor a bot."
The important claim is that self-improving agents need durable memory, evaluation, observability, and workflow control in one substrate.
That is the category Elastifund is trying to make legible in public.

In this repo, Elastic is the shared substrate for:

- **System memory.** Trading workers, JJ-N, and the finance control plane write artifacts, traces, telemetry, and operator context into a searchable evidence layer instead of leaving state trapped in local logs.
- **Evaluation.** Signal quality, blocked claims, kill rules, confidence labels, and promotion decisions stay tied to labeled artifacts instead of drifting into blended dashboards or vague summaries.
- **Observability.** Elastic APM, dashboards, and ML/anomaly jobs make it possible to inspect latency, execution quality, workflow health, and abnormal regimes without changing runtime behavior.
- **Publishing.** The public site, operator docs, and GitHub narrative can all point back to the same evidence surfaces, keeping public claims narrower than raw internal state when they need to be.

### Shared Evidence Layer

```text
Trading workers ---\
JJ-N workers ------+--> Elastic-backed evidence layer --> evaluation + observability --> README, /live/, /elastic/, docs
Finance control ---/
```

Shared layer contents: artifacts, traces, telemetry. Shared outputs: scorecards, kill rules, blocked claims, dashboards.

That is why the trading sleeve, JJ-N launch-prep work, and the repo's public surfaces can stay separate without becoming contradictory. They share one evidence substrate.

### Why An Elastic Employee Should Care

This repo is a public proof surface for Search AI, system memory, observability, evaluation, and workflow control working together in one agentic system. It stays paper-mode safe in public by separating live proof from blocked claims and by reading only sanitized checked-in artifacts from the browser side.

Start with [/elastic/](https://elastifund.io/elastic/) for the employee-facing route, [docs/ELASTIC_INTEGRATION.md](docs/ELASTIC_INTEGRATION.md) for the operator-facing integration details, and [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md) for the shortest repo run path.

## Why Trading First And Non-Trading Next

Trading is the first proof lane because it offers fast feedback and hard outcomes.
It is not the whole product.

The larger opportunity for Elastic is the non-trading lane: a shared operating system for agents that improve customer-facing and revenue-facing workflows through better retrieval, better memory, better evaluation, and better workflow control.

That is why JJ-N matters.
It is not decorative roadmap copy.
It is the bridge from "interesting trading lab" to "company-relevant self-improving agent platform."

## What We Are Not Claiming Yet

- Estimated ARR is the only public revenue metric, and it is labeled as an estimate.
- We are not publishing bankroll size, wallet value, or free collateral as a pitch surface.
- We are not presenting fund-level realized returns as clean while reconciliation and attribution remain open.
- We are not presenting JJ-N as fully launched revenue.

---

## What Has Improved (System Changelog)

This is the autoresearch-style improvement log. It records implemented system changes, but it is not a claim that the launch contract is green or that multi-venue live trading is currently authorized.

### Cycle 2 — Structural Alpha & Microstructure Defense (Current)

**Deployed improvements:**

- **The reconciliation pass clarified market outcome attribution and exposure posture** from mixed realized and unresolved signals.
- **BTC5 guardrail fixes deployed 2026-03-14.** Three simultaneous blockers diagnosed and fixed: delta widened from 0.00075 to 0.0040, UP direction enabled (was shadow-only), min_buy_price lowered to 0.42. Remaining skips are legitimate market-quality gates.
- **Directional edge is still strongest in the DOWN lane, with price-bucket behavior currently the main structural discriminator.**
- **A-6 and B-1 structural alpha lanes killed 2026-03-13.** Zero evidence after 5-day kill-watch. Full rationale in `research/what_doesnt_work_diary_v1.md`.
- **Wallet reconciliation completed on 2026-03-14.** Root cause was wrong wallet address for data API queries; wallet-authoritative value is now tracked as $458.13 Polymarket with +$207.31 realized net P&L.
- **Maker-only execution enforced.** 100% post-only orders. Zero taker fees. Maker rebates on every fill. This single change (Dispatch #75) eliminated the fee drag that killed earlier strategies.
- **Six signal sources are implemented in the codebase.** They are not all approved for live capital, and the current proving-ground reset keeps BTC5 on Polymarket as the only candidate sleeve for graduation.
- **Automated kill rules are implemented in the runtime.** They remain part of the proving ground, but current launch posture still depends on wallet truth, replay, and promotion artifacts agreeing.
- **WebSocket CLOB feed integrated.** Real-time order book data flowing into VPIN and OFI calculations for microstructure-aware execution.
- **Calibration locked.** Static Platt A=0.5914, B=-0.3977 validated on 532 markets (Brier 0.2134). Beats all rolling windows tested. No drift detected.

**Known issues being worked:**

- Launch-contract drift still needs cleanup: profile semantics and operator docs can disagree (`execution_mode=shadow` while live order submission is enabled).
- BTC5 promotion gate currently fails: hold at $5/trade until `reports/btc5_promotion_gate.json` reports `overall_gate=true` over a >=7-day window.
- `FAST_TRADE_EDGE_ANALYSIS.md` still says "REJECT ALL" (~5 days stale) while BTC5 has real live fills. The edge scan pipeline is decoupled from actual execution.
- 50 test failures in `test_btc_5min_maker_process_window_core.py` from recent guardrail changes. All other test surfaces green.
- BTC5 guardrail fixes deployed 2026-03-14. Awaiting fill validation during US trading hours.

### Cycle 1 — Foundation & First Trades

- Built the complete six-signal trading loop from scratch
- Deployed to AWS Lightsail Dublin VPS for 24/7 operation
- Integrated Polymarket Gamma API, CLOB, and Kalshi API
- Established the hypothesis testing pipeline with automated kill rules
- Tested and rejected 10 strategies with documented evidence (see `research/what_doesnt_work_diary_v1.md`)
- Published 95 research dispatches covering edge hypotheses, platform analysis, and failure documentation
- Built the non-trading revenue lane (JJ-N) with five-engine architecture, CRM, and compliance gates
- Achieved 1,397 passing tests across all surfaces

---

## Architecture

The system runs two worker families plus one finance control plane sharing an Elastic-backed evidence layer for memory, evaluation, observability, and publishing:

- **Trading workers** — research, simulate, rank, and execute market strategies under policy (Polymarket, Kalshi)
- **Non-trading workers (JJ-N)** — create economic value through business development, research, services, and customer acquisition
- **Finance control plane** — rank personal cash, subscriptions, tool spend, trading capital, and experiment budgets as one allocation problem

The live trading loop:

1. Scan current markets
2. Filter out lanes where the model has no defensible edge
3. Pull recent context and structured inputs
4. Estimate probabilities without anchoring to the market price
5. Calibrate those probabilities (Platt scaling)
6. Compare estimated value to market pricing, fees, and execution constraints
7. Size conservatively (quarter-Kelly)
8. Route only when risk rules and lane-specific gates pass

Around this sits the research flywheel: `research -> implement -> test -> record -> publish -> repeat`

---

## Route Matrix

| I want to... | Start here |
|---|---|
| See the employee-facing Elastic route | [/elastic/](https://elastifund.io/elastic/) |
| Boot the repo with the least friction | [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md) |
| Hand one root packet to Deep Research | [COMMAND_NODE.md](COMMAND_NODE.md) |
| Understand the Elastic observability layer | [docs/ELASTIC_INTEGRATION.md](docs/ELASTIC_INTEGRATION.md) |
| Run the observability demo on Replit | [docs/REPLIT_BUILD_GUIDE.md](docs/REPLIT_BUILD_GUIDE.md) |
| Use Codex and Claude Code in parallel | [AGENTS.md](AGENTS.md) + [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) |
| Load active session context before planning | current task context packet (CLI/runtime-handoff equivalent) |
| Understand the monorepo layout before editing | [docs/REPO_MAP.md](docs/REPO_MAP.md) |
| Explore the non-trading revenue lane | [nontrading/README.md](nontrading/README.md) + [docs/NON_TRADING_STATUS.md](docs/NON_TRADING_STATUS.md) |
| Work only on the trading bot subproject | [polymarket-bot/README.md](polymarket-bot/README.md) |
| Inspect the HTTP/control-plane surface | [docs/api/README.md](docs/api/README.md) |
| Contribute code safely | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Fastest Paper-Mode Boot

```bash
git clone https://github.com/CrunchyJohnHaven/elastifund.git
cd elastifund
make doctor
make quickstart
```

That path prepares `.env`, writes the runtime manifest, and starts the local coordination stack if Docker is installed.
It is the recommended employee-safe path and does not require live trading credentials.

```bash
# Full developer verification
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
make verify
make smoke-nontrading
```

For docs/static/index-only changes, use the lightweight loop:

```bash
make bootstrap-lite
make verify-static
make test-select
```

`bootstrap-lite` intentionally skips runtime/research dependencies. For runtime-only dependencies without test/dev extras, use `make bootstrap-runtime`.

## Verified On March 14, 2026

Core commands pass: `make doctor`, `make quickstart`, `make test-polymarket`, `make test-nontrading`, `make smoke-nontrading`. Root `make test` has 50 isolated failures in BTC5 process-window tests (guardrail regression); all other surfaces green.

## Public Snapshot Contract

Machine-readable dataset: [improvement_velocity.json](improvement_velocity.json)

Use the checked-in contract for verification status, strategy counts, cycle counts, and worker readiness.
Do not treat the raw forecast fields inside it as interchangeable with realized live performance or fund-level public claims.

## Tech Stack

- Python 3.12, `pytest`, and repo-root `make` targets
- Polymarket Gamma API and CLOB integration
- Kalshi API integration
- SQLite and SQLAlchemy-backed persistence surfaces
- FastAPI-based dashboards and control-plane APIs
- Elastic Stack: Elasticsearch, Kibana, Filebeat, APM Server, and Elastic ML
- Docker Compose for local multi-service boot

## What This Repo Is

Elastifund is a public research engine for three related problems:

1. Where do LLMs actually help on prediction markets?
2. Which bounded non-trading automation lanes can produce cash flow without hand-waved compliance or billing risk?
3. How do you build a self-improving agentic system where better data, better memory, and better evaluation produce measurably better agents?

The repo contains both implementation code and the evidence trail behind it. The failures matter as much as the wins. The unifying principle: the project does not just run agents — it improves agents.

## Observability

Elastic is not a vanity dashboard layer. It is the operator surface for understanding which signal sources produce usable decisions, where latency accumulates in the signal-to-order path, how close the bot is to kill-rule thresholds, what the order book looked like when a trade was placed, and whether order flow or spread behavior has moved into an abnormal regime.

The integration is designed to fail soft. Elasticsearch writes are asynchronous, Filebeat handles shipping, and the bot keeps running with `ES_ENABLED=false` or when the Elastic stack is unreachable.

### Dashboards

- **Trading Overview:** trades per hour, win rate, cumulative P&L, and average fill latency
- **Signal Quality:** per-source signal accuracy, calibration drift, and signal-to-trade conversion
- **Kill Rule Monitor:** kill triggers over time, top firing rules, and current headroom to thresholds
- **Orderbook Health:** spread, depth, VPIN, and OFI state for fast-market execution review

Use [docs/ELASTIC_INTEGRATION.md](docs/ELASTIC_INTEGRATION.md) for the master guide and [docs/REPLIT_BUILD_GUIDE.md](docs/REPLIT_BUILD_GUIDE.md) for the Replit path.

## Non-Trading Lane (JJ-N)

The non-trading revenue worker (JJ-N) is the first-class front door of the project. The vision: start with a constrained revenue-operations worker for one narrow, high-ticket service offer, instrument everything, publish the evidence, and only expand once the first loop is repeatable.

JJ-N v1 is a revenue-operations worker with five engines: Account Intelligence, Outreach, Interaction, Proposal, and Learning. All five write into the same Elastic-backed memory.

What is already real: a compliance-first revenue-agent harness, a runnable five-engine `RevenuePipeline`, the first service offer (Website Growth Audit, estimated ARR only in public materials), a digital-product niche discovery pipeline, a Phase 0 CRM, paper-mode approval and compliance gates, Elastic-ready telemetry, niche ranking, and passing targeted tests with deterministic smoke coverage.

What is not built yet: the fully launched production path for the Website Growth Audit plus recurring monitor, a production KPI dashboard, and checkout/billing/fulfillment reporting.

For the current implementation state, use [docs/NON_TRADING_STATUS.md](docs/NON_TRADING_STATUS.md).

## Repo Tour

| Path | Purpose |
|---|---|
| `bot/` | live trading loop, signal wiring, structural-arb scanners, runtime decisions |
| `execution/` | multi-leg order orchestration and rollback rules |
| `strategies/` + `signals/` | strategy-specific logic and shared signal helpers |
| `src/`, `backtest/`, `simulator/` | edge-discovery and validation pipeline |
| `hub/`, `data_layer/`, `orchestration/` | APIs, persistence, flywheel/control-plane plumbing |
| `nontrading/` | non-trading revenue automation, Phase 0 CRM/approval/telemetry foundations, digital-product discovery, and the finance control plane |
| `polymarket-bot/` | self-contained trading bot subproject with dashboard and tests |
| `inventory/` | benchmark lane for comparing external systems cleanly |
| `docs/` + `research/` | durable docs, ADRs, prompts, dispatches, and findings |
| `deploy/` | bootstrap scripts and deployment assets |

If you want the deeper map, use [docs/REPO_MAP.md](docs/REPO_MAP.md).

## Key Documents

| Document | Purpose |
|---|---|
| [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md) | easiest bootstrap and host/spoke onboarding flow |
| [AGENTS.md](AGENTS.md) | machine-first entrypoint and core commands |
| [COMMAND_NODE.md](COMMAND_NODE.md) | single root deep-research handoff for current machine truth, implementation map, and improvement guidance |
| [docs/ELASTIC_INTEGRATION.md](docs/ELASTIC_INTEGRATION.md) | master Elastic Stack integration guide |
| [docs/REPLIT_BUILD_GUIDE.md](docs/REPLIT_BUILD_GUIDE.md) | Replit deployment path for the observability stack |
| [docs/ELASTIC_LESSONS_LEARNED.md](docs/ELASTIC_LESSONS_LEARNED.md) | public log of what the Elastic layer actually teaches us |
| [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) | how to split work between Codex and Claude Code safely |
| [docs/REPO_MAP.md](docs/REPO_MAP.md) | canonical monorepo map and edit boundaries |
| [nontrading/README.md](nontrading/README.md) | non-trading developer entrypoint |
| [docs/NON_TRADING_STATUS.md](docs/NON_TRADING_STATUS.md) | current implementation status of the non-trading lane |
| [polymarket-bot/README.md](polymarket-bot/README.md) | standalone trading bot subproject guide |
| [docs/api/README.md](docs/api/README.md) | API surfaces and OpenAPI generation |
| [research/dispatches/README.md](research/dispatches/README.md) | dispatch system for parallel research and implementation |
| [research/what_doesnt_work_diary_v1.md](research/what_doesnt_work_diary_v1.md) | failure diary and dead-lane evidence |

## Mission

**20% of all net trading profits go to veteran suicide prevention.**

- [Veterans Crisis Line](https://www.veteranscrisisline.net/)
- [Stop Soldier Suicide](https://stopsoldiersuicide.org/)
- [22Until None](https://www.22untilnone.org/)

## Contributing

The repo is open because scrutiny is useful. If you contribute: be explicit about whether something is live, paper, backtest, non-trading research, or ops. Bring tests or evidence when behavior changes. Do not leak secrets, wallets, or private operational settings. Prefer a clean failure over a vague success claim.

Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and disclosure expectations.

## License

MIT.
