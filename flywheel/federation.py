"""Cross-fork bulletin exchange for sharing high-value flywheel findings."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from data_layer import crud

from .improvement_exchange import build_knowledge_pack_leaderboard_entry
from .intelligence import FindingSpec, TaskSpec, record_finding_with_task


def export_bulletin(
    session: Session,
    *,
    peer_name: str,
    decision_types: tuple[str, ...] = ("promote", "kill"),
    limit: int = 20,
    include_knowledge_packs: bool = False,
    knowledge_pack_limit: int | None = None,
) -> dict[str, Any]:
    """Export recent high-value findings as a portable bulletin."""

    versions = {row.id: row for row in crud.list_strategy_versions(session, limit=500)}
    items: list[dict[str, Any]] = []
    for decision_type in decision_types:
        for row in crud.list_promotion_decisions(session, decision=decision_type, limit=limit):
            version = versions.get(row.strategy_version_id)
            if version is None:
                continue
            items.append(
                {
                    "strategy_key": version.strategy_key,
                    "version_label": version.version_label,
                    "lane": version.lane,
                    "decision": row.decision,
                    "from_stage": row.from_stage,
                    "to_stage": row.to_stage,
                    "reason_code": row.reason_code,
                    "notes": row.notes,
                    "metrics": row.metrics,
                }
            )

    bulletin = {
        "peer_name": peer_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(items),
        "items": items[:limit],
    }
    if include_knowledge_packs:
        knowledge_items = _knowledge_pack_bulletin_items(
            session,
            limit=knowledge_pack_limit or limit,
        )
        bulletin["knowledge_pack_count"] = len(knowledge_items)
        bulletin["knowledge_packs"] = knowledge_items
    return bulletin


def write_bulletin(bulletin: dict[str, Any], output_path: str | Path) -> str:
    """Write a bulletin to disk."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bulletin, indent=2, sort_keys=True))
    return str(path)


def load_bulletin(path: str | Path) -> dict[str, Any]:
    """Load a bulletin from JSON."""

    return json.loads(Path(path).read_text())


def import_bulletin(session: Session, bulletin: dict[str, Any]) -> dict[str, Any]:
    """Convert a peer bulletin into local review tasks."""

    peer_name = bulletin["peer_name"]
    generated_at = bulletin["generated_at"]
    cycle_key = _cycle_key(peer_name, generated_at)
    existing = crud.get_flywheel_cycle(session, cycle_key)
    if existing is not None:
        return {"cycle_key": cycle_key, "tasks_created": 0, "already_imported": True}

    cycle = crud.create_flywheel_cycle(
        session,
        cycle_key=cycle_key,
        status="completed",
        summary=f"Imported peer bulletin from {peer_name}",
    )

    created = 0
    for item in bulletin.get("items", []):
        title = f"Review peer paydirt from {peer_name}: {item['strategy_key']}:{item['version_label']}"
        details = (
            f"Decision={item['decision']} {item['from_stage']}->{item['to_stage']} "
            f"reason={item['reason_code']}. {item.get('notes') or ''}"
        ).strip()
        record_finding_with_task(
            session,
            finding=FindingSpec(
                finding_key=(
                    f"peer_bulletin:{peer_name}:{generated_at}:{item['strategy_key']}:"
                    f"{item['version_label']}:{item['decision']}"
                ),
                cycle_id=cycle.id,
                strategy_version_id=None,
                lane=item.get("lane"),
                environment=item.get("to_stage"),
                source_kind="peer_bulletin",
                finding_type="peer_signal",
                title=f"Peer bulletin from {peer_name}: {item['strategy_key']}:{item['version_label']}",
                summary=details,
                lesson="Peer findings are hypotheses until replayed locally under the same gates.",
                evidence=item,
                priority=35 if item["decision"] == "promote" else 45,
                confidence=None,
                status="open",
            ),
            task=TaskSpec(
                cycle_id=cycle.id,
                strategy_version_id=None,
                action="recommend",
                title=title,
                details=details,
                priority=35 if item["decision"] == "promote" else 45,
                status="open",
                lane=item.get("lane"),
                environment=item.get("to_stage"),
                source_kind="peer_bulletin",
                source_ref=f"bulletin:{peer_name}:{generated_at}",
                metadata={"item": item},
            ),
        )
        created += 1

    session.commit()
    return {"cycle_key": cycle_key, "tasks_created": created, "already_imported": False}


def _cycle_key(peer_name: str, generated_at: str) -> str:
    safe_peer = peer_name.replace(" ", "-").lower()
    safe_ts = generated_at.replace(":", "").replace("+", "").replace(".", "-")
    return f"bulletin-{safe_peer}-{safe_ts}"


def _knowledge_pack_bulletin_items(session: Session, *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in crud.list_peer_improvement_bundles(
        session,
        direction="exported",
        limit=max(limit * 5, limit),
    ):
        raw_bundle = row.raw_bundle or {}
        if raw_bundle.get("bundle_type") != "knowledge_pack":
            continue
        leaderboard_entry = raw_bundle.get("leaderboard_entry") or build_knowledge_pack_leaderboard_entry(
            raw_bundle,
            verification_status=row.verification_status,
        )
        items.append(
            {
                "bundle_id": row.bundle_id,
                "peer_name": row.peer_name,
                "engine_key": leaderboard_entry["engine_key"],
                "engine_version": leaderboard_entry["engine_version"],
                "lane": leaderboard_entry["lane"],
                "score_after_penalty": leaderboard_entry["score_after_penalty"],
                "expected_net_cash_30d": leaderboard_entry["expected_net_cash_30d"],
                "penalty_total": leaderboard_entry["penalty_total"],
                "verification_status": row.verification_status,
            }
        )
        if len(items) >= limit:
            break
    return items
