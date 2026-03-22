# Mean-Reversion BTC Strategy: Deterministic Specification

**Status:** CANDIDATE — requires validation before any code is written
**Author:** JJ (autonomous assessment)
**Date:** 2026-03-22
**Source claim:** Advertised stack uses VWAP, RSI(14), ATR compression gate, volume exhaustion, MACD divergence, and Hilbert transform proxy for mean-reversion BTC trading.

---

## 0. Relationship to Current BTC5 Architecture

The existing `bot/btc_5min_maker.py` operates on a fundamentally different paradigm: it compares Binance BTC spot to 5-min candle open price at T-10s before close, places a directional maker order on the UP or DOWN binary token if |delta| exceeds a threshold. There are no traditional TA indicators in the current system.

This spec defines a **supplementary signal layer** that could feed into the existing ensemble estimator or act as a standalone pre-filter. It does NOT replace the delta-based core logic.

---

## 1. VWAP (Volume-Weighted Average Price)

### Mathematical Definition

```
VWAP(t) = sum(P_i * V_i, i=session_start..t) / sum(V_i, i=session_start..t)
```

Where:
- `P_i` = typical price of bar i = (High_i + Low_i + Close_i) / 3
- `V_i` = volume (in base currency, i.e., BTC) of bar i
- Session start = 00:00 UTC (BTC trades 24/7; use UTC midnight as anchor)

### Parameters
- **Lookback:** Rolling session VWAP from 00:00 UTC, reset daily.
- **Data source:** Binance BTC/USDT 1-minute klines aggregated.
- **Update frequency:** Recalculated every 1 minute (or at each 5-min decision point).

### Signal Derivation
- `vwap_deviation = (current_price - VWAP) / VWAP`
- Mean-reversion hypothesis: price reverts toward VWAP.
- **Long (expect UP):** `vwap_deviation < -VWAP_ENTRY_THRESHOLD`
- **Short (expect DOWN):** `vwap_deviation > +VWAP_ENTRY_THRESHOLD`

### Mapping to BTC 5-min Binary Markets
- If `vwap_deviation < -VWAP_ENTRY_THRESHOLD` at T-10s: signal favors UP token (price below VWAP, expect reversion upward within next candle).
- If `vwap_deviation > +VWAP_ENTRY_THRESHOLD` at T-10s: signal favors DOWN token.
- **VWAP_ENTRY_THRESHOLD:** Must be calibrated. Starting point: 0.0005 (5 basis points). This is a tunable parameter, NOT a fixed constant.

### Deterministic? YES
Standard formula, no discretion. Requires only OHLCV data from a single exchange.

---

## 2. RSI (Relative Strength Index, period 14)

### Mathematical Definition (Wilder's Smoothing)

```
RS = avg_gain(14) / avg_loss(14)
RSI = 100 - (100 / (1 + RS))
```

Where for the initial calculation (first 14 periods):
```
avg_gain_0 = sum(gains over 14 periods) / 14
avg_loss_0 = sum(losses over 14 periods) / 14
```

Subsequent periods use Wilder's exponential smoothing:
```
avg_gain_t = (avg_gain_{t-1} * 13 + gain_t) / 14
avg_loss_t = (avg_loss_{t-1} * 13 + loss_t) / 14
```

Where:
- `gain_t = max(close_t - close_{t-1}, 0)`
- `loss_t = max(close_{t-1} - close_t, 0)`

### Parameters
- **Period:** 14 bars
- **Bar size:** 5-minute (matching the BTC5 trading window)
- **Data source:** Binance BTC/USDT 5-min closes
- **Warmup:** Minimum 14 bars (70 minutes) before first valid signal

### Signal Derivation (Mean-Reversion)
- **Oversold (expect UP):** RSI < 30
- **Overbought (expect DOWN):** RSI > 70
- **Neutral zone (no signal):** 30 <= RSI <= 70

### Mapping to BTC 5-min Binary Markets
- RSI < 30 at T-10s: signal favors UP token
- RSI > 70 at T-10s: signal favors DOWN token
- 30 <= RSI <= 70: no RSI signal (does not block other signals; simply contributes 0 to the conjunction)

### Deterministic? YES
Wilder's RSI is fully specified. The only ambiguity in practice is initialization (first 14-bar seed), which we resolve by using Wilder's original method above. Any implementation using the same close prices and this formula will produce identical results.

---

## 3. ATR Compression Gate

### Mathematical Definition

ATR (Average True Range, Wilder's smoothing, period 14):
```
TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|)

ATR_0 = mean(TR_1 ... TR_14)
ATR_t = (ATR_{t-1} * 13 + TR_t) / 14
```

### Compression Ratio
```
compression_ratio = ATR_current / ATR_baseline
```

Where:
- `ATR_current` = ATR(14) on 5-minute bars at the current decision point
- `ATR_baseline` = median ATR(14) over the trailing 288 bars (24 hours of 5-min bars)

### Gate Logic
- **ATR compression gate PASSES** when: `compression_ratio < ATR_COMPRESSION_THRESHOLD`
- **Interpretation:** Low volatility relative to recent norm indicates consolidation. Mean-reversion strategies perform better in range-bound, low-vol environments. The gate blocks entries during high-volatility breakout regimes where mean-reversion gets crushed.
- **ATR_COMPRESSION_THRESHOLD:** Starting value: 0.75 (ATR is 75% or less of its 24h median). Tunable.

### What "Compression" Means (Precisely)
ATR compression = current realized volatility is contractring relative to its own recent history. This is NOT ATR < N% of price. It is ATR < N% of its own trailing median. The distinction matters: a $100 BTC move when BTC is at $87,000 is tiny in percentage terms but may be large relative to a quiet session's ATR.

### Mapping to BTC 5-min Binary Markets
The ATR gate does not produce a directional signal. It is a binary filter:
- Gate OPEN (compression detected): allow mean-reversion entries
- Gate CLOSED (expansion detected): block all mean-reversion entries, regardless of other signals

### Deterministic? YES
Standard ATR with a ratio to trailing median. No discretion.

---

## 4. Volume Exhaustion

### Mathematical Definition

```
volume_ratio = V_current / V_baseline
```

Where:
- `V_current` = volume of the current 5-minute bar (or the bar immediately preceding the decision point)
- `V_baseline` = SMA(volume, 20) — simple moving average of volume over the trailing 20 five-minute bars (100 minutes)

### Exhaustion Condition
Volume exhaustion occurs when a directional move (identified by RSI or VWAP deviation) is accompanied by declining volume:

```
volume_exhaustion = (volume_ratio < VOLUME_EXHAUSTION_THRESHOLD)
                    AND (directional_move_present)
```

Where:
- `VOLUME_EXHAUSTION_THRESHOLD` = 0.6 (volume is below 60% of its 20-bar average). Tunable.
- `directional_move_present` = RSI < 30 OR RSI > 70 (the price has moved but volume is drying up, suggesting the move is losing steam)

### Alternative: Volume Spike Then Decline Pattern
A stricter version requires:
1. A volume spike (volume_ratio > 2.0) within the last 5 bars
2. Followed by current volume_ratio < 0.8

This captures the "blowoff" pattern where a final surge of volume marks the end of a directional move. **Recommend implementing both and testing which has predictive power in BTC 5-min context.**

### Mapping to BTC 5-min Binary Markets
Volume exhaustion is a confirming filter, not a directional signal:
- If RSI says oversold AND volume is exhausted: stronger UP conviction
- If RSI says overbought AND volume is exhausted: stronger DOWN conviction
- Volume exhaustion alone generates no trade

### Deterministic? YES
SMA of volume and a ratio. Fully mechanical.

---

## 5. MACD Divergence

### Mathematical Definition

```
MACD_line = EMA(close, 12) - EMA(close, 26)
Signal_line = EMA(MACD_line, 9)
Histogram = MACD_line - Signal_line
```

EMA formula (standard):
```
EMA_t = close_t * k + EMA_{t-1} * (1 - k)
k = 2 / (period + 1)
```

### Divergence Detection

**Bullish divergence (expect UP):**
- Price makes a lower low (close_t < close at prior swing low)
- MACD histogram makes a higher low (histogram_t > histogram at prior swing low)
- Both swing lows must occur within the last N bars

**Bearish divergence (expect DOWN):**
- Price makes a higher high (close_t > close at prior swing high)
- MACD histogram makes a lower high (histogram_t < histogram at prior swing high)
- Both swing highs must occur within the last N bars

### Swing Detection Algorithm
A swing low at bar i requires:
```
close[i] < close[i-1] AND close[i] < close[i-2]
AND close[i] < close[i+1] AND close[i] < close[i+2]
```
(Mirror for swing high. Use 2-bar confirmation on each side.)

### Parameters
- **Fast period:** 12 (5-min bars = 1 hour)
- **Slow period:** 26 (5-min bars = 2h 10m)
- **Signal period:** 9
- **Divergence lookback:** 30 bars (2.5 hours) — maximum distance between the two swing points
- **Minimum swing separation:** 5 bars (25 minutes) — swing points too close together are noise

### WARNING: Divergence Is Semi-Discretionary
This is the weakest component of the stack. Swing detection requires a look-ahead of 2 bars for confirmation, meaning the signal is only available 10 minutes after the actual swing point. In a 5-minute binary market context, this lag is significant. Additionally, "divergence" is pattern-matched, and different swing detection algorithms will identify different divergences.

### Mapping to BTC 5-min Binary Markets
- Bullish MACD divergence detected AND most recent bar confirms: signal favors UP
- Bearish MACD divergence detected AND most recent bar confirms: signal favors DOWN
- No divergence: no signal

### Deterministic? CONDITIONALLY YES
The MACD calculation itself is deterministic. The divergence detection is deterministic IF AND ONLY IF the swing detection algorithm is exactly specified (as above). However, different reasonable swing detection methods will produce different signals. This is the component most likely to diverge between implementations.

---

## 6. Hilbert Transform Proxy (Ehlers)

### Mathematical Definition

The Ehlers Hilbert Transform Dominant Cycle uses the discrete Hilbert transform to extract instantaneous phase from price data.

**Smoothed price (2-bar weighted moving average as detrend):**
```
smooth_price_t = (4 * P_t + 3 * P_{t-1} + 2 * P_{t-2} + P_{t-3}) / 10
```
Where P_t = (High_t + Low_t) / 2 (median price).

**Hilbert transform (discrete approximation):**
```
detrender_t = (0.0962 * smooth_price_t + 0.5769 * smooth_price_{t-2}
              - 0.5769 * smooth_price_{t-4} - 0.0962 * smooth_price_{t-6})
              * (0.075 * period_{t-1} + 0.54)
```

**Quadrature component (Q1) and In-phase component (I1):**
```
Q1_t = (0.0962 * detrender_t + 0.5769 * detrender_{t-2}
       - 0.5769 * detrender_{t-4} - 0.0962 * detrender_{t-6})
       * (0.075 * period_{t-1} + 0.54)

I1_t = detrender_{t-3}
```

**Phase smoothing (1-bar EMA):**
```
I2_t = I1_t - Q1_t * 0.338 * (I1_t + I1_{t-1}) (simplified; see Ehlers for full)
Q2_t = Q1_t + I1_t * 0.338 * (Q1_t + Q1_{t-1})
```

**Instantaneous phase:**
```
phase_t = atan2(Q2_t, I2_t)   [radians, range -pi to +pi]
```

**Instantaneous period (dominant cycle):**
```
delta_phase_t = phase_t - phase_{t-1}
if delta_phase_t < 0.1: delta_phase_t = 0.1   # clamp
period_t = 2 * pi / delta_phase_t
period_t = clamp(period_t, 6, 50)              # bar units
period_t = 0.2 * period_t + 0.8 * period_{t-1} # smooth
```

### Signal Derivation

The Hilbert transform produces two signals relevant to mean-reversion:

1. **Cycle mode indicator:** When a dominant cycle is stable (period variance low over last 10 bars), the market is in mean-reversion territory. When cycle is unstable (period jumping), the market is trending.

2. **Phase-based entry:**
   - Phase crossing from -pi/2 to 0 (sine wave trough): expect UP
   - Phase crossing from +pi/2 to pi (sine wave peak): expect DOWN

### Parameters
- **Bar size:** 5-minute
- **Minimum warmup:** 50 bars (from Ehlers' recommendation)
- **Cycle stability window:** 10 bars. If `std(period, 10) > 0.3 * mean(period, 10)`, market is trending; block mean-reversion.
- **Phase threshold:** Use zero-crossings of sin(phase) as the cycle turn signal.

### Mapping to BTC 5-min Binary Markets
- Cycle mode = mean-reversion AND sin(phase) crosses zero downward: favor DOWN
- Cycle mode = mean-reversion AND sin(phase) crosses zero upward: favor UP
- Cycle mode = trending: block all mean-reversion signals (similar role to ATR gate)

### Deterministic? YES, BUT WITH CAVEATS
The Ehlers Hilbert Transform is published in "Rocket Science for Traders" (2001) and "Cybernetic Analysis for Stocks and Futures" (2004). The algorithm is fully specified. However:
- Numerical precision matters: the recursive smoothing accumulates floating-point differences.
- Multiple versions exist in the literature (2001 vs 2004 vs MESA adaptations). **We pin to the 2004 "Cybernetic Analysis" version.**
- The 50-bar warmup means signals are unavailable for the first ~4 hours of a session.

---

## 7. Entry Conditions (Conjunction)

A mean-reversion entry requires ALL of the following to be true simultaneously at T-10s before the 5-minute candle close:

| # | Condition | Signal |
|---|-----------|--------|
| 1 | VWAP deviation exceeds threshold | Directional (UP or DOWN) |
| 2 | RSI in extreme zone (< 30 or > 70) | Directional (must agree with VWAP) |
| 3 | ATR compression gate passes | Filter (compression_ratio < 0.75) |
| 4 | Volume exhaustion present | Confirmer (volume_ratio < 0.6) |
| 5 | MACD divergence confirms direction | Directional (must agree with VWAP + RSI) |
| 6 | Hilbert cycle mode = mean-reversion | Filter (cycle stable, not trending) |

**Direction agreement rule:** VWAP, RSI, and MACD divergence must all point the same direction. If VWAP says UP but RSI says DOWN, no entry. If any directional component is neutral (e.g., RSI in 30-70 zone), the conjunction fails.

**Practical note:** Requiring all 6 simultaneously will produce very few signals. This is expected for a conservative mean-reversion approach. If signal frequency is too low to be useful (< 1 per day), consider relaxing to 4-of-6 with mandatory inclusion of ATR gate and at least one directional indicator.

---

## 8. Exit Conditions

In the BTC 5-min binary market context, "exit" means the market resolves in 5 minutes. There is no early exit mechanism on Polymarket binary candle markets. The position resolves at candle close.

Therefore, exit conditions are relevant ONLY if this strategy is adapted to longer-duration markets or spot trading. For BTC5:
- **Exit = market resolution at T+5 minutes. No discretionary exit.**

For reference (if adapted to spot):
- Exit when price crosses VWAP (mean achieved)
- Exit when RSI returns to 50 +/- 5
- Hard stop: ATR_current * 1.5 from entry price
- Time stop: 3 bars (15 minutes) without reaching target

---

## 9. Position Sizing

Use existing BTC5 infrastructure:
- **Base size:** $5/trade (current BTC5 parameter, promotion gate failed for $10)
- **Kelly adjustment:** If confidence from the conjunction is quantifiable (e.g., number of confirming signals / 6), scale position:
  ```
  size = base_size * kelly_fraction * (confirming_signals / total_signals)
  ```
  With `kelly_fraction = 0.25` (quarter-Kelly, per existing config).
- **Maximum position:** $10 (hard cap, per existing system)
- **Maker-only execution:** All orders placed as post-only limit orders on the favorable side of the CLOB spread.

---

## 10. Kill Rules

| Rule | Trigger | Action |
|------|---------|--------|
| Daily loss limit | Cumulative daily loss > $25 | Halt all mean-reversion entries for remainder of UTC day |
| Win-rate floor | Win rate < 48% after 50+ trades | KILL strategy entirely pending review |
| Profit factor floor | PF < 0.95 after 50+ trades | KILL strategy entirely pending review |
| Drawdown cap | Peak-to-trough > $50 | KILL strategy entirely pending review |
| Signal drought | < 1 signal per 24h over 3 consecutive days | Flag for parameter review (thresholds too tight) |
| ATR regime break | ATR compression gate blocks > 90% of windows over 24h | Market is trending; strategy is structurally disadvantaged. Pause. |

---

## 11. Binary Market Mapping Summary

The fundamental translation problem: these are continuous-market indicators being applied to a binary outcome (BTC candle UP or DOWN in 5 minutes).

**What works:**
- VWAP deviation: "Price is below VWAP" maps cleanly to "expect reversion upward" which maps to "favor UP token."
- RSI extremes: Oversold/overbought maps to directional expectation.
- ATR gate: Low vol = range-bound = mean-reversion friendly. Clean binary filter.
- Volume exhaustion: Confirming signal, no mapping issue.

**What is problematic:**
- MACD divergence: Swing detection operates on multi-bar patterns. On 5-min bars, the divergence may span 30+ minutes. The signal says "this move is losing momentum" but the binary market only asks about the NEXT 5 minutes. The timescale mismatch is severe. A divergence that takes 2 hours to play out is useless for a 5-minute bet.
- Hilbert cycle: Dominant cycle periods of 6-50 bars (30 min to 4+ hours) are much longer than the 5-minute resolution window. The cycle's "mean-reversion mode" detection is useful as a regime filter but the phase-based directional signal has a timescale mismatch.

---

## 12. Deterministic Implementation Assessment

**CAN THIS BE IMPLEMENTED DETERMINISTICALLY? YES — with one qualification.**

Every component has a precise mathematical definition that produces identical outputs given identical inputs. There is no discretionary interpretation required.

**The qualification:** MACD divergence detection involves swing identification, which is deterministic per the spec above but sensitive to the exact algorithm used. Two "correct" implementations using different swing detection methods will disagree on some signals. This is not a discretionary problem — it is a specification precision problem, which this document resolves by pinning the 2-bar confirmation swing algorithm.

**However, the more important question is: should it be implemented?**

### Honest Assessment

1. **Timescale mismatch is the critical weakness.** Four of six components (VWAP session deviation, MACD divergence, Hilbert cycle, RSI-14 on 5-min bars) operate on timescales of 1-4+ hours. The BTC5 binary market resolves in 5 minutes. Mean-reversion signals that are valid over 2 hours do not reliably predict the next 5-minute candle direction.

2. **The useful components are the filters, not the signals.** ATR compression gate and Hilbert cycle-mode detection are genuinely useful as regime filters for the existing delta-based BTC5 strategy. They answer "is the market in a mean-reversion regime right now?" which is valuable. The directional signals (VWAP, RSI, MACD divergence) add little over the existing |delta| method for 5-minute prediction.

3. **The conjunction requirement virtually guarantees signal drought.** Requiring 6 independent conditions to align simultaneously on 5-minute bars will produce near-zero signals per day. The strategy as described is not practically tradeable at this frequency.

4. **Recommended approach:** Extract the ATR compression gate and Hilbert cycle-mode detector as supplementary filters for the existing BTC5 delta strategy. Do NOT implement the full 6-component conjunction as a standalone strategy for 5-minute markets. If mean-reversion is to be pursued, target 1-hour or 4-hour markets where the indicator timescales match the resolution window.

### Classification

**Strategy status: IMPLEMENTABLE_BUT_MISMATCHED**

The specification is deterministic and complete. The strategy is coherent for spot or longer-timeframe markets. For BTC 5-minute binary markets specifically, the timescale mismatch renders the full conjunction impractical. Salvageable components (ATR gate, Hilbert regime filter) should be extracted as filters for the existing system.

---

## Appendix A: Data Requirements

| Indicator | Data Needed | Source | Min History |
|-----------|-------------|--------|-------------|
| VWAP | OHLCV 1-min | Binance BTC/USDT | Since 00:00 UTC |
| RSI(14) | Close 5-min | Binance BTC/USDT | 70 min (14 bars) |
| ATR(14) | OHLC 5-min | Binance BTC/USDT | 70 min + 24h baseline |
| Volume exhaustion | Volume 5-min | Binance BTC/USDT | 100 min (20 bars) |
| MACD(12,26,9) | Close 5-min | Binance BTC/USDT | 130 min (26 bars) + divergence lookback |
| Hilbert transform | HL 5-min | Binance BTC/USDT | 250 min (50 bars) |

All data can be sourced from a single Binance BTC/USDT 1-minute kline stream, with 5-minute bars aggregated locally.

## Appendix B: Environment Variables (If Implemented)

```
MR_VWAP_ENTRY_THRESHOLD=0.0005
MR_RSI_OVERSOLD=30
MR_RSI_OVERBOUGHT=70
MR_ATR_COMPRESSION_THRESHOLD=0.75
MR_ATR_BASELINE_BARS=288
MR_VOLUME_EXHAUSTION_THRESHOLD=0.6
MR_VOLUME_BASELINE_BARS=20
MR_MACD_FAST=12
MR_MACD_SLOW=26
MR_MACD_SIGNAL=9
MR_MACD_DIVERGENCE_LOOKBACK=30
MR_HILBERT_STABILITY_WINDOW=10
MR_HILBERT_STABILITY_THRESHOLD=0.3
MR_DAILY_LOSS_LIMIT=25.0
MR_KILL_MIN_TRADES=50
MR_KILL_WINRATE_FLOOR=0.48
MR_KILL_PF_FLOOR=0.95
MR_KILL_MAX_DRAWDOWN=50.0
```
