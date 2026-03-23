from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_strike_desk.py"


def _packet(
    *,
    strategy_id: str,
    market_id: str,
    priority: int,
    direction: str = "YES",
    size_usd: float = 10.0,
    edge_estimate: float = 0.05,
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "market_id": market_id,
        "platform": "polymarket",
        "direction": direction,
        "token_id": f"{market_id}-token",
        "size_usd": size_usd,
        "edge_estimate": edge_estimate,
        "confidence": 0.9,
        "evidence_hash": f"{strategy_id}-{market_id}",
        "max_slippage": 0.02,
        "ttl_seconds": 120,
        "order_type": "maker",
        "priority": priority,
        "linked_packets": [],
        "metadata": {"group_id": market_id},
    }


def test_runner_writes_queue_and_event_tape(tmp_path: Path) -> None:
    packets = [
        _packet(strategy_id="neg_risk", market_id="m1", priority=0, size_usd=12.0, edge_estimate=0.10),
        _packet(strategy_id="whale", market_id="m1", priority=4, size_usd=12.0, edge_estimate=0.04),
        _packet(strategy_id="resolution", market_id="m2", priority=2, size_usd=5.0, edge_estimate=0.03),
    ]
    packets_path = tmp_path / "packets.json"
    packets_path.write_text(json.dumps(packets, indent=2), encoding="utf-8")

    reports_dir = tmp_path / "strike_desk_reports"
    tape_db = tmp_path / "strike_desk.db"
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--packets-json",
            str(packets_path),
            "--reports-dir",
            str(reports_dir),
            "--tape-db",
            str(tape_db),
            "--cycle-id",
            "cycle_test",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    latest_json = reports_dir / "latest.json"
    latest_md = reports_dir / "latest.md"
    history_jsonl = reports_dir / "history.jsonl"
    assert latest_json.exists()
    assert latest_md.exists()
    assert history_jsonl.exists()
    assert tape_db.exists()

    report = json.loads(latest_json.read_text(encoding="utf-8"))
    assert report["cycle_id"] == "cycle_test"
    assert report["lane_set"] == "p2_p4"
    assert report["source_mode"].startswith("fixture:")
    assert report["raw_packet_count"] == 3
    assert report["approved_packet_count"] == 2
    assert report["rejected_packet_count"] == 1
    assert report["execution_queue"][0]["strategy_id"] == "neg_risk"
    assert report["execution_queue"][1]["strategy_id"] == "resolution"
    assert report["rejected_packets"][0]["strategy_id"] == "whale"
    assert report["tape"]["event_counts"]["events"] >= 6
    assert report["tape"]["event_counts"]["decision_trade_proposed"] == 3
    assert report["tape"]["event_counts"]["decision_trade_approved"] == 2
    assert report["tape"]["event_counts"]["decision_trade_rejected"] == 1

    with sqlite3.connect(tape_db) as conn:
        proposed = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'decision.trade_proposed'"
        ).fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'decision.trade_approved'"
        ).fetchone()[0]
        rejected = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'decision.trade_rejected'"
        ).fetchone()[0]

    assert proposed == 3
    assert approved == 2
    assert rejected == 1
