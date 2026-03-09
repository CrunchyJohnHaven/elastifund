# Non-Trading Lane

This directory holds Elastifund's second revenue lane: automation intended to generate cash flow outside prediction-market trading.

## Current Status

Two non-trading subsystems already exist:

- `nontrading/main.py`: a compliance-first revenue agent with lead import, policy gating, suppression handling, unsubscribe support, dry-run sending, and provider adapters
- `nontrading/digital_products/main.py`: a digital-product niche discovery pipeline that ranks opportunities and emits Elastic-ready knowledge documents

What is not built yet:

- the recommended phase-1 production wedge from the design doc: a self-serve website growth audit and recurring monitor
- hosted checkout, billing webhooks, provisioning, and fulfillment reporting
- a production KPI dashboard for non-trading revenue

## Safe Defaults

- Revenue-agent sending defaults to `dry_run`.
- The current outbound lane should be treated as a compliance harness and future phase-2 engine, not the first production wedge.
- The digital-products lane is research and prioritization infrastructure, not listing automation.

## Commands

Targeted tests:

```bash
make test-nontrading
```

Deterministic smoke run for both non-trading lanes:

```bash
make smoke-nontrading
```

Run the revenue-agent harness directly:

```bash
python3 -m nontrading.main --run-once --import-csv nontrading/tests/fixtures/sample_leads.csv
```

Run the digital-product niche discovery lane directly:

```bash
python3 -m nontrading.digital_products.main \
  --run-once \
  --source-file nontrading/tests/fixtures/sample_product_niches.json \
  --top 5
```

## Development Order

1. Keep the current harnesses green with tests and smoke runs.
2. Build the website growth audit and recurring monitor path described in [docs/NON_TRADING_EARNING_AGENT_DESIGN.md](/Users/johnbradley/Desktop/Elastifund/docs/NON_TRADING_EARNING_AGENT_DESIGN.md).
3. Add checkout, fulfillment, and reporting before treating the non-trading lane as revenue-bearing.
