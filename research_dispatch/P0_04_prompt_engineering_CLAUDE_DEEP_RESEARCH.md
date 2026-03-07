# P0-04: Optimal Prompt Engineering for Probability Estimation
**Tool:** CLAUDE_DEEP_RESEARCH
**Status:** COMPLETED (GPT-4.5 Deep Research, 2026-03-05)
**Results:** See `/research_prompts/04_prompt_engineering_calibration_research.md`
**Key Findings:** Temperature scaling best for post-hoc calibration. Base-rate-first prompts most effective. CoT worsens calibration. Explicit debiasing ("you overestimate YES by 20-30%") helps. For ensembles: start with simple average, then test BTLP.
**Expected ARR Impact:** +10-25% (better estimates = more edge)

## Research Question
What prompt strategies produce the most calibrated probability estimates from LLMs?

## Prompt for Claude Deep Research

```
I'm using Claude Haiku to estimate probabilities for prediction market trading. My current prompt removes the market price to avoid anchoring, but Claude is still systematically overconfident — when it says 90% YES, the actual rate is only 63%.

Research the following:

1. PROMPT CALIBRATION TECHNIQUES:
   - What academic research exists on improving LLM probability calibration?
   - What prompt engineering techniques produce better-calibrated estimates?
   - Does chain-of-thought reasoning improve or worsen calibration?
   - Does asking for confidence intervals help?
   - Should the prompt include base rates? Historical examples?
   - Does asking the model to "think like a superforecaster" help?

2. SPECIFIC TECHNIQUES TO TEST:
   - Verbal uncertainty scales vs numeric probabilities
   - Asking for "percent chance" vs "probability"
   - Requesting estimates from multiple perspectives (bull case, bear case, base case)
   - Pre-mortem analysis ("If this resolved NO, what happened?")
   - Reference class forecasting prompts
   - Decomposition prompts (break question into sub-questions)
   - Devil's advocate prompts (argue against your estimate)
   - "Consider the outside view" prompting

3. ANTI-OVERCONFIDENCE:
   - How to specifically reduce overconfidence in LLMs?
   - Are there prompt strategies that push estimates toward the center (0.50)?
   - Should we explicitly tell the model "You tend to be overconfident on YES"?
   - Does providing calibration feedback in the prompt improve future estimates?

4. MULTI-STEP ESTIMATION:
   - Step 1: Estimate base rate
   - Step 2: List evidence for/against
   - Step 3: Adjust from base rate
   - Step 4: Give final estimate
   Does this produce better calibration?

5. Provide 5-10 specific prompt templates I can A/B test against my current prompt, ranked by expected calibration improvement.
```
