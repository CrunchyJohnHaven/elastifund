# P0-69: ChatGPT 5.4 — Optimal Forecasting Prompt Discovery
**Tool:** CHATGPT 5.4
**Status:** READY
**Priority:** P0 — GPT-5.4 may respond differently to prompt strategies than Claude. Must find its optimal prompt.
**Expected ARR Impact:** +5–15% (if GPT-5.4's optimal prompt differs from Claude's)

## Prompt (paste into ChatGPT 5.4)

```
I'm building an AI prediction market trading system that uses LLMs to estimate probabilities. I need to find YOUR optimal forecasting prompt — the prompt structure that makes YOU most accurate.

BACKGROUND FROM ACADEMIC RESEARCH:
- Schoenegger (2025): Only base-rate-first prompting improves LLM forecasting (−0.014 Brier). Chain-of-thought, Bayesian reasoning, and elaborate prompts HURT calibration.
- Halawi et al. (2024, NeurIPS): Multi-model LLM ensembles match human crowd accuracy.
- Bridgewater AIA Forecaster (2025): Platt-scaling calibration + ensemble with market consensus beats either alone.
- Key finding: LLMs have "acquiescence bias" — they skew toward YES. Anti-anchoring (hiding the market price) is critical.

WHAT WE KNOW WORKS WITH CLAUDE HAIKU:
1. Anti-anchoring: Never show the market price
2. Base-rate-first: "Start with the historical base rate, then adjust"
3. Structured 6-step reasoning: outside view → evidence for → evidence against → calibration check → confidence → final estimate
4. Category awareness: tell the model what category (politics, weather, economic)
5. Debiasing: explicit instruction to avoid overconfidence on YES

WHAT I NEED FROM YOU:
Test yourself on this prediction market question using 5 different prompt strategies. Give me your probability estimate for EACH strategy so I can see how your estimate changes based on prompting:

QUESTION: "Will the US impose new tariffs on Chinese goods exceeding 25% by June 2026?"

STRATEGY 1 — MINIMAL (baseline):
Just answer: what's the probability this resolves YES? Give a number between 0 and 1.

STRATEGY 2 — BASE-RATE-FIRST:
First, identify the base rate: how often has the US imposed new tariffs on China in recent years? Start with that rate, then adjust for current conditions.

STRATEGY 3 — STRUCTURED REASONING (our current Claude prompt):
Step 1: What's the outside view (base rate for this type of event)?
Step 2: List 3 pieces of evidence FOR this happening
Step 3: List 3 pieces of evidence AGAINST this happening
Step 4: Check yourself — are you being overconfident? LLMs typically skew 10-20% too confident toward YES.
Step 5: Rate your confidence (LOW/MEDIUM/HIGH)
Step 6: Give your final probability estimate

STRATEGY 4 — PRE-MORTEM:
First, imagine it's June 2026 and new tariffs WERE imposed. Write a brief story of how it happened.
Then, imagine it's June 2026 and new tariffs were NOT imposed. Write a brief story of why.
Now, weighing both scenarios, estimate the probability.

STRATEGY 5 — DECOMPOSITION (Fermi):
Break this into sub-questions:
- P(political will exists for new tariffs) = ?
- P(specific trigger event occurs given political will) = ?
- P(tariffs exceed 25% threshold given trigger) = ?
- P(implementation by June given announcement) = ?
Multiply relevant probabilities for your final estimate.

AFTER GIVING ALL 5 ESTIMATES:
1. Which strategy felt most natural and produced the most thoughtful answer?
2. Which strategy do you think produced the most ACCURATE estimate? Why?
3. Did you notice yourself anchoring to your first estimate? Were later estimates pulled toward earlier ones?
4. What prompting strategy would you RECOMMEND I use with you for maximum accuracy?
5. Design your ideal prompt template — the one you think would make you most accurate as a forecaster. Include exact wording.

I will test your recommended prompt against our current Claude prompt on 100+ resolved markets to compare.
```

## How to Use Results

1. If GPT-5.4 estimates vary >10% across strategies → prompt engineering matters for this model
2. If estimates are stable across strategies → GPT-5.4 is prompt-robust (good for ensemble)
3. Use GPT-5.4's self-designed prompt template as the starting point for its ensemble integration
4. Run P0-68 benchmark using GPT-5.4's recommended prompt (not our Claude prompt)

## SOP
Store results in `research/gpt54_prompt_optimization_results.md`. Update P0-02 (ensemble architecture) with findings about optimal per-model prompts.
