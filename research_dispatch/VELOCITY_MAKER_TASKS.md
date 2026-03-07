# Velocity Maker Strategy — Cowork Tasks

Priority-ranked tasks for implementing the full velocity maker strategy.
Each task has a clear objective, estimated effort, and expected impact.

---

## P0 — Critical (Do This Week)

### VM-001: WebSocket Integration for Real-Time Order Book
**Objective:** Replace REST polling with WebSocket streams for sub-second market data.
**Why:** REST is rate-limited to 60 req/min. WebSocket `wss://ws-subscriptions-clob.polymarket.com/ws/market` provides real-time `price_change`, `last_trade_price`, and `book` events with no rate limit.
**Implementation:**
- Connect to market channel WebSocket
- Subscribe to top-20 velocity markets
- Stream `best_bid_ask` changes into signal pipeline
- React to `market_resolved` events for instant position resolution
**Files:** `src/websocket_client.py` (exists on VPS), new `src/ws_market_feed.py`
**Effort:** 4-6 hours
**Impact:** 10x faster data, enables sub-minute strategies

### VM-002: Maker-Only Order Execution Mode
**Objective:** Ensure all orders are limit orders that rest on the book (never cross spread).
**Why:** Makers pay 0% fees + earn daily USDC rebates. Takers pay up to 1.56% on crypto markets. This is a +2.24pp structural edge (maker +1.12% vs taker -1.12%).
**Implementation:**
- Add `maker_only` flag to broker
- Place buy orders at `best_bid` or `best_bid - 0.01` (never at ask)
- Place sell orders at `best_ask` or `best_ask + 0.01`
- Cancel and re-place if not filled within 30 seconds
- Track maker fill rate metric
**Files:** `src/broker/polymarket_broker.py`, `src/paper_trader.py`
**Effort:** 3-4 hours
**Impact:** +2.24pp per trade (eliminates all fees)

### VM-003: 5-Minute Crypto Market Scanner
**Objective:** Scan and trade BTC/ETH/SOL/XRP 5-minute Up/Down markets.
**Why:** Highest-volume short-duration markets. 0.44% max taker fee (low), maker rebates. Resolve every 5 minutes = extreme capital velocity.
**Implementation:**
- Query Gamma API with tag_id for crypto 5M markets
- Parse market windows (start time, end time)
- Integrate with Binance/Coinbase WebSocket for real-time crypto prices
- Compare exchange price vs Polymarket odds to find edge
- Only trade when exchange price strongly predicts outcome (>70% confidence)
**Files:** New `src/crypto_5min_scanner.py`
**Effort:** 6-8 hours
**Impact:** Opens 100+ daily trading opportunities

---

## P1 — High Priority (Do This Month)

### VM-004: Combinatorial/Semantic Arbitrage Engine
**Objective:** Use Claude to detect logically linked markets with inconsistent odds.
**Why:** $40M/year in realized arbitrage on Polymarket (arXiv:2508.03474). Example: "Trump wins presidency" at 60% while "Republican wins presidency" at 55% = arbitrage.
**Implementation:**
- Embed all active market questions using Claude
- Cluster semantically similar markets
- Check logical consistency: P(A) ≤ P(B) when A implies B
- Flag violations as arbitrage opportunities
- Size trades to lock in guaranteed profit
**Files:** New `src/semantic_arb.py`
**Effort:** 8-12 hours
**Impact:** Risk-free profit extraction

### VM-005: Category-Specific Edge Exploitation
**Objective:** Systematically target categories with highest maker-taker gaps.
**Why:** World Events (7.32pp), Media (7.28pp), Entertainment (4.79pp) have 40x larger gaps than Finance (0.17pp). Most bots target crypto/finance — we should target where the edge is.
**Implementation:**
- Auto-categorize all markets using Claude
- Weight signal generation toward high-gap categories
- Track per-category P&L and adjust
- Build category-specific calibration (Platt scaling per category)
**Files:** `src/scanner.py` (already has category detection), `src/calibration/`
**Effort:** 4-6 hours
**Impact:** +3-7pp edge on underserved categories

### VM-006: Sports In-Game Trading
**Objective:** React to live sports scores to trade game-outcome markets.
**Why:** Live scores via `wss://sports-api.polymarket.com/ws` (channel: `sport_result`). Score changes happen before crowd adjusts odds. NCAAB/Serie A have only 0.44% max taker fee.
**Implementation:**
- Connect to sports WebSocket
- Map score events to market outcomes
- Simple model: team up by X points with Y minutes left → compute win probability
- Compare model probability vs market odds
- Enter maker orders when model disagrees with market
**Files:** New `src/sports_live.py`
**Effort:** 8-10 hours
**Impact:** Multiple opportunities per game day

### VM-007: Weather Market Exploitation
**Objective:** Trade daily temperature markets using professional forecast models.
**Why:** 153+ markets daily, 0% fees, professional models (GFS, ECMWF) update every 6 hours. Latency between model updates and Polymarket odds = systematic edge.
**Implementation:**
- Expand NOAA client to parse temperature ranges
- Map NOAA forecasts to Polymarket temperature outcome buckets
- Trade when forecast strongly disagrees with market odds
- Already have NOAA integration — needs market matching logic
**Files:** `src/noaa_client.py` (exists), new `src/weather_trader.py`
**Effort:** 4-6 hours
**Impact:** 150+ daily trades with 0% fees

---

## P2 — Important (Ongoing)

### VM-008: Optimism Tax Harvester
**Objective:** Systematically sell YES longshots where takers overpay.
**Why:** YES contracts at 1-10¢ have -41% to -64% EV for takers. NO outperforms YES at 69/99 price levels. Pure structural edge.
**Implementation:**
- Identify markets where YES is priced 1-10¢
- Claude estimates true probability
- If true prob < market YES price, sell YES (buy NO)
- Focus on Entertainment/World Events categories (biggest gap)
**Files:** New logic in `src/claude_analyzer.py`
**Effort:** 2-3 hours
**Impact:** Harvests persistent behavioral bias

### VM-009: AI + Market Consensus Ensemble
**Objective:** Combine Claude probability with market price for better estimates.
**Why:** AIA Forecaster research shows AI+consensus ensemble beats consensus alone, even when AI alone is slightly worse than market.
**Implementation:**
- Claude estimates prob independently (already exists)
- Combine with market price using weighted average: `final = w*claude + (1-w)*market`
- Optimize w per category using backtest data
- Use ensemble for Brier score improvement
**Files:** `src/claude_analyzer.py`, `src/calibration/`
**Effort:** 3-4 hours
**Impact:** Better probability estimates across the board

### VM-010: Cross-Platform Arbitrage (Polymarket vs Kalshi)
**Objective:** Monitor same-event markets on both platforms for price divergence.
**Why:** Prices diverge by >5pp ~15-20% of the time. Zero-risk profit when yes_poly + no_kalshi < 1.00.
**Implementation:**
- Kalshi API integration for market scanning
- Match markets across platforms by question similarity
- Monitor price divergence in real time
- Alert when arb opportunity exceeds fee threshold
**Files:** New `src/kalshi_client.py`, `src/cross_platform_arb.py`
**Effort:** 10-15 hours
**Impact:** Risk-free arbitrage but capital-intensive

### VM-011: Whale Copy Trading Signal
**Objective:** Monitor top-performing wallets and use their trades as signals.
**Why:** Top wallets (SeriouslySirius $2M+, HyperLiquid0xb $1.4M+) have demonstrated consistent edge.
**Implementation:**
- Track top 10 wallets via Polymarket Data API `/trades` endpoint
- When a tracked wallet enters a position, log as supporting evidence
- Feed into Bayesian signal processor as additional evidence source
- Don't blindly copy — use as one input in ensemble
**Files:** New `src/whale_tracker.py`, modify `src/bayesian_signal.py`
**Effort:** 6-8 hours
**Impact:** Additional signal source from proven traders

---

## P3 — Research & Future

### VM-012: Black-Scholes for Prediction Markets
**Research:** Implement logit jump-diffusion pricing model (arXiv:2510.15205).
**Goal:** Enable options-style Greeks and hedging for prediction market positions.

### VM-013: Resolution Rule Parsing via LLM
**Research:** Use Claude to systematically parse fine-print resolution rules.
**Goal:** Identify ambiguous resolutions and exploit divergent interpretations.

### VM-014: Multi-Agent Debate for Probability Estimation
**Research:** Use multiple Claude instances debating to improve calibration.
**Goal:** Reduce overconfidence through adversarial reasoning.

---

## Key Reference Accounts (X/Twitter)
- @beckerrjon — Microstructure research (72.1M trades dataset)
- @Domahhhh — Top trader, strategy breakdowns
- @GaetenD — Entertainment market specialist ($300K+)
- @Param_eth — On-chain bot analysis
- @DextersSolab — Bot performance analysis
- @the_smart_ape — Correlation tools
- @bankrbot — AI agent strategies
- @NateSilver538 — Polymarket advisor

## Key Tools
- polymarketanalytics.com — Trader performance dashboards
- polywhaler.com — Whale trade alerts
- polytrackhq.app — Smart money detection
- polymarketcorrelation.com — Cross-market correlation
