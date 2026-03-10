from __future__ import annotations

import json
from pathlib import Path

from scripts import btc5_autoresearch_autopush as autopush


def _write_cycle_payload(
    path: Path,
    *,
    session_policy: list[dict] | None = None,
    selected_session_policy: list[dict] | None = None,
    promoted_package_selected: bool = False,
) -> None:
    payload: dict[str, object] = {
        "generated_at": "2026-03-09T20:00:00Z",
        "decision": {
            "action": "promote",
            "reason": "promotion_thresholds_met",
            "median_arr_delta_pct": 10.0,
        },
        "best_candidate": {
            "profile": {
                "name": "grid_candidate",
                "max_abs_delta": 0.0001,
                "up_max_buy_price": 0.48,
                "down_max_buy_price": 0.49,
            },
            "base_profile": {
                "name": "grid_candidate",
                "max_abs_delta": 0.0001,
                "up_max_buy_price": 0.48,
                "down_max_buy_price": 0.49,
            },
            "session_overrides": [],
        },
        "best_runtime_package": {
            "profile": {"name": "grid_candidate"},
            "session_policy": session_policy or [],
        },
        "capital_scale_recommendation": {
            "promoted_package_selected": promoted_package_selected,
        },
    }
    if selected_session_policy is not None:
        payload["selected_best_runtime_package"] = {
            "profile": {"name": "selected_grid_candidate"},
            "session_policy": selected_session_policy,
        }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_apply_session_policy_line_adds_and_removes() -> None:
    text = "BTC5_MAX_ABS_DELTA=0.0001\nBTC5_SESSION_POLICY_JSON=[{\"name\":\"stale\"}]\n"
    added = autopush._apply_session_policy_line(
        text,
        [{"name": "open_et", "et_hours": [9], "max_abs_delta": 0.0001}],
    )
    assert "BTC5_SESSION_POLICY_JSON=" in added
    assert '"name":"open_et"' in added

    removed = autopush._apply_session_policy_line(added, [])
    assert "BTC5_SESSION_POLICY_JSON=" not in removed


def test_autopush_noop_on_dirty_worktree(tmp_path: Path, monkeypatch) -> None:
    cycle_json = tmp_path / "latest.json"
    base_env = tmp_path / "btc5_strategy.env"
    _write_cycle_payload(cycle_json, session_policy=[{"name": "open_et", "et_hours": [9]}])
    base_env.write_text("ORIGINAL=1\n", encoding="utf-8")

    monkeypatch.setattr(autopush, "_dirty_paths", lambda: ["bot/jj_live.py"])
    monkeypatch.setattr(
        autopush,
        "_run",
        lambda cmd: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    monkeypatch.setattr(
        autopush,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "cycle_json": cycle_json,
                "base_env": base_env,
                "branch": "main",
                "allow_path": [],
            },
        )(),
    )

    rc = autopush.main()
    assert rc == 0
    assert base_env.read_text(encoding="utf-8") == "ORIGINAL=1\n"


def test_autopush_writes_session_policy_when_promoted(tmp_path: Path, monkeypatch, capsys) -> None:
    cycle_json = tmp_path / "latest.json"
    base_env = tmp_path / "btc5_strategy.env"
    _write_cycle_payload(cycle_json, session_policy=[{"name": "open_et", "et_hours": [9]}])

    calls: list[list[str]] = []

    def fake_run(cmd: list[str]):
        calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(autopush, "_dirty_paths", lambda: [])
    monkeypatch.setattr(autopush, "_run", fake_run)
    monkeypatch.setattr(
        autopush,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "cycle_json": cycle_json,
                "base_env": base_env,
                "branch": "main",
                "allow_path": [str(base_env.relative_to(tmp_path))],
            },
        )(),
    )
    monkeypatch.setattr(autopush, "DEFAULT_ALLOWED_PATHS", [str(base_env.relative_to(tmp_path))])
    monkeypatch.setattr(autopush, "ROOT", tmp_path)

    rc = autopush.main()
    assert rc == 0
    text = base_env.read_text(encoding="utf-8")
    assert "BTC5_SESSION_POLICY_JSON=" in text
    assert '"name":"open_et"' in text
    assert any(cmd[:2] == ["git", "add"] for cmd in calls)
    output = capsys.readouterr().out
    assert '"promoted_package_already_loaded": false' in output


def test_autopush_prefers_selected_runtime_package_policy(tmp_path: Path, monkeypatch, capsys) -> None:
    cycle_json = tmp_path / "latest.json"
    base_env = tmp_path / "btc5_strategy.env"
    _write_cycle_payload(
        cycle_json,
        session_policy=[{"name": "fallback_policy", "et_hours": [10]}],
        selected_session_policy=[{"name": "selected_policy", "et_hours": [9]}],
        promoted_package_selected=True,
    )

    monkeypatch.setattr(autopush, "_dirty_paths", lambda: [])
    monkeypatch.setattr(
        autopush,
        "_run",
        lambda cmd: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    monkeypatch.setattr(
        autopush,
        "parse_args",
        lambda: type(
            "Args",
            (),
            {
                "cycle_json": cycle_json,
                "base_env": base_env,
                "branch": "main",
                "allow_path": [str(base_env.relative_to(tmp_path))],
            },
        )(),
    )
    monkeypatch.setattr(autopush, "DEFAULT_ALLOWED_PATHS", [str(base_env.relative_to(tmp_path))])
    monkeypatch.setattr(autopush, "ROOT", tmp_path)

    rc = autopush.main()
    assert rc == 0
    text = base_env.read_text(encoding="utf-8")
    assert '"name":"selected_policy"' in text
    assert '"name":"fallback_policy"' not in text
    output = capsys.readouterr().out
    assert '"promoted_package_already_loaded": true' in output
