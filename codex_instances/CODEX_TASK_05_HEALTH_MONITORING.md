# CODEX TASK 05: Finish the Health-Monitoring Runtime Surface

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Path ownership for this task: `bot/health_monitor.py`, `scripts/install_jj_health_cron.sh`, `bot/polymarket_runtime.py`, `polymarket-bot/src/telegram.py`, and health-monitor tests
- Do **not** edit `scripts/deploy.sh` here. Task 07 owns deploy packaging.

## Machine Truth (March 9, 2026)
- Heartbeat writing, stale-service checks, auto-restart handling, and daily summaries already exist in `bot/health_monitor.py`.
- `JJLive` already writes startup and cycle heartbeats, and `scripts/install_jj_health_cron.sh` already installs the cron entrypoint.
- The remaining ops gap is runtime reliability: prior VPS logs reported `Telegram module not available — notifications disabled`.
- `bot/polymarket_runtime.py` lazy-loads `src.telegram`, and `polymarket-bot/src/telegram.py` imports `src.core.time_utils`, so the import chain is more fragile than the older prompt assumed.

## Goal
Do not re-implement heartbeat logic. Validate the existing health-monitor path and fix the remaining runtime issues so Telegram alerts and daily summaries work when credentials are present.

## Required Work
1. Audit the current `bot.health_monitor` and Telegram import path end to end.
2. Fix any code-level issue that prevents:
   - `python -m bot.health_monitor` from constructing a sender in a non-async CLI context
   - graceful fallback when Telegram credentials are missing
3. Keep `scripts/install_jj_health_cron.sh` aligned with the canonical `python -m bot.health_monitor` entrypoint.
4. Add or extend tests to cover:
   - sender construction success
   - graceful fallback when Telegram is unavailable or unconfigured
   - daily summary formatting still working

## Deliverables
- Only the minimal runtime hardening needed in the owned files
- Additional focused tests if current coverage misses the Telegram path

## Verification
- `python -m pytest tests/test_health_monitor.py`
- Run any new targeted test file you add

## Constraints
- Do not create duplicate wrappers like `scripts/health_check.sh` or `scripts/daily_summary.py`; the canonical implementation is already in `bot/health_monitor.py`.
- Do not add Prometheus, Grafana, or new services.
- Keep the feature set bash/cron friendly and VPS friendly.
