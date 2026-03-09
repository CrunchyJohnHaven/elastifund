#!/usr/bin/env python3
"""Write the compact remote-cycle status report."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flywheel.status_report import build_remote_cycle_status as build_base_remote_cycle_status


DEFAULT_CONFIG_PATH = Path("config/remote_cycle_status.json")
DEFAULT_MARKDOWN_PATH = Path("reports/remote_cycle_status.md")
DEFAULT_JSON_PATH = Path("reports/remote_cycle_status.json")
DEFAULT_SERVICE_STATUS_PATH = Path("reports/remote_service_status.json")
DEFAULT_ROOT_TEST_STATUS_PATH = Path("reports/root_test_status.json")
DEFAULT_ARB_STATUS_PATH = Path("reports/arb_empirical_snapshot.json")
DEFAULT_WALLET_SCORES_PATH = Path("data/smart_wallets.json")
DEFAULT_WALLET_DB_PATH = Path("data/wallet_scores.db")
DEFAULT_TRADES_DB_PATH = Path("data/jj_trades.db")
DEFAULT_LAUNCH_CHECKLIST_PATH = Path("docs/ops/TRADING_LAUNCH_CHECKLIST.md")
DEFAULT_ROOT_TEST_COMMAND = ("make", "test")


def build_remote_cycle_status(
    root: Path,
    *,
    config_path: Path | None = None,
    service_status_path: Path | None = None,
    root_test_status_path: Path | None = None,
    arb_status_path: Path | None = None,
) -> dict[str, Any]:
    """Build an enriched status payload from synced runtime artifacts."""

    repo_root = root.resolve()
    status = build_base_remote_cycle_status(repo_root, config_path=config_path or DEFAULT_CONFIG_PATH)
    jj_state = _load_json(repo_root / "jj_state.json", default={})

    trade_counts = _load_trade_counts(repo_root)
    status["runtime"]["closed_trades"] = trade_counts["closed_trades"]
    status["runtime"]["trade_db_total_trades"] = trade_counts["total_trades"]
    status["runtime"]["trade_db_source"] = trade_counts["source"]

    service = _load_service_status(
        _resolve_path(repo_root, service_status_path or DEFAULT_SERVICE_STATUS_PATH)
    )
    root_tests = _load_root_test_status(
        _resolve_path(repo_root, root_test_status_path or DEFAULT_ROOT_TEST_STATUS_PATH)
    )
    wallet_flow = _load_wallet_flow_status(repo_root)

    arb_payload = _load_json(
        _resolve_path(repo_root, arb_status_path or DEFAULT_ARB_STATUS_PATH),
        default={},
    )
    a6_gate = _build_a6_gate_status(arb_payload)
    b1_gate = _build_b1_gate_status(arb_payload, jj_state=jj_state)

    launch = _build_launch_status(
        status=status,
        service=service,
        root_tests=root_tests,
        wallet_flow=wallet_flow,
        a6_gate=a6_gate,
        b1_gate=b1_gate,
    )
    runtime_truth = _build_runtime_truth(
        status=status,
        jj_state=jj_state,
        service=service,
        launch=launch,
    )

    status["service"] = service
    status["root_tests"] = root_tests
    status["wallet_flow"] = wallet_flow
    status["structural_gates"] = {"a6": a6_gate, "b1": b1_gate}
    status["launch"] = launch
    status["runtime_truth"] = runtime_truth
    status["deployment_finish"] = _reconcile_deployment_finish(
        status.get("deployment_finish") or {},
        service=service,
        launch=launch,
    )
    status["artifacts"] = {
        "launch_checklist": str(_resolve_path(repo_root, DEFAULT_LAUNCH_CHECKLIST_PATH)),
        "service_status_json": str(
            _resolve_path(repo_root, service_status_path or DEFAULT_SERVICE_STATUS_PATH)
        ),
        "root_test_status_json": str(
            _resolve_path(repo_root, root_test_status_path or DEFAULT_ROOT_TEST_STATUS_PATH)
        ),
        "arb_status_json": str(_resolve_path(repo_root, arb_status_path or DEFAULT_ARB_STATUS_PATH)),
    }
    return status


def render_remote_cycle_status_markdown(status: dict[str, Any]) -> str:
    """Render the remote-cycle status artifact in markdown."""

    capital = status["capital"]
    runtime = status["runtime"]
    flywheel = status["flywheel"]
    cadence = status["data_cadence"]
    forecast = status["velocity_forecast"]
    finish = status["deployment_finish"]
    service = status["service"]
    root_tests = status["root_tests"]
    wallet_flow = status["wallet_flow"]
    gates = status["structural_gates"]
    launch = status["launch"]
    truth = status["runtime_truth"]

    lines = [
        "# Remote Cycle Status",
        "",
        f"- Generated: {status['generated_at']}",
        f"- Service: {service['status']} ({service.get('systemctl_state') or 'unknown'})",
        f"- Root regression suite: {root_tests['status']}",
        f"- Wallet-flow bootstrap: {wallet_flow['status']}",
        f"- A-6 gate: {gates['a6']['status']}",
        f"- B-1 gate: {gates['b1']['status']}",
        f"- Runtime drift detected: {'yes' if truth['drift_detected'] else 'no'}",
        f"- Live launch blocked: {'yes' if launch['live_launch_blocked'] else 'no'}",
        f"- Next operator action: {launch['next_operator_action']}",
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
            f"- Closed trades: {runtime.get('closed_trades', 0)}",
            f"- Open positions: {runtime['open_positions']}",
            f"- Trades today: {runtime['trades_today']}",
            f"- Cycles completed: {runtime['cycles_completed']}",
            f"- Last remote pull: {runtime.get('last_remote_pull_at') or 'unknown'}",
            "",
            "## Service And Validation",
            "",
            f"- Service status: {service['status']}",
            f"- Service detail: {service.get('detail') or 'n/a'}",
            f"- Service checked at: {service.get('checked_at') or 'unknown'}",
            f"- Root regression status: {root_tests['status']}",
            f"- Root regression checked at: {root_tests.get('checked_at') or 'unknown'}",
            f"- Root regression summary: {root_tests.get('summary') or 'n/a'}",
            f"- Wallet-flow readiness: {wallet_flow['status']}",
            f"- Wallet-flow wallet count: {wallet_flow['wallet_count']}",
            f"- Wallet-flow scores file exists: {'yes' if wallet_flow['scores_exists'] else 'no'}",
            f"- Wallet-flow DB exists: {'yes' if wallet_flow['db_exists'] else 'no'}",
            f"- Wallet-flow last updated: {wallet_flow.get('last_updated') or 'unknown'}",
            "",
            "### Wallet-Flow Reasons",
            "",
        ]
    )

    wallet_reasons = wallet_flow.get("reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in wallet_reasons)
    lines.extend(
        [
            "",
            "## Structural Gates",
            "",
            f"- A-6 status: {gates['a6']['status']}",
            f"- A-6 summary: {gates['a6']['summary']}",
            f"- A-6 maker-fill proxy rate: {_format_optional_float(gates['a6'].get('maker_fill_proxy_rate'))}",
            f"- A-6 violation half-life seconds: {_format_optional_float(gates['a6'].get('violation_half_life_seconds'))}",
            f"- A-6 settlement evidence count: {gates['a6'].get('settlement_evidence_count', 0)}",
            "",
            "### A-6 Blocked Reasons",
            "",
        ]
    )

    a6_reasons = gates["a6"].get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in a6_reasons)
    lines.extend(
        [
            "",
            f"- B-1 status: {gates['b1']['status']}",
            f"- B-1 summary: {gates['b1']['summary']}",
            f"- B-1 classification accuracy: {_format_optional_pct(gates['b1'].get('classification_accuracy'))}",
            f"- B-1 false positive rate: {_format_optional_pct(gates['b1'].get('false_positive_rate'))}",
            f"- B-1 violation half-life seconds: {_format_optional_float(gates['b1'].get('violation_half_life_seconds'))}",
            "",
            "### B-1 Blocked Reasons",
            "",
        ]
    )

    b1_reasons = gates["b1"].get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in b1_reasons)
    lines.extend(
        [
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
            "## Launch Path",
            "",
            f"- Fast-flow restart ready: {'yes' if launch['fast_flow_restart_ready'] else 'no'}",
            f"- Live launch blocked: {'yes' if launch['live_launch_blocked'] else 'no'}",
            f"- Next operator action: {launch['next_operator_action']}",
            f"- Launch checklist: {status['artifacts']['launch_checklist']}",
            "",
            "### Launch Blockers",
            "",
        ]
    )

    launch_reasons = launch.get("blocked_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in launch_reasons)
    lines.extend(
        [
            "",
            "## Runtime Truth",
            "",
            f"- Service status: {truth['service_status']}",
            f"- Cycles completed: {truth['cycles_completed']}",
            f"- Launch blocked: {'yes' if truth['launch_blocked'] else 'no'}",
            f"- Drift detected: {'yes' if truth['drift_detected'] else 'no'}",
            f"- Next action: {truth['next_action']}",
            "",
            "### Drift Reasons",
            "",
        ]
    )

    drift_reasons = truth.get("drift_reasons") or ["none"]
    lines.extend(f"- {reason}" for reason in drift_reasons)
    lines.extend(
        [
            "",
            "## Data Cadence",
            "",
            f"- Pull cadence: every {cadence['pull_cadence_minutes']} minutes",
            f"- Full development cycle cadence: every {cadence['full_cycle_cadence_minutes']} minutes",
            f"- Freshness SLA: {cadence['freshness_sla_minutes']} minutes",
            f"- Last remote pull: {cadence.get('last_remote_pull_at') or 'unknown'}",
            f"- Next expected pull: {cadence.get('next_expected_pull_at') or 'unknown'}",
            f"- Current data age: {cadence.get('data_age_minutes') if cadence.get('data_age_minutes') is not None else 'unknown'} minutes",
            f"- Data stale: {'yes' if cadence.get('stale') else 'no'}",
            f"- Next data expectation: {cadence.get('expected_next_data_note') or 'n/a'}",
            "",
            "### Mandatory Extra Pulls",
            "",
        ]
    )

    triggers = cadence.get("manual_pull_triggers") or ["None recorded."]
    lines.extend(f"- {item}" for item in triggers)
    lines.extend(
        [
            "",
            "## Velocity Forecast",
            "",
            f"- Metric: {forecast['metric_name']}",
            f"- Definition: {forecast['definition']}",
            f"- Status: {forecast['status']}",
            f"- Confidence: {forecast['confidence']}",
            f"- Current annualized return run-rate: {forecast['current_annualized_return_pct']:.2f}% ({_format_money(forecast['current_annualized_return_usd'])}/year on tracked capital)",
            (
                f"- Next target annualized return run-rate: "
                f"{forecast['next_target_annualized_return_pct']:.2f}% "
                f"({_format_money(forecast['next_target_annualized_return_usd'])}/year) "
                f"after about {forecast['next_target_after_hours_of_work']:.1f} more engineering hours"
                if forecast.get("next_target_annualized_return_pct") is not None
                and forecast.get("next_target_after_hours_of_work") is not None
                else "- Next target annualized return run-rate: n/a"
            ),
            f"- Basis: {forecast.get('basis') or 'n/a'}",
            "",
            "### Forecast Assumptions",
            "",
        ]
    )

    assumptions = forecast.get("assumptions") or ["None recorded."]
    lines.extend(f"- {item}" for item in assumptions)
    lines.extend(
        [
            "",
            "### Forecast Invalidators",
            "",
        ]
    )
    invalidators = forecast.get("invalidators") or ["None recorded."]
    lines.extend(f"- {item}" for item in invalidators)
    lines.extend(
        [
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
    service_status_path: Path | None = None,
    root_test_status_path: Path | None = None,
    arb_status_path: Path | None = None,
    refresh_root_tests: bool = False,
    root_test_command: Sequence[str] = DEFAULT_ROOT_TEST_COMMAND,
    root_test_timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Write markdown and JSON status artifacts to disk."""

    repo_root = root.resolve()
    root_test_status_target = _resolve_path(
        repo_root,
        root_test_status_path or DEFAULT_ROOT_TEST_STATUS_PATH,
    )
    if refresh_root_tests:
        refresh_root_test_status(
            repo_root,
            status_path=root_test_status_target,
            command=root_test_command,
            timeout_seconds=root_test_timeout_seconds,
        )

    status = build_remote_cycle_status(
        repo_root,
        config_path=config_path or DEFAULT_CONFIG_PATH,
        service_status_path=service_status_path or DEFAULT_SERVICE_STATUS_PATH,
        root_test_status_path=root_test_status_target,
        arb_status_path=arb_status_path or DEFAULT_ARB_STATUS_PATH,
    )

    markdown_target = _resolve_path(repo_root, markdown_path or DEFAULT_MARKDOWN_PATH)
    json_target = _resolve_path(repo_root, json_path or DEFAULT_JSON_PATH)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.parent.mkdir(parents=True, exist_ok=True)

    markdown_target.write_text(render_remote_cycle_status_markdown(status))
    json_target.write_text(json.dumps(status, indent=2, sort_keys=True))

    return {
        "markdown": str(markdown_target),
        "json": str(json_target),
        "status": status,
    }


def refresh_root_test_status(
    root: Path,
    *,
    status_path: Path,
    command: Sequence[str] = DEFAULT_ROOT_TEST_COMMAND,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Run the root regression command and persist a compact status snapshot."""

    checked_at = datetime.now(timezone.utc).isoformat()
    command_text = " ".join(command)
    try:
        result = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        output = "\n".join(
            chunk for chunk in (result.stdout.strip(), result.stderr.strip()) if chunk
        ).strip()
        status = "passing" if result.returncode == 0 else "failing"
        payload = {
            "checked_at": checked_at,
            "command": command_text,
            "status": status,
            "returncode": int(result.returncode),
            "summary": _summarize_command_output(output, success=result.returncode == 0),
            "output_tail": _tail_lines(output, limit=12),
        }
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            chunk
            for chunk in (
                (exc.stdout or "").strip(),
                (exc.stderr or "").strip(),
            )
            if chunk
        ).strip()
        payload = {
            "checked_at": checked_at,
            "command": command_text,
            "status": "timeout",
            "returncode": None,
            "summary": f"Timed out after {timeout_seconds}s while running {command_text}.",
            "output_tail": _tail_lines(output, limit=12),
        }

    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return payload


def _load_trade_counts(root: Path) -> dict[str, Any]:
    db_path = root / DEFAULT_TRADES_DB_PATH
    if not db_path.exists():
        return {"source": "jj_state_fallback", "total_trades": 0, "closed_trades": 0}

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN outcome IS NOT NULL AND outcome != '' THEN 1 ELSE 0 END) AS closed_trades
            FROM trades
            """
        ).fetchone()
    except sqlite3.DatabaseError:
        return {"source": "jj_state_fallback", "total_trades": 0, "closed_trades": 0}
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    total_trades = int(row[0] or 0) if row else 0
    closed_trades = int(row[1] or 0) if row else 0
    return {
        "source": "data/jj_trades.db",
        "total_trades": total_trades,
        "closed_trades": closed_trades,
    }


def _load_service_status(path: Path) -> dict[str, Any]:
    raw = _load_json(path, default={})
    systemctl_state = str(
        raw.get("systemctl_state")
        or raw.get("active_state")
        or raw.get("state")
        or "unknown"
    ).strip()
    status = str(raw.get("status") or "").strip().lower()
    if not status:
        lowered = systemctl_state.lower()
        if lowered == "active":
            status = "running"
        elif lowered in {"inactive", "failed", "deactivating"}:
            status = "stopped"
        else:
            status = "unknown"

    return {
        "status": status,
        "systemctl_state": systemctl_state or "unknown",
        "detail": raw.get("detail") or raw.get("error") or systemctl_state or "unknown",
        "checked_at": raw.get("checked_at"),
        "service_name": raw.get("service_name") or "jj-live.service",
        "host": raw.get("host"),
    }


def _load_root_test_status(path: Path) -> dict[str, Any]:
    raw = _load_json(path, default={})
    return {
        "status": str(raw.get("status") or "unknown"),
        "checked_at": raw.get("checked_at"),
        "command": raw.get("command") or "make test",
        "summary": raw.get("summary") or "Root regression status has not been refreshed yet.",
        "returncode": raw.get("returncode"),
        "output_tail": list(raw.get("output_tail") or []),
    }


def _load_wallet_flow_status(root: Path) -> dict[str, Any]:
    scores_path = root / DEFAULT_WALLET_SCORES_PATH
    db_path = root / DEFAULT_WALLET_DB_PATH

    scores_exists = scores_path.exists()
    db_exists = db_path.exists()
    reasons: list[str] = []
    wallet_count = 0
    last_updated = None

    if not scores_exists:
        reasons.append("missing_data/smart_wallets.json")
    else:
        try:
            payload = json.loads(scores_path.read_text())
            wallet_count = _extract_wallet_count(payload)
            last_updated = _extract_wallet_last_updated(payload)
        except json.JSONDecodeError:
            reasons.append("invalid_data/smart_wallets.json")

    if not db_exists:
        reasons.append("missing_data/wallet_scores.db")

    if wallet_count <= 0:
        reasons.append("no_scored_wallets")

    if last_updated is None:
        candidate_times = [
            _safe_iso_mtime(path)
            for path in (scores_path, db_path)
            if path.exists()
        ]
        last_updated = next((value for value in candidate_times if value), None)

    ready = scores_exists and db_exists and wallet_count > 0
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "reasons": reasons,
        "wallet_count": wallet_count,
        "scores_exists": scores_exists,
        "db_exists": db_exists,
        "last_updated": last_updated,
    }


def _build_a6_gate_status(payload: dict[str, Any]) -> dict[str, Any]:
    gating = payload.get("gating_metrics") or {}
    fill_proxy = payload.get("fill_proxy") or {}
    live_surface = payload.get("live_surface") or {}
    explicit = _extract_lane_payload(payload, lane_key="a6")

    status = _first_nonempty(
        explicit.get("status"),
        payload.get("a6_status"),
    )
    maker_fill_proxy_rate = _float_or_none(
        _first_nonempty(
            explicit.get("maker_fill_proxy_rate"),
            fill_proxy.get("full_fill_proxy_rate"),
        )
    )
    violation_half_life_seconds = _float_or_none(
        _first_nonempty(
            explicit.get("violation_half_life_seconds"),
            gating.get("half_life_seconds"),
            live_surface.get("a6_completed_half_life_seconds"),
            live_surface.get("a6_completed_half_life_p90_seconds"),
        )
    )
    settlement_evidence_count = int(
        _first_nonempty(
            explicit.get("settlement_evidence_count"),
            payload.get("settlement", {}).get("successful_operation_count"),
            payload.get("settlement", {}).get("operation_count"),
            0,
        )
        or 0
    )

    blocked_reasons = list(explicit.get("blocked_reasons") or [])
    if not blocked_reasons:
        if gating.get("fill_probability_gate") != "pass":
            blocked_reasons.append("maker_fill_proxy_not_proven")
        if gating.get("half_life_gate") != "pass":
            blocked_reasons.append("violation_half_life_below_gate")
        if gating.get("settlement_path_gate") != "pass" or settlement_evidence_count <= 0:
            blocked_reasons.append("settlement_path_unproven")
        blocked_reasons.append("public_data_audit_found_0_executable_a6_constructions_below_0.95_gate")

    if not status:
        status = "blocked"
        if gating.get("all_gates_pass"):
            status = "ready_for_shadow"

    summary = explicit.get("summary")
    if not summary:
        summary = (
            "Public-data audits still show 0 executable A-6 constructions below the 0.95 gate; "
            "maker-fill and settlement evidence remain insufficient."
        )

    return {
        "status": status,
        "summary": summary,
        "maker_fill_proxy_rate": maker_fill_proxy_rate,
        "violation_half_life_seconds": violation_half_life_seconds,
        "settlement_evidence_count": settlement_evidence_count,
        "blocked_reasons": blocked_reasons,
        "source": "reports/arb_empirical_snapshot.json",
    }


def _build_b1_gate_status(payload: dict[str, Any], *, jj_state: dict[str, Any]) -> dict[str, Any]:
    b1_payload = payload.get("b1") or {}
    explicit = _extract_lane_payload(payload, lane_key="b1")

    status = _first_nonempty(explicit.get("status"), payload.get("b1_status"))
    classification_accuracy = _float_or_none(
        _first_nonempty(
            explicit.get("classification_accuracy"),
            b1_payload.get("classification_accuracy"),
            (jj_state.get("b1_state") or {}).get("validation_accuracy"),
        )
    )
    false_positive_rate = _float_or_none(
        _first_nonempty(
            explicit.get("false_positive_rate"),
            b1_payload.get("false_positive_rate"),
        )
    )
    violation_half_life_seconds = _float_or_none(
        _first_nonempty(
            explicit.get("violation_half_life_seconds"),
            b1_payload.get("a6_or_b1_half_life_seconds"),
        )
    )

    blocked_reasons = list(explicit.get("blocked_reasons") or [])
    if not blocked_reasons:
        if classification_accuracy is None or classification_accuracy < 0.85:
            blocked_reasons.append("classification_accuracy_below_85pct")
        if false_positive_rate is None:
            blocked_reasons.append("false_positive_rate_unmeasured")
        elif false_positive_rate > 0.05:
            blocked_reasons.append("false_positive_rate_above_5pct")
        blocked_reasons.append(
            "public_data_audit_found_0_deterministic_template_pairs_in_first_1000_allowed_markets"
        )

    if not status:
        status = "blocked"
        if (
            classification_accuracy is not None
            and classification_accuracy >= 0.85
            and false_positive_rate is not None
            and false_positive_rate <= 0.05
        ):
            status = "ready_for_shadow"

    summary = explicit.get("summary")
    if not summary:
        summary = (
            "Public-data audits still show 0 deterministic template pairs in the first 1,000 "
            "allowed markets, so B-1 remains blocked."
        )

    return {
        "status": status,
        "summary": summary,
        "classification_accuracy": classification_accuracy,
        "false_positive_rate": false_positive_rate,
        "violation_half_life_seconds": violation_half_life_seconds,
        "blocked_reasons": blocked_reasons,
        "source": "reports/arb_empirical_snapshot.json",
    }


def _build_launch_status(
    *,
    status: dict[str, Any],
    service: dict[str, Any],
    root_tests: dict[str, Any],
    wallet_flow: dict[str, Any],
    a6_gate: dict[str, Any],
    b1_gate: dict[str, Any],
) -> dict[str, Any]:
    runtime = status["runtime"]
    flywheel = status["flywheel"]

    blocked_checks: list[str] = []
    blocked_reasons: list[str] = []

    if root_tests["status"] != "passing":
        blocked_checks.append("root_tests_not_passing")
        blocked_reasons.append(
            f"Root regression suite is {root_tests['status']}: {root_tests.get('summary') or 'no summary'}"
        )
    if not wallet_flow["ready"]:
        blocked_checks.append("wallet_flow_not_ready")
        blocked_reasons.append(
            "Wallet-flow bootstrap is not ready: "
            + ", ".join(wallet_flow.get("reasons") or ["unknown"])
        )
    if service["status"] != "running":
        blocked_checks.append("service_not_running")
        blocked_reasons.append(
            f"Remote service is {service['status']} ({service.get('systemctl_state') or 'unknown'})."
        )
    if runtime.get("closed_trades", 0) <= 0:
        blocked_checks.append("no_closed_trades")
        blocked_reasons.append("No closed trades are available for calibration yet.")
    if status["capital"]["deployed_capital_usd"] <= 0:
        blocked_checks.append("no_deployed_capital")
        blocked_reasons.append("No capital is currently deployed.")
    if a6_gate["status"] == "blocked":
        blocked_checks.append("a6_gate_blocked")
        blocked_reasons.append(a6_gate["summary"])
    if b1_gate["status"] == "blocked":
        blocked_checks.append("b1_gate_blocked")
        blocked_reasons.append(b1_gate["summary"])
    if flywheel.get("decision") != "deploy":
        blocked_checks.append("flywheel_not_green")
        blocked_reasons.append(
            f"Latest flywheel decision is {flywheel.get('decision') or 'n/a'}."
        )

    fast_flow_restart_ready = (
        root_tests["status"] == "passing"
        and wallet_flow["ready"]
    )

    if root_tests["status"] == "failing":
        next_operator_action = (
            "Merge the root regression repair and rerun `make test` before any restart or deploy."
        )
    elif root_tests["status"] != "passing":
        next_operator_action = (
            "Refresh the root regression status with `make test` before any restart or deploy."
        )
    elif not wallet_flow["ready"]:
        next_operator_action = (
            "Build wallet-flow bootstrap artifacts, confirm readiness, then restart `jj_live` in paper or shadow fast-flow mode."
        )
    elif service["status"] != "running":
        next_operator_action = (
            "Restart `jj_live` in paper or shadow with conservative caps, keep A-6/B-1 blocked, and collect the first closed trades or structural samples."
        )
    elif blocked_checks:
        next_operator_action = (
            "Confirm the running `jj_live` mode is paper or shadow; if it is unintentionally live, stop it. "
            "Keep A-6/B-1 blocked and collect the first closed trades or structural samples."
        )
    elif runtime.get("closed_trades", 0) <= 0:
        next_operator_action = (
            "Keep the fast-flow sleeve running until the first closed trades or structural samples appear."
        )
    else:
        next_operator_action = (
            "Advance wallet-flow and LMSR through paper -> shadow -> micro-live, and require explicit operator approval before any live capital deployment."
        )

    return {
        "fast_flow_restart_ready": fast_flow_restart_ready,
        "live_launch_blocked": bool(blocked_checks),
        "blocked_checks": blocked_checks,
        "blocked_reasons": blocked_reasons,
        "next_operator_action": next_operator_action,
    }


def _build_runtime_truth(
    *,
    status: dict[str, Any],
    jj_state: dict[str, Any],
    service: dict[str, Any],
    launch: dict[str, Any],
) -> dict[str, Any]:
    runtime = status["runtime"]

    cycles_completed = int(runtime.get("cycles_completed") or 0)
    jj_state_cycles_completed = int(jj_state.get("cycles_completed") or 0)
    total_trades = int(runtime.get("total_trades") or 0)
    jj_state_total_trades = int(jj_state.get("total_trades") or 0)
    bankroll_usd = _float_or_none(runtime.get("bankroll_usd"))
    jj_state_bankroll_usd = _float_or_none(jj_state.get("bankroll"))

    jj_state_drift_detected = False
    drift_reasons: list[str] = []

    if cycles_completed != jj_state_cycles_completed:
        jj_state_drift_detected = True
        drift_reasons.append(
            "cycles_completed mismatch between refreshed status and jj_state.json "
            f"({cycles_completed} vs {jj_state_cycles_completed})"
        )
    if total_trades != jj_state_total_trades:
        jj_state_drift_detected = True
        drift_reasons.append(
            "total_trades mismatch between refreshed status and jj_state.json "
            f"({total_trades} vs {jj_state_total_trades})"
        )
    if (
        bankroll_usd is not None
        and jj_state_bankroll_usd is not None
        and abs(bankroll_usd - jj_state_bankroll_usd) > 1e-9
    ):
        jj_state_drift_detected = True
        drift_reasons.append(
            "bankroll mismatch between refreshed status and jj_state.json "
            f"({_format_money(bankroll_usd)} vs {_format_money(jj_state_bankroll_usd)})"
        )

    service_drift_detected = service["status"] == "running" and launch["live_launch_blocked"]
    if service_drift_detected:
        drift_reasons.append(
            "jj-live.service is running while launch posture remains blocked; confirm the remote mode is paper or shadow."
        )

    return {
        "service_status": service["status"],
        "cycles_completed": cycles_completed,
        "launch_blocked": launch["live_launch_blocked"],
        "drift_detected": bool(drift_reasons),
        "service_drift_detected": service_drift_detected,
        "jj_state_drift_detected": jj_state_drift_detected,
        "next_action": launch["next_operator_action"],
        "drift_reasons": drift_reasons,
    }


def _reconcile_deployment_finish(
    finish: dict[str, Any],
    *,
    service: dict[str, Any],
    launch: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(finish)
    blockers = [
        blocker
        for blocker in list(payload.get("blockers") or [])
        if blocker != "jj-live is intentionally stopped while structural alpha integration is completed."
    ]

    if service["status"] == "running" and launch["live_launch_blocked"]:
        blockers.insert(
            0,
            "jj-live.service is currently running on the VPS while launch posture remains blocked; treat this as operational drift until the remote mode is reconciled.",
        )
    elif service["status"] != "running":
        blockers.insert(
            0,
            f"jj-live.service is {service['status']} ({service.get('systemctl_state') or 'unknown'}).",
        )

    payload["blockers"] = _dedupe_preserve_order(blockers)
    return payload


def _extract_lane_payload(payload: dict[str, Any], *, lane_key: str) -> dict[str, Any]:
    candidates = [
        payload.get("lanes", {}).get(lane_key),
        payload.get(f"{lane_key}_gate"),
        payload.get(lane_key) if isinstance(payload.get(lane_key), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and (
            "status" in candidate
            or "blocked_reasons" in candidate
            or "summary" in candidate
        ):
            return candidate
    return {}


def _extract_wallet_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("wallets", "smart_wallets", "scores"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                return len(value)
        if "wallet_count" in payload:
            return int(payload.get("wallet_count") or 0)
    return 0


def _extract_wallet_last_updated(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("last_updated", "updated_at", "generated_at", "timestamp"):
            value = payload.get(key)
            if value:
                return str(value)
    return None


def _summarize_command_output(output: str, *, success: bool) -> str:
    if not output:
        return "Command passed cleanly." if success else "Command failed without output."

    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return "Command passed cleanly." if success else "Command failed without output."


def _tail_lines(output: str, *, limit: int) -> list[str]:
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-limit:]


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _format_money(value: float) -> str:
    return f"${float(value):,.2f}"


def _format_optional_float(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    return f"{float(value):.4f}"


def _format_optional_pct(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    return f"{float(value) * 100.0:.2f}%"


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _safe_iso_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except FileNotFoundError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the remote-cycle status artifact.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--output-md", default=str(DEFAULT_MARKDOWN_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_JSON_PATH))
    parser.add_argument("--service-status-json", default=str(DEFAULT_SERVICE_STATUS_PATH))
    parser.add_argument("--root-test-status-json", default=str(DEFAULT_ROOT_TEST_STATUS_PATH))
    parser.add_argument("--arb-status-json", default=str(DEFAULT_ARB_STATUS_PATH))
    parser.add_argument("--refresh-root-tests", action="store_true")
    parser.add_argument("--root-test-timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    result = write_remote_cycle_status(
        ROOT,
        markdown_path=Path(args.output_md),
        json_path=Path(args.output_json),
        config_path=Path(args.config),
        service_status_path=Path(args.service_status_json),
        root_test_status_path=Path(args.root_test_status_json),
        arb_status_path=Path(args.arb_status_json),
        refresh_root_tests=args.refresh_root_tests,
        root_test_timeout_seconds=args.root_test_timeout_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
