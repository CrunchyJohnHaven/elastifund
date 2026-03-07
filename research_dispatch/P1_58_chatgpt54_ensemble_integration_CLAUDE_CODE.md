# P1-58: ChatGPT 5.4 Integration for Ensemble
**Tool:** CLAUDE_CODE
**Status:** READY
**Priority:** P1 — New frontier model = potential calibration improvement. Must test immediately.
**Expected ARR Impact:** +10-25% (if GPT-5.4 is better calibrated than GPT-4o-mini in ensemble)

## Background
ChatGPT 5.4 just launched. This is potentially a significantly better forecasting model than GPT-4o-mini. If its probability estimates are better calibrated, it could dramatically improve our ensemble quality.

## Task

1. **Add GPT-5.4 as an ensemble member:**
   ```python
   class GPT54Client(ModelClient):
       model = "gpt-5.4"  # verify exact API model string
       # Check: is it available via OpenAI API? What's the pricing?

       def estimate_probability(self, question: str, context: str = "") -> dict:
           """Same anti-anchoring prompt as other models."""
   ```

2. **Head-to-head benchmark on 532 markets:**
   - Query GPT-5.4 on all 532 resolved markets (use cached questions)
   - Compare Brier score vs: Claude Haiku, GPT-4o-mini, Grok
   - If GPT-5.4 has better calibration, it should get higher weight in ensemble

3. **Cost-benefit analysis:**
   - GPT-5.4 pricing vs GPT-4o-mini
   - If 5× more expensive: use only for high-value markets (top 20 by score)
   - If similar price: replace GPT-4o-mini entirely

4. **Optimal ensemble with GPT-5.4:**
   - Test: Claude + GPT-5.4 (2 models)
   - Test: Claude + GPT-5.4 + Grok (3 models)
   - Test: Claude + GPT-5.4 + GPT-4o-mini + Grok (4 models)
   - Find the combination that minimizes Brier score per dollar of API cost

5. **Special GPT-5.4 capabilities:**
   - Does GPT-5.4 have better reasoning? Test with complex multi-step forecasting prompts
   - Does it handle the superforecaster pipeline (P0-50) better than Haiku?
   - Is it better at specific categories? (Politics? Economics?)
   - Test with and without chain-of-thought (Schoenegger showed CoT hurts for some models — does it help GPT-5.4?)

## API Setup
- Verify GPT-5.4 API availability and model string
- Check pricing at https://openai.com/api/pricing
- Add to .env: `OPENAI_MODEL_ENSEMBLE=gpt-5.4` (or whatever the model string is)

## Files to Modify
- NEW or MODIFY: `src/gpt_client.py` — add GPT-5.4 configuration
- MODIFY: `src/ensemble.py` — add GPT-5.4 as ensemble member
- MODIFY: `backtest/engine.py` — add GPT-5.4 to benchmarking suite

## Expected Outcome
- GPT-5.4 benchmarked against all existing models on our dataset
- Decision: include in ensemble, replace GPT-4o-mini, or skip
- If included: optimal ensemble weights determined
- Cost analysis: is the improvement worth the additional API spend?
