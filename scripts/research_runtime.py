"""Shared runtime helpers for research/simulation scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from infra.fast_json import dump_path_atomic, load_path


RunMode = Literal["full", "analyze"]


def normalize_mode(raw: Any, *, default: RunMode = "full") -> RunMode:
    text = str(raw or default).strip().lower()
    if text in {"analyze", "quick", "fast"}:
        return "analyze"
    return "full"


def cap_for_mode(value: int, *, mode: RunMode, analyze_cap: int, floor: int = 1) -> int:
    parsed = max(floor, int(value))
    if mode == "analyze":
        return max(floor, min(parsed, int(analyze_cap)))
    return parsed


def load_json_dict(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = load_path(path)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    dump_path_atomic(path, payload, indent=2, sort_keys=True, trailing_newline=True)
