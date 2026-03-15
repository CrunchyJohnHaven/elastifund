from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.write_remote_cycle_status import (  # noqa: E402
    _load_btc5_selected_package_summary,
    _resolve_authoritative_trade_totals,
    build_remote_cycle_status,
    render_remote_cycle_status_markdown,
    write_remote_cycle_status,
)


















































































def _write_base_remote_state(root: Path) -> None:
    _write_json(
        root / "config" / "remote_cycle_status.json",
        {
            "capital_sources": [
                {"account": "Polymarket", "amount_usd": 250.0, "source": "jj_state.json"},
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
            "bankroll": 250.0,
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


def _write_validated_btc5_package(
    root: Path,
    *,
    generated_at: datetime,
    deploy_recommendation: str = "promote",
    confidence_label: str = "high",
    validation_live_filled_rows: int = 8,
    generalization_ratio: float = 0.85,
    promoted_package_selected: bool = True,
    median_arr_delta_pct: float = 25.0,
    selected_active_profile_name: str = "policy_current_live_profile__midday_et",
    selected_best_profile_name: str | None = None,
    frontier_gap_vs_incumbent: float | None = None,
) -> None:
    best_profile_name = selected_best_profile_name or selected_active_profile_name
    active_package = {
        "profile": {
            "name": selected_active_profile_name,
            "max_abs_delta": 0.00015,
            "up_max_buy_price": 0.49,
            "down_max_buy_price": 0.51,
        },
        "session_policy": [
            {
                "name": "midday_et",
                "et_hours": [12, 13],
                "max_abs_delta": 0.00015,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.51,
            }
        ],
    }
    best_package = {
        "profile": {
            "name": best_profile_name,
            "max_abs_delta": 0.00015,
            "up_max_buy_price": 0.49,
            "down_max_buy_price": 0.51,
        },
        "session_policy": [
            {
                "name": "midday_et",
                "et_hours": [12, 13],
                "max_abs_delta": 0.00015,
                "up_max_buy_price": 0.49,
                "down_max_buy_price": 0.51,
            }
        ],
    }
    _write_json(
        root / "reports" / "btc5_autoresearch" / "latest.json",
        {
            "generated_at": generated_at.isoformat(),
            "deploy_recommendation": deploy_recommendation,
            "package_confidence_label": confidence_label,
            "selected_deploy_recommendation": deploy_recommendation,
            "selected_package_confidence_label": confidence_label,
            "validation_live_filled_rows": validation_live_filled_rows,
            "generalization_ratio": generalization_ratio,
            "arr_tracking": {
                "median_arr_delta_pct": median_arr_delta_pct,
            },
            "best_live_package": {
                "median_arr_delta_pct": median_arr_delta_pct,
            },
            "selected_active_runtime_package": active_package,
            "selected_best_runtime_package": best_package,
            "promoted_package_selected": promoted_package_selected,
            "runtime_package_selection": {
                "source": "standard",
                "source_artifact": "reports/btc5_autoresearch/latest.json",
            },
            "frontier_gap_vs_incumbent": frontier_gap_vs_incumbent,
            "capital_stage_recommendation": {
                "runtime_package_loaded": promoted_package_selected,
                "runtime_load_required": deploy_recommendation in {"promote", "shadow_only"} and not promoted_package_selected,
            },
        },
    )


def _write_finance_latest(
    root: Path,
    *,
    generated_at: datetime,
    finance_gate_pass: bool,
    reason: str | None = None,
    status: str | None = None,
    retry_in_minutes: int | None = None,
    finance_state: str | None = None,
    stage_cap: int | None = None,
) -> None:
    live_hold = {}
    if reason is not None or status is not None:
        live_hold = {
            "action_key": "allocate::fund_trading",
            "destination": "polymarket_runtime",
            "reason": reason,
            "status": status or ("pass" if finance_gate_pass else "blocked"),
            "retry_in_minutes": retry_in_minutes,
            "requested_mode": "live_treasury",
            "remediation": "Update treasury policy or keep the action shadowed.",
        }
    _write_json(
        root / "reports" / "finance" / "latest.json",
        {
            "generated_at": generated_at.isoformat(),
            "finance_gate": {
                "pass": finance_gate_pass,
                "reason": reason,
            },
            "last_execute": {
                "generated_at": generated_at.isoformat(),
                "finance_gate_pass": finance_gate_pass,
                "requested_mode": "live_treasury",
                "live_hold": live_hold,
            },
            "capital_expansion_policy": {
                "finance_state": finance_state,
                "stage_cap": stage_cap,
            },
            "rollout_gates": {
                "ready_for_live_treasury": True,
                "snapshot_reconciliation": 1.0,
                "classification_precision": 1.0,
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


def _write_btc5_db(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE window_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start_ts INTEGER NOT NULL UNIQUE,
            window_end_ts INTEGER NOT NULL,
            slug TEXT NOT NULL,
            decision_ts INTEGER NOT NULL,
            direction TEXT,
            open_price REAL,
            current_price REAL,
            delta REAL,
            token_id TEXT,
            best_bid REAL,
            best_ask REAL,
            order_price REAL,
            trade_size_usd REAL,
            shares REAL,
            order_id TEXT,
            order_status TEXT NOT NULL,
            filled INTEGER,
            reason TEXT,
            resolved_side TEXT,
            won INTEGER,
            pnl_usd REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO window_trades (
            window_start_ts,
            window_end_ts,
            slug,
            decision_ts,
            direction,
            order_price,
            trade_size_usd,
            order_status,
            filled,
            pnl_usd,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["window_start_ts"],
                row["window_end_ts"],
                row["slug"],
                row["decision_ts"],
                row.get("direction"),
                row.get("order_price"),
                row.get("trade_size_usd"),
                row["order_status"],
                row.get("filled"),
                row.get("pnl_usd"),
                row["created_at"],
                row["updated_at"],
            )
            for row in rows
        ],
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
