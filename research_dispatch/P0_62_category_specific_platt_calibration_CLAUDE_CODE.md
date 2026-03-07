# P0-62: Category-Specific Platt Calibration
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — Current calibration uses ONE set of Platt parameters for ALL categories. Claude's error patterns differ dramatically by category.
**Expected ARR Impact:** +10–20% (reduces worst-category miscalibration)

## Background

Read COMMAND_NODE.md in the selected folder for full project context. Also read `research/calibration_2_0_plan.md` for the calibration architecture.

Current system: single Platt scaling with A=0.5914, B=−0.3977 applied to ALL markets regardless of category. But our backtest data shows Claude's calibration error varies wildly by category:

- **Politics:** Claude is reasonably calibrated (small systematic YES overconfidence)
- **Weather:** Claude is well-calibrated when given NOAA data, poorly calibrated without
- **Economic:** Claude is systematically overconfident (training data is stale for economic indicators)
- **Geopolitical:** Claude is ~30% worse than experts (per Lu 2025)

A single Platt transform can't fix category-specific biases. Fitting separate parameters per category should significantly improve calibration.

## Task

### 1. Segment 532-Market Backtest by Category

```python
# In backtest/calibration.py
def fit_category_platt(backtest_data: list[dict]) -> dict[str, PlattParams]:
    """Fit separate Platt parameters for each category."""
    from sklearn.linear_model import LogisticRegression
    import numpy as np

    categories = set(d["category"] for d in backtest_data)
    category_params = {}

    for cat in categories:
        cat_data = [d for d in backtest_data if d["category"] == cat]

        if len(cat_data) < 20:
            # Not enough data — fall back to global Platt
            category_params[cat] = {"use_global": True, "n": len(cat_data)}
            continue

        preds = np.array([d["claude_estimate"] for d in cat_data])
        outcomes = np.array([d["outcome"] for d in cat_data])

        # 70/30 split within category
        split = int(len(preds) * 0.7)
        train_p, test_p = preds[:split], preds[split:]
        train_o, test_o = outcomes[:split], outcomes[split:]

        logits = np.log(train_p / (1 - train_p)).reshape(-1, 1)
        lr = LogisticRegression(C=1.0, solver='lbfgs')
        lr.fit(logits, train_o)

        a, b = lr.coef_[0][0], lr.intercept_[0]

        # Compute OOS Brier for this category
        test_logits = np.log(test_p / (1 - test_p))
        calibrated = 1 / (1 + np.exp(-(a * test_logits + b)))
        brier_raw = np.mean((test_p - test_o) ** 2)
        brier_cal = np.mean((calibrated - test_o) ** 2)

        category_params[cat] = {
            "platt_a": a,
            "platt_b": b,
            "n_train": len(train_p),
            "n_test": len(test_p),
            "brier_raw": float(brier_raw),
            "brier_calibrated": float(brier_cal),
            "improvement": float(brier_raw - brier_cal),
            "use_global": False,
        }

    return category_params
```

### 2. Update claude_analyzer.py

Replace the single `calibrate()` call with category-aware routing:

```python
class CategoryCalibrator:
    def __init__(self, global_params: dict, category_params: dict):
        self.global_a = global_params["platt_a"]
        self.global_b = global_params["platt_b"]
        self.category_params = category_params

    def calibrate(self, raw_estimate: float, category: str) -> float:
        params = self.category_params.get(category, {})

        if params.get("use_global", True):
            a, b = self.global_a, self.global_b
        else:
            a, b = params["platt_a"], params["platt_b"]

        logit = np.log(raw_estimate / (1 - raw_estimate))
        calibrated_logit = a * logit + b
        return 1 / (1 + np.exp(-calibrated_logit))
```

### 3. Run Full Backtest Comparison

Compare three calibration approaches on 532 markets:
1. **No calibration** (raw Claude)
2. **Global Platt** (current: A=0.5914, B=−0.3977)
3. **Category-specific Platt** (new)

For each, compute:
- Overall Brier score (OOS)
- Per-category Brier score
- Win rate
- Total P&L
- Number of trades with signal

### 4. Live Calibration Updates

Wire into the DriftDetector from `calibration_2_0_plan.md`:
- When category accumulates 50+ new resolved trades, refit that category's Platt params
- If category has <20 trades, fall back to global params (with 0.5x confidence sizing)
- Log per-category ECE in drift monitoring

### 5. Files to Modify

- MODIFY: `src/claude_analyzer.py` — replace single Platt with CategoryCalibrator
- MODIFY: `backtest/calibration.py` — add `fit_category_platt()`
- MODIFY: `backtest/engine.py` — run comparison across 3 calibration modes
- NEW: `src/calibration/category_calibrator.py` — CategoryCalibrator class
- MODIFY: `src/core/config.py` — add category Platt params to config

### 6. Store Results

Save to `backtest/results/category_calibration_results.json`:
```json
{
  "global_platt": {"brier_oos": 0.245, "win_rate": 0.685},
  "category_platt": {
    "overall": {"brier_oos": "...", "win_rate": "..."},
    "per_category": {
      "politics": {"a": "...", "b": "...", "brier_raw": "...", "brier_cal": "...", "n": "..."},
      "weather": {"..."},
      "economic": {"..."},
      "geopolitical": {"..."},
      "unknown": {"..."}
    }
  },
  "improvement_vs_global": "..."
}
```

## Expected Outcome
- Per-category Brier scores improve, especially for categories where Claude has asymmetric bias
- Overall OOS Brier drops from 0.245 to ~0.220–0.230
- Categories with <20 samples safely fall back to global params
- Foundation laid for live per-category drift monitoring

## Success Criteria
- Category-specific Platt achieves lower OOS Brier than global Platt on at least 3 of 5 categories
- No category gets WORSE calibration (regression check)
- Total win rate improves by at least 1 percentage point

## SOP
After completing this task, UPDATE COMMAND_NODE.md (increment version number, add version log entry) and review STRATEGY_REPORT.md and INVESTOR_REPORT.md for stale calibration numbers.
