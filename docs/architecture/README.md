# Architecture Control Plane

**Status:** Canonical landing page
**Role:** Primary index for the proof-carrying runtime, revenue path, promotion gates, replay tape, temporal memory, and deployment split.
**Date:** 2026-03-22

This directory is the canonical architecture surface for the Desktop checkout.
Use it when you need to answer:

- what the system-of-record is
- where live capital authority lives
- how replay and truth are reconstructed
- how local shadow and Lightsail execution split
- which docs are canonical versus reference

## Read In This Order

1. [proof_carrying_kernel.md](proof_carrying_kernel.md)
2. [event_sourced_tape.md](event_sourced_tape.md)
3. [strike_desk.md](strike_desk.md)
4. [promotion_ladder.md](promotion_ladder.md)
5. [intelligence_harness.md](intelligence_harness.md)
6. [qd_thesis_repertoire.md](qd_thesis_repertoire.md)
7. [temporal_edge_memory.md](temporal_edge_memory.md)
8. [deployment_blueprint.md](deployment_blueprint.md)

## Canonical Roles

| File | Role |
|---|---|
| [proof_carrying_kernel.md](proof_carrying_kernel.md) | System-of-record for decision authority |
| [event_sourced_tape.md](event_sourced_tape.md) | Append-only replay backbone |
| [strike_desk.md](strike_desk.md) | Revenue-first execution path |
| [promotion_ladder.md](promotion_ladder.md) | Proof-to-capital stage gate |
| [intelligence_harness.md](intelligence_harness.md) | Acceptance gate for self-improvement |
| [qd_thesis_repertoire.md](qd_thesis_repertoire.md) | Niche preservation and compounding |
| [temporal_edge_memory.md](temporal_edge_memory.md) | Long-horizon provenance and retrieval |
| [deployment_blueprint.md](deployment_blueprint.md) | Local twin vs Lightsail split |

## Hard Rules

- `evidence_bundle -> thesis_bundle -> promotion_bundle -> learning_bundle` remains the only authoritative kernel flow.
- `continuous_orchestration` is a renderer/scheduler derived from the bundles, not a competing authority.
- The execution layer consumes `PromotionTicket` objects only.
- Every live decision must be reconstructable from the event tape.
- Every mutation must survive the intelligence harness before it can change live behavior.

## Deployment Order

Use this order for staged deployment work:

1. Local twin shadow
2. Lightsail truth writers + event tape
3. Strike desk shadow
4. Promotion manager enforcement
5. Seed-live Resolution Sniper
6. Whale Copy
7. Neg-Risk

## Command Map

- Canonical commands and verification flows live in [scripts/README.md](../../scripts/README.md).
- Local shadow entrypoints live in [../ops/LOCAL_TWIN_ENTRYPOINTS.md](../ops/LOCAL_TWIN_ENTRYPOINTS.md).

## Related Strategy Surfaces

- Tail-calibration strategy policy and gates live in [../strategy/tail_calibration_harness.md](../strategy/tail_calibration_harness.md).
- The durable research synthesis for public-data execution, tail calibration, and Alpaca design lives in [../../research/deep_research_packets/06_DEEP_RESEARCH_PUBLIC_DATA_TAIL_AND_ALPACA_DESIGN.md](../../research/deep_research_packets/06_DEEP_RESEARCH_PUBLIC_DATA_TAIL_AND_ALPACA_DESIGN.md).
- The durable BTC5 oracle-aligned modeling and fill-conditioning doctrine lives in [../../research/deep_research_packets/10_DEEP_RESEARCH_BTC5_ORACLE_ALIGNED_PROBABILITY_AND_FILL_MODEL.md](../../research/deep_research_packets/10_DEEP_RESEARCH_BTC5_ORACLE_ALIGNED_PROBABILITY_AND_FILL_MODEL.md).
