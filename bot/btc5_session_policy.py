#!/usr/bin/env python3
"""Session guardrail policy helpers for BTC 5m maker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from zoneinfo import ZoneInfo


ET_ZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SessionGuardrailOverride:
    name: str
    et_hours: tuple[int, ...]
    min_delta: float | None = None
    max_abs_delta: float | None = None
    up_max_buy_price: float | None = None
    down_max_buy_price: float | None = None
    maker_improve_ticks: int | None = None
    exclude_price_buckets: tuple[float, ...] = ()

    @property
    def session_name(self) -> str:
        return self.name


def _session_guardrail_sort_key(override: SessionGuardrailOverride) -> tuple[int, tuple[int, ...], str]:
    return (len(tuple(sorted(override.et_hours))), tuple(sorted(override.et_hours)), override.session_name)


def order_session_guardrail_overrides(
    overrides: Iterable[SessionGuardrailOverride],
) -> tuple[SessionGuardrailOverride, ...]:
    return tuple(sorted(tuple(overrides), key=_session_guardrail_sort_key))


def _load_json_array_file(path_value: str, *, parse_json_list_fn: Callable[[Any], list[Any]]) -> list[Any]:
    path_text = str(path_value or "").strip()
    if not path_text:
        return []
    path = Path(path_text)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_json_list_fn(raw)


def parse_session_guardrail_overrides(
    value: Any,
    *,
    parse_json_list_fn: Callable[[Any], list[Any]],
    safe_float_fn: Callable[[Any, float | None], float | None],
    normalized_env_optional_float_fn: Callable[[Any], float | None],
) -> tuple[SessionGuardrailOverride, ...]:
    parsed = parse_json_list_fn(value)
    overrides: list[SessionGuardrailOverride] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("session_name") or "").strip()
        if not name:
            continue
        raw_hours = item.get("et_hours")
        hours: list[int] = []
        if isinstance(raw_hours, list):
            for raw_hour in raw_hours:
                try:
                    hour = int(raw_hour)
                except (TypeError, ValueError):
                    continue
                if 0 <= hour <= 23 and hour not in hours:
                    hours.append(hour)
        if not hours:
            continue
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else item
        maker_improve_ticks = safe_float_fn(profile.get("maker_improve_ticks"), None)
        parsed_ticks = int(maker_improve_ticks) if maker_improve_ticks is not None and maker_improve_ticks >= 0 else None
        raw_excluded_buckets = profile.get("exclude_price_buckets")
        excluded_buckets: list[float] = []
        if isinstance(raw_excluded_buckets, list):
            for raw_bucket in raw_excluded_buckets:
                parsed_bucket = normalized_env_optional_float_fn(raw_bucket)
                if parsed_bucket is None:
                    continue
                normalized_bucket = round(float(parsed_bucket), 2)
                if 0.0 <= normalized_bucket <= 1.0 and normalized_bucket not in excluded_buckets:
                    excluded_buckets.append(normalized_bucket)
        overrides.append(
            SessionGuardrailOverride(
                name=name,
                et_hours=tuple(hours),
                min_delta=normalized_env_optional_float_fn(profile.get("min_delta")),
                max_abs_delta=normalized_env_optional_float_fn(profile.get("max_abs_delta")),
                up_max_buy_price=normalized_env_optional_float_fn(profile.get("up_max_buy_price")),
                down_max_buy_price=normalized_env_optional_float_fn(profile.get("down_max_buy_price")),
                maker_improve_ticks=parsed_ticks,
                exclude_price_buckets=tuple(sorted(excluded_buckets)),
            )
        )
    return order_session_guardrail_overrides(overrides)


def load_session_guardrail_overrides(
    *,
    inline_json: str,
    path_value: str,
    legacy_json: str,
    parse_json_list_fn: Callable[[Any], list[Any]],
    safe_float_fn: Callable[[Any, float | None], float | None],
    normalized_env_optional_float_fn: Callable[[Any], float | None],
) -> tuple[SessionGuardrailOverride, ...]:
    inline = str(inline_json or "").strip()
    if inline:
        return parse_session_guardrail_overrides(
            inline,
            parse_json_list_fn=parse_json_list_fn,
            safe_float_fn=safe_float_fn,
            normalized_env_optional_float_fn=normalized_env_optional_float_fn,
        )
    from_path = _load_json_array_file(path_value, parse_json_list_fn=parse_json_list_fn)
    if from_path:
        return parse_session_guardrail_overrides(
            from_path,
            parse_json_list_fn=parse_json_list_fn,
            safe_float_fn=safe_float_fn,
            normalized_env_optional_float_fn=normalized_env_optional_float_fn,
        )
    return parse_session_guardrail_overrides(
        legacy_json,
        parse_json_list_fn=parse_json_list_fn,
        safe_float_fn=safe_float_fn,
        normalized_env_optional_float_fn=normalized_env_optional_float_fn,
    )


def window_dt_et(window_start_ts: int) -> datetime | None:
    if int(window_start_ts or 0) <= 0:
        return None
    return datetime.fromtimestamp(int(window_start_ts), tz=timezone.utc).astimezone(ET_ZONE)


def active_session_guardrail_override(
    overrides: tuple[SessionGuardrailOverride, ...],
    *,
    window_start_ts: int,
) -> SessionGuardrailOverride | None:
    dt_et = window_dt_et(window_start_ts)
    if dt_et is None:
        return None
    matches = [override for override in overrides if dt_et.hour in override.et_hours]
    return matches[0] if matches else None


def session_guardrail_reason(
    override: SessionGuardrailOverride | None,
    *,
    window_start_ts: int,
) -> str | None:
    if override is None:
        return None
    dt_et = window_dt_et(window_start_ts)
    hour = dt_et.hour if dt_et is not None else "na"
    return (
        f"session_policy name={override.session_name} hour_et={hour} "
        f"min_delta={override.min_delta} "
        f"max_abs_delta={override.max_abs_delta} "
        f"up_max={override.up_max_buy_price} down_max={override.down_max_buy_price} "
        f"maker_ticks={override.maker_improve_ticks} "
        f"exclude_price_buckets={list(override.exclude_price_buckets)}"
    )
