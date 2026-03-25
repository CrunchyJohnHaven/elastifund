#!/usr/bin/env python3
"""Proof-carrying kernel types.

Minimal immutable records used by the strike factory and proof chain.
The goal is to keep the authoritative bundle flow explicit without turning
this module into a decision authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    source_module: str
    evidence_type: str
    timestamp_utc: float
    staleness_limit_s: float
    payload: dict[str, Any]
    confidence: float
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_evidence_record(
    *,
    source_module: str,
    evidence_type: str,
    timestamp_utc: float,
    staleness_limit_s: float,
    payload: Mapping[str, Any],
    confidence: float,
) -> EvidenceRecord:
    base = {
        "source_module": source_module,
        "evidence_type": evidence_type,
        "timestamp_utc": timestamp_utc,
        "staleness_limit_s": staleness_limit_s,
        "payload": dict(payload),
        "confidence": confidence,
    }
    return EvidenceRecord(
        source_module=source_module,
        evidence_type=evidence_type,
        timestamp_utc=timestamp_utc,
        staleness_limit_s=staleness_limit_s,
        payload=dict(payload),
        confidence=confidence,
        hash=_hash_payload(base),
    )


@dataclass(frozen=True)
class ThesisRecord:
    thesis_id: str
    version: int
    hypothesis: str
    strategy_class: str
    evidence_refs: list[str]
    calibrated_probability: float
    confidence_interval: tuple[float, float]
    edge_estimate: float
    regime_context: str
    kill_rule_results: dict[str, Any]
    created_utc: float
    expires_utc: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_thesis_record(
    *,
    hypothesis: str,
    strategy_class: str,
    evidence_refs: list[str],
    calibrated_probability: float,
    confidence_interval: tuple[float, float],
    edge_estimate: float,
    regime_context: str,
    kill_rule_results: Mapping[str, Any],
    created_utc: float,
    expires_utc: float,
    version: int = 1,
) -> ThesisRecord:
    thesis_id = _hash_payload(
        {
            "hypothesis": hypothesis,
            "strategy_class": strategy_class,
            "evidence_refs": list(evidence_refs),
            "calibrated_probability": calibrated_probability,
            "confidence_interval": list(confidence_interval),
            "edge_estimate": edge_estimate,
            "regime_context": regime_context,
            "version": version,
        }
    )[:16]
    return ThesisRecord(
        thesis_id=thesis_id,
        version=version,
        hypothesis=hypothesis,
        strategy_class=strategy_class,
        evidence_refs=list(evidence_refs),
        calibrated_probability=calibrated_probability,
        confidence_interval=confidence_interval,
        edge_estimate=edge_estimate,
        regime_context=regime_context,
        kill_rule_results=dict(kill_rule_results),
        created_utc=created_utc,
        expires_utc=expires_utc,
    )


@dataclass(frozen=True)
class PromotionTicket:
    ticket_id: str
    thesis_ref: str
    evidence_refs: list[str]
    constraint_result: dict[str, Any]
    stage_gate_result: dict[str, Any]
    position_size_usd: float
    max_loss_usd: float
    execution_mode: str
    approved_utc: float
    expires_utc: float
    promotion_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_promotion_ticket(
    *,
    thesis_ref: str,
    evidence_refs: list[str],
    constraint_result: Mapping[str, Any],
    stage_gate_result: Mapping[str, Any],
    position_size_usd: float,
    max_loss_usd: float,
    execution_mode: str,
    approved_utc: float,
    expires_utc: float,
    promotion_path: str,
) -> PromotionTicket:
    ticket_id = _hash_payload(
        {
            "thesis_ref": thesis_ref,
            "evidence_refs": list(evidence_refs),
            "constraint_result": dict(constraint_result),
            "stage_gate_result": dict(stage_gate_result),
            "position_size_usd": position_size_usd,
            "max_loss_usd": max_loss_usd,
            "execution_mode": execution_mode,
            "approved_utc": approved_utc,
            "expires_utc": expires_utc,
            "promotion_path": promotion_path,
        }
    )[:16]
    return PromotionTicket(
        ticket_id=ticket_id,
        thesis_ref=thesis_ref,
        evidence_refs=list(evidence_refs),
        constraint_result=dict(constraint_result),
        stage_gate_result=dict(stage_gate_result),
        position_size_usd=position_size_usd,
        max_loss_usd=max_loss_usd,
        execution_mode=execution_mode,
        approved_utc=approved_utc,
        expires_utc=expires_utc,
        promotion_path=promotion_path,
    )


@dataclass(frozen=True)
class WalletTruthSnapshot:
    snapshot_id: str
    generated_at: str
    wallet_address: str
    control_posture: str
    truth_status: str
    open_positions_count: int
    closed_positions_count: int
    estimated_total_value_usd: float
    available_cash_usd: float
    capital_live: bool
    source_of_truth: dict[str, str] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_wallet_truth_snapshot(
    *,
    generated_at: str,
    wallet_address: str,
    control_posture: str,
    truth_status: str,
    open_positions_count: int,
    closed_positions_count: int,
    estimated_total_value_usd: float,
    available_cash_usd: float,
    capital_live: bool,
    source_of_truth: Mapping[str, str] | None = None,
    blockers: Sequence[str] | None = None,
    mismatches: Sequence[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> WalletTruthSnapshot:
    source_map = {str(key): str(value) for key, value in dict(source_of_truth or {}).items()}
    blocker_list = [str(item) for item in list(blockers or [])]
    mismatch_list = [str(item) for item in list(mismatches or [])]
    metadata_map = dict(metadata or {})
    snapshot_id = _hash_payload(
        {
            "generated_at": generated_at,
            "wallet_address": wallet_address,
            "control_posture": control_posture,
            "truth_status": truth_status,
            "open_positions_count": open_positions_count,
            "closed_positions_count": closed_positions_count,
            "estimated_total_value_usd": estimated_total_value_usd,
            "available_cash_usd": available_cash_usd,
            "capital_live": capital_live,
            "source_of_truth": source_map,
            "blockers": blocker_list,
            "mismatches": mismatch_list,
            "metadata": metadata_map,
        }
    )[:16]
    return WalletTruthSnapshot(
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        wallet_address=wallet_address,
        control_posture=control_posture,
        truth_status=truth_status,
        open_positions_count=int(open_positions_count),
        closed_positions_count=int(closed_positions_count),
        estimated_total_value_usd=float(estimated_total_value_usd),
        available_cash_usd=float(available_cash_usd),
        capital_live=bool(capital_live),
        source_of_truth=source_map,
        blockers=blocker_list,
        mismatches=mismatch_list,
        metadata=metadata_map,
    )


@dataclass(frozen=True)
class RuntimeTruthSnapshot:
    snapshot_id: str
    generated_at: str
    selected_runtime_profile: str
    execution_mode: str
    agent_run_mode: str
    launch_posture: str
    service_state: str
    allow_order_submission: bool
    truth_gate_status: str
    baseline_live_allowed: bool
    blockers: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_runtime_truth_contract_snapshot(
    *,
    generated_at: str,
    selected_runtime_profile: str,
    execution_mode: str,
    agent_run_mode: str,
    launch_posture: str,
    service_state: str,
    allow_order_submission: bool,
    truth_gate_status: str,
    baseline_live_allowed: bool,
    blockers: Sequence[str] | None = None,
    artifacts: Mapping[str, str] | None = None,
    summary: str = "",
) -> RuntimeTruthSnapshot:
    blocker_list = [str(item) for item in list(blockers or [])]
    artifact_map = {str(key): str(value) for key, value in dict(artifacts or {}).items()}
    snapshot_id = _hash_payload(
        {
            "generated_at": generated_at,
            "selected_runtime_profile": selected_runtime_profile,
            "execution_mode": execution_mode,
            "agent_run_mode": agent_run_mode,
            "launch_posture": launch_posture,
            "service_state": service_state,
            "allow_order_submission": allow_order_submission,
            "truth_gate_status": truth_gate_status,
            "baseline_live_allowed": baseline_live_allowed,
            "blockers": blocker_list,
            "artifacts": artifact_map,
            "summary": summary,
        }
    )[:16]
    return RuntimeTruthSnapshot(
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        selected_runtime_profile=selected_runtime_profile,
        execution_mode=execution_mode,
        agent_run_mode=agent_run_mode,
        launch_posture=launch_posture,
        service_state=service_state,
        allow_order_submission=bool(allow_order_submission),
        truth_gate_status=truth_gate_status,
        baseline_live_allowed=bool(baseline_live_allowed),
        blockers=blocker_list,
        artifacts=artifact_map,
        summary=str(summary or ""),
    )


@dataclass(frozen=True)
class ExecutionResult:
    result_id: str
    ticket_ref: str
    thesis_ref: str
    status: str
    filled: bool
    fill_price: float
    fill_size_usd: float
    reason: str
    causation_chain: list[str] = field(default_factory=list)
    executed_utc: float = 0.0
    raw_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearningRecord:
    trade_id: str
    thesis_ref: str
    ticket_ref: str
    outcome: str
    actual_pnl_usd: float
    predicted_edge: float
    actual_edge: float
    reflection: str
    parameter_proposals: list[dict[str, Any]] = field(default_factory=list)
    calibration_update: dict[str, Any] = field(default_factory=dict)
    written_utc: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MutationPackage:
    package_id: str
    created_at: str
    mutation_kind: str
    summary: str
    change_set: dict[str, Any]
    replay_corpus: list[str] = field(default_factory=list)
    acceptance_metrics: dict[str, Any] = field(default_factory=dict)
    selected_runtime_package: dict[str, Any] = field(default_factory=dict)
    rollback_target: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_mutation_package(
    *,
    created_at: str,
    mutation_kind: str,
    summary: str,
    change_set: Mapping[str, Any],
    replay_corpus: Sequence[str] | None = None,
    acceptance_metrics: Mapping[str, Any] | None = None,
    selected_runtime_package: Mapping[str, Any] | None = None,
    rollback_target: Mapping[str, Any] | None = None,
) -> MutationPackage:
    change_map = dict(change_set)
    replay_list = [str(item) for item in list(replay_corpus or [])]
    acceptance_map = dict(acceptance_metrics or {})
    selected_package_map = dict(selected_runtime_package or {})
    rollback_map = dict(rollback_target or {})
    package_id = _hash_payload(
        {
            "created_at": created_at,
            "mutation_kind": mutation_kind,
            "summary": summary,
            "change_set": change_map,
            "replay_corpus": replay_list,
            "acceptance_metrics": acceptance_map,
            "selected_runtime_package": selected_package_map,
            "rollback_target": rollback_map,
        }
    )[:16]
    return MutationPackage(
        package_id=package_id,
        created_at=created_at,
        mutation_kind=mutation_kind,
        summary=summary,
        change_set=change_map,
        replay_corpus=replay_list,
        acceptance_metrics=acceptance_map,
        selected_runtime_package=selected_package_map,
        rollback_target=rollback_map,
    )


@dataclass(frozen=True)
class KernelCyclePacket:
    cycle_id: str
    generated_at: str
    source_of_truth_map: dict[str, str]
    evidence_bundle: list[EvidenceRecord] = field(default_factory=list)
    thesis_bundle: list[ThesisRecord] = field(default_factory=list)
    promotion_bundle: list[PromotionTicket] = field(default_factory=list)
    learning_bundle: list[LearningRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_kernel_cycle_packet(
    *,
    cycle_id: str,
    generated_at: str,
    source_of_truth_map: Mapping[str, str],
    evidence_bundle: list[EvidenceRecord] | None = None,
    thesis_bundle: list[ThesisRecord] | None = None,
    promotion_bundle: list[PromotionTicket] | None = None,
    learning_bundle: list[LearningRecord] | None = None,
) -> KernelCyclePacket:
    return KernelCyclePacket(
        cycle_id=cycle_id,
        generated_at=generated_at,
        source_of_truth_map=dict(source_of_truth_map),
        evidence_bundle=list(evidence_bundle or []),
        thesis_bundle=list(thesis_bundle or []),
        promotion_bundle=list(promotion_bundle or []),
        learning_bundle=list(learning_bundle or []),
    )
