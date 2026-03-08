# Weather Bracket Arbitrage: Edge Validation Report

**Dispatch:** Kalshi Weather Bracket Arbitrage — Edge Validation
**Priority:** P0 | **Target:** Claude Code | **Status:** COMPLETED
**Date:** March 7, 2026 | **Author:** JJ (Claude Code)
**Capital at stake:** $100 USD on Kalshi

## Expected ARR: ~457% on $100 Capital (THEORETICAL) / ~0% REALIZABLE
## Verdict: NO-GO

### Why This Research Was Conducted

A research report identified a potential structural edge in Kalshi's daily high-temperature markets: the NWS Daily Climate Report (which Kalshi uses for settlement) derives from raw ASOS METAR Celsius readings that undergo integer rounding before Fahrenheit conversion. This double-rounding can push the official reported temperature across Kalshi's 2°F bracket boundaries in ways that consumer weather apps (which retail traders use) do not predict. The research claimed 500-1500% ROI per bracket-crossing trade. If validated, this would be a rare structural arbitrage — an information edge baked into the settlement mechanics themselves, independent of forecasting skill.

Our job: validate whether this edge actually exists in historical data, quantify it, and produce a go/no-go decision for the $100 funded on Kalshi.

### Executive Summary

The METAR rounding discrepancy is **mathematically real** — NWS double-rounding produces a different integer Fahrenheit than consumer apps ~48% of the time, crossing a Kalshi 2°F bracket boundary ~23% of days. However, the edge is **not exploitable in practice** for three independent reasons, any one of which would kill the strategy alone:

1. **Input problem:** The rounding math requires knowing the actual daily max Celsius to ±0.1°C. Weather forecasts have ±1.5°C uncertainty — 15x too imprecise. By the time you know the actual max, the market is closed.
2. **Model accuracy problem:** Even using real ASOS readings as input, our rounding model predicted the official NWS settlement only 27-35% of the time. Hourly snapshots miss the true continuous daily max by up to 7°F.
3. **Pricing problem:** At realistic entry prices ($0.25-$0.40 for adjacent brackets, not the fantasy $0.10), the 21% empirical win rate produces negative expected value.

**This edge exists in a textbook but not on a trading screen.**

---

### 1. The Rounding Model

**NWS Climatological Report Protocol (Confirmed):**

Kalshi settles against: *"the highest temperature recorded in [city] as reported by the National Weather Service's Climatological Report (Daily)"* — confirmed directly from Kalshi market rules via API.

The NWS Daily Climate Report derives from ASOS METAR readings. METAR reports temperature as integer Celsius. The conversion pathway:

```
Raw sensor → METAR integer °C → convert to °F → round to integer °F
```

**Consumer weather apps** typically get raw data and convert directly:
```
Raw sensor °C → convert to °F → round to integer °F
```

The intermediate integer rounding in Celsius can cause a ±1°F difference in the final Fahrenheit reading.

**Discrepancy Zones Mapped (full -10°C to 45°C range relevant to target cities):**

| Celsius Range | NWS °F | Consumer °F | Diff | Bracket Cross |
|---------------|--------|-------------|------|---------------|
| -9.5 to -9.2 | 16 | 15 | +1 | YES |
| -8.5 to -8.1 | 18 | 17 | +1 | YES |
| -6.9 to -6.6 | 19 | 20 | -1 | YES |
| -5.8 to -5.6 | 21 | 22 | -1 | YES |
| -1.5 to -1.4 | 30 | 29 | +1 | YES |
| 0.5 to 0.8 | 34 | 33 | +1 | YES |
| 1.5 to 1.9 | 36 | 35 | +1 | YES |
| 3.1 to 3.4 | 37 | 38 | -1 | YES |
| 4.2 to 4.4 | 39 | 40 | -1 | YES |
| 5.3 to 5.4 | 41 | 42 | -1 | YES |
| 8.5 to 8.6 | 48 | 47 | +1 | YES |
| 10.5 to 10.8 | 52 | 51 | +1 | YES |
| 13.1 to 13.4 | 55 | 56 | -1 | YES |
| 14.2 to 14.4 | 57 | 58 | -1 | YES |
| 18.5 to 18.6 | 66 | 65 | +1 | YES |
| 20.5 to 20.8 | 70 | 69 | +1 | YES |
| 21.5 to 21.9 | 72 | 71 | +1 | YES |
| 23.1 to 23.4 | 73 | 74 | -1 | YES |
| 24.2 to 24.4 | 75 | 76 | -1 | YES |
| 28.5 to 28.6 | 84 | 83 | +1 | YES |
| 30.5 to 30.8 | 88 | 87 | +1 | YES |
| 33.1 to 33.4 | 91 | 92 | -1 | YES |

**Total exploitable zones:** 44 bracket-crossing zones out of 88 total discrepancy zones in the -10°C to 45°C range. The discrepancy is always exactly ±1°F.

**Rounding variant impact:** Standard rounding vs banker's rounding produces identical bracket-crossing counts (44 zones). Truncation produces more discrepancies (60 bracket-crossing zones) but doesn't match observed data.

---

### 2. Historical Backtest Results

**Data source:** Iowa Environmental Mesonet (IEM) ASOS download service — real historical hourly METAR observations. Gold standard source, same data feed NWS uses.

**Date range:** December 1, 2025 — March 7, 2026 (96-97 days per station)

**Rounding Model Accuracy vs Official NWS Daily High:**

| Model | NYC | ORD | AUS | Description |
|-------|-----|-----|-----|-------------|
| NWS Standard Rounding | 27.1% | 34.4% | 35.4% | Round C int → convert → round F |
| NWS Banker's Rounding | 27.1% | 34.4% | 35.4% | Same with Python round() |
| NWS Truncation | 16.7% | 19.8% | 10.4% | Floor C → convert → round F |
| METAR Integer | 27.1% | 34.4% | 35.4% | Same as standard (METAR gives int C) |
| ASOS Direct Reported °F | 43.8% | 56.2% | 43.8% | Use ASOS hourly max_tmpf as-is |

**Critical finding:** None of the rounding models achieve even 50% accuracy. The "direct reported" ASOS hourly max Fahrenheit is the best predictor and it's only 44-56% accurate. This is because:

1. **Hourly ASOS readings sample once per hour** — they miss the actual temperature peak that occurs between readings
2. **The NWS daily max comes from continuous temperature traces**, not hourly snapshots
3. **The official daily max can differ significantly** from the highest hourly reading (we observed differences of up to 7°F)

**Per-station backtest results:**

| Station | Days | Discrepancies | Bracket Crossings | NWS Model Right | Consumer Model Right |
|---------|------|---------------|-------------------|-----------------|---------------------|
| KNYC (Central Park) | 96 | 47 (49.0%) | 22 (22.9%) | 27.1% | 43.8% |
| KORD (O'Hare) | 96 | 54 (56.2%) | 21 (21.9%) | 34.4% | 56.2% |
| KAUS (Austin) | 96 | 43 (44.8%) | 24 (25.0%) | 35.4% | 43.8% |
| **Combined** | **288** | **144 (50.0%)** | **67 (23.3%)** | **32.3%** | **47.9%** |

**Predictability (max temp settled by 8pm UTC / ~2pm local):**

| Station | Days | Max Settled by 2pm | Rate |
|---------|------|--------------------|------|
| KNYC | 96 | 91 | 94.8% |
| KORD | 96 | 88 | 91.7% |
| KAUS | 96 | 64 | 66.7% |

Austin's lower predictability reflects warmer weather with afternoon heating continuing past 2pm.

---

### 3. Simulated Trading P&L

**Assumptions (all explicitly stated):**
- Entry price: $0.10 per contract (bracket priced as 10% likely — longshot odds)
- Position size: $5 per trade (5% of $100 bankroll)
- Contracts per trade: 50 ($5 / $0.10)
- Win payout: $1.00 per contract (net $0.90 profit per contract on win)
- Loss: -$5.00 (entire position lost)
- Kalshi taker fee: 7% × price × (1-price) per contract, capped at $0.07
- Trade every bracket-crossing day where NWS model predicts different bracket than consumer model
- Win = NWS model was correct and official settles in our bracket

| Metric | NYC | ORD | AUS | Combined |
|--------|-----|-----|-----|----------|
| Total tradeable days (96d) | 22 | 21 | 24 | 67 |
| Wins | 4 | 3 | 7 | 14 |
| Losses | 18 | 18 | 17 | 53 |
| Win rate | 18.2% | 14.3% | 29.2% | 20.9% |
| Avg entry price assumption | $0.10 | $0.10 | $0.10 | $0.10 |
| Avg profit per trade | $4.03 | $2.10 | $9.49 | $5.38 |
| Total simulated P&L | $88.74 | $44.06 | $227.80 | $360.60 |
| **Annualized Return Rate (ARR)** | **337%** | **168%** | **866%** | **~457%** |
| Sharpe ratio | 1.89 | 1.07 | 3.77 | ~2.2 |
| Max single-day risk | $5.00 | $5.00 | $5.00 | $5.00 |

**WHY THESE NUMBERS ARE MISLEADING:**

The positive P&L is entirely an artifact of the **$0.10 entry price assumption** combined with a 21% win rate. At $0.10 entry, you need only >10% win rate to profit. But this assumption is critically flawed:

1. **The correct bracket won't be priced at $0.10.** If the market expects 62-63°F (e.g., based on weather forecasts), that bracket will be priced at $0.25-$0.50, not $0.10. The "wrong" bracket based on rounding would be adjacent (e.g., 64-65°F) and also priced significantly above $0.10.

2. **You can't identify which bracket is "wrong" in advance.** The rounding edge only matters at specific Celsius boundaries (e.g., 14.4°C vs 14.5°C). You'd need to predict the daily max to within ±0.1°C accuracy to know if you're in a discrepancy zone. Weather forecasts have ±2-3°F (±1-1.5°C) error margins.

3. **At realistic entry prices ($0.25-$0.40 for an adjacent bracket), the math inverts.** With a 21% win rate and $0.30 entry: expected value = 0.21 × $0.70 - 0.79 × $0.30 = $0.147 - $0.237 = **-$0.09 per contract (negative EV)**.

---

### 4. Sensitivity Analysis

**4a. Rounding Model Variants:**

| NWS Model | Consumer Model | Discrepancy Points | Bracket Crossings |
|-----------|---------------|-------------------|-------------------|
| Standard | Standard | 264 | 44 |
| Banker's | Standard | 270 | 44 |
| Standard | Banker's | 270 | 44 |
| Truncation | Standard | 385 | 60 |

Standard vs banker's rounding makes virtually no difference. Best-fit model could not be determined because **all models performed poorly** against actual NWS data (27-35% accuracy).

**4b. Bracket Width Sensitivity:**

| Bracket Width | Crossing Zones (of 88) | Impact |
|---------------|----------------------|--------|
| 1°F | 88 (100%) | Every discrepancy crosses |
| 2°F (Kalshi actual) | 44 (50%) | Half cross |
| 3°F | 33 (38%) | Fewer crossings |
| 5°F | 18 (20%) | Minimal edge |

Wider brackets = fewer crossings = fewer trades. At 2°F (Kalshi's actual width), the theoretical surface is reasonable but the model accuracy kills the edge.

**4c. Seasonal Variation:**

| Season | Temp Range | Discrepancy Rate |
|--------|-----------|-----------------|
| Winter (-10 to 5°C) | 14-41°F | 50.0% |
| Spring/Fall (5 to 20°C) | 41-68°F | 50.0% |
| Summer (20 to 40°C) | 68-104°F | 49.2% |

Remarkably uniform across seasons. The rounding math doesn't favor any particular temperature range. However, in practice, summer may be slightly worse because afternoon heating continues later, making the daily max harder to predict early.

---

### 5. Liquidity Assessment

**Kalshi weather markets ARE liquid.** Real data from API (March 7-8, 2026):

**NYC High Temp (Mar 8, 2026) — active market:**

| Bracket | Yes Bid | Yes Ask | Spread | Volume | Open Interest |
|---------|---------|---------|--------|--------|---------------|
| 61° or below | $0.20 | $0.24 | $0.04 | 512 | 493 |
| 62° to 63° | $0.25 | $0.26 | $0.01 | 343 | 343 |
| 64° to 65° | $0.26 | $0.27 | $0.01 | 51 | 43 |
| 66° to 67° | $0.15 | $0.16 | $0.01 | 107 | 101 |
| 68° to 69° | $0.06 | $0.08 | $0.02 | 241 | 216 |
| 70° or above | $0.03 | $0.05 | $0.02 | 22 | 22 |

**NYC High Temp (Mar 6, 2026) — settled market:**

| Bracket | Result | Volume | Open Interest |
|---------|--------|--------|---------------|
| 40° or below | No | 46,494 | 33,179 |
| **41° to 42°** | **Yes** | **57,574** | **31,026** |
| 43° to 44° | No | 57,451 | 24,546 |
| 45° to 46° | No | 28,100 | 19,551 |
| 47° to 48° | No | 12,775 | 10,964 |
| 49° or above | No | 16,505 | 15,023 |

**Key liquidity findings:**
- Volume is excellent on popular brackets: 28K-57K contracts for settled markets
- Upcoming markets have thinner volume (50-500 contracts) but tight $0.01-$0.04 spreads
- $5 positions are trivially small — no market impact
- Even $50-$100 positions would not move these markets significantly
- Settlement source confirmed: NWS Climatological Report (Daily) via Central Park

**Liquidity is NOT the bottleneck for this strategy. The edge itself is the bottleneck.**

---

### 6. Risk Factors

1. **Model accuracy is catastrophically low (27-35%).** The rounding model does not reliably predict the official NWS daily high because hourly ASOS snapshots ≠ continuous daily max.

2. **You cannot identify discrepancy zones in advance.** To know you're in a rounding discrepancy zone, you need the actual daily max Celsius to within ±0.1°C. Weather forecast uncertainty is ±1-1.5°C, which spans 5-8 Kalshi brackets.

3. **The "correct" bracket won't be priced as a longshot.** Adjacent brackets are priced at $0.15-$0.30, not $0.05-$0.10. At realistic prices with 21% win rate, expected value is negative.

4. **Other traders may already understand this.** Market makers on Kalshi likely use direct NWS data feeds. The bracket prices already incorporate NWS-protocol resolution mechanics.

5. **Temporal precision problem.** Even if you identified a discrepancy zone at 2pm local time, the temperature could continue rising. Austin showed only 67% of daily maxima were established by 2pm.

6. **Resolution timing.** Markets close at ~midnight EST but don't settle until the NWS CLI product is issued, usually the following morning. This creates overnight risk.

7. **The ±1°F difference is always exactly 1°F.** It never crosses more than one bracket boundary, so even in the best case, you're picking between two adjacent brackets — not finding a massive mispricing.

8. **Small sample validation concern.** The NWS rounding model was correct in only 14 of 67 bracket-crossing days across all stations. This is below the base rate of simply guessing the consumer-model bracket.

---

### 7. Implementation Requirements

If this were a GO (it is not), the build would require:

| Component | Estimated Effort | Notes |
|-----------|-----------------|-------|
| Real-time ASOS data feed | 1 day | IEM ASOS endpoint, poll every 5 min |
| NWS forecast integration | 1 day | Pull NWS point forecast for target stations |
| Celsius boundary detector | 0.5 day | Flag when current max is in a discrepancy zone |
| Kalshi order placement | 2 days | RSA-signed API, bracket selection, sizing |
| Settlement tracker | 1 day | Monitor NWS CLI product for resolution |
| Monitoring/alerts | 0.5 day | Telegram alerts for trades and settlement |
| **Total** | **~6 days** | |

---

### 8. Recommendation

## NO-GO

The METAR rounding arbitrage is a **beautiful theory that fails in practice**. The core research claim is technically correct: NWS double-rounding does produce different Fahrenheit values than direct conversion ~48% of the time, and this crosses Kalshi 2°F bracket boundaries ~23% of days.

**However, the edge is not exploitable because:**

1. **You can't predict the input.** The rounding math requires the actual daily max Celsius to within ±0.1°C. No weather forecast achieves this precision. By the time you know the actual max, the market is closed.

2. **Even with perfect input, the model fails.** Against 96 days of real data, the NWS rounding model predicted the official settlement temperature only 27-35% of the time. The daily max from hourly ASOS readings systematically underestimates the true daily max because it samples once per hour instead of continuously.

3. **The P&L simulation is misleading.** The positive returns depend entirely on the assumption that the correct bracket is priced at $0.10 (longshot odds). In reality, adjacent brackets are priced at $0.15-$0.30, and at those prices with a 21% empirical win rate, the strategy has negative expected value.

**What would change this to a GO (and why it's unlikely):**
- A high-frequency ASOS data source providing continuous (not hourly) temperature data — *unlikely because ASOS reports are standardized at hourly intervals; 1-minute data exists in METAR special reports but only for extreme events, not routine max tracking*
- Evidence that Kalshi markets systematically misprice adjacent brackets near rounding boundaries — *our data shows no evidence; Kalshi market makers likely already use NWS data feeds*
- A forecasting model predicting daily max within ±0.3°F (±0.17°C) — *this exceeds state-of-the-art NWP model accuracy by roughly 10x; operational NWS forecasts carry ±2-3°F uncertainty for daily highs*

---

### 9. What This Means for Kalshi Strategy

The rounding edge is dead, but the research produced valuable infrastructure and insights for the $100 Kalshi capital:

**Positive findings to build on:**
1. **Kalshi weather markets are liquid and well-structured.** 28K-57K contracts per bracket on settled NYC markets, $0.01 spreads, 2°F bracket widths, clear NWS settlement rules. This is a real, tradeable venue.
2. **Our Kalshi API access works.** Public endpoints return market-level data (events, brackets, volume, orderbook). RSA-authenticated endpoints are available for order placement when ready.
3. **The data pipeline is reusable.** IEM ASOS fetcher, NWS daily parser, and rounding model are all built and tested in `research/weather_validation/`. These can serve a forecast-based weather strategy.
4. **Settlement mechanics are confirmed and documented.** Kalshi resolves daily high temp markets via "National Weather Service's Climatological Report (Daily)" — we now know exactly what we're trading against.

**Alternative Kalshi strategies worth pursuing (ranked):**

| Strategy | Edge Source | Estimated Build | Capital Needed |
|----------|-----------|-----------------|----------------|
| **LLM ensemble bracket picker** | Use our multi-model ensemble (Claude+GPT+Groq) to predict which 2°F bracket the daily high falls in. Compare to market prices. Trade mispriced brackets. | 2-3 days (reuse llm_ensemble.py) | $100 |
| **NWS forecast vs market price** | Pull NWS point forecast for NYC/ORD/AUS. When NWS forecast confidently places temp in a bracket that Kalshi prices below fair value, buy. | 1-2 days (reuse noaa_client.py) | $100 |
| **Cross-platform weather arb** | Compare Kalshi weather bracket prices to Polymarket weather markets (if any exist). Risk-free if both sides price below $1.00 combined. | Already built (cross_platform_arb.py) | Split across platforms |
| **Tail bracket value plays** | Longshot brackets (70°+ or 40°-) are sometimes priced at $0.02-$0.05. If NWS forecast gives >10% chance, these are +EV. | 1 day | $100 |

**Recommended next step:** Deploy the LLM ensemble bracket picker. We already have the ensemble engine, Kalshi API access, and weather data pipeline. The key question — "can our AI pick the right temperature bracket better than the market?" — is testable with paper trades in 48 hours.

---

### 10. Lessons Learned for Future Edge Hunting

This investigation produced generalizable insights for Elastifund's edge discovery process:

1. **"Structural" edges require structural access.** The rounding edge is structurally real, but exploiting it requires access to the same continuous temperature data the NWS uses — not the hourly snapshots available to the public. A structural edge in settlement mechanics only helps if you can predict the settlement input better than the market. If your data resolution is coarser than the edge width, the edge is noise.

2. **Backtest with the settlement source, not a proxy.** The original research compared rounding models against each other (NWS vs consumer). We compared against the actual NWS settlement values and found both models fail. Always validate against the actual settlement source — never against a theoretical model of the settlement source.

3. **Entry price assumptions drive P&L more than edge size.** A strategy with 21% win rate looks incredible at $0.10 entry but disastrous at $0.30 entry. The same edge can be +EV or -EV depending purely on the price you pay. Always simulate with real orderbook data, not assumed prices.

4. **Liquidity and mechanics are independent of edge validity.** We confirmed Kalshi weather markets are liquid, well-structured, and have clear settlement rules — even though the specific rounding edge doesn't work. This infrastructure knowledge is valuable for future Kalshi strategies.

5. **Kill fast, reuse the pipeline.** This investigation took ~3 hours from dispatch to verdict. The code, data, and API connections are all reusable. A clean NO-GO with salvageable infrastructure is better than months of ambiguous paper trading.

---

### Appendix A: Data Sources & Methodology

- **Hourly ASOS data:** Iowa Environmental Mesonet (IEM) ASOS download service, stations NYC/ORD/AUS, Dec 1 2025 - Mar 7 2026, report_type=3 (routine METAR + specials), UTC timezone. 2,290-2,301 hourly records per station.
- **Daily summaries:** IEM daily summary endpoint, same stations and date range, `max_temp_f` column. 97 daily records per station.
- **Kalshi market data:** Production API (`api.elections.kalshi.com/trade-api/v2`), read-only queries for events, markets, resolution rules, and orderbook data. No orders placed.
- **Rounding model:** Implemented in Python (`rounding_model.py`), tested with standard rounding, banker's rounding, truncation, and METAR integer variants against both standard and banker's consumer models.
- **Backtest:** 288 station-days (96 days x 3 stations), all real observed data, no synthetic data needed.
- **Kalshi fee model:** Taker fee = 7% x price x (1-price), capped at $0.07/contract. Maker fee = 1.75% coefficient.
- **All code:** `research/weather_validation/` — `rounding_model.py`, `fetch_data.py`, `backtest.py`, `check_kalshi_liquidity.py`

### Appendix B: Cross-Validation Against Live Kalshi Settlement

NYC March 6, 2026 — verified end-to-end:
- Our ASOS hourly max: 5.0°C / 41.0°F
- IEM daily summary: 41.0°F
- Kalshi settlement: 41-42°F bracket (YES) — confirmed via API
- Both rounding models agree at exactly 5.0°C (no rounding ambiguity at integer values)
- Market volume on settled event: 218,899 total contracts across 6 brackets

This confirms our data pipeline is aligned with Kalshi's settlement source and that the market is actively traded.

### Appendix C: Code Inventory

| File | Lines | Purpose |
|------|-------|---------|
| `research/weather_validation/rounding_model.py` | ~150 | 4 NWS rounding variants, 2 consumer variants, discrepancy finder, zone mapper, bracket crossing detector |
| `research/weather_validation/fetch_data.py` | ~180 | IEM ASOS hourly fetcher, IEM daily summary fetcher, CSV parsers, daily max computation from hourly data |
| `research/weather_validation/backtest.py` | ~350 | Rounding model validation, discrepancy backtest, predictability analysis, P&L simulation with Kalshi fee model, sensitivity analysis |
| `research/weather_validation/check_kalshi_liquidity.py` | ~120 | Kalshi API market scanner, weather event finder, orderbook data extraction |
| `research/weather_validation/raw_asos/` | — | Raw ASOS CSVs and computed daily max JSONs for NYC, ORD, AUS |
| `research/weather_validation/nws_daily/` | — | IEM daily summary CSVs and JSONs for NYC, ORD, AUS |
| `research/weather_validation/backtest_results.json` | — | Full structured results from backtest run |
| `research/weather_validation/kalshi_liquidity.json` | — | Kalshi API market data snapshot |

---

*Report generated March 7, 2026. All analysis uses real historical data from IEM and real-time Kalshi market data via API. No synthetic data was used. Verdict: NO-GO on rounding arbitrage. Infrastructure reusable for forecast-based Kalshi weather strategy.*
