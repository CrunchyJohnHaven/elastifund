from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.run_autoprompt_cycle import build_autoprompt_cycle


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_fresh_inputs(root: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _write_json(
        root / "reports" / "runtime_truth_latest.json",
        {
            "generated_at": now,
            "agent_run_mode": "live",
            "execution_mode": "live",
            "allow_order_submission": True,
            "summary": {"launch_posture": "clear"},
        },
    )
    _write_json(
        root / "reports" / "finance" / "latest.json",
        {
            "generated_at": now,
            "finance_gate_pass": True,
            "finance_gate": {"pass": True, "status": "pass", "reason": "queue_ready"},
        },
    )
    _write_json(
        root / "reports" / "root_test_status.json",
        {
            "generated_at": now,
            "summary": {"passed": 1723, "warnings": 5},
        },
    )


def test_build_autoprompt_cycle_writes_latest_cycle_and_merge_artifacts(tmp_path: Path) -> None:
    _write_fresh_inputs(tmp_path)

    latest_json = tmp_path / "reports" / "autoprompting" / "latest.json"
    cycle_dir = tmp_path / "reports" / "autoprompting" / "cycles"
    merge_dir = tmp_path / "reports" / "autoprompting" / "merges"
    instance4_json = tmp_path / "reports" / "autoprompting" / "instance4" / "latest.json"

    outcome = build_autoprompt_cycle(
        root=tmp_path,
        latest_json_path=latest_json,
        cycle_dir=cycle_dir,
        merge_dir=merge_dir,
        instance4_json_path=instance4_json,
    )

    assert outcome["status"] == "active"
    assert latest_json.exists()
    assert Path(outcome["cycle_json"]).exists()
    assert Path(outcome["merge_json"]).exists()
    assert Path(outcome["instance4_json"]).exists()

    latest_payload = json.loads(latest_json.read_text(encoding="utf-8"))
    cycle_payload = json.loads(Path(outcome["cycle_json"]).read_text(encoding="utf-8"))
    merge_payload = json.loads(Path(outcome["merge_json"]).read_text(encoding="utf-8"))

    assert latest_payload["schema_version"] == "autoprompting.v1"
    assert cycle_payload["schema_version"] == "cycle_truth.v1"
    assert merge_payload["schema_version"] == "autoprompt_merges.v1"

    assert latest_payload["required_outputs"]["candidate_delta_arr_bps"] == 130
    assert latest_payload["required_outputs"]["arr_confidence_score"] == 0.74
    assert latest_payload["required_outputs"]["finance_gate_pass"] is True

    assert merge_payload["summary"]["auto_merge"] >= 1
    assert merge_payload["summary"]["gated_merge"] >= 1


def test_build_autoprompt_cycle_drops_to_hold_repair_on_missing_critical_inputs(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports" / "finance" / "latest.json",
        {"generated_at": datetime.now(timezone.utc).isoformat(), "finance_gate_pass": True},
    )

    latest_json = tmp_path / "reports" / "autoprompting" / "latest.json"
    cycle_dir = tmp_path / "reports" / "autoprompting" / "cycles"
    merge_dir = tmp_path / "reports" / "autoprompting" / "merges"
    instance4_json = tmp_path / "reports" / "autoprompting" / "instance4" / "latest.json"

    outcome = build_autoprompt_cycle(
        root=tmp_path,
        latest_json_path=latest_json,
        cycle_dir=cycle_dir,
        merge_dir=merge_dir,
        instance4_json_path=instance4_json,
    )

    assert outcome["status"] == "hold_repair"

    latest_payload = json.loads(latest_json.read_text(encoding="utf-8"))
    hold_repair = latest_payload["stale_hold_repair"]

    assert hold_repair["active"] is True
    assert hold_repair["mode"] == "observe_only"
    assert hold_repair["retry_in_minutes"] == 15
    assert any(str(reason).startswith("missing:reports/runtime_truth_latest.json") for reason in hold_repair["block_reasons"])
