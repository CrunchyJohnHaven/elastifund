#!/usr/bin/env python3
"""Run one calibration-lane benchmark iteration and append it to the ledger."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.calibration_v1.benchmark import run_benchmark, write_benchmark_artifacts  # noqa: E402
from data_layer import crud, database  # noqa: E402
from flywheel.intelligence import FindingSpec, TaskSpec, record_finding_with_task  # noqa: E402
from scripts.render_lane_progress import render_progress  # noqa: E402


LEDGER_COLUMNS = [
    "run_id",
    "timestamp",
    "benchmark_id",
    "candidate_label",
    "description",
    "mutable_surface",
    "git_sha",
    "mutable_surface_sha256",
    "selected_variant",
    "benchmark_score",
    "brier",
    "ece",
    "log_loss",
    "status",
    "decision_reason",
    "warmup_rows",
    "holdout_rows",
    "packet_json",
    "packet_md",
    "mutation_cmd",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one calibration-lane autoresearch iteration.")
    parser.add_argument(
        "--manifest",
        default="benchmarks/calibration_v1/manifest.json",
        help="Frozen benchmark manifest",
    )
    parser.add_argument(
        "--ledger",
        default="research/results/calibration/results.tsv",
        help="Append-only results ledger",
    )
    parser.add_argument(
        "--progress-tsv",
        default="research/results/calibration/progress.tsv",
        help="Derived progress TSV path",
    )
    parser.add_argument(
        "--progress-svg",
        default="research/results/calibration/progress.svg",
        help="Derived progress SVG path",
    )
    parser.add_argument(
        "--summary-md",
        default="research/results/calibration/summary.md",
        help="Lane summary markdown path",
    )
    parser.add_argument(
        "--output-dir",
        default="research/results/calibration/packets",
        help="Directory for benchmark packets",
    )
    parser.add_argument(
        "--candidate-label",
        default="manual",
        help="Short label for the current candidate",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Free-text description recorded in the ledger",
    )
    parser.add_argument(
        "--mutation-cmd",
        help="Optional shell command that mutates the mutable surface before benchmarking",
    )
    parser.add_argument(
        "--control-db-url",
        help="Optional SQLAlchemy database URL for publishing flywheel review tasks",
    )
    parser.add_argument(
        "--keep-epsilon",
        type=float,
        default=1e-9,
        help="Minimum score delta required to mark a run as keep",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ledger_path = ROOT / args.ledger
    progress_tsv = ROOT / args.progress_tsv
    progress_svg = ROOT / args.progress_svg
    summary_md = ROOT / args.summary_md
    output_dir = ROOT / args.output_dir

    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_ledger(ledger_path)
    existing_rows = read_ledger(ledger_path)
    run_id = (max((int(row["run_id"]) for row in existing_rows), default=0) + 1)

    packet_stem = f"run_{run_id:04d}_{slugify(args.candidate_label)}"
    packet_json = output_dir / f"{packet_stem}.json"
    packet_md = output_dir / f"{packet_stem}.md"

    packet: dict[str, Any] | None = None
    status = "crash"
    decision_reason = "benchmark_failed"
    backup_path: Path | None = None
    mutable_surface = ROOT / "bot/adaptive_platt.py"

    try:
        if args.mutation_cmd:
            backup_path = backup_surface(mutable_surface)
            run_mutation(args.mutation_cmd)

        packet = run_benchmark(args.manifest, description=args.description)
        write_benchmark_artifacts(packet, json_path=packet_json, summary_path=packet_md)
        status, decision_reason = classify_run(existing_rows, packet, epsilon=args.keep_epsilon)
        if backup_path is not None and status != "keep":
            restore_surface(backup_path, mutable_surface)
    except Exception as exc:  # pragma: no cover - exercised through CLI behavior
        if backup_path is not None:
            restore_surface(backup_path, mutable_surface)
        packet = crash_packet(args.manifest, description=args.description, exc=exc)
        packet_json.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
        packet_md.write_text(render_crash_markdown(packet), encoding="utf-8")
        status = "crash"
        decision_reason = type(exc).__name__
    finally:
        if backup_path is not None and backup_path.exists():
            backup_path.unlink()

    row = ledger_row(
        run_id=run_id,
        packet=packet,
        status=status,
        decision_reason=decision_reason,
        candidate_label=args.candidate_label,
        description=args.description,
        packet_json=display_path(packet_json),
        packet_md=display_path(packet_md),
        mutation_cmd=args.mutation_cmd or "",
    )
    append_ledger_row(ledger_path, row)

    records = render_progress(ledger_path, progress_tsv, progress_svg)
    write_summary(summary_md, rows=read_ledger(ledger_path), records_count=len(records))

    task_info = None
    if args.control_db_url:
        task_info = publish_flywheel_review(
            control_db_url=args.control_db_url,
            row=row,
        )

    result = {
        "run_id": run_id,
        "status": status,
        "decision_reason": decision_reason,
        "benchmark_score": row["benchmark_score"],
        "packet_json": display_path(packet_json),
        "packet_md": display_path(packet_md),
        "progress_tsv": display_path(progress_tsv),
        "progress_svg": display_path(progress_svg),
        "summary_md": display_path(summary_md),
        "flywheel": task_info,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def ensure_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.write_text("\t".join(LEDGER_COLUMNS) + "\n", encoding="utf-8")


def read_ledger(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def append_ledger_row(path: Path, row: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(row[column] for column in LEDGER_COLUMNS) + "\n")


def classify_run(
    existing_rows: list[dict[str, str]],
    packet: dict[str, Any],
    *,
    epsilon: float,
) -> tuple[str, str]:
    score = float(packet["selected_variant"]["benchmark_score"])
    prior_scores = [
        float(row["benchmark_score"])
        for row in existing_rows
        if row.get("benchmark_score")
    ]
    if not prior_scores:
        return "keep", "baseline_frontier"
    prior_best = max(prior_scores)
    if score > prior_best + epsilon:
        return "keep", "improved_frontier"
    return "discard", "below_frontier"


def ledger_row(
    *,
    run_id: int,
    packet: dict[str, Any],
    status: str,
    decision_reason: str,
    candidate_label: str,
    description: str,
    packet_json: str,
    packet_md: str,
    mutation_cmd: str,
) -> dict[str, str]:
    selected = packet.get("selected_variant") or {}
    dataset = packet.get("dataset") or {}
    git_info = packet.get("git") or {}
    return {
        "run_id": str(run_id),
        "timestamp": str(packet.get("generated_at") or utc_now_iso()),
        "benchmark_id": str(packet.get("benchmark_id") or "calibration_v1"),
        "candidate_label": sanitize_tsv(candidate_label),
        "description": sanitize_tsv(description or packet.get("description") or ""),
        "mutable_surface": str(packet.get("mutable_surface") or "bot/adaptive_platt.py"),
        "git_sha": str(git_info.get("sha") or "unknown"),
        "mutable_surface_sha256": str(packet.get("mutable_surface_sha256") or ""),
        "selected_variant": str(selected.get("name") or ""),
        "benchmark_score": format_metric(selected.get("benchmark_score")),
        "brier": format_metric(selected.get("brier")),
        "ece": format_metric(selected.get("ece")),
        "log_loss": format_metric(selected.get("log_loss")),
        "status": status,
        "decision_reason": sanitize_tsv(decision_reason),
        "warmup_rows": str(dataset.get("warmup_rows") or ""),
        "holdout_rows": str(dataset.get("holdout_rows") or ""),
        "packet_json": packet_json,
        "packet_md": packet_md,
        "mutation_cmd": sanitize_tsv(mutation_cmd),
    }


def write_summary(path: Path, *, rows: list[dict[str, str]], records_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keep_count = sum(1 for row in rows if row["status"] == "keep")
    discard_count = sum(1 for row in rows if row["status"] == "discard")
    crash_count = sum(1 for row in rows if row["status"] == "crash")
    latest = rows[-1] if rows else None
    valid_scores = [(int(row["run_id"]), float(row["benchmark_score"])) for row in rows if row.get("benchmark_score")]
    best_run = max(valid_scores, key=lambda item: item[1]) if valid_scores else None

    lines = [
        "# Calibration Lane Summary",
        "",
        f"- Logged runs: {records_count}",
        f"- Kept frontier marks: {keep_count}",
        f"- Discarded runs: {discard_count}",
        f"- Crashes: {crash_count}",
        "",
        "Calibration benchmark wins do not imply paper, shadow, or live-trading readiness.",
    ]

    if best_run:
        lines.extend(
            [
                "",
                "## Frontier",
                "",
                f"- Best run: `{best_run[0]}`",
                f"- Best benchmark score: {best_run[1]:.6f}",
            ]
        )
    if latest:
        lines.extend(
            [
                "",
                "## Latest Run",
                "",
                f"- Run: `{latest['run_id']}`",
                f"- Status: `{latest['status']}`",
                f"- Decision reason: `{latest['decision_reason']}`",
                f"- Selected variant: `{latest['selected_variant']}`",
                f"- Benchmark score: {latest['benchmark_score'] or 'n/a'}",
                f"- Packet: `{latest['packet_json']}`",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish_flywheel_review(
    *,
    control_db_url: str,
    row: dict[str, str],
) -> dict[str, Any]:
    database.reset_engine()
    engine = database.get_engine(control_db_url)
    database.init_db(engine)
    session = database.get_session_factory(engine)()
    try:
        cycle = crud.create_flywheel_cycle(
            session,
            cycle_key=f"calibration-benchmark-{row['run_id']}-{timestamp_slug()}",
            status="running",
            summary=None,
            artifacts_path=row["packet_json"],
        )
        title, action, priority = flywheel_task_fields(row)
        finding, task = record_finding_with_task(
            session,
            finding=FindingSpec(
                finding_key=f"benchmark:{row['benchmark_id']}:{row['run_id']}",
                cycle_id=cycle.id,
                strategy_version_id=None,
                lane="slow_directional",
                environment="benchmark",
                source_kind="benchmark_lane",
                finding_type=benchmark_finding_type(row),
                title=benchmark_finding_title(row),
                summary=flywheel_details(row),
                lesson=benchmark_lesson(row),
                evidence={
                    "run_id": row["run_id"],
                    "benchmark_id": row["benchmark_id"],
                    "candidate_label": row["candidate_label"],
                    "decision_reason": row["decision_reason"],
                    "selected_variant": row["selected_variant"],
                    "benchmark_score": row["benchmark_score"],
                    "packet_json": row["packet_json"],
                    "packet_md": row["packet_md"],
                },
                priority=priority,
                confidence=None,
                status="open",
            ),
            task=TaskSpec(
                cycle_id=cycle.id,
                strategy_version_id=None,
                action=action,
                title=title,
                details=flywheel_details(row),
                priority=priority,
                status="open",
                lane="slow_directional",
                environment="benchmark",
                source_kind="benchmark_lane",
                source_ref=f"benchmark:{row['benchmark_id']}:{row['run_id']}",
                metadata={
                    "run_id": row["run_id"],
                    "benchmark_id": row["benchmark_id"],
                    "packet_json": row["packet_json"],
                    "packet_md": row["packet_md"],
                    "status": row["status"],
                    "decision_reason": row["decision_reason"],
                },
            ),
        )
        crud.finish_flywheel_cycle(
            session,
            cycle.id,
            status="completed",
            summary=title,
            artifacts_path=row["packet_json"],
        )
        session.commit()
        return {
            "cycle_id": cycle.id,
            "task_id": task.id,
            "finding_id": None if finding is None else finding.id,
            "action": action,
            "title": title,
        }
    finally:
        session.close()
        database.reset_engine()


def flywheel_task_fields(row: dict[str, str]) -> tuple[str, str, int]:
    if row["status"] == "keep" and row["decision_reason"] != "baseline_frontier":
        return (
            "Review retained calibration benchmark improvement",
            "recommend",
            20,
        )
    if row["status"] == "keep":
        return (
            "Freeze calibration benchmark baseline",
            "observe",
            40,
        )
    if row["status"] == "discard":
        return (
            "Record calibration benchmark null result",
            "observe",
            50,
        )
    return (
        "Investigate calibration lane benchmark crash",
        "observe",
        10,
    )


def flywheel_details(row: dict[str, str]) -> str:
    return (
        f"Run {row['run_id']} ended with status={row['status']} reason={row['decision_reason']}. "
        f"variant={row['selected_variant']} benchmark_score={row['benchmark_score'] or 'n/a'} "
        f"brier={row['brier'] or 'n/a'} ece={row['ece'] or 'n/a'} packet={row['packet_json']}. "
        "Calibration benchmark results require replay or paper validation before any broader adoption."
    )


def benchmark_finding_title(row: dict[str, str]) -> str:
    return f"Calibration lane run {row['run_id']} {row['status']} ({row['decision_reason']})"


def benchmark_finding_type(row: dict[str, str]) -> str:
    if row["status"] == "keep" and row["decision_reason"] == "baseline_frontier":
        return "benchmark_baseline"
    if row["status"] == "keep":
        return "benchmark_improvement"
    if row["status"] == "discard":
        return "benchmark_null"
    return "benchmark_crash"


def benchmark_lesson(row: dict[str, str]) -> str:
    if row["status"] == "keep" and row["decision_reason"] == "baseline_frontier":
        return "Freeze the initial benchmark frontier before expanding the search surface."
    if row["status"] == "keep":
        return "Benchmark wins should enter review as evidence packets, not silent code adoption."
    if row["status"] == "discard":
        return "Null results are useful search bounds and should remain in the append-only ledger."
    return "Crashes in the lane harness are control-plane work, not hidden experimental noise."


def run_mutation(command: str) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"mutation command failed with exit code {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )


def backup_surface(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    handle = tempfile.NamedTemporaryFile(prefix="lane_backup_", suffix=path.suffix, delete=False)
    handle.close()
    backup = Path(handle.name)
    shutil.copy2(path, backup)
    return backup


def restore_surface(backup_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, target_path)


def crash_packet(*, manifest: str, description: str, exc: Exception) -> dict[str, Any]:
    return {
        "benchmark_id": "calibration_v1",
        "generated_at": utc_now_iso(),
        "description": description,
        "manifest_path": manifest,
        "mutable_surface": "bot/adaptive_platt.py",
        "mutable_surface_sha256": "",
        "git": {"sha": "unknown", "dirty": True},
        "selected_variant": {},
        "dataset": {},
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def render_crash_markdown(packet: dict[str, Any]) -> str:
    error = packet.get("error") or {}
    lines = [
        "# Calibration Benchmark Crash",
        "",
        f"- Generated at: {packet['generated_at']}",
        f"- Error type: `{error.get('type', 'unknown')}`",
        f"- Error: {error.get('message', 'unknown')}",
        "",
        "The mutation was restored from a local backup before the crash packet was written.",
    ]
    return "\n".join(lines) + "\n"


def sanitize_tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").strip()


def format_metric(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):.6f}"


def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "run"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
