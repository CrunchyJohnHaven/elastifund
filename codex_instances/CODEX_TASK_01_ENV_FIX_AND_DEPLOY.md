# CODEX TASK 01: Build the `.env` Cleanup Helper

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Path ownership for this task: `scripts/clean_env_for_profile.sh` and any new focused test file
- Do **not** edit `scripts/deploy.sh` here. Task 07 owns deploy-script integration.

## Machine Truth (March 9, 2026)
- `reports/deploy_20260309T013604Z.json` showed the remote VPS `.env` exposing only `PAPER_TRADING=false`; `JJ_RUNTIME_PROFILE` was absent.
- `config/runtime_profile.py` uses `OVERRIDE_SPECS`, so stray `JJ_*` and related env keys can silently override the checked-in runtime profiles.
- `scripts/deploy.sh` already syncs runtime profile JSON files, but there is no checked-in helper that sanitizes a remote `.env` for profile-based launches.

## Goal
Create a reusable shell helper that strips runtime overrides from an existing `.env`, preserves secrets, and appends a single `JJ_RUNTIME_PROFILE=<profile>` selector.

## Required Work
1. Create `scripts/clean_env_for_profile.sh`.
2. Default the profile argument to `live_aggressive`; allow an explicit profile name as `$1`.
3. Back up the input `.env` to `.env.backup.<timestamp>` before rewriting it.
4. Preserve secrets and deploy identity keys such as `KEY`, `SECRET`, `TOKEN`, `PASSPHRASE`, `PK`, `ADDRESS`, `TELEGRAM`, `API_KEY`, `PRIVATE`, `FUNDER`, `SAFE_ADDRESS`, and `PROXY`.
5. Remove runtime override keys such as `JJ_*`, `PAPER_TRADING`, `LIVE_TRADING`, `ENABLE_*`, `CLAUDE_MODEL`, and `ELASTIFUND_AGENT_RUN_MODE`.
6. Append exactly one `JJ_RUNTIME_PROFILE=<profile>` line.
7. Print the cleaned file contents and run a Python verification snippet that loads the selected runtime profile and prints the profile name plus a few key values.

## Deliverables
- `scripts/clean_env_for_profile.sh`
- A focused regression test if you need one, for example `tests/test_clean_env_for_profile.py`

## Verification
- `bash -n scripts/clean_env_for_profile.sh`
- `python -m pytest tests/test_runtime_profile.py`
- If you add a new test file, run it explicitly

## Constraints
- Do not SSH to the VPS.
- Do not modify `config/runtime_profile.py`.
- Do not edit any profile JSON files in `config/runtime_profiles/`.
- Keep the helper POSIX-shell friendly enough to run on the VPS with `bash`.
