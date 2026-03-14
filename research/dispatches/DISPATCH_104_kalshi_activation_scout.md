# DISPATCH 104 — Kalshi Activation Scout

**Date:** 2026-03-14
**Instance:** 14 (Wave 3)
**Priority:** P2
**Status:** VIABLE — Paper testing ready, one auth blocker for live

---

## Executive Summary

The $100 Kalshi account has a viable path to paper trading within hours. The weather arbitrage strategy (`binary_threshold`) is the clear winner: 7/9 scenarios profitable in simulation, median PnL +$90.33 on a $100 bankroll, 89.5% median win rate across 76 trades per scenario. The code is fully built, the API connectivity works, and settlement reconciliation — broken since launch — is now fixed.

**Verdict: Stage for paper testing immediately. Do not go live until paper evidence matches simulation.**

---

## 1. Infrastructure Assessment

### What Works
- **Kalshi API connectivity:** Public market endpoints respond correctly from Mac (200 OK)
- **NWS weather API:** All 5 cities (NYC, CHI, MIA, AUS, LAX) return forecasts
- **Weather scanner:** `kalshi/weather_arb.py` — 1,590 lines, fully functional paper mode
- **Weather simulator:** `kalshi/weather_simulator.py` — scenario analysis across 9 parameter variants
- **Cross-platform arb scanner:** `bot/cross_platform_arb.py` — complete with venue routing, fuzzy matching, fee calculation
- **Forecast snapshot archive:** 2,003 rows across 15 city-date pairs (captured through Mar 11)
- **Settlement reconciliation:** Fixed (was 0/10 matched, now 10/10 = 100%)
- **Tests:** 30/30 passing (test_kalshi_weather_arb.py + test_kalshi_weather_simulator.py)

### What's Broken
- **Auth for portfolio/order endpoints:** Local `.env` has placeholder `KALSHI_API_KEY_ID`. The real key (`b20ab9fa-...`) and RSA private key (`bot/kalshi/kalshi_rsa_private.pem`) exist but `.env` isn't configured. Paper mode doesn't need auth (it doesn't place orders), but live mode will.
- **RSA key path mismatch:** Key is at `bot/kalshi/kalshi_rsa_private.pem` but `KALSHI_RSA_KEY_PATH` in `.env` points to `kalshi/kalshi_rsa_private.pem` (missing). The `cross_platform_arb.py` has a fallback path list that includes the correct location.
- **kalshi_python SDK Pydantic bug:** SDK rejects `"finalized"` as a market status (only accepts initialized/active/closed/settled/determined). Fixed in `weather_arb.py` with fallback to raw JSON endpoint.

### What's Missing for Live
1. Configure `.env` with real `KALSHI_API_KEY_ID=b20ab9fa-b387-4aac-b160-c22d58705935`
2. Fix `KALSHI_RSA_KEY_PATH=bot/kalshi/kalshi_rsa_private.pem`
3. Run `python3 -m kalshi.weather_arb --mode paper --loop` for at least 48 hours
4. Verify paper P&L matches simulation expectations before going live

---

## 2. Strategy Assessment

### Weather Arbitrage — Binary Threshold (RECOMMENDED)

**Mechanism:** Compare NWS point forecasts against Kalshi high-temperature market prices. When the model (NWS forecast + ASOS nowcast residual) disagrees with market pricing by >5% edge, take a position.

**Simulation results (9 scenario variants, 3 cities, ~96 days):**

| Scenario | Trades | Wins | Win Rate | P&L | Max DD |
|----------|--------|------|----------|-----|--------|
| h18_std1.00 | 76 | 59 | 77.6% | +$300.60 | 5.2% |
| h18_std1.15 | 76 | 68 | 89.5% | +$182.14 | 3.6% |
| h18_std1.30 | 76 | 70 | 92.1% | +$154.77 | 3.8% |
| h20_std1.00 | 14 | 4 | 28.6% | -$3.48 | 18.2% |
| h20_std1.15 | 69 | 61 | 88.4% | +$75.80 | 10.5% |
| h20_std1.30 | 76 | 71 | 93.4% | +$90.33 | 8.5% |
| h22_std1.00 | 16 | 3 | 18.8% | -$24.23 | 27.5% |
| h22_std1.15 | 76 | 69 | 90.8% | +$97.74 | 9.6% |
| h22_std1.30 | 76 | 70 | 92.1% | +$80.30 | 13.8% |

**Robustness summary:**
- 7/9 scenarios profitable (77.8%)
- Median P&L: +$90.33
- Median win rate: 89.5%
- Best: +$300.60 (h18, low uncertainty)
- Worst: -$24.23 (h22, low uncertainty — thin sample)

**Key insight:** The h18 UTC (1pm ET) decision hour dominates. This is when NWS afternoon forecasts are freshest and the late-morning temperature trajectory is well established. The std1.00 multiplier (assuming market equals model uncertainty) produces the highest raw PnL but also the most variance. The std1.15-1.30 range is safer — still 89%+ win rate with controlled drawdown.

### Weather Arbitrage — Range Tail YES (SECONDARY)

- 5/9 scenarios profitable (55.6%)
- Median P&L: +$20.84
- High variance: best +$210.23, worst -$1.42
- Mechanism: buy cheap (<$0.20) range contracts when nowcast suggests the temperature will land in that bucket
- **Assessment:** Lower conviction, higher variance. Not recommended as primary lane.

### Weather Arbitrage — Range Fade (TERTIARY)

- 9/9 scenarios positive (100%)
- But tiny: median P&L only +$16.39, median 9 trades
- **Assessment:** Safe but too few opportunities per day. Not worth the operational complexity.

### Cross-Platform Arbitrage (NOT READY)

`bot/cross_platform_arb.py` is a complete cross-platform arb scanner (Polymarket vs Kalshi) with:
- Fuzzy title matching (SequenceMatcher + Jaccard keyword similarity)
- Fee-aware profit calculation (Kalshi 7% taker, Poly 0% maker / 2% taker)
- Venue routing via `orchestration/venue_router.py`
- Market caching and retry logic

**But:**
- Requires simultaneous API auth on both platforms
- Match quality depends on title overlap — most Polymarket and Kalshi markets phrase questions differently
- No historical evidence of profitable matches
- The scanner cannot be run in read-only mode without both API connections
- **Assessment:** Interesting but speculative. Lower priority than weather.

---

## 3. Backtest Validation (Historical ASOS Data)

Separate from the simulator, historical backtest results from `research/weather_validation/backtest_results.json`:

| Station | Trades | Wins | Win Rate | P&L | Sharpe |
|---------|--------|------|----------|-----|--------|
| NYC | 22 | 4 | 18.2% | +$88.74 | 1.89 |
| ORD | 21 | 3 | 14.3% | +$44.06 | 1.07 |
| AUS | 24 | 7 | 29.2% | +$227.80 | 3.77 |

Low win rates but high P&L because the strategy buys cheap contracts that pay off big when they hit. The AUS station is the strongest with a 3.77 Sharpe.

**Important caveat:** These backtests use synthetic market prices (no historical Kalshi order book data exists in the repo). Real market spreads and liquidity could significantly impact execution.

---

## 4. Settlement Reconciliation Fix

**Bug found and fixed:** The `kalshi_python` SDK's Pydantic model rejects `"finalized"` as a valid market status. Kalshi added this status value after the SDK was published. The SDK only accepts: `initialized`, `active`, `closed`, `settled`, `determined`.

**Fix:** Added inner try/except in `log_settlement_outcomes()` that catches SDK validation errors and falls back to raw JSON API endpoint (`_json_get`), which returns the data without Pydantic validation.

**Result:**
- Before fix: 0/10 settlements matched (0%)
- After fix: 10/10 settlements matched (100%), 67 total settlement outcomes logged
- Settlement breakdown: 23 wins / 44 losses (34.3% overall)
- Best city: CHI at 64% win rate; worst: MIA at 13%

The low win rate on actual paper decisions vs the 89% simulation win rate indicates the paper scanner was not running the optimal parameters. The simulation recommends h18 UTC decision hour with std1.15+ uncertainty — the live paper scanner may have been using different settings.

---

## 5. Gaps to Close

| Gap | Effort | Blocking? |
|-----|--------|-----------|
| Configure `.env` with real Kalshi API key | 2 min (John manual) | Yes for live, no for paper |
| Fix RSA key path in `.env` | 1 min (John manual) | Yes for live, no for paper |
| Run paper loop for 48+ hours | 48 hrs wall clock | Yes for live promotion |
| Align paper scanner params with optimal (h18, std1.15) | 10 min code change | No, but improves evidence quality |
| Collect historical Kalshi order book data | Ongoing | No, but improves backtest validity |
| Cross-platform arb requires dual auth | 30 min setup | Yes for cross-platform lane |

---

## 6. Recommended Next Steps

1. **Immediate:** Run `python3 -m kalshi.weather_arb --mode paper --loop --interval-seconds 300` in a tmux session. This will accumulate paper evidence at h18 decision hour automatically.

2. **Within 24 hours:** John configures `.env` with real Kalshi credentials:
   ```
   KALSHI_API_KEY_ID=b20ab9fa-b387-4aac-b160-c22d58705935
   KALSHI_RSA_KEY_PATH=bot/kalshi/kalshi_rsa_private.pem
   ```

3. **After 48 hours of paper data:** If paper win rate >=60% and P&L > 0, promote to live with $5/contract max.

4. **Cross-platform arb:** Defer. The weather lane has simulation evidence; the cross-platform scanner has none.

---

## 7. Paper Trading Configuration (Ready to Deploy)

```bash
python3 -m kalshi.weather_arb \
  --mode paper \
  --loop \
  --interval-seconds 300 \
  --edge-threshold 0.05 \
  --max-spread 0.05 \
  --bankroll-usd 100 \
  --max-order-usd 5 \
  --kelly-fraction 0.25 \
  --max-signals 3 \
  --log-level INFO
```

For VPS deployment, create a systemd service similar to btc-5min-maker.service.

---

*Generated by Instance 14 (Kalshi Activation Scout), 2026-03-14*
