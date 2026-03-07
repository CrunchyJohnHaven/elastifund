# AUDIT_REPORT
Date: 2026-03-07
Scope: `polymarket-bot/src/` + `jj_live.py`

## Bugs Found

### Critical
- `jj_live.py` double-calibration risk in VPS bridge path (fixed)
  - File: `/Users/johnbradley/Desktop/Elastifund/jj_live.py:1540-1573`
  - Issue: if upstream payload already had `calibrated_probability`, the bridge recalibrated it again.
  - Fix: added `already_calibrated` handling in `compute_calibrated_signal(...)` and raw-probability-first selection.

- VPS signal mapping could crash on non-numeric probability/confidence (fixed)
  - File: `/Users/johnbradley/Desktop/Elastifund/jj_live.py:456-487`, `/Users/johnbradley/Desktop/Elastifund/jj_live.py:1577-1593`
  - Issue: direct `float(...)` casts on mixed external payloads could raise and abort cycle.
  - Fix: `_safe_float`, `normalize_confidence`, and `map_vps_signal_direction` added and wired.

### High
- Safety rails did not enforce max concurrent position count (fixed)
  - File: `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/src/safety.py:39-97`
  - Issue: daily loss/exposure/per-trade checks existed, but no open-position cap gate.
  - Fix: added `open_positions_count` input and `max_open_positions` check.

- Missing config knob for position-count rail (fixed)
  - File: `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/src/core/config.py:118`
  - Fix: added `max_open_positions` setting.

### Medium
- Engine bankroll estimate likely under-specified
  - File: `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/src/engine/loop.py:295`
  - Observation: `bankroll = total_exposure + settings.max_position_usd` uses a config cap as cash proxy; this can mis-size positions.

- Potential unit mismatch in safety pre-trade check
  - File: `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/src/engine/loop.py:358`
  - Observation: `trade_size_usd=size * price` assumes `size` is shares; sizing pipeline returns USD-sized amount.

- Calibration behavior inconsistency with target mappings (fixed)
  - File: `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/src/claude_analyzer.py:101-122`, `/Users/johnbradley/Desktop/Elastifund/jj_live.py:144-155`
  - Issue: original function mapped 50% to ~40%; did not meet expected 50% invariant.
  - Fix: symmetry-preserving calibration (`0.5 -> 0.5`, `0.1 -> ~0.29`, while preserving high-probability compression).

## Test Coverage Gaps
- No end-to-end async integration test for full cycle `scan -> analyze -> calibrate -> size -> execute` under mixed failures/timeouts.
- No regression test validating unit semantics (`USD` vs `shares`) across `compute_sizing -> broker.place_order -> safety`.
- Ensemble and backtester lack dedicated test modules in this pass.

## Critical Fixes Implemented
- `jj_live.py`
  - safer repository path bootstrap for `src` imports.
  - safe signal mapping + confidence normalization helpers.
  - no double-calibration in VPS bridge path.
- `polymarket-bot/src/safety.py`
  - max open positions rail.
- `polymarket-bot/src/core/config.py`
  - `max_open_positions` setting.
- `polymarket-bot/src/engine/loop.py`
  - passes `open_positions_count` into safety check.
- `polymarket-bot/src/claude_analyzer.py`
  - calibration mapping corrected to match required targets.

## New Tests Added
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/tests/test_calibration.py`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/tests/test_kelly_sizing.py`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/tests/test_safety_rails.py`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/tests/test_signal_mapping.py`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/tests/test_category_filter.py`
- `/Users/johnbradley/Desktop/Elastifund/polymarket-bot/tests/test_fee_awareness.py`

Result: `21 passed` for the requested suite.
