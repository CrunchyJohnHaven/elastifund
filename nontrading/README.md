# Non-Trading Lane

`nontrading/` is the JJ-N product lane: revenue workflow automation plus finance control-plane execution.

## Canonical Package Map

- Package map and ownership guide: `nontrading/PACKAGE_MAP.md`
- Revenue lane runtime: `python -m nontrading --run-once ...`
- Finance control plane runtime: `python -m nontrading.finance sync|audit|allocate|execute`
- Digital product research lane: `python -m nontrading.digital_products --run-once ...`

## Current Workflow State

- **Manual-close-ready surface**: Website Growth Audit discovery, scoring, outreach sequencing, and approval gating.
- **Automated-checkout-ready surface**: Revenue-audit checkout + webhook + fulfillment pipeline exists but remains launch-gated by operator policy and environment readiness.
- **Finance control plane**: import/sync, subscription audit, allocator planning, and action queue execution are active with policy rails.

## Operator Entrypoints

```bash
# Revenue lane (JJ-N pipeline)
python -m nontrading --run-once --import-csv nontrading/tests/fixtures/sample_leads.csv

# Finance control plane
python -m nontrading.finance sync
python -m nontrading.finance audit
python -m nontrading.finance allocate
python -m nontrading.finance execute --mode shadow

# Digital products research lane
python -m nontrading.digital_products \
  --run-once \
  --source-file nontrading/tests/fixtures/sample_product_niches.json \
  --top 5
```

## Workflow Boundaries

- `nontrading/main.py` runs the five-stage revenue pipeline (`Account Intelligence -> Outreach -> Interaction -> Proposal -> Learning`).
- `nontrading/revenue_audit/` owns checkout and fulfillment contracts for the Website Growth Audit offer.
- `nontrading/finance/` is treasury-sensitive and must stay policy-aligned with `AGENTS.md` and `docs/ops/finance_control_plane.md`.
- `nontrading/digital_products/` is opportunity research and CRM feed infrastructure, not autonomous listing/publishing.

## Compatibility Surfaces (Intentional)

- `nontrading/approval_gate.py` is an explicit compatibility shim re-exporting `ApprovalGate` from `nontrading/approval.py`.
- `nontrading/engines/*` keep `process()`-style compatibility paths for Phase 0 callers while `nontrading/pipeline.py` is the canonical orchestrator.

## Verification

```bash
make test-nontrading
make smoke-nontrading
```

## Related Docs

- `../docs/NON_TRADING_STATUS.md`
- `../docs/NON_TRADING_EARNING_AGENT_DESIGN.md`
