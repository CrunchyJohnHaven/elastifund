# Tweet 06 — Anti-Anchoring
**Pillar:** Agentic Architecture
**Priority:** Medium (design insight, counterintuitive)

---

Design rule for LLM-based trading: never show the model the current market price.

Anchoring bias is well-documented in human forecasting. It's worse in LLMs. Show Claude that a market is at 73% and its "independent" estimate clusters around 70-76%.

Our ensemble (Claude + GPT-4.1-mini + Llama 3.3) estimates probability blind. The market price enters only at the sizing stage, never the estimation stage.

If your edge IS the model's estimate, you can't let the market contaminate it.

---

**Notes:** Architectural insight that most bot builders haven't considered. Schoenegger 2025 has supporting evidence.
