#!/usr/bin/env python3
"""Search regime-conditioned BTC5 policies on top of the live global profile."""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo import (  # noqa: E402
    DEFAULT_ARCHIVE_GLOB,
    DEFAULT_LOSS_LIMIT_USD,
    DEFAULT_REMOTE_ROWS_JSON,
    DEFAULT_RUNTIME_TRUTH,
    DEFAULT_UP_MAX,
    DEFAULT_DOWN_MAX,
    DEFAULT_MAX_ABS_DELTA,
    GuardrailProfile,
    _annualize_arr_pct,
    _estimate_fill_retention_ratio,
    _load_runtime_truth,
    _live_profile_from_runtime_truth,
    _percentile,
    _round_metrics,
    _run_monte_carlo_from_entries,
    _safe_float,
    _safe_int,
    assemble_observed_rows,
)


DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BASE_ENV = Path("config/btc5_strategy.env")
DEFAULT_OVERRIDE_ENV = Path("state/btc5_autoresearch.env")
DEFAULT_REPORT_DIR = Path("reports/btc5_regime_policy_lab")
WINDOW_MINUTES = 5
WINDOWS_PER_YEAR = int((365 * 24 * 60) / WINDOW_MINUTES)
ET_ZONE = ZoneInfo("America/New_York")
SESSION_FILTERS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("open_et", (9, 10, 11)),
    ("midday_et", (12, 13)),
    ("late_et", (14, 15, 16)),
)
FRONTIER_SIZE_TARGETS = (10.0, 20.0, 50.0, 100.0, 200.0)
PROMOTION_FILL_RETENTION_FLOOR = 0.85
PROMOTION_REALISM_FLOOR = 0.85
CANDIDATE_CLASS_PRIORITY = {
    "promote": 3,
    "hold_current": 2,
    "probe_only": 1,
    "suppress_cluster": 0,
}


@dataclass(frozen=True)
class PolicyOverride:
    session_name: str
    et_hours: tuple[int, ...]
    profile: GuardrailProfile


@dataclass(frozen=True)
class PolicyCandidate:
    name: str
    default_profile: GuardrailProfile
    overrides: tuple[PolicyOverride, ...] = tuple()
    note: str = ""


def _policy_override_sort_key(override: PolicyOverride) -> tuple[int, tuple[int, ...], str]:
    hours = tuple(sorted(override.et_hours))
    return (len(hours), hours, override.session_name)


def order_policy_overrides(overrides: tuple[PolicyOverride, ...] | list[PolicyOverride]) -> tuple[PolicyOverride, ...]:
    return tuple(sorted(tuple(overrides), key=_policy_override_sort_key))


def _evidence_band(fills: int) -> str:
    if fills >= 16:
        return "validated"
    if fills >= 8:
        return "candidate"
    return "exploratory"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now_utc().strftime("%Y%m%dT%H%M%SZ")


def _load_env_file(path: Path) -> dict[str, str]:
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


def _merged_strategy_env(base_env: Path, override_env: Path) -> dict[str, str]:
    merged = _load_env_file(base_env)
    merged.update(_load_env_file(override_env))
    return merged


def _profile_from_env(name: str, env: dict[str, str]) -> GuardrailProfile:
    return GuardrailProfile(
        name=name,
        max_abs_delta=_safe_float(env.get("BTC5_MAX_ABS_DELTA"), DEFAULT_MAX_ABS_DELTA),
        up_max_buy_price=_safe_float(env.get("BTC5_UP_MAX_BUY_PRICE"), DEFAULT_UP_MAX),
        down_max_buy_price=_safe_float(env.get("BTC5_DOWN_MAX_BUY_PRICE"), DEFAULT_DOWN_MAX),
        note="loaded from strategy env",
    )


def _window_dt_et(row: dict[str, Any]) -> datetime | None:
    window_start_ts = _safe_int(row.get("window_start_ts"), 0)
    if window_start_ts <= 0:
        return None
    return datetime.fromtimestamp(window_start_ts, tz=timezone.utc).astimezone(ET_ZONE)


def _row_observed_at_utc(row: dict[str, Any]) -> datetime | None:
    window_start_ts = _safe_int(row.get("window_start_ts"), 0)
    if window_start_ts > 0:
        return datetime.fromtimestamp(window_start_ts, tz=timezone.utc)
    updated_raw = str(row.get("updated_at") or "").strip()
    if not updated_raw:
        return None
    try:
        observed = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        return observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc)


def enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        dt_et = _window_dt_et(row)
        item = dict(row)
        item["et_hour"] = dt_et.hour if dt_et is not None else None
        enriched.append(item)
    return enriched


def _profile_key(profile: GuardrailProfile) -> tuple[float | None, float | None, float | None]:
    return (
        profile.max_abs_delta,
        profile.up_max_buy_price,
        profile.down_max_buy_price,
    )


def build_session_filters(rows: list[dict[str, Any]], *, min_session_rows: int) -> list[tuple[str, tuple[int, ...]]]:
    counts_by_hour: dict[int, int] = {}
    for row in rows:
        hour = row.get("et_hour")
        if hour is None:
            continue
        counts_by_hour[int(hour)] = counts_by_hour.get(int(hour), 0) + 1
    hour_filters = [
        (f"hour_et_{hour:02d}", (hour,))
        for hour, count in sorted(counts_by_hour.items())
        if count >= max(1, int(min_session_rows))
    ]
    return list(SESSION_FILTERS) + hour_filters


def build_override_profiles() -> list[GuardrailProfile]:
    profiles: list[GuardrailProfile] = []
    seen: set[tuple[float | None, float | None, float | None]] = set()
    for max_abs_delta in (0.00002, 0.00005, 0.00010, 0.00015):
        for down_cap in (0.48, 0.49, 0.50, 0.51):
            for up_cap in (0.0, 0.47, 0.48, 0.49, 0.50, 0.51):
                profile = GuardrailProfile(
                    name=f"grid_d{max_abs_delta:.5f}_up{up_cap:.2f}_down{down_cap:.2f}",
                    max_abs_delta=max_abs_delta,
                    up_max_buy_price=up_cap,
                    down_max_buy_price=down_cap,
                )
                key = _profile_key(profile)
                if key in seen:
                    continue
                profiles.append(profile)
                seen.add(key)
    return profiles


def _policy_name(default_profile: GuardrailProfile, overrides: tuple[PolicyOverride, ...]) -> str:
    ordered = order_policy_overrides(overrides)
    if not ordered:
        return f"policy_{default_profile.name}"
    suffix = "__".join(f"{override.session_name}__{override.profile.name}" for override in ordered)
    return f"policy_{default_profile.name}__{suffix}"


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


def _matching_policy_override(row: dict[str, Any], policy: PolicyCandidate) -> PolicyOverride | None:
    hour = row.get("et_hour")
    if hour is None:
        return None
    matches = [override for override in policy.overrides if hour in override.et_hours]
    if not matches:
        return None
    return order_policy_overrides(matches)[0]


def row_matches_policy(row: dict[str, Any], policy: PolicyCandidate) -> bool:
    override = _matching_policy_override(row, policy)
    if override is not None:
        return row_matches_profile(row, override.profile)
    return row_matches_profile(row, policy.default_profile)


def summarize_policy_history(rows: list[dict[str, Any]], policy: PolicyCandidate) -> dict[str, Any]:
    matched = [row for row in rows if row_matches_policy(row, policy)]
    baseline_filled = [row for row in rows if row.get("order_status") == "live_filled"]
    matched_filled = [row for row in matched if row.get("order_status") == "live_filled"]
    matched_attempted = [row for row in matched if str(row.get("order_status") or "").startswith("live_")]
    wins = sum(1 for row in matched_filled if _safe_float(row.get("pnl_usd"), 0.0) > 0)
    replay_pnl = sum(_safe_float(row.get("pnl_usd"), 0.0) for row in matched_filled)
    total_notional = sum(_safe_float(row.get("trade_size_usd"), 0.0) for row in matched_filled)
    return _round_metrics(
        {
            "baseline_window_rows": len(rows),
            "baseline_live_filled_rows": len(baseline_filled),
            "replay_window_rows": len(matched),
            "replay_attempt_rows": len(matched_attempted),
            "replay_live_filled_rows": len(matched_filled),
            "window_coverage_ratio": (len(matched) / len(rows)) if rows else 0.0,
            "fill_coverage_ratio": (len(matched_filled) / len(baseline_filled)) if baseline_filled else 0.0,
            "replay_live_filled_pnl_usd": replay_pnl,
            "avg_pnl_usd": (replay_pnl / len(matched_filled)) if matched_filled else 0.0,
            "win_rate": (wins / len(matched_filled)) if matched_filled else 0.0,
            "trade_notional_usd": total_notional,
        }
    )


def _block_bootstrap_series(
    values: list[float],
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


def run_policy_monte_carlo(
    rows: list[dict[str, Any]],
    policy: PolicyCandidate,
    *,
    paths: int,
    horizon_trades: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
) -> dict[str, Any]:
    series = [
        _safe_float(row.get("realized_pnl_usd"), 0.0) if row_matches_policy(row, policy) else 0.0
        for row in rows
    ]
    non_zero = [value for value in series if abs(value) > 1e-12]
    if not series:
        return {
            "paths": int(paths),
            "horizon_trades": int(horizon_trades),
            "block_size": int(block_size),
            "loss_limit_usd": round(loss_limit_usd, 4),
            "profit_probability": 0.0,
            "mean_total_pnl_usd": 0.0,
            "median_total_pnl_usd": 0.0,
            "p05_total_pnl_usd": 0.0,
            "p95_total_pnl_usd": 0.0,
            "p95_max_drawdown_usd": 0.0,
            "loss_limit_hit_probability": 0.0,
            "avg_active_trades": 0.0,
        }

    rng = random.Random(f"{seed}:{policy.name}")
    total_pnls: list[float] = []
    max_drawdowns: list[float] = []
    active_counts: list[int] = []
    loss_hits = 0
    for _ in range(max(1, int(paths))):
        path = _block_bootstrap_series(
            series,
            horizon_trades=max(1, int(horizon_trades)),
            block_size=max(1, int(block_size)),
            rng=rng,
        )
        running_pnl = 0.0
        peak_pnl = 0.0
        max_drawdown = 0.0
        active_trades = 0
        loss_hit = False
        for pnl in path:
            if abs(pnl) > 1e-12:
                active_trades += 1
            running_pnl += pnl
            peak_pnl = max(peak_pnl, running_pnl)
            max_drawdown = max(max_drawdown, peak_pnl - running_pnl)
            if running_pnl <= -abs(loss_limit_usd):
                loss_hit = True
        if loss_hit:
            loss_hits += 1
        total_pnls.append(running_pnl)
        max_drawdowns.append(max_drawdown)
        active_counts.append(active_trades)

    profit_probability = sum(1 for value in total_pnls if value > 0) / len(total_pnls)
    return _round_metrics(
        {
            "paths": int(paths),
            "horizon_trades": int(horizon_trades),
            "block_size": int(block_size),
            "loss_limit_usd": round(loss_limit_usd, 4),
            "empirical_non_zero_rows": len(non_zero),
            "profit_probability": profit_probability,
            "mean_total_pnl_usd": sum(total_pnls) / len(total_pnls),
            "median_total_pnl_usd": _percentile(total_pnls, 50),
            "p05_total_pnl_usd": _percentile(total_pnls, 5),
            "p95_total_pnl_usd": _percentile(total_pnls, 95),
            "p95_max_drawdown_usd": _percentile(max_drawdowns, 95),
            "loss_limit_hit_probability": loss_hits / len(total_pnls),
            "avg_active_trades": sum(active_counts) / len(active_counts),
        }
    )


def summarize_policy_arr(
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


def build_policy_candidates(
    rows: list[dict[str, Any]],
    *,
    current_live_profile: GuardrailProfile,
    min_session_rows: int,
) -> list[PolicyCandidate]:
    sessions = build_session_filters(rows, min_session_rows=min_session_rows)
    override_profiles = build_override_profiles()
    candidates = [
        PolicyCandidate(
            name=_policy_name(current_live_profile, tuple()),
            default_profile=current_live_profile,
        )
    ]
    for session_name, hours in sessions:
        for profile in override_profiles:
            if _profile_key(profile) == _profile_key(current_live_profile):
                continue
            override = PolicyOverride(session_name=session_name, et_hours=tuple(hours), profile=profile)
            ordered_overrides = order_policy_overrides((override,))
            candidates.append(
                PolicyCandidate(
                    name=_policy_name(current_live_profile, ordered_overrides),
                    default_profile=current_live_profile,
                    overrides=ordered_overrides,
                    note="single-session override on top of current live profile",
                )
            )
    return candidates


def _score_candidates(evaluated: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    current_policy = next(
        (candidate for candidate in evaluated if not (candidate.get("policy", {}).get("overrides") or [])),
        None,
    )
    current_replay_pnl = max(
        1e-9,
        _safe_float((current_policy or {}).get("historical", {}).get("replay_live_filled_pnl_usd"), 0.0),
    )
    current_fill_rows = max(
        1,
        _safe_int((current_policy or {}).get("historical", {}).get("replay_live_filled_rows"), 0),
    )
    for candidate in evaluated:
        replay_pnl_ratio = _safe_float(candidate["historical"].get("replay_live_filled_pnl_usd"), 0.0) / current_replay_pnl
        fill_ratio = _safe_int(candidate["historical"].get("replay_live_filled_rows"), 0) / float(current_fill_rows)
        profit_probability = _safe_float(candidate["monte_carlo"].get("profit_probability"), 0.0)
        median_arr_pct = _safe_float(candidate["continuation"].get("median_arr_pct"), 0.0)
        policy = candidate.get("policy") if isinstance(candidate.get("policy"), dict) else {}
        overrides = policy.get("overrides") if isinstance(policy.get("overrides"), list) else []
        frontier_focus_tags: set[str] = set()
        frontier_bias_weight = 1.0
        for override in overrides:
            if not isinstance(override, dict):
                continue
            hours = {
                int(hour)
                for hour in (override.get("et_hours") or [])
                if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
            }
            profile = override.get("profile") if isinstance(override.get("profile"), dict) else {}
            up_cap = profile.get("up_max_buy_price")
            down_cap = profile.get("down_max_buy_price")
            max_abs_delta = profile.get("max_abs_delta")
            if hours:
                frontier_focus_tags.add("session_conditioned")
            if up_cap is not None and _safe_float(up_cap, 1.0) <= 0.01:
                frontier_focus_tags.add("session_conditioned_one_sided")
                frontier_bias_weight *= 1.2
            if max_abs_delta is not None and _safe_float(max_abs_delta, 1.0) <= 0.00010:
                frontier_focus_tags.add("session_tight_delta")
                frontier_bias_weight *= 1.1
            if max_abs_delta is not None and _safe_float(max_abs_delta, 1.0) <= 0.00005:
                frontier_focus_tags.add("high_conviction_tight_delta")
                frontier_bias_weight *= 1.1
            if (
                down_cap is not None
                and _safe_float(down_cap, 1.0) <= 0.49
                and any(hour in {9, 10, 11} for hour in hours)
            ):
                frontier_focus_tags.add("session_tight_down_bias")
                frontier_bias_weight *= 1.1
        candidate["scoring"] = _round_metrics(
            {
                "metric_name": "live_policy_score",
                "replay_pnl_ratio_vs_current": replay_pnl_ratio,
                "fill_ratio_vs_current": fill_ratio,
                "profit_probability": profit_probability,
                "frontier_bias_weight": frontier_bias_weight,
                "frontier_focus_tags": sorted(frontier_focus_tags),
                "live_policy_score": median_arr_pct
                * max(0.25, min(1.0, replay_pnl_ratio))
                * max(0.25, min(1.0, fill_ratio))
                * max(0.5, profit_probability)
                * frontier_bias_weight,
            }
        )

    evaluated.sort(
        key=lambda candidate: (
            _safe_float(candidate.get("scoring", {}).get("live_policy_score"), 0.0),
            _safe_float(candidate["continuation"].get("median_arr_pct"), 0.0),
            _safe_float(candidate["continuation"].get("p05_arr_pct"), 0.0),
            _safe_float(candidate["monte_carlo"].get("profit_probability"), 0.0),
            -_safe_float(candidate["monte_carlo"].get("p95_max_drawdown_usd"), 0.0),
            _safe_int(candidate["historical"].get("replay_live_filled_rows"), 0),
            _safe_float(candidate["historical"].get("replay_live_filled_pnl_usd"), 0.0),
        ),
        reverse=True,
    )
    return evaluated, current_policy


def _policy_candidate_from_record(record: dict[str, Any]) -> PolicyCandidate | None:
    policy = record.get("policy") if isinstance(record, dict) else {}
    if not isinstance(policy, dict):
        return None
    default_profile_payload = policy.get("default_profile")
    if not isinstance(default_profile_payload, dict):
        return None
    default_profile = GuardrailProfile(
        name=str(default_profile_payload.get("name") or "default_profile"),
        max_abs_delta=_safe_float(default_profile_payload.get("max_abs_delta"), None),
        up_max_buy_price=_safe_float(default_profile_payload.get("up_max_buy_price"), None),
        down_max_buy_price=_safe_float(default_profile_payload.get("down_max_buy_price"), None),
        note=str(default_profile_payload.get("note") or ""),
    )
    overrides: list[PolicyOverride] = []
    for item in policy.get("overrides") or []:
        if not isinstance(item, dict):
            continue
        profile_payload = item.get("profile")
        if not isinstance(profile_payload, dict):
            continue
        hours = tuple(
            int(hour)
            for hour in (item.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
        )
        if not hours:
            continue
        overrides.append(
            PolicyOverride(
                session_name=str(item.get("session_name") or "").strip(),
                et_hours=hours,
                profile=GuardrailProfile(
                    name=str(profile_payload.get("name") or "override_profile"),
                    max_abs_delta=_safe_float(profile_payload.get("max_abs_delta"), None),
                    up_max_buy_price=_safe_float(profile_payload.get("up_max_buy_price"), None),
                    down_max_buy_price=_safe_float(profile_payload.get("down_max_buy_price"), None),
                    note=str(profile_payload.get("note") or ""),
                ),
            )
        )
    ordered_overrides = order_policy_overrides(overrides)
    return PolicyCandidate(
        name=_policy_name(default_profile, ordered_overrides),
        default_profile=default_profile,
        overrides=ordered_overrides,
        note=str(policy.get("note") or ""),
    )


def _composed_policy_candidates(
    *,
    evaluated: list[dict[str, Any]],
    current_live_profile: GuardrailProfile,
    max_session_overrides: int,
    top_single_overrides_per_session: int,
    max_composed_candidates: int,
) -> list[PolicyCandidate]:
    if max_session_overrides <= 1:
        return []

    singles_by_session: dict[str, list[dict[str, Any]]] = {}
    for candidate in evaluated:
        overrides = (candidate.get("policy") or {}).get("overrides") or []
        if len(overrides) != 1:
            continue
        override = overrides[0] if isinstance(overrides[0], dict) else {}
        session_name = str(override.get("session_name") or "").strip()
        if not session_name:
            continue
        singles_by_session.setdefault(session_name, []).append(candidate)

    seeds: list[dict[str, Any]] = []
    for session_candidates in singles_by_session.values():
        session_candidates.sort(
            key=lambda candidate: (
                _safe_float((candidate.get("scoring") or {}).get("live_policy_score"), 0.0),
                _safe_float(((candidate.get("continuation") or {}).get("median_arr_pct")), 0.0),
                _safe_float(((candidate.get("historical") or {}).get("replay_live_filled_pnl_usd")), 0.0),
            ),
            reverse=True,
        )
        seeds.extend(session_candidates[: max(1, int(top_single_overrides_per_session))])

    composed: list[tuple[float, PolicyCandidate]] = []
    seen_names: set[str] = set()
    for left, right in combinations(seeds, 2):
        left_policy = _policy_candidate_from_record(left)
        right_policy = _policy_candidate_from_record(right)
        if left_policy is None or right_policy is None:
            continue
        if len(left_policy.overrides) != 1 or len(right_policy.overrides) != 1:
            continue
        if left_policy.overrides[0].session_name == right_policy.overrides[0].session_name:
            continue
        overrides = order_policy_overrides(left_policy.overrides + right_policy.overrides)
        if len(overrides) > max(1, int(max_session_overrides)):
            continue
        candidate = PolicyCandidate(
            name=_policy_name(current_live_profile, overrides),
            default_profile=current_live_profile,
            overrides=overrides,
            note=f"{len(overrides)}-session override on top of current live profile",
        )
        if candidate.name in seen_names:
            continue
        seen_names.add(candidate.name)
        composed_score = (
            _safe_float((left.get("scoring") or {}).get("live_policy_score"), 0.0)
            + _safe_float((right.get("scoring") or {}).get("live_policy_score"), 0.0)
        )
        composed.append((composed_score, candidate))

    composed.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in composed[: max(0, int(max_composed_candidates))]]


def _recommended_session_policy(best_policy: dict[str, Any] | None) -> list[dict[str, Any]]:
    policy = (best_policy or {}).get("policy") or {}
    recommended: list[dict[str, Any]] = []
    for override in policy.get("overrides") or []:
        if not isinstance(override, dict):
            continue
        hours = sorted(
            {
                int(hour)
                for hour in (override.get("et_hours") or [])
                if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
            }
        )
        if not hours:
            continue
        profile = override.get("profile") if isinstance(override.get("profile"), dict) else {}
        record: dict[str, Any] = {
            "name": str(override.get("session_name") or profile.get("name") or "session_policy").strip(),
            "et_hours": hours,
        }
        max_abs_delta = profile.get("max_abs_delta")
        up_max_buy_price = profile.get("up_max_buy_price")
        down_max_buy_price = profile.get("down_max_buy_price")
        if max_abs_delta is not None:
            record["max_abs_delta"] = _safe_float(max_abs_delta, 0.0) or 0.0
        if up_max_buy_price is not None:
            record["up_max_buy_price"] = _safe_float(up_max_buy_price, 0.0) or 0.0
        if down_max_buy_price is not None:
            record["down_max_buy_price"] = _safe_float(down_max_buy_price, 0.0) or 0.0
        recommended.append(record)
    return recommended


def _row_matches_policy_payload(row: dict[str, Any], policy_payload: dict[str, Any]) -> bool:
    default_profile_payload = policy_payload.get("default_profile")
    if not isinstance(default_profile_payload, dict):
        return False
    default_profile = GuardrailProfile(
        name=str(default_profile_payload.get("name") or "default"),
        max_abs_delta=(
            _safe_float(default_profile_payload.get("max_abs_delta"), 0.0)
            if default_profile_payload.get("max_abs_delta") is not None
            else None
        ),
        up_max_buy_price=(
            _safe_float(default_profile_payload.get("up_max_buy_price"), 0.0)
            if default_profile_payload.get("up_max_buy_price") is not None
            else None
        ),
        down_max_buy_price=(
            _safe_float(default_profile_payload.get("down_max_buy_price"), 0.0)
            if default_profile_payload.get("down_max_buy_price") is not None
            else None
        ),
    )
    hour = row.get("et_hour")
    overrides = policy_payload.get("overrides")
    if isinstance(overrides, list):
        for override in overrides:
            if not isinstance(override, dict):
                continue
            hours = {
                int(h)
                for h in (override.get("et_hours") or [])
                if isinstance(h, int) or (isinstance(h, str) and h.isdigit())
            }
            if hours and hour in hours:
                profile_payload = override.get("profile")
                if not isinstance(profile_payload, dict):
                    return False
                override_profile = GuardrailProfile(
                    name=str(profile_payload.get("name") or "override"),
                    max_abs_delta=(
                        _safe_float(profile_payload.get("max_abs_delta"), 0.0)
                        if profile_payload.get("max_abs_delta") is not None
                        else None
                    ),
                    up_max_buy_price=(
                        _safe_float(profile_payload.get("up_max_buy_price"), 0.0)
                        if profile_payload.get("up_max_buy_price") is not None
                        else None
                    ),
                    down_max_buy_price=(
                        _safe_float(profile_payload.get("down_max_buy_price"), 0.0)
                        if profile_payload.get("down_max_buy_price") is not None
                        else None
                    ),
                )
                return row_matches_profile(row, override_profile)
    return row_matches_profile(row, default_profile)


def _last_improvement_for_policy(
    rows: list[dict[str, Any]],
    best_policy: dict[str, Any] | None,
) -> datetime | None:
    policy_payload = (best_policy or {}).get("policy")
    if not isinstance(policy_payload, dict):
        return None
    matched = [
        row for row in rows
        if _row_matches_policy_payload(row, policy_payload)
        and str(row.get("order_status") or "").strip().lower() == "live_filled"
        and _safe_float(row.get("pnl_usd"), 0.0) > 0.0
    ]
    if not matched:
        matched = [
            row for row in rows
            if _row_matches_policy_payload(row, policy_payload)
            and str(row.get("order_status") or "").strip().lower() == "live_filled"
        ]
    timestamps = [ts for ts in (_row_observed_at_utc(row) for row in matched) if ts is not None]
    return max(timestamps) if timestamps else None


def _candidate_runtime_package(candidate: dict[str, Any]) -> dict[str, Any]:
    policy = candidate.get("policy") if isinstance(candidate, dict) else {}
    if not isinstance(policy, dict):
        policy = {}
    historical = candidate.get("historical") if isinstance(candidate, dict) else {}
    if not isinstance(historical, dict):
        historical = {}
    continuation = candidate.get("continuation") if isinstance(candidate, dict) else {}
    if not isinstance(continuation, dict):
        continuation = {}
    scoring = candidate.get("scoring") if isinstance(candidate, dict) else {}
    if not isinstance(scoring, dict):
        scoring = {}
    session_policy = _recommended_session_policy(candidate)
    overrides = policy.get("overrides") if isinstance(policy.get("overrides"), list) else []
    primary_override = overrides[0] if overrides and isinstance(overrides[0], dict) else {}
    override_profile = (
        primary_override.get("profile")
        if isinstance(primary_override, dict) and isinstance(primary_override.get("profile"), dict)
        else {}
    )
    if not isinstance(override_profile, dict):
        override_profile = {}
    default_profile = policy.get("default_profile") if isinstance(policy.get("default_profile"), dict) else {}
    if not isinstance(default_profile, dict):
        default_profile = {}
    profile = override_profile or default_profile
    session_names = [str(item.get("name") or "") for item in session_policy if isinstance(item, dict)]
    et_hours = sorted(
        {
            int(hour)
            for item in session_policy
            if isinstance(item, dict)
            for hour in (item.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
        }
    )
    primary_session_name = (
        str(primary_override.get("session_name") or "any")
        if len(session_policy) <= 1
        else f"{len(session_policy)}_sessions"
    )
    validation_live_filled_rows = _safe_int(historical.get("replay_live_filled_rows"), 0)
    generalization_ratio = max(
        0.0,
        min(1.5, _safe_float(scoring.get("fill_ratio_vs_current"), 0.0)),
    )
    return {
        "name": str(policy.get("name") or "candidate_policy"),
        "session_name": primary_session_name,
        "session_names": session_names,
        "session_count": len(session_policy),
        "session_policy": session_policy,
        "et_hours": et_hours,
        "max_abs_delta": (
            _safe_float(profile.get("max_abs_delta"), 0.0)
            if profile.get("max_abs_delta") is not None
            else None
        ),
        "up_max_buy_price": (
            _safe_float(profile.get("up_max_buy_price"), 0.0)
            if profile.get("up_max_buy_price") is not None
            else None
        ),
        "down_max_buy_price": (
            _safe_float(profile.get("down_max_buy_price"), 0.0)
            if profile.get("down_max_buy_price") is not None
            else None
        ),
        "ranking_score": _safe_float(scoring.get("live_policy_score"), 0.0),
        "evidence_band": _evidence_band(validation_live_filled_rows),
        "validation_live_filled_rows": validation_live_filled_rows,
        "generalization_ratio": generalization_ratio,
        "validation_median_arr_pct": _safe_float(continuation.get("median_arr_pct"), 0.0),
        "validation_p05_arr_pct": _safe_float(continuation.get("p05_arr_pct"), 0.0),
        "validation_replay_pnl_usd": _safe_float(historical.get("replay_live_filled_pnl_usd"), 0.0),
    }


def _profile_runtime_package(profile: GuardrailProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "session_name": "any",
        "session_names": [],
        "session_count": 0,
        "session_policy": [],
        "et_hours": [],
        "max_abs_delta": profile.max_abs_delta,
        "up_max_buy_price": profile.up_max_buy_price,
        "down_max_buy_price": profile.down_max_buy_price,
        "ranking_score": 0.0,
        "evidence_band": "exploratory",
        "validation_live_filled_rows": 0,
        "generalization_ratio": 0.0,
        "validation_median_arr_pct": 0.0,
        "validation_p05_arr_pct": 0.0,
        "validation_replay_pnl_usd": 0.0,
    }


def _follow_up_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _follow_up_candidates_with_tradeoffs(candidates, active_candidate=None)


def _evidence_weight(evidence_band: str) -> float:
    if evidence_band == "validated":
        return 1.0
    if evidence_band == "candidate":
        return 0.8
    return 0.6


def _normalized_generalization(value: Any) -> float:
    return min(1.0, max(0.0, _safe_float(value, 0.0)))


def _regime_followup_families(item: dict[str, Any]) -> list[str]:
    families: list[str] = []
    up_cap = item.get("up_max_buy_price")
    down_cap = item.get("down_max_buy_price")
    max_abs_delta = item.get("max_abs_delta")
    et_hours = tuple(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int))
    session_count = _safe_int(item.get("session_count"), 0)

    if up_cap is None or _safe_float(up_cap, 1.0) <= 0.01:
        families.append("down_only")
    if up_cap is None or _safe_float(up_cap, 1.0) <= 0.47:
        families.append("up_disabled_or_nearly_disabled")
    if (
        max_abs_delta is not None
        and _safe_float(max_abs_delta, 1.0) <= 0.00008
        and down_cap is not None
        and _safe_float(down_cap, 1.0) <= 0.49
    ):
        families.append("tight_delta_down_bias")
    if (
        session_count > 0
        and max_abs_delta is not None
        and _safe_float(max_abs_delta, 1.0) <= 0.00010
        and down_cap is not None
        and _safe_float(down_cap, 1.0) <= 0.49
        and any(hour in {9, 10, 11} for hour in et_hours)
    ):
        families.append("session_tight_down_bias")
    return families


def _frontier_focus_tags(item: dict[str, Any]) -> list[str]:
    tags = set(str(tag) for tag in (item.get("follow_up_families") or []))
    session_count = _safe_int(item.get("session_count"), 0)
    max_abs_delta = item.get("max_abs_delta")
    up_cap = item.get("up_max_buy_price")

    if session_count > 0:
        tags.add("session_conditioned")
    if session_count > 0 and up_cap is not None and _safe_float(up_cap, 1.0) <= 0.01:
        tags.add("session_conditioned_one_sided")
    if max_abs_delta is not None:
        delta = _safe_float(max_abs_delta, 0.0)
        if delta <= 0.00005:
            tags.add("high_conviction_tight_delta")
        elif delta <= 0.00010 and session_count > 0:
            tags.add("session_tight_delta")
    return sorted(tags)


def _frontier_bias_score(item: dict[str, Any]) -> float:
    tags = set(str(tag) for tag in (item.get("frontier_focus_tags") or _frontier_focus_tags(item)))
    score = 0.0
    if "session_conditioned_one_sided" in tags:
        score += 2.5
    if "high_conviction_tight_delta" in tags:
        score += 2.0
    elif "session_tight_delta" in tags:
        score += 1.25
    if "session_tight_down_bias" in tags:
        score += 1.5
    score += min(1.0, _safe_float(item.get("execution_realism_score"), 0.0))
    score += min(1.0, _safe_int(item.get("validation_live_filled_rows"), 0) / 16.0)
    score += 0.5 * _evidence_weight(str(item.get("evidence_band") or "exploratory"))
    return round(score, 4)


def _high_conviction_score(item: dict[str, Any]) -> float:
    score = _frontier_bias_score(item)
    if _safe_float(item.get("validation_p05_arr_pct"), 0.0) > 0.0:
        score += 1.0
    score += 0.75 * _normalized_generalization(item.get("generalization_ratio"))
    return round(score, 4)


def _execution_realism_score(*, fill_retention: float, generalization_ratio: float, evidence_band: str) -> float:
    evidence_weight = _evidence_weight(evidence_band)
    return min(
        1.0,
        max(
            0.0,
            (0.5 * min(1.0, fill_retention))
            + (0.3 * min(1.0, generalization_ratio))
            + (0.2 * evidence_weight),
        ),
    )


def _candidate_status_fields(candidate_class: str) -> tuple[str, str]:
    if candidate_class == "promote":
        return "promotion_ready", "clear_for_promotion"
    if candidate_class == "hold_current":
        return "validated_hold", "insufficient_clear_upgrade_vs_active"
    if candidate_class == "suppress_cluster":
        return "suppress_cluster", "shadow_block_until_revalidated"
    return "probe_only", "requires_revalidation_or_fill_retention_recovery"


def _candidate_classification(
    *,
    evidence_band: str,
    fill_retention: float,
    execution_realism_score: float,
    arr_delta_vs_active_pct: float,
    p05_delta_vs_active_pct: float,
    replay_pnl_delta_vs_active_usd: float | None = None,
) -> tuple[str, list[str]]:
    reason_tags: list[str] = []
    if evidence_band != "validated":
        reason_tags.append(f"evidence_{evidence_band}")
    if fill_retention < PROMOTION_FILL_RETENTION_FLOOR:
        reason_tags.append("fill_retention_below_0.85")
    if execution_realism_score < PROMOTION_REALISM_FLOOR:
        reason_tags.append("execution_realism_below_0.85")
    if arr_delta_vs_active_pct <= 0.0:
        reason_tags.append("median_not_above_active")
    if p05_delta_vs_active_pct <= 0.0:
        reason_tags.append("p05_not_above_active")
    if replay_pnl_delta_vs_active_usd is not None and replay_pnl_delta_vs_active_usd <= 0.0:
        reason_tags.append("replay_pnl_not_above_active")

    if (
        evidence_band == "validated"
        and fill_retention >= PROMOTION_FILL_RETENTION_FLOOR
        and execution_realism_score >= PROMOTION_REALISM_FLOOR
        and arr_delta_vs_active_pct > 0.0
        and p05_delta_vs_active_pct > 0.0
        and (replay_pnl_delta_vs_active_usd is None or replay_pnl_delta_vs_active_usd > 0.0)
    ):
        return "promote", ["validated_clear_upgrade"]
    if (
        evidence_band != "validated"
        or fill_retention < PROMOTION_FILL_RETENTION_FLOOR
        or execution_realism_score < PROMOTION_REALISM_FLOOR
    ):
        return "probe_only", reason_tags or ["requires_revalidation"]
    return "hold_current", reason_tags or ["validated_but_not_clear_upgrade"]


def _apply_candidate_classification(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    candidate_class, reason_tags = _candidate_classification(
        evidence_band=str(payload.get("evidence_band") or "exploratory"),
        fill_retention=_safe_float(payload.get("fill_retention_vs_active"), 0.0),
        execution_realism_score=_safe_float(payload.get("execution_realism_score"), 0.0),
        arr_delta_vs_active_pct=_safe_float(payload.get("arr_improvement_vs_active_pct"), 0.0),
        p05_delta_vs_active_pct=_safe_float(payload.get("p05_arr_improvement_vs_active_pct"), 0.0),
        replay_pnl_delta_vs_active_usd=(
            _safe_float(payload.get("replay_pnl_improvement_vs_active_usd"), 0.0)
            if payload.get("replay_pnl_improvement_vs_active_usd") is not None
            else None
        ),
    )
    families = {str(tag) for tag in (payload.get("follow_up_families") or []) if str(tag)}
    if candidate_class == "probe_only":
        families.add("probe_only_exploratory")
    payload["follow_up_families"] = sorted(families)
    research_status, promotion_gate = _candidate_status_fields(candidate_class)
    payload["candidate_class"] = candidate_class
    payload["candidate_class_reason_tags"] = reason_tags
    payload["research_status"] = research_status
    payload["promotion_gate"] = promotion_gate
    return payload


def _candidate_class_priority(item: dict[str, Any]) -> int:
    return CANDIDATE_CLASS_PRIORITY.get(str(item.get("candidate_class") or ""), -1)


def _best_candidate_by_class(candidates: list[dict[str, Any]], candidate_class: str) -> dict[str, Any] | None:
    eligible = [item for item in candidates if str(item.get("candidate_class") or "") == candidate_class]
    if not eligible:
        return None
    if candidate_class == "promote":
        return dict(eligible[0])
    eligible.sort(
        key=lambda item: (
            _candidate_class_priority(item),
            _safe_float(item.get("ranking_score"), 0.0),
            _safe_float(item.get("execution_realism_score"), 0.0),
            _safe_float(item.get("validation_p05_arr_pct"), 0.0),
            -_safe_float(item.get("total_loss_usd"), 0.0),
            str(item.get("name") or item.get("filter_name") or ""),
        ),
        reverse=True,
    )
    return dict(eligible[0])


def _class_breakdown(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts = {label: 0 for label in CANDIDATE_CLASS_PRIORITY}
    for candidate in candidates:
        label = str(candidate.get("candidate_class") or "")
        if label in counts:
            counts[label] += 1
    return counts


def _hold_current_candidate(active_candidate: dict[str, Any]) -> dict[str, Any]:
    payload = dict(active_candidate)
    evidence_band = str(payload.get("evidence_band") or "exploratory")
    generalization_ratio = _safe_float(payload.get("generalization_ratio"), 0.0)
    execution_realism_score = _execution_realism_score(
        fill_retention=1.0,
        generalization_ratio=generalization_ratio,
        evidence_band=evidence_band,
    )
    payload.update(
        {
            "arr_improvement_vs_active_pct": 0.0,
            "p05_arr_improvement_vs_active_pct": 0.0,
            "fill_retention_vs_active": 1.0,
            "execution_realism_score": round(execution_realism_score, 4),
            "execution_realism_label": (
                "high" if execution_realism_score >= 0.8 else ("medium" if execution_realism_score >= 0.6 else "low")
            ),
            "follow_up_families": [],
            "frontier_focus_tags": [],
            "frontier_bias_score": 0.0,
            "high_conviction_score": round(0.75 * _normalized_generalization(generalization_ratio), 4),
            "candidate_class": "hold_current",
            "candidate_class_reason_tags": ["active_profile_baseline"],
            "research_status": "validated_hold",
            "promotion_gate": "active_profile_baseline",
        }
    )
    return payload


def _follow_up_candidates_with_tradeoffs(
    candidates: list[dict[str, Any]],
    *,
    active_candidate: dict[str, Any] | None,
    limit: int | None = 5,
) -> list[dict[str, Any]]:
    active_arr = _safe_float((active_candidate or {}).get("validation_median_arr_pct"), 0.0)
    active_replay_pnl = _safe_float((active_candidate or {}).get("validation_replay_pnl_usd"), 0.0)
    active_p05 = _safe_float((active_candidate or {}).get("validation_p05_arr_pct"), 0.0)
    active_fills = max(1, _safe_int((active_candidate or {}).get("validation_live_filled_rows"), 0))
    packages: list[dict[str, Any]] = []
    for candidate in candidates:
        package = _candidate_runtime_package(candidate)
        validation_fills = _safe_int(package.get("validation_live_filled_rows"), 0)
        fill_retention = validation_fills / float(active_fills)
        generalization_ratio = _safe_float(package.get("generalization_ratio"), 0.0)
        evidence_band = str(package.get("evidence_band") or "exploratory")
        execution_realism_score = _execution_realism_score(
            fill_retention=fill_retention,
            generalization_ratio=generalization_ratio,
            evidence_band=evidence_band,
        )
        package["arr_improvement_vs_active_pct"] = round(
            _safe_float(package.get("validation_median_arr_pct"), 0.0) - active_arr,
            4,
        )
        package["replay_pnl_improvement_vs_active_usd"] = round(
            _safe_float(package.get("validation_replay_pnl_usd"), 0.0) - active_replay_pnl,
            4,
        )
        package["p05_arr_improvement_vs_active_pct"] = round(
            _safe_float(package.get("validation_p05_arr_pct"), 0.0) - active_p05,
            4,
        )
        package["fill_retention_vs_active"] = round(fill_retention, 4)
        package["execution_realism_score"] = round(execution_realism_score, 4)
        package["execution_realism_label"] = (
            "high" if execution_realism_score >= 0.8 else ("medium" if execution_realism_score >= 0.6 else "low")
        )
        package["follow_up_families"] = _regime_followup_families(package)
        package["frontier_focus_tags"] = _frontier_focus_tags(package)
        package["frontier_bias_score"] = _frontier_bias_score(package)
        package["high_conviction_score"] = _high_conviction_score(package)
        packages.append(_apply_candidate_classification(package))
    packages.sort(
        key=lambda item: (
            -_candidate_class_priority(item),
            -_safe_float(item.get("ranking_score"), 0.0),
            -_safe_float(item.get("execution_realism_score"), 0.0),
            str(item.get("name") or ""),
        )
    )
    if limit is None:
        return packages
    return packages[: max(0, int(limit))]


def _best_live_followups(follow_ups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in follow_ups if item.get("follow_up_families")]
    if not candidates:
        candidates = list(follow_ups)
    candidates.sort(
        key=lambda item: (
            -_candidate_class_priority(item),
            -_safe_float(item.get("execution_realism_score"), 0.0),
            -_safe_float(item.get("ranking_score"), 0.0),
            str(item.get("name") or ""),
        )
    )
    return candidates[:5]


def _best_one_sided_followups(follow_ups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    one_sided_families = {"down_only", "up_disabled_or_nearly_disabled"}
    candidates = [
        item
        for item in follow_ups
        if any(family in one_sided_families for family in (item.get("follow_up_families") or []))
    ]
    candidates.sort(
        key=lambda item: (
            -_candidate_class_priority(item),
            -_safe_float(item.get("execution_realism_score"), 0.0),
            -_safe_float(item.get("ranking_score"), 0.0),
            str(item.get("name") or ""),
        )
    )
    return candidates[:5]


def _high_conviction_followups(follow_ups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = list(follow_ups)
    ranked.sort(
        key=lambda item: (
            -_candidate_class_priority(item),
            -_safe_float(item.get("high_conviction_score"), 0.0),
            -_safe_float(item.get("execution_realism_score"), 0.0),
            -_safe_float(item.get("ranking_score"), 0.0),
            str(item.get("name") or ""),
        )
    )
    return ranked[:5]


def _capacity_stress_candidates(
    *,
    rows: list[dict[str, Any]],
    best_policy_record: dict[str, Any] | None,
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
) -> list[dict[str, Any]]:
    if not isinstance(best_policy_record, dict):
        return []
    base_policy = _policy_candidate_from_record(best_policy_record)
    if base_policy is None or not base_policy.overrides:
        return []

    base_history = best_policy_record.get("historical") if isinstance(best_policy_record.get("historical"), dict) else {}
    base_mc = best_policy_record.get("monte_carlo") if isinstance(best_policy_record.get("monte_carlo"), dict) else {}
    base_cont = best_policy_record.get("continuation") if isinstance(best_policy_record.get("continuation"), dict) else {}
    base_fills = _safe_int(base_history.get("replay_live_filled_rows"), 0)
    base_median_pnl = _safe_float(base_mc.get("median_total_pnl_usd"), 0.0)
    base_p05_arr = _safe_float(base_cont.get("p05_arr_pct"), 0.0)

    variants: list[tuple[str, int, str, PolicyCandidate]] = []
    for index, override in enumerate(order_policy_overrides(base_policy.overrides)):
        for variant_name in ("tight_quote", "loose_quote", "tight_delta", "loose_delta"):
            profile = override.profile
            if variant_name == "tight_quote":
                updated_profile = GuardrailProfile(
                    name=f"{profile.name}_tight_quote",
                    max_abs_delta=profile.max_abs_delta,
                    up_max_buy_price=(
                        round(max(0.45, min(0.55, (profile.up_max_buy_price or 0.49) - 0.01)), 2)
                        if profile.up_max_buy_price is not None
                        else None
                    ),
                    down_max_buy_price=(
                        round(max(0.45, min(0.55, (profile.down_max_buy_price or 0.49) - 0.01)), 2)
                        if profile.down_max_buy_price is not None
                        else None
                    ),
                    note=profile.note,
                )
            elif variant_name == "loose_quote":
                updated_profile = GuardrailProfile(
                    name=f"{profile.name}_loose_quote",
                    max_abs_delta=profile.max_abs_delta,
                    up_max_buy_price=(
                        round(max(0.45, min(0.55, (profile.up_max_buy_price or 0.49) + 0.01)), 2)
                        if profile.up_max_buy_price is not None
                        else None
                    ),
                    down_max_buy_price=(
                        round(max(0.45, min(0.55, (profile.down_max_buy_price or 0.49) + 0.01)), 2)
                        if profile.down_max_buy_price is not None
                        else None
                    ),
                    note=profile.note,
                )
            elif variant_name == "tight_delta":
                updated_profile = GuardrailProfile(
                    name=f"{profile.name}_tight_delta",
                    max_abs_delta=(
                        round(max(0.00001, (profile.max_abs_delta or 0.00010) * 0.90), 8)
                        if profile.max_abs_delta is not None
                        else None
                    ),
                    up_max_buy_price=profile.up_max_buy_price,
                    down_max_buy_price=profile.down_max_buy_price,
                    note=profile.note,
                )
            else:
                updated_profile = GuardrailProfile(
                    name=f"{profile.name}_loose_delta",
                    max_abs_delta=(
                        round(min(0.00100, (profile.max_abs_delta or 0.00010) * 1.10), 8)
                        if profile.max_abs_delta is not None
                        else None
                    ),
                    up_max_buy_price=profile.up_max_buy_price,
                    down_max_buy_price=profile.down_max_buy_price,
                    note=profile.note,
                )

            updated_overrides = list(base_policy.overrides)
            updated_overrides[index] = PolicyOverride(
                session_name=override.session_name,
                et_hours=override.et_hours,
                profile=updated_profile,
            )
            ordered = order_policy_overrides(updated_overrides)
            variants.append(
                (
                    variant_name,
                    index,
                    override.session_name,
                    PolicyCandidate(
                        name=_policy_name(base_policy.default_profile, ordered),
                        default_profile=base_policy.default_profile,
                        overrides=ordered,
                        note=f"capacity_stress:{variant_name}",
                    ),
                )
            )

    candidates: list[dict[str, Any]] = []
    for idx, (variant_name, override_index, session_name, policy) in enumerate(variants, start=1):
        historical = summarize_policy_history(rows, policy)
        monte_carlo = run_policy_monte_carlo(
            rows,
            policy,
            paths=max(80, int(paths // 4)),
            horizon_trades=max(len(rows), 20),
            block_size=max(1, int(block_size)),
            loss_limit_usd=loss_limit_usd,
            seed=seed + (idx * 97),
        )
        continuation = summarize_policy_arr(historical=historical, monte_carlo=monte_carlo)
        fills = _safe_int(historical.get("replay_live_filled_rows"), 0)
        candidates.append(
            {
                "name": policy.name,
                "session_name": session_name,
                "variant": variant_name,
                "override_index": override_index,
                "expected_fill_lift": fills - base_fills,
                "expected_median_pnl_delta_usd": round(
                    _safe_float(monte_carlo.get("median_total_pnl_usd"), 0.0) - base_median_pnl,
                    4,
                ),
                "expected_p05_arr_delta_pct": round(
                    _safe_float(continuation.get("p05_arr_pct"), 0.0) - base_p05_arr,
                    4,
                ),
                "evidence_band": _evidence_band(fills),
                "follow_up_families": ["capacity_stress"],
                "candidate_class": "probe_only",
                "candidate_class_reason_tags": ["requires_capacity_revalidation"],
                "research_status": "probe_only",
                "promotion_gate": "requires_capacity_revalidation",
            }
        )
    candidates.sort(
        key=lambda item: (
            _safe_float(item.get("expected_p05_arr_delta_pct"), 0.0),
            _safe_float(item.get("expected_median_pnl_delta_usd"), 0.0),
            str(item.get("name") or ""),
        ),
        reverse=True,
    )
    return candidates[:5]


def _session_name_for_hour(et_hour: int | None) -> str:
    if et_hour is None:
        return "unknown"
    if et_hour in {9, 10, 11}:
        return "open_et"
    if et_hour in {12, 13}:
        return "midday_et"
    if et_hour in {14, 15, 16}:
        return "late_et"
    return f"hour_et_{int(et_hour):02d}"


def _price_bucket(order_price: float) -> str:
    if order_price < 0.49:
        return "lt_0.49"
    if order_price <= 0.51:
        return "0.49_to_0.51"
    return "gt_0.51"


def _delta_bucket(abs_delta: float) -> str:
    if abs_delta <= 0.00005:
        return "le_0.00005"
    if abs_delta <= 0.00010:
        return "0.00005_to_0.00010"
    return "gt_0.00010"


def _loss_cluster_suppression_candidates(
    rows: list[dict[str, Any]],
    best_policy_record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    policy_payload = (best_policy_record or {}).get("policy")
    scoped_rows = rows
    if isinstance(policy_payload, dict):
        scoped_rows = [row for row in rows if _row_matches_policy_payload(row, policy_payload)]
    negative_fills = [
        row
        for row in scoped_rows
        if str(row.get("order_status") or "").strip().lower() == "live_filled"
        and _safe_float(row.get("pnl_usd"), 0.0) < 0.0
    ]
    if not negative_fills and scoped_rows is not rows:
        negative_fills = [
            row
            for row in rows
            if str(row.get("order_status") or "").strip().lower() == "live_filled"
            and _safe_float(row.get("pnl_usd"), 0.0) < 0.0
        ]
    if not negative_fills:
        return []

    clusters: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in negative_fills:
        direction = str(row.get("direction") or "UNKNOWN").upper()
        et_hour = row.get("et_hour")
        session_name = _session_name_for_hour(int(et_hour) if isinstance(et_hour, int) else None)
        order_price = _safe_float(row.get("order_price"), 0.0)
        abs_delta = _safe_float(row.get("abs_delta"), abs(_safe_float(row.get("delta"), 0.0)))
        key = (direction, session_name, _price_bucket(order_price), _delta_bucket(abs_delta))
        cluster = clusters.setdefault(
            key,
            {
                "direction": direction,
                "session_name": session_name,
                "price_bucket": key[2],
                "delta_bucket": key[3],
                "loss_rows": 0,
                "total_loss_usd": 0.0,
            },
        )
        cluster["loss_rows"] = int(cluster["loss_rows"]) + 1
        cluster["total_loss_usd"] = _safe_float(cluster["total_loss_usd"], 0.0) + _safe_float(row.get("pnl_usd"), 0.0)

    ranked = sorted(
        clusters.values(),
        key=lambda item: (
            _safe_float(item.get("total_loss_usd"), 0.0),
            -_safe_int(item.get("loss_rows"), 0),
            str(item.get("session_name") or ""),
            str(item.get("price_bucket") or ""),
            str(item.get("delta_bucket") or ""),
        ),
    )
    return [
        {
            "direction": str(cluster.get("direction") or "UNKNOWN"),
            "session_name": str(cluster.get("session_name") or "unknown"),
            "price_bucket": str(cluster.get("price_bucket") or "unknown"),
            "delta_bucket": str(cluster.get("delta_bucket") or "unknown"),
            "loss_rows": _safe_int(cluster.get("loss_rows"), 0),
            "total_loss_usd": round(_safe_float(cluster.get("total_loss_usd"), 0.0), 4),
            "suggested_action": "suppress_cluster_until_revalidated",
            "follow_up_families": ["loss_cluster_suppression"],
            "candidate_class": "suppress_cluster",
            "candidate_class_reason_tags": ["loss_cluster_detected"],
            "research_status": "suppress_cluster",
            "promotion_gate": "shadow_block_until_revalidated",
        }
        for cluster in ranked[:5]
    ]


def _loss_cluster_filters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    for cluster in clusters[:5]:
        direction = str(cluster.get("direction") or "UNKNOWN").upper()
        session_name = str(cluster.get("session_name") or "unknown")
        price_bucket = str(cluster.get("price_bucket") or "unknown")
        delta_bucket = str(cluster.get("delta_bucket") or "unknown")
        loss_rows = _safe_int(cluster.get("loss_rows"), 0)
        total_loss_usd = round(_safe_float(cluster.get("total_loss_usd"), 0.0), 4)
        filters.append(
            {
                "filter_name": "_".join(
                    (
                        direction.lower(),
                        session_name,
                        price_bucket,
                        delta_bucket,
                    )
                ),
                "direction": direction,
                "session_name": session_name,
                "price_bucket": price_bucket,
                "delta_bucket": delta_bucket,
                "loss_rows": loss_rows,
                "total_loss_usd": total_loss_usd,
                "severity": "high" if loss_rows >= 2 or total_loss_usd <= -10.0 else "medium",
                "filter_action": "shadow_block_until_revalidated",
                "revalidation_gate": "requires_fresh_positive_cluster_and_capacity_agreement",
                "research_status": "research_only",
            }
        )
    return filters


def _is_live_filled_row(row: dict[str, Any]) -> bool:
    status = str(row.get("order_status") or "").strip().lower()
    return status == "live_filled" or (status.startswith("live_") and _safe_float(row.get("trade_size_usd"), 0.0) > 0.0)


def _policy_candidate_from_followup_payload(
    item: dict[str, Any],
    *,
    current_live_profile: GuardrailProfile,
) -> PolicyCandidate:
    session_policy = item.get("session_policy") if isinstance(item.get("session_policy"), list) else []
    if not session_policy:
        return PolicyCandidate(
            name=str(item.get("name") or "candidate_policy"),
            default_profile=GuardrailProfile(
                name=str(item.get("name") or current_live_profile.name),
                max_abs_delta=(
                    _safe_float(item.get("max_abs_delta"), 0.0)
                    if item.get("max_abs_delta") is not None
                    else current_live_profile.max_abs_delta
                ),
                up_max_buy_price=(
                    _safe_float(item.get("up_max_buy_price"), 0.0)
                    if item.get("up_max_buy_price") is not None
                    else current_live_profile.up_max_buy_price
                ),
                down_max_buy_price=(
                    _safe_float(item.get("down_max_buy_price"), 0.0)
                    if item.get("down_max_buy_price") is not None
                    else current_live_profile.down_max_buy_price
                ),
                note="reconstructed from follow-up payload",
            ),
        )

    overrides: list[PolicyOverride] = []
    for index, session in enumerate(session_policy, start=1):
        if not isinstance(session, dict):
            continue
        overrides.append(
            PolicyOverride(
                session_name=str(session.get("name") or f"session_{index}"),
                et_hours=tuple(
                    int(hour)
                    for hour in (session.get("et_hours") or [])
                    if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
                ),
                profile=GuardrailProfile(
                    name=f"{item.get('name', 'candidate_policy')}_override_{index}",
                    max_abs_delta=(
                        _safe_float(session.get("max_abs_delta"), 0.0)
                        if session.get("max_abs_delta") is not None
                        else current_live_profile.max_abs_delta
                    ),
                    up_max_buy_price=(
                        _safe_float(session.get("up_max_buy_price"), 0.0)
                        if session.get("up_max_buy_price") is not None
                        else current_live_profile.up_max_buy_price
                    ),
                    down_max_buy_price=(
                        _safe_float(session.get("down_max_buy_price"), 0.0)
                        if session.get("down_max_buy_price") is not None
                        else current_live_profile.down_max_buy_price
                    ),
                    note="reconstructed from follow-up payload",
                ),
            )
        )
    return PolicyCandidate(
        name=str(item.get("name") or "candidate_policy"),
        default_profile=current_live_profile,
        overrides=order_policy_overrides(overrides),
    )


def _size_stress_assessment(
    rows: list[dict[str, Any]],
    item: dict[str, Any],
    *,
    current_live_profile: GuardrailProfile,
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
) -> dict[str, Any]:
    policy = _policy_candidate_from_followup_payload(item, current_live_profile=current_live_profile)
    history = summarize_policy_history(rows, policy)
    horizon_trades = max(len(rows), 12)
    matched_fills = [row for row in rows if row_matches_policy(row, policy) and _is_live_filled_row(row)]
    live_fills = max(1, _safe_int(history.get("replay_live_filled_rows"), 0))
    reference_trade_size_usd = _safe_float(history.get("trade_notional_usd"), 0.0) / float(live_fills)
    if reference_trade_size_usd <= 0.0:
        reference_trade_size_usd = max(
            5.0,
            sum(max(0.0, _safe_float(row.get("trade_size_usd"), 0.0)) for row in matched_fills)
            / float(len(matched_fills))
            if matched_fills
            else 5.0,
        )
    sweeps: list[dict[str, Any]] = []
    size_paths = max(40, min(180, int(paths)))
    for trade_size_usd in FRONTIER_SIZE_TARGETS:
        fill_retention_ratio = _estimate_fill_retention_ratio(
            matched_fills,
            target_trade_size_usd=trade_size_usd,
            fallback_trade_size_usd=reference_trade_size_usd,
        )
        entries = [
            {
                "pnl_usd": (
                    _safe_float(row.get("realized_pnl_usd"), 0.0)
                    * ((trade_size_usd / reference_trade_size_usd) if reference_trade_size_usd > 0 else 1.0)
                )
                if row_matches_policy(row, policy)
                else 0.0,
                "activation_probability": fill_retention_ratio if row_matches_policy(row, policy) else 0.0,
                "execution_cost_usd": 0.0,
            }
            for row in rows
        ]
        stress_monte_carlo = _run_monte_carlo_from_entries(
            entries,
            paths=size_paths,
            horizon_trades=horizon_trades,
            block_size=max(1, int(block_size)),
            loss_limit_usd=float(loss_limit_usd),
            seed_material=f"{seed}:{policy.name}:{trade_size_usd:.2f}",
        )
        stress_continuation = summarize_policy_arr(
            historical=history,
            monte_carlo=stress_monte_carlo,
            avg_trade_size_usd_override=trade_size_usd,
        )
        sweeps.append(
            _round_metrics(
                {
                    "trade_size_usd": trade_size_usd,
                    "expected_fill_retention_ratio": fill_retention_ratio,
                    "expected_profit_probability": _safe_float(stress_monte_carlo.get("profit_probability"), 0.0),
                    "expected_loss_limit_hit_probability": _safe_float(
                        stress_monte_carlo.get("loss_limit_hit_probability"),
                        0.0,
                    ),
                    "expected_median_arr_pct": _safe_float(stress_continuation.get("median_arr_pct"), 0.0),
                    "expected_p05_arr_pct": _safe_float(stress_continuation.get("p05_arr_pct"), 0.0),
                }
            )
        )
    shadow_trade_sizes = [
        float(sweep["trade_size_usd"])
        for sweep in sweeps
        if _safe_float(sweep.get("expected_p05_arr_pct"), 0.0) > 0.0
        and _safe_float(sweep.get("expected_profit_probability"), 0.0) >= 0.5
    ]
    max_shadow_trade_size = max(shadow_trade_sizes) if shadow_trade_sizes else 0.0
    size_readiness_score = round(
        (max_shadow_trade_size / 50.0)
        + (1.0 if max_shadow_trade_size >= 50.0 else 0.0)
        + (0.5 if max_shadow_trade_size >= 100.0 else 0.0)
        + min(1.0, _safe_float(item.get("execution_realism_score"), 0.0))
        + 0.5 * _evidence_weight(str(item.get("evidence_band") or "exploratory")),
        4,
    )
    if max_shadow_trade_size >= 100.0:
        readiness_status = "shadow_100_plus_candidate"
    elif max_shadow_trade_size >= 50.0:
        readiness_status = "shadow_50_plus_candidate"
    elif max_shadow_trade_size >= 20.0:
        readiness_status = "shadow_stage_path_only"
    elif max_shadow_trade_size >= 10.0:
        readiness_status = "shadow_stage_1_only"
    else:
        readiness_status = "needs_more_size_evidence"
    return {
        "size_sweep_reference_trade_size_usd": round(reference_trade_size_usd, 4),
        "shadow_trade_sizes_usd": shadow_trade_sizes,
        "max_shadow_trade_size_usd": max_shadow_trade_size,
        "size_stress_sweeps": sweeps,
        "size_readiness_score": size_readiness_score,
        "size_readiness_status": readiness_status,
        "follow_up_families": sorted(
            {
                str(tag)
                for tag in ((item.get("follow_up_families") or []) + ["capacity_stress"])
                if str(tag)
            }
        ),
        "candidate_class": "probe_only",
        "candidate_class_reason_tags": ["requires_capacity_revalidation"],
        "research_status": "probe_only",
        "promotion_gate": "requires_capacity_revalidation",
    }


def _size_ready_followups(
    rows: list[dict[str, Any]],
    follow_ups: list[dict[str, Any]],
    *,
    current_live_profile: GuardrailProfile,
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
) -> list[dict[str, Any]]:
    assessed: list[dict[str, Any]] = []
    for index, item in enumerate(follow_ups):
        payload = dict(item)
        payload.update(
            _size_stress_assessment(
                rows,
                item,
                current_live_profile=current_live_profile,
                paths=paths,
                block_size=block_size,
                loss_limit_usd=loss_limit_usd,
                seed=seed + index + 1,
            )
        )
        assessed.append(payload)
    candidates = [item for item in assessed if item.get("shadow_trade_sizes_usd")] or assessed
    candidates.sort(
        key=lambda item: (
            -_candidate_class_priority(item),
            -_safe_float(item.get("max_shadow_trade_size_usd"), 0.0),
            -_safe_float(item.get("size_readiness_score"), 0.0),
            -_safe_float(item.get("high_conviction_score"), 0.0),
            -_safe_float(item.get("ranking_score"), 0.0),
            str(item.get("name") or ""),
        )
    )
    return candidates[:5]


def _evaluate_policies(
    *,
    rows: list[dict[str, Any]],
    policies: list[PolicyCandidate],
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
    min_replay_fills: int,
) -> list[dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    for policy in policies:
        historical = summarize_policy_history(rows, policy)
        if _safe_int(historical.get("replay_live_filled_rows"), 0) < min_replay_fills:
            continue
        monte_carlo = run_policy_monte_carlo(
            rows,
            policy,
            paths=paths,
            horizon_trades=max(len(rows), 20),
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed=seed,
        )
        continuation = summarize_policy_arr(historical=historical, monte_carlo=monte_carlo)
        evaluated.append(
            {
                "policy": {
                    "name": policy.name,
                    "default_profile": asdict(policy.default_profile),
                    "overrides": [
                        {
                            "session_name": override.session_name,
                            "et_hours": list(override.et_hours),
                            "profile": asdict(override.profile),
                        }
                        for override in policy.overrides
                    ],
                    "note": policy.note,
                },
                "historical": historical,
                "monte_carlo": monte_carlo,
                "continuation": continuation,
            }
        )
    return evaluated


def build_summary(
    *,
    rows: list[dict[str, Any]],
    db_path: Path,
    current_live_profile: GuardrailProfile,
    runtime_recommended_profile: GuardrailProfile,
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
    min_replay_fills: int,
    min_session_rows: int,
    max_session_overrides: int,
    top_single_overrides_per_session: int,
    max_composed_candidates: int,
) -> dict[str, Any]:
    enriched_rows = enrich_rows(rows)
    initial_candidates = build_policy_candidates(
        enriched_rows,
        current_live_profile=current_live_profile,
        min_session_rows=min_session_rows,
    )
    evaluated = _evaluate_policies(
        rows=enriched_rows,
        policies=initial_candidates,
        paths=paths,
        block_size=block_size,
        loss_limit_usd=loss_limit_usd,
        seed=seed,
        min_replay_fills=min_replay_fills,
    )
    evaluated, current_policy = _score_candidates(evaluated)

    composed_candidates = _composed_policy_candidates(
        evaluated=evaluated,
        current_live_profile=current_live_profile,
        max_session_overrides=max_session_overrides,
        top_single_overrides_per_session=top_single_overrides_per_session,
        max_composed_candidates=max_composed_candidates,
    )
    if composed_candidates:
        evaluated.extend(
            _evaluate_policies(
                rows=enriched_rows,
                policies=composed_candidates,
                paths=paths,
                block_size=block_size,
                loss_limit_usd=loss_limit_usd,
                seed=seed,
                min_replay_fills=min_replay_fills,
            )
        )
        evaluated, current_policy = _score_candidates(evaluated)

    ranked_best_policy = evaluated[0] if evaluated else None
    active_profile_summary = (
        _candidate_runtime_package(current_policy)
        if current_policy is not None
        else _profile_runtime_package(current_live_profile)
    )
    hold_current_candidate = _hold_current_candidate(active_profile_summary)
    all_follow_ups = _follow_up_candidates_with_tradeoffs(
        evaluated,
        active_candidate=active_profile_summary,
        limit=None,
    )
    follow_up_by_name = {str(item.get("name") or ""): item for item in all_follow_ups}
    for candidate in evaluated:
        policy_name = str(((candidate.get("policy") or {}).get("name")) or "")
        meta = follow_up_by_name.get(policy_name)
        if not meta:
            continue
        candidate["candidate_class"] = meta.get("candidate_class")
        candidate["candidate_class_reason_tags"] = meta.get("candidate_class_reason_tags")
        candidate["follow_up_families"] = meta.get("follow_up_families")

    ranked_best_candidate_summary = (
        _candidate_runtime_package(ranked_best_policy)
        if ranked_best_policy is not None
        else _profile_runtime_package(current_live_profile)
    )
    ranked_best_candidate_summary = follow_up_by_name.get(
        ranked_best_candidate_summary.get("name", ""),
        ranked_best_candidate_summary,
    )
    best_promote_ready_candidate = _best_candidate_by_class(all_follow_ups, "promote")
    best_probe_only_candidate = _best_candidate_by_class(all_follow_ups, "probe_only")
    best_policy = current_policy
    if best_promote_ready_candidate is not None:
        best_policy = next(
            (
                candidate
                for candidate in evaluated
                if str(((candidate.get("policy") or {}).get("name")) or "") == str(best_promote_ready_candidate.get("name") or "")
            ),
            current_policy or ranked_best_policy,
        )

    best_vs_current = None
    if best_policy is not None and current_policy is not None:
        best_vs_current = _round_metrics(
            {
                "best_policy_name": best_policy["policy"]["name"],
                "current_policy_name": current_policy["policy"]["name"],
                "historical_arr_pct_delta": _safe_float(best_policy["continuation"].get("historical_arr_pct"), 0.0)
                - _safe_float(current_policy["continuation"].get("historical_arr_pct"), 0.0),
                "median_arr_pct_delta": _safe_float(best_policy["continuation"].get("median_arr_pct"), 0.0)
                - _safe_float(current_policy["continuation"].get("median_arr_pct"), 0.0),
                "p05_arr_pct_delta": _safe_float(best_policy["continuation"].get("p05_arr_pct"), 0.0)
                - _safe_float(current_policy["continuation"].get("p05_arr_pct"), 0.0),
                "replay_pnl_delta_usd": _safe_float(best_policy["historical"].get("replay_live_filled_pnl_usd"), 0.0)
                - _safe_float(current_policy["historical"].get("replay_live_filled_pnl_usd"), 0.0),
                "median_pnl_delta_usd": _safe_float(best_policy["monte_carlo"].get("median_total_pnl_usd"), 0.0)
                - _safe_float(current_policy["monte_carlo"].get("median_total_pnl_usd"), 0.0),
                "profit_probability_delta": _safe_float(best_policy["monte_carlo"].get("profit_probability"), 0.0)
                - _safe_float(current_policy["monte_carlo"].get("profit_probability"), 0.0),
                "p95_drawdown_delta_usd": _safe_float(best_policy["monte_carlo"].get("p95_max_drawdown_usd"), 0.0)
                - _safe_float(current_policy["monte_carlo"].get("p95_max_drawdown_usd"), 0.0),
                "fill_lift": _safe_int(best_policy["historical"].get("replay_live_filled_rows"), 0)
                - _safe_int(current_policy["historical"].get("replay_live_filled_rows"), 0),
            }
        )
    best_candidate_summary = dict(best_promote_ready_candidate or hold_current_candidate)
    follow_ups = all_follow_ups[:5]
    loss_clusters = _loss_cluster_suppression_candidates(
        enriched_rows,
        best_policy,
    )
    candidate_class_breakdown = _class_breakdown(all_follow_ups + loss_clusters + [hold_current_candidate])
    last_improvement_at = _last_improvement_for_policy(enriched_rows, best_policy)
    hours_since_last_improvement = (
        round((_now_utc() - last_improvement_at).total_seconds() / 3600.0, 4)
        if last_improvement_at is not None
        else None
    )

    return {
        "generated_at": _now_utc().isoformat(),
        "db_path": str(db_path),
        "input": {
            "observed_window_rows": len(enriched_rows),
            "live_filled_rows": sum(1 for row in enriched_rows if row.get("order_status") == "live_filled"),
            "observed_pnl_usd": round(
                sum(_safe_float(row.get("pnl_usd"), 0.0) for row in enriched_rows if row.get("order_status") == "live_filled"),
                4,
            ),
            "generated_policies": len(initial_candidates) + len(composed_candidates),
            "generated_initial_policies": len(initial_candidates),
            "generated_composed_policies": len(composed_candidates),
            "simulated_policies": len(evaluated),
        },
        "simulation": {
            "paths": int(paths),
            "horizon_trades": len(enriched_rows),
            "block_size": int(block_size),
            "loss_limit_usd": round(loss_limit_usd, 4),
            "seed": int(seed),
            "min_replay_fills": int(min_replay_fills),
            "min_session_rows": int(min_session_rows),
            "max_session_overrides": int(max_session_overrides),
            "top_single_overrides_per_session": int(top_single_overrides_per_session),
            "max_composed_candidates": int(max_composed_candidates),
        },
        "current_live_profile": asdict(current_live_profile),
        "runtime_recommended_profile": asdict(runtime_recommended_profile),
        "candidates": evaluated,
        "active_profile": {
            "name": current_live_profile.name,
            "session_name": "any",
            "et_hours": [],
            "max_abs_delta": current_live_profile.max_abs_delta,
            "up_max_buy_price": current_live_profile.up_max_buy_price,
            "down_max_buy_price": current_live_profile.down_max_buy_price,
        },
        "best_candidate": best_candidate_summary,
        "best_ranked_candidate": ranked_best_candidate_summary,
        "best_promote_ready_candidate": best_promote_ready_candidate,
        "best_probe_only_candidate": best_probe_only_candidate,
        "hold_current_candidate": hold_current_candidate,
        "deployment_recommendation": "promote" if best_promote_ready_candidate is not None else "hold_current",
        "candidate_class_breakdown": candidate_class_breakdown,
        "arr_delta_vs_active_pct": _safe_float((best_vs_current or {}).get("median_arr_pct_delta"), 0.0),
        "p05_arr_delta_vs_active_pct": _safe_float((best_vs_current or {}).get("p05_arr_pct_delta"), 0.0),
        "validation_live_filled_rows": _safe_int(best_candidate_summary.get("validation_live_filled_rows"), 0),
        "generalization_ratio": _safe_float(best_candidate_summary.get("generalization_ratio"), 0.0),
        "evidence_band": str(best_candidate_summary.get("evidence_band") or "exploratory"),
        "last_improvement_at": (
            last_improvement_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if last_improvement_at is not None
            else None
        ),
        "hours_since_last_improvement": hours_since_last_improvement,
        "current_policy": current_policy,
        "best_policy": best_policy,
        "best_ranked_policy": ranked_best_policy,
        "recommended_session_policy": _recommended_session_policy(best_policy),
        "follow_up_candidates": follow_ups,
        "best_live_followups": _best_live_followups(follow_ups),
        "best_one_sided_followups": _best_one_sided_followups(follow_ups),
        "high_conviction_followups": _high_conviction_followups(follow_ups),
        "size_ready_followups": _size_ready_followups(
            enriched_rows,
            follow_ups,
            current_live_profile=current_live_profile,
            paths=max(1, int(paths)),
            block_size=max(1, int(block_size)),
            loss_limit_usd=max(0.0, float(loss_limit_usd)),
            seed=int(seed),
        ),
        "loss_cluster_suppression_candidates": loss_clusters,
        "loss_cluster_filters": _loss_cluster_filters(loss_clusters),
        "capacity_stress_candidates": _capacity_stress_candidates(
            rows=enriched_rows,
            best_policy_record=best_policy,
            paths=max(1, int(paths)),
            block_size=max(1, int(block_size)),
            loss_limit_usd=max(0.0, float(loss_limit_usd)),
            seed=int(seed),
        ),
        "best_vs_current": best_vs_current,
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    best = summary.get("best_policy") or {}
    best_policy = best.get("policy") or {}
    recommended_policy = summary.get("recommended_session_policy") or []
    comparison = summary.get("best_vs_current") or {}
    high_conviction = summary.get("high_conviction_followups") or []
    size_ready = summary.get("size_ready_followups") or []
    loss_filters = summary.get("loss_cluster_filters") or []
    lines = [
        "# BTC5 Regime Policy Lab",
        "",
        "This lab searches bounded session overrides on top of the live BTC5 global profile. It is research-only and does not auto-promote live config.",
        "",
        f"- Generated at: `{summary.get('generated_at')}`",
        f"- Observed decision rows: `{summary['input']['observed_window_rows']}`",
        f"- Observed live-filled rows: `{summary['input']['live_filled_rows']}`",
        f"- Observed realized PnL: `{summary['input']['observed_pnl_usd']:.4f}` USD",
        f"- Policies generated: `{summary['input']['generated_policies']}`",
        f"- Composed policies generated: `{summary['input'].get('generated_composed_policies', 0)}`",
        f"- Policies simulated: `{summary['input']['simulated_policies']}`",
        "",
        "## Best Policy",
        "",
        f"- Name: `{best_policy.get('name', 'none')}`",
        f"- Live policy score: `{_safe_float((best.get('scoring') or {}).get('live_policy_score'), 0.0):.2f}`",
        f"- Median continuation ARR: `{_safe_float((best.get('continuation') or {}).get('median_arr_pct'), 0.0):.2f}%`",
        f"- P05 continuation ARR: `{_safe_float((best.get('continuation') or {}).get('p05_arr_pct'), 0.0):.2f}%`",
        f"- Replay PnL: `{_safe_float((best.get('historical') or {}).get('replay_live_filled_pnl_usd'), 0.0):.4f}` USD",
        f"- Replay fills: `{_safe_int((best.get('historical') or {}).get('replay_live_filled_rows'), 0)}`",
        "",
        "## Best vs Current",
        "",
        f"- Median ARR delta: `{_safe_float(comparison.get('median_arr_pct_delta'), 0.0):.2f}` percentage points",
        f"- P05 ARR delta: `{_safe_float(comparison.get('p05_arr_pct_delta'), 0.0):.2f}` percentage points",
        f"- Replay PnL delta: `{_safe_float(comparison.get('replay_pnl_delta_usd'), 0.0):.4f}` USD",
        f"- Median PnL delta: `{_safe_float(comparison.get('median_pnl_delta_usd'), 0.0):.4f}` USD",
        f"- Profit-probability delta: `{_safe_float(comparison.get('profit_probability_delta'), 0.0):.4f}`",
        f"- P95 drawdown delta: `{_safe_float(comparison.get('p95_drawdown_delta_usd'), 0.0):.4f}` USD",
        f"- Fill lift: `{_safe_int(comparison.get('fill_lift'), 0)}`",
        "",
        "## Recommended Session Policy",
        "",
        f"- Runtime-ready policy records: `{len(recommended_policy)}`",
        "",
        "```json",
        json.dumps(recommended_policy, indent=2),
        "```",
        "",
    ]
    if high_conviction:
        lines.extend(["## High Conviction Follow-Ups", ""])
        for item in high_conviction[:3]:
            lines.append(
                f"- `{item.get('name')}` "
                + f"(score `{_safe_float(item.get('high_conviction_score'), 0.0):.2f}`, "
                + f"tags `{', '.join(item.get('frontier_focus_tags') or [])}`)"
            )
        lines.append("")
    if size_ready:
        lines.extend(["## Size-Ready Follow-Ups", ""])
        for item in size_ready[:3]:
            lines.append(
                f"- `{item.get('name')}` "
                + f"(status `{item.get('size_readiness_status')}`, "
                + f"shadow max `${_safe_float(item.get('max_shadow_trade_size_usd'), 0.0):.0f}`)"
            )
        lines.append("")
    if loss_filters:
        lines.extend(["## Loss Cluster Filters", ""])
        for item in loss_filters[:3]:
            lines.append(
                f"- `{item.get('filter_name')}` "
                + f"({item.get('severity')} severity, loss `{_safe_float(item.get('total_loss_usd'), 0.0):.4f}` USD)"
            )
        lines.append("")
    lines.extend(
        [
            "## Top Policies",
            "",
            "| Rank | Policy | Live Score | Median ARR | P05 ARR | Replay PnL | Replay Fills | P95 Drawdown |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for index, candidate in enumerate(summary.get("candidates") or [], start=1):
        policy = candidate.get("policy") or {}
        scoring = candidate.get("scoring") or {}
        continuation = candidate.get("continuation") or {}
        historical = candidate.get("historical") or {}
        monte_carlo = candidate.get("monte_carlo") or {}
        lines.append(
            "| "
            + f"{index} | {policy.get('name')} | "
            + f"{_safe_float(scoring.get('live_policy_score'), 0.0):.2f} | "
            + f"{_safe_float(continuation.get('median_arr_pct'), 0.0):.2f}% | "
            + f"{_safe_float(continuation.get('p05_arr_pct'), 0.0):.2f}% | "
            + f"{_safe_float(historical.get('replay_live_filled_pnl_usd'), 0.0):.4f} | "
            + f"{_safe_int(historical.get('replay_live_filled_rows'), 0)} | "
            + f"{_safe_float(monte_carlo.get('p95_max_drawdown_usd'), 0.0):.4f} |"
        )
    return "\n".join(lines) + "\n"


def _write_outputs(output_dir: Path, *, summary: dict[str, Any], write_latest: bool) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    md_path.write_text(_render_markdown(summary))
    if write_latest:
        shutil.copy2(json_path, output_dir.parent / "btc5_regime_policy_lab_latest.json")
        shutil.copy2(md_path, output_dir.parent / "btc5_regime_policy_lab_latest.md")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--strategy-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--override-env", type=Path, default=DEFAULT_OVERRIDE_ENV)
    parser.add_argument("--runtime-truth", type=Path, default=DEFAULT_RUNTIME_TRUTH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--loss-limit-usd", type=float, default=DEFAULT_LOSS_LIMIT_USD)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-replay-fills", type=int, default=12)
    parser.add_argument("--min-session-rows", type=int, default=6)
    parser.add_argument("--max-session-overrides", type=int, default=2)
    parser.add_argument("--top-single-overrides-per-session", type=int, default=2)
    parser.add_argument("--max-composed-candidates", type=int, default=64)
    parser.add_argument("--include-archive-csvs", action="store_true")
    parser.add_argument("--archive-glob", default=DEFAULT_ARCHIVE_GLOB)
    parser.add_argument("--refresh-remote", action="store_true")
    parser.add_argument("--remote-cache-json", type=Path, default=DEFAULT_REMOTE_ROWS_JSON)
    parser.add_argument("--write-latest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_truth = _load_runtime_truth(args.runtime_truth)
    merged_env = _merged_strategy_env(args.strategy_env, args.override_env)
    current_live_profile = _profile_from_env("current_live_profile", merged_env)
    runtime_recommended_profile = _live_profile_from_runtime_truth(runtime_truth)
    rows, _ = assemble_observed_rows(
        db_path=args.db_path,
        include_archive_csvs=bool(args.include_archive_csvs),
        archive_glob=str(args.archive_glob),
        refresh_remote=bool(args.refresh_remote),
        remote_cache_json=args.remote_cache_json,
    )
    summary = build_summary(
        rows=rows,
        db_path=args.db_path,
        current_live_profile=current_live_profile,
        runtime_recommended_profile=runtime_recommended_profile,
        paths=max(1, int(args.paths)),
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=max(0.0, float(args.loss_limit_usd)),
        seed=int(args.seed),
        min_replay_fills=max(1, int(args.min_replay_fills)),
        min_session_rows=max(1, int(args.min_session_rows)),
        max_session_overrides=max(1, int(args.max_session_overrides)),
        top_single_overrides_per_session=max(1, int(args.top_single_overrides_per_session)),
        max_composed_candidates=max(0, int(args.max_composed_candidates)),
    )
    json_path, md_path = _write_outputs(
        args.output_dir,
        summary=summary,
        write_latest=bool(args.write_latest),
    )
    print(json.dumps({"summary_json": str(json_path), "report_md": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
