# P0-50: Superforecaster Techniques Implementation
**Tool:** CLAUDE_DEEP_RESEARCH
**Status:** READY
**Priority:** P0 — The top 2% of forecasters use specific techniques. We should encode ALL of them.
**Expected ARR Impact:** +15-30% (Tetlock's research shows these techniques consistently improve accuracy)

## Background
Philip Tetlock's research on superforecasters identified specific cognitive techniques that the top 2% of forecasters use. These aren't vague heuristics — they're concrete, implementable methods. Our current system uses ONE of these (base-rate anchoring). We should encode ALL of them into our LLM pipeline.

## Research Questions

```
Deep research on superforecaster techniques that can be encoded into an LLM prediction system:

1. TETLOCK'S COMMANDMENTS — What are the 10 commandments of superforecasting from "Superforecasting: The Art and Science of Prediction"? For each one:
   - Explain the technique in detail
   - Is it already implemented in our system? (Our system: LLM estimates probability from question text with base-rate-first prompt, calibration correction, no market price shown)
   - How would you implement it as a specific prompt instruction or code module?
   - What's the expected improvement?

2. GOOD JUDGMENT PROJECT (GJP) METHODS:
   - What specific forecasting protocols did the GJP use?
   - How did they train forecasters to improve?
   - "Belief updating" — what's the Bayesian framework they taught?
   - "Granularity" — why does precise numerical estimation improve accuracy?
   - "Active open-mindedness" — how to encode anti-confirmation bias?

3. DECOMPOSITION TECHNIQUES:
   - Fermi estimation: break complex questions into estimable sub-questions
   - Reference class forecasting: find the base rate from similar historical events
   - Inside/outside view: estimate from both specific details and general category rates
   - How to implement each as a structured LLM prompt chain?

4. METACOGNITIVE TECHNIQUES:
   - Pre-mortem: "Imagine this event DID happen — why?" and "Imagine it DIDN'T happen — why?"
   - Dialectical bootstrapping: query the same LLM twice with different framings, average
   - Devil's advocate: force the model to argue the opposite position
   - Which of these measurably improve LLM forecasting accuracy? (cite papers)

5. CALIBRATION TRAINING:
   - How did GJP train forecasters to become better calibrated?
   - "Calibration quizzes" — can we build a calibration feedback loop for our LLM?
   - Extremizing: when combining forecasts, push the average toward extremes — by how much?
   - Shrinkage toward base rates: optimal shrinkage factor for LLM estimates?

6. DECISION PIPELINE:
   - Design a complete multi-step forecasting pipeline that encodes ALL superforecaster techniques:
     Step 1: Question decomposition (Fermi)
     Step 2: Reference class identification (base rate)
     Step 3: Inside view estimation (specific evidence)
     Step 4: Outside view estimation (category base rate)
     Step 5: Synthesis (Bayesian update inside on outside)
     Step 6: Pre-mortem check (argue both sides)
     Step 7: Calibration correction (temperature scaling)
     Step 8: Extremization (if ensembling)

   - For each step, write the EXACT prompt text that should be sent to the LLM
   - How many API calls does this pipeline require? (Cost analysis)
   - Can it be parallelized?

7. WHAT'S PROVEN vs UNPROVEN:
   - Which techniques have RCT-level evidence of improving LLM forecasting?
   - Which are theoretically sound but untested with LLMs?
   - Which techniques HURT LLM performance? (Schoenegger 2025 showed CoT hurts)
```

## Expected Outcome
- Complete multi-step forecasting pipeline with exact prompts
- Ranked list of techniques by evidence strength and implementability
- Cost analysis: how many API calls for the full pipeline per market
- Implementation spec ready to hand to Claude Code
