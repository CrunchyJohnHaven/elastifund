# AGENTS.md

Use this as the machine-first entrypoint for coding sessions in the Elastifund monorepo.

## Read In This Order

1. `README.md` for the public overview and the shortest path into the repo
2. `docs/FORK_AND_RUN.md` if the goal is booting or forking the stack
3. `docs/PARALLEL_AGENT_WORKFLOW.md` if Codex and Claude Code will work in parallel
4. `docs/REPO_MAP.md` for path ownership and safe edit boundaries
5. `PROJECT_INSTRUCTIONS.md` for the active operating context
6. `CONTRIBUTING.md` for setup, tests, and PR rules

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
make test-polymarket
```

## Parallel Codex / Claude Code Split

Use one owner per path at a time.

| Lane | Best fit | Typical ownership |
|---|---|---|
| Focused implementation, bug fixing, test repair | Codex | `bot/`, `execution/`, `strategies/`, `signals/`, isolated code patches |
| Repo reconnaissance, broad synthesis, doc orchestration | Claude Code | `docs/`, `research/`, `deploy/`, cross-cutting summaries, rollout briefs |
| Shared verification | either | `make hygiene`, `make test`, `make test-polymarket` |

If two agents need the same file, stop parallelizing. Path ownership beats merge cleanup.

## Repo Rules

- Use one shared root virtualenv. Do not editable-install `polymarket-bot/` into it.
- Treat `bot/`, `execution/`, `strategies/`, and `infra/` as live-trading-sensitive paths. Behavior changes there need tests and evidence.
- Treat `data/`, `logs/`, `reports/`, and `state/` as runtime artifact directories, not source-of-truth docs.
- Keep new durable docs under `docs/` or `research/`, not the repo root.
- Keep secrets in `.env` only. Runtime state, credentials, exports, and local scratch files should stay ignored.
- Private investor and legal materials live outside this repo and are out of scope for normal coding sessions.

## Task Routing

- Live trading logic: `bot/`, `execution/`, `strategies/`, `signals/`, `infra/`
- Research pipeline and validation: `src/`, `backtest/`, `simulator/`, `edge-backlog/`
- APIs, persistence, and orchestration: `hub/`, `data_layer/`, `orchestration/`
- Non-trading revenue lanes: `nontrading/`, `inventory/`
- Documentation and publishing: `docs/`, `research/`, `README.md`

## Definition Of Done

- Run the narrowest relevant test target.
- Run `make hygiene` after doc or config changes.
- If you touch root workflow docs, keep `README.md`, `AGENTS.md`, `docs/FORK_AND_RUN.md`, `docs/PARALLEL_AGENT_WORKFLOW.md`, and `docs/REPO_MAP.md` aligned.
