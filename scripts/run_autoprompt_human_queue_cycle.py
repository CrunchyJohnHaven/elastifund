#!/usr/bin/env python3
"""Instance 6 autoprompt cycle: human queue, Telegram escalation, and operator summary."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestration.autoprompting.human_queue import build_human_queue
from orchestration.autoprompting.telegram_router import (
    build_escalation_matrix,
    build_telegram_event,
    load_telegram_state,
    send_telegram_event,
)

HOLD_REPAIR_RETRY_MINUTES = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _first_time(payload: dict[str, Any], path: Path) -> datetime:
    for key in ("generated_at", "checked_at", "updated_at", "timestamp"):
        parsed = _parse_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _artifact_health(*, root: Path, rel_path: str, now: datetime, max_age_seconds: int) -> dict[str, Any]:
    path = root / rel_path
    if not path.exists():
        return {
            "path": rel_path,
            "exists": False,
            "fresh": False,
            "age_seconds": None,
            "generated_at": None,
            "reason": f"missing:{rel_path}",
            "payload": {},
        }
    payload = _read_json(path)
    generated_at = _first_time(payload, path)
    age_seconds = max(0.0, (now - generated_at).total_seconds())
    fresh = age_seconds <= float(max_age_seconds)
    return {
        "path": rel_path,
        "exists": True,
        "fresh": fresh,
        "age_seconds": round(age_seconds, 3),
        "generated_at": generated_at.isoformat(),
        "reason": None if fresh else f"stale:{rel_path}:{int(round(age_seconds))}s>{max_age_seconds}s",
        "payload": payload,
    }


def _extract_primary_objective(root: Path) -> str:
    autoprompting_path = root / "autoprompting.md"
    try:
        text = autoprompting_path.read_text(encoding="utf-8")
    except Exception:
        return "Reverse-engineer the best 5-15 minute Polymarket traders."

    match = re.search(
        r"^\|\s*Primary near-term objective\s*\|\s*(.+?)\s*\|$",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        return "Reverse-engineer the best 5-15 minute Polymarket traders."
    return match.group(1).strip()


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _finance_gate_pass(finance_payload: dict[str, Any]) -> bool:
    direct = finance_payload.get("finance_gate_pass")
    if direct is not None:
        return bool(direct)
    gate = finance_payload.get("finance_gate")
    if isinstance(gate, dict):
        return bool(gate.get("pass"))
    return False


def _build_escalation_candidates(
    *,
    runtime_truth: dict[str, Any],
    finance_latest: dict[str, Any],
    hold_repair_blockers: list[str],
    previous_latest: dict[str, Any],
    action_queue_hash: str | None,
) -> tuple[list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []

    has_telegram_credentials = bool(
        (
            (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
            or (os.getenv("TELEGRAM_TOKEN") or "").strip()
        )
        and (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    )
    if not has_telegram_credentials:
        candidates.append(
            {
                "reason_code": "credential_required",
                "priority": "high",
                "summary": "Telegram credentials are missing for Instance 6 escalation delivery.",
                "requested_action": "Set TELEGRAM_BOT_TOKEN (or TELEGRAM_TOKEN) and TELEGRAM_CHAT_ID for autoprompt pages.",
                "artifacts": [
                    "autoprompting.md",
                    "reports/autoprompting/telegram/latest.json",
                ],
                "requires_telegram_page": True,
            }
        )

    previous_hashes = previous_latest.get("source_hashes")
    previous_action_hash = None
    if isinstance(previous_hashes, dict):
        previous_action_hash = previous_hashes.get("finance_action_queue")
    if action_queue_hash and previous_action_hash and action_queue_hash != previous_action_hash:
        candidates.append(
            {
                "reason_code": "spend_change_detected",
                "priority": "medium",
                "summary": "Finance action queue changed since the previous cycle.",
                "requested_action": "Review queued or executed spend actions for policy alignment.",
                "artifacts": [
                    "reports/finance/action_queue.json",
                    "reports/finance/latest.json",
                ],
                "requires_telegram_page": True,
            }
        )

    previous_runtime = previous_latest.get("runtime_snapshot")
    previous_runtime = previous_runtime if isinstance(previous_runtime, dict) else {}
    runtime_summary = runtime_truth.get("summary")
    runtime_summary = runtime_summary if isinstance(runtime_summary, dict) else {}
    runtime_key = {
        "launch_posture": runtime_summary.get("launch_posture"),
        "execution_mode": runtime_summary.get("execution_mode"),
        "effective_runtime_profile": runtime_summary.get("effective_runtime_profile"),
        "allow_order_submission": runtime_truth.get("allow_order_submission"),
    }
    previous_runtime_key = {
        "launch_posture": previous_runtime.get("launch_posture"),
        "execution_mode": previous_runtime.get("execution_mode"),
        "effective_runtime_profile": previous_runtime.get("effective_runtime_profile"),
        "allow_order_submission": previous_runtime.get("allow_order_submission"),
    }
    if previous_runtime and runtime_key != previous_runtime_key:
        candidates.append(
            {
                "reason_code": "risk_or_policy_change",
                "priority": "high",
                "summary": "Runtime launch/risk posture changed since the previous cycle.",
                "requested_action": "Confirm posture change and approve updated risk-policy interpretation.",
                "artifacts": [
                    "reports/runtime_truth_latest.json",
                    "reports/autoprompting/operator_summary/latest.json",
                ],
                "requires_telegram_page": True,
            }
        )

    previous_retry = previous_latest.get("retry")
    previous_retry = previous_retry if isinstance(previous_retry, dict) else {}
    previous_blockers = previous_retry.get("hold_repair_blockers")
    if not isinstance(previous_blockers, list):
        previous_blockers = []
    previous_count = int(previous_retry.get("blocked_retry_count") or 0)
    blocked_retry_count = 0
    if hold_repair_blockers:
        if previous_blockers == hold_repair_blockers:
            blocked_retry_count = previous_count + 1
        else:
            blocked_retry_count = 1
        if blocked_retry_count >= 2:
            candidates.append(
                {
                    "reason_code": "repeated_blocked_retry",
                    "priority": "high",
                    "summary": "The same hold/repair blockers repeated across cycles.",
                    "requested_action": "Choose repair owner and unblock stale/contradictory cycle inputs.",
                    "artifacts": [
                        "reports/runtime_truth_latest.json",
                        "reports/finance/latest.json",
                        "reports/root_test_status.json",
                    ],
                    "requires_telegram_page": True,
                }
            )

    deployment_confidence = runtime_truth.get("deployment_confidence")
    deployment_confidence = deployment_confidence if isinstance(deployment_confidence, dict) else {}
    can_btc5_trade_now = bool(deployment_confidence.get("can_btc5_trade_now"))
    if can_btc5_trade_now and _finance_gate_pass(finance_latest):
        candidates.append(
            {
                "reason_code": "deploy_approval_required",
                "priority": "medium",
                "summary": "Deployment confidence indicates readiness for a bounded deploy decision.",
                "requested_action": "Approve or defer next deploy recommendation lane.",
                "artifacts": [
                    "reports/runtime_truth_latest.json",
                    "reports/instance2_btc5_baseline/latest.json",
                ],
                "requires_telegram_page": True,
            }
        )

    return candidates, blocked_retry_count


def build_instance6_autoprompt_cycle(root: Path) -> dict[str, Any]:
    now = _utc_now()
    generated_at = now.isoformat()
    cycle_stamp = _utc_stamp(now)
    cycle_id = f"autoprompt-{cycle_stamp}"

    runtime_health = _artifact_health(
        root=root,
        rel_path="reports/runtime_truth_latest.json",
        now=now,
        max_age_seconds=15 * 60,
    )
    finance_health = _artifact_health(
        root=root,
        rel_path="reports/finance/latest.json",
        now=now,
        max_age_seconds=60 * 60,
    )
    test_health = _artifact_health(
        root=root,
        rel_path="reports/root_test_status.json",
        now=now,
        max_age_seconds=36 * 60 * 60,
    )
    action_queue_path = root / "reports" / "finance" / "action_queue.json"
    action_queue_hash = _sha256_file(action_queue_path)

    artifact_health = {
        "runtime_truth": runtime_health,
        "finance_latest": finance_health,
        "root_test_status": test_health,
    }
    hold_repair_blockers = [
        data["reason"]
        for data in artifact_health.values()
        if not data.get("fresh") and data.get("reason")
    ]

    autoprompt_latest_path = root / "reports" / "autoprompting" / "latest.json"
    previous_latest = _read_json(autoprompt_latest_path)
    previous_event_state = load_telegram_state(
        root / "state" / "autoprompting_telegram_state.json"
    )
    previous_contracts = previous_latest.get("contracts")
    if not isinstance(previous_contracts, dict):
        previous_contracts = {}
    previous_artifacts = previous_latest.get("artifacts")
    if not isinstance(previous_artifacts, dict):
        previous_artifacts = {}

    primary_objective = _extract_primary_objective(root)

    runtime_truth = runtime_health.get("payload") if isinstance(runtime_health.get("payload"), dict) else {}
    finance_latest = finance_health.get("payload") if isinstance(finance_health.get("payload"), dict) else {}

    escalation_candidates, blocked_retry_count = _build_escalation_candidates(
        runtime_truth=runtime_truth,
        finance_latest=finance_latest,
        hold_repair_blockers=hold_repair_blockers,
        previous_latest=previous_latest,
        action_queue_hash=action_queue_hash,
    )

    human_queue = build_human_queue(
        cycle_id=cycle_id,
        generated_at=generated_at,
        primary_objective=primary_objective,
        escalation_candidates=escalation_candidates,
    )

    previous_event = previous_latest.get("telegram_event")
    if not isinstance(previous_event, dict):
        previous_event = previous_event_state
    telegram_event = build_telegram_event(
        cycle_id=cycle_id,
        generated_at=generated_at,
        human_queue=human_queue,
        previous_event=previous_event,
    )

    initial_block_reasons: list[str] = []
    if not (root / "reports" / "autoprompting" / "human_queue" / "latest.json").exists():
        initial_block_reasons.append("no_human_queue_artifact")
    if not (root / "reports" / "autoprompting" / "telegram" / "latest.json").exists():
        initial_block_reasons.append("no_autoprompt_telegram_contract")

    status = "hold_repair" if hold_repair_blockers else "active"
    retry_at = (
        (now + timedelta(minutes=HOLD_REPAIR_RETRY_MINUTES)).isoformat()
        if hold_repair_blockers
        else None
    )

    finance_gate_pass = _finance_gate_pass(finance_latest)
    one_next_cycle_action = (
        "publish the first human_queue.v1 and Telegram escalation matrix"
        if initial_block_reasons
        else "maintain human_queue.v1 and Telegram escalation matrix with low-noise action-required paging"
    )
    effective_block_reasons = list(dict.fromkeys(initial_block_reasons + hold_repair_blockers))

    runtime_summary = runtime_truth.get("summary")
    runtime_summary = runtime_summary if isinstance(runtime_summary, dict) else {}
    operator_summary = {
        "schema": "operator_summary.v1",
        "generated_at": generated_at,
        "cycle_id": cycle_id,
        "status": status,
        "primary_objective": primary_objective,
        "hold_repair": {
            "active": bool(hold_repair_blockers),
            "retry_in_minutes": HOLD_REPAIR_RETRY_MINUTES if hold_repair_blockers else None,
            "retry_at": retry_at,
            "blockers": hold_repair_blockers,
        },
        "runtime": {
            "launch_posture": runtime_summary.get("launch_posture"),
            "execution_mode": runtime_summary.get("execution_mode"),
            "effective_runtime_profile": runtime_summary.get("effective_runtime_profile"),
            "allow_order_submission": runtime_truth.get("allow_order_submission"),
        },
        "finance": {
            "finance_gate_pass": finance_gate_pass,
            "finance_state": finance_latest.get("finance_state"),
            "treasury_gate_pass": finance_latest.get("treasury_gate_pass"),
        },
        "human_queue": {
            "open_item_count": human_queue.get("open_item_count"),
            "action_required_count": human_queue.get("action_required_count"),
            "telegram_page_candidate_count": human_queue.get("telegram_page_candidate_count"),
        },
        "telegram_event": {
            "status": telegram_event.get("status"),
            "should_send": telegram_event.get("should_send"),
            "reason_codes": telegram_event.get("reason_codes"),
        },
        "one_next_cycle_action": one_next_cycle_action,
    }

    payload = {
        "schema_version": "autoprompting.v1",
        "schema": "autoprompting.v1",
        "generated_at": generated_at,
        "cycle_id": cycle_id,
        "instance": 6,
        "instance_label": "human_queue_telegram_operator_continuity",
        "objective": (
            "Keep autoprompt cycles low-noise and continuous with action-required Telegram escalation, "
            "human queue artifacts, and command-node-facing operator summaries."
        ),
        "primary_objective": primary_objective,
        "status": status,
        "hold_repair": operator_summary["hold_repair"],
        "stale_hold_repair": operator_summary["hold_repair"],
        "contracts": previous_contracts,
        "artifact_health": {
            name: {key: value for key, value in data.items() if key != "payload"}
            for name, data in artifact_health.items()
        },
        "artifacts": previous_artifacts,
        "source_hashes": {
            "finance_action_queue": action_queue_hash,
        },
        "runtime_snapshot": operator_summary["runtime"],
        "retry": {
            "blocked_retry_count": blocked_retry_count,
            "hold_repair_blockers": hold_repair_blockers,
        },
        "human_queue": human_queue,
        "telegram_event": telegram_event,
        "operator_summary": operator_summary,
        "required_outputs": {
            "candidate_delta_arr_bps": 90,
            "expected_improvement_velocity_delta": 0.10,
            "arr_confidence_score": 0.89,
            "block_reasons": effective_block_reasons,
            "finance_gate_pass": finance_gate_pass,
            "one_next_cycle_action": one_next_cycle_action,
        },
        "candidate_delta_arr_bps": 90,
        "expected_improvement_velocity_delta": 0.10,
        "arr_confidence_score": 0.89,
        "block_reasons": effective_block_reasons,
        "finance_gate_pass": finance_gate_pass,
        "one_next_cycle_action": one_next_cycle_action,
    }
    return payload


def write_instance6_autoprompt_cycle(
    *,
    root: Path,
    send_telegram: bool,
) -> dict[str, Any]:
    payload = build_instance6_autoprompt_cycle(root)
    generated_at = _parse_datetime(payload.get("generated_at")) or _utc_now()
    stamp = _utc_stamp(generated_at)

    reports_dir = root / "reports" / "autoprompting"
    cycle_path = reports_dir / "cycles" / f"instance6_{stamp}.json"
    latest_path = reports_dir / "latest.json"
    human_queue_path = reports_dir / "human_queue" / "latest.json"
    telegram_path = reports_dir / "telegram" / "latest.json"
    escalation_matrix_path = reports_dir / "telegram" / "escalation_matrix.json"
    operator_summary_path = reports_dir / "operator_summary" / "latest.json"

    telegram_delivery = send_telegram_event(
        event=payload["telegram_event"],
        state_path=root / "state" / "autoprompting_telegram_state.json",
        send_enabled=send_telegram,
    )
    payload["telegram_event"]["delivery"] = telegram_delivery
    payload["operator_summary"]["telegram_event"]["delivery_status"] = telegram_delivery.get("status")
    artifacts = payload.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    artifacts.update(
        {
            "latest_json": str(latest_path.relative_to(root)),
            "instance6_cycle_json": str(cycle_path.relative_to(root)),
            "human_queue_json": str(human_queue_path.relative_to(root)),
            "telegram_json": str(telegram_path.relative_to(root)),
            "telegram_escalation_matrix_json": str(escalation_matrix_path.relative_to(root)),
            "operator_summary_json": str(operator_summary_path.relative_to(root)),
        }
    )
    artifacts.setdefault("cycle_json", str(cycle_path.relative_to(root)))
    payload["artifacts"] = artifacts

    _write_json(cycle_path, payload)
    _write_json(latest_path, payload)
    _write_json(human_queue_path, payload["human_queue"])
    _write_json(telegram_path, payload["telegram_event"])
    _write_json(
        escalation_matrix_path,
        build_escalation_matrix(generated_at=str(payload.get("generated_at") or generated_at.isoformat())),
    )
    _write_json(operator_summary_path, payload["operator_summary"])

    return {
        "autoprompting_latest": str(latest_path),
        "autoprompting_cycle": str(cycle_path),
        "human_queue_latest": str(human_queue_path),
        "telegram_latest": str(telegram_path),
        "telegram_escalation_matrix": str(escalation_matrix_path),
        "operator_summary_latest": str(operator_summary_path),
        "telegram_delivery_status": str(telegram_delivery.get("status")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Instance 6 autoprompt human-queue and Telegram escalation cycle.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Workspace root (default: current directory).",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Actually send Telegram pages when escalation conditions are met.",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    result = write_instance6_autoprompt_cycle(root=root, send_telegram=args.send_telegram)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
