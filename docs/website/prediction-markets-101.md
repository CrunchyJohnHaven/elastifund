---
title: "Prediction Markets 101"
status: "active"
doc_type: "background_research"
last_reviewed: "2026-03-11"
---

# Prediction Markets 101

*Part of the Elastifund Education Center — [elastifund.io/learn/prediction-markets-101](https://elastifund.io/learn/prediction-markets-101)*

---

## TL;DR (30 seconds)

Prediction markets are markets where you bet on whether real-world events will happen. If you think the probability of something is higher than the market price suggests, you buy; if lower, you sell. The market price represents the crowd's collective estimate of probability. When the event resolves (happens or doesn't), you either get $1 per share or $0. The difference between what you paid and what you received is your profit or loss.

Think of it like this: if a prediction market prices "Will it rain tomorrow in New York?" at $0.60, the crowd collectively estimates a 60% chance of rain. If you think it's actually 80% likely, you buy at $0.60 and expect to make money over many such trades.

---

## The Full Explanation (5 minutes)

### How Prediction Markets Work

A prediction market lists a question with a binary outcome: something either happens or it doesn't. For each question, there are two "shares" you can buy:

- **YES shares:** Pay $1 if the event happens, $0 if it doesn't.
- **NO shares:** Pay $1 if the event doesn't happen, $0 if it does.

The price of a YES share can be interpreted as the market's probability estimate. If YES costs $0.70, the market thinks there's roughly a 70% chance the event occurs.

Prices move based on supply and demand. If new information makes the event more likely, people buy YES, pushing the price up. If information makes it less likely, people buy NO (or sell YES), pushing the price down.

### Where Can You Trade?

Two major platforms operate in 2026:

**Polymarket** (polymarket.com): Crypto-based. You trade with USDC (a cryptocurrency pegged to the US dollar) on the Polygon blockchain. No KYC required for small amounts. Categories include politics, crypto, weather, geopolitics, entertainment. The order book (called CLOB) matches buyers and sellers electronically. Maker orders (limit orders) pay 0% fees. Taker orders (market orders) pay up to 1.56% on crypto markets.

**Kalshi** (kalshi.com): CFTC-regulated US exchange. You trade with US dollars. Categories include weather, economics, events, sports. Cent-based pricing ($0.01 to $0.99 per share). Different fee structure: taker fee = 7% × price × (1-price), maxing around 1.75%.

Both platforms let you place trades via API, which is how our automated system operates.

### An Example Trade

**Market:** "Will the S&P 500 close above 5,000 on March 15?"
**Current YES price:** $0.45 (market thinks 45% chance)
**Your estimate:** 65% chance (based on trend analysis)
**Edge:** 65% - 45% = 20 percentage points

You buy 10 YES shares at $0.45 each = $4.50 total investment.

**If the S&P closes above 5,000:** You receive 10 × $1.00 = $10.00. Profit = $5.50 (122% return).
**If it doesn't:** You receive $0. Loss = $4.50.

**Expected value:** 0.65 × $10.00 + 0.35 × $0.00 - $4.50 = $6.50 - $4.50 = **+$2.00 expected profit** per trade cycle.

Over many such trades with genuine edge, the law of large numbers works in your favor. The key word is "genuine" — most people who think they have an edge don't.

### Why Prediction Markets Matter

Prediction markets aggregate information from many participants into a single number (the price). Research has shown they're often more accurate than polls, expert panels, or individual forecasters for certain types of questions. When participants have real money at stake, they're motivated to be honest and to seek out accurate information.

That said, prediction markets aren't perfectly efficient. Clinton & Huang (2025) found that Polymarket political markets are only about 67% accurate. That 33% error rate is the opportunity for systems like ours.

---

## Technical Deep Dive (30 minutes)

### Market Microstructure

Polymarket uses a Central Limit Order Book (CLOB) model. Here's what that means in practice:

**Order types:**
- **Limit order (maker):** "I want to buy YES at $0.45 or less." Your order sits in the book until someone accepts your price. You pay 0% fee and receive a share of the maker rebate pool.
- **Market order (taker):** "I want to buy YES right now at whatever price is available." You pay the taker fee: up to 1.56% on crypto markets, 0.44% on sports markets. On fee-free markets (politics, weather, most other categories as of March 2026), taker fees are 0%.

**Token mechanics on Polymarket:**
Polymarket operates on the Polygon blockchain. When you deposit USDC, the system can split $1.00 of USDC into one YES token and one NO token (or "merge" them back). This is how market makers create liquidity — they split USDC into token pairs and post both sides. When one side gets bought, they hold inventory on the other side.

**Resolution:**
Each market specifies a resolution source. Political markets typically use Associated Press or official government results. Crypto candle markets use Chainlink oracle prices (which pull from exchanges like Binance). Weather markets use official NWS observations. When the resolution source confirms the outcome, the UMA oracle verifies it, and winning shares are redeemed for $1.00.

### The Fee Landscape (Critical for Automated Trading)

Fees are the single most important factor in prediction market profitability. Our analysis of 72.1 million Polymarket trades (via jbecker.dev) found that makers earn +1.12% excess returns while takers lose -1.12%. The fee structure is that decisive.

**Polymarket fee formula (crypto markets):**
```
effectiveFee = feeRate × price × (1 - price) ^ exponent
```
Where feeRate = 0.25, exponent = 2 for crypto markets. Maximum fee: 1.56% at price = $0.50.

**Why this matters:** If your strategy requires taker execution on crypto markets, you need at least 1.56% raw edge just to break even at mid-range prices. Most edges are smaller than that. This is why our system uses maker orders exclusively on fee-bearing markets.

**Fee-free markets:** As of March 2026, politics, weather, geopolitics, economics, and most other non-crypto, non-sports categories have zero fees for both makers and takers. This is where forecasting-based strategies (like our LLM estimator) have the best chance of working.

### Accuracy and Efficiency

How accurate are prediction markets? The academic evidence is mixed:

- **Manski (2006):** Prediction market prices don't directly correspond to probabilities because participants have varying risk preferences and budget constraints.
- **Arrow et al. (2008):** Markets aggregate information well in liquid, well-designed settings.
- **Clinton & Huang (2025):** Polymarket political markets are ~67% accurate — better than most individual forecasters, but far from perfect.
- **Schoenegger (2025):** LLMs are approaching prediction market accuracy on some categories. Base-rate-first prompting + calibration brings LLMs within striking distance of market consensus.

The inefficiency varies by category. Political markets are relatively efficient (many informed participants). Weather markets are less efficient (fewer participants, specialized knowledge required). Crypto candle markets are mostly speed-based (no forecasting edge, just execution speed).

### Our Implementation

Elastifund's approach: We ask AI models to estimate probabilities WITHOUT showing them the current market price. This prevents "anchoring" — the cognitive bias where knowing the market's estimate biases your own estimate toward it. We then calibrate the raw estimates using Platt scaling (correcting for systematic overconfidence) and compare the calibrated estimate to the market price. If the difference exceeds our edge threshold (15% for YES signals, 5% for NO signals), we trade.

Why asymmetric thresholds? Because our data shows a 76.2% win rate on NO trades vs 55.8% on YES trades. This is the "favorite-longshot bias" — the crowd systematically overprices exciting low-probability events. We exploit this by setting a lower bar for NO signals.

Full system details: [System Architecture](/system) | Code: [GitHub](https://github.com/CrunchyJohnHaven/elastifund)

---

*Last updated: March 7, 2026 | Part of the Elastifund Education Center*
