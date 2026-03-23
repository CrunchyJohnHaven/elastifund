from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = REPO_ROOT / "deploy" / "strike-desk.service"
TIMER_PATH = REPO_ROOT / "deploy" / "strike-desk.timer"


def test_strike_desk_service_runs_runner_in_shadow_mode() -> None:
    text = SERVICE_PATH.read_text(encoding="utf-8")
    assert "Description=Strike Desk Execution Orchestrator" in text
    assert "scripts/run_strike_desk.py" in text
    assert "reports/strike_desk" in text
    assert "data/tape/strike_desk.db" in text
    assert "Environment=STRIKE_DESK_LANE_SET=p2_p4" in text
    assert "SyslogIdentifier=strike-desk" in text


def test_strike_desk_timer_is_continuous_but_bounded() -> None:
    text = TIMER_PATH.read_text(encoding="utf-8")
    assert "OnBootSec=10min" in text
    assert "OnUnitActiveSec=5min" in text
    assert "strike-desk.service" in text
