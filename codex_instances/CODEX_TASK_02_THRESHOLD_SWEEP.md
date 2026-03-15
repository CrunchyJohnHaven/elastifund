# CODEX TASK 02: Check In a Real Threshold Sweep Script

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
- Do not claim “8 markets” unless the script actually observes 8 on the run you execute. Earlier March 8 prose said 8, but the latest checked-in fast-market artifact shows 6.
- Keep the output explicit about the difference between threshold reachability and a real dispatchable trade set.
