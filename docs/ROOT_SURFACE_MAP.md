# Root Surface Map

Machine-first classification of root docs and top-level directories.

Last updated: 2026-03-11

## Root Markdown Classification

### Canonical

| Path | Role |
|---|---|
| `README.md` | Public overview and onboarding entrypoint |
| `AGENTS.md` | Machine-first workflow contract |
| `COMMAND_NODE.md` | Operator packet |
| `PROJECT_INSTRUCTIONS.md` | Active policy and runtime context |
| `CONTRIBUTING.md` | Contributor setup and PR rules |
| `REPLIT_NEXT_BUILD.md` | Website build contract |
| `SECURITY.md` | Security reporting policy |
| `SUPPORT.md` | User support and troubleshooting path |
| `DCO.md` | DCO sign-off contract |
| `CLAUDE.md` | Claude-specific behavior contract |

### Compatibility Pointers

These files are root shims only. Edit canonical policy content in `docs/numbered/`.

- `00_MISSION_AND_PRINCIPLES.md`
- `01_EXECUTIVE_SUMMARY.md`
- `02_ARCHITECTURE.md`
- `03_METRICS_AND_LEADERBOARDS.md`
- `04_TRADING_WORKERS.md`
- `05_NON_TRADING_WORKERS.md`
- `06_EXPERIMENT_DIARY.md`
- `07_FORECASTS_AND_CHECKPOINTS.md`
- `08_PROMPT_LIBRARY.md`
- `09_GOVERNANCE_AND_SAFETY.md`
- `10_OPERATIONS_RUNBOOK.md`
- `11_PUBLIC_MESSAGING.md`
- `12_MANAGED_SERVICE_BOUNDARY.md`

### Compatibility Pointers (Archived Canonical Content)

| Path | Canonical archived destination |
|---|---|
| `CODEX_DISPATCH.md` | `docs/ops/_archive/root_planning/CODEX_DISPATCH.md` |
| `CODEX_MASTER_PLAN.md` | `docs/ops/_archive/root_planning/CODEX_MASTER_PLAN.md` |
| `DEPLOY_MAKER_VELOCITY.md` | `docs/ops/_archive/root_planning/deploy_maker_velocity_2026-03-09.md` |
| `DEPLOY_NOW.md` | `docs/ops/_archive/root_planning/deploy_now_2026-03-09.md` |
| `FAST_TRADE_EDGE_ANALYSIS.md` | `docs/strategy/history/fast_trade_edge_analysis_2026-03-09.md` |

## Top-Level Directory Classification

| Directory | Type | Entrypoint | Notes |
|---|---|---|---|
| `agent/` | code-bearing | `agent/README.md` | shared abstractions/templates |
| `archive/` | historical | `archive/README.md` | provenance only, non-canonical |
| `build/` | static content route | `build/README.md` | hidden onboarding and internal build packet |
| `codex_instances/` | historical coordination | `codex_instances/README.md` | multi-instance dispatch artifacts |
| `config/` | code-bearing config | `config/README.md` | runtime profile contracts |
| `data/` | runtime/generated artifacts | `data/README.md` | non-canonical data/cache surface |
| `diary/` | static content route | `diary/README.md` | published diary page assets |
| `docs/` | canonical docs | `docs/README.md` | durable operator/contributor guidance |
| `edge-backlog/` | code-bearing research package | `edge-backlog/README.md` | ranked edge backlog package |
| `kalshi/` | code-bearing strategy lane | `kalshi/README.md` | exchange-specific logic |
| `logs/` | runtime/generated artifacts | `logs/README.md` | ephemeral process logs |
| `shared/` | code-bearing shared library | `shared/README.md` | reusable cross-lane helpers |
