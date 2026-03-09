# CODEX TASK 01: Create .env Cleanup Script for VPS Deploy

## MACHINE TRUTH (2026-03-09)
- VPS is NOT a git checkout — deployed via scp (scripts/deploy.sh)
- .env on VPS has explicit JJ_* vars overriding runtime profile
- Result: paper_aggressive profile loads but ALL values trampled by .env overrides
- Logs show: YES=15%/NO=5% (should be 8%/3%), position=$0.50 (should be $5), paper=False
- OVERRIDE_SPECS in config/runtime_profile.py lines 213-310 lists every overridable env var

## TASK
Create `scripts/clean_env_for_profile.sh` that:
1. Takes optional argument: profile name (default: `live_aggressive`)
2. Backs up `.env` to `.env.backup.<timestamp>`
3. Reads the current `.env` line by line
4. KEEPS lines containing: KEY, SECRET, TOKEN, PASSPHRASE, PK, ADDRESS, TELEGRAM, API_KEY, PRIVATE, FUNDER, SAFE_ADDRESS, PROXY
5. REMOVES lines starting with: JJ_, PAPER_TRADING, ENABLE_, CLAUDE_MODEL
6. Appends `JJ_RUNTIME_PROFILE=<profile_name>`
7. Prints the cleaned .env for verification
8. Runs a python verification: loads the profile and prints key values

Also update `scripts/deploy.sh`:
- After syncing files, call clean_env_for_profile.sh on VPS if `--clean-env` flag is passed
- Add a `--profile` flag to specify which profile (default: live_aggressive)

## FILES
- `scripts/clean_env_for_profile.sh` (CREATE)
- `scripts/deploy.sh` (MODIFY — add --clean-env and --profile flags)

## TESTS
- Run `make test` — must pass
- Run `bash -n scripts/clean_env_for_profile.sh` — syntax check
- Run `bash -n scripts/deploy.sh` — syntax check

## DO NOT
- SSH to VPS
- Modify runtime_profile.py loading logic
- Change any profile JSON files
