# P0-02: Multi-Model Ensemble (Claude + GPT + Grok)
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** +20-40% (reduces single-model bias)

## Problem
Single model (Claude Haiku) has systematic biases. Ensemble of 3+ models should average out individual biases and improve calibration.

## Task
Build an ensemble system that:
1. Queries Claude Haiku, GPT-4o-mini, and Grok (via APIs) with the SAME anti-anchoring prompt
2. Aggregates probability estimates using (ranked by research evidence):
   - Simple average (robust baseline — ensembles of LLMs averaged have matched human crowds)
   - Weighted average (weight by historical Brier score per model)
   - Logarithmic pool (geometric mean in odds — gives more weight to confident models, minimizes log-loss; risk: amplifies overconfidence errors)
   - Beta-Transformed Linear Pool (BTLP — apply Beta CDF transform to correct calibration bias, then average; outperformed equal-weighted pools in disease-forecast ensembles)
   - Median (robust to outliers)
3. Backtest all 3 aggregation methods on our 532 resolved markets
4. Compare ensemble win rate vs single-model win rate
5. Select the best aggregation method

## API Setup Needed
- Claude: Already have key
- OpenAI GPT-4o-mini: Need API key (user will provide)
- Grok (xAI): Need API key (user will provide)

## Architecture
```python
class EnsembleEstimator:
    def __init__(self, models: list[ModelClient]):
        self.models = models

    def estimate(self, question: str) -> dict:
        estimates = [m.estimate(question) for m in self.models]
        return {
            "mean": mean(e.prob for e in estimates),
            "median": median(e.prob for e in estimates),
            "weighted": weighted_avg(estimates, weights=self.brier_weights),
            "spread": max - min,  # disagreement metric
            "individual": estimates,
        }
```

## Research Update (2026-03-05, from P0-04)
GPT-4.5 research on ensemble methods recommends: Start with **simple average** (competitive and easy). If calibration varies across models, try **Beta-Transformed Linear Pool (BTLP)**. **Log pools** are theoretically optimal under log-scoring rules — try when models are comparably calibrated. Key risk: log-pooling amplifies errors when any model is overconfident on wrong outcome.

## Expected Outcome
- Brier score improvement from 0.239 to <0.18
- Win rate improvement from 65% to 70%+
- Disagreement metric useful as confidence indicator
