from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def to_repo_relative(*, root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def parse_timestamp(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def isoformat(timestamp: datetime | None) -> str | None:
    if timestamp is None:
        return None
    return timestamp.astimezone(UTC).isoformat()


def get_path(payload: dict[str, Any] | None, dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def pick_first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def normalize_confidence_label(value: Any, *, allowed: set[str]) -> str:
    text = str(value or "unknown").strip().lower()
    return text if text in allowed else "unknown"


def normalize_deploy_recommendation(value: Any, *, allowed: set[str]) -> str:
    text = str(value or "hold").strip().lower()
    return text if text in allowed else "hold"


def as_number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric) or math.isinf(numeric):
        return default
    return numeric


def as_int(value: Any, default: int = 0) -> int:
    numeric = as_number(value)
    if numeric is None:
        return default
    return int(round(numeric))


def as_int_or_none(value: Any) -> int | None:
    numeric = as_number(value)
    if numeric is None:
        return None
    return int(round(numeric))
