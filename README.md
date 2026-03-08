# Elastifund

**Open-source infrastructure for running an agentic prediction-market research and trading lab.**

Elastifund is not a single bot. It is a working monorepo for:

- live and paper trading on prediction markets
- systematic edge discovery and kill-rule validation
- shared observability through Elastic
- documentation, research dispatching, and public postmortems

The repo is built to be usable by humans and by coding agents. If you want to fork it, boot it, and start making progress quickly, the fastest paths are documented below.

**Website:** [elastifund.io](https://elastifund.io)

## Choose Your Path

| I want to... | Start here |
|---|---|
| Boot the repo with the least friction | [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md) |
| Use Codex and Claude Code in parallel | [AGENTS.md](AGENTS.md) + [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) |
| Understand the monorepo layout before editing | [docs/REPO_MAP.md](docs/REPO_MAP.md) |
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

That path is designed for first-time users. It prepares `.env`, writes the runtime manifest, and starts the full local coordination stack if Docker is installed.

If you want to prepare the repo without starting Docker yet:

```bash
python3 scripts/quickstart.py --prepare-only
```

If you want the full developer verification pass as well:

```bash
python3 -m venv .venv
source .venv/bin/activate
make bootstrap
make verify
```

## Verified On March 8, 2026

These commands were run successfully in this repo state:

- `python3 scripts/doctor.py`
- `python3 scripts/quickstart.py --prepare-only`
- `make hygiene`
- `make test`
- `make test-polymarket`

The non-Docker path was verified directly. Docker still requires Docker Desktop or Docker Engine on the machine running the stack.

## Optimized For Codex And Claude Code

This repo now has a small canonical entrypoint set for LLM-driven work:

1. [AGENTS.md](AGENTS.md) for commands, guardrails, and safe task routing
2. [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) for Codex/Claude split patterns
3. [docs/REPO_MAP.md](docs/REPO_MAP.md) for directory ownership and edit boundaries
4. [ProjectInstructions.md](ProjectInstructions.md) for the current operating context
5. [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and PR rules

The intent is simple: an agent should be able to enter the repo, find the right lane, run the right checks, and avoid trampling unrelated work.

## What This Repo Is

Elastifund is a public research engine for prediction-market trading. It tries to answer three questions honestly:

1. Where do LLMs actually help on prediction markets?
2. Which strategies survive realistic costs, sparse signals, and execution constraints?
3. How do you run a multi-agent trading/research stack without hiding the failures?

That means the repo contains both implementation code and the evidence trail behind it. The failures matter as much as the wins.

## Long-Term Vision

Prediction markets are phase one, not the terminal state. The longer-term target is an autonomous market operator that can:

- compare opportunities across a defined eligible universe, including equities, without hard-coded favoritism toward one venue
- decide when a new market is worth entering
- build the data, execution, and settlement adapter required to trade it
- keep new lanes in paper or shadow mode until they survive evidence-based promotion gates

The cautionary precedent is Enron: rapid internal market creation was powerful, but opaque risk, leverage, and instruments the company did not understand were fatal. Elastifund wants the upside of autonomous market discovery without the "trade it before you can explain it" failure mode. The working thesis lives in [docs/website/autonomous-market-operators.md](docs/website/autonomous-market-operators.md).

## Current Snapshot

| Area | Current state |
|---|---|
| Capital tracked in docs | `$347.51` total (`$247.51` Polymarket + `$100` Kalshi) |
| Strategy catalog | `131` tracked (`7` deployed, `8` building, `10` rejected, `8` pre-rejected, `98` pipeline) |
| Verified tests | repo-root regression suite plus the standalone `polymarket-bot` suite |
| `bot/` Python modules | `38` |
| Research dispatches | `95` markdown dispatch files |
| Active signal lanes | forecasting, flow/microstructure, structural arb, validation lanes |
| Live validated P&L | still effectively pre-revenue; no inflated claims here |

## What The System Actually Does

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

## Repo Tour

| Path | Purpose |
|---|---|
| `bot/` | live trading loop, signal wiring, structural-arb scanners, runtime decisions |
| `execution/` | multi-leg order orchestration and rollback rules |
| `strategies/` + `signals/` | strategy-specific logic and shared signal helpers |
| `src/`, `backtest/`, `simulator/` | edge-discovery and validation pipeline |
| `hub/`, `data_layer/`, `orchestration/` | APIs, persistence, flywheel/control-plane plumbing |
| `polymarket-bot/` | self-contained trading bot subproject with dashboard and tests |
| `inventory/` | benchmark lane for comparing external systems cleanly |
| `docs/` + `research/` | durable docs, ADRs, prompts, dispatches, and findings |
| `deploy/` | bootstrap scripts and deployment assets |

If you want the deeper map, use [docs/REPO_MAP.md](docs/REPO_MAP.md).

## What We’ve Proven

- **Anti-anchoring helps.** Hiding the market price from the model and asking for an independent estimate produces better-behaved probabilities.
- **Calibration is mandatory.** Raw model confidence is not trustworthy enough on its own; post-hoc correction materially improves the output.
- **Execution quality matters as much as prediction quality.** Thin edges vanish quickly under taker fees, bad fills, or slow routing.
- **Negative results are valuable.** The repo is strongest where it records why a lane died, not where it hand-waves a success story.

## What We Refuse To Fake

- live profitability before it exists
- leaderboard results before clean-room benchmark runs exist
- strategy edges that disappear once fees or sparse signals are modeled
- “multi-agent autonomy” claims that are broader than the code and docs support

## Why Fork This

Forking Elastifund is useful if you want:

- a working prediction-market experimentation base instead of a blank repo
- a monorepo already organized for LLM-only or LLM-heavy development
- a hub-and-spoke collaboration model where multiple forks can point at one shared control plane
- a public record of what failed, not just what looked impressive on a landing page

## Key Documents

| Document | Purpose |
|---|---|
| [docs/FORK_AND_RUN.md](docs/FORK_AND_RUN.md) | easiest bootstrap and host/spoke onboarding flow |
| [AGENTS.md](AGENTS.md) | machine-first entrypoint and core commands |
| [docs/PARALLEL_AGENT_WORKFLOW.md](docs/PARALLEL_AGENT_WORKFLOW.md) | how to split work between Codex and Claude Code safely |
| [docs/REPO_MAP.md](docs/REPO_MAP.md) | canonical monorepo map and edit boundaries |
| [ProjectInstructions.md](ProjectInstructions.md) | current build priorities and operating context |
| [SECURITY.md](SECURITY.md) | vulnerability reporting and disclosure expectations |
| [SUPPORT.md](SUPPORT.md) | where to start when setup or runtime behavior looks wrong |
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

- be explicit about whether something is live, paper, backtest, or research
- bring tests or evidence when behavior changes
- do not leak secrets, wallets, or private operational settings
- prefer a clean failure over a vague success claim

Start with [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT.
