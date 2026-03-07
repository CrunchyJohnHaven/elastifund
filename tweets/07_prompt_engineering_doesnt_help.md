# Tweet 07 — Prompt Engineering for Forecasting
**Pillar:** Calibration & Probability
**Priority:** Medium (contrarian, citable)

---

Prompt engineering mostly doesn't improve LLM forecasting accuracy. (Schoenegger 2025)

Chain-of-thought: hurts calibration.
Bayesian reasoning prompts: no improvement.
Superforecaster personas: no improvement.

One technique works: base-rate-first prompting. -0.014 Brier score improvement.

Everything else is noise after you control for it.

What actually moves the needle: Platt calibration (-0.02 to -0.05 Brier), ensemble averaging (-0.01 to -0.03), and agentic RAG search (Brier 0.36 → 0.10).

Spend time on infrastructure, not prompts.

---

**Notes:** Contrarian take backed by academic evidence. Will get engagement from the prompt engineering crowd.
