"""Shared BTC5 helper functions used by research scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def price_bucket(order_price: Any) -> str:
    price = safe_float(order_price, 0.0)
    if price < 0.49:
        return "lt_0.49"
    if price <= 0.51:
        return "0.49_to_0.51"
    return "gt_0.51"


def delta_bucket(abs_delta: Any) -> str:
    delta = abs(safe_float(abs_delta, 0.0))
    if delta <= 0.00005:
        return "le_0.00005"
    if delta <= 0.00010:
        return "0.00005_to_0.00010"
    return "gt_0.00010"
