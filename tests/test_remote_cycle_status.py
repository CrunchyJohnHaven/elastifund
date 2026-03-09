from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.write_remote_cycle_status import (  # noqa: E402
    build_remote_cycle_status,
    render_remote_cycle_status_markdown,
    write_remote_cycle_status,
)


def test_build_remote_cycle_status_reports_launch_blockers(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-08T09:01:00+00:00",
            "command": "make test",
            "status": "failing",
            "summary": "scripts/run_edge_collector.py uses stdlib-incompatible logging kwargs.",
            "returncode": 2,
            "output_tail": ["FAILED tests/test_edge_collector_standalone.py"],
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "fill_proxy": {
                "full_fill_proxy_rate": None,
            },
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {
                "measurement_status": "insufficient_live_samples",
            },
        },
    )
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": "won"},
            {"market_id": "m2", "outcome": None},
        ],
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["service"]["status"] == "stopped"
    assert status["root_tests"]["status"] == "failing"
    assert status["runtime"]["closed_trades"] == 1
    assert status["wallet_flow"]["ready"] is False
    assert "missing_data/smart_wallets.json" in status["wallet_flow"]["reasons"]
    assert "missing_data/wallet_scores.db" in status["wallet_flow"]["reasons"]
    assert status["structural_gates"]["a6"]["status"] == "blocked"
    assert status["structural_gates"]["b1"]["status"] == "blocked"
    assert status["launch"]["fast_flow_restart_ready"] is False
    assert status["launch"]["live_launch_blocked"] is True
    assert status["launch"]["next_operator_action"].startswith(
        "Merge the root regression repair"
    )


def test_write_remote_cycle_status_refreshes_root_test_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "running",
            "systemctl_state": "active",
            "detail": "active",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "fill_proxy": {"full_fill_proxy_rate": 0.72},
            "gating_metrics": {
                "all_gates_pass": True,
                "fill_probability_gate": "pass",
                "half_life_gate": "pass",
                "half_life_seconds": 480.0,
                "settlement_path_gate": "pass",
            },
            "settlement": {
                "successful_operation_count": 3,
            },
            "lanes": {
                "b1": {
                    "status": "ready_for_shadow",
                    "summary": "B-1 is ready for shadow validation.",
                    "classification_accuracy": 0.9,
                    "false_positive_rate": 0.03,
                }
            },
        },
    )
    _write_json(
        tmp_path / "data" / "smart_wallets.json",
        {
            "wallets": [
                {"address": "0x1"},
                {"address": "0x2"},
                {"address": "0x3"},
            ],
            "last_updated": "2026-03-08T08:55:00+00:00",
        },
    )
    (tmp_path / "data" / "wallet_scores.db").write_bytes(b"sqlite-stub")
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": "won"},
            {"market_id": "m2", "outcome": "lost"},
        ],
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="collected 12 items\n12 passed\n",
            stderr="",
        )

    monkeypatch.setattr("scripts.write_remote_cycle_status.subprocess.run", fake_run)

    written = write_remote_cycle_status(tmp_path, refresh_root_tests=True)

    root_test_snapshot = json.loads(
        (tmp_path / "reports" / "root_test_status.json").read_text()
    )
    payload = json.loads(Path(written["json"]).read_text())

    assert root_test_snapshot["status"] == "passing"
    assert root_test_snapshot["summary"] == "12 passed"
    assert payload["root_tests"]["status"] == "passing"
    assert payload["wallet_flow"]["ready"] is True
    assert payload["structural_gates"]["a6"]["status"] == "ready_for_shadow"
    assert payload["structural_gates"]["b1"]["status"] == "ready_for_shadow"


def test_render_remote_cycle_status_markdown_includes_operator_truth(tmp_path: Path):
    _write_base_remote_state(tmp_path)
    _write_json(
        tmp_path / "reports" / "remote_service_status.json",
        {
            "checked_at": "2026-03-08T09:00:00+00:00",
            "status": "stopped",
            "systemctl_state": "inactive",
            "detail": "inactive",
        },
    )
    _write_json(
        tmp_path / "reports" / "root_test_status.json",
        {
            "checked_at": "2026-03-08T09:01:00+00:00",
            "command": "make test",
            "status": "failing",
            "summary": "make test is still red.",
        },
    )
    _write_json(
        tmp_path / "reports" / "arb_empirical_snapshot.json",
        {
            "gating_metrics": {
                "all_gates_pass": False,
                "fill_probability_gate": "insufficient_data",
                "half_life_gate": "fail",
                "half_life_seconds": 0.0,
                "settlement_path_gate": "untested",
            },
            "b1": {},
        },
    )
    _write_trade_db(
        tmp_path / "data" / "jj_trades.db",
        [
            {"market_id": "m1", "outcome": "won"},
        ],
    )

    markdown = render_remote_cycle_status_markdown(build_remote_cycle_status(tmp_path))

    assert "- Service: stopped (inactive)" in markdown
    assert "- Root regression suite: failing" in markdown
    assert "- Wallet-flow bootstrap: not_ready" in markdown
    assert "- Closed trades: 1" in markdown
    assert "- A-6 gate: blocked" in markdown
    assert "- B-1 gate: blocked" in markdown
    assert "- Live launch blocked: yes" in markdown
    assert "Merge the root regression repair" in markdown


def test_bridge_pull_only_captures_service_snapshot_before_status(tmp_path: Path):
    project_dir = tmp_path / "project"
    bin_dir = tmp_path / "bin"
    project_dir.mkdir()
    (project_dir / "scripts").mkdir()
    (project_dir / "reports").mkdir()
    (project_dir / "data").mkdir()
    bin_dir.mkdir()

    key_path = tmp_path / "lightsail.pem"
    key_path.write_text("test-key")

    bridge_script = REPO_ROOT / "scripts" / "bridge.sh"
    trace_path = project_dir / "status_invocation.json"
    command_log = tmp_path / "bridge_commands.log"

    _write_text(
        project_dir / "scripts" / "write_remote_cycle_status.py",
        "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "root = Path(__file__).resolve().parents[1]",
                "payload = {",
                "    'service_snapshot_exists': (root / 'reports' / 'remote_service_status.json').exists(),",
                "    'jj_state_exists': (root / 'jj_state.json').exists(),",
                "}",
                f"Path({str(trace_path)!r}).write_text(json.dumps(payload, sort_keys=True))",
                "print(json.dumps({'ok': True}, sort_keys=True))",
            ]
        ),
    )
    _write_executable(
        bin_dir / "rsync",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import os",
                "import sys",
                "from pathlib import Path",
                "log = Path(os.environ['BRIDGE_TEST_COMMAND_LOG'])",
                "with log.open('a') as fh:",
                "    fh.write('rsync ' + ' '.join(sys.argv[1:]) + '\\n')",
                "dest = Path(sys.argv[-1])",
                "if ':' not in sys.argv[-1]:",
                "    (dest / 'data').mkdir(parents=True, exist_ok=True)",
                "    (dest / 'reports' / 'flywheel').mkdir(parents=True, exist_ok=True)",
                "    (dest / 'jj_state.json').write_text(json.dumps({",
                "        'bankroll': 247.51,",
                "        'total_deployed': 0.0,",
                "        'daily_pnl': 0.0,",
                "        'total_pnl': 0.0,",
                "        'daily_pnl_date': '2026-03-08',",
                "        'trades_today': 0,",
                "        'total_trades': 0,",
                "        'open_positions': {},",
                "        'cycles_completed': 16,",
                "    }, sort_keys=True))",
                "    (dest / 'data' / 'intel_snapshot.json').write_text(json.dumps({",
                "        'last_updated': '2026-03-08T08:53:32+00:00',",
                "        'total_cycles': 16,",
                "    }, sort_keys=True))",
                "    (dest / 'reports' / 'flywheel' / 'latest_sync.json').write_text(json.dumps({",
                "        'cycle_key': 'live-flywheel-20260308T085000Z',",
                "        'evaluated': 1,",
                "        'decisions': [{'decision': 'hold', 'reason_code': 'insufficient_evidence'}],",
                "        'artifacts': {},",
                "    }, sort_keys=True))",
            ]
        ),
    )
    _write_executable(
        bin_dir / "ssh",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os",
                "import sys",
                "from pathlib import Path",
                "log = Path(os.environ['BRIDGE_TEST_COMMAND_LOG'])",
                "with log.open('a') as fh:",
                "    fh.write('ssh ' + ' '.join(sys.argv[1:]) + '\\n')",
                "command = sys.argv[-1]",
                "if 'systemctl is-active jj-live.service' in command:",
                "    print('inactive')",
                "elif 'jj_state.json' in command:",
                "    print('  Bankroll: $247.51')",
                "    print('  Daily P&L: $0.00')",
                "    print('  Total P&L: $0.00')",
                "    print('  Open positions: 0')",
                "    print('  Total trades: 0')",
                "    print('  Cycles: 16')",
            ]
        ),
    )

    env = os.environ.copy()
    env["ELASTIFUND_PROJECT_DIR"] = str(project_dir)
    env["PYTHON_BIN"] = sys.executable
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["BRIDGE_TEST_COMMAND_LOG"] = str(command_log)

    result = subprocess.run(
        [
            "bash",
            str(bridge_script),
            "--pull-only",
            "--skip-flywheel",
            "--key",
            str(key_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    service_status = json.loads(
        (project_dir / "reports" / "remote_service_status.json").read_text()
    )
    status_invocation = json.loads(trace_path.read_text())

    assert service_status["status"] == "stopped"
    assert service_status["systemctl_state"] == "inactive"
    assert status_invocation == {
        "jj_state_exists": True,
        "service_snapshot_exists": True,
    }


def _write_base_remote_state(root: Path) -> None:
    _write_json(
        root / "config" / "remote_cycle_status.json",
        {
            "capital_sources": [
                {"account": "Polymarket", "amount_usd": 247.51, "source": "jj_state.json"},
                {"account": "Kalshi", "amount_usd": 100.0, "source": "manual_tracked_balance"},
            ],
            "pull_policy": {
                "pull_cadence_minutes": 30,
                "full_cycle_cadence_minutes": 60,
                "freshness_sla_minutes": 45,
                "expected_next_data_note": "Expect the next synced dataset on the next 30-minute pull.",
                "manual_pull_triggers": ["Immediately before any deploy."],
            },
            "velocity_forecast": {
                "current_annualized_return_pct": 0.0,
                "next_target_annualized_return_pct": 10.0,
                "next_target_after_hours_of_work": 3.0,
            },
            "deployment_finish": {
                "status": "blocked",
                "eta": "TBD",
                "blockers": ["Need more evidence."],
                "exit_criteria": ["Collect closed trades."],
            },
        },
    )
    _write_json(
        root / "jj_state.json",
        {
            "bankroll": 247.51,
            "total_deployed": 0.0,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "daily_pnl_date": "2026-03-08",
            "trades_today": 0,
            "total_trades": 0,
            "open_positions": {},
            "cycles_completed": 16,
            "b1_state": {"validation_accuracy": None},
        },
    )
    _write_json(
        root / "data" / "intel_snapshot.json",
        {
            "last_updated": "2026-03-08T08:53:32+00:00",
            "total_cycles": 16,
        },
    )
    _write_json(
        root / "reports" / "flywheel" / "latest_sync.json",
        {
            "cycle_key": "live-flywheel-20260308T085000Z",
            "evaluated": 1,
            "decisions": [
                {
                    "decision": "hold",
                    "reason_code": "insufficient_evidence",
                    "notes": "Collect more closed trades before promoting.",
                }
            ],
            "artifacts": {
                "summary_md": "reports/flywheel/latest.md",
                "scorecard": "reports/flywheel/latest.json",
            },
        },
    )


def _write_trade_db(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trades (market_id TEXT, outcome TEXT)")
    conn.executemany(
        "INSERT INTO trades (market_id, outcome) VALUES (?, ?)",
        [(row["market_id"], row["outcome"]) for row in rows],
    )
    conn.commit()
    conn.close()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _write_executable(path: Path, text: str) -> None:
    _write_text(path, text)
    path.chmod(0o755)
