# CODEX TASK 06: Validate and Finish Wallet-Flow Bootstrap on Startup

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Preferred path ownership: `bot/wallet_flow_detector.py`, `tests/test_wallet_flow_detector.py`, `tests/test_wallet_flow_init.py`
- Avoid `scripts/deploy.sh` here. Task 07 owns deploy-script changes.

## Machine Truth (March 9, 2026)
- `reports/wallet_flow_bootstrap_20260309T002535Z.json` shows the local bootstrap artifacts are ready: `80` scored wallets with fresh `data/smart_wallets.json` and `data/wallet_scores.db`.
- `JJLive` now has `_wallet_flow_bootstrap_status()` and `_maybe_initialize_wallet_flow_bootstrap()`, and `bot/wallet_flow_detector.py` already exposes `ensure_bootstrap_artifacts(...)`.
- `tests/test_wallet_flow_init.py` already exists and covers part of this flow.
- The earlier VPS failure was operational: the remote runtime did not have usable wallet-flow bootstrap artifacts and logged `No smart wallet scores found`.

## Goal
Treat this as a validate-and-harden task, not a blank-slate implementation. Prove the startup bootstrap path works, and patch only the remaining gaps if you find them.

## Required Work
1. Audit the existing startup path:
   - `bot/wallet_flow_detector.py`
   - `bot/jj_live.py` wallet-flow bootstrap hooks
   - `tests/test_wallet_flow_init.py`
2. If the current implementation is sufficient, keep code changes minimal and strengthen tests only where evidence is missing.
3. If a real gap remains, fix it in the wallet-flow bootstrap path without changing the scoring algorithm.
4. Cover at least these cases in tests:
   - bootstrap artifacts already present
   - database exists but JSON needs regeneration
   - rebuild attempt fails but the bot degrades gracefully
   - startup does not require a human to run `--build-scores` manually

## Deliverables
- Minimal wallet-flow bootstrap hardening, only if needed
- Updated tests proving the startup path is deterministic

## Verification
- `python -m pytest tests/test_wallet_flow_detector.py tests/test_wallet_flow_init.py`

## Constraints
- Do not change wallet-scoring thresholds or the scoring formula.
- Do not edit `scripts/deploy.sh` in this task.
- If you conclude the startup path is already correct, say so in code comments/tests rather than forcing a gratuitous refactor.
