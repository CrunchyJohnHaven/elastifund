# Research Dispatches Index

This directory contains dispatch packets for research and implementation handoffs.

## Canonical Purpose

A dispatch is a self-contained task packet with:
- objective
- context package
- explicit done criteria
- output target path

## Dispatch Families

### Active Numbered Dispatches

Naming convention:
- `DISPATCH_<id>_<slug>.md`

Rule:
- one unique dispatch ID per file
- if a collision is discovered, keep one canonical ID and renumber the others
- leave a thin pointer file at the old path when renumbering

Recent collision fixes:
- `DISPATCH_083_combinatorial_research_ingest.md` -> pointer to `DISPATCH_084_combinatorial_research_ingest.md`
- `DISPATCH_083_structural_arb_reprioritization.md` -> pointer to `DISPATCH_085_structural_arb_reprioritization.md`
- `DISPATCH_099_BTC5_truth_plumbing_and_execution_confidence.md` -> pointer to `DISPATCH_102_BTC5_truth_plumbing_and_execution_confidence.md`

### Legacy Priority Dispatches

Naming convention:
- `P0_<id>_<slug>_<tool>.md`
- `P1_<id>_<slug>_<tool>.md`
- `P2_<id>_<slug>_<tool>.md`
- `P3_<id>_<slug>_<tool>.md`

These are historical backlog records and remain valid for traceability.

## Tool Tags

- `CLAUDE_CODE`: implementation and repo surgery
- `CLAUDE_DEEP_RESEARCH`: literature and external deep research
- `CHATGPT_DEEP_RESEARCH`: browsing-heavy empirical research
- `COWORK`: collaborative analysis/planning
- `GROK`: real-time competitive/market intel

## Status Flow

`READY -> DISPATCHED -> COMPLETED -> INTEGRATED`

## Priority Legend

- `P0`: now
- `P1`: near-term
- `P2`: opportunistic
- `P3`: background

## History Pointer

Historical outlier dispatch filenames removed from this active directory are stored at:
- `research/history/2026_q1_velocity_cleanup_wave1/dispatches/`
