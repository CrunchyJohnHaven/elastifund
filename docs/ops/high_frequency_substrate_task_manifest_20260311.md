# High-Frequency Substrate Task Manifest

Status: active plan
Last updated: 2026-03-11
Category: active plan
Canonical: yes

**Date:** 2026-03-11  
**Purpose:** methodical execution backlog for the Phase 2 high-frequency blueprint.  
**Companion docs:** `research/high_frequency_substrate_phase2_blueprint_2026-03-11.md`, `research/dispatches/DISPATCH_101_DEEP_RESEARCH_INGESTION_20260311.md`, `research/imports/deep_research_report_2026-03-11.md`, `COMMAND_NODE.md`

## Status Legend

- `DONE` — implemented in the repo or already wired into the current worktree
- `PARTIAL` — code exists, but rollout gating, integration, or evidence is incomplete
- `PENDING` — not built yet
- `DEFERRED` — intentionally postponed until an earlier measurement gate passes

## Program-Level Objectives

1. restore runtime truth so launch gates mean something,
2. make maker economics and fill quality measurable,
3. stop stale registry and data-plane artifacts from hiding live opportunity,
4. finance-gate any paid data or infra upgrades,
5. and only escalate topology complexity after measured evidence.

## Workstream A — Truth Layer And Launch Contract

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| A1 | PARTIAL | P0 | Make wallet reconciliation a required per-cycle input to launch posture and rollout control | `bot/wallet_reconciliation.py`, `scripts/reconcile_polymarket_wallet.py`, `scripts/write_remote_cycle_status.py`, `reports/wallet_reconciliation/latest.json` | none | runtime packets expose reconciliation freshness, precision, phantom count, and recommendation every cycle |
| A2 | PARTIAL | P0 | Add deterministic local-overwrite and phantom-purge policy to the runtime flow with explicit dry-run and approved-fix modes | same as A1 | A1 | local cleanup is machine-auditable and never happens silently |
| A3 | PENDING | P0 | Reconcile `capital.polymarket_accounting_delta_usd` against wallet export cash flow and local trade attribution | `COMMAND_NODE.md`, `reports/runtime_truth_latest.json`, BTC5 attribution surfaces | A1 | residual capital delta is explained, bounded, and emitted in artifacts |
| A4 | PENDING | P0 | Eliminate launch-contract mismatch between service state, effective profile, `execution_mode`, and `allow_order_submission` | `scripts/write_remote_cycle_status.py`, runtime profile loaders, service artifacts | A1 | `launch_posture=clear` is achievable without manual story repair |
| A5 | PENDING | P1 | Publish a single machine-readable "truth precedence" block into the runtime packet | runtime/public snapshot generators | A1 | downstream docs and controllers stop inferring precedence from prose |
| A6 | PENDING | P0 | Add a hard-fail truth lattice so contradictory posture/recommendation/trade-count surfaces emit `hold_repair` instead of silent merges | `scripts/write_remote_cycle_status.py`, runtime/public snapshot generators, launch packet outputs | A4, A5 | mixed `promote`/`shadow_only` or silent `max_observed` trade-count merges are impossible without an explicit broken-reason artifact |

## Workstream B — Market Discovery And Data Plane Repair

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| B1 | PARTIAL | P0 | Repair `pm_fast_market_registry` so live eligible counts match direct Gamma pulls | `bot/pm_fast_market_registry.py`, `reports/market_registry/latest.json` | none | `eligible_count` no longer falls to zero when live crypto markets exist |
| B2 | PARTIAL | P0 | Publish quote staleness and discovery-health as first-class rollout blockers | registry + `infra/cross_asset_data_plane.py`, `reports/data_plane_health/latest.json` | B1 | stale quote and missing-registry failures are classified consistently |
| B3 | PENDING | P1 | Add RTDS ingestion for Binance + Chainlink streams into the canonical data plane | `infra/cross_asset_data_plane.py`, `bot/ws_trade_stream.py`, RTDS consumers | B2 | RTDS freshness visible in health artifacts and usable by candle/threshold lanes |
| B4 | PENDING | P1 | Add direct exchange reference feeds and align timestamps across venue events | cross-asset data plane + downstream envelopes | B3 | envelopes share stable event timestamps and source metadata |
| B5 | PENDING | P2 | Persist compact market-envelope replay slices for targeted microstructure backtests | `reports/`, `state/`, replay helpers | B3 | one-cycle replays can reproduce signal decisions without full raw-log retention |

## Workstream C — Maker Economics And Execution Quality

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| C1 | PARTIAL | P0 | Unify maker-rebate and taker-fee logic across fast lanes using shared helpers and dynamic fee discovery where supported | `src/polymarket_fee_model.py`, fast execution paths | none | fast-lane EV outputs no longer depend on stale hardcoded fee assumptions |
| C2 | PENDING | P0 | Instrument queue-aware fill outcomes, cancel causes, and post-only rejection reasons | `bot/btc_5min_maker.py`, CLOB clients, order outcome artifacts | none | each fill or miss has a structured attribution reason |
| C3 | PARTIAL | P0 | Wire VPIN into live cancellation, hold, spread-adjustment, and stale-quote scale-down decisions | `bot/vpin_toxicity.py`, `bot/btc_5min_maker.py`, stream handlers | C2 | toxicity or stale-quote regime changes alter live shadow behavior, are observable in artifacts, and always emit explicit reject reasons |
| C4 | PENDING | P1 | Add OFI computation and combine it with VPIN for maker safety gating | order-book stream handlers, fast-lane artifacts | C3 | OFI and VPIN both appear in per-market telemetry and execution decisions |
| C5 | PARTIAL | P1 | Fix the BTC5 `0.49` / near-mid drag by price-bucket-aware quoting gates and a bounded suppress-vs-reprice experiment contract | `bot/btc_5min_maker.py`, BTC5 probe/reporting surfaces | C2 | shadow/live evidence shows reduced loss concentration in the drag bucket and the artifact trail can distinguish hard suppression from defensive repricing |
| C6 | PENDING | P1 | Publish maker fill-rate, capture-rate, and queue survival as operator metrics | BTC5 and cross-asset reporting surfaces | C2 | rollout decisions can use fill quality instead of P&L alone |
| C7 | DEFERRED | P3 | Evaluate Rust/PyO3 hot-path replacement only after Python p95/p99 profiling proves persistent execution loss | future `infra/` or Rust bridge | C2, C3, C4 | measured Python hot-path overhead is shown to be the limiting factor |

## Workstream D — Cross-Asset Information Flow

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| D1 | PARTIAL | P1 | Turn symbolic transfer entropy into a published gating artifact, not just a helper module | `src/transfer_entropy.py`, `src/cross_asset_cascade.py` | B3 | latest cascade packet exposes forward/reverse TE and sample sufficiency |
| D2 | PARTIAL | P1 | Keep follower-lane rollout behind Instance 6 finance + reconciliation gates | `scripts/instance6_rollout_controller.py`, `scripts/run_instance6_rollout_finance_dispatch.py` | A1, B2 | no follower promotion occurs with stale finance or weak wallet reconciliation |
| D3 | PENDING | P1 | Validate follower EV by asset and kill unproductive followers quickly | cascade artifacts and tests | D1 | only positive post-cost followers remain promotion-eligible |
| D4 | PARTIAL | P1 | Run CoinAPI as a measured improvement candidate, not an assumed prerequisite | `bot/cross_asset_history.py`, finance artifacts | finance gate green | paid vendor trial produces a before/after data-gap artifact |

## Workstream E — Infrastructure And Route Topology

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| E1 | PENDING | P1 | Build an empirical latency and fill-quality benchmark for the current deployment path | new benchmark script/artifacts under `scripts/` and `reports/` | C2 | baseline includes observe-to-submit latency, quote age, and fill outcome quality |
| E2 | PENDING | P1 | Benchmark at least one London-adjacent path against the current non-geoblocked baseline | deploy/runtime profile surfaces | E1 | topology decisions are driven by measured delta, not only inference |
| E3 | PENDING | P2 | Evaluate proxy-based routing only after compliance, stability, and latency are measured together | deployment + operator docs | E2 | proxy path is either explicitly approved with guardrails or rejected |
| E4 | DEFERRED | P3 | Pilot LD4 bare metal only if E2 shows a meaningful edge over the current path | deployment surfaces | E2 | measured improvement justifies added complexity and compliance burden |
| E5 | DEFERRED | P3 | Add TLS/user-agent impersonation only if compliant network paths still fail systematically | HTTP/CLOB client layer | E3 | blocking evidence exists and the change is legally/operator-approved |

## Workstream F — Polygon RPC And Settlement Safety

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| F1 | PENDING | P1 | Standardize on a private Polygon RPC vendor for settlement-sensitive flows | RPC abstraction / env / docs | none | settlement reads stop depending on shared public nodes |
| F2 | PENDING | P1 | Make finalized or milestone-safe reads the default for reconciliation and merge-sensitive paths | reconciliation and merge utilities | F1 | state reads stop bouncing on optimistic tip data |
| F3 | PENDING | P2 | Select a Polygon-appropriate private transaction relay path for sensitive maintenance actions | execution maintenance flows | F1 | the chosen relay is documented, measurable, and Polygon-compatible |
| F4 | DEFERRED | P3 | Add advanced bundle / MEV protection only after basic private-RPC and finalized-read posture is stable | same as F3 | F2, F3 | no premature complexity before baseline safety is working |

## Workstream G — Observability And Storage Discipline

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| G1 | PARTIAL | P1 | Finish the LogsDB posture with retention, compression, and schema consistency | `infra/index_templates/elastifund-*.json` | none | disk usage remains bounded under current fast-market load |
| G2 | PENDING | P1 | Add latency, quote-staleness, and cancel-quality dashboards | Elastic/Kibana assets | C2, B2 | operators can inspect quality regressions without tailing raw logs |
| G3 | PENDING | P2 | Define per-artifact retention classes so raw high-churn data does not exhaust the VPS again | observability and ops configs | G1 | hot-path telemetry survives without storage blowups |
| G4 | PENDING | P1 | Publish DORA-style trading ops metrics for deployment frequency, hypothesis lead time, change failure rate, and MTTR | `scripts/write_remote_cycle_status.py`, public/runtime truth packets, operator dashboards | A6, C2 | each cycle emits machine-readable velocity metrics and blocker MTTR instead of prose-only status |

## Workstream H — Finance And Operator Packet

| ID | Status | Priority | Task | Primary files | Dependency | Acceptance gate |
|---|---|---|---|---|---|---|
| H1 | PENDING | P0 | Emit explicit finance asks for CoinAPI, private RPC, and any topology pilot | `reports/finance/allocation_plan.json`, `reports/finance/action_queue.json` | finance cycle refresh | asks include amount, rationale, confidence, rollback, and caps |
| H2 | DONE | P0 | Keep the March 11 research packet and this manifest in the canonical root handoff docs | `COMMAND_NODE.md`, `PROJECT_INSTRUCTIONS.md` | none | future sessions ingest these files by default |
| H3 | PENDING | P1 | Refresh public/private messaging so topology claims do not outrun measured evidence | README/public surfaces if later changed | H2 | no public doc states an infra migration as accomplished before it exists |

## Immediate Execution Order

1. `A1` — make reconciliation state unavoidable in the cycle packet.
2. `A4` and `A6` — repair the launch contract and make contradictory truth surfaces fail hard instead of merging silently.
3. `B1` and `B2` — restore accurate market discovery and freshness blocking.
4. `C2` and `C3` — measure fill quality and wire toxicity plus stale-quote gating into live shadow behavior.
5. `A3` and `C5` — explain the capital/BTC5 attribution gap and the `0.49` bucket drag with bounded suppress-vs-reprice evidence.
6. `B3` and `D1` — promote RTDS plus transfer-entropy artifacts into the canonical data plane.
7. `F1` and `F2` — harden settlement truth with a private RPC and finalized reads.
8. `H1` — finance-gate CoinAPI and any topology pilot only after the free-stack gap is measured.
9. `E1` and `E2` — benchmark the current path against a London-adjacent option before any major migration decision.
10. `G1`, `G2`, and `G4` — lock the telemetry/storage posture and publish machine-readable velocity metrics after the fast-lane signal path is producing denser data.

## Definition Of Done For Phase 2

Phase 2 is not complete when the docs look sharper. It is complete when:

- wallet, runtime, and launch truth align closely enough that promotion gates are trustworthy,
- market registry and data-plane freshness stop hiding live opportunity,
- maker fill quality is measurable by regime and price bucket,
- follower lanes are promoted only with positive post-cost evidence,
- paid data and infra upgrades are finance-approved instead of implied,
- and topology claims are backed by measured latency plus fill-quality improvement.
