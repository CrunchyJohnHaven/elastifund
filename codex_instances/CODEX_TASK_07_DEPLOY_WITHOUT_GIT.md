# CODEX TASK 07: Upgrade `scripts/deploy.sh` for Real VPS-Without-Git Deploys

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Path ownership for this task: `scripts/deploy.sh`, `tests/test_deploy_script.py`
- This task owns deploy-script integration for Tasks 01, 05, and 06.

## Machine Truth (March 9, 2026)
- The VPS deploy target is a file-copy install, not a git checkout.
- `scripts/deploy.sh` currently syncs `bot/*.py`, runtime profile JSON files, and a thin slice of `polymarket-bot/src/`.
- It does **not** support `--clean-env`, `--profile`, or `--restart`.
- It does **not** currently sync wallet-flow bootstrap artifacts such as `data/smart_wallets.json` and `data/wallet_scores.db`.
- It also does not sync the deeper `polymarket-bot/src/core/` files that `src.telegram` depends on.
- `reports/deploy_20260309T013604Z.json` showed three concrete deploy-time problems:
  - remote mode contract absent from `.env`
  - wallet-flow bootstrap missing on the VPS
  - cross-platform/Telegram-adjacent runtime issues visible only after deploy

## Goal
Turn `scripts/deploy.sh` into a complete, backward-compatible one-command deploy for the scp-only VPS.

## Required Work
1. Add shell flag parsing for:
   - `--clean-env`
   - `--profile <name>` with default `live_aggressive`
   - `--restart`
   - keep the existing positional VPS target override working
2. Integrate Task 01’s `scripts/clean_env_for_profile.sh` on the remote host when `--clean-env` is passed.
3. Sync the full runtime-profile contract:
   - prefer globbing `config/runtime_profiles/*.json` over a hardcoded list
4. Sync all runtime files needed for Telegram and health monitoring:
   - at minimum, the `polymarket-bot/src/core/` modules required by `src.telegram`
5. Sync wallet-flow bootstrap artifacts if they exist locally:
   - `data/smart_wallets.json`
   - `data/wallet_scores.db`
6. Never overwrite remote `jj_state.json`.
7. Add post-deploy verification that prints:
   - selected runtime profile
   - YES/NO thresholds
   - execution mode and paper/live flags
   - crypto category priority
   - wallet-flow bootstrap readiness if feasible
8. If `--restart` is passed, restart `jj-live.service` and show recent log lines.

## Deliverables
- Updated `scripts/deploy.sh`
- Updated `tests/test_deploy_script.py`

## Verification
- `bash -n scripts/deploy.sh`
- `python -m pytest tests/test_deploy_script.py`

## Constraints
- Backward compatibility matters: no-arg behavior should stay equivalent to today’s sync-only deploy.
- Do not deploy `.env` from local disk.
- Do not overwrite remote runtime state files like `jj_state.json`.
- Do not SSH manually outside what the deploy script itself does.
