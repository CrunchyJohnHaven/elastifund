# Execute Instance #5 — GitHub Sync & Improvement Velocity Charts

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09 v2.8.0)

- Cycle: 2 — Structural Alpha & Microstructure Defense
- Current system ARR: 0% realized
- Strategies: 131 tracked (7 deployed, 6 building, 2 structural alpha, 10 rejected, 8 pre-rejected, 1 re-evaluating, 97 research)
- Tests: 1,278 total verified (871+22 root, 374 polymarket, 11 non-trading)
- Dispatches: 11 DISPATCH_* work-orders; 95 markdown files in `research/dispatches/`
- Signal sources: 7 (LLM Ensemble, LMSR, WalletFlow, CrossPlatformArb, VPIN/OFI, LeadLag, ElasticML)
- Bot modules: 46 bot/*.py files (all pass syntax)
- Cycles: 305 completed, 0 live trades
- Wallet-flow: ready (80 scored wallets)
- Backtest win rate: 71.2% calibrated (NO-only: 76.2%)
- Maker excess return: +1.12% (jbecker 72M trades)
- Velocity benchmarks: 72% win rate on <24h, 6007% ARR maker-only
- Vision integration: completed March 9

### VISION CONTEXT

Both trading AND non-trading velocity metrics must be tracked. The improvement_velocity.json must include JJ-N status. The chart title should reflect "agentic operating system" not just "trading."

---

## OBJECTIVE

Push all changes to GitHub. Generate updated improvement velocity metrics and charts covering both trading and non-trading agent systems. Ensure the public repo reflects the latest verified state.

## YOU OWN

`.github/`, `improvement_velocity.json`, `improvement_velocity.svg`, `arr_estimate.svg`, `README.md` (chart/metrics section only), `nontrading/`

## DO NOT TOUCH

`bot/` internals, `docs/` prose, website files, `CLAUDE.md`, `COMMAND_NODE.md`

## STEPS

1. Verify local repo is clean:
   ```bash
   git status
   ```

2. Read `CLAUDE.md` "Current State" for cycle number, dates, capital, strategy counts.

3. Read `research/velocity_maker_strategy.md` for velocity benchmarks.

4. Read `nontrading/` directory for non-trading revenue lane status:
   ```bash
   ls nontrading/ 2>/dev/null || echo "nontrading/ directory status"
   ```

5. Read all `docs/diary/` entries to extract timeline.

6. Read `research/edge_backlog_ranked.md` for strategy funnel metrics.

7. Generate `improvement_velocity.json` at repo root:
   ```json
   {
     "generated_at": "<ISO timestamp>",
     "instance_version": "2.8.0",
     "cycle": "2 — Structural Alpha & Microstructure Defense",
     "trading_agent": {
       "strategies_total": 131,
       "strategies_deployed": 7,
       "strategies_building": 6,
       "strategies_structural_alpha": 2,
       "strategies_rejected": 10,
       "strategies_pre_rejected": 8,
       "strategies_re_evaluating": 1,
       "strategies_research": 97,
       "test_count_root": 893,
       "test_count_polymarket": 374,
       "test_count_nontrading": 11,
       "test_count_total": 1278,
       "dispatch_count": 95,
       "dispatch_work_orders": 11,
       "current_system_arr_pct": 0.0,
       "backtest_win_rate_calibrated": 0.712,
       "backtest_win_rate_no_only": 0.762,
       "maker_excess_return_pct": 1.12,
       "signal_sources": 7,
       "bot_modules": 46,
       "live_trades": 0,
       "cycles_completed": 305,
       "wallet_flow_ready": true,
       "scored_wallets": 80,
       "a6_executable": 0,
       "b1_deterministic_pairs": 0
     },
     "non_trading_agent": {
       "modules_complete": 0,
       "revenue_lanes_active": 0,
       "compliance_status": "planning",
       "jj_n_rollout_phase": "Phase 0 — Foundations (not started)",
       "five_engines_defined": true,
       "opportunity_scoring_framework": true,
       "crm_schema": false,
       "telemetry_wired": false
     },
     "vision_compliance": {
       "product_definition": "agentic OS for real economic work",
       "worker_families": ["trading", "non-trading (JJ-N)"],
       "messaging_approved": true,
       "numbered_docs_created": 0,
       "numbered_docs_planned": 13
     },
     "velocity_metrics": {
       "project_age_days": 22,
       "strategies_per_week": 42,
       "tests_added_total": 1278,
       "dispatches_total": 95,
       "diary_entries": 14,
       "vision_docs_integrated": 2
     },
     "arr_estimate": {
       "trading_arr_backtest": "theoretical only (0 live trades, 0 closed positions)",
       "non_trading_arr": "not started",
       "combined_arr": "no live data yet",
       "methodology": "No live ARR can be computed with 0 closed trades. First live trade is the prerequisite."
     }
   }
   ```

8. Generate `improvement_velocity.svg` chart using Python matplotlib:
   ```python
   import matplotlib
   matplotlib.use('Agg')
   import matplotlib.pyplot as plt
   import matplotlib.dates as mdates
   from datetime import datetime

   dates = [
       datetime(2026,2,15), datetime(2026,2,20), datetime(2026,2,22),
       datetime(2026,2,24), datetime(2026,2,28), datetime(2026,3,1),
       datetime(2026,3,2), datetime(2026,3,6), datetime(2026,3,7), datetime(2026,3,9)
   ]
   strategies = [1, 3, 5, 8, 15, 25, 62, 121, 131, 131]
   tests = [10, 50, 100, 150, 200, 345, 500, 900, 1200, 1278]
   dispatches = [0, 5, 10, 15, 25, 40, 60, 80, 90, 95]

   fig, ax1 = plt.subplots(figsize=(12, 6))
   fig.patch.set_facecolor('#0a0e17')
   ax1.set_facecolor('#0a0e17')

   ax1.plot(dates, strategies, '#10b981', linewidth=2, label='Strategies Tracked')
   ax1.plot(dates, dispatches, '#6366f1', linewidth=2, label='Research Dispatches')
   ax1.set_ylabel('Count', color='white')
   ax1.tick_params(colors='white')
   ax1.legend(loc='upper left', facecolor='#1a1f2e', edgecolor='#2d3748', labelcolor='white')

   ax2 = ax1.twinx()
   ax2.plot(dates, tests, '#f59e0b', linewidth=2, linestyle='--', label='Tests Passing')
   ax2.set_ylabel('Tests', color='#f59e0b')
   ax2.tick_params(colors='#f59e0b')
   ax2.legend(loc='upper right', facecolor='#1a1f2e', edgecolor='#2d3748', labelcolor='white')

   ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
   plt.title('Elastifund Improvement Velocity — Agentic OS Cycle 2', color='white', fontsize=14)
   for spine in [*ax1.spines.values(), *ax2.spines.values()]:
       spine.set_color('#2d3748')

   plt.tight_layout()
   plt.savefig('improvement_velocity.svg', facecolor='#0a0e17', edgecolor='none')
   print('Chart saved')
   ```

9. Update `README.md` to reference the chart and reflect vision-aligned framing if not already done.

10. Commit and push:
    ```bash
    git add improvement_velocity.json improvement_velocity.svg
    git commit -m "chore: update velocity metrics and chart [Cycle 2, v2.8.0]

    Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
    git push origin main
    ```

## VERIFICATION

```bash
git log -1 --oneline
ls improvement_velocity.json improvement_velocity.svg
python3 -c "import json; d=json.load(open('improvement_velocity.json')); assert d['trading_agent']['test_count_total']==1278; print('JSON valid')"
```

## HANDOFF

```
INSTANCE #5 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after]
GitHub push: [success|failed + reason]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
