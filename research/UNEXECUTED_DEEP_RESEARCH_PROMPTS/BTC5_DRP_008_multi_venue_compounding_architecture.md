---
id: BTC5_DRP_008
title: Proof-Carrying Multi-Venue Architecture for Compounding Small Edges
tool: CHATGPT_DEEP_RESEARCH
priority: P0
status: READY
created: 2026-03-23
---

# Proof-Carrying Multi-Venue Architecture for Compounding Small Edges

## Context

The user goal is not just "find one more signal." The real ask is:

**What architecture could turn tiny, fragile, small-capital edges into a path that
compounds fast enough to matter?**

The current repo is unusually strong on architecture ideas:

- `docs/architecture/proof_carrying_kernel.md`
- `docs/architecture/event_sourced_tape.md`
- `docs/architecture/strike_desk.md`
- `docs/architecture/promotion_ladder.md`
- `docs/architecture/intelligence_harness.md`
- `docs/architecture/qd_thesis_repertoire.md`
- `docs/architecture/temporal_edge_memory.md`
- `bot/proof_types.py`
- `bot/thesis_foundry.py`
- `bot/promotion_manager.py`
- `bot/strike_desk.py`

But these pieces are not yet fused into a fully operational cross-venue edge factory.
The repo is still too BTC5-concentrated, Alpaca is barely present, Kalshi is only
partially integrated, and the event tape / thesis foundry / QD repertoire are more
specified than realized.

The likely "big idea others miss" may not be one secret signal.
It may be a **learning-speed architecture** that:

- keeps multiple niches warm
- routes capital only through proof
- kills weak lanes quickly
- preserves weird promising niches through regime changes
- compounds bankroll by increasing edge density and capital velocity, not by one
  oversized bet

## Core Question

Using the repo's current kernel and constraints, design the fastest plausible path
from small balances (`$1K` Alpaca, `$1K` Polymarket, `$100` Kalshi) to a scalable
multi-venue system.

If there is no credible path to "large money fast" from this bankroll, say so directly
and define the fastest plausible compounding path instead.

## Research Questions

1. **What is the best niche portfolio, not single strategy?**
   Given the current repo, which 3-5 niches should be kept active or warming at all
   times? Candidate families include:
   - Polymarket maker microstructure
   - Polymarket event-market calibrated LLM lanes
   - Kalshi official-truth / weather / same-day event lanes
   - cross-venue parity and rule-divergence lanes
   - Alpaca-linked reference / hedge / intraday reaction lanes
   Identify the best repertoire, not just the flashiest idea.

2. **How should capital be segmented?**
   Derive a principled allocation for:
   - discovery capital
   - micro-live proving capital
   - reserve capital
   - convex tail experiments
   - hedge capital
   The answer must acknowledge tiny bankroll and path dependence.

3. **What architecture increases edge discovery velocity most?**
   Determine which architectural upgrades produce the biggest improvement in:
   - opportunity density
   - attribution quality
   - promotion accuracy
   - time-to-kill for bad ideas
   - time-to-scale for good ones

4. **How should the kernel become tri-venue?**
   Map how Alpaca, Polymarket, and Kalshi should enter the existing four-bundle flow:
   - Evidence Bundle
   - Thesis Bundle
   - Promotion Bundle
   - Learning Bundle
   Do not invent a second control plane.

5. **What is the mathematically correct promotion logic for tiny samples?**
   The current promotion ladder is strict. Determine the best small-capital proving
   design that balances:
   - false promotions
   - false kills
   - opportunity cost
   - bankroll survival

6. **What is the best regime-switching doctrine?**
   When one niche degrades, how should capital move?
   Compare:
   - static allocations
   - Thompson sampling / Bayesian bandits
   - Gittins-index style allocation
   - drawdown-contingent switching
   - value-of-information weighted exploration

## Formulas Required

Provide explicit formulas or authoritative references for:

- **Expected bankroll growth**
  `E[log_growth] = sum_i w_i * E[log(1 + r_i)]`
  with correlation awareness or a better robust-growth equivalent

- **Value of information**
  A formula for prioritizing experiments by expected decision improvement per dollar
  or per engineering hour

- **Edge discovery velocity**
  A measurable metric, not a slogan
  e.g. `validated_edges / week` or `promotion-quality-adjusted edge gain`

- **False-promotion cost**
  `FP_cost = capital_lost + time_lost + trust_damage`
  formalized as much as possible

- **Resource-aware niche score**
  combining edge estimate, recurrence, capacity, cost to test, and regime diversification

- **Adaptive allocation rule**
  for routing capital across niches under uncertainty

- **Kill / hold / promote posterior**
  based on small-sample evidence, not naive win rate alone

## Measurable Hypotheses

The research must test these or stronger replacements:

H1. A multi-niche repertoire beats a BTC5 monoculture on risk-adjusted growth and
    edge discovery velocity, even with tiny capital.

H2. The highest-ROI breakthrough in this repo is at least partly architectural:
    better evidence routing, measurement, and promotion reduce wasted cycles more
    than adding yet another unmeasured signal.

H3. Alpaca should enter the system in a specific role (execution, hedge, truth,
    or defer) that improves the overall repertoire, not just as a side account.

H4. One or two concrete architectural upgrades would materially reduce false
    promotions or false kills within 30 days.

H5. If the right answer is "the bankroll is too small for fast large-money scaling,"
    the research should say that and give the fastest credible compounding design.

## Required Deliverables

Return all of the following:

1. A **target operating doctrine** for the next 30, 90, and 180 days:
   - which niches stay live
   - which stay shadow
   - which are killed
   - where Alpaca fits

2. A **capital segmentation model** for the current bankroll across the three venues
   with explicit reasons and formulas

3. A **kernel integration map** showing how each venue and niche should flow through:
   - Evidence
   - Thesis
   - Promotion
   - Learning

4. A **minimum viable architecture backlog** in repo language:
   - what to build first
   - what not to build yet
   - what to delete or freeze

5. A **metric contract** for proving that the architecture is working:
   - edge discovery velocity
   - false-promotion rate
   - attribution coverage
   - execution-quality score
   - opportunity density
   - capital velocity
   - unresolved capital trapped

6. A blunt **reality verdict**:
   - Is there a plausible route from this bankroll to something materially larger?
   - If yes, through what sequence?
   - If no, what is the most honest version of the path?

## Failure Modes To Address Explicitly

- Architecture complexity outruns bankroll size
- Capital gets fragmented into too many weak experiments
- Promotion logic is too strict and kills real edges before they mature
- Promotion logic is too loose and blows up small capital
- Alpaca integration becomes a distraction rather than multiplier
- Multiple niches share hidden correlation and fail together

## Direct Repo Integration Targets

- `bot/thesis_foundry.py`
- `bot/strike_desk.py`
- `bot/promotion_manager.py`
- `bot/proof_types.py`
- `bot/event_tape.py`
- `docs/architecture/proof_carrying_kernel.md`
- `docs/architecture/event_sourced_tape.md`
- `docs/architecture/strike_desk.md`
- `docs/architecture/promotion_ladder.md`
- `docs/architecture/qd_thesis_repertoire.md`
- `docs/architecture/temporal_edge_memory.md`
- `scripts/run_intelligence_harness.py`
- `scripts/run_structural_profit_cycle.py`

## Hard Constraints

- Do not propose a second control plane
- Do not rely on giant leverage, hidden credit, or unrealistic borrow
- Do not assume away fees, slippage, fill uncertainty, or legal constraints
- Respect the repo's proof-to-capital philosophy
- If the true bottleneck is architecture and measurement, say that clearly
