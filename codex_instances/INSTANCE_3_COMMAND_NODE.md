# Execute Instance #3 — Command Node & Documentation Sync

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- Capital: $347.51 total ($247.51 Polymarket + $100 Kalshi)
- Cycle: 2 — Structural Alpha & Microstructure Defense
- Service: `jj-live.service` active at `2026-03-09T01:06:09Z`, 0 trades in 305 cycles — drift
- Pipeline: REJECT ALL across 74 observed markets
- Tests: 1,278 total verified (871+22 root, 374 polymarket, 11 non-trading); `make hygiene` passed
- Dispatches: 11 DISPATCH_* work-orders; 95 markdown files in `research/dispatches/`
- Strategies: 131 tracked (7/6/2/10/8/1/97)
- Edge thresholds: env-var configurable (committed)
- Wallet-flow: ready (80 scored wallets, fast_flow_restart_ready=true)
- A-6: 0 executable below 0.95 (563 allowed, 57 qualified) | B-1: 0 deterministic pairs
- Deploy blocker: release manifest expects `config/runtime_profiles/blocked_safe.yaml` but file is `.json`
- COMMAND_NODE.md: currently at v2.8.0
- PROJECT_INSTRUCTIONS.md: currently at v3.8.0
- Vision integration: completed March 9 — product definition, six-layer architecture, five-engine model, numbered docs, messaging system, JJ-N rollout, opportunity scoring

---

## OBJECTIVE

Reconcile all canonical admin files against the latest machine truth from all other instances' handoff artifacts. Bump COMMAND_NODE.md to v2.9.0. This instance is the single source of truth writer — every other instance reads what you produce.

## YOU OWN

`COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, `CLAUDE.md` (Current State section only), `docs/`, `research/edge_backlog_ranked.md`, `README.md`, `AGENTS.md`, `docs/REPO_MAP.md`

## DO NOT TOUCH

`bot/`, `execution/`, `strategies/`, `signals/`, `src/`, website files, `index.html`

## STEPS

1. Read `CLAUDE.md` "Current State" section as ground truth baseline.

2. Read every `reports/*.json` file modified in the last 24 hours:
   ```bash
   find reports/ -name "*.json" -mtime -1 -ls
   ```

3. Read `FAST_TRADE_EDGE_ANALYSIS.md` for latest pipeline outputs.

4. Count passing tests across all surfaces:
   ```bash
   python3 -m pytest tests/ -q --tb=no 2>&1 | tail -3
   cd tests/polymarket && python3 -m pytest -q --tb=no 2>&1 | tail -3; cd ../..
   cd tests/nontrading && python3 -m pytest -q --tb=no 2>&1 | tail -3; cd ../..
   ```

5. Count dispatches:
   ```bash
   ls research/dispatches/ | wc -l
   find research/dispatches/ -name "DISPATCH_*" | wc -l
   ```

6. Count strategies by status in `research/edge_backlog_ranked.md`.

7. Read handoff artifacts from other instances if they exist:
   ```bash
   ls reports/edge_scan_*.json reports/pipeline_refresh_*.json reports/deploy_*.json 2>/dev/null
   ```

8. Update `COMMAND_NODE.md` to v2.9.0:
   - Refresh all machine truth numbers from steps 2-7
   - Update version log with change summary
   - Update "Current status" paragraph
   - Update strategy status table if counts changed
   - Update verification status with fresh test counts
   - Update dispatch inventory
   - Update "Next operator action" based on latest state
   - Ensure vision integration sections remain intact (product definition, architectures, governance, messaging)

9. Update `PROJECT_INSTRUCTIONS.md`:
   - Section 1 status paragraph: update cycle/test/trade counts
   - Section 2A machine snapshot table: update all metrics
   - Handoff list: add any new report artifacts

10. Update `CLAUDE.md` "Current State":
    - Date: 2026-03-09
    - Test counts: update to fresh numbers
    - Cycle count: update
    - Any new findings from other instances
    - Next action: update based on current state

11. Update `README.md` scorecard if headline numbers changed.

12. Update `docs/REPO_MAP.md` if any new directories or key files were created by other instances.

13. Update `AGENTS.md` with any new commands or workflow changes.

## VERIFICATION

```bash
python3 -m pytest tests/ -x -q --tb=short
# Verify cross-document consistency
python3 -c "
import re
for f in ['COMMAND_NODE.md', 'PROJECT_INSTRUCTIONS.md', 'CLAUDE.md']:
    with open(f) as fh: c = fh.read()
    assert '2.8.0' in c or '2.9.0' in c or '3.8.0' in c or '3.9.0' in c, f'{f}: version stale'
print('Version check passed')
"
```

## HANDOFF

```
INSTANCE #3 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after for each metric]
Version bumps: [list]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
