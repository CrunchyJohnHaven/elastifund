#!/usr/bin/env python3
"""Empirical BTC5 Monte Carlo engine for guardrail iteration."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import shlex
import shutil
import sqlite3
import subprocess
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_REMOTE_DB = REPORTS_DIR / "tmp_remote_btc_5min_maker.db"
DEFAULT_LOCAL_DB = REPO_ROOT / "data" / "btc_5min_maker.db"
DEFAULT_RUNTIME_TRUTH = REPORTS_DIR / "runtime_truth_latest.json"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
DEFAULT_ARCHIVE_GLOB = "reports/btc_intraday_llm_bundle_*/raw/remote_btc5_window_trades.csv"
DEFAULT_REMOTE_ROWS_JSON = REPORTS_DIR / "tmp_remote_btc5_window_rows.json"
DEFAULT_UP_MAX = 0.49
DEFAULT_DOWN_MAX = 0.51
DEFAULT_MAX_ABS_DELTA = 0.00015
DEFAULT_CURRENT_TRADE_SIZE_USD = 5.0
DEFAULT_LOSS_LIMIT_USD = 10.0
DEFAULT_CAPACITY_TRADE_SIZES = (10.0, 20.0, 50.0, 100.0, 200.0)
CAPITAL_STAGE_TRADE_SIZES = (
    (1, 10.0),
    (2, 20.0),
    (3, 50.0),
)
SHADOW_TRADE_SIZES = (
    ("shadow_100", 100.0),
    ("shadow_200", 200.0),
)
WINDOW_MINUTES = 5
WINDOWS_PER_YEAR = int((365 * 24 * 60) / WINDOW_MINUTES)
REMOTE_BOT_DIR = "/home/ubuntu/polymarket-trading-bot"
ET_TZ = ZoneInfo("America/New_York")
ONE_TICK_USD = 0.01
ONE_TICK_RECOVERY_BASE = 0.60
LIVE_FILLED_STATUSES = {
    "live_filled",
    "live_partial_fill_cancelled",
    "live_partial_fill_open",
}
ORDER_FAILED_STATUSES = {
    "live_order_failed",
    "order_failed",
    "order_placement_failed",
    "post_only_cross_failure",
    "retry_failed",
}
CANCELLED_UNFILLED_STATUSES = {
    "live_cancelled_unfilled",
    "cancelled_unfilled",
    "cancel_before_fill",
    "retry_no_book",
    "retry_no_safe_price",
    "retry_size_too_large",
}
SKIP_PRICE_STATUSES = {
    "skip_price_outside_guardrails",
}

REMOTE_ROWS_PROBE_SCRIPT = """import json
import sqlite3
from pathlib import Path

db_path = Path("data/btc_5min_maker.db")
if not db_path.exists():
    print(json.dumps({"status": "unavailable", "reason": "missing_data/btc_5min_maker.db"}))
    raise SystemExit(0)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = [
    dict(row)
    for row in conn.execute(
        '''
        SELECT
            id,
            window_start_ts,
            slug,
            direction,
            delta,
            order_price,
            trade_size_usd,
            won,
            pnl_usd,
            order_status,
            updated_at
        FROM window_trades
        ORDER BY window_start_ts ASC, id ASC
        '''
    ).fetchall()
]
conn.close()
print(json.dumps({"status": "ok", "rows": rows}))
"""


@dataclass(frozen=True)
class GuardrailProfile:
    name: str
    max_abs_delta: float | None
    up_max_buy_price: float | None
    down_max_buy_price: float | None
    note: str = ""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now_utc().strftime("%Y%m%dT%H%M%SZ")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * (pct / 100.0)))
    index = max(0, min(index, len(ordered) - 1))
    return float(ordered[index])


def _round_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    rounded: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, float):
            rounded[key] = round(value, 4)
        else:
            rounded[key] = value
    return rounded


def _clamp(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _annualize_arr_pct(
    *,
    total_pnl_usd: float,
    average_deployed_capital_usd: float,
    horizon_windows: int,
) -> float:
    if average_deployed_capital_usd <= 0 or horizon_windows <= 0:
        return 0.0
    pnl_per_window = total_pnl_usd / float(horizon_windows)
    annual_profit_usd = pnl_per_window * float(WINDOWS_PER_YEAR)
    return (annual_profit_usd / average_deployed_capital_usd) * 100.0


def summarize_continuation_arr(
    *,
    historical: dict[str, Any],
    monte_carlo: dict[str, Any],
    avg_trade_size_usd_override: float | None = None,
) -> dict[str, Any]:
    replay_window_rows = max(0, _safe_int(historical.get("replay_window_rows")))
    replay_live_filled_rows = max(0, _safe_int(historical.get("replay_live_filled_rows")))
    trade_notional_usd = max(0.0, _safe_float(historical.get("trade_notional_usd"), 0.0))
    avg_trade_size_usd = max(0.0, _safe_float(avg_trade_size_usd_override, 0.0))
    if avg_trade_size_usd <= 0.0:
        avg_trade_size_usd = (
            trade_notional_usd / float(replay_live_filled_rows) if replay_live_filled_rows > 0 else 0.0
        )
    historical_avg_deployed_capital_usd = (
        trade_notional_usd / float(replay_window_rows) if replay_window_rows > 0 else 0.0
    )
    avg_active_trades = max(0.0, _safe_float(monte_carlo.get("avg_active_trades"), 0.0))
    horizon_trades = max(0, _safe_int(monte_carlo.get("horizon_trades")))
    monte_carlo_avg_deployed_capital_usd = (
        avg_trade_size_usd * avg_active_trades / float(horizon_trades) if horizon_trades > 0 else 0.0
    )
    return _round_metrics(
        {
            "metric_name": "continuation_arr_pct",
            "window_minutes": WINDOW_MINUTES,
            "windows_per_year": WINDOWS_PER_YEAR,
            "avg_trade_size_usd": avg_trade_size_usd,
            "historical_avg_deployed_capital_usd": historical_avg_deployed_capital_usd,
            "historical_arr_pct": _annualize_arr_pct(
                total_pnl_usd=_safe_float(historical.get("replay_live_filled_pnl_usd"), 0.0),
                average_deployed_capital_usd=historical_avg_deployed_capital_usd,
                horizon_windows=replay_window_rows,
            ),
            "monte_carlo_avg_deployed_capital_usd": monte_carlo_avg_deployed_capital_usd,
            "mean_arr_pct": _annualize_arr_pct(
                total_pnl_usd=_safe_float(monte_carlo.get("mean_total_pnl_usd"), 0.0),
                average_deployed_capital_usd=monte_carlo_avg_deployed_capital_usd,
                horizon_windows=horizon_trades,
            ),
            "median_arr_pct": _annualize_arr_pct(
                total_pnl_usd=_safe_float(monte_carlo.get("median_total_pnl_usd"), 0.0),
                average_deployed_capital_usd=monte_carlo_avg_deployed_capital_usd,
                horizon_windows=horizon_trades,
            ),
            "p05_arr_pct": _annualize_arr_pct(
                total_pnl_usd=_safe_float(monte_carlo.get("p05_total_pnl_usd"), 0.0),
                average_deployed_capital_usd=monte_carlo_avg_deployed_capital_usd,
                horizon_windows=horizon_trades,
            ),
            "p95_arr_pct": _annualize_arr_pct(
                total_pnl_usd=_safe_float(monte_carlo.get("p95_total_pnl_usd"), 0.0),
                average_deployed_capital_usd=monte_carlo_avg_deployed_capital_usd,
                horizon_windows=horizon_trades,
            ),
        }
    )


def _parse_env_file(path: Path) -> dict[str, str]:
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


def _parse_iso(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _et_hour_from_window_start_ts(window_start_ts: Any) -> int | None:
    ts = _safe_int(window_start_ts, default=0)
    if ts <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET_TZ)
    except (OverflowError, OSError, ValueError):
        return None
    return int(dt.hour)


def _session_name_for_et_hour(et_hour: int | None) -> str:
    if et_hour is None:
        return "unknown"
    if et_hour in {9, 10, 11}:
        return "open_et"
    if et_hour in {12, 13}:
        return "midday_et"
    if et_hour in {14, 15, 16}:
        return "late_et"
    return f"hour_et_{int(et_hour):02d}"


def _price_bucket(order_price: Any) -> str:
    price = _safe_float(order_price, 0.0)
    if price < 0.49:
        return "lt_0.49"
    if price <= 0.51:
        return "0.49_to_0.51"
    return "gt_0.51"


def _delta_bucket(abs_delta: Any) -> str:
    delta = abs(_safe_float(abs_delta, 0.0))
    if delta <= 0.00005:
        return "le_0.00005"
    if delta <= 0.00010:
        return "0.00005_to_0.00010"
    return "gt_0.00010"


def _regime_key(
    *,
    session_name: Any,
    direction: Any,
    price_bucket: Any,
    delta_bucket: Any,
) -> str:
    return "|".join(
        [
            str(session_name or "unknown"),
            str(direction or "UNKNOWN"),
            str(price_bucket or "unknown"),
            str(delta_bucket or "unknown"),
        ]
    )


def _source_priority(source: str) -> int:
    normalized = str(source or "").strip().lower()
    if normalized.startswith("remote_probe"):
        return 4
    if normalized.startswith("sqlite"):
        return 3
    if normalized.startswith("archive_csv"):
        return 2
    return 1


def _row_identity(row: dict[str, Any]) -> str:
    slug = str(row.get("slug") or "").strip()
    if slug:
        return slug
    window_start_ts = _safe_int(row.get("window_start_ts"))
    direction = str(row.get("direction") or "").strip().upper()
    return f"{window_start_ts}:{direction}"


def _is_live_filled_status(order_status: Any, trade_size_usd: Any = 0.0) -> bool:
    status = str(order_status or "").strip().lower()
    if status in LIVE_FILLED_STATUSES:
        return True
    return status.startswith("live_") and _safe_float(trade_size_usd, 0.0) > 0.0


def _is_live_attempt_status(order_status: Any) -> bool:
    return str(order_status or "").strip().lower().startswith("live_")


def _is_order_failed_status(order_status: Any) -> bool:
    return str(order_status or "").strip().lower() in ORDER_FAILED_STATUSES


def _is_cancelled_unfilled_status(order_status: Any) -> bool:
    return str(order_status or "").strip().lower() in CANCELLED_UNFILLED_STATUSES


def _is_skip_price_status(order_status: Any) -> bool:
    return str(order_status or "").strip().lower() in SKIP_PRICE_STATUSES


def _is_live_filled_row(row: dict[str, Any]) -> bool:
    return _is_live_filled_status(
        row.get("order_status"),
        row.get("trade_size_usd"),
    )


def _normalize_row(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    direction = str(payload.get("direction") or "").strip().upper()
    window_start_ts = _safe_int(payload.get("window_start_ts"))
    slug = str(payload.get("slug") or "").strip() or (
        f"btc-updown-5m-{window_start_ts}" if window_start_ts else ""
    )
    order_status = str(payload.get("order_status") or "").strip()
    delta = _safe_float(payload.get("delta"), 0.0)
    pnl_usd = _safe_float(payload.get("pnl_usd"), 0.0)
    et_hour = _et_hour_from_window_start_ts(window_start_ts)
    abs_delta = abs(delta)
    session_name = _session_name_for_et_hour(et_hour)
    price_bucket = _price_bucket(payload.get("order_price"))
    delta_bucket = _delta_bucket(abs_delta)
    return {
        "id": _safe_int(payload.get("id")),
        "window_start_ts": window_start_ts,
        "slug": slug,
        "direction": direction,
        "delta": delta,
        "abs_delta": abs_delta,
        "order_price": _safe_float(payload.get("order_price"), 0.0),
        "price_bucket": price_bucket,
        "delta_bucket": delta_bucket,
        "trade_size_usd": _safe_float(payload.get("trade_size_usd"), 0.0),
        "won": bool(payload.get("won")),
        "pnl_usd": pnl_usd,
        "realized_pnl_usd": pnl_usd if _is_live_filled_status(order_status, payload.get("trade_size_usd")) else 0.0,
        "order_status": order_status,
        "et_hour": et_hour,
        "session_name": session_name,
        "regime_key": _regime_key(
            session_name=session_name,
            direction=direction,
            price_bucket=price_bucket,
            delta_bucket=delta_bucket,
        ),
        "updated_at": _parse_iso(payload.get("updated_at")),
        "source": source,
        "source_priority": _source_priority(source),
    }


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_identity: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = _row_identity(row)
        current = best_by_identity.get(identity)
        if current is None:
            best_by_identity[identity] = row
            continue
        current_key = (
            _safe_int(current.get("source_priority")),
            str(current.get("updated_at") or ""),
            _safe_int(current.get("id")),
        )
        candidate_key = (
            _safe_int(row.get("source_priority")),
            str(row.get("updated_at") or ""),
            _safe_int(row.get("id")),
        )
        if candidate_key > current_key:
            best_by_identity[identity] = row
    return sorted(best_by_identity.values(), key=lambda row: (_safe_int(row.get("window_start_ts")), _safe_int(row.get("id"))))


def _default_db_path() -> Path:
    if DEFAULT_REMOTE_DB.exists():
        return DEFAULT_REMOTE_DB
    return DEFAULT_LOCAL_DB


def _load_runtime_truth(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _profile_key(profile: GuardrailProfile) -> tuple[float | None, float | None, float | None]:
    return (
        profile.max_abs_delta,
        profile.up_max_buy_price,
        profile.down_max_buy_price,
    )


def _live_profile_from_runtime_truth(runtime_truth: dict[str, Any]) -> GuardrailProfile:
    runtime = runtime_truth.get("runtime") or {}
    recommendation = runtime.get("btc5_guardrail_recommendation") or {}
    max_abs_delta = recommendation.get("max_abs_delta")
    up_max = recommendation.get("up_max_buy_price")
    down_max = recommendation.get("down_max_buy_price")
    return GuardrailProfile(
        name="runtime_recommended",
        max_abs_delta=_safe_float(max_abs_delta, DEFAULT_MAX_ABS_DELTA),
        up_max_buy_price=_safe_float(up_max, DEFAULT_UP_MAX),
        down_max_buy_price=_safe_float(down_max, DEFAULT_DOWN_MAX),
        note="latest runtime truth recommendation",
    )


def load_observed_rows_from_db(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"BTC5 DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                window_start_ts,
                slug,
                direction,
                delta,
                order_price,
                trade_size_usd,
                won,
                pnl_usd,
                order_status,
                updated_at
            FROM window_trades
            ORDER BY window_start_ts ASC, id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    return [_normalize_row(dict(row), source=f"sqlite:{db_path.name}") for row in rows]


def load_observed_rows_from_csv(csv_path: Path, *, source: str) -> list[dict[str, Any]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"BTC5 CSV not found: {csv_path}")
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return [_normalize_row(dict(row), source=source) for row in reader]


def fetch_remote_rows(env_path: Path = DEFAULT_ENV_PATH) -> list[dict[str, Any]]:
    env = {**os.environ, **_parse_env_file(env_path)}
    ssh_key = env.get("LIGHTSAIL_KEY")
    vps_ip = env.get("VPS_IP")
    vps_user = env.get("VPS_USER", "ubuntu")
    if not ssh_key or not vps_ip:
        raise RuntimeError("Missing LIGHTSAIL_KEY or VPS_IP for remote BTC5 pull.")
    remote_cmd = (
        f"cd {shlex.quote(REMOTE_BOT_DIR)} && /usr/bin/python3 - <<'PY'\n"
        f"{REMOTE_ROWS_PROBE_SCRIPT}\nPY"
    )
    result = subprocess.run(
        [
            "ssh",
            "-i",
            ssh_key,
            "-o",
            "StrictHostKeyChecking=no",
            f"{vps_user}@{vps_ip}",
            remote_cmd,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "remote probe failed").strip()[-400:])
    payload = json.loads((result.stdout or "").strip() or "{}")
    if payload.get("status") != "ok":
        raise RuntimeError(str(payload))
    rows = payload.get("rows") or []
    return [_normalize_row(dict(row), source="remote_probe:ssh") for row in rows if isinstance(row, dict)]


def assemble_observed_rows(
    *,
    db_path: Path | None,
    include_archive_csvs: bool,
    archive_glob: str,
    refresh_remote: bool,
    remote_cache_json: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    if db_path is not None and db_path.exists():
        db_rows = load_observed_rows_from_db(db_path)
        collected.extend(db_rows)
        sources.append(
            {
                "path": str(db_path),
                "source": f"sqlite:{db_path.name}",
                "rows_loaded": len(db_rows),
            }
        )

    if refresh_remote:
        remote_rows = fetch_remote_rows()
        remote_cache_json.parent.mkdir(parents=True, exist_ok=True)
        remote_cache_json.write_text(json.dumps(remote_rows, indent=2) + "\n")
        collected.extend(remote_rows)
        sources.append(
            {
                "path": str(remote_cache_json),
                "source": "remote_probe:ssh",
                "rows_loaded": len(remote_rows),
            }
        )

    if include_archive_csvs:
        for csv_path in sorted(REPO_ROOT.glob(archive_glob)):
            archive_rows = load_observed_rows_from_csv(csv_path, source=f"archive_csv:{csv_path.parent.parent.name}")
            collected.extend(archive_rows)
            sources.append(
                {
                    "path": str(csv_path),
                    "source": f"archive_csv:{csv_path.parent.parent.name}",
                    "rows_loaded": len(archive_rows),
                }
            )

    rows = _dedupe_rows(collected)
    filled_rows = [row for row in rows if _is_live_filled_row(row)]
    source_rollup: dict[str, int] = {}
    for row in rows:
        source_rollup[row["source"]] = source_rollup.get(row["source"], 0) + 1
    source_rollup = dict(sorted(source_rollup.items(), key=lambda item: (-item[1], item[0])))
    return rows, {
        "sources": sources,
        "deduped_rows": len(rows),
        "deduped_live_filled_rows": len(filled_rows),
        "rows_by_source": source_rollup,
        "first_window_start_ts": _safe_int(rows[0].get("window_start_ts")) if rows else None,
        "last_window_start_ts": _safe_int(rows[-1].get("window_start_ts")) if rows else None,
    }


def row_matches_profile(row: dict[str, Any], profile: GuardrailProfile) -> bool:
    direction = str(row.get("direction") or "").strip().upper()
    order_price = _safe_float(row.get("order_price"), 0.0)
    abs_delta = _safe_float(row.get("abs_delta"), abs(_safe_float(row.get("delta"), 0.0)))

    if profile.max_abs_delta is not None and abs_delta > profile.max_abs_delta:
        return False
    if direction == "UP" and profile.up_max_buy_price is not None and order_price > profile.up_max_buy_price:
        return False
    if direction == "DOWN" and profile.down_max_buy_price is not None and order_price > profile.down_max_buy_price:
        return False
    return True


def summarize_profile_history(rows: list[dict[str, Any]], profile: GuardrailProfile) -> dict[str, Any]:
    matched = [row for row in rows if row_matches_profile(row, profile)]
    baseline_filled = [row for row in rows if _is_live_filled_row(row)]
    matched_filled = [row for row in matched if _is_live_filled_row(row)]
    matched_attempted = [row for row in matched if str(row.get("order_status") or "").startswith("live_")]
    wins = sum(1 for row in matched_filled if _safe_float(row.get("pnl_usd"), 0.0) > 0)
    total_rows = len(rows)
    total_live_filled = len(baseline_filled)
    matched_rows = len(matched)
    matched_live_filled = len(matched_filled)
    replay_pnl = sum(_safe_float(row.get("pnl_usd"), 0.0) for row in matched_filled)
    total_notional = sum(_safe_float(row.get("trade_size_usd"), 0.0) for row in matched_filled)
    return _round_metrics(
        {
            "baseline_window_rows": total_rows,
            "baseline_live_filled_rows": total_live_filled,
            "replay_window_rows": matched_rows,
            "replay_attempt_rows": len(matched_attempted),
            "replay_live_filled_rows": matched_live_filled,
            "window_coverage_ratio": (matched_rows / total_rows) if total_rows else 0.0,
            "fill_coverage_ratio": (matched_live_filled / total_live_filled) if total_live_filled else 0.0,
            "replay_live_filled_pnl_usd": replay_pnl,
            "avg_pnl_usd": (replay_pnl / matched_live_filled) if matched_live_filled else 0.0,
            "win_rate": (wins / matched_live_filled) if matched_live_filled else 0.0,
            "trade_notional_usd": total_notional,
        }
    )


def build_candidate_profiles(
    rows: list[dict[str, Any]],
    *,
    current_live_profile: GuardrailProfile,
    runtime_recommended_profile: GuardrailProfile,
    top_grid_candidates: int,
    min_replay_fills: int,
) -> list[GuardrailProfile]:
    candidates: list[GuardrailProfile] = []
    seen: set[tuple[float | None, float | None, float | None]] = set()
    for profile in (
        GuardrailProfile(
            name="baseline_all_live_fills",
            max_abs_delta=None,
            up_max_buy_price=None,
            down_max_buy_price=None,
            note="no additional guardrails; use all observed live fills",
        ),
        current_live_profile,
        runtime_recommended_profile,
    ):
        key = _profile_key(profile)
        if key in seen:
            continue
        candidates.append(profile)
        seen.add(key)

    scored_grid: list[tuple[tuple[float, int, float, float], GuardrailProfile]] = []
    for max_abs_delta in (0.00002, 0.00005, 0.00010, 0.00015):
        for down_cap in (0.48, 0.49, 0.50, 0.51):
            for up_cap in (0.47, 0.48, 0.49, 0.50, 0.51):
                profile = GuardrailProfile(
                    name=f"grid_d{max_abs_delta:.5f}_up{up_cap:.2f}_down{down_cap:.2f}",
                    max_abs_delta=max_abs_delta,
                    up_max_buy_price=up_cap,
                    down_max_buy_price=down_cap,
                )
                history = summarize_profile_history(rows, profile)
                matched_rows = int(history["replay_live_filled_rows"])
                if matched_rows < min_replay_fills:
                    continue
                score = (
                    _safe_float(history["replay_live_filled_pnl_usd"], 0.0),
                    matched_rows,
                    -abs(down_cap - DEFAULT_DOWN_MAX),
                    -abs(up_cap - DEFAULT_UP_MAX),
                )
                scored_grid.append((score, profile))

    scored_grid.sort(key=lambda item: item[0], reverse=True)
    for _, profile in scored_grid:
        key = _profile_key(profile)
        if key in seen:
            continue
        candidates.append(profile)
        seen.add(key)
        if len(candidates) >= top_grid_candidates + 3:
            break
    return candidates


def _block_bootstrap_series(
    values: list[Any],
    *,
    horizon_trades: int,
    block_size: int,
    rng: random.Random,
) -> list[float]:
    if not values or horizon_trades <= 0:
        return []

    horizon = max(1, int(horizon_trades))
    block = max(1, min(int(block_size), len(values)))
    if len(values) == 1:
        return [values[0]] * horizon

    last_start = max(0, len(values) - block)
    sample: list[float] = []
    while len(sample) < horizon:
        start = rng.randint(0, last_start)
        sample.extend(values[start : start + block])
    return sample[:horizon]


def _profile_entries(rows: list[dict[str, Any]], profile: GuardrailProfile) -> list[dict[str, Any]]:
    regime_rollup = _regime_bucket_rollup(rows, profile=profile)
    regime_by_key = {
        str(item.get("regime_key") or ""): item
        for item in regime_rollup
    }
    entries: list[dict[str, Any]] = []
    for row in rows:
        matched = row_matches_profile(row, profile)
        regime_payload = regime_by_key.get(str(row.get("regime_key") or "")) or {}
        pnl_samples = list(regime_payload.get("pnl_samples") or [])
        negative_pnl_samples = list(regime_payload.get("negative_pnl_samples") or [])
        observed_trade_size_usd = max(
            0.0,
            _safe_float(row.get("trade_size_usd"), 0.0),
            _safe_float(regime_payload.get("observed_avg_trade_size_usd"), 0.0),
        )
        entries.append(
            {
                "pnl_usd": _safe_float(row.get("realized_pnl_usd"), 0.0) if matched else 0.0,
                "activation_probability": _clamp(
                    _safe_float(regime_payload.get("baseline_fill_probability"), 1.0 if matched else 0.0),
                    lower=0.0,
                    upper=1.0,
                )
                if matched
                else 0.0,
                "order_failed_probability": _clamp(
                    _safe_float(regime_payload.get("baseline_order_failed_rate"), 0.0),
                    lower=0.0,
                    upper=1.0,
                )
                if matched
                else 0.0,
                "cancelled_unfilled_probability": _clamp(
                    _safe_float(regime_payload.get("baseline_cancelled_unfilled_rate"), 0.0),
                    lower=0.0,
                    upper=1.0,
                )
                if matched
                else 0.0,
                "one_tick_probability": 0.0,
                "one_tick_cost_usd_if_triggered": 0.0,
                "execution_cost_usd": 0.0,
                "session_name": str(row.get("session_name") or "unknown"),
                "direction": str(row.get("direction") or "UNKNOWN"),
                "price_bucket": str(row.get("price_bucket") or "unknown"),
                "delta_bucket": str(row.get("delta_bucket") or "unknown"),
                "regime_key": str(row.get("regime_key") or ""),
                "trade_size_usd": observed_trade_size_usd,
                "effective_trade_size_usd": observed_trade_size_usd,
                "size_multiple": 1.0,
                "pnl_samples": pnl_samples,
                "negative_pnl_samples": negative_pnl_samples,
            }
        )
    return entries


def _matched_live_filled_rows(rows: list[dict[str, Any]], profile: GuardrailProfile) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row_matches_profile(row, profile) and _is_live_filled_row(row)
    ]


def _average_trade_size_usd(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    total = sum(max(0.0, _safe_float(row.get("trade_size_usd"), 0.0)) for row in rows)
    return total / float(len(rows)) if rows else 0.0


def _average_order_price(rows: list[dict[str, Any]], *, fallback: float = DEFAULT_UP_MAX) -> float:
    prices = [max(ONE_TICK_USD, _safe_float(row.get("order_price"), 0.0)) for row in rows if _safe_float(row.get("order_price"), 0.0) > 0.0]
    if not prices:
        return max(ONE_TICK_USD, float(fallback))
    return sum(prices) / float(len(prices))


def _one_tick_execution_cost_usd(*, trade_size_usd: float, order_price: float) -> float:
    price = max(ONE_TICK_USD, _safe_float(order_price, DEFAULT_UP_MAX))
    shares = max(0.0, float(trade_size_usd)) / price if price > 0.0 else 0.0
    return shares * ONE_TICK_USD


def _estimate_fill_retention_ratio(
    rows: list[dict[str, Any]],
    *,
    target_trade_size_usd: float,
    fallback_trade_size_usd: float,
) -> float:
    target = max(0.0, float(target_trade_size_usd))
    if target <= 0.0:
        return 0.0
    if not rows:
        fallback = max(0.0, float(fallback_trade_size_usd))
        return round(min(1.0, fallback / target) if fallback > 0 else 0.0, 4)

    retention_values: list[float] = []
    for row in rows:
        available = max(0.0, _safe_float(row.get("trade_size_usd"), fallback_trade_size_usd))
        retention_values.append(min(1.0, available / target) if target > 0 else 0.0)
    if not retention_values:
        return 0.0
    return round(sum(retention_values) / float(len(retention_values)), 4)


def _edge_weight_multiplier(bucket: dict[str, Any]) -> float:
    avg_trade_size = max(0.01, _safe_float(bucket.get("observed_avg_trade_size_usd"), 0.0), 5.0)
    avg_pnl_usd = _safe_float(bucket.get("avg_pnl_usd"), 0.0)
    win_rate = _clamp(_safe_float(bucket.get("win_rate"), 0.0), lower=0.0, upper=1.0)
    pnl_efficiency = _clamp(0.5 + (avg_pnl_usd / avg_trade_size), lower=0.0, upper=1.0)
    multiplier = 0.25 + (0.45 * win_rate) + (0.30 * pnl_efficiency)
    if avg_pnl_usd < 0.0:
        multiplier *= 0.6
    if str(bucket.get("session_name") or "") == "open_et" and avg_pnl_usd <= 0.0:
        multiplier *= 0.8
    return round(_clamp(multiplier, lower=0.25, upper=1.0), 4)


def _regime_bucket_rollup(
    rows: list[dict[str, Any]],
    *,
    profile: GuardrailProfile,
) -> list[dict[str, Any]]:
    matched_rows = [row for row in rows if row_matches_profile(row, profile)]
    matched_live_filled_rows = [row for row in matched_rows if _is_live_filled_row(row)]
    total_fill_weight = max(1, len(matched_live_filled_rows))
    buckets: dict[str, dict[str, Any]] = {}
    for row in matched_rows:
        regime_key = str(row.get("regime_key") or "")
        bucket = buckets.setdefault(
            regime_key,
            {
                "regime_key": regime_key,
                "session_name": str(row.get("session_name") or "unknown"),
                "direction": str(row.get("direction") or "UNKNOWN"),
                "price_bucket": str(row.get("price_bucket") or "unknown"),
                "delta_bucket": str(row.get("delta_bucket") or "unknown"),
                "rows": [],
                "live_filled_rows": [],
                "attempt_rows": 0,
                "order_failed_count": 0,
                "cancelled_unfilled_count": 0,
                "skip_price_count": 0,
            },
        )
        bucket["rows"].append(row)
        status = row.get("order_status")
        if _is_live_filled_row(row):
            bucket["live_filled_rows"].append(row)
        if _is_live_attempt_status(status):
            bucket["attempt_rows"] = int(bucket["attempt_rows"]) + 1
        if _is_order_failed_status(status):
            bucket["order_failed_count"] = int(bucket["order_failed_count"]) + 1
        if _is_cancelled_unfilled_status(status):
            bucket["cancelled_unfilled_count"] = int(bucket["cancelled_unfilled_count"]) + 1
        if _is_skip_price_status(status):
            bucket["skip_price_count"] = int(bucket["skip_price_count"]) + 1
    rollup: list[dict[str, Any]] = []
    for regime_key, bucket in sorted(
        buckets.items(),
        key=lambda item: (
            str(item[1].get("session_name") or ""),
            str(item[1].get("direction") or ""),
            str(item[1].get("price_bucket") or ""),
            str(item[1].get("delta_bucket") or ""),
            item[0],
        ),
    ):
        rows_count = len(bucket["rows"])
        live_filled_source_rows = list(bucket["live_filled_rows"])
        filled_rows = len(live_filled_source_rows)
        attempt_rows = max(1, int(bucket["attempt_rows"]))
        pnl_samples = [
            _safe_float(row.get("realized_pnl_usd"), 0.0)
            for row in live_filled_source_rows
            if abs(_safe_float(row.get("realized_pnl_usd"), 0.0)) > 1e-12
        ]
        negative_pnl_samples = [value for value in pnl_samples if value < 0.0]
        wins = sum(1 for value in pnl_samples if value > 0.0)
        fill_probability = filled_rows / float(max(1, rows_count))
        rollup.append(
            {
                "regime_key": regime_key,
                "session_name": str(bucket.get("session_name") or "unknown"),
                "direction": str(bucket.get("direction") or "UNKNOWN"),
                "price_bucket": str(bucket.get("price_bucket") or "unknown"),
                "delta_bucket": str(bucket.get("delta_bucket") or "unknown"),
                "matched_rows": rows_count,
                "live_filled_rows": filled_rows,
                "attempt_rows": int(bucket["attempt_rows"]),
                "observed_fill_share": filled_rows / float(total_fill_weight),
                "observed_avg_trade_size_usd": _average_trade_size_usd(live_filled_source_rows),
                "observed_avg_order_price": _average_order_price(live_filled_source_rows),
                "baseline_fill_probability": fill_probability,
                "baseline_order_failed_rate": _safe_int(bucket["order_failed_count"]) / float(attempt_rows),
                "baseline_cancelled_unfilled_rate": _safe_int(bucket["cancelled_unfilled_count"]) / float(attempt_rows),
                "baseline_post_only_retry_failure_rate": (
                    (_safe_int(bucket["order_failed_count"]) + _safe_int(bucket["cancelled_unfilled_count"]))
                    / float(attempt_rows)
                ),
                "baseline_skip_price_rate": _safe_int(bucket["skip_price_count"]) / float(max(1, rows_count)),
                "avg_pnl_usd": (sum(pnl_samples) / float(filled_rows)) if filled_rows else 0.0,
                "win_rate": (wins / float(filled_rows)) if filled_rows else 0.0,
                "pnl_samples": pnl_samples,
                "negative_pnl_samples": negative_pnl_samples,
                "live_filled_source_rows": live_filled_source_rows,
            }
        )
    return rollup


def _regime_size_sensitivity(
    *,
    rows: list[dict[str, Any]],
    profile: GuardrailProfile,
    target_trade_size_usd: float,
    reference_trade_size_usd: float,
    edge_tier_weighted: bool = False,
) -> list[dict[str, Any]]:
    sensitivity: list[dict[str, Any]] = []
    for bucket in _regime_bucket_rollup(rows, profile=profile):
        live_filled_rows = list(bucket.pop("live_filled_source_rows", []))
        edge_weight_multiplier = _edge_weight_multiplier(bucket) if edge_tier_weighted else 1.0
        effective_trade_size_usd = float(target_trade_size_usd) * edge_weight_multiplier
        observed_avg_trade_size_usd = max(
            0.0,
            _safe_float(bucket.get("observed_avg_trade_size_usd"), 0.0),
            reference_trade_size_usd,
        )
        size_multiple = (
            float(effective_trade_size_usd) / float(reference_trade_size_usd)
            if reference_trade_size_usd > 0.0
            else 0.0
        )
        same_level_fill_ratio = _estimate_fill_retention_ratio(
            live_filled_rows,
            target_trade_size_usd=effective_trade_size_usd,
            fallback_trade_size_usd=observed_avg_trade_size_usd,
        )
        shortfall_ratio = max(0.0, 1.0 - same_level_fill_ratio)
        baseline_retry_failure_rate = _safe_float(bucket.get("baseline_post_only_retry_failure_rate"), 0.0)
        recovery_share = 0.0
        if shortfall_ratio > 0.0 and size_multiple > 1.0:
            recovery_share = _clamp(
                ONE_TICK_RECOVERY_BASE * (1.0 - baseline_retry_failure_rate) / math.sqrt(size_multiple),
                lower=0.0,
                upper=0.95,
            )
        one_tick_worse_fill_ratio = shortfall_ratio * recovery_share
        effective_fill_retention_ratio = _clamp(
            same_level_fill_ratio + one_tick_worse_fill_ratio,
            lower=0.0,
            upper=1.0,
        )
        baseline_fill_probability = _clamp(
            _safe_float(bucket.get("baseline_fill_probability"), 0.0),
            lower=0.0,
            upper=1.0,
        )
        expected_fill_probability = _clamp(
            baseline_fill_probability * effective_fill_retention_ratio,
            lower=0.0,
            upper=1.0,
        )
        additional_non_fill_probability = max(0.0, baseline_fill_probability - expected_fill_probability)
        base_order_failed_probability = _clamp(
            _safe_float(bucket.get("baseline_order_failed_rate"), 0.0),
            lower=0.0,
            upper=1.0,
        )
        base_cancelled_probability = _clamp(
            _safe_float(bucket.get("baseline_cancelled_unfilled_rate"), 0.0),
            lower=0.0,
            upper=1.0,
        )
        failure_mix = base_order_failed_probability + base_cancelled_probability
        if failure_mix > 0.0:
            order_failed_probability = base_order_failed_probability + (
                additional_non_fill_probability * (base_order_failed_probability / failure_mix)
            )
            cancelled_unfilled_probability = base_cancelled_probability + (
                additional_non_fill_probability * (base_cancelled_probability / failure_mix)
            )
        else:
            order_failed_probability = additional_non_fill_probability
            cancelled_unfilled_probability = 0.0
        avg_one_tick_cost_usd = (
            sum(
                _one_tick_execution_cost_usd(
                    trade_size_usd=effective_trade_size_usd,
                    order_price=_safe_float(row.get("order_price"), 0.0),
                )
                for row in live_filled_rows
            )
            / float(len(live_filled_rows))
            if live_filled_rows
            else _one_tick_execution_cost_usd(
                trade_size_usd=effective_trade_size_usd,
                order_price=_safe_float(bucket.get("observed_avg_order_price"), DEFAULT_UP_MAX),
            )
        )
        conditional_one_tick_share = (
            one_tick_worse_fill_ratio / effective_fill_retention_ratio
            if effective_fill_retention_ratio > 0.0
            else 0.0
        )
        sensitivity.append(
            _round_metrics(
                {
                    **bucket,
                    "trade_size_usd": float(target_trade_size_usd),
                    "effective_trade_size_usd": effective_trade_size_usd,
                    "edge_weight_multiplier": edge_weight_multiplier,
                    "size_multiple": size_multiple,
                    "expected_same_level_fill_ratio": same_level_fill_ratio,
                    "expected_one_tick_worse_fill_ratio": one_tick_worse_fill_ratio,
                    "expected_fill_retention_ratio": effective_fill_retention_ratio,
                    "expected_fill_probability": expected_fill_probability,
                    "expected_order_failed_probability": _clamp(order_failed_probability, lower=0.0, upper=1.0),
                    "expected_cancelled_unfilled_probability": _clamp(
                        cancelled_unfilled_probability,
                        lower=0.0,
                        upper=1.0,
                    ),
                    "expected_post_only_retry_failure_rate": max(
                        0.0,
                        1.0 - expected_fill_probability,
                    ),
                    "expected_one_tick_fill_probability": conditional_one_tick_share,
                    "one_tick_cost_usd_if_triggered": avg_one_tick_cost_usd,
                    "expected_one_tick_cost_per_active_fill_usd": avg_one_tick_cost_usd * conditional_one_tick_share,
                    "expected_one_tick_cost_per_attempt_usd": avg_one_tick_cost_usd * one_tick_worse_fill_ratio,
                }
            )
        )
    return sensitivity


def _aggregate_regime_sensitivity(regime_sensitivity: list[dict[str, Any]]) -> dict[str, Any]:
    if not regime_sensitivity:
        return {
            "expected_same_level_fill_ratio": 0.0,
            "expected_one_tick_worse_fill_ratio": 0.0,
            "expected_fill_retention_ratio": 0.0,
            "expected_fill_probability": 0.0,
            "expected_order_failed_probability": 0.0,
            "expected_cancelled_unfilled_probability": 0.0,
            "expected_post_only_retry_failure_rate": 1.0,
            "expected_one_tick_fill_probability": 0.0,
            "expected_one_tick_cost_per_active_fill_usd": 0.0,
            "expected_one_tick_cost_per_attempt_usd": 0.0,
            "expected_trade_size_usd": 0.0,
            "edge_weight_multiplier": 0.0,
        }
    total_weight = sum(max(0.0, _safe_float(item.get("observed_fill_share"), 0.0)) for item in regime_sensitivity)
    if total_weight <= 0.0:
        total_weight = float(len(regime_sensitivity))

    def _weighted(field: str) -> float:
        numerator = 0.0
        for item in regime_sensitivity:
            weight = max(0.0, _safe_float(item.get("observed_fill_share"), 0.0))
            if total_weight == float(len(regime_sensitivity)) and total_weight > 0.0:
                weight = 1.0
            numerator += _safe_float(item.get(field), 0.0) * weight
        return numerator / float(total_weight) if total_weight > 0.0 else 0.0

    return _round_metrics(
        {
            "expected_same_level_fill_ratio": _weighted("expected_same_level_fill_ratio"),
            "expected_one_tick_worse_fill_ratio": _weighted("expected_one_tick_worse_fill_ratio"),
            "expected_fill_retention_ratio": _weighted("expected_fill_retention_ratio"),
            "expected_fill_probability": _weighted("expected_fill_probability"),
            "expected_order_failed_probability": _weighted("expected_order_failed_probability"),
            "expected_cancelled_unfilled_probability": _weighted("expected_cancelled_unfilled_probability"),
            "expected_post_only_retry_failure_rate": _weighted("expected_post_only_retry_failure_rate"),
            "expected_one_tick_fill_probability": _weighted("expected_one_tick_fill_probability"),
            "expected_one_tick_cost_per_active_fill_usd": _weighted("expected_one_tick_cost_per_active_fill_usd"),
            "expected_one_tick_cost_per_attempt_usd": _weighted("expected_one_tick_cost_per_attempt_usd"),
            "expected_trade_size_usd": _weighted("effective_trade_size_usd"),
            "edge_weight_multiplier": _weighted("edge_weight_multiplier"),
        }
    )


def _session_sensitivity_from_regimes(regime_sensitivity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in regime_sensitivity:
        grouped[str(item.get("session_name") or "unknown")].append(item)
    session_rollup: list[dict[str, Any]] = []
    for session_name, items in sorted(grouped.items()):
        total_weight = sum(max(0.0, _safe_float(item.get("observed_fill_share"), 0.0)) for item in items)
        if total_weight <= 0.0:
            total_weight = float(len(items))

        def _weighted(field: str) -> float:
            numerator = 0.0
            for item in items:
                weight = max(0.0, _safe_float(item.get("observed_fill_share"), 0.0))
                if total_weight == float(len(items)) and total_weight > 0.0:
                    weight = 1.0
                numerator += _safe_float(item.get(field), 0.0) * weight
            return numerator / float(total_weight) if total_weight > 0.0 else 0.0

        session_rollup.append(
            _round_metrics(
                {
                    "session_name": session_name,
                    "matched_rows": sum(_safe_int(item.get("matched_rows"), 0) for item in items),
                    "live_filled_rows": sum(_safe_int(item.get("live_filled_rows"), 0) for item in items),
                    "observed_fill_share": sum(
                        max(0.0, _safe_float(item.get("observed_fill_share"), 0.0)) for item in items
                    ),
                    "trade_size_usd": _weighted("trade_size_usd"),
                    "effective_trade_size_usd": _weighted("effective_trade_size_usd"),
                    "edge_weight_multiplier": _weighted("edge_weight_multiplier"),
                    "expected_same_level_fill_ratio": _weighted("expected_same_level_fill_ratio"),
                    "expected_one_tick_worse_fill_ratio": _weighted("expected_one_tick_worse_fill_ratio"),
                    "expected_fill_retention_ratio": _weighted("expected_fill_retention_ratio"),
                    "expected_fill_probability": _weighted("expected_fill_probability"),
                    "expected_order_failed_probability": _weighted("expected_order_failed_probability"),
                    "expected_cancelled_unfilled_probability": _weighted(
                        "expected_cancelled_unfilled_probability"
                    ),
                    "expected_post_only_retry_failure_rate": _weighted(
                        "expected_post_only_retry_failure_rate"
                    ),
                    "expected_one_tick_fill_probability": _weighted("expected_one_tick_fill_probability"),
                    "expected_one_tick_cost_per_active_fill_usd": _weighted(
                        "expected_one_tick_cost_per_active_fill_usd"
                    ),
                    "expected_one_tick_cost_per_attempt_usd": _weighted(
                        "expected_one_tick_cost_per_attempt_usd"
                    ),
                }
            )
        )
    return session_rollup


def _session_bucket_rollup(
    rows: list[dict[str, Any]],
    *,
    profile: GuardrailProfile,
) -> list[dict[str, Any]]:
    matched_rows = [row for row in rows if row_matches_profile(row, profile)]
    matched_live_filled_rows = [row for row in matched_rows if _is_live_filled_row(row)]
    total_fill_weight = max(1, len(matched_live_filled_rows))
    buckets: dict[str, dict[str, Any]] = {}
    for row in matched_rows:
        session_name = str(row.get("session_name") or "unknown")
        bucket = buckets.setdefault(
            session_name,
            {
                "session_name": session_name,
                "rows": [],
                "live_filled_rows": [],
                "attempt_rows": 0,
                "order_failed_count": 0,
                "cancelled_unfilled_count": 0,
                "skip_price_count": 0,
            },
        )
        bucket["rows"].append(row)
        status = row.get("order_status")
        if _is_live_filled_row(row):
            bucket["live_filled_rows"].append(row)
        if _is_live_attempt_status(status):
            bucket["attempt_rows"] = int(bucket["attempt_rows"]) + 1
        if _is_order_failed_status(status):
            bucket["order_failed_count"] = int(bucket["order_failed_count"]) + 1
        if _is_cancelled_unfilled_status(status):
            bucket["cancelled_unfilled_count"] = int(bucket["cancelled_unfilled_count"]) + 1
        if _is_skip_price_status(status):
            bucket["skip_price_count"] = int(bucket["skip_price_count"]) + 1
    rollup: list[dict[str, Any]] = []
    for session_name, bucket in sorted(buckets.items()):
        rows_count = len(bucket["rows"])
        filled_rows = len(bucket["live_filled_rows"])
        attempt_rows = max(1, int(bucket["attempt_rows"]))
        rollup.append(
            {
                "session_name": session_name,
                "matched_rows": rows_count,
                "live_filled_rows": filled_rows,
                "observed_fill_share": filled_rows / float(total_fill_weight),
                "observed_avg_trade_size_usd": _average_trade_size_usd(bucket["live_filled_rows"]),
                "observed_avg_order_price": _average_order_price(bucket["live_filled_rows"]),
                "baseline_order_failed_rate": _safe_int(bucket["order_failed_count"]) / float(attempt_rows),
                "baseline_cancelled_unfilled_rate": _safe_int(bucket["cancelled_unfilled_count"]) / float(attempt_rows),
                "baseline_post_only_retry_failure_rate": (
                    (_safe_int(bucket["order_failed_count"]) + _safe_int(bucket["cancelled_unfilled_count"]))
                    / float(attempt_rows)
                ),
                "baseline_skip_price_rate": _safe_int(bucket["skip_price_count"]) / float(max(1, rows_count)),
                "live_filled_source_rows": list(bucket["live_filled_rows"]),
            }
        )
    return rollup


def _session_size_sensitivity(
    *,
    rows: list[dict[str, Any]],
    profile: GuardrailProfile,
    target_trade_size_usd: float,
    reference_trade_size_usd: float,
) -> list[dict[str, Any]]:
    size_multiple = (
        float(target_trade_size_usd) / float(reference_trade_size_usd)
        if reference_trade_size_usd > 0.0
        else 0.0
    )
    sensitivity: list[dict[str, Any]] = []
    for bucket in _session_bucket_rollup(rows, profile=profile):
        live_filled_rows = list(bucket.pop("live_filled_source_rows", []))
        observed_avg_trade_size_usd = max(
            0.0,
            _safe_float(bucket.get("observed_avg_trade_size_usd"), 0.0),
            reference_trade_size_usd,
        )
        same_level_fill_ratio = _estimate_fill_retention_ratio(
            live_filled_rows,
            target_trade_size_usd=target_trade_size_usd,
            fallback_trade_size_usd=observed_avg_trade_size_usd,
        )
        shortfall_ratio = max(0.0, 1.0 - same_level_fill_ratio)
        baseline_retry_failure_rate = _safe_float(bucket.get("baseline_post_only_retry_failure_rate"), 0.0)
        recovery_share = 0.0
        if shortfall_ratio > 0.0 and size_multiple > 1.0:
            recovery_share = _clamp(
                ONE_TICK_RECOVERY_BASE * (1.0 - baseline_retry_failure_rate) / math.sqrt(size_multiple),
                lower=0.0,
                upper=0.95,
            )
        one_tick_worse_fill_ratio = shortfall_ratio * recovery_share
        effective_fill_retention_ratio = _clamp(
            same_level_fill_ratio + one_tick_worse_fill_ratio,
            lower=0.0,
            upper=1.0,
        )
        post_only_retry_failure_rate = max(0.0, 1.0 - effective_fill_retention_ratio)
        avg_one_tick_cost_usd = (
            sum(
                _one_tick_execution_cost_usd(
                    trade_size_usd=target_trade_size_usd,
                    order_price=_safe_float(row.get("order_price"), 0.0),
                )
                for row in live_filled_rows
            )
            / float(len(live_filled_rows))
            if live_filled_rows
            else _one_tick_execution_cost_usd(
                trade_size_usd=target_trade_size_usd,
                order_price=_safe_float(bucket.get("observed_avg_order_price"), DEFAULT_UP_MAX),
            )
        )
        conditional_one_tick_share = (
            one_tick_worse_fill_ratio / effective_fill_retention_ratio
            if effective_fill_retention_ratio > 0.0
            else 0.0
        )
        sensitivity.append(
            _round_metrics(
                {
                    **bucket,
                    "trade_size_usd": float(target_trade_size_usd),
                    "size_multiple": size_multiple,
                    "expected_same_level_fill_ratio": same_level_fill_ratio,
                    "expected_one_tick_worse_fill_ratio": one_tick_worse_fill_ratio,
                    "expected_fill_retention_ratio": effective_fill_retention_ratio,
                    "expected_post_only_retry_failure_rate": post_only_retry_failure_rate,
                    "expected_one_tick_cost_per_active_fill_usd": avg_one_tick_cost_usd * conditional_one_tick_share,
                    "expected_one_tick_cost_per_attempt_usd": avg_one_tick_cost_usd * one_tick_worse_fill_ratio,
                }
            )
        )
    return sensitivity


def _aggregate_session_sensitivity(session_sensitivity: list[dict[str, Any]]) -> dict[str, Any]:
    if not session_sensitivity:
        return {
            "expected_same_level_fill_ratio": 0.0,
            "expected_one_tick_worse_fill_ratio": 0.0,
            "expected_fill_retention_ratio": 0.0,
            "expected_fill_probability": 0.0,
            "expected_order_failed_probability": 0.0,
            "expected_cancelled_unfilled_probability": 0.0,
            "expected_post_only_retry_failure_rate": 1.0,
            "expected_one_tick_fill_probability": 0.0,
            "expected_one_tick_cost_per_active_fill_usd": 0.0,
            "expected_one_tick_cost_per_attempt_usd": 0.0,
        }
    total_weight = sum(max(0.0, _safe_float(item.get("observed_fill_share"), 0.0)) for item in session_sensitivity)
    if total_weight <= 0.0:
        total_weight = float(len(session_sensitivity))
    def _weighted(field: str) -> float:
        numerator = 0.0
        for item in session_sensitivity:
            weight = max(0.0, _safe_float(item.get("observed_fill_share"), 0.0))
            if total_weight == float(len(session_sensitivity)) and total_weight > 0.0:
                weight = 1.0
            numerator += _safe_float(item.get(field), 0.0) * weight
        return numerator / float(total_weight) if total_weight > 0.0 else 0.0
    return _round_metrics(
        {
            "expected_same_level_fill_ratio": _weighted("expected_same_level_fill_ratio"),
            "expected_one_tick_worse_fill_ratio": _weighted("expected_one_tick_worse_fill_ratio"),
            "expected_fill_retention_ratio": _weighted("expected_fill_retention_ratio"),
            "expected_fill_probability": _weighted("expected_fill_probability"),
            "expected_order_failed_probability": _weighted("expected_order_failed_probability"),
            "expected_cancelled_unfilled_probability": _weighted("expected_cancelled_unfilled_probability"),
            "expected_post_only_retry_failure_rate": _weighted("expected_post_only_retry_failure_rate"),
            "expected_one_tick_fill_probability": _weighted("expected_one_tick_fill_probability"),
            "expected_one_tick_cost_per_active_fill_usd": _weighted("expected_one_tick_cost_per_active_fill_usd"),
            "expected_one_tick_cost_per_attempt_usd": _weighted("expected_one_tick_cost_per_attempt_usd"),
        }
    )


def _loss_cluster_shock_scenarios(
    rows: list[dict[str, Any]],
    *,
    profile: GuardrailProfile,
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for bucket in _regime_bucket_rollup(rows, profile=profile):
        negative_samples = list(bucket.get("negative_pnl_samples") or [])
        if not negative_samples:
            continue
        session_name = str(bucket.get("session_name") or "unknown")
        if session_name not in {"open_et", "midday_et"} and len(negative_samples) < 2:
            continue
        loss_rows = len(negative_samples)
        matched_rows = max(1, _safe_int(bucket.get("matched_rows"), 0))
        avg_trade_size_usd = max(
            0.01,
            _safe_float(bucket.get("observed_avg_trade_size_usd"), 0.0),
            5.0,
        )
        total_loss_usd = sum(negative_samples)
        avg_loss_usd = abs(total_loss_usd) / float(loss_rows)
        loss_share = loss_rows / float(matched_rows)
        base_shock_probability = max(0.05 if session_name == "open_et" else 0.03, loss_share)
        scenarios.append(
            _round_metrics(
                {
                    "scenario_name": f"{session_name}_{bucket['direction'].lower()}_{bucket['price_bucket']}_{bucket['delta_bucket']}",
                    "regime_key": str(bucket.get("regime_key") or ""),
                    "session_name": session_name,
                    "direction": str(bucket.get("direction") or "UNKNOWN"),
                    "price_bucket": str(bucket.get("price_bucket") or "unknown"),
                    "delta_bucket": str(bucket.get("delta_bucket") or "unknown"),
                    "loss_rows": loss_rows,
                    "matched_rows": matched_rows,
                    "shock_probability": _clamp(
                        base_shock_probability,
                        lower=0.0,
                        upper=0.45 if session_name == "open_et" else 0.30,
                    ),
                    "fill_retention_multiplier": _clamp(
                        1.0 - (0.20 if session_name == "open_et" else 0.12) - (0.15 * loss_share),
                        lower=0.50,
                        upper=1.0,
                    ),
                    "retry_failure_lift": min(
                        0.30 if session_name == "open_et" else 0.20,
                        0.05 + (0.40 * loss_share),
                    ),
                    "negative_pnl_multiplier": 1.0 + min(1.0, avg_loss_usd / avg_trade_size_usd),
                    "prefer_negative_samples": True,
                    "total_loss_usd": total_loss_usd,
                    "avg_loss_usd": avg_loss_usd,
                }
            )
        )
    return sorted(
        scenarios,
        key=lambda item: (
            0 if str(item.get("session_name") or "") == "open_et" else 1,
            0 if str(item.get("session_name") or "") == "midday_et" else 1,
            -_safe_int(item.get("loss_rows"), 0),
            _safe_float(item.get("total_loss_usd"), 0.0),
        ),
    )


def _loss_cluster_scenario_matches_entry(
    scenario: dict[str, Any],
    entry: dict[str, Any],
) -> bool:
    regime_key = str(scenario.get("regime_key") or "")
    if regime_key and regime_key == str(entry.get("regime_key") or ""):
        return True
    for field in ("session_name", "direction", "price_bucket", "delta_bucket"):
        scenario_value = str(scenario.get(field) or "")
        entry_value = str(entry.get(field) or "")
        if scenario_value and scenario_value != entry_value:
            return False
    return True


def _activate_loss_cluster_scenarios(
    scenarios: list[dict[str, Any]],
    *,
    rng: random.Random,
) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for scenario in scenarios:
        if rng.random() <= _clamp(_safe_float(scenario.get("shock_probability"), 0.0), lower=0.0, upper=1.0):
            active.append(scenario)
    return active


def _stress_profile_entries(
    *,
    rows: list[dict[str, Any]],
    profile: GuardrailProfile,
    target_trade_size_usd: float,
    reference_trade_size_usd: float,
    regime_sensitivity: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sensitivity_by_regime = {
        str(item.get("regime_key") or ""): item
        for item in regime_sensitivity
    }
    entries: list[dict[str, Any]] = []
    for row in rows:
        if not row_matches_profile(row, profile):
            entries.append(
                {
                    "pnl_usd": 0.0,
                    "activation_probability": 0.0,
                    "execution_cost_usd": 0.0,
                    "session_name": str(row.get("session_name") or "unknown"),
                    "direction": str(row.get("direction") or "UNKNOWN"),
                    "price_bucket": str(row.get("price_bucket") or "unknown"),
                    "delta_bucket": str(row.get("delta_bucket") or "unknown"),
                    "regime_key": str(row.get("regime_key") or ""),
                    "trade_size_usd": 0.0,
                    "effective_trade_size_usd": 0.0,
                }
            )
            continue
        regime_payload = sensitivity_by_regime.get(str(row.get("regime_key") or "")) or {}
        observed_trade_size_usd = max(
            0.01,
            _safe_float(row.get("trade_size_usd"), 0.0),
            _safe_float(regime_payload.get("observed_avg_trade_size_usd"), 0.0),
            reference_trade_size_usd,
            5.0,
        )
        effective_trade_size_usd = max(
            0.0,
            _safe_float(regime_payload.get("effective_trade_size_usd"), target_trade_size_usd),
        )
        pnl_samples = list(regime_payload.get("pnl_samples") or [])
        negative_pnl_samples = list(regime_payload.get("negative_pnl_samples") or [])
        entries.append(
            {
                "pnl_usd": _safe_float(row.get("realized_pnl_usd"), 0.0),
                "activation_probability": _clamp(
                    _safe_float(
                        regime_payload.get("expected_fill_probability"),
                        _safe_float(regime_payload.get("baseline_fill_probability"), 0.0),
                    ),
                    lower=0.0,
                    upper=1.0,
                ),
                "order_failed_probability": _clamp(
                    _safe_float(regime_payload.get("expected_order_failed_probability"), 0.0),
                    lower=0.0,
                    upper=1.0,
                ),
                "cancelled_unfilled_probability": _clamp(
                    _safe_float(regime_payload.get("expected_cancelled_unfilled_probability"), 0.0),
                    lower=0.0,
                    upper=1.0,
                ),
                "one_tick_probability": _clamp(
                    _safe_float(regime_payload.get("expected_one_tick_fill_probability"), 0.0),
                    lower=0.0,
                    upper=1.0,
                ),
                "one_tick_cost_usd_if_triggered": max(
                    0.0,
                    _safe_float(regime_payload.get("one_tick_cost_usd_if_triggered"), 0.0),
                ),
                "execution_cost_usd": 0.0,
                "session_name": str(row.get("session_name") or "unknown"),
                "direction": str(row.get("direction") or "UNKNOWN"),
                "price_bucket": str(row.get("price_bucket") or "unknown"),
                "delta_bucket": str(row.get("delta_bucket") or "unknown"),
                "regime_key": str(row.get("regime_key") or ""),
                "trade_size_usd": observed_trade_size_usd,
                "effective_trade_size_usd": effective_trade_size_usd,
                "size_multiple": (
                    effective_trade_size_usd / observed_trade_size_usd
                    if observed_trade_size_usd > 0.0
                    else 1.0
                ),
                "pnl_samples": pnl_samples,
                "negative_pnl_samples": negative_pnl_samples,
            }
        )
    return entries


def _baseline_execution_drag(
    *,
    rows: list[dict[str, Any]],
    profile: GuardrailProfile,
) -> dict[str, Any]:
    matched_rows = [row for row in rows if row_matches_profile(row, profile)]
    matched_attempt_rows = [row for row in matched_rows if _is_live_attempt_status(row.get("order_status"))]
    live_filled_rows = [row for row in matched_rows if _is_live_filled_row(row)]
    order_failed_count = sum(1 for row in matched_rows if _is_order_failed_status(row.get("order_status")))
    cancelled_unfilled_count = sum(1 for row in matched_rows if _is_cancelled_unfilled_status(row.get("order_status")))
    skip_price_count = sum(1 for row in matched_rows if _is_skip_price_status(row.get("order_status")))
    attempts = max(1, len(matched_attempt_rows))
    total = max(1, len(matched_rows))
    return _round_metrics(
        {
            "matched_rows": len(matched_rows),
            "matched_attempt_rows": len(matched_attempt_rows),
            "matched_live_filled_rows": len(live_filled_rows),
            "skip_price_count": skip_price_count,
            "order_failed_count": order_failed_count,
            "cancelled_unfilled_count": cancelled_unfilled_count,
            "skip_price_rate": skip_price_count / float(total),
            "order_failed_rate": order_failed_count / float(attempts),
            "cancelled_unfilled_rate": cancelled_unfilled_count / float(attempts),
            "post_only_retry_failure_rate": (order_failed_count + cancelled_unfilled_count) / float(attempts),
            "session_baseline": [
                _round_metrics(
                    {
                        key: value
                        for key, value in bucket.items()
                        if key != "live_filled_source_rows"
                    }
                )
                for bucket in _session_bucket_rollup(rows, profile=profile)
            ],
        }
    )


def _regime_sampling_summary(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for entry in entries:
        regime_key = str(entry.get("regime_key") or "")
        if not regime_key or _clamp(_safe_float(entry.get("activation_probability"), 0.0), lower=0.0, upper=1.0) <= 0.0:
            continue
        bucket = buckets.setdefault(
            regime_key,
            {
                "regime_key": regime_key,
                "session_name": str(entry.get("session_name") or "unknown"),
                "direction": str(entry.get("direction") or "UNKNOWN"),
                "price_bucket": str(entry.get("price_bucket") or "unknown"),
                "delta_bucket": str(entry.get("delta_bucket") or "unknown"),
                "matched_rows": 0,
                "activation_probability_sum": 0.0,
                "order_failed_probability_sum": 0.0,
                "trade_size_usd_sum": 0.0,
                "pnl_sample_count": 0,
            },
        )
        bucket["matched_rows"] = int(bucket["matched_rows"]) + 1
        bucket["activation_probability_sum"] = _safe_float(bucket.get("activation_probability_sum"), 0.0) + _safe_float(
            entry.get("activation_probability"),
            0.0,
        )
        bucket["order_failed_probability_sum"] = _safe_float(
            bucket.get("order_failed_probability_sum"),
            0.0,
        ) + _safe_float(entry.get("order_failed_probability"), 0.0)
        bucket["trade_size_usd_sum"] = _safe_float(bucket.get("trade_size_usd_sum"), 0.0) + _safe_float(
            entry.get("effective_trade_size_usd"),
            entry.get("trade_size_usd"),
        )
        bucket["pnl_sample_count"] = int(bucket["pnl_sample_count"]) + len(entry.get("pnl_samples") or [])
    summary: list[dict[str, Any]] = []
    for bucket in buckets.values():
        matched_rows = max(1, _safe_int(bucket.get("matched_rows"), 0))
        summary.append(
            _round_metrics(
                {
                    "regime_key": str(bucket.get("regime_key") or ""),
                    "session_name": str(bucket.get("session_name") or "unknown"),
                    "direction": str(bucket.get("direction") or "UNKNOWN"),
                    "price_bucket": str(bucket.get("price_bucket") or "unknown"),
                    "delta_bucket": str(bucket.get("delta_bucket") or "unknown"),
                    "matched_rows": matched_rows,
                    "activation_probability": _safe_float(bucket.get("activation_probability_sum"), 0.0)
                    / float(matched_rows),
                    "order_failed_probability": _safe_float(bucket.get("order_failed_probability_sum"), 0.0)
                    / float(matched_rows),
                    "expected_trade_size_usd": _safe_float(bucket.get("trade_size_usd_sum"), 0.0)
                    / float(matched_rows),
                    "pnl_sample_count": _safe_int(bucket.get("pnl_sample_count"), 0),
                }
            )
        )
    summary.sort(
        key=lambda item: (
            _safe_int(item.get("matched_rows"), 0),
            _safe_float(item.get("activation_probability"), 0.0),
            _safe_float(item.get("expected_trade_size_usd"), 0.0),
        ),
        reverse=True,
    )
    return summary


def _simulate_entry_outcome(
    entry: dict[str, Any],
    *,
    rng: random.Random,
    active_loss_cluster_scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    session_name = str(entry.get("session_name") or "unknown")
    matched = _clamp(_safe_float(entry.get("activation_probability"), 0.0), lower=0.0, upper=1.0) > 0.0
    if not matched:
        return {
            "pnl_usd": 0.0,
            "active_trade": False,
            "order_failed": False,
            "cancelled_unfilled": False,
            "one_tick_adjusted": False,
            "deployed_capital_usd": 0.0,
            "session_name": session_name,
            "regime_key": str(entry.get("regime_key") or ""),
            "shock_applied": False,
            "triggered_loss_clusters": [],
        }

    triggered_loss_clusters = [
        scenario
        for scenario in active_loss_cluster_scenarios
        if _loss_cluster_scenario_matches_entry(scenario, entry)
    ]
    activation_probability = _clamp(
        _safe_float(entry.get("activation_probability"), 0.0),
        lower=0.0,
        upper=1.0,
    )
    order_failed_probability = _clamp(
        _safe_float(entry.get("order_failed_probability"), 0.0),
        lower=0.0,
        upper=1.0,
    )
    cancelled_unfilled_probability = _clamp(
        _safe_float(entry.get("cancelled_unfilled_probability"), 0.0),
        lower=0.0,
        upper=1.0,
    )
    negative_pnl_multiplier = 1.0
    prefer_negative_samples = False
    if triggered_loss_clusters:
        for scenario in triggered_loss_clusters:
            activation_probability = _clamp(
                activation_probability * _safe_float(scenario.get("fill_retention_multiplier"), 1.0),
                lower=0.0,
                upper=1.0,
            )
            order_failed_probability = _clamp(
                order_failed_probability + _safe_float(scenario.get("retry_failure_lift"), 0.0),
                lower=0.0,
                upper=1.0,
            )
            negative_pnl_multiplier = max(
                negative_pnl_multiplier,
                _safe_float(scenario.get("negative_pnl_multiplier"), 1.0),
            )
            prefer_negative_samples = prefer_negative_samples or bool(scenario.get("prefer_negative_samples"))

    if rng.random() > activation_probability:
        non_fill_roll = rng.random()
        order_failed = non_fill_roll <= order_failed_probability
        cancelled_unfilled = (not order_failed) and (
            non_fill_roll <= (order_failed_probability + cancelled_unfilled_probability)
        )
        return {
            "pnl_usd": 0.0,
            "active_trade": False,
            "order_failed": order_failed,
            "cancelled_unfilled": cancelled_unfilled,
            "one_tick_adjusted": False,
            "deployed_capital_usd": 0.0,
            "session_name": session_name,
            "regime_key": str(entry.get("regime_key") or ""),
            "shock_applied": bool(triggered_loss_clusters),
            "triggered_loss_clusters": [
                str(item.get("scenario_name") or "") for item in triggered_loss_clusters
            ],
        }

    pnl_samples = list(entry.get("pnl_samples") or [])
    if prefer_negative_samples and entry.get("negative_pnl_samples"):
        sample_pool = (
            list(entry.get("negative_pnl_samples") or [])
            if rng.random() <= 0.75
            else pnl_samples
        )
    else:
        sample_pool = pnl_samples
    raw_pnl = (
        _safe_float(rng.choice(sample_pool), 0.0)
        if sample_pool
        else _safe_float(entry.get("pnl_usd"), 0.0)
    )
    pnl = raw_pnl * max(0.0, _safe_float(entry.get("size_multiple"), 1.0))
    if pnl < 0.0:
        pnl *= negative_pnl_multiplier

    one_tick_adjusted = False
    one_tick_probability = _clamp(
        _safe_float(entry.get("one_tick_probability"), 0.0),
        lower=0.0,
        upper=1.0,
    )
    execution_cost_usd = max(0.0, _safe_float(entry.get("execution_cost_usd"), 0.0))
    if one_tick_probability > 0.0 and rng.random() <= one_tick_probability:
        one_tick_adjusted = True
        execution_cost_usd = max(
            execution_cost_usd,
            _safe_float(entry.get("one_tick_cost_usd_if_triggered"), 0.0),
        )
    pnl -= execution_cost_usd

    return {
        "pnl_usd": pnl,
        "active_trade": True,
        "order_failed": False,
        "cancelled_unfilled": False,
        "one_tick_adjusted": one_tick_adjusted,
        "deployed_capital_usd": max(
            0.0,
            _safe_float(
                entry.get("effective_trade_size_usd"),
                _safe_float(entry.get("trade_size_usd"), 0.0),
            ),
        ),
        "session_name": session_name,
        "regime_key": str(entry.get("regime_key") or ""),
        "shock_applied": bool(triggered_loss_clusters),
        "triggered_loss_clusters": [
            str(item.get("scenario_name") or "") for item in triggered_loss_clusters
        ],
    }


def _run_monte_carlo_from_entries(
    entries: list[dict[str, Any]],
    *,
    paths: int,
    horizon_trades: int,
    block_size: int,
    loss_limit_usd: float,
    seed_material: str,
    sampling_dimensions: list[str] | None = None,
    loss_cluster_scenarios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    non_zero = [
        entry
        for entry in entries
        if (
            abs(_safe_float(entry.get("pnl_usd"), 0.0)) > 1e-12
            or bool(entry.get("pnl_samples"))
        )
    ]
    if not entries:
        return {
            "paths": int(paths),
            "horizon_trades": int(horizon_trades),
            "block_size": int(block_size),
            "loss_limit_usd": round(loss_limit_usd, 4),
            "profit_probability": 0.0,
            "non_positive_probability": 1.0,
            "active_trade_ratio": 0.0,
            "mean_total_pnl_usd": 0.0,
            "median_total_pnl_usd": 0.0,
            "p05_total_pnl_usd": 0.0,
            "p95_total_pnl_usd": 0.0,
            "avg_max_drawdown_usd": 0.0,
            "p95_max_drawdown_usd": 0.0,
            "loss_limit_hit_probability": 0.0,
            "daily_loss_hit_probability": 0.0,
            "avg_active_trades": 0.0,
            "expected_active_trade_load": 0.0,
            "avg_win_rate": 0.0,
            "avg_order_failed_trades": 0.0,
            "avg_cancelled_unfilled_trades": 0.0,
            "avg_one_tick_adjustments": 0.0,
            "avg_deployed_capital_usd": 0.0,
            "capital_efficiency": 0.0,
            "loss_cluster_shock_hit_probability": 0.0,
            "sampling_dimensions": list(sampling_dimensions or []),
            "regime_sampling_summary": [],
            "session_tail_contribution": [],
            "loss_cluster_scenarios": list(loss_cluster_scenarios or []),
            "ranking_score": 0.0,
        }

    rng = random.Random(
        f"{seed_material}:{paths}:{horizon_trades}:{block_size}:{loss_limit_usd:.6f}"
    )
    total_pnls: list[float] = []
    max_drawdowns: list[float] = []
    active_counts: list[int] = []
    win_rates: list[float] = []
    order_failed_counts: list[int] = []
    cancelled_counts: list[int] = []
    one_tick_counts: list[int] = []
    deployed_capitals: list[float] = []
    loss_limit_hits = 0
    daily_loss_hits = 0
    loss_cluster_hit_paths = 0
    path_tail_details: list[dict[str, Any]] = []
    daily_window_trades = max(1, min(int(horizon_trades), int((24 * 60) / WINDOW_MINUTES)))
    regime_summary = _regime_sampling_summary(entries)

    for _ in range(max(1, int(paths))):
        path = _block_bootstrap_series(
            entries,
            horizon_trades=max(1, int(horizon_trades)),
            block_size=max(1, int(block_size)),
            rng=rng,
        )
        active_loss_clusters = _activate_loss_cluster_scenarios(
            list(loss_cluster_scenarios or []),
            rng=rng,
        )
        running_pnl = 0.0
        peak_pnl = 0.0
        max_drawdown = 0.0
        active_trades = 0
        wins = 0
        loss_limit_hit = False
        daily_loss_hit = False
        order_failed_trades = 0
        cancelled_unfilled_trades = 0
        one_tick_adjustments = 0
        deployed_capital_usd = 0.0
        path_session_drawdown: dict[str, float] = defaultdict(float)
        path_session_losses: dict[str, float] = defaultdict(float)
        rolling_daily = deque(maxlen=daily_window_trades)
        triggered_loss_clusters: set[str] = set()

        for entry in path:
            previous_drawdown = max(0.0, peak_pnl - running_pnl)
            outcome = _simulate_entry_outcome(
                entry,
                rng=rng,
                active_loss_cluster_scenarios=active_loss_clusters,
            )
            pnl = _safe_float(outcome.get("pnl_usd"), 0.0)
            session_name = str(outcome.get("session_name") or "unknown")
            if bool(outcome.get("active_trade")):
                active_trades += 1
                deployed_capital_usd += max(0.0, _safe_float(outcome.get("deployed_capital_usd"), 0.0))
                if pnl > 0:
                    wins += 1
            if bool(outcome.get("order_failed")):
                order_failed_trades += 1
            if bool(outcome.get("cancelled_unfilled")):
                cancelled_unfilled_trades += 1
            if bool(outcome.get("one_tick_adjusted")):
                one_tick_adjustments += 1
            if pnl < 0.0:
                path_session_losses[session_name] += abs(pnl)
            if bool(outcome.get("shock_applied")):
                triggered_loss_clusters.update(
                    str(label or "") for label in outcome.get("triggered_loss_clusters") or []
                )
            running_pnl += pnl
            rolling_daily.append(pnl)
            if sum(rolling_daily) <= -abs(loss_limit_usd):
                daily_loss_hit = True
            peak_pnl = max(peak_pnl, running_pnl)
            max_drawdown = max(max_drawdown, peak_pnl - running_pnl)
            current_drawdown = max(0.0, peak_pnl - running_pnl)
            drawdown_increase = max(0.0, current_drawdown - previous_drawdown)
            if drawdown_increase > 0.0:
                path_session_drawdown[session_name] += drawdown_increase
            if running_pnl <= -abs(loss_limit_usd):
                loss_limit_hit = True

        if loss_limit_hit:
            loss_limit_hits += 1
        if daily_loss_hit:
            daily_loss_hits += 1
        if triggered_loss_clusters:
            loss_cluster_hit_paths += 1
        total_pnls.append(running_pnl)
        max_drawdowns.append(max_drawdown)
        active_counts.append(active_trades)
        win_rates.append((wins / active_trades) if active_trades else 0.0)
        order_failed_counts.append(order_failed_trades)
        cancelled_counts.append(cancelled_unfilled_trades)
        one_tick_counts.append(one_tick_adjustments)
        deployed_capitals.append(deployed_capital_usd)
        path_tail_details.append(
            {
                "total_pnl_usd": running_pnl,
                "max_drawdown_usd": max_drawdown,
                "session_drawdown": dict(path_session_drawdown),
                "session_losses": dict(path_session_losses),
                "triggered_loss_clusters": sorted(triggered_loss_clusters),
            }
        )

    profit_probability = sum(1 for value in total_pnls if value > 0) / len(total_pnls)
    avg_active_trades = sum(active_counts) / len(active_counts)
    avg_win_rate = sum(win_rates) / len(win_rates)
    avg_deployed_capital_usd = sum(deployed_capitals) / len(deployed_capitals)
    capital_efficiency = (
        (sum(total_pnls) / len(total_pnls)) / avg_deployed_capital_usd
        if avg_deployed_capital_usd > 0.0
        else 0.0
    )
    p95_drawdown_cutoff = _percentile(max_drawdowns, 95)
    tail_paths = [
        detail
        for detail in path_tail_details
        if _safe_float(detail.get("max_drawdown_usd"), 0.0) >= p95_drawdown_cutoff
    ]
    non_positive_paths = [
        detail
        for detail in path_tail_details
        if _safe_float(detail.get("total_pnl_usd"), 0.0) <= 0.0
    ]
    all_sessions = sorted(
        {
            session_name
            for detail in path_tail_details
            for session_name in (
                set((detail.get("session_drawdown") or {}).keys())
                | set((detail.get("session_losses") or {}).keys())
            )
        }
    )
    session_tail_contribution: list[dict[str, Any]] = []
    total_tail_drawdown = sum(
        _safe_float(amount, 0.0)
        for detail in tail_paths
        for amount in (detail.get("session_drawdown") or {}).values()
    )
    total_non_positive_losses = sum(
        _safe_float(amount, 0.0)
        for detail in non_positive_paths
        for amount in (detail.get("session_losses") or {}).values()
    )
    for session_name in all_sessions:
        tail_drawdown_sum = sum(
            _safe_float((detail.get("session_drawdown") or {}).get(session_name), 0.0)
            for detail in tail_paths
        )
        tail_drawdown_presence = sum(
            1
            for detail in tail_paths
            if _safe_float((detail.get("session_drawdown") or {}).get(session_name), 0.0) > 0.0
        )
        non_positive_loss_sum = sum(
            _safe_float((detail.get("session_losses") or {}).get(session_name), 0.0)
            for detail in non_positive_paths
        )
        non_positive_presence = sum(
            1
            for detail in non_positive_paths
            if _safe_float((detail.get("session_losses") or {}).get(session_name), 0.0) > 0.0
        )
        if tail_drawdown_sum <= 0.0 and non_positive_loss_sum <= 0.0:
            continue
        avg_tail_drawdown_usd = (
            tail_drawdown_sum / float(len(tail_paths))
            if tail_paths
            else 0.0
        )
        avg_non_positive_loss_usd = (
            non_positive_loss_sum / float(len(non_positive_paths))
            if non_positive_paths
            else 0.0
        )
        session_tail_contribution.append(
            _round_metrics(
                {
                    "session_name": session_name,
                    "p95_drawdown_contribution_usd": avg_tail_drawdown_usd,
                    "p95_drawdown_contribution_share": (
                        tail_drawdown_sum / float(total_tail_drawdown)
                        if total_tail_drawdown > 0.0
                        else 0.0
                    ),
                    "tail_path_share": (
                        tail_drawdown_presence / float(len(tail_paths))
                        if tail_paths
                        else 0.0
                    ),
                    "non_positive_loss_contribution_usd": avg_non_positive_loss_usd,
                    "non_positive_loss_share": (
                        non_positive_loss_sum / float(total_non_positive_losses)
                        if total_non_positive_losses > 0.0
                        else 0.0
                    ),
                    "non_positive_path_share": (
                        non_positive_presence / float(len(non_positive_paths))
                        if non_positive_paths
                        else 0.0
                    ),
                }
            )
        )
    session_tail_contribution.sort(
        key=lambda item: (
            _safe_float(item.get("p95_drawdown_contribution_share"), 0.0),
            _safe_float(item.get("non_positive_loss_share"), 0.0),
        ),
        reverse=True,
    )
    ranking_score = (
        _percentile(total_pnls, 50) * profit_probability
        - _percentile(max_drawdowns, 95) * (loss_limit_hits / len(total_pnls))
    )
    return _round_metrics(
        {
            "paths": int(paths),
            "horizon_trades": int(horizon_trades),
            "block_size": int(block_size),
            "loss_limit_usd": loss_limit_usd,
            "empirical_non_zero_rows": len(non_zero),
            "profit_probability": profit_probability,
            "non_positive_probability": 1.0 - profit_probability,
            "active_trade_ratio": (avg_active_trades / max(1, horizon_trades)),
            "mean_total_pnl_usd": sum(total_pnls) / len(total_pnls),
            "median_total_pnl_usd": _percentile(total_pnls, 50),
            "p05_total_pnl_usd": _percentile(total_pnls, 5),
            "p95_total_pnl_usd": _percentile(total_pnls, 95),
            "avg_max_drawdown_usd": sum(max_drawdowns) / len(max_drawdowns),
            "p95_max_drawdown_usd": _percentile(max_drawdowns, 95),
            "loss_limit_hit_probability": loss_limit_hits / len(total_pnls),
            "daily_loss_hit_probability": daily_loss_hits / len(total_pnls),
            "avg_active_trades": avg_active_trades,
            "expected_active_trade_load": avg_active_trades,
            "avg_win_rate": avg_win_rate,
            "avg_order_failed_trades": sum(order_failed_counts) / len(order_failed_counts),
            "avg_cancelled_unfilled_trades": sum(cancelled_counts) / len(cancelled_counts),
            "avg_one_tick_adjustments": sum(one_tick_counts) / len(one_tick_counts),
            "avg_deployed_capital_usd": avg_deployed_capital_usd,
            "capital_efficiency": capital_efficiency,
            "loss_cluster_shock_hit_probability": loss_cluster_hit_paths / len(total_pnls),
            "sampling_dimensions": list(sampling_dimensions or []),
            "regime_sampling_summary": regime_summary[:12],
            "session_tail_contribution": session_tail_contribution[:6],
            "loss_cluster_scenarios": list(loss_cluster_scenarios or [])[:8],
            "ranking_score": ranking_score,
        }
    )


def run_monte_carlo(
    rows: list[dict[str, Any]],
    profile: GuardrailProfile,
    *,
    paths: int,
    horizon_trades: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
) -> dict[str, Any]:
    entries = _profile_entries(rows, profile)
    loss_cluster_scenarios = _loss_cluster_shock_scenarios(rows, profile=profile)
    return _run_monte_carlo_from_entries(
        entries,
        paths=paths,
        horizon_trades=horizon_trades,
        block_size=block_size,
        loss_limit_usd=loss_limit_usd,
        seed_material=f"{seed}:{_profile_key(profile)}",
        sampling_dimensions=["session_name", "direction", "price_bucket", "delta_bucket"],
        loss_cluster_scenarios=loss_cluster_scenarios,
    )


def build_capacity_stress_summary(
    *,
    rows: list[dict[str, Any]],
    profile: GuardrailProfile,
    historical: dict[str, Any],
    monte_carlo: dict[str, Any],
    continuation: dict[str, Any],
    current_trade_size_usd: float | None = DEFAULT_CURRENT_TRADE_SIZE_USD,
    paths: int,
    horizon_trades: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
    trade_sizes_usd: tuple[float, ...] = DEFAULT_CAPACITY_TRADE_SIZES,
) -> dict[str, Any]:
    matched_live_filled_rows = _matched_live_filled_rows(rows, profile)
    observed_avg_trade_size_usd = max(
        0.0,
        _safe_float(continuation.get("avg_trade_size_usd"), 0.0),
        _average_trade_size_usd(matched_live_filled_rows),
    )
    configured_current_trade_size_usd = max(0.0, _safe_float(current_trade_size_usd, 0.0))
    reference_trade_size_usd = (
        configured_current_trade_size_usd
        or observed_avg_trade_size_usd
        or DEFAULT_CURRENT_TRADE_SIZE_USD
    )
    reference_trade_size_source = (
        "configured_current_trade_size_usd"
        if configured_current_trade_size_usd > 0.0
        else ("observed_avg_trade_size_usd" if observed_avg_trade_size_usd > 0.0 else "default_current_trade_size_usd")
    )
    base_median_arr_pct = _safe_float(continuation.get("median_arr_pct"), 0.0)
    base_p05_arr_pct = _safe_float(continuation.get("p05_arr_pct"), 0.0)
    base_loss_hit_probability = _safe_float(monte_carlo.get("loss_limit_hit_probability"), 0.0)
    base_daily_loss_hit_probability = _safe_float(monte_carlo.get("daily_loss_hit_probability"), 0.0)
    base_profit_probability = _safe_float(monte_carlo.get("profit_probability"), 0.0)
    base_non_positive_probability = _safe_float(monte_carlo.get("non_positive_probability"), 0.0)
    base_avg_max_drawdown_usd = _safe_float(monte_carlo.get("avg_max_drawdown_usd"), 0.0)
    base_p95_max_drawdown_usd = _safe_float(monte_carlo.get("p95_max_drawdown_usd"), 0.0)
    base_capital_efficiency = _safe_float(monte_carlo.get("capital_efficiency"), 0.0)
    base_active_trade_load = _safe_float(monte_carlo.get("expected_active_trade_load"), 0.0)
    baseline_execution_drag = _baseline_execution_drag(rows=rows, profile=profile)
    loss_cluster_scenarios = _loss_cluster_shock_scenarios(rows, profile=profile)

    sweeps: list[dict[str, Any]] = []
    size_levels = sorted(
        {
            round(reference_trade_size_usd, 4),
            *{
                round(float(size), 4)
                for size in trade_sizes_usd
                if float(size) > 0.0
            },
        }
    )
    for trade_size_usd in size_levels:
        regime_sensitivity = _regime_size_sensitivity(
            rows=rows,
            profile=profile,
            target_trade_size_usd=trade_size_usd,
            reference_trade_size_usd=reference_trade_size_usd,
        )
        session_sensitivity = _session_sensitivity_from_regimes(regime_sensitivity)
        aggregate_sensitivity = _aggregate_regime_sensitivity(regime_sensitivity)
        fill_retention_ratio = _safe_float(aggregate_sensitivity.get("expected_fill_retention_ratio"), 0.0)
        stress_entries = _stress_profile_entries(
            rows=rows,
            profile=profile,
            target_trade_size_usd=trade_size_usd,
            reference_trade_size_usd=reference_trade_size_usd,
            regime_sensitivity=regime_sensitivity,
        )
        if (
            abs(trade_size_usd - reference_trade_size_usd) <= 1e-9
            and abs(fill_retention_ratio - 1.0) <= 1e-9
            and abs(_safe_float(aggregate_sensitivity.get("expected_one_tick_cost_per_active_fill_usd"), 0.0)) <= 1e-9
        ):
            stress_monte_carlo = dict(monte_carlo)
            stress_continuation = dict(continuation)
        else:
            stress_monte_carlo = _run_monte_carlo_from_entries(
                stress_entries,
                paths=paths,
                horizon_trades=horizon_trades,
                block_size=block_size,
                loss_limit_usd=loss_limit_usd,
                seed_material=f"{seed}:{profile.name}:{trade_size_usd:.2f}",
                sampling_dimensions=["session_name", "direction", "price_bucket", "delta_bucket"],
                loss_cluster_scenarios=loss_cluster_scenarios,
            )
            stress_continuation = summarize_continuation_arr(
                historical=historical,
                monte_carlo=stress_monte_carlo,
                avg_trade_size_usd_override=trade_size_usd,
            )
        capital_stage = next(
            (int(stage) for stage, size in CAPITAL_STAGE_TRADE_SIZES if abs(float(size) - trade_size_usd) <= 1e-9),
            None,
        )
        shadow_label = next(
            (label for label, size in SHADOW_TRADE_SIZES if abs(float(size) - trade_size_usd) <= 1e-9),
            None,
        )
        sizing_track = "current_base" if abs(trade_size_usd - reference_trade_size_usd) <= 1e-9 else ("shadow" if shadow_label else "live_stage")
        sweeps.append(
            _round_metrics(
                {
                    "trade_size_usd": trade_size_usd,
                    "sizing_track": sizing_track,
                    "capital_stage": capital_stage,
                    "stage_label": (
                        "current_base_cap"
                        if sizing_track == "current_base"
                        else (f"stage_{capital_stage}" if capital_stage is not None else None)
                    ),
                    "shadow_label": shadow_label,
                    "size_multiple": (trade_size_usd / reference_trade_size_usd) if reference_trade_size_usd > 0 else 0.0,
                    "expected_same_level_fill_ratio": _safe_float(
                        aggregate_sensitivity.get("expected_same_level_fill_ratio"),
                        0.0,
                    ),
                    "expected_fill_probability": _safe_float(
                        aggregate_sensitivity.get("expected_fill_probability"),
                        0.0,
                    ),
                    "expected_fill_retention_ratio": fill_retention_ratio,
                    "fill_retention_impact": fill_retention_ratio - 1.0,
                    "expected_one_tick_worse_fill_ratio": _safe_float(
                        aggregate_sensitivity.get("expected_one_tick_worse_fill_ratio"),
                        0.0,
                    ),
                    "expected_order_failed_probability": _safe_float(
                        aggregate_sensitivity.get("expected_order_failed_probability"),
                        0.0,
                    ),
                    "expected_cancelled_unfilled_probability": _safe_float(
                        aggregate_sensitivity.get("expected_cancelled_unfilled_probability"),
                        0.0,
                    ),
                    "expected_post_only_retry_failure_rate": _safe_float(
                        aggregate_sensitivity.get("expected_post_only_retry_failure_rate"),
                        0.0,
                    ),
                    "expected_one_tick_fill_probability": _safe_float(
                        aggregate_sensitivity.get("expected_one_tick_fill_probability"),
                        0.0,
                    ),
                    "expected_one_tick_cost_per_active_fill_usd": _safe_float(
                        aggregate_sensitivity.get("expected_one_tick_cost_per_active_fill_usd"),
                        0.0,
                    ),
                    "expected_one_tick_cost_per_attempt_usd": _safe_float(
                        aggregate_sensitivity.get("expected_one_tick_cost_per_attempt_usd"),
                        0.0,
                    ),
                    "expected_profit_probability": _safe_float(
                        stress_monte_carlo.get("profit_probability"),
                        0.0,
                    ),
                    "profit_probability_impact": _safe_float(
                        stress_monte_carlo.get("profit_probability"),
                        0.0,
                    )
                    - base_profit_probability,
                    "expected_non_positive_path_probability": _safe_float(
                        stress_monte_carlo.get("non_positive_probability"),
                        0.0,
                    ),
                    "non_positive_path_probability_impact": _safe_float(
                        stress_monte_carlo.get("non_positive_probability"),
                        0.0,
                    )
                    - base_non_positive_probability,
                    "expected_loss_limit_hit_probability": _safe_float(
                        stress_monte_carlo.get("loss_limit_hit_probability"),
                        0.0,
                    ),
                    "loss_hit_probability_impact": _safe_float(
                        stress_monte_carlo.get("loss_limit_hit_probability"),
                        0.0,
                    )
                    - base_loss_hit_probability,
                    "expected_daily_loss_hit_probability": _safe_float(
                        stress_monte_carlo.get("daily_loss_hit_probability"),
                        0.0,
                    ),
                    "daily_loss_hit_probability_impact": _safe_float(
                        stress_monte_carlo.get("daily_loss_hit_probability"),
                        0.0,
                    )
                    - base_daily_loss_hit_probability,
                    "expected_avg_max_drawdown_usd": _safe_float(
                        stress_monte_carlo.get("avg_max_drawdown_usd"),
                        0.0,
                    ),
                    "avg_drawdown_impact_usd": _safe_float(
                        stress_monte_carlo.get("avg_max_drawdown_usd"),
                        0.0,
                    )
                    - base_avg_max_drawdown_usd,
                    "expected_p95_max_drawdown_usd": _safe_float(
                        stress_monte_carlo.get("p95_max_drawdown_usd"),
                        0.0,
                    ),
                    "p95_drawdown_impact_usd": _safe_float(
                        stress_monte_carlo.get("p95_max_drawdown_usd"),
                        0.0,
                    )
                    - base_p95_max_drawdown_usd,
                    "expected_capital_efficiency": _safe_float(
                        stress_monte_carlo.get("capital_efficiency"),
                        0.0,
                    ),
                    "capital_efficiency_impact": _safe_float(
                        stress_monte_carlo.get("capital_efficiency"),
                        0.0,
                    )
                    - base_capital_efficiency,
                    "expected_active_trade_load": _safe_float(
                        stress_monte_carlo.get("expected_active_trade_load"),
                        0.0,
                    ),
                    "active_trade_load_impact": _safe_float(
                        stress_monte_carlo.get("expected_active_trade_load"),
                        0.0,
                    )
                    - base_active_trade_load,
                    "expected_median_arr_pct": _safe_float(
                        stress_continuation.get("median_arr_pct"),
                        0.0,
                    ),
                    "expected_median_arr_pct_delta": _safe_float(
                        stress_continuation.get("median_arr_pct"),
                        0.0,
                    )
                    - base_median_arr_pct,
                    "expected_p05_arr_pct": _safe_float(
                        stress_continuation.get("p05_arr_pct"),
                        0.0,
                    ),
                    "expected_p05_arr_pct_delta": _safe_float(
                        stress_continuation.get("p05_arr_pct"),
                        0.0,
                    )
                    - base_p05_arr_pct,
                    "execution_drag_summary": _round_metrics(
                        {
                            "same_level_fill_ratio": _safe_float(
                                aggregate_sensitivity.get("expected_same_level_fill_ratio"),
                                0.0,
                            ),
                            "fill_probability": _safe_float(
                                aggregate_sensitivity.get("expected_fill_probability"),
                                0.0,
                            ),
                            "one_tick_worse_fill_ratio": _safe_float(
                                aggregate_sensitivity.get("expected_one_tick_worse_fill_ratio"),
                                0.0,
                            ),
                            "one_tick_fill_probability": _safe_float(
                                aggregate_sensitivity.get("expected_one_tick_fill_probability"),
                                0.0,
                            ),
                            "order_failed_probability": _safe_float(
                                aggregate_sensitivity.get("expected_order_failed_probability"),
                                0.0,
                            ),
                            "cancelled_unfilled_probability": _safe_float(
                                aggregate_sensitivity.get("expected_cancelled_unfilled_probability"),
                                0.0,
                            ),
                            "post_only_retry_failure_rate": _safe_float(
                                aggregate_sensitivity.get("expected_post_only_retry_failure_rate"),
                                0.0,
                            ),
                            "one_tick_cost_per_active_fill_usd": _safe_float(
                                aggregate_sensitivity.get("expected_one_tick_cost_per_active_fill_usd"),
                                0.0,
                            ),
                            "one_tick_cost_per_attempt_usd": _safe_float(
                                aggregate_sensitivity.get("expected_one_tick_cost_per_attempt_usd"),
                                0.0,
                            ),
                        }
                    ),
                    "regime_size_sensitivity": regime_sensitivity,
                    "session_size_sensitivity": session_sensitivity,
                    "session_tail_contribution": list(
                        stress_monte_carlo.get("session_tail_contribution") or []
                    ),
                }
            )
        )

    stage_sweeps: list[dict[str, Any]] = []
    current_base_sweep: dict[str, Any] | None = None
    shadow_sweeps: list[dict[str, Any]] = []
    sweeps_by_trade_size = {
        round(_safe_float(sweep.get("trade_size_usd"), 0.0), 4): sweep
        for sweep in sweeps
    }
    current_base_sweep = sweeps_by_trade_size.get(round(reference_trade_size_usd, 4))
    for capital_stage, trade_size_usd in CAPITAL_STAGE_TRADE_SIZES:
        sweep = sweeps_by_trade_size.get(round(trade_size_usd, 4))
        if sweep is None:
            continue
        stage_sweeps.append(
            {
                "capital_stage": int(capital_stage),
                "stage_label": f"stage_{capital_stage}",
                **sweep,
            }
        )
    for shadow_label, trade_size_usd in SHADOW_TRADE_SIZES:
        sweep = sweeps_by_trade_size.get(round(trade_size_usd, 4))
        if sweep is None:
            continue
        shadow_sweeps.append(
            {
                "shadow_label": shadow_label,
                **sweep,
            }
        )

    edge_tier_weighted_stage_sweeps: list[dict[str, Any]] = []
    for capital_stage, trade_size_usd in CAPITAL_STAGE_TRADE_SIZES:
        regime_sensitivity = _regime_size_sensitivity(
            rows=rows,
            profile=profile,
            target_trade_size_usd=trade_size_usd,
            reference_trade_size_usd=reference_trade_size_usd,
            edge_tier_weighted=True,
        )
        stress_entries = _stress_profile_entries(
            rows=rows,
            profile=profile,
            target_trade_size_usd=trade_size_usd,
            reference_trade_size_usd=reference_trade_size_usd,
            regime_sensitivity=regime_sensitivity,
        )
        stress_monte_carlo = _run_monte_carlo_from_entries(
            stress_entries,
            paths=paths,
            horizon_trades=horizon_trades,
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed_material=f"{seed}:{profile.name}:edge_weighted:{trade_size_usd:.2f}",
            sampling_dimensions=["session_name", "direction", "price_bucket", "delta_bucket"],
            loss_cluster_scenarios=loss_cluster_scenarios,
        )
        aggregate_sensitivity = _aggregate_regime_sensitivity(regime_sensitivity)
        edge_tier_weighted_stage_sweeps.append(
            _round_metrics(
                {
                    "capital_stage": int(capital_stage),
                    "stage_label": f"stage_{capital_stage}",
                    "sizing_track": "edge_tier_weighted",
                    "trade_size_usd": float(trade_size_usd),
                    "expected_trade_size_usd": _safe_float(
                        aggregate_sensitivity.get("expected_trade_size_usd"),
                        0.0,
                    ),
                    "edge_weight_multiplier": _safe_float(
                        aggregate_sensitivity.get("edge_weight_multiplier"),
                        0.0,
                    ),
                    "expected_fill_probability": _safe_float(
                        aggregate_sensitivity.get("expected_fill_probability"),
                        0.0,
                    ),
                    "expected_fill_retention_ratio": _safe_float(
                        aggregate_sensitivity.get("expected_fill_retention_ratio"),
                        0.0,
                    ),
                    "expected_non_positive_path_probability": _safe_float(
                        stress_monte_carlo.get("non_positive_probability"),
                        0.0,
                    ),
                    "expected_daily_loss_hit_probability": _safe_float(
                        stress_monte_carlo.get("daily_loss_hit_probability"),
                        0.0,
                    ),
                    "expected_p95_max_drawdown_usd": _safe_float(
                        stress_monte_carlo.get("p95_max_drawdown_usd"),
                        0.0,
                    ),
                    "expected_capital_efficiency": _safe_float(
                        stress_monte_carlo.get("capital_efficiency"),
                        0.0,
                    ),
                    "expected_active_trade_load": _safe_float(
                        stress_monte_carlo.get("expected_active_trade_load"),
                        0.0,
                    ),
                    "session_tail_contribution": list(
                        stress_monte_carlo.get("session_tail_contribution") or []
                    ),
                    "regime_size_sensitivity": regime_sensitivity,
                }
            )
        )

    return {
        "metric_name": "capacity_stress_summary",
        "profile_name": profile.name,
        "configured_current_trade_size_usd": round(configured_current_trade_size_usd, 4)
        if configured_current_trade_size_usd > 0.0
        else None,
        "observed_avg_trade_size_usd": round(observed_avg_trade_size_usd, 4),
        "reference_trade_size_usd": round(reference_trade_size_usd, 4),
        "reference_trade_size_source": reference_trade_size_source,
        "fill_retention_source_rows": len(matched_live_filled_rows),
        "baseline_execution_drag": baseline_execution_drag,
        "paths": int(paths),
        "horizon_trades": int(horizon_trades),
        "block_size": int(block_size),
        "loss_limit_usd": round(loss_limit_usd, 4),
        "loss_cluster_scenarios": loss_cluster_scenarios,
        "trade_sizes_usd": [float(item["trade_size_usd"]) for item in sweeps],
        "current_base_trade_size_usd": round(reference_trade_size_usd, 4),
        "stage_trade_sizes_usd": {
            f"stage_{capital_stage}": trade_size_usd
            for capital_stage, trade_size_usd in CAPITAL_STAGE_TRADE_SIZES
        },
        "shadow_trade_sizes_usd": {
            label: trade_size_usd
            for label, trade_size_usd in SHADOW_TRADE_SIZES
        },
        "current_base_sweep": current_base_sweep,
        "stage_sweeps": stage_sweeps,
        "shadow_sweeps": shadow_sweeps,
        "edge_tier_weighted_stage_sweeps": edge_tier_weighted_stage_sweeps,
        "size_sweeps": sweeps,
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    current_arr_pct = 0.0
    for candidate in summary["candidates"]:
        if candidate["profile"]["name"] == summary["current_live_profile"]["name"]:
            current_arr_pct = _safe_float(candidate["continuation"].get("median_arr_pct"), 0.0)
            break
    lines = [
        "# BTC5 Monte Carlo Report",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Primary DB: `{summary['db_path']}`",
        f"- Observed decision rows: `{summary['input']['observed_window_rows']}`",
        f"- Observed live-filled rows: `{summary['input']['live_filled_rows']}`",
        f"- Observed realized PnL: `{summary['input']['observed_pnl_usd']:.4f}` USD",
        f"- Monte Carlo paths: `{summary['simulation']['paths']}`",
        f"- Horizon trades per path: `{summary['simulation']['horizon_trades']}`",
        f"- Bootstrap block size: `{summary['simulation']['block_size']}`",
        "",
        "## Baseline",
        "",
        f"- Deduped rows by source: `{summary['baseline']['rows_by_source']}`",
        f"- Window range: `{summary['baseline']['first_window_start_ts']}` to `{summary['baseline']['last_window_start_ts']}`",
        "",
        "## Candidate Ranking",
        "",
        "| Rank | Profile | Hist ARR | MC Median ARR | ARR Delta vs Current | Profit Prob | P95 Drawdown | Loss-Limit Hit |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for index, candidate in enumerate(summary["candidates"], start=1):
        continuation = candidate["continuation"]
        monte_carlo = candidate["monte_carlo"]
        arr_delta_pct = _safe_float(continuation.get("median_arr_pct"), 0.0) - current_arr_pct
        lines.append(
            "| "
            + f"{index} | {candidate['profile']['name']} | "
            + f"{continuation['historical_arr_pct']:.2f}% | "
            + f"{continuation['median_arr_pct']:.2f}% | "
            + f"{arr_delta_pct:.2f}pp | "
            + f"{monte_carlo['profit_probability']:.2%} | "
            + f"{monte_carlo['p95_max_drawdown_usd']:.4f} | "
            + f"{monte_carlo['loss_limit_hit_probability']:.2%} |"
        )

    best = summary["best_candidate"]
    comparison = summary.get("best_vs_current") or {}
    capacity_stress = summary.get("capacity_stress_summary") or {}
    lines.extend(
        [
            "",
            "## Best Candidate",
            "",
            f"- Name: `{best['profile']['name']}`",
            f"- Max abs delta: `{best['profile']['max_abs_delta']}`",
            f"- UP max buy price: `{best['profile']['up_max_buy_price']}`",
            f"- DOWN max buy price: `{best['profile']['down_max_buy_price']}`",
            f"- Historical continuation ARR: `{best['continuation']['historical_arr_pct']:.2f}%`",
            f"- Monte Carlo median continuation ARR: `{best['continuation']['median_arr_pct']:.2f}%`",
            f"- Monte Carlo P05 continuation ARR: `{best['continuation']['p05_arr_pct']:.2f}%`",
            f"- Replay PnL: `{best['historical']['replay_live_filled_pnl_usd']:.4f}` USD on `{best['historical']['replay_live_filled_rows']}` fills",
            f"- Monte Carlo median PnL: `{best['monte_carlo']['median_total_pnl_usd']:.4f}` USD",
            f"- Monte Carlo profit probability: `{best['monte_carlo']['profit_probability']:.2%}`",
            f"- Monte Carlo P95 drawdown: `{best['monte_carlo']['p95_max_drawdown_usd']:.4f}` USD",
            "",
            "## Best vs Current Live",
            "",
            f"- Best candidate: `{comparison.get('best_candidate_name')}`",
            f"- Current live candidate: `{comparison.get('current_candidate_name')}`",
            f"- Historical continuation ARR delta vs current: `{comparison.get('historical_arr_pct_delta', 0.0):.2f}` percentage points",
            f"- Monte Carlo median continuation ARR delta vs current: `{comparison.get('median_arr_pct_delta', 0.0):.2f}` percentage points",
            f"- Monte Carlo P05 continuation ARR delta vs current: `{comparison.get('p05_arr_pct_delta', 0.0):.2f}` percentage points",
            f"- Replay PnL delta vs current: `{comparison.get('replay_pnl_delta_usd', 0.0):.4f}` USD",
            f"- Monte Carlo median PnL delta vs current: `{comparison.get('median_pnl_delta_usd', 0.0):.4f}` USD",
            f"- Profit-probability delta vs current: `{comparison.get('profit_probability_delta', 0.0):.2%}`",
            f"- P95 drawdown delta vs current: `{comparison.get('p95_drawdown_delta_usd', 0.0):.4f}` USD",
            "",
            "## Caveat",
            "",
            "This engine is empirical and bootstrap-based. It ranks guardrail profiles from the live BTC5 fill tape; it does not invent extra alpha beyond the observed distribution.",
        ]
    )
    if isinstance(capacity_stress, dict) and capacity_stress.get("profiles"):
        lines.extend(
            [
                "",
                "## Capacity Stress",
                "",
                f"- Recommended reference profile: `{capacity_stress.get('recommended_reference')}`",
            ]
        )
        for label, payload in (capacity_stress.get("profiles") or {}).items():
            if not isinstance(payload, dict):
                continue
            lines.extend(
                [
                    "",
                    f"### {label}",
                    "",
                    f"- Profile name: `{payload.get('profile_name', 'unknown')}`",
                    f"- Reference trade size: `{_safe_float(payload.get('reference_trade_size_usd'), 0.0):.2f}` USD",
                    "",
                    "| Ticket | Track | Fill Retention | 1-Tick Worse | Retry Fail | Median ARR Delta | P95 Drawdown Impact |",
                    "|---|---|---:|---:|---:|---:|---:|",
                ]
            )
            for sweep in payload.get("size_sweeps") or []:
                lines.append(
                    "| "
                    + f"{_safe_float(sweep.get('trade_size_usd'), 0.0):.2f} | "
                    + f"{str(sweep.get('sizing_track') or 'unknown')} | "
                    + f"{_safe_float(sweep.get('expected_fill_retention_ratio'), 0.0):.2%} | "
                    + f"{_safe_float(sweep.get('expected_one_tick_worse_fill_ratio'), 0.0):.2%} | "
                    + f"{_safe_float(sweep.get('expected_post_only_retry_failure_rate'), 0.0):.2%} | "
                    + f"{_safe_float(sweep.get('expected_median_arr_pct_delta'), 0.0):.2f}pp | "
                    + f"{_safe_float(sweep.get('p95_drawdown_impact_usd'), 0.0):.4f} |"
                )
    return "\n".join(lines) + "\n"


def _write_outputs(
    output_dir: Path,
    *,
    summary: dict[str, Any],
    write_latest: bool,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    md_path.write_text(_render_markdown(summary))

    if write_latest:
        shutil.copy2(json_path, REPORTS_DIR / "btc5_monte_carlo_latest.json")
        shutil.copy2(md_path, REPORTS_DIR / "btc5_monte_carlo_latest.md")
    return json_path, md_path


def build_summary(
    *,
    rows: list[dict[str, Any]],
    db_path: Path,
    current_live_profile: GuardrailProfile,
    runtime_recommended_profile: GuardrailProfile,
    current_trade_size_usd: float = DEFAULT_CURRENT_TRADE_SIZE_USD,
    paths: int,
    horizon_trades: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
    top_grid_candidates: int,
    min_replay_fills: int,
) -> dict[str, Any]:
    candidates = build_candidate_profiles(
        rows,
        current_live_profile=current_live_profile,
        runtime_recommended_profile=runtime_recommended_profile,
        top_grid_candidates=top_grid_candidates,
        min_replay_fills=min_replay_fills,
    )

    evaluated: list[dict[str, Any]] = []
    for profile in candidates:
        historical = summarize_profile_history(rows, profile)
        monte_carlo = run_monte_carlo(
            rows,
            profile,
            paths=paths,
            horizon_trades=horizon_trades,
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed=seed,
        )
        continuation = summarize_continuation_arr(historical=historical, monte_carlo=monte_carlo)
        evaluated.append(
            {
                "profile": asdict(profile),
                "historical": historical,
                "monte_carlo": monte_carlo,
                "continuation": continuation,
            }
        )

    evaluated.sort(
        key=lambda candidate: (
            _safe_float(candidate["continuation"].get("median_arr_pct"), 0.0),
            _safe_float(candidate["monte_carlo"].get("profit_probability"), 0.0),
            -_safe_float(candidate["monte_carlo"].get("p95_max_drawdown_usd"), 0.0),
            _safe_float(candidate["historical"].get("replay_live_filled_rows"), 0.0),
        ),
        reverse=True,
    )

    current_candidate = next(
        (candidate for candidate in evaluated if candidate["profile"]["name"] == current_live_profile.name),
        None,
    )
    best_candidate = evaluated[0] if evaluated else None
    best_vs_current = None
    if best_candidate is not None and current_candidate is not None:
        best_vs_current = _round_metrics(
            {
                "best_candidate_name": best_candidate["profile"]["name"],
                "current_candidate_name": current_candidate["profile"]["name"],
                "historical_arr_pct_delta": _safe_float(
                    best_candidate["continuation"].get("historical_arr_pct"), 0.0
                )
                - _safe_float(current_candidate["continuation"].get("historical_arr_pct"), 0.0),
                "median_arr_pct_delta": _safe_float(
                    best_candidate["continuation"].get("median_arr_pct"), 0.0
                )
                - _safe_float(current_candidate["continuation"].get("median_arr_pct"), 0.0),
                "p05_arr_pct_delta": _safe_float(
                    best_candidate["continuation"].get("p05_arr_pct"), 0.0
                )
                - _safe_float(current_candidate["continuation"].get("p05_arr_pct"), 0.0),
                "replay_pnl_delta_usd": _safe_float(
                    best_candidate["historical"].get("replay_live_filled_pnl_usd"), 0.0
                )
                - _safe_float(current_candidate["historical"].get("replay_live_filled_pnl_usd"), 0.0),
                "median_pnl_delta_usd": _safe_float(
                    best_candidate["monte_carlo"].get("median_total_pnl_usd"), 0.0
                )
                - _safe_float(current_candidate["monte_carlo"].get("median_total_pnl_usd"), 0.0),
                "profit_probability_delta": _safe_float(
                    best_candidate["monte_carlo"].get("profit_probability"), 0.0
                )
                - _safe_float(current_candidate["monte_carlo"].get("profit_probability"), 0.0),
                "p95_drawdown_delta_usd": _safe_float(
                    best_candidate["monte_carlo"].get("p95_max_drawdown_usd"), 0.0
                )
                - _safe_float(current_candidate["monte_carlo"].get("p95_max_drawdown_usd"), 0.0),
            }
        )

    capacity_stress_profiles: dict[str, Any] = {}
    if current_candidate is not None:
        current_profile = GuardrailProfile(**current_candidate["profile"])
        capacity_stress_profiles["current_live_profile"] = build_capacity_stress_summary(
            rows=rows,
            profile=current_profile,
            historical=current_candidate["historical"],
            monte_carlo=current_candidate["monte_carlo"],
            continuation=current_candidate["continuation"],
            current_trade_size_usd=current_trade_size_usd,
            paths=paths,
            horizon_trades=horizon_trades,
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed=seed,
        )
    if best_candidate is not None:
        best_profile = GuardrailProfile(**best_candidate["profile"])
        capacity_stress_profiles["best_candidate"] = build_capacity_stress_summary(
            rows=rows,
            profile=best_profile,
            historical=best_candidate["historical"],
            monte_carlo=best_candidate["monte_carlo"],
            continuation=best_candidate["continuation"],
            current_trade_size_usd=current_trade_size_usd,
            paths=paths,
            horizon_trades=horizon_trades,
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed=seed,
        )

    return {
        "generated_at": _now_utc().isoformat(),
        "db_path": str(db_path),
        "input": {
            "observed_window_rows": len(rows),
            "live_filled_rows": sum(1 for row in rows if _is_live_filled_row(row)),
            "observed_pnl_usd": round(sum(_safe_float(row.get("realized_pnl_usd"), 0.0) for row in rows), 4),
        },
        "simulation": {
            "paths": int(paths),
            "horizon_trades": int(horizon_trades),
            "block_size": int(block_size),
            "loss_limit_usd": round(loss_limit_usd, 4),
            "seed": int(seed),
        },
        "baseline": {},
        "current_live_profile": asdict(current_live_profile),
        "runtime_recommended_profile": asdict(runtime_recommended_profile),
        "candidates": evaluated,
        "best_candidate": best_candidate,
        "best_vs_current": best_vs_current,
        "capacity_stress_summary": {
            "metric_name": "capacity_stress_summary",
            "recommended_reference": "best_candidate" if best_candidate is not None else "current_live_profile",
            "profiles": capacity_stress_profiles,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=None, help="Path to BTC5 SQLite DB.")
    parser.add_argument(
        "--refresh-remote",
        action="store_true",
        help="Pull the latest BTC5 decision rows from the VPS over SSH before simulation.",
    )
    parser.add_argument(
        "--include-archive-csvs",
        action="store_true",
        help="Merge archived BTC5 CSV exports into the baseline before deduping.",
    )
    parser.add_argument(
        "--archive-glob",
        default=DEFAULT_ARCHIVE_GLOB,
        help="Repo-root glob for archived BTC5 CSV exports.",
    )
    parser.add_argument(
        "--remote-cache-json",
        type=Path,
        default=DEFAULT_REMOTE_ROWS_JSON,
        help="Where to cache freshly pulled remote BTC5 rows.",
    )
    parser.add_argument(
        "--runtime-truth",
        type=Path,
        default=DEFAULT_RUNTIME_TRUTH,
        help="Path to runtime truth snapshot for the latest recommended profile.",
    )
    parser.add_argument("--paths", type=int, default=5000, help="Monte Carlo path count.")
    parser.add_argument(
        "--horizon-trades",
        type=int,
        default=0,
        help="Trades per Monte Carlo path. Defaults to max(observed live fills, 40).",
    )
    parser.add_argument("--block-size", type=int, default=4, help="Block bootstrap size.")
    parser.add_argument(
        "--loss-limit-usd",
        type=float,
        default=DEFAULT_LOSS_LIMIT_USD,
        help="Path-level rollback trigger threshold for loss-hit probability.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--top-grid-candidates",
        type=int,
        default=6,
        help="Number of grid-swept guardrail candidates to keep beyond baseline/current/runtime.",
    )
    parser.add_argument(
        "--min-replay-fills",
        type=int,
        default=8,
        help="Minimum historical fills required for a grid candidate to be simulated.",
    )
    parser.add_argument(
        "--current-max-abs-delta",
        type=float,
        default=DEFAULT_MAX_ABS_DELTA,
        help="Current live max abs delta cap.",
    )
    parser.add_argument(
        "--current-up-max-buy-price",
        type=float,
        default=DEFAULT_UP_MAX,
        help="Current live UP max buy price.",
    )
    parser.add_argument(
        "--current-down-max-buy-price",
        type=float,
        default=DEFAULT_DOWN_MAX,
        help="Current live DOWN max buy price.",
    )
    parser.add_argument(
        "--current-max-position-usd",
        type=float,
        default=DEFAULT_CURRENT_TRADE_SIZE_USD,
        help="Current live BTC5 position-size cap used as the base capacity stress ticket.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for summary.json and report.md. Defaults to reports/btc5_monte_carlo_<stamp>.",
    )
    parser.add_argument(
        "--write-latest",
        action="store_true",
        help="Also copy outputs to reports/btc5_monte_carlo_latest.{json,md}.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = args.db_path or _default_db_path()
    runtime_truth = _load_runtime_truth(args.runtime_truth)
    rows, baseline_summary = assemble_observed_rows(
        db_path=db_path,
        include_archive_csvs=bool(args.include_archive_csvs),
        archive_glob=str(args.archive_glob),
        refresh_remote=bool(args.refresh_remote),
        remote_cache_json=args.remote_cache_json,
    )
    if not rows:
        raise SystemExit(f"No BTC5 observed rows found from {db_path}")

    current_live_profile = GuardrailProfile(
        name="current_live_profile",
        max_abs_delta=float(args.current_max_abs_delta),
        up_max_buy_price=float(args.current_up_max_buy_price),
        down_max_buy_price=float(args.current_down_max_buy_price),
        note="current deployed BTC5 guardrails",
    )
    runtime_recommended_profile = _live_profile_from_runtime_truth(runtime_truth)
    horizon_trades = int(args.horizon_trades) if int(args.horizon_trades) > 0 else max(len(rows), 40)
    output_dir = args.output_dir or (REPORTS_DIR / f"btc5_monte_carlo_{_stamp()}")

    summary = build_summary(
        rows=rows,
        db_path=db_path,
        current_live_profile=current_live_profile,
        runtime_recommended_profile=runtime_recommended_profile,
        current_trade_size_usd=float(args.current_max_position_usd),
        paths=max(1, int(args.paths)),
        horizon_trades=horizon_trades,
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        top_grid_candidates=max(1, int(args.top_grid_candidates)),
        min_replay_fills=max(1, int(args.min_replay_fills)),
    )
    summary["baseline"] = baseline_summary
    json_path, md_path = _write_outputs(output_dir, summary=summary, write_latest=bool(args.write_latest))
    print(json.dumps({"summary_json": str(json_path), "report_md": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
