# Deep Research Packet 04: Priorities And Open Questions

This is an attachment packet, not a new source of truth.

Canonical sources:

- `research/deep_research_output.md`
- `research/jj_assessment_dispatch.md`
- `research/edge_backlog_ranked.md`
- `docs/strategy/combinatorial_arb_implementation_deep_dive.md`
- `docs/ops/TRADING_LAUNCH_CHECKLIST.md`

## Priority Frame

The repo does not need generic brainstorming. It needs research that sharpens decisions in the next few stages of execution.

The best research themes are:

1. fast-flow restart quality
2. maker execution and fillability
3. structural-arb gate measurement
4. small-capital deployment discipline
5. scaling paths only after the above are credible

## Highest-Value Research Questions

### 1. Wallet-Flow Validity

- Which wallet behaviors are actually predictive versus noisy?
- How should wallet scoring be refreshed and decayed?
- What signal definitions are robust enough for cold start and thin data?

### 2. LMSR Edge Quality

- In which market regimes does the LMSR/Bayesian blend materially outperform plain price-following?
- What thresholds survive realistic execution and spread assumptions?
- How should this lane be ranked against wallet-flow for the first fast-flow restart?

### 3. Maker Fill And Dwell

- What fill-rate assumptions are realistic for `$5` passive orders on Polymarket?
- How long do exploitable mispricings persist in practice?
- Which strategies collapse once queue position and partial-fill rollback are modeled honestly?

### 4. A-6 Empirical Promotion

- Is the current `0.95` gate too strict, or is the lane genuinely sparse?
- What underround threshold is defensible at small size?
- What settlement paths are operationally credible for the repo's actual tooling?

### 5. B-1 Precision And Density

- Which deterministic market families are dense enough to matter?
- What labeling and auditing design can actually get to `>=85%` precision?
- Is the current first-1,000-market zero-density result a real dead end or a scope-definition problem?

### 6. Fast-Flow Execution Rails

- Which runtime, latency, and post-only constraints matter most for paper-to-shadow promotion?
- How should lane health be surfaced so restart failures are obvious, not silent?
- What minimal evidence should be required before micro-live?

### 7. Small-Capital Scaling

- Which lanes scale cleanly from roughly `$1K` to `$10K` to `$100K`?
- Which lanes are interesting at research scale but economically irrelevant at current bankroll?
- Where does fee drag or utilization become the dominant constraint?

## Lower-Value Research Right Now

These are less useful unless they are tied directly to near-term execution:

- broad speculative strategy ideation with no promotion path
- strategies that assume high-frequency infra not present in the repo
- strategies that require large capital to matter
- abstract research that ignores current gating evidence

## Desired Research Output Style

The most helpful deep research output should:

- use the repo's actual lane names
- distinguish `paper`, `shadow`, `micro-live`, and `live`
- treat fillability and precision as first-class constraints
- separate "interesting hypothesis" from "next executable step"
- call out explicit kill criteria and evidence thresholds
