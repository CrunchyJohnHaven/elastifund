#!/usr/bin/env python3
"""Run one strike-desk cycle and publish the execution queue plus tape events."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.event_tape import EventTapeWriter  # noqa: E402
from bot.strike_desk import ExecutionPacket, LANE_NAMES, StrikeDesk  # noqa: E402


DEFAULT_REPORTS_DIR = REPO_ROOT / "reports" / "strike_desk"
DEFAULT_TAPE_DB = REPO_ROOT / "data" / "tape" / "strike_desk.db"
DEFAULT_MARKET_REGISTRY = REPO_ROOT / "reports" / "market_registry" / "latest.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports-dir",
        default=str(DEFAULT_REPORTS_DIR),
        help="Directory for latest.json / latest.md / history.jsonl.",
    )
    parser.add_argument(
        "--tape-db",
        default=str(DEFAULT_TAPE_DB),
        help="SQLite event tape path for append-only decision logging.",
    )
    parser.add_argument(
        "--packets-json",
        default="",
        help="Optional JSON file containing prebuilt execution packets for shadow/replay runs.",
    )
    parser.add_argument(
        "--market-registry-json",
        default=str(DEFAULT_MARKET_REGISTRY),
        help="Optional market-registry artifact used to feed the resolution sniper lane.",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=None,
        help="Optional strike-desk capital override.",
    )
    parser.add_argument(
        "--cycle-id",
        default="",
        help="Optional cycle identifier override.",
    )
    parser.add_argument(
        "--lane-set",
        default=os.environ.get("STRIKE_DESK_LANE_SET", "p2_p4"),
        choices=("all", "p2_p4"),
        help="Which lane bundle to scan. 'p2_p4' keeps the inaugural Lightsail cycle bounded.",
    )
    return parser.parse_args(argv)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_packet_payload(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("packets", "execution_packets", "items", "data", "queue"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError(f"Unsupported packet payload shape in {path}")


def _packet_from_dict(data: dict[str, Any]) -> ExecutionPacket:
    packet = ExecutionPacket(
        strategy_id=str(data.get("strategy_id", "") or ""),
        market_id=str(data.get("market_id", "") or ""),
        platform=str(data.get("platform", "polymarket") or "polymarket"),
        direction=str(data.get("direction", "YES") or "YES"),
        token_id=str(data.get("token_id", "") or ""),
        size_usd=float(data.get("size_usd", 0.0) or 0.0),
        edge_estimate=float(data.get("edge_estimate", 0.0) or 0.0),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        evidence_hash=str(data.get("evidence_hash", "") or ""),
        max_slippage=float(data.get("max_slippage", 0.02) or 0.02),
        ttl_seconds=int(data.get("ttl_seconds", 120) or 120),
        order_type=str(data.get("order_type", "maker") or "maker"),
        priority=int(data.get("priority", 0) or 0),
        linked_packets=list(data.get("linked_packets") or []),
        metadata=dict(data.get("metadata") or {}),
    )
    packet_id = str(data.get("packet_id", "") or "").strip()
    if packet_id:
        packet.packet_id = packet_id
    timestamp = data.get("timestamp")
    if timestamp is not None:
        try:
            packet.timestamp = float(timestamp)
        except (TypeError, ValueError):
            pass
    status = str(data.get("status", "") or "").strip()
    if status:
        packet.status = status
    return packet


def _packet_to_summary(packet: ExecutionPacket, *, approved: bool, reason: str = "") -> dict[str, Any]:
    payload = packet.to_dict()
    payload.update(
        {
            "approved": approved,
            "reason": reason,
            "lane": packet.strategy_id,
        }
    )
    return payload


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Strike Desk Cycle",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- cycle_id: {report['cycle_id']}",
        f"- source_mode: {report['source_mode']}",
        f"- raw_packets: {report['raw_packet_count']}",
        f"- approved_packets: {report['approved_packet_count']}",
        f"- rejected_packets: {report['rejected_packet_count']}",
        f"- desk_capital: ${float(report['diagnostics']['capital']):.2f}",
        f"- desk_budget: ${float(report['diagnostics']['desk_budget']):.2f}",
        f"- total_exposure: ${float(report['diagnostics']['total_exposure']):.2f}",
        "",
        "## Execution Queue",
    ]
    queue = report.get("execution_queue") or []
    if queue:
        lines.append("| priority | strategy | market | side | size_usd | edge | confidence | ttl | order_type |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
        for row in queue[:20]:
            lines.append(
                "| {priority} | {strategy_id} | {market_id} | {direction} | ${size_usd:.2f} | {edge_estimate:.4f} | {confidence:.3f} | {ttl_seconds}s | {order_type} |".format(
                    priority=row.get("priority", ""),
                    strategy_id=row.get("strategy_id", ""),
                    market_id=row.get("market_id", ""),
                    direction=row.get("direction", ""),
                    size_usd=float(row.get("size_usd", 0.0) or 0.0),
                    edge_estimate=float(row.get("edge_estimate", 0.0) or 0.0),
                    confidence=float(row.get("confidence", 0.0) or 0.0),
                    ttl_seconds=int(row.get("ttl_seconds", 0) or 0),
                    order_type=row.get("order_type", ""),
                )
            )
    else:
        lines.append("- no approved packets")

    rejected = report.get("rejected_packets") or []
    lines.extend(["", "## Rejections"])
    if rejected:
        for row in rejected[:20]:
            lines.append(
                f"- {row.get('strategy_id', '')} {row.get('market_id', '')} — {row.get('reason', '')}"
            )
    else:
        lines.append("- none")

    diagnostics = report.get("diagnostics") or {}
    lines.extend(["", "## Diagnostics"])
    lines.append(f"- lane_exposure: {diagnostics.get('lane_exposure', {})}")
    lines.append(f"- market_exposure: {diagnostics.get('market_exposure', {})}")
    lines.append(f"- total_fills: {diagnostics.get('total_fills', 0)}")
    lines.append(f"- total_rejections: {diagnostics.get('total_rejections', 0)}")
    return "\n".join(lines) + "\n"


def _load_market_registry_markets(path: Path | None) -> tuple[list[dict[str, Any]], str]:
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    if DEFAULT_MARKET_REGISTRY not in candidates:
        candidates.append(DEFAULT_MARKET_REGISTRY)

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = _load_json(candidate)
        except Exception:
            continue
        registry_rows = payload.get("registry") if isinstance(payload, dict) else None
        if not isinstance(registry_rows, list):
            continue

        markets: list[dict[str, Any]] = []
        for row in registry_rows:
            if not isinstance(row, dict):
                continue
            if not row.get("eligible", True):
                continue
            market_id = str(row.get("market_id") or row.get("condition_id") or "").strip()
            if not market_id:
                continue
            yes_price = row.get("best_ask")
            if yes_price is None:
                yes_price = row.get("best_bid")
            if yes_price is None:
                yes_price = row.get("mid")
            yes_price_f = float(yes_price) if yes_price is not None else 0.5
            if not 0.0 <= yes_price_f <= 1.0:
                yes_price_f = 0.5
            best_bid = _float_or_none(row.get("best_bid"))
            best_ask = _float_or_none(row.get("best_ask"))
            mid = _float_or_none(row.get("mid"))
            markets.append(
                {
                    "market_id": market_id,
                    "question": str(row.get("question") or row.get("event_title") or ""),
                    "yes_price": yes_price_f,
                    "no_price": 1.0 - yes_price_f,
                    "resolution_source": "pm_fast_market_registry",
                    "volume_24h": float(row.get("volume_24h") or 0.0),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "bid_depth_usd": _float_or_none(row.get("bid_depth_usd")) or 1.0,
                    "ask_depth_usd": _float_or_none(row.get("ask_depth_usd")) or 1.0,
                    "mid": mid,
                    "quote_freshness_seconds": row.get("quote_staleness_seconds"),
                    "priority_lane": row.get("priority_lane"),
                }
            )
        return markets, str(candidate)

    try:
        from bot.pm_fast_market_registry import build_registry
    except Exception:
        return [], "market_registry_unavailable"

    try:
        registry = build_registry(fetch_quotes=True)
    except Exception as exc:
        return [], f"market_registry_fetch_failed:{type(exc).__name__}"

    markets = []
    for row in registry.registry:
        if not row.eligible:
            continue
        yes_price = row.best_ask if row.best_ask is not None else row.best_bid
        yes_price_f = float(yes_price) if yes_price is not None else 0.5
        if not 0.0 <= yes_price_f <= 1.0:
            yes_price_f = 0.5
        markets.append(
            {
                "market_id": row.market_id or row.condition_id,
                "question": row.question,
                "yes_price": yes_price_f,
                "no_price": 1.0 - yes_price_f,
                "resolution_source": "pm_fast_market_registry_live",
                "volume_24h": 0.0,
                "best_bid": _float_or_none(row.best_bid),
                "best_ask": _float_or_none(row.best_ask),
                "bid_depth_usd": 1.0,
                "ask_depth_usd": 1.0,
                "mid": _float_or_none(row.mid),
                "priority_lane": row.priority_lane,
            }
        )
    return markets, "live_registry"


async def _collect_packets(
    desk: StrikeDesk,
    *,
    packets_json: Path | None,
    market_registry_json: Path | None,
    lane_set: str,
) -> tuple[list[ExecutionPacket], str, dict[str, Any]]:
    if packets_json is not None:
        raw_packets = [_packet_from_dict(item) for item in _load_packet_payload(packets_json)]
        return raw_packets, f"fixture:{packets_json}", {
            "market_registry_source": None,
            "lane_set": lane_set,
        }

    live_kwargs: dict[str, Any] = {}
    markets, market_source = _load_market_registry_markets(market_registry_json)
    if markets:
        live_kwargs["sniper_markets"] = markets
    enabled_lanes = None if lane_set == "all" else {"resolution", "whale"}

    raw_packets = await desk.scan_all_lanes(enabled_lanes=enabled_lanes, **live_kwargs)
    return raw_packets, "live_scanners", {
        "market_registry_source": market_source,
        "sniper_market_count": len(markets),
        "lane_set": lane_set,
    }


def build_cycle(
    *,
    reports_dir: Path,
    tape_db: Path,
    packets_json: Path | None = None,
    market_registry_json: Path | None = None,
    lane_set: str = "p2_p4",
    capital: float | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    tape_db.parent.mkdir(parents=True, exist_ok=True)

    desk = StrikeDesk(config={"capital": capital} if capital is not None else None)
    raw_packets, source_mode, source_details = asyncio.run(
        _collect_packets(
            desk,
            packets_json=packets_json,
            market_registry_json=market_registry_json,
            lane_set=lane_set,
        )
    )

    approved_packets = desk.generate_packets(list(raw_packets))
    approved_ids = {pkt.packet_id for pkt in approved_packets}
    cycle_id = cycle_id or uuid.uuid4().hex[:12]

    with EventTapeWriter(str(tape_db), session_id=cycle_id) as tape:
        for packet in raw_packets:
            corr = str(packet.metadata.get("group_id") or packet.market_id or cycle_id)
            proposed = tape.emit_decision(
                "trade_proposed",
                payload={
                    "packet_id": packet.packet_id,
                    "strategy_id": packet.strategy_id,
                    "market_id": packet.market_id,
                    "platform": packet.platform,
                    "direction": packet.direction,
                    "size_usd": packet.size_usd,
                    "edge_estimate": packet.edge_estimate,
                    "confidence": packet.confidence,
                    "priority": packet.priority,
                    "ttl_seconds": packet.ttl_seconds,
                    "order_type": packet.order_type,
                    "evidence_hash": packet.evidence_hash,
                    "linked_packets": list(packet.linked_packets),
                },
                source="strike_desk",
                correlation_id=corr,
            )
            if packet.packet_id in approved_ids:
                tape.emit_decision(
                    "trade_approved",
                    payload={
                        "packet_id": packet.packet_id,
                        "strategy_id": packet.strategy_id,
                        "market_id": packet.market_id,
                        "approved_size_usd": packet.size_usd,
                        "approved_price": packet.metadata.get("reference_price"),
                        "approval_reason": "priority_and_exposure_ok",
                        "gates_passed": ["priority", "exposure"],
                    },
                    source="strike_desk",
                    causation_seq=proposed.seq,
                    correlation_id=corr,
                )
            else:
                rejection_reason = "exposure_cap" if packet.status == "rejected" else "priority_or_conflict"
                tape.emit_decision(
                    "trade_rejected",
                    payload={
                        "packet_id": packet.packet_id,
                        "strategy_id": packet.strategy_id,
                        "market_id": packet.market_id,
                        "direction": packet.direction,
                        "rejection_reason": rejection_reason,
                        "rejection_detail": packet.metadata.get("rejection_detail")
                        or f"desk suppressed {packet.strategy_id} during queue shaping",
                        "gate_that_failed": "desk_queue_gate",
                        "parameters_at_rejection": {
                            "priority": packet.priority,
                            "market_id": packet.market_id,
                            "strategy_id": packet.strategy_id,
                        },
                    },
                    source="strike_desk",
                    causation_seq=proposed.seq,
                    correlation_id=corr,
                )

        diagnostics = desk.get_diagnostics()
        tape_counts = {
            "events": tape.count_events(),
            "decision_trade_proposed": tape.count_events("decision.trade_proposed"),
            "decision_trade_approved": tape.count_events("decision.trade_approved"),
            "decision_trade_rejected": tape.count_events("decision.trade_rejected"),
        }

    queue = [_packet_to_summary(pkt, approved=True) for pkt in approved_packets]
    rejected_packets = [
        _packet_to_summary(
            pkt,
            approved=False,
            reason="exposure_cap" if pkt.status == "rejected" else "priority_or_conflict",
        )
        for pkt in raw_packets
        if pkt.packet_id not in approved_ids
    ]
    lane_counts = Counter(pkt.strategy_id for pkt in raw_packets)
    execution_mode = "shadow_ready" if queue else "idle"

    report = {
        "artifact": "strike_desk_cycle",
        "cycle_id": cycle_id,
        "generated_at": _now_iso(),
        "execution_mode": execution_mode,
        "lane_set": lane_set,
        "source_mode": source_mode,
        "source_details": source_details,
        "raw_packet_count": len(raw_packets),
        "approved_packet_count": len(approved_packets),
        "rejected_packet_count": len(raw_packets) - len(approved_packets),
        "lane_counts": dict(lane_counts),
        "lane_priority_order": [LANE_NAMES.get(pkt.priority, f"p{pkt.priority}") for pkt in approved_packets],
        "execution_queue": queue,
        "rejected_packets": rejected_packets,
        "diagnostics": diagnostics,
        "tape": {
            "db_path": str(tape_db),
            "event_counts": tape_counts,
        },
        "handoff": {
            "approved_packets": queue,
            "desk_budget_usd": diagnostics.get("desk_budget"),
            "max_single_market_usd": diagnostics.get("max_per_market"),
            "max_single_lane_usd": diagnostics.get("max_per_lane"),
        },
    }

    latest_json = reports_dir / "latest.json"
    latest_md = reports_dir / "latest.md"
    history_jsonl = reports_dir / "history.jsonl"
    latest_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest_md.write_text(_render_markdown(report), encoding="utf-8")
    with history_jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")

    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    reports_dir = Path(args.reports_dir).expanduser().resolve()
    tape_db = Path(args.tape_db).expanduser().resolve()
    packets_json = Path(args.packets_json).expanduser().resolve() if args.packets_json else None
    market_registry_json = (
        Path(args.market_registry_json).expanduser().resolve()
        if args.market_registry_json
        else None
    )

    report = build_cycle(
        reports_dir=reports_dir,
        tape_db=tape_db,
        packets_json=packets_json,
        market_registry_json=market_registry_json,
        lane_set=args.lane_set,
        capital=args.capital,
        cycle_id=args.cycle_id or None,
    )

    print(json.dumps(
        {
            "cycle_id": report["cycle_id"],
            "execution_mode": report["execution_mode"],
            "lane_set": report["lane_set"],
            "raw_packet_count": report["raw_packet_count"],
            "approved_packet_count": report["approved_packet_count"],
            "reports_dir": str(reports_dir),
            "latest_json": str(reports_dir / "latest.json"),
        },
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
