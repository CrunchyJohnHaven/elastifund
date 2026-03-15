# CODEX TASK 04: Harden Signal Attribution and Fix Cross-Platform Async Reentrancy

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Preferred path ownership: `bot/cross_platform_arb.py`, `scripts/run_signal_source_audit.py`, `tests/test_signal_source_audit.py`, and a focused arb async regression test
- Touch `bot/jj_live.py` only if a minimal call-site change is required.

## Machine Truth (March 9, 2026)
- Signal attribution is already partially landed. `bot/jj_live.py` persists `source`, `source_combo`, `source_components`, and `source_count`, and `scripts/run_signal_source_audit.py` plus `tests/test_signal_source_audit.py` already exist.
- `reports/signal_source_audit.json` confirms the current attribution contract is present in both `jj_state.json` and `data/jj_trades.db`.
- `reports/deploy_20260309T013604Z.json` captured a non-fatal cross-platform arb asyncio warning on the VPS.
- The current `bot/cross_platform_arb.py:get_signals_for_engine()` still uses `run_until_complete()` with an `asyncio.run()` fallback, which is not safe when called from `JJLive.run_cycle()` inside an already-running event loop.

## Goal
Preserve the existing attribution schema, then fix the cross-platform arb event-loop boundary so the lane can run cleanly inside the live bot.

## Required Work
1. Audit the current attribution contract before changing anything.
2. Do not invent a second schema such as `signal_sources` if the current `source` / `source_combo` / `source_components` contract is already sufficient.
3. Fix the async boundary in `bot/cross_platform_arb.py`:
   - provide an async-safe entrypoint for `JJLive`
   - keep the synchronous CLI path working
4. If needed, make the smallest possible `bot/jj_live.py` call-site change to use the async-safe entrypoint.
5. Extend `scripts/run_signal_source_audit.py` only if a useful missing metric is obvious.
6. Add a focused regression test that exercises cross-platform signal retrieval from inside a running event loop.

## Deliverables
- Minimal code fix for the arb async boundary
- Updated attribution audit only if needed
- A regression test proving the nested-event-loop failure is gone

## Verification
- `python -m pytest tests/test_signal_source_audit.py`
- `python -m pytest bot/tests/test_cross_platform_arb.py` or a new focused test file if you add one

## Constraints
- Do not change signal-generation logic or thresholds.
- Do not rename or remove the existing attribution fields.
- Keep the output format of `reports/signal_source_audit.json` backward compatible unless there is a strong reason not to.
