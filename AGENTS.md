# AGENTS.md

Use this as the machine-first entrypoint for coding sessions in the Elastifund monorepo.

## Read In This Order

1. `README.md` for the public overview and the shortest path into the repo
2. `docs/FORK_AND_RUN.md` if the goal is booting or forking the stack
3. `docs/PARALLEL_AGENT_WORKFLOW.md` if Codex and Claude Code will work in parallel
4. `docs/REPO_MAP.md` for path ownership and safe edit boundaries
5. `docs/architecture/README.md` for the canonical proof-carrying runtime map
6. `PROJECT_INSTRUCTIONS.md` for the active operating context
7. `CONTRIBUTING.md` for setup, tests, and PR rules

Open `CLAUDE.md` only when you need the JJ operating model or higher-level process rules.

## Canonical Commands

Run these from the repo root unless a subproject explicitly says otherwise.

```bash
make doctor
make quickstart
make bootstrap
make onboard
make preflight
make hygiene
make test
make verify
make test-nontrading
make smoke-nontrading
make strike-factory-local
python3 scripts/run_local_twin.py
python3 scripts/run_kernel_cycle.py
python3 scripts/run_intelligence_harness.py
make test-polymarket
```

## Parallel Codex / Claude Code Split

Use one owner per path at a time.

| Lane | Best fit | Typical ownership |
|---|---|---|
| Focused implementation, bug fixing, test repair | Codex | `bot/`, `execution/`, `strategies/`, `signals/`, `nontrading/`, isolated code patches |
| Repo reconnaissance, broad synthesis, doc orchestration | Claude Code | `docs/`, `research/`, `deploy/`, cross-cutting summaries, rollout briefs |
| Shared verification | either | `make hygiene`, `make test`, `make test-polymarket` |

If two agents need the same file, stop parallelizing. Path ownership beats merge cleanup.

## Repo Rules

- Use one shared root virtualenv. Do not editable-install `polymarket-bot/` into it.
- Treat `bot/`, `execution/`, `strategies/`, and `infra/` as live-trading-sensitive paths. Behavior changes there need tests and evidence.
- Treat `data/`, `logs/`, and `state/` as runtime artifact directories, not source-of-truth docs.
- For live posture and cycle truth, prefer checked-in contracts (`config/remote_cycle_status.json`, `improvement_velocity.json`) plus `research/edge_backlog_ranked.md`; use `reports/*` artifacts only when they are available from a runtime machine.
- Existing JSON handoff artifacts are the runtime status contract. Do not invent new runtime APIs just to pass state between lanes.
- Keep new durable docs under `docs/` or `research/`, not the repo root, except for the approved numbered governance set `00_MISSION_AND_PRINCIPLES.md` through `12_MANAGED_SERVICE_BOUNDARY.md`.
- Keep the repo root narrow: entrypoints, the approved numbered governance set, public repo standards, and compatibility files only.
- The canonical architecture map lives in `docs/architecture/README.md`; do not mint a second control plane in root docs.
- Keep secrets in `.env` only. Runtime state, credentials, exports, and local scratch files should stay ignored.
- Private investor and legal materials live outside this repo and are out of scope for normal coding sessions.

## Task Routing

- Live trading logic: `bot/`, `execution/`, `strategies/`, `signals/`, `infra/`
- Research pipeline and validation: `src/`, `backtest/`, `simulator/`, `edge-backlog/`
- APIs, persistence, and orchestration: `hub/`, `data_layer/`, `orchestration/`
- Non-trading revenue lanes (JJ-N): `nontrading/`, `inventory/`
- Governance and messaging docs: `00_MISSION_AND_PRINCIPLES.md` through `12_MANAGED_SERVICE_BOUNDARY.md`, `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`
- Vision and strategic docs: `research/elastic_vision_document.md`, `research/platform_vision_document.md`
- Website build guidance: `REPLIT_NEXT_BUILD.md`, `REPLIT_WEBSITE_CURRENT.pdf`, `develop/`, `elastic/`, `leaderboards/`
- Documentation and publishing: `docs/`, `research/`, `README.md`, numbered root docs

## Definition Of Done

- Run the narrowest relevant test target.
- Run `make hygiene` after doc or config changes.
- If you touch root workflow docs, keep `README.md`, `AGENTS.md`, `docs/FORK_AND_RUN.md`, `docs/PARALLEL_AGENT_WORKFLOW.md`, and `docs/REPO_MAP.md` aligned.
