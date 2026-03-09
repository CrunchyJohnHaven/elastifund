from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bot.polymarket_runtime import TelegramNotifier


REPO_ROOT = Path(__file__).resolve().parent.parent


def _create_monitor_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            cycle_number INTEGER,
            signals_found INTEGER,
            trades_placed INTEGER
        );

        CREATE TABLE trades (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            paper INTEGER DEFAULT 1,
            outcome TEXT,
            pnl REAL,
            resolved_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def test_telegram_notifier_accepts_telegram_token_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "alias-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    notifier = TelegramNotifier()

    assert notifier.bot_token == "alias-token"
    assert notifier.is_configured is True


def test_daily_summary_script_prints_to_stdout_without_telegram(tmp_path: Path) -> None:
    db_path = tmp_path / "jj_trades.db"
    heartbeat_path = tmp_path / "heartbeat.json"
    jj_state_path = tmp_path / "jj_state.json"
    _create_monitor_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO cycles (timestamp, cycle_number, signals_found, trades_placed)
            VALUES (?, ?, ?, ?)
            """,
            ("2026-03-08T00:05:00+00:00", 7, 2, 1),
        )
        conn.execute(
            """
            INSERT INTO trades (id, timestamp, paper, outcome, pnl, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("paper-1", "2026-03-08T00:06:00+00:00", 1, "won", 1.25, "2026-03-08T00:10:00+00:00"),
        )
        conn.commit()

    heartbeat_path.write_text(
        json.dumps(
            {
                "profile_name": "paper_aggressive",
                "runtime_mode": "shadow",
                "paper_mode": True,
                "cycle_number": 7,
                "last_cycle_summary": {
                    "cycle": 7,
                    "status": "ok",
                    "signals": 2,
                    "trades_placed": 1,
                },
            }
        )
    )
    jj_state_path.write_text(
        json.dumps(
            {
                "bankroll": 248.76,
                "total_trades": 1,
                "trades_today": 1,
                "open_positions": {"m1": {}},
            }
        )
    )

    env = os.environ.copy()
    env.pop("TELEGRAM_BOT_TOKEN", None)
    env.pop("TELEGRAM_TOKEN", None)
    env.pop("TELEGRAM_CHAT_ID", None)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "daily_summary.py"),
            "--date",
            "2026-03-08",
            "--db-path",
            str(db_path),
            "--jj-state-file",
            str(jj_state_path),
            "--heartbeat-file",
            str(heartbeat_path),
            "--stdout-only",
        ],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    assert "JJ DAILY SUMMARY - 2026-03-08 UTC" in result.stdout
    assert "Cycles: 1 | Signals: 2" in result.stdout
    assert "P&L: $+1.25" in result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required for shell heartbeat tests")
def test_health_check_shell_script_returns_nonzero_for_stale_heartbeat(tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "heartbeat.json"
    heartbeat_path.write_text(
        json.dumps(
            {
                "status": "running",
                "cycle_number": 314,
                "profile_name": "live_aggressive",
                "runtime_mode": "shadow",
                "last_cycle_completed_at": "2026-03-09T00:00:00+00:00",
            }
        )
    )

    fixed_now = int(datetime(2026, 3, 9, 0, 20, tzinfo=timezone.utc).timestamp())
    env = os.environ.copy()
    env["JJ_HEARTBEAT_FILE"] = str(heartbeat_path)
    env["JJ_HEARTBEAT_TIMEOUT_SECONDS"] = "600"
    env["JJ_HEALTH_NOW_EPOCH"] = str(fixed_now)
    env.pop("TELEGRAM_BOT_TOKEN", None)
    env.pop("TELEGRAM_TOKEN", None)
    env.pop("TELEGRAM_CHAT_ID", None)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "health_check.sh")],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
        text=True,
    )

    assert result.returncode == 1
    assert "JJ HEALTH ALERT" in result.stderr
    assert "heartbeat older than 600s" in result.stderr
