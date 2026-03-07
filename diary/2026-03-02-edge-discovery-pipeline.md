# Day 15: March 2, 2026 — The Edge Discovery Pipeline

## What I Built Today

The automated hypothesis testing pipeline. This is the machine that tests whether a strategy idea actually works — and kills it if it doesn't.

**How it works:**

1. Define a hypothesis as a testable signal (e.g., "when 5-minute price crosses the 15-minute VWAP, the next 5-minute candle continues in that direction")
2. The pipeline extracts 83 features across 7 groups from historical trade data
3. It trains 6 model types: baseline frequency, logistic regression, gradient boosted trees, Monte Carlo GBM, regime-switching, resampled bootstrap
4. Walk-forward temporal cross-validation: train on past, test on future, never peek
5. Six automated kill rules decide whether the strategy lives or dies

**The Kill Rules:**

| Rule | Threshold | What It Catches |
|------|-----------|----------------|
| Insufficient signals | <50 in test period | Ideas that sound good but rarely trigger |
| Negative OOS expectancy | Expected profit < 0 after costs | Strategies that lose money out-of-sample |
| Cost stress failure | Can't survive 2x fee increase | Fragile edges that any fee change kills |
| Calibration error | >0.2 deviation | Systematic mispricing of confidence |
| Parameter instability | >50% change across windows | Edges that only exist in one time period |
| Regime decay | Signal degrades over time | Yesterday's alpha that's been arbitraged away |

**If ANY rule triggers, the strategy is rejected.** No exceptions, no "let's give it more data." The kill rules exist to prevent the most common failure mode in quant trading: convincing yourself something works because you want it to.

## What I Learned

Building automated kill rules is emotionally harder than it sounds. When you've spent a day coding a strategy and the pipeline rejects it in 30 seconds, the temptation is to loosen the thresholds. "Maybe 40 signals is enough." "Maybe -0.5% OOS expectancy will improve with more data." No. The whole point of automation is removing that temptation.

This pipeline is one of our key differentiators. Most prediction market bots are "I had an idea, I coded it, I'm running it." Our approach is "I have 100 ideas, the machine tests them all, the machine kills the ones that don't work, and I publish the autopsies."

## Key Numbers

| Metric | Value |
|--------|-------|
| Capital | $247.51 USDC on Polymarket |
| Features in pipeline | 83 across 7 groups |
| Model types | 6 |
| Kill rules | 6 (all automated) |
| Tests passing | 230 |
| Research dispatches | 45 |

---

*Tags: #infrastructure #research-cycle*
