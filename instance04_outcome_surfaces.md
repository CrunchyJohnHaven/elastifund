# Instance 4 - ARR and USD/Day Outcome Surfaces

Status: **COMPLETE**
Owner model: Claude Code | Opus 4.6
Validated: 2026-03-11

## Objective

Promote ARR and USD/day to first-class BTC5 operator outcome surfaces, keep them clearly separate from benchmark-loss charts, and make the overnight closeout require a real unattended window instead of a short local refresh.

## What Landed

### Outcome charts

- `research/btc5_arr_progress.svg` remains the ARR outcome chart.
- `research/btc5_usd_per_day_progress.svg` is now the USD/day outcome chart.
- `reports/autoresearch/outcomes/latest.json` is the machine-readable outcome surface snapshot.
- `reports/autoresearch/outcomes/history.jsonl` remains append-only.

### Runtime integration

- `scripts/render_btc5_usd_per_day_progress.py` renders the USD/day chart and summary from the outcome ledger, with optional portfolio-expectation enrichment.
- `scripts/btc5_dual_autoresearch_ops.py` now:
  - refreshes outcome surfaces alongside the lane surface snapshot
  - appends wallet-scaled outcome records from `reports/btc5_portfolio_expectation/latest.json`
  - exposes ARR and USD/day separately from benchmark charts in the morning packet
  - exposes ARR and USD/day separately from benchmark charts in the overnight closeout
  - enforces the honest overnight gate: audit span >= 8h, at least 4 market runs, at least 4 command-node runs, fresh objective-lane artifacts, zero lane crashes

### Machine-readable fields

`reports/autoresearch/outcomes/latest.json` includes:

- `expected_arr_pct`
- `expected_usd_per_day`
- `expected_pnl_30d_usd`
- `expected_fills_per_day`
- `current_live`
- `best_validated_variant`
- `current_vs_best_validated`

## Key Files

- `scripts/render_btc5_usd_per_day_progress.py`
- `scripts/btc5_dual_autoresearch_ops.py`
- `tests/test_render_btc5_usd_per_day_progress.py`
- `tests/test_outcome_surfaces_and_overnight_gate.py`

## Verification

Executed:

```bash
pytest tests/test_render_btc5_usd_per_day_progress.py \
  tests/test_outcome_surfaces_and_overnight_gate.py \
  tests/test_btc5_dual_autoresearch_ops.py \
  tests/test_btc5_portfolio_expectation.py \
  tests/test_btc5_dual_autoresearch_e2e_integration.py
```

Result:

- `39 passed in 1.30s`

## Acceptance

- ARR and USD/day are first-class operator outputs: **PASS**
- Benchmark loss and business outcomes are separated in packets and markdown: **PASS**
- Short local runs cannot produce green overnight status: **PASS**
- Null-result overnights remain valid when explicit and fully supervised: **PASS**

## Follow-on Boundary

Instance 4 is complete in the repo workspace.
The remaining objective depends on Instance 5 burn-in proving the mutation-loop services can hold an unattended AWS window under the hardened gate.
