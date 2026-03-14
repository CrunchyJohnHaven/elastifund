# Monte Carlo Trading Simulation Design
## Prediction Market Strategy — Advanced Methodology & Formulas

---

## 1. Backtest Summary (Inputs)

| Parameter | Value |
|---|---|
| Resolved markets | 532 |
| Overall win rate | 64.9% |
| Buy YES win rate | 55.8% |
| Buy NO win rate | 76.2% |
| Avg P&L per trade | +$0.60 on $2 position (30% return) |
| Edge distribution | mean 31.7%, range [5%, 80%] |
| Brier score | 0.239 |

---

## 2. Trade Distribution Model

### 2.1 Binary Outcome Structure

Every Polymarket trade resolves to WIN or LOSS. From the backtest:

```
E[P&L] = P(win) × E[profit|win] + P(loss) × E[loss|loss]

0.649 × E[profit|win] - 0.351 × $2.00 = $0.60
E[profit|win] = $1.302 / 0.649 ≈ $2.006
```

**Key result:** Average wins return ~$2.00 profit on $2.00 risked (~100%), and losses lose the full $2.00 stake. This implies an average entry price near $0.50 across both YES and NO trades.

### 2.2 Payoff Functions

**Buy YES at market price p:**

- Shares purchased: 2/p (each share costs $p, pays $1 if YES)
- Win (YES resolves): profit = 2(1 − p)/p
- Loss (NO resolves): loss = −$2

**Buy NO at market price p (equivalently, buy NO shares at price 1 − p):**

- Win (NO resolves): profit = 2p/(1 − p)
- Loss (YES resolves): loss = −$2

### 2.3 Entry Price & Edge Relationship

The edge is defined as `edge = p_true − p_market` for YES bets, or `edge = (1 − p_market) − (1 − p_true) = p_market − p_true` for NO bets (always positive when we have an edge).

From the aggregate statistics:

```
E[p_true] ≈ overall_win_rate = 0.649
E[edge] = 0.317
E[p_market] ≈ E[p_true] − E[edge] = 0.649 − 0.317 = 0.332
```

This means on average, the strategy enters markets priced around 33.2% and wins 64.9% of the time — a substantial informational edge.

### 2.4 Edge Distribution Parameterization

**Recommended: Truncated Beta distribution** on [0.05, 0.80].

```
raw ~ Beta(α, β)
edge = 0.05 + raw × 0.75

Calibration: match E[edge] = 0.317
  → E[raw] = (0.317 − 0.05) / 0.75 = 0.356
  → α/(α + β) = 0.356
```

Starting point: `Beta(α=2.5, β=4.5)` gives mean ≈ 0.357. Fine-tune α, β to match empirical moments from the 532-market dataset. If the edge distribution is right-skewed (many small edges, few large ones), a `Gamma(shape=2.5, scale=0.127)` truncated to [0.05, 0.80] is an alternative (mean = 2.5 × 0.127 = 0.317).

### 2.5 Trade Generation Algorithm

For each simulated trade t:

```
Step 1: Draw edge
    e_t ~ TruncatedBeta(α, β, min=0.05, max=0.80)

Step 2: Draw trade direction
    direction_t ~ Bernoulli(p_YES=0.558)
    (55.8% of trades are buy_YES, 44.2% are buy_NO)

Step 3: Derive market price
    If buy_YES:
        p_market = p_true − edge, where p_true ~ f(edge)
        Or: draw p_market from empirical distribution, then p_true = p_market + e_t
    If buy_NO:
        p_market drawn similarly, p_true = p_market − e_t (we think YES is overpriced)

Step 4: Compute win probability and payoff
    If buy_YES:
        win_prob = p_market + e_t  (clamped to [0, 1])
        win_payoff = 2(1 − p_market) / p_market
    If buy_NO:
        win_prob = 1 − p_market + e_t  (our NO probability)
        win_payoff = 2 × p_market / (1 − p_market)
    loss_payoff = −$2

Step 5: Resolve trade
    outcome ~ Bernoulli(win_prob)
    P&L_t = outcome × win_payoff + (1 − outcome) × loss_payoff
```

**Validation:** After generating N trades, confirm mean(P&L) ≈ $0.60 and mean(win_rate) ≈ 64.9%.

---

## 3. Portfolio Path Simulation (10,000 Monte Carlo Runs)

### 3.1 Simulation Loop

```
Parameters:
    N_sim = 10,000        # number of simulation paths
    trades_per_day = 5
    days = 365
    T = trades_per_day × days = 1,825 trades per path
    B_0 = starting capital

For each simulation i in [1, N_sim]:
    bankroll = B_0
    peak = B_0
    max_drawdown = 0
    daily_returns = []
    wealth_path = [B_0]

    For each day d in [1, 365]:
        daily_pnl = 0

        For each trade t in [1, 5]:
            Generate trade using Section 2.5 algorithm
            Apply position sizing (Section 4)
            Apply market impact (Section 5)
            Resolve trade → P&L_t
            daily_pnl += P&L_t
            bankroll += P&L_t

            If bankroll <= 0:
                Mark ruin at (day d, trade t)
                Break both loops

        daily_return = daily_pnl / (bankroll − daily_pnl)
        daily_returns.append(daily_return)
        wealth_path.append(bankroll)

        peak = max(peak, bankroll)
        drawdown = (bankroll − peak) / peak
        max_drawdown = min(max_drawdown, drawdown)

    Record: final_bankroll, max_drawdown, wealth_path, daily_returns
```

### 3.2 Output Metrics per Path

| Metric | Formula |
|---|---|
| Final capital | bankroll at end of path (or 0 if ruin) |
| Total return | (final − B_0) / B_0 |
| CAGR | (final / B_0)^(1/years) − 1 |
| Max drawdown | min over path of (W_t − peak_t) / peak_t |
| Ruin flag | 1 if bankroll ever ≤ 0 |

### 3.3 Aggregated Outputs (Across 10,000 Paths)

```
Median final capital:     percentile(final_capitals, 50)
5th percentile path:      percentile(final_capitals, 5)
95th percentile path:     percentile(final_capitals, 95)
Mean final capital:       mean(final_capitals)

P(ruin):                  count(ruin_flags) / N_sim
P(doubling):              count(final > 2 × B_0) / N_sim
P(negative return):       count(final < B_0) / N_sim
```

Plot the median, 5th, and 95th percentile *paths* (cumulative P&L over time) by tracking wealth_path percentiles at each time step.

---

## 4. Capital Scaling & Kelly Criterion Sizing

### 4.1 Kelly Criterion for Prediction Markets

For a trade with market price p and estimated true probability p_true:

**Buy YES (when p_true > p):**

```
f* = (p_true − p) / (1 − p) = edge / (1 − p)
```

**Derivation:** The Kelly criterion maximizes E[log(wealth)]. For a binary bet with win probability p_w and payoff ratio b (profit per dollar risked):

```
f* = (p_w × b − q) / b     where q = 1 − p_w

For buy YES: b = (1−p)/p, p_w = p_true
f* = (p_true × (1−p)/p − (1−p_true)) / ((1−p)/p)
   = (p_true(1−p) − (1−p_true)p) / (1−p)
   = (p_true − p) / (1 − p)
```

**Buy NO (when p_true < p):**

```
f* = (p − p_true) / p = edge_NO / p
```

**Derivation:** For buy NO: b = p/(1−p), p_w = 1 − p_true
```
f* = ((1−p_true) × p/(1−p) − p_true) / (p/(1−p))
   = ((1−p_true)p − p_true(1−p)) / p
   = (p − p_true) / p
```

### 4.2 Fractional Kelly

Full Kelly maximizes long-run geometric growth but produces large drawdowns. Fractional Kelly reduces both:

```
position_size = α × f* × bankroll

α = 1.00  →  Full Kelly (maximum growth, ~50% peak drawdowns)
α = 0.50  →  Half Kelly (75% of max growth rate, ~25% drawdowns)
α = 0.25  →  Quarter Kelly (50% of max growth rate, ~12% drawdowns)
```

The growth rate under fractional Kelly is:

```
g(α) = α × E[edge] − (α²/2) × Var[returns_per_unit_bet]
```

Growth rate is maximized at α = 1 (full Kelly) but decreases gracefully for α < 1.

### 4.3 Position Sizing at Each Capital Level

For each trade, the position size in dollars:

```
position_t = α × f*_t × bankroll_t

where f*_t = edge_t / (1 − p_market_t)   for buy YES
      f*_t = edge_t / p_market_t          for buy NO
```

**Example at each capital level (using avg edge = 31.7%, avg p_market = 0.332):**

| Capital | Full Kelly f* | Full Kelly Position | Half Kelly | Quarter Kelly |
|---|---|---|---|---|
| $75 | 47.5% | $35.60 | $17.80 | $8.90 |
| $1,000 | 47.5% | $474.85 | $237.43 | $118.71 |
| $10,000 | 47.5% | $4,748.50 | $2,374.25 | $1,187.13 |
| $100,000 | 47.5% | $47,485.03 | $23,742.51 | $11,871.26 |

Where f* = 0.317 / (1 − 0.332) = 0.4749.

**Important:** These are theoretical maximums. At larger capitals, market impact will significantly reduce effective edge (see Section 5).

### 4.4 Position Size Caps

Implement practical guardrails:

```
max_position = min(
    α × f* × bankroll,            # Kelly-derived size
    0.10 × bankroll,              # hard cap: 10% of bankroll per trade
    daily_volume × 0.02           # liquidity cap: 2% of daily volume
)
```

---

## 5. Market Impact Model

### 5.1 Square-Root Impact Model

```
slippage(Q) = s_base + k × √(Q / V)

Parameters:
    s_base = 0.005  (0.5% base bid-ask spread)
    k = 0.015       (impact coefficient, calibrated to Polymarket)
    Q = order size in dollars
    V = daily volume of the market in dollars
```

**Effective entry price:**

```
p_effective = p_market × (1 + slippage)      for buy YES
p_effective = (1 − p_market) × (1 + slippage) for buy NO
```

**Net return after impact (round-trip: entry + exit):**

```
return_net = return_gross − 2 × slippage(Q)
```

### 5.2 Impact at Scale

| Order Size Q | Volume V=$50K | Slippage | Round-Trip Cost |
|---|---|---|---|
| $2 | $50,000 | 0.51% | 1.02% |
| $100 | $50,000 | 0.57% | 1.13% |
| $1,000 | $50,000 | 0.71% | 1.43% |
| $5,000 | $50,000 | 0.97% | 1.95% |
| $10,000 | $50,000 | 1.21% | 2.42% |
| $25,000 | $50,000 | 1.56% | 3.12% |

### 5.3 Edge Erosion at Scale

Net edge after market impact:

```
edge_net = edge_gross − 2 × slippage(position_size)

At $2 positions:   edge_net = 31.7% − 1.0% = 30.7%  (minimal erosion)
At $5K positions:   edge_net = 31.7% − 1.9% = 29.8%  (modest erosion)
At $25K positions:  edge_net = 31.7% − 3.1% = 28.6%  (significant erosion)
```

**In the simulation:** Recompute Kelly fraction using edge_net rather than edge_gross:

```
f*_adjusted = edge_net / (1 − p_effective)
```

---

## 6. Risk Metrics

### 6.1 Probability of Ruin

**Analytical approximation (gambler's ruin for positive-edge strategy):**

```
P(ruin) ≈ exp(−2 × edge_avg × B_0 / avg_position_size)
```

For half-Kelly sizing with avg edge 31.7%:

| Starting Capital | Avg Position (Half-Kelly) | B_0 / Position | P(Ruin) Approx |
|---|---|---|---|
| $75 | $17.80 | 4.2 | ~7.1% |
| $1,000 | $237 | 4.2 | ~7.1% |
| $10,000 | $2,374 | 4.2 | ~7.1% |
| $100,000 | $23,743 | 4.2 | ~7.1% |

Note: With Kelly sizing, ruin probability is scale-invariant (depends only on Kelly fraction). The actual ruin probability from MC simulation will be lower because Kelly fractions adapt to edge per trade.

**From simulation:** P(ruin) = count(paths reaching $0) / 10,000.

### 6.2 Probability of Doubling

**Analytical approximation (random walk with drift):**

```
E[trades to double] ≈ B_0 / E[P&L_per_trade_at_scale]

At $10K with half-Kelly:
  avg_position ≈ $2,374
  avg_return ≈ 30% − slippage ≈ 28%
  avg_P&L_per_trade ≈ $665
  E[trades_to_double] ≈ 10,000 / 665 ≈ 15 trades

At 5 trades/day → roughly 3 days to double (at half-Kelly!)
```

**From simulation:** P(double by T) = count(paths where max(wealth) ≥ 2 × B_0 by time T) / 10,000.

### 6.3 Maximum Drawdown Distribution

Compute from MC paths:

```
For each path i:
    DD_max_i = max over all t of: (peak_up_to_t − wealth_t) / peak_up_to_t

Across N_sim paths:
    E[DD_max] = mean(DD_max_i)
    DD_max_5th = percentile(DD_max_i, 5)     # best case
    DD_max_50th = percentile(DD_max_i, 50)    # typical
    DD_max_95th = percentile(DD_max_i, 95)    # worst case
```

### 6.4 Sharpe Ratio

**Per-trade statistics:**

```
E[R] = $0.60 per $2 = 0.30 (30% return)
Var[R] = E[R²] − (E[R])²
E[R²] = 0.649 × (1.0)² + 0.351 × (−1.0)² = 1.0
    (returns are +100% or −100% on the position)
Var[R] = 1.0 − 0.09 = 0.91
SD[R] = 0.954

Per-trade Sharpe = 0.30 / 0.954 = 0.314
```

**Annualized Sharpe (5 trades/day, 365 days = 1,825 trades):**

```
SR_annual = SR_trade × √(1825) = 0.314 × 42.72 = 13.4
```

This is exceptionally high because the strategy has a 30% average return per trade with binary outcomes. In practice, the Sharpe should be computed from daily P&L (which aggregates 5 trades):

```
E[daily_return] = 5 × E[trade_return] = 5 × 0.30 = 1.50 (150% daily, impractical)
```

**Important nuance:** These returns are per *position* not per *portfolio*. The portfolio-level Sharpe depends on position sizing. At half-Kelly with 47.5% Kelly fraction:

```
Capital allocation per trade ≈ 23.7% of bankroll
E[portfolio_return_per_trade] = 0.237 × 0.30 = 7.1%
SD[portfolio_return_per_trade] = 0.237 × 0.954 = 22.6%

Per-trade SR_portfolio = 0.071 / 0.226 = 0.314  (same Sharpe, different scale)

Daily SR (5 trades): 0.314 × √5 = 0.702
Annual SR: 0.702 × √365 = 13.4
```

In the simulation, compute Sharpe directly from the daily portfolio return series.

### 6.5 Sortino Ratio

**Downside deviation (target return = 0):**

```
DD² = E[min(R, 0)²] = P(loss) × E[loss²]
    = 0.351 × 1.0 = 0.351
DD = 0.593

Per-trade Sortino = 0.30 / 0.593 = 0.506

Annualized Sortino = 0.506 × √1825 = 21.6
```

Again, compute from the simulated daily portfolio return series for the most accurate result.

### 6.6 Calmar Ratio

```
Calmar = CAGR / |Max Drawdown|

Compute from each MC path, then report median and percentiles.
```

---

## 7. Sensitivity Analysis

### 7.1 Parameter Perturbations

For each parameter, run the full 10,000-path MC simulation while holding all other parameters at baseline:

| # | Parameter | Baseline | Stress Values | What Breaks? |
|---|---|---|---|---|
| 1 | Win rate | 64.9% | 55%, 58%, 60%, 62%, 65%, 70% | At what win rate does expected P&L go negative? |
| 2 | Avg P&L | +$0.60 | $0.20, $0.30, $0.40, $0.50, $0.60, $0.80 | How sensitive is doubling probability? |
| 3 | Trades/day | 5 | 1, 2, 3, 5, 8, 10 | Time-to-double and drawdown impact |
| 4 | Edge mean | 31.7% | 15%, 20%, 25%, 30%, 35%, 40% | Kelly fraction and position size changes |
| 5 | Mkt impact k | 0.015 | 0, 0.005, 0.01, 0.02, 0.03, 0.05 | At what k does edge disappear? |

### 7.2 Break-Even Analysis

**Minimum win rate to cover costs (zero expected P&L):**

With avg win = avg loss = $2:

```
p_win × $2 − (1 − p_win) × $2 = transaction_cost
(2 × p_win − 1) × $2 = cost

If cost = 2 × slippage × position = 2 × 0.005 × $2 = $0.02:
  p_min = (1 + 0.02/2) / 2 = 0.505 → 50.5%

If cost = 2 × 0.02 × $2 = $0.08 (at scale):
  p_min = (1 + 0.08/2) / 2 = 0.52 → 52%
```

The strategy has a large buffer above break-even (64.9% vs ~51%).

### 7.3 Scenario Grid

**What if win rate is 55% instead of 65%?**

```
E[P&L] = 0.55 × $2 − 0.45 × $2 = $0.20 (was $0.60)
Return drops from 30% to 10%
Kelly fraction drops proportionally
Time-to-double roughly triples
```

**What if avg P&L drops to $0.30?**

```
Implies either win rate dropped to ~57.5% or payoff structure changed
Kelly fraction and growth rate approximately halve
```

**What if only 3 trades/day?**

```
Annual trades: 3 × 365 = 1,095 (was 1,825)
Time-to-double: ~1.67× longer
Annual Sharpe: decreases by factor of √(3/5) = 0.775
Drawdown distribution: slightly wider (less diversification per day)
```

### 7.4 Tornado Diagram

Rank parameters by their elasticity (% change in final wealth per % change in parameter):

```
Typically:
  1. Win rate         (highest sensitivity — shifts mean outcome)
  2. Avg P&L / edge   (directly scales growth rate)
  3. Trades per day   (√n effect on convergence)
  4. Kelly fraction α (diminishing returns beyond half-Kelly)
  5. Market impact k  (erosion matters mostly at large scale)
  6. Starting capital (no effect on % returns, only $ scale)
```

---

## 8. Investor Scenarios

### 8.1 Setup: $10K Invested March 10

**Parameters:**

```
B_0 = $10,000
Entry date = March 10 (Day 0)
Kelly multiplier α = 0.50 (half-Kelly, recommended)
Trades per day = 5
Evaluation horizons: 3 months (≈456 trades), 6 months (≈912), 12 months (≈1,825)
```

### 8.2 Expected Value Calculation

**Per trade (at half-Kelly):**

```
avg_kelly_fraction = 0.317 / (1 − 0.332) = 0.4749
position_per_trade = 0.50 × 0.4749 × bankroll ≈ 23.7% of bankroll
E[return_on_bankroll_per_trade] = 0.237 × 0.30 = 7.12%
```

**Compound growth (geometric):**

```
g = E[ln(1 + r_trade)]
  ≈ E[r] − Var[r]/2
  = 0.0712 − (0.237² × 0.91)/2
  = 0.0712 − 0.0256
  = 0.0456 per trade (4.56% log-growth per trade)

After n trades:
  E[wealth] = B_0 × exp(g × n)
```

| Horizon | Trades | E[Wealth] (geometric) | E[Total Return] |
|---|---|---|---|
| 3 months | 456 | $10K × exp(0.0456 × 456) = enormous | >1000× |
| 6 months | 912 | even larger | >10^6× |
| 12 months | 1,825 | astronomical | >10^12× |

**Reality check:** These numbers assume constant edge and unlimited liquidity. In practice, the edge will degrade, liquidity will cap position sizes, and the market will adapt. The simulation should cap growth by applying realistic constraints.

### 8.3 Realistic Constraints for Investor Scenario

```
1. Position cap: min(Kelly_position, $500)  → limits growth at larger portfolios
2. Market impact: apply Section 5 model
3. Edge decay: assume edge degrades 1-2% per month as markets become efficient
4. Opportunity cap: not all 5 slots per day may have qualifying trades
```

**With position cap of $500:**

```
Once bankroll > $500 / 0.237 ≈ $2,110, position is capped
E[P&L per trade at cap] = $500 × 0.30 = $150
E[daily P&L] = 5 × $150 = $750

Growth becomes linear after bankroll >> cap threshold:
  At 3 months: $10K + 91 days × $750/day ≈ $78,250
  At 6 months: $10K + 182 × $750 ≈ $146,500
  At 12 months: $10K + 365 × $750 ≈ $283,750
```

### 8.4 Confidence Intervals (from MC Simulation)

Run the 10,000 paths with realistic constraints and report:

```
┌──────────────────────────────────────────────────────────────┐
│ INVESTOR SCENARIO: $10K on March 10                          │
│ Position sizing: Half-Kelly, capped at $500/trade            │
│ Trades: 5/day, 365 days                                     │
├──────────────────────────────────────────────────────────────┤
│ Horizon        Median      5th %ile    95th %ile    P(loss)  │
│ 3 months       $___        $___        $___         ___%     │
│ 6 months       $___        $___        $___         ___%     │
│ 12 months      $___        $___        $___         ___%     │
├──────────────────────────────────────────────────────────────┤
│ P(negative return at 3mo):  __%                              │
│ P(negative return at 6mo):  __%                              │
│ P(negative return at 12mo): __%                              │
├──────────────────────────────────────────────────────────────┤
│ Monthly Return Distribution:                                 │
│   Mean monthly return:       $___  (__%)                     │
│   Median monthly return:     $___  (__%)                     │
│   Std dev of monthly return: $___  (__%)                     │
│   Worst month (5th %ile):    $___  (__%)                     │
│   Best month (95th %ile):    $___  (__%)                     │
└──────────────────────────────────────────────────────────────┘
```

### 8.5 Monthly Return Distribution

For each MC path, group daily returns into monthly buckets and compute the distribution of monthly returns across all paths and all months.

```
For each path i, for each month m:
    monthly_return_{i,m} = (wealth_end_of_month − wealth_start_of_month) / wealth_start_of_month

Distribution across all (i, m) pairs gives monthly return distribution.
```

---

## 9. Capital Scaling Comparison

### 9.1 Simulation Grid

| Starting Capital | Kelly: Full | Kelly: Half | Kelly: Quarter |
|---|---|---|---|
| $75 | Sim A1 | Sim A2 | Sim A3 |
| $1,000 | Sim B1 | Sim B2 | Sim B3 |
| $10,000 | Sim C1 | Sim C2 | Sim C3 |
| $100,000 | Sim D1 | Sim D2 | Sim D3 |

For each cell, report: median final wealth, P(ruin), max drawdown (median and 95th percentile), Sharpe, and P(doubling at 3/6/12 months).

### 9.2 Market Impact at Scale

At $100K starting capital with half-Kelly, average position ≈ $23,700. Assuming $50K average daily volume per market:

```
slippage = 0.005 + 0.015 × √(23700/50000) = 0.005 + 0.015 × 0.688 = 1.53%
Round-trip cost: 3.06%
Edge erosion: 31.7% − 3.1% = 28.6% net edge

Still profitable, but growth rate reduced by ~10%.
```

At very large scale ($100K positions), edge may erode entirely — this is the capacity constraint of the strategy.

### 9.3 Strategy Capacity Estimate

The maximum deployable capital is where net edge approaches zero:

```
edge_net = edge_gross − 2 × (s_base + k × √(Q/V))

Set edge_net = 0:
0.317 = 2 × (0.005 + 0.015 × √(Q/50000))
0.1535 = 0.015 × √(Q/50000)
√(Q/50000) = 10.23
Q/50000 = 104.7
Q = $5.23M per trade
```

At half-Kelly (23.7% of bankroll), this implies max bankroll ≈ $22M. However, this assumes constant $50K volume. Many Polymarket markets have lower volume, so practical capacity is likely $1-5M.

---

## 10. Implementation Checklist

When implementing in Python, the simulation should:

1. **Trade generator function** — draws (edge, direction, market_price, win_prob, payoffs) from parameterized distributions, validated against backtest moments
2. **Kelly position sizer** — computes f* per trade, applies fractional multiplier and caps
3. **Market impact function** — adjusts entry/exit prices based on order size and assumed volume
4. **Path simulator** — loops through trades, tracks wealth, drawdown, and ruin
5. **Metrics aggregator** — computes all risk metrics across simulation paths
6. **Sensitivity runner** — sweeps each parameter independently, stores results for tornado plot
7. **Investor scenario module** — runs specific investor parameters with realistic constraints
8. **Visualization** — fan charts for wealth paths, histograms for drawdown/return distributions, tornado diagrams for sensitivity

**Recommended libraries:** NumPy (vectorized simulation), SciPy (distributions), Matplotlib/Plotly (visualization), Pandas (metrics tables).

---

## 11. Formula Quick Reference

| Formula | Expression |
|---|---|
| Trade payoff (YES win) | 2(1 − p)/p |
| Trade payoff (NO win) | 2p/(1 − p) |
| Kelly (buy YES) | f* = edge / (1 − p_market) |
| Kelly (buy NO) | f* = edge / p_market |
| Market impact | slippage = 0.005 + 0.015 × √(Q/V) |
| Sharpe (annualized) | SR_daily × √365 |
| Sortino | E[R] / √(E[min(R,0)²]) |
| P(ruin) approx | exp(−2 × edge × B_0/position) |
| Break-even win rate | (1 + cost/$2) / 2 |
| Strategy capacity | Q where edge = 2 × slippage(Q) |
