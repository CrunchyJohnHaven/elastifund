# High-Frequency Substrate Phase 2 Blueprint

**As of:** 2026-03-11  
**Origin:** operator-provided research integrated into the repo  
**Purpose:** convert the March 11 high-frequency research packet into a repo-safe architecture direction, with explicit distinction between verified external constraints, current repo status, and hypotheses that still need measurement before they become system defaults.

## Executive Disposition

Elastifund is no longer blocked by a lack of ideas. It is blocked by a mismatch between:

- wallet truth,
- local ledger truth,
- runtime launch truth,
- and the execution assumptions embedded in the fast-market stack.

Phase 2 therefore prioritizes:

1. wallet-first state reconciliation,
2. maker-first execution economics,
3. lower-latency and higher-fidelity market data,
4. finance-gated infrastructure and data upgrades,
5. and tighter rollout rules that force evidence before promotion.

This blueprint accepts the research direction, but it does **not** blindly convert every infrastructure claim into policy. Where the research is stronger than current repo evidence, the system should treat the claim as a measured rollout hypothesis rather than a truth surface.

## Additional March 11 Dispatch Integration

An additional imported research packet is now preserved at:

- `research/imports/deep_research_report_2026-03-11.md`

Its useful delta has been integrated through:

- `research/dispatches/DISPATCH_101_DEEP_RESEARCH_INGESTION_20260311.md`
- `docs/ops/high_frequency_substrate_task_manifest_20260311.md`

What was accepted from that packet:

1. contradictory launch / deploy / trade-count truth must fail hard rather than merge silently,
2. the BTC5 `0.49` drag should be handled as a bounded suppress-vs-reprice experiment with explicit evidence,
3. toxicity and quote staleness should be treated as one control surface for scale-down decisions,
4. and DORA-style operator metrics are useful as improvement-velocity telemetry.

What was not promoted to system default from that packet:

- broad regime-model replacements,
- capital-allocation flywheel rewrites,
- and topology or venue-expansion claims without measured fill-quality proof.

## What Is Now System Direction

### 1. Wallet truth beats local SQLite truth

The system must treat live wallet and remote Polymarket position truth as authoritative whenever local trade tables drift.

Operational rule:

`live wallet / remote positions > runtime artifacts > public metrics > local seed state`

This changes the role of SQLite in the fast lane:

- SQLite remains a local execution and attribution cache.
- SQLite is not the final arbiter for capital, open-position counts, or resolved state.
- Local rows with no defensible remote match are reconciliation candidates, not durable truth.

### 2. Fast-market execution is maker-first by default

The research direction is accepted: 5-minute and 15-minute crypto execution must assume passive maker economics unless a separate lane proves a positive taker path after live fee and fill modeling.

System consequences:

- `post_only` behavior is mandatory in the fast maker lanes.
- fee and rebate handling must be sourced dynamically from venue truth where possible.
- expected value calculations must include maker rebates and fill risk, not just static spread assumptions.

### 3. Microstructure signals are no longer optional research toys

VPIN, OFI, queue/fill attribution, and cross-asset information-flow measures are now part of the accepted Phase 2 architecture because they directly affect maker adverse-selection risk.

The stack should assume:

- raw WebSocket or RTDS event ingestion,
- continuously updated microstructure features,
- cancellation logic keyed off toxicity and stale-book detection,
- and measured queue-position / fill-probability artifacts.

### 4. Finance must gate data and infra upgrades explicitly

CoinAPI, private RPC vendors, and more aggressive deployment topologies are finance-plane decisions, not ad hoc engineering purchases.

Every paid upgrade must enter the machine-readable finance contract with:

- ask amount,
- expected lift,
- confidence,
- rollback,
- and policy-cap compliance.

## Verified External Constraints

These are supported by current official docs and can be treated as current external constraints for implementation planning.

### Polymarket Data API rate limits

Official Polymarket docs currently list:

- `GET /positions`: `150 requests / 10s`
- `GET /closed-positions`: `150 requests / 10s`

Implementation consequence:

- reconciliation code should keep the token-bucket limiter already present,
- and all pagination/backoff logic should assume Cloudflare sliding-window throttling rather than simple hard failures.

### Polymarket fee / rebate posture for crypto fast markets

Official Polymarket docs currently show that maker rebates are funded by taker fees and that crypto fast markets are fee-enabled with fee-curve weighting.

Implementation consequence:

- do not hardcode static fee tables as permanent truth,
- but do treat maker-rebate-aware economics as mandatory in fast-market EV calculations.

### Polymarket RTDS availability

Official Polymarket docs expose RTDS as a real-time socket and explicitly mention Binance and Chainlink crypto price streams.

Implementation consequence:

- RTDS should be a first-class input to the fast data plane,
- especially for candle and threshold markets whose resolution logic depends on exchange/oracle moves.

### Geographic restriction and server-region facts

Official Polymarket docs currently state:

- primary servers: `eu-west-2`
- closest non-georestricted region: `eu-west-1`
- `GB` is currently restricted

Implementation consequence:

- London proximity matters physically,
- but London-hosted execution cannot be adopted as a repo default without also solving geoblocking, compliance, and route-legitimacy concerns.

### Polygon PoS finality after Heimdall v2

Official Polygon docs currently describe deterministic finality in roughly `2-5 seconds` under Heimdall v2 / milestones.

Implementation consequence:

- reconciliation and settlement confirmation loops can be materially tighter than older 60-90 second assumptions,
- but they should still key off finalized or milestone-safe state rather than optimistic tip reads.

## Disposition Of The Research Claims

| Topic | Disposition | Current repo status | Required next step |
|---|---|---|---|
| Wallet-first reconciliation | **Accepted** | `bot/wallet_reconciliation.py` and `scripts/reconcile_polymarket_wallet.py` exist | Make reconciliation a required rollout input, not a side utility |
| Deterministic overwrite / phantom purge policy | **Accepted with safeguards** | Opt-in local fixes and phantom purge are already implemented | Add clear cycle-level gating and dry-run evidence before destructive cleanup |
| Maker-only fee/rebate economics | **Accepted** | `src/polymarket_fee_model.py` exists; maker-only routes exist in parts of the stack | Expand dynamic fee-rate usage and unify fast-lane EV logic |
| VPIN / OFI toxicity defense | **Accepted** | `bot/vpin_toxicity.py` exists; broader integration is partial | Wire live cancellation/spread logic and publish artifacts |
| Symbolic transfer entropy / cross-asset lead-lag | **Accepted** | `src/transfer_entropy.py` exists; cross-asset lane is active in shadow | Publish gating artifacts and require follower EV proof before promotion |
| `msgspec`/fast JSON hot path | **Accepted** | `infra/fast_json.py` exists and is already wired into CLOB paths | Extend typed decode use only if profiling shows remaining JSON bottlenecks |
| CoinAPI / premium L3 data | **Accepted as a finance-gated upgrade** | `bot/cross_asset_history.py` already emits CoinAPI asks | Run the trial only after finance gate is green and the free stack gap is measured |
| LD4 bare-metal migration | **Conditional hypothesis** | no production LD4 path exists | Benchmark current Dublin / London / proxy path before treating LD4 as mandatory |
| Swiss/Austrian static residential proxy cluster | **Conditional hypothesis** | no compliant proxy stack exists | Treat as a legal/compliance + latency pilot, not a default rollout assumption |
| TLS impersonation / browser fingerprint evasion | **Conditional hypothesis** | not implemented | Only pursue if official client + compliant network path still trigger systematic blocking |
| Private Polygon RPC | **Accepted** | not yet standardized across the fast lanes | choose vendor and make finalized-state reads the default |
| MEV-protected private relay on Polygon | **Accepted in principle, vendor unresolved** | not implemented | select a Polygon-appropriate private-transaction path; do not assume Flashbots Protect is the final answer |
| Rust/PyO3/Disruptor rewrite | **Deferred** | not implemented | profile Python hot paths first and only escalate if measured p99 latency still blocks viable fills |
| LogsDB observability posture | **Accepted** | logsdb template tightening already landed in the worktree | complete retention, compression, and disk-budget policy |

## Relationship To Earlier Dublin-Latency Research

Earlier repo research argued that a tuned Dublin deployment plus WebSockets and RTDS likely closes most of the meaningful latency gap. The new research packet argues for a more aggressive jump to LD4 bare metal.

These are not mutually exclusive if handled correctly.

Current repo disposition:

- treat `eu-west-1` as the current lowest-risk non-geoblocked baseline,
- treat `eu-west-2` / LD4 proximity as a performance hypothesis worth benchmarking,
- and do **not** encode the phrase "LD4 is mandatory" into policy until measured latency, fill quality, geoblock stability, and operator compliance are all better than the current path.

The system should not confuse plausible microstructure logic with proven deployment ROI.

## Phase 2 Architecture

### Phase 0: Truth Restoration

Goal: make launch truth, wallet truth, and attribution truth agree closely enough that live gating is meaningful again.

Primary repo surfaces:

- `bot/wallet_reconciliation.py`
- `scripts/reconcile_polymarket_wallet.py`
- `scripts/write_remote_cycle_status.py`
- `reports/runtime_truth_latest.json`
- `reports/public_runtime_snapshot.json`
- `reports/wallet_reconciliation/latest.json`

Exit criteria:

- snapshot precision >= `99%`
- classification precision >= `95%`
- zero phantom local open trades after approved cleanup
- capital attribution delta reduced to an explicitly bounded and explained residual

### Phase 1: Discovery And Data Plane Repair

Goal: stop losing opportunity truth because discovery, registry, or data-refresh layers are stale.

Primary repo surfaces:

- `bot/pm_fast_market_registry.py`
- `infra/cross_asset_data_plane.py`
- `reports/market_registry/latest.json`
- `reports/data_plane_health/latest.json`
- `reports/cross_asset_cascade/latest.json`

Exit criteria:

- registry eligible counts match live market pulls within a bounded tolerance
- quote staleness classification is published every cycle
- RTDS / exchange feeds stay inside freshness SLOs

### Phase 2: Maker Microstructure Defense

Goal: only rest quotes when the local book and flow regime are defensible.

Primary repo surfaces:

- `bot/btc_5min_maker.py`
- `bot/vpin_toxicity.py`
- `bot/clob_ws_client.py`
- `bot/ws_trade_stream.py`
- `infra/clob_ws.py`

Exit criteria:

- VPIN and OFI artifacts are produced in live shadow
- cancel / hold / tighten decisions are explainable from artifacts
- maker fill outcomes are attributed by queue/price-bucket regime instead of only gross P&L

### Phase 3: Cross-Asset Information Flow

Goal: use BTC-led information flow only when the follower lane proves post-cost value.

Primary repo surfaces:

- `src/transfer_entropy.py`
- `src/cross_asset_cascade.py`
- `scripts/run_instance5_cross_asset_cascade.py`
- `scripts/instance6_rollout_controller.py`

Exit criteria:

- follower-lane win rate and post-cost EV remain positive under published gates
- BTC5 remains healthy while follower lanes scale
- rollout controller keeps finance, reconciliation, and artifact freshness in the decision loop

### Phase 4: Infra And Route Topology

Goal: measure, not assume, whether a more aggressive topology materially improves fill quality.

Primary repo surfaces:

- deployment configs under `deploy/`
- runtime profiles under `config/runtime_profiles/`
- future benchmark artifacts under `reports/latency/` and `reports/topology/`

Exit criteria:

- measured end-to-end latency and fill quality from the current baseline
- measured comparison against at least one London-adjacent path
- clear compliance posture for any proxy-based routing before live use

### Phase 5: Polygon Settlement And RPC Hardening

Goal: tighten state reads and protect on-chain maintenance actions from stale data and public-mempool leakage.

Primary repo surfaces:

- wallet reconciliation
- position merge / settlement paths
- future RPC abstraction layer in `infra/`

Exit criteria:

- private RPC vendor selected
- finalized-state reads used by default for settlement-sensitive flows
- private transaction relay path chosen only if it is Polygon-appropriate and measurable

### Phase 6: Observability And Disk Discipline

Goal: keep the telemetry spine useful without repeating disk-exhaustion failures.

Primary repo surfaces:

- `infra/index_templates/elastifund-*.json`
- Elastic dashboards / latency dashboards
- retention / ILM policy configs

Exit criteria:

- logsdb index posture applied consistently
- latency, quote-staleness, and cancel-quality traces available
- disk growth remains bounded under expected fast-market load

## Engineering Guardrails

- Do not promote prose over machine-readable artifacts.
- Do not introduce new runtime APIs when the existing JSON contract already carries state.
- Do not hardcode vendor assumptions for fees, rebates, or geoblock handling when the venue provides runtime-discoverable values.
- Keep raw wallet exports out of the repo.
- Keep finance asks explicit and machine-readable.
- Keep high-risk path changes paired with targeted tests.
- Treat latency claims as measurement problems, not just architecture beliefs.

## References

Official sources used to classify current external constraints:

- Polymarket API rate limits: <https://docs.polymarket.com/quickstart/introduction/rate-limits>
- Polymarket maker rebates: <https://docs.polymarket.com/polymarket-learn/trading/maker-rebates-program>
- Polymarket RTDS: <https://docs.polymarket.com/developers/RTDS/:slug*>
- Polymarket geographic restrictions: <https://docs.polymarket.com/polymarket-learn/FAQ/geoblocking>
- Polygon finality: <https://docs.polygon.technology/pos/concepts/finality/finality/>
- Polygon Heimdall v2 / milestones: <https://docs.polygon.technology/pos/architecture/heimdall_v2/introduction/> and <https://docs.polygon.technology/pos/architecture/heimdall_v2/milestones/>
