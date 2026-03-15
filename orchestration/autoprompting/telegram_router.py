"""Telegram escalation routing for autoprompting control-plane cycles."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from bot.polymarket_runtime import TelegramBot

ALLOWED_REASON_CODES = {
    "credential_required",
    "spend_change_detected",
    "risk_or_policy_change",
    "repeated_blocked_retry",
    "no_dominant_winner",
    "deploy_approval_required",
}

REASON_CODE_ALIASES = {
    "finance_policy_required": "spend_change_detected",
    "risk_policy_required": "risk_or_policy_change",
    "architecture_tie": "no_dominant_winner",
    "repeated_blocker": "repeated_blocked_retry",
    "deploy_decision_required": "deploy_approval_required",
    "external_human_task": "credential_required",
}

REASON_CODE_DESCRIPTIONS = {
    "credential_required": "A login, API key, 2FA step, or secret is required before the cycle can proceed.",
    "spend_change_detected": "Model/tool spend queue changed and needs operator awareness.",
    "risk_or_policy_change": "Runtime or policy posture changed and needs explicit human confirmation.",
    "repeated_blocked_retry": "The same blocker repeated across cycles and now needs intervention.",
    "no_dominant_winner": "Two materially different options are both valid without a clear winner.",
    "deploy_approval_required": "A deploy recommendation is ready and requires human approval.",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_reason_code(reason_code: str) -> str:
    token = str(reason_code or "").strip().lower()
    if not token:
        return ""
    return REASON_CODE_ALIASES.get(token, token)


def _make_dedupe_key(cycle_id: str, reason_codes: list[str], task_ids: list[str]) -> str:
    signature = {
        "cycle_id": cycle_id,
        "reason_codes": sorted(reason_codes),
        "task_ids": sorted(task_ids),
    }
    digest = hashlib.sha256(
        json.dumps(signature, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest


def build_telegram_event(
    *,
    cycle_id: str,
    generated_at: str,
    human_queue: dict[str, Any],
    previous_event: dict[str, Any] | None,
    dedupe_window_minutes: int = 240,
) -> dict[str, Any]:
    """Build a `telegram_event.v1` decision payload."""
    queue_items = human_queue.get("queue")
    if not isinstance(queue_items, list):
        queue_items = []

    actionable = [
        item
        for item in queue_items
        if isinstance(item, dict)
        and bool(item.get("requires_telegram_page"))
        and str(item.get("type") or "") == "human_action"
    ]
    reason_codes = [
        _normalize_reason_code(str(item.get("reason_code") or ""))
        for item in actionable
    ]
    reason_codes = [
        reason for reason in reason_codes if reason and reason in ALLOWED_REASON_CODES
    ]
    task_ids = [str(item.get("id") or "") for item in actionable if str(item.get("id") or "").strip()]
    dedupe_key = _make_dedupe_key(cycle_id=cycle_id, reason_codes=reason_codes, task_ids=task_ids)

    previous = previous_event or {}
    previous_dedupe_key = str(previous.get("dedupe_key") or "").strip()
    previous_sent_at = _parse_datetime(previous.get("sent_at"))
    current_ts = _parse_datetime(generated_at) or _utc_now()
    duplicate_within_window = False
    if previous_dedupe_key and previous_sent_at and previous_dedupe_key == dedupe_key:
        delta_minutes = (current_ts - previous_sent_at).total_seconds() / 60.0
        duplicate_within_window = delta_minutes < float(dedupe_window_minutes)

    should_send = bool(reason_codes) and not duplicate_within_window

    first_task_summary = str(actionable[0].get("summary")) if actionable else "No action required."
    first_task_action = str(actionable[0].get("requested_action")) if actionable else "No action required."
    artifacts = actionable[0].get("artifacts") if actionable else []
    if not isinstance(artifacts, list):
        artifacts = []
    artifact_line = ", ".join(str(path) for path in artifacts[:3]) if artifacts else "reports/autoprompting/operator_summary/latest.json"

    message = (
        "ELASTIFUND AUTOPROMPTING: HUMAN ACTION REQUIRED\n\n"
        f"Reason: {', '.join(reason_codes) if reason_codes else 'none'}\n"
        f"Cycle: {cycle_id}\n"
        f"Severity: {'high' if reason_codes else 'low'}\n"
        f"What changed: {first_task_summary}\n"
        "Why the system cannot continue alone: A human authority decision or credential action is required.\n"
        f"Recommended action: {first_task_action}\n"
        "If ignored for 24h: Improvement cycles may continue in hold/repair without progression.\n"
        f"Artifacts: {artifact_line}"
    )

    return {
        "schema": "telegram_event.v1",
        "generated_at": generated_at,
        "cycle_id": cycle_id,
        "reason_codes": reason_codes,
        "dedupe_key": dedupe_key,
        "dedupe_window_minutes": dedupe_window_minutes,
        "duplicate_within_window": duplicate_within_window,
        "should_send": should_send,
        "message": message,
        "status": "send" if should_send else "skip",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def send_telegram_event(
    *,
    event: dict[str, Any],
    state_path: Path,
    send_enabled: bool,
) -> dict[str, Any]:
    """Send a Telegram event when enabled and required."""
    should_send = bool(event.get("should_send"))
    if not should_send:
        return {"status": "skip_no_action_required", "sent": False}
    if not send_enabled:
        return {"status": "dry_run_send_disabled", "sent": False}

    try:
        bot = TelegramBot()
        sent = bool(bot.send(str(event.get("message") or ""), parse_mode="HTML"))
    except Exception as exc:  # pragma: no cover - depends on runtime credentials/network
        return {"status": "send_failed", "sent": False, "error": str(exc)}

    if sent:
        state_payload = {
            "schema": "telegram_event_state.v1",
            "sent_at": _utc_now().isoformat(),
            "dedupe_key": str(event.get("dedupe_key") or ""),
            "reason_codes": event.get("reason_codes") if isinstance(event.get("reason_codes"), list) else [],
        }
        _write_json(state_path, state_payload)
        return {"status": "sent", "sent": True}
    return {"status": "send_failed", "sent": False}


def load_telegram_state(path: Path) -> dict[str, Any]:
    """Load the prior Telegram event state for dedupe."""
    return _read_json(path)


def build_escalation_matrix(*, generated_at: str) -> dict[str, Any]:
    """Publish a machine-readable low-noise escalation contract."""
    reasons = []
    for code in sorted(ALLOWED_REASON_CODES):
        reasons.append(
            {
                "reason_code": code,
                "action_required": True,
                "default_page": True,
                "description": REASON_CODE_DESCRIPTIONS.get(code, ""),
            }
        )
    return {
        "schema": "telegram_escalation_matrix.v1",
        "generated_at": generated_at,
        "default_policy": "silent_by_default",
        "informational_updates_policy": "artifact_only_no_telegram",
        "dedupe_window_minutes": 240,
        "reasons": reasons,
    }
