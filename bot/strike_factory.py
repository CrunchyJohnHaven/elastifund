#!/usr/bin/env python3
"""Strike Factory orchestration layer.

Runs the revenue-first ordering for structural lanes:
strike desk -> event tape -> promotion snapshot -> optional harness.

This is intentionally a thin coordinator. The decision logic stays in the
existing desk, tape, promotion, and harness modules.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bot.event_tape import EventTapeWriter
from bot.promotion_manager import PromotionManager
from bot.proof_types import (
    EvidenceRecord,
    KernelCyclePacket,
    LearningRecord,
    PromotionTicket,
    ThesisRecord,
    build_evidence_record,
    build_kernel_cycle_packet,
    build_promotion_ticket,
    build_thesis_record,
)
from bot.strike_desk import ExecutionPacket, StrikeDesk
from scripts.report_envelope import write_report


DEFAULT_OUTPUT_PATH = Path("reports/strike_factory/latest.json")
DEFAULT_MARKDOWN_PATH = Path("reports/strike_factory/latest.md")
DEFAULT_TAPE_DB_PATH = Path("data/tape/strike_factory.db")
DEFAULT_PROMOTION_DB_PATH = Path("data/promotion_manager.db")
DEFAULT_RESOLUTION_MARKETS_PATH = Path("reports/parallel/current_btc5_dual_sided_markets.json")
DEFAULT_LAUNCH_ORDER = [
    "resolution",
    "whale",
    "neg_risk",
    "cross_plat",
    "leader_follower",
    "llm_tournament",
    "btc5",
]
DEFAULT_SOURCE_OF_TRUTH_MAP = {
    "evidence": "reports/evidence_bundle.json",
    "thesis": "reports/thesis_bundle.json",
    "promotion": "reports/promotion_bundle.json",
    "learning": "reports/learning_bundle.json",
    "execution": "bot.jj_live.place_order",
}


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _packet_summary(packet: ExecutionPacket) -> dict[str, Any]:
    payload = packet.to_dict()
    payload["linked_packets"] = list(packet.linked_packets)
    return payload


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_resolution_markets(
    path: Path = DEFAULT_RESOLUTION_MARKETS_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load and normalize the local BTC5 dual-sided resolution fixture."""
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    if not path.exists():
        return [], {"path": str(path), "loaded": False, "reason": "missing", "count": 0}

    try:
        payload = _load_json(path)
    except Exception as exc:
        return [], {
            "path": str(path),
            "loaded": False,
            "reason": f"load_failed:{type(exc).__name__}",
            "count": 0,
        }

    if not isinstance(payload, list):
        return [], {"path": str(path), "loaded": False, "reason": "unexpected_shape", "count": 0}

    markets: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        market_id = str(row.get("market_id") or "").strip()
        question = str(row.get("question") or "").strip()
        if not market_id or not question:
            continue
        yes_price = float(row.get("yes_price") or 0.5)
        no_price = float(row.get("no_price") or (1.0 - yes_price))
        liquidity_usd = float(row.get("liquidity_usd") or 0.0)
        resolution_hours = float(row.get("resolution_hours") or 24.0)
        markets.append(
            {
                "market_id": market_id,
                "question": question,
                "yes_price": yes_price,
                "no_price": no_price,
                "resolution_source": "btc5_dual_sided_fixture",
                "volume_24h": liquidity_usd,
                "resolution_eta_hours": resolution_hours,
                "best_bid": yes_price,
                "best_ask": float(row.get("yes_best_ask") or row.get("no_best_ask") or 0.99),
                "bid_depth_usd": liquidity_usd,
                "ask_depth_usd": liquidity_usd,
                "mid": 0.5,
                "venue": str(row.get("venue") or "polymarket"),
                "source_artifact": str(path),
                "combined_bid_cost": row.get("combined_bid_cost"),
                "timestamp": row.get("timestamp"),
            }
        )

    return markets, {
        "path": str(path),
        "loaded": True,
        "reason": "fixture",
        "count": len(markets),
    }


def build_default_strike_factory_packets(
    desk: StrikeDesk | None = None,
    markets_path: Path = DEFAULT_RESOLUTION_MARKETS_PATH,
) -> tuple[list[ExecutionPacket], dict[str, Any]]:
    """Build the default shadow packet set from the local BTC5 resolution fixture."""
    desk = desk or StrikeDesk()
    markets, source_info = _load_resolution_markets(markets_path)
    if not markets:
        source_info["raw_packet_count"] = 0
        return [], source_info
    raw_packets = asyncio.run(desk._scan_resolution(markets))
    source_info["raw_packet_count"] = len(raw_packets)
    source_info["lane"] = "resolution"
    return raw_packets, source_info


def _build_thesis_for_packet(packet: ExecutionPacket, *, now: datetime) -> ThesisRecord:
    """Derive a thesis record from a desk packet without mutating the desk."""
    calibrated_probability = max(0.0, min(1.0, float(packet.confidence)))
    spread = min(0.25, max(0.02, 0.10 + abs(packet.edge_estimate) * 0.10))
    confidence_interval = (
        max(0.0, calibrated_probability - spread),
        min(1.0, calibrated_probability + spread),
    )
    return build_thesis_record(
        hypothesis=f"{packet.strategy_id}:{packet.market_id}:{packet.direction}",
        strategy_class=packet.strategy_id,
        evidence_refs=[packet.evidence_hash],
        calibrated_probability=calibrated_probability,
        confidence_interval=confidence_interval,
        edge_estimate=float(packet.edge_estimate),
        regime_context=str(packet.metadata.get("regime_context", "live") or "live"),
        kill_rule_results={
            "passed": True,
            "reason": "strike_factory_queue",
            "market_id": packet.market_id,
            "strategy_id": packet.strategy_id,
        },
        created_utc=packet.timestamp,
        expires_utc=packet.timestamp + float(packet.ttl_seconds),
    )


def _build_ticket_for_packet(
    packet: ExecutionPacket,
    thesis: ThesisRecord,
    *,
    pm: PromotionManager | None,
    execution_mode: str,
    now: datetime,
) -> PromotionTicket:
    if pm is not None:
        rec = pm.get_strategy(packet.strategy_id)
        if rec is None:
            rec = pm.register_strategy(packet.strategy_id)
        stage_gate_result = {
            "registered": True,
            "current_stage": rec.current_stage.name,
            "position_cap_usd": pm.get_position_cap(packet.strategy_id),
            "capital_allocation_usd": pm.get_capital_allocation(packet.strategy_id),
            "promotion_check": pm.check_promotion(packet.strategy_id),
        }
    else:
        stage_gate_result = {
            "registered": False,
            "current_stage": "UNREGISTERED",
            "position_cap_usd": packet.size_usd,
            "capital_allocation_usd": packet.size_usd,
            "promotion_check": {"eligible": False, "gates_failed": ["promotion_manager_unavailable"]},
        }

    constraint_result = {
        "allowed": True,
        "reason": "strike_desk_queue_approved",
        "launch_priority": packet.priority,
        "order_type": packet.order_type,
    }
    position_size_usd = round(float(packet.size_usd), 2)
    max_loss_usd = round(position_size_usd, 2)
    return build_promotion_ticket(
        thesis_ref=thesis.thesis_id,
        evidence_refs=list(thesis.evidence_refs),
        constraint_result=constraint_result,
        stage_gate_result=stage_gate_result,
        position_size_usd=position_size_usd,
        max_loss_usd=max_loss_usd,
        execution_mode=execution_mode,
        approved_utc=now.timestamp(),
        expires_utc=packet.timestamp + float(packet.ttl_seconds),
        promotion_path="revenue_first_strike_factory",
    )


@dataclass
class StrikeFactoryRun:
    generated_at: str
    cycle_id: str
    launch_order: list[str]
    raw_packet_count: int
    approved_packet_count: int
    rejected_packet_count: int
    lane_counts: dict[str, int] = field(default_factory=dict)
    priority_counts: dict[str, int] = field(default_factory=dict)
    queue: list[dict[str, Any]] = field(default_factory=list)
    rejected_packets: list[dict[str, Any]] = field(default_factory=list)
    promotion_tickets: list[dict[str, Any]] = field(default_factory=list)
    proof_chain: list[dict[str, Any]] = field(default_factory=list)
    kernel_cycle: dict[str, Any] = field(default_factory=dict)
    event_tape: dict[str, Any] = field(default_factory=dict)
    promotion_snapshot: dict[str, Any] = field(default_factory=dict)
    execution_summary: dict[str, Any] = field(default_factory=dict)
    harness_snapshot: dict[str, Any] | None = None
    source_mode: str = ""
    source_inputs: dict[str, Any] = field(default_factory=dict)
    status: str = "fresh"
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _write_markdown(report: StrikeFactoryRun, path: Path) -> None:
    lines = [
        "# Strike Factory",
        "",
        f"- generated_at: `{report.generated_at}`",
        f"- cycle_id: `{report.cycle_id}`",
        f"- launch_order: `{', '.join(report.launch_order)}`",
        f"- raw_packets: `{report.raw_packet_count}`",
        f"- approved_packets: `{report.approved_packet_count}`",
        f"- rejected_packets: `{report.rejected_packet_count}`",
        f"- tape_events: `{report.event_tape.get('event_count', 0)}`",
        f"- tape_db: `{report.event_tape.get('db_path', '')}`",
        "",
        "## Queue",
        "",
    ]

    if report.queue:
        lines.append("| priority | strategy | market | platform | direction | size_usd | edge_estimate |")
        lines.append("|---|---|---|---|---|---:|---:|")
        for item in report.queue[:12]:
            lines.append(
                "| {priority} | {strategy_id} | {market_id} | {platform} | {direction} | {size_usd:.2f} | {edge_estimate:.4f} |".format(
                    priority=item.get("priority"),
                    strategy_id=item.get("strategy_id", ""),
                    market_id=item.get("market_id", ""),
                    platform=item.get("platform", ""),
                    direction=item.get("direction", ""),
                    size_usd=float(item.get("size_usd") or 0.0),
                    edge_estimate=float(item.get("edge_estimate") or 0.0),
                )
            )
    else:
        lines.append("_No packets selected this cycle._")

    if report.promotion_snapshot:
        lines.extend([
            "",
            "## Promotion Snapshot",
            "",
            json.dumps(report.promotion_snapshot, indent=2, sort_keys=True),
        ])

    if report.kernel_cycle:
        lines.extend([
            "",
            "## Kernel Cycle",
            "",
            json.dumps(report.kernel_cycle, indent=2, sort_keys=True),
        ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_strike_factory_cycle(
    *,
    desk: StrikeDesk | None = None,
    raw_packets: list[ExecutionPacket] | None = None,
    executor: Any | None = None,
    tape_writer: EventTapeWriter | None = None,
    promotion_manager: PromotionManager | None = None,
    promotion_db_path: Path | None = None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    markdown_path: Path = DEFAULT_MARKDOWN_PATH,
    tape_db_path: Path = DEFAULT_TAPE_DB_PATH,
    run_harness: bool = False,
    harness_output_path: Path | None = None,
    launch_order: list[str] | None = None,
    source_mode: str = "",
    source_inputs: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> StrikeFactoryRun:
    now = now or datetime.now(timezone.utc)
    cycle_id = f"strike_factory:{_iso_z(now)}"
    launch_order = list(launch_order or DEFAULT_LAUNCH_ORDER)
    source_inputs = dict(source_inputs or {})

    desk = desk or StrikeDesk()
    if raw_packets is None:
        raw_packets = asyncio.run(desk.scan_all_lanes())

    raw_packets = list(raw_packets)

    close_tape_writer = tape_writer is None
    tape_writer = tape_writer or EventTapeWriter(db_path=str(tape_db_path), session_id=cycle_id)
    # Keep the desk and factory on the same proof tape.
    try:
        desk._tape_writer = tape_writer  # type: ignore[attr-defined]
    except Exception:
        pass

    event_seed = tape_writer.emit(
        "decision.strike_factory_started",
        "strike_factory",
        {
            "cycle_id": cycle_id,
            "raw_packet_count": len(raw_packets),
            "launch_order": list(launch_order),
        },
        correlation_id=cycle_id,
    )

    approved_packets = desk.generate_packets(raw_packets, launch_order=launch_order)
    approved_ids = {pkt.packet_id for pkt in approved_packets}
    rejection_map = {
        str(entry.get("packet_id")): str(entry.get("reason") or "rejected")
        for entry in getattr(desk, "_rejections", [])
        if entry.get("packet_id")
    }

    rejected_packets: list[dict[str, Any]] = []
    evidence_records: list[EvidenceRecord] = []
    thesis_records: list[ThesisRecord] = []
    promotion_tickets: list[PromotionTicket] = []
    proof_chain: list[dict[str, Any]] = []
    proof_lookup: dict[str, dict[str, str]] = {}
    for packet in raw_packets:
        evidence_record = build_evidence_record(
            source_module="strike_desk",
            evidence_type=f"lane.{packet.strategy_id}",
            timestamp_utc=packet.timestamp,
            staleness_limit_s=float(packet.ttl_seconds),
            payload={
                "packet_id": packet.packet_id,
                "strategy_id": packet.strategy_id,
                "market_id": packet.market_id,
                "platform": packet.platform,
                "direction": packet.direction,
                "size_usd": packet.size_usd,
                "edge_estimate": packet.edge_estimate,
                "confidence": packet.confidence,
                "order_type": packet.order_type,
                "metadata": dict(packet.metadata),
            },
            confidence=float(packet.confidence),
        )
        evidence_records.append(evidence_record)

        is_approved = packet.packet_id in approved_ids
        if is_approved:
            thesis_record = _build_thesis_for_packet(packet, now=now)
            thesis_records.append(thesis_record)
            ticket = _build_ticket_for_packet(
                packet,
                thesis_record,
                pm=promotion_manager,
                execution_mode="live" if executor is not None else "shadow",
                now=now,
            )
            promotion_tickets.append(ticket)
            proof_lookup[packet.packet_id] = {
                "evidence_hash": evidence_record.hash,
                "thesis_id": thesis_record.thesis_id,
                "ticket_id": ticket.ticket_id,
            }
        else:
            proof_lookup[packet.packet_id] = {
                "evidence_hash": evidence_record.hash,
                "thesis_id": "",
                "ticket_id": "",
            }

        proposal = tape_writer.emit_decision(
            "trade_proposed",
            {
                "packet_id": packet.packet_id,
                "strategy_id": packet.strategy_id,
                "market_id": packet.market_id,
                "platform": packet.platform,
                "direction": packet.direction,
                "size_usd": packet.size_usd,
                "edge_estimate": packet.edge_estimate,
                "confidence": packet.confidence,
                "priority": packet.priority,
                "order_type": packet.order_type,
                "packet": _packet_summary(packet),
            },
            source="strike_factory",
            causation_seq=event_seed.seq,
            correlation_id=cycle_id,
        )
        if is_approved:
            thesis = thesis_records[-1]
            ticket = promotion_tickets[-1]
            thesis_evt = tape_writer.emit_decision(
                "thesis_recorded",
                {
                    "packet_id": packet.packet_id,
                    "thesis_id": thesis.thesis_id,
                    "hypothesis": thesis.hypothesis,
                    "strategy_class": thesis.strategy_class,
                    "evidence_refs": list(thesis.evidence_refs),
                    "edge_estimate": thesis.edge_estimate,
                    "confidence_interval": list(thesis.confidence_interval),
                },
                source="strike_factory",
                causation_seq=proposal.seq,
                correlation_id=cycle_id,
            )
            tape_writer.emit_decision(
                "promotion_ticket_issued",
                {
                    "packet_id": packet.packet_id,
                    "strategy_id": packet.strategy_id,
                    "market_id": packet.market_id,
                    "ticket_id": ticket.ticket_id,
                    "thesis_id": thesis.thesis_id,
                    "position_size_usd": ticket.position_size_usd,
                    "max_loss_usd": ticket.max_loss_usd,
                    "execution_mode": ticket.execution_mode,
                    "constraint_result": ticket.constraint_result,
                    "stage_gate_result": ticket.stage_gate_result,
                    "proof_chain": {
                        "evidence_hash": evidence_record.hash,
                        "thesis_id": thesis.thesis_id,
                        "ticket_id": ticket.ticket_id,
                    },
                },
                source="strike_factory",
                causation_seq=thesis_evt.seq,
                correlation_id=cycle_id,
            )
            proof_chain.append({
                "packet_id": packet.packet_id,
                "evidence_hash": evidence_record.hash,
                "thesis_id": thesis.thesis_id,
                "ticket_id": ticket.ticket_id,
            })
        else:
            reason = rejection_map.get(packet.packet_id, "not_selected_by_strike_desk")
            rejected_payload = {
                "packet_id": packet.packet_id,
                "strategy_id": packet.strategy_id,
                "market_id": packet.market_id,
                "reason": reason,
                "packet": _packet_summary(packet),
            }
            tape_writer.emit_decision(
                "trade_rejected",
                rejected_payload,
                source="strike_factory",
                causation_seq=proposal.seq,
                correlation_id=cycle_id,
            )
            rejected_packets.append(rejected_payload)

    queue = [_packet_summary(packet) for packet in approved_packets]
    for queue_item in queue:
        proof = proof_lookup.get(queue_item.get("packet_id", ""), {})
        queue_item.update(
            {
                "evidence_hash": proof.get("evidence_hash", ""),
                "thesis_id": proof.get("thesis_id", ""),
                "ticket_id": proof.get("ticket_id", ""),
            }
        )
    if approved_packets or rejected_packets:
        tape_writer.emit_shadow_alternative(
            chosen_action=approved_packets[0].packet_id if approved_packets else "none",
            rejected_actions=rejected_packets,
            source="strike_factory",
            causation_seq=event_seed.seq,
            correlation_id=cycle_id,
            metadata={
                "approved_packet_ids": [packet.packet_id for packet in approved_packets],
                "queue_length": len(approved_packets),
            },
        )

    lane_counts = dict(Counter(packet.strategy_id for packet in approved_packets))
    priority_counts = dict(Counter(str(packet.priority) for packet in approved_packets))

    execution_summary = asyncio.run(
        desk.execute_queue(
            approved_packets,
            executor=executor,
            tape_writer=tape_writer,
            allow_taker_fallback=False,
        )
    )

    blockers: list[str] = []
    if not raw_packets:
        blockers.append("no_raw_packets")
    if not approved_packets:
        blockers.append("no_approved_packets")
    if executor is not None and execution_summary.get("submitted", 0) == 0:
        blockers.append("no_executable_packets")
    report_status = "blocked" if blockers else "fresh"

    promotion_snapshot: dict[str, Any] = {}
    pm_path = promotion_db_path or DEFAULT_PROMOTION_DB_PATH
    if promotion_manager is not None or pm_path.exists():
        pm = promotion_manager or PromotionManager(str(pm_path))
        strategies = []
        for packet in approved_packets:
            rec = pm.get_strategy(packet.strategy_id)
            if rec is None:
                pm.register_strategy(packet.strategy_id)
                rec = pm.get_strategy(packet.strategy_id)
            if rec is None:
                continue
            strategies.append(
                {
                    "strategy_id": rec.strategy_id,
                    "stage": rec.current_stage.name,
                    "fills": rec.fills,
                    "win_rate": rec.win_rate,
                    "profit_factor": rec.profit_factor,
                    "position_cap_usd": pm.get_position_cap(rec.strategy_id),
                    "capital_allocation_usd": pm.get_capital_allocation(rec.strategy_id),
                }
            )
        promotion_snapshot = {
            "stage_summary": pm.get_stage_summary(),
            "strategies": strategies,
        }
        if promotion_manager is None:
            pm.close()

    harness_snapshot: dict[str, Any] | None = None
    learning_bundle: list[LearningRecord] = []
    if run_harness:
        from scripts.intelligence_harness import run_full_harness

        harness = run_full_harness(output_path=harness_output_path)
        harness_snapshot = harness.to_dict()
        if promotion_tickets:
            top_ticket = promotion_tickets[0]
            learning_bundle.append(
                LearningRecord(
                    trade_id=cycle_id,
                    thesis_ref=top_ticket.thesis_ref,
                    ticket_ref=top_ticket.ticket_id,
                    outcome="win" if harness.harness_passed else "loss",
                    actual_pnl_usd=0.0,
                    predicted_edge=0.0,
                    actual_edge=0.0,
                    reflection="strike_factory harness snapshot",
                    parameter_proposals=[],
                    calibration_update={
                        "harness_passed": harness.harness_passed,
                        "failure_summary": list(harness.failure_summary),
                    },
                    written_utc=now.timestamp(),
                )
            )

    kernel_cycle = build_kernel_cycle_packet(
        cycle_id=cycle_id,
        generated_at=_iso_z(now),
        source_of_truth_map=DEFAULT_SOURCE_OF_TRUTH_MAP,
        evidence_bundle=evidence_records,
        thesis_bundle=thesis_records,
        promotion_bundle=promotion_tickets,
        learning_bundle=learning_bundle,
    )

    report = StrikeFactoryRun(
        generated_at=_iso_z(now),
        cycle_id=cycle_id,
        launch_order=list(launch_order),
        raw_packet_count=len(raw_packets),
        approved_packet_count=len(approved_packets),
        rejected_packet_count=len(rejected_packets),
        lane_counts=lane_counts,
        priority_counts=priority_counts,
        queue=queue,
        rejected_packets=rejected_packets,
        promotion_tickets=[ticket.to_dict() for ticket in promotion_tickets],
        proof_chain=proof_chain,
        kernel_cycle=kernel_cycle.to_dict(),
        event_tape={
            "db_path": str(tape_db_path),
            "latest_seq": tape_writer.get_latest_seq(),
            "event_count": tape_writer.count_events(),
        },
        promotion_snapshot=promotion_snapshot,
        execution_summary=execution_summary,
        harness_snapshot=harness_snapshot,
        source_mode=source_mode,
        source_inputs=source_inputs,
        status=report_status,
        blockers=blockers,
    )

    write_report(
        output_path,
        artifact="strike_factory.v1",
        payload=report.to_dict(),
        status=report_status,
        source_of_truth=(
            "reports/evidence_bundle.json; reports/thesis_bundle.json; "
            "reports/promotion_bundle.json; reports/learning_bundle.json"
        ),
        freshness_sla_seconds=900,
        blockers=blockers,
        summary=(
            f"approved={report.approved_packet_count} rejected={report.rejected_packet_count} "
            f"submitted={report.execution_summary.get('submitted', 0)}"
        ),
    )
    _write_markdown(report, markdown_path)
    if close_tape_writer:
        tape_writer.close()
    return report
