# P2-15: A/B Test 5 Prompt Variants Against 532 Markets
**Tool:** CLAUDE_CODE
**Status:** READY
**Expected ARR Impact:** +5-15%

## Task
Build an A/B testing framework for prompt variants:

### Variant A (Current — Control)
Anti-anchoring, first-principles estimation, no market price

### Variant B (Superforecaster)
"You are a superforecaster trained in Tetlock's methodology. First identify the reference class, then adjust from the base rate..."

### Variant C (Devil's Advocate)
Two-step: first estimate, then argue against your own estimate, then give final estimate

### Variant D (Decomposition)
"Break this question into 3-5 sub-questions. Estimate each sub-question probability. Combine to get final estimate."

### Variant E (Calibration-Aware)
"Historical analysis shows you tend to overestimate YES probabilities by 20-30%. Adjust your estimate accordingly. When your gut says 80%, the actual rate is closer to 55%."

## Implementation
1. Run each variant on all 532 markets (use caching per variant)
2. Compute win rate, Brier score, P&L for each
3. Statistical significance test (bootstrap confidence intervals)
4. Select best variant for production

## Cost
~$7.50 per variant × 5 = ~$37.50 total API cost
