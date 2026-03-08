# ADR 0003: Pursue a Dual-Lane Revenue Architecture with Shared Allocation and Risk Rails

- Status: Accepted
- Date: 2026-03-07

## Context

Trading is the current execution center of gravity, but the broader Elastifund.io vision is more durable if revenue is not tied to one market regime.

The repo already contains early pieces of that direction:

- trading systems in `bot/` and `polymarket-bot/`
- non-trading architecture in `docs/NON_TRADING_EARNING_AGENT_DESIGN.md`
- digital-product research code in `nontrading/digital_products/`
- a shared allocator in `orchestration/resource_allocator.py`

## Decision

Adopt a dual-lane revenue architecture:

- trading agents pursue market-making, forecasting, and structural mispricing
- non-trading agents pursue bounded digital-product and outbound revenue workflows
- both lanes compete for budget through a shared allocator and common safety philosophy

The allocator and risk rails, not hype, decide whether a lane should scale.

## Consequences

Positive:

- revenue diversification across uncorrelated lanes
- a stronger internal case for a shared knowledge hub
- the non-trading lane can validate automation and Elastic observability even when markets are quiet

Negative:

- more surface area for compliance, billing, and operational mistakes
- more documentation and policy burden than a trading-only system

## Follow-up

Non-trading should remain bounded and compliance-aware. A second revenue lane is useful only if it is auditable and does not turn the platform into a rule-violating spam engine.
