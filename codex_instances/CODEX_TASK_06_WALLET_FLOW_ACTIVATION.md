# CODEX TASK 06: Wallet Flow Signal Activation

## MACHINE TRUTH (2026-03-09)
- Wallet flow detector: 80 scored wallets, fast_flow_restart_ready=true
- VPS log: "No smart wallet scores found. Run --build-scores first."
- wallet_scores.db exists locally but may not be on VPS
- With crypto unlocked, wallet flow should now have markets to signal on
- bot/wallet_flow_detector.py is the module

## TASK
1. Read `bot/wallet_flow_detector.py` — understand score building and signal generation
2. Identify why VPS shows "No smart wallet scores found":
   - Check if wallet_scores.db needs to exist at a specific path
   - Check if --build-scores is a CLI flag or an initialization step
   - Check if scores are built from historical CLOB data or from a pre-seeded file
3. Fix the initialization:
   - If scores need to be pre-built, add an initialization step to jj_live.py startup
   - If scores need a data file deployed, add it to deploy.sh CONFIG_FILES
   - If scores build over time from CLOB observations, ensure the accumulation logic runs
4. Add wallet flow scores to deploy.sh:
   - If `data/wallet_scores.db` exists locally, include it in the deploy manifest
   - Or: add a `--build-scores` initialization flag to jj_live.py startup sequence
5. Write a test that verifies wallet flow initialization succeeds when database is empty

## FILES
- `bot/wallet_flow_detector.py` (READ, possibly MODIFY)
- `bot/jj_live.py` (MODIFY — add wallet score initialization if needed)
- `scripts/deploy.sh` (MODIFY — add wallet_scores.db to deploy manifest)
- `tests/test_wallet_flow_init.py` (CREATE)

## CONSTRAINTS
- Wallet flow must gracefully degrade if no scored wallets (current behavior OK)
- Score building should happen automatically, not require manual intervention
- Do NOT modify wallet scoring algorithm — only fix deployment/initialization
- `make test` must pass

## SUCCESS CRITERIA
- After deploy, wallet flow detector initializes without "No smart wallet scores" warning
- Scores either deploy from local DB or build automatically from CLOB data
- Wallet flow signals appear in logs within 30 minutes of service restart
- `make test` passes
