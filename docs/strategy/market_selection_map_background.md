# Market Selection Map: Prediction Market Category Analysis

*Prepared: March 2026 | Target platforms: Polymarket, Kalshi, and cross-platform*

---

## Executive Summary

Prediction markets have exploded to ~$44B in annual volume across platforms (2025), up ~300x from early 2024. Wall Street firms (DRW, Susquehanna, Jump Trading) are building dedicated desks, compressing edges fast. Only ~7.6% of Polymarket wallets are profitable. The window for retail-scale systematic strategies is narrowing but category selection determines whether you're fishing in a pond with Goldman or one they haven't bothered with yet.

This document maps nine categories across six dimensions to identify where residual inefficiency is large enough to survive fees, slippage, and dispute risk.

---

## Category Matrix

### 1. Weather

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | Retail traders anchor on "feels like" intuition and recent weather rather than NWP model ensembles. Forecast skill degrades sharply beyond 7 days but markets price longer horizons as if skill is linear. Localized events (city-level temperature, precipitation) attract thin participation. |
| **Data Availability** | **Free:** NOAA GFS/GEFS, ECMWF open data, NWS forecasts, Iowa State Mesonet archives. **Paid:** ECMWF HRES/ENS (gold standard, ~€5K–50K/yr depending on tier), IBM Weather Company, Tomorrow.io API. |
| **Resolution Clarity** | **High.** Kalshi weather markets resolve against NWS final climate reports — objective, timestamped, rarely disputed. Binary framing (above/below threshold) is clean. *[Needs verification: whether Polymarket offers equivalent weather markets with similar resolution sources.]* |
| **Liquidity Profile** | **Low-to-moderate.** Kalshi offers weather markets but specific volume data isn't publicly broken out. Likely $10K–$100K per market. Capacity ceiling is low; a $50K position would move most markets. |
| **Best-Fit Edge Families** | **Structural/model superiority.** If you run ECMWF ENS or a calibrated ML post-processing model, you have a durable information edge over retail anchoring on GFS or gut feel. Latency is irrelevant (markets move on daily timescales). |
| **Holding Horizon** | 1–10 days. Enter when your model diverges from market-implied probability; hold to resolution. |

**Verdict: HIGH POTENTIAL — low competition, clean resolution, durable model edge. Capacity-constrained.**

---

### 2. Sports (Major Leagues: NFL, NBA, MLB, Soccer)

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | Fan bias (hometown overweighting), narrative recency bias, slow incorporation of injury/lineup news in prediction markets vs. sportsbooks. However, Polymarket sports markets accuracy is high (~85%+ for liquid markets). Wash trading inflates apparent volume — Columbia researchers found 45% of sports volume on Polymarket was artificial. |
| **Data Availability** | **Free:** ESPN, Basketball-Reference, FBref, injury reports, social media. **Paid:** Statcast, Second Spectrum, Opta, PFF ($500–$5K/yr), real-time odds feeds from sportsbooks. |
| **Resolution Clarity** | **High** for final outcomes (win/loss). **Moderate** for prop-style markets (player performance thresholds can have edge cases). |
| **Liquidity Profile** | **High** for major events (Super Bowl, NBA Finals: $1M+ markets). **Low** for mid-season regular games. Capacity is decent for marquee events only. *[Needs verification: current Polymarket sports market depth vs. Kalshi sports contracts, given Kalshi's recent sports expansion.]* |
| **Best-Fit Edge Families** | **Latency** (injury news, lineup changes — but sportsbooks are faster). **Cross-market arbitrage** (prediction market vs. sportsbook implied probabilities). **Structural** (prediction markets may lag sportsbook line moves by minutes to hours). |
| **Holding Horizon** | Minutes (latency plays) to days (pre-game positioning). |

**Verdict: MODERATE — edges exist but professional sportsbook arb desks and bots are already here. The 45% wash-trading figure means apparent liquidity overstates real capacity. Marquee events only.**

---

### 3. Politics (Elections, Legislation, Appointments)

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | **Partisan bias** is the single largest structural inefficiency — traders bet their hopes, not their models. Polling aggregation models (538-style) consistently outperform raw market prices during non-terminal periods. However, markets become very efficient in the final 48 hours. Insider information risk is real (Google insider case: 22-for-23, $3M→$4.15M). |
| **Data Availability** | **Free:** FiveThirtyEight/Silver Bulletin, RCP averages, FEC filings, PACER (court dockets), congressional calendars. **Paid:** Predictit/Metaculus calibration data, partisan polling crosstabs, campaign finance analytics. |
| **Resolution Clarity** | **High** for elections (certified results). **Low-to-moderate** for legislation ("will bill pass by X date" — amendments, procedural tricks create ambiguity). **Low** for appointment markets (confirmation timing is unpredictable). |
| **Liquidity Profile** | **Very high** for presidential/major elections ($100M+ on Polymarket for 2024 presidential). **Moderate** for Senate/House races. **Low** for state-level or policy markets. Deep capacity for top-of-ticket only. |
| **Best-Fit Edge Families** | **Structural** (polling model vs. partisan-biased market). **Microstructure** (buying at 95¢ on "already decided" outcomes for annualized yield — the "high-probability bond" strategy). **Calendar** (buying dips during noise events that don't change fundamentals). |
| **Holding Horizon** | Weeks to months for polling-model strategies. Hours to days for the high-probability bond approach. |

**Verdict: HIGH POTENTIAL for major cycles, but episodic — 18 months of nothing, then 6 months of deep liquidity. Partisan bias is real and exploitable. Off-cycle, capacity is near zero.**

---

### 4. Macro / Economics (Fed rates, CPI, GDP, unemployment)

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | Markets converge quickly to Fed Funds futures and CME FedWatch. Residual edge is small and exists mainly in the "last mile" — when the market is at 92¢ and you have reason to believe resolution is certain, you capture a small yield. Retail traders occasionally misprice conditional scenarios (e.g., emergency cuts). |
| **Data Availability** | **Free:** FRED, BLS releases, Fed minutes/dot plots, CME FedWatch. **Paid:** Bloomberg terminal, Macroeconomic Advisers (GDP nowcast), Cleveland Fed inflation expectations. |
| **Resolution Clarity** | **Very high.** Fed rate decisions, BLS prints, and GDP releases are unambiguous. Best resolution clarity of any category. |
| **Liquidity Profile** | **Moderate-to-high** on Kalshi for Fed rate decisions (Kalshi is CFTC-regulated for these). Polymarket also offers these. $100K+ positions possible on major decisions. *[Needs verification: Kalshi vs. Polymarket spread comparison for identical macro markets.]* |
| **Best-Fit Edge Families** | **High-probability bond** (buying near-certain outcomes at 95–98¢ for annualized yield). **Latency** (reacting to data releases faster than prediction market order books update — but CME futures are faster). **Cross-market arb** (prediction market vs. CME Fed Funds futures implied probabilities). |
| **Holding Horizon** | Days to weeks for bond-style. Seconds to minutes for latency (extremely competitive). |

**Verdict: LOW EDGE — macro markets are the most efficiently priced category because they're directly arbitrageable against deep, liquid CME derivatives. The bond strategy works but yields are thin after fees.**

---

### 5. Tech Milestones (AI benchmarks, product launches, regulatory actions)

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | **High narrative sensitivity** — hype cycles cause systematic overpricing of "by date X" milestones. Insiders at major tech companies have asymmetric information about launch timelines. Public rarely calibrates well on technical feasibility (e.g., AGI timelines, self-driving deployment dates). |
| **Data Availability** | **Free:** ArXiv, GitHub repos, FCC filings, patent databases, company blogs, SEC filings. **Paid:** expert networks (GLG, AlphaSights), Gartner/IDC reports, semiconductor supply chain trackers. |
| **Resolution Clarity** | **Low-to-moderate.** "Will GPT-5 be released by Q2 2026?" — what counts as "released"? API access? Public launch? Waitlist? Polymarket has faced disputes over ambiguous tech milestone definitions. *[Needs verification: specific disputed tech markets on Polymarket.]* |
| **Liquidity Profile** | **Low-to-moderate.** AI-related markets occasionally spike to $500K+ but most tech milestones are $10K–$100K. Thin order books. |
| **Best-Fit Edge Families** | **Structural/domain expertise** (if you understand the technical pipeline, you can price feasibility better than narrative-driven retail). **Information edge** (monitoring GitHub commits, API changelogs, job postings for signal). **Contrarian** (fading hype-driven overpricing on ambitious timelines). |
| **Holding Horizon** | Weeks to months. Slow-moving, thesis-driven. |

**Verdict: MODERATE — real edges from domain expertise but resolution ambiguity is a serious risk. Insider information asymmetry works against you unless you're the insider.**

---

### 6. Legal / Court Rulings

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | General public is terrible at predicting legal outcomes — anchoring on media narratives rather than procedural/precedent analysis. Legal experts have meaningful calibration advantages. However, markets are thin and timing is unpredictable (continuances, settlements). |
| **Data Availability** | **Free:** PACER, CourtListener, SCOTUSblog, oral argument transcripts. **Paid:** Lex Machina, Westlaw analytics, Bloomberg Law litigation analytics. |
| **Resolution Clarity** | **Moderate.** Binary rulings (guilty/not guilty, affirm/reverse) are clean. But "will X be indicted by date Y" or "will settlement exceed $Z" introduce timing and definitional ambiguity. |
| **Liquidity Profile** | **Very low** except for marquee cases (Trump indictments saw significant volume). Most legal markets are $5K–$50K. Capacity is minimal. |
| **Best-Fit Edge Families** | **Domain expertise** (former clerks, litigators have genuine calibration edge). **Structural** (oral argument analysis — Supreme Court prediction models using argument transcripts achieve ~70% accuracy vs. base rate ~60%). |
| **Holding Horizon** | Weeks to months. Courts operate on their own timeline. Capital is locked for extended, unpredictable periods. |

**Verdict: MODERATE EDGE, POOR CAPACITY — genuine inefficiency exists but liquidity is too thin for systematic scale. Better as a supplementary category than a core strategy.**

---

### 7. Entertainment (Awards, Box Office, TV ratings)

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | Fan/popularity bias dominates — voters ≠ fans, and prediction markets overweight popular favorites. Industry insiders (academy members, guild voters, studio marketing teams) have strong private information. Oscars/Emmys precursor analysis (guild awards → Oscar winners) is underused by retail. |
| **Data Availability** | **Free:** Box Office Mojo, TMDb, guild award results, social media sentiment. **Paid:** Comscore, Nielsen, Quorum analytics, industry trade subscriptions (Variety, Deadline). |
| **Resolution Clarity** | **High** for awards (winner is announced). **Moderate** for box office (domestic vs. worldwide, opening weekend definition). |
| **Liquidity Profile** | **Low.** Awards markets rarely exceed $50K–$100K except for the Oscars Best Picture race. Box office markets are thin. |
| **Best-Fit Edge Families** | **Structural** (precursor modeling — tracking guild/critics awards as leading indicators). **Sentiment analysis** (industry trade vs. public perception divergence). |
| **Holding Horizon** | Weeks (awards season runs Nov–Mar). |

**Verdict: MODERATE EDGE, POOR CAPACITY — similar to legal. Real inefficiency, but too thin to scale. Seasonal.**

---

### 8. Crypto (Price thresholds, ETF approvals, protocol milestones)

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | **Reflexivity** — crypto prediction markets are on crypto platforms, attracting crypto-bullish traders who systematically overprice bullish outcomes. Correlation between platform activity and underlying asset creates structural bias. However, sophisticated quant firms are now active. |
| **Data Availability** | **Free:** CoinGecko, DeFiLlama, Glassnode (limited free tier), on-chain explorers, exchange order books. **Paid:** Glassnode Pro, Kaiko, Amberdata, Nansen (~$1K–$10K/yr). |
| **Resolution Clarity** | **Moderate.** Price thresholds should be clean but disputes have occurred over which exchange/aggregator is the resolution source. CoinMarketCap vs. CoinGecko vs. exchange-specific prices diverge during volatility. Polymarket has had crypto market resolution disputes (Coinbase vs. Upbit volume controversy). |
| **Liquidity Profile** | **Moderate-to-high** for BTC/ETH price milestones ($100K+ markets common). **Low** for altcoin or protocol-specific markets. |
| **Best-Fit Edge Families** | **Cross-market arb** (prediction market implied probability vs. options-market implied probability from Deribit/CME). **Structural** (fading the reflexive bullish bias in the trader base). **Microstructure** (prediction markets update slower than spot/derivatives during volatility spikes). |
| **Holding Horizon** | Days to weeks for price thresholds. Months for ETF/regulatory approvals. |

**Verdict: MODERATE — reflexive bias is real but crypto quant firms are already exploiting it. Resolution disputes are a genuine risk. Cross-market arb with options is the cleanest edge but requires capital in both prediction markets and derivatives.**

---

### 9. Geopolitics (Conflicts, treaties, sanctions, regime change)

| Dimension | Assessment |
|---|---|
| **Inefficiency Drivers** | Availability bias (media-salient events are overpriced) and anchoring on status quo. Intelligence community analysts are better calibrated than markets on geopolitical transitions, but that information isn't public. Black-swan tail risk is systematically underpriced in "will X NOT happen" contracts. |
| **Data Availability** | **Free:** ACLED conflict data, UN reports, SIPRI, satellite imagery (Sentinel Hub), OSINT Twitter/Telegram. **Paid:** Stratfor, RANE, Eurasia Group, Recorded Future (~$10K–$100K/yr). |
| **Resolution Clarity** | **Low.** "Will Russia and Ukraine reach a ceasefire by X?" — what constitutes a ceasefire? Who declares it? Polymarket geopolitical markets have notoriously ambiguous resolution criteria. Disputes are common. |
| **Liquidity Profile** | **Moderate** during active crises (Ukraine, Taiwan markets have seen $500K+). **Very low** otherwise. Extremely spiky and event-driven. |
| **Best-Fit Edge Families** | **OSINT/information edge** (satellite imagery analysis, ship tracking, flight data for military movements). **Contrarian** (selling overpriced tail-risk scenarios). **Structural** (status-quo bias means "nothing happens" is systematically underpriced). |
| **Holding Horizon** | Weeks to months. Capital lock-up risk is high due to unpredictable timelines. |

**Verdict: HIGH EDGE POTENTIAL, HIGH RISK — genuine inefficiency but resolution ambiguity and unpredictable timelines make this dangerous for systematic strategies. Better for discretionary OSINT specialists than automated systems.**

---

## Summary Scoring Matrix

| Category | Inefficiency Size | Data Edge Feasibility | Resolution Clarity | Liquidity / Capacity | Systematic Fit | Overall |
|---|---|---|---|---|---|---|
| **Weather** | ★★★★ | ★★★★★ | ★★★★★ | ★★ | ★★★★★ | **A** |
| **Politics** | ★★★★ | ★★★★ | ★★★★ | ★★★★ (cyclical) | ★★★★ | **A-** |
| **Sports** | ★★★ | ★★★ | ★★★★ | ★★★★ | ★★★ | **B+** |
| **Crypto** | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ | **B** |
| **Tech Milestones** | ★★★ | ★★★ | ★★ | ★★ | ★★★ | **B-** |
| **Legal/Court** | ★★★★ | ★★★ | ★★★ | ★ | ★★ | **C+** |
| **Entertainment** | ★★★ | ★★★ | ★★★★ | ★ | ★★ | **C+** |
| **Geopolitics** | ★★★★ | ★★★ | ★★ | ★★ | ★★ | **C** |
| **Macro** | ★ | ★★ | ★★★★★ | ★★★ | ★★ | **C-** |

---

## Top 3 Categories to Start — Ranked

### 1. Weather

**Why start here.** Weather is the single best category for a systematic, model-driven approach. The edge is durable because it's rooted in superior forecasting models (ECMWF ENS + ML post-processing) rather than speed or information access. Resolution is unambiguous (NWS reports). Competition is thin — Wall Street quant desks aren't building weather prediction market desks because the capacity is too small for them, which is exactly why it's attractive for a smaller operation. The main constraint is capacity ($50K–$100K positions would be the practical ceiling per market), so this works as a high-Sharpe, low-capacity core.

**How to build the edge:** License ECMWF ENS data, build a calibrated probabilistic post-processing model (quantile regression or neural network on historical NWP output vs. observed), compare your CDF against market-implied probabilities, trade when divergence exceeds fee+spread threshold.

### 2. Politics (Election Cycles)

**Why start here.** Partisan bias is the most well-documented structural inefficiency in prediction markets. During active election cycles, the combination of a rigorous polling aggregation model and the high-probability bond strategy on resolved-but-unsettled outcomes creates two distinct and complementary edge sources. Liquidity is excellent for top-of-ticket races. The main risk is that this is episodic — you need a plan for off-cycle periods.

**How to build the edge:** Build or license a polling aggregation model with demographic and turnout adjustments. Monitor for divergence between model-implied probabilities and market prices. Layer in the bond strategy (buying 95¢+ contracts on near-certain outcomes for yield). Size aggressively during primary season and general election; scale to zero off-cycle.

### 3. Crypto (Price Thresholds + Cross-Market Arb)

**Why start here.** The reflexive bullish bias in the Polymarket trader base creates a structural, repeatable edge — especially on "BTC above $X by date Y" markets where options-implied probabilities from Deribit or CME provide a clean anchor. Cross-market arbitrage between prediction market prices and options-implied probabilities is the most quantifiable edge in this category. Liquidity is reasonable for BTC/ETH markets. The risk is resolution disputes and platform-specific issues.

**How to build the edge:** Build a pipeline that converts Deribit/CME BTC/ETH options surfaces into implied probabilities for the same thresholds prediction markets are pricing. Trade when prediction market price > options-implied probability + fee threshold (selling the bullish bias) or vice versa.

---

## Do-Not-Touch List

### 1. Macro / Economics

**Why avoid.** These markets are directly arbitrageable against the deepest, most liquid derivatives markets in the world (CME Fed Funds futures, Eurodollar futures, TIPS breakevens). Any mispricing is corrected in seconds by institutional desks with co-located infrastructure. The "bond strategy" (buying at 95–98¢) yields 2–5% over days, but after Polymarket/Kalshi fees and capital lock-up opportunity cost, net returns are marginal. You're competing with Susquehanna and DRW on their home turf.

### 2. Geopolitics

**Why avoid.** Despite genuine inefficiency, the combination of: (a) extremely ambiguous resolution criteria that invite disputes, (b) unpredictable and often very long capital lock-up periods, (c) event-driven liquidity that evaporates when you need to exit, and (d) insider information asymmetry from intelligence/government sources makes this systematically untradeable. Polymarket geopolitical market disputes have been among the most contentious on the platform. Edges here favor discretionary OSINT analysts, not systematic strategies.

### 3. Entertainment (Awards, Box Office)

**Why avoid.** Real inefficiency exists (precursor modeling works) but liquidity is simply too thin to matter. Even if you nail every Oscar category, the total addressable profit across an entire awards season might be $10K–$20K before fees. The opportunity cost of building and maintaining an entertainment prediction pipeline is not justified by the available capacity. Seasonal concentration (November–March) compounds the problem.

### Honorable Mention: Legal / Court

**Near the line.** Genuine domain-expertise edge exists and resolution is cleaner than geopolitics, but liquidity is typically too thin for systematic scale. Worth monitoring for high-profile cases where volume spikes (Supreme Court term, major criminal trials) but not worth building dedicated infrastructure for.

---

## Platform-Specific Notes

*All items below are labeled per the constraint that platform-specific behavior needs verification unless reliably cited.*

- **Polymarket fees:** ~2% on winning positions (embedded in CLOB spread, not a separate fee). *[Needs verification: fee structure may have changed with US re-entry in 2025.]*
- **Kalshi fees:** 7¢ per contract on event contracts; 0 fees on some promotional markets. *[Needs verification: current fee schedule.]*
- **Polymarket US vs. International:** Different resolution processes — US version has direct Markets Team resolution; International uses UMA Oracle with token-weighted voting. *[Verified per Polymarket documentation.]*
- **Cross-platform arbitrage:** Simultaneous positions on Polymarket + Kalshi for the same event can capture pricing divergence but capital is locked on both platforms. Polymarket requires USDC on Polygon; Kalshi accepts USD. *[Needs verification: whether identical markets exist on both platforms with sufficient frequency.]*
- **Wash trading:** Columbia University research found ~25% average wash trading across Polymarket, spiking to 45% for sports. This means apparent liquidity significantly overstates real depth. *[Verified per Columbia research, November 2025.]*

---

## Key References

- [Arbitrage in Prediction Markets — arXiv (Aug 2025)](https://arxiv.org/abs/2508.03474)
- [Polymarket Accuracy Analysis — Fensory (2026)](https://www.fensory.com/intelligence/predict/polymarket-accuracy-analysis-track-record-2026)
- [Polymarket Wash Trading — Fortune / Columbia Research (Nov 2025)](https://fortune.com/2025/11/07/polymarket-wash-trading-inflated-prediction-markets-columbia-research/)
- [Polymarket Dispute Resolution — Polymarket Docs](https://docs.polymarket.com/polymarket-learn/markets/dispute)
- [Kalshi Weather Markets — Kalshi Help Center](https://help.kalshi.com/markets/popular-markets/weather-markets)
- [Prediction Markets Legal Crossroads 2026 — Holland & Knight](https://www.hklaw.com/en/insights/publications/2026/02/prediction-markets-at-a-crossroads-the-continued-jurisdictional-battle)
- [Prediction Market Insider Trading Analysis — philippdubach.com](https://philippdubach.com/posts/the-absolute-insider-mess-of-prediction-markets/)
