# Validating 128% ARR on Polymarket: a rigorous backtesting framework

**Your simulated 128% annual return is plausible but sits squarely in the danger zone for overfitting.** Systematic prediction market strategies have documented realistic returns of 35–95% annually, making triple-digit ARR possible but suspicious without rigorous out-of-sample validation. The core challenge: prediction markets generate small sample sizes (50–500 trades), binary return distributions that violate normality assumptions, and thin orderbooks that make backtested fills unrealistic. This report provides the complete technical framework—formulas, thresholds, code, and data sources—to stress-test your strategy against real-world constraints before deploying capital.

The framework rests on three pillars: realistic simulation of Polymarket's microstructure (fees, slippage, fill rates), rigorous statistical validation (Deflated Sharpe Ratio, CPCV, Monte Carlo ruin analysis), and honest calibration of your weather-market edge against NOAA forecast accuracy data. Each section below provides implementable specifics.

---

## 1. Polymarket's data infrastructure and its backtesting limitations

The single most important constraint for backtesting Polymarket strategies is that **historical orderbook data does not exist in the official APIs**. The CLOB `/prices-history` endpoint returns only midpoint price timeseries, and for resolved markets, granularity degrades to 12-hour intervals—far too coarse for simulating intraday strategies. This means any backtest using only official data is testing against midpoint prices with no information about available liquidity, spreads, or depth.

**API architecture for data collection:**

| Service | Base URL | Backtesting Utility |
|---------|----------|-------------------|
| Gamma API | `gamma-api.polymarket.com` | Market discovery, metadata, volume, liquidity snapshots |
| CLOB API | `clob.polymarket.com` | Live orderbooks, `/prices-history` for price timeseries |
| WebSocket | `wss://ws-subscriptions-clob.polymarket.com/ws/` | Real-time L2 orderbook streaming (prospective recording only) |
| Data API | `data-api.polymarket.com` | User-specific trade history, positions |

The practical path to realistic backtesting requires **recording live orderbook data going forward** via the WebSocket feed, or purchasing historical L2 snapshots from third-party providers like PolymarketData.co, which offers configurable-resolution bid/ask depth snapshots specifically designed for backtesting. On-chain reconstruction through The Graph subgraphs or Dune Analytics dashboards can recover the trade tape (fills, volumes) but not resting order state.

```python
from py_clob_client.client import ClobClient

client = ClobClient("https://clob.polymarket.com")  # Level 0: no auth needed
book = client.get_order_book("<token_id>")       # Full L2 snapshot
mid  = client.get_midpoint("<token_id>")          # Midpoint price
last = client.get_last_trade_price("<token_id>")  # Last fill
```

Rate limits are generous for data collection: **1,500 requests/10s** for `/book` and **1,000/10s** for price history—sufficient to snapshot hundreds of markets per minute. The `py-clob-client` library (Python 3.9+) handles all read-only operations without authentication.

---

## 2. Realistic simulation constraints will erode your backtested returns

The gap between backtested and live performance in prediction markets is dominated by three factors: **fees, slippage, and fill rates**. Modeling these correctly will likely reduce your 128% ARR by 20–50%.

**Fee structure (as of March 2026):**

Most Polymarket markets charge **zero taker fees**—a critical advantage. However, 5-minute and 15-minute crypto markets use a nonlinear fee formula that peaks at **~1.56% at the 50¢ price level**:

```python
def taker_fee(p: float, fee_rate: float = 0.0625) -> float:
    """Parabolic taker fee. Zero at extremes, maximum at p=0.50."""
    return p * (1 - p) * fee_rate
```

Weather markets carry a **2% winner fee** on resolved positions but no taker fee. For a weather strategy, this means every winning trade loses 2% of its gross payout—a constraint that sets the minimum exploitable edge at roughly 2.5–3% after accounting for spread costs.

**Slippage modeling by market tier:**

Polymarket liquidity is extremely concentrated. Analysis of 290,000 markets reveals that **63% of active short-term markets have zero 24-hour volume**, while top political markets hold ~$450K in depth. Weather markets sit in between, with $2K–$1M in liquidity depending on the city.

| Market Type | Typical Spread | Slippage per $1K Traded |
|------------|---------------|------------------------|
| High-volume politics/crypto | 1–2¢ | 0.1–0.5% |
| Major US city weather (NYC, Atlanta) | 4–10¢ | 0.5–2% |
| International weather (Seoul, London) | 10–30¢ | 2–10%+ |
| Niche/illiquid markets | 10–34¢+ | Effectively untradeable at scale |

For your backtest, implement depth-based slippage by fetching the full orderbook and computing average execution price across levels:

```python
def estimate_slippage(book_side: list, order_size: float) -> float:
    """Walk the book to compute average fill price for a given order size."""
    filled, cost = 0.0, 0.0
    for level in book_side:
        price, size = float(level["price"]), float(level["size"])
        fill_at_level = min(size, order_size - filled)
        cost += fill_at_level * price
        filled += fill_at_level
        if filled >= order_size:
            break
    return cost / filled if filled > 0 else None
```

**Fill rate assumptions** deserve special attention. Polymarket uses **off-chain matching** with no transparent queue priority, making classical queue-position models unreliable. For limit orders in thin weather markets, assume **30–60% fill rates** for orders within 2¢ of midpoint and near-zero fill rates for orders 5¢+ away in markets with zero 24-hour volume. Post-only orders (available since January 2026) guarantee maker status but cannot cross the spread.

**There are no formal position limits** on Polymarket, but practical constraints are severe: the effective position limit equals available orderbook depth. A $10K order in a NYC weather market with $85K total volume will move the price substantially.

---

## 3. Backtesting prediction markets requires fundamentally different methods

Standard equity backtesting frameworks fail for prediction markets because returns are **binary** (win/lose), positions have **finite lifespans**, and prices represent **probabilities** rather than asset values. Three methodological adaptations are essential.

**Walk-forward optimization must use market cohorts, not calendar windows.** Since each prediction market has a defined resolution date, rolling windows should be defined by groups of contemporary markets rather than fixed time periods. Walk-Forward Efficiency (WFE = annualized OOS return / annualized IS return) above **50–60%** suggests robustness; below 50% indicates overfitting. However, Arian, Norouzi, and Seco (2024) found that **Combinatorial Purged Cross-Validation (CPCV) has marked superiority** over walk-forward analysis, with lower Probability of Backtest Overfitting and superior Deflated Sharpe Ratio statistics.

**Minimum sample sizes are larger than most traders realize.** For a claimed 60% win rate, the binomial confidence interval at 95% confidence is:

```
CI = p̂ ± 1.96 × √(p̂(1-p̂)/n)
```

| Trades (n) | 95% CI for 60% Win Rate | z-stat vs 50% | p-value |
|-----------|------------------------|---------------|---------|
| 50 | [46.4%, 73.6%] | 1.41 | 0.079 — **not significant** |
| 100 | [50.4%, 69.6%] | 2.00 | 0.023 — barely significant |
| 200 | [53.2%, 66.8%] | 2.83 | 0.002 — significant |
| 385 | [55.1%, 64.9%] | 3.92 | <0.0001 — highly significant |

You need **at least 200 trades** to establish a 60% win rate as statistically distinguishable from chance at p < 0.01, and **~385 trades** for a ±5% margin of error at 95% confidence. The Wilson Score interval should replace the Wald interval for samples under 150 trades.

**Brier score decomposition reveals whether your predictions are calibrated or merely lucky.** The Murphy (1973) decomposition splits the Brier score (BS = mean of (forecast − outcome)²) into three components:

```
BS = Reliability − Resolution + Uncertainty
```

- **Reliability (lower is better):** measures calibration error—how close your probability estimates are to observed frequencies
- **Resolution (higher is better):** measures discrimination—how well you separate likely from unlikely outcomes
- **Uncertainty (fixed):** inherent unpredictability = base_rate × (1 − base_rate)

Polymarket's aggregate Brier score across ~90,000 predictions is **0.058** at 12-hour horizons, with highly liquid markets achieving **0.026**. A profitable trading strategy should demonstrate BS < 0.15, with the edge coming from high resolution (discriminating signal) rather than poor calibration of the market itself.

---

## 4. De Prado's framework catches strategies that look good but aren't

The most dangerous failure mode in prediction market strategy development is **multiple testing bias**—testing many strategy variants and cherry-picking the best performer. Bailey, Borwein, López de Prado, and Zhu (2014) proved that after only 1,000 independent backtests with zero true skill, the expected maximum Sharpe Ratio is **3.26**, purely from randomness. No raw Sharpe threshold is safe without correction.

**The Deflated Sharpe Ratio (DSR)** corrects for the number of strategies tested, non-normality of returns, and sample length. The formula:

```
DSR = Φ[(SR̂ − SR₀) × √(T−1) / √(1 − γ₃·SR̂ + (γ₄−1)/4 · SR̂²)]
```

where SR₀ is the expected maximum Sharpe from random strategies, γ₃ is skewness, γ₄ is kurtosis, and Φ is the standard normal CDF. **DSR ≥ 0.95 is required** to conclude genuine skill at 95% confidence. A strategy with Sharpe 1.92 and an apparently impressive Probabilistic Sharpe Ratio of 0.99 might have DSR of only 0.82 after accounting for 5,000 tested variants—failing the threshold entirely.

**CPCV implementation** partitions your trade data into N groups, computes all C(N,k) train/test combinations with temporal purging (removing training observations whose resolution periods overlap test observations) and embargoing (adding buffers to handle serial correlation). The key output is the **Probability of Backtest Overfitting (PBO)**—the fraction of CPCV paths where the IS-optimal strategy underperforms OOS. Target **PBO < 0.40**; values above 0.50 indicate the strategy is likely overfit. Available implementations include `skfolio.model_selection.CombinatorialPurgedCV` and `mlfinlab.cross_validation.cpcv`.

**Kelly Criterion for prediction market position sizing** simplifies elegantly for binary contracts. For a YES contract at price c with estimated true probability p:

```
f* = (p − c) / (1 − c)
```

At p = 0.70 and c = 0.55: f* = 0.15/0.45 = **33.3%** of bankroll. This is dangerously aggressive. **Half-Kelly (f*/2 ≈ 16.7%)** sacrifices only ~25% of geometric growth rate while dramatically reducing variance and the probability of ruin. For prediction markets specifically, **quarter-Kelly** is defensible given the inherent uncertainty in probability estimation. Never allocate more than 20–25% to a single market regardless of Kelly output, and adjust the edge calculation for fees: effective_edge = (p − c) − fee_rate.

**Monte Carlo ruin analysis** should target < 5% probability of hitting a 50% drawdown. Run at least 10,000 simulations. Critical finding: **the 95th percentile Monte Carlo drawdown is typically 1.5–3× the backtest maximum drawdown.** A strategy showing 23% max drawdown in backtesting may face 50–70% drawdown potential in practice.

| Validation Metric | Healthy Range | Red Flag |
|-------------------|--------------|----------|
| Backtest Sharpe | 0.5–2.5 | > 3.0 |
| OOS/IS Sharpe Ratio | > 0.50 | < 0.50 |
| Deflated Sharpe Ratio | > 0.95 | < 0.95 |
| PBO (CPCV) | < 0.40 | > 0.50 |
| Monte Carlo P(Ruin) | < 5% | > 10% |
| Min trades for significance | 200–500 | < 100 |

---

## 5. Weather market edge is real but narrowing fast

The core weather arbitrage thesis is sound: **NOAA 24-hour temperature forecasts achieve ~85–90% accuracy** (MAE of ~2–3°F for daily high temperature), while Polymarket weather market prices frequently lag forecast updates by minutes to hours. This creates latency arbitrage between professional weather models and crowd-driven pricing.

**Forecast accuracy by lead time (NOAA/NWS):**

- **12-hour:** MAE ~1.4°F — extremely precise
- **24-hour:** MAE ~2–3°F — reliable enough to identify 2°F bucket with 70–85% confidence
- **48-hour:** MAE ~3–4°F — still useful but widens the probability distribution across 2–3 adjacent buckets
- **5-day:** ~90% accuracy; equivalent to a 3-day forecast from 2002
- **10+ days:** ~50% accuracy — essentially useless for trading

Temperature is the most predictable variable; precipitation is significantly harder (HSS of only 0.49 for 24-hour forecasts). Geographic variation matters: Southwest US forecasts hold accuracy 5–6 days out, while Great Plains accuracy drops after 2 days. Summer forecasts are substantially more accurate than winter.

**Polymarket weather markets** number roughly **357 active markets** covering 30+ cities globally. The dominant format is daily high temperature bucketed into 2–3°F ranges, resolving against NWS CLI (Climatological Report) data. Liquidity varies enormously:

- **NYC/Atlanta:** $55K–$85K volume, $500K–$1M liquidity — tradeable at meaningful size
- **London/Seoul:** $45K–$60K volume, $2K–$4K liquidity — thin, moves easily
- **Smaller cities:** Often < $10K volume — micro-positions only

**Documented profitable weather traders** include accounts like "gopfan2" (reportedly $2M+ net profit) and several automated bots turning $1K–$2.3K into $18K–$65K by exploiting forecast-price discrepancies. The core strategy: buy shares priced at $0.01–$0.15 for outcomes NOAA considers 70%+ likely, capturing 5–20%+ mispricings that persist for minutes to hours after forecast model updates.

**Forecast model update schedule creates specific trading windows:**
- **GFS:** Updates at 00, 06, 12, 18 UTC (every 6 hours)
- **ECMWF:** Updates at 00, 12 UTC (every 12 hours)
- **HRRR:** Hourly updates for US locations

After a model run showing a significant temperature shift (≥2°F), Polymarket prices often haven't adjusted—creating the arbitrage window. Multi-model consensus (GFS + ECMWF + HRRR agreement) provides the highest-confidence signals.

**Edge calculation for weather trades:**
```
Gross EV = true_probability × $1.00
Net EV = true_probability × $0.98  (after 2% winner fee)
Edge per share = Net EV − market_price
Expected profit = (p × ($0.98 − cost)) − ((1−p) × cost)
```

For p = 0.70, market_price = $0.50: expected profit = 0.70 × $0.48 − 0.30 × $0.50 = **$0.186 per share**. However, this edge is compressing as more bots enter the market. Multiple sources note tightening spreads and faster price adjustments to forecast updates throughout 2025–2026.

**Key data sources for automated weather trading:** NWS API (`api.weather.gov` — free, JSON REST), NOAA CDO API (historical climate data, 5 req/s limit), Open-Meteo API (free, multi-model, Historical Forecast API for training ML models), and `noaa-sdk` Python wrapper.

---

## 6. Sharpe ratios and calibration metrics for prediction market portfolios

Calculating performance metrics for binary outcome strategies requires adapting standard formulas to handle bimodal return distributions. **The standard Sharpe ratio's √N annualization assumes i.i.d. normal returns—both assumptions are violated by prediction market trades.** Binary outcomes produce returns that cluster at two extremes (full win, full loss), and correlated markets (e.g., multiple weather markets on the same weather system) violate independence.

The most defensible approach: calculate **daily portfolio-level P&L** by marking positions to market, then compute the daily Sharpe and annualize with √252. For the risk-free rate, use the **Aave USDC supply rate (~4–6% APY)** as the true opportunity cost of deploying USDC into prediction markets rather than DeFi lending.

**Realistic Sharpe expectations:** A Sharpe of **1.0–1.5 would be very strong** for a systematic prediction market strategy. Above 2.0, suspect overfitting. Harvey and Liu (2014) recommend requiring **t-statistics > 3.0** (not the traditional 2.0) to account for multiple testing, and even higher (3.5–5.0) for extensive strategy search. The relationship t = Sharpe × √(years) means a Sharpe of 1.5 needs roughly 4 years of data to reach t = 3.0.

**Calibration curves** are arguably more important than Sharpe ratios for prediction market strategies. Plot your predicted probabilities (x-axis) against actual resolution rates (y-axis) across decile bins. A well-calibrated strategy lies on the 45° diagonal. Kalshi analysis across 3,587 markets shows **92.4% aggregate accuracy** but with a persistent **favorite-longshot bias**: events priced above 80% resolve only ~84% of the time. This bias represents a systematic opportunity for contrarian strategies.

**Is 128% ARR realistic?** It falls in the plausible-but-suspicious range. Key stress tests to apply:

- Reduce reported returns by estimated slippage (10–30% reduction for weather markets)
- Apply the Deflated Sharpe Ratio with honest accounting of all strategy variants tested
- Run Monte Carlo simulation: the 95th percentile return will likely be 30–50% lower than the median
- Check OOS/IS degradation: if OOS returns < 50% of IS returns, the strategy is likely overfit
- Verify sample size: < 200 trades makes statistical significance nearly impossible to establish

Across the Polymarket ecosystem, **70% of traders lose money** and only **0.51% of wallets** achieve profits exceeding $1,000. The top 0.04% capture 71% of all gains. These base rates should calibrate your priors before accepting any high-return backtest at face value.

---

## 7. Polymarket is now federally legal for US users, but complexity lurks beneath

The regulatory landscape transformed dramatically in 2025. After the **$1.4 million CFTC settlement in January 2022** forced Polymarket to block US users, the company spent three years rebuilding its regulatory position. In **July 2025**, Polymarket acquired QCEX for $112 million—obtaining a CFTC-designated DCM license—and the DOJ/CFTC formally ended investigations without new charges. By **November 2025**, the CFTC issued an Amended Order of Designation permitting Polymarket to operate as a fully regulated intermediated trading platform, and **December 2, 2025** marked the official US relaunch on an invite-only basis.

**Two separate platforms now exist:** the global crypto-wallet-based platform (still geo-blocked for US users) and the US CFTC-regulated platform requiring KYC and FCM intermediation. US traders attempting to access the global platform via VPN risk having funds frozen.

**For a pooled investment vehicle trading prediction markets**, the regulatory path involves:

- **Fund structure:** Delaware LP or LLC with GP/LP structure; prediction market contracts are CFTC-regulated derivatives, not securities, which may avoid Investment Company Act classification
- **Adviser registration:** Private Fund Adviser Exemption (ERA status) for AUM under **$150 million**, requiring Form ADV filing but not full SEC registration
- **Investor requirements:** Regulation D 506(b) allows up to 35 non-accredited sophisticated investors plus unlimited accredited investors (no general solicitation); 506(c) permits advertising but requires accredited-only and verification. March 2025 SEC guidance eased verification burdens.
- **Investment Company Act exemptions:** Section 3(c)(1) limits the fund to **100 beneficial owners**; Section 3(c)(7) requires qualified purchasers ($5M+ investments) but allows up to 2,000 investors

**The CFTC's regulatory posture has shifted dramatically pro-prediction-market.** Chairman Michael Selig withdrew the Biden-era proposed rule that would have banned political and sports event contracts (January 29, 2026) and announced new, more permissive rulemaking. However, **state-level friction is intensifying**: Massachusetts, Nevada, Maryland, and others have issued cease-and-desist orders or preliminary injunctions against prediction market operators, arguing these contracts constitute gambling under state law. The Kalshi litigation across multiple state courts remains unresolved, with conflicting rulings on CEA preemption of state gambling laws.

Two recent CFTC enforcement cases on KalshiEX established that **insider trading rules fully apply** to prediction markets under Section 6(c)(1) of the CEA, with penalties including fines and multi-year trading bans.

---

## Conclusion: a concrete validation checklist

The framework for validating your 128% ARR strategy requires passing each gate sequentially, not selectively. **First, verify data integrity:** ensure your backtest uses point-in-time orderbook data (not midpoint prices) with realistic slippage, the 2% winner fee on weather markets, and conservative fill rate assumptions of 30–60% for limit orders. Second, **establish statistical significance**: with the sample sizes typical of weather market trading, you need 200+ resolved trades to distinguish a 60% win rate from chance—and the Deflated Sharpe Ratio must exceed 0.95 after honest accounting of all strategy variants explored. Third, **stress-test with Monte Carlo**: run 10,000 simulations to estimate the 95th percentile drawdown and probability of ruin at your planned position sizing. The 95th percentile return, not the median, is your realistic planning number.

The most actionable insight from this research is that **the weather market edge is genuine but rapidly compressing**. NOAA's 24-hour forecast accuracy creates a real informational advantage over crowd pricing, with documented mispricings of 15–30%. But increasing bot competition is tightening this window from hours to minutes after forecast updates. A strategy that achieved 128% ARR six months ago may achieve 60% ARR today—making the recency and out-of-sample period of your backtest the single most important variable to scrutinize.