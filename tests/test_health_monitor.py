from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from bot.health_monitor import (
    HeartbeatWriter,
    build_telegram_sender,
    build_daily_summary_snapshot,
    evaluate_heartbeat,
    format_daily_summary,
    load_heartbeat,
    run_health_check,
)


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


def test_heartbeat_writer_tracks_errors_and_cycle_completion(tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "heartbeat.json"
    writer = HeartbeatWriter(heartbeat_path)

    writer.mark_startup(
        profile_name="paper_aggressive",
        runtime_mode="shadow",
        paper_mode=True,
        scan_interval_seconds=120,
    )
    writer.mark_cycle_started(
        41,
        profile_name="paper_aggressive",
        runtime_mode="shadow",
        paper_mode=True,
        scan_interval_seconds=120,
    )
    writer.mark_cycle_error(
        "scanner timeout",
        cycle_number=41,
        profile_name="paper_aggressive",
        runtime_mode="shadow",
        paper_mode=True,
        scan_interval_seconds=120,
    )
    writer.mark_cycle_completed(
        {
            "status": "ok",
            "cycle": 41,
            "signals": 3,
            "trades_placed": 1,
            "open_positions": 2,
            "bankroll": 250.25,
        },
        profile_name="paper_aggressive",
        runtime_mode="shadow",
        paper_mode=True,
        scan_interval_seconds=120,
        total_trades=4,
        trades_today=2,
        open_positions=2,
    )

    payload = load_heartbeat(heartbeat_path)
    today = datetime.now(timezone.utc).date().isoformat()

    assert payload["status"] == "ok"
    assert payload["cycle_number"] == 41
    assert payload["signals_found"] == 3
    assert payload["trades_placed"] == 1
    assert payload["paper_mode"] is True
    assert payload["error_counts_by_date"][today] == 1
    assert payload["last_cycle_completed_at"]


def test_evaluate_heartbeat_prefers_last_completed_cycle_time() -> None:
    now = datetime(2026, 3, 9, 0, 15, tzinfo=timezone.utc)
    heartbeat = {
        "status": "running",
        "cycle_number": 314,
        "profile_name": "paper_aggressive",
        "runtime_mode": "shadow",
        "paper_mode": True,
        "last_cycle_completed_at": (now - timedelta(minutes=11)).isoformat(),
        "last_updated_at": (now - timedelta(minutes=1)).isoformat(),
    }

    evaluation = evaluate_heartbeat(heartbeat, now=now, timeout_seconds=600)

    assert evaluation["status"] == "stale"
    assert evaluation["reference_field"] == "last_cycle_completed_at"
    assert evaluation["cycle_number"] == 314


def test_build_daily_summary_snapshot_counts_signals_trades_and_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "jj_trades.db"
    heartbeat_path = tmp_path / "heartbeat.json"
    state_path = tmp_path / "jj_state.json"
    _create_monitor_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO cycles (timestamp, cycle_number, signals_found, trades_placed)
        VALUES (?, ?, ?, ?)
        """,
        [
            ("2026-03-08T00:01:00+00:00", 1, 2, 1),
            ("2026-03-08T00:03:00+00:00", 2, 3, 1),
        ],
    )
    conn.executemany(
        """
        INSERT INTO trades (id, timestamp, paper, outcome, pnl, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("paper-1", "2026-03-08T00:02:00+00:00", 1, "won", 1.25, "2026-03-08T01:00:00+00:00"),
            ("paper-2", "2026-03-08T00:04:00+00:00", 1, "lost", -0.50, "2026-03-08T02:00:00+00:00"),
            ("live-1", "2026-03-08T00:05:00+00:00", 0, None, None, None),
        ],
    )
    conn.commit()
    conn.close()

    heartbeat_path.write_text(
        json.dumps(
            {
                "profile_name": "paper_aggressive",
                "runtime_mode": "shadow",
                "paper_mode": True,
                "error_counts_by_date": {"2026-03-08": 2},
                "cycle_number": 314,
                "last_cycle_summary": {
                    "cycle": 314,
                    "status": "ok",
                    "signals": 5,
                    "trades_placed": 1,
                },
            }
        )
    )
    state_path.write_text(
        json.dumps(
            {
                "bankroll": 250.0,
                "total_trades": 3,
                "trades_today": 2,
                "open_positions": {"m1": {}, "m2": {}},
            }
        )
    )

    snapshot = build_daily_summary_snapshot(
        target_date=date(2026, 3, 8),
        db_path=db_path,
        jj_state_path=state_path,
        heartbeat_path=heartbeat_path,
    )

    assert snapshot["cycles_run"] == 2
    assert snapshot["signals_found"] == 5
    assert snapshot["paper_trades"] == 2
    assert snapshot["live_trades"] == 1
    assert snapshot["resolved_trades"] == 2
    assert snapshot["wins"] == 1
    assert snapshot["losses"] == 1
    assert snapshot["daily_pnl"] == 0.75
    assert snapshot["error_count"] == 2
    assert snapshot["open_positions"] == 2
    assert snapshot["bankroll"] == 250.0


def test_build_telegram_sender_constructs_sync_sender_without_loading_scanner(
    monkeypatch,
) -> None:
    import bot.polymarket_runtime as runtime

    runtime._telegram_notifier_cls = runtime._UNSET
    runtime._runtime_export_cache.clear()
    sent_messages: list[tuple[str, str]] = []

    class FakeNotifier:
        enabled = True

        def __init__(self, *args, **kwargs):
            pass

        async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
            sent_messages.append((text, parse_mode))
            return True

    def _fake_import(module_name: str):
        if module_name == "telegram":
            return SimpleNamespace(TelegramNotifier=FakeNotifier)
        raise AssertionError(f"unexpected import: {module_name}")

    monkeypatch.setattr(runtime, "import_polymarket_module", _fake_import)

    sender = build_telegram_sender()

    assert sender is not None
    assert sender("JJ HEALTH TEST") is True
    assert sent_messages == [("JJ HEALTH TEST", "")]


def test_build_telegram_sender_returns_none_when_unconfigured(monkeypatch) -> None:
    import bot.polymarket_runtime as runtime

    runtime._telegram_notifier_cls = runtime._UNSET

    class FakeNotifier:
        enabled = False

        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(
        runtime,
        "import_polymarket_module",
        lambda module_name: SimpleNamespace(TelegramNotifier=FakeNotifier),
    )

    assert build_telegram_sender() is None


def test_build_telegram_sender_returns_none_when_telegram_unavailable(monkeypatch) -> None:
    import bot.polymarket_runtime as runtime

    runtime._telegram_notifier_cls = runtime._UNSET

    def _fake_import(module_name: str):
        raise ImportError(module_name)

    monkeypatch.setattr(runtime, "import_polymarket_module", _fake_import)

    assert build_telegram_sender() is None


def test_format_daily_summary_preserves_operational_fields() -> None:
    message = format_daily_summary(
        {
            "target_date": "2026-03-08",
            "profile_name": "live_aggressive",
            "runtime_mode": "shadow",
            "paper_mode": False,
            "cycles_run": 12,
            "signals_found": 7,
            "paper_trades": 0,
            "live_trades": 2,
            "resolved_trades": 2,
            "wins": 1,
            "losses": 1,
            "daily_pnl": 0.75,
            "error_count": 1,
            "open_positions": 3,
            "bankroll": 250.0,
            "last_cycle_number": 314,
            "last_cycle_status": "ok",
            "last_cycle_signals": 2,
            "last_cycle_trades_placed": 1,
        }
    )

    assert "JJ DAILY SUMMARY - 2026-03-08 UTC" in message
    assert "Profile: live_aggressive | Mode: shadow | Trading: live" in message
    assert "Cycles: 12 | Signals: 7 | Paper trades: 0 | Live trades: 2" in message
    assert "P&L: $+0.75 | Errors: 1 | Open positions: 3" in message
    assert "Last cycle: #314 (ok, signals=2, trades=1)" in message


def test_run_health_check_dedupes_restart_and_daily_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "jj_trades.db"
    heartbeat_path = tmp_path / "heartbeat.json"
    state_path = tmp_path / "monitor_state.json"
    jj_state_path = tmp_path / "jj_state.json"
    _create_monitor_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO cycles (timestamp, cycle_number, signals_found, trades_placed)
        VALUES (?, ?, ?, ?)
        """,
        ("2026-03-08T23:55:00+00:00", 314, 4, 1),
    )
    conn.execute(
        """
        INSERT INTO trades (id, timestamp, paper, outcome, pnl, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("paper-1", "2026-03-08T23:56:00+00:00", 1, "won", 1.0, "2026-03-08T23:59:00+00:00"),
    )
    conn.commit()
    conn.close()

    heartbeat_path.write_text(
        json.dumps(
            {
                "status": "error",
                "cycle_number": 314,
                "profile_name": "paper_aggressive",
                "runtime_mode": "shadow",
                "paper_mode": True,
                "last_cycle_completed_at": "2026-03-08T23:40:00+00:00",
                "last_error": "scanner failed",
                "error_counts_by_date": {"2026-03-08": 1},
                "last_cycle_summary": {"cycle": 314, "status": "ok", "signals": 4, "trades_placed": 1},
            }
        )
    )
    jj_state_path.write_text(
        json.dumps(
            {
                "bankroll": 248.51,
                "total_trades": 1,
                "open_positions": {"m1": {}},
            }
        )
    )

    messages: list[str] = []
    restart_calls: list[dict[str, object]] = []

    def _send(message: str) -> bool:
        messages.append(message)
        return True

    def _restart(*, service_name: str, use_sudo: bool) -> dict[str, object]:
        restart_calls.append({"service_name": service_name, "use_sudo": use_sudo})
        return {"ok": True, "active_state": "active"}

    first_now = datetime(2026, 3, 9, 0, 5, tzinfo=timezone.utc)
    first_result = run_health_check(
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        db_path=db_path,
        jj_state_path=jj_state_path,
        timeout_seconds=600,
        auto_restart=True,
        service_name="jj-live.service",
        use_sudo_systemctl=True,
        restart_cooldown_seconds=900,
        send_daily_summary=True,
        daily_summary_hour_utc=0,
        daily_summary_minute_utc=0,
        now=first_now,
        send_message=_send,
        restart_func=_restart,
    )

    second_result = run_health_check(
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        db_path=db_path,
        jj_state_path=jj_state_path,
        timeout_seconds=600,
        auto_restart=True,
        service_name="jj-live.service",
        use_sudo_systemctl=True,
        restart_cooldown_seconds=900,
        send_daily_summary=True,
        daily_summary_hour_utc=0,
        daily_summary_minute_utc=0,
        now=first_now + timedelta(minutes=1),
        send_message=_send,
        restart_func=_restart,
    )

    assert "health_alert_sent" in first_result["actions"]
    assert "service_restart_attempted" in first_result["actions"]
    assert "daily_summary_sent" in first_result["actions"]
    assert second_result["actions"] == ["restart_cooldown_active"]
    assert len(restart_calls) == 1
    assert any("JJ HEALTH ALERT" in message for message in messages)
    assert any("JJ HEALTH ACTION" in message for message in messages)
    assert any("JJ DAILY SUMMARY - 2026-03-08 UTC" in message for message in messages)

    monitor_state = json.loads(state_path.read_text())
    assert monitor_state["last_daily_summary_for_date"] == "2026-03-08"
    assert monitor_state["last_health_status"] == "stale"
