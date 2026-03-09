# Elastifund

**A self-improving agentic operating system for real economic work.**

Elastifund turns research, experiments, and execution into searchable evidence — so trading and non-trading agents can improve with every run. The Elastic Stack is the system memory, evaluation, and observability substrate underneath the whole thing.

The system has two families of workers sharing a common data, evaluation, and improvement layer:

- **Trading workers** — research, simulate, rank, and optionally execute market strategies under policy (Polymarket, Kalshi)
- **Non-trading workers (JJ-N)** — create economic value through business development, research, services, operations, and customer acquisition

The repo is built to be usable by humans and by coding agents. Fork it, run one command to start in default paper mode, and begin contributing validated improvements back into the system.

**Website:** [elastifund.io](https://elastifund.io)

## Choose Your Path

| I want to... | Start here |
|---|---|
| Boot the repo with the least friction | [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md) |
| Understand the Elastic observability layer | [docs/ELASTIC_INTEGRATION.md](docs/ELASTIC_INTEGRATION.md) |
| Run the observability demo on Replit | [docs/REPLIT_BUILD_GUIDE.md](docs/REPLIT_BUILD_GUIDE.md) |
| Use Codex and Claude Code in parallel | [AGENTS.md](AGENTS.md) + [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) |
| Understand the monorepo layout before editing | [docs/REPO_MAP.md](docs/REPO_MAP.md) |
| Explore the non-trading revenue lane | [nontrading/README.md](nontrading/README.md) + [docs/NON_TRADING_STATUS.md](docs/NON_TRADING_STATUS.md) |
| Work only on the trading bot subproject | [polymarket-bot/README.md](polymarket-bot/README.md) |
| Inspect the HTTP/control-plane surface | [docs/api/README.md](docs/api/README.md) |
| Contribute code safely | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Fastest Local Boot

From the repo root:

```bash
git clone https://github.com/CrunchyJohnHaven/elastifund.git
cd elastifund
python3 scripts/doctor.py
python3 scripts/quickstart.py
```

That path prepares `.env`, writes the runtime manifest, and starts the local coordination stack if Docker is installed.

If you want to prepare the repo without starting Docker yet:

```bash
python3 scripts/quickstart.py --prepare-only
```

If you want the full developer verification pass:

```bash
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
make verify
make smoke-nontrading
```

## Verified On March 8, 2026

These commands were run successfully in this repo state:

- `python3 scripts/doctor.py`
- `python3 scripts/quickstart.py --prepare-only`
- `make test`
- `make test-polymarket`
- `make test-nontrading`
- `make smoke-nontrading`

The non-Docker path was verified directly. Docker still requires Docker Desktop or Docker Engine on the machine running the stack.

## Current Snapshot

| Area | Current state |
|---|---|
| Runtime truth | prefer `reports/public_runtime_snapshot.json` and `reports/runtime_truth_latest.json`; use `reports/remote_cycle_status.json`, `reports/remote_service_status.json`, `FAST_TRADE_EDGE_ANALYSIS.md`, and `reports/arb_empirical_snapshot.json` for the underlying detail |
| Capital tracked in docs | `$347.51` total (`$247.51` Polymarket + `$100` Kalshi) |
| Runtime state | `0` trades after `313` cycles; `reports/remote_service_status.json` shows `jj-live.service` `stopped` at `2026-03-09T01:28:43Z`, while launch posture remains blocked |
| Fast-flow launch posture | wallet-flow is `ready` with `80` scored wallets and `fast_flow_restart_ready=true`, but the latest edge scan still says `stay_paused`, the service is stopped, and the threshold-sensitivity refresh still found `0` tradeable markets at YES `0.15`, NO `0.05`; YES `0.08`, NO `0.03`; and YES `0.05`, NO `0.02` |
| Trading strategy catalog | `131` tracked (`7` deployed, `6` building, `2` structural alpha, `1` re-evaluating, `10` rejected, `8` pre-rejected, `97` pipeline) |
| Non-trading lane | compliance-first revenue harness, digital-product niche discovery, and JJ-N Phase 0 foundations (CRM, opportunity registry, approval/compliance, telemetry, engine stubs) are in repo; first revenue product is not yet launched |
| Verification status | latest local verification shows root passing (`962 passed in 18.12s; 22 passed in 3.83s`); the current full multi-surface green baseline is `1,397` total tests (`962 + 22` root, `374` polymarket, `39` non-trading), and the repo-root `tests/` sync pass is `421` green |
| Live validated P&L | still effectively pre-revenue; no inflated claims here |

The March 9 runtime snapshot supersedes older prose that said the service was stopped and wallet-flow was not ready, but it still does not clear launch. The stable public snapshot now shows wallet-flow ready, service stopped, and launch blocked because there are no closed trades, no deployed capital, and A-6/B-1 remain unresolved. The latest deploy dry-run is now validated and kept the service stopped, but the remote mode is still unknown and the latest edge scan still says `stay_paused`, so any actual bundle upload or restart remains a deliberate paper/shadow evidence-collection decision rather than a green light from the signal stack.

## Velocity Charts

These repo-root charts reconcile the March 9 runtime truth with the diary, backlog funnel, and non-trading lane status.

![Improvement velocity](improvement_velocity.svg)

![ARR estimate](arr_estimate.svg)

Machine-readable dataset: [improvement_velocity.json](improvement_velocity.json)

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

That means the repo contains both implementation code and the evidence trail behind it. The failures matter as much as the wins. The unifying principle: the project does not just run agents — it improves agents.

## Observability

Elastic is not a vanity dashboard layer in this repo. It is the operator surface for understanding:

- which signal sources are producing usable decisions
- where latency is accumulating in the signal-to-order path
- how close the bot is to kill-rule thresholds
- what the order book looked like when a trade was placed
- whether order flow or spread behavior has moved into an abnormal regime

The integration is designed to fail soft. Elasticsearch writes are asynchronous, Filebeat handles shipping, and the bot must keep running with `ES_ENABLED=false` or when the Elastic stack is unreachable.

### Dashboards

- **Trading Overview:** trades per hour, win rate, cumulative P&L, and average fill latency
- **Signal Quality:** per-source signal accuracy, calibration drift, and signal-to-trade conversion
- **Kill Rule Monitor:** kill triggers over time, top firing rules, and current headroom to thresholds
- **Orderbook Health:** spread, depth, VPIN, and OFI state for fast-market execution review

Use [docs/ELASTIC_INTEGRATION.md](docs/ELASTIC_INTEGRATION.md) for the master guide and [docs/REPLIT_BUILD_GUIDE.md](docs/REPLIT_BUILD_GUIDE.md) for the Replit path.

## Trading Lane

At a high level, the live loop works like this:

1. Scan current markets.
2. Filter out lanes where the model has no defensible edge.
3. Pull recent context and structured inputs.
4. Estimate probabilities without anchoring the model to the market price.
5. Calibrate those probabilities.
6. Compare estimated value to market pricing, fees, and execution constraints.
7. Size conservatively.
8. Route only when risk rules and lane-specific gates pass.

That is the trading side. Around it sits a larger flywheel:

`research -> implement -> test -> record -> publish -> repeat`

## Non-Trading Lane (JJ-N)

The non-trading revenue worker (JJ-N) is the first-class front door of the project. The vision: start with a constrained revenue-operations worker for one narrow, high-ticket service offer, instrument everything, publish the evidence, and only expand once the first loop is repeatable.

JJ-N v1 is a revenue-operations worker with five engines: Account Intelligence, Outreach, Interaction, Proposal, and Learning. All five write into the same Elastic-backed memory.

What is already real:

- a compliance-first revenue-agent harness in [nontrading/main.py](nontrading/main.py)
- a digital-product niche discovery pipeline in [nontrading/digital_products/main.py](nontrading/digital_products/main.py)
- a Phase 0 CRM schema in [nontrading/models.py](nontrading/models.py) and [nontrading/store.py](nontrading/store.py)
- an opportunity registry in [nontrading/opportunity_registry.py](nontrading/opportunity_registry.py)
- paper-mode approval and compliance gates in [nontrading/approval.py](nontrading/approval.py) and [nontrading/compliance.py](nontrading/compliance.py)
- Elastic-ready telemetry plus five engine stubs under [nontrading/telemetry.py](nontrading/telemetry.py) and [nontrading/engines/__init__.py](nontrading/engines/__init__.py)
- niche ranking and Elastic-ready bulk export
- passing targeted tests and deterministic smoke coverage

What is not built yet:

- the recommended phase-1 production wedge from the design doc: a self-serve website growth audit plus recurring monitor
- a production KPI dashboard and live reply / meeting workflow
- checkout, billing webhooks, provisioning, and fulfillment reporting

For the current implementation state and next steps, use [docs/NON_TRADING_STATUS.md](docs/NON_TRADING_STATUS.md).

## Repo Tour

| Path | Purpose |
|---|---|
| `bot/` | live trading loop, signal wiring, structural-arb scanners, runtime decisions |
| `execution/` | multi-leg order orchestration and rollback rules |
| `strategies/` + `signals/` | strategy-specific logic and shared signal helpers |
| `src/`, `backtest/`, `simulator/` | edge-discovery and validation pipeline |
| `hub/`, `data_layer/`, `orchestration/` | APIs, persistence, flywheel/control-plane plumbing |
| `nontrading/` | non-trading revenue automation, Phase 0 CRM/approval/telemetry foundations, and digital-product discovery |
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
| [docs/ELASTIC_INTEGRATION.md](docs/ELASTIC_INTEGRATION.md) | master Elastic Stack integration guide |
| [docs/REPLIT_BUILD_GUIDE.md](docs/REPLIT_BUILD_GUIDE.md) | Replit deployment path for the observability stack |
| [docs/ELASTIC_LESSONS_LEARNED.md](docs/ELASTIC_LESSONS_LEARNED.md) | public log of what the Elastic layer actually teaches us |
| [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) | how to split work between Codex and Claude Code safely |
| [docs/REPO_MAP.md](docs/REPO_MAP.md) | canonical monorepo map and edit boundaries |
| [nontrading/README.md](nontrading/README.md) | non-trading developer entrypoint |
| [docs/NON_TRADING_STATUS.md](docs/NON_TRADING_STATUS.md) | current implementation status of the non-trading lane |
| [docs/NON_TRADING_EARNING_AGENT_DESIGN.md](docs/NON_TRADING_EARNING_AGENT_DESIGN.md) | non-trading design and launch model |
| [docs/NON_TRADING_ALLOCATOR_SPEC.md](docs/NON_TRADING_ALLOCATOR_SPEC.md) | shared trading/non-trading allocation logic |
| [polymarket-bot/README.md](polymarket-bot/README.md) | standalone trading bot subproject guide |
| [docs/api/README.md](docs/api/README.md) | API surfaces and OpenAPI generation |
| [research/dispatches/README.md](research/dispatches/README.md) | dispatch system for parallel research and implementation |
| [docs/website/autonomous-market-operators.md](docs/website/autonomous-market-operators.md) | long-term vision for cross-market autonomy and neutral capital allocation |
| [research/what_doesnt_work_diary_v1.md](research/what_doesnt_work_diary_v1.md) | failure diary and dead-lane evidence |

## Mission

**20% of all net trading profits go to veteran suicide prevention.**

- [Veterans Crisis Line](https://www.veteranscrisisline.net/)
- [Stop Soldier Suicide](https://stopsoldiersuicide.org/)
- [22Until None](https://www.22untilnone.org/)

## Contributing

The repo is open because scrutiny is useful. If you contribute:

- be explicit about whether something is live, paper, backtest, non-trading research, or ops
- bring tests or evidence when behavior changes
- do not leak secrets, wallets, or private operational settings
- prefer a clean failure over a vague success claim

Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and disclosure expectations.

## License

MIT.
