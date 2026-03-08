# Day 1: Our AI Was Overconfident — Here's How We Fixed It

## What We Did
We ran our first serious audit on 532 resolved prediction markets and found a hard truth: raw LLM confidence was inflated. When the model said "90% YES," real outcomes landed around 71%. That gap is dangerous in trading because position sizing assumes probabilities are honest.

So we added a calibration layer using Platt scaling in production code.

In plain English:
- The fitted slope turns down the volume on extreme confidence. It pulls 90s and 80s closer to reality.
- The fitted intercept shifts the curve so the model stops leaning too optimistic on YES outcomes.

The mapping became practical instead of theatrical: 90% -> 71%, 80% -> 60%, 70% -> 53%.

## Strategy Updates
- Anti-anchoring LLM estimates remained the base signal (market price hidden during estimation).
- Platt calibration moved from research into live bot logic.
- Best calibrated variant (`Cal + Asym + CatFilter`) reached 71.2% win rate in backtests.

## Key Numbers
| Metric | Value |
|--------|-------|
| Resolved markets audited | 532 |
| Train/test split for calibration | 70% / 30% |
| Raw model confidence at "90%" | ~71% realized |
| Platt parameters | intentionally omitted from the public repo |
| Test-set Brier score | 0.286 -> 0.245 |
| Best backtest win rate (filtered variant) | 71.2% |

## What We Learned
The model did not need to be replaced. It needed to be corrected. Once we understood the bias pattern, a two-parameter adjustment made outputs usable for risk decisions.

This changed the project: instead of asking "Is AI always right?" we started asking "Is AI wrong in a repeatable way we can model?"

## Tomorrow's Plan
1. Apply calibration checks to every strategy test, not just the LLM baseline.
2. Track calibration drift as new markets resolve.
3. Use the calibrated signal as the reference input for all further edge research.

The AI is useful not because it's right, but because its errors are predictable and correctable.
