# Execute Instance #3 — Command Node & Documentation Sync

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09)

- Capital: $347.51 total ($247.51 Polymarket + $100 Kalshi)
- Cycle: 2 — Machine Truth Reconciliation
- Service: `jj-live.service` running but 0 trades in 298 cycles — drift
- Pipeline: REJECT ALL
- Tests: 353 local; 1,256 total verified
- Dispatches: 95 in `research/dispatches/`
- Strategies: 131 tracked (7/6/2/10/8/1/97)
- Edge thresholds: Now env-var configurable (committed this session)
- Recent commits: 7 cleanup commits landed (threshold config, doc reorg, Elastic stack, tests)
- New directories: `research/deep_research_packets/`, `nontrading/`, `infra/`, `codex_instances/`
- A-6: 0 executable below 0.95 | B-1: 0 deterministic pairs

---

## OBJECTIVE

Update `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, `CLAUDE.md`, and all canonical docs to reflect the current cycle's state. This is the source of truth every other instance reads.

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

4. Count passing tests:
   ```bash
   python3 -m pytest tests/ -q --tb=no 2>&1 | tail -3
   ```

5. Count dispatches:
   ```bash
   ls research/dispatches/ | wc -l
   ```

6. Count strategies by status in `research/edge_backlog_ranked.md`.

7. Update `COMMAND_NODE.md`:
   - Current capital: $347.51
   - Current cycle: 2
   - Strategy counts: 7 deployed, 6 building, 2 structural, 10 rejected, 8 pre-rejected, 1 re-evaluating, 97 research = 131 total
   - Test counts: update with fresh numbers from step 4
   - Dispatch counts: update with fresh number from step 5
   - Service status: running (drift, 0 trades)
   - NEW: Edge thresholds now env-var configurable
   - NEW: 7 cleanup commits this session
   - NEW: `codex_instances/` directory with 6 parallel dispatch files
   - Last action: repo cleanup, threshold configurability, Codex dispatch generation
   - Next action: lower thresholds on VPS, monitor for first trade

8. Update `PROJECT_INSTRUCTIONS.md`:
   - Section 1 status paragraph: add threshold configurability note
   - Section 2A machine snapshot: update test counts
   - Section 3 signal architecture: add note about env-var threshold control
   - Add threshold configuration to operator reference

9. Update `CLAUDE.md` "Current State":
   - Date: 2026-03-09
   - Add: "Edge thresholds now env-var configurable"
   - Test count: update
   - Note 7 cleanup commits
   - Next action: SSH to VPS, set aggressive thresholds, restart, monitor

10. Update `README.md` scorecard if headline numbers changed.

11. Update `docs/REPO_MAP.md` with new directories:
    - `research/deep_research_packets/` — numbered deep research attachment packets
    - `nontrading/` — non-trading revenue lane modules and docs
    - `infra/` — Elastic stack configs, Docker Compose, Kibana dashboards
    - `codex_instances/` — self-contained Codex parallel dispatch files

12. Update `AGENTS.md` with threshold configuration commands:
    ```
    # Aggressive (more trades):
    export JJ_YES_THRESHOLD=0.08 JJ_NO_THRESHOLD=0.03 JJ_MIN_CATEGORY_PRIORITY=0

    # Conservative (fewer trades):
    export JJ_YES_THRESHOLD=0.20 JJ_NO_THRESHOLD=0.08 JJ_MIN_CATEGORY_PRIORITY=2

    # Unlock specific categories:
    export JJ_CAT_PRIORITY_CRYPTO=2
    ```

13. If Instance #1 produced edge scan results, update `research/edge_backlog_ranked.md` with any status changes.

## VERIFICATION

```bash
python3 -m pytest tests/ -x -q --tb=short
# Verify all doc cross-references are consistent
grep -c "131" COMMAND_NODE.md PROJECT_INSTRUCTIONS.md CLAUDE.md
```

## HANDOFF

```
INSTANCE #3 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after for each metric]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
