# CODEX TASK 03: Check In the Crypto Category Audit

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
- Use concrete counts from the run you perform. Do not hardcode the earlier “8 markets” claim.
- Keep the audit simple and deterministic. Keyword and pattern classification is fine.
- Do not widen runtime category rules in this task; this task is evidence generation, not policy change.
