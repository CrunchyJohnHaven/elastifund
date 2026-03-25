from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import scripts.run_local_twin as local_twin
from scripts.run_local_twin import DAEMON_PROFILES, LANE_RUNNERS, _resolve_lanes


def test_resolve_lanes_uses_requested_lane_even_in_daemon_mode() -> None:
    args = Namespace(lane="truth", daemon=True, daemon_profile="heavy_local")
    assert _resolve_lanes(args) == ["truth"]


def test_resolve_lanes_uses_default_daemon_profile() -> None:
    args = Namespace(lane=None, daemon=True, daemon_profile="default")
    assert _resolve_lanes(args) == DAEMON_PROFILES["default"]


def test_resolve_lanes_uses_heavy_local_daemon_profile() -> None:
    args = Namespace(lane=None, daemon=True, daemon_profile="heavy_local")
    assert _resolve_lanes(args) == DAEMON_PROFILES["heavy_local"]


def test_resolve_lanes_uses_all_lanes_for_one_shot() -> None:
    args = Namespace(lane=None, daemon=False, daemon_profile="default")
    assert _resolve_lanes(args) == list(LANE_RUNNERS.keys())


def test_default_daemon_profile_includes_alpaca_lane() -> None:
    assert "alpaca" in DAEMON_PROFILES["default"]


def test_default_daemon_profile_includes_feedback_lane() -> None:
    assert "feedback" in DAEMON_PROFILES["default"]


def test_run_alpaca_skips_when_credentials_missing(monkeypatch) -> None:
    monkeypatch.setenv("ALPACA_TRADING_MODE", "paper")
    for key in (
        "ALPACA_PAPER_API_KEY_ID",
        "ALPACA_PAPER_API_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(local_twin, "_repo_env", lambda: {})

    assert local_twin.run_alpaca(Namespace()) == 0


def test_run_alpaca_downgrades_live_without_explicit_local_live_gate(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("ALPACA_TRADING_MODE", "live")
    monkeypatch.setenv("ALPACA_ALLOW_LIVE", "true")
    monkeypatch.setenv("ALPACA_PAPER_API_KEY_ID", "paper-key")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET_KEY", "paper-secret")

    def _fake_run_script(relpath: str, extra_args=None, env_overrides=None) -> int:
        captured["relpath"] = relpath
        captured["extra_args"] = list(extra_args or [])
        captured["env_overrides"] = dict(env_overrides or {})
        return 0

    monkeypatch.setattr(local_twin, "_run_script", _fake_run_script)

    assert local_twin.run_alpaca(Namespace()) == 0
    assert captured["relpath"] == "scripts/run_alpaca_first_trade.py"
    assert captured["extra_args"] == ["--mode", "paper"]
    assert captured["env_overrides"] == {"ALPACA_TRADING_MODE": "paper"}


def test_run_alpaca_invokes_live_mode_when_venue_is_enabled(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("ALPACA_TRADING_MODE", "paper")
    monkeypatch.setenv("ALPACA_ALLOW_LIVE", "true")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")

    def _fake_run_script(relpath: str, extra_args=None, env_overrides=None) -> int:
        captured["relpath"] = relpath
        captured["extra_args"] = list(extra_args or [])
        captured["env_overrides"] = dict(env_overrides or {})
        return 0

    monkeypatch.setattr(local_twin, "_run_script", _fake_run_script)

    args = Namespace(local_live_venues="alpaca")
    assert local_twin.run_alpaca(args) == 0
    assert captured["relpath"] == "scripts/run_alpaca_first_trade.py"
    assert captured["extra_args"] == ["--mode", "live"]
    assert captured["env_overrides"] == {"ALPACA_TRADING_MODE": "live"}


def test_run_alpaca_persists_execution_error_as_blocker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALPACA_TRADING_MODE", "paper")
    monkeypatch.setenv("ALPACA_ALLOW_LIVE", "true")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret")
    monkeypatch.setattr(local_twin, "REPO_ROOT", tmp_path)

    written: list[tuple[str, dict[str, object]]] = []

    def _fake_update(args, venue, payload):  # type: ignore[no-untyped-def]
        written.append((venue, dict(payload)))

    monkeypatch.setattr(local_twin, "_update_local_live_status", _fake_update)
    monkeypatch.setattr(local_twin, "_run_script", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        local_twin,
        "_load_json",
        lambda path: {
            "status": "error",
            "summary": "alpaca first-trade executor hit an Alpaca API error",
            "blockers": ["alpaca_api_error"],
            "payload": {"error": 'Alpaca API 422: {"message":"crypto orders not allowed for account"}'},
        } if "alpaca_first_trade/latest.json" in str(path) else None,
    )

    args = Namespace(local_live_venues="alpaca")
    assert local_twin.run_alpaca(args) == 1
    assert written[-1][0] == "alpaca"
    payload = written[-1][1]
    assert payload["last_execution_status"] == "error"
    assert "alpaca_crypto_orders_not_allowed" in payload["blockers"]
    assert payload["feedback_loop_ready"] is False


def test_run_script_inherits_repo_env(monkeypatch, tmp_path: Path) -> None:
    script_path = tmp_path / "scripts" / "fake.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("print('ok')", encoding="utf-8")
    (tmp_path / ".env").write_text("LIGHTSAIL_KEY=/tmp/test-key.pem\n", encoding="utf-8")
    monkeypatch.delenv("LIGHTSAIL_KEY", raising=False)

    monkeypatch.setattr(local_twin, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(local_twin, "PYTHON", "python3")

    captured: dict[str, object] = {}

    class _Result:
        returncode = 0

    def _fake_run(cmd, cwd=None, env=None, timeout=None):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = dict(env or {})
        return _Result()

    monkeypatch.setattr(local_twin.subprocess, "run", _fake_run)

    assert local_twin._run_script("scripts/fake.py") == 0
    assert captured["cwd"] == str(tmp_path)
    assert captured["env"]["LIGHTSAIL_KEY"] == "/tmp/test-key.pem"


def test_run_structural_profit_treats_blocked_report_as_healthy(monkeypatch, tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "structural_alpha" / "local_cycle.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"status":"blocked"}', encoding="utf-8")

    monkeypatch.setattr(local_twin, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(local_twin, "_run_script", lambda *args, **kwargs: 1)

    assert local_twin.run_structural_profit(Namespace()) == 0


def test_run_kalshi_downgrades_live_when_auth_is_placeholder(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("KALSHI_API_KEY_ID", "your-kalshi-key-id-here")
    monkeypatch.setenv("KALSHI_RSA_KEY_PATH", "/tmp/kalshi.pem")

    def _fake_run_script(relpath: str, extra_args=None, env_overrides=None) -> int:
        captured["relpath"] = relpath
        captured["extra_args"] = list(extra_args or [])
        captured["env_overrides"] = dict(env_overrides or {})
        return 0

    monkeypatch.setattr(local_twin, "_run_script", _fake_run_script)

    args = Namespace(local_live_venues="kalshi")
    assert local_twin.run_kalshi(args) == 0
    assert captured["relpath"] == "kalshi/weather_arb.py"
    assert captured["extra_args"] == ["--mode", "paper"]
    assert captured["env_overrides"]["KALSHI_WEATHER_MODE"] == "paper"


def test_run_kalshi_accepts_env_example_key_path(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    key_path = tmp_path / "kalshi" / "kalshi_rsa_private.pem"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text("test", encoding="utf-8")

    monkeypatch.setattr(local_twin, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("KALSHI_API_KEY_ID", "real-kalshi-key")
    monkeypatch.setenv("KALSHI_RSA_KEY_PATH", "kalshi/kalshi_rsa_private.pem")

    def _fake_run_script(relpath: str, extra_args=None, env_overrides=None) -> int:
        captured["relpath"] = relpath
        captured["extra_args"] = list(extra_args or [])
        captured["env_overrides"] = dict(env_overrides or {})
        return 0

    monkeypatch.setattr(local_twin, "_run_script", _fake_run_script)

    args = Namespace(local_live_venues="kalshi")
    assert local_twin.run_kalshi(args) == 0
    assert captured["extra_args"] == ["--mode", "live", "--execute"]


def test_run_kalshi_accepts_inline_private_key_env(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("KALSHI_API_KEY_ID", "real-kalshi-key")
    monkeypatch.setenv(
        "KALSHI_RSA_PRIVATE_KEY",
        "-----BEGIN "
        + "RSA PRIVATE KEY-----\\nabc123\\n-----END "
        + "RSA PRIVATE KEY-----",
    )

    def _fake_run_script(relpath: str, extra_args=None, env_overrides=None) -> int:
        captured["relpath"] = relpath
        captured["extra_args"] = list(extra_args or [])
        captured["env_overrides"] = dict(env_overrides or {})
        return 0

    monkeypatch.setattr(local_twin, "_run_script", _fake_run_script)

    args = Namespace(local_live_venues="kalshi")
    assert local_twin.run_kalshi(args) == 0
    assert captured["extra_args"] == ["--mode", "live", "--execute"]


def test_run_kalshi_marks_nonzero_exit_as_not_feedback_ready(monkeypatch) -> None:
    written: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setenv("KALSHI_API_KEY_ID", "your-kalshi-key-id-here")
    monkeypatch.setenv("KALSHI_RSA_KEY_PATH", "/tmp/kalshi.pem")

    def _fake_update(args, venue, payload):  # type: ignore[no-untyped-def]
        written.append((venue, dict(payload)))

    monkeypatch.setattr(local_twin, "_update_local_live_status", _fake_update)
    monkeypatch.setattr(local_twin, "_run_script", lambda *args, **kwargs: 1)

    args = Namespace(local_live_venues="kalshi")
    assert local_twin.run_kalshi(args) == 1
    assert written[-1][0] == "kalshi"
    payload = written[-1][1]
    assert payload["feedback_loop_ready"] is False
    assert "kalshi_lane_process_failed" in payload["blockers"]


def test_run_polymarket_downgrades_live_when_btc5_gate_blocked(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("POLYMARKET_PK", "pk")
    monkeypatch.setenv("POLYMARKET_FUNDER", "0x123")

    def _fake_run_script(relpath: str, extra_args=None, env_overrides=None) -> int:
        captured["relpath"] = relpath
        captured["extra_args"] = list(extra_args or [])
        captured["env_overrides"] = dict(env_overrides or {})
        return 0

    monkeypatch.setattr(local_twin, "_run_script", _fake_run_script)
    monkeypatch.setattr(
        local_twin,
        "_load_json",
        lambda path: {"launch_posture": "blocked"} if "launch_packet_latest.json" in str(path) else {},
    )

    args = Namespace(local_live_venues="polymarket")
    assert local_twin.run_polymarket(args) == 0
    assert captured["relpath"] == "bot/btc_5min_maker.py"
    assert captured["extra_args"] == ["--run-now", "--paper"]
    assert captured["env_overrides"]["BTC5_PAPER_TRADING"] == "true"


def test_run_feedback_invokes_feedback_compiler(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_run_script(relpath: str, extra_args=None, env_overrides=None) -> int:
        captured["relpath"] = relpath
        captured["extra_args"] = list(extra_args or [])
        captured["env_overrides"] = dict(env_overrides or {})
        return 0

    monkeypatch.setattr(local_twin, "_run_script", _fake_run_script)

    assert local_twin.run_feedback(Namespace()) == 0
    assert captured["relpath"] == "scripts/build_local_feedback_loop.py"
    assert captured["extra_args"] == []


def test_reset_local_live_status_preserves_unscheduled_venues(monkeypatch, tmp_path: Path) -> None:
    status_path = tmp_path / "reports" / "local_live_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(
            {
                "venues": {
                    "alpaca": {"effective_mode": "paper"},
                    "kalshi": {"effective_mode": "live"},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(local_twin, "REPO_ROOT", tmp_path)
    local_twin._reset_local_live_status(Namespace(local_live_venues=""), ["feedback"])

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["venues"]["alpaca"]["effective_mode"] == "paper"
    assert payload["venues"]["kalshi"]["effective_mode"] == "live"
