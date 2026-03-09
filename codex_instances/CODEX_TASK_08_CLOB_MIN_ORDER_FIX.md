# CODEX TASK 08: Fix CLOB Minimum Order Size Logic

## MACHINE TRUTH (2026-03-09)
- VPS log: "SKIP (3.85 shares / $0.50 below live min 38.47 shares / $5.00)"
- The $0.50 position came from .env override (will be fixed by Task 01/07)
- BUT: even with $5.00 position, at price=0.13, that's only 38.5 shares
- CLOB minimum: 5 shares AND $5 notional (whichever is larger)
- At low prices (crypto candle NO tokens at $0.13), $5 notional = 38.5 shares
- Kelly sizing at $247.51 bankroll with 0.25 fraction on 37% edge = ~$23
- But MAX_POSITION_USD caps at $5, so effective position = $5
- $5 at $0.13 = 38.5 shares, which passes the 5-share minimum but needs $5 notional

## TASK
1. Read `bot/jj_live.py` around the SKIP logic (search for "SKIP.*below live min")
2. Trace the full order sizing path:
   - Kelly calculation → cap at MAX_POSITION_USD → convert to shares → check vs CLOB min
3. Verify that with paper_aggressive/live_aggressive settings:
   - MAX_POSITION_USD = $5.00
   - For a BTC candle NO token at price $0.13: shares = $5.00 / $0.13 = 38.5
   - CLOB min shares = 5.0, CLOB min notional = $5.00
   - $5.00 / $0.13 = 38.5 shares → passes both minimums → SHOULD NOT SKIP
4. If the logic is wrong (comparing against wrong minimum), fix it
5. If the logic is right but the position was $0.50 (the .env bug), confirm that Task 01/07 fix resolves this
6. Add a test specifically for low-price token order sizing:
   - Test: price=$0.13, position=$5.00 → should NOT skip
   - Test: price=$0.13, position=$0.50 → should skip (below $5 notional)
   - Test: price=$0.90, position=$5.00 → should NOT skip (5.6 shares, $5 notional)

## FILES
- `bot/jj_live.py` (READ, possibly MODIFY if logic bug found)
- `tests/test_clob_min_order.py` (CREATE)

## CONSTRAINTS
- Do NOT change CLOB minimum constants (_CLOB_HARD_MIN_SHARES=5.0, _CLOB_HARD_MIN_NOTIONAL_USD=5.0)
- Do NOT change Kelly sizing or MAX_POSITION_USD
- `make test` must pass

## SUCCESS CRITERIA
- Clear documentation of the order sizing path for crypto candle tokens
- Test cases cover edge cases at various price points
- Confirmed: with live_aggressive profile ($5 position), orders will NOT skip
- `make test` passes
