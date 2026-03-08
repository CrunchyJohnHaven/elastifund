"""Generate a compact remote-cycle status artifact from synced bot state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("config/remote_cycle_status.json")
DEFAULT_MARKDOWN_PATH = Path("reports/remote_cycle_status.md")
DEFAULT_JSON_PATH = Path("reports/remote_cycle_status.json")


def build_remote_cycle_status(
    root: Path,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Build a status payload from synced runtime artifacts."""

    repo_root = root.resolve()
    config = _load_json(_resolve_path(repo_root, config_path or DEFAULT_CONFIG_PATH), default={})
    jj_state = _load_json(repo_root / "jj_state.json", default={})
    intel_snapshot = _load_json(repo_root / "data" / "intel_snapshot.json", default={})
    latest_sync = _load_json(repo_root / "reports" / "flywheel" / "latest_sync.json", default={})

    capital_sources = _build_capital_sources(config.get("capital_sources", []), jj_state)
    tracked_capital_usd = _round_money(sum(item["amount_usd"] for item in capital_sources))
    deployed_capital_usd = _round_money(float(jj_state.get("total_deployed") or 0.0))
    undeployed_capital_usd = _round_money(max(tracked_capital_usd - deployed_capital_usd, 0.0))
    deployment_progress_pct = (
        round((deployed_capital_usd / tracked_capital_usd * 100.0), 2)
        if tracked_capital_usd
        else 0.0
    )

    open_positions = jj_state.get("open_positions") or {}
    open_position_count = len(open_positions) if isinstance(open_positions, dict) else int(open_positions)
    latest_decisions = latest_sync.get("decisions") or []
    latest_decision = latest_decisions[0] if latest_decisions else {}
    finish = config.get("deployment_finish") or {}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "capital": {
            "sources": capital_sources,
            "tracked_capital_usd": tracked_capital_usd,
            "deployed_capital_usd": deployed_capital_usd,
            "undeployed_capital_usd": undeployed_capital_usd,
            "deployment_progress_pct": deployment_progress_pct,
        },
        "runtime": {
            "bankroll_usd": _round_money(float(jj_state.get("bankroll") or 0.0)),
            "daily_pnl_usd": _round_money(float(jj_state.get("daily_pnl") or 0.0)),
            "total_pnl_usd": _round_money(float(jj_state.get("total_pnl") or 0.0)),
            "total_trades": int(jj_state.get("total_trades") or 0),
            "trades_today": int(jj_state.get("trades_today") or 0),
            "cycles_completed": int(
                jj_state.get("cycles_completed")
                or intel_snapshot.get("total_cycles")
                or 0
            ),
            "open_positions": open_position_count,
            "last_remote_pull_at": intel_snapshot.get("last_updated"),
            "daily_pnl_date": jj_state.get("daily_pnl_date"),
        },
        "flywheel": {
            "cycle_key": latest_sync.get("cycle_key"),
            "evaluated": int(latest_sync.get("evaluated") or 0),
            "decision": latest_decision.get("decision"),
            "reason_code": latest_decision.get("reason_code"),
            "notes": latest_decision.get("notes"),
            "artifacts": latest_sync.get("artifacts") or {},
        },
        "deployment_finish": {
            "status": finish.get("status", "unknown"),
            "eta": finish.get("eta", "TBD"),
            "blockers": list(finish.get("blockers") or []),
            "exit_criteria": list(finish.get("exit_criteria") or []),
        },
    }


def render_remote_cycle_status_markdown(status: dict[str, Any]) -> str:
    """Render the remote-cycle status artifact in markdown."""

    capital = status["capital"]
    runtime = status["runtime"]
    flywheel = status["flywheel"]
    finish = status["deployment_finish"]

    lines = [
        "# Remote Cycle Status",
        "",
        f"- Generated: {status['generated_at']}",
        f"- Last remote pull: {runtime.get('last_remote_pull_at') or 'unknown'}",
        "",
        "## Capital",
        "",
        "| Account | Tracked USD | Source |",
        "|---------|-------------|--------|",
    ]

    for item in capital["sources"]:
        lines.append(
            f"| {item['account']} | {_format_money(item['amount_usd'])} | {item['source']} |"
        )

    lines.extend(
        [
            "",
            f"- Total tracked capital: {_format_money(capital['tracked_capital_usd'])}",
            f"- Capital currently deployed: {_format_money(capital['deployed_capital_usd'])}",
            f"- Capital still undeployed: {_format_money(capital['undeployed_capital_usd'])}",
            f"- Deployment progress: {capital['deployment_progress_pct']:.2f}%",
            "",
            "## Runtime",
            "",
            f"- Bankroll: {_format_money(runtime['bankroll_usd'])}",
            f"- Daily PnL: {_format_money(runtime['daily_pnl_usd'])} ({runtime.get('daily_pnl_date') or 'n/a'})",
            f"- Total PnL: {_format_money(runtime['total_pnl_usd'])}",
            f"- Total trades: {runtime['total_trades']}",
            f"- Trades today: {runtime['trades_today']}",
            f"- Open positions: {runtime['open_positions']}",
            f"- Cycles completed: {runtime['cycles_completed']}",
            "",
            "## Flywheel",
            "",
            f"- Latest cycle: {flywheel.get('cycle_key') or 'n/a'}",
            f"- Deploy decision: {flywheel.get('decision') or 'n/a'}",
            f"- Reason: {flywheel.get('reason_code') or 'n/a'}",
            f"- Notes: {flywheel.get('notes') or 'n/a'}",
            f"- Summary artifact: {(flywheel.get('artifacts') or {}).get('summary_md', 'n/a')}",
            f"- Scorecard artifact: {(flywheel.get('artifacts') or {}).get('scorecard', 'n/a')}",
            "",
            "## Deployment Finish",
            "",
            f"- Status: {finish['status']}",
            f"- ETA: {finish['eta']}",
            "",
            "### Current Blockers",
            "",
        ]
    )

    blockers = finish.get("blockers") or ["None recorded."]
    lines.extend(f"- {item}" for item in blockers)
    lines.extend(
        [
            "",
            "### Exit Criteria",
            "",
        ]
    )
    exit_criteria = finish.get("exit_criteria") or ["None recorded."]
    lines.extend(f"- {item}" for item in exit_criteria)
    lines.append("")
    return "\n".join(lines)


def write_remote_cycle_status(
    root: Path,
    *,
    markdown_path: Path | None = None,
    json_path: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, str]:
    """Write markdown and JSON status artifacts to disk."""

    repo_root = root.resolve()
    status = build_remote_cycle_status(repo_root, config_path=config_path)

    markdown_target = _resolve_path(repo_root, markdown_path or DEFAULT_MARKDOWN_PATH)
    json_target = _resolve_path(repo_root, json_path or DEFAULT_JSON_PATH)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.parent.mkdir(parents=True, exist_ok=True)

    markdown_target.write_text(render_remote_cycle_status_markdown(status))
    json_target.write_text(json.dumps(status, indent=2, sort_keys=True))

    return {
        "markdown": str(markdown_target),
        "json": str(json_target),
    }


def _build_capital_sources(rows: list[dict[str, Any]], jj_state: dict[str, Any]) -> list[dict[str, Any]]:
    live_polymarket = _round_money(float(jj_state.get("bankroll") or 0.0))

    if not rows:
        if live_polymarket:
            return [
                {
                    "account": "Polymarket",
                    "amount_usd": live_polymarket,
                    "source": "jj_state.json",
                }
            ]
        return []

    sources: list[dict[str, Any]] = []
    for row in rows:
        account = str(row.get("account") or "Unknown")
        amount = _round_money(float(row.get("amount_usd") or 0.0))
        source = str(row.get("source") or "config")
        if account.lower() == "polymarket" and live_polymarket:
            amount = live_polymarket
            source = "jj_state.json"
        sources.append(
            {
                "account": account,
                "amount_usd": amount,
                "source": source,
            }
        )
    return sources


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _format_money(value: float) -> str:
    return f"${float(value):,.2f}"
