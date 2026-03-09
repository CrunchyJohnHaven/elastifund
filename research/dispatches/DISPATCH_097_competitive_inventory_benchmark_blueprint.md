# Dispatch #97 — Competitive Inventory & Benchmark Blueprint

**Date:** 2026-03-07
**Source:** Deep Research (comprehensive web crawl, official repos + docs)
**Priority:** P2 (Website Content — not trading priority)
**Status:** RESEARCH COMPLETE — awaiting engineering allocation for benchmark harness
**Canonical full report:** `research/competitive_inventory_benchmark_deep_research.md`

---

## Summary

Comprehensive inventory of trading bots and algorithmic trading frameworks available on the web, benchmarked for operational quality rather than profitability claims. The imported full report confirms three things:

1. The opportunity is a continuously updated catalog plus a reproducible evaluation harness, not a one-off "best bots" blog post.
2. The strongest initial comparison set is Freqtrade, Hummingbot, Jesse, OctoBot, NautilusTrader, and Lean.
3. This is a website moat and credibility asset, not a direct source of prediction-market alpha.

The detailed synthesis now lives in `research/competitive_inventory_benchmark_deep_research.md`. This dispatch remains the implementation-facing brief.

## Why It Matters To Elastifund

- Nearly every notable system targets crypto spot/futures or general quant trading, not prediction-market microstructure.
- That means Elastifund is early enough to define the public benchmark category rather than merely participate in it.
- A methodology-first benchmark page strengthens the website, contributor funnel, and recruiting signal without making fake profitability claims.
- The harness also gives us an external operational baseline for our own reliability, execution, and calibration discipline.

## Initial Cohort

Ship the first public harness run with six systems only:

| System | Role | Why it is in batch one | Preferred mode |
|--------|------|-------------------------|----------------|
| Freqtrade | OSS execution bot | dominant open-source crypto baseline | internal simulation |
| Hummingbot | OSS execution bot | strongest market-making reference | paper connectors / sandbox |
| Jesse | OSS execution framework | programmable strategy API | paper/live-sim hybrid |
| OctoBot | OSS execution bot | broad retail feature set | internal paper mode |
| NautilusTrader | OSS engine | best research-to-live parity reference | deterministic simulation |
| Lean | OSS engine | general quant baseline outside crypto-native tooling | deterministic simulation |

Second wave after methodology is stable:

- HftBacktest
- Superalgos
- Backtrader
- Qlib
- selected commercial SaaS profiles

Legacy systems such as Zenbot and Gekko should remain historical baselines only.

## Benchmark Modes

Public results must distinguish between:

- internal simulation
- exchange sandbox
- deterministic simulation

And every run should be labeled as:

- native strategy
- translated Elastifund canonical strategy

Do not collapse candle-track bots and order-book/HFT tools into the same ranking bucket.

## Benchmark Test Matrix (T0-T7)

| Test ID | Name | Measures | Pass Criteria |
|---------|------|----------|---------------|
| T0 | Reproducible build | Install from clean VM | Build succeeds, no manual edits |
| T1 | Smoke paper run | Time to first decision | Decisions in <15 min |
| T2 | Forced restart | Crash resilience | Recovery <5 min, no corrupted state |
| T3 | Data-feed disconnect | Reconnect logic | Reconnect <2 min, gap logged |
| T4 | 24-hour soak | Memory leaks, cumulative errors | <10% RSS drift, no crash |
| T5 | 7-day run | Reliability + operational cost | Crash-free >=99% |
| T6 | Backtest parity | Research-to-live divergence | Signal divergence <= tolerance |
| T7 | Execution fidelity | Slippage + order semantics | Slippage within defined band |

## Scoring Rubric (100 points)

| Category | Weight | What It Measures |
|----------|--------|-----------------|
| Reliability & Operations | 25 | 7-day uptime, crash recovery, reconnect |
| Execution Fidelity | 20 | Fill-model realism, order semantics |
| Research & Iteration Speed | 15 | Backtest speed, data ingestion, reproducibility |
| Integration Breadth | 15 | Viable venues, adapter quality |
| Usability & Onboarding | 10 | Docker-first install, time to first paper run |
| Community & Maintenance | 10 | Stars, recency, contributor activity |
| License & Legal | 5 | Permissive vs copyleft vs restricted |

## Safety And Compliance Gates

Before any external bot reaches even a testnet endpoint:

- generate an SBOM
- run secrets scanning
- run dependency vulnerability scanning
- run static analysis where available
- detect and store declared plus inferred licenses

No production keys. No shared credentials. Copyleft systems are benchmarkable, but public redistribution of modified images needs disciplined source release handling.

## Elastifund Differentiation (What None of These Do)

1. **Prediction market native** — Every system above targets CEX spot/futures or equities. Zero are built for prediction market microstructure.
2. **Probabilistic calibration pipeline** — Platt scaling, anti-anchoring, acquiescence bias correction. No competitor publishes calibration methodology.
3. **Kill-rule discipline with public autopsies** — 10 strategies rejected with full post-mortems. No competitor documents failures.
4. **Structural alpha scanning** — A-6 guaranteed-dollar, B-1 dependency graph. These exploit prediction market specific structure (neg-risk, outcome constraints).
5. **Maker-only execution** — Zero taker fee + rebate. Most crypto bots assume taker execution.
6. **VPIN toxicity gating** — Order flow toxicity detection in prediction markets. Novel application.
7. **Agent-run autonomous operation** — AI makes trade decisions, human builds infrastructure. No competitor frames it this way with live evidence.

## Public Deliverables

Sequence the public outputs this way:

1. `/benchmark/methodology`
2. system profile pages
3. leaderboard
4. run-artifact and paper-status API

This keeps methodology ahead of comparison claims.

## Open Questions For Benchmark Implementation

1. Standard venue for crypto paper runs: dry-run on live data only, or require exchange testnet?
2. Separate prediction markets from traditional markets on leaderboard?
3. Fixed scoring weights (transparent) or adaptive (versioned quarterly)?

## JJ Assessment

This inventory is comprehensive and useful exclusively as a website content asset. It does not generate trading edge. Priority is P2: build the comparison page after the P0 empirical gates (A-6/B-1) and P1 execution work are complete.

The benchmark harness concept (T0-T7 + scoring rubric) is the genuinely differentiated idea here. Nobody has published a reproducible, standardized benchmark of trading systems. If we build this and publish the methodology, artifacts, and results, it becomes the reference that everyone else cites. That IS the website moat.

Engineering estimate: 40-60 hours to build the harness and run the first 6 systems. Not allocated yet. Sequence after Cycle 2 completes and after the current A-6/B-1 empirical gates.

---

*Filed as part of the Elastifund research flywheel. See `edge_backlog_ranked.md` for full strategy catalog.*
