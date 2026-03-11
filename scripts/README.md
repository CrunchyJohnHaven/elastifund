# Scripts Index

_Generated from `scripts/scripts_catalog.json` via `python3 scripts/render_scripts_index.py --write`._

Canonical command path rule:

1. Prefer `make <target>` when available.
2. Use `python3 scripts/<tool>.py` (or `bash scripts/<tool>.sh`) only when no Make target exists.
3. Prefer one command per workflow and treat legacy wrappers as compatibility shims.

## Onboarding And Environment

| Workflow | Canonical command | Script entrypoint |
|---|---|---|
| Setup diagnostics | `make doctor` | `python3 scripts/doctor.py` |
| Bootstrap `.env` + runtime defaults | `make onboard` | `python3 scripts/elastifund_setup.py --non-interactive` |
| Quick local start | `make quickstart` | `python3 scripts/quickstart.py` |
| Preflight check | `make preflight` | `python3 scripts/elastifund_setup.py --check` |

## Verification And Hygiene

| Workflow | Canonical command | Script entrypoint |
|---|---|---|
| Repo hygiene gate | `make hygiene` | `python3 scripts/check_repo_hygiene.py` + `python3 scripts/check_docs_indexes.py` + `python3 scripts/check_static_routes.py` + `python3 scripts/check_shell_help.py` + `python3 scripts/render_scripts_index.py --check` + `python3 scripts/render_deprecation_candidates.py --check` |
| Root regression matrix | `make test` | `python3 scripts/run_root_tests.py` |
| Full verify path | `make verify` | `make hygiene && make test && make test-polymarket` |
| Non-trading-only tests | `make test-nontrading` | `python3 -m pytest nontrading/tests -q` |
| Non-trading smoke | `make smoke-nontrading` | `python3 scripts/nontrading_smoke.py` |
| Public messaging scan | `make lint-messaging` | `python3 scripts/lint_messaging.py` |

## Deploy, Remote Ops, And Runtime Control

| Workflow | Canonical command | Notes |
|---|---|---|
| Safe release manifest + deploy flow | `python3 scripts/deploy_release_bundle.py --help` | Manifest-checked deploy bundle path |
| Direct VPS sync deploy | `bash scripts/deploy.sh --help` | Compatibility deploy wrapper used by multiple runbooks |
| Mac↔VPS bridge cycle | `bash scripts/bridge.sh --help` | Pull-before-push remote cycle automation |
| BTC5 remote status check | `bash scripts/btc5_status.sh --help` | Reads target from `.env`/env unless host arg supplied |
| WebSocket-only deploy | `bash scripts/deploy_ws.sh --help` | Scoped jj-ws deploy lane |
| BTC5 service launcher | `bash scripts/run_btc5_service.sh --help` | Used by BTC5 service units |
| Runtime mode/profile edits | `python3 scripts/runtime_controls.py --help` | Profile/override control |
| Remote cycle status artifact | `python3 scripts/write_remote_cycle_status.py --help` | Refreshes remote cycle status contract |

## Research And Lane Automation

- `run_*` scripts: lane dispatches and one-shot operators (cross-asset, audits, collectors, autoresearch).
- `render_*` scripts: artifact/report rendering only.
- `build_*` scripts: gold sets and benchmark fixtures.
- `generate_*` scripts: report/brief generation.
- BTC5 lab surface: `run_btc5_autoresearch_cycle.py`, `run_btc5_autoresearch_loop.py`, `btc5_hypothesis_lab.py`, `btc5_regime_policy_lab.py`, `render_btc5_arr_progress.py`, `render_btc5_hypothesis_frontier.py`.

## Shell Wrapper Notes

- `scripts/deploy.sh` and `scripts/deploy_release_bundle.py` are both active. The Python bundle path is the manifest-safe deploy lane; `deploy.sh` remains an explicit compatibility wrapper for existing VPS workflows.
- `scripts/deploy_ws.sh` is a scoped WebSocket deployment utility, not a replacement for full deploy.
- `scripts/vps_setup.sh` is a one-shot bootstrap helper for manual VPS bring-up; treat it as manual-only and non-canonical for daily operations.
- Cron installer wrappers (`install_bridge_cron.sh`, `install_jj_health_cron.sh`) are operational helpers and should expose `--help`.
