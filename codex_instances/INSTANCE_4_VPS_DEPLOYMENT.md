# Execute Instance #4 — AWS VPS Deployment & Infrastructure

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09)

- VPS: Dublin AWS Lightsail eu-west-1, IP: 52.208.155.0
- SSH: `ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0`
- Bot path on VPS: `/home/ubuntu/polymarket-trading-bot/`
- Service: `jj-live.service` — last known `active` (drift, 0 trades in 298 cycles)
- Dashboard sidecar: NOT YET DEPLOYED (new `jj-dashboard.service` planned)
- Local git HEAD: `cde466f` (7 cleanup commits this session)
- Key changes to deploy: env-var threshold configurability, doc reorg, Elastic stack, new tests
- Required env vars: ANTHROPIC_API_KEY, POLYMARKET_API_KEY, POLYMARKET_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY, PAPER_TRADING
- New env vars available: JJ_YES_THRESHOLD, JJ_NO_THRESHOLD, JJ_MIN_CATEGORY_PRIORITY, JJ_CAT_PRIORITY_*

---

## OBJECTIVE

Push all committed code to the Dublin VPS. Verify runtime health. Prepare for threshold-tuned restart. DO NOT restart the live service unless it is already running — restarting a stopped service that trades real money is a human escalation.

## YOU OWN

`deploy/`, `config/`, `.github/workflows/`, VPS operations, `infra/jj-dashboard.service`, `reports/`

## DO NOT TOUCH

`docs/`, `research/`, website files, `CLAUDE.md`, `COMMAND_NODE.md`

## STEPS

1. Read `CLAUDE.md` "Current State" for current VPS status and deployment config.

2. Verify local repo is clean:
   ```bash
   git status
   ```

3. Run the full test suite locally — do NOT deploy if tests fail:
   ```bash
   python3 -m pytest tests/ -x -q --tb=short
   ```

4. Push to GitHub:
   ```bash
   git push origin main
   ```

5. SSH to Dublin VPS:
   ```bash
   ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0
   ```

6. On VPS — pull latest code:
   ```bash
   cd /home/ubuntu/polymarket-trading-bot/
   git pull origin main
   git log --oneline -5
   ```

7. Verify HEAD matches local:
   ```bash
   git rev-parse HEAD  # Should match local cde466f or later
   ```

8. Check `.env` on VPS for all required keys (DO NOT create or modify — just report):
   ```bash
   grep -c "ANTHROPIC_API_KEY" .env
   grep -c "POLYMARKET_API_KEY" .env
   grep -c "POLYMARKET_SECRET" .env
   grep -c "POLYMARKET_PASSPHRASE" .env
   grep -c "POLYMARKET_PRIVATE_KEY" .env
   grep "PAPER_TRADING" .env
   ```
   Flag any missing keys for human action.

9. Check if new threshold env vars are set:
   ```bash
   grep "JJ_YES_THRESHOLD\|JJ_NO_THRESHOLD\|JJ_MIN_CATEGORY" .env || echo "Threshold env vars not yet configured — using defaults"
   ```

10. Verify Python environment:
    ```bash
    python3 -c "from bot.jj_live import TradingBot; print('import OK')"
    ```

11. Check current service state:
    ```bash
    sudo systemctl status jj-live.service
    ```

12. If service is RUNNING: it will pick up code changes on next restart. Note the service state in handoff.
    If service is STOPPED: DO NOT restart. Flag as "restart-recommended-with-aggressive-thresholds" in handoff. This is a human escalation (spending real money).

13. Check systemd service file is current:
    ```bash
    cat /etc/systemd/system/jj-live.service
    ```

14. Verify logging works:
    ```bash
    sudo journalctl -u jj-live.service --no-pager -n 20
    ```

15. Write handoff to `reports/deploy_<timestamp>.json`:
    ```json
    {
      "timestamp": "<ISO>",
      "vps_sha": "<git rev-parse HEAD on VPS>",
      "repo_sha": "<git rev-parse HEAD local>",
      "sha_match": true|false,
      "service_status": "active|inactive|failed",
      "env_keys_present": ["ANTHROPIC_API_KEY", ...],
      "env_keys_missing": [],
      "threshold_env_vars_configured": true|false,
      "paper_trading": "true|false",
      "restart_recommended": true|false,
      "restart_reason": "...",
      "recommended_env_additions": [
        "JJ_YES_THRESHOLD=0.08",
        "JJ_NO_THRESHOLD=0.03",
        "JJ_MIN_CATEGORY_PRIORITY=0"
      ]
    }
    ```

## ESCALATION NOTE

Per CLAUDE.md rules, restarting a stopped service that trades real money requires human approval. If the service is stopped, this instance prepares the restart command but does NOT execute it. The handoff artifact tells John exactly what to run:
```bash
# Add to VPS .env:
echo 'JJ_YES_THRESHOLD=0.08' >> .env
echo 'JJ_NO_THRESHOLD=0.03' >> .env
echo 'JJ_MIN_CATEGORY_PRIORITY=0' >> .env
# Then restart:
sudo systemctl restart jj-live.service
```

## VERIFICATION

- VPS git SHA matches local HEAD
- `systemctl status jj-live.service` returns expected state
- All required env keys present
- Python import succeeds on VPS

## HANDOFF

```
INSTANCE #4 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
