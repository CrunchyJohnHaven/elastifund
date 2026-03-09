# CODEX TASK 08: Prove the Low-Price CLOB Minimum-Order Behavior

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
