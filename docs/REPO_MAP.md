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
| `docs/numbered/00_MISSION_AND_PRINCIPLES.md` → `docs/numbered/12_MANAGED_SERVICE_BOUNDARY.md` | canonical governance, narrative, and public-messaging numbered-doc lane |
| `docs/strategy/edge_discovery_system.md` | research and kill-rule architecture |
| `FAST_TRADE_EDGE_ANALYSIS.md` | latest validation output |

If a new doc overlaps one of the files above or the numbered-doc lane, consolidate instead of creating another source of truth.
The repo root should stay narrow: session entrypoints, public repo standards, and a small number of compatibility files only.
For live status, prefer checked-in runtime contracts (`config/remote_cycle_status.json`, `improvement_velocity.json`) and `research/edge_backlog_ranked.md` over stale prose. Runtime-local artifacts under `reports/` can be used when available, but may be absent in a clean clone.

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
| `nontrading/` | non-trading revenue automation | separate lane from live trading; `nontrading/engines/` holds the five-engine Phase 0 stubs |
| `inventory/` | methodology-first benchmark catalog and evidence | no fake leaderboard claims |
| `polymarket-bot/` | standalone trading bot subproject | own packaging and tests |
| `develop/`, `diary/`, `elastic/`, `leaderboards/`, `manage/`, `roadmap/` | static website route stubs and leaderboard surfaces | keep public messaging aligned with `docs/numbered/11_PUBLIC_MESSAGING.md` and the numbered-doc lane |
| `docs/` | durable docs, ADRs, API notes, onboarding, templates | prefer new docs here |
| `research/` | prompts, dispatches, findings, postmortems | investigative output |
| `deploy/` | deployment and infra artifacts (systemd services for BTC5, JJ-live, shadow lanes, autoresearch) | operator-facing |
| `scripts/` | reusable repo automation (`compare_shadow_vs_live.py` for shadow-vs-BTC5 head-to-head) | add repeatable workflows here |
| `data/`, `logs/`, `reports/`, `state/` | generated runtime artifacts | keep disposable and ignored; treat checked-in contracts (`config/remote_cycle_status.json`, `improvement_velocity.json`) as canonical when `reports/` artifacts are unavailable |

### Wallet Sync

| File | Purpose |
|---|---|
| `bot/wallet_poller.py` | Continuous polling loop that keeps the local trade ledger in sync with the live Polymarket wallet (wallet is authoritative). Supports `--once`, `--continuous`, and `--status` CLI modes. |
| `bot/wallet_reconciliation.py` | Core reconciliation engine — fetches remote positions, patches local SQLite, scores drift. Used by `wallet_poller.py` as a library. |
| `deploy/wallet-poller.service` | systemd unit for the wallet poller daemon on the Dublin VPS. |
| `tests/test_wallet_poller.py` | 17 test cases covering snapshot persistence, poll cycles, error handling, and status reporting. |
| `archive/` | superseded material | not current guidance |

## Numbered Docs

`docs/numbered/` is the canonical numbered operating-manual lane:

- `docs/numbered/00_MISSION_AND_PRINCIPLES.md`
- `docs/numbered/01_EXECUTIVE_SUMMARY.md`
- `docs/numbered/02_ARCHITECTURE.md`
- `docs/numbered/03_METRICS_AND_LEADERBOARDS.md`
- `docs/numbered/04_TRADING_WORKERS.md`
- `docs/numbered/05_NON_TRADING_WORKERS.md`
- `docs/numbered/06_EXPERIMENT_DIARY.md`
- `docs/numbered/07_FORECASTS_AND_CHECKPOINTS.md`
- `docs/numbered/08_PROMPT_LIBRARY.md`
- `docs/numbered/09_GOVERNANCE_AND_SAFETY.md`
- `docs/numbered/10_OPERATIONS_RUNBOOK.md`
- `docs/numbered/11_PUBLIC_MESSAGING.md`
- `docs/numbered/12_MANAGED_SERVICE_BOUNDARY.md`

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
| `python3 scripts/lint_messaging.py` | scan canonical public surfaces for forbidden messaging terms |
| `make test` | run the root regression suite |
| `make verify` | run hygiene plus both major Python test surfaces |
| `make test-nontrading` | run only the `nontrading/` suite |
| `make smoke-nontrading` | run the deterministic non-trading smoke check |
| `make test-polymarket` | run the nested `polymarket-bot` suite |
| `make api-specs` | regenerate OpenAPI specs |
| `make clean` | remove caches and Finder/Python noise |

## Layout Rules

- New durable docs belong in `docs/` or `research/`, not the repo root.
- `docs/numbered/` is the canonical numbered-doc lane; if root-level numbered drafts exist, archive or delete them instead of editing two copies.
- Prefer `docs/diary/`, `docs/ops/`, `docs/strategy/`, and `research/` over minting new root folders for writing-heavy workflows.
- New repeated workflows belong in `scripts/`.
- New generated artifacts belong under `reports/`, `logs/`, `data/`, or `state/`.
- Private investor and legal materials are intentionally kept outside the repo; do not reintroduce a `fund/` tree here.
- If you change the workflow surface, update `README.md`, `AGENTS.md`, `docs/FORK_AND_RUN.md`, and `docs/PARALLEL_AGENT_WORKFLOW.md` together.
