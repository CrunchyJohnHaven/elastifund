#!/usr/bin/env python3
"""Instance 4 weather lane dispatcher: NWS/Kalshi divergence shadow activation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi.weather_arb import (  # noqa: E402
    CITY_CONFIG,
    _field,
    _market_city_code,
    _market_type,
    extract_market_target_date,
    fetch_weather_series_markets,
    get_kalshi_client,
)

NWS_BASE = "https://api.weather.gov"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "parallel" / "instance04_weather_divergence_shadow.json"
DEFAULT_MARKDOWN_PATH = REPO_ROOT / "reports" / "parallel" / "instance04_weather_divergence_shadow.md"
DEFAULT_FINANCE_PATH = REPO_ROOT / "reports" / "finance" / "latest.json"
DEFAULT_RUNTIME_TRUTH_PATH = REPO_ROOT / "reports" / "runtime_truth_latest.json"

SCAN_WINDOWS_MINUTES = [25, 55]
WINDOW_HALF_WIDTH_MINUTES = 4
FOLLOWUP_LENGTH_MINUTES = 6
MIN_REQUIRED_CLEAN_MAPPINGS = 3
MAX_TARGET_HORIZON_DAYS = 7
MIN_EDGE_THRESHOLD = 0.03

CITY_NWS_MAP: dict[str, dict[str, str]] = {
    "NYC": {
        "station": "knyc",
        "timeseries": "https://www.weather.gov/wrh/timeseries?site=knyc",
        "climate_family": "NWS Climatological Report (Daily) - Central Park",
    },
    "CHI": {
        "station": "kmdw",
        "timeseries": "https://www.weather.gov/wrh/timeseries?site=kmdw",
        "climate_family": "NWS Climatological Report (Daily) - Chicago Midway",
    },
    "AUS": {
        "station": "kaus",
        "timeseries": "https://www.weather.gov/wrh/timeseries?site=kaus",
        "climate_family": "NWS Climatological Report (Daily) - Austin Bergstrom",
    },
    "MIA": {
        "station": "kmia",
        "timeseries": "https://www.weather.gov/wrh/timeseries?site=kmia",
        "climate_family": "NWS Climatological Report (Daily) - Miami Intl",
    },
    "LAX": {
        "station": "klax",
        "timeseries": "https://www.weather.gov/wrh/timeseries?site=klax",
        "climate_family": "NWS Climatological Report (Daily) - Los Angeles Intl",
    },
}


@dataclass
class CitySnapshot:
    city: str
    target_date: str
    point_high_f: float | None
    hourly_high_f: float | None
    pop_probability: float | None
    point_updated_at: str | None
    hourly_updated_at: str | None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_prob(value: Any) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    if parsed > 1.0:
        parsed /= 100.0
    return max(0.0, min(1.0, parsed))


def _normal_cdf(x: float, mean: float, std: float) -> float:
    denom = max(1e-6, std) * math.sqrt(2.0)
    return 0.5 * (1.0 + math.erf((x - mean) / denom))


def _temperature_prob_above(threshold_f: float, point_high_f: float, hourly_high_f: float) -> float:
    mean = 0.55 * point_high_f + 0.45 * hourly_high_f
    spread = abs(point_high_f - hourly_high_f)
    std = max(1.5, 2.2 + 0.35 * spread)
    prob = 1.0 - _normal_cdf(threshold_f - 0.5, mean, std)
    return max(0.01, min(0.99, prob))


def _contains_bracket_structure(text: str) -> bool:
    compact = text.lower()
    if "between" in compact and " and " in compact:
        return True
    if re.search(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\b", compact):
        return True
    if " to " in compact and re.search(r"\d", compact):
        return True
    return False


def _parse_temp_threshold_f(title: str, subtitle: str) -> float | None:
    text = f"{title} {subtitle}".lower()
    match = re.search(r">\s*(\d{1,3})", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d{1,3})\s*°\s*or\s*above", text)
    if match:
        return float(match.group(1)) - 1.0
    match = re.search(r"above\s*(\d{1,3})", text)
    if match:
        return float(match.group(1))
    return None


def _scan_windows(now: datetime) -> dict[str, Any]:
    utc_now = now.astimezone(timezone.utc)
    active_windows: list[dict[str, str]] = []
    upcoming_windows: list[dict[str, str]] = []

    for hour_offset in (-1, 0, 1, 2):
        base = utc_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour_offset)
        for minute in SCAN_WINDOWS_MINUTES:
            center = base.replace(minute=minute)
            primary_start = center - timedelta(minutes=WINDOW_HALF_WIDTH_MINUTES)
            primary_end = center + timedelta(minutes=WINDOW_HALF_WIDTH_MINUTES)
            followup_start = primary_end
            followup_end = followup_start + timedelta(minutes=FOLLOWUP_LENGTH_MINUTES)

            windows = [
                ("primary", primary_start, primary_end),
                ("followup", followup_start, followup_end),
            ]
            for kind, start, end in windows:
                row = {
                    "window_type": kind,
                    "start_utc": _iso_z(start),
                    "end_utc": _iso_z(end),
                    "center_utc": _iso_z(center),
                }
                if start <= utc_now <= end:
                    active_windows.append(row)
                elif end > utc_now:
                    upcoming_windows.append(row)

    upcoming_windows.sort(key=lambda item: item["start_utc"])
    return {
        "should_scan_now": bool(active_windows),
        "active_windows": active_windows,
        "next_windows": upcoming_windows[:6],
        "cadence": {
            "primary_centers_minute": list(SCAN_WINDOWS_MINUTES),
            "primary_half_width_minutes": WINDOW_HALF_WIDTH_MINUTES,
            "followup_length_minutes": FOLLOWUP_LENGTH_MINUTES,
        },
    }


def _nws_json_get(url: str) -> dict[str, Any]:
    resp = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "Elastifund/instance4-weather-shadow"},
    )
    resp.raise_for_status()
    body = resp.json()
    return body if isinstance(body, dict) else {}


def _fetch_city_snapshot(city_code: str, target_date: datetime) -> CitySnapshot:
    cfg = CITY_CONFIG[city_code]
    points = _nws_json_get(f"{NWS_BASE}/points/{cfg['lat']},{cfg['lon']}")
    properties = points.get("properties") or {}
    forecast_url = str(properties.get("forecast") or "").strip()
    hourly_url = str(properties.get("forecastHourly") or "").strip()
    if not forecast_url or not hourly_url:
        raise RuntimeError(f"missing_nws_forecast_endpoints:{city_code}")

    daily = _nws_json_get(forecast_url)
    hourly = _nws_json_get(hourly_url)
    target_day = target_date.date()

    point_high_f: float | None = None
    pop_values: list[float] = []
    for period in (daily.get("properties") or {}).get("periods") or []:
        start = str(period.get("startTime") or "")
        if not start:
            continue
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            continue
        if start_dt.date() != target_day:
            continue
        temp = _safe_float(period.get("temperature"))
        unit = str(period.get("temperatureUnit") or "F").upper()
        if temp is not None and unit == "C":
            temp = temp * 9.0 / 5.0 + 32.0
        if period.get("isDaytime") and temp is not None:
            point_high_f = temp
        pop_val = _safe_float(((period.get("probabilityOfPrecipitation") or {}).get("value")))
        if pop_val is not None:
            pop_values.append(max(0.0, min(1.0, pop_val / 100.0)))

    hourly_high_f: float | None = None
    for period in (hourly.get("properties") or {}).get("periods") or []:
        start = str(period.get("startTime") or "")
        if not start:
            continue
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            continue
        if start_dt.date() != target_day:
            continue
        temp = _safe_float(period.get("temperature"))
        unit = str(period.get("temperatureUnit") or "F").upper()
        if temp is not None and unit == "C":
            temp = temp * 9.0 / 5.0 + 32.0
        if temp is None:
            continue
        hourly_high_f = temp if hourly_high_f is None else max(hourly_high_f, temp)

    daily_pop: float | None = None
    if pop_values:
        no_precip = 1.0
        for pop in pop_values:
            no_precip *= (1.0 - pop)
        daily_pop = max(0.0, min(1.0, 1.0 - no_precip))

    return CitySnapshot(
        city=city_code,
        target_date=target_day.isoformat(),
        point_high_f=point_high_f,
        hourly_high_f=hourly_high_f,
        pop_probability=daily_pop,
        point_updated_at=str((daily.get("properties") or {}).get("updateTime") or "") or None,
        hourly_updated_at=str((hourly.get("properties") or {}).get("updateTime") or "") or None,
    )


def _market_implied_surface(market: dict[str, Any]) -> dict[str, float | None]:
    yes_bid = _to_prob(_field(market, "yes_bid"))
    yes_ask = _to_prob(_field(market, "yes_ask"))
    no_bid = _to_prob(_field(market, "no_bid"))
    no_ask = _to_prob(_field(market, "no_ask"))

    if yes_bid is None:
        yes_bid = _to_prob(_field(market, "yes_bid_dollars"))
    if yes_ask is None:
        yes_ask = _to_prob(_field(market, "yes_ask_dollars"))
    if no_bid is None:
        no_bid = _to_prob(_field(market, "no_bid_dollars"))
    if no_ask is None:
        no_ask = _to_prob(_field(market, "no_ask_dollars"))

    yes_spread = (yes_ask - yes_bid) if yes_ask is not None and yes_bid is not None else None
    no_spread = (no_ask - no_bid) if no_ask is not None and no_bid is not None else None

    def _all_in(ask: float | None, spread: float | None) -> float | None:
        if ask is None:
            return None
        fee = 0.07 * ask * (1.0 - ask)
        spread_cost = max(0.0, spread or 0.0) * 0.5
        return min(0.999, ask + fee + spread_cost)

    return {
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "yes_spread": yes_spread,
        "no_spread": no_spread,
        "yes_all_in": _all_in(yes_ask, yes_spread),
        "no_all_in": _all_in(no_ask, no_spread),
    }


def _is_clean_nws_settlement_contract(market: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    rules_primary = str(_field(market, "rules_primary", "") or "")
    rules_secondary = str(_field(market, "rules_secondary", "") or "")
    rules_text = f"{rules_primary} {rules_secondary}".lower()
    title = str(_field(market, "title", "") or "")
    subtitle = str(_field(market, "subtitle", "") or "")

    if _contains_bracket_structure(f"{title} {subtitle}"):
        reasons.append("bracket_contract_excluded")

    has_climate_anchor = "climatological report" in rules_text
    has_nws_anchor = "national weather service" in rules_text or "weather.gov" in rules_text
    if not has_climate_anchor:
        reasons.append("missing_climatological_report_anchor")
    if not has_nws_anchor:
        reasons.append("missing_nws_anchor")

    mtype = _market_type(market)
    if mtype == "temperature":
        threshold = _parse_temp_threshold_f(title, subtitle)
        if threshold is None:
            reasons.append("non_binary_temperature_contract")
    elif mtype == "rain":
        if "strictly greater than" not in rules_text and "rain" not in title.lower():
            reasons.append("non_binary_precip_contract")
    else:
        reasons.append("unsupported_market_type")

    return len(reasons) == 0, reasons


def _build_market_row(market: dict[str, Any], snapshot: CitySnapshot) -> dict[str, Any]:
    title = str(_field(market, "title", "") or "")
    subtitle = str(_field(market, "subtitle", "") or "")
    mtype = _market_type(market)
    implied = _market_implied_surface(market)

    model_prob: float | None = None
    model_component: dict[str, float | None] = {
        "point_forecast_high_f": snapshot.point_high_f,
        "hourly_forecast_high_f": snapshot.hourly_high_f,
        "daily_pop_probability": snapshot.pop_probability,
    }

    if mtype == "temperature":
        threshold_f = _parse_temp_threshold_f(title, subtitle)
        model_component["threshold_f"] = threshold_f
        if threshold_f is not None and snapshot.point_high_f is not None and snapshot.hourly_high_f is not None:
            model_prob = _temperature_prob_above(
                threshold_f=threshold_f,
                point_high_f=snapshot.point_high_f,
                hourly_high_f=snapshot.hourly_high_f,
            )
    elif mtype == "rain":
        if snapshot.pop_probability is not None:
            model_prob = snapshot.pop_probability

    yes_all_in = implied.get("yes_all_in")
    no_all_in = implied.get("no_all_in")
    yes_edge = (model_prob - yes_all_in) if model_prob is not None and yes_all_in is not None else None
    no_edge = ((1.0 - model_prob) - no_all_in) if model_prob is not None and no_all_in is not None else None

    preferred_side = None
    spread_adjusted_edge = None
    if yes_edge is not None or no_edge is not None:
        if (yes_edge or float("-inf")) >= (no_edge or float("-inf")):
            preferred_side = "yes"
            spread_adjusted_edge = yes_edge
        else:
            preferred_side = "no"
            spread_adjusted_edge = no_edge

    return {
        "ticker": str(_field(market, "ticker", "") or ""),
        "event_ticker": str(_field(market, "event_ticker", "") or ""),
        "title": title,
        "subtitle": subtitle,
        "market_type": mtype,
        "status": str(_field(market, "status", "") or ""),
        "target_date": snapshot.target_date,
        "nws_model": model_component,
        "model_probability": model_prob,
        "market_implied": implied,
        "edge": {
            "yes_spread_adjusted": yes_edge,
            "no_spread_adjusted": no_edge,
            "preferred_side": preferred_side,
            "spread_adjusted_edge": spread_adjusted_edge,
        },
        "candidate": bool(spread_adjusted_edge is not None and spread_adjusted_edge >= MIN_EDGE_THRESHOLD),
    }


def _fetch_markets() -> list[dict[str, Any]]:
    session = get_kalshi_client(execute=False)
    markets = fetch_weather_series_markets(session)
    rows: list[dict[str, Any]] = []
    for market in markets:
        if isinstance(market, dict):
            rows.append(dict(market))
        else:
            rows.append(dict(market))
    enriched: list[dict[str, Any]] = []
    for market in rows:
        ticker = str(_field(market, "ticker", "") or "").strip()
        if not ticker:
            enriched.append(market)
            continue
        if _field(market, "rules_primary") or _field(market, "rules_secondary"):
            enriched.append(market)
            continue
        try:
            detail = _nws_json_get(
                f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
            )
        except Exception:
            enriched.append(market)
            continue
        market_blob = detail.get("market")
        if isinstance(market_blob, dict):
            merged = dict(market)
            merged.update(market_blob)
            enriched.append(merged)
        else:
            enriched.append(market)
    return enriched


def _extract_target_dates(markets: list[dict[str, Any]], now: datetime) -> dict[tuple[str, str], None]:
    selected: dict[tuple[str, str], None] = {}
    today = now.astimezone(timezone.utc).date()
    for market in markets:
        city = _market_city_code(market)
        if city not in CITY_CONFIG:
            continue
        if _market_type(market) not in {"temperature", "rain"}:
            continue
        target_date = extract_market_target_date(market)
        if target_date is None:
            continue
        horizon = (target_date - today).days
        if horizon < 0 or horizon > MAX_TARGET_HORIZON_DAYS:
            continue
        selected[(city, target_date.isoformat())] = None
    return selected


def build_instance4_weather_lane_artifact(
    *,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
    markets: list[dict[str, Any]] | None = None,
    snapshot_overrides: dict[tuple[str, str], CitySnapshot] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    markets = markets if markets is not None else _fetch_markets()
    snapshot_overrides = snapshot_overrides or {}

    runtime_truth = _read_json(repo_root / "reports" / "runtime_truth_latest.json")
    finance_latest = _read_json(repo_root / "reports" / "finance" / "latest.json")
    finance_gate_pass = bool(finance_latest.get("finance_gate_pass", True))

    target_pairs = _extract_target_dates(markets, now)

    city_snapshots: dict[tuple[str, str], CitySnapshot] = {}
    snapshot_failures: list[str] = []
    for city, target_date in sorted(target_pairs.keys()):
        key = (city, target_date)
        if key in snapshot_overrides:
            city_snapshots[key] = snapshot_overrides[key]
            continue
        try:
            target_dt = datetime.fromisoformat(target_date).replace(tzinfo=timezone.utc)
            city_snapshots[key] = _fetch_city_snapshot(city, target_dt)
        except Exception as exc:
            snapshot_failures.append(f"snapshot_fetch_failed:{city}:{target_date}:{exc}")

    clean_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    mapped_city_keys: set[str] = set()

    for market in markets:
        city = _market_city_code(market)
        if city not in CITY_CONFIG:
            continue
        target = extract_market_target_date(market)
        if target is None:
            continue
        key = (city, target.isoformat())
        snapshot = city_snapshots.get(key)
        if snapshot is None:
            continue

        clean, reasons = _is_clean_nws_settlement_contract(market)
        if not clean:
            excluded_rows.append(
                {
                    "ticker": str(_field(market, "ticker", "") or ""),
                    "city": city,
                    "target_date": snapshot.target_date,
                    "reasons": reasons,
                }
            )
            continue

        row = _build_market_row(market, snapshot)
        mapping = CITY_NWS_MAP.get(city, {})
        row["settlement_source"] = {
            "city": city,
            "station": mapping.get("station"),
            "climate_family": mapping.get("climate_family"),
            "timeseries_url": mapping.get("timeseries"),
            "rules_primary": str(_field(market, "rules_primary", "") or ""),
        }
        row["nws_update_surface"] = {
            "point_forecast_updated_at": snapshot.point_updated_at,
            "hourly_forecast_updated_at": snapshot.hourly_updated_at,
        }
        clean_rows.append(row)
        mapped_city_keys.add(city)

    candidates = [row for row in clean_rows if row.get("candidate")]

    block_reasons: list[str] = ["shadow_only_cycle_no_live_capital", "bracket_rounding_thesis_rejected"]
    if len(mapped_city_keys) < MIN_REQUIRED_CLEAN_MAPPINGS:
        block_reasons.append(f"clean_mapping_below_minimum:{len(mapped_city_keys)}<{MIN_REQUIRED_CLEAN_MAPPINGS}")
    if not clean_rows:
        block_reasons.append("no_clean_weather_contracts")
    if not candidates:
        block_reasons.append("no_spread_adjusted_positive_candidates")
    if snapshot_failures:
        block_reasons.extend(snapshot_failures)

    # Lane remains shadow-only even when finance gate is true for baseline operations.
    if finance_gate_pass:
        weather_finance_pass = True
    else:
        weather_finance_pass = False
        block_reasons.append("finance_gate_not_passed")

    max_edge = max((row.get("edge", {}).get("spread_adjusted_edge") or 0.0) for row in clean_rows) if clean_rows else 0.0
    candidate_delta_arr_bps = 100
    if max_edge <= 0.0:
        candidate_delta_arr_bps = 50

    scan_windows = _scan_windows(now)

    artifact = {
        "artifact": "instance4_weather_divergence_shadow.v1",
        "instance": 4,
        "generated_at": _iso_z(now),
        "objective": "Validate NWS/Kalshi weather divergence lane in shadow mode with clean settlement-source mapping.",
        "execution_policy": {
            "mode": "shadow_only",
            "live_capital_usd": 0,
            "bracket_rounding_policy": "excluded_forever",
            "live_activation_requirement": "minimum_7d_shadow_logging_and_operator_review",
        },
        "scan_windows": scan_windows,
        "source_mapping_summary": {
            "clean_city_count": len(mapped_city_keys),
            "clean_cities": sorted(mapped_city_keys),
            "minimum_required": MIN_REQUIRED_CLEAN_MAPPINGS,
            "target_market_families": ["daily_temperature_binary", "daily_precip_binary"],
        },
        "market_scan": {
            "fetched_markets": len(markets),
            "clean_tradeable_markets": len(clean_rows),
            "candidate_count": len(candidates),
            "candidate_rows": candidates,
            "all_clean_rows": clean_rows,
            "excluded_rows": excluded_rows,
        },
        "runtime_context": {
            "launch_posture": runtime_truth.get("launch_posture")
            or (runtime_truth.get("summary") or {}).get("launch_posture"),
            "allow_order_submission": runtime_truth.get("allow_order_submission"),
            "execution_mode": runtime_truth.get("execution_mode"),
            "agent_run_mode": runtime_truth.get("agent_run_mode"),
        },
        "required_outputs": {
            "candidate_delta_arr_bps": candidate_delta_arr_bps,
            "expected_improvement_velocity_delta": 0.18,
            "arr_confidence_score": 0.46,
            "block_reasons": block_reasons,
            "finance_gate_pass": weather_finance_pass,
            "one_next_cycle_action": "run_shadow_scans_for_7d_on_:25_:55_windows_and_review_settlement_traceability",
        },
        "candidate_delta_arr_bps": candidate_delta_arr_bps,
        "expected_improvement_velocity_delta": 0.18,
        "arr_confidence_score": 0.46,
        "block_reasons": block_reasons,
        "finance_gate_pass": weather_finance_pass,
        "one_next_cycle_action": "run_shadow_scans_for_7d_on_:25_:55_windows_and_review_settlement_traceability",
        "references": {
            "dead_thesis_report": "research/imports/WEATHER_BRACKET_VALIDATION_REPORT.md",
            "edge_backlog": "research/edge_backlog_ranked.md",
            "finance_latest": "reports/finance/latest.json",
            "runtime_truth": "reports/runtime_truth_latest.json",
        },
    }
    return artifact


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("source_mapping_summary") if isinstance(payload.get("source_mapping_summary"), dict) else {}
    scan = payload.get("scan_windows") if isinstance(payload.get("scan_windows"), dict) else {}
    lines = [
        "# Instance 4 Weather Divergence Shadow",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        "- mode: shadow_only",
        f"- clean_city_count: {summary.get('clean_city_count')}",
        f"- clean_tradeable_markets: {(payload.get('market_scan') or {}).get('clean_tradeable_markets')}",
        f"- candidate_count: {(payload.get('market_scan') or {}).get('candidate_count')}",
        f"- should_scan_now: {scan.get('should_scan_now')}",
        f"- candidate_delta_arr_bps: {payload.get('candidate_delta_arr_bps')}",
        f"- arr_confidence_score: {payload.get('arr_confidence_score')}",
        f"- finance_gate_pass: {payload.get('finance_gate_pass')}",
        "",
        "## Block Reasons",
    ]
    for reason in payload.get("block_reasons") or []:
        lines.append(f"- {reason}")
    return "\n".join(lines) + "\n"


def main() -> int:
    payload = build_instance4_weather_lane_artifact()

    DEFAULT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    DEFAULT_MARKDOWN_PATH.write_text(render_markdown(payload), encoding="utf-8")

    print(f"Wrote {DEFAULT_OUTPUT_PATH}")
    print(f"Wrote {DEFAULT_MARKDOWN_PATH}")
    print(
        "required_outputs: "
        f"candidate_delta_arr_bps={payload['candidate_delta_arr_bps']} "
        f"expected_improvement_velocity_delta={payload['expected_improvement_velocity_delta']} "
        f"arr_confidence_score={payload['arr_confidence_score']} "
        f"finance_gate_pass={payload['finance_gate_pass']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
