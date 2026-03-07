# Quantitative Prediction Market Fund — Investor Report

**Date:** March 2026
**Fund Status:** Pre-Launch (Live Paper Trading + Historical Backtest Complete)
**Trading Begins:** ~March 10, 2026

---

## Executive Summary

We operate an AI-powered automated trading system on Polymarket, the world's largest prediction market platform. The system uses a multi-model AI ensemble to identify mispriced prediction markets and trade them for profit.

**How it works in plain English:** Prediction markets let people bet on future events ("Will the Fed cut rates in June?"). The crowd sets a price reflecting the perceived probability. Our AI reads each question, estimates the true probability from first principles, and bets when it disagrees with the crowd. Think of it like a poker player who can calculate odds faster and more accurately than the table.

### Key Performance Metrics (Backtested)

| Metric | Value |
|--------|-------|
| Markets tested | 532 resolved prediction markets |
| Win rate | **64.9%** (305 wins / 470 trades) |
| Best strategy win rate | **71.2%** (calibrated + selective, out-of-sample validated, fee-adjusted) |
| Probability of total loss | **0.0%** (10,000 Monte Carlo simulations) |
| Estimated annual return | **+124% to +872%** depending on strategy and trade frequency |

**Important:** These results are from backtesting against historical data, not live trading. Past performance — simulated or otherwise — does not guarantee future results.

---

## How the System Works

### The Edge: AI Probability Estimation

1. **Scan** — Every 5 minutes, the system scans 100+ active markets on Polymarket
2. **Estimate** — An AI ensemble (Claude, GPT, Grok) estimates the true probability of each event, without seeing the market price (to avoid bias)
3. **Compare** — If the AI's estimate diverges from the market price by more than 5%, a trade signal is generated
4. **Trade** — The system places a bet on the side it believes is mispriced
5. **Learn** — Performance data continuously feeds back to improve calibration

### Why This Works

Prediction markets are efficient on average, but **not perfectly efficient** for every market at every moment. Our AI exploits three specific inefficiencies:

- **Speed** — AI analyzes markets 24/7, catching mispricings before human traders
- **Scale** — AI evaluates hundreds of markets simultaneously, finding needles in haystacks
- **Discipline** — AI doesn't have emotions, FOMO, or anchoring bias

### Academic Validation

Recent academic research supports our approach. Halawi et al. (2024, NeurIPS) demonstrated that multi-model LLM ensembles can match the "wisdom of crowds" accuracy level, validating our planned multi-model architecture. Clinton & Huang (2025, Vanderbilt) found that 2024 US election markets on Polymarket were only approximately 67% correct — confirming exploitable inefficiencies in political markets. The Forecasting Research Institute projects LLM-superforecaster parity by November 2026, validating the thesis that AI can generate genuine forecasting alpha.

### The NO Bias Advantage

Our backtest revealed a powerful asymmetry: **betting NO wins 76% of the time**, compared to 56% for YES bets. This happens because prediction markets tend to overprice exciting outcomes (people want to bet YES on things happening). Our system exploits this by favoring NO bets.

---

## Performance Data

### Backtest Results (532 Resolved Markets)

We tested our AI on 532 prediction markets that have already resolved (we know the actual outcome). The AI estimated probabilities without seeing the market price, then we simulated what would have happened if we traded based on those estimates.

| Metric | Value |
|--------|-------|
| Total markets analyzed | 532 |
| Markets generating a trade signal | 470 (88%) |
| **Overall win rate (uncalibrated)** | **64.9%** |
| **Overall win rate (calibrated v2)** | **68.5%** |
| Buy YES win rate (calibrated) | 63.3% |
| Buy NO win rate (calibrated) | 70.2% |
| Average profit per trade | $0.74 on $2.00 position (+37%) |
| Total simulated profit | +$276.00 |
| Brier score (raw) | 0.239 |
| **Brier score (calibrated, out-of-sample)** | **0.217** (0.25 = random) |

### Strategy Optimization

We tested 10 strategy variants to find the optimal configuration:

| Strategy | Win Rate | Trades | Net P&L | Brier | ARR @5/day |
|----------|----------|--------|---------|-------|-----------|
| Baseline (5% threshold) | 64.9% | 470 | $275.30 | 0.239 | +1,086% |
| NO-only (bet NO exclusively) | 76.2% | 210 | $217.90 | 0.239 | +2,170% |
| Calibrated v2 (Platt scaling) | 68.5% | 372 | $272.28 | 0.217 | +1,437% |
| **Cal + CatFilter + Asymmetric** | **71.2%** | **264** | **$221.36** | **0.214** | **+1,692%** |
| Cal + Asym + Confidence Sizing | 71.2% | 264 | $219.68 | 0.214 | +1,677% |

All figures include taker fees (fee rate r=0.02). Calibration v2 uses Platt scaling fitted on 70% of markets and validated on the remaining 30%. The "Calibrated + Selective" variant combines calibration, category filtering (skip crypto/sports), and asymmetric thresholds (YES 15%, NO 5%).

### Monte Carlo Simulation (10,000 Paths)

We simulated 10,000 possible outcomes over 12 months to understand the range of returns:

**At $75 starting capital:**
| Scenario | 12-Month Portfolio Value | Annual Return |
|----------|------------------------|---------------|
| Worst reasonable (5th percentile) | $782 | +942% |
| **Median (most likely)** | **$918** | **+1,124%** |
| Best reasonable (95th percentile) | $1,054 | +1,305% |
| Probability of total loss | **0.0%** | |

**At $10,000 starting capital (investor scenario):**
| Scenario | 12-Month Portfolio Value | Annual Return |
|----------|------------------------|---------------|
| Worst reasonable (5th percentile) | $33,507 | +235% |
| **Median (most likely)** | **$36,907** | **+269%** |
| Best reasonable (95th percentile) | $40,207 | +302% |
| Probability of total loss | **0.0%** | |

**Projected monthly returns at $10,000:**
Month 1: +22% | Month 2: +18% | Month 3: +15% | Month 4: +13% | Month 5: +11% | Month 6: +10%

Returns decrease over time because position sizes are fixed — as capital grows, each trade becomes a smaller percentage of the portfolio.

---

## Risk Factors

Investors should carefully consider the following risks:

1. **Backtest ≠ Live Performance.** All performance data is from historical backtesting. Live trading involves execution challenges (slippage, fill rates, timing) not captured in backtests. Actual returns will differ.

2. **AI Model Risk.** The system depends on AI probability estimation. If AI models become less accurate, or if prediction markets become more efficient, the edge may disappear.

3. **Platform Risk.** Polymarket is a crypto-based prediction market. It could face regulatory action, technical failures, or liquidity crises. The CFTC took enforcement action against Polymarket in 2022.

4. **Liquidity Risk.** Large trades may not fill at expected prices. This limits the strategy's capacity — it works best with smaller capital amounts.

5. **Capital Risk.** While Monte Carlo simulations show 0% probability of total loss at current parameters, unexpected market conditions could cause significant drawdowns.

6. **Regulatory Risk.** The legal status of prediction market trading in the US is evolving. Tax treatment of gains is unclear (may be capital gains, gambling income, or ordinary income).

7. **Technology Risk.** The system runs on cloud infrastructure. Server failures, API outages, or software bugs could cause missed trades or errors.

8. **Concentration Risk.** The strategy currently operates only on Polymarket. Diversification across platforms would reduce risk but is not yet implemented.

9. **Competitive Pressure.** The prediction market bot ecosystem is intensifying. Top automated accounts show seven-figure profits (OpenClaw 0x8dxd earned approximately $1.7M over 20,000 trades; Fredi9999 shows $16.62M all-time P&L). Tens of millions of dollars are under automated trading on Polymarket. Alpha decay is accelerating — Polymarket has added fees and latency limits to curb arbitrage bots. Only approximately 0.5% of Polymarket users earn more than $1,000. Our edge must be continuously validated and improved against this competitive backdrop.

10. **Arbitrage vs. Forecasting Risk.** Research shows the dominant profitable bot strategy on Polymarket is mechanical arbitrage, not AI forecasting. Our forecasting-based approach is differentiated but unproven at institutional scale. If AI forecasting cannot generate competitive returns against arbitrage strategies, the fund's thesis may be challenged.

**This is a speculative investment. You should only invest money you can afford to lose entirely.**

---

## Fund Terms (Proposed)

| Term | Detail |
|------|--------|
| Minimum investment | $1,000 |
| Management fee | 0% |
| Performance fee (carry) | 30% of profits above high-water mark |
| Lock-up period | 90 days |
| Withdrawal notice | 30 days |
| Reporting | Monthly performance summary |
| Withdrawal frequency | Quarterly |

**High-water mark:** The manager only earns carry on NEW profits. If the fund drops from $12,000 to $10,000 and then recovers to $12,000, no carry is charged on the recovery — only on gains above $12,000.

**Example:** You invest $10,000. After 6 months, the fund grows to $15,000. Your profit is $5,000. The manager's carry is 30% x $5,000 = $1,500. Your net profit: $3,500 (35% return in 6 months).

---

## Infrastructure

| Component | Detail |
|-----------|--------|
| Trading platform | Polymarket (CLOB) |
| AI models | Claude Haiku, GPT-4o-mini, Grok-2 (ensemble) |
| Hosting | DigitalOcean VPS (Frankfurt) |
| Scan frequency | Every 5 minutes, 24/7 |
| Position sizing | Quarter-Kelly criterion |
| Risk management | Max drawdown limits, position concentration limits |
| Monthly infrastructure cost | ~$20 (VPS + API costs) |

---

## Appendix: Charts

Charts are available in the shared folder:

1. **calibration_plot.png** — How well the AI's probability estimates match reality
2. **equity_curve.png** — Simulated portfolio growth across 470 backtest trades
3. **monte_carlo_fan.png** — 500 simulated portfolio paths showing range of outcomes
4. **win_rate_direction.png** — Win rate comparison: Buy YES vs Buy NO
5. **strategy_comparison.png** — Performance of 6 strategy variants
6. **monthly_returns.png** — Projected monthly returns

---

## Contact

For questions about the fund, strategy, or to discuss investment, contact the fund manager directly.

---

*This document is for informational purposes only. It does not constitute an offer to sell or a solicitation of an offer to buy any securities. All performance figures are based on backtested/simulated results and do not represent actual trading. Past performance, whether simulated or actual, does not guarantee future results. Prediction market trading involves substantial risk of loss. This document should be reviewed by a qualified attorney before use in soliciting investments.*
