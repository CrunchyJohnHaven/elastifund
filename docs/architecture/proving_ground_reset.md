# Proving-Ground Reset

**Status:** Implementing Phase 1
**Role:** Operational reset contract for runtime truth, wallet truth, and proving-ground scope
**Date:** 2026-03-24

This document is the bridge between the broader architecture designs and the
current implementation reset. Its job is to say what is authoritative now.

## Current Reality

- No durable edge is proven yet.
- BTC5 is the proving ground because it has the deepest execution history and the clearest failure evidence.
- Multi-venue autonomy remains the target, but not the immediate live scope.
- Control-plane ambiguity is treated as a defect, not a tolerable operating condition.

## Hard Rules

- `execution_mode` is a first-class contract: `blocked`, `shadow`, or `live`.
- Profiles intended for real order submission must declare `execution_mode=live`; they may not hide behind `shadow` with `paper_trading=false`.
- Wallet truth is authoritative for capital posture. If wallet truth is stale, contradictory, or blocked, autonomous live trading must degrade away from live execution.
- `runtime_truth_latest` remains the broad runtime report, and the typed runtime-truth snapshot is the contract alias for downstream control-plane consumers.
- The typed wallet-truth snapshot is the contract alias derived from canonical truth reconciliation.

## Phase 1 Deliverables

- Remove runtime-mode contradictions from checked-in profiles.
- Emit typed runtime and wallet truth snapshots with stable IDs and explicit blockers.
- Keep autonomous live execution fail-closed until launch posture, service state, wallet truth, and test truth agree.

## Near-Term Scope

- Polymarket BTC5 is the only venue eligible for proving-ground graduation.
- Kalshi and Alpaca stay architecture-conforming but non-graduated during the reset.
- Research automation can keep generating candidate mutations, but promotion still requires replay, attribution, and truth-gate integrity.
