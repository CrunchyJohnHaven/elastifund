# Deep Research Packet 03: Active Lanes And Gates

This is an attachment packet, not a new source of truth.

Canonical sources:

- `PROJECT_INSTRUCTIONS.md`
- `COMMAND_NODE.md`
- `research/edge_backlog_ranked.md`
- `docs/strategy/combinatorial_arb_implementation_deep_dive.md`
- `docs/ops/TRADING_LAUNCH_CHECKLIST.md`

## Active Trading and Research Lanes

### Lane 1: LLM Directional Baseline

Role:

- slow-market directional forecasting
- calibrated probability estimation
- existing live baseline

Current view:

- already implemented
- useful as a baseline and confirmation source
- not sufficient alone for the fastest Polymarket markets

### Lane 2: Smart Wallet Flow

Role:

- monitor public trade flow
- rank wallets
- detect convergence among high-signal wallets

Current view:

- one of the primary restart candidates
- especially important for fast crypto-style markets
- needs explicit bootstrap readiness and reliable cold-start behavior

### Lane 3: LMSR Bayesian Engine

Role:

- infer mispricing from sequential trade flow and blended posterior pricing

Current view:

- code complete
- considered a primary fast-flow restart candidate
- should be evaluated as a math-first lane, not an LLM lane

### Lane 4: Cross-Platform Arb

Role:

- compare Polymarket and Kalshi pricing after fees

Current view:

- implemented
- not the first restart priority, but still a real lane
- key question is executable matching quality and capital efficiency at small size

### Lane 5: A-6 Guaranteed-Dollar Scanner

Role:

- detect guaranteed-dollar constructions inside neg-risk events

Current view:

- still gated research
- public-data audit found `0` executable constructions below the `0.95` gate
- promotion depends on maker-fill curve, violation half-life, and settlement proof

### Lane 6: B-1 Templated Dependency Engine

Role:

- detect implication and exclusion violations in narrow deterministic market families

Current view:

- still gated research
- public-data audit found `0` deterministic template pairs in the first `1,000` allowed markets
- promotion depends on precision at or above `85%` and false positives at or below `5%`

## Current Gate Logic

The repo is explicitly telling us:

- wallet-flow and LMSR are the most realistic near-term restart lanes
- A-6 and B-1 are not blocked by lack of imagination; they are blocked by lack of empirical proof
- real bottlenecks are fillability, density, precision, and settlement evidence

## Launch Staging

The required order is:

1. `paper`
2. `shadow`
3. `micro-live`
4. `live`

Deep research should align recommendations to that ladder.

## The Most Important Lane-Level Unknowns

- Can wallet-flow bootstrap and signal quality stay stable enough for daily use?
- Does LMSR produce enough actionable mispricings after realistic execution assumptions?
- Are cross-platform matches frequent enough at small capital to matter?
- Is A-6 genuinely too sparse, or just too strict under the current executable gate?
- Is B-1 structurally sparse, or is the current deterministic scope still under-specified?
