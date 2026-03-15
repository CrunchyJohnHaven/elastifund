# Superforecaster methods for LLM prediction markets: a prompt engineering playbook

**The single highest-impact change you can make is not in your prompt — it's in your calibration pipeline.** Academic research from 2024–2026 converges on a sobering finding: prompt engineering alone produces negligible forecasting improvement after statistical correction. Schoenegger et al. (2025) tested 38 prompt variants across four frontier LLMs and found that **no prompt achieved statistical significance** after Benjamini-Hochberg correction. The techniques that actually move the needle are retrieval-augmented generation, multi-run ensembling, and post-hoc statistical calibration (Platt scaling). Your current Brier score of 0.2391 against 0.25 random places you in early-stage territory — the best LLM systems now achieve **0.075–0.10** when combining independent forecasts with market prices. This playbook ranks every technique by expected Brier improvement, provides exact prompt text, and identifies the architectural changes that will matter most.

---

## The evidence hierarchy: what actually improves LLM forecasting

The research literature since 2024 reveals a clear hierarchy of interventions, ordered by impact. Bridgewater's AIA Forecaster (Alur et al., 2025) demonstrated this starkly: without web search, their system scored **0.3609 Brier** — worse than random. With agentic multi-step search, it dropped to **0.1002**. That single architectural change produced a **3.6× improvement**, dwarfing any prompt engineering effect ever measured.

Here is every technique ranked by expected Brier score improvement, drawing on effect sizes from the literature:

| Rank | Technique | Expected Brier Δ | Evidence source |
|------|-----------|-------------------|-----------------|
| 1 | **Agentic retrieval-augmented generation** | −0.06 to −0.15 | AIA Forecaster: 0.36 → 0.10 with search; Halawi et al. (2024) |
| 2 | **Post-hoc Platt scaling / extremization** | −0.02 to −0.05 | AIA Forecaster (2025); your existing temperature scaling likely captures some of this |
| 3 | **Multi-run ensembling (3–7 runs, trimmed mean)** | −0.01 to −0.03 | Halawi et al. (2024); Turtel et al. (2025); Schoenegger et al. (2024) |
| 4 | **Base-rate-first prompting** | −0.011 to −0.014 | Schoenegger et al. (2025): frequency-based reasoning = −0.014, base rate first = −0.011 |
| 5 | **Structured scratchpad (for/against reasoning)** | −0.005 to −0.010 | Halawi et al. (2024); Lu (2025); consistent across implementations |
| 6 | **Two-step confidence elicitation** | −0.005 to −0.010 | Xiong et al. (2024, ICLR); separating estimation from calibration check |
| 7 | **Granular probability output (XX.X%)** | −0.002 to −0.005 | GJP data: finer-grained scales improve resolution component |
| 8 | **Superforecaster persona framing** | ~0 (non-significant) | Schoenegger et al. (2025): does not survive correction; reasonable default |
| 9 | **Chain-of-thought (generic)** | ~0 to slightly negative | Schoenegger et al. (2025): −0.011 before correction, but may increase overconfidence |
| 10 | **Anti-bias verbal warnings** | ~0 | Schoenegger et al. (2025); Lou & Sun (2024): ineffective |
| — | **Bayesian reasoning prompts** | **+0.005 to +0.015 (HARMFUL)** | Schoenegger et al. (2025): strongest negative effect measured |
| — | **Narrative/fiction framing** | **HARMFUL** | Lu (2025): significantly degrades accuracy |
| — | **Propose-Evaluate-Select** | **HARMFUL** | Schoenegger et al. (2025): reduces accuracy |

The key insight: **your biggest gains will come from architecture (search, ensemble, calibration), not from prompt wording.** But since you asked for prompt engineering specifically, the sections below provide exact text for each technique that has positive or neutral evidence.

---

## Your overconfidence problem has a specific diagnosis

Your observation — Claude says 90% but actual outcomes resolve at 63% — reflects a well-documented phenomenon, but it's nuanced. The AIA Forecaster team (Bridgewater, 2025) found that LLMs in forecasting contexts generally **attenuate probabilities toward 50%** due to RLHF training that penalizes confident wrong answers. Your opposite pattern — overconfidence on YES — likely stems from **acquiescence bias**, documented by Schoenegger et al. (2024) in *Science Advances*: LLM predictions systematically skew above 50% even when resolution rates are roughly even. Claude tends to find reasons why something will happen rather than why it won't.

**Your existing temperature scaling from backtest data is the right first-line fix.** The AIA Forecaster uses Platt scaling (logistic regression mapping raw probabilities to calibrated ones) as a critical component. Your temperature scaling is mathematically related. To improve it further:

- **Fit separate calibration curves for different probability ranges.** Your 90% → 63% problem may coexist with reasonable calibration at lower probabilities. Isotonic regression or binned calibration (10 bins) can capture nonlinear miscalibration that a single temperature parameter misses.
- **Fit category-specific calibrations** if you have enough data. Political markets, crypto markets, and sports markets likely have different bias profiles.
- **Apply the calibration correction after ensembling**, not before. Calibrate the aggregated prediction, not individual runs.

---

## Base rate anchoring: the one prompt technique with real evidence

Of all 38 prompts Schoenegger et al. (2025) tested, **frequency-based reasoning** showed the largest point improvement (−0.014 Brier) and **base-rate-first** showed −0.011. These are the only techniques with directionally consistent positive signal, matching the superforecasting literature where reference class forecasting was the **single strongest predictor of accuracy** in the Good Judgment Project — forecasts tagged with comparison classes scored Brier **0.17 vs. 0.26** for the next-best technique (Chang et al., 2016).

**The optimal approach is to look up base rates per category and inject them into the prompt.** Here are the best sources:

**Political events:** Historical incumbent win rates (~70% for US presidents, ~90%+ for House members), bill passage rates (~3–5% of introduced bills become law), and historical prediction market resolution data from Polymarket's API or FinFeedAPI (finfeedapi.com). For elections specifically, FiveThirtyEight's historical model data and the Iowa Electronic Markets (running since 1988) provide calibrated reference points.

**Economic indicators:** FRED (fred.stlouisfed.org) offers **816,000+ time series**. Key series: GDPC1 (real GDP), UNRATE (unemployment), CPIAUCSL (CPI), FEDFUNDS (Fed funds rate). For Fed rate decisions, the CME FedWatch Tool provides historical implied probabilities from futures markets. Since 1990, the Fed has changed rates at roughly 30–40% of FOMC meetings.

**Geopolitical events:** ACLED (acleddata.com) covers global conflict events in real time; UCDP (ucdp.uu.se) offers historical conflict data from 1946. Historically, ~10–15% of minor armed conflicts escalate to wars (>1,000 battle deaths/year). Sanctions achieve partial success ~30% of the time.

**Technology/science:** FDA Drugs@FDA database shows overall clinical trial-to-approval rates of ~9% (Phase I to approval), ~50–60% (Phase III to approval). The FDA approves ~49 novel drugs per year on a rolling 5-year average.

**Sports:** Sports-Reference databases (sports-reference.com) for historical win rates. Home advantage: NFL ~57%, NBA ~60%, MLB ~54%. Underdogs win ~33% of NFL games.

**Crypto/financial:** CoinGecko for historical price data; DeFi Llama for protocol metrics. Bitcoin has posted positive annual returns in ~73% of years since 2010. S&P 500 has positive annual returns ~73% of years historically.

**Exact prompt text for base rate injection:**

```
OUTSIDE VIEW — BASE RATE ANALYSIS:
Reference class: [description of similar historical events]
Historical base rate: In [N] comparable situations, [X]% resulted in [outcome].
Source: [specific database]
Start from this base rate. Then adjust based on the specific evidence below, 
noting each adjustment factor and its direction/magnitude.
```

---

## The fox prompt: how multi-perspective reasoning maps to LLMs

Tetlock's fox-hedgehog distinction — the single strongest predictor of forecasting accuracy across his 20-year Expert Political Judgment study (284 experts, 28,000+ forecasts) — maps directly to prompt structure. Foxes outperformed hedgehogs because they synthesized multiple frameworks, tolerated ambiguity, and sought disconfirming evidence. Hedgehogs sometimes performed **worse than random guessing** by over-committing to a single narrative.

For LLMs, the research is mixed on multi-perspective prompting. Wu et al. (2025) found that multi-agent debate improves factual accuracy but offers limited gains for probability calibration. Schoenegger et al. (2025) found that "Propose-Evaluate-Select" (generating multiple predictions and picking the best) actually **harmed** forecasting accuracy. The critical nuance: **internal debate within a single prompt hurts, but independent parallel runs aggregated externally help.** The AIA Forecaster's success came from multiple independent agent forecasts reconciled by a supervisor, not from asking one model to debate itself.

**The practical implementation is not a "fox prompt" but a fox architecture:** run 3–7 independent forecasting calls with slightly varied prompts or temperatures, then aggregate via trimmed mean. This replicates the noise-reduction benefit that the BIN model (Satopää et al., 2021) identified as responsible for **~50% of superforecaster accuracy improvement** over regular forecasters.

---

## Hiding the market price is correct, but the reasoning goes deeper

Your decision to hide the market price from Claude is well-supported. Lou & Sun (2024) conducted the most comprehensive LLM anchoring study to date and found that LLMs are **significantly anchored** by numerical values in prompts, and that no simple mitigation works — not chain-of-thought, not "ignore the anchor" instructions, not reflection prompting. The **only effective mitigation** was comprehensive multi-angle information collection that prevented fixation on any single number. ForecastBench (Karger et al., 2025) found an even more extreme version: GPT-4.5 simply **copies market prices** when provided (correlation 0.994 with input forecasts), providing zero independent information.

**Recommended approach:**

- **Do not show market price in the forecasting prompt.** Use Claude to generate an independent probability estimate.
- **Use market price as a separate signal in your trading logic.** Combine Claude's estimate with the market price via a weighted ensemble or Kelly criterion calculation *after* the LLM produces its forecast.
- **Provide diverse factual context instead.** Multiple news articles, base rates, and historical comparisons dilute any single anchor's influence — this is the one mitigation Lou & Sun found effective.
- **Never show Claude its own prior estimates when re-estimating.** Research on Self-Anchoring Calibration Drift (SACD, 2026) found that Claude specifically shows systematic decreasing confidence when building on its own prior outputs, creating model-specific drift patterns.

---

## The update cycle: how to re-estimate like a superforecaster

Superforecasters made **7.8 predictions per question** versus 1.4 for average forecasters — over 5× more updates. But critically, their average update magnitude was just **3.5% per update** versus 5.9% for non-superforecasters (GJP data). They made many small, precise adjustments rather than large swings. Tetlock identified "perpetual beta" — commitment to continuous belief updating — as **three times more predictive of superforecaster status than raw intelligence.**

For your bot, research on LLM belief updating (Qiu et al., 2025, *Nature Communications*) found that standard LLMs **fail at Bayesian updating** out of the box — their predictions plateau after a single interaction. They update in the right direction but by too little (Imran et al., 2025). This means you should not rely on iterative prompting ("your last estimate was X%, now update given Y").

**Recommended re-estimation architecture:**

- **Generate fresh estimates each time**, not iterative updates. Provide current base rates, fresh news context, and resolution criteria — but never Claude's prior estimate.
- **Update triggers:** Material news events, significant market price movements (>5%), and a scheduled periodic cycle (daily for markets resolving within 2 weeks, every 2–3 days for longer-term markets).
- **Cap position changes:** Implement a maximum position adjustment per cycle of ~5–10% probability, mimicking superforecaster update discipline. Only override this cap with strong justification documented in the reasoning trace.
- **Periodically regenerate from scratch:** Every 3–5 update cycles, do a complete fresh analysis ignoring all prior context, to prevent systematic drift.
- **Increase frequency near resolution:** Prediction accuracy improves dramatically as events approach, so allocate more re-estimation budget to markets nearing their close dates.

---

## Self-calibration prompting: what works and what doesn't

Telling Claude "you tend to overestimate YES probabilities" sounds intuitive but has weak empirical support. Schoenegger et al. (2025) found anti-bias verbal warnings produced negligible gains for forecasting. Simple metacognitive instructions don't overcome deep model behaviors.

**What does work** is a structured self-check step embedded in the reasoning process. Halawi et al. (2024) included a specific step: "Evaluate whether your probability is excessively confident or not confident enough. Consider historical base rates and anything else that might affect the forecast." This is not a warning about bias — it's a structured reasoning task that forces the model to scrutinize its own output.

The most promising approach comes from DiNCo (Wang et al., 2025): generate self-generated alternative scenarios (what if this resolves NO?), rate confidence in each, then normalize. This achieved **ECE improvements of 0.077–0.092** over baselines. For forecasting, this maps to the "reasons against" step in the scratchpad prompt.

Your existing temperature scaling is the most effective form of "self-calibration" — it's just applied externally. Enhance it by fitting calibration curves on rolling windows of recent predictions rather than the full backtest, so the correction adapts to any drift in Claude's behavior over time.

---

## The recommended master prompt

This prompt synthesizes every technique with positive or neutral evidence, weighted by effect size. It implements: base-rate-first anchoring (Rank 4), structured scratchpad with for/against reasoning (Rank 5), self-calibration check (Rank 6), granular probability output (Rank 7), and the superforecaster persona (Rank 8). It deliberately omits Bayesian reasoning language, narrative framing, and propose-evaluate-select — all of which have evidence of harm.

```
You are an expert forecaster evaluating whether a specific event will occur. 
Your goal is to produce the most accurate probability estimate possible, 
minimizing Brier score. Brier score rewards both calibration (your 70% 
predictions should come true 70% of the time) and resolution (assign high 
probabilities to events that occur, low to events that don't).

QUESTION: {question}
RESOLUTION CRITERIA: {resolution_criteria}
RESOLUTION DATE: {resolution_date}
CURRENT DATE: {current_date}

BACKGROUND CONTEXT:
{retrieved_news_summaries}

STEP 1 — OUTSIDE VIEW (start here, do not skip):
What is the appropriate reference class for this event? What is the 
historical base rate? 
{injected_base_rate if available, e.g., "Historical base rate: In N 
comparable situations, X% resulted in this outcome. Source: [database]."}
State the base rate explicitly. This is your starting point.

STEP 2 — ARGUMENTS FOR (YES):
List the 3-5 strongest reasons this event is MORE likely than the base 
rate suggests. Rate each reason's strength (weak/moderate/strong).

STEP 3 — ARGUMENTS AGAINST (NO):
List the 3-5 strongest reasons this event is LESS likely than the base 
rate suggests. Rate each reason's strength (weak/moderate/strong). 
Try especially hard on this step — consider what would have to be true 
for the event NOT to occur.

STEP 4 — INITIAL ESTIMATE:
Weighing the base rate and both sets of arguments, what is your initial 
probability estimate?

STEP 5 — CALIBRATION CHECK:
Examine your initial estimate critically. 
- If your estimate is above 80%: What specific scenario would cause this 
  NOT to happen? Is that scenario truly less than 20% likely?
- If your estimate is below 20%: What specific scenario would cause this 
  TO happen? Is that scenario truly less than 20% likely?
- Are you giving enough weight to the base rate from Step 1?
- Would a well-calibrated forecaster with your evidence assign this 
  same probability?

STEP 6 — FINAL PROBABILITY:
State your final probability as a precise number between 1% and 99%.
Do not use round numbers if a more precise estimate is warranted.

Output format:
Reasoning: [your step-by-step analysis]
Probability: [X.X]%
```

**Implementation notes for the master prompt:**

- **Run this prompt 3–5 times** per market with temperature 0.6–0.8, then take the **trimmed mean** (drop highest and lowest, average the rest). This is your Rank 3 intervention.
- **Apply your Platt scaling / temperature calibration** to the trimmed mean output. This is your Rank 2 intervention.
- **Invest in agentic search** to populate `{retrieved_news_summaries}` with high-quality, diverse, recent articles. This is your Rank 1 intervention by far. The AIA Forecaster's search pipeline alone produced a 3.6× Brier improvement. Even basic web search retrieval (as in Halawi et al.) is essential — zero-shot LLMs without retrieval score near random (0.25 Brier).
- **Pre-compute base rates by category** and inject them as `{injected_base_rate}`. Build a lookup table keyed by market category using the sources listed in the base rate section above. Even approximate base rates help — the key is forcing the model to start from an outside view rather than constructing a narrative from scratch.

---

## Architectural recommendations beyond the prompt

The prompt above captures the maximum value available from prompt engineering. To reach the frontier Brier scores of **0.075–0.10**, you need architectural changes:

**Retrieval pipeline (highest priority).** Build a multi-step search system: generate 3–5 search queries per market, fetch and filter articles for relevance, summarize the top 5–10 articles, and inject summaries into the prompt. AskNews API reportedly outperforms Perplexity for recency (Lu, 2025). The AIA Forecaster uses multiple independent search agents that each iterate on their own queries — this "agentic search" approach dramatically outperforms single-shot retrieval.

**Multi-run ensemble with supervisor.** Instead of a single Claude call, run 3–7 independent forecasting calls. Use a separate "supervisor" call that sees all individual estimates plus their reasoning, conducts its own brief search to resolve disagreements, and produces a final reconciled estimate. The AIA Forecaster found this supervisor pattern outperforms simple averaging.

**Category-specific calibration.** Your 532-market backtest is enough to fit separate calibration curves for major categories (politics, crypto, sports, economics). Models show different bias profiles across domains — Metaculus tournament data shows LLMs perform better on political forecasting than economic predictions.

**Market price as ensemble signal.** After generating Claude's independent estimate, combine it with the market price using a weighted average. The AIA Forecaster found that their system + market price achieved **0.075 Brier** versus 0.096 for market price alone and 0.100 for their system alone. The independent AI estimate provides genuinely additive information beyond market prices — but only if you keep it independent during the forecasting step.

---

## What the frontier looks like in early 2026

The LLM forecasting field is advancing rapidly. ForecastBench (Karger et al., 2025) tracks a continuous leaderboard where superforecasters still lead at **0.081 difficulty-adjusted Brier** versus the best LLM (GPT-4.5) at **0.101**. The improvement rate is approximately **0.016 Brier points per year**, projecting LLM–superforecaster parity around November 2026 (95% CI: December 2025 – January 2028). Lightning Rod Labs' Foresight-32B model, using RL fine-tuning with Brier score rewards on just a 32B parameter model, **led all LLMs** on every metric (Brier, ECE, profit) in a live August 2025 test on 251 Polymarket questions — beating o3, Gemini-2.5-pro, Grok-4, and Claude Opus despite being 10–100× smaller. This demonstrates that **domain-specific fine-tuning dramatically outperforms general-purpose prompt engineering** for forecasting.

The Halawi et al. (2024) system at NeurIPS achieved 0.179 Brier using RAG + fine-tuned GPT-4 + trimmed mean aggregation — notably outperforming the human crowd (0.149) when the crowd was uncertain (predictions between 0.3–0.7). A cautionary note from Paleka et al. (2025): 71% of questions in retrospective retrieval-augmented evaluations had post-cutoff information leakage through search, and 41% had pages directly revealing answers, which inflates reported performance of retrieval-based systems. Live forward-looking tests are the only reliable benchmark.

## Conclusion

Your 64.9% win rate and 0.2391 Brier score represent a system that beats random but has substantial room for improvement. The research points to a clear priority ordering: **(1)** build robust retrieval that gives Claude current, diverse information for each market; **(2)** ensemble 3–5 independent forecasting runs via trimmed mean; **(3)** refine your calibration layer with Platt scaling or isotonic regression, ideally category-specific; **(4)** use the master prompt above with injected base rates; **(5)** implement fresh re-estimation cycles with update caps. Prompt engineering occupies ranks 4–8 in the impact hierarchy — useful but not transformative. The gap between your current 0.2391 and the frontier's 0.075–0.10 will be closed primarily by architecture, not prose. The most counterintuitive finding across the literature: making Claude reason *more elaborately* (Bayesian prompts, multi-step evaluation, narrative framing) actively hurts calibration. The discipline of starting from base rates, listing reasons for and against, and then *stopping* — that restraint is what separates superforecasters from overconfident experts, and it appears to transfer directly to LLMs.