from __future__ import annotations

import json
from pathlib import Path

from flywheel.status_report import (
    build_remote_cycle_status,
    render_remote_cycle_status_markdown,
    write_remote_cycle_status,
)


def test_build_remote_cycle_status_uses_live_polymarket_balance(tmp_path: Path):
    _write_json(
        tmp_path / "config" / "remote_cycle_status.json",
        {
            "capital_sources": [
                {"account": "Polymarket", "amount_usd": 10.0, "source": "config"},
                {"account": "Kalshi", "amount_usd": 100.0, "source": "manual"},
            ],
            "pull_policy": {
                "pull_cadence_minutes": 30,
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
        tmp_path / "jj_state.json",
        {
            "bankroll": 247.51,
            "total_deployed": 12.5,
            "daily_pnl": 0.0,
            "total_pnl": 1.25,
            "daily_pnl_date": "2026-03-08",
            "trades_today": 0,
            "total_trades": 3,
            "open_positions": {"abc": {"size": 1}},
            "cycles_completed": 109,
        },
    )
    _write_json(
        tmp_path / "data" / "intel_snapshot.json",
        {
            "last_updated": "2026-03-08T08:17:45+00:00",
            "total_cycles": 109,
        },
    )
    _write_json(
        tmp_path / "reports" / "flywheel" / "latest_sync.json",
        {
            "cycle_key": "live-flywheel-20260308T080000Z",
            "evaluated": 1,
            "decisions": [
                {
                    "decision": "hold",
                    "reason_code": "insufficient_evidence",
                    "notes": "Collect more closed trades before promoting.",
                }
            ],
            "artifacts": {
                "summary_md": "reports/flywheel/live-flywheel-20260308T080000Z/summary.md",
                "scorecard": "reports/flywheel/live-flywheel-20260308T080000Z/scorecard.json",
            },
        },
    )

    status = build_remote_cycle_status(tmp_path)

    assert status["capital"]["tracked_capital_usd"] == 347.51
    assert status["capital"]["deployed_capital_usd"] == 12.5
    assert status["capital"]["undeployed_capital_usd"] == 335.01
    assert status["capital"]["sources"][0]["source"] == "jj_state.json"
    assert status["runtime"]["open_positions"] == 1
    assert status["flywheel"]["decision"] == "hold"
    assert status["data_cadence"]["next_expected_pull_at"] == "2026-03-08T08:47:45+00:00"
    assert status["velocity_forecast"]["next_target_annualized_return_usd"] == 34.75
    assert status["deployment_finish"]["eta"] == "TBD"


def test_write_remote_cycle_status_writes_markdown_and_json(tmp_path: Path):
    _write_json(
        tmp_path / "config" / "remote_cycle_status.json",
        {
            "capital_sources": [
                {"account": "Polymarket", "amount_usd": 247.51, "source": "jj_state.json"},
            ],
            "pull_policy": {
                "pull_cadence_minutes": 30,
            },
            "velocity_forecast": {
                "current_annualized_return_pct": 0.0,
                "next_target_annualized_return_pct": 10.0,
                "next_target_after_hours_of_work": 3.0,
            },
            "deployment_finish": {
                "status": "blocked",
                "eta": "TBD",
                "blockers": ["jj-live stopped."],
                "exit_criteria": ["Resume runtime."],
            },
        },
    )
    _write_json(
        tmp_path / "jj_state.json",
        {
            "bankroll": 247.51,
            "total_deployed": 0.0,
            "daily_pnl": 0.0,
            "total_pnl": 0.0,
            "daily_pnl_date": "2026-03-08",
            "trades_today": 0,
            "total_trades": 0,
            "open_positions": {},
            "cycles_completed": 109,
        },
    )

    written = write_remote_cycle_status(tmp_path)

    markdown_path = Path(written["markdown"])
    json_path = Path(written["json"])
    markdown = markdown_path.read_text()
    payload = json.loads(json_path.read_text())

    assert markdown_path.exists()
    assert json_path.exists()
    assert "Capital currently deployed: $0.00" in markdown
    assert "ETA: TBD" in markdown
    assert "Pull cadence: every 30 minutes" in markdown
    assert payload["capital"]["tracked_capital_usd"] == 247.51
    assert payload["deployment_finish"]["blockers"] == ["jj-live stopped."]


def test_render_remote_cycle_status_markdown_includes_latest_decision():
    markdown = render_remote_cycle_status_markdown(
        {
            "generated_at": "2026-03-08T09:00:00+00:00",
            "capital": {
                "sources": [{"account": "Polymarket", "amount_usd": 247.51, "source": "jj_state.json"}],
                "tracked_capital_usd": 247.51,
                "deployed_capital_usd": 5.0,
                "undeployed_capital_usd": 242.51,
                "deployment_progress_pct": 2.02,
            },
            "runtime": {
                "bankroll_usd": 247.51,
                "daily_pnl_usd": 0.0,
                "total_pnl_usd": 0.0,
                "total_trades": 0,
                "trades_today": 0,
                "cycles_completed": 109,
                "open_positions": 0,
                "last_remote_pull_at": "2026-03-08T08:17:45+00:00",
                "daily_pnl_date": "2026-03-08",
            },
            "flywheel": {
                "cycle_key": "live-flywheel-20260308T080000Z",
                "evaluated": 1,
                "decision": "hold",
                "reason_code": "insufficient_evidence",
                "notes": "Collect more closed trades before promoting.",
                "artifacts": {
                    "summary_md": "reports/flywheel/latest.md",
                    "scorecard": "reports/flywheel/latest.json",
                },
            },
            "data_cadence": {
                "pull_cadence_minutes": 30,
                "full_cycle_cadence_minutes": 60,
                "freshness_sla_minutes": 45,
                "last_remote_pull_at": "2026-03-08T08:17:45+00:00",
                "next_expected_pull_at": "2026-03-08T08:47:45+00:00",
                "data_age_minutes": 12.0,
                "stale": False,
                "expected_next_data_note": "Next pull should bring the next synced dataset.",
                "manual_pull_triggers": ["Immediately before any deploy."],
            },
            "velocity_forecast": {
                "metric_name": "annualized_return_run_rate_pct",
                "definition": "Operator forecast.",
                "status": "speculative",
                "confidence": "low",
                "current_annualized_return_pct": 0.0,
                "current_annualized_return_usd": 0.0,
                "next_target_annualized_return_pct": 10.0,
                "next_target_annualized_return_usd": 24.75,
                "next_target_after_hours_of_work": 3.0,
                "basis": "Best guess after one more focused session.",
                "assumptions": ["Runtime resumes."],
                "invalidators": ["Runtime remains paused."],
            },
            "deployment_finish": {
                "status": "blocked",
                "eta": "TBD",
                "blockers": ["Need more evidence."],
                "exit_criteria": ["Resume runtime."],
            },
        }
    )

    assert "Deploy decision: hold" in markdown
    assert "Reason: insufficient_evidence" in markdown
    assert "Deployment progress: 2.02%" in markdown
    assert "Next expected pull: 2026-03-08T08:47:45+00:00" in markdown
    assert "Next target annualized return run-rate: 10.00% ($24.75/year) after about 3.0 more engineering hours" in markdown


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
