# Instance 03 — Outcome Surfaces and Honest Overnight Gate

Status: **COMPLETE**
Instance: Claude Code | Opus 4.6
Generated: 2026-03-11

## Objective

Promote outcome surfaces (ARR, USD/day) to first-class operator artifacts, integrate them into morning and overnight packets as companion outcome estimates clearly separated from benchmark loss metrics, and harden the overnight gate to prevent short local runs from producing green.

## Deliverables

### 1. USD/day Outcome Chart Renderer

**File:** `scripts/render_btc5_usd_per_day_progress.py`

- Mirrors the structure of `render_btc5_arr_progress.py`.
- Reads from `reports/autoresearch/outcomes/history.jsonl` (append-only ledger).
- Renders `research/btc5_usd_per_day_progress.svg` — wallet-scaled USD/day time series with expected (MC median), historical replay, and frontier expected lines.
- Writes machine-readable `reports/autoresearch/outcomes/latest.json`.
- `build_outcome_summary()` accepts optional `portfolio_expectation` dict for live data enrichment.

### 2. Outcome Surfaces Integrated into Dual Autoresearch Ops

**File:** `scripts/btc5_dual_autoresearch_ops.py`

Changes:

- **New constants:** `OUTCOME_HISTORY_RELATIVE`, `OUTCOME_LATEST_RELATIVE`, `PORTFOLIO_EXPECTATION_RELATIVE`, `ARR_SVG_RELATIVE`, `USD_PER_DAY_SVG_RELATIVE`.
- **New functions:**
  - `_load_portfolio_expectation()` — reads `reports/btc5_portfolio_expectation/latest.json`.
  - `_load_outcome_summary()` — reads `reports/autoresearch/outcomes/latest.json`.
  - `_build_outcome_surfaces()` — builds outcome surface block from portfolio expectation, including expected/historical USD/day, fills/day, 30d projection, edge status, and chart existence flags.
  - `append_outcome_record()` — appends a single outcome record to the history ledger from the current portfolio expectation; called after each lane run in `run_lane()`.
- **Surface snapshot:** `public_charts` now includes `arr_outcome` and `usd_per_day_outcome` entries with `benchmark_progress_only: false`.
- **Morning packet:** schema_version bumped to 3; includes `outcome_surfaces` block.
- **Overnight closeout:** schema_version bumped to 2; includes `outcome_surfaces` block.
- **Morning markdown:** new "## Outcome Charts (estimates, not benchmark loss)" section after benchmark charts, showing USD/day, fills/day, edge status.
- **Overnight markdown:** new "## Outcome Surfaces (estimates, not benchmark loss)" section before service audit, showing expected/historical USD/day, fills/day, 30d projection, edge status, chart paths.

### 3. Overnight Gate (Already Hardened)

The existing gate already enforces all required checks:

| Check | Requirement | Status |
|-------|------------|--------|
| `service_audit_span_at_least_8h` | >= 8 hours of audit span | Enforced |
| `market_runs_at_least_4` | >= 4 market runs in window | Enforced |
| `command_node_runs_at_least_4` | >= 4 command-node runs in window | Enforced |
| `market_fresh` | Fresh market artifact | Enforced |
| `command_node_fresh` | Fresh command-node artifact | Enforced |
| `no_lane_crashes` | Zero lane crashes (including policy) | Enforced |

**Key behavior:** Policy lane is reported in all packets but its crash does block green (consistent with dispatch spec: "it does not block green for this objective unless it crashes").

A null-result overnight (no better candidates found) passes honestly with green if all gate checks pass.

## Test Coverage

### New test files:

**`tests/test_render_btc5_usd_per_day_progress.py`** (6 tests)
- `test_load_records_parses_history` — verifies record loading and frontier tracking.
- `test_load_records_empty_file` — graceful empty handling.
- `test_build_outcome_summary_from_records` — summary from ledger records.
- `test_build_outcome_summary_with_portfolio_expectation` — summary from live PE data.
- `test_render_svg_creates_valid_svg` — valid SVG output with data.
- `test_render_svg_empty_records` — empty SVG placeholder.

**`tests/test_outcome_surfaces_and_overnight_gate.py`** (12 tests)
- `test_morning_packet_includes_outcome_surfaces` — outcome_surfaces block present with correct values.
- `test_overnight_closeout_includes_outcome_surfaces` — outcome_surfaces in closeout.
- `test_surface_snapshot_includes_outcome_charts` — arr_outcome and usd_per_day_outcome in public_charts.
- `test_append_outcome_record_writes_to_ledger` — ledger append works.
- `test_append_outcome_record_returns_none_without_pe` — graceful without PE.
- `test_overnight_gate_rejects_short_local_run` — short run (< 8h, < 4 runs) produces red.
- `test_overnight_gate_rejects_missing_market_runs` — 8h span but < 4 market runs is red.
- `test_overnight_gate_passes_valid_null_result_night` — null-result with all criteria met is green.
- `test_overnight_gate_rejects_lane_crash` — command_node crash blocks green.
- `test_overnight_gate_policy_crash_blocks_green` — policy crash blocks green.
- `test_morning_markdown_separates_benchmark_and_outcome_charts` — markdown has separate sections.
- `test_overnight_markdown_includes_outcome_section` — outcome surfaces in closeout markdown.

### Regression: 12/12 existing `test_btc5_dual_autoresearch_ops.py` tests pass. Zero regressions.

## Quality Checklist

- [x] Morning and overnight packets show benchmark charts and outcome charts separately
- [x] USD/day is first-class and machine-readable (`reports/autoresearch/outcomes/latest.json`)
- [x] A short local run can no longer produce green (8h span + 4 runs per lane required)
- [x] A null-result overnight can still pass honestly if no better candidate is found
- [x] Outcome surfaces clearly labeled as estimates, not benchmark loss metrics
- [x] 30 tests total (18 new + 12 existing), all passing

## File Manifest

| File | Action |
|------|--------|
| `scripts/render_btc5_usd_per_day_progress.py` | **NEW** — USD/day chart renderer |
| `scripts/btc5_dual_autoresearch_ops.py` | **MODIFIED** — outcome surfaces + gate integration |
| `tests/test_render_btc5_usd_per_day_progress.py` | **NEW** — 6 tests |
| `tests/test_outcome_surfaces_and_overnight_gate.py` | **NEW** — 12 tests |
| `instance03_outcome_surfaces_dispatch.md` | **NEW** — this dispatch |
