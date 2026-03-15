# CODEX DISPATCH — ALL 8 TASKS
# Generated 2026-03-09 by JJ
# Each task is self-contained. Paste one per Codex instance.
# Repo: /Users/johnbradley/Desktop/Elastifund
# Read first in every instance: README.md, docs/REPO_MAP.md, PROJECT_INSTRUCTIONS.md

---

# ════════════════════════════════════════════════════════
# TASK 01: Build the .env Cleanup Helper
# ════════════════════════════════════════════════════════

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Path ownership for this task: `scripts/clean_env_for_profile.sh` and any new focused test file
- Do **not** edit `scripts/deploy.sh` here. Task 07 owns deploy-script integration.

## Machine Truth (March 9, 2026)
- `reports/deploy_20260309T013604Z.json` showed the remote VPS `.env` exposing only `PAPER_TRADING=false`; `JJ_RUNTIME_PROFILE` was absent.
- `config/runtime_profile.py` uses `OVERRIDE_SPECS`, so stray `JJ_*` and related env keys can silently override the checked-in runtime profiles.
- `scripts/deploy.sh` already syncs runtime profile JSON files, but there is no checked-in helper that sanitizes a remote `.env` for profile-based launches.

## Goal
Create a reusable shell helper that strips runtime overrides from an existing `.env`, preserves secrets, and appends a single `JJ_RUNTIME_PROFILE=<profile>` selector.

## Required Work
1. Create `scripts/clean_env_for_profile.sh`.
2. Default the profile argument to `live_aggressive`; allow an explicit profile name as `$1`.
3. Back up the input `.env` to `.env.backup.<timestamp>` before rewriting it.
4. Preserve secrets and deploy identity keys such as `KEY`, `SECRET`, `TOKEN`, `PASSPHRASE`, `PK`, `ADDRESS`, `TELEGRAM`, `API_KEY`, `PRIVATE`, `FUNDER`, `SAFE_ADDRESS`, and `PROXY`.
5. Remove runtime override keys such as `JJ_*`, `PAPER_TRADING`, `LIVE_TRADING`, `ENABLE_*`, `CLAUDE_MODEL`, and `ELASTIFUND_AGENT_RUN_MODE`.
6. Append exactly one `JJ_RUNTIME_PROFILE=<profile>` line.
7. Print the cleaned file contents and run a Python verification snippet that loads the selected runtime profile and prints the profile name plus a few key values.

## Deliverables
- `scripts/clean_env_for_profile.sh`
- A focused regression test if you need one, for example `tests/test_clean_env_for_profile.py`

## Verification
- `bash -n scripts/clean_env_for_profile.sh`
- `python -m pytest tests/test_runtime_profile.py`
- If you add a new test file, run it explicitly

## Constraints
- Do not SSH to the VPS.
- Do not modify `config/runtime_profile.py`.
- Do not edit any profile JSON files in `config/runtime_profiles/`.
- Keep the helper POSIX-shell friendly enough to run on the VPS with `bash`.

---

# ════════════════════════════════════════════════════════
# TASK 02: Check In a Real Threshold Sweep Script
# ════════════════════════════════════════════════════════

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Path ownership for this task: `scripts/threshold_sweep.py`, `tests/test_threshold_sweep.py`, `reports/threshold_sensitivity_sweep.json`
- Avoid editing `src/pipeline_refresh.py` unless a tiny helper extraction is unavoidable.

## Machine Truth (March 9, 2026)
- `reports/pipeline_refresh_20260309T013209Z.json` at `2026-03-09T01:32:09Z` found `0` tradeable markets at current, aggressive, and wide-open thresholds when working from the flattened Gamma universe.
- `reports/pipeline_refresh_20260309T015834Z.json` at `2026-03-09T01:58:34Z` used fast-market discovery and found `6` BTC candle windows with threshold reachability at `0.08/0.03` and `0.05/0.02`, while `0.15/0.05` still stayed at `0`.
- `reports/threshold_sensitivity_sweep.json` already exists, but there is no checked-in script behind it, and the current report explicitly says it measures threshold reachability, not validated live model-pass rate.

## Goal
Create a reproducible script that regenerates the sweep report from repo code and makes the reachability-vs-pipeline distinction explicit.

## Required Work
1. Create `scripts/threshold_sweep.py`.
2. Reuse the existing `src.pipeline_refresh` logic instead of re-implementing threshold math from scratch.
3. Support an offline path that can build from the latest checked-in `reports/pipeline_refresh_*.json` artifact.
4. Emit a JSON report to `reports/threshold_sensitivity_sweep.json` with:
   - the source artifact used
   - threshold pairs tested
   - counts for both `pipeline_tradeable` and `fast_market_reachability`
   - breakpoint detection
   - a plain-English conclusion explaining whether `0.08/0.03` unlocks only reachability or actual tradeable markets
5. Print a concise step-function summary to stdout.
6. Add `tests/test_threshold_sweep.py` with mocked inputs covering the current-vs-aggressive breakpoint behavior.

## Deliverables
- `scripts/threshold_sweep.py`
- `tests/test_threshold_sweep.py`
- Updated `reports/threshold_sensitivity_sweep.json`

## Verification
- `python3 scripts/threshold_sweep.py`
- `python -m pytest tests/test_pipeline_refresh.py tests/test_threshold_sweep.py`

## Constraints
- Do not route this through `bot.polymarket_runtime.MarketScanner`; the checked-in March 9 logic lives in `src/pipeline_refresh.py`.
- Do not claim "8 markets" unless the script actually observes 8 on the run you execute. Earlier March 8 prose said 8, but the latest checked-in fast-market artifact shows 6.
- Keep the output explicit about the difference between threshold reachability and a real dispatchable trade set.

---

# ════════════════════════════════════════════════════════
# TASK 03: Check In the Crypto Category Audit
# ════════════════════════════════════════════════════════

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Path ownership for this task: `scripts/crypto_category_audit.py`, `tests/test_crypto_category_audit.py`, `reports/crypto_category_audit.json`
- Avoid editing `src/pipeline_refresh.py` unless a small helper extraction is unavoidable.

## Machine Truth (March 9, 2026)
- Earlier March 8 notes referenced `8` BTC markets. The latest checked-in fast-market artifact at `2026-03-09T01:58:34Z` shows `6` reachable BTC candle windows instead.
- `reports/crypto_category_audit.json` already exists as output, but there is no checked-in generator script.
- That report shows a broad `crypto`-tagged open-event universe of `115` markets, mostly altcoin or airdrop noise, while the actual fast-market set came from series/slug discovery and resolved to `6` BTC candle markets.

## Goal
Create a reproducible audit script that separates the noisy broad crypto universe from the actual fast BTC/ETH candle lanes the bot could trade.

## Required Work
1. Create `scripts/crypto_category_audit.py`.
2. Pull the open Gamma events feed and classify crypto-tagged markets into:
   - `btc_candle`
   - `eth_candle`
   - `altcoin_meme`
   - `crypto_other`
3. Also derive the fast-market set using the current repo logic, preferably via `src.pipeline_refresh.load_fast_markets(...)` or an equivalent shared helper.
4. Write `reports/crypto_category_audit.json` with:
   - counts for the broad crypto-tagged universe
   - counts for the actual fast-market tradeable set
   - sample markets for each class
   - a recommendation
5. Recommendation rules:
   - `APPROVE_BTC_CANDLES_ONLY` if the fast-market set is only BTC/ETH candle contracts with clear resolution mechanics
   - `ADD_SUBCATEGORY_FILTER` if any altcoin or meme markets enter the fast-market reachable set
6. Add `tests/test_crypto_category_audit.py` for classification logic and report-shape coverage.

## Deliverables
- `scripts/crypto_category_audit.py`
- `tests/test_crypto_category_audit.py`
- Updated `reports/crypto_category_audit.json`

## Verification
- `python3 scripts/crypto_category_audit.py`
- `python -m pytest tests/test_crypto_category_audit.py`

## Constraints
- Use concrete counts from the run you perform. Do not hardcode the earlier "8 markets" claim.
- Keep the audit simple and deterministic. Keyword and pattern classification is fine.
- Do not widen runtime category rules in this task; this task is evidence generation, not policy change.

---

# ════════════════════════════════════════════════════════
# TASK 04: Harden Signal Attribution and Fix Cross-Platform Async Reentrancy
# ════════════════════════════════════════════════════════

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

---

# ════════════════════════════════════════════════════════
# TASK 05: Finish the Health-Monitoring Runtime Surface
# ════════════════════════════════════════════════════════

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

---

# ════════════════════════════════════════════════════════
# TASK 06: Validate and Finish Wallet-Flow Bootstrap on Startup
# ════════════════════════════════════════════════════════

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Preferred path ownership: `bot/wallet_flow_detector.py`, `tests/test_wallet_flow_detector.py`, `tests/test_wallet_flow_init.py`
- Avoid `scripts/deploy.sh` here. Task 07 owns deploy-script changes.

## Machine Truth (March 9, 2026)
- `reports/wallet_flow_bootstrap_20260309T002535Z.json` shows the local bootstrap artifacts are ready: `80` scored wallets with fresh `data/smart_wallets.json` and `data/wallet_scores.db`.
- `JJLive` now has `_wallet_flow_bootstrap_status()` and `_maybe_initialize_wallet_flow_bootstrap()`, and `bot/wallet_flow_detector.py` already exposes `ensure_bootstrap_artifacts(...)`.
- `tests/test_wallet_flow_init.py` already exists and covers part of this flow.
- The earlier VPS failure was operational: the remote runtime did not have usable wallet-flow bootstrap artifacts and logged `No smart wallet scores found`.

## Goal
Treat this as a validate-and-harden task, not a blank-slate implementation. Prove the startup bootstrap path works, and patch only the remaining gaps if you find them.

## Required Work
1. Audit the existing startup path:
   - `bot/wallet_flow_detector.py`
   - `bot/jj_live.py` wallet-flow bootstrap hooks
   - `tests/test_wallet_flow_init.py`
2. If the current implementation is sufficient, keep code changes minimal and strengthen tests only where evidence is missing.
3. If a real gap remains, fix it in the wallet-flow bootstrap path without changing the scoring algorithm.
4. Cover at least these cases in tests:
   - bootstrap artifacts already present
   - database exists but JSON needs regeneration
   - rebuild attempt fails but the bot degrades gracefully
   - startup does not require a human to run `--build-scores` manually

## Deliverables
- Minimal wallet-flow bootstrap hardening, only if needed
- Updated tests proving the startup path is deterministic

## Verification
- `python -m pytest tests/test_wallet_flow_detector.py tests/test_wallet_flow_init.py`

## Constraints
- Do not change wallet-scoring thresholds or the scoring formula.
- Do not edit `scripts/deploy.sh` in this task.
- If you conclude the startup path is already correct, say so in code comments/tests rather than forcing a gratuitous refactor.

---

# ════════════════════════════════════════════════════════
# TASK 07: Upgrade deploy.sh for Real VPS-Without-Git Deploys
# ════════════════════════════════════════════════════════

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Path ownership for this task: `scripts/deploy.sh`, `tests/test_deploy_script.py`
- This task owns deploy-script integration for Tasks 01, 05, and 06.

## Machine Truth (March 9, 2026)
- The VPS deploy target is a file-copy install, not a git checkout.
- `scripts/deploy.sh` currently syncs `bot/*.py`, runtime profile JSON files, and a thin slice of `polymarket-bot/src/`.
- It does **not** support `--clean-env`, `--profile`, or `--restart`.
- It does **not** currently sync wallet-flow bootstrap artifacts such as `data/smart_wallets.json` and `data/wallet_scores.db`.
- It also does not sync the deeper `polymarket-bot/src/core/` files that `src.telegram` depends on.
- `reports/deploy_20260309T013604Z.json` showed three concrete deploy-time problems:
  - remote mode contract absent from `.env`
  - wallet-flow bootstrap missing on the VPS
  - cross-platform/Telegram-adjacent runtime issues visible only after deploy

## Goal
Turn `scripts/deploy.sh` into a complete, backward-compatible one-command deploy for the scp-only VPS.

## Required Work
1. Add shell flag parsing for:
   - `--clean-env`
   - `--profile <name>` with default `live_aggressive`
   - `--restart`
   - keep the existing positional VPS target override working
2. Integrate Task 01's `scripts/clean_env_for_profile.sh` on the remote host when `--clean-env` is passed.
3. Sync the full runtime-profile contract:
   - prefer globbing `config/runtime_profiles/*.json` over a hardcoded list
4. Sync all runtime files needed for Telegram and health monitoring:
   - at minimum, the `polymarket-bot/src/core/` modules required by `src.telegram`
5. Sync wallet-flow bootstrap artifacts if they exist locally:
   - `data/smart_wallets.json`
   - `data/wallet_scores.db`
6. Never overwrite remote `jj_state.json`.
7. Add post-deploy verification that prints:
   - selected runtime profile
   - YES/NO thresholds
   - execution mode and paper/live flags
   - crypto category priority
   - wallet-flow bootstrap readiness if feasible
8. If `--restart` is passed, restart `jj-live.service` and show recent log lines.

## Deliverables
- Updated `scripts/deploy.sh`
- Updated `tests/test_deploy_script.py`

## Verification
- `bash -n scripts/deploy.sh`
- `python -m pytest tests/test_deploy_script.py`

## Constraints
- Backward compatibility matters: no-arg behavior should stay equivalent to today's sync-only deploy.
- Do not deploy `.env` from local disk.
- Do not overwrite remote runtime state files like `jj_state.json`.
- Do not SSH manually outside what the deploy script itself does.

---

# ════════════════════════════════════════════════════════
# TASK 08: Prove the Low-Price CLOB Minimum-Order Behavior
# ════════════════════════════════════════════════════════

## Working Context
- Repo: `/Users/johnbradley/Desktop/Elastifund`
- Read first: `README.md`, `docs/REPO_MAP.md`, `PROJECT_INSTRUCTIONS.md`
- Preferred path ownership: `tests/test_clob_min_order.py`
- Touch `bot/jj_live.py` only if the tests prove a real logic bug.

## Machine Truth (March 9, 2026)
- `bot/jj_live.py` already defines `_CLOB_HARD_MIN_SHARES = 5.0`, `_CLOB_HARD_MIN_NOTIONAL_USD = 5.0`, and `clob_min_order_size(price)` as `max(min_shares, 5 USD / price)`.
- The live-order path around `bot/jj_live.py:3890` hard-skips orders below the live minimum.
- The paper/shadow execution path around `bot/jj_live.py:6230` bumps undersized orders up to the minimum unless that bump would exceed `2x` `MAX_POSITION_USD`.
- `reports/deploy_20260309T013604Z.json` recorded a skipped low-price order, but that same report also said the remote `.env` was still forcing `PAPER_TRADING=false` with stale override behavior. The first question is whether the skip was a real sizing bug or just the bad `$0.50` position cap from the remote env.

## Goal
Write the missing edge-case tests first, then patch code only if the tests expose an actual mistake.

## Required Work
1. Add a focused test file such as `tests/test_clob_min_order.py`.
2. Cover at least these cases:
   - `$5.00` at price `$0.13` should satisfy the `$5` notional minimum
   - `$0.50` at price `$0.13` should fail
   - `$5.00` at price `$0.90` should still satisfy the live minimum
   - a bumped order that would exceed `2x MAX_POSITION_USD` should still be skipped in the paper/shadow path
3. If the logic is already correct, leave production code alone and document through tests that the bad env override was the root cause.
4. If you find a real bug, patch the smallest possible unit of logic in `bot/jj_live.py`.

## Deliverables
- `tests/test_clob_min_order.py`
- A code change in `bot/jj_live.py` only if the tests prove one is needed

## Verification
- `python -m pytest tests/test_clob_min_order.py`

## Constraints
- Do not change `_CLOB_HARD_MIN_SHARES`.
- Do not change `_CLOB_HARD_MIN_NOTIONAL_USD`.
- Do not change Kelly sizing or `MAX_POSITION_USD`.
- Prefer pure-function and small helper tests over a full end-to-end JJ cycle unless you truly need the larger harness.
