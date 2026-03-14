# PREDICTIVE ALPHA FUND — LAUNCH READINESS CHECKLIST
### Last Updated: 2026-03-06 | Status: PRE-LAUNCH

> **Purpose:** Verify every system component is 100% optimized and ready for live trading.
> **Rule:** Nothing goes live until every Critical item is ✅.

---

## 1. FUNDING & CAPITAL DEPLOYMENT

### Getting Money Into Polymarket

- [ ] **Create/verify Polymarket account** — Sign up at polymarket.com, complete KYC if required
- [ ] **Choose funding method:**
  - [ ] **Option A: Crypto exchange transfer (cheapest)** — Buy USDC on Coinbase/Kraken/Binance → Withdraw to Polymarket deposit address → **MUST select Polygon (MATIC) network** → Funds arrive in 1-5 minutes
  - [ ] **Option B: Credit/debit card via MoonPay** — Click "Deposit" → Select card option → MoonPay handles USDC purchase → Higher fees (~3-5%) but fastest for non-crypto users → Min ~$30
  - [ ] **Option C: MetaMask wallet** — Install MetaMask → Switch to Polygon network → Bridge USDC if on Ethereum mainnet → Send to Polymarket deposit address
  - [ ] **Option D: Coinbase Pay / Robinhood Connect** — Direct integration from Coinbase or Robinhood balance
- [ ] **Deposit seed capital: $75 USDC minimum** (current plan) — verify balance visible in Polymarket UI
- [ ] **Confirm USDC.e balance on Polygon** — Check via Polygonscan using funder address
- [ ] **Plan capital deployment schedule:** $2K seed + $1K/week from disposable income
- [ ] **⚠️ CRITICAL: NEVER send non-USDC tokens or use wrong network — funds will be permanently lost**

---

## 2. POLYMARKET API CREDENTIALS

- [ ] **Export private key** from wallet used to fund Polymarket account
- [ ] **Record funder address** (the `0x...` Polygon address holding USDC.e)
- [ ] **Generate API credentials** (if using builder program):
  - [ ] `POLYMARKET_API_KEY`
  - [ ] `POLYMARKET_API_SECRET`
  - [ ] `POLYMARKET_API_PASSPHRASE`
- [ ] **Test CLOB connectivity** — Run: `curl https://clob.polymarket.com/` and confirm 200 response
- [ ] **Test authenticated endpoint** — Verify signing works with private key
- [ ] **Verify py-clob-client installed** on VPS: `pip show py-clob-client`

---

## 3. VPS & INFRASTRUCTURE

### Server (161.35.24.142 — DigitalOcean Frankfurt)

- [ ] **SSH access verified:** `ssh root@161.35.24.142`
- [ ] **Python 3.10+ confirmed:** `python3 --version`
- [ ] **All dependencies installed:** `pip install -r requirements.txt --break-system-packages`
- [ ] **py-clob-client installed:** `pip install py-clob-client --break-system-packages`
- [ ] **systemd service configured:** `systemctl status polymarket-bot`
- [ ] **Auto-restart on crash:** Verify `Restart=always` in service file
- [ ] **Disk space adequate:** `df -h` (bot.db ~102KB, ingest.db ~7.2MB)
- [ ] **Memory adequate:** `free -h` (bot is lightweight)
- [ ] **Network connectivity stable:** Ping Polymarket APIs from VPS
- [ ] **Tailscale VPN active** for dashboard access (port 8000 not publicly exposed)
- [ ] **Firewall rules reviewed** — Only SSH + Tailscale allowed

### Database

- [ ] **bot.db exists and writable:** `ls -la bot.db`
- [ ] **Schema up to date:** All 5 models (Order, Fill, Position, RiskEvent, KillSwitch)
- [ ] **Consider PostgreSQL migration** for concurrent writes (config supports `postgresql+asyncpg://`)
- [ ] **Backup strategy defined** — At minimum: daily `cp bot.db bot.db.bak`

---

## 4. ENVIRONMENT CONFIGURATION

### .env File on VPS (copy from .env.live.template)

**Kill Gates (CRITICAL — both must be explicitly changed):**
- [ ] `NO_TRADE_MODE=false` ← Change from default `true`
- [ ] `LIVE_TRADING=true` ← Change from default `false`

**Polymarket Credentials:**
- [ ] `POLYMARKET_PRIVATE_KEY=<real_key>`
- [ ] `POLYMARKET_FUNDER_ADDRESS=<real_0x_address>`
- [ ] `POLYMARKET_API_KEY=<if_applicable>`
- [ ] `POLYMARKET_API_SECRET=<if_applicable>`
- [ ] `POLYMARKET_API_PASSPHRASE=<if_applicable>`
- [ ] `POLYMARKET_CLOB_URL=https://clob.polymarket.com`
- [ ] `POLYMARKET_GAMMA_URL=https://gamma-api.polymarket.com`
- [ ] `CHAIN_ID=137`

**Claude AI:**
- [ ] `ANTHROPIC_API_KEY=sk-ant-...` ← Verify active and funded
- [ ] `CLAUDE_MODEL=claude-haiku-4-5-20241022` ← Confirm model string

**Risk Parameters (Week 1 — Conservative):**
- [ ] `MAX_DAILY_DRAWDOWN_USD=10.0`
- [ ] `MAX_PER_TRADE_USD=5.0`
- [ ] `MAX_EXPOSURE_PCT=0.80`
- [ ] `COOLDOWN_CONSECUTIVE_LOSSES=3`
- [ ] `COOLDOWN_SECONDS=3600`
- [ ] `ORDER_TIMEOUT_SECONDS=60`

**Rollout Tier (Week 1):**
- [ ] `ROLLOUT_MAX_PER_TRADE_USD=1.0`
- [ ] `ROLLOUT_MAX_TRADES_PER_DAY=3`
- [ ] `ROLLOUT_KELLY_ACTIVE=false`

**Telegram Alerting:**
- [ ] `TELEGRAM_BOT_TOKEN=<bot_token>`
- [ ] `TELEGRAM_CHAT_ID=<chat_id>`
- [ ] **Test alert:** Send test message via bot to confirm delivery

**Dashboard:**
- [ ] `DASHBOARD_TOKEN=<strong_random_token>` ← NOT `change_me`

---

## 5. SAFETY RAILS VERIFICATION

### All 6 Layers Must Be Operational

- [ ] **Layer 1 — Global Kill Gate:** `NO_TRADE_MODE` prevents ALL trades when `true`
- [ ] **Layer 2 — Broker Selection:** `LIVE_TRADING` toggles paper vs live broker
- [ ] **Layer 3 — Safety Rails (src/safety.py):**
  - [ ] Daily loss limit: Exits if daily P&L ≤ -$10
  - [ ] Per-trade hard cap: Clamped to min($5, rollout cap)
  - [ ] Total exposure cap: Cannot exceed 80% of bankroll
  - [ ] Cooldown: 3 consecutive losses → 1-hour pause
  - [ ] Rollout daily limit: Max 3 trades/day (Week 1)
- [ ] **Layer 4 — Risk Manager:** Position limits, rate limits enforced
- [ ] **Layer 5 — Kill Switch (DB-level):**
  - [ ] `POST /kill` immediately halts trading + cancels open orders
  - [ ] `POST /unkill` resumes trading
  - [ ] **TEST BOTH ENDPOINTS** before going live
- [ ] **Layer 6 — Telegram Alerts:** Every trade, error, kill event → notification

### Market Order Block

- [ ] **Confirmed: Market orders are PERMANENTLY BLOCKED** in `polymarket_broker.py`
- [ ] Only limit orders allowed (maker = zero fees on non-crypto/sports markets)
- [ ] Buy price offset of -$0.01 applied automatically

---

## 6. TRADING ENGINE VERIFICATION

### Core Loop (src/engine/loop.py)

- [ ] **5-minute scan interval** confirmed: `ENGINE_LOOP_SECONDS=300`
- [ ] **Market scanning:** Gamma API fetches ~100 active markets per cycle
- [ ] **Filtering:** YES price 10-90%, min $100 liquidity, scored by proximity to 50/50
- [ ] **Claude analysis:** Anti-anchoring prompt (market price HIDDEN from Claude)
- [ ] **Calibration v2 active:** fitted Platt scaling from the 532-market audit
  - [ ] 90% Claude → 71% calibrated
  - [ ] 80% Claude → 60% calibrated
  - [ ] 50% Claude → 40% calibrated
- [ ] **Asymmetric thresholds:** YES edge ≥ 15%, NO edge ≥ 5%
- [ ] **Taker fee subtraction:** Edge must exceed fee to trade
- [ ] **Quarter-Kelly sizing:**
  - [ ] YES multiplier: 0.25×
  - [ ] NO multiplier: 0.35×
  - [ ] Min position: $0.50
  - [ ] Max position: $10 (or rollout cap)
- [ ] **Category routing active:**
  - [ ] Politics/Weather: Priority 3 (HIGH)
  - [ ] Economic/Unknown: Priority 2 (MODERATE)
  - [ ] Geopolitical: Priority 1 (LOW, reduced sizing)
  - [ ] Crypto/Sports/Fed: Priority 0 (DO NOT TRADE)
- [ ] **Resolution time estimator:** Velocity scoring prioritizes fast-resolving markets
- [ ] **Order timeout:** Unfilled orders auto-cancelled after 60 seconds

---

## 7. BACKTEST & MODEL VALIDATION

### 532-Market Backtest Results (Verified 2026-03-05)

- [ ] **Win rate (calibrated):** 68.5% ✓
- [ ] **Win rate (NO only):** 70.2% ✓
- [ ] **Brier score (out-of-sample):** 0.245 ✓
- [ ] **Brier improvement vs raw:** +0.041 (from 0.286) ✓
- [ ] **Platt scaling validated on 30% holdout** ✓

### Monte Carlo Simulation (10,000 paths)

- [ ] **P(Ruin) = 0.0%** across all 10,000 simulations ✓
- [ ] **Median final value:** $918 from $75 starting capital (12 months) ✓
- [ ] **Quarter-Kelly outperforms flat by +309%** ✓

### ARR Scenarios

- [ ] Conservative: +124% (baseline, 5 trades/day)
- [ ] Moderate: +403% (calibrated + category filter + asymmetric)
- [ ] Aggressive: +872% (NO-only strategy)
- [ ] ★ Velocity Target: +6,007% (top-5 velocity-sorted, 3x capital turnover)

### Confidence Check

- [ ] **Acknowledge: 32% confidence** — Backtest ≠ live performance
- [ ] **Expect 10-20% slippage** vs backtest in live trading
- [ ] **Zero live resolved trades to date** — all metrics are simulated

---

## 8. MONITORING & ALERTING

### FastAPI Dashboard (port 8000)

- [ ] `GET /health` — Returns 200 ✓
- [ ] `GET /status` — Shows positions, PnL, kill state ✓
- [ ] `GET /metrics` — Order/position counts ✓
- [ ] `GET /risk` — Current limit configurations ✓
- [ ] `PUT /risk` — Can update limits dynamically ✓
- [ ] `POST /kill` — Emergency stop works ✓
- [ ] `POST /unkill` — Resume works ✓
- [ ] `GET /orders` — Shows recent order history ✓
- [ ] `GET /execution` — Fee drag, slippage analysis ✓
- [ ] `GET /logs/tail` — Last N log lines ✓
- [ ] **Dashboard token is NOT default** (`change_me`)

### Telegram Bot

- [ ] Bot token valid and active
- [ ] Chat ID correct (messages arrive in correct chat)
- [ ] Startup notification: "💰 Live Trading" message received
- [ ] Trade notifications: Received on every order placement
- [ ] Error notifications: Received on API failures
- [ ] Kill switch notifications: Received on /kill and /unkill

### Log Monitoring

- [ ] `journalctl -u polymarket-bot -f` works on VPS
- [ ] structlog JSON formatting active
- [ ] Log rotation configured (prevent disk fill)

---

## 9. FIRST LIVE TRADE VERIFICATION

### Go-Live Sequence (Week 1)

- [ ] **Step 1:** SSH into VPS
- [ ] **Step 2:** Verify .env has all credentials + `LIVE_TRADING=true` + `NO_TRADE_MODE=false`
- [ ] **Step 3:** Restart bot: `sudo systemctl restart polymarket-bot`
- [ ] **Step 4:** Watch logs: `journalctl -u polymarket-bot -f`
- [ ] **Step 5:** Confirm Telegram startup alert received
- [ ] **Step 6:** Wait for first trade signal (may take 1-5 cycles = 5-25 minutes)
- [ ] **Step 7:** Verify first order:
  - [ ] Order appears on Polymarket CLOB
  - [ ] Telegram alert received with market details
  - [ ] `bot.db` order record created
  - [ ] Order size ≤ $1.00 (Week 1 rollout cap)
  - [ ] Order auto-cancels after 60s if unfilled
- [ ] **Step 8:** Test kill switch
  - [ ] `POST /kill` with reason → all orders cancelled
  - [ ] Telegram alert confirms kill
  - [ ] `POST /unkill` → trading resumes
  - [ ] Telegram alert confirms unkill

### First 50 Trades Monitoring

- [ ] Track fill rate (% of orders that execute)
- [ ] Track average slippage vs expected price
- [ ] Track fee drag per trade
- [ ] Compare paper P&L vs live P&L
- [ ] Verify win rate tracking (target: ~68% calibrated)
- [ ] Check execution endpoint: `GET /execution` for detailed stats

---

## 10. GRADUAL ROLLOUT SCHEDULE

### Week 1-2: Observation Phase

- [ ] Max per trade: **$1.00**
- [ ] Max trades/day: **3**
- [ ] Kelly sizing: **OFF** (flat sizing)
- [ ] **Success criteria:** >60% win rate, no system errors, fills executing correctly
- [ ] **Abort criteria:** >3 consecutive system errors, fill rate <50%, unexpected losses

### Week 2-3: Increased Exposure

- [ ] Bump to: `ROLLOUT_MAX_PER_TRADE_USD=2.0`
- [ ] Bump to: `ROLLOUT_MAX_TRADES_PER_DAY=5`
- [ ] Kelly: Still OFF
- [ ] **Success criteria:** Consistent profitability, slippage within expectations

### Week 3+: Full Kelly Activation

- [ ] Bump to: `ROLLOUT_MAX_PER_TRADE_USD=5.0`
- [ ] Unlimited trades/day: `ROLLOUT_MAX_TRADES_PER_DAY=-1`
- [ ] Enable Kelly: `ROLLOUT_KELLY_ACTIVE=true`
- [ ] **Success criteria:** P&L tracking backtest within 20% margin

---

## 11. OPTIMIZATION OPPORTUNITIES (HIGH LEVERAGE)

### More Markets

- [ ] **Increase scan coverage:** Currently 100 markets/cycle → Target 200-500
- [ ] **Add more category-specific logic** for politics, weather, economic events
- [ ] **Category-specific calibration models** (P0-62) — Separate Platt parameters per category
- [ ] **Pre-resolution exit strategy** (P0-60) — Exploit info leakage 3-7 days before resolution (+20-40% ARR)
- [ ] **Cross-platform arbitrage** (P1-43) — NegRisk, other prediction markets

### More Sophisticated Monte Carlo

- [ ] **Current:** 10,000 paths, quarter-Kelly, compounding
- [ ] **Add:** Regime-switching (bull/bear market conditions)
- [ ] **Add:** Correlated market movements (not just independent draws)
- [ ] **Add:** Dynamic Kelly adjustment based on rolling win rate
- [ ] **Add:** Drawdown-conditional position scaling
- [ ] **Add:** Fat-tailed distributions (replace normal with Student-t or Levy)
- [ ] **Add:** Market impact modeling (slippage increases with position size)
- [ ] **Add:** Time-varying edge decay (model competitive erosion)
- [ ] **Add:** Liquidity constraints (order book depth affects max position)
- [ ] **Add:** Multi-strategy simulation (run all 8 variants simultaneously)

### More Sophisticated Black-Scholes / Options-Style Pricing

- [ ] **Binary option pricing model** — Treat prediction markets as European binary options
  - [ ] Implied volatility extraction from order book spread
  - [ ] Greeks: Delta (probability sensitivity), Theta (time decay to resolution)
  - [ ] Vega (volatility sensitivity to news events)
- [ ] **Stochastic volatility model** (Heston-style) for probability dynamics
- [ ] **Jump-diffusion model** (Merton) for sudden probability shifts (news events)
- [ ] **Mean-reversion model** — Ornstein-Uhlenbeck for probability oscillation around fair value
- [ ] **Information-theoretic pricing** — KL divergence between Claude estimate and market price
- [ ] **Bayesian updating framework** — Prior (base rate) → Posterior (with evidence) with explicit uncertainty quantification
- [ ] **Volatility surface construction** — Map implied vol across markets by time-to-resolution and current price
- [ ] **Risk-neutral pricing** — Back out risk-neutral probabilities from order book
- [ ] **Pairs trading model** — Correlated market identification + spread trading

### Data Feed Expansion

- [ ] **News sentiment pipeline** (P0-37) — Reuters, Bloomberg, NewsData.io (+15-30% ARR)
- [ ] **Polling data integration** (P1-38) — FiveThirtyEight, RCP, Ipsos
- [ ] **Government data** (P0-59) — FRED, BLS economic releases
- [ ] **Wikipedia pageview signals** (P0-63) — Attention proxy
- [ ] **Google Trends integration** (P0-63) — Search interest as leading indicator
- [ ] **Social media sentiment** — Twitter/X, Reddit signal extraction

### Multi-Model Ensemble

- [ ] **GPT-4o estimator** — Implement in `src/ensemble.py` (currently placeholder)
- [ ] **Grok-3 estimator** — Implement in `src/ensemble.py` (currently placeholder)
- [ ] **Aggregation logic:** Mean when stdev < 0.15 (models agree), abstain otherwise
- [ ] **Expected improvement:** Higher confidence signals, reduced variance
- [ ] **Multi-run ensemble** — 3-7 Claude runs per market, aggregate for stability

### Market Making Mode

- [ ] **Two-sided CLOB quoting** — Maker-only, zero fees
- [ ] **Inventory management** — Skew quotes based on position
- [ ] **Split/merge token operations** — Required for proper market making
- [ ] **Sandbox testing** — Already has `MAKER_MODE=false` config ready
- [ ] **Estimated ROI:** $50-200/mo on $1-5K capital

---

## 12. COMMAND NODE UPDATE ITEMS

- [ ] **Version bump** from v1.4.0 to v1.5.0 upon live launch
- [ ] **Update status** from "Live-ready" to "LIVE — Week 1 rollout"
- [ ] **Record first live trade date and details**
- [ ] **Update starting capital** once actual deposit confirmed
- [ ] **Add live performance section** (separate from backtest)
- [ ] **Document any parameter changes** from backtest defaults
- [ ] **Update research dispatch priorities** based on live performance data
- [ ] **Add execution quality metrics** (fill rate, slippage, fee drag)

---

## 13. REPLIT DASHBOARD UPDATE ITEMS

- [ ] **Fix hero number:** Update from +1,692% to +6,007% (velocity-optimized)
- [ ] **Fix 7 duplicate content blocks:**
  1. [ ] Favorite-Longshot Bias chart (renders twice)
  2. [ ] Velocity Score Formula (renders twice)
  3. [ ] Safety Rails diagram (renders twice)
  4. [ ] Position Sizing summary (renders twice)
  5. [ ] Strategy Comparison table (partially duplicates)
  6. [ ] Research Foundation evidence cards (duplicate)
  7. [ ] Resource Allocation treemap (renders twice)
- [ ] **Fix blank/black dead space** on page 11
- [ ] **Add missing "Honest Risk Assessment"** content (Section 14 — header exists, no risk cards)
- [ ] **Add missing "Competitive Landscape"** section (Section 15 — completely absent)
- [ ] **Complete Category Routing** — Tier B and Tier F not fully rendering
- [ ] **Add Monte Carlo confidence bands** to chart
- [ ] **Add prediction market explainer**
- [ ] **Add anchoring before/after scatter plots**
- [ ] **Add Kelly vs Flat chart labels/legend**
- [ ] **Clarify drawdown ladder vs rollout plan** (currently confused)

---

## 14. LEGAL & COMPLIANCE

- [ ] **LLC entity registered** for Predictive Alpha Fund
- [ ] **Reg D 506(b) compliance** — PPM drafted and reviewed
- [ ] **CFTC Rule 4.13 exemption** verified (commodity pool operator exemption)
- [ ] **Tax strategy defined** — Prediction market gains reporting
- [ ] **Investor materials finalized** — Ready for $10K-$100K raise
- [ ] **Risk disclosures comprehensive** — 13+ risk factors documented in Command Node
- [ ] **Polymarket ToS compliance** — Bot trading permitted under platform terms

---

## 15. DISASTER RECOVERY

- [ ] **Kill switch tested:** `POST /kill` → immediate halt, all orders cancelled
- [ ] **Rollback plan:** `git revert` or restore from known-good commit
- [ ] **Database backup schedule:** Daily `cp bot.db bot.db.bak`
- [ ] **VPS snapshot available** on DigitalOcean
- [ ] **Graceful shutdown:** SIGTERM → close all orders → persist DB → exit
- [ ] **Communication plan:** Telegram alerts to personal + any investors
- [ ] **Maximum loss scenario documented:** Daily cap $10, total exposure 80%, no ruin path in MC

---

## LAUNCH DECISION MATRIX

| Gate | Requirement | Status |
|------|-------------|--------|
| **G1** | Polymarket funded with ≥$75 USDC | ⬜ |
| **G2** | API credentials configured and tested | ⬜ |
| **G3** | VPS running, systemd service healthy | ⬜ |
| **G4** | All 6 safety layers verified | ⬜ |
| **G5** | Kill switch tested (kill + unkill) | ⬜ |
| **G6** | Telegram alerts confirmed working | ⬜ |
| **G7** | Dashboard endpoints all responding | ⬜ |
| **G8** | First paper trade observed in logs | ⬜ |
| **G9** | .env reviewed — no default passwords | ⬜ |
| **G10** | Rollout Week 1 parameters set | ⬜ |

**ALL 10 GATES MUST BE ✅ BEFORE LIVE TRADING.**

---

*Generated 2026-03-06 from comprehensive codebase audit. Cross-referenced against COMMAND_NODE.md, src/safety.py, src/core/config.py, src/broker/polymarket_broker.py, .env.live.template, and 47 Python source files.*
