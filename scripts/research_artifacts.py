"""Shared artifact I/O helpers for research and simulation scripts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from infra.fast_json import dump_path_atomic


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp() -> str:
    return utc_now().strftime("%Y%m%dT%H%M%SZ")


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_path_atomic(path, payload, indent=2, sort_keys=True, trailing_newline=True)


def write_json_and_markdown(
    *,
    json_path: Path,
    markdown_path: Path,
    payload: dict[str, Any],
    markdown: str,
) -> None:
    write_json_payload(json_path, payload)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown)


def write_versioned_cycle_reports(
    *,
    report_dir: Path,
    payload: dict[str, Any],
    markdown: str,
) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    cycle_json = report_dir / f"cycle_{utc_stamp()}.json"
    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    artifacts = {
        "cycle_json": str(cycle_json),
        "latest_json": str(latest_json),
        "latest_md": str(latest_md),
    }
    payload_with_artifacts = dict(payload, artifacts=artifacts)
    write_json_payload(cycle_json, payload_with_artifacts)
    write_json_payload(latest_json, payload_with_artifacts)
    latest_md.write_text(markdown)
    return artifacts
