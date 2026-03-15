# ADR 0002: Keep Evidence-First Reporting and a Strict Public/Private Data Boundary

- Status: Accepted
- Date: 2026-03-07

## Context

This repo publishes performance, research findings, and operating docs. It also touches live-money workflows and private infrastructure.

The project already makes an explicit distinction:

- public docs explain methods, backtests, failures, and operating principles
- raw live data, wallet addresses, credentials, and exact live coefficients stay private

That boundary shows up in:

- `README.md`
- `docs/PERFORMANCE.md`
- `docs/ARCHITECTURE.md`
- `docs/RESEARCH_LOG.md`

## Decision

Maintain an evidence-first public posture with sanitized reporting.

Rules:

- backtest, simulation, and live results must never be conflated
- negative findings are published rather than buried
- private runtime data stays out of the repo unless it has been deliberately sanitized
- public docs may explain the method without disclosing active edge settings or secrets

## Consequences

Positive:

- better credibility with contributors, investors, and internal stakeholders
- lower risk of accidentally leaking live edge or credential material
- easier long-term governance because the repo documents what is actually known

Negative:

- public live reporting may lag until a safe aggregation path exists
- some readers will want cleaner marketing numbers than the repo can honestly provide

## Follow-up

Any future dashboard, leaderboard, or investor artifact should inherit the same labeling discipline: live is live, backtest is backtest, and blank sections stay blank until evidence exists.
