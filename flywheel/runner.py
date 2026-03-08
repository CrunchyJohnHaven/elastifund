"""Sequential flywheel control-plane runner."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from data_layer import crud

from .intelligence import FindingSpec, TaskSpec, lesson_for_reason, record_finding_with_task
from .policy import PolicyOutcome, evaluate_snapshot
from .resilience import monitor_snapshot_activity
from .reporting import build_scorecard, write_artifacts

DEFAULT_ARTIFACT_ROOT = Path("reports") / "flywheel"


def load_payload(path: str | Path) -> dict[str, Any]:
    """Load one cycle input payload from JSON."""

    return json.loads(Path(path).read_text())


def run_cycle(
    session: Session,
    payload: dict[str, Any],
    *,
    artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
) -> dict[str, Any]:
    """Run one sequential flywheel cycle end-to-end."""

    cycle_key = payload.get("cycle_key") or _cycle_key()
    artifact_dir = Path(artifact_root) / cycle_key
    cycle = crud.create_flywheel_cycle(
        session,
        cycle_key=cycle_key,
        status="running",
        artifacts_path=str(artifact_dir),
    )

    records: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    task_rows: list[dict[str, Any]] = []
    finding_rows: list[dict[str, Any]] = []
    guardrail_rows: list[dict[str, Any]] = []

    for strategy_payload in payload.get("strategies", []):
        version = crud.get_or_create_strategy_version(
            session,
            strategy_key=strategy_payload["strategy_key"],
            version_label=strategy_payload["version_label"],
            lane=strategy_payload["lane"],
            artifact_uri=strategy_payload.get("artifact_uri"),
            git_sha=strategy_payload.get("git_sha"),
            config=strategy_payload.get("config"),
            status=strategy_payload.get("status", "candidate"),
        )

        for deployment_payload in strategy_payload.get("deployments", []):
            deployment = crud.get_or_create_deployment(
                session,
                strategy_version_id=version.id,
                environment=deployment_payload["environment"],
                capital_cap_usd=float(deployment_payload.get("capital_cap_usd", 0.0)),
                status=deployment_payload.get("status", "active"),
                notes=deployment_payload.get("notes"),
                metrics=deployment_payload.get("metrics"),
            )

            snapshot_payload = deployment_payload.get("snapshot")
            if snapshot_payload is None:
                continue

            snapshot = crud.create_daily_snapshot(
                session,
                strategy_version_id=version.id,
                deployment_id=deployment.id,
                environment=deployment.environment,
                snapshot_date=snapshot_payload["snapshot_date"],
                starting_bankroll=float(snapshot_payload["starting_bankroll"]),
                ending_bankroll=float(snapshot_payload["ending_bankroll"]),
                realized_pnl=float(snapshot_payload.get("realized_pnl", 0.0)),
                unrealized_pnl=float(snapshot_payload.get("unrealized_pnl", 0.0)),
                open_positions=int(snapshot_payload.get("open_positions", 0)),
                closed_trades=int(snapshot_payload.get("closed_trades", 0)),
                win_rate=_float_or_none(snapshot_payload.get("win_rate")),
                fill_rate=_float_or_none(snapshot_payload.get("fill_rate")),
                avg_slippage_bps=_float_or_none(snapshot_payload.get("avg_slippage_bps")),
                rolling_brier=_float_or_none(snapshot_payload.get("rolling_brier")),
                rolling_ece=_float_or_none(snapshot_payload.get("rolling_ece")),
                max_drawdown_pct=float(snapshot_payload.get("max_drawdown_pct", 0.0)),
                kill_events=int(snapshot_payload.get("kill_events", 0)),
                metrics=snapshot_payload.get("metrics"),
            )

            anomaly = monitor_snapshot_activity(
                session,
                strategy_key=version.strategy_key,
                version_label=version.version_label,
                lane=version.lane,
                environment=deployment.environment,
                deployment_id=deployment.id,
                snapshot=snapshot,
            )

            outcome = evaluate_snapshot(snapshot)
            decision = crud.create_promotion_decision(
                session,
                strategy_version_id=version.id,
                deployment_id=deployment.id,
                from_stage=outcome.from_stage,
                to_stage=outcome.to_stage,
                decision=outcome.decision,
                reason_code=outcome.reason_code,
                metrics=outcome.metrics,
                notes=outcome.notes,
            )

            if outcome.decision in {"promote", "demote"} and outcome.to_stage != outcome.from_stage:
                _close_current_deployment(session, deployment.id, outcome.decision)
                _ensure_target_deployment(
                    session,
                    strategy_version_id=version.id,
                    environment=outcome.to_stage,
                    capital_cap_usd=_promotion_cap(float(deployment.capital_cap_usd), outcome.to_stage),
                    notes=f"Auto-created by cycle {cycle_key} from {outcome.from_stage}",
                )
            elif outcome.decision == "kill":
                _close_current_deployment(session, deployment.id, "killed")

            finding = _build_finding(
                cycle_id=cycle.id,
                strategy_version_id=version.id,
                strategy_key=version.strategy_key,
                version_label=version.version_label,
                lane=version.lane,
                environment=deployment.environment,
                cycle_key=cycle_key,
                outcome=outcome,
            )
            task = _build_task(
                cycle_id=cycle.id,
                strategy_version_id=version.id,
                strategy_key=version.strategy_key,
                version_label=version.version_label,
                lane=version.lane,
                environment=deployment.environment,
                cycle_key=cycle_key,
                outcome=outcome,
            )
            finding_row, _ = record_finding_with_task(
                session,
                finding=FindingSpec(**finding["db"]),
                task=TaskSpec(**task["db"]),
            )

            if anomaly.triggered:
                guardrail_finding = _build_guardrail_finding(
                    cycle_id=cycle.id,
                    strategy_version_id=version.id,
                    strategy_key=version.strategy_key,
                    version_label=version.version_label,
                    lane=version.lane,
                    environment=deployment.environment,
                    cycle_key=cycle_key,
                    anomaly=anomaly,
                )
                guardrail = _build_guardrail_task(
                    cycle_id=cycle.id,
                    strategy_version_id=version.id,
                    strategy_key=version.strategy_key,
                    version_label=version.version_label,
                    lane=version.lane,
                    environment=deployment.environment,
                    cycle_key=cycle_key,
                    anomaly=anomaly,
                )
                record_finding_with_task(
                    session,
                    finding=FindingSpec(**guardrail_finding["db"]),
                    task=TaskSpec(**guardrail["db"]),
                )
                finding_rows.append(guardrail_finding["artifact"])
                task_rows.append(guardrail["artifact"])
                guardrail_rows.append(
                    {
                        "strategy_key": version.strategy_key,
                        "version_label": version.version_label,
                        "metric": anomaly.metric,
                        "z_score": anomaly.z_score,
                        "reason": anomaly.reason,
                    }
                )

            record = {
                "strategy_key": version.strategy_key,
                "version_label": version.version_label,
                "lane": version.lane,
                "environment": deployment.environment,
                "capital_cap_usd": float(deployment.capital_cap_usd),
                "realized_pnl": snapshot.realized_pnl,
                "closed_trades": snapshot.closed_trades,
                "open_positions": snapshot.open_positions,
                "kill_events": snapshot.kill_events,
                "decision": outcome.decision,
                "reason_code": outcome.reason_code,
            }
            records.append(record)
            decision_rows.append(
                {
                    "id": decision.id,
                    "strategy_key": version.strategy_key,
                    "version_label": version.version_label,
                    "decision": outcome.decision,
                    "from_stage": outcome.from_stage,
                    "to_stage": outcome.to_stage,
                    "reason_code": outcome.reason_code,
                    "notes": outcome.notes,
                    "priority": outcome.priority,
                }
            )
            finding_rows.append(
                {
                    **finding["artifact"],
                    "finding_id": None if finding_row is None else finding_row.id,
                }
            )
            task_rows.append(task["artifact"])

    scorecard = build_scorecard(records, decision_rows, task_rows, finding_rows)
    written_paths = write_artifacts(artifact_dir, scorecard, decision_rows, task_rows, finding_rows)

    crud.finish_flywheel_cycle(
        session,
        cycle.id,
        status="completed",
        summary=f"Evaluated {len(records)} deployments and generated {len(task_rows)} tasks.",
        artifacts_path=str(artifact_dir),
    )
    session.commit()

    return {
        "cycle_key": cycle_key,
        "evaluated": len(records),
        "decisions": decision_rows,
        "tasks": task_rows,
        "findings": finding_rows,
        "guardrails": guardrail_rows,
        "artifacts": written_paths,
        "scorecard": scorecard,
    }


def build_scorecard_from_db(session: Session, environment: str | None = None) -> dict[str, Any]:
    """Build a scorecard from the latest snapshots already in the database."""

    records: list[dict[str, Any]] = []
    for deployment in crud.list_deployments(session, environment=environment, limit=500):
        snapshot = crud.get_latest_snapshot(session, deployment_id=deployment.id)
        if snapshot is None:
            continue
        version = next(
            (
                row
                for row in crud.list_strategy_versions(session, limit=500)
                if row.id == deployment.strategy_version_id
            ),
            None,
        )
        if version is None:
            continue
        records.append(
            {
                "strategy_key": version.strategy_key,
                "version_label": version.version_label,
                "lane": version.lane,
                "environment": snapshot.environment,
                "capital_cap_usd": float(deployment.capital_cap_usd),
                "realized_pnl": snapshot.realized_pnl,
                "closed_trades": snapshot.closed_trades,
                "open_positions": snapshot.open_positions,
                "kill_events": snapshot.kill_events,
            }
        )
    findings = [
        {
            "finding_type": row.finding_type,
            "source_kind": row.source_kind,
        }
        for row in crud.list_flywheel_findings(session, environment=environment, limit=500)
    ]
    return build_scorecard(records, [], [], findings)


def _close_current_deployment(session: Session, deployment_id: int, status: str) -> None:
    if status == "promote":
        target_status = "promoted"
    elif status == "demote":
        target_status = "demoted"
    else:
        target_status = status
    crud.end_deployment(session, deployment_id, status=target_status)


def _ensure_target_deployment(
    session: Session,
    *,
    strategy_version_id: int,
    environment: str,
    capital_cap_usd: float,
    notes: str,
) -> None:
    existing = [
        row
        for row in crud.list_deployments(
            session,
            environment=environment,
            strategy_version_id=strategy_version_id,
            limit=20,
        )
        if row.status in {"active", "planned"}
    ]
    if existing:
        return
    crud.create_deployment(
        session,
        strategy_version_id=strategy_version_id,
        environment=environment,
        capital_cap_usd=capital_cap_usd,
        status="planned",
        notes=notes,
    )


def _promotion_cap(current_cap: float, target_stage: str) -> float:
    if target_stage == "micro_live":
        return min(current_cap or 25.0, 25.0)
    if target_stage == "scaled_live":
        return max(current_cap, 50.0)
    return current_cap


def _build_task(
    *,
    cycle_id: int,
    strategy_version_id: int,
    strategy_key: str,
    version_label: str,
    lane: str,
    environment: str,
    cycle_key: str,
    outcome: PolicyOutcome,
) -> dict[str, Any]:
    title = f"{outcome.decision.upper()}: {strategy_key}:{version_label} {outcome.from_stage} -> {outcome.to_stage}"
    details = outcome.notes
    action = _task_action(outcome)
    db_payload = {
        "cycle_id": cycle_id,
        "strategy_version_id": strategy_version_id,
        "action": action,
        "title": title,
        "details": details,
        "priority": outcome.priority,
        "status": "open",
        "lane": lane,
        "environment": environment,
        "source_kind": "policy_cycle",
        "source_ref": f"cycle:{cycle_key}",
        "metadata": {
            "decision": outcome.decision,
            "reason_code": outcome.reason_code,
            "from_stage": outcome.from_stage,
            "to_stage": outcome.to_stage,
        },
    }
    artifact_payload = {
        "action": action,
        "title": title,
        "details": details,
        "priority": outcome.priority,
        "lane": lane,
        "environment": environment,
        "source_kind": "policy_cycle",
    }
    return {"db": db_payload, "artifact": artifact_payload}


def _build_finding(
    *,
    cycle_id: int,
    strategy_version_id: int,
    strategy_key: str,
    version_label: str,
    lane: str,
    environment: str,
    cycle_key: str,
    outcome: PolicyOutcome,
) -> dict[str, Any]:
    finding_type = _finding_type(outcome)
    title = f"{strategy_key}:{version_label} {outcome.decision} ({outcome.reason_code})"
    lesson = lesson_for_reason(outcome.reason_code, default=outcome.notes)
    db_payload = {
        "finding_key": (
            f"policy:{cycle_key}:{strategy_key}:{version_label}:{environment}:"
            f"{outcome.metrics.get('snapshot_date')}:"
            f"{outcome.decision}:{outcome.reason_code}"
        ),
        "cycle_id": cycle_id,
        "strategy_version_id": strategy_version_id,
        "lane": lane,
        "environment": environment,
        "source_kind": "policy_cycle",
        "finding_type": finding_type,
        "title": title,
        "summary": outcome.notes,
        "lesson": lesson,
        "evidence": {
            "decision": outcome.decision,
            "reason_code": outcome.reason_code,
            "from_stage": outcome.from_stage,
            "to_stage": outcome.to_stage,
            "metrics": outcome.metrics,
        },
        "priority": outcome.priority,
        "confidence": None,
        "status": "open",
    }
    artifact_payload = {
        "finding_type": finding_type,
        "source_kind": "policy_cycle",
        "title": title,
        "summary": outcome.notes,
        "lesson": lesson,
        "priority": outcome.priority,
        "lane": lane,
        "environment": environment,
    }
    return {"db": db_payload, "artifact": artifact_payload}


def _build_guardrail_task(
    *,
    cycle_id: int,
    strategy_version_id: int,
    strategy_key: str,
    version_label: str,
    lane: str,
    environment: str,
    cycle_key: str,
    anomaly: Any,
) -> dict[str, Any]:
    title = f"PAUSE: {strategy_key}:{version_label} activity anomaly"
    details = anomaly.reason
    db_payload = {
        "cycle_id": cycle_id,
        "strategy_version_id": strategy_version_id,
        "action": "kill",
        "title": title,
        "details": details,
        "priority": 100,
        "status": "open",
        "lane": lane,
        "environment": environment,
        "source_kind": "guardrail",
        "source_ref": f"cycle:{cycle_key}",
        "metadata": {
            "metric": anomaly.metric,
            "z_score": anomaly.z_score,
            "baseline_mean": anomaly.baseline_mean,
            "baseline_std": anomaly.baseline_std,
            "current_value": anomaly.current_value,
        },
    }
    artifact_payload = {
        "action": "kill",
        "title": title,
        "details": details,
        "priority": 100,
        "lane": lane,
        "environment": environment,
        "source_kind": "guardrail",
    }
    return {"db": db_payload, "artifact": artifact_payload}


def _build_guardrail_finding(
    *,
    cycle_id: int,
    strategy_version_id: int,
    strategy_key: str,
    version_label: str,
    lane: str,
    environment: str,
    cycle_key: str,
    anomaly: Any,
) -> dict[str, Any]:
    title = f"{strategy_key}:{version_label} runtime activity anomaly"
    summary = anomaly.reason
    lesson = lesson_for_reason("activity_anomaly", default=summary)
    db_payload = {
        "finding_key": f"guardrail:{cycle_key}:{strategy_key}:{version_label}:{environment}:{anomaly.metric}",
        "cycle_id": cycle_id,
        "strategy_version_id": strategy_version_id,
        "lane": lane,
        "environment": environment,
        "source_kind": "guardrail",
        "finding_type": "anomaly",
        "title": title,
        "summary": summary,
        "lesson": lesson,
        "evidence": {
            "metric": anomaly.metric,
            "z_score": anomaly.z_score,
            "baseline_mean": anomaly.baseline_mean,
            "baseline_std": anomaly.baseline_std,
            "current_value": anomaly.current_value,
        },
        "priority": 100,
        "confidence": None,
        "status": "open",
    }
    artifact_payload = {
        "finding_type": "anomaly",
        "source_kind": "guardrail",
        "title": title,
        "summary": summary,
        "lesson": lesson,
        "priority": 100,
        "lane": lane,
        "environment": environment,
    }
    return {"db": db_payload, "artifact": artifact_payload}


def _task_action(outcome: PolicyOutcome) -> str:
    if outcome.decision == "promote":
        return "promote"
    if outcome.decision == "demote":
        return "demote"
    if outcome.decision == "kill":
        return "kill"
    if outcome.reason_code == "insufficient_evidence":
        return "observe"
    return "recommend"


def _finding_type(outcome: PolicyOutcome) -> str:
    if outcome.decision == "promote":
        return "promotion"
    if outcome.decision == "demote":
        return "regression"
    if outcome.decision == "kill":
        return "kill"
    if outcome.reason_code == "insufficient_evidence":
        return "evidence_gap"
    return "review"


def _cycle_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
