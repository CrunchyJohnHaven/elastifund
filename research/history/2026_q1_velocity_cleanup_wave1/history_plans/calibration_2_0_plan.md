# Calibration 2.0 Plan

**Version:** 1.0.0
**Date:** 2026-03-05
**Purpose:** Upgrade from static temperature scaling to a live, drift-aware calibration system. Engineer-ready spec — Claude Code can implement drift monitoring without interpretation gaps.

---

## 1. Current State (Calibration 1.0)

### What We Have

The current calibration layer in `claude_analyzer.py` uses a static temperature-scaling lookup table derived from the 532-market backtest:

| Claude Estimate Bin | Actual YES Rate | Calibration Error |
|---------------------|-----------------|-------------------|
| 0–10% | 15.7% | +10.7% |
| 10–20% | 12.0% | -3.0% |
| 20–30% | 22.0% | -3.0% |
| 30–40% | 62.5% | +27.5% |
| 40–50% | 41.7% | -3.3% |
| 50–60% | 46.6% | -8.4% |
| 60–70% | 45.5% | -19.5% |
| 70–80% | 52.8% | -22.2% |
| 80–90% | 63.2% | -21.8% |
| 90–100% | 63.2% | -31.8% |

### Problems with 1.0

1. **Static table — no adaptation.** The lookup table was fit once on 532 markets. If Claude's behavior changes (model updates, different market mix), the table is wrong.
2. **Bin-level granularity only.** A 61% estimate and a 69% estimate get the same correction. No interpolation.
3. **No category awareness.** Claude may be well-calibrated for politics but poorly calibrated for economics. A single table ignores this.
4. **Small-sample bins.** The 30–40% bin has only 16 markets (62.5% actual rate, +27.5% error). The 60–70% bin has only 11. These are unreliable.
5. **Backtest overfit risk.** Temperature scaling on the same data used to evaluate P&L creates circular reasoning. Out-of-sample performance is unknown.
6. **No drift detection.** If calibration degrades over time, nothing alerts us.

---

## 2. Calibration Method Evaluation

### Option A: Temperature Scaling (Current)

**How it works:** Single parameter T scales logits: `calibrated = σ(logit(p) / T)`. Optimized by minimizing NLL on calibration set.

**Pros:** Simple, one parameter, low overfit risk, works well with small datasets.
**Cons:** Assumes miscalibration is uniform across the probability range (it isn't — Claude is well-calibrated at 10–30% but terrible at 60–90%). Cannot model non-monotonic errors.
**Verdict:** Insufficient for our error pattern.

### Option B: Platt Scaling

**How it works:** Two parameters (a, b): `calibrated = σ(a × logit(p) + b)`. Logistic regression on calibration set.

**Pros:** Two parameters capture both scale (overconfidence) and shift (systematic bias). Still low overfit risk. Used by Bridgewater's AIA Forecaster.
**Cons:** Still assumes a smooth, monotonic transformation. Cannot model the 30–40% bin anomaly (+27.5% error).
**Verdict:** Good upgrade over temperature scaling. Recommended as the primary method.

### Option C: Isotonic Regression

**How it works:** Non-parametric monotonic mapping. Fits a step function that maps predicted → actual probabilities while maintaining monotonicity.

**Pros:** Can model any monotonic miscalibration pattern. No functional form assumptions. Handles the non-linear error pattern in our data.
**Cons:** Overfits with small datasets (our 532 markets → ~50 per bin is borderline). Requires more data than Platt. Step-function output is discontinuous.
**Verdict:** Use as a secondary check / ensemble member, not primary. Needs >1,000 resolved trades to be reliable standalone.

### Option D: Histogram Binning (Enhanced Version of Current)

**How it works:** Divide predictions into bins, map each bin to the empirical frequency of positives in that bin. Enhanced: use variable-width bins (equal-count instead of equal-width) and interpolate between bin centers.

**Pros:** Simple, interpretable, handles any pattern.
**Cons:** Requires many samples per bin. No interpolation without engineering it in. Discontinuous at bin edges.
**Verdict:** Use as a fallback when Platt fails validation.

### Recommendation: Platt Scaling (Primary) + Isotonic (Validation)

**Implementation:**
1. Platt scaling as the production calibrator (2 parameters, robust to small data)
2. Isotonic regression as an offline validation check (run weekly, compare to Platt)
3. If Platt and isotonic disagree by >5% on any bin, flag for manual review
4. Once we have >1,000 resolved live trades, consider switching to isotonic as primary

---

## 3. Avoiding Backtest Overfit

### The Problem

Currently, calibration is fit on the same 532 markets used to compute P&L. This inflates apparent performance because the calibration table "knows" the outcomes.

### Solution: Temporal Cross-Validation

```
Timeline:  [---Train---][---Val---][---Test---]
           Markets 1-266  267-399   400-532
           (50%)          (25%)     (25%)
```

**Protocol:**
1. Sort all resolved markets by resolution date (chronological)
2. Train calibration on first 50% (earliest markets)
3. Validate (tune hyperparameters) on next 25%
4. Report final performance on last 25% (never touched during fitting)
5. For production, retrain on Train+Val (75%) and deploy

**Rolling recalibration (live):**
- Every 50 new resolved trades, refit Platt parameters using all historical data
- Compare new Platt parameters to previous — if shift > 0.1 in either parameter, alert
- Never use unresolved trades for calibration fitting

### Implementation Guard

```python
class CalibrationManager:
    def __init__(self):
        self.platt_a = None  # logit scale
        self.platt_b = None  # logit shift
        self.fit_date = None
        self.fit_n_trades = 0
        self.fit_markets = set()  # track which markets were used

    def fit(self, predictions: list[float], outcomes: list[int]):
        """Fit Platt scaling. predictions = Claude raw estimates, outcomes = 0/1."""
        from sklearn.linear_model import LogisticRegression
        import numpy as np

        logits = np.log(np.array(predictions) / (1 - np.array(predictions)))
        logits = logits.reshape(-1, 1)

        lr = LogisticRegression(C=1.0, solver='lbfgs')
        lr.fit(logits, outcomes)

        self.platt_a = lr.coef_[0][0]
        self.platt_b = lr.intercept_[0]
        self.fit_date = datetime.utcnow()
        self.fit_n_trades = len(predictions)

    def calibrate(self, raw_estimate: float) -> float:
        """Apply Platt scaling to a raw Claude estimate."""
        import numpy as np
        logit = np.log(raw_estimate / (1 - raw_estimate))
        calibrated_logit = self.platt_a * logit + self.platt_b
        return 1 / (1 + np.exp(-calibrated_logit))
```

---

## 4. Live Calibration Drift Monitoring

### 4.1 Metrics to Track

| Metric | Definition | Window | Alert Threshold |
|--------|-----------|--------|----------------|
| **ECE (Expected Calibration Error)** | Mean absolute difference between predicted probability and actual frequency, across bins | Rolling 50 trades | > 0.10 = warn, > 0.15 = throttle |
| **MCE (Maximum Calibration Error)** | Max bin-level calibration error | Rolling 50 trades | > 0.25 = flag specific bin |
| **Brier Score** | Mean squared error of probability estimates | Rolling 50 trades | > 0.240 = warn, > 0.250 = critical |
| **Reliability Curve R²** | R² of linear fit to reliability diagram | Rolling 100 trades | < 0.70 = recalibrate |
| **Platt Parameter Drift** | |Δa| or |Δb| from last calibration fit | Per refit (every 50 trades) | Δ > 0.15 = refit, Δ > 0.30 = alert |
| **Overconfidence Index** | Mean(predicted - actual) for predictions > 0.60 | Rolling 50 trades | > 0.10 = throttle YES sizing |
| **Underconfidence Index** | Mean(actual - predicted) for predictions < 0.40 | Rolling 50 trades | > 0.10 = increase NO sizing |

### 4.2 ECE Computation

```python
def compute_ece(predictions: list[float], outcomes: list[int], n_bins: int = 10) -> float:
    """Expected Calibration Error with equal-width bins."""
    import numpy as np

    predictions = np.array(predictions)
    outcomes = np.array(outcomes)
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0

    for i in range(n_bins):
        mask = (predictions >= bin_edges[i]) & (predictions < bin_edges[i + 1])
        if mask.sum() == 0:
            continue
        bin_accuracy = outcomes[mask].mean()
        bin_confidence = predictions[mask].mean()
        bin_weight = mask.sum() / len(predictions)
        ece += bin_weight * abs(bin_accuracy - bin_confidence)

    return ece
```

### 4.3 Reliability Curve

```python
def compute_reliability_curve(predictions: list[float], outcomes: list[int], n_bins: int = 10):
    """Returns bin_centers, bin_accuracies, bin_counts for plotting."""
    import numpy as np

    predictions = np.array(predictions)
    outcomes = np.array(outcomes)
    bin_edges = np.linspace(0, 1, n_bins + 1)

    centers, accuracies, counts = [], [], []
    for i in range(n_bins):
        mask = (predictions >= bin_edges[i]) & (predictions < bin_edges[i + 1])
        if mask.sum() < 3:  # minimum bin count
            continue
        centers.append(predictions[mask].mean())
        accuracies.append(outcomes[mask].mean())
        counts.append(mask.sum())

    return centers, accuracies, counts
```

### 4.4 Drift Detection Algorithm

```python
class DriftDetector:
    def __init__(self, warn_ece=0.10, critical_ece=0.15, warn_brier=0.240, critical_brier=0.250):
        self.warn_ece = warn_ece
        self.critical_ece = critical_ece
        self.warn_brier = warn_brier
        self.critical_brier = critical_brier
        self.history = []  # list of (prediction, outcome, timestamp, category)

    def add_resolved_trade(self, prediction: float, outcome: int, category: str):
        self.history.append({
            'prediction': prediction,
            'outcome': outcome,
            'timestamp': datetime.utcnow(),
            'category': category
        })

    def check_drift(self, window: int = 50) -> dict:
        """Check calibration drift on last `window` resolved trades."""
        recent = self.history[-window:]
        if len(recent) < 20:
            return {'status': 'insufficient_data', 'n': len(recent)}

        preds = [r['prediction'] for r in recent]
        outcomes = [r['outcome'] for r in recent]

        ece = compute_ece(preds, outcomes)
        brier = sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds)

        # Category-level drift
        categories = set(r['category'] for r in recent)
        cat_drift = {}
        for cat in categories:
            cat_recent = [r for r in recent if r['category'] == cat]
            if len(cat_recent) >= 10:
                cat_preds = [r['prediction'] for r in cat_recent]
                cat_outcomes = [r['outcome'] for r in cat_recent]
                cat_drift[cat] = {
                    'ece': compute_ece(cat_preds, cat_outcomes),
                    'brier': sum((p-o)**2 for p,o in zip(cat_preds, cat_outcomes)) / len(cat_preds),
                    'n': len(cat_recent)
                }

        # Determine action
        action = 'none'
        if ece > self.critical_ece or brier > self.critical_brier:
            action = 'throttle_sizes_50pct'
        elif ece > self.warn_ece or brier > self.warn_brier:
            action = 'warn_and_refit'

        return {
            'status': action,
            'ece': ece,
            'brier': brier,
            'n': len(recent),
            'category_drift': cat_drift,
            'recommendation': self._recommend(action, ece, brier, cat_drift)
        }

    def _recommend(self, action, ece, brier, cat_drift):
        if action == 'throttle_sizes_50pct':
            return (f"CRITICAL: ECE={ece:.3f}, Brier={brier:.3f}. "
                    f"Reduce all position sizes by 50% until recalibration. "
                    f"Refit Platt parameters immediately.")
        elif action == 'warn_and_refit':
            worst_cat = max(cat_drift, key=lambda c: cat_drift[c]['ece']) if cat_drift else 'N/A'
            return (f"WARNING: ECE={ece:.3f}, Brier={brier:.3f}. "
                    f"Schedule Platt refit. Worst category: {worst_cat}.")
        return "Calibration within normal range."
```

---

## 5. Auto-Throttle Rules

When drift is detected, the system should automatically reduce risk:

| Drift Level | Trigger | Position Size Action | Duration |
|-------------|---------|---------------------|----------|
| **Green** | ECE < 0.10 AND Brier < 0.240 | Full quarter-Kelly | — |
| **Yellow** | ECE 0.10–0.15 OR Brier 0.240–0.250 | Reduce to 60% of Kelly | Until next refit + 20 trades |
| **Red** | ECE > 0.15 OR Brier > 0.250 | Reduce to 30% of Kelly | Until refit + 50 trades pass Green |
| **Black** | ECE > 0.20 OR Brier > 0.260 | Halt all new trades | Manual review required |

**Category-level throttle:** If any individual category has ECE > 0.20, halt trading in that category regardless of overall ECE.

**Implementation in sizing.py:**

```python
def get_drift_multiplier(drift_status: dict) -> float:
    """Returns a multiplier [0, 1] to apply to Kelly sizing."""
    ece = drift_status.get('ece', 0)
    brier = drift_status.get('brier', 0)

    if ece > 0.20 or brier > 0.260:
        return 0.0  # halt
    elif ece > 0.15 or brier > 0.250:
        return 0.30
    elif ece > 0.10 or brier > 0.240:
        return 0.60
    return 1.0

def position_size_with_drift(bankroll, kelly_f, side, category, drift_status):
    """Enhanced position_size that incorporates drift throttling."""
    base_size = position_size(bankroll, kelly_f, side, category)
    drift_mult = get_drift_multiplier(drift_status)

    # Category-specific throttle
    cat_drift = drift_status.get('category_drift', {}).get(category, {})
    if cat_drift.get('ece', 0) > 0.20:
        return 0.0  # halt this category

    return base_size * drift_mult
```

---

## 6. Calibration Logging Schema

Minimal schema for logging all calibration inputs/outputs. Extends the `calibration_log` table from the Live Scorecard spec.

```sql
CREATE TABLE calibration_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fit_date TIMESTAMP NOT NULL,
    platt_a REAL NOT NULL,
    platt_b REAL NOT NULL,
    fit_n_trades INTEGER NOT NULL,
    train_ece REAL NOT NULL,
    val_ece REAL,
    train_brier REAL NOT NULL,
    val_brier REAL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Extends calibration_log (defined in live_scorecard_spec.md) with drift fields
-- Add these columns to calibration_log:
ALTER TABLE calibration_log ADD COLUMN drift_ece_at_signal REAL;
ALTER TABLE calibration_log ADD COLUMN drift_brier_at_signal REAL;
ALTER TABLE calibration_log ADD COLUMN drift_multiplier REAL DEFAULT 1.0;
ALTER TABLE calibration_log ADD COLUMN platt_a_at_signal REAL;
ALTER TABLE calibration_log ADD COLUMN platt_b_at_signal REAL;
```

### Logging Contract

Every trade signal must log:

```python
{
    "market_id": "0x...",
    "claude_raw_estimate": 0.82,         # Before any calibration
    "platt_a": 0.65,                     # Current Platt parameter
    "platt_b": -0.12,                    # Current Platt parameter
    "calibrated_estimate": 0.61,         # After Platt scaling
    "market_price": 0.75,               # At signal time
    "edge": -0.14,                       # calibrated - market (negative = BUY_NO)
    "side": "NO",
    "category": "politics",
    "drift_ece": 0.078,                  # Current rolling ECE
    "drift_brier": 0.231,               # Current rolling Brier
    "drift_multiplier": 1.0,            # Position size multiplier from drift
    "kelly_fraction": 0.087,            # Raw Kelly
    "position_size_usd": 4.35,          # After all adjustments
    "traded": true,
    "timestamp": "2026-03-05T14:23:00Z"
}
```

---

## 7. Recalibration Schedule

| Event | Action |
|-------|--------|
| Every 50 resolved trades | Refit Platt parameters using all resolved trades |
| Weekly (Sunday 00:00 UTC) | Generate reliability curve, compute ECE/Brier, log to `calibration_state` |
| Drift Yellow triggered | Immediate refit + alert to Telegram |
| Drift Red triggered | Immediate refit + throttle + Telegram alert |
| Monthly | Compare Platt vs isotonic regression offline. If isotonic outperforms by >0.02 ECE, consider switching. |
| Quarterly | Full review: temporal cross-validation on all data, assess if calibration approach needs fundamental change |

---

## 8. Migration Path (1.0 → 2.0)

**Step 1 (Day 1):** Create `calibration_log` and `calibration_state` tables. Start logging all signals (even if not yet using Platt).

**Step 2 (Day 2):** Fit initial Platt parameters on existing 532-market data using temporal cross-validation. Record baseline ECE/Brier.

**Step 3 (Day 3):** Replace static lookup table in `claude_analyzer.py` with Platt scaling. A/B test: log both old-table and new-Platt outputs for first 50 trades.

**Step 4 (Day 7):** Implement `DriftDetector` class. Wire into main trading loop. Start drift monitoring.

**Step 5 (Day 7):** Wire `get_drift_multiplier` into `sizing.py`. Auto-throttle now live.

**Step 6 (Day 14):** First reliability curve review. Confirm Platt outperforms static table.

**Step 7 (Ongoing):** Refit every 50 trades. Monitor drift. Quarterly review.

---

*This plan is complete. Claude Code can implement drift monitoring (Steps 1–5) directly from this document without interpretation gaps. All schemas, algorithms, thresholds, and code are specified.*
