# Building an LLM-powered prediction market fund: a complete technical dossier

**The evidence points to a narrow but real edge.** LLM ensembles now achieve Brier scores within 0.02–0.03 of human superforecasters, Polymarket's new fee structure creates a structural advantage for makers over takers, and the Groq free tier can support 100+ daily market analyses at zero cost across three to four models. However, the legal path is more complex than most operators assume — a prediction market fund almost certainly qualifies as a CFTC-regulated commodity pool, and the de minimis exemption likely won't apply when event contracts are the primary strategy. This report synthesizes every available datapoint across six domains to provide a complete operational picture as of March 2026.

---

## Section 1: LLM forecasting has closed most of the gap with human crowds

### The three foundational papers

**Halawi et al. (2024), "Approaching Human-Level Forecasting with Language Models" (NeurIPS 2024, arXiv:2402.18563)** built a three-stage retrieval-augmented pipeline: an LLM generates search queries against the NewsCatcher API, ranks and summarizes articles, then feeds them into base and fine-tuned GPT-4 models that produce probability forecasts aggregated via trimmed mean. The system was tested on **914 binary questions** from five platforms (Metaculus, Good Judgment Open, INFER, Polymarket, Manifold) published after the model's knowledge cutoff. Results: the system achieved a **Brier score of 0.179** versus the human crowd's **0.149** — a gap of 0.030. Accuracy was 71.5% versus 77.0% for the crowd. Critically, when the crowd was uncertain (predictions between 0.3–0.7), the system **matched or slightly beat** humans (0.238 vs 0.240). When system and crowd forecasts were combined via weighted average, the Brier score improved to **0.146**, beating either alone — evidence of complementary information.

Fine-tuning was self-supervised: GPT-4 generated reasoning+forecast pairs on training questions, and a second GPT-4 was fine-tuned on the outputs that beat the crowd (selected by Brier score on resolved questions). Without fine-tuning and retrieval, performance degraded to near-random (**0.21–0.25 Brier**). A critical caveat flagged by Paleka et al. (2025): 71% of date-filtered search queries may return post-cutoff leakage pages, inflating retrospective results.

**Schoenegger et al. (2024), "Wisdom of the Silicon Crowd" (Science Advances, PMC11800985)** tested an ensemble of **12 diverse LLMs** (GPT-4, PaLM2, Llama-2-70B, Claude 2, and others) making probabilistic predictions on **31 binary questions** in a three-month Metaculus tournament against **925 human forecasters**. The LLM crowd median was **statistically indistinguishable** from the human crowd aggregate within equivalence bounds (medium effect size, d = 0.081 Brier). When GPT-4 and Claude 2 were exposed to the human median prediction, their accuracy improved by **17–28%**, but simply averaging human and machine forecasts outperformed either updating method. The paper confirmed that diversity across model families — not raw count — drives the "wisdom of the silicon crowd" effect. However, the 31-question sample is very small, and the 0.081 equivalence bound is wide enough that a forecaster with Brier 0.271 (worse than random) would qualify as "equivalent."

**Bridgewater AIA Forecaster (arXiv:2511.07678, November 2025)** represents the current state of the art. Its architecture deploys M independent agentic forecasters, each with full discretion over multi-step search queries, followed by a **supervisor agent** that reconciles disagreements via targeted fact-checking. The system then applies **Platt scaling** — which the paper proves is mathematically equivalent to generalized log-odds extremization — to correct LLMs' systematic hedging toward 50%.

On ForecastBench's market subset, AIA achieved **Brier 0.0753**, statistically indistinguishable from human superforecasters (**0.0740**) and far ahead of the market price baseline (0.0965). On the harder MarketLiquid benchmark (1,610 liquid prediction market questions), the standalone system scored 0.1258 — worse than market consensus alone at 0.1106. But **blending 67% market price with 33% AI forecast** produced a combined Brier of **0.106**, beating both components individually. Search proved essential: without it, Brier collapsed from 0.1002 to **0.3609** (worse than always predicting 50%).

The paper's strongest finding on calibration: **"Platt scaling is consistently more robust than simple prompting changes"** for correcting LLMs' systematic underconfidence. LLMs hedge excessively — predicting 60% when evidence supports 85%, or 95% instead of 99% with rationalizations like "unexpected things might happen." Simple extremization techniques capture most of the calibration gain. Naive LLM-based aggregation (asking a model to combine forecasts) fails because LLMs overweight outlier opinions. The supervisor agent works precisely because it's framed as **disagreement resolution** rather than aggregation.

### Additional papers through early 2026

**Foresight-32B (Lightning Rod Labs, 2025)** applied RL fine-tuning to Qwen3-32B for live Polymarket evaluation (251 questions, July–August 2025). The base model's Brier of 0.253 improved to **0.199** versus the market's 0.170, and ECE dropped from 19.2% to **6.0%** — a 69% reduction. It was the only model besides o3 to achieve positive simulated profitability. **KalshiBench (arXiv:2512.16030)** found all five frontier models show universal overconfidence (ECE 0.12–0.40), and extended reasoning **worsens** calibration — a paradox confirming that post-hoc calibration is non-negotiable. **ForecastBench's live leaderboard** projects LLM-superforecaster parity around **November 2026** (95% CI: December 2025 – January 2028) under linear extrapolation.

### Synthesis: the numbers that matter for a trading system

**Brier score ceiling for a standalone LLM ensemble**: approximately **0.10–0.13** on liquid prediction markets, **~0.075** on curated benchmarks. With market price blending (67/33), the ceiling drops to approximately **0.10–0.11**. True superforecaster parity on hard liquid markets (~0.08) has not been demonstrated by any published system.

**Edge from Platt scaling**: approximately **100–500 Brier basis points** depending on baseline miscalibration. Well-prompted systems gain ~100–200 bp; raw LLM outputs gain 300–500 bp. AIA's pipeline (which embeds Platt scaling) improves from ~0.126 standalone to 0.106 when blended with market prices.

**Optimal ensemble size**: **8–12 diverse models** before diminishing returns, with diversity across model families far more important than count within a single family. The supervisor/reconciliation agent adds meaningful value over simple averaging. Multi-run ensembling of the same model provides variance reduction with diminishing returns after ~5–10 runs.

---

## Section 2: Polymarket's fee structure now rewards makers and punishes latency arbitrage

### The taker fee formula

All fee-enabled markets use the same formula with different parameters:

**`fee = C × p × feeRate × (p × (1 − p))^exponent`**

where C is shares traded, p is price per share (0–1.00), feeRate and exponent vary by category.

| Market type | feeRate | Exponent | Maker rebate | Peak fee (at p=0.50) |
|---|---|---|---|---|
| **5-min & 15-min crypto** | 0.25 | 2 | 20% of taker fees | **1.56%** |
| **Sports (NCAAB, Serie A)** | 0.0175 | 1 | 25% of taker fees | **0.44%** |
| **All crypto** (from March 6, 2026) | Same as 5/15-min | 2 | 20% | **1.56%** |

The quadratic exponent on crypto markets produces dramatically higher fees near 50% probability (where latency arbitrage is most profitable) and near-zero fees at extremes. At p=0.10 or p=0.90, crypto fees drop to just **0.20%**; at p=0.05, they're **0.06%**.

**Markets with zero fees**: all politics/election markets, all non-crypto event markets (economics, entertainment, weather, geopolitics). These remain fee-free as of March 7, 2026.

**Polymarket US** (the CFTC-regulated entity acquired via QCEX) operates a separate flat fee structure: **0.01% (1 basis point)** taker fee and **0.01%** maker rebate on total contract premium.

### The February–March 2026 fee rollout timeline

Fees were introduced incrementally, motivated by combating latency arbitrage bots:

- **January 19, 2026**: Taker fees on 15-minute crypto markets (first fees on the global platform)
- **February 12, 2026**: Extended to 5-minute crypto markets
- **February 18, 2026**: Extended to NCAAB and Serie A sports (new markets only)
- **~March 6, 2026**: Google-indexed docs show expansion to **all crypto markets** — likely in active rollout

The 15-min crypto fee introduction was done without formal announcement, discovered via documentation changes. The fees were specifically designed to neutralize the latency arbitrage strategy that bots like 0x8dxd exploited.

### Maker rebates: daily USDC from the taker fee pool

Rebates use the same fee-curve formula. Your daily rebate equals `(your_fee_equivalent / total_fee_equivalent) × rebate_pool`, where you compete only with other makers in the same market. Distribution is **daily in USDC** directly to your wallet. The rebate percentage is at Polymarket's sole discretion — it started at 100%, dropped to 20% for crypto, and is 25% for sports. **Makers pay zero fees** and receive a share of what takers pay.

### Post-only orders in py-clob-client

Version **0.34.5** (released January 13, 2026) is current. The key parameter is **`post_only`** (boolean, defaults to `False`) on `post_order()` or `create_and_post_order()`. When `True`, the order is rejected if it would immediately match against existing liquidity, guaranteeing it rests on the book as passive liquidity. The `feeRateBps` field must be fetched dynamically per token via `GET https://clob.polymarket.com/fee-rate?token_id={token_id}` — never hardcode this value. Order types compatible with post-only: `OrderType.GTC` (Good-Til-Cancelled) and `OrderType.GTD` (Good-Til-Date). `OrderType.FOK` (Fill-or-Kill) is incompatible.

### Builder Program tiers

| Feature | Unverified | Verified | Partner |
|---|---|---|---|
| **Daily gasless transactions** | **100** | **1,500** | **Unlimited** |
| Approval required | No | Yes (manual) | Enterprise discussion |
| RevShare protocol | ❌ | ✅ | ✅ |
| Weekly USDC rewards | ❌ | ✅ | ✅ (with multiplier) |
| Engineering support | ❌ | Standard | Elevated |
| Base fee split | ❌ | ❌ | ✅ (custom agreement) |
| Market suggestions | ❌ | ❌ | ✅ |

To start: `polymarket.com/settings?tab=builder` → create profile → generate API keys. Verified tier requires contacting Polymarket with your API key, use case, expected volume, and relevant documentation. Partner examples include Base, MetaMask, and Rainbow.

---

## Section 3: Most "profitable bot" stories are real but the strategies are now dead

### 0x8dxd: the $313-to-$438K legend is verified — but the edge has evaporated

The Polymarket profile @0x8dxd shows **26,738 predictions**, $60K current positions, and $41.2K biggest single win. Multiple independent sources (Finbold, Blake.ETH's analysis, PolyBot Arena) confirm the P&L trajectory from Polymarket's own interface: **$313 starting capital in December 2025, ~$437,600 profit by January 6, 2026** with a ~98% win rate across 6,615 predictions, scaling to ~$512K by January 9 and reportedly **>$1.7M cumulative** by February/March 2026.

The strategy was pure **latency arbitrage** on 15-minute crypto Up/Down markets, exploiting a 500ms–2s pricing lag where Binance/Coinbase spot prices had already confirmed a directional move but Polymarket's odds hadn't adjusted. The bot entered trades when true probability was ~85%+ but the market still showed ~50/50. Blake.ETH's independent analysis: "$313 → $359K in 29 days, 5,637 trades, 96.3% win rate," running on "a $20/month VPS."

**Post-February 2026 status**: the strategy is effectively dead. The combination of dynamic taker fees (peaking at 1.56% near 50% probability) and the removal of the 500ms taker delay on February 18 eliminated the exploitable spread. As @_dominatos noted (1.1M-view article): "The fee alone is now higher than the exploitable spread." However, 0x8dxd remains active at 26,738 predictions — suggesting adaptation to a maker strategy with reduced margins.

The full hex wallet address was not publicly disclosed in any source reviewed; "0x8dxd" is a display name, not the actual Polygon address.

### @igor_mikerin's $2.2M claim: unverified

The @ilovecircle Polymarket account exists, and Igor Mikerin posted on December 23, 2025 claiming "$2.2M in 2 months using probability models." The described strategy — an ensemble of neural networks trained on news, social media, and on-chain data, trading when AI-estimated probability exceeded market price by a threshold — is plausible. **But every subsequent article (BeInCrypto, LiveBitcoinNews, Phemex, MEXC) traces back to this single tweet.** No Dune dashboard or Polygonscan analysis independently confirms the $2.2M figure. **Evidence quality: low-medium.**

### Polystrat/Olas: legitimate technology, unproven on Polymarket

Launched February 2026 on the Pearl app (Olas ecosystem, built by Valory). Uses FSM architecture with self-custodial Safe smart accounts. Two preset strategies: Balanced (fixed trade size) and Risky (Kelly-criterion based). On the predecessor Omen platform (Gnosis chain), agents collectively executed **13 million transactions** with win rates of 59–64% in business/science categories but near-random (~51%) in sports. **No published Polymarket performance data exists** — the product launched too recently.

### Institutional players: Jump, SIG, and Théo are confirmed

**Jump Trading** is acquiring equity stakes in both Kalshi and Polymarket in exchange for providing liquidity, with **20+ staffers** dedicated to prediction market trading (Bloomberg, February 9, 2026). **Susquehanna** was the first publicly disclosed institutional market maker for Kalshi and conducts cross-platform arbitrage exploiting 4–6 cent price gaps between platforms. **Jane Street** is referenced as part of the "big three" but with less direct documentation.

The most verified large profit belongs to **French trader "Théo"**: **$80–85M profit** on 2024 Trump election bets across as many as 11 accounts (confirmed by Chainalysis blockchain forensics). He commissioned private YouGov polls using "neighbor effect" methodology and wagered ~$80M total.

### The base rates are sobering

Only **7.6% of Polymarket wallets** are profitable. Only **0.51%** have profits exceeding $1,000. Arbitrageurs extracted >$40M in risk-free profits from April 2024–April 2025, but fee changes have since closed most of those windows. The top 3 arbitrage wallets made $4.2M combined. Key tracking tools: Dune dashboards (dune.com/rchen8/polymarket, dune.com/filarm/polymarket-activity), PolyBot Arena (polybot-arena.com), and PolyTrack (polytrackhq.app).

---

## Section 4: Groq's free tier supports a full forecasting pipeline at zero cost

### Model availability and rate limits (confirmed from official docs)

| Model | RPM | RPD | TPM | TPD |
|---|---|---|---|---|
| **Llama 4 Scout 17Bx16E** | 30 | 1K | **30K** | **500K** |
| **Llama 4 Maverick 17Bx128E** | 30 | 1K | 6K | **500K** |
| **Qwen3 32B** | 60 | 1K | 6K | **500K** |
| Llama 3.3 70B | 30 | 1K | 12K | **100K** |
| Llama 3.1 8B | 30 | 14.4K | 6K | **500K** |
| GPT-OSS 120B | 30 | 1K | 8K | **200K** |
| GPT-OSS 20B | 30 | 1K | 8K | **200K** |
| Kimi K2 (1T MoE) | 60 | 1K | 10K | **300K** |

Llama 3.3 70B remains free but is **severely TPD-constrained at 100K** — insufficient for primary workload. DeepSeek models are **not currently on the free tier**. Groq's deterministic LPU architecture delivers p99 latency within ~15% of median (effectively no tail latency), with output speeds of **394–1,000 tokens/second** depending on model. Structured JSON output and function calling are fully supported.

### Feasibility: 100 analyses/day across 3–4 models

Each analysis requires ~2,000 input + 500 output tokens = 2,500 tokens. At 100 analyses/day, that's **250,000 tokens per model per day**.

The optimal free-tier ensemble: **Llama 4 Scout + Llama 4 Maverick + Qwen3 32B** — each with 500K TPD, giving 1.5M total daily token budget against a 750K requirement. This runs at **50% utilization** with substantial headroom. Adding Llama 3.1 8B as a fourth model brings total capacity to 2M TPD. Requests spread across the day (~7/hour) stay well within TPM limits. **Verdict: fully feasible at zero cost**, but Llama 3.3 70B and GPT-OSS models cannot serve as primary workhorses due to TPD caps.

### xAI Grok API: powerful but not free

| Model | Input $/M tokens | Output $/M tokens | Context window |
|---|---|---|---|
| **Grok 4.1 Fast** | $0.20 | $0.50 | **2M tokens** |
| **Grok 4** (flagship reasoning) | $3.00 | $15.00 | 256K |
| **Grok 3** | $2.00 | $10.00 | 128K |
| **Grok 3 Mini** | $0.10 | $0.30 | 128K |

No traditional free tier exists, but xAI offers **$25 in credits at signup** (no credit card required) plus **$150/month additional** through a data-sharing opt-in program (requires a prior $5 spend). The data-sharing program means xAI uses your interactions for training — unsuitable for proprietary strategies. The API endpoint is `https://api.x.ai/v1` with `xai-`-prefixed API keys and full OpenAI SDK compatibility. Built-in web and X/Twitter search tools cost $5/1K calls.

**No formal calibration or forecasting benchmarks exist for Grok** as of March 2026. Grok 4 scored 50.7% on Humanity's Last Exam (first model above 50%) and 66.6% on ARC-AGI v1, suggesting strong abstract reasoning, but prediction market calibration hasn't been tested in published research. Its real-time X data integration provides unique value for sentiment-driven short-term predictions.

**Recommended hybrid approach**: use Groq free tier (Llama 4 Scout/Maverick + Qwen3 32B) for high-volume structured analysis, then selectively use Grok with web/X search for real-time sentiment on high-value predictions. At $5/1K search calls, 100 daily web searches cost ~$15/month, easily covered by credits.

---

## Section 5: $350M daily volume, but liquidity is a spotlight, not sunlight

### Volume and open interest

Polymarket's **24-hour volume** was approximately **$346.6M** as of early March 2026, with a **30-day rolling volume of $8.1B** and **open interest of $375.1M** (DefiLlama). The all-time daily high was **$478M** on February 28, 2026 — driven by Iran strike markets that pushed politics to 46% of daily volume. January 2026 set the monthly record at **$12B**; February came in at **$7–8.1B**. Annualized fees reached **$69.7M** with **$46.2M** in revenue. A critical methodological note from Paradigm Research (December 2025): many dashboards were double-counting volume by summing all OrderFilled events rather than only taker-side events, potentially inflating some figures by ~2x.

### Category distribution (structural averages, adjusted for event spikes)

| Category | Share of volume | Active markets | Notes |
|---|---|---|---|
| **Sports** | ~39% | Major contributor | Largest category; dominates short-term |
| **Crypto** | ~28% | 4,056 markets | Dominated by 5/15-min price markets |
| **Politics/Geopolitics** | ~20% | 1,551 markets | Highest average volume per market |
| **Economics** | ~3–5% | 162 markets, $228.9M cumulative | Fed, CPI, unemployment |
| **Entertainment** | ~2–3% | Thin, attention-cycle driven | Volatile around events |
| **Weather/Niche** | <1% | Limited but growing | — |

Volume concentration is extreme: **505 markets with >$10M volume account for 47% of all trading**. The vast majority of Polymarket's ~21,848 active short-term markets have near-zero volume — 63% show zero 24-hour volume. An estimated **2,000–5,000 markets** have >$10K liquidity at any given time. Long-term US politics markets average **$811,000** in liquidity.

### Spreads reveal where the market-making opportunity lives

| Market tier | Typical spread | Examples |
|---|---|---|
| **High-liquidity** (>$1M vol) | **1–2¢** | Major elections, Fed decisions, top sports, BTC daily |
| **Mid-liquidity** ($50K–$1M) | **3–6¢** | Mid-tier sports, crypto alts, policy questions |
| **Low-liquidity** (<$10K) | **10–34¢+** | Entertainment, niche culture, weather |

From tightest to widest: major sports and crypto price markets (1–2¢) → flagship politics (1–4¢) → economics (3–6¢) → AI/tech (4–10¢) → geopolitics (variable) → entertainment/culture (10–30¢+) → weather/niche (>10¢). The displayed price is the midpoint of best bid/ask only when the spread is ≤$0.10; wider spreads show last traded price instead.

**Best risk-adjusted market-making opportunity**: medium-liquidity political markets where price oscillates in a narrow band over weeks. Practitioners report **$150–300/day per market** with >$100K daily volume. Polymarket pays ~$300/day in LP rewards per market option. Only 3–4 serious liquidity providers were active when the first open-source market-making bot launched in May 2025, and the competitive landscape remains thin versus traditional crypto market making.

### Resolution timelines

Crypto 5/15-min markets resolve in **minutes**. Daily crypto in **~24 hours**. Sports in **2–5 hours** (individual games). Economics resolves at specific meeting/release dates (**1–6 weeks**). Politics ranges from **days** (near-term policy questions) to **months or years** (elections). Entertainment resolves around event dates. Resolution uses the **UMA Optimistic Oracle** with a $750 USDC bond and 2-hour dispute window; ~98.5% of proposals are uncontested. Sports and crypto use Managed Optimistic Oracle v2 (MOOv2) with whitelisted proposers for faster settlement.

---

## Section 6: The CFTC commodity pool problem is the biggest legal hurdle

### Entity structure: manager-managed Delaware LLC

For a sub-$1M friends-and-family fund, a **manager-managed Delaware LLC** is optimal. It provides limited liability for all members (unlike an LP where the GP has unlimited personal liability without a separate shield entity), requires only one entity to form, and offers maximum operating agreement flexibility. Delaware's Court of Chancery, established LLC case law, and investor familiarity justify the ~$300/year franchise tax premium over Wyoming's $60 annual report fee. An LP structure adds unnecessary complexity at this scale — it requires forming at least two entities (GP LLC + LP) and more formal documentation.

### Securities exemption: Rule 506(b) is the clear choice

**Rule 506(b)** allows unlimited accredited investors plus up to **35 non-accredited but sophisticated investors**, requires no general solicitation (naturally satisfied for friends/family), and permits investor **self-certification** of accredited status. Rule 506(c) would allow advertising but requires formal verification (tax returns, bank statements, or third-party letters) and excludes all non-accredited investors. Since a F&F fund involves pre-existing substantive relationships and no need for public marketing, 506(b) eliminates verification burden while preserving flexibility. **Practical tip**: even under 506(b), accept only accredited investors to avoid the substantially heavier disclosure obligations triggered by including non-accredited participants (Rule 502(b) requires near-registration-level disclosure documents, potentially including audited financials).

File **Form D** with the SEC within 15 days of first sale, plus state Blue Sky notice filings in each investor's state of residence ($100–$300 per state via the NASAA Electronic Filing Depository).

### SEC Marketing Rule: technically doesn't apply, but anti-fraud does

The Marketing Rule (Rule 206(4)-1) **applies only to registered or required-to-be-registered investment advisers**. Exempt reporting advisers and unregistered managers are not bound by its prescriptive requirements. However, the SEC staff views the Marketing Rule as "relevant to the application of the anti-fraud provisions under the Advisers Act, which apply to **all** investment advisers, whether registered or not." This means:

- You don't technically need formal written policies for hypothetical performance
- But **any presentation of backtested or simulated returns must include robust disclosures** about methodology, assumptions, risks, and limitations
- Never post hypothetical performance on a public-facing website (the SEC has fined firms $50K–$175K for this)
- When showing backtested returns to investors: clearly state that results were not actually achieved, that backtesting has inherent limitations, that past performance doesn't predict future results, and detail every assumption in the methodology
- Always show net performance alongside gross performance with equal prominence

### The critical CFTC issue: your fund is almost certainly a commodity pool

The CFTC's regulatory posture has evolved dramatically. After settling with Polymarket for $1.4M in January 2022, the agency ended its investigation in July 2025, and Polymarket acquired QCEX (a CFTC-licensed derivatives exchange) for $112M. In November 2025, the CFTC issued an Amended Order of Designation permitting Polymarket to operate as a designated contract market (DCM) for US customers. In February 2026, the CFTC filed an amicus brief asserting **exclusive federal jurisdiction** over event contracts, classifying them as "swaps" under the Commodity Exchange Act.

This classification has a direct consequence: **a fund that pools investor capital to trade prediction market event contracts almost certainly constitutes a commodity pool**, making the manager a Commodity Pool Operator (CPO) subject to CFTC/NFA registration — or qualifying for an exemption.

The most commonly used exemption, **Rule 4.13(a)(3) ("de minimis")**, requires that aggregate initial margin and premiums for commodity positions stay **≤5% of portfolio liquidation value** (Test 1) or that net notional value stay **≤100% of liquidation value** (Test 2). **A fund whose primary strategy is trading prediction market contracts will almost certainly fail both tests**, since the entire portfolio consists of commodity interest positions.

The available alternatives are limited:

- **Rule 4.13(a)(2) ("small pool")**: no more than 15 participants and total gross contributions ≤$400,000 — too restrictive for a ~$1M fund
- **Rule 4.13(a)(1) ("investment club")**: no compensation except expense reimbursement — incompatible with management/performance fees
- **Full CPO registration**: NFA membership, Part 4 compliance, disclosure documents, periodic investor reporting — substantially increases costs and complexity

**This is the single most critical legal issue** and requires experienced CFTC counsel. The regulatory framework for prediction markets remains in flux, with nearly 50 active state lawsuits challenging CFTC jurisdiction, and some courts characterizing event contracts as gambling subject to state regulation. Fund documents must prominently disclose this uncertainty and the risk of forced position unwinding.

### Minimum viable documents

**Operating agreement** (for manager-managed LLC): investment strategy and purpose, manager authority and designation, capital contribution and call provisions, profit/loss allocation including carried interest (typically 20%), management fee (typically 1.5–2% AUM), distribution waterfall, transfer restrictions, withdrawal/redemption rights or lock-up period, **prediction market position valuation methodology**, key person provisions, dissolution and winding-down, indemnification/exculpation of manager, and Delaware governing law.

**Subscription agreement**: investor accredited status representations and warranties, subscription amount and payment terms, investor questionnaire, risk factor acknowledgment, power of attorney for fund operations, transfer restrictions, AML representations, and W-9.

**PPM**: not legally required under Reg D, but **strongly recommended**. A robust subscription booklet with comprehensive risk factors (prediction market regulatory uncertainty, CFTC jurisdiction, counterparty risk, platform risk, illiquidity) may suffice for a small F&F fund with only accredited investors. A full PPM typically costs **$8,000–$15,000** with specialized securities counsel. If any non-accredited investors participate, near-registration-level disclosure is required under Rule 502(b).

### Accredited investor thresholds remain unchanged since 1982

The current definition: individual income >$200,000 (>$300,000 with spouse) in each of the prior two years with reasonable expectation of continuation, or net worth >$1,000,000 excluding primary residence. Holders of Series 7, 65, or 82 licenses also qualify. Multiple House-passed bills (Equal Opportunity for All Investors Act, Fair Investment Opportunities for Professional Experts Act, INVEST Act) would create competency-based examination pathways and inflation-adjust thresholds, but **none have been enacted as of March 2026**. The Section 3(c)(1) Investment Company Act exemption (≤100 beneficial owners) will be easily satisfied. "Knowledgeable employees" of the fund manager are deemed accredited and don't count toward the 100-owner limit.

---

## Conclusion: a viable but legally complex opportunity

The technical foundation is sound. LLM ensembles of **8–12 diverse models** with Platt scaling can achieve Brier scores within 0.02–0.05 of market prices, and the **67/33 market-price/AI-forecast blend** demonstrated by Bridgewater's AIA system consistently outperforms either component alone. Groq's free tier supports a full three-model ensemble (Llama 4 Scout + Maverick + Qwen3 32B) at 50% TPD utilization for 100 daily analyses. Polymarket's new fee structure creates a clear **maker advantage**: zero fees, daily USDC rebates (20–25% of taker fee pool), and the death of latency arbitrage strategies that previously dominated. The widest spreads — and thus the richest market-making opportunity — exist in mid-liquidity political and economics markets where only 3–4 serious providers compete.

The binding constraint is legal, not technical. **A prediction market fund is almost certainly a CFTC-regulated commodity pool**, and the standard de minimis exemption won't apply when event contracts are the primary strategy. This likely means full CPO registration, NFA membership, and substantially higher compliance costs than a typical small hedge fund. The regulatory landscape is further complicated by active state litigation challenging CFTC jurisdiction over event contracts. Any serious fund formation must begin with specialized CFTC counsel — the cost of getting this wrong dwarfs the cost of getting it right.