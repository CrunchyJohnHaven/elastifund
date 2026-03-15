from __future__ import annotations

import os
from typing import Iterable


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: Iterable[str]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return tuple(default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def mask_secret(secret: str, visible_tail: int = 4) -> str:
    if not secret:
        return ""
    if len(secret) <= visible_tail:
        return "*" * len(secret)
    return f"{'*' * max(len(secret) - visible_tail, 4)}{secret[-visible_tail:]}"
