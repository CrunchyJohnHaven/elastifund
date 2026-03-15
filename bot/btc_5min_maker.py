#!/usr/bin/env python3
"""Instance 2: BTC 5m maker bot (T-10s execution).

This runner targets Polymarket 5-minute BTC candle markets using maker-only
orders near close.

Flow per 5-minute window:
  1) Wait until T-10 seconds before close.
  2) Compare current Binance BTC spot to candle open.
  3) If |delta| >= threshold, select UP or DOWN outcome.
  4) Read CLOB top-of-book and place post-only BUY on winning token.
  5) Cancel unfilled order at T-2 seconds.
  6) Persist every decision in SQLite for fill/win-rate analysis.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import math
import os
import sqlite3
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import aiohttp

try:
    import websockets
except Exception:  # pragma: no cover - optional runtime dependency
    websockets = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - optional runtime dependency
    pass

try:
    from bot.polymarket_clob import build_authenticated_clob_client, parse_signature_type
except ImportError:
    from polymarket_clob import build_authenticated_clob_client, parse_signature_type  # type: ignore

logger = logging.getLogger("BTC5Maker")

WINDOW_SECONDS = max(60, int(os.environ.get("BTC5_WINDOW_SECONDS", "300")))
MARKET_SLUG_PREFIX = str(os.environ.get("BTC5_MARKET_SLUG_PREFIX", "btc-updown-5m")).strip().rstrip("-")
if not MARKET_SLUG_PREFIX:
    MARKET_SLUG_PREFIX = "btc-updown-5m"
DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
CLOB_HARD_MIN_SHARES = 5.0
CLOB_HARD_MIN_NOTIONAL_USD = 5.0
PROBE_DEFAULT_UP_MAX_BUY_PRICE = 0.49
PROBE_DEFAULT_DOWN_MAX_BUY_PRICE = 0.51
ET_ZONE = ZoneInfo("America/New_York")
LIVE_FILLED_STATUSES = {
    "live_filled",
    "live_partial_fill_cancelled",
    "live_partial_fill_open",
}
LIVE_STAGE_IDS = {1, 2, 3}
ACTIONABLE_ORDER_STATUSES = {
    "live_filled",
    "live_partial_fill_cancelled",
    "live_partial_fill_open",
    "live_cancelled_unfilled",
    "live_order_failed",
}
VALIDATED_STRONG_PRICE_BUCKETS = frozenset({"<0.49", "0.49"})
OBSERVED_BTC5_LOSS_CLUSTERS = frozenset(
    {
        ("open_et", "DOWN", "0.49_to_0.51", "le_0.00005"),
        ("open_et", "UP", "0.49_to_0.51", "le_0.00005"),
        ("open_et", "UP", "lt_0.49", "le_0.00005"),
        ("open_et", "UP", "lt_0.49", "0.00005_to_0.00010"),
        ("midday_et", "DOWN", "0.49_to_0.51", "0.00005_to_0.00010"),
    }
)
BTC5_ATTRIBUTION_REASON_KEYS = (
    "book_failure_attribution",
    "placement_failure_attribution",
    "order_outcome_attribution",
)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return None
    parsed = _safe_float(raw, None)
    if parsed is None or parsed <= 0:
        return None
    return float(parsed)


def _env_stage(name: str, default: int = 1) -> int:
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


def _env_optional_stage(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return None
    return _env_stage(name, 1)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _join_reasons(*parts: str | None) -> str | None:
    text = " | ".join(part for part in parts if part)
    return text or None


def _reason_tag(name: str, value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return f"{name}={text}"


def _parse_reason_tags(reason: Any) -> dict[str, str]:
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


def _is_post_only_cross_text(error_msg: Any) -> bool:
    text = str(error_msg or "").strip().lower()
    return "post-only" in text and "crosses book" in text


def _is_transient_request_error_text(error_msg: Any) -> bool:
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


def _normalized_env_optional_float(value: Any) -> float | None:
    parsed = _safe_float(value, None)
    if parsed is None or parsed <= 0:
        return None
    return float(parsed)


def _day_start_utc_ts(now_ts: float | None = None) -> int:
    now = datetime.fromtimestamp(float(now_ts) if now_ts is not None else time.time(), tz=timezone.utc)
    return int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())


def _won_flag(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return 1 if int(value) == 1 else 0
    except (TypeError, ValueError):
        return None


def _is_live_filled_status(order_status: Any, filled: Any) -> bool:
    status = str(order_status or "").strip().lower()
    if status in LIVE_FILLED_STATUSES:
        return True
    try:
        return bool(int(filled) == 1 and status.startswith("live_"))
    except (TypeError, ValueError):
        return False


def _btc5_price_bucket(order_price: Any) -> str:
    price = _safe_float(order_price, None)
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


def _btc5_cluster_price_bucket(order_price: Any) -> str:
    price = _safe_float(order_price, None)
    if price is None:
        return "unknown"
    if price < 0.49:
        return "lt_0.49"
    if price <= 0.51:
        return "0.49_to_0.51"
    return "gt_0.51"


def _btc5_delta_bucket(delta: Any) -> str:
    abs_delta = abs(_safe_float(delta, 0.0) or 0.0)
    if abs_delta <= 0.00005:
        return "le_0.00005"
    if abs_delta <= 0.00010:
        return "0.00005_to_0.00010"
    if abs_delta <= 0.00015:
        return "0.00010_to_0.00015"
    return "gt_0.00015"


def _btc5_session_bucket(window_start_ts: int) -> str:
    dt_et = _window_dt_et(window_start_ts)
    if dt_et is None:
        return "unknown"
    if dt_et.hour in {9, 10, 11}:
        return "open_et"
    if dt_et.hour in {12, 13}:
        return "midday_et"
    return f"hour_et_{dt_et.hour:02d}"


def _serialize_json_list(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        return json.dumps(value, separators=(",", ":"))
    return None


def _unique_tags(*parts: str | None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _rollup_trade_group(group_rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    fills = len(group_rows)
    pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in group_rows), 4)
    avg_pnl = round(pnl / fills, 4) if fills else 0.0
    avg_price = round(
        sum(_safe_float(row.get("order_price"), 0.0) for row in group_rows) / fills,
        4,
    ) if fills else 0.0
    settled = [row for row in group_rows if _won_flag(row.get("won")) is not None]
    wins = sum(1 for row in settled if _won_flag(row.get("won")) == 1)
    return {
        "label": label,
        "fills": fills,
        "pnl_usd": pnl,
        "avg_pnl_usd": avg_pnl,
        "avg_order_price": avg_price,
        "settled_fills": len(settled),
        "wins": wins,
        "win_rate": round(wins / len(settled), 4) if settled else None,
    }


def _infer_row_attributions(row: dict[str, Any]) -> dict[str, str]:
    tags = _parse_reason_tags(row.get("reason"))
    status = str(row.get("order_status") or "").strip().lower()
    if "book_failure_attribution" not in tags:
        if status == "skip_no_book":
            tags["book_failure_attribution"] = "no_book"
        elif status == "skip_bad_book":
            tags["book_failure_attribution"] = "bad_book"
    if "placement_failure_attribution" not in tags and status == "live_order_failed":
        tags["placement_failure_attribution"] = (
            "post_only_cross_failure"
            if _is_post_only_cross_text(row.get("reason"))
            else "order_placement_failure"
        )
    if "order_outcome_attribution" not in tags:
        if status == "live_cancelled_unfilled":
            tags["order_outcome_attribution"] = "cancel_before_fill"
        elif status == "live_partial_fill_cancelled":
            tags["order_outcome_attribution"] = "partial_fill_then_cancel"
    return tags


def _classify_book_quotes(best_bid: float | None, best_ask: float | None) -> tuple[str | None, str | None]:
    if best_bid is None or best_ask is None:
        return "bad_book", f"best_bid={best_bid} best_ask={best_ask}"
    if best_bid < 0.0 or best_bid > 1.0 or best_ask <= 0.0 or best_ask > 1.0:
        return "bad_book", f"best_bid={best_bid} best_ask={best_ask}"
    if best_bid >= best_ask:
        return "bad_book", f"best_bid={best_bid} best_ask={best_ask} crossed_or_inverted_book"
    return None, None


def current_window_start(ts: float | None = None) -> int:
    now = int(ts if ts is not None else time.time())
    return now - (now % WINDOW_SECONDS)


@dataclass(frozen=True)
class SessionGuardrailOverride:
    name: str
    et_hours: tuple[int, ...]
    min_delta: float | None = None
    max_abs_delta: float | None = None
    up_max_buy_price: float | None = None
    down_max_buy_price: float | None = None
    maker_improve_ticks: int | None = None

    @property
    def session_name(self) -> str:
        return self.name


def _session_guardrail_sort_key(override: SessionGuardrailOverride) -> tuple[int, tuple[int, ...], str]:
    return (len(tuple(sorted(override.et_hours))), tuple(sorted(override.et_hours)), override.session_name)


def order_session_guardrail_overrides(
    overrides: Iterable[SessionGuardrailOverride],
) -> tuple[SessionGuardrailOverride, ...]:
    return tuple(sorted(tuple(overrides), key=_session_guardrail_sort_key))


def _load_json_array_file(path_value: str) -> list[Any]:
    path_text = str(path_value or "").strip()
    if not path_text:
        return []
    path = Path(path_text)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_json_list(raw)


def parse_session_guardrail_overrides(value: Any) -> tuple[SessionGuardrailOverride, ...]:
    parsed = parse_json_list(value)
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
        maker_improve_ticks = _safe_float(profile.get("maker_improve_ticks"), None)
        parsed_ticks = int(maker_improve_ticks) if maker_improve_ticks is not None and maker_improve_ticks >= 0 else None
        overrides.append(
            SessionGuardrailOverride(
                name=name,
                et_hours=tuple(hours),
                min_delta=_normalized_env_optional_float(profile.get("min_delta")),
                max_abs_delta=_normalized_env_optional_float(profile.get("max_abs_delta")),
                up_max_buy_price=_normalized_env_optional_float(profile.get("up_max_buy_price")),
                down_max_buy_price=_normalized_env_optional_float(profile.get("down_max_buy_price")),
                maker_improve_ticks=parsed_ticks,
            )
        )
    return order_session_guardrail_overrides(overrides)


def load_session_guardrail_overrides(
    *,
    inline_json: str,
    path_value: str,
    legacy_json: str,
) -> tuple[SessionGuardrailOverride, ...]:
    inline = str(inline_json or "").strip()
    if inline:
        return parse_session_guardrail_overrides(inline)
    from_path = _load_json_array_file(path_value)
    if from_path:
        return parse_session_guardrail_overrides(from_path)
    return parse_session_guardrail_overrides(legacy_json)


def _window_dt_et(window_start_ts: int) -> datetime | None:
    if int(window_start_ts or 0) <= 0:
        return None
    return datetime.fromtimestamp(int(window_start_ts), tz=timezone.utc).astimezone(ET_ZONE)


def active_session_guardrail_override(
    cfg: "MakerConfig",
    *,
    window_start_ts: int,
) -> SessionGuardrailOverride | None:
    dt_et = _window_dt_et(window_start_ts)
    if dt_et is None:
        return None
    matches = [
        override for override in cfg.session_guardrail_overrides if dt_et.hour in override.et_hours
    ]
    return matches[0] if matches else None


def session_guardrail_reason(
    override: SessionGuardrailOverride | None,
    *,
    window_start_ts: int,
) -> str | None:
    if override is None:
        return None
    dt_et = _window_dt_et(window_start_ts)
    hour = dt_et.hour if dt_et is not None else "na"
    return (
        f"session_policy name={override.session_name} hour_et={hour} "
        f"min_delta={override.min_delta} "
        f"max_abs_delta={override.max_abs_delta} "
        f"up_max={override.up_max_buy_price} down_max={override.down_max_buy_price} "
        f"maker_ticks={override.maker_improve_ticks}"
    )


def _round_down_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        return round(price, 4)
    tick = Decimal(str(tick_size))
    steps = (Decimal(str(price)) / tick).to_integral_value(rounding=ROUND_FLOOR)
    return float(steps * tick)


def _round_up(value: float, decimals: int = 2) -> float:
    scale = 10 ** max(0, int(decimals))
    return math.ceil(max(0.0, float(value)) * scale - 1e-12) / scale


def _round_down(value: float, decimals: int = 2) -> float:
    scale = 10 ** max(0, int(decimals))
    return math.floor(max(0.0, float(value)) * scale + 1e-12) / scale


def clob_min_order_size(price: float, *, min_shares: float = CLOB_HARD_MIN_SHARES) -> float:
    price = max(0.0, float(price))
    required = max(float(min_shares), (CLOB_HARD_MIN_NOTIONAL_USD / price) if price > 0.0 else float(min_shares))
    return _round_up(required, decimals=2)


def _parse_order_size(value: Any) -> float | None:
    parsed = _safe_float(value, None)
    if parsed is None:
        return None
    text = str(value).strip().lower()
    if text and "." not in text and "e" not in text and abs(parsed) > 1000:
        # Official docs have shown both human-readable strings and 1e6-scaled
        # integers for order sizes. This bot only trades a few shares, so very
        # large integer payloads are safely treated as fixed-point quantities.
        return float(parsed) / 1_000_000.0
    return float(parsed)


def market_slug_for_window(window_start_ts: int) -> str:
    return f"{MARKET_SLUG_PREFIX}-{int(window_start_ts)}"


def direction_from_prices(open_price: float, current_price: float, min_delta: float) -> tuple[str | None, float]:
    if open_price <= 0:
        return None, 0.0
    delta = (current_price - open_price) / open_price
    if abs(delta) < min_delta:
        return None, delta
    return ("UP" if delta > 0 else "DOWN"), delta


def choose_maker_buy_price(
    *,
    best_bid: float | None,
    best_ask: float | None,
    max_price: float,
    min_price: float,
    tick_size: float,
    aggression_ticks: int = 1,
    post_only_safety_ticks: int = 0,
) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    if best_ask > max_price:
        return None
    if best_ask <= 0 or best_bid < 0:
        return None

    min_valid = _round_down_to_tick(min_price, tick_size)
    safety_ticks = max(0, int(post_only_safety_ticks))
    max_valid = _round_down_to_tick(
        min(max_price, best_ask - ((1 + safety_ticks) * tick_size)),
        tick_size,
    )
    if max_valid <= 0 or max_valid < min_valid:
        return None

    # Stay maker: bid below best ask. Improve by one tick from current best bid.
    quote_ticks = max(0, int(aggression_ticks))
    candidate = _round_down_to_tick(
        best_bid + ((quote_ticks - safety_ticks) * tick_size),
        tick_size,
    )
    price = min(max(candidate, min_valid), max_valid)
    if price >= best_ask:
        return None
    return price


def effective_max_buy_price(
    cfg: "MakerConfig",
    direction: str,
    *,
    session_override: SessionGuardrailOverride | None = None,
) -> float:
    normalized = str(direction or "").strip().upper()
    base = float(cfg.max_buy_price)
    if normalized == "UP":
        if cfg.up_max_buy_price is not None:
            base = float(cfg.up_max_buy_price)
        if session_override and session_override.up_max_buy_price is not None:
            return min(base, float(session_override.up_max_buy_price))
        return base
    if normalized == "DOWN":
        if cfg.down_max_buy_price is not None:
            base = float(cfg.down_max_buy_price)
        if session_override and session_override.down_max_buy_price is not None:
            return min(base, float(session_override.down_max_buy_price))
        return base
    return base


def summarize_recent_direction_regime(
    rows: list[dict[str, Any]],
    *,
    default_quote_ticks: int,
    weaker_direction_quote_ticks: int,
    min_fills_per_direction: int,
    min_pnl_gap_usd: float,
    enable_one_sided_guardrail: bool,
    one_sided_min_pnl_gap_usd: float,
) -> dict[str, Any] | None:
    if not rows:
        return None

    direction_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        direction = str(row.get("direction") or "").strip().upper()
        if direction not in {"UP", "DOWN"}:
            continue
        direction_groups.setdefault(direction, []).append(row)

    if not direction_groups:
        return None

    by_direction = sorted(
        (_rollup_trade_group(group_rows, label=direction) for direction, group_rows in direction_groups.items()),
        key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
    )
    regime = {
        "fills_considered": sum(item["fills"] for item in by_direction),
        "default_quote_ticks": max(0, int(default_quote_ticks)),
        "weaker_direction_quote_ticks": max(0, int(weaker_direction_quote_ticks)),
        "min_fills_per_direction": max(1, int(min_fills_per_direction)),
        "min_pnl_gap_usd": round(max(0.0, float(min_pnl_gap_usd)), 4),
        "enable_one_sided_guardrail": bool(enable_one_sided_guardrail),
        "one_sided_min_pnl_gap_usd": round(max(0.0, float(one_sided_min_pnl_gap_usd)), 4),
        "by_direction": by_direction,
        "triggered": False,
        "trigger_reason": "insufficient_directions",
        "direction_quote_ticks": {},
        "directional_mode": "two_sided",
        "allowed_directions": [item["label"] for item in by_direction],
        "suppressed_direction": None,
        "one_sided_triggered": False,
        "one_sided_trigger_reason": "insufficient_directions",
    }
    if len(by_direction) < 2:
        return regime

    favored = by_direction[0]
    weaker = by_direction[1]
    pnl_gap = round(favored["pnl_usd"] - weaker["pnl_usd"], 4)
    regime.update(
        {
            "favored_direction": favored["label"],
            "weaker_direction": weaker["label"],
            "pnl_gap_usd": pnl_gap,
        }
    )

    min_fills = regime["min_fills_per_direction"]
    if favored["fills"] < min_fills or weaker["fills"] < min_fills:
        regime["trigger_reason"] = "insufficient_fills"
        regime["one_sided_trigger_reason"] = "insufficient_fills"
        return regime
    if favored["avg_pnl_usd"] <= weaker["avg_pnl_usd"]:
        regime["trigger_reason"] = "no_avg_pnl_edge"
        regime["one_sided_trigger_reason"] = "no_avg_pnl_edge"
        return regime
    if pnl_gap < regime["min_pnl_gap_usd"]:
        regime["trigger_reason"] = "pnl_gap_below_threshold"
        regime["one_sided_trigger_reason"] = "pnl_gap_below_threshold"
        return regime

    regime["triggered"] = True
    regime["trigger_reason"] = "weaker_direction_quote_tightened"
    regime["direction_quote_ticks"] = {
        favored["label"]: regime["default_quote_ticks"],
        weaker["label"]: regime["weaker_direction_quote_ticks"],
    }
    regime["one_sided_trigger_reason"] = "disabled" if not enable_one_sided_guardrail else "pnl_gap_below_one_sided_threshold"
    if enable_one_sided_guardrail and pnl_gap >= regime["one_sided_min_pnl_gap_usd"]:
        regime["one_sided_triggered"] = True
        regime["one_sided_trigger_reason"] = "weaker_direction_suppressed"
        regime["directional_mode"] = "one_sided"
        regime["suppressed_direction"] = weaker["label"]
        regime["allowed_directions"] = [favored["label"]]
    return regime


def effective_quote_ticks(
    cfg: "MakerConfig",
    direction: str,
    *,
    session_override: SessionGuardrailOverride | None = None,
    recent_regime: dict[str, Any] | None = None,
) -> int:
    normalized = str(direction or "").strip().upper()
    base_ticks = max(0, int(cfg.maker_improve_ticks))
    if session_override and session_override.maker_improve_ticks is not None:
        base_ticks = min(base_ticks, max(0, int(session_override.maker_improve_ticks)))
    if not recent_regime or not recent_regime.get("triggered"):
        return base_ticks
    override = (recent_regime.get("direction_quote_ticks") or {}).get(normalized)
    if override is None:
        return base_ticks
    return min(base_ticks, max(0, int(override)))


def calc_trade_size_usd(bankroll_usd: float, risk_fraction: float, max_trade_usd: float) -> float:
    if bankroll_usd <= 0 or risk_fraction <= 0 or max_trade_usd <= 0:
        return 0.0
    return round(min(bankroll_usd * risk_fraction, max_trade_usd), 2)


def deterministic_fill(window_start_ts: int, fill_probability: float) -> bool:
    p = max(0.0, min(1.0, fill_probability))
    digest = hashlib.sha256(str(window_start_ts).encode("utf-8")).hexdigest()
    sample = int(digest[:8], 16) / 0xFFFFFFFF
    return sample < p


def _normalize_outcome_label(label: str) -> str:
    text = (label or "").strip().lower()
    if not text:
        return ""
    if text in {"up", "yes", "true", "higher"}:
        return "UP"
    if text in {"down", "no", "false", "lower"}:
        return "DOWN"
    if "up" in text or "above" in text or "higher" in text:
        return "UP"
    if "down" in text or "below" in text or "lower" in text:
        return "DOWN"
    return text.upper()


def choose_token_id_for_direction(market: dict[str, Any], direction: str) -> str | None:
    want = direction.upper()

    tokens = market.get("tokens")
    if isinstance(tokens, list):
        for t in tokens:
            if not isinstance(t, dict):
                continue
            label = _normalize_outcome_label(str(t.get("outcome", "")))
            token_id = str(t.get("token_id") or t.get("clobTokenId") or t.get("id") or "")
            if label == want and token_id:
                return token_id

    outcomes = parse_json_list(market.get("outcomes"))
    token_ids = parse_json_list(market.get("clobTokenIds"))
    if outcomes and token_ids and len(outcomes) == len(token_ids):
        for out, tid in zip(outcomes, token_ids):
            if _normalize_outcome_label(str(out)) == want:
                token_id = str(tid)
                if token_id:
                    return token_id
        # Fallback for classic binary ordering: index 0=UP, 1=DOWN.
        if len(token_ids) == 2:
            return str(token_ids[0] if want == "UP" else token_ids[1])

    return None


@dataclass
class MakerConfig:
    paper_trading: bool = os.environ.get("BTC5_PAPER_TRADING", "true").lower() in {"1", "true", "yes"}
    bankroll_usd: float = float(os.environ.get("BTC5_BANKROLL_USD", "250"))
    risk_fraction: float = float(os.environ.get("BTC5_RISK_FRACTION", "0.02"))
    max_trade_usd: float = float(os.environ.get("BTC5_MAX_TRADE_USD", "5.00"))
    capital_stage: int | None = _env_stage("BTC5_CAPITAL_STAGE", 1)
    stage1_max_trade_usd: float = float(os.environ.get("BTC5_STAGE1_MAX_TRADE_USD", "10"))
    stage2_max_trade_usd: float = float(os.environ.get("BTC5_STAGE2_MAX_TRADE_USD", "20"))
    stage3_max_trade_usd: float = float(os.environ.get("BTC5_STAGE3_MAX_TRADE_USD", "50"))
    stage1_daily_loss_limit_usd: float | None = _optional_env_float("BTC5_STAGE1_DAILY_LOSS_LIMIT_USD")
    stage2_daily_loss_limit_usd: float | None = _optional_env_float("BTC5_STAGE2_DAILY_LOSS_LIMIT_USD")
    stage3_daily_loss_limit_usd: float | None = _optional_env_float("BTC5_STAGE3_DAILY_LOSS_LIMIT_USD")
    shadow_100_max_trade_usd: float = float(os.environ.get("BTC5_SHADOW_100_MAX_TRADE_USD", "100"))
    shadow_200_max_trade_usd: float = float(os.environ.get("BTC5_SHADOW_200_MAX_TRADE_USD", "200"))
    stage_probe_freshness_max_hours: float = float(os.environ.get("BTC5_STAGE_PROBE_FRESHNESS_MAX_HOURS", "6"))
    stage_order_failed_rate_limit: float = float(os.environ.get("BTC5_STAGE_ORDER_FAILED_RATE_LIMIT", "0.25"))
    min_trade_usd: float = float(os.environ.get("BTC5_MIN_TRADE_USD", "5.00"))
    min_delta: float = float(os.environ.get("BTC5_MIN_DELTA", "0.0003"))
    enable_spread_capture: bool = _env_flag("BTC5_ENABLE_SPREAD_CAPTURE", False)
    max_abs_delta: float | None = _optional_env_float("BTC5_MAX_ABS_DELTA")
    maker_improve_ticks: int = int(os.environ.get("BTC5_MAKER_IMPROVE_TICKS", "1"))
    max_buy_price: float = float(os.environ.get("BTC5_MAX_BUY_PRICE", "0.95"))
    up_max_buy_price: float | None = _optional_env_float("BTC5_UP_MAX_BUY_PRICE")
    down_max_buy_price: float | None = _optional_env_float("BTC5_DOWN_MAX_BUY_PRICE")
    session_policy_json: str = os.environ.get("BTC5_SESSION_POLICY_JSON", "")
    session_policy_path: str = os.environ.get("BTC5_SESSION_POLICY_PATH", "")
    session_overrides_json: str = os.environ.get("BTC5_SESSION_OVERRIDES_JSON", "")
    enable_recent_regime_skew: bool = os.environ.get("BTC5_ENABLE_RECENT_REGIME_SKEW", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    recent_regime_fills: int = int(os.environ.get("BTC5_RECENT_REGIME_FILLS", "12"))
    regime_min_fills_per_direction: int = int(os.environ.get("BTC5_REGIME_MIN_FILLS_PER_DIRECTION", "5"))
    regime_min_pnl_gap_usd: float = float(os.environ.get("BTC5_REGIME_MIN_PNL_GAP_USD", "20.0"))
    regime_weaker_direction_quote_ticks: int = int(
        os.environ.get("BTC5_REGIME_WEAKER_DIRECTION_QUOTE_TICKS", "0")
    )
    enable_recent_regime_one_sided_guardrail: bool = os.environ.get(
        "BTC5_ENABLE_RECENT_REGIME_ONE_SIDED_GUARDRAIL",
        "true",
    ).lower() in {"1", "true", "yes"}
    regime_one_sided_min_pnl_gap_usd: float = float(
        os.environ.get("BTC5_REGIME_ONE_SIDED_MIN_PNL_GAP_USD", "30.0")
    )
    min_buy_price: float = float(os.environ.get("BTC5_MIN_BUY_PRICE", "0.90"))
    tick_size: float = float(os.environ.get("BTC5_TICK_SIZE", "0.01"))
    entry_seconds_before_close: int = int(os.environ.get("BTC5_ENTRY_SECONDS_BEFORE_CLOSE", "10"))
    cancel_seconds_before_close: int = int(os.environ.get("BTC5_CANCEL_SECONDS_BEFORE_CLOSE", "2"))
    daily_loss_limit_usd: float = float(os.environ.get("BTC5_DAILY_LOSS_LIMIT_USD", "247"))
    enable_probe_after_daily_loss: bool = _env_flag("BTC5_ENABLE_PROBE_AFTER_DAILY_LOSS", True)
    enable_probe_after_recent_loss: bool = _env_flag("BTC5_ENABLE_PROBE_AFTER_RECENT_LOSS", True)
    probe_recent_fills: int = int(os.environ.get("BTC5_PROBE_RECENT_FILLS", "8"))
    probe_recent_min_pnl_usd: float = float(os.environ.get("BTC5_PROBE_RECENT_MIN_PNL_USD", "0.0"))
    probe_min_delta_multiplier: float = float(os.environ.get("BTC5_PROBE_MIN_DELTA_MULTIPLIER", "1.0"))
    probe_quote_ticks: int = int(os.environ.get("BTC5_PROBE_QUOTE_TICKS", "0"))
    probe_max_abs_delta: float | None = _optional_env_float("BTC5_PROBE_MAX_ABS_DELTA")
    probe_up_max_buy_price: float | None = _optional_env_float("BTC5_PROBE_UP_MAX_BUY_PRICE")
    probe_down_max_buy_price: float | None = _optional_env_float("BTC5_PROBE_DOWN_MAX_BUY_PRICE")
    retry_post_only_cross: bool = _env_flag("BTC5_RETRY_POST_ONLY_CROSS", True)
    retry_post_only_safety_ticks: int = int(os.environ.get("BTC5_RETRY_POST_ONLY_SAFETY_TICKS", "1"))
    paper_fill_probability: float = float(os.environ.get("BTC5_PAPER_FILL_PROBABILITY", "0.20"))
    clob_fee_rate_bps: int = int(os.environ.get("BTC5_CLOB_FEE_RATE_BPS", "0"))
    request_timeout_sec: float = float(os.environ.get("BTC5_REQUEST_TIMEOUT_SEC", "8"))

    binance_ws_url: str = os.environ.get("BTC5_BINANCE_WS_URL", "wss://stream.binance.com:9443/ws/btcusdt@trade")
    binance_klines_url: str = os.environ.get(
        "BTC5_BINANCE_KLINES_URL",
        "https://api.binance.com/api/v3/klines",
    )
    binance_ticker_url: str = os.environ.get(
        "BTC5_BINANCE_TICKER_URL",
        "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    )
    binance_symbol: str = str(os.environ.get("BTC5_BINANCE_SYMBOL", "BTCUSDT")).strip().upper() or "BTCUSDT"
    binance_kline_interval: str = (
        str(os.environ.get("BTC5_BINANCE_KLINE_INTERVAL", "5m")).strip().lower() or "5m"
    )
    gamma_markets_url: str = os.environ.get(
        "BTC5_GAMMA_MARKETS_URL",
        "https://gamma-api.polymarket.com/markets",
    )
    clob_book_url: str = os.environ.get(
        "BTC5_CLOB_BOOK_URL",
        "https://clob.polymarket.com/book",
    )
    db_path: Path = Path(os.environ.get("BTC5_DB_PATH", str(DEFAULT_DB_PATH)))
    session_guardrail_overrides: tuple[SessionGuardrailOverride, ...] = field(init=False, default_factory=tuple)

    def __post_init__(self) -> None:
        self.session_guardrail_overrides = load_session_guardrail_overrides(
            inline_json=self.session_policy_json,
            path_value=self.session_policy_path,
            legacy_json=self.session_overrides_json,
        )
        if self.stage1_daily_loss_limit_usd is None:
            self.stage1_daily_loss_limit_usd = float(self.daily_loss_limit_usd)
        if self.stage2_daily_loss_limit_usd is None:
            self.stage2_daily_loss_limit_usd = float(self.daily_loss_limit_usd)
        if self.stage3_daily_loss_limit_usd is None:
            self.stage3_daily_loss_limit_usd = float(self.daily_loss_limit_usd)

    @property
    def effective_max_trade_usd(self) -> float:
        if self.capital_stage is None:
            return max(0.0, float(self.max_trade_usd))
        if self.capital_stage == 2:
            return max(0.0, float(self.stage2_max_trade_usd))
        if self.capital_stage == 3:
            return max(0.0, float(self.stage3_max_trade_usd))
        if self.capital_stage == 1:
            return max(0.0, float(self.stage1_max_trade_usd))
        return max(0.0, float(self.max_trade_usd))

    @property
    def effective_daily_loss_limit_usd(self) -> float:
        if self.capital_stage is None:
            return max(0.0, float(self.daily_loss_limit_usd))
        if self.capital_stage == 2:
            return max(0.0, float(self.stage2_daily_loss_limit_usd))
        if self.capital_stage == 3:
            return max(0.0, float(self.stage3_daily_loss_limit_usd))
        return max(0.0, float(self.stage1_daily_loss_limit_usd))


@dataclass(frozen=True)
class PlacementResult:
    order_id: str | None
    success: bool
    status: str | None
    error_msg: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveOrderState:
    order_id: str
    status: str | None
    original_size: float | None
    size_matched: float
    price: float | None
    raw: dict[str, Any] | None = None

    @property
    def normalized_status(self) -> str:
        return (self.status or "").strip().lower()

    @property
    def is_cancelled(self) -> bool:
        return self.normalized_status in {"cancelled", "canceled"}

    @property
    def is_live(self) -> bool:
        return self.normalized_status in {"live", "open", "delayed", "unmatched", "pending"}

    @property
    def fully_filled(self) -> bool:
        if self.normalized_status in {"matched", "filled", "completed"}:
            return self.size_matched > 0
        if self.original_size is None:
            return False
        return self.size_matched + 1e-9 >= self.original_size and self.size_matched > 0

    @property
    def partially_filled(self) -> bool:
        return self.size_matched > 0 and not self.fully_filled


class TradeDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS window_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    window_start_ts INTEGER NOT NULL UNIQUE,
                    window_end_ts INTEGER NOT NULL,
                    slug TEXT NOT NULL,
                    decision_ts INTEGER NOT NULL,
                    direction TEXT,
                    open_price REAL,
                    current_price REAL,
                    delta REAL,
                    token_id TEXT,
                    best_bid REAL,
                    best_ask REAL,
                    order_price REAL,
                    trade_size_usd REAL,
                    shares REAL,
                    order_id TEXT,
                    order_status TEXT NOT NULL,
                    filled INTEGER,
                    reason TEXT,
                    edge_tier TEXT,
                    sizing_reason_tags TEXT,
                    loss_cluster_suppressed INTEGER,
                    session_policy_name TEXT,
                    effective_stage INTEGER,
                    resolved_side TEXT,
                    won INTEGER,
                    pnl_usd REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_window_trades_decision_ts
                    ON window_trades(decision_ts);
                """
            )
            existing = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(window_trades)").fetchall()
            }
            for column_name, column_type in (
                ("edge_tier", "TEXT"),
                ("sizing_reason_tags", "TEXT"),
                ("loss_cluster_suppressed", "INTEGER"),
                ("session_policy_name", "TEXT"),
                ("effective_stage", "INTEGER"),
            ):
                if column_name not in existing:
                    conn.execute(f"ALTER TABLE window_trades ADD COLUMN {column_name} {column_type}")

    def window_exists(self, window_start_ts: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM window_trades WHERE window_start_ts = ?",
                (int(window_start_ts),),
            ).fetchone()
        return row is not None

    def upsert_window(self, row: dict[str, Any]) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "window_start_ts": int(row["window_start_ts"]),
            "window_end_ts": int(row["window_end_ts"]),
            "slug": str(row.get("slug") or market_slug_for_window(int(row["window_start_ts"]))),
            "decision_ts": int(row.get("decision_ts", time.time())),
            "direction": row.get("direction"),
            "open_price": row.get("open_price"),
            "current_price": row.get("current_price"),
            "delta": row.get("delta"),
            "token_id": row.get("token_id"),
            "best_bid": row.get("best_bid"),
            "best_ask": row.get("best_ask"),
            "order_price": row.get("order_price"),
            "trade_size_usd": row.get("trade_size_usd"),
            "shares": row.get("shares"),
            "order_id": row.get("order_id"),
            "order_status": row.get("order_status", "unknown"),
            "filled": row.get("filled"),
            "reason": row.get("reason"),
            "edge_tier": row.get("edge_tier"),
            "sizing_reason_tags": _serialize_json_list(row.get("sizing_reason_tags")),
            "loss_cluster_suppressed": (
                None
                if row.get("loss_cluster_suppressed") is None
                else int(bool(row.get("loss_cluster_suppressed")))
            ),
            "session_policy_name": row.get("session_policy_name"),
            "effective_stage": row.get("effective_stage"),
            "resolved_side": row.get("resolved_side"),
            "won": row.get("won"),
            "pnl_usd": row.get("pnl_usd"),
            "created_at": row.get("created_at") or now_iso,
            "updated_at": now_iso,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO window_trades (
                    window_start_ts, window_end_ts, slug, decision_ts, direction,
                    open_price, current_price, delta, token_id, best_bid, best_ask,
                    order_price, trade_size_usd, shares, order_id, order_status,
                    filled, reason, edge_tier, sizing_reason_tags, loss_cluster_suppressed,
                    session_policy_name, effective_stage, resolved_side, won, pnl_usd,
                    created_at, updated_at
                ) VALUES (
                    :window_start_ts, :window_end_ts, :slug, :decision_ts, :direction,
                    :open_price, :current_price, :delta, :token_id, :best_bid, :best_ask,
                    :order_price, :trade_size_usd, :shares, :order_id, :order_status,
                    :filled, :reason, :edge_tier, :sizing_reason_tags, :loss_cluster_suppressed,
                    :session_policy_name, :effective_stage, :resolved_side, :won, :pnl_usd,
                    :created_at, :updated_at
                )
                ON CONFLICT(window_start_ts) DO UPDATE SET
                    decision_ts=excluded.decision_ts,
                    direction=excluded.direction,
                    open_price=excluded.open_price,
                    current_price=excluded.current_price,
                    delta=excluded.delta,
                    token_id=excluded.token_id,
                    best_bid=excluded.best_bid,
                    best_ask=excluded.best_ask,
                    order_price=excluded.order_price,
                    trade_size_usd=excluded.trade_size_usd,
                    shares=excluded.shares,
                    order_id=excluded.order_id,
                    order_status=excluded.order_status,
                    filled=excluded.filled,
                    reason=excluded.reason,
                    edge_tier=excluded.edge_tier,
                    sizing_reason_tags=excluded.sizing_reason_tags,
                    loss_cluster_suppressed=excluded.loss_cluster_suppressed,
                    session_policy_name=excluded.session_policy_name,
                    effective_stage=excluded.effective_stage,
                    resolved_side=excluded.resolved_side,
                    won=excluded.won,
                    pnl_usd=excluded.pnl_usd,
                    updated_at=excluded.updated_at
                """,
                payload,
            )

    def unsettled_rows(self, max_window_start_ts: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM window_trades
                WHERE window_start_ts <= ?
                  AND resolved_side IS NULL
                ORDER BY window_start_ts ASC
                """,
                (int(max_window_start_ts),),
            ).fetchall()
        return rows

    def today_realized_pnl(self) -> float:
        day_start = _day_start_utc_ts()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(pnl_usd), 0.0) AS pnl
                FROM window_trades
                WHERE decision_ts >= ?
                  AND pnl_usd IS NOT NULL
                """,
                (day_start,),
            ).fetchone()
        return float(row["pnl"] if row else 0.0)

    def recent_live_filled(self, *, limit: int) -> list[dict[str, Any]]:
        capped_limit = max(0, int(limit))
        if capped_limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    direction,
                    order_price,
                    pnl_usd
                FROM window_trades
                WHERE order_status = 'live_filled'
                ORDER BY id DESC
                LIMIT ?
                """,
                (capped_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def trailing_live_filled_pnl(self, *, limit: int) -> dict[str, Any]:
        rows = self.recent_live_filled(limit=limit)
        return {
            "fills": len(rows),
            "pnl_usd": round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in rows), 4),
        }

    def latest_decision_ts(self) -> int | None:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(decision_ts) AS latest_decision_ts FROM window_trades").fetchone()
        latest = int(row["latest_decision_ts"]) if row and row["latest_decision_ts"] is not None else None
        return latest if latest and latest > 0 else None

    def recent_execution_drag(self, *, limit: int = 120) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT order_status
                FROM window_trades
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        statuses = [str(row["order_status"] or "").strip().lower() for row in rows]
        total = len(statuses)
        actionable = [status for status in statuses if status in ACTIONABLE_ORDER_STATUSES]
        skip_price = sum(1 for status in statuses if status == "skip_price_outside_guardrails")
        order_failed = sum(1 for status in statuses if status == "live_order_failed")
        cancelled_unfilled = sum(1 for status in statuses if status == "live_cancelled_unfilled")
        return {
            "lookback_windows": total,
            "actionable_windows": len(actionable),
            "live_filled": sum(1 for status in statuses if status == "live_filled"),
            "live_partial_fill_cancelled": sum(
                1 for status in statuses if status == "live_partial_fill_cancelled"
            ),
            "live_partial_fill_open": sum(1 for status in statuses if status == "live_partial_fill_open"),
            "skip_price_outside_guardrails": skip_price,
            "live_order_failed": order_failed,
            "live_cancelled_unfilled": cancelled_unfilled,
            "order_failed_rate": round(order_failed / len(actionable), 6) if actionable else None,
        }

    def intraday_live_summary(self, *, now_ts: float | None = None) -> dict[str, Any]:
        day_start = _day_start_utc_ts(now_ts)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    decision_ts,
                    direction,
                    order_price,
                    order_status,
                    filled,
                    reason,
                    won,
                    pnl_usd
                FROM window_trades
                WHERE decision_ts >= ?
                ORDER BY decision_ts ASC, id ASC
                """,
                (day_start,),
            ).fetchall()
        day_rows = [dict(row) for row in rows]
        live_filled_rows = [
            row for row in day_rows if _is_live_filled_status(row.get("order_status"), row.get("filled"))
        ]
        skip_counts = Counter(
            str(row.get("order_status") or "").strip().lower()
            for row in day_rows
            if str(row.get("order_status") or "").strip().lower().startswith("skip_")
        )
        order_failure_counts: Counter[str] = Counter()
        for row in day_rows:
            for attribution in _infer_row_attributions(row).values():
                order_failure_counts[attribution] += 1

        direction_groups: dict[str, list[dict[str, Any]]] = {}
        price_bucket_groups: dict[str, list[dict[str, Any]]] = {}
        for row in live_filled_rows:
            direction = str(row.get("direction") or "UNKNOWN").strip().upper() or "UNKNOWN"
            direction_groups.setdefault(direction, []).append(row)
            price_bucket_groups.setdefault(_btc5_price_bucket(row.get("order_price")), []).append(row)

        direction_performance = sorted(
            (_rollup_trade_group(group_rows, label=direction) for direction, group_rows in direction_groups.items()),
            key=lambda item: (-item["pnl_usd"], -item["fills"], item["label"]),
        )
        bucket_order = {"<0.49": 0, "0.49": 1, "0.50": 2, "0.51+": 3, "unknown": 99}
        price_bucket_performance = sorted(
            (_rollup_trade_group(group_rows, label=bucket) for bucket, group_rows in price_bucket_groups.items()),
            key=lambda item: bucket_order.get(item["label"], 99),
        )
        settled_live = [row for row in live_filled_rows if _won_flag(row.get("won")) is not None]
        wins = sum(1 for row in settled_live if _won_flag(row.get("won")) == 1)

        def _recent_live_pnl(limit: int) -> float:
            recent_rows = self.recent_live_filled(limit=limit)
            return round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in recent_rows), 4)

        best_direction_today = direction_performance[0] if direction_performance else None
        best_price_bucket_today = max(
            price_bucket_performance,
            key=lambda item: (item["pnl_usd"], item["fills"], -bucket_order.get(item["label"], 99)),
            default=None,
        )
        return {
            "filled_rows_today": len(live_filled_rows),
            "filled_pnl_usd_today": round(
                sum(_safe_float(row.get("pnl_usd"), 0.0) for row in live_filled_rows),
                4,
            ),
            "win_rate_today": round(wins / len(settled_live), 4) if settled_live else 0.0,
            "recent_5_pnl_usd": _recent_live_pnl(5),
            "recent_12_pnl_usd": _recent_live_pnl(12),
            "recent_20_pnl_usd": _recent_live_pnl(20),
            "skip_price_count": int(skip_counts.get("skip_price_outside_guardrails", 0)),
            "order_failed_count": sum(
                1 for row in day_rows if str(row.get("order_status") or "").strip().lower() == "live_order_failed"
            ),
            "cancelled_unfilled_count": sum(
                1
                for row in day_rows
                if str(row.get("order_status") or "").strip().lower() == "live_cancelled_unfilled"
            ),
            "skip_counts": dict(sorted(skip_counts.items())),
            "order_failure_counts": dict(sorted(order_failure_counts.items())),
            "direction_performance_today": direction_performance,
            "price_bucket_performance_today": price_bucket_performance,
            "best_direction_today": best_direction_today,
            "best_price_bucket_today": best_price_bucket_today,
        }

    def today_notional_usd(self, *, now_ts: float | None = None) -> float:
        day_start = _day_start_utc_ts(now_ts)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(trade_size_usd), 0.0) AS notional
                FROM window_trades
                WHERE decision_ts >= ?
                """,
                (day_start,),
            ).fetchone()
        return round(float(row["notional"] if row else 0.0), 4)

    def status_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS windows_seen,
                    SUM(CASE WHEN order_id IS NOT NULL THEN 1 ELSE 0 END) AS orders_placed,
                    SUM(CASE WHEN filled = 1 THEN 1 ELSE 0 END) AS fills,
                    SUM(CASE WHEN filled = 1 AND won IS NOT NULL THEN 1 ELSE 0 END) AS settled_fills,
                    SUM(CASE WHEN filled = 1 AND won = 1 THEN 1 ELSE 0 END) AS wins,
                    COALESCE(SUM(pnl_usd), 0.0) AS total_pnl
                FROM window_trades
                """
            ).fetchone()
        orders_placed = int(totals["orders_placed"] or 0)
        fills = int(totals["fills"] or 0)
        settled_fills = int(totals["settled_fills"] or 0)
        wins = int(totals["wins"] or 0)
        return {
            "windows_seen": int(totals["windows_seen"] or 0),
            "orders_placed": orders_placed,
            "fills": fills,
            "fill_rate": (fills / orders_placed) if orders_placed else 0.0,
            "settled_fills": settled_fills,
            "wins": wins,
            "win_rate": (wins / settled_fills) if settled_fills else 0.0,
            "total_pnl_usd": float(totals["total_pnl"] or 0.0),
            "today_pnl_usd": self.today_realized_pnl(),
            "today_notional_usd": self.today_notional_usd(),
            "intraday_live_summary": self.intraday_live_summary(),
        }


class BinancePriceCache:
    def __init__(self, maxlen: int = 6000):
        self._ticks: deque[tuple[int, float]] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def add_tick(self, ts_sec: int, price: float) -> None:
        async with self._lock:
            self._ticks.append((ts_sec, price))

    async def latest(self) -> tuple[int, float] | None:
        async with self._lock:
            if not self._ticks:
                return None
            return self._ticks[-1]

    async def open_price_for_window(self, window_start_ts: int) -> float | None:
        upper = window_start_ts + 30
        async with self._lock:
            if not self._ticks:
                return None
            for ts, px in self._ticks:
                if window_start_ts <= ts <= upper:
                    return px
            # Fallback: nearest observed tick around the boundary.
            nearest = min(self._ticks, key=lambda item: abs(item[0] - window_start_ts))
            if abs(nearest[0] - window_start_ts) <= 180:
                return nearest[1]
        return None


class BinanceTradeFeed:
    def __init__(self, ws_url: str, cache: BinancePriceCache):
        self.ws_url = ws_url
        self.cache = cache

    async def run(self, stop_event: asyncio.Event) -> None:
        if websockets is None:
            logger.warning("websockets package missing; Binance trade stream disabled")
            return
        backoff = 1.0
        while not stop_event.is_set():
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("Connected to Binance trade stream")
                    backoff = 1.0
                    async for raw in ws:
                        if stop_event.is_set():
                            break
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        price = _safe_float(payload.get("p"), None)
                        event_ms = _safe_float(payload.get("E"), None)
                        if price is None or event_ms is None:
                            continue
                        ts = int(event_ms // 1000)
                        await self.cache.add_tick(ts, float(price))
            except Exception as exc:
                logger.warning("Binance WS reconnect in %.1fs (%s)", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)


class MarketHttpClient:
    def __init__(self, cfg: MakerConfig, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.session = session

    async def fetch_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        # Primary path: explicit slug query.
        try:
            async with self.session.get(
                self.cfg.gamma_markets_url,
                params={"slug": slug, "limit": 5},
                timeout=timeout,
            ) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    markets = payload if isinstance(payload, list) else payload.get("data", [])
                    for m in markets:
                        if isinstance(m, dict) and str(m.get("slug", "")) == slug:
                            return m
        except Exception as exc:
            logger.warning("Gamma slug lookup failed for %s: %s", slug, exc)

        # Fallback: scan latest markets and match exact slug.
        try:
            async with self.session.get(
                self.cfg.gamma_markets_url,
                params={"limit": 400, "active": "true"},
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                markets = payload if isinstance(payload, list) else payload.get("data", [])
                for m in markets:
                    if isinstance(m, dict) and str(m.get("slug", "")) == slug:
                        return m
        except Exception as exc:
            logger.warning("Gamma fallback scan failed: %s", exc)
        return None

    async def fetch_book(self, token_id: str) -> dict[str, Any] | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        try:
            async with self.session.get(
                self.cfg.clob_book_url,
                params={"token_id": token_id},
                timeout=timeout,
            ) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                return payload if isinstance(payload, dict) else None
        except Exception as exc:
            logger.warning("Book fetch failed for %s: %s", token_id[:12], exc)
            return None

    async def fetch_binance_window_open_close(self, window_start_ts: int) -> tuple[float, float] | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        params = {
            "symbol": self.cfg.binance_symbol,
            "interval": self.cfg.binance_kline_interval,
            "startTime": int(window_start_ts) * 1000,
            "limit": 1,
        }
        try:
            async with self.session.get(self.cfg.binance_klines_url, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                if not isinstance(payload, list) or not payload:
                    return None
                row = payload[0]
                if not isinstance(row, list) or len(row) < 5:
                    return None
                open_px = _safe_float(row[1], None)
                close_px = _safe_float(row[4], None)
                if open_px is None or close_px is None:
                    return None
                return float(open_px), float(close_px)
        except Exception as exc:
            logger.warning("Binance kline fetch failed: %s", exc)
            return None

    async def fetch_binance_spot(self) -> float | None:
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        try:
            async with self.session.get(self.cfg.binance_ticker_url, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json()
                return _safe_float(payload.get("price"), None)
        except Exception:
            return None

    @staticmethod
    def top_of_book(book: dict[str, Any]) -> tuple[float | None, float | None]:
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        def _best(levels: Iterable[dict[str, Any]], side: str) -> float | None:
            prices: list[float] = []
            for level in levels:
                if not isinstance(level, dict):
                    continue
                px = _safe_float(level.get("price"), None)
                if px is None:
                    continue
                prices.append(float(px))
            if not prices:
                return None
            return max(prices) if side == "bid" else min(prices)

        return _best(bids, "bid"), _best(asks, "ask")


class CLOBExecutor:
    def __init__(self, cfg: MakerConfig):
        self.cfg = cfg
        self.client = None

    @staticmethod
    def _signature_type() -> int:
        raw = os.environ.get("JJ_CLOB_SIGNATURE_TYPE", "1")
        parsed = parse_signature_type(raw, default=1)
        if str(raw).strip() not in {"0", "1", "2"}:
            logger.warning("Invalid JJ_CLOB_SIGNATURE_TYPE=%r; defaulting to 1", raw)
        return parsed

    def _init_client(self) -> Any:
        try:
            import py_clob_client  # noqa: F401
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError("py_clob_client is required for live mode") from exc

        private_key = os.environ.get("POLY_PRIVATE_KEY", "") or os.environ.get("POLYMARKET_PK", "")
        safe_address = os.environ.get("POLY_SAFE_ADDRESS", "") or os.environ.get("POLYMARKET_FUNDER", "")
        if not private_key:
            raise RuntimeError("POLY_PRIVATE_KEY or POLYMARKET_PK is required for live mode")
        if not safe_address:
            raise RuntimeError("POLY_SAFE_ADDRESS or POLYMARKET_FUNDER is required for live mode")
        client, _, _ = build_authenticated_clob_client(
            private_key=private_key,
            safe_address=safe_address,
            configured_signature_type=self._signature_type(),
            logger=logger,
            log_prefix="BTC5",
        )
        return client

    def ensure_client(self) -> Any:
        if self.client is None:
            self.client = self._init_client()
        return self.client

    def place_post_only_buy(self, token_id: str, price: float, shares: float) -> PlacementResult:
        client = self.ensure_client()
        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError("py_clob_client imports unavailable at order time") from exc

        order_sig = inspect.signature(OrderArgs)
        kwargs: dict[str, Any] = {
            "token_id": token_id,
            "price": round(price, 2),
            "size": _round_up(shares, 2),
            "side": BUY,
        }

        signed = client.create_order(OrderArgs(**kwargs))
        try:
            resp = client.post_order(signed, OrderType.GTC, post_only=True)
        except TypeError as exc:
            raise RuntimeError(
                "py_clob_client.post_order must support post_only=True for maker-only execution; "
                "upgrade the client dependency"
            ) from exc

        if isinstance(resp, dict):
            order_id = str(resp.get("orderID") or resp.get("id") or "").strip() or None
            status = str(resp.get("status") or resp.get("orderStatus") or "").strip().lower() or None
            error_msg = str(resp.get("errorMsg") or resp.get("error") or "").strip() or None
            success = not bool(resp.get("error")) and bool(order_id)
            return PlacementResult(
                order_id=order_id,
                success=success,
                status=status,
                error_msg=error_msg,
                raw=resp,
            )
        return PlacementResult(
            order_id=None,
            success=bool(resp),
            status=None,
            raw={"response": resp},
        )

    def cancel_order(self, order_id: str) -> bool:
        if not order_id:
            return False
        client = self.ensure_client()
        try:
            resp = client.cancel(order_id)
            if isinstance(resp, dict):
                if resp.get("error"):
                    return False
                if resp.get("success") is False:
                    return False
            return True
        except Exception:
            return False

    def get_order_state(self, order_id: str) -> LiveOrderState | None:
        if not order_id:
            return None
        client = self.ensure_client()
        try:
            resp = client.get_order(order_id)
        except Exception:
            return None
        if not isinstance(resp, dict):
            return None

        payload = resp.get("order") if isinstance(resp.get("order"), dict) else resp
        status = str(payload.get("status") or payload.get("order_status") or "").strip() or None
        original_size = _parse_order_size(
            payload.get("original_size") or payload.get("size") or payload.get("order_size")
        )
        size_matched = _parse_order_size(
            payload.get("size_matched") or payload.get("filled_size") or payload.get("size_filled") or 0.0
        ) or 0.0
        price = _safe_float(payload.get("price") or payload.get("avg_price"), None)
        return LiveOrderState(
            order_id=order_id,
            status=status,
            original_size=original_size,
            size_matched=size_matched,
            price=price,
            raw=payload,
        )


class BTC5MinMakerBot:
    def __init__(self, cfg: MakerConfig):
        self.cfg = cfg
        self.db = TradeDB(cfg.db_path)
        self.cache = BinancePriceCache()
        self.clob = CLOBExecutor(cfg)

    def _recent_direction_regime(self) -> dict[str, Any] | None:
        if not self.cfg.enable_recent_regime_skew:
            return None
        rows = self.db.recent_live_filled(limit=self.cfg.recent_regime_fills)
        return summarize_recent_direction_regime(
            rows,
            default_quote_ticks=self.cfg.maker_improve_ticks,
            weaker_direction_quote_ticks=self.cfg.regime_weaker_direction_quote_ticks,
            min_fills_per_direction=self.cfg.regime_min_fills_per_direction,
            min_pnl_gap_usd=self.cfg.regime_min_pnl_gap_usd,
            enable_one_sided_guardrail=self.cfg.enable_recent_regime_one_sided_guardrail,
            one_sided_min_pnl_gap_usd=self.cfg.regime_one_sided_min_pnl_gap_usd,
        )

    def _probe_max_buy_price(self, direction: str) -> float:
        normalized = str(direction or "").strip().upper()
        normal_cap = effective_max_buy_price(self.cfg, normalized)
        if normalized == "UP":
            probe_cap = self.cfg.probe_up_max_buy_price
            if probe_cap is None:
                probe_cap = PROBE_DEFAULT_UP_MAX_BUY_PRICE
            return min(normal_cap, float(probe_cap))
        if normalized == "DOWN":
            probe_cap = self.cfg.probe_down_max_buy_price
            if probe_cap is None:
                probe_cap = PROBE_DEFAULT_DOWN_MAX_BUY_PRICE
            return min(normal_cap, float(probe_cap))
        return normal_cap

    def _loss_cluster_match(
        self,
        *,
        window_start_ts: int,
        direction: str,
        order_price: float,
        delta: float,
    ) -> dict[str, str] | None:
        session_bucket = _btc5_session_bucket(window_start_ts)
        cluster_price_bucket = _btc5_cluster_price_bucket(order_price)
        delta_bucket = _btc5_delta_bucket(delta)
        cluster_key = (
            session_bucket,
            str(direction or "").strip().upper(),
            cluster_price_bucket,
            delta_bucket,
        )
        if cluster_key not in OBSERVED_BTC5_LOSS_CLUSTERS:
            return None
        return {
            "session_name": session_bucket,
            "direction": str(direction or "").strip().upper(),
            "price_bucket": cluster_price_bucket,
            "delta_bucket": delta_bucket,
        }

    @staticmethod
    def _session_override_has_balanced_caps(session_override: SessionGuardrailOverride | None) -> bool:
        if session_override is None:
            return False
        up_cap = _safe_float(session_override.up_max_buy_price, None)
        down_cap = _safe_float(session_override.down_max_buy_price, None)
        if up_cap is None or down_cap is None:
            return False
        return abs(up_cap - down_cap) <= 1e-9

    def _classify_edge_tier(
        self,
        *,
        window_start_ts: int,
        direction: str,
        delta: float,
        order_price: float,
        session_override: SessionGuardrailOverride | None,
        session_policy_name: str | None,
        effective_stage: int,
        recommended_live_stage: int,
        recent_regime: dict[str, Any] | None,
        probe_mode: dict[str, Any] | None,
    ) -> dict[str, Any]:
        dt_et = _window_dt_et(window_start_ts)
        et_hour = dt_et.hour if dt_et is not None else None
        session_bucket = _btc5_session_bucket(window_start_ts)
        order_price_bucket = _btc5_price_bucket(order_price)
        delta_bucket = _btc5_delta_bucket(delta)
        balanced_session_caps = self._session_override_has_balanced_caps(session_override)
        tags = _unique_tags(
            f"session_bucket={session_bucket}",
            f"session_policy_name={session_policy_name or 'none'}",
            f"et_hour={et_hour if et_hour is not None else 'unknown'}",
            f"direction={str(direction or '').strip().upper()}",
            f"order_price_bucket={order_price_bucket}",
            f"delta_bucket={delta_bucket}",
            f"effective_stage={max(1, int(effective_stage or 1))}",
            f"recommended_live_stage={max(1, int(recommended_live_stage or effective_stage or 1))}",
            f"session_caps_balanced={'true' if balanced_session_caps else 'false'}",
            "probe_mode=on" if probe_mode else None,
        )

        suppressed_direction = str((recent_regime or {}).get("suppressed_direction") or "").strip().upper()
        if suppressed_direction and str(direction or "").strip().upper() == suppressed_direction:
            return {
                "edge_tier": "suppressed",
                "loss_cluster_suppressed": True,
                "order_price_bucket": order_price_bucket,
                "delta_bucket": delta_bucket,
                "session_bucket": session_bucket,
                "sizing_reason_tags": _unique_tags(
                    *tags,
                    "recent_regime_one_sided_guardrail",
                    f"suppressed_direction={suppressed_direction}",
                    "edge_tier=suppressed",
                ),
            }

        loss_cluster = self._loss_cluster_match(
            window_start_ts=window_start_ts,
            direction=direction,
            order_price=order_price,
            delta=delta,
        )
        if loss_cluster is not None:
            return {
                "edge_tier": "suppressed",
                "loss_cluster_suppressed": True,
                "order_price_bucket": order_price_bucket,
                "delta_bucket": delta_bucket,
                "session_bucket": session_bucket,
                "sizing_reason_tags": _unique_tags(
                    *tags,
                    "observed_loss_cluster_guardrail",
                    f"loss_cluster_session={loss_cluster['session_name']}",
                    f"loss_cluster_price_bucket={loss_cluster['price_bucket']}",
                    f"loss_cluster_delta_bucket={loss_cluster['delta_bucket']}",
                    "edge_tier=suppressed",
                ),
            }

        if probe_mode:
            return {
                "edge_tier": "exploratory",
                "loss_cluster_suppressed": False,
                "order_price_bucket": order_price_bucket,
                "delta_bucket": delta_bucket,
                "session_bucket": session_bucket,
                "sizing_reason_tags": _unique_tags(
                    *tags,
                    "probe_feedback_guardrail",
                    "edge_tier=exploratory",
                ),
            }

        if (
            session_policy_name == "hour_et_09"
            and str(direction or "").strip().upper() == "DOWN"
            and order_price_bucket in VALIDATED_STRONG_PRICE_BUCKETS
        ):
            return {
                "edge_tier": "strong_validated",
                "loss_cluster_suppressed": False,
                "order_price_bucket": order_price_bucket,
                "delta_bucket": delta_bucket,
                "session_bucket": session_bucket,
                "sizing_reason_tags": _unique_tags(
                    *tags,
                    "validated_session_hour_et_09",
                    "validated_direction_down",
                    "validated_price_bucket_strength",
                    "edge_tier=strong_validated",
                ),
            }

        if (
            session_policy_name == "hour_et_11"
            and balanced_session_caps
            and order_price_bucket in VALIDATED_STRONG_PRICE_BUCKETS
        ):
            return {
                "edge_tier": "strong_validated",
                "loss_cluster_suppressed": False,
                "order_price_bucket": order_price_bucket,
                "delta_bucket": delta_bucket,
                "session_bucket": session_bucket,
                "sizing_reason_tags": _unique_tags(
                    *tags,
                    "validated_session_hour_et_11",
                    "validated_balanced_session_caps",
                    "validated_price_bucket_strength",
                    "edge_tier=strong_validated",
                ),
            }

        if session_policy_name == "hour_et_11" and str(direction or "").strip().upper() == "DOWN":
            return {
                "edge_tier": "exploratory",
                "loss_cluster_suppressed": False,
                "order_price_bucket": order_price_bucket,
                "delta_bucket": delta_bucket,
                "session_bucket": session_bucket,
                "sizing_reason_tags": _unique_tags(
                    *tags,
                    (
                        "hour_11_down_bias_probe_only_guardrail"
                        if not balanced_session_caps
                        else "hour_11_down_bias_exploratory_guardrail"
                    ),
                    "edge_tier=exploratory",
                ),
            }

        return {
            "edge_tier": "standard",
            "loss_cluster_suppressed": False,
            "order_price_bucket": order_price_bucket,
            "delta_bucket": delta_bucket,
            "session_bucket": session_bucket,
            "sizing_reason_tags": _unique_tags(
                *tags,
                "edge_tier=standard",
            ),
        }

    def _trade_size_for_edge_tier(
        self,
        *,
        edge_tier: str,
        effective_max_trade_usd: float,
    ) -> dict[str, Any]:
        stage_cap_usd = round(max(0.0, float(effective_max_trade_usd)), 2)
        standard_size_usd = calc_trade_size_usd(
            self.cfg.bankroll_usd,
            self.cfg.risk_fraction,
            stage_cap_usd,
        )
        if edge_tier == "strong_validated":
            return {
                "target_size_usd": stage_cap_usd,
                "size_cap_usd": stage_cap_usd,
                "sizing_reason_tags": _unique_tags(
                    "sizing_mode=full_stage_cap",
                    f"stage_cap_usd={stage_cap_usd:.2f}",
                    f"standard_size_usd={standard_size_usd:.2f}",
                ),
            }
        if edge_tier == "exploratory":
            exploratory_cap_usd = round(stage_cap_usd * 0.5, 2)
            exploratory_size_usd = calc_trade_size_usd(
                self.cfg.bankroll_usd,
                self.cfg.risk_fraction * 0.5,
                exploratory_cap_usd,
            )
            return {
                "target_size_usd": exploratory_size_usd,
                "size_cap_usd": exploratory_cap_usd,
                "sizing_reason_tags": _unique_tags(
                    "sizing_mode=exploratory_half_cap",
                    f"stage_cap_usd={stage_cap_usd:.2f}",
                    f"exploratory_cap_usd={exploratory_cap_usd:.2f}",
                    f"standard_size_usd={standard_size_usd:.2f}",
                ),
            }
        if edge_tier == "standard":
            return {
                "target_size_usd": standard_size_usd,
                "size_cap_usd": stage_cap_usd,
                "sizing_reason_tags": _unique_tags(
                    "sizing_mode=standard_risk_fraction",
                    f"stage_cap_usd={stage_cap_usd:.2f}",
                    f"standard_size_usd={standard_size_usd:.2f}",
                ),
            }
        return {
            "target_size_usd": 0.0,
            "size_cap_usd": 0.0,
            "sizing_reason_tags": ["sizing_mode=suppressed"],
        }

    def _configured_live_stage(self) -> int:
        stage = self.cfg.capital_stage
        if stage in LIVE_STAGE_IDS:
            return int(stage)
        return 1

    def _max_trade_for_stage(self, stage: int) -> float:
        if stage >= 3:
            return float(self.cfg.stage3_max_trade_usd)
        if stage == 2:
            return float(self.cfg.stage2_max_trade_usd)
        return float(self.cfg.stage1_max_trade_usd)

    def _daily_loss_limit_for_stage(self, stage: int) -> float:
        if stage >= 3:
            return max(0.0, float(self.cfg.stage3_daily_loss_limit_usd))
        if stage == 2:
            return max(0.0, float(self.cfg.stage2_daily_loss_limit_usd))
        return max(0.0, float(self.cfg.stage1_daily_loss_limit_usd))

    def _advantage_tier(self, highest_ready_stage: int) -> str:
        if highest_ready_stage >= 3:
            return "stage_3_live_ready"
        if highest_ready_stage >= 2:
            return "stage_2_live_ready"
        return "stage_1_live_only"

    def _shadow_research_tiers(self, *, order_price: float | None = None) -> dict[str, dict[str, Any]]:
        min_shares = max(CLOB_HARD_MIN_SHARES, float(os.environ.get("JJ_POLY_MIN_ORDER_SHARES", "5.0")))
        tiers: dict[str, dict[str, Any]] = {}
        for tier_name, max_trade_usd in (
            ("shadow_100", float(self.cfg.shadow_100_max_trade_usd)),
            ("shadow_200", float(self.cfg.shadow_200_max_trade_usd)),
        ):
            size_usd = calc_trade_size_usd(self.cfg.bankroll_usd, self.cfg.risk_fraction, max_trade_usd)
            shares = None
            required_shares = None
            would_skip_for_min_shares = False
            if order_price is not None and order_price > 0:
                shares = _round_up(size_usd / order_price, 2)
                required_shares = clob_min_order_size(order_price, min_shares=min_shares)
                if shares < required_shares:
                    bumped_usd = round(required_shares * order_price, 2)
                    would_skip_for_min_shares = bumped_usd > max_trade_usd * 2
                    shares = required_shares
                    size_usd = bumped_usd
            tiers[tier_name] = {
                "advantage_tier": tier_name,
                "shadow_only": True,
                "max_trade_usd": round(max_trade_usd, 4),
                "size_usd": round(size_usd, 4),
                "shares": round(float(shares), 4) if shares is not None else None,
                "required_shares": round(float(required_shares), 4) if required_shares is not None else None,
                "would_skip_for_min_shares": would_skip_for_min_shares,
                "activation": "research_only",
                "stage_gate_reason": "shadow_only_requires_separate_promotion",
            }
        return tiers

    def _capital_stage_controls(self, *, today_pnl: float) -> dict[str, Any]:
        _ = today_pnl
        desired_stage = self._configured_live_stage()
        trailing_12 = self.db.trailing_live_filled_pnl(limit=12)
        trailing_40 = self.db.trailing_live_filled_pnl(limit=40)
        trailing_120 = self.db.trailing_live_filled_pnl(limit=120)
        drag = self.db.recent_execution_drag(limit=40)
        latest_decision_ts = self.db.latest_decision_ts()
        probe_freshness_hours = (
            round(max(0.0, time.time() - float(latest_decision_ts)) / 3600.0, 4)
            if latest_decision_ts is not None
            else None
        )
        probe_fresh_for_stage_upgrade = bool(
            probe_freshness_hours is not None
            and probe_freshness_hours <= max(0.0, float(self.cfg.stage_probe_freshness_max_hours))
        )
        order_failed_rate = _safe_float(drag.get("order_failed_rate"), None)

        stage2_gates = (
            probe_fresh_for_stage_upgrade
            and trailing_12.get("fills", 0) >= 12
            and _safe_float(trailing_12.get("pnl_usd"), 0.0) > 0.0
            and trailing_40.get("fills", 0) >= 40
            and _safe_float(trailing_40.get("pnl_usd"), 0.0) > 0.0
            and order_failed_rate is not None
            and order_failed_rate < float(self.cfg.stage_order_failed_rate_limit)
        )
        stage3_gates = (
            stage2_gates
            and trailing_120.get("fills", 0) >= 120
            and _safe_float(trailing_120.get("pnl_usd"), 0.0) > 0.0
        )
        highest_ready_stage = 1
        if stage2_gates:
            highest_ready_stage = 2
        if stage3_gates:
            highest_ready_stage = 3

        stage_blockers: list[str] = []
        if latest_decision_ts is None:
            stage_blockers.append("stage_upgrade_probe_missing")
        elif not probe_fresh_for_stage_upgrade:
            stage_blockers.append("stage_upgrade_probe_stale")
        if trailing_12.get("fills", 0) < 12:
            stage_blockers.append("insufficient_trailing_12_live_fills")
        elif _safe_float(trailing_12.get("pnl_usd"), 0.0) <= 0.0:
            stage_blockers.append("trailing_12_live_filled_not_positive")
        if trailing_40.get("fills", 0) < 40:
            stage_blockers.append("insufficient_trailing_40_live_fills")
        elif _safe_float(trailing_40.get("pnl_usd"), 0.0) <= 0.0:
            stage_blockers.append("trailing_40_live_filled_not_positive")
        if order_failed_rate is None:
            stage_blockers.append("order_failed_rate_unavailable")
        elif order_failed_rate >= float(self.cfg.stage_order_failed_rate_limit):
            stage_blockers.append("order_failed_rate_above_stage_limit")
        if trailing_120.get("fills", 0) < 120:
            stage_blockers.append("insufficient_trailing_120_live_fills")
        elif _safe_float(trailing_120.get("pnl_usd"), 0.0) <= 0.0:
            stage_blockers.append("trailing_120_live_filled_not_positive")

        effective_stage = min(desired_stage, highest_ready_stage)
        stage_blocker_text = ",".join(stage_blockers)
        if effective_stage < desired_stage:
            gate_reason = (
                f"requested_stage_{desired_stage}_capped_to_stage_{effective_stage}; blockers={stage_blocker_text}"
            )
        elif highest_ready_stage > effective_stage:
            gate_reason = (
                f"stage_{highest_ready_stage}_ready_but_configured_stage_{effective_stage}_applied"
            )
        elif effective_stage == 3:
            gate_reason = "stage_3_live_guardrails_pass"
        elif effective_stage == 2:
            gate_reason = "stage_2_live_guardrails_pass; stage_3 waits for 120 positive live-filled rows"
        else:
            gate_reason = (
                "stage_1_live_only; stage_2 waits for fresh probe telemetry, positive trailing fills, "
                f"and order_failed_rate<{self.cfg.stage_order_failed_rate_limit:.2f}"
            )

        return {
            "desired_stage": desired_stage,
            "recommended_live_stage": highest_ready_stage,
            "effective_stage": effective_stage,
            "effective_max_trade_usd": round(max(0.0, self._max_trade_for_stage(effective_stage)), 4),
            "effective_daily_loss_limit_usd": round(self._daily_loss_limit_for_stage(effective_stage), 4),
            "advantage_tier": self._advantage_tier(highest_ready_stage),
            "stage_gate_reason": gate_reason,
            "stage_blockers": list(dict.fromkeys(stage_blockers)),
            "probe_latest_decision_ts": latest_decision_ts,
            "probe_freshness_hours": probe_freshness_hours,
            "probe_fresh_for_stage_upgrade": probe_fresh_for_stage_upgrade,
            "execution_drag_counts": drag,
            "trailing_12": trailing_12,
            "trailing_40": trailing_40,
            "trailing_120": trailing_120,
            "shadow_research_tiers": self._shadow_research_tiers(),
        }

    def _probe_mode(self, *, today_pnl: float, effective_daily_loss_limit_usd: float) -> dict[str, Any] | None:
        reasons: list[str] = []
        hard_daily_loss_hit = today_pnl <= -abs(effective_daily_loss_limit_usd)
        if hard_daily_loss_hit and self.cfg.enable_probe_after_daily_loss:
            reasons.append(
                f"probe_daily_loss today_pnl={today_pnl:.4f} limit={effective_daily_loss_limit_usd:.2f}"
            )

        recent_rows = self.db.recent_live_filled(limit=self.cfg.probe_recent_fills)
        recent_pnl = round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in recent_rows), 4)
        if (
            self.cfg.enable_probe_after_recent_loss
            and self.cfg.probe_recent_fills > 0
            and len(recent_rows) >= self.cfg.probe_recent_fills
            and recent_pnl <= self.cfg.probe_recent_min_pnl_usd
        ):
            reasons.append(
                "probe_recent_live_pnl "
                f"recent_pnl={recent_pnl:.4f} fills={len(recent_rows)} "
                f"threshold={self.cfg.probe_recent_min_pnl_usd:.4f}"
            )

        if not reasons:
            return None

        effective_max_abs_delta = self.cfg.probe_max_abs_delta
        if self.cfg.max_abs_delta is not None:
            effective_max_abs_delta = (
                min(float(self.cfg.max_abs_delta), float(effective_max_abs_delta))
                if effective_max_abs_delta is not None
                else float(self.cfg.max_abs_delta)
            )

        return {
            "mode": "probe",
            "reason": _join_reasons(*reasons),
            "min_delta": max(
                float(self.cfg.min_delta),
                float(self.cfg.min_delta) * max(1.0, float(self.cfg.probe_min_delta_multiplier)),
            ),
            "max_abs_delta": effective_max_abs_delta,
            "quote_ticks": max(0, int(self.cfg.probe_quote_ticks)),
            "up_max_buy_price": self._probe_max_buy_price("UP"),
            "down_max_buy_price": self._probe_max_buy_price("DOWN"),
            "recent_live_pnl_usd": recent_pnl,
            "recent_live_fills": len(recent_rows),
            "hard_daily_loss_hit": hard_daily_loss_hit,
        }

    @staticmethod
    def _is_post_only_cross_error(error_msg: str | None) -> bool:
        return _is_post_only_cross_text(error_msg)

    async def _retry_post_only_cross(
        self,
        *,
        http: MarketHttpClient,
        token_id: str,
        direction: str,
        quote_ticks: int,
        max_buy_price: float,
        min_price: float,
        requested_shares: float,
        prior_price: float,
        size_cap_usd: float,
    ) -> dict[str, Any] | None:
        if not self.cfg.retry_post_only_cross:
            return None

        refreshed_book = await http.fetch_book(token_id)
        if not refreshed_book:
            return {
                "placement": PlacementResult(
                    order_id=None,
                    success=False,
                    status="retry_no_book",
                    error_msg="post_only_retry_no_book",
                ),
                "best_bid": None,
                "best_ask": None,
                "order_price": prior_price,
                "reason": "post_only_retry_no_book",
            }

        best_bid, best_ask = http.top_of_book(refreshed_book)
        retry_price = choose_maker_buy_price(
            best_bid=best_bid,
            best_ask=best_ask,
            max_price=max_buy_price,
            min_price=min_price,
            tick_size=self.cfg.tick_size,
            aggression_ticks=quote_ticks,
            post_only_safety_ticks=self.cfg.retry_post_only_safety_ticks,
        )
        if retry_price is None:
            return {
                "placement": PlacementResult(
                    order_id=None,
                    success=False,
                    status="retry_no_safe_price",
                    error_msg="post_only_retry_no_safe_price",
                ),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_price": prior_price,
                "reason": (
                    "post_only_retry_no_safe_price "
                    f"direction={direction} best_bid={best_bid} best_ask={best_ask}"
                ),
            }

        retry_shares = float(requested_shares)
        _btc5_min_shares = max(
            CLOB_HARD_MIN_SHARES,
            float(os.environ.get("JJ_POLY_MIN_ORDER_SHARES", "5.0")),
        )
        retry_required_shares = clob_min_order_size(retry_price, min_shares=_btc5_min_shares)
        if retry_shares < retry_required_shares:
            retry_shares = retry_required_shares
        retry_notional_usd = round(retry_shares * retry_price, 2)
        if retry_notional_usd > max(0.0, float(size_cap_usd)) + 1e-9:
            return {
                "placement": PlacementResult(
                    order_id=None,
                    success=False,
                    status="retry_size_too_large",
                    error_msg="post_only_retry_size_too_large",
                ),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_price": retry_price,
                "shares": retry_shares,
                "reason": (
                    "post_only_retry_size_too_large "
                    f"direction={direction} retry_price={retry_price:.2f} "
                    f"retry_shares={retry_shares:.2f} retry_notional_usd={retry_notional_usd:.2f} "
                    f"tier_cap_usd={float(size_cap_usd):.2f}"
                ),
            }

        try:
            placement = self.clob.place_post_only_buy(
                token_id=token_id,
                price=retry_price,
                shares=retry_shares,
            )
        except Exception as exc:
            placement = PlacementResult(
                order_id=None,
                success=False,
                status="retry_failed",
                error_msg=str(exc),
            )
        return {
            "placement": placement,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "order_price": retry_price,
            "shares": retry_shares,
            "reason": (
                "post_only_retry "
                f"direction={direction} from={prior_price:.2f} to={retry_price:.2f} "
                f"best_bid={best_bid} best_ask={best_ask} shares={retry_shares:.2f}"
            ),
        }

    async def _resolve_unsettled(self, http: MarketHttpClient, through_window_start: int) -> None:
        rows = self.db.unsettled_rows(max_window_start_ts=through_window_start)
        for row in rows:
            kline = await http.fetch_binance_window_open_close(int(row["window_start_ts"]))
            if not kline:
                continue
            open_px, close_px = kline
            if close_px > open_px:
                resolved_side = "UP"
            elif close_px < open_px:
                resolved_side = "DOWN"
            else:
                resolved_side = "FLAT"

            filled = row["filled"]
            direction = str(row["direction"] or "")
            order_price = _safe_float(row["order_price"], 0.0) or 0.0
            shares = _safe_float(row["shares"], 0.0) or 0.0
            pnl = None
            won = None

            if filled == 1 and direction in {"UP", "DOWN"} and resolved_side in {"UP", "DOWN"}:
                won = 1 if direction == resolved_side else 0
                pnl = round(shares * (1.0 - order_price), 6) if won else round(-shares * order_price, 6)
            elif filled == 0:
                won = 0
                pnl = 0.0

            self.db.upsert_window(
                {
                    "window_start_ts": row["window_start_ts"],
                    "window_end_ts": row["window_end_ts"],
                    "slug": row["slug"],
                    "decision_ts": row["decision_ts"],
                    "direction": row["direction"],
                    "open_price": row["open_price"],
                    "current_price": row["current_price"],
                    "delta": row["delta"],
                    "token_id": row["token_id"],
                    "best_bid": row["best_bid"],
                    "best_ask": row["best_ask"],
                    "order_price": row["order_price"],
                    "trade_size_usd": row["trade_size_usd"],
                    "shares": row["shares"],
                    "order_id": row["order_id"],
                    "order_status": row["order_status"],
                    "filled": row["filled"],
                    "reason": row["reason"],
                    "resolved_side": resolved_side,
                    "won": won,
                    "pnl_usd": pnl,
                }
            )

    async def _get_open_and_current_price(
        self,
        *,
        window_start_ts: int,
        http: MarketHttpClient,
    ) -> tuple[float | None, float | None]:
        open_price = await self.cache.open_price_for_window(window_start_ts)
        latest = await self.cache.latest()
        current_price = latest[1] if latest else None

        # Fallback to Binance REST if WS data is sparse.
        if open_price is None:
            kline = await http.fetch_binance_window_open_close(window_start_ts)
            if kline:
                open_price = kline[0]
        if current_price is None:
            current_price = await http.fetch_binance_spot()

        return open_price, current_price

    async def _reconcile_live_order(
        self,
        *,
        order_id: str,
        requested_shares: float,
        window_end_ts: int,
    ) -> tuple[str, int | None, float | None, str | None, str | None]:
        cancel_at = window_end_ts - self.cfg.cancel_seconds_before_close
        wait_seconds = max(0.0, cancel_at - time.time())
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        before_cancel = self.clob.get_order_state(order_id)
        if before_cancel and before_cancel.fully_filled:
            return "live_filled", 1, before_cancel.size_matched or requested_shares, None, None
        if before_cancel and before_cancel.partially_filled and before_cancel.is_cancelled:
            return "live_partial_fill_cancelled", 1, before_cancel.size_matched, None, "partial_fill_then_cancel"
        if before_cancel and before_cancel.is_cancelled and before_cancel.size_matched <= 0:
            return "live_cancelled_unfilled", 0, 0.0, None, "cancel_before_fill"

        cancelled = self.clob.cancel_order(order_id)
        after_cancel = self.clob.get_order_state(order_id)
        final_state = after_cancel or before_cancel

        if final_state:
            if final_state.fully_filled:
                return "live_filled", 1, final_state.size_matched or requested_shares, None, None
            if final_state.partially_filled:
                return (
                    "live_partial_fill_cancelled" if cancelled or final_state.is_cancelled else "live_partial_fill_open",
                    1,
                    final_state.size_matched,
                    None,
                    "partial_fill_then_cancel" if cancelled or final_state.is_cancelled else None,
                )
            if final_state.is_cancelled:
                return "live_cancelled_unfilled", 0, 0.0, None, "cancel_before_fill"
            if final_state.is_live:
                return "live_cancel_unknown", None, None, f"status={final_state.normalized_status}", None

        if cancelled:
            return "live_cancelled_unfilled", 0, 0.0, None, "cancel_before_fill"
        return "live_cancel_unknown", None, None, "order_status_unavailable", None

    async def _process_window(self, *, window_start_ts: int, http: MarketHttpClient) -> dict[str, Any]:
        window_end_ts = window_start_ts + WINDOW_SECONDS
        slug = market_slug_for_window(window_start_ts)
        session_bucket = _btc5_session_bucket(window_start_ts)
        capital_stage = 1
        effective_max_trade_usd = float(self._max_trade_for_stage(capital_stage))
        effective_daily_loss_limit_usd = float(self._daily_loss_limit_for_stage(capital_stage))
        recommended_live_stage = capital_stage
        advantage_tier = "stage_1_live_only"
        stage_gate_reason = "stage_gates_pending_live_evaluation"
        stage_blockers: list[str] = []
        probe_freshness_hours: float | None = None
        probe_fresh_for_stage_upgrade = False
        execution_drag_counts = self.db.recent_execution_drag(limit=40)
        capital_utilization_ratio = 0.0
        shadow_research_tiers = self._shadow_research_tiers()
        session_override = active_session_guardrail_override(self.cfg, window_start_ts=window_start_ts)
        session_policy_name = session_override.session_name if session_override is not None else None
        session_reason = session_guardrail_reason(session_override, window_start_ts=window_start_ts)
        recent_regime: dict[str, Any] | None = None
        edge_tier = "suppressed"
        sizing_reason_tags: list[str] = _unique_tags(
            f"session_bucket={session_bucket}",
            f"session_policy_name={session_policy_name or 'none'}",
            f"effective_stage={capital_stage}",
            f"recommended_live_stage={recommended_live_stage}",
        )
        loss_cluster_suppressed = False

        def _result(payload: dict[str, Any]) -> dict[str, Any]:
            if "capital_stage" not in payload:
                payload["capital_stage"] = capital_stage
            if "effective_stage" not in payload:
                payload["effective_stage"] = capital_stage
            if "effective_max_trade_usd" not in payload:
                payload["effective_max_trade_usd"] = round(effective_max_trade_usd, 4)
            if "effective_daily_loss_limit_usd" not in payload:
                payload["effective_daily_loss_limit_usd"] = round(effective_daily_loss_limit_usd, 4)
            if "recommended_live_stage" not in payload:
                payload["recommended_live_stage"] = recommended_live_stage
            if "advantage_tier" not in payload:
                payload["advantage_tier"] = advantage_tier
            if "stage_gate_reason" not in payload:
                payload["stage_gate_reason"] = stage_gate_reason
            if "stage_blockers" not in payload:
                payload["stage_blockers"] = list(stage_blockers)
            if "probe_freshness_hours" not in payload:
                payload["probe_freshness_hours"] = probe_freshness_hours
            if "probe_fresh_for_stage_upgrade" not in payload:
                payload["probe_fresh_for_stage_upgrade"] = probe_fresh_for_stage_upgrade
            if "execution_drag_counts" not in payload:
                payload["execution_drag_counts"] = dict(execution_drag_counts)
            if "capital_utilization_ratio" not in payload:
                payload["capital_utilization_ratio"] = round(max(0.0, float(capital_utilization_ratio)), 6)
            if "shadow_research_tiers" not in payload:
                payload["shadow_research_tiers"] = dict(shadow_research_tiers)
            if "session_override_triggered" not in payload:
                payload["session_override_triggered"] = session_override is not None
            if "session_policy_name" not in payload:
                payload["session_policy_name"] = session_policy_name
            if "edge_tier" not in payload:
                payload["edge_tier"] = edge_tier
            if "sizing_reason_tags" not in payload:
                payload["sizing_reason_tags"] = list(sizing_reason_tags)
            if "loss_cluster_suppressed" not in payload:
                payload["loss_cluster_suppressed"] = loss_cluster_suppressed
            if "directional_mode" not in payload:
                payload["directional_mode"] = (
                    str((recent_regime or {}).get("directional_mode") or "two_sided")
                    if recent_regime
                    else "two_sided"
                )
            if "suppressed_direction" not in payload:
                payload["suppressed_direction"] = (recent_regime or {}).get("suppressed_direction")
            if "book_failure_attribution" not in payload:
                payload["book_failure_attribution"] = None
            if "placement_failure_attribution" not in payload:
                payload["placement_failure_attribution"] = None
            if "order_outcome_attribution" not in payload:
                payload["order_outcome_attribution"] = None
            return payload

        def _persist(row: dict[str, Any]) -> None:
            payload = dict(row)
            if "edge_tier" not in payload:
                payload["edge_tier"] = edge_tier
            if "sizing_reason_tags" not in payload:
                payload["sizing_reason_tags"] = list(sizing_reason_tags)
            if "loss_cluster_suppressed" not in payload:
                payload["loss_cluster_suppressed"] = loss_cluster_suppressed
            if "session_policy_name" not in payload:
                payload["session_policy_name"] = session_policy_name
            if "effective_stage" not in payload:
                payload["effective_stage"] = capital_stage
            self.db.upsert_window(payload)

        if self.db.window_exists(window_start_ts):
            return _result({"window_start_ts": window_start_ts, "status": "skip_already_processed"})

        # Resolve prior windows first so daily PnL gate uses latest info.
        await self._resolve_unsettled(http, through_window_start=window_start_ts - WINDOW_SECONDS)

        today_pnl = self.db.today_realized_pnl()
        stage_controls = self._capital_stage_controls(today_pnl=today_pnl)
        capital_stage = int(stage_controls.get("effective_stage") or 1)
        recommended_live_stage = int(stage_controls.get("recommended_live_stage") or capital_stage)
        effective_max_trade_usd = float(stage_controls.get("effective_max_trade_usd") or self.cfg.max_trade_usd)
        effective_daily_loss_limit_usd = float(
            stage_controls.get("effective_daily_loss_limit_usd") or self.cfg.daily_loss_limit_usd
        )
        advantage_tier = str(stage_controls.get("advantage_tier") or advantage_tier)
        stage_gate_reason = str(stage_controls.get("stage_gate_reason") or stage_gate_reason)
        stage_blockers = list(stage_controls.get("stage_blockers") or stage_blockers)
        probe_freshness_hours = _safe_float(stage_controls.get("probe_freshness_hours"), None)
        probe_fresh_for_stage_upgrade = bool(stage_controls.get("probe_fresh_for_stage_upgrade"))
        execution_drag_counts = dict(stage_controls.get("execution_drag_counts") or execution_drag_counts)
        shadow_research_tiers = dict(stage_controls.get("shadow_research_tiers") or shadow_research_tiers)
        probe_mode = self._probe_mode(
            today_pnl=today_pnl,
            effective_daily_loss_limit_usd=effective_daily_loss_limit_usd,
        )
        sizing_reason_tags = _unique_tags(
            f"session_bucket={session_bucket}",
            f"session_policy_name={session_policy_name or 'none'}",
            f"effective_stage={capital_stage}",
            f"recommended_live_stage={recommended_live_stage}",
            "probe_mode=on" if probe_mode else "probe_mode=off",
            "probe_fresh_for_stage_upgrade=true" if probe_fresh_for_stage_upgrade else "probe_fresh_for_stage_upgrade=false",
        )
        hard_daily_loss_hit = today_pnl <= -abs(effective_daily_loss_limit_usd)
        if hard_daily_loss_hit and probe_mode is None:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "order_status": "skip_daily_loss_limit",
                "reason": _join_reasons(
                    session_reason,
                    f"today_pnl={today_pnl:.4f} limit={effective_daily_loss_limit_usd:.2f}",
                ),
            }
            _persist(row)
            return _result({"window_start_ts": window_start_ts, "status": row["order_status"], "today_pnl": today_pnl})
        effective_min_delta = float(probe_mode["min_delta"]) if probe_mode else float(self.cfg.min_delta)
        if session_override and session_override.min_delta is not None:
            effective_min_delta = max(effective_min_delta, float(session_override.min_delta))
        effective_max_abs_delta = (
            float(session_override.max_abs_delta)
            if session_override and session_override.max_abs_delta is not None
            else self.cfg.max_abs_delta
        )
        if self.cfg.max_abs_delta is not None and effective_max_abs_delta is not None:
            effective_max_abs_delta = min(float(self.cfg.max_abs_delta), float(effective_max_abs_delta))
        if probe_mode:
            probe_max_abs_delta = _safe_float(probe_mode.get("max_abs_delta"), None)
            if probe_max_abs_delta is not None:
                effective_max_abs_delta = (
                    min(float(effective_max_abs_delta), float(probe_max_abs_delta))
                    if effective_max_abs_delta is not None
                    else float(probe_max_abs_delta)
                )
        probe_reason = probe_mode.get("reason") if probe_mode else None

        open_price, current_price = await self._get_open_and_current_price(window_start_ts=window_start_ts, http=http)
        if not open_price or not current_price:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "open_price": open_price,
                "current_price": current_price,
                "order_status": "skip_missing_price",
                "reason": session_reason,
            }
            _persist(row)
            return _result({"window_start_ts": window_start_ts, "status": row["order_status"]})

        direction, delta = direction_from_prices(open_price, current_price, effective_min_delta)
        if direction is None and self.cfg.enable_spread_capture:
            # Spread-capture mode: bypass delta gate when BTC is flat.
            # Alternate UP/DOWN each window for statistical neutrality.
            direction = "UP" if (window_start_ts // 300) % 2 == 0 else "DOWN"
            delta = (current_price - open_price) / open_price if open_price > 0 else 0.0
            logger.info(
                "Spread-capture mode: delta=%.6f below threshold, "
                "forcing direction=%s for window %d",
                abs(delta), direction, window_start_ts,
            )
        if direction is None:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_delta_too_small",
                "reason": _join_reasons(
                    probe_reason,
                    session_reason,
                    f"abs(delta)={abs(delta):.6f} < {effective_min_delta:.6f}",
                ),
            }
            _persist(row)
            return _result({
                "window_start_ts": window_start_ts,
                "status": row["order_status"],
                "delta": delta,
                "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
                "stage_gate_reason": stage_gate_reason,
            })

        if effective_max_abs_delta is not None and abs(delta) > effective_max_abs_delta:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_delta_too_large",
                "reason": _join_reasons(
                    probe_reason,
                    session_reason,
                    f"abs(delta)={abs(delta):.6f} > {effective_max_abs_delta:.6f}",
                ),
            }
            _persist(row)
            return _result({
                "window_start_ts": window_start_ts,
                "status": row["order_status"],
                "delta": delta,
                "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
                "stage_gate_reason": stage_gate_reason,
            })

        recent_regime = self._recent_direction_regime()
        directional_mode = str((recent_regime or {}).get("directional_mode") or "two_sided")
        suppressed_direction = str((recent_regime or {}).get("suppressed_direction") or "").strip().upper() or None
        quote_ticks: int | None = None
        market = await http.fetch_market_by_slug(slug)
        if not market:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_market_not_found",
                "reason": session_reason,
            }
            _persist(row)
            return _result({"window_start_ts": window_start_ts, "status": row["order_status"]})

        token_id = choose_token_id_for_direction(market, direction)
        if not token_id:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "order_status": "skip_token_not_found",
                "reason": session_reason,
            }
            _persist(row)
            return _result({"window_start_ts": window_start_ts, "status": row["order_status"]})

        regime_reason = None
        if recent_regime and recent_regime.get("triggered"):
            favored = recent_regime.get("favored_direction") or "n/a"
            weaker = recent_regime.get("weaker_direction") or "n/a"
            regime_reason = f"recent_regime favored={favored} weaker={weaker} directional_mode={directional_mode}"
        if suppressed_direction and direction == suppressed_direction:
            edge_tier = "suppressed"
            loss_cluster_suppressed = True
            sizing_reason_tags = _unique_tags(
                *sizing_reason_tags,
                f"direction={direction}",
                f"delta_bucket={_btc5_delta_bucket(delta)}",
                "recent_regime_one_sided_guardrail",
                f"suppressed_direction={suppressed_direction}",
                "edge_tier=suppressed",
            )
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "order_status": "skip_direction_suppressed",
                "reason": _join_reasons(
                    probe_reason,
                    session_reason,
                    regime_reason,
                    _reason_tag("suppressed_direction", suppressed_direction),
                ),
            }
            _persist(row)
            return _result(
                {
                    "window_start_ts": window_start_ts,
                    "status": row["order_status"],
                    "direction": direction,
                    "delta": delta,
                    "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
                    "regime_triggered": bool(recent_regime and recent_regime.get("triggered")),
                }
            )

        book = await http.fetch_book(token_id)
        if not book:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "order_status": "skip_no_book",
                "reason": _join_reasons(
                    probe_reason,
                    session_reason,
                    regime_reason,
                    _reason_tag("book_failure_attribution", "no_book"),
                ),
            }
            _persist(row)
            return _result(
                {
                    "window_start_ts": window_start_ts,
                    "status": row["order_status"],
                    "direction": direction,
                    "delta": delta,
                    "book_failure_attribution": "no_book",
                }
            )

        best_bid, best_ask = http.top_of_book(book)
        book_failure_attribution, book_detail = _classify_book_quotes(best_bid, best_ask)
        if book_failure_attribution is not None:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_status": "skip_bad_book",
                "reason": _join_reasons(
                    probe_reason,
                    session_reason,
                    regime_reason,
                    _reason_tag("book_failure_attribution", book_failure_attribution),
                    book_detail,
                ),
            }
            _persist(row)
            return _result(
                {
                    "window_start_ts": window_start_ts,
                    "status": row["order_status"],
                    "direction": direction,
                    "delta": delta,
                    "book_failure_attribution": book_failure_attribution,
                }
            )

        quote_ticks = effective_quote_ticks(
            self.cfg,
            direction,
            session_override=session_override,
            recent_regime=recent_regime,
        )
        if probe_mode:
            quote_ticks = min(int(quote_ticks), int(probe_mode["quote_ticks"]))
        if recent_regime and recent_regime.get("triggered"):
            favored = recent_regime.get("favored_direction") or "n/a"
            weaker = recent_regime.get("weaker_direction") or "n/a"
            regime_reason = (
                f"recent_regime favored={favored} weaker={weaker} "
                f"{direction}_quote_ticks={quote_ticks}"
            )
            if recent_regime.get("one_sided_triggered"):
                regime_reason = f"{regime_reason} suppressed_direction={suppressed_direction}"
        mode_max_buy_price = effective_max_buy_price(self.cfg, direction, session_override=session_override)
        if probe_mode and direction == "UP":
            mode_max_buy_price = min(mode_max_buy_price, float(probe_mode["up_max_buy_price"]))
        elif probe_mode and direction == "DOWN":
            mode_max_buy_price = min(mode_max_buy_price, float(probe_mode["down_max_buy_price"]))

        order_price = choose_maker_buy_price(
            best_bid=best_bid,
            best_ask=best_ask,
            max_price=mode_max_buy_price,
            min_price=self.cfg.min_buy_price,
            tick_size=self.cfg.tick_size,
            aggression_ticks=quote_ticks,
        )
        if order_price is None:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_status": "skip_price_outside_guardrails",
                "reason": _join_reasons(probe_reason, session_reason, regime_reason),
            }
            _persist(row)
            return _result({
                "window_start_ts": window_start_ts,
                "status": row["order_status"],
                "quote_ticks": quote_ticks,
                "regime_triggered": bool(recent_regime and recent_regime.get("triggered")),
                "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
                "stage_gate_reason": stage_gate_reason,
            })

        shadow_research_tiers = self._shadow_research_tiers(order_price=order_price)
        edge_profile = self._classify_edge_tier(
            window_start_ts=window_start_ts,
            direction=direction,
            delta=delta,
            order_price=order_price,
            session_override=session_override,
            session_policy_name=session_policy_name,
            effective_stage=capital_stage,
            recommended_live_stage=recommended_live_stage,
            recent_regime=recent_regime,
            probe_mode=probe_mode,
        )
        edge_tier = str(edge_profile.get("edge_tier") or "standard")
        loss_cluster_suppressed = bool(edge_profile.get("loss_cluster_suppressed"))
        sizing_reason_tags = list(edge_profile.get("sizing_reason_tags") or sizing_reason_tags)
        size_plan = self._trade_size_for_edge_tier(
            edge_tier=edge_tier,
            effective_max_trade_usd=effective_max_trade_usd,
        )
        size_usd = float(size_plan.get("target_size_usd") or 0.0)
        size_cap_usd = float(size_plan.get("size_cap_usd") or 0.0)
        sizing_reason_tags = _unique_tags(
            *sizing_reason_tags,
            *(size_plan.get("sizing_reason_tags") or []),
        )

        if edge_tier == "suppressed":
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_price": order_price,
                "trade_size_usd": 0.0,
                "shares": 0.0,
                "order_status": "skip_loss_cluster_suppressed",
                "reason": _join_reasons(
                    probe_reason,
                    session_reason,
                    regime_reason,
                    "observed_loss_cluster_suppressed",
                ),
            }
            _persist(row)
            return _result(
                {
                    "window_start_ts": window_start_ts,
                    "status": row["order_status"],
                    "direction": direction,
                    "delta": delta,
                    "price": order_price,
                    "size_usd": 0.0,
                    "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
                    "quote_ticks": quote_ticks,
                }
            )

        if size_usd < self.cfg.min_trade_usd:
            row = {
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "slug": slug,
                "direction": direction,
                "open_price": open_price,
                "current_price": current_price,
                "delta": delta,
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "order_price": order_price,
                "trade_size_usd": size_usd,
                "order_status": "skip_size_too_small",
                "reason": _join_reasons(session_reason, _reason_tag("edge_tier", edge_tier)),
            }
            _persist(row)
            return _result({"window_start_ts": window_start_ts, "status": row["order_status"]})

        shares = _round_down(size_usd / max(order_price, 1e-6), 2)
        _btc5_min_shares = max(CLOB_HARD_MIN_SHARES, float(os.environ.get("JJ_POLY_MIN_ORDER_SHARES", "5.0")))
        required_shares = clob_min_order_size(order_price, min_shares=_btc5_min_shares)
        if shares < required_shares:
            bumped_usd = round(required_shares * order_price, 2)
            if bumped_usd > size_cap_usd + 1e-9:
                logger.info(
                    "SKIP: %.2f shares / $%.2f below live min %.2f shares / $%.2f, bump $%.2f > tier cap $%.2f",
                    shares,
                    shares * order_price,
                    required_shares,
                    CLOB_HARD_MIN_NOTIONAL_USD,
                    bumped_usd,
                    size_cap_usd,
                )
                row = {
                    "window_start_ts": window_start_ts,
                    "window_end_ts": window_end_ts,
                    "slug": slug,
                    "direction": direction,
                    "open_price": open_price,
                    "current_price": current_price,
                    "delta": delta,
                    "token_id": token_id,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "order_price": order_price,
                    "trade_size_usd": size_usd,
                    "order_status": "skip_below_min_shares",
                    "reason": _join_reasons(
                        session_reason,
                        _reason_tag("edge_tier", edge_tier),
                        f"tier_cap_usd={size_cap_usd:.2f}",
                    ),
                }
                _persist(row)
                return _result({"window_start_ts": window_start_ts, "status": row["order_status"]})
            shares = required_shares
            size_usd = bumped_usd
            sizing_reason_tags = _unique_tags(
                *sizing_reason_tags,
                "min_share_bump_applied",
                f"required_shares={required_shares:.2f}",
            )
        capital_utilization_ratio = (
            (size_usd / effective_max_trade_usd) if effective_max_trade_usd > 0 else 0.0
        )
        order_id = None
        filled: int | None = None
        order_status = "order_error"
        reason: str | None = _join_reasons(
            probe_reason,
            session_reason,
            regime_reason,
            _reason_tag("edge_tier", edge_tier),
        )
        executed_shares = shares
        placement_failure_attribution: str | None = None
        order_outcome_attribution: str | None = None

        if self.cfg.paper_trading:
            order_id = f"paper-{window_start_ts}"
            filled = 1 if deterministic_fill(window_start_ts, self.cfg.paper_fill_probability) else 0
            order_status = "paper_filled" if filled == 1 else "paper_unfilled"
            if filled == 0:
                executed_shares = 0.0
        else:
            placement = PlacementResult(
                order_id=None,
                success=False,
                status="order_failed",
                error_msg=None,
            )
            retry_note: str | None = None
            try:
                placement = self.clob.place_post_only_buy(token_id=token_id, price=order_price, shares=shares)
            except Exception as exc:
                placement = PlacementResult(
                    order_id=None,
                    success=False,
                    status="order_failed",
                    error_msg=str(exc),
                )

            if not placement.success and self._is_post_only_cross_error(placement.error_msg):
                placement_failure_attribution = "post_only_cross_failure"
                retry_payload = await self._retry_post_only_cross(
                    http=http,
                    token_id=token_id,
                    direction=direction,
                    quote_ticks=quote_ticks,
                    max_buy_price=mode_max_buy_price,
                    min_price=self.cfg.min_buy_price,
                    requested_shares=shares,
                    prior_price=order_price,
                    size_cap_usd=size_cap_usd,
                )
                if retry_payload is not None:
                    retry_note = retry_payload.get("reason")
                    retry_bid = retry_payload.get("best_bid")
                    retry_ask = retry_payload.get("best_ask")
                    retry_price = retry_payload.get("order_price")
                    retry_shares = retry_payload.get("shares")
                    if retry_bid is not None:
                        best_bid = retry_bid
                    if retry_ask is not None:
                        best_ask = retry_ask
                    if retry_price is not None:
                        order_price = float(retry_price)
                        size_usd = round(shares * order_price, 2)
                        capital_utilization_ratio = (
                            (size_usd / effective_max_trade_usd) if effective_max_trade_usd > 0 else 0.0
                        )
                        shadow_research_tiers = self._shadow_research_tiers(order_price=order_price)
                    if retry_shares is not None:
                        shares = float(retry_shares)
                        size_usd = round(shares * order_price, 2)
                        capital_utilization_ratio = (
                            (size_usd / effective_max_trade_usd) if effective_max_trade_usd > 0 else 0.0
                        )
                        shadow_research_tiers = self._shadow_research_tiers(order_price=order_price)
                    retry_placement = retry_payload.get("placement")
                    if isinstance(retry_placement, PlacementResult):
                        placement = retry_placement
                    logger.info("Retried post-only cross for %s: %s", slug, retry_note or "retry")

            if placement.success:
                order_id = placement.order_id
                order_status = f"live_{placement.status}" if placement.status else "live_order_placed"
                reason = _join_reasons(
                    reason,
                    retry_note,
                    _reason_tag("placement_failure_attribution", placement_failure_attribution),
                )
            else:
                order_status = "live_order_failed"
                if placement_failure_attribution is None:
                    placement_failure_attribution = (
                        "post_only_cross_failure"
                        if self._is_post_only_cross_error(placement.error_msg)
                        else "order_placement_failure"
                    )
                if placement.error_msg:
                    logger.error("Live order placement failed: %s", placement.error_msg)
                reason = _join_reasons(
                    reason,
                    retry_note,
                    _reason_tag("placement_failure_attribution", placement_failure_attribution),
                    placement.error_msg,
                )

            if order_id and placement.success:
                (
                    order_status,
                    filled,
                    executed_shares,
                    reconcile_reason,
                    order_outcome_attribution,
                ) = await self._reconcile_live_order(
                    order_id=order_id,
                    requested_shares=shares,
                    window_end_ts=window_end_ts,
                )
                reason = _join_reasons(
                    reason,
                    _reason_tag("order_outcome_attribution", order_outcome_attribution),
                    reconcile_reason,
                )
            else:
                filled = 0
                executed_shares = 0.0

        row = {
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "slug": slug,
            "direction": direction,
            "open_price": open_price,
            "current_price": current_price,
            "delta": delta,
            "token_id": token_id,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "order_price": order_price,
            "trade_size_usd": round((executed_shares or 0.0) * order_price, 4) if filled == 1 else 0.0,
            "shares": executed_shares if filled == 1 else 0.0,
            "order_id": order_id,
            "filled": filled,
            "order_status": order_status,
            "reason": reason,
        }
        _persist(row)
        return _result({
            "window_start_ts": window_start_ts,
            "status": order_status,
            "direction": direction,
            "delta": delta,
            "order_id": order_id,
            "price": order_price,
            "size_usd": row["trade_size_usd"],
            "filled": filled,
            "reason": reason,
            "quote_ticks": quote_ticks,
            "regime_triggered": bool(recent_regime and recent_regime.get("triggered")),
            "risk_mode": probe_mode.get("mode") if probe_mode else "normal",
            "placement_failure_attribution": placement_failure_attribution,
            "order_outcome_attribution": order_outcome_attribution,
            "stage_gate_reason": stage_gate_reason,
            "capital_utilization_ratio": round(max(0.0, float(capital_utilization_ratio)), 6),
        })

    async def run_windows(self, *, count: int, continuous: bool) -> None:
        stop_event = asyncio.Event()
        feed = BinanceTradeFeed(self.cfg.binance_ws_url, self.cache)
        feed_task = asyncio.create_task(feed.run(stop_event))

        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            http = MarketHttpClient(self.cfg, session)
            executed = 0

            try:
                while True:
                    now = time.time()
                    ws = current_window_start(now)
                    decision_ts = ws + WINDOW_SECONDS - self.cfg.entry_seconds_before_close
                    if now > decision_ts + 1:
                        ws += WINDOW_SECONDS
                        decision_ts = ws + WINDOW_SECONDS - self.cfg.entry_seconds_before_close
                    wait = max(0.0, decision_ts - time.time())
                    if wait > 0:
                        logger.info("Waiting %.1fs until decision time for window %s", wait, ws)
                        await asyncio.sleep(wait)

                    summary = await self._process_window(window_start_ts=ws, http=http)
                    logger.info("Window result: %s", json.dumps(summary, sort_keys=True))
                    executed += 1

                    if not continuous and executed >= count:
                        break
            finally:
                stop_event.set()
                await asyncio.sleep(0)
                feed_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await feed_task

        # Resolve the most recent completed window if possible.
        async with aiohttp.ClientSession(timeout=timeout) as session:
            http = MarketHttpClient(self.cfg, session)
            await self._resolve_unsettled(http, through_window_start=current_window_start() - WINDOW_SECONDS)

    async def run_now(self) -> dict[str, Any]:
        """Execute the decision pipeline immediately for the current 5m window."""
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            http = MarketHttpClient(self.cfg, session)
            ws = current_window_start()
            return await self._process_window(window_start_ts=ws, http=http)

    def live_summary(self) -> dict[str, Any]:
        return self.db.intraday_live_summary()

    def print_status(self) -> None:
        status = self.db.status_summary()
        stage_controls = self._capital_stage_controls(today_pnl=float(status.get("today_pnl_usd") or 0.0))
        today_notional = float(status.get("today_notional_usd") or 0.0)
        bankroll = max(float(self.cfg.bankroll_usd), 1e-9)
        utilization = max(0.0, today_notional / bankroll)
        print(
            json.dumps(
                {
                    "paper_trading": self.cfg.paper_trading,
                    "db_path": str(self.cfg.db_path),
                    "capital_stage": int(stage_controls.get("effective_stage") or self._configured_live_stage()),
                    "recommended_live_stage": int(
                        stage_controls.get("recommended_live_stage") or self._configured_live_stage()
                    ),
                    "effective_max_trade_usd": round(
                        float(stage_controls.get("effective_max_trade_usd") or self.cfg.effective_max_trade_usd),
                        4,
                    ),
                    "effective_daily_loss_limit_usd": round(
                        float(stage_controls.get("effective_daily_loss_limit_usd") or self.cfg.effective_daily_loss_limit_usd),
                        4,
                    ),
                    "advantage_tier": str(stage_controls.get("advantage_tier") or "stage_1_live_only"),
                    "stage_gate_reason": str(stage_controls.get("stage_gate_reason") or "stage_gates_pending_live_evaluation"),
                    "stage_blockers": list(stage_controls.get("stage_blockers") or []),
                    "probe_freshness_hours": _safe_float(stage_controls.get("probe_freshness_hours"), None),
                    "probe_fresh_for_stage_upgrade": bool(stage_controls.get("probe_fresh_for_stage_upgrade")),
                    "execution_drag_counts": dict(stage_controls.get("execution_drag_counts") or {}),
                    "capital_utilization_ratio": round(utilization, 6),
                    "shadow_research_tiers": dict(stage_controls.get("shadow_research_tiers") or {}),
                    **status,
                },
                indent=2,
                sort_keys=True,
            )
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BTC 5m maker bot (Instance 2)")
    parser.add_argument("--continuous", action="store_true", help="Run indefinitely")
    parser.add_argument("--windows", type=int, default=1, help="Number of windows to process in non-continuous mode")
    parser.add_argument("--status", action="store_true", help="Print status summary from SQLite DB and exit")
    parser.add_argument("--paper", action="store_true", help="Force paper mode for this run")
    parser.add_argument("--live", action="store_true", help="Force live mode for this run")
    parser.add_argument("--run-now", action="store_true", help="Run immediately on current window (no T-10 wait)")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logs")
    return parser


async def _run(args: argparse.Namespace) -> None:
    cfg = MakerConfig()
    if args.paper and args.live:
        raise SystemExit("Use only one of --paper or --live")
    if args.paper:
        cfg.paper_trading = True
    if args.live:
        cfg.paper_trading = False

    if cfg.entry_seconds_before_close <= cfg.cancel_seconds_before_close:
        raise SystemExit("BTC5_ENTRY_SECONDS_BEFORE_CLOSE must be greater than BTC5_CANCEL_SECONDS_BEFORE_CLOSE")

    bot = BTC5MinMakerBot(cfg)
    if args.status:
        bot.print_status()
        return

    if args.run_now:
        summary = await bot.run_now()
        logger.info("Immediate run result: %s", json.dumps(summary, sort_keys=True))
        bot.print_status()
        return

    if not args.continuous and args.windows < 1:
        raise SystemExit("--windows must be >= 1")

    logger.info(
        "Starting BTC5 maker | mode=%s | bankroll=%.2f | risk_fraction=%.4f | max_trade=%.2f | max_abs_delta=%s | up_max=%.2f | down_max=%.2f | improve_ticks=%d | session_overrides=%d | regime_skew=%s | probe_daily_loss=%s | probe_recent=%s | retry_post_only_cross=%s safety_ticks=%d | window_seconds=%d | slug_prefix=%s | binance_symbol=%s | kline_interval=%s",
        "paper" if cfg.paper_trading else "live",
        cfg.bankroll_usd,
        cfg.risk_fraction,
        cfg.max_trade_usd,
        "disabled" if cfg.max_abs_delta is None else f"{cfg.max_abs_delta:.6f}",
        effective_max_buy_price(cfg, "UP"),
        effective_max_buy_price(cfg, "DOWN"),
        max(0, int(cfg.maker_improve_ticks)),
        len(cfg.session_guardrail_overrides),
        "enabled" if cfg.enable_recent_regime_skew else "disabled",
        "enabled" if cfg.enable_probe_after_daily_loss else "disabled",
        "enabled" if cfg.enable_probe_after_recent_loss else "disabled",
        "enabled" if cfg.retry_post_only_cross else "disabled",
        max(0, int(cfg.retry_post_only_safety_ticks)),
        WINDOW_SECONDS,
        MARKET_SLUG_PREFIX,
        cfg.binance_symbol,
        cfg.binance_kline_interval,
    )
    await bot.run_windows(count=args.windows, continuous=args.continuous)
    bot.print_status()


def main() -> None:
    args = build_arg_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
