# CODEX TASK 03: Crypto Market Category Audit

## MACHINE TRUTH (2026-03-09)
- paper_aggressive and live_aggressive profiles set crypto priority = 2
- All 8 markets passing 0.08/0.03 threshold are BTC crypto
- Category gate was blocking ALL tradeable markets (crypto priority was 0)
- Risk: enabling crypto might expose system to meme coin / degenerate markets
- Need to verify the 8 markets are legitimate BTC price candles

## TASK
Create `scripts/crypto_category_audit.py` that:
1. Pulls all active markets from Polymarket Gamma API (gamma-api.polymarket.com)
2. Filters to category = "crypto" or tag contains "crypto", "bitcoin", "btc", "ethereum"
3. For each crypto market, classify as:
   - `btc_candle`: BTC price above/below X by specific datetime (clear resolution)
   - `eth_candle`: ETH price above/below X by specific datetime
   - `altcoin`: Any other specific coin price
   - `meme_degenerate`: Meme coins, pump timing, vague resolution
   - `crypto_other`: Regulatory, adoption, exchange-related
4. Output `reports/crypto_category_audit.json`:
   ```json
   {
     "generated_at": "ISO timestamp",
     "total_crypto_markets": 110,
     "classifications": {
       "btc_candle": [...],
       "eth_candle": [...],
       "altcoin": [...],
       "meme_degenerate": [...],
       "crypto_other": [...]
     },
     "tradeable_at_008": [
       {"market_id": "...", "question": "...", "class": "btc_candle", "price": 0.X, "resolution_hours": Y}
     ],
     "recommendation": "APPROVE" or "ADD_SUBCATEGORY_FILTER"
   }
   ```
5. If any meme/degenerate markets pass the 0.08 threshold, recommend a sub-filter

## CONSTRAINTS
- Use Gamma API directly (no API key needed): GET https://gamma-api.polymarket.com/markets
- Classification can use simple keyword matching (no LLM needed)
- Keywords for btc_candle: "BTC", "Bitcoin", "above $", "below $", candle timeframes
- Script must be runnable as: `python3 scripts/crypto_category_audit.py`

## FILES
- `scripts/crypto_category_audit.py` (CREATE)
- `reports/crypto_category_audit.json` (GENERATED OUTPUT)
- `tests/test_crypto_audit.py` (CREATE — test classification logic with sample data)

## SUCCESS CRITERIA
- Audit runs successfully against live Gamma API
- All 8 tradeable markets classified
- Recommendation generated: APPROVE if all btc_candle, ADD_SUBCATEGORY_FILTER if meme found
- `make test` passes including new test
