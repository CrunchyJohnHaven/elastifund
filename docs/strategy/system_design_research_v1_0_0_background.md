# Predictive Alpha Fund: system design research and implementation instructions

**The Polymarket bot opportunity has fundamentally shifted since late 2025.** Simple arbitrage is dead — average windows collapsed to 2.7 seconds, 73% of profits go to sub-100ms bots, and Polymarket introduced taker fees in January 2026 specifically to kill latency exploitation. Only **7.6% of wallets are profitable** and just 0.51% earned more than $1,000. But the market is exploding ($12B volume in January 2026 alone), short-duration crypto markets still have exploitable lag, and LLM ensemble forecasting has reached human-crowd parity. The viable path forward is a multi-strategy system combining smart wallet signals, LLM ensemble probability estimation, selective crypto-market latency trading, and maker-order liquidity provision — not any single edge. Starting at $75 USDC, the system should prove each strategy component independently before scaling. Two of the eight X accounts cited in the original brief (@0xwhrrari, @PolyDekos) do not appear to exist; the @seelffff "79.4% LSTM win rate" claim is completely unverifiable. Multiple "viral success stories" in this space are promotional fabrications.

---

## What's real versus what's Twitter fantasy

Before building anything, internalize this credibility assessment. It determines which strategies to prioritize and which to abandon.

**Confirmed with evidence:** LLM ensembles match human crowd forecasting accuracy (Halawi et al. NeurIPS 2024, Schoenegger et al. Science Advances, Bridgewater AIA). Polymarket price lag of **30–90 seconds** on crypto markets vs Binance is real and documented by multiple independent sources. Bot 0x8dxd turned $313 into $438K+ in one month (Dec 2025) on 15-min crypto markets — verified on-chain by CoinDesk. An estimated **$40 million** in arbitrage was extracted from Polymarket between April 2024 and April 2025 (IMDEA Networks, arXiv:2508.03474). OpenClaw's **20% malicious skill rate** is verified by three independent security firms (Koi Security, Antiy CERT, Snyk).

**Unverifiable hype — do NOT rely on:** The @seelffff "79.4% win rate with top-10 wallet concentration + LSTM" claim has zero evidence anywhere on the web. The @0xwhrrari "$1K→$5K in 24 hours with Claude multi-agent" — this account may not even exist. ClawdBot's "$150K risk-free arbitrage" is debunked marketing content. The "11ms arbitrage windows" claim is unsupported; real data shows 2.7-second average windows. Any claim of consistent 5x daily returns on prediction markets is almost certainly fabrication or survivorship bias.

**Real but now dying:** Pure latency arbitrage on 15-min crypto markets was killed in Feb 2026 when Polymarket removed the 500ms speed bump and expanded taker fees. The 0x8dxd strategy window is largely closed. Simple sum-to-one arbitrage on binary markets is structurally impossible (shared order book guarantees YES+NO = $1.00). Cross-platform Polymarket-Kalshi arbitrage carries severe "leg risk" from divergent resolution rules — a 2024 government shutdown case saw Polymarket resolve YES and Kalshi resolve NO on the "same" event.

---

## Component 1: smart wallet flow detection engine

Build this first. It is the highest-value proprietary edge and the hardest for competitors to replicate. The existing ecosystem of tools (PolyWallet, Polyburg, Dune dashboards) proves the signal exists but none combine ML inference with automated trading execution.

**Core contract addresses on Polygon (all verified across 3+ sources):**

| Contract | Address |
|---|---|
| Conditional Tokens (ERC1155) | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` |
| CTF Exchange | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` |
| NegRisk CTF Exchange | `0xC5d563A36AE78145C45a50134d48A1215220f80a` |
| NegRisk Adapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` |
| USDC.e (Collateral) | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` |

**Events to monitor:** Listen to `OrderFilled` and `OrdersMatched` from both CTF Exchange and NegRisk CTF Exchange for trade flow. Listen to `TransferSingle` and `TransferBatch` from the Conditional Tokens contract for position movements. Listen to `PositionSplit` and `PositionsMerge` from the NegRisk Adapter for minting/burning. The `PositionsConverted` event on the NegRisk Adapter is unique and critical — it captures NO→YES token conversions only visible through this contract.

**ETL pipeline implementation:** Use The Graph's official Polymarket subgraph (subgraph ID: `Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp`, endpoint: `https://gateway.thegraph.com/api/{key}/subgraphs/id/Bx1W4S7kDVxs9gC3s2G6DS8kdNBJNVhMviCtin2DiBp`, free tier: 100K queries/month) as the primary indexed data source. Use Alchemy's free-tier Polygon WebSocket endpoint for real-time event streaming. Do NOT use `polygon-rpc.com` — it stopped working February 16, 2026. For historical backfill, use Bitquery's Polymarket-specific API endpoints at `docs.bitquery.io/docs/examples/polymarket-api/`.

**Smart wallet identification criteria (consensus from analysis of 1.3M+ wallets):** Filter for win rate >60% across 100+ trades, 4+ months of track record, positive 30-day and 7-day PnL, category specialization (70%+ of trades in 2–3 topics), gradual position accumulation over days/weeks, and fewer than 100 predictions per month. Explicitly exclude: 15-minute crypto bot wallets, one-hit wonders, exotic/low-volume market traders, and high-PnL-but-terrible-win-rate gamblers.

**ML model — use XGBoost, not LSTM:** The academic literature validates LSTM+XGBoost hybrids for financial time series (arXiv 2506.22055, IEEE 2025), but for this specific use case — tabular wallet flow features mapped to directional signals — **XGBoost alone is sufficient and dramatically more practical** on a low-spec VPS. LSTM adds value only if modeling sequential patterns in individual wallet behavior over time windows. XGBoost trains in seconds on modest hardware and inference is near-instant. Start with XGBoost on these features: wallet concentration ratio (% of volume in top-N wallets per market), entry timing relative to market open, size delta vs historical average, rolling wallet win rate, wallet age/nonce, cross-wallet agreement percentage (the "80%+ basket" heuristic from the copy-trading community), and order flow imbalance.

**Key repos to reference:**
- `github.com/pselamy/polymarket-insider-tracker` — best existing insider detection (DBSCAN clustering, composite risk scoring)
- `github.com/NickNaskida/polymarket-insider-bot` — async detection with SQLite, Slack alerts, anomaly scoring
- `github.com/Polymarket/polymarket-subgraph` — official subgraph manifest (165 stars)
- `github.com/PaulieB14/polymarket-subgraph-analytics` — analytics with multiple subgraphs
- `github.com/Polymarket/agents` — official AI agents framework for autonomous trading

**Do NOT:** Build an LSTM as the primary model. Do NOT use OpenClaw or ClawHub skills — 20% are malicious, including Polymarket-specific trojans that harvest wallet keys. Do NOT trust the @seelffff 79.4% claim for any design decisions.

---

## Component 2: LLM ensemble probability estimator

This is the second-highest priority. The evidence is strong that scaffolded LLM ensembles match or approach human crowd accuracy, and Bridgewater's research proves that blending AI forecasts with market prices outperforms either alone.

**Architecture — follow the Bridgewater AIA pattern:** Deploy 5–7 independent LLM agents, each performing agentic web search over news sources, independently reasoning, and outputting a probability estimate. Then use a supervisor agent that reads all rationales, runs targeted searches for disputed facts and base rates, and produces a reconciled forecast. Apply **Platt scaling** post-hoc to correct the universal LLM tendency to hedge toward 50%.

**Model selection for the ensemble:** Use at minimum three model families for diversity (diversity drives the ensemble benefit, per Schoenegger et al.). Recommended mix: **Groq Llama 3.3 70B** ($0.59/$0.79 per M tokens, 394 TPS — workhorse for cheap quality), **Groq Qwen3 32B** ($0.29/$0.59 per M tokens — different training data for diversity), **Claude Haiku** ($1.00/$5.00 per M tokens — Anthropic's reasoning style as contrast), and **GPT-4o Mini** ($0.15/$0.60 per M tokens — OpenAI's perspective). For high-confidence signals requiring deeper analysis, escalate to **Claude Sonnet** ($3.00/$15.00) or **GPT-4o** ($2.50/$10.00). Use Groq's free tier aggressively — it provides zero-cost access to Llama and Qwen models with rate limits sufficient for 50–100 forecasts per day.

**Aggregation method:** Start with trimmed mean (Halawi et al. found this most robust). Upgrade to supervisor-agent reconciliation once the basic ensemble is validated. The key finding from Bridgewater's AIA: **optimal weighting is approximately 67% market price / 33% AI forecast** when combining with market consensus. Even when AI trails the market in absolute accuracy, its forecasts contain independent information that improves blended performance.

**Calibration implementation:** Use scikit-learn's `CalibratedClassifierCV` with `method='sigmoid'` (Platt scaling). Requires minimum 100 resolved predictions with model outputs paired to binary outcomes. Fit separate calibrators per domain (politics, sports, crypto). Re-calibrate monthly. Clip all outputs to [0.03, 0.97] — never output raw 0% or 100% confidence. Bridgewater's AIA found Platt scaling "consistently more robust than simple prompting changes" for debiasing.

**Cost target:** $10–30/month for a 5–7 model ensemble doing 50–100 forecasts per day. Achievable using Groq free tier for 3–4 models plus Claude Haiku batch API ($0.50/$2.50 with 50% batch discount) for the supervisor layer.

**Key papers to reference for implementation:** Halawi et al. 2024 "Approaching Human-Level Forecasting with Language Models" (arXiv:2402.18563, NeurIPS 2024), Schoenegger et al. 2024 "Wisdom of the Silicon Crowd" (Science Advances, PMC11800985), AIA Forecaster Technical Report (arXiv:2511.07678).

**Key frameworks:** `github.com/Metaculus/forecasting-tools` (TemplateBot, SmartSearcher, Key Factor Analysis, Monetary Cost Manager), `github.com/PredictionXBT/PredictOS` (multi-agent system with "Bookmaker Agent" judge), `github.com/gnosis/prediction-market-agent` (supports Polymarket directly).

---

## Component 3: short-duration crypto market trading

This is the most immediately profitable strategy but carries the highest saturation risk. The window is narrowing fast.

**Resolution mechanism:** Polymarket's 5-minute and 15-minute BTC/ETH markets use **Chainlink Data Streams** (pull-based, sub-second latency) for resolution data, triggered by **Chainlink Automation** at interval boundaries. "Up" resolves if end price ≥ start price; **ties resolve as "Up"** (slight structural bias to exploit). Settlement uses 64-block confirmation (~2 minutes on Polygon). Markets launched February 12, 2026.

**The exploitable lag:** The oracle itself has sub-second latency. The exploitable gap is in the **order book** — Polymarket's CLOB prices lag Binance spot by **30–90 seconds** because human/bot order flow takes time to adjust. When BTC makes a sharp directional move and the actual probability of "Up" jumps to ~85%, the Polymarket order book may still show ~50/50 pricing. This is the window.

**Fee structure on crypto markets:** Taker fee = `p × (1-p) × 0.0625`. At 50¢ price: 1.56¢ per contract (maximum). At 85¢: 0.80¢. At 95¢: 0.30¢. **Maker orders pay zero fees** and earn daily USDC rebates from the taker fee pool. Build the system to use maker/post-only orders wherever possible.

**Critical March 2026 change:** Polymarket removed the 500ms speed bump on crypto markets. "With the speed bump gone, latency is now the only moat." This advantages the fastest bots and disadvantages slower entrants. The fee introduction + speed bump removal together mean this strategy now requires faster execution and tighter risk management than in December 2025.

**Data feeds:** Use Polymarket's own RTDS WebSocket, which provides both Binance and Chainlink price feeds simultaneously (`crypto_prices` for Binance source, `crypto_prices_chainlink` for Chainlink source, docs at `docs.polymarket.com/developers/RTDS/RTDS-crypto-prices`). Compare the two feeds in real-time for resolution prediction. Supplement with direct Binance WebSocket for lowest-latency spot price.

**Realistic expectations:** Backtesting across 1,000 BTC 5-min windows yields ~55–60% win rate with momentum models vs 50% random. Annual ROI estimate: **20–50% at 1% risk per trade**. This is modest compared to viral claims but realistic after fees. One practitioner (Itan Scott, March 2026) built three bots with Claude Code for 5-min BTC markets — Bot 2 checks the Chainlink oracle to compare opening BTC price, trading in the 5–20 second window before resolution.

**Do NOT:** Expect to replicate 0x8dxd's $313→$438K results — that strategy window is largely closed. Do NOT use taker orders for this strategy — the fee at midpoint prices erases most edge. Do NOT run this strategy without a kill switch — one practitioner published a profitable strategy then "got targeted and lost ~$5K in 18 hours" from adversarial counter-trading.

---

## Component 4: NegRisk multi-outcome arbitrage scanner

Build this as a passive monitoring layer, not a primary strategy. It generates small but consistent returns.

**How it works:** In NegRisk markets with 3+ mutually exclusive outcomes, the sum of all YES prices can drift below $1.00. Buying one share of every outcome guarantees $1.00 payout. Binary market arbitrage (YES+NO < $1 within a single market) is **structurally impossible** due to Polymarket's shared order book — this is a common misconception promoted by content creators.

**Current viability:** Average opportunity duration is **2.7 seconds** (down from 12.3 seconds in 2024). Median spread is 0.3%. 73% of profits go to sub-100ms bots. This strategy is supplementary income at best on a modest VPS. Use maker orders to pre-position on outcomes you believe are underpriced within multi-outcome markets rather than trying to capture fleeting windows with taker orders.

**Cross-platform Polymarket-Kalshi:** Real price divergences >5 percentage points occur 15–20% of the time. But resolution rule divergence creates "leg risk" that is NOT risk-free. Only attempt with markets that have identical, unambiguous resolution criteria. Reference repos: `github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot`, `github.com/ImMike/polymarket-arbitrage`.

---

## Polymarket API current state (verified March 2026)

**py-clob-client:** Version **0.34.5** on PyPI. 91 total versions, 139K weekly downloads, 13 contributors. Active development — 14+ releases in the past 12 months. Install with `pip install py-clob-client`. Pin version in requirements.txt. Also available: `polymarket-apis` (unified third-party Python client, released March 4, 2026). GitHub: `github.com/Polymarket/py-clob-client`.

**Rate limits (verified from official docs at `docs.polymarket.com/quickstart/introduction/rate-limits`):** General: **15,000 requests/10s** (confirmed). CLOB general: 9,000/10s. Order posting: **3,500/10s burst + 36,000/10min sustained**. Order cancellation: 3,000/10s burst + 30,000/10min sustained. Book endpoint: 1,500/10s. Enforcement is Cloudflare throttling (requests delayed, not dropped).

**WebSocket:** Market channel provides `book`, `price_change`, `last_trade_price` events. **Max 500 instruments per connection** (undocumented but confirmed). No unsubscribe support — once subscribed, create a new connection to change subscriptions. Breaking change September 15, 2025 altered `price_change` event structure. RTDS (launched September 24, 2025) provides real-time crypto price feeds.

**Builder Program:** Fully operational, permissionless entry. Unverified tier: 100 gasless relayer transactions/day, standard rate limits. Verified tier: 1,500/day + weekly USDC rewards + RevShare. Partner tier: unlimited. Register at `polymarket.com/settings?tab=builder`. Upgrade by emailing `builders@polymarket.com`.

**Post-only orders:** Confirmed added January 2026. Limit orders that are rejected if they would immediately match — guarantees maker status and zero fees. Critical for all strategies in this system.

---

## The accounts worth following versus ignoring

| Account | Verdict | Credibility |
|---|---|---|
| @0xEthan | **Genuine practitioner.** Built documented HFT front-running bot, cited by BeInCrypto and Yahoo Finance. No public wallet address though. | Medium-High |
| @pearldotyou / Polystrat (Olas) | **Legitimate product.** VC-backed (Valory/Olas), 13M on-chain txns on predecessor Omenstrat, named team. Autonomous AI trading agent for Polymarket. | High |
| @seelffff | **Real developer** (GitHub linked, ~1K followers, London). Copy-trading content is technically literate. 79.4% LSTM claim is unverifiable. | Medium-Low |
| @FractionAI_xyz | **Mischaracterized.** This is a decentralized AI agent competition platform on NEAR, not a Polymarket bot. VC-backed (Borderless Capital, Spartan). | High (as company), irrelevant to your use case |
| @kreoapp | **Early-stage product.** Telegram copy-trading platform, November 2025 launch, ambassador/affiliate program. Promotional. | Medium |
| @PolyScalping | **Alerting tool.** Real-time scalping alerts, Telegram notifications. Legitimate utility, no inflated profit claims. | Medium |
| @0xwhrrari | **Cannot verify exists.** Zero search results anywhere. $1K→$5K claim is likely fabrication. | Unverifiable — ignore |
| @PolyDekos | **Cannot verify exists.** Zero search results. | Unverifiable — ignore |

**Accounts worth adding:** @DextersSolab (Dexter's Lab, credible analyst who first documented 0x8dxd), @lookonchain (on-chain analytics, widely cited), @igor_mikerin (bot making $2.2M, cited by BeInCrypto), @itanscott1 (building Claude Code bots for 5-min BTC markets, transparent about results).

---

## OpenClaw is a severe security threat — do not use

OpenClaw (formerly Clawdbot/Moltbot) has **215,000+ GitHub stars** but is riddled with malicious plugins. Koi Security found 341 malicious skills (12%) in February 2026. Antiy CERT expanded this to **1,184+ malicious skills (~20%)**. Snyk's ToxicSkills audit found **36% of all skills contain prompt injection** and confirmed 1,467 malicious payloads. Specific Polymarket-targeting malware includes `polymarket-traiding-bot` (152 downloads, GitHub malware link) and `polymarket-all-in-one` (remote code execution). Nine CVEs disclosed, three with public exploit code. **135,000 OpenClaw instances** are exposed to the public internet with insecure defaults.

Build all components in-house using vetted open-source libraries. Do not install any third-party "skills" or plugins from community marketplaces. If you need an agent framework, evaluate IronClaw (Near.AI's security-focused alternative using Rust with WebAssembly sandboxing) or build on `github.com/Polymarket/agents` directly.

---

## Regulatory environment is currently favorable but fragile

The CFTC and DOJ **formally ended investigations** into Polymarket in July 2025. Polymarket acquired QCEX (a CFTC-licensed exchange) for $112M and received CFTC Amended Order of Designation in November 2025 for regulated U.S. operations. The U.S. platform launched in December 2025 (iOS, sports-only initially, invite-based). **No specific regulations target automated/bot trading on prediction markets** — bot trading is legal on platforms with official API access, subject to anti-manipulation rules (no spoofing, layering, wash trading).

Risks: Nevada Gaming Control Board filed a civil complaint in January 2026 arguing Polymarket needs a state gaming license. Massachusetts issued a preliminary injunction against Kalshi. A U.S. senator proposed a **ban on prediction markets** in February 2026. Poland, Singapore, and Belgium have banned Polymarket. The UMA oracle is vulnerable — a March 2025 governance attack used 5M UMA tokens to force a fraudulent resolution.

For the Predictive Alpha Fund operating from a Frankfurt VPS: the international (non-U.S.) Polymarket platform has no current restrictions for EU-based operations. Monitor the EU regulatory environment. Do not serve U.S. users or use VPN to access the U.S. platform from outside the U.S.

---

## Infrastructure and budget architecture

**VPS recommendation: Hetzner CCX13 in Frankfurt.** 2 dedicated AMD vCPUs, 8GB RAM, 80GB NVMe, 20TB transfer — **€14.86/month** (increasing to ~€19/month after April 1, 2026 price increase). This handles: trading bot, blockchain event monitoring, XGBoost inference, PostgreSQL, and all API calls comfortably. For initial development, Hetzner CPX22 (2 shared vCPU, 4GB, 80GB) at €5.99/month is sufficient. Migrate from current DigitalOcean to Hetzner for ~60% cost savings at equivalent specs.

**Database: Start with SQLite, migrate to PostgreSQL at scale.** SQLite handles tens of thousands of reads/sec and is perfectly adequate for a single trading bot. Migrate to PostgreSQL when you need concurrent write access from multiple processes or data exceeds ~10GB. Expect **1–5GB/month** of data growth depending on market coverage. PostgreSQL runs fine on the same Hetzner VPS.

**Full monthly cost breakdown (comfortable production tier):**

| Component | Cost |
|---|---|
| VPS (Hetzner CCX13, Frankfurt) | ~$16 |
| LLM APIs (Groq free + Claude Haiku + GPT-4o Mini) | $15–30 |
| Polygon RPC (Alchemy free tier → PAYG) | $0–5 |
| The Graph API (free tier, 100K queries/month) | $0 |
| Database (SQLite/PostgreSQL on VPS) | $0 |
| Monitoring (Better Stack + Telegram alerts) | $0 |
| VPS snapshots/backups | $2–3 |
| **Total** | **$33–54/month** |

To run the full system with heavier LLM usage and paid RPC: $80–120/month. This scales well — LLM costs are the primary variable expense and scale with forecast volume, not capital deployed.

---

## Prioritized implementation roadmap

**Phase 1 (Weeks 1–2): Foundation and quick wins.** Migrate to Hetzner CCX13. Set up py-clob-client 0.34.5 with Builder Program registration (gasless trading). Implement WebSocket connection to market channel with reconnection logic. Build SQLite schema for orders, positions, market snapshots. Port existing Claude Haiku probability estimator. Implement post-only order support for zero-fee maker orders. Verify existing quarter-Kelly sizing and Platt scaling calibration pipeline works on new infrastructure.

**Phase 2 (Weeks 3–4): LLM ensemble.** Add Groq free-tier models (Llama 3.3 70B, Qwen3 32B) alongside existing Claude Haiku. Implement trimmed-mean aggregation. Build news retrieval pipeline using web search APIs. Implement the 67/33 market-price/AI-forecast blending formula from Bridgewater's research. Set up automated calibration pipeline using resolved Polymarket questions. Target: 50–100 forecasts per day on active markets.

**Phase 3 (Weeks 5–8): Smart wallet flow engine.** Deploy Polygon event listener on Alchemy WebSocket (free tier). Index `OrderFilled` events from both CTF Exchange contracts. Build wallet scoring pipeline: historical PnL, win rate, category specialization, position accumulation patterns. Reference `polymarket-insider-tracker` repo for anomaly detection patterns. Train initial XGBoost model on historical wallet flow data from The Graph subgraph backfill. Build signal: when 80%+ of tracked high-score wallets agree on an outcome, flag for ensemble consideration.

**Phase 4 (Weeks 9–10): Crypto market latency module.** Connect to Polymarket RTDS WebSocket for both Binance and Chainlink crypto price feeds. Build momentum detection: identify sharp directional BTC/ETH moves using Binance WebSocket. Implement maker-order placement when momentum signal diverges from current Polymarket book prices. Start with paper trading for minimum 500 5-minute windows before deploying real capital. Build kill switch for adversarial counter-trading detection.

**Phase 5 (Weeks 11–12): NegRisk scanner and integration.** Build passive scanner for multi-outcome markets where sum of YES prices < $0.995. Pre-position maker orders on underpriced outcomes. Integrate all four strategy signals into unified position management with portfolio-level Kelly sizing. Implement monitoring dashboard with Telegram alerts for all trade executions, P&L updates, and system health.

**Phase 6 (Ongoing): Scaling and hardening.** Migrate SQLite to PostgreSQL when data exceeds 5GB. Upgrade Hetzner to CPX42 (8 vCPU, 16GB) if ML training becomes a bottleneck. Apply for Builder Program Verified tier once volume justifies it. Build comprehensive backtesting framework across all strategy components. Begin investor reporting infrastructure for $10K–$100K scaling.

---

## Conclusion: the honest edge assessment

The Predictive Alpha Fund's viable edge in March 2026 is not any single strategy — it is the **combination of multiple weak signals into a system that is difficult to replicate**. Smart wallet flow detection provides information about informed market participants. LLM ensemble forecasting provides independent probability estimates that improve market prices when blended. Crypto market latency provides short-duration tactical opportunities. Maker-order placement provides fee advantage and rebate income.

The competitive environment is dramatically harder than 2024. ICE invested up to $2 billion in Polymarket. Jump Trading and Susquehanna are active market makers. The top 10 wallets capture 80%+ of arbitrage profits. But **volume is growing faster than competition** ($12B in January 2026 alone), and the shift from simple arbitrage to ML-driven signal extraction favors technically sophisticated operators willing to build proprietary data pipelines. Realistic return expectations: **2–5% monthly** with meaningful drawdown risk, scaling favorably as capital increases from $75 to $10K+ because the primary constraint is signal quality, not capital deployment speed. The $75 starting capital phase should be treated as a live paper-trading validation period — prove each component generates positive expected value before accepting investor capital.