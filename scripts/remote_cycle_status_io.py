"""Shared IO helpers for remote cycle status artifact generation."""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

from infra.fast_json import load_path, loads as fast_loads


DEFAULT_USER_AGENT = "elastifund-runtime-truth/1.0"


def fetch_json_url(url: str, *, timeout_seconds: int = 20, user_agent: str = DEFAULT_USER_AGENT) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return fast_loads(response.read())


def load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return load_path(path)
    except ValueError:
        return default


def load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = fast_loads(text)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows
