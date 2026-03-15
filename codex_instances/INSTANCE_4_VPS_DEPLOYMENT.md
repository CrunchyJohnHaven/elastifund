# Execute Instance #4 — VPS Deployment & Release Manifest Fix

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- VPS: 52.208.155.0 (AWS Lightsail Dublin, eu-west-1)
- SSH: `ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0`
- Bot path on VPS: `/home/ubuntu/polymarket-trading-bot/`
- Service: `jj-live.service` `active` at `2026-03-09T01:06:09Z`
- Service mode: UNKNOWN — treat as drift. Must confirm paper/shadow/live before any action.
- Cycles: 305 completed, 0 live trades placed
- Deploy dry-run: BLOCKED at `2026-03-09T01:06:52Z` — release manifest expects `config/runtime_profiles/blocked_safe.yaml` but actual file is `config/runtime_profiles/blocked_safe.json`
- Runtime profiles available: `blocked_safe.json`, `shadow_fast_flow.json`, `research_scan.json`
- Runtime profile contract: `docs/ops/runtime_profile_contract.md`
- Wallet-flow: ready (80 scored wallets, fast_flow_restart_ready=true)
- Launch posture: BLOCKED (no closed trades, no deployed capital, A-6/B-1 gates, flywheel hold)
- Tests: 1,278 total verified, all green
- New env vars available: JJ_YES_THRESHOLD, JJ_NO_THRESHOLD, JJ_MIN_CATEGORY_PRIORITY, JJ_CAT_PRIORITY_*
- Required env vars: ANTHROPIC_API_KEY, POLYMARKET_API_KEY, POLYMARKET_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY, PAPER_TRADING

---

## OBJECTIVE

Fix the release manifest path mismatch that blocks deploy dry-runs, confirm the running service mode, prepare the deployment pipeline for the eventual first-trade restart, and push code to VPS. Do NOT enable live trading or deploy with real money routing. Restarting a stopped service that trades real money is a human escalation.

## YOU OWN

`deploy/`, `config/`, `Makefile` (deploy targets only), `reports/deploy_*.json`, `.github/workflows/`

## DO NOT TOUCH

`bot/` (except reading mode/config), `docs/`, `research/`, website files, `CLAUDE.md`, `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`

## STEPS

1. Read `docs/ops/runtime_profile_contract.md` for the profile specification.

2. **Find and fix the manifest path mismatch:**
   ```bash
   grep -rn "blocked_safe.yaml" deploy/ config/ Makefile .github/ 2>/dev/null
   ```
   The actual file is `config/runtime_profiles/blocked_safe.json`. Either:
   - (a) Update the manifest/script to reference `.json` instead of `.yaml`, OR
   - (b) Create a `.yaml` version if the contract requires YAML format
   Choose the option that matches the runtime profile contract.

3. Verify all three runtime profiles are valid:
   ```bash
   for f in config/runtime_profiles/*.json; do
     python3 -m json.tool "$f" > /dev/null && echo "VALID: $f" || echo "INVALID: $f"
   done
   ```

4. Run the deploy dry-run after the fix:
   ```bash
   make deploy-dry-run 2>&1 || python3 deploy/dry_run.py 2>&1 || echo "No deploy script found — check Makefile targets"
   ```

5. Verify local repo is clean and tests pass:
   ```bash
   git status
   python3 -m pytest tests/ -x -q --tb=short
   ```

6. Push to GitHub:
   ```bash
   git push origin main
   ```

7. SSH to Dublin VPS and pull:
   ```bash
   ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0 << 'REMOTE'
   cd /home/ubuntu/polymarket-trading-bot/
   git pull origin main
   git log --oneline -3
   python3 -c "from bot.jj_live import TradingBot; print('import OK')"
   sudo systemctl status jj-live.service --no-pager
   grep "PAPER_TRADING\|LIVE_TRADING\|JJ_RUNTIME_PROFILE" .env 2>/dev/null || echo "Mode env vars not set"
   sudo journalctl -u jj-live.service --no-pager -n 10
   REMOTE
   ```

8. Check if new threshold env vars are set on VPS:
   ```bash
   ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0 \
     "grep 'JJ_YES_THRESHOLD\|JJ_NO_THRESHOLD\|JJ_MIN_CATEGORY' /home/ubuntu/polymarket-trading-bot/.env || echo 'Threshold env vars not yet configured'"
   ```

9. If service is RUNNING: note in handoff. Do NOT restart — it will pick up code on next natural restart.
   If service is STOPPED: DO NOT restart. Prepare the restart command for John.

10. Produce `reports/deploy_<timestamp>.json`:
    ```json
    {
      "timestamp": "<ISO>",
      "instance_version": "2.8.0",
      "manifest_fix": "blocked_safe.yaml → blocked_safe.json (or describe what was done)",
      "dry_run_result": "pass|fail",
      "vps_sha": "<git rev-parse HEAD on VPS>",
      "repo_sha": "<git rev-parse HEAD local>",
      "sha_match": true,
      "service_status": "active|inactive|failed",
      "service_mode_confirmed": "paper|shadow|live|unknown",
      "env_keys_present": ["ANTHROPIC_API_KEY", ...],
      "env_keys_missing": [],
      "threshold_env_vars_configured": false,
      "launch_gates_status": {
        "closed_trades": false,
        "deployed_capital": false,
        "a6_gate": false,
        "b1_gate": false,
        "flywheel_hold": true
      },
      "recommended_action": "confirm-service-mode | add-threshold-env-vars | ready-for-paper-restart"
    }
    ```

## ESCALATION NOTE

Per CLAUDE.md rules, restarting a stopped service that trades real money requires human approval. If the service is stopped, this instance prepares the restart command but does NOT execute it:
```bash
# Add to VPS .env:
echo 'JJ_YES_THRESHOLD=0.08' >> .env
echo 'JJ_NO_THRESHOLD=0.03' >> .env
echo 'JJ_MIN_CATEGORY_PRIORITY=0' >> .env
# Then restart:
sudo systemctl restart jj-live.service
```

## VERIFICATION

```bash
python3 -m pytest tests/ -x -q --tb=short
# Confirm the yaml reference is gone
! grep -r "blocked_safe.yaml" deploy/ config/ Makefile .github/ 2>/dev/null && echo "No stale yaml refs"
# Confirm profiles are valid
for f in config/runtime_profiles/*.json; do python3 -m json.tool "$f" > /dev/null; done && echo "All profiles valid"
```

## HANDOFF

```
INSTANCE #4 HANDOFF
---
Files changed: [list]
Commands run: [list]
Manifest fix: [exact change made]
Service mode: [paper|shadow|live|unknown — what you found]
Dry-run result: [pass|fail + reason]
VPS SHA match: [yes|no]
Launch gates: [which are met, which are not]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
