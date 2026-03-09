# CODEX TASK 07: Fix deploy.sh for Complete VPS Deployment

## MACHINE TRUTH (2026-03-09)
- VPS has NO git repo — deployed via scp only (scripts/deploy.sh)
- deploy.sh syncs bot/*.py, config/, polymarket-bot/src/ to VPS
- Missing from deploy manifest: live_aggressive.json, data/wallet_scores.db
- deploy.sh needs --clean-env flag to strip .env overrides on VPS
- deploy.sh needs --profile flag to set JJ_RUNTIME_PROFILE on VPS
- VPS connection: ssh -i $LIGHTSAIL_KEY ubuntu@52.208.155.0
- BOT_DIR on VPS: /home/ubuntu/polymarket-trading-bot
- Systemd PYTHONPATH: /home/ubuntu/polymarket-trading-bot:/home/ubuntu/polymarket-trading-bot/bot:/home/ubuntu/polymarket-trading-bot/polymarket-bot

## TASK
Update `scripts/deploy.sh` to be a complete, one-command deployment:

1. **Add --clean-env flag:**
   When passed, after syncing files:
   ```bash
   ssh $VPS "cd $BOT_DIR && cp .env .env.backup.\$(date +%s) && \
     grep -iE '(KEY|SECRET|TOKEN|PASSPHRASE|PK|ADDRESS|TELEGRAM|PRIVATE|FUNDER|PROXY|API_KEY)' .env > .env.clean && \
     echo 'JJ_RUNTIME_PROFILE=${PROFILE_NAME}' >> .env.clean && \
     mv .env.clean .env"
   ```

2. **Add --profile flag:**
   Default: `live_aggressive`. Sets JJ_RUNTIME_PROFILE in the cleaned .env.

3. **Add all runtime profiles to CONFIG_FILES:**
   Currently missing: live_aggressive.json. Add it. Or better: glob all *.json in config/runtime_profiles/.

4. **Add data file deployment:**
   If `data/wallet_scores.db` exists locally, scp it to VPS.
   If `data/jj_state.json` exists locally and is newer, offer to sync (but DON'T overwrite by default — VPS state is authoritative).

5. **Add post-deploy verification:**
   ```bash
   ssh $VPS "cd $BOT_DIR && source venv/bin/activate && \
     PYTHONPATH=$REMOTE_PYTHONPATH python3 -c \"
       from config.runtime_profile import load_runtime_profile
       p = load_runtime_profile()
       print(f'Profile: {p.profile_name}')
       print(f'YES threshold: {p.signal_thresholds.yes_threshold}')
       print(f'NO threshold: {p.signal_thresholds.no_threshold}')
       print(f'Paper: {p.mode.paper_trading}')
       print(f'Order submission: {p.mode.allow_order_submission}')
       print(f'Execution mode: {p.mode.execution_mode}')
       print(f'Crypto priority: {p.market_filters.category_priorities.get(\"crypto\", \"MISSING\")}')
     \""
   ```

6. **Add --restart flag:**
   When passed, restart jj-live.service after deploy and show last 20 log lines.

## USAGE AFTER FIX
```bash
# Full deploy + clean env + set live_aggressive + restart
./scripts/deploy.sh --clean-env --profile live_aggressive --restart

# Just sync code, don't touch env or restart
./scripts/deploy.sh

# Deploy with paper mode
./scripts/deploy.sh --clean-env --profile paper_aggressive --restart
```

## FILES
- `scripts/deploy.sh` (MODIFY)

## CONSTRAINTS
- Must remain backward compatible (no args = current behavior)
- Must NOT deploy .env, only modify it on VPS via --clean-env
- Must NOT overwrite jj_state.json on VPS (VPS state is authoritative)
- Must handle SSH key at $LIGHTSAIL_KEY or ~/.ssh/lightsail.pem
- `bash -n scripts/deploy.sh` must pass (syntax check)
- `make test` must pass

## SUCCESS CRITERIA
- `./scripts/deploy.sh --clean-env --profile live_aggressive --restart` works end-to-end
- Post-deploy verification shows correct profile values
- Service restarts and logs show new profile active
