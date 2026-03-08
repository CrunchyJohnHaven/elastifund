# Repo Map

This is the canonical map for navigating Elastifund quickly, especially in LLM-driven sessions.

## Canonical Docs

| File | Use it for |
|---|---|
| `README.md` | public overview, quick boot, current positioning |
| `docs/FORK_AND_RUN.md` | easiest fork/bootstrap path |
| `AGENTS.md` | machine-first commands and guardrails |
| `docs/PARALLEL_AGENT_WORKFLOW.md` | Codex/Claude split rules and sync cadence |
| `PROJECT_INSTRUCTIONS.md` | current priorities and operating context |
| `CLAUDE.md` | JJ operating model and process rules |
| `CONTRIBUTING.md` | setup, verification, PR expectations |
| `EDGE_DISCOVERY_SYSTEM.md` | research and kill-rule architecture |
| `FAST_TRADE_EDGE_ANALYSIS.md` | latest validation output |

If a new root doc overlaps one of the files above, consolidate instead of creating another source of truth.

## Directory Map

| Path | Purpose | Notes |
|---|---|---|
| `bot/` | live trading loop, ensembles, scanners, execution routing | highest-risk path; pair changes with tests |
| `execution/` | multi-leg execution contracts and rollback logic | keep maker-only rules explicit |
| `strategies/` | strategy-specific orchestration | promotion needs evidence |
| `signals/` | reusable signal-family helpers | often shared by `bot/` and `strategies/` |
| `infra/` | transport, shared clients, infrastructure primitives | prefer reuse over duplication |
| `src/` | edge-discovery and control-plane research code | research/control lane |
| `backtest/` | historical validation and benchmark data | research lane |
| `simulator/` | fill, sizing, and sensitivity simulation | research lane |
| `edge-backlog/` | ranked strategy backlog package and tests | editable package in root env |
| `data_layer/` | schema, CRUD, migrations, CLI | shared persistence surface |
| `hub/` | API and Elastic-backed coordination layer | shared service boundary |
| `orchestration/` | flywheel/control-plane workflow logic | glue between systems |
| `nontrading/` | non-trading revenue automation | separate lane from live trading |
| `inventory/` | methodology-first benchmark catalog and evidence | no fake leaderboard claims |
| `polymarket-bot/` | standalone trading bot subproject | own packaging and tests |
| `docs/` | durable docs, ADRs, API notes, onboarding, templates | prefer new docs here |
| `research/` | prompts, dispatches, findings, postmortems | investigative output |
| `deploy/` | deployment and infra artifacts | operator-facing |
| `scripts/` | reusable repo automation | add repeatable workflows here |
| `data/`, `logs/`, `reports/`, `state/` | generated runtime artifacts | keep disposable and ignored |
| `archive/` | superseded material | not current guidance |

## Parallel Ownership Map

| Workstream | Primary owner |
|---|---|
| Narrow code implementation and test repair | Codex |
| Repo-wide synthesis, documentation, coordination, and prompts | Claude Code |
| Shared regression and release verification | whichever agent is closing the task |

The hard rule is simple: one owner per file at a time. Split by directory or by deliverable, not by hope.

## Standard Commands

| Command | What it does |
|---|---|
| `make bootstrap` | install root development dependencies |
| `make doctor` | check whether the machine is ready for local setup |
| `make quickstart` | prepare `.env` and start the local Docker stack |
| `make onboard` | generate a working `.env` and runtime manifest for a fresh clone |
| `make preflight` | validate env/runtime prerequisites |
| `make hygiene` | scan for tracked sensitive artifacts and broken canonical-doc references |
| `make test` | run the root regression suite |
| `make verify` | run hygiene plus both major Python test surfaces |
| `make test-polymarket` | run the nested `polymarket-bot` suite |
| `make api-specs` | regenerate OpenAPI specs |
| `make clean` | remove caches and Finder/Python noise |

## Layout Rules

- New durable docs belong in `docs/` or `research/`, not the repo root.
- New repeated workflows belong in `scripts/`.
- New generated artifacts belong under `reports/`, `logs/`, `data/`, or `state/`.
- Private investor and legal materials are intentionally kept outside the repo; do not reintroduce a `fund/` tree here.
- If you change the workflow surface, update `README.md`, `AGENTS.md`, `docs/FORK_AND_RUN.md`, and `docs/PARALLEL_AGENT_WORKFLOW.md` together.
