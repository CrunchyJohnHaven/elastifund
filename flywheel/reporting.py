"""Scorecard and artifact rendering for the flywheel control plane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_scorecard(
    records: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate strategy records into a compact scorecard."""

    findings = findings or []
    environments: dict[str, dict[str, Any]] = {}
    for record in records:
        env = record["environment"]
        bucket = environments.setdefault(
            env,
            {
                "strategies": 0,
                "realized_pnl": 0.0,
                "closed_trades": 0,
                "open_positions": 0,
                "kill_events": 0,
            },
        )
        bucket["strategies"] += 1
        bucket["realized_pnl"] += float(record.get("realized_pnl") or 0.0)
        bucket["closed_trades"] += int(record.get("closed_trades") or 0)
        bucket["open_positions"] += int(record.get("open_positions") or 0)
        bucket["kill_events"] += int(record.get("kill_events") or 0)

    return {
        "strategy_count": len(records),
        "environments": environments,
        "decision_counts": _count_values(item["decision"] for item in decisions),
        "task_counts": _count_values(item["action"] for item in tasks),
        "finding_counts": _count_values(item["finding_type"] for item in findings),
        "strategies": records,
    }


def write_artifacts(
    artifact_dir: Path,
    scorecard: dict[str, Any],
    decisions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Write JSON and markdown artifacts for one flywheel cycle."""

    findings = findings or []
    artifact_dir.mkdir(parents=True, exist_ok=True)

    scorecard_path = artifact_dir / "scorecard.json"
    decisions_path = artifact_dir / "promotion_decisions.json"
    tasks_path = artifact_dir / "tasks.json"
    findings_path = artifact_dir / "findings.json"
    summary_path = artifact_dir / "summary.md"
    task_md_path = artifact_dir / "tasks.md"
    finding_md_path = artifact_dir / "findings.md"

    scorecard_path.write_text(json.dumps(scorecard, indent=2, sort_keys=True))
    decisions_path.write_text(json.dumps(decisions, indent=2, sort_keys=True))
    tasks_path.write_text(json.dumps(tasks, indent=2, sort_keys=True))
    findings_path.write_text(json.dumps(findings, indent=2, sort_keys=True))
    summary_path.write_text(render_summary_markdown(scorecard, decisions, tasks, findings))
    task_md_path.write_text(render_tasks_markdown(tasks))
    finding_md_path.write_text(render_findings_markdown(findings))

    return {
        "scorecard": str(scorecard_path),
        "promotion_decisions": str(decisions_path),
        "tasks_json": str(tasks_path),
        "findings_json": str(findings_path),
        "summary_md": str(summary_path),
        "tasks_md": str(task_md_path),
        "findings_md": str(finding_md_path),
    }


def render_summary_markdown(
    scorecard: dict[str, Any],
    decisions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
) -> str:
    """Render the cycle summary in markdown."""

    findings = findings or []
    lines = [
        "# Flywheel Cycle Summary",
        "",
        f"- Strategies evaluated: {scorecard['strategy_count']}",
        f"- Decisions: {scorecard['decision_counts']}",
        f"- Task actions: {scorecard['task_counts']}",
        f"- Findings: {scorecard.get('finding_counts', {})}",
        "",
        "## Environment Scorecard",
        "",
        "| Environment | Strategies | Realized PnL | Closed Trades | Open Positions | Kill Events |",
        "|-------------|------------|--------------|---------------|----------------|-------------|",
    ]

    for env, metrics in sorted(scorecard["environments"].items()):
        lines.append(
            f"| {env} | {metrics['strategies']} | {metrics['realized_pnl']:.2f} | "
            f"{metrics['closed_trades']} | {metrics['open_positions']} | {metrics['kill_events']} |"
        )

    lines.extend(
        [
            "",
            "## Promotion Decisions",
            "",
            "| Strategy | Environment | Decision | Target | Reason |",
            "|----------|-------------|----------|--------|--------|",
        ]
    )
    for item in decisions:
        lines.append(
            f"| {item['strategy_key']}:{item['version_label']} | {item['from_stage']} | "
            f"{item['decision']} | {item['to_stage']} | {item['reason_code']} |"
        )

    lines.extend(
        [
            "",
            "## Key Findings",
            "",
        ]
    )
    for finding in sorted(findings, key=lambda row: row["priority"])[:10]:
        lines.append(f"- P{finding['priority']}: [{finding['finding_type']}] {finding['title']}")

    lines.extend(
        [
            "",
            "## Top Tasks",
            "",
        ]
    )
    for task in sorted(tasks, key=lambda row: row["priority"])[:10]:
        lines.append(f"- P{task['priority']}: [{task['action']}] {task['title']}")

    return "\n".join(lines) + "\n"


def render_tasks_markdown(tasks: list[dict[str, Any]]) -> str:
    """Render generated tasks in markdown."""

    lines = [
        "# Flywheel Task Queue",
        "",
        "| Priority | Action | Title | Details |",
        "|----------|--------|-------|---------|",
    ]
    for task in sorted(tasks, key=lambda row: row["priority"]):
        lines.append(
            f"| {task['priority']} | {task['action']} | {task['title']} | {task.get('details', '')} |"
        )
    return "\n".join(lines) + "\n"


def render_findings_markdown(findings: list[dict[str, Any]]) -> str:
    """Render structured findings in markdown."""

    lines = [
        "# Flywheel Findings",
        "",
        "| Priority | Type | Source | Title | Lesson |",
        "|----------|------|--------|-------|--------|",
    ]
    for finding in sorted(findings, key=lambda row: row["priority"]):
        lines.append(
            f"| {finding['priority']} | {finding['finding_type']} | {finding['source_kind']} | "
            f"{finding['title']} | {finding.get('lesson', '')} |"
        )
    return "\n".join(lines) + "\n"


def _count_values(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
