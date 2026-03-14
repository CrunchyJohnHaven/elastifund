# Polymarket LLM Trading Bot Research

**Model: GPT-4.5 (state-of-the-art)**

This analysis shows AI bots excel in high-data, liquid markets (sports, crypto, politics) by exploiting news/poll data and arbitrage. Academic benchmarks reveal LLM forecasts still trail expert humans, but aggregated LLM ensembles can match the wisdom of crowds. Prediction markets often show inefficiencies ripe for bots (e.g. US election markets were only ~67% accurate on Polymarket). Thus an LLM-based trading bot should prioritize sectors with rich real-time information and liquidity (see ranked list below). Robust data feeds (news, polls, economic releases, social sentiment, search trends, sportsbook odds) are critical to capture emerging signals.

---

## 1. Market Category Analysis

### 1a. Political Elections
These markets have very high liquidity (Polymarket's political category saw >$1.2B volume in late 2025) and fixed resolution dates. Efficiency is mixed – for example 2024 US election markets on Polymarket were only ~67% correct, indicating exploitable biases. AI can leverage poll aggregates, campaign news and sentiment to forecast. Resolution occurs on election day (weeks–months out).

### 1b. Economic Indicators
Macro markets (e.g. GDP, inflation, unemployment) resolve on scheduled releases. Polymarket data shows PM consensus matches official forecasts ~95% of the time, leaving a ~5% drift (historically ~12 bp profit) when surprises occur. Liquidity is moderate (widely followed releases attract interest). AI advantage: ingest real-time govt data (FRED, BLS releases, central bank statements) and fast-changing economic news. Timeframe: monthly/quarterly.

### 1c. Sports
Very high liquidity; Polymarket's sports sector exceeded $1.2B in volume (Super Bowl events alone can approach $1B). Resolution is short-term (each game/event). Sports markets are semi-efficient (professional odds are available) but often thin enough for arbitrage. AI edge: processing rich data (stats, injury reports) and real-time in-play info.

### 1d. Tech Milestones
Speculative tech developments (e.g. "Will X AI launch by date") are long-horizon (months–years) with few specialists. Liquidity is relatively low. Markets are often inefficient due to sparse information. AI can read research papers, patent filings, company announcements to gauge trends.

### 1e. Entertainment
Includes awards, releases, social media events. Predictability is low (subjective tastes, viral factors) and liquidity moderate (big-popularity topics see more bets). AI edge: sentiment mining (Twitter trends, Google trends, box-office projections). Short-to-medium resolution (days–weeks around events).

### 1f. Weather
Forecastable by scientific models (e.g. El Niño). If Polymarket hosts such markets, they resolve on known schedules (season/year). Liquidity is likely low. AI can leverage meteorological models and real-time weather data.

### 1g. Crypto
High liquidity and volatility (>$1.2B Polymarket crypto volume). Many markets on price thresholds or events (forks, ETFs). Efficiency is low – prices can swing on news. AI strengths: analyzing on-chain metrics, exchange data, macro headlines. Resolutions vary (short-term triggers or fixed dates).

### 1h. Science
Rare "science breakthrough" bets (e.g. tech demos, number of discoveries). Unpredictable and very low liquidity. AI edge is limited (tracking publications or experiment timelines), but overall these markets are hardest to forecast.

### 1i. Geopolitics
Covers conflicts, treaties, international elections. High uncertainty and noisy news flow. Liquidity ranges from low to moderate. AI can parse global news/satellite data, but resolutions are often distant and ill-defined.

---

## 2. Academic Literature on LLM Forecasting

### 2a. LLM vs. Human Forecasters
Studies show current LLMs underperform expert forecasters. The ForecastBench benchmark (Karger et al.) found humans beat top LLMs (p<0.001). Even advanced models (GPT-4o, Claude 3.5) generally match median public forecasts but lag superforecaster teams. However, Halawi et al. (2024) demonstrated that combining LLM prompts can "near the crowd aggregate" accuracy and in some cases surpass it, suggesting ensemble methods may close the gap. Prompt tweaks (referencing base rates) yield modest gains.

### 2b. Market Efficiency by Category
Research on PM efficiency varies by domain. Well-structured markets (with many participants) reliably forecast outcomes: e.g. past studies confirm markets predict sports, macro data, elections with high accuracy. However, inefficiencies arise in practice. Clinton & Huang (2025) found 2024 US election markets often misprice outcomes (Polymarket only 67% correct) with price divergences and late-arbitrage bursts. Thin markets or rapidly changing news (e.g. sudden Covid developments or flash crashes) also violate efficiency. Design matters: LMSR-style markets (like Polymarket) can outperform traditional order-book markets when liquidity is low.

### 2c. Superforecasting & Ensembles
Tetlock's insights (diversity, base rates, Bayesian updating) extend to AI. Aggregating multiple forecasts improves accuracy. For instance, an experiment found an "LLM crowd" (ensemble of models) was statistically equivalent to the human crowd. Conversely, curating a small set of high-performance models ("elite crowd") is also fruitful. In practice, multi-model ensembles or ensembles of prompt variants can mimic these superforecaster principles. Approaches like deliberation, breaking questions into subparts, or training models on historical market data may further boost performance.

### 2d. Calibration of LLM Probabilities
LLM output probabilities are often miscalibrated. TMLR (2025) analysis shows model confidence (max softmax) poorly matches true accuracy, even though confidence scores correlate with correctness. In other words, higher logits tend to coincide with right answers, but the numeric probability isn't trustworthy as-is. For a trading bot, this means you should not take raw LLM probabilities at face value – post-hoc calibration (e.g. scaling) or using multiple runs to average confidence may be needed to get valid probabilities.

---

## 3. Competitive Landscape: Polymarket Bots & Firms

### 3a. Open-source Bots
The community already shares tools. For example, Aule Gabriel built and published a Python bot for Polymarket 15-minute Bitcoin up/down markets (on GitHub). Discountry's GitHub repo provides a "Polymarket Trading Bot" in Python with gasless trading, WebSocket feeds and a built-in flash-crash strategy. Similarly, PolyScripts (GitHub org) hosts arbitrage bots (e.g. Polymarket–Kalshi arb) and sports trading bots. These projects illustrate common features: real-time order book ingestion, arbitrage logic, and risk controls.

### 3b. Commercial/AI Bots
Emerging AI frameworks are being applied. Notably, the OpenClaw agent framework powered a Polymarket bot that reportedly earned $115K in one week. OpenClaw bots use LLM "logic" for opportunity filtering but hard-code execution rules for speed. Major strategy categories include arbitrage, market-making (providing liquidity), and sentiment-driven trades. Reports emphasize that bots capturing arbitrage (not narrative analysis) tend to make money. For instance, one trader noted that only "a minority of traders" are profitable and successful bots "typically employ sophisticated arbitrage rather than directional bets".

### 3c. Firms & Funds
Traditional finance is cautiously eyeing prediction markets. Most hedge funds currently ingest PM data as alternative signals rather than deploying capital. Polymarket itself offers a free volume data feed, and companies like Dysrupt Labs (Australia) incorporate PM prices into their macro research. Dysrupt found PM consensus aligns with economists 95% of the time, and the 5% deviation yields ~12 bp advantage. Some prop trading firms are directly engaged: for example, Susquehanna listed jobs for prediction-market traders. However, the "smart money" generally focuses on leveraging the data (through proprietary analytics) rather than large-scale betting on Polymarket itself.

### 3d. Trading Strategies
Across sources, the dominant profitable tactics are arbitrage and market-making. QuantVPS and FlyPix analyses note that Polymarket arbitrage opportunities (buying mismatched YES/NO prices, cross-platform spreads) exist only briefly and are captured by bots. Bots typically operate on milliseconds latency (running on VPS near Polygon nodes). UI-based sports or opinion trading is largely left to novices; in practice, automation focuses on mechanical edges. The competitive nature is intense: one blog noted $40M profit for arbitrageurs in one year but only ~0.5% of users earned >$1,000.

---

## 4. Ranked Market Categories by Profitability (LLM Bot)

Based on liquidity, informational richness, and inefficiency:

1. **Sports** – Highest profit potential. Massive volume (>$1.2B) and predictable schedules.
2. **Crypto** – High volatility and liquidity; AI can parse blockchain and news signals.
3. **Political Elections** – High liquidity; some inefficiency exists (2024 Polymarket ~67% accuracy). AI can use polling and news to edge the market.
4. **Economic Indicators** – Frequent events with large participation. Only small mispricing exists (95% consensus alignment), so returns are tighter but steady.
5. **Tech Milestones** – Moderate opportunity; long horizon means fewer markets/liquidity and slower signals.
6. **Entertainment** – Lower liquidity (except blockbuster events) and high noise; harder to predict reliably.
7. **Weather** – Forecastable by science, but Polymarket presence is limited; niche markets (e.g. El Niño) offer some edge to highly tuned AI models.
8. **Geopolitics** – High uncertainty and variable liquidity; AI news analysis helps but surprises are common.
9. **Science** – Lowest profitability. Markets are rare and outcomes hard to anticipate. AI has little prior data to train on these rare events.

This ordering is supported by volume and accuracy data: Polymarket's top volumes are in sports, politics, crypto, while niche areas show much thinner trading.

---

## 5. Data Feeds & APIs for Edge

Key data sources can give a prediction-bot an edge:

- **News APIs:** Real-time news and social feeds (e.g. Reuters/Bloomberg APIs, Google News, specialized PM-news sites). Fast news is crucial – the "biggest edge" is knowing information before others. Sentiment scores (NewsData.io, Finnhub sentiment) can quantify headlines for LLM input.
- **Polling Data:** Aggregated polls (FiveThirtyEight, RealClearPolitics) and election trackers. Studies show Polymarket often outperforms polls, so polling serves as a strong baseline.
- **Official Data Feeds:** Government releases (FRED API for macro data, NOAA for weather, national statistics APIs). Scheduled releases (inflation, jobs) are the backbone of some markets. Automating ingestion of these releases lets the bot anticipate market moves.
- **Social Media:** Twitter/X API and Reddit feeds for sentiment. Viral discussions often precede PM moves. NLP on social platforms can flag emerging trends (e.g. public interest spikes).
- **Search/Trend Data:** Google Trends or Wikipedia pageviews for keywords. Sudden search spikes can predate market movements (especially in entertainment or tech).
- **Sports/Betting Odds:** Odds aggregator APIs (TheOddsAPI, Betfair API) and sports data (ESPN, SportsRadar) to benchmark Polymarket quotes. Tools like Oddpool aggregate live PM odds and spreads across platforms, revealing arbitrage gaps.
- **Prediction Market Aggregators:** APIs providing real-time PM data (e.g. Verso, PolyRouter) let a bot monitor multiple markets easily. These feed actionable signals (e.g. unusual volume spikes) not found elsewhere.

---

*Sources: Recent forecasts research and prediction-market analyses informing category dynamics, LLM capabilities, and data strategies.*
