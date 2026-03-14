# Instance 02 — Ops Truth Cleanup Dispatch

Status: complete
Instance: 2 (Claude Code | Opus 4.6)
Date: 2026-03-11

## Objective

Fix champion extraction, remove the legacy ARR chart blocker, add champion-delta tracking, and separate benchmark from live posture blockers in the morning packet.

## Changes Made

### 1. Champion extraction uses rich metadata

**File:** `scripts/btc5_dual_autoresearch_ops.py` — `_extract_champion()`

- Loss is now extracted from the `champion` dict first, then falls back to top-level fields. Previously the market lane showed `loss: null` because the loss was nested inside `champion.loss`.
- `candidate_model_name` and `candidate_label` are now surfaced as `model_name` in the champion dict.
- `policy_id` is extracted when present.
- `updated_at` prefers the champion dict's timestamp over the top-level artifact timestamp.

**Before:** Market champion showed hash as id, loss=null, no model name.
**After:** Market champion shows `id=baseline-market`, `loss=5.178`, `model_name=empirical_backoff_v1`.

### 2. Policy ARR chart removed from blocking logic

**File:** `scripts/btc5_dual_autoresearch_ops.py` — `LANE_SPECS["policy"]`

- Changed `chart_paths=("research/btc5_arr_progress.svg",)` to `chart_paths=()`.
- Only market-model and command-node charts are required benchmark charts per the objective spec.
- This eliminates the `stale_chart:research/btc5_arr_progress.svg` blocker that was marking the policy lane as degraded and polluting the top-level blocker list.

### 3. Champion-delta fields in morning packet

**File:** `scripts/btc5_dual_autoresearch_ops.py` — new `_build_champion_deltas()` + updated `build_morning_packet()`

- `build_morning_packet` now accepts `previous_champions` dict.
- `write_morning_packet` loads previous champions from the ops state file and saves current champions after writing.
- Morning packet now includes `champion_deltas` with per-lane fields:
  - `previous_champion`: full champion dict from last run (or null)
  - `current_champion`: full champion dict from this run (or null)
  - `changed`: boolean, true if champion id differs
  - `delta_if_comparable`: float loss delta (current - previous) when both have numeric loss, else null

### 4. Benchmark vs live posture blockers separated

**File:** `scripts/btc5_dual_autoresearch_ops.py` — `build_morning_packet()`

- New fields: `benchmark_blockers` (stale artifacts, lane-specific issues) and `live_posture_blockers` (finance gates, launch posture).
- `blockers` field retained for backward compat as the union of both lists.
- Markdown renderer now has separate sections: `## Benchmark Blockers` and `## Live Posture Blockers`.
- Summary lines use `Benchmark blockers:` and `Live posture blockers:` prefixes.
- Schema version bumped to 2.

## Quality Checklist

- [x] Market morning summary shows model name, loss, and updated time
- [x] No stale btc5_arr_progress.svg blocker remains
- [x] Morning packet clearly separates benchmark status from live posture blockers
- [x] Tests cover market, policy, and command-node champion rendering
- [x] 9 tests passing (4 existing updated + 5 new)

## Test Coverage

| Test | What it covers |
|------|---------------|
| `test_build_lane_snapshot_extracts_market_champion_and_health` | Champion dict metadata extraction (model_name, loss) |
| `test_update_lane_state_after_run_uses_exponential_backoff` | Backoff logic (unchanged) |
| `test_build_morning_packet_collects_keeps_promotions_and_crashes` | Full morning packet assembly across 3 lanes |
| `test_run_lane_skips_during_backoff_and_appends_audit_rows` | Supervised run with audit trail |
| `test_champion_extraction_uses_rich_metadata` | Rich champion dict fields (model_name, loss from nested dict) |
| `test_policy_lane_no_arr_chart_blocker` | Policy lane has no ARR chart blocker |
| `test_champion_delta_fields_in_morning_packet` | Champion deltas with changed/unchanged/delta_if_comparable |
| `test_morning_packet_separates_benchmark_and_live_blockers` | Blocker separation (benchmark vs live posture) |
| `test_morning_markdown_shows_model_name_and_deltas` | Markdown rendering of model names, deltas, separated blockers |

## Files Modified

- `scripts/btc5_dual_autoresearch_ops.py`
- `tests/test_btc5_dual_autoresearch_ops.py`

## Artifacts

- `instance02_ops_truth_cleanup_dispatch.md` (this file)
