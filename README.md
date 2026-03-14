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

- **Live proof:** the BTC5 sleeve is the active trading proof lane. 128 closed contracts, 75W/53L, +$131.52 realized, 1.49 profit factor. Currently diagnosing a zero-fill condition on VPS (service running but not filling). Broader fund-level claims stay blocked until reconciliation and attribution are consistent.
- **Structural alpha killed:** A-6 (Guaranteed Basis) and B-1 (Templated Dependency) formally killed 2026-03-13 after 5-day kill-watch with zero evidence. Engineering capacity reallocated to BTC5 optimization and Kalshi calibration.
- **Pipeline-execution gap:** FAST_TRADE_EDGE_ANALYSIS.md says REJECT ALL, but this only covers the LLM-probability pipeline. The BTC5 maker operates independently using price-delta microstructure. See `research/dispatches/DISPATCH_101_pipeline_execution_gap.md`.
- **Historical validation:** `71.2%` is the strongest labeled calibrated validation result on `532` resolved markets. It is historical validation, not a live-performance headline.
- **Non-trading wedge:** JJ-N's first offer is the Website Growth Audit. It is built in code, explicitly gated, and not yet presented as launched revenue.
- **Contribution posture:** public routes read sanitized checked-in artifacts and the default contribution path is paper mode. No live exchange credentials are required to inspect or improve the system.
- **Verification:** the latest checked-in root verification summary is `1641 passed, 5 warnings in 37.10s; 25 passed, 1 warning in 4.56s`.

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

This is the autoresearch-style improvement log. Each entry represents a validated change to the live system, not a plan or hypothesis.

### Cycle 2 — Structural Alpha & Microstructure Defense (Current)

**Deployed improvements:**

- **The reconciliation pass clarified market outcome attribution and exposure posture** from mixed realized and unresolved signals.
- **BTC5 public status is currently in a cautious posture.** The deploy recommendation is now **shadow_only** (not promote) while blocked-claim alignment remains in force.
- **Directional edge is still strongest in the DOWN lane, with price-bucket behavior currently the main structural discriminator.**
- **Wallet and local ledger counts are back in sync.** The latest reconciliation surface shows **50** closed positions and **9** open positions on both the local ledger and the remote wallet, removing one major source of status drift.
- **The live market-universe context is fresher.** The March 11 pull shows **7,017** active markets across **500** events, with **111** crypto markets in the broad universe and **26** active crypto markets resolving within **24 hours** on the active surface.
- **Maker-only execution enforced.** 100% post-only orders. Zero taker fees. Maker rebates on every fill. This single change (Dispatch #75) eliminated the fee drag that killed earlier strategies.
- **Six signal sources wired into the live loop.** LLM probability estimation, smart wallet flow detection, LMSR Bayesian pricing, cross-platform arbitrage, VPIN/OFI microstructure, and semantic lead-lag. Each can be independently enabled or disabled per runtime profile.
- **Automated kill rules operational.** Semantic decay, toxicity survival, cost stress polynomial, and calibration enforcement — all running in production. Strategies that fail these die automatically.
- **WebSocket CLOB feed integrated.** Real-time order book data flowing into VPIN and OFI calculations for microstructure-aware execution.
- **Calibration locked.** Static Platt A=0.5914, B=-0.3977 validated on 532 markets (Brier 0.2134). Beats all rolling windows tested. No drift detected.

**Known issues being worked:**

- Launch-contract drift still blocks live promotion: `agent_run_mode=live`, `execution_mode=shadow`, `allow_order_submission=false`, `launch_posture=blocked`.
- Capital accounting is still not coherent even though position counts are reconciled; the latest Polymarket accounting delta remains non-zero versus tracked capital.
- `scripts/run_pm_fast_market_registry.py` reached Gamma successfully on March 11 but still wrote **0 discovered eligible markets**, while direct Gamma pulls show active crypto threshold, range, and candle markets. The registry logic is stale relative to the live API.
- `FAST_TRADE_EDGE_ANALYSIS.md` says "REJECT ALL" for the LLM-probability pipeline. This is correct for that pipeline. The BTC5 maker operates on a different signal (price delta) and is not subject to this report. See `research/dispatches/DISPATCH_101_pipeline_execution_gap.md`.
- A-6 (Guaranteed Basis) and B-1 (Templated Dependency) structural alpha lanes **KILLED** 2026-03-13. Zero evidence after 5-day kill-watch. Capacity reallocated.

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

## Verified On March 9, 2026

All commands pass in this repo state: `make doctor`, `make quickstart`, `make test`, `make test-polymarket`, `make test-nontrading`, `make smoke-nontrading`.

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
