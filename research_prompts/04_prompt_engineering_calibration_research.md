# P0-04 Research Results: Optimal Prompt Engineering for Probability Estimation
**Source:** GPT-4.5 Deep Research
**Date:** 2026-03-05
**Status:** COMPLETED

---

## BLUF
Post-hoc temperature scaling on an LLM's confidence scores is generally most effective. Chain-of-thought and decomposition can help organize reasoning but may worsen calibration if overused. Forecasting prompts that anchor on historical reference classes (base rates) and include critical steps (pre-mortem, scenario analysis) have been shown to improve calibration. A multi-step protocol (outside-view base rate → evidence → adjustment → final) mirrors best practices and tends to yield more calibrated probabilities. For ensembles, simple averaging of models often boosts accuracy, but logarithmic pools (geometric mean in odds) give extreme weight to confident models, and beta-transformed linear pools can correct bias (they outperformed equal-weighted pools in disease-forecast ensembles).

---

## 1. Calibration Techniques

### Definitions
- **Platt scaling:** Sigmoid fit to scores (2 parameters, suited to binary tasks)
- **Isotonic regression:** Nonparametric monotonic fit; can capture complex miscalibration with ample data but risks overfitting with scarce data
- **Temperature scaling (TS):** Single-parameter softmax rescale; preserves prediction ordering

### LLM-Specific Findings
- TS is particularly effective for LLMs
- One study prompting LLMs to output verbalized probabilities used an "invert softmax" trick to extract logits, then applied TS → significantly reduced ECE
- TS preserves accuracy and needs little data
- Isotonic/Platt may require more tuning and risk overfitting on limited held-out sets

### Empirical Ranking
**Temperature scaling usually performs best for LLM outputs.** If large calibration datasets are available, isotonic regression can sometimes further improve metrics (at risk of overfitting). Platt's sigmoid is less flexible.

---

## 2. Prompt Strategies for Better Calibration

### Chain-of-Thought vs. Direct
- Step-by-step reasoning can improve accuracy but often **increases overconfidence**
- "Thinking longer" can make LLMs more overconfident
- Longer CoT chains boosted accuracy modestly but drove confidence well above true accuracy
- **Use CoT judiciously**

### Reference-Class Forecasting (MOST PROMISING)
- Prompting the model to consider historical analogies or base rates is **highly effective**
- "Base Rate First" or "Frequency-Based Reasoning" where the model first recalls similar past events
- Prompts explicitly drawing on reference-class reasoning were particularly promising
- Aligns with human forecaster guidelines (Tetlock & Gardner, 2016)

### Decomposition
- Break the problem into sub-questions or steps
- "Step-Back" or guided principle prompts have shown some benefits
- List (a) relevant metrics or (b) a timeline before answering

### Devil's Advocate / Self-Critique
- Have the model argue both sides
- First get an answer and reasoning, then prompt "Now play devil's advocate: give reasons your answer might be wrong"
- Aligns with ensemble/self-consistency ideas

### Pre-mortem (Error Analysis)
- Explicitly ask the model to consider how its forecast could fail
- "Pre-mortem: Imagine you will be wrong. What uncertainties or assumptions could cause this?"
- Encourages caution and can lower bias

### Explicit Debiasing
- Remind the model of known biases
- Example: "Note: Models often overestimate [Yes] probabilities by 20–30%. Adjust for this."
- Evidence shows RLHF-tuned LLMs are poorly calibrated and tend to overconfident "Yes" answers

### Few-Shot Calibration Examples
- Provide example Q&A pairs with rationales and calibrated percentages
- Few-shot examples can improve both accuracy and calibration

---

## 3. Multi-Step Estimation Protocol

### Four-Step Approach (Outside → Inside View)

1. **Base Rate (Outside View):** Ask for the probability of similar events or historical frequency first
2. **Evidence (Inside View):** List specific factors or data relevant to the question
3. **Adjustment:** Combine the evidence-based adjustment to the base rate
4. **Final Probability:** Output the updated forecast

### Illustration
"Base rate: 8%. After +5% positive and -3% negative factors, Final probability = 10%."

### Additional Sub-Steps
- Note time until resolution
- Describe current status quo
- Forecast longer horizons for consistency

---

## 4. Prompt Templates (Ranked by Expected Improvement)

### Template 1: Base-Rate-and-Evidence (HIGHEST EXPECTED IMPROVEMENT)
```
Begin by estimating a base rate from analogous events. Then list evidence for and against the outcome before giving a final probability. Format:

1. Historical Base Rate (e.g., analogous cases or global statistics): ...%
2. Current Evidence (key factors supporting or opposing): [detailed rationale]
3. Adjusted Probability (combine base rate + adjustments): ...%

Final forecast (Yes probability): ...%
```

### Template 2: Pre-mortem + Scenarios
```
First, write a "pre-mortem" analysis: what might make your forecast wrong? Describe the biggest uncertainties. Next, describe one scenario leading to a NO outcome and one scenario leading to a YES outcome. Finally, state your probability. Format:

- Pre-mortem (Why my forecast could be wrong): [analysis]
- Scenario if NO: [narrative]
- Scenario if YES: [narrative]
- **Final forecast (Probability of YES):** ...%
```

### Template 3: Devil's Advocate
```
Give your initial probability and reasoning, then argue against it before finalizing. Format:

1. Initial Forecast and Reasoning: ...% [rationale]
2. Devil's Advocate (arguments against that forecast): [contrary evidence or flaws]
3. Revised Final Forecast: ...%
```

### Template 4: Chain-of-Thought Stepwise
```
Answer the question step-by-step. Think out loud in a clear, logical chain of thought. After your reasoning, give the final probability. Format:

Q: [Question]
A: Let's reason this out step by step. [Model's detailed reasoning] … Therefore, the probability is ...%.
```

### Template 5: Few-shot Example
```
Q1: [Example question 1]
A1: [Rationale + Forecast]%
Q2: [Example question 2]
A2: [Rationale + Forecast]%

Now answer the target question: [Your question].
```

---

## 5. Ensemble Aggregation Methods

### Linear (Arithmetic) Pool
- Simply average the probabilities (equal or weighted)
- "Wisdom of crowds" approach — robust and easy
- Ensembles of LLMs (averaged) have matched or exceeded human crowds
- Tends to produce moderate (well-calibrated) consensus forecasts

### Logarithmic (Geometric) Pool
- Combine by averaging log-odds (multiply probabilities and renormalize)
- Gives more weight to confident models
- Minimizes average log-loss
- "Takes confident forecasts more seriously" than linear pooling
- **Risk:** If an LLM is overconfident on a wrong outcome, log-pooling amplifies that error

### Beta-Transformed Linear Pool (BTLP)
- Apply a Beta CDF transform to each model's forecast to correct calibration, then average
- Significantly outperformed equal-weighted linear pools in influenza ensembles
- Effectively learns to stretch/squash the probability scale to correct biases

### Recommendation
- Start with **simple average** of well-calibrated models (competitive and easy)
- If calibration varies, try **beta-transformed pools**
- **Log pools** are theoretically optimal under log-scoring rules; try when models are comparably calibrated

---

## Key Actionable Takeaways for Our Bot

1. **Implement temperature scaling** as post-hoc calibration (P0-01) — most effective single fix
2. **Switch prompt to Base-Rate-and-Evidence template** (Template 1) — highest expected calibration improvement
3. **Add explicit debiasing line** to prompt: "Note: You tend to overestimate YES probabilities by 20-30%. Adjust accordingly."
4. **For ensemble (P0-02):** Start with simple average, then test log-pool and BTLP
5. **A/B test templates** against current prompt on resolved markets (P2-15)
6. **Avoid heavy CoT** — it worsens calibration despite improving accuracy
