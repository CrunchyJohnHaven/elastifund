# Strategy Autopsy: R10 — NOAA Weather Bracket Arbitrage (Kalshi)

*Status: REJECTED | Tested: March 7, 2026 | Kill Reason: NWS rounding creates insufficient model accuracy*

---

## The Hypothesis

**Testable statement:** Kalshi weather bracket markets (e.g., "Will the high temperature in NYC exceed 45°F tomorrow?") can be beaten by NOAA's National Weather Service forecasts, because NWS models have access to better data than retail traders using consumer weather apps.

## The Mechanism

Kalshi lists weather markets with exact temperature thresholds. The National Weather Service provides free, professional-grade forecasts via api.weather.gov. If NWS forecasts 52°F for New York's high and the Kalshi market prices the >45°F bracket at only 60%, the NWS data implies the bracket should be priced much higher — perhaps 85%+. That's a huge edge.

The structural argument: retail traders on Kalshi check iPhone weather apps that use simplified models. The NWS uses ensemble models (GFS, HRRR) with far more computational resources. Information asymmetry should create edge.

## What We Expected

We expected NWS forecasts to place the correct temperature bracket 70-80% of the time for 24-48 hour forecasts. Combined with Kalshi's relatively thin liquidity (fewer sophisticated participants), we expected 10-20% edge on weather markets.

## What Actually Happened

NWS bracket placement accuracy: **27-35%.**

Not 70-80%. Not even 50%. The NWS forecast was accurate to the correct bracket only about a third of the time.

## Why It Failed

**The rounding problem.** NWS forecasts report temperatures in whole degrees Fahrenheit. Kalshi brackets also use whole degrees. When the NWS says "high of 45°F" and the bracket boundary is 45°F, the actual temperature could be anywhere from 43°F to 47°F — and the NWS forecast can't distinguish between "44.8°F" (below threshold) and "45.2°F" (above threshold).

Temperature forecast error at 24 hours is typically ±2-3°F. That error range is wider than most Kalshi brackets. When you're trying to predict which side of a specific degree boundary the temperature will land on, ±3°F of uncertainty is fatal.

**A concrete example:**

- NWS forecast: High of 46°F in New York
- Kalshi bracket: "Will the high exceed 45°F?"
- NWS is saying "somewhere between 43-49°F"
- The 45°F boundary falls right in the middle of the uncertainty range
- The NWS forecast gives us essentially no useful information about which side of 45°F the actual temperature will land on

The only scenarios where NWS forecasts ARE useful: when the forecast is far from the bracket boundary (NWS says 55°F, bracket is 45°F). But in those cases, the Kalshi market already prices the bracket correctly because even retail traders can tell 55°F > 45°F.

## The Transferable Insight

**Market structure can negate data quality.** The NWS has objectively better weather data than retail traders. But the market structure (exact-degree brackets) neutralizes this advantage because the data isn't precise enough at the resolution boundary.

This is a general principle: having better information only creates edge if the MARKET QUESTION is answerable with your information. If the question requires precision your data can't provide, superior data quality is worthless.

**Application to other strategies:** Before pursuing any "we have better data than the market" strategy, ask: "Can our data answer the SPECIFIC question the market asks, at the SPECIFIC precision the market requires?" If the market asks "will CPI exceed 3.00%?" and your model has ±0.15% error, you only have edge when your forecast is far from 3.00%.

## The Multi-Model Variant (Our Edge #1 in Pipeline)

We still have a weather strategy in the pipeline: NOAA Multi-Model Weather Consensus using GFS + ECMWF + HRRR ensemble. The thesis: combining multiple weather models reduces forecast error enough to beat single-model predictions at bracket boundaries.

**Honest assessment after this autopsy:** the multi-model approach reduces error from ±3°F to perhaps ±1.5-2°F. That's still a wide range relative to 1°F bracket widths. Probability of the multi-model variant surviving our kill rules: ~25%. We'll test it, but expectations are calibrated downward.

## What Would Make Weather Strategies Work?

1. **Wider brackets.** If Kalshi listed "Will the high exceed 40°F?" instead of "45°F?", and the NWS forecast is 52°F, we'd have plenty of margin. But Kalshi sets the brackets, not us.

2. **Precipitation markets instead of temperature.** "Will it rain?" is a binary question with clearer NWS signal than "Will the temperature land above or below exactly 45°F?" Rain/no-rain forecasts are 80-90% accurate at 24 hours.

3. **Extreme weather events.** "Will a hurricane make landfall?" or "Will temperatures drop below 0°F?" — these are high-signal, rare events where weather models have clear edge over retail intuition. But they're also rare, limiting the number of tradeable opportunities.

4. **Longer time horizons with wider confidence intervals.** 7-day forecasts have more error, but markets might also misprice them more. There could be a sweet spot where forecast error is large but market mispricing is larger.

## Code

Strategy implementation: `src/strategies/weather_bracket.py`
Validation report: `research/imports/WEATHER_BRACKET_VALIDATION_REPORT.md`
NOAA client: `polymarket-bot/src/noaa_client.py`

---

*This autopsy is part of the Elastifund Strategy Encyclopedia. The lesson here — data quality ≠ edge when market structure demands precision your data can't provide — applies to any strategy built on information advantage.*
