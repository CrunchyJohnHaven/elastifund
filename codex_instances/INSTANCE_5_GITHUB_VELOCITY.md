# Execute Instance #5 — GitHub Sync & Improvement Velocity Charts

You are an autonomous Codex instance for the Elastifund trading system. Execute every step below without human intervention. Report findings, commit code, and produce the handoff artifact.

---

## STATE SNAPSHOT (Injected 2026-03-09)

- Cycle: 2 — Machine Truth Reconciliation
- Capital: $347.51 ($247.51 Polymarket + $100 Kalshi)
- Strategies: 131 tracked (7 deployed, 6 building, 2 structural, 10 rejected, 8 pre-rejected, 1 re-evaluating, 97 research)
- Tests: 353 local; 1,256 total verified
- Dispatches: 95
- Signal sources: 7
- Bot modules: 45 bot/*.py files
- Test files: 74
- Diary entries: 14
- Backtest win rate: 71.2% calibrated (NO-only: 76.2%)
- Maker excess return: +1.12% (jbecker 72M trades)
- Velocity benchmarks: 72% win rate on <24h, 6007% ARR maker-only
- Git HEAD: cde466f (7 cleanup commits this session)

---

## OBJECTIVE

Push all changes to GitHub. Generate updated improvement velocity metrics and charts. Cover both trading agent and non-trading agent systems.

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

4. Read `nontrading/` directory for non-trading revenue lane status.

5. Read all `docs/diary/` entries to extract timeline:
   - 2026-02-15: Project inception
   - 2026-02-20: First backtest
   - 2026-02-22: Calibration breakthrough
   - 2026-02-24: Kelly criterion
   - 2026-02-28: Four signal sources
   - 2026-03-01: Dublin VPS live
   - 2026-03-02: Edge discovery pipeline
   - 2026-03-04: Cross-platform arb
   - 2026-03-06: Nine strategies rejected, then twelve
   - 2026-03-07: Day one, the flywheel, weather fail / latency win

6. Read `research/edge_backlog_ranked.md` for strategy funnel metrics.

7. Generate `improvement_velocity.json` at repo root:
   ```json
   {
     "generated_at": "<ISO timestamp>",
     "cycle": "2 — Machine Truth Reconciliation",
     "trading_agent": {
       "strategies_total": 131,
       "strategies_deployed": 7,
       "strategies_building": 8,
       "strategies_structural_alpha": 2,
       "strategies_rejected": 18,
       "strategies_pre_rejected": 8,
       "strategies_re_evaluating": 1,
       "strategies_research": 97,
       "test_count_local": 353,
       "test_count_total": 1256,
       "dispatch_count": 95,
       "capital_deployed_usd": 347.51,
       "backtest_win_rate_calibrated": 0.712,
       "backtest_win_rate_no_only": 0.762,
       "maker_excess_return_pct": 1.12,
       "signal_sources": 7,
       "bot_modules": 45,
       "live_trades": 0,
       "cycles_completed": 298
     },
     "non_trading_agent": {
       "modules_complete": 0,
       "revenue_lanes_active": 0,
       "compliance_status": "planning",
       "jj_n_rollout_status": "90-day plan canonical, not started"
     },
     "threshold_config": {
       "yes_threshold": "env:JJ_YES_THRESHOLD (default 0.15)",
       "no_threshold": "env:JJ_NO_THRESHOLD (default 0.05)",
       "min_category_priority": "env:JJ_MIN_CATEGORY_PRIORITY (default 1)",
       "category_overrides": "env:JJ_CAT_PRIORITY_<CATEGORY>",
       "configurable_since": "2026-03-09"
     },
     "velocity_metrics": {
       "project_age_days": 22,
       "strategies_per_week": 42,
       "tests_added_total": 1256,
       "dispatches_total": 95,
       "diary_entries": 14,
       "commits_this_session": 7,
       "files_reorganized": 21
     },
     "arr_estimate": {
       "trading_arr_backtest": "velocity_maker: $247.51 × 72% win × 6007% annualized = theoretical only (0 live trades)",
       "non_trading_arr": "not started",
       "combined_arr": "no live data yet",
       "methodology": "No live ARR can be computed with 0 closed trades. Backtest ARR is theoretical. First live trade is the prerequisite."
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
   tests = [10, 50, 100, 150, 200, 345, 500, 900, 1200, 1256]
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
   plt.title('Elastifund Improvement Velocity — Cycle 2', color='white', fontsize=14)
   for spine in [*ax1.spines.values(), *ax2.spines.values()]:
       spine.set_color('#2d3748')

   plt.tight_layout()
   plt.savefig('improvement_velocity.svg', facecolor='#0a0e17', edgecolor='none')
   print('Chart saved')
   ```

9. Update `README.md` to reference the chart if not already linked.

10. Commit:
    ```bash
    git add improvement_velocity.json improvement_velocity.svg
    git commit -m "chore: update velocity metrics and chart [Cycle 2]

    Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
    ```

11. Push to GitHub:
    ```bash
    git push origin main
    ```

## VERIFICATION

```bash
git log -1 --oneline  # Shows new commit
ls improvement_velocity.json improvement_velocity.svg  # Files exist
```

## HANDOFF

```
INSTANCE #5 HANDOFF
---
Files changed: [list]
Commands run: [list]
Key findings: [1-3 sentences]
Numbers that moved: [before→after]
Unverified: [anything next cycle should check]
Next instance can edit these files: [yes/no per file]
```
