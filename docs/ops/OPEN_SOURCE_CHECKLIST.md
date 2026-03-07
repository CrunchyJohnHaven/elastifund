# OPEN_SOURCE_CHECKLIST
Date: 2026-03-07
Scope scanned: `/Users/johnbradley/Desktop/Elastifund`

## Summary
- Hardcoded live API secrets were not found in scanned text files.
- Public/operational identifiers were found and should be sanitized for open-source release.

## Files Requiring Sanitization (with line numbers)
- `/Users/johnbradley/Desktop/Elastifund/scripts/deploy.sh:13`
  - Contains fixed VPS target `root@161.35.24.142`.
  - Action: replace with env var placeholder.

- `/Users/johnbradley/Desktop/Elastifund/Checklist.md:42`
- `/Users/johnbradley/Desktop/Elastifund/Checklist.md:44`
- `/Users/johnbradley/Desktop/Elastifund/Report_Generation_Checklist.md:13`
- `/Users/johnbradley/Desktop/Elastifund/Report_Generation_Checklist.md:26`
- `/Users/johnbradley/Desktop/Elastifund/JJ_SYSTEM_v1.0.md:58`
- `/Users/johnbradley/Desktop/Elastifund/JJ_SYSTEM_v1.0.md:173`
- `/Users/johnbradley/Desktop/Elastifund/Predictive-Alpha-2.0-Handoff/02_CURRENT_SYSTEM/SYSTEM_OVERVIEW.md:617`
- `/Users/johnbradley/Desktop/Elastifund/research_dispatch/P0_33_live_vs_backtest_scorecard_COWORK.md:8`
- `/Users/johnbradley/Desktop/Elastifund/research_dispatch/P0_65_live_scorecard_statistical_validation_COWORK.md:16`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/HEALTH_REPORT_20260305.md:14`
  - Contains specific server IP `161.35.24.142`.
  - Action: replace with `${VPS_HOST}` or redact.

- `/Users/johnbradley/Desktop/Elastifund/CONTRIBUTING.md:76`
- `/Users/johnbradley/Desktop/Elastifund/INVESTOR_FOLDER_INDEX.md:67`
- `/Users/johnbradley/Desktop/Elastifund/JJ_SYSTEM_v1.0.md:5`
- `/Users/johnbradley/Desktop/Elastifund/generate_monthly_report.js:416`
  - Contains personal email `johnhavenbradley@gmail.com`.
  - Action: replace with team alias email.

- `/Users/johnbradley/Desktop/Elastifund/Checklist.md:84`
- `/Users/johnbradley/Desktop/Elastifund/research_dispatch/P1_39_multi_model_ensemble_implementation_CLAUDE_CODE.md:89`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/.env.live.template:30`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/QUICK_START.md:86`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/INDEX.md:180`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/START_HERE.md:168`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/FILES_SUMMARY.txt:212`
  - Contains key-like examples (`sk-...`, `sk-ant-...`).
  - Action: replace with neutral placeholders (already done in root `.env.example`).

## Repository Hygiene Actions Applied
- Added/updated root `.env.example` placeholders to avoid key-like strings.
- Ensured root `.gitignore` includes:
  - `.env`, `jj_state.json`, `*.db`, `venv/`, `__pycache__/`, `research/`.
  - `polymarket-bot/backtest_output/`.
