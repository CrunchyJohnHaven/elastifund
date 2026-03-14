import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

import _remote_cycle_status_shared as _shared

globals().update({k: v for k, v in vars(_shared).items() if not k.startswith("__")})

def test_render_remote_cycle_status_markdown_includes_operator_truth(
    tmp_path: Path,
    monkeypatch,
):
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

    monkeypatch.setattr(
        "scripts.write_remote_cycle_status._load_polymarket_wallet_state",
        lambda root: {
            "status": "ok",
            "checked_at": "2026-03-09T12:31:00+00:00",
            "maker_address": "0xabc",
            "signature_type": 1,
            "free_collateral_usd": 0.0,
            "reserved_order_usd": 0.0,
            "live_orders_count": 0,
            "live_orders": [],
            "open_positions_count": 1,
            "positions_initial_value_usd": 5.0,
            "positions_current_value_usd": 4.5,
            "positions_unrealized_pnl_usd": -0.5,
            "closed_positions_count": 1,
            "closed_positions_realized_pnl_usd": -1.49,
            "total_wallet_value_usd": 4.5,
            "warnings": ["positions_fetch_failed:test"],
        },
    )

    markdown = render_remote_cycle_status_markdown(build_remote_cycle_status(tmp_path))

    assert "- Service: stopped (inactive)" in markdown
    assert "- Root regression suite: failing" in markdown
    assert "- Wallet-flow bootstrap: not_ready" in markdown
    assert "- Closed trades: 1" in markdown
    assert "- Polymarket actual deployable USD: $0.00" in markdown
    assert "- Wallet status: ok" in markdown
    assert "- Realized PnL: $-1.49" in markdown
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
                "        'bankroll': 250.0,",
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
                "    print('  Bankroll: configured in .env')",
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
