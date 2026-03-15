# Tweet 10 — Agentic RAG for Forecasting
**Pillar:** Agentic Architecture
**Priority:** Medium (frontier research, impressive numbers)

---

LLM forecasting without web search: Brier score 0.36
LLM forecasting with agentic RAG: Brier score 0.10

That's a 3.6x improvement from one architectural decision. (Bridgewater AIA Forecaster, 2025)

Frontier prediction systems hit Brier 0.075-0.10 by combining:
- LLM probability estimate (blind to market price)
- Agentic web search for base rates and recent evidence
- Platt calibration on historical performance
- Market price as a Bayesian prior in a second stage

The model's job isn't to know the answer. It's to know what to look up, how to weight it, and how wrong it's been before.

---

**Notes:** The Bridgewater reference adds institutional credibility. The 3.6x number is the hook. Could expand into a thread on two-stage estimation architecture.
