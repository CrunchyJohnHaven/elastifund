#!/usr/bin/env python3
"""Shared helpers for canonical report envelopes.

The canonical report shape keeps the top-level artifact self-describing while
preserving the original payload fields for downstream compatibility.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

STANDARD_STATUSES = {"fresh", "stale", "blocked", "error"}
BLOCKED_STATUS_ALIASES = {
    "blocked",
    "blocked_for_repair",
    "hold_repair",
    "launch_blocked",
    "live_blocked",
    "repair_required",
}
FRESH_STATUS_ALIASES = {
    "ok",
    "success",
    "complete",
    "completed",
    "ready",
    "unblocked",
}
STALE_STATUS_ALIASES = {"aging", "expired", "outdated"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_status(status: str | None) -> str:
    normalized = str(status or "fresh").strip().lower()
    if normalized in FRESH_STATUS_ALIASES:
        return "fresh"
    if normalized in BLOCKED_STATUS_ALIASES:
        return "blocked"
    if normalized in STALE_STATUS_ALIASES:
        return "stale"
    if normalized not in STANDARD_STATUSES:
        return "fresh"
    return normalized


def _normalize_blockers(blockers: Any | None) -> list[str]:
    if blockers is None:
        return []
    if isinstance(blockers, str):
        return [blockers]
    if isinstance(blockers, Mapping):
        return [f"{key}:{value}" for key, value in blockers.items()]
    if isinstance(blockers, (list, tuple, set)):
        return [str(item) for item in blockers if str(item).strip()]
    return [str(blockers)]


def _compute_stale_after(
    generated_at: str,
    freshness_sla_seconds: int | float | None,
) -> str | None:
    if freshness_sla_seconds is None:
        return None
    try:
        ts = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        stale_after = ts + timedelta(seconds=float(freshness_sla_seconds))
        return stale_after.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def build_report_envelope(
    *,
    artifact: str,
    payload: Mapping[str, Any] | None = None,
    status: str = "fresh",
    source_of_truth: str = "",
    freshness_sla_seconds: int | float | None = None,
    generated_at: str | None = None,
    blockers: Any | None = None,
    summary: str = "",
) -> dict[str, Any]:
    body = dict(payload or {})
    generated_at = str(generated_at or body.get("generated_at") or utc_now())
    normalized_status = _normalize_status(status)
    normalized_blockers = _normalize_blockers(blockers)
    payload_summary = body.pop("summary", None)
    canonical_summary = payload_summary if payload_summary is not None else summary

    if not body:
        normalized_blockers = normalized_blockers or ["empty_payload"]
        if normalized_status == "fresh":
            normalized_status = "blocked"
        canonical_summary = canonical_summary or f"{artifact} emitted an empty payload"
    else:
        canonical_summary = canonical_summary or f"{artifact} ready"

    envelope = {
        "artifact": artifact,
        "generated_at": generated_at,
        "status": normalized_status,
        "source_of_truth": source_of_truth,
        "freshness_sla_seconds": int(freshness_sla_seconds or 0),
        "stale_after": _compute_stale_after(generated_at, freshness_sla_seconds),
        "blockers": normalized_blockers,
        "summary": canonical_summary,
    }

    report = dict(body)
    report.update(envelope)
    return report


def validate_report_envelope(report: Mapping[str, Any] | None) -> list[str]:
    """Return human-readable issues for a canonical report payload."""
    issues: list[str] = []
    if not isinstance(report, Mapping) or not report:
        return ["empty_payload"]

    required_fields = (
        "artifact",
        "generated_at",
        "status",
        "source_of_truth",
        "freshness_sla_seconds",
        "stale_after",
        "blockers",
        "summary",
    )
    for field in required_fields:
        if field not in report:
            issues.append(f"missing:{field}")
            continue
        value = report.get(field)
        if field == "blockers":
            if value is None:
                issues.append("empty:blockers")
            continue
        if value in (None, "", [], {}):
            issues.append(f"empty:{field}")

    status = str(report.get("status") or "").strip().lower()
    if status and _normalize_status(status) not in STANDARD_STATUSES:
        issues.append(f"invalid_status:{status}")

    stale_after = report.get("stale_after")
    if stale_after not in (None, ""):
        try:
            datetime.fromisoformat(str(stale_after).replace("Z", "+00:00"))
        except Exception:
            issues.append(f"invalid_stale_after:{stale_after}")

    freshness = report.get("freshness_sla_seconds")
    try:
        if freshness is None:
            issues.append("missing:freshness_sla_seconds")
        elif int(freshness) < 0:
            issues.append(f"negative:freshness_sla_seconds:{freshness}")
    except Exception:
        issues.append(f"invalid:freshness_sla_seconds:{freshness}")

    blockers = report.get("blockers")
    if blockers is None:
        issues.append("missing:blockers")
    elif not isinstance(blockers, (list, tuple, set)):
        issues.append("invalid:blockers")

    return issues


def write_report(
    path: Path,
    *,
    artifact: str,
    payload: Mapping[str, Any] | None = None,
    status: str = "fresh",
    source_of_truth: str = "",
    freshness_sla_seconds: int | float | None = None,
    generated_at: str | None = None,
    blockers: Any | None = None,
    summary: str = "",
) -> dict[str, Any]:
    report = build_report_envelope(
        artifact=artifact,
        payload=payload,
        status=status,
        source_of_truth=source_of_truth,
        freshness_sla_seconds=freshness_sla_seconds,
        generated_at=generated_at,
        blockers=blockers,
        summary=summary,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with open(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True, default=str)
            fh.write("\n")
        Path(tmp).replace(path)
    except Exception:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
        raise
    return report
