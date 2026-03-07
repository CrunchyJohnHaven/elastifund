# P0-72: Master Forecasting Prompt v2 — Integrating RAG + Superforecaster Pipeline
**Tool:** CLAUDE (claude.ai — conversational, NOT Claude Code)
**Status:** READY
**Priority:** P0 — The prompt is the core of the entire system. Every 0.01 Brier improvement here multiplies across every trade.
**Expected ARR Impact:** +10–20% (prompt quality directly determines win rate)

## Prompt (paste into Claude.ai conversation)

```
I'm building a prediction market trading system that uses you (Claude) to estimate probabilities of binary events. I need you to help me design the OPTIMAL forecasting prompt — the one that makes you most accurate.

CURRENT SYSTEM:
- You analyze Polymarket questions and estimate P(YES)
- You do NOT see the market price (prevents anchoring)
- Your estimate is calibrated with Platt scaling (A=0.5914, B=−0.3977)
- Current Brier score: 0.217 (calibrated), 0.245 out-of-sample
- 532-market backtest: 68.5% win rate
- Known biases: you're overconfident on YES (says 90% → actual 63%), acquiescence bias

CURRENT PROMPT (simplified):
"Estimate the probability this resolves YES. Start with the base rate. Consider evidence for and against. Be aware you tend to overestimate YES probabilities. Give a precise number."

WHAT I'M ADDING:
1. Real-time web search results (Agentic RAG) — you'll receive 3-5 search result snippets as context
2. Category-specific calibration (different Platt parameters for politics vs weather vs economic)
3. Multi-model ensemble (your estimate gets averaged with GPT-5.4 and Grok)

SUPERFORECASTER RESEARCH FINDINGS (from our playbook):
- Base-rate-first is the ONLY prompting technique proven to help (−0.014 Brier)
- Chain-of-thought HURTS calibration (+0.005 to +0.015 worse Brier)
- Bayesian reasoning prompts HURT calibration
- Narrative framing HURTS calibration
- Multi-run averaging helps (3-7 runs, take median)
- Two-step confidence elicitation helps (estimate, then reconsider)
- Structured scratchpad helps slightly
- Acquiescence bias: you skew YES — explicit debiasing instruction helps
- SACD drift: NEVER show you your own prior estimates when re-estimating

YOUR TASK:
Design the optimal forecasting prompt for yourself. The prompt should:

1. Incorporate web search context (RAG results) WITHOUT over-relying on them
2. Use base-rate-first technique (proven)
3. Include structured reasoning that DOESN'T trigger chain-of-thought calibration damage
4. Explicitly debias for YES overconfidence
5. Work across categories (politics, weather, economics, geopolitical)
6. Produce a precise numerical probability (0.01 to 0.99)
7. Include a confidence level that can be used for position sizing
8. Be SHORT enough to not waste tokens (you'll run this 100+ times per day)

CRITICAL CONSTRAINT:
The research says elaborate prompts HURT your calibration. So the prompt needs to be structured but MINIMAL. No chain-of-thought, no "think step by step", no elaborate reasoning chains. Keep it tight.

WHAT I WANT YOU TO PRODUCE:

A. The EXACT prompt template (with {placeholders} for question, category, web_context)

B. A worked example: apply the prompt to "Will the EU impose new tariffs on US goods by April 2026?" with fake web search results

C. An anti-pattern list: specific things that should NEVER be in the prompt (based on the research findings above)

D. Your honest assessment: what's the Brier score floor you think you can achieve with this prompt + RAG? Where are you fundamentally limited?

E. A variant for "high-information" markets (lots of RAG results) vs "low-information" markets (no relevant search results found)
```

## How to Use Results

1. Take Claude's self-designed prompt template
2. Test it on 50 resolved markets (using cached questions + simulated web search results)
3. Compare Brier score vs current prompt
4. If better → deploy to `src/claude_analyzer.py`
5. Store the anti-pattern list in `research/` as a reference

## Follow-Up Prompt (after initial design)

```
Now let me test your prompt. Here are 10 prediction market questions with web search results. Use the exact prompt template you designed. Give me your probability estimates.

[INSERT 10 QUESTIONS WITH FAKE WEB CONTEXT]

After estimating all 10, I'll tell you the actual outcomes so we can measure your Brier score with this new prompt.
```

## SOP
Store final prompt template in `research/master_forecast_prompt_v2.md`. Update `src/claude_analyzer.py` with the new prompt. Update COMMAND_NODE.md with version increment and new Brier targets.
