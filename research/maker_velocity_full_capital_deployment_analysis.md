# Maker Velocity Full-Capital Deployment Analysis

**Author:** JJ (Autonomous Execution Layer)
**Date:** 2026-03-09
**Classification:** Internal — Decision Document
**Capital at stake:** $347.51 ($247.51 Polymarket USDC + $100 Kalshi USD)

---

## Executive Summary: The Honest Answer

You asked me to push all capital into maker velocity and get it deployed in the next hour. I've read every line of code, every dispatch, every pipeline output. Here is the truth:

**We have zero validated edge.** The pipeline says REJECT ALL. Every strategy variant has failed kill rules. We have zero resolved signals, zero closed trades, zero fill-rate data. Deploying $347.51 of real capital into a strategy with no empirical validation is not "pushing in" — it is donating to counterparties.

That said, you asked for the analysis of *how* to do it, and you asked about maximizing ARR through fast-resolving trades for data collection. Those are two different things, and the second one is actually the right instinct. Below is everything an LLM system designer needs to build the optimal deployment, followed by my honest assessment of what we should actually do.

---

## Part 1: The Maker Velocity System — Complete Architecture for LLM Design

### What the System Does

The maker velocity strategy places **post-only limit orders** on prediction markets, targeting fast-resolving contracts (under 48 hours) where we believe we have an information or calibration edge. "Maker" means we provide liquidity rather than consume it, which means:

- **Zero or near-zero fees** (Polymarket: 0% maker fee; Kalshi: reduced maker fees)
- **Better pricing** — we set our price, not accept theirs
- **Fill uncertainty** — orders may never execute, which is the core tradeoff

### The Signal Chain (How We Decide What to Trade)

```
Market Discovery → Probability Estimation → Calibration → Edge Calculation →
Toxicity Check → Velocity Scoring → Capital Allocation → Laddered Quoting
```

**Step 1: Market Discovery**
- Pull all active markets from Polymarket Gamma API and Kalshi API
- Filter: resolution < 48 hours, YES price between 0.10-0.90, allowed category
- Current category gates: politics (priority 3), weather (3), economic (2), geopolitical (1)
- Rejected categories: crypto (0), sports (0), unknown (0)

**Step 2: Probability Estimation (Ensemble)**
- `bot/ensemble_estimator.py`: Multi-model LLM consensus with temporal grounding
- Each model independently estimates P(YES) without seeing market price (anti-anchoring)
- Models: Claude, GPT-4, potentially others in ensemble
- Output: raw probability estimate with confidence interval

**Step 3: Calibration (Platt Scaling)**
- Static Platt parameters: A=0.5914, B=-0.3977
- Converts raw LLM probability to calibrated probability
- Walk-forward validated: static Brier 0.2134 beats all rolling windows
- Formula: `calibrated_p = 1 / (1 + exp(A * raw_p + B))`

**Step 4: Edge Calculation**
- `edge = calibrated_p - market_price` (for YES side)
- `edge = (1 - calibrated_p) - (1 - market_price)` (for NO side)
- Minimum edge threshold: 5% (MIN_EDGE = 0.05)
- After edge calculation, apply cost stress test (Kill Rule 3)

**Step 5: Toxicity Check (VPIN)**
- `bot/vpin_toxicity.py`: Volume-synchronized probability of informed trading
- Flow regimes: TOXIC (>0.75) → pull all orders; NEUTRAL (0.25-0.75) → normal; SAFE (<0.25) → tighten spread
- Equal-volume buckets (500 shares), rolling window of 10 buckets
- Requires WebSocket feed from `bot/ws_trade_stream.py`

**Step 6: Velocity Scoring**
- `velocity_score = (edge × 365) / resolution_hours`
- This is the annualized return per unit of capital lockup
- A 5% edge on a 4-hour market scores 109,500% annualized
- A 5% edge on a 48-hour market scores 38,000% annualized
- Fastest resolution = highest capital velocity = most data per dollar per day

**Step 7: Capital Allocation**
- `bot/maker_velocity_blitz.py`: `allocate_hour0_notional()`
- 5% reserve held back (always)
- 20% per-market concentration cap
- Score-weighted allocation across all positive-signal markets
- Spillover redistribution for under-cap markets

**Step 8: Laddered Quoting**
- `build_laddered_quote_intents()`: 3 price levels per market
- Level 1: reference price (best bid/ask)
- Level 2: reference - 1 tick ($0.01)
- Level 3: reference - 2 ticks ($0.02)
- Refresh intervals: 10s / 15s / 20s per level
- All orders are post-only (maker)

### The Scoring Function (Core Formula)

```python
score = edge × fill_probability × velocity_multiplier × wallet_confidence × toxicity_penalty
```

Where:
- `edge`: Calibrated probability minus market price (minimum 0.05)
- `fill_probability`: Estimated chance our limit order gets filled (currently UNMEASURED — this is the fatal gap)
- `velocity_multiplier`: `365 / resolution_hours` (faster = better)
- `wallet_confidence`: Signal from tracked smart wallets (80 scored, status: ready)
- `toxicity_penalty`: 1.0 if safe, 0.0 if toxic, linear between

### Kill Rules (What Stops a Trade)

1. **Semantic Decay**: Lead-lag confidence < 0.3 → kill
2. **Toxicity Survival**: >50% degradation under toxic flow simulation → kill
3. **Cost Stress**: `net_ev = gross_ev - taker_fee - latency_slippage > 0` required
   - Polymarket crypto fee: `price × (1-price) × 0.025` (max ~1.56%)
   - Polymarket sports fee: `price × (1-price) × 0.007` (max ~0.44%)
   - Default/politics: 0% taker fee
   - Latency slippage: 5ms × 0.0001 = 0.0005
4. **Calibration Enforcement**: Must pass Platt scaling within tolerance
5. **Minimum Signal Count**: N ≥ 100 for candidate, N ≥ 300 for validated
6. **OOS EV**: Out-of-sample expected value > 0, OOS/IS ratio ≥ 0.3

---

## Part 2: Platform-Specific Deployment Details

### Polymarket ($247.51 USDC)

**API Integration:**
- CLOB API with signature_type=1 (POLY_PROXY) — type 2 fails
- Post-only maker orders: 0% fee
- Minimum order: 5 shares, $5 notional (CLOB_HARD_MIN_SHARES=5, CLOB_HARD_MIN_NOTIONAL_USD=5)
- Tick size: $0.01

**Available Fast Markets (as of last pull):**
- 7,050 active markets across 500 events
- 22 BTC markets with <48h resolution
- 6 pass basic price/timing filters
- 0 pass current category gate (crypto = rejected)
- Politics (2,882 markets), weather (10), economic (390) are allowed categories
- None of the allowed-category markets have <24h resolution in current data

**The Minimum Order Problem:**
With $5 minimum notional per order and $247.51 total capital:
- Maximum simultaneous positions: 49 (at minimum size)
- At $5/position with 30 max open (current config): $150 deployed, $97.51 idle
- With 3-level ladders: $15 per market (3 × $5), max 16 markets simultaneously
- Reserve (5%): $12.38 held back → $235.13 deployable

**Order Flow:**
1. Scan allowed-category markets for edge ≥ 5%
2. Rank by velocity score
3. Allocate via score-weighted method
4. Place 3-level laddered post-only orders
5. Refresh every 10-20 seconds
6. Cancel unfilled orders if VPIN enters toxic regime
7. Record all decisions in SQLite

### Kalshi ($100 USD)

**API Integration:**
- `bot/kalshi/` directory with RSA key management
- Weather markets: temperature (above/below/range) and rain probability
- Separate from main pipeline (instance 3)

**Available Fast Markets:**
- Weather markets resolve daily or sub-daily
- Temperature markets: specific city, specific day, above/below threshold
- Rain markets: will it rain in [city] tomorrow?

**Edge Source for Kalshi:**
- NWS (National Weather Service) hourly forecast data
- Probability model: Normal distribution with historical standard deviation
- Edge threshold: 10% minimum (higher than Polymarket's 5% — weather is noisier)
- Signal construction: Compare Kalshi implied probability to NWS-derived probability

**Capital Math:**
- $100 total, likely similar minimum order constraints
- Weather markets have natural daily resolution cadence
- 1-3 markets per day realistically tradeable
- At $10-20 per position: 5-10 simultaneous positions possible

### BTC 5-Minute Maker (Fastest Resolution Path)

**This is the fastest data generator in the system.** `bot/btc_5min_maker.py`:

- 5-minute candle close markets on Polymarket
- Entry: T-10 seconds before close
- Signal: Compare Binance BTC spot to candle open; if |delta| ≥ 0.03% (30 bps), trade direction
- Quote range: 0.90-0.95 (conservative)
- Order size: $0.25-$2.50 per trade (BTC5_RISK_FRACTION=0.01 of $250 bankroll)
- Cancel unfilled at T-2 seconds
- Daily loss limit: $5

**Data generation rate:**
- 288 five-minute windows per day
- If 20% qualify (delta ≥ 30bps): ~58 trade attempts per day
- At 20% paper fill rate: ~12 fills per day
- 100 resolved trades in ~8 days at this rate

**THE PROBLEM:** Crypto category is priority 0 (REJECTED) in the current category filter. The BTC 5-min maker is coded and ready but blocked by our own rules because crypto markets have negative expected value under taker fee assumptions. As maker-only, the fee structure is different — but the category gate doesn't distinguish.

---

## Part 3: The ARR and Data Velocity Analysis

### Your Instinct Is Correct About Fast Resolution

You said you want fastest resolving trades for best ARR and data. Here's the math:

**Capital velocity = edge × (365 × 24 / resolution_hours)**

| Market Type | Resolution | Turns/Day | Annual Turns | $5 Position ARR (at 5% edge) |
|---|---|---|---|---|
| BTC 5-min | 5 minutes | 288 | 105,120 | $26,280 theoretical |
| BTC 15-min | 15 minutes | 96 | 35,040 | $8,760 theoretical |
| BTC 4-hour | 4 hours | 6 | 2,190 | $547.50 theoretical |
| Weather (daily) | 24 hours | 1 | 365 | $91.25 theoretical |
| Politics (weekly) | 168 hours | 0.14 | 52 | $13.00 theoretical |

**But these are THEORETICAL.** Actual ARR = theoretical × fill_rate × win_rate_above_breakeven.

With fill rate unmeasured (pipeline says `maker_fill_proxy_unmeasured`), we have no idea what the actual denominator is. If fill rate is 5% instead of the assumed 60%, the entire model collapses.

### Data Collection Value

Even if every trade loses money, the DATA from 100 resolved trades is worth more than the capital at risk, because:

1. We get real fill-rate measurement (currently zero data points)
2. We get real maker queue position data
3. We get real VPIN calibration from live order flow
4. We get real latency distribution data
5. We calibrate the ensemble estimator against actual outcomes

**The 100-trade target costs at most $10/day × 8-10 days = $80-100 in worst-case losses** (at daily loss cap). The information value of knowing our fill rate, win rate, and calibration accuracy is worth far more than $100 to a $347.51 fund trying to scale.

### Optimal Data Collection Allocation

If the goal is maximum data per day per dollar at risk:

```
Polymarket BTC 5-min:  $150 allocated, $2.50/trade, ~12 fills/day, $5 daily loss cap
Polymarket politics:   $50 allocated, $5/trade, ~2-3 fills/day, $5 daily loss cap
Kalshi weather:        $50 allocated, $10/trade, ~1-2 fills/day, $5 daily loss cap
Reserve:               $97.51 (28% of capital — higher than normal 5% because this is a data collection campaign, not an alpha deployment)
```

Expected data rate: ~15-17 resolved trades per day → 100 trades in 6-7 days.

---

## Part 4: What's Actually Blocking Us Right Now

### Blockers (Ranked by Severity)

**1. RUNTIME_EXECUTION_MODE = "blocked" (Fatal)**
The live bot literally cannot submit orders. `PAPER_TRADING = True`, `ALLOW_ORDER_SUBMISSION = False`. This is a code-level gate, not just a config flag.

**2. Drift Detected (Fatal)**
CLAUDE.md reports drift between service status (running) and launch posture (blocked). The bot is cycling on the VPS but not trading. This must be resolved to confirm we're in paper/shadow mode, not accidentally live.

**3. Category Gate Blocks All Fast Markets (Critical)**
The fastest data generators (BTC 5-min, BTC 15-min) are crypto category = priority 0 = REJECTED. To use them, we must either:
- Override the category gate for maker-only BTC fast markets (justified: 0% maker fee eliminates the taker-fee argument for rejection)
- Or accept that politics/weather markets resolve much slower (days, not minutes)

**4. $5 Minimum Order Size vs. $2.50 BTC Risk Target (Critical)**
The BTC 5-min bot targets $2.50 per trade (`BTC5_RISK_FRACTION=0.01 × $250`), but the CLOB minimum is $5 notional. This means either:
- Increase risk per trade to $5 (doubles exposure per window)
- Or accept that we can't trade at our preferred sizing

**5. Fill Rate = Unknown (Serious)**
The pipeline explicitly flags `maker_fill_proxy_unmeasured`. We've never placed a real maker order. We don't know if fill rate is 60% (assumption) or 5% (possible). The entire capital velocity model depends on this number.

**6. A-6 and B-1 Kill Watch (Active, Deadline March 14)**
Both structural alpha lanes show zero executable constructions. Kill deadline in 5 days. If we're going to reallocate to maker velocity, the kill watch gives us cover — we're already planning to sunset these lanes.

**7. Zero Resolved Signals (Serious)**
Best strategy variant (Bootstrap Cohort) has 3 raw signals, 0 resolved. We need 100 resolved for candidate status, 300 for validated. We are at the very beginning.

---

## Part 5: The One-Hour Deployment Plan (If We Do This)

Here is exactly what would need to happen to deploy capital in the next hour. I'm listing it because you asked. I am not recommending we do all of this in one hour.

### Hour-0 Checklist

**Minutes 0-10: Confirm Remote State**
```bash
ssh dublin "systemctl status jj-live && cat /opt/elastifund/jj_state.json"
```
- Verify paper mode confirmed
- Verify no accidental live orders exist
- Verify capital balances match expected ($247.51 Poly, $100 Kalshi)

**Minutes 10-20: Lift Category Gate for BTC Maker-Only**
- In `jj_live.py`: Add exception to `_DEFAULT_CATEGORY_PRIORITY` for crypto when execution_mode = "maker_only"
- Justification: Crypto rejection was based on taker fees (1.56-3.15%). Maker fee is 0%. The rejection reason doesn't apply.
- This unlocks 22 BTC fast markets (6 passing basic filters)

**Minutes 20-30: Fix Minimum Order Sizing**
- BTC 5-min bot: Increase `BTC5_MIN_TRADE_USD` to $5.00 (matches CLOB minimum)
- Adjust `BTC5_RISK_FRACTION` to 0.02 ($5/$250)
- Update daily loss limit to $10 (matches main bot)

**Minutes 30-40: Switch to Shadow-Live Mode**
- Set `PAPER_TRADING = False`
- Set `ALLOW_ORDER_SUBMISSION = True`
- Set `RUNTIME_EXECUTION_MODE = "shadow_live"` (orders placed but auto-cancelled after 30s if unfilled)
- Keep all daily loss caps active
- Keep Kelly fraction at 0.25

**Minutes 40-50: Deploy and Verify First Cycle**
```bash
ssh dublin "cd /opt/elastifund && python bot/btc_5min_maker.py --live --shadow"
```
- Watch first 5-minute window
- Verify order placement succeeds
- Verify order cancellation works
- Verify SQLite persistence captures all fields
- Check balance didn't change (shadow mode = auto-cancel)

**Minutes 50-60: Go Live on Next Window**
- If shadow cycle passed: remove auto-cancel
- First real maker order placed
- Monitor fill/no-fill
- Begin data collection

### What This Costs in Worst Case

- Daily loss cap: $10 (Polymarket) + $5 (Kalshi) = $15/day
- Maximum 7-day loss: $105 (30% of capital)
- Expected 7-day loss (assuming 45% win rate with 5% edge): ~$20-40
- Data collected: ~100-120 resolved trades
- Information value: Priceless (fill rate, calibration, latency, VPIN accuracy)

---

## Part 6: JJ's Recommendation

Here's what I actually think we should do, and it's not "push all capital in right now."

**The right move is a phased data collection campaign, not a capital deployment.**

**Phase 1 (Today, 1 hour): Shadow-Live on BTC 5-min**
- Lift crypto category gate for maker-only
- Fix minimum order sizing
- Deploy BTC 5-min in shadow-live mode (orders placed, auto-cancelled)
- Goal: Verify the plumbing works. Zero capital at risk.

**Phase 2 (Days 1-3): Live Maker with $5 Daily Loss Cap**
- First real maker orders on BTC 5-min markets
- $5 per trade, $5 daily loss cap (not $10)
- Target: 30-40 resolved trades
- Measure: Fill rate, execution latency, VPIN accuracy
- Maximum capital at risk: $15 (3 days × $5 cap)

**Phase 3 (Days 3-7): Scale Based on Data**
- If fill rate > 15% AND win rate > 48%: Double position size to $10, raise daily cap to $10
- If fill rate < 5% OR win rate < 45%: Tighten pricing, don't scale
- Add Kalshi weather markets in parallel ($5/trade, $5 daily cap)
- Target: 60-80 more resolved trades (100 total)

**Phase 4 (Day 7+): Full Capital Deployment Decision**
- With 100 resolved trades, we know:
  - Actual fill rate (the single most important unknown)
  - Actual win rate against resolved outcomes
  - Actual maker EV (edge minus execution costs)
  - Actual VPIN regime distribution
- If maker EV > 0 with statistical significance: Push to 90% capital deployment
- If maker EV ≤ 0: Kill maker velocity, reallocate to next strategy

**Why phased?** Because deploying $347.51 all at once based on zero empirical data violates our own Kill Rule 5 (minimum signal count), Kill Rule 6 (OOS EV must be positive), and the promotion gates (≥20 signals, ≥50% capture rate, ≤5% false positive rate). The rules exist for a reason. I wrote them.

**The fastest path to deploying all capital IS the phased approach.** It gets us from zero data to a deployment decision in 7 days. Pushing all capital in right now gets us the same data but with $200+ more at risk and no ability to course-correct.

---

## Part 7: The Numbers That Matter

### What We Know
- Capital: $347.51
- Infrastructure: Built, tested, 1,397 passing tests
- Calibration: Validated (Brier 0.2134, beats all rolling windows)
- Wallet flow: Ready (80 scored wallets)
- WebSocket: Coded (VPIN + OFI)
- Kill rules: Comprehensive (6 rules + promotion gates)

### What We Don't Know (And Must Learn)
- **Fill rate**: Assumed 60%, could be 5%. This is a 12× uncertainty.
- **Win rate on resolved trades**: Estimated 51-54%, no empirical data
- **Execution latency in production**: Coded for <200ms, never measured live
- **VPIN accuracy on real flow**: Simulated only, no live calibration
- **Kalshi weather model accuracy**: NWS-derived, untested against real outcomes

### The Honest Probability Assessment
- P(maker velocity generates positive EV over 100 trades): **35%**
  - Based on: 0% maker fees give real cost advantage, but fill rate uncertainty dominates
- P(we lose more than $50 in 7-day data collection): **15%**
  - Based on: $5/day loss cap × 7 days = $35 max, but gap risk on resolution could exceed cap
- P(data collection leads to validated edge for full deployment): **25%**
  - Based on: Historical success rate of strategy validation in this system (7 deployed / 131 tracked = 5.3%, but maker velocity has structural advantages the others didn't)

---

## Part 8: Context Package for Future LLM Sessions

Any LLM session that needs to design or execute the optimal maker velocity deployment should ingest:

### Required Files
1. `bot/maker_velocity_blitz.py` — Data contracts, scoring, allocation, laddering
2. `bot/btc_5min_maker.py` — BTC fast-market execution (1,100+ lines)
3. `bot/vpin_toxicity.py` — Toxicity detection for maker defense
4. `bot/ws_trade_stream.py` — WebSocket feed infrastructure
5. `bot/kill_rules.py` — Validation discipline (6 rules)
6. `bot/jj_live.py` — Main execution loop (lines 1-100 for config, 2800-2900 for signal dedup)
7. `bot/ensemble_estimator.py` — Probability estimation
8. `FAST_TRADE_EDGE_ANALYSIS.md` — Current pipeline status
9. `CLAUDE.md` — Operating instructions and current state
10. This document — Full deployment analysis

### Key Design Parameters
```python
# Capital
TOTAL_CAPITAL = 347.51  # USD equivalent
POLYMARKET_USDC = 247.51
KALSHI_USD = 100.00

# Risk Limits
MAX_POSITION_USD = 5.0
DAILY_LOSS_CAP = 10.0  # Polymarket
KALSHI_DAILY_LOSS_CAP = 5.0
KELLY_FRACTION = 0.25
MAX_OPEN_POSITIONS = 30
MAX_EXPOSURE_PCT = 0.90

# Execution
EXECUTION_MODE = "post_only_maker"
SIGNATURE_TYPE = 1  # POLY_PROXY
MIN_EDGE = 0.05
MAX_RESOLUTION_HOURS = 48.0
CLOB_MIN_NOTIONAL = 5.0
CLOB_MIN_SHARES = 5.0

# BTC 5-Min Specific
BTC5_ENTRY_SECONDS_BEFORE_CLOSE = 10
BTC5_CANCEL_SECONDS_BEFORE_CLOSE = 2
BTC5_MIN_DELTA = 0.0003  # 3 bps
BTC5_PRICE_RANGE = (0.90, 0.95)

# Calibration
PLATT_A = 0.5914
PLATT_B = -0.3977

# Velocity Scoring
velocity_score = (edge * 365 * 24) / resolution_hours

# Signal Scoring
signal_score = edge * fill_prob * velocity_mult * wallet_conf * toxicity_penalty
```

### Critical Unknowns to Resolve
1. Actual maker fill rate (assumed 60%, range 5-80%)
2. Actual execution latency P50/P95/P99
3. VPIN regime distribution on live markets
4. Category gate lift: Does removing crypto rejection for maker-only actually change the EV picture?
5. Kalshi weather model OOS performance

---

*End of analysis. The data tells us to be patient. The infrastructure is ready. The capital is available. The missing piece is empirical validation, and that takes trades, not wishes.*

— JJ
