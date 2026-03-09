# CODEX DISPATCH — Elastifund Parallel Instance Execution Plan

> **Generated:** 2026-03-09 (Cycle 2 — Machine Truth Reconciliation)
> **State injected from:** CLAUDE.md, COMMAND_NODE.md, edge_backlog_ranked.md, FAST_TRADE_EDGE_ANALYSIS.md, PROJECT_INSTRUCTIONS.md
> **Instructions:** Paste each Instance block verbatim into a separate Codex session: "Execute Instance #N — [block]"

---

## CURRENT STATE SNAPSHOT (Read by all instances)

| Metric | Value |
|--------|-------|
| Capital | Internal seed bankroll withheld from public docs |
| Service | `jj-live.service` status ambiguous — remote artifact shows `active`, but 0 trades in 298 cycles. Launch gates blocked. |
| Live trades | 0 |
| Fast-trade pipeline | `REJECT ALL` (all hypotheses failed kill rules) |
| A-6 gate | 0 executable constructions below 0.95 |
| B-1 gate | 0 deterministic template pairs in first 1,000 markets |
| Wallet-flow | `not_ready` (bootstrap artifacts missing) |
| Tests | 353 passing locally |
| Dispatches | 95 in `research/dispatches/` |
| Strategies | 131 tracked (7 deployed, 6 building, 2 structural alpha, 10 rejected, 8 pre-rejected, 1 re-evaluating, 97 research) |
| Threshold config | **NEW** — `JJ_YES_THRESHOLD`, `JJ_NO_THRESHOLD`, `JJ_MIN_CATEGORY_PRIORITY`, `JJ_CAT_PRIORITY_*` are now env-var-driven. Defaults: YES=0.15, NO=0.05, MIN_CAT=1 |
| Git HEAD | Clean tree. 6 commits landed this session. |
| Execution mode | 100% Post-Only maker orders (Dispatch #75 pivot) |
| Platt calibration | A=0.5914, B=-0.3977 (532-market fit) |
| Kelly | 0.25 quarter-Kelly, $5/position, 5 max open, $5 daily loss cap |

---

## INSTANCE #1 — THRESHOLD TUNING & TRADE DEPLOYMENT

**Objective:** Using the newly env-var-configurable thresholds, determine optimal aggressive settings backed by data, then deploy to VPS and monitor for the first live trade.

**You own:** `bot/jj_live.py` (config section only), `.env` on VPS, `reports/`
**Do not touch:** `docs/`, `research/`, website files, core bot logic

**Steps:**

1. Read `bot/jj_live.py` lines 674-682 for the new threshold env vars: `JJ_YES_THRESHOLD`, `JJ_NO_THRESHOLD`, `JJ_MIN_CATEGORY_PRIORITY`, `JJ_CAT_PRIORITY_*`.
2. Read `research/edge_backlog_ranked.md` Section "DEPLOYED STRATEGIES" — note the D2 asymmetric thresholds evidence: 76.2% NO-only win rate supports lower NO threshold.
3. Compute optimal aggressive thresholds:
   - YES: Lower from 0.15 to 0.08. Rationale: Platt calibration compresses 90%→71%, so 0.15 requires raw LLM output >92%. At 0.08, raw >85% is sufficient — still selective but realistic.
   - NO: Lower from 0.05 to 0.03. Rationale: NO side has 76% historical win rate, lower bar justified.
   - MIN_CATEGORY_PRIORITY: Lower from 1 to 0 temporarily to scan ALL categories and measure what the LLM produces. Data before doctrine.
4. SSH to Dublin VPS: `ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0`
5. Verify VPS `.env` has: `PAPER_TRADING=false`, `ANTHROPIC_API_KEY` set, `POLYMARKET_API_KEY`/`POLYMARKET_SECRET`/`POLYMARKET_PASSPHRASE` set.
6. Add to VPS `.env`:
   ```
   JJ_YES_THRESHOLD=0.08
   JJ_NO_THRESHOLD=0.03
   JJ_MIN_CATEGORY_PRIORITY=0
   ```
7. Restart service: `sudo systemctl restart jj-live.service`
8. Monitor first 3 cycles: `sudo journalctl -u jj-live.service -f --no-pager | head -500`
9. After 3 cycles: check `jj_state.json` for any trades placed. Check logs for edge calculations to verify thresholds are working.
10. Write results to `reports/threshold_tuning_<timestamp>.json` with: `{thresholds_applied, markets_scanned, signals_generated, signals_passed_threshold, trades_placed, edge_distribution}`.

**Verification:** `systemctl is-active jj-live.service` returns `active`. At least one scan cycle completes without error. Threshold values visible in log output.

**Handoff artifact:** `reports/threshold_tuning_<timestamp>.json`

**ESCALATION NOTE:** This instance changes risk parameters (lowering thresholds). Per CLAUDE.md, this requires human approval. John has explicitly authorized this in the session that generated this dispatch. Proceed.

---

## INSTANCE #2 — NO-BIAS STATISTICAL SIGNAL

**Objective:** Implement a pure statistical NO-bias signal based on the jbecker.dev 72.1M trade dataset. NO outperforms YES at 69/99 price levels. This requires zero LLM calls — pure data.

**You own:** `bot/no_bias_signal.py` (new file), `bot/jj_live.py` (signal integration)
**Do not touch:** `docs/`, `research/`, website files, deployment

**Steps:**

1. Read the jbecker research findings documented in `CLAUDE.md` and `research/edge_backlog_ranked.md`:
   - NO outperforms YES at 69/99 price levels
   - Category gaps: World Events 7.32pp, Media 7.28pp, Entertainment 4.79pp
   - Makers earn +1.12% excess return
2. Create `bot/no_bias_signal.py`:
   ```python
   """NO-bias statistical signal based on 72.1M Polymarket trade analysis.

   Source: jbecker.dev empirical analysis
   Finding: NO contracts outperform YES at 69/99 price levels.
   Category gaps: World Events 7.32pp, Media 7.28pp, Entertainment 4.79pp.

   This signal requires NO LLM call. Pure statistics.
   """
   ```
   - Function: `compute_no_bias_edge(yes_price: float, category: str) -> dict`
   - Returns: `{direction: "NO", edge: float, confidence: str, source: "jbecker_72m"}`
   - Edge calculation: `edge = yes_price - fair_value_by_category[category]` where fair values are empirically derived
   - Only fires when `yes_price > 0.55` (NO is cheap relative to historical outcomes)
   - Category-specific adjustments: `world_events` gets +7.32pp boost, `media` +7.28pp, `entertainment` +4.79pp
   - Sizing: 1/8 Kelly (conservative, statistical edge not LLM-verified)
3. Write tests in `tests/test_no_bias_signal.py`:
   - Test edge computation at various price points
   - Test category adjustments
   - Test that signal fires only above 0.55 YES price
   - Test that NO direction is always returned
4. Wire into `bot/jj_live.py` as Signal Source #7:
   - Add to the signal collection loop alongside LLM and VPIN signals
   - Log it distinctly: `"NO-BIAS: edge=%.3f category=%s source=jbecker_72m"`
   - Size at 1/8 Kelly via `KELLY_FRACTION * 0.5`
5. Run `python3 -m pytest tests/ -x -q` to verify nothing broke.

**Verification:** `python3 -m pytest tests/test_no_bias_signal.py -v` passes. `python3 -c "from bot.no_bias_signal import compute_no_bias_edge; print(compute_no_bias_edge(0.70, 'politics'))"` returns a valid signal dict.

**Handoff artifact:** `bot/no_bias_signal.py`, `tests/test_no_bias_signal.py`, diff of `bot/jj_live.py` integration.

---

## INSTANCE #3 — COMMAND NODE & DOC SYNC

**Objective:** Update all canonical docs to reflect the repo cleanup, threshold configurability, and current cycle state.

**You own:** `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md`, `CLAUDE.md`, `docs/`, `research/edge_backlog_ranked.md`, `README.md`, `AGENTS.md`
**Do not touch:** `bot/`, `scripts/`, `tests/`, website files

**Steps:**

1. Read current `CLAUDE.md` "Current State" section.
2. Update `CLAUDE.md` "Current State":
   - Date: 2026-03-09
   - Add: "Edge thresholds now env-var configurable (JJ_YES_THRESHOLD, JJ_NO_THRESHOLD, JJ_MIN_CATEGORY_PRIORITY, JJ_CAT_PRIORITY_*)"
   - Update test count: 353 passing locally
   - Note repo cleanup: 6 commits — threshold config, doc reorg, Elastic stack, new tests
   - Update next action based on Instance #1 results if available
3. Update `COMMAND_NODE.md`:
   - Section 1 current status: add threshold configurability note
   - Update verification baseline with new test count
   - Note the 6 cleanup commits
4. Update `PROJECT_INSTRUCTIONS.md`:
   - Section 2A machine snapshot: update test counts
   - Section 3 signal architecture: add Signal #7 (NO-Bias Statistical) if Instance #2 completed
   - Add threshold configuration documentation to the operator reference
5. Update `README.md` scorecard if headline numbers changed.
6. Update `docs/REPO_MAP.md` with new directories: `research/deep_research_packets/`, `nontrading/`, `infra/`
7. Update `AGENTS.md` with threshold configuration commands.
8. Run `make hygiene` if available to verify consistency.
9. Commit all changes with message: `docs: sync canonical docs with Cycle 2 cleanup [353 tests, env-var thresholds]`

**Verification:** All doc cross-references are consistent. Test counts match. Strategy counts match `research/edge_backlog_ranked.md`.

**Handoff artifact:** Diff summary of all doc changes with before→after numbers.

---

## INSTANCE #4 — VPS DEPLOYMENT & SERVICE HEALTH

**Objective:** Push all committed code to the Dublin VPS. Verify runtime health. Prepare for threshold-tuned restart.

**You own:** VPS operations, `scripts/deploy_release_bundle.py`, systemd config
**Do not touch:** `docs/`, `research/`, website files, core bot logic

**Steps:**

1. Verify local repo is clean: `git status` shows no uncommitted changes.
2. Push to GitHub: `git push origin main`
3. SSH to Dublin VPS: `ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem ubuntu@52.208.155.0`
4. On VPS:
   ```bash
   cd /home/ubuntu/polymarket-trading-bot/
   git pull origin main
   git log --oneline -5  # Verify HEAD matches local
   ```
5. Check `.env` on VPS for all required keys:
   - `ANTHROPIC_API_KEY` — must be set and valid
   - `POLYMARKET_API_KEY`, `POLYMARKET_SECRET`, `POLYMARKET_PASSPHRASE` — must be set
   - `PAPER_TRADING` — must be `false` for live trading
   - `POLYMARKET_PRIVATE_KEY` — wallet private key must be set
   - Flag any missing keys — DO NOT create them, just report.
6. Verify Python environment: `python3 -c "from bot.jj_live import TradingBot; print('import OK')"`
7. Run a dry-run cycle: `python3 bot/jj_live.py --dry-run --cycles=1 2>&1 | tail -50` (if supported)
   - If `--dry-run` is not supported, run with `PAPER_TRADING=true python3 bot/jj_live.py` for one cycle manually.
8. Check systemd service file is current: `cat /etc/systemd/system/jj-live.service`
9. Verify the service can start: `sudo systemctl start jj-live.service && sleep 5 && sudo systemctl status jj-live.service`
10. Write results to `reports/deploy_<timestamp>.json` with: `{vps_sha, repo_sha, service_status, env_keys_present, env_keys_missing, dry_run_result}`

**Verification:** VPS git SHA matches local HEAD. Service starts without immediate crash. All required env keys present.

**Handoff artifact:** `reports/deploy_<timestamp>.json`

---

## INSTANCE #5 — GITHUB SYNC & VELOCITY METRICS

**Objective:** Push all changes to GitHub. Update velocity tracking. Verify CI health.

**You own:** `.github/`, `improvement_velocity.json`, `README.md` (metrics section)
**Do not touch:** `bot/` internals, `docs/` prose, website files

**Steps:**

1. Verify local repo is clean and all 6 cleanup commits are on `main`.
2. Push to GitHub: `git push origin main`
3. Generate `improvement_velocity.json` at repo root:
   ```json
   {
     "generated_at": "<ISO timestamp>",
     "cycle": "2 — Machine Truth Reconciliation",
     "trading_agent": {
       "strategies_total": 131,
       "strategies_deployed": 7,
       "strategies_building": 8,
       "strategies_rejected": 18,
       "test_count": 353,
       "dispatch_count": 95,
       "current_system_arr_pct": 0.0,
       "backtest_win_rate_no": 0.762,
       "backtest_win_rate_yes": 0.56,
       "maker_excess_return_pct": 1.12,
       "signal_sources": 7
     },
     "threshold_config": {
       "yes_threshold": "env:JJ_YES_THRESHOLD (default 0.15)",
       "no_threshold": "env:JJ_NO_THRESHOLD (default 0.05)",
       "min_category_priority": "env:JJ_MIN_CATEGORY_PRIORITY (default 1)",
       "category_overrides": "env:JJ_CAT_PRIORITY_<CATEGORY>"
     },
     "velocity_metrics": {
       "strategies_per_cycle": 8,
       "tests_added_this_session": 10,
       "commits_this_session": 6,
       "files_reorganized": 21,
       "new_env_var_knobs": 4
     }
   }
   ```
4. Update `README.md` with current metrics if stale.
5. Commit and push: `git add . && git commit -m "chore: update velocity metrics [Cycle 2]" && git push`
6. Verify GitHub Actions CI passes (if configured): `gh run list --limit 3`

**Verification:** `git log origin/main --oneline -5` shows all commits. `improvement_velocity.json` exists at root.

**Handoff artifact:** Git commit SHA + CI status.

---

## INSTANCE #6 — DATA PULL & PIPELINE REFRESH

**Objective:** Pull fresh Polymarket market data, evaluate current opportunities against the new lower thresholds, and produce an updated `FAST_TRADE_EDGE_ANALYSIS.md`.

**You own:** `src/`, `backtest/`, `data/`, `reports/`, `FAST_TRADE_EDGE_ANALYSIS.md`
**Do not touch:** `bot/` (except reading configs), `docs/`, website files

**Steps:**

1. Pull active Polymarket markets:
   ```bash
   curl -s "https://gamma-api.polymarket.com/events?closed=false&limit=500" > data/gamma_markets_$(date +%Y%m%dT%H%M%S).json
   ```
2. Filter for markets resolving within 48 hours of now. Count how many pass.
3. Filter for markets in categories with priority >= 1 (politics, weather, economic, geopolitical). Count how many pass.
4. Filter for markets with YES price between 0.10 and 0.90. Count how many pass.
5. For each surviving market, compute the edge that would be needed for the LLM to trigger a trade at:
   - Current thresholds: YES=0.15, NO=0.05
   - Aggressive thresholds: YES=0.08, NO=0.03
   - Report: how many MORE markets become tradeable at aggressive thresholds?
6. Run the A-6 sum-violation scanner against neg-risk events if `bot/a6_sum_scanner.py` exists:
   ```bash
   python3 -c "from bot.a6_sum_scanner import scan_neg_risk_events; print(scan_neg_risk_events())"
   ```
7. Update `FAST_TRADE_EDGE_ANALYSIS.md` with:
   - New timestamp
   - Market universe size at each filter stage
   - Threshold sensitivity analysis (current vs aggressive)
   - A-6 scan results
   - Updated recommendation (REJECT ALL → or specific opportunities)
8. Write detailed results to `reports/pipeline_refresh_<timestamp>.json`
9. Run `python3 -m pytest tests/ -x -q` to verify nothing broke.

**Verification:** `FAST_TRADE_EDGE_ANALYSIS.md` timestamp is current. `data/` has fresh market data. Tests pass.

**Handoff artifact:** `FAST_TRADE_EDGE_ANALYSIS.md` (updated) + `reports/pipeline_refresh_<timestamp>.json`

---

## INSTANCE DEPENDENCY MAP

```
Instance #6 (Data Pull) ──────┐
                               ├──→ Instance #1 (Threshold Tuning) ──→ Instance #4 (VPS Deploy)
Instance #3 (Doc Sync) ───────┘                                              │
       │                                                                      │
Instance #2 (NO-Bias Signal) ─────────────────────────────────────────────────┘
                                                                              │
Instance #5 (GitHub + Velocity) ←─────────────────────────────────────────────┘
```

**Recommended execution order:**
- **Wave 1 (parallel):** #2 (NO-Bias), #3 (Docs), #6 (Data Pull)
- **Wave 2 (parallel):** #1 (Thresholds), #4 (VPS Deploy)
- **Wave 3:** #5 (GitHub Sync)

**If running all 6 truly in parallel:** Instances read stale state on first pass. That's fine — the flywheel corrects drift. After one pass, all instances converge.

---

## ESCALATION RULES (EVERY INSTANCE FOLLOWS THESE)

Escalate to human (John) ONLY when:
- Spending real money (switching paper → live, restarting stopped service)
- Changing risk parameters (position sizes, loss limits, Kelly fractions)
- Architectural decisions with no clear best option
- Something is broken after exhausting debugging
- Legal/compliance questions

**Pre-authorized for this dispatch:**
- Lowering edge thresholds (John approved in session)
- Restarting `jj-live.service` with new thresholds (John approved in session)
- Adding NO-bias signal as Signal #7 (John approved in session)

For everything else: execute, commit, push, report.

---

## HANDOFF CONTRACT (EVERY INSTANCE PRODUCES THIS)

```
INSTANCE #N HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [list with before→after]
Unverified: [anything the next cycle should check]
Next instance can edit these files: [yes/no per file]
```

---

## HOW TO USE THIS DISPATCH

1. Open 6 Codex sessions (or as many as available).
2. Paste each Instance block into a separate session: "Execute Instance #N — [block]"
3. Wave 1 instances (#2, #3, #6) can run immediately.
4. Wave 2 instances (#1, #4) can run after Wave 1 if strict ordering desired, or immediately for eventual consistency.
5. Wave 3 instance (#5) runs last to capture all changes.
6. Collect handoff artifacts. Feed into next flywheel cycle.

The system improves every pass. The velocity metrics prove it.
