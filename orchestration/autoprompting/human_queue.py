"""Human queue contracts for autoprompting control-plane cycles."""

from __future__ import annotations

from typing import Any

TRADING_OBJECTIVE_KEYWORDS = (
    "trading",
    "trader",
    "polymarket",
    "wallet",
    "btc",
    "eth",
    "signal",
    "execution",
    "market",
    "clone",
    "replay",
)


def is_trading_heavy_objective(objective: str) -> bool:
    """Return True when the objective is primarily trading-oriented."""
    text = (objective or "").strip().lower()
    return any(keyword in text for keyword in TRADING_OBJECTIVE_KEYWORDS)


def build_non_trading_continuity_task(*, cycle_id: str, generated_at: str) -> dict[str, Any]:
    """Create the mandatory non-trading continuity lane task."""
    return {
        "id": f"continuity:{cycle_id}",
        "type": "non_trading_continuity",
        "priority": "medium",
        "status": "queued",
        "required_by_policy": True,
        "summary": "Advance one bounded non-trading continuity task while trading-heavy objective is active.",
        "requested_action": "Ship one non-trading continuity increment with explicit artifact output this cycle.",
        "owned_paths": [
            "nontrading/",
            "docs/ops/",
            "reports/finance/",
        ],
        "verification_command": "python -m nontrading.main --help",
        "artifact_contract": "reports/nontrading_public_report.json",
        "requires_telegram_page": False,
        "created_at": generated_at,
    }


def _priority_rank(priority: str) -> int:
    value = (priority or "").strip().lower()
    if value == "high":
        return 3
    if value == "medium":
        return 2
    return 1


def _normalize_reason(item: dict[str, Any]) -> str:
    token = str(item.get("reason_code") or "").strip()
    return token or "unspecified_human_task"


def _normalize_item(index: int, raw: dict[str, Any], generated_at: str) -> dict[str, Any]:
    priority = str(raw.get("priority") or "medium").strip().lower()
    if priority not in {"low", "medium", "high"}:
        priority = "medium"
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
    return {
        "id": str(raw.get("id") or f"hq:{_normalize_reason(raw)}:{index}"),
        "type": "human_action",
        "reason_code": _normalize_reason(raw),
        "priority": priority,
        "status": str(raw.get("status") or "open"),
        "summary": str(raw.get("summary") or "Human input required."),
        "requested_action": str(raw.get("requested_action") or "Review and choose next step."),
        "artifacts": [str(path) for path in artifacts if str(path).strip()],
        "retry_in_minutes": int(raw.get("retry_in_minutes") or 0) or None,
        "requires_telegram_page": bool(raw.get("requires_telegram_page")),
        "created_at": generated_at,
    }


def build_human_queue(
    *,
    cycle_id: str,
    generated_at: str,
    primary_objective: str,
    escalation_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the `human_queue.v1` payload for the current cycle."""
    queue_items = [
        _normalize_item(index + 1, candidate, generated_at)
        for index, candidate in enumerate(escalation_candidates)
    ]

    if is_trading_heavy_objective(primary_objective):
        queue_items.append(
            build_non_trading_continuity_task(
                cycle_id=cycle_id,
                generated_at=generated_at,
            )
        )

    queue_items.sort(
        key=lambda item: _priority_rank(str(item.get("priority") or "")),
        reverse=True,
    )

    action_required_count = sum(
        1 for item in queue_items if str(item.get("type")) == "human_action"
    )
    telegram_page_count = sum(
        1 for item in queue_items if bool(item.get("requires_telegram_page"))
    )

    return {
        "schema": "human_queue.v1",
        "generated_at": generated_at,
        "cycle_id": cycle_id,
        "primary_objective": primary_objective,
        "trading_heavy_objective": is_trading_heavy_objective(primary_objective),
        "open_item_count": len(queue_items),
        "action_required_count": action_required_count,
        "telegram_page_candidate_count": telegram_page_count,
        "queue": queue_items,
        "status": "action_required" if action_required_count > 0 else "no_page_required",
    }

