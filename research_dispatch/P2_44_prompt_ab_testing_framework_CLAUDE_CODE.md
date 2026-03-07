# P2-44: Prompt A/B Testing Framework
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P2 — Important for continuous improvement but not blocking anything
**Expected ARR Impact:** +5-15% (incremental prompt improvements compound over time)

## Background
We've applied one major prompt fix (anti-anchoring + base-rate-first), but we have no systematic way to test prompt variants against each other. Schoenegger (2025) showed most prompt engineering techniques HURT calibration except base-rate-first. We need an A/B framework to test this empirically on our data.

## Task

Build a prompt A/B testing harness into the backtest engine:

1. **Prompt registry:**
   ```python
   PROMPT_VARIANTS = {
       "v1_baseline": "Estimate the probability that the following event occurs...",
       "v2_base_rate_first": "First, identify the base rate for this type of event...",
       "v3_explicit_debias": "You tend to be overconfident on YES outcomes. Correct for this...",
       "v4_structured_reasoning": "Step 1: Base rate. Step 2: Evidence. Step 3: Adjustment...",
       "v5_contrarian": "Consider arguments AGAINST the most obvious outcome first...",
       "v6_calibrated_output": "Express your estimate on a scale where 70% means...",
   }
   ```

2. **A/B test runner:**
   - Take a sample of 100 resolved markets
   - Run each prompt variant against the sample
   - For each variant, measure: Brier score, win rate, calibration error, edge distribution
   - Output comparison table with statistical significance tests
   - Use paired comparison (same markets for each variant) to reduce noise

3. **Automated prompt tournament:**
   - Run all variants → rank by Brier score
   - Top 2 variants advance to larger 500-market test
   - Winner becomes the new production prompt
   - Log all results for historical comparison

4. **Continuous testing pipeline:**
   - Every week, auto-run the current production prompt vs one challenger on the latest 50 resolved markets
   - If challenger wins significantly (p < 0.05), flag for review
   - Never auto-deploy — always require manual review of prompt changes

## Files to Create/Modify
- NEW: `backtest/prompt_ab_test.py` — A/B testing harness
- NEW: `backtest/prompt_registry.py` — versioned prompt storage
- MODIFY: `backtest/engine.py` — accept prompt parameter for backtest runs

## Expected Outcome
- Systematic way to evaluate prompt changes before deploying
- Historical record of what prompt variants work and don't
- Prevents regression: new prompts must beat the incumbent to ship
