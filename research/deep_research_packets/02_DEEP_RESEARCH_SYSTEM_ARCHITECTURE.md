# Deep Research Packet 02: System Architecture

This is an attachment packet, not a new source of truth.

Canonical sources:

- `COMMAND_NODE.md`
- `docs/REPO_MAP.md`
- `docs/strategy/edge_discovery_system.md`
- `docs/strategy/combinatorial_arb_implementation_deep_dive.md`
- `docs/ops/REMOTE_DEV_CYCLE_STANDARD.md`

## Top-Level Architecture

Elastifund has three interacting layers:

1. Trading runtime
2. Research and validation pipeline
3. Remote pull/store/status/deploy loop

## Trading Runtime

The main live loop is `bot/jj_live.py`.

Its job is to:

- scan markets
- collect signal inputs
- apply calibration and risk gates
- size trades conservatively
- route eligible orders
- record runtime state and evidence

## Major Runtime Signal Families

- LLM directional analysis
- wallet-flow consensus
- LMSR/Bayesian fast-market pricing
- cross-platform arb
- A-6 structural guaranteed-dollar scanning
- B-1 templated dependency scanning
- Elastic anomaly feedback as a caution layer

## Research and Validation Layer

The repo also contains a separate research engine for edge discovery and rejection. That layer is designed to:

- collect market and reference data
- generate hypotheses
- backtest with realistic execution assumptions
- reject weak edges quickly
- maintain a ranked backlog of promising lanes

Important point: not every module in the repo is meant for immediate live deployment. Some are explicitly validation or shadow infrastructure.

## Structural-Arb Subsystem

The combinatorial stack is deliberately narrow right now.

A-6 means:

- guaranteed-dollar scanning inside neg-risk events
- rank straddles and full-event baskets
- only consider executable constructions

B-1 means:

- implication and exclusion monitoring for narrow deterministic families
- no broad graph expansion until density and precision are proven

## Persistence and Artifacts

Important state stores include:

- `jj_state.json` for runtime state
- `data/jj_trades.db` for trade history
- `data/constraint_arb.db` for structural-arb telemetry
- `reports/flywheel/latest_sync.json` for latest control-plane summary
- `reports/remote_cycle_status.json` for compact remote truth

## Remote Operating Model

The local repo is the control point. The VPS is the execution target.

Canonical flow:

1. pull remote artifacts
2. store locally
3. run research/status refresh
4. make the smallest justified change
5. deploy only validated deltas
6. validate the remote runtime again

The VPS is not treated as a git checkout.

## What This Means for Deep Research

Useful research must fit the actual architecture:

- maker-first execution bias
- staged promotion from research to shadow to micro-live
- explicit telemetry and gate design
- small-capital constraints
- remote pull-first workflow

Research that assumes unlimited liquidity, unrestricted live deployment, or a blank-slate architecture will mismatch the repo.
