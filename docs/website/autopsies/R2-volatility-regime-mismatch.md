# Strategy Autopsy: R2 — Volatility Regime Mismatch

*Status: REJECTED | Tested: March 6, 2026 | Kill Reason: Negative EV, degrades over time*

---

## The Hypothesis

**Testable statement:** When implied volatility (derived from order book spread width) diverges from realized volatility (derived from actual trade price movement) by more than 1 standard deviation, the market is mispricing uncertainty, and trading toward the mean generates positive expected value.

## The Mechanism

Prediction markets price uncertainty through their spreads. A wide bid-ask spread implies high uncertainty (the market isn't sure). Realized volatility measures how much the price actually moved. When implied vol is high but realized vol is low, the market is overpricing uncertainty — shares are cheaper than they should be. When implied vol is low but realized vol is high, the market is underpricing uncertainty — shares are more expensive than they should be.

This is the prediction market equivalent of a fundamental options trading strategy: selling overpriced vol and buying underpriced vol.

## What We Expected

We expected to find 50-100 signals per test period where implied and realized vol diverged by more than 1 standard deviation. We expected a win rate of 55-60% on these signals, generating modest but consistent edge.

## What Actually Happened

| Metric | Expected | Actual |
|--------|----------|--------|
| Signals generated | 50-100 | 34 |
| Win rate | 55-60% | **32.35%** |
| Out-of-sample expectancy | Positive | **Negative** |
| Signal stability over time | Stable | **Decaying** |

34 signals, 32.35% win rate. That's worse than a coin flip. Not "slightly below breakeven" — substantially below.

## Why It Failed

Three compounding factors:

**1. Spread data from CLOB is noisy.** Polymarket's order book is thin for many markets. A single large order appearing or disappearing can change the bid-ask spread by 10% in seconds. Our "implied volatility" measure was capturing order book noise, not true market uncertainty. The CLOB depth API also returned 404 errors on approximately 30% of requests, creating gaps in our data.

**2. Realized volatility is dominated by information events, not mean-reversion.** In equity options, high implied vol often reverts to the mean as uncertainty resolves. In prediction markets, high actual price movement usually reflects NEW INFORMATION arriving (a news event, a poll release, a policy announcement). This information has a direction — it pushes the price to a new equilibrium, not back to the mean. Trading against information flow is a losing strategy.

**3. The signal decayed over the test period.** Whatever marginal pattern existed in early data disappeared in later data. This triggered our "regime decay" kill rule. The most likely explanation: any vol-based pattern was quickly arbitraged by other participants.

## The Transferable Insight

**Prediction markets are NOT like options markets.** In options, implied volatility has a well-defined relationship to realized volatility because the underlying (a stock price) is a continuous diffusion process. In prediction markets, the underlying (a probability) moves in response to discrete information events. Volatility-based strategies developed for equity options don't translate directly.

More broadly: be suspicious of strategies that work in traditional finance "applied to prediction markets." The underlying market structure is different enough that the analogy often breaks down.

## What Would Make This Work?

Two possible salvage paths (neither implemented):

1. **Better implied vol measurement.** Use order book depth and trade flow velocity instead of raw spread width. This requires the CLOB WebSocket (not REST API) for reliable real-time data. Possible after our WebSocket upgrade.

2. **Category-specific vol regimes.** Political markets near election dates might have predictable vol compression. Crypto markets near fee changes might have vol expansion. Testing vol signals WITHIN categories with known event structures could work where a generic cross-category signal doesn't.

Neither path is currently prioritized because the base signal quality was so poor (32.35% win rate). The juice isn't worth the squeeze.

## Code

Strategy implementation: `src/strategies/vol_regime_mismatch.py`
Test results: `reports/strategy_R2_vol_regime_mismatch.json`
GitHub: [View on GitHub](https://github.com/CrunchyJohnHaven/elastifund/tree/main/src/strategies)

---

*This autopsy is part of the Elastifund Strategy Encyclopedia. We publish every failure because mapping what doesn't work is as valuable as finding what does.*
