# High-Frequency Refactor Revision Log

Status: historical briefing
Last updated: 2026-03-11
Category: historical briefing
Canonical: no

Date: 2026-03-11

This log records the concrete repo changes completed in this implementation pass against the "Strategic Refactoring of the Elastifund High-Frequency Substrate" blueprint.

## Completed

### 1. Wallet Reconciliation Hardening

Files:
- `bot/wallet_reconciliation.py`
- `scripts/reconcile_polymarket_wallet.py`
- `tests/test_wallet_reconciliation.py`

Changes:
- Expanded the reconciliation artifact with explicit `status`, unmatched open/closed deltas, rollout recommendation, remaining remote/local mismatch ids, and applied-fix counts.
- Added opt-in local purification flags:
  - `--apply-local-fixes`
  - `--purge-phantoms`
- Added best-effort local closure backfill for trades that the wallet marks closed but the local ledger still marks open.
- Added phantom-open deletion for rows with no remote match and no local transaction hash.
- Hardened the reconciliation logic against narrower `trades` table schemas.

Effect:
- The wallet-reconciliation artifact can now act as a stronger rollout-gate input instead of a bare precision score.
- Local-ledger cleanup remains explicit and opt-in; nothing destructive happens by default.

### 2. Maker-Only Fee Model Correction

Files:
- `src/polymarket_fee_model.py`
- `bot/sum_violation_strategy.py`
- `tests/test_sum_violation_strategy.py`
- `tests/test_polymarket_fee_model.py`

Changes:
- Added a shared Polymarket fee/rebate model with:
  - crypto parabolic taker fee curve
  - maker rebate share handling
  - per-share fee and rebate helpers
- Removed the structural-arb self-penalty where the sum-violation lane subtracted taker fees despite routing passive quotes.
- Added explicit reporting fields for:
  - actual maker fee drag
  - hypothetical taker fee drag
  - maker rebate per basket

Effect:
- The maker-only combinatorial lane now evaluates opportunities on the correct execution economics.

### 3. Fast JSON Decode Path

Files:
- `infra/fast_json.py`
- `bot/clob_ws_client.py`
- `bot/ws_trade_stream.py`
- `infra/clob_ws.py`
- `tests/test_fast_json.py`
- `requirements.txt`

Changes:
- Added a shared JSON helper that uses `msgspec` when available and falls back to stdlib JSON otherwise.
- Switched the CLOB market-data clients and stream handlers to the shared decoder for raw WebSocket/HTTP payloads.
- Added regression tests for bytes and `memoryview` inputs.

Effect:
- The hot path can use a materially faster decoder without introducing a hard runtime dependency.

### 4. Elastic LogsDB Template Tightening

Files:
- `infra/index_templates/elastifund-kills.json`
- `infra/index_templates/elastifund-latency.json`
- `infra/index_templates/elastifund-orderbook.json`
- `infra/index_templates/elastifund-signals.json`
- `infra/index_templates/elastifund-trades.json`
- `tests/test_elastic_client.py`

Changes:
- Added explicit `host.ip` mappings with `synthetic_source_keep: "none"` to the logsdb templates.

Effect:
- The templates are closer to the intended compressed-observability posture for high-churn telemetry.

## Not Completed In This Pass

- Rust/PyO3 bridge
- ring-buffer / Disruptor runtime replacement
- private RPC / MEV relay plumbing
- execution-heartbeat integration against Polymarket's order-cancel APIs
- residential proxy / topology automation
- negative-risk conversion routing for A-6 batch execution
- full migration of all strategy code onto the shared maker-rebate fee model

## Validation Scope

Targeted tests and hygiene are required after this change set:
- wallet reconciliation tests
- sum-violation strategy tests
- fee-model tests
- CLOB/WebSocket parser tests
- Elastic template tests
- `make hygiene` because docs and templates changed
