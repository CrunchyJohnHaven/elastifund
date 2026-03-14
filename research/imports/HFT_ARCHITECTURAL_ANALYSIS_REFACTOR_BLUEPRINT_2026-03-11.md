# HFT Architectural Analysis And Refactoring Blueprint (Imported Research)

**Imported:** 2026-03-11  
**Source:** Operator-provided research brief (Codex session input)  
**Status:** `imported_for_integration`  
**Canonical integration targets:** `docs/ops/hft_refactor_blueprint.md`, `reports/hft_refactor/latest.json`

## Purpose

This file preserves the research packet as an operator artifact and normalizes it into implementation-facing claims.
It is not a replacement for machine-truth runtime artifacts.

When this file conflicts with live wallet/runtime telemetry, wallet and runtime truth win.

## Extracted Diagnosis

1. The system is technically active but operationally stalled by launch-profile drift and attribution incoherence.
2. Legacy taker/latency assumptions are mismatched with a maker-rebate market structure.
3. Runtime truth drift between local SQLite state and remote wallet state can misfire risk gating.
4. Existing components show localized edge, but not stable deployment posture at the system level.
5. Microstructure and concurrency constraints need a clear separation between control plane and hot path execution.

## Extracted Architectural Direction

1. Treat remote wallet truth as authoritative whenever local artifacts drift.
2. Keep Python as control plane; move latency-critical execution and book math to Rust over time.
3. Enforce strict maker-only execution (`post_only`) for fee-bearing lanes.
4. Add explicit microstructure defenses (OFI + VPIN) to protect passive orders.
5. Add non-linear cross-asset signal work (STE) instead of relying on linear-only causality tests.
6. Keep A-6/B-1/NegRisk work tightly gated by executable density and settlement evidence.
7. Move to a staged rollout contract with measurable gate checks, not one-shot rewrites.

## Claims Requiring Local Verification Before Promotion

1. Trade win/loss and ARR figures from narrative text must be re-verified against checked-in runtime artifacts and wallet exports.
2. Venue infrastructure assumptions and latency topology claims require active environment measurement before infra migration.
3. Any network/proxy topology must pass legal/compliance and platform-policy constraints before implementation.

## Non-Negotiable Repo Guardrails (Applied)

1. Finance autonomy caps and reserve-floor policy remain in force.
2. Trading-sensitive paths (`bot/`, `execution/`, `strategies/`, `signals/`, `infra/`) require tests plus evidence.
3. Runtime artifact contracts remain machine-readable and versioned under `reports/`.
4. No direct live promotion for any lane without explicit gate pass artifacts.

## Integration Result

The research has been converted into:

1. A phased refactor blueprint: `docs/ops/hft_refactor_blueprint.md`
2. A machine-readable program task contract: `reports/hft_refactor/latest.json`
3. A backlog-level activation note in `research/edge_backlog_ranked.md`
