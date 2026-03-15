# LLM Probability Calibration System for Prediction Markets

## 1. Recommended Calibration Approach

### Comparison

| Method | Mechanism | Pros | Cons |
|---|---|---|---|
| **Platt Scaling** | Fits logistic sigmoid: `p_cal = 1/(1+exp(-a*logit+b))` | Simple (2 params), fast, works well when raw scores are roughly sigmoidal | Assumes monotonic sigmoid shape; poor if LLM miscalibration is non-monotonic |
| **Temperature Scaling** | Single scalar: `p_cal = softmax(logit/T)` | 1 param, very low overfitting risk, standard in deep learning | Too rigid for LLMs whose errors vary across probability ranges |
| **Isotonic Regression** | Fits stepwise non-decreasing function via PAV algorithm | No shape assumptions, captures arbitrary miscalibration curves | Needs more data (~500+ resolved outcomes); can overfit with small bins |

### Recommendation: Isotonic Regression (primary) + Platt Scaling (fallback)

**Why isotonic is the right default for prediction markets:**

LLMs exhibit *non-uniform* miscalibration. They tend to be overconfident in the 70–95% range and underconfident near 50%. This pattern is not well-captured by a 2-parameter sigmoid. Isotonic regression fits the actual shape of miscalibration without assuming one.

**When to fall back to Platt:** If you have fewer than 300 resolved outcomes in a given question category, isotonic regression will overfit. Use Platt scaling until you accumulate enough data, then switch.

**Practical threshold rule:**
```
if n_resolved >= 500:
    use isotonic
elif n_resolved >= 100:
    use platt
else:
    use raw LLM output with a "uncalibrated" flag
```

---

## 2. Online + Offline Calibration Workflow

### Offline Pipeline (batch, runs daily or weekly)

```
┌─────────────┐    ┌──────────────┐    ┌───────────────┐    ┌──────────────┐
│ Resolved     │───▶│ Join with    │───▶│ Fit isotonic  │───▶│ Serialize    │
│ outcome log  │    │ raw LLM      │    │ or Platt on   │    │ calibrator   │
│              │    │ predictions  │    │ train split   │    │ to disk      │
└─────────────┘    └──────────────┘    └───────────────┘    └──────────────┘
                                              │
                                              ▼
                                       ┌───────────────┐
                                       │ Evaluate on    │
                                       │ held-out split │
                                       │ (→ Brier, ECE) │
                                       └───────────────┘
```

**Steps:**

1. **Extract** all `(raw_prob, outcome)` pairs from the log where `resolution_date <= now`.
2. **Split** by time: train on outcomes resolved before cutoff `T`, validate on outcomes resolved after `T`. Never random-split (see §3).
3. **Fit** `sklearn.isotonic.IsotonicRegression(out_of_bounds='clip')` on training set.
4. **Evaluate** on validation set. If calibration error degrades vs. previous model, keep the old one.
5. **Serialize** with `joblib.dump()`. Tag with `{fit_date, n_train, n_val, ece_val, brier_val}`.
6. **Deploy** by swapping the calibrator artifact in the inference service.

### Online Pipeline (per-request, at inference time)

```
┌────────────┐    ┌────────────┐    ┌────────────────┐    ┌──────────────┐
│ User query  │───▶│ LLM infer  │───▶│ Apply loaded   │───▶│ Return       │
│ (question)  │    │ raw_prob   │    │ calibrator     │    │ cal_prob +   │
│             │    │            │    │ cal(raw_prob)  │    │ metadata     │
└────────────┘    └────────────┘    └────────────────┘    └──────────────┘
                                                                 │
                                                                 ▼
                                                          ┌──────────────┐
                                                          │ Log to       │
                                                          │ prediction   │
                                                          │ store        │
                                                          └──────────────┘
```

**Steps:**

1. LLM produces `raw_prob` (e.g., 0.73).
2. Load current calibrator from cache (deserialize once, refresh on deploy).
3. `cal_prob = calibrator.predict([raw_prob])[0]`.
4. Clamp: `cal_prob = max(0.01, min(0.99, cal_prob))` — avoid 0/1 extremes.
5. Return `{cal_prob, raw_prob, calibrator_version, model_id}`.
6. Append full record to prediction log (see §4).

### Staleness Guard

Re-fit when any of these trigger:

- 7 days since last fit
- 200+ new resolved outcomes accumulated
- Rolling Brier score on last 100 predictions drifts >0.02 from validation baseline

---

## 3. Avoiding Leakage and Lookahead Bias

This is the most common failure mode in calibration systems. Every violation here makes your calibration look artificially good in backtest and breaks in production.

### Rule 1: Temporal splits only

Never use random train/test splits. Always split by resolution date.

```python
# CORRECT
train = df[df['resolution_date'] < cutoff]
val   = df[df['resolution_date'] >= cutoff]

# WRONG — leaks future calibration patterns into training
train, val = train_test_split(df, test_size=0.2, random_state=42)
```

### Rule 2: No outcome data at prediction time

The LLM prompt must never contain the resolved outcome of the question it is predicting. This sounds obvious, but it can leak in subtle ways:

- **News context contamination:** If you feed the LLM recent news as context, and that news contains the resolution, you have leakage. Fix: truncate context to `news_before <= question_open_date`.
- **Related question leakage:** If question A resolves and its outcome implies the answer to question B, and you include A's resolution in context for B, that's leakage. Fix: only include resolutions of questions in unrelated categories.
- **Model training data leakage:** If the LLM's training data includes the resolved outcomes (e.g., for historical events), the raw probabilities are already contaminated. Fix: only calibrate on questions whose resolution post-dates the LLM's training cutoff.

### Rule 3: Calibrator must not see its own validation data during fitting

```python
# CORRECT — fit only on train
calibrator.fit(train['raw_prob'], train['outcome'])
val_calibrated = calibrator.predict(val['raw_prob'])

# WRONG — fitting on all data, then "evaluating" on same data
calibrator.fit(df['raw_prob'], df['outcome'])
```

### Rule 4: Feature engineering cutoffs

If your calibration model uses features beyond `raw_prob` (e.g., question category, market volume, days to resolution), all features must be computable from information available at prediction time. No `days_until_resolution` (requires knowing resolution date), no `final_market_price`, etc.

### Checklist

```
[ ] Train/val split is strictly temporal
[ ] LLM prompt context is truncated to before question open date
[ ] No resolved-outcome text in prompt for open questions
[ ] Calibrator fit uses only training split
[ ] All features available at prediction time
[ ] LLM training cutoff predates question resolution dates
```

---

## 4. Training Data Logging Schema

Every prediction must be logged with enough detail to reconstruct the calibration dataset later.

### Schema

```json
{
  "prediction_id": "uuid-v4",
  "timestamp": "2026-03-05T14:22:00Z",
  "question_id": "polymarket-abc123",
  "question_text": "Will X happen by Y date?",
  "resolution_date": null,
  "outcome": null,

  "model_id": "claude-sonnet-4-5-20250929",
  "prompt_hash": "sha256:ab3f...d912",
  "prompt_template_version": "v2.3",

  "raw_prob": 0.73,
  "cal_prob": 0.68,
  "calibrator_version": "iso-2026-03-01-n1247",

  "features": {
    "category": "politics-us",
    "days_until_close": 45,
    "market_price_at_prediction": 0.65,
    "news_context_tokens": 2048,
    "prompt_pattern": "cot-numeric"
  },

  "metadata": {
    "latency_ms": 1200,
    "token_count": 350,
    "context_window_used": 0.15
  }
}
```

### Storage Rules

1. **Store prompts by reference, not inline.** Hash the full prompt and store the actual text in a separate content-addressed blob store. This keeps the log table small and queryable.

2. **Append-only log.** Never mutate prediction records. When an outcome resolves, write a separate resolution event:
   ```json
   {
     "event": "resolution",
     "question_id": "polymarket-abc123",
     "outcome": 1,
     "resolution_date": "2026-04-15T00:00:00Z",
     "resolution_source": "official"
   }
   ```
   Join at calibration-fit time.

3. **Partition by month.** Makes temporal splits trivial and keeps queries fast.

4. **Retain raw_prob forever.** You will re-calibrate many times; the raw model output is the immutable ground truth for your system.

### Minimal viable setup

For early-stage work, a single append-only JSONL file works:

```
predictions_2026_03.jsonl   # one JSON object per line
resolutions_2026_03.jsonl
```

Graduate to Postgres or BigQuery when you exceed ~100k records or need concurrent writers.

---

## 5. Test Harness Plan

### 5a. Reliability Diagram

The single most important visual diagnostic. Plots predicted probability (x-axis) vs. observed frequency (y-axis).

```python
import numpy as np
import matplotlib.pyplot as plt

def reliability_diagram(y_true, y_prob, n_bins=10, title="Reliability Diagram"):
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_centers = []
    observed_freq = []
    bin_counts = []

    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (y_prob >= lo) & (y_prob < hi)
        if mask.sum() == 0:
            continue
        bin_centers.append(y_prob[mask].mean())
        observed_freq.append(y_true[mask].mean())
        bin_counts.append(mask.sum())

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 8),
                                     gridspec_kw={'height_ratios': [3, 1]})
    ax1.plot([0, 1], [0, 1], 'k--', label='Perfect calibration')
    ax1.plot(bin_centers, observed_freq, 'o-', label='Model')
    ax1.set_xlabel('Predicted probability')
    ax1.set_ylabel('Observed frequency')
    ax1.set_title(title)
    ax1.legend()

    ax2.bar(bin_centers, bin_counts, width=1/n_bins, alpha=0.5)
    ax2.set_xlabel('Predicted probability')
    ax2.set_ylabel('Count')
    plt.tight_layout()
    return fig
```

**What to look for:** Deviations from the diagonal. A curve above the diagonal means the model is underconfident (says 60%, actually happens 75%). Below means overconfident.

### 5b. Brier Score

```python
def brier_score(y_true, y_prob):
    return np.mean((y_prob - y_true) ** 2)
```

**Interpretation:** 0 = perfect, 0.25 = coin flip baseline. For well-calibrated prediction market forecasts, aim for Brier < 0.20. Decompose into calibration + resolution + uncertainty for deeper diagnostics.

**Brier decomposition:**

```python
def brier_decomposition(y_true, y_prob, n_bins=10):
    bin_edges = np.linspace(0, 1, n_bins + 1)
    calibration = 0.0
    resolution = 0.0
    base_rate = y_true.mean()
    n = len(y_true)

    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (y_prob >= lo) & (y_prob < hi)
        n_k = mask.sum()
        if n_k == 0:
            continue
        avg_pred = y_prob[mask].mean()
        avg_outcome = y_true[mask].mean()
        calibration += n_k * (avg_pred - avg_outcome) ** 2
        resolution += n_k * (avg_outcome - base_rate) ** 2

    calibration /= n
    resolution /= n
    uncertainty = base_rate * (1 - base_rate)
    return {
        'calibration': calibration,   # lower is better
        'resolution': resolution,     # higher is better
        'uncertainty': uncertainty,
        'brier': calibration - resolution + uncertainty
    }
```

### 5c. Expected Calibration Error (ECE) by Bucket

```python
def expected_calibration_error(y_true, y_prob, n_bins=10):
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    bucket_errors = []

    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (y_prob >= lo) & (y_prob < hi)
        n_k = mask.sum()
        if n_k == 0:
            bucket_errors.append({
                'range': f'{lo:.1f}-{hi:.1f}', 'count': 0, 'error': None
            })
            continue
        avg_pred = y_prob[mask].mean()
        avg_outcome = y_true[mask].mean()
        error = abs(avg_pred - avg_outcome)
        ece += (n_k / n) * error
        bucket_errors.append({
            'range': f'{lo:.1f}-{hi:.1f}',
            'count': int(n_k),
            'avg_pred': round(avg_pred, 3),
            'avg_outcome': round(avg_outcome, 3),
            'error': round(error, 3)
        })

    return {'ece': round(ece, 4), 'buckets': bucket_errors}
```

### 5d. Full Test Harness Runner

```python
def run_calibration_eval(y_true, y_prob_raw, y_prob_cal, output_dir="eval_output"):
    """Run full evaluation suite comparing raw vs calibrated probabilities."""
    import os, json
    os.makedirs(output_dir, exist_ok=True)

    results = {}
    for label, probs in [("raw", y_prob_raw), ("calibrated", y_prob_cal)]:
        brier = brier_score(y_true, probs)
        decomp = brier_decomposition(y_true, probs)
        ece_result = expected_calibration_error(y_true, probs)
        fig = reliability_diagram(y_true, probs, title=f"Reliability: {label}")
        fig.savefig(f"{output_dir}/reliability_{label}.png", dpi=150)
        plt.close(fig)

        results[label] = {
            'brier': round(brier, 4),
            'decomposition': decomp,
            'ece': ece_result['ece'],
            'buckets': ece_result['buckets'],
            'n': len(y_true)
        }

    with open(f"{output_dir}/eval_results.json", 'w') as f:
        json.dump(results, f, indent=2)

    # Print summary
    for label in ['raw', 'calibrated']:
        r = results[label]
        print(f"\n--- {label.upper()} ---")
        print(f"  Brier:       {r['brier']}")
        print(f"  ECE:         {r['ece']}")
        print(f"  Cal term:    {r['decomposition']['calibration']:.4f}")
        print(f"  Resolution:  {r['decomposition']['resolution']:.4f}")

    return results
```

### Data requirements

| Metric | Minimum resolved outcomes | Reliable at |
|---|---|---|
| Brier score | 50 | 200+ |
| Reliability diagram (10 bins) | 200 | 500+ |
| ECE (10 bins) | 200 | 500+ |
| Per-category calibration | 100 per category | 300+ per category |

---

## 6. Prompting Patterns That Help Calibration

### Pattern 1: Explicit Numeric Extraction

Force the LLM to commit to a number rather than hedging with language.

```
You are a calibrated forecaster. Estimate the probability that
{question} will resolve YES.

Think step by step. Then output EXACTLY one line in this format:
PROBABILITY: 0.XX

Rules:
- Use values between 0.02 and 0.98 (never 0 or 1)
- 0.50 means you have no information either way
- Be precise to two decimal places
```

**Why it helps:** Eliminates parsing ambiguity. The calibrator receives clean floats.

### Pattern 2: Reference Class Prompting

```
Consider the reference class of similar events:
- How often do events like {question} happen historically?
- What is the base rate for this category?

Start from the base rate, then adjust for specific evidence.
State your base rate, your adjustment, and your final probability.

BASE_RATE: 0.XX
ADJUSTMENT: +/- 0.XX (with reasoning)
PROBABILITY: 0.XX
```

**Why it helps:** Anchors the LLM to statistical frequencies rather than narrative reasoning. Reduces overconfidence on salient/dramatic events.

### Pattern 3: Adversarial Debiasing

```
Estimate the probability that {question} resolves YES.

Before giving your final answer:
1. State the strongest argument FOR (YES).
2. State the strongest argument AGAINST (NO).
3. Consider: are you anchoring on a recent headline? Are you
   overweighting a vivid scenario?
4. Give your final calibrated estimate.

PROBABILITY: 0.XX
```

**Why it helps:** Forces consideration of both sides. LLMs that only argue one direction produce extreme, poorly calibrated probabilities.

### Pattern 4: Confidence Bucketing

```
Classify your confidence level:
- VERY_LOW (0.05-0.20 or 0.80-0.95): Strong evidence one direction
- LOW (0.20-0.35 or 0.65-0.80): Moderate evidence
- TOSS_UP (0.35-0.65): Genuinely uncertain
- Select your bucket first, THEN pick a precise number within it.

BUCKET: [your bucket]
PROBABILITY: 0.XX
```

**Why it helps:** Prevents the LLM from clustering predictions around 0.50 or 0.70. Forces deliberate range selection first.

### Pattern 5: Multi-Sample Aggregation

Instead of one prompt, sample N times with temperature > 0 and aggregate:

```python
raw_probs = []
for _ in range(5):
    response = llm.generate(prompt, temperature=0.7)
    prob = parse_probability(response)
    raw_probs.append(prob)

# Use trimmed mean to reduce outlier influence
raw_probs.sort()
ensemble_prob = np.mean(raw_probs[1:-1])  # drop min and max
```

**Why it helps:** Reduces variance from single-sample noise. The trimmed mean is more robust than median for small N.

### Pattern 6: Elicit Reasoning Quality Signal

```
Rate your own confidence in your reasoning (not the event):
REASONING_QUALITY: HIGH | MEDIUM | LOW

If LOW, state what information would change your estimate most.
```

**Why it helps:** This becomes a useful feature for the calibrator. Predictions where the LLM reports LOW reasoning quality can be shrunk toward the base rate during calibration.

---

## Appendix: Quick-Start Checklist

```
1. [ ] Set up append-only prediction log (JSONL or database)
2. [ ] Implement prompt Pattern 1 (explicit numeric extraction)
3. [ ] Accumulate 100+ resolved outcomes
4. [ ] Fit Platt scaling as initial calibrator
5. [ ] Run reliability diagram — inspect visually
6. [ ] At 500+ outcomes, switch to isotonic regression
7. [ ] Automate offline re-fit (weekly cron)
8. [ ] Add staleness guard (drift detection)
9. [ ] Set up eval dashboard (Brier, ECE, reliability diagram)
10. [ ] Iterate on prompt patterns based on per-bucket error analysis
```
