# P0-51: Automated Architecture — Self-Improving System Design
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P0 — The system should improve itself, not wait for us to push changes
**Expected ARR Impact:** Compounding — every auto-improvement multiplies future returns

## Background
Right now, every improvement requires manual research → manual coding → manual deployment. In 5 days, we need a system that improves itself automatically. The architecture should:
1. Continuously measure its own performance
2. Identify what's working and what isn't
3. Test improvements in shadow mode
4. Promote winning variants automatically (with human approval gate)

This is our meta-edge: not just a prediction bot, but a SELF-IMPROVING prediction engine.

## Task

Build three auto-improvement subsystems:

### A. Auto-Calibration Recalibrator
Every time we accumulate 50 new resolved trades (live or backtest), automatically:
1. Refit the temperature-scaling calibration using all available data
2. Compare new calibration vs old on holdout set (last 20% of data)
3. If new calibration improves Brier score by >0.005, deploy it
4. Log the recalibration event and notify via Telegram

```python
class AutoCalibrator:
    def __init__(self, min_samples=50, improvement_threshold=0.005):
        self.min_samples = min_samples
        self.threshold = improvement_threshold

    def check_and_recalibrate(self, predictions: list, outcomes: list):
        if len(predictions) < self.min_samples:
            return False

        # Hold out last 20% for validation
        split = int(len(predictions) * 0.8)
        train_preds, val_preds = predictions[:split], predictions[split:]
        train_outs, val_outs = outcomes[:split], outcomes[split:]

        # Fit new temperature on training set
        new_temp = optimize_temperature(train_preds, train_outs)

        # Compare on validation set
        old_brier = brier_score(val_preds, val_outs)
        new_brier = brier_score(calibrate(val_preds, new_temp), val_outs)

        if old_brier - new_brier > self.threshold:
            self.deploy_new_calibration(new_temp)
            return True
        return False
```

### B. Strategy Parameter Auto-Tuner
Extend the existing auto-tuning (every 20 cycles) with more parameters:
- Edge thresholds: test ±2% variations, pick best by backtested Sharpe
- Kelly fraction: adjust based on recent win rate trend (not just absolute level)
- Category weights: shift capital toward categories with highest recent win rate
- Ensemble weights: adjust Claude vs market weight based on recent forecast accuracy

All changes logged and reversible. Max one parameter change per tuning cycle (avoid overfitting to noise).

### C. Shadow Mode for New Strategies
Any new strategy variant (prompt change, model addition, parameter change) runs in shadow mode first:
1. New variant generates signals alongside production
2. Both production and shadow signals logged
3. After 50+ signals, compare performance
4. If shadow beats production by >5% win rate with p < 0.10, flag for promotion
5. Human approves → shadow becomes production → old strategy becomes shadow

```python
class ShadowTester:
    def __init__(self):
        self.production_signals = []
        self.shadow_signals = []

    def log_signal(self, market_id, production_signal, shadow_signal):
        self.production_signals.append((market_id, production_signal))
        self.shadow_signals.append((market_id, shadow_signal))

    def evaluate(self) -> dict:
        if len(self.production_signals) < 50:
            return {"status": "accumulating", "n": len(self.production_signals)}

        prod_wr = self.win_rate(self.production_signals)
        shadow_wr = self.win_rate(self.shadow_signals)
        p_value = binomial_test(shadow_wr, prod_wr, len(self.shadow_signals))

        return {
            "production_wr": prod_wr,
            "shadow_wr": shadow_wr,
            "p_value": p_value,
            "recommend_promote": shadow_wr > prod_wr + 0.05 and p_value < 0.10
        }
```

## Files to Create
- NEW: `src/auto_calibrator.py`
- NEW: `src/auto_tuner.py` (expand from existing tuning logic)
- NEW: `src/shadow_tester.py`
- MODIFY: `improvement_loop.py` — integrate all three subsystems
- MODIFY: `src/telegram.py` — auto-improvement notifications

## Expected Outcome
- System that gets better automatically over time
- Calibration stays fresh as market conditions change
- Parameters adapt to current market regime
- New strategies validated before deployment (no blind deploys)
- Compounding edge: each improvement enables the next
