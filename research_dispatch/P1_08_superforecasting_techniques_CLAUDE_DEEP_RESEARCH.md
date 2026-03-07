# P1-08: Superforecasting Techniques for LLM-Based Prediction
**Tool:** CLAUDE_DEEP_RESEARCH
**Status:** READY
**Expected ARR Impact:** +10-20% (systematic improvement in estimation quality)

## Prompt for Claude Deep Research

```
I'm building an AI prediction market trading system. I need comprehensive research on superforecasting techniques and how to apply them to automated LLM-based prediction.

1. PHILIP TETLOCK'S SUPERFORECASTING:
   - What are the key principles from "Superforecasting" by Tetlock?
   - What makes superforecasters better than average?
   - Which techniques are automatable with LLMs?
   - How do superforecaster teams aggregate individual estimates?

2. FORECASTING TOURNAMENT DATA:
   - What do we know from the Good Judgment Project, Metaculus, and IARPA ACE?
   - What is the typical accuracy of top forecasters vs LLMs?
   - Recent papers (2024-2026) comparing LLM forecasting to human forecasters
   - ForecastBench, Halawi et al. 2024, and other benchmarks

3. SPECIFIC TECHNIQUES TO IMPLEMENT:
   a) Reference class forecasting: How to identify the right reference class for a prediction market question
   b) Fermi estimation: Breaking complex questions into estimable sub-questions
   c) Base rate neglect correction: How to anchor on base rates before adjusting
   d) Wisdom of crowds: How to simulate diverse perspectives with a single LLM
   e) Extremizing: When and how to push estimates away from 50%
   f) Decay functions: How to weight information by recency
   g) Outside view vs inside view: Structured protocols for combining both

4. CALIBRATION TRAINING:
   - Can you "train" an LLM to be better calibrated through prompting?
   - What happens if you include calibration feedback in the prompt?
   - Does few-shot learning with calibrated examples help?
   - Can you use the LLM's own past performance to improve future estimates?

5. PREDICTION MARKET SPECIFIC:
   - How do prediction market prices relate to true probabilities?
   - What is the typical vig/rake in prediction market pricing?
   - How to account for risk premium in market prices?
   - Time decay effects: do market prices become more accurate closer to resolution?

Provide actionable findings I can implement in an automated system within 1 week.
```
