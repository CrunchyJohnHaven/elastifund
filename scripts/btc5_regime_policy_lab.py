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
    _load_runtime_truth,
    _live_profile_from_runtime_truth,
    _percentile,
    _round_metrics,
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
            for up_cap in (0.47, 0.48, 0.49, 0.50, 0.51):
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


def summarize_policy_arr(*, historical: dict[str, Any], monte_carlo: dict[str, Any]) -> dict[str, Any]:
    replay_window_rows = max(0, _safe_int(historical.get("replay_window_rows")))
    replay_live_filled_rows = max(0, _safe_int(historical.get("replay_live_filled_rows")))
    trade_notional_usd = max(0.0, _safe_float(historical.get("trade_notional_usd"), 0.0))
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
        candidate["scoring"] = _round_metrics(
            {
                "metric_name": "live_policy_score",
                "replay_pnl_ratio_vs_current": replay_pnl_ratio,
                "fill_ratio_vs_current": fill_ratio,
                "profit_probability": profit_probability,
                "live_policy_score": median_arr_pct
                * max(0.25, min(1.0, replay_pnl_ratio))
                * max(0.25, min(1.0, fill_ratio))
                * max(0.5, profit_probability),
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
    }


def _follow_up_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    packages = [_candidate_runtime_package(candidate) for candidate in candidates]
    packages.sort(
        key=lambda item: (
            -_safe_float(item.get("ranking_score"), 0.0),
            str(item.get("name") or ""),
        )
    )
    return packages[:5]


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

    best_policy = evaluated[0] if evaluated else None
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
    active_profile_summary = _candidate_runtime_package(current_policy or {})
    best_candidate_summary = _candidate_runtime_package(best_policy or {})

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
            "name": active_profile_summary.get("name", current_live_profile.name),
            "session_name": "any",
            "et_hours": [],
            "max_abs_delta": current_live_profile.max_abs_delta,
            "up_max_buy_price": current_live_profile.up_max_buy_price,
            "down_max_buy_price": current_live_profile.down_max_buy_price,
        },
        "best_candidate": best_candidate_summary,
        "arr_delta_vs_active_pct": _safe_float((best_vs_current or {}).get("median_arr_pct_delta"), 0.0),
        "p05_arr_delta_vs_active_pct": _safe_float((best_vs_current or {}).get("p05_arr_pct_delta"), 0.0),
        "validation_live_filled_rows": _safe_int(best_candidate_summary.get("validation_live_filled_rows"), 0),
        "generalization_ratio": _safe_float(best_candidate_summary.get("generalization_ratio"), 0.0),
        "evidence_band": str(best_candidate_summary.get("evidence_band") or "exploratory"),
        "current_policy": current_policy,
        "best_policy": best_policy,
        "recommended_session_policy": _recommended_session_policy(best_policy),
        "follow_up_candidates": _follow_up_candidates(evaluated),
        "best_vs_current": best_vs_current,
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    best = summary.get("best_policy") or {}
    best_policy = best.get("policy") or {}
    recommended_policy = summary.get("recommended_session_policy") or []
    comparison = summary.get("best_vs_current") or {}
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
        "## Top Policies",
        "",
        "| Rank | Policy | Live Score | Median ARR | P05 ARR | Replay PnL | Replay Fills | P95 Drawdown |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
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
