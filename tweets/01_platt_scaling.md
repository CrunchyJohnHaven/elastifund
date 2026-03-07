# Tweet 01 — Platt Scaling
**Pillar:** Calibration & Probability
**Priority:** High (foundational concept, establishes quantitative credibility)

---

Claude says 90% confident. Actual hit rate: 71%.

LLMs are systematically overconfident. Fix:

calibrated = 1 / (1 + exp(-(A·logit(raw) + B)))

Fitted on 532 resolved markets:
A = 0.5914, B = -0.3977

OOS Brier improvement: 0.2862 → 0.2451

Temperature-scale your models or you're trading on noise.

---

**Notes:** Strong opener. Establishes that we test rigorously and know the math. The 90%→71% gap is immediately surprising. Link to repo if live.
