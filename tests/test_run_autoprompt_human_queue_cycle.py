from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from scripts.run_autoprompt_human_queue_cycle import (
    build_instance6_autoprompt_cycle,
    write_instance6_autoprompt_cycle,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_build_cycle_emits_human_queue_and_initial_contract_blockers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": _iso_now(),
            "allow_order_submission": True,
            "summary": {
                "launch_posture": "clear",
                "execution_mode": "live",
                "effective_runtime_profile": "maker_velocity_live",
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "finance" / "latest.json",
        {
            "generated_at": _iso_now(),
            "finance_gate_pass": True,
            "finance_state": "hold_no_spend",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": _iso_now(),
            "status": "passing",
        },
    )
    (tmp_path / "autoprompting.md").write_text(
        "| Primary near-term objective | Reverse-engineer the best 5-15 minute Polymarket traders |\n",
        encoding="utf-8",
    )

    payload = build_instance6_autoprompt_cycle(tmp_path)

    assert payload["status"] == "active"
    assert "no_human_queue_artifact" in payload["required_outputs"]["block_reasons"]
    assert "no_autoprompt_telegram_contract" in payload["required_outputs"]["block_reasons"]
    queue_items = payload["human_queue"]["queue"]
    assert any(item["type"] == "non_trading_continuity" for item in queue_items)
    assert payload["telegram_event"]["should_send"] is True
    assert "credential_required" in payload["telegram_event"]["reason_codes"]


def test_build_cycle_accepts_telegram_token_alias(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "alias-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": _iso_now(),
            "allow_order_submission": True,
            "summary": {
                "launch_posture": "clear",
                "execution_mode": "live",
                "effective_runtime_profile": "maker_velocity_live",
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "finance" / "latest.json",
        {
            "generated_at": _iso_now(),
            "finance_gate_pass": True,
            "finance_state": "hold_no_spend",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": _iso_now(),
            "status": "passing",
        },
    )

    payload = build_instance6_autoprompt_cycle(tmp_path)

    assert payload["telegram_event"]["should_send"] is False
    assert "credential_required" not in payload["telegram_event"]["reason_codes"]


def test_build_cycle_uses_hold_repair_and_repeated_blocked_retry_signal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    _write_json(
        tmp_path / "reports" / "finance" / "latest.json",
        {
            "generated_at": _iso_now(),
            "finance_gate_pass": True,
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": _iso_now(),
            "status": "passing",
        },
    )
    _write_json(
        tmp_path / "reports" / "autoprompting" / "latest.json",
        {
            "generated_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            "retry": {
                "blocked_retry_count": 1,
                "hold_repair_blockers": ["missing:reports/runtime_truth_latest.json"],
            },
            "runtime_snapshot": {
                "launch_posture": "blocked",
            },
            "source_hashes": {},
        },
    )

    payload = build_instance6_autoprompt_cycle(tmp_path)

    assert payload["status"] == "hold_repair"
    assert payload["hold_repair"]["active"] is True
    assert "missing:reports/runtime_truth_latest.json" in payload["hold_repair"]["blockers"]
    assert payload["retry"]["blocked_retry_count"] == 2
    assert any(
        item.get("reason_code") == "repeated_blocked_retry"
        for item in payload["human_queue"]["queue"]
        if item.get("type") == "human_action"
    )


def test_write_cycle_publishes_required_artifacts(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": _iso_now(),
            "allow_order_submission": True,
            "summary": {
                "launch_posture": "clear",
                "execution_mode": "live",
                "effective_runtime_profile": "maker_velocity_live",
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "finance" / "latest.json",
        {
            "generated_at": _iso_now(),
            "finance_gate_pass": True,
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": _iso_now(),
            "status": "passing",
        },
    )

    result = write_instance6_autoprompt_cycle(root=tmp_path, send_telegram=False)

    assert (tmp_path / "reports" / "autoprompting" / "latest.json").exists()
    assert (tmp_path / "reports" / "autoprompting" / "human_queue" / "latest.json").exists()
    assert (tmp_path / "reports" / "autoprompting" / "telegram" / "latest.json").exists()
    assert (tmp_path / "reports" / "autoprompting" / "telegram" / "escalation_matrix.json").exists()
    assert (tmp_path / "reports" / "autoprompting" / "operator_summary" / "latest.json").exists()
    escalation_matrix = json.loads(
        (tmp_path / "reports" / "autoprompting" / "telegram" / "escalation_matrix.json").read_text(encoding="utf-8")
    )
    reason_codes = {entry.get("reason_code") for entry in escalation_matrix.get("reasons", [])}
    assert "credential_required" in reason_codes
    assert "deploy_approval_required" in reason_codes
    assert "telegram_escalation_matrix" in result
    assert result["telegram_delivery_status"] in {"dry_run_send_disabled", "skip_no_action_required"}
