---
title: How AI Forecasts: The Science of Machine Probability Estimation
status: published
doc_type: article
last_reviewed: 2026-03-22
---

# How AI Forecasts: The Science of Machine Probability Estimation

*Part of the Elastifund Education Center — [elastifund.io/learn/how-ai-forecasts](https://elastifund.io/learn/how-ai-forecasts)*

---

## TL;DR (30 seconds)

We ask multiple AI models to estimate the probability of real-world events — without showing them the current market price. This is called "anti-anchoring" and it prevents the most common bias in forecasting. The raw estimates are then corrected for systematic overconfidence using a mathematical technique called Platt scaling. If the corrected estimate disagrees with the market price by enough, we trade.

The key insight: AI models are systematically overconfident. When Claude says "90% likely," it's actually right about 63% of the time. Calibration fixes this.

---

## The Full Explanation (5 minutes)

### Why Hide the Market Price?

Imagine you're estimating the probability that it will rain tomorrow. If I tell you "the weather market prices rain at 40%," your estimate will be pulled toward 40% — even if your independent analysis says 70%. This is anchoring bias, and it's one of the strongest cognitive biases in psychology. It affects humans and AI models alike.

Our system asks Claude, GPT, and other AI models to estimate probabilities with zero knowledge of what the market thinks. The prompt explicitly instructs: "Do NOT use the current market price as an input. Estimate from first principles."

This discipline costs us information (the market price does contain useful signal), but it prevents a worse problem: the AI just agreeing with the market, which produces zero edge.

### The Estimation Process

For each market the system considers trading:

1. **Market context collection.** The system fetches the market question, resolution criteria, end date, and current news context via web search (DuckDuckGo). This is "Agentic RAG" — retrieval-augmented generation — and academic research shows it's the single highest-impact technique for LLM forecasting (Brier improvement of 0.06 to 0.15).

2. **Multi-model estimation.** Three AI models estimate independently and in parallel: Claude Haiku (Anthropic), GPT-4.1-mini (OpenAI), and Llama 3.3 via Groq. Each receives the same context and the same anti-anchoring prompt.

3. **Aggregation.** We take the trimmed mean of the three estimates (drop the highest and lowest, average the rest). Academic research (Halawi et al. 2024, NeurIPS) showed that combining multiple LLM estimates produces a "wisdom of crowds" effect — individual model biases cancel out.

4. **Consensus gating.** If fewer than 75% of models agree on the direction (all saying YES likely or NO likely), we skip the trade. Disagreement between models means the question is genuinely uncertain, and that's not where we have edge.

5. **Calibration.** The raw ensemble estimate is corrected using Platt scaling — a mathematical function that maps the AI's confident-but-wrong estimates to more accurate ones.

6. **Edge calculation.** We compare the calibrated estimate to the market price. If the difference exceeds our threshold (15% for YES, 5% for NO), we trade.

### Why Multiple Models?

Claude has specific biases: it tends to agree with the framing of questions (acquiescence bias), making it overconfident on YES outcomes. GPT may have different biases. Llama, trained differently, may have yet another bias profile.

When all three independently arrive at a similar estimate, that's stronger evidence than any single model. When they disagree sharply, that's a warning to stay out.

This mirrors the academic finding that "crowds of models" match "crowds of humans" in forecasting accuracy. The diversity of training data and architectural differences between models creates the same diversity of perspective that makes human crowds wise.

### The Calibration Problem

Raw AI estimates are unreliable in a specific, measurable way:

| Claude Says | Actually True |
|------------|--------------|
| 90% likely | 63% of the time |
| 80% likely | 60% of the time |
| 70% likely | 53% of the time |
| 50% likely | 40% of the time |

Claude is overconfident across the board, but especially on high-confidence YES estimates. Platt scaling is a logistic regression in logit space that corrects this: it maps the AI's stated confidence to the historically observed accuracy.

Our fitted Platt curve was trained on 372 resolved markets and validated on 160 held-out markets (temporal split, not random — you can't use future data to calibrate past estimates). The improvement: Brier score from 0.286 to 0.245 on the held-out set. The exact live coefficients are intentionally not published in the public docs.

---

## Technical Deep Dive (30 minutes)

### The Anti-Anchoring Prompt

The exact prompt structure matters enormously. Academic research (Schoenegger 2025) tested dozens of prompting strategies for LLM forecasting and found that most techniques HURT accuracy:

**Techniques that help (ranked by Brier improvement):**
1. Agentic RAG (web search for context): −0.06 to −0.15
2. Platt scaling calibration: −0.02 to −0.05
3. Multi-run ensemble (3-7 estimates): −0.01 to −0.03
4. Base-rate-first prompting: −0.011 to −0.014
5. Structured scratchpad: −0.005 to −0.010

**Techniques that HURT accuracy:**
- Bayesian reasoning prompts: +0.005 to +0.015 WORSE
- Chain-of-thought (for probability): makes models verbose, not accurate
- Elaborate "think step by step" instructions: adds noise
- Asking the model to propose and evaluate multiple scenarios: degrades calibration

Our prompt uses base-rate-first structure (the model considers the outside-view base rate before the inside-view specifics), a structured scratchpad, and explicit debiasing instructions. It does NOT use chain-of-thought, Bayesian reasoning, or scenario analysis — because the data says those techniques make things worse.

### Platt Scaling: The Math

Platt scaling fits a logistic function to map raw model outputs to calibrated probabilities:

```
calibrated_prob = 1 / (1 + exp(A × logit(raw_prob) + B))
```

Where logit(p) = log(p / (1-p)), and A and B are learned parameters.

Our calibration uses a compressed and shifted logistic curve. Geometrically, that means extreme estimates are pulled back toward 50% and the whole curve leans slightly lower to correct YES-overconfidence.

**Training process:**
1. Run Claude on 532 resolved markets (anti-anchoring mode, no market price shown)
2. Split temporally: first 372 markets for training, last 160 for validation
3. Fit Platt parameters on training set using maximum likelihood
4. Evaluate on held-out set: Brier 0.2862 → 0.2451 (improvement of 0.0411)

We also tested isotonic regression (a non-parametric alternative), which achieved 0.2482 on the held-out set — comparable but slightly worse and less interpretable. We chose Platt for interpretability: two parameters are easier to reason about and monitor for drift than a step function.

### Category-Specific Calibration

Claude's biases differ by topic. On political markets, Claude is moderately overconfident. On geopolitical markets, it's severely overconfident. On weather, it's actually somewhat underconfident.

We trained separate Platt parameters for each market category with >30 training samples. The result: overall Brier improved from 0.1561 to 0.1329 — a 2.3% improvement, with 4.6% improvement on geopolitical markets specifically.

Categories with <30 samples fall back to the global calibration. This prevents overfitting on small sample sizes.

### The Acquiescence Bias Problem

"Acquiescence bias" means Claude tends to answer YES to yes/no questions. When asked "Will X happen?", Claude's estimates skew toward higher probabilities than reality. This is why our system has asymmetric edge thresholds:

- **YES threshold: 15%.** We need to be very confident Claude's YES estimate is real, not just acquiescence.
- **NO threshold: 5%.** NO estimates are more reliable, so we trade them with less evidence.

The empirical basis: across 532 resolved markets, buying NO won 76.2% of the time. Buying YES won 55.8%. The crowd systematically overpays for exciting YES outcomes, and our NO-biased thresholds exploit this.

### SACD Drift: Why Fresh Estimates Matter

Self-Anchored Confirmation Drift (SACD): if you show an LLM its previous estimate and ask it to update, it anchors to its own prior. Updates become tiny, even when new information is significant. The model confirms its own previous judgment.

Our solution: never show the model its own priors. Every estimation is fresh — new web search, new analysis, new number. This is computationally wasteful (we could cache and update), but the alternative (anchored models that refuse to change their minds) is worse.

Academic support: superforecasters make 7.8 predictions per question (vs 1.4 average) but with small update magnitudes (3.5% vs 5.9%). The key is frequent, small, fresh estimates — not infrequent, large updates.

### Measuring Forecast Quality: Brier Scores

The Brier score is the gold standard for evaluating probability forecasts:

```
Brier = mean((forecast - outcome)²)
```

Where forecast is the estimated probability (0 to 1) and outcome is the actual result (0 or 1).

A perfect forecaster scores 0. Random guessing on binary events scores 0.25. The current frontier for LLM-based forecasting is approximately 0.075-0.10 when combining the model estimate with market price.

Our system: 0.2171 (calibrated, without market price). That's better than random but far from the frontier. The gap is partly because we deliberately don't use market price as an input (anti-anchoring), which sacrifices accuracy for independence. The frontier scores blend model + market.

---

*Last updated: March 7, 2026 | Part of the Elastifund Education Center*
