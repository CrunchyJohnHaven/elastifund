from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


ET_ZONE = ZoneInfo("America/New_York")
LIVE_FILLED_STATUSES = {
    "live_filled",
    "live_partial_fill_cancelled",
    "live_partial_fill_open",
}
BTC5_ATTRIBUTION_REASON_KEYS = (
    "book_failure_attribution",
    "placement_failure_attribution",
    "order_outcome_attribution",
)


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def optional_env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return None
    parsed = safe_float(raw, None)
    if parsed is None or parsed < 0:
        return None
    return float(parsed)


def env_stage(name: str, default: int = 1) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return int(default)
    try:
        stage = int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)
    if stage not in {1, 2, 3}:
        return int(default)
    return stage


def env_optional_stage(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return None
    return env_stage(name, 1)


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def join_reasons(*parts: str | None) -> str | None:
    text = " | ".join(part for part in parts if part)
    return text or None


def reason_tag(name: str, value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return f"{name}={text}"


def parse_reason_tags(reason: Any) -> dict[str, str]:
    tags: dict[str, str] = {}
    text = str(reason or "").strip()
    if not text:
        return tags
    for part in text.split("|"):
        piece = part.strip()
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        key = key.strip()
        if key in BTC5_ATTRIBUTION_REASON_KEYS:
            tags[key] = value.strip()
    return tags


def has_reason_fragment(reason: Any, fragment: str) -> bool:
    text = str(reason or "").strip().lower()
    token = str(fragment or "").strip().lower()
    return bool(text and token and token in text)


def is_post_only_cross_text(error_msg: Any) -> bool:
    text = str(error_msg or "").strip().lower()
    return "post-only" in text and "crosses book" in text


def is_transient_request_error_text(error_msg: Any) -> bool:
    text = str(error_msg or "").strip().lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "request exception",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "temporarily unavailable",
            "service unavailable",
        )
    )


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def normalized_env_optional_float(value: Any) -> float | None:
    parsed = safe_float(value, None)
    if parsed is None or parsed < 0:
        return None
    return float(parsed)


def day_start_utc_ts(now_ts: float | None = None) -> int:
    now = datetime.fromtimestamp(float(now_ts) if now_ts is not None else time.time(), tz=timezone.utc)
    return int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())


def won_flag(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return 1 if int(value) == 1 else 0
    except (TypeError, ValueError):
        return None


def is_live_filled_status(order_status: Any, filled: Any) -> bool:
    status = str(order_status or "").strip().lower()
    if status in LIVE_FILLED_STATUSES:
        return True
    try:
        return bool(int(filled) == 1 and status.startswith("live_"))
    except (TypeError, ValueError):
        return False


def btc5_price_bucket(order_price: Any) -> str:
    price = safe_float(order_price, None)
    if price is None:
        return "unknown"
    rounded = round(float(price), 2)
    if rounded < 0.49:
        return "<0.49"
    if rounded < 0.50:
        return "0.49"
    if rounded < 0.51:
        return "0.50"
    return "0.51+"


def btc5_cluster_price_bucket(order_price: Any) -> str:
    price = safe_float(order_price, None)
    if price is None:
        return "unknown"
    if price < 0.49:
        return "lt_0.49"
    if price <= 0.51:
        return "0.49_to_0.51"
    return "gt_0.51"


def btc5_delta_bucket(delta: Any) -> str:
    abs_delta = abs(safe_float(delta, 0.0) or 0.0)
    if abs_delta <= 0.00005:
        return "le_0.00005"
    if abs_delta <= 0.00010:
        return "0.00005_to_0.00010"
    if abs_delta <= 0.00015:
        return "0.00010_to_0.00015"
    return "gt_0.00015"


def btc5_session_bucket(window_start_ts: int) -> str:
    dt = datetime.fromtimestamp(int(window_start_ts), tz=timezone.utc).astimezone(ET_ZONE)
    if dt.hour in {9, 10, 11}:
        return "open_et"
    if dt.hour in {12, 13}:
        return "midday_et"
    return f"hour_et_{dt.hour:02d}"
