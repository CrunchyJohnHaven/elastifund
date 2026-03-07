# Day 17: March 4, 2026 — Cross-Platform Arbitrage: Polymarket vs Kalshi

## What I Built Today

Connected Kalshi ($100 funded, RSA-signed API) and built the cross-platform arbitrage scanner. This is Signal Source 4 — the one that finds risk-free profit opportunities.

## How It Works

Polymarket and Kalshi list markets on the same events but with different resolution sources, different fee structures, and different participant pools. Sometimes the prices disagree enough that you can buy YES on one platform and YES on the other side on the other platform, and guarantee a profit regardless of outcome.

**The scanner:**
1. Fetches ~300 active Polymarket markets (Gamma API) and ~3,000 active Kalshi markets (Kalshi SDK)
2. Matches equivalent markets using title similarity (SequenceMatcher + Jaccard keyword overlap, 70% threshold)
3. Skips sports/esports (we filter via KALSHI_SKIP_PREFIXES) and zero-liquidity markets
4. For matched pairs: calculates YES_ask + NO_ask after fees on each platform
5. If the combined cost < $1.00, that's an arbitrage — you buy both sides, one must resolve YES, guaranteed profit

**The fee math matters:**
- Polymarket maker: 0% fee
- Kalshi taker: fee = 0.07 × p × (1-p), max ~1.75% at p=0.50
- A "10-cent arb" (YES costs $0.45 on one platform, NO costs $0.45 on the other) earns $0.10 per pair
- After Kalshi taker fees, this becomes $0.10 - ~$0.017 = $0.083 profit
- That's an 8.3% risk-free return

## What I Learned

Cross-platform arb is the cleanest form of edge: it doesn't require any prediction, any AI, any calibration. If the math works, it works. The challenge is finding the matches — title similarity is imperfect, and you need to verify that the resolution criteria actually match (same event, same timeframe, same source).

In practice, the opportunities are rare and small. Markets that are listed on both platforms tend to have similar prices because informed traders already arb them. The opportunities that exist tend to be in obscure markets with low liquidity, which limits how much capital you can deploy.

Still, this is the lowest-risk signal source in our system. When it fires, we trade quarter-Kelly (high confidence sizing) regardless of what other sources say.

## Key Numbers

| Metric | Value |
|--------|-------|
| Capital | $247.51 Polymarket + $100 Kalshi |
| Kalshi markets scanned | ~3,000 |
| Cross-platform matches found | 47 |
| Arb opportunities detected | 3 (narrow, <$5 capacity each) |
| Tests passing | 270 |
| Research dispatches | 52 |

---

*Tags: #strategy-deployed #infrastructure*
