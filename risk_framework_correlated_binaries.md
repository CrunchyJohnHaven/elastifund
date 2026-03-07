# Risk Framework: Correlated Binary Markets, Small Bankroll

---

## 0. Notation & Setup

| Symbol | Meaning |
|--------|---------|
| `B` | Current bankroll (mark-to-market) |
| `B₀` | Bankroll at start of day / session |
| `p̂ᵢ` | Estimated true probability for market *i* |
| `mᵢ` | Market price (implied probability) for market *i* |
| `eᵢ = p̂ᵢ − mᵢ` | Edge on market *i* |
| `σᵢ` | Uncertainty in `p̂ᵢ` (model standard error) |
| `ρᵢⱼ` | Estimated pairwise correlation between outcomes *i*, *j* |
| `Cₖ` | Category cluster *k* (set of market indices) |
| `f*ᵢ` | Raw Kelly fraction for market *i* |
| `fᵢ` | Final position size as fraction of bankroll |

A "binary market" pays 1 if the outcome occurs, 0 otherwise. You buy at price `mᵢ` or sell (short) at `1 − mᵢ`. Profit on a correct long: `1 − mᵢ`. Loss on a wrong long: `mᵢ`.

---

## 1. Position Sizing Policy

### 1.1 Raw Kelly for a Single Binary

For a binary with estimated probability `p̂` and market price `m`:

```
f* = (p̂ − m) / (1 − m)       if going long  (p̂ > m)
f* = (m − p̂) / m              if going short (p̂ < m)
```

This is the edge divided by the odds. It tells you the bankroll fraction that maximises log-growth *if your estimate is exactly right*—which it never is.

### 1.2 Fractional Kelly with Uncertainty Shrinkage

Small bankrolls cannot survive the variance that full Kelly produces. Apply two layers of reduction:

**Layer 1 — Uncertainty shrinkage.** Penalise the edge proportional to estimation uncertainty:

```
adjusted_edge = max(0, |eᵢ| − λ · σᵢ)
```

where `λ` is a conservatism parameter (recommended: `λ = 1.0` to start; raise toward 2.0 in low-data regimes). If the adjusted edge is zero, skip the market.

Recompute Kelly using `adjusted_edge` in place of the raw edge:

```
f_shrunk = adjusted_edge / odds
```

where `odds = (1 − mᵢ)` for longs, `mᵢ` for shorts.

**Layer 2 — Fractional Kelly multiplier.**

```
fᵢ = κ · f_shrunk
```

Use `κ = 0.25` as default for a small bankroll. This alone cuts geometric growth by only ~6% relative to full Kelly but cuts variance by ~75%.

### 1.3 Per-Market Caps

Even after shrinkage, hard-cap every position:

| Constraint | Value | Rationale |
|---|---|---|
| Max single position | `0.05 · B` (5%) | Survival: no single wrong answer kills you |
| Min position | Ignore if `fᵢ · B < min_tick` | Don't pay fees on dust |
| Max positions open | 20 | Attention budget; raise only with automation |

```
fᵢ = min(fᵢ, 0.05)
```

### 1.4 Summary: Sizing Pipeline

```
for each market i:
    compute p̂ᵢ, σᵢ, mᵢ
    eᵢ = |p̂ᵢ − mᵢ|
    adj_eᵢ = max(0, eᵢ − λ · σᵢ)
    if adj_eᵢ == 0: skip
    odds = (1 − mᵢ) if long else mᵢ
    f_kelly = adj_eᵢ / odds
    fᵢ = min(κ · f_kelly, 0.05)
    sizeᵢ = fᵢ · B
```

---

## 2. Correlation Handling

Correlation is the main way a small bankroll dies. Ten "independent" positions that are actually driven by the same event can all lose simultaneously.

### 2.1 Category Cluster Caps

Group markets into clusters by causal driver. Examples:

| Cluster | Markets |
|---|---|
| US Election | President winner, Senate control, swing states, turnout bands |
| Fed Policy | Rate decision, dot plot median, press conference sentiment |
| Geopolitical | Conflict escalation, sanctions, oil price bands |
| Single Sport Event | Spread, total, player props for the same game |

**Rule: total exposure to any single cluster must not exceed `cluster_cap`.**

```
cluster_cap = 0.15 · B      # 15% of bankroll
```

Enforcement:

```
for each cluster k:
    cluster_exposure = sum(|sizeᵢ| for i in Cₖ)
    if cluster_exposure > cluster_cap:
        scale = cluster_cap / cluster_exposure
        for i in Cₖ:
            sizeᵢ *= scale
```

Scale down proportionally; don't drop positions entirely (you still want the diversification within the cluster if the individual edges are real).

### 2.2 Event-Based Exposure Aggregation

Some correlations cross clusters. A government shutdown could hit both "Fed policy" and "legislation" markets. For these, define **event scenarios** and compute aggregate exposure:

```
scenario: "Government shutdown occurs"
affected_markets: [m3, m7, m12, m19]
direction_if_scenario: [lose, lose, win, lose]
net_loss_if_scenario = sum of losses on the losing side − gains on winning side
```

**Rule: no single scenario's net loss may exceed `scenario_cap`.**

```
scenario_cap = 0.10 · B     # 10% of bankroll
```

If breached, scale down all positions in that scenario proportionally.

### 2.3 Correlation-Adjusted Kelly (Optional, More Rigorous)

If you have a full correlation matrix `Ρ`, the multivariate Kelly optimal fractions solve:

```
f = κ · Σ⁻¹ · e
```

where `Σ` is the covariance matrix of market outcomes and `e` is the vector of edges. In practice this is fragile—`Σ` is estimated with huge error for binary markets—so use it only as a sanity check against the cluster/scenario caps, not as the primary sizer.

---

## 3. Drawdown Controls

### 3.1 Daily Loss Limit

```
daily_loss_limit = 0.07 · B₀     # 7% of start-of-day bankroll
```

When cumulative realised + unrealised P&L for the day hits `−daily_loss_limit`:

1. **Close** all open positions (or set them to "close only").
2. **Block** new entries until next session.
3. **Log** the event for post-mortem.

Why 7%: aggressive enough to let you trade through normal variance, conservative enough that three consecutive max-loss days (~19% drawdown) triggers the hard stop below.

### 3.2 Max Drawdown Stop

Track the high-water mark `HWM = max(B over all time)`.

```
max_drawdown_pct = (HWM − B) / HWM
```

| Drawdown | Action |
|---|---|
| 15% | Halve all position sizes (`κ → κ/2`) |
| 25% | Halt all trading. Full model review before resuming. |

After a halt at 25%, do not resume until you have:

- Re-estimated all `p̂ᵢ` on fresh data.
- Verified that the sizing engine is computing correctly.
- Optionally reduced `κ` permanently (e.g., from 0.25 to 0.15).

### 3.3 Ratcheting Bankroll Reference

To avoid the trap where a big win inflates your sizing into a subsequent loss:

```
effective_B = min(B, SMA_5d(B))
```

Use a 5-day simple moving average of bankroll as the sizing base. This smooths out spikes from clustered resolutions.

---

## 4. Stress Tests

Run these before going live and weekly thereafter.

### 4.1 Correlated Loss Scenario

**Setup:** Take your current portfolio. Assume every market in the largest cluster resolves against you simultaneously.

**Metric:** What fraction of bankroll is lost?

```
correlated_loss = sum(sizeᵢ for i in largest_cluster where position loses)
```

**Pass condition:** `correlated_loss / B ≤ 0.15`. If it fails, tighten `cluster_cap`.

**Variant:** Run for *all* clusters, not just the largest. Also run for every defined event scenario.

### 4.2 Liquidity Vanishes

**Setup:** Assume you need to exit all positions but bid-ask spreads widen to 3× normal (or the book thins so you can only exit at 5% worse than mid).

```
slippage_cost = sum(0.05 · |sizeᵢ| for all i)
exit_loss = slippage_cost + sum(unrealised_lossᵢ)
```

**Pass condition:** `exit_loss / B ≤ 0.20`. If it fails, reduce total gross exposure.

**Implementation note:** Track average spread on each market. If a market's spread is consistently > 8%, treat it as illiquid and apply a 50% sizing penalty (`fᵢ *= 0.5`).

### 4.3 Resolution Delay / Disputes

**Setup:** Assume that your three largest positions (by dollar size) are frozen for 30 days due to resolution disputes. Capital is locked; you cannot trade with it.

```
locked_capital = sum of 3 largest |sizeᵢ|
available_B = B − locked_capital
```

**Pass condition:** `available_B` is enough to continue trading the remaining portfolio at reduced size without breaching any caps. Specifically, `available_B / B ≥ 0.50`.

**Mitigation:** If you fail, cap any single position at `0.03 · B` instead of `0.05 · B`, and limit total gross exposure to `0.60 · B` so that a 3-position freeze always leaves enough free capital.

### 4.4 Combined Worst Case

Run scenarios 4.1 + 4.2 together: the biggest cluster goes against you *and* spreads blow out on exit for the rest. This is the "everything breaks" scenario.

**Pass condition:** Total loss ≤ 30% of bankroll. If it fails, you are over-leveraged for your bankroll size.

---

## 5. Implementation Notes

### 5.1 What the Sizing Engine Must Compute

Every time you consider a new trade or rebalance:

```python
# INPUTS (per market)
p_hat: float          # model probability
sigma: float          # std error of p_hat
market_price: float   # current market price
cluster_id: str       # which cluster this market belongs to
scenario_ids: list    # which event scenarios it participates in
direction: str        # "long" or "short"

# INPUTS (global)
B: float              # current bankroll (mark-to-market)
B_sma: float          # 5-day SMA of bankroll
HWM: float            # high-water mark
daily_pnl: float      # cumulative P&L today
kappa: float          # fractional Kelly multiplier (default 0.25)
lam: float            # uncertainty penalty (default 1.0)

# PIPELINE
effective_B = min(B, B_sma)

# Step 1: per-market sizing
for each market i:
    edge = abs(p_hat_i - market_price_i)
    adj_edge = max(0, edge - lam * sigma_i)
    if adj_edge == 0: skip
    odds = (1 - market_price_i) if long else market_price_i
    f_kelly = adj_edge / odds
    f_i = min(kappa * f_kelly, 0.05)
    size_i = f_i * effective_B

# Step 2: cluster caps
for each cluster k:
    total = sum(size_i for i in cluster_k)
    if total > 0.15 * effective_B:
        scale = (0.15 * effective_B) / total
        for i in cluster_k: size_i *= scale

# Step 3: scenario caps
for each scenario s:
    net_loss = compute_scenario_loss(s, sizes, directions)
    if net_loss > 0.10 * effective_B:
        scale = (0.10 * effective_B) / net_loss
        for i in scenario_s: size_i *= scale

# Step 4: drawdown adjustments
dd = (HWM - B) / HWM
if dd > 0.25: HALT
elif dd > 0.15: kappa *= 0.5  # already applied above, but re-check

# Step 5: daily loss gate
if daily_pnl <= -0.07 * B_start_of_day: HALT_FOR_DAY

# OUTPUT
final_sizes: dict     # market_id -> dollar size
```

### 5.2 Data Requirements

| Data | Source | Frequency |
|---|---|---|
| `p̂ᵢ`, `σᵢ` | Your model | Per-trade or on schedule |
| `mᵢ`, spreads | Exchange API | Real-time or polling |
| Cluster assignments | Manual + heuristics | Updated when new markets open |
| Scenario definitions | Manual | Updated per event cycle |
| `B`, P&L | Portfolio tracker | Real-time |

### 5.3 Logging

Log every sizing decision:

```
timestamp | market_id | p_hat | sigma | market_price | raw_kelly
  | adj_edge | pre_cap_size | post_cap_size | cluster | scenarios
  | bankroll | daily_pnl | drawdown_pct
```

This log is your primary tool for debugging bad runs and recalibrating `λ` and `κ`.

### 5.4 Parameter Tuning Schedule

| Parameter | Starting Value | When to Adjust |
|---|---|---|
| `κ` (Kelly fraction) | 0.25 | Lower after drawdown; raise after 3+ months of profitable, calibrated trading |
| `λ` (uncertainty penalty) | 1.0 | Raise if model is overconfident (calibration check); lower if edges are consistently real |
| `cluster_cap` | 15% | Lower if clusters prove more correlated than expected |
| `scenario_cap` | 10% | Lower if tail scenarios are hitting more often than modelled |
| `daily_loss_limit` | 7% | Lower if daily variance is lower than expected (tighter control) |

### 5.5 Calibration Check (Run Monthly)

For each probability bucket (e.g., `p̂ ∈ [0.6, 0.7)`), compute the actual resolution rate. If your 65% predictions resolve YES only 50% of the time, your model is overconfident and you should increase `λ` or apply a calibration correction to `p̂` before feeding it into the sizer.

---

## Appendix: Quick-Start Defaults

For a bankroll of $1,000 on a platform like Polymarket or Kalshi:

| Parameter | Value |
|---|---|
| `κ` | 0.25 |
| `λ` | 1.0 |
| Max single position | $50 (5%) |
| Cluster cap | $150 (15%) |
| Scenario cap | $100 (10%) |
| Daily loss limit | $70 (7%) |
| Drawdown half-size | at 15% DD |
| Drawdown halt | at 25% DD |
| Min edge after shrinkage | 3% (below this, don't trade) |

These are conservative. The goal is to survive the first 100 trades and collect enough data to calibrate your model—then you can tune up.
