#!/usr/bin/env python3
"""Generate BTC5 regime hypotheses and validate them with walk-forward bootstrap."""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo import (  # noqa: E402
    DEFAULT_ARCHIVE_GLOB,
    DEFAULT_DOWN_MAX,
    DEFAULT_LOSS_LIMIT_USD,
    DEFAULT_MAX_ABS_DELTA,
    DEFAULT_REMOTE_ROWS_JSON,
    DEFAULT_UP_MAX,
    REPORTS_DIR,
    GuardrailProfile,
    _estimate_fill_retention_ratio,
    _percentile,
    _round_metrics,
    _run_monte_carlo_from_entries,
    _safe_float,
    _safe_int,
    assemble_observed_rows,
    summarize_continuation_arr,
)


DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BASE_ENV = Path("config/btc5_strategy.env")
DEFAULT_OVERRIDE_ENV = Path("state/btc5_autoresearch.env")
DEFAULT_REPORT_DIR = Path("reports/btc5_hypothesis_lab")
ET_ZONE = ZoneInfo("America/New_York")
SESSION_FILTERS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("any", tuple()),
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
class HypothesisSpec:
    name: str
    direction: str | None
    max_abs_delta: float | None
    up_max_buy_price: float | None
    down_max_buy_price: float | None
    et_hours: tuple[int, ...] = tuple()
    session_name: str = "any"
    note: str = ""


@dataclass(frozen=True)
class WalkForwardSplit:
    index: int
    train_end: int
    validate_end: int


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


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _row_observed_at_utc(row: dict[str, Any]) -> datetime | None:
    window_start_ts = _safe_int(row.get("window_start_ts"), 0)
    if window_start_ts > 0:
        return datetime.fromtimestamp(window_start_ts, tz=timezone.utc)
    observed = _parse_iso(row.get("updated_at"))
    if observed is None:
        return None
    if observed.tzinfo is None:
        return observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc)


def _window_dt_et(row: dict[str, Any]) -> datetime | None:
    window_start_ts = _safe_int(row.get("window_start_ts"), 0)
    if window_start_ts > 0:
        return datetime.fromtimestamp(window_start_ts, tz=timezone.utc).astimezone(ET_ZONE)
    updated_at = _parse_iso(row.get("updated_at"))
    if updated_at is not None:
        return updated_at.astimezone(ET_ZONE)
    return None


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


def enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        dt_et = _window_dt_et(row)
        item = dict(row)
        item["et_hour"] = dt_et.hour if dt_et is not None else None
        item["et_date"] = dt_et.date().isoformat() if dt_et is not None else None
        item["priced_observation"] = _safe_float(row.get("order_price"), 0.0) > 0.0
        enriched.append(item)
    return enriched


def priced_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in enrich_rows(rows) if bool(row.get("priced_observation"))]


def row_matches_hypothesis(row: dict[str, Any], spec: HypothesisSpec) -> bool:
    direction = str(row.get("direction") or "").strip().upper()
    order_price = _safe_float(row.get("order_price"), 0.0)
    abs_delta = _safe_float(row.get("abs_delta"), abs(_safe_float(row.get("delta"), 0.0)))
    et_hour = row.get("et_hour")

    if spec.direction is not None and direction != spec.direction:
        return False
    if spec.max_abs_delta is not None and abs_delta > spec.max_abs_delta:
        return False
    if direction == "UP" and spec.up_max_buy_price is not None and order_price > spec.up_max_buy_price:
        return False
    if direction == "DOWN" and spec.down_max_buy_price is not None and order_price > spec.down_max_buy_price:
        return False
    if spec.et_hours and et_hour not in spec.et_hours:
        return False
    return True


def summarize_hypothesis_history(rows: list[dict[str, Any]], spec: HypothesisSpec) -> dict[str, Any]:
    matched = [row for row in rows if row_matches_hypothesis(row, spec)]
    baseline_filled = [row for row in rows if row.get("order_status") == "live_filled"]
    matched_filled = [row for row in matched if row.get("order_status") == "live_filled"]
    matched_attempted = [row for row in matched if str(row.get("order_status") or "").startswith("live_")]
    wins = sum(1 for row in matched_filled if _safe_float(row.get("pnl_usd"), 0.0) > 0)
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
            "attempt_fill_rate": (len(matched_filled) / len(matched_attempted)) if matched_attempted else 0.0,
            "replay_live_filled_pnl_usd": sum(_safe_float(row.get("pnl_usd"), 0.0) for row in matched_filled),
            "avg_pnl_usd": (
                sum(_safe_float(row.get("pnl_usd"), 0.0) for row in matched_filled) / len(matched_filled)
                if matched_filled
                else 0.0
            ),
            "win_rate": (wins / len(matched_filled)) if matched_filled else 0.0,
            "trade_notional_usd": total_notional,
        }
    )


def _block_bootstrap_series(
    values: list[float],
    *,
    horizon_windows: int,
    block_size: int,
    rng: random.Random,
) -> list[float]:
    if not values or horizon_windows <= 0:
        return []
    horizon = max(1, int(horizon_windows))
    block = max(1, min(int(block_size), len(values)))
    if len(values) == 1:
        return [values[0]] * horizon
    last_start = max(0, len(values) - block)
    sample: list[float] = []
    while len(sample) < horizon:
        start = rng.randint(0, last_start)
        sample.extend(values[start : start + block])
    return sample[:horizon]


def run_hypothesis_bootstrap(
    rows: list[dict[str, Any]],
    spec: HypothesisSpec,
    *,
    paths: int,
    horizon_windows: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
) -> dict[str, Any]:
    series = [
        _safe_float(row.get("realized_pnl_usd"), 0.0) if row_matches_hypothesis(row, spec) else 0.0
        for row in rows
    ]
    non_zero = [value for value in series if abs(value) > 1e-12]
    if not series:
        return {
            "paths": int(paths),
            "horizon_trades": int(horizon_windows),
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

    rng = random.Random(f"{seed}:{asdict(spec)}")
    total_pnls: list[float] = []
    max_drawdowns: list[float] = []
    active_counts: list[int] = []
    loss_hits = 0

    for _ in range(max(1, int(paths))):
        path = _block_bootstrap_series(
            series,
            horizon_windows=max(1, int(horizon_windows)),
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
            "horizon_trades": int(horizon_windows),
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


def build_walk_forward_splits(
    rows: list[dict[str, Any]],
    *,
    min_train_rows: int,
    min_validate_rows: int,
) -> list[WalkForwardSplit]:
    total = len(rows)
    if total < (min_train_rows + min_validate_rows):
        return []
    anchors = sorted(
        {
            max(min_train_rows, int(total * ratio))
            for ratio in (0.45, 0.60, 0.75)
            if max(min_train_rows, int(total * ratio)) < total
        }
    )
    splits: list[WalkForwardSplit] = []
    for index, train_end in enumerate(anchors, start=1):
        validate_end = anchors[index] if index < len(anchors) else total
        if train_end < min_train_rows:
            continue
        if (validate_end - train_end) < min_validate_rows:
            continue
        splits.append(WalkForwardSplit(index=index, train_end=train_end, validate_end=validate_end))
    return splits


def build_hypothesis_specs(rows: list[dict[str, Any]], *, min_rows_per_hour: int) -> list[HypothesisSpec]:
    counts_by_hour: dict[int, int] = {}
    for row in rows:
        et_hour = row.get("et_hour")
        if et_hour is None:
            continue
        counts_by_hour[int(et_hour)] = counts_by_hour.get(int(et_hour), 0) + 1
    hour_filters = [
        (f"hour_et_{hour:02d}", (hour,))
        for hour, count in sorted(counts_by_hour.items())
        if count >= min_rows_per_hour
    ]
    session_filters = list(SESSION_FILTERS) + hour_filters
    candidates: list[HypothesisSpec] = []
    seen: set[tuple[Any, ...]] = set()
    for session_name, et_hours in session_filters:
        for direction in (None, "DOWN", "UP"):
            for max_abs_delta in (None, 0.00002, 0.00005, 0.00010, 0.00015):
                for down_cap in (None, 0.49, 0.50, 0.51):
                    for up_cap in (None, 0.48, 0.49, 0.50, 0.51):
                        key = (direction, max_abs_delta, up_cap, down_cap, et_hours)
                        if key in seen:
                            continue
                        seen.add(key)
                        name_bits = ["hyp"]
                        if direction:
                            name_bits.append(direction.lower())
                        if max_abs_delta is not None:
                            name_bits.append(f"d{max_abs_delta:.5f}")
                        if up_cap is not None:
                            name_bits.append(f"up{up_cap:.2f}")
                        if down_cap is not None:
                            name_bits.append(f"down{down_cap:.2f}")
                        if session_name != "any":
                            name_bits.append(session_name)
                        candidates.append(
                            HypothesisSpec(
                                name="_".join(name_bits),
                                direction=direction,
                                max_abs_delta=max_abs_delta,
                                up_max_buy_price=up_cap,
                                down_max_buy_price=down_cap,
                                et_hours=tuple(et_hours),
                                session_name=session_name,
                            )
                        )
    return candidates


def rank_hypothesis_pool(
    rows: list[dict[str, Any]],
    specs: list[HypothesisSpec],
    *,
    max_candidates: int,
    min_live_fills: int,
) -> list[HypothesisSpec]:
    ranked: list[tuple[tuple[float, float, int, float], HypothesisSpec]] = []
    for spec in specs:
        history = summarize_hypothesis_history(rows, spec)
        if int(history.get("replay_live_filled_rows") or 0) < min_live_fills:
            continue
        bootstrap = run_hypothesis_bootstrap(
            rows,
            spec,
            paths=300,
            horizon_windows=max(len(rows), 20),
            block_size=4,
            loss_limit_usd=DEFAULT_LOSS_LIMIT_USD,
            seed=13,
        )
        continuation = summarize_continuation_arr(historical=history, monte_carlo=bootstrap)
        fills = _safe_int(history.get("replay_live_filled_rows"), 0)
        fill_weight = min(1.0, fills / 8.0)
        attempt_fill_rate = _safe_float(history.get("attempt_fill_rate"), 0.0)
        exploration_score = (
            _safe_float(continuation.get("p05_arr_pct"), 0.0)
            * max(0.25, fill_weight)
            * max(0.25, attempt_fill_rate + 0.25)
        )
        # Bias toward the currently live-winning structure:
        # DOWN + sub-0.49 quote caps + open/09 ET sessions.
        focus_weight = 1.0
        if str(spec.direction or "").upper() == "DOWN":
            focus_weight *= 1.5
        if spec.down_max_buy_price is not None and spec.down_max_buy_price < 0.49:
            focus_weight *= 1.4
        elif spec.down_max_buy_price is not None and spec.down_max_buy_price <= 0.49:
            focus_weight *= 1.2
        if spec.session_name == "open_et" or 9 in tuple(spec.et_hours):
            focus_weight *= 1.2
        if spec.session_name != "any" and str(spec.direction or "").upper() == "DOWN":
            focus_weight *= 1.15
        if (
            spec.session_name != "any"
            and str(spec.direction or "").upper() == "DOWN"
            and spec.up_max_buy_price in (None, 0.48)
        ):
            focus_weight *= 1.1
        if spec.max_abs_delta is not None and spec.max_abs_delta <= 0.00010:
            focus_weight *= 1.1
        if spec.max_abs_delta is not None and spec.max_abs_delta <= 0.00005 and spec.session_name != "any":
            focus_weight *= 1.15
        exploration_score *= focus_weight
        key = (
            exploration_score,
            _safe_float(continuation.get("p05_arr_pct"), 0.0),
            fills,
            _safe_float(history.get("replay_live_filled_pnl_usd"), 0.0),
        )
        ranked.append((key, spec))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [spec for _, spec in ranked[: max(1, int(max_candidates))]]


def evaluate_hypothesis_walk_forward(
    rows: list[dict[str, Any]],
    spec: HypothesisSpec,
    *,
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
    min_train_rows: int,
    min_validate_rows: int,
    min_train_fills: int,
    min_validate_fills: int,
) -> dict[str, Any] | None:
    splits = build_walk_forward_splits(
        rows,
        min_train_rows=min_train_rows,
        min_validate_rows=min_validate_rows,
    )
    evaluations: list[dict[str, Any]] = []
    for split in splits:
        train_rows = rows[: split.train_end]
        validate_rows = rows[split.train_end : split.validate_end]
        train_history = summarize_hypothesis_history(train_rows, spec)
        validate_history = summarize_hypothesis_history(validate_rows, spec)
        if _safe_int(train_history.get("replay_live_filled_rows"), 0) < min_train_fills:
            continue
        if _safe_int(validate_history.get("replay_live_filled_rows"), 0) < min_validate_fills:
            continue
        train_mc = run_hypothesis_bootstrap(
            train_rows,
            spec,
            paths=paths,
            horizon_windows=max(len(train_rows), 20),
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed=seed + split.index,
        )
        validate_mc = run_hypothesis_bootstrap(
            validate_rows,
            spec,
            paths=paths,
            horizon_windows=max(len(validate_rows), 12),
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed=(seed * 10) + split.index,
        )
        train_cont = summarize_continuation_arr(historical=train_history, monte_carlo=train_mc)
        validate_cont = summarize_continuation_arr(historical=validate_history, monte_carlo=validate_mc)
        train_arr = _safe_float(train_cont.get("median_arr_pct"), 0.0)
        validate_arr = _safe_float(validate_cont.get("median_arr_pct"), 0.0)
        evaluations.append(
            {
                "split": asdict(split),
                "train": {
                    "historical": train_history,
                    "monte_carlo": train_mc,
                    "continuation": train_cont,
                },
                "validate": {
                    "historical": validate_history,
                    "monte_carlo": validate_mc,
                    "continuation": validate_cont,
                },
                "generalization_ratio": round(
                    (validate_arr / train_arr) if abs(train_arr) > 1e-12 else 0.0,
                    4,
                ),
            }
        )
    if not evaluations:
        return None
    validation_arrs = [
        _safe_float(item["validate"]["continuation"].get("median_arr_pct"), 0.0)
        for item in evaluations
    ]
    validation_p05_arrs = [
        _safe_float(item["validate"]["continuation"].get("p05_arr_pct"), 0.0)
        for item in evaluations
    ]
    validation_probs = [
        _safe_float(item["validate"]["monte_carlo"].get("profit_probability"), 0.0)
        for item in evaluations
    ]
    validation_drawdowns = [
        _safe_float(item["validate"]["monte_carlo"].get("p95_max_drawdown_usd"), 0.0)
        for item in evaluations
    ]
    validation_pnls = [
        _safe_float(item["validate"]["historical"].get("replay_live_filled_pnl_usd"), 0.0)
        for item in evaluations
    ]
    validation_fills = [
        _safe_int(item["validate"]["historical"].get("replay_live_filled_rows"), 0)
        for item in evaluations
    ]
    train_arrs = [
        _safe_float(item["train"]["continuation"].get("median_arr_pct"), 0.0)
        for item in evaluations
    ]
    aggregated = _round_metrics(
        {
            "splits_total": len(splits),
            "splits_evaluated": len(evaluations),
            "train_median_arr_pct": _percentile(train_arrs, 50),
            "validation_median_arr_pct": _percentile(validation_arrs, 50),
            "validation_p05_arr_pct": _percentile(validation_p05_arrs, 50),
            "validation_profit_probability": sum(validation_probs) / len(validation_probs),
            "validation_p95_drawdown_usd": _percentile(validation_drawdowns, 50),
            "validation_replay_pnl_usd": sum(validation_pnls),
            "validation_live_filled_rows": sum(validation_fills),
            "generalization_ratio": (
                _percentile(validation_arrs, 50) / _percentile(train_arrs, 50)
                if abs(_percentile(train_arrs, 50)) > 1e-12
                else 0.0
            ),
            "ranking_score": (
                _percentile(validation_p05_arrs, 50)
                * max(0.0, sum(validation_probs) / len(validation_probs))
            ),
            "evidence_band": _evidence_band(sum(validation_fills)),
        }
    )
    return {
        "hypothesis": asdict(spec),
        "summary": aggregated,
        "splits": evaluations,
    }


def _top_by_key(candidates: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        label = str((candidate.get("hypothesis") or {}).get(key_name) or "any")
        current = best.get(label)
        if current is None:
            best[label] = candidate
            continue
        current_score = _safe_float((current.get("summary") or {}).get("validation_p05_arr_pct"), 0.0)
        candidate_score = _safe_float((candidate.get("summary") or {}).get("validation_p05_arr_pct"), 0.0)
        if candidate_score > current_score:
            best[label] = candidate
    return sorted(
        best.values(),
        key=lambda item: _safe_float((item.get("summary") or {}).get("validation_p05_arr_pct"), 0.0),
        reverse=True,
    )


def _recommended_session_policy(best_hypothesis: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = best_hypothesis or {}
    hypothesis = payload.get("hypothesis") if isinstance(payload.get("hypothesis"), dict) else payload
    session_name = str(hypothesis.get("session_name") or "").strip()
    et_hours = sorted(
        {
            int(hour)
            for hour in (hypothesis.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
        }
    )
    if not et_hours:
        return []

    record: dict[str, Any] = {
        "name": session_name or str(hypothesis.get("name") or "hypothesis_session"),
        "et_hours": et_hours,
    }
    max_abs_delta = hypothesis.get("max_abs_delta")
    up_max_buy_price = hypothesis.get("up_max_buy_price")
    down_max_buy_price = hypothesis.get("down_max_buy_price")
    if max_abs_delta is not None:
        record["max_abs_delta"] = _safe_float(max_abs_delta, 0.0) or 0.0
    if up_max_buy_price is not None:
        record["up_max_buy_price"] = _safe_float(up_max_buy_price, 0.0) or 0.0
    if down_max_buy_price is not None:
        record["down_max_buy_price"] = _safe_float(down_max_buy_price, 0.0) or 0.0
    return [record]


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


def _hypothesis_followup_families(item: dict[str, Any]) -> list[str]:
    families: list[str] = []
    direction = str(item.get("direction") or "").upper()
    up_cap = item.get("up_max_buy_price")
    down_cap = item.get("down_max_buy_price")
    max_abs_delta = item.get("max_abs_delta")
    et_hours = tuple(int(hour) for hour in (item.get("et_hours") or []) if isinstance(hour, int))
    session_name = str(item.get("session_name") or "any")

    if direction == "DOWN" and up_cap is None:
        families.append("down_only")
    if direction == "DOWN" and (up_cap is None or _safe_float(up_cap, 1.0) <= 0.47):
        families.append("up_disabled_or_nearly_disabled")
    if (
        direction == "DOWN"
        and max_abs_delta is not None
        and _safe_float(max_abs_delta, 1.0) <= 0.00008
        and down_cap is not None
        and _safe_float(down_cap, 1.0) <= 0.49
    ):
        families.append("tight_delta_down_bias")
    if (
        direction == "DOWN"
        and max_abs_delta is not None
        and _safe_float(max_abs_delta, 1.0) <= 0.00010
        and down_cap is not None
        and _safe_float(down_cap, 1.0) <= 0.49
        and (session_name == "open_et" or any(hour in {9, 10, 11} for hour in et_hours))
    ):
        families.append("session_tight_down_bias")
    return families


def _frontier_focus_tags(item: dict[str, Any]) -> list[str]:
    tags = set(str(tag) for tag in (item.get("follow_up_families") or []))
    direction = str(item.get("direction") or "").upper()
    session_name = str(item.get("session_name") or "any")
    max_abs_delta = item.get("max_abs_delta")

    if session_name != "any":
        tags.add("session_conditioned")
    if direction == "DOWN":
        tags.add("one_sided")
        if session_name != "any":
            tags.add("session_conditioned_one_sided")
    if max_abs_delta is not None:
        delta = _safe_float(max_abs_delta, 0.0)
        if delta <= 0.00005:
            tags.add("high_conviction_tight_delta")
        elif delta <= 0.00010 and session_name != "any":
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
    score += min(1.0, _safe_int(item.get("validation_live_filled_rows"), 0) / 12.0)
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
    items: list[dict[str, Any]] = []
    active_arr = _safe_float((active_candidate or {}).get("validation_median_arr_pct"), 0.0)
    active_p05 = _safe_float((active_candidate or {}).get("validation_p05_arr_pct"), 0.0)
    active_replay_pnl = _safe_float((active_candidate or {}).get("validation_replay_pnl_usd"), 0.0)
    active_fills = max(1, _safe_int((active_candidate or {}).get("validation_live_filled_rows"), 0))
    for candidate in candidates:
        hypothesis = candidate.get("hypothesis") if isinstance(candidate, dict) else {}
        summary = candidate.get("summary") if isinstance(candidate, dict) else {}
        if not isinstance(hypothesis, dict):
            hypothesis = {}
        if not isinstance(summary, dict):
            summary = {}
        et_hours = sorted(
            {
                int(hour)
                for hour in (hypothesis.get("et_hours") or [])
                if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
            }
        )
        validation_fills = _safe_int(summary.get("validation_live_filled_rows"), 0)
        fill_retention = validation_fills / float(active_fills)
        generalization_ratio = _safe_float(summary.get("generalization_ratio"), 0.0)
        evidence_band = str(summary.get("evidence_band") or "exploratory")
        execution_realism_score = _execution_realism_score(
            fill_retention=fill_retention,
            generalization_ratio=generalization_ratio,
            evidence_band=evidence_band,
        )
        payload = {
            "name": str(hypothesis.get("name") or "candidate"),
            "direction": str(hypothesis.get("direction") or "").upper() or None,
            "session_name": str(hypothesis.get("session_name") or "any"),
            "et_hours": et_hours,
            "max_abs_delta": (
                _safe_float(hypothesis.get("max_abs_delta"), 0.0)
                if hypothesis.get("max_abs_delta") is not None
                else None
            ),
            "up_max_buy_price": (
                _safe_float(hypothesis.get("up_max_buy_price"), 0.0)
                if hypothesis.get("up_max_buy_price") is not None
                else None
            ),
            "down_max_buy_price": (
                _safe_float(hypothesis.get("down_max_buy_price"), 0.0)
                if hypothesis.get("down_max_buy_price") is not None
                else None
            ),
            "ranking_score": _safe_float(summary.get("ranking_score"), 0.0),
            "evidence_band": evidence_band,
            "validation_live_filled_rows": validation_fills,
            "generalization_ratio": generalization_ratio,
            "validation_median_arr_pct": _safe_float(summary.get("validation_median_arr_pct"), 0.0),
            "validation_p05_arr_pct": _safe_float(summary.get("validation_p05_arr_pct"), 0.0),
            "validation_replay_pnl_usd": _safe_float(summary.get("validation_replay_pnl_usd"), 0.0),
            "arr_improvement_vs_active_pct": round(
                _safe_float(summary.get("validation_median_arr_pct"), 0.0) - active_arr,
                4,
            ),
            "p05_arr_improvement_vs_active_pct": round(
                _safe_float(summary.get("validation_p05_arr_pct"), 0.0) - active_p05,
                4,
            ),
            "replay_pnl_improvement_vs_active_usd": round(
                _safe_float(summary.get("validation_replay_pnl_usd"), 0.0) - active_replay_pnl,
                4,
            ),
            "fill_retention_vs_active": round(fill_retention, 4),
            "execution_realism_score": round(execution_realism_score, 4),
            "execution_realism_label": (
                "high" if execution_realism_score >= 0.8 else ("medium" if execution_realism_score >= 0.6 else "low")
            ),
        }
        payload["follow_up_families"] = _hypothesis_followup_families(payload)
        payload["frontier_focus_tags"] = _frontier_focus_tags(payload)
        payload["frontier_bias_score"] = _frontier_bias_score(payload)
        payload["high_conviction_score"] = _high_conviction_score(payload)
        items.append(_apply_candidate_classification(payload))
    items.sort(
        key=lambda item: (
            -_candidate_class_priority(item),
            -_safe_float(item.get("ranking_score"), 0.0),
            -_safe_float(item.get("execution_realism_score"), 0.0),
            str(item.get("name") or ""),
        )
    )
    if limit is None:
        return items
    return items[: max(0, int(limit))]


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


def _candidate_from_profile_result(
    *,
    profile: GuardrailProfile,
    evaluated: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(evaluated, dict):
        return {
            "name": profile.name,
            "session_name": "any",
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
    hypothesis = dict(evaluated.get("hypothesis") or {})
    summary = dict(evaluated.get("summary") or {})
    return {
        "name": str(hypothesis.get("name") or profile.name),
        "session_name": str(hypothesis.get("session_name") or "any"),
        "et_hours": sorted(
            {
                int(hour)
                for hour in (hypothesis.get("et_hours") or [])
                if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
            }
        ),
        "max_abs_delta": (
            _safe_float(hypothesis.get("max_abs_delta"), 0.0)
            if hypothesis.get("max_abs_delta") is not None
            else None
        ),
        "up_max_buy_price": (
            _safe_float(hypothesis.get("up_max_buy_price"), 0.0)
            if hypothesis.get("up_max_buy_price") is not None
            else None
        ),
        "down_max_buy_price": (
            _safe_float(hypothesis.get("down_max_buy_price"), 0.0)
            if hypothesis.get("down_max_buy_price") is not None
            else None
        ),
        "ranking_score": _safe_float(summary.get("ranking_score"), 0.0),
        "evidence_band": str(summary.get("evidence_band") or "exploratory"),
        "validation_live_filled_rows": _safe_int(summary.get("validation_live_filled_rows"), 0),
        "generalization_ratio": _safe_float(summary.get("generalization_ratio"), 0.0),
        "validation_median_arr_pct": _safe_float(summary.get("validation_median_arr_pct"), 0.0),
        "validation_p05_arr_pct": _safe_float(summary.get("validation_p05_arr_pct"), 0.0),
        "validation_replay_pnl_usd": _safe_float(summary.get("validation_replay_pnl_usd"), 0.0),
    }


def _is_live_filled_row(row: dict[str, Any]) -> bool:
    status = str(row.get("order_status") or "").strip().lower()
    return status == "live_filled" or (status.startswith("live_") and _safe_float(row.get("trade_size_usd"), 0.0) > 0.0)


def _hypothesis_spec_from_followup(item: dict[str, Any]) -> HypothesisSpec:
    return HypothesisSpec(
        name=str(item.get("name") or "candidate"),
        direction=(str(item.get("direction")).upper() if item.get("direction") else None),
        max_abs_delta=(
            _safe_float(item.get("max_abs_delta"), 0.0)
            if item.get("max_abs_delta") is not None
            else None
        ),
        up_max_buy_price=(
            _safe_float(item.get("up_max_buy_price"), 0.0)
            if item.get("up_max_buy_price") is not None
            else None
        ),
        down_max_buy_price=(
            _safe_float(item.get("down_max_buy_price"), 0.0)
            if item.get("down_max_buy_price") is not None
            else None
        ),
        et_hours=tuple(
            int(hour)
            for hour in (item.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
        ),
        session_name=str(item.get("session_name") or "any"),
    )


def _size_stress_assessment(
    rows: list[dict[str, Any]],
    item: dict[str, Any],
    *,
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
) -> dict[str, Any]:
    spec = _hypothesis_spec_from_followup(item)
    history = summarize_hypothesis_history(rows, spec)
    horizon_windows = max(len(rows), 12)
    matched_fills = [row for row in rows if row_matches_hypothesis(row, spec) and _is_live_filled_row(row)]
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
                if row_matches_hypothesis(row, spec)
                else 0.0,
                "activation_probability": fill_retention_ratio if row_matches_hypothesis(row, spec) else 0.0,
                "execution_cost_usd": 0.0,
            }
            for row in rows
        ]
        stress_monte_carlo = _run_monte_carlo_from_entries(
            entries,
            paths=size_paths,
            horizon_trades=horizon_windows,
            block_size=max(1, int(block_size)),
            loss_limit_usd=float(loss_limit_usd),
            seed_material=f"{seed}:{spec.name}:{trade_size_usd:.2f}",
        )
        stress_continuation = summarize_continuation_arr(
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


def _capacity_stress_candidates(
    rows: list[dict[str, Any]],
    best_hypothesis: dict[str, Any] | None,
    *,
    paths: int,
    block_size: int,
    loss_limit_usd: float,
    seed: int,
    min_train_rows: int,
    min_validate_rows: int,
    min_train_fills: int,
    min_validate_fills: int,
) -> list[dict[str, Any]]:
    if not isinstance(best_hypothesis, dict):
        return []
    base_h = best_hypothesis.get("hypothesis")
    base_s = best_hypothesis.get("summary")
    if not isinstance(base_h, dict) or not isinstance(base_s, dict):
        return []
    base_spec = HypothesisSpec(
        name=str(base_h.get("name") or "best"),
        direction=str(base_h.get("direction")).upper() if base_h.get("direction") else None,
        max_abs_delta=(
            _safe_float(base_h.get("max_abs_delta"), 0.0) if base_h.get("max_abs_delta") is not None else None
        ),
        up_max_buy_price=(
            _safe_float(base_h.get("up_max_buy_price"), 0.0) if base_h.get("up_max_buy_price") is not None else None
        ),
        down_max_buy_price=(
            _safe_float(base_h.get("down_max_buy_price"), 0.0) if base_h.get("down_max_buy_price") is not None else None
        ),
        et_hours=tuple(
            int(hour)
            for hour in (base_h.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
        ),
        session_name=str(base_h.get("session_name") or "any"),
    )
    variant_specs = [
        ("tight_quote", base_spec.__class__(
            name=f"{base_spec.name}_tight_quote",
            direction=base_spec.direction,
            max_abs_delta=base_spec.max_abs_delta,
            up_max_buy_price=(
                round(max(0.45, min(0.55, (base_spec.up_max_buy_price or 0.49) - 0.01)), 2)
                if base_spec.up_max_buy_price is not None
                else None
            ),
            down_max_buy_price=(
                round(max(0.45, min(0.55, (base_spec.down_max_buy_price or 0.49) - 0.01)), 2)
                if base_spec.down_max_buy_price is not None
                else None
            ),
            et_hours=base_spec.et_hours,
            session_name=base_spec.session_name,
        )),
        ("loose_quote", base_spec.__class__(
            name=f"{base_spec.name}_loose_quote",
            direction=base_spec.direction,
            max_abs_delta=base_spec.max_abs_delta,
            up_max_buy_price=(
                round(max(0.45, min(0.55, (base_spec.up_max_buy_price or 0.49) + 0.01)), 2)
                if base_spec.up_max_buy_price is not None
                else None
            ),
            down_max_buy_price=(
                round(max(0.45, min(0.55, (base_spec.down_max_buy_price or 0.49) + 0.01)), 2)
                if base_spec.down_max_buy_price is not None
                else None
            ),
            et_hours=base_spec.et_hours,
            session_name=base_spec.session_name,
        )),
        ("tight_delta", base_spec.__class__(
            name=f"{base_spec.name}_tight_delta",
            direction=base_spec.direction,
            max_abs_delta=(
                round(max(0.00001, (base_spec.max_abs_delta or 0.00010) * 0.85), 8)
                if base_spec.max_abs_delta is not None
                else None
            ),
            up_max_buy_price=base_spec.up_max_buy_price,
            down_max_buy_price=base_spec.down_max_buy_price,
            et_hours=base_spec.et_hours,
            session_name=base_spec.session_name,
        )),
        ("loose_delta", base_spec.__class__(
            name=f"{base_spec.name}_loose_delta",
            direction=base_spec.direction,
            max_abs_delta=(
                round(min(0.00100, (base_spec.max_abs_delta or 0.00010) * 1.15), 8)
                if base_spec.max_abs_delta is not None
                else None
            ),
            up_max_buy_price=base_spec.up_max_buy_price,
            down_max_buy_price=base_spec.down_max_buy_price,
            et_hours=base_spec.et_hours,
            session_name=base_spec.session_name,
        )),
    ]

    base_fills = _safe_int(base_s.get("validation_live_filled_rows"), 0)
    base_pnl = _safe_float(base_s.get("validation_replay_pnl_usd"), 0.0)
    base_p05 = _safe_float(base_s.get("validation_p05_arr_pct"), 0.0)
    candidates: list[dict[str, Any]] = []
    for idx, (variant_name, variant_spec) in enumerate(variant_specs, start=1):
        evaluated = evaluate_hypothesis_walk_forward(
            rows,
            variant_spec,
            paths=max(50, int(paths // 3)),
            block_size=block_size,
            loss_limit_usd=loss_limit_usd,
            seed=seed + (idx * 101),
            min_train_rows=min_train_rows,
            min_validate_rows=min_validate_rows,
            min_train_fills=min_train_fills,
            min_validate_fills=min_validate_fills,
        )
        if not isinstance(evaluated, dict):
            continue
        summary = evaluated.get("summary") if isinstance(evaluated.get("summary"), dict) else {}
        fills = _safe_int(summary.get("validation_live_filled_rows"), 0)
        pnl = _safe_float(summary.get("validation_replay_pnl_usd"), 0.0)
        p05 = _safe_float(summary.get("validation_p05_arr_pct"), 0.0)
        candidates.append(
            {
                "name": str(variant_spec.name),
                "variant": variant_name,
                "session_name": variant_spec.session_name,
                "et_hours": list(variant_spec.et_hours),
                "max_abs_delta": variant_spec.max_abs_delta,
                "up_max_buy_price": variant_spec.up_max_buy_price,
                "down_max_buy_price": variant_spec.down_max_buy_price,
                "expected_fill_lift": int(fills - base_fills),
                "expected_median_pnl_delta_usd": round(pnl - base_pnl, 4),
                "expected_p05_arr_delta_pct": round(p05 - base_p05, 4),
                "evidence_band": str(summary.get("evidence_band") or _evidence_band(fills)),
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
    best_hypothesis: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    hypothesis = (best_hypothesis or {}).get("hypothesis")
    scoped_rows = rows
    if isinstance(hypothesis, dict):
        spec = HypothesisSpec(
            name=str(hypothesis.get("name") or "best"),
            direction=str(hypothesis.get("direction")).upper() if hypothesis.get("direction") else None,
            max_abs_delta=(
                _safe_float(hypothesis.get("max_abs_delta"), 0.0)
                if hypothesis.get("max_abs_delta") is not None
                else None
            ),
            up_max_buy_price=(
                _safe_float(hypothesis.get("up_max_buy_price"), 0.0)
                if hypothesis.get("up_max_buy_price") is not None
                else None
            ),
            down_max_buy_price=(
                _safe_float(hypothesis.get("down_max_buy_price"), 0.0)
                if hypothesis.get("down_max_buy_price") is not None
                else None
            ),
            et_hours=tuple(
                int(hour)
                for hour in (hypothesis.get("et_hours") or [])
                if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
            ),
            session_name=str(hypothesis.get("session_name") or "any"),
        )
        scoped_rows = [row for row in rows if row_matches_hypothesis(row, spec)]
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


def _last_improvement_for_hypothesis(
    rows: list[dict[str, Any]],
    hypothesis_payload: dict[str, Any] | None,
) -> datetime | None:
    hypothesis_payload = hypothesis_payload or {}
    if not isinstance(hypothesis_payload, dict):
        return None
    spec = HypothesisSpec(
        name=str(hypothesis_payload.get("name") or "candidate"),
        direction=(
            str(hypothesis_payload.get("direction")).strip().upper()
            if hypothesis_payload.get("direction") not in (None, "")
            else None
        ),
        max_abs_delta=(
            _safe_float(hypothesis_payload.get("max_abs_delta"), 0.0)
            if hypothesis_payload.get("max_abs_delta") is not None
            else None
        ),
        up_max_buy_price=(
            _safe_float(hypothesis_payload.get("up_max_buy_price"), 0.0)
            if hypothesis_payload.get("up_max_buy_price") is not None
            else None
        ),
        down_max_buy_price=(
            _safe_float(hypothesis_payload.get("down_max_buy_price"), 0.0)
            if hypothesis_payload.get("down_max_buy_price") is not None
            else None
        ),
        et_hours=tuple(
            int(hour)
            for hour in (hypothesis_payload.get("et_hours") or [])
            if isinstance(hour, int) or (isinstance(hour, str) and hour.isdigit())
        ),
        session_name=str(hypothesis_payload.get("session_name") or "any"),
    )
    matched = [
        row for row in rows
        if row_matches_hypothesis(row, spec)
        and str(row.get("order_status") or "").strip().lower() == "live_filled"
        and _safe_float(row.get("pnl_usd"), 0.0) > 0.0
    ]
    if not matched:
        matched = [
            row for row in rows
            if row_matches_hypothesis(row, spec)
            and str(row.get("order_status") or "").strip().lower() == "live_filled"
        ]
    timestamps = [ts for ts in (_row_observed_at_utc(row) for row in matched) if ts is not None]
    return max(timestamps) if timestamps else None


def _render_markdown(summary: dict[str, Any]) -> str:
    top = summary.get("top_hypotheses") or []
    best = summary.get("best_hypothesis") or {}
    recommended_policy = summary.get("recommended_session_policy") or []
    best_candidate = summary.get("best_candidate") or {}
    active_profile = summary.get("active_profile") or {}
    high_conviction = summary.get("high_conviction_followups") or []
    size_ready = summary.get("size_ready_followups") or []
    loss_filters = summary.get("loss_cluster_filters") or []
    lines = [
        "# BTC5 Hypothesis Lab",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Source rows: `{summary['input']['observed_window_rows']}` total, `{summary['input']['priced_window_rows']}` priced observations",
        f"- Candidate pool: `{summary['input']['generated_candidates']}` generated, `{summary['input']['walk_forward_candidates']}` walk-forward validated",
        f"- Validation metric: `{summary['metric_name']}`",
        f"- Active profile: `{active_profile.get('name', 'n/a')}`",
        f"- Best candidate: `{best_candidate.get('name', 'n/a')}`",
        f"- ARR delta vs active: `{_safe_float(summary.get('arr_delta_vs_active_pct'), 0.0):.2f}` percentage points",
        f"- P05 ARR delta vs active: `{_safe_float(summary.get('p05_arr_delta_vs_active_pct'), 0.0):.2f}` percentage points",
        f"- Validation fills: `{_safe_int(summary.get('validation_live_filled_rows'), 0)}`",
        f"- Generalization ratio: `{_safe_float(summary.get('generalization_ratio'), 0.0):.4f}`",
        f"- Evidence band: `{summary.get('evidence_band', 'exploratory')}`",
        f"- Last improvement at: `{summary.get('last_improvement_at') or 'unknown'}`",
        f"- Hours since last improvement: `{summary.get('hours_since_last_improvement')}`",
        "",
    ]
    if best:
        hypothesis = best.get("hypothesis") or {}
        stats = best.get("summary") or {}
        lines.extend(
            [
                "## Best Hypothesis",
                "",
                f"- Name: `{hypothesis.get('name')}`",
                f"- Direction: `{hypothesis.get('direction') or 'ANY'}`",
                f"- Session: `{hypothesis.get('session_name') or 'any'}`",
                f"- Validation median ARR: `{stats.get('validation_median_arr_pct', 0.0):.2f}%`",
                f"- Validation P05 ARR: `{stats.get('validation_p05_arr_pct', 0.0):.2f}%`",
                f"- Validation replay PnL: `{stats.get('validation_replay_pnl_usd', 0.0):.4f}` USD",
                f"- Validation live fills: `{stats.get('validation_live_filled_rows', 0)}`",
                f"- Validation profit probability: `{stats.get('validation_profit_probability', 0.0):.2%}`",
                f"- Evidence band: `{stats.get('evidence_band', 'exploratory')}`",
                f"- Generalization ratio: `{stats.get('generalization_ratio', 0.0):.4f}`",
                "",
            ]
        )
    if recommended_policy:
        lines.extend(
            [
                "## Recommended Session Policy",
                "",
                f"- Runtime-ready policy records: `{len(recommended_policy)}`",
                "",
                "```json",
                json.dumps(recommended_policy, indent=2),
                "```",
                "",
            ]
        )
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
            "## Top Hypotheses",
            "",
            "| Rank | Hypothesis | Direction | Session | Validation Median ARR | Validation P05 ARR | Validation PnL | Fills |",
            "|---|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for index, candidate in enumerate(top, start=1):
        hypothesis = candidate.get("hypothesis") or {}
        stats = candidate.get("summary") or {}
        lines.append(
            "| "
            + f"{index} | {hypothesis.get('name')} | "
            + f"{hypothesis.get('direction') or 'ANY'} | "
            + f"{hypothesis.get('session_name') or 'any'} | "
            + f"{stats.get('validation_median_arr_pct', 0.0):.2f}% | "
            + f"{stats.get('validation_p05_arr_pct', 0.0):.2f}% | "
            + f"{stats.get('validation_replay_pnl_usd', 0.0):.4f} | "
            + f"{stats.get('validation_live_filled_rows', 0)} |"
        )
    top_by_direction = summary.get("top_by_direction") or []
    top_by_session = summary.get("top_by_session") or []
    if top_by_direction:
        lines.extend(["", "## Best By Direction", ""])
        for candidate in top_by_direction:
            hypothesis = candidate.get("hypothesis") or {}
            stats = candidate.get("summary") or {}
            lines.append(
                f"- `{hypothesis.get('direction') or 'ANY'}`: `{hypothesis.get('name')}` "
                + f"(P05 ARR `{stats.get('validation_p05_arr_pct', 0.0):.2f}%`, "
                + f"replay `{stats.get('validation_replay_pnl_usd', 0.0):.4f}` USD)"
            )
    if top_by_session:
        lines.extend(["", "## Best By Session", ""])
        for candidate in top_by_session[:5]:
            hypothesis = candidate.get("hypothesis") or {}
            stats = candidate.get("summary") or {}
            lines.append(
                f"- `{hypothesis.get('session_name') or 'any'}`: `{hypothesis.get('name')}` "
                + f"(P05 ARR `{stats.get('validation_p05_arr_pct', 0.0):.2f}%`, "
                + f"fills `{stats.get('validation_live_filled_rows', 0)}`)"
            )
    return "\n".join(lines) + "\n"


def _write_outputs(output_dir: Path, *, summary: dict[str, Any], write_latest: bool) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    md_path.write_text(_render_markdown(summary))
    if write_latest:
        shutil.copy2(json_path, REPORTS_DIR / "btc5_hypothesis_lab_latest.json")
        shutil.copy2(md_path, REPORTS_DIR / "btc5_hypothesis_lab_latest.md")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--strategy-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--override-env", type=Path, default=DEFAULT_OVERRIDE_ENV)
    parser.add_argument("--include-archive-csvs", action="store_true")
    parser.add_argument("--archive-glob", default=DEFAULT_ARCHIVE_GLOB)
    parser.add_argument("--refresh-remote", action="store_true")
    parser.add_argument("--remote-cache-json", type=Path, default=DEFAULT_REMOTE_ROWS_JSON)
    parser.add_argument("--paths", type=int, default=750)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--loss-limit-usd", type=float, default=DEFAULT_LOSS_LIMIT_USD)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--top-hypotheses", type=int, default=12)
    parser.add_argument("--min-full-history-fills", type=int, default=3)
    parser.add_argument("--min-train-rows", type=int, default=12)
    parser.add_argument("--min-validate-rows", type=int, default=8)
    parser.add_argument("--min-train-fills", type=int, default=1)
    parser.add_argument("--min-validate-fills", type=int, default=1)
    parser.add_argument("--min-rows-per-hour", type=int, default=6)
    parser.add_argument("--write-latest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    merged_env = _merged_strategy_env(args.strategy_env, args.override_env)
    active_profile = _profile_from_env("active_profile", merged_env)
    rows, baseline = assemble_observed_rows(
        db_path=args.db_path,
        include_archive_csvs=bool(args.include_archive_csvs),
        archive_glob=str(args.archive_glob),
        refresh_remote=bool(args.refresh_remote),
        remote_cache_json=args.remote_cache_json,
    )
    enriched_priced_rows = priced_rows(rows)
    generated = build_hypothesis_specs(
        enriched_priced_rows,
        min_rows_per_hour=max(1, int(args.min_rows_per_hour)),
    )
    candidates = rank_hypothesis_pool(
        enriched_priced_rows,
        generated,
        max_candidates=max(1, int(args.max_candidates)),
        min_live_fills=max(1, int(args.min_full_history_fills)),
    )
    evaluated: list[dict[str, Any]] = []
    for spec in candidates:
        result = evaluate_hypothesis_walk_forward(
            enriched_priced_rows,
            spec,
            paths=max(1, int(args.paths)),
            block_size=max(1, int(args.block_size)),
            loss_limit_usd=float(args.loss_limit_usd),
            seed=int(args.seed),
            min_train_rows=max(1, int(args.min_train_rows)),
            min_validate_rows=max(1, int(args.min_validate_rows)),
            min_train_fills=max(1, int(args.min_train_fills)),
            min_validate_fills=max(1, int(args.min_validate_fills)),
        )
        if result is not None:
            evaluated.append(result)
    evaluated.sort(
        key=lambda item: (
            _safe_float((item.get("summary") or {}).get("validation_p05_arr_pct"), 0.0),
            _safe_float((item.get("summary") or {}).get("validation_median_arr_pct"), 0.0),
            _safe_float((item.get("summary") or {}).get("validation_profit_probability"), 0.0),
            _safe_int((item.get("summary") or {}).get("validation_live_filled_rows"), 0),
        ),
        reverse=True,
    )
    top = evaluated[: max(1, int(args.top_hypotheses))]
    active_spec = HypothesisSpec(
        name=active_profile.name,
        direction=None,
        max_abs_delta=active_profile.max_abs_delta,
        up_max_buy_price=active_profile.up_max_buy_price,
        down_max_buy_price=active_profile.down_max_buy_price,
        et_hours=tuple(),
        session_name="any",
    )
    active_result = evaluate_hypothesis_walk_forward(
        enriched_priced_rows,
        active_spec,
        paths=max(1, int(args.paths)),
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        min_train_rows=max(1, int(args.min_train_rows)),
        min_validate_rows=max(1, int(args.min_validate_rows)),
        min_train_fills=max(1, int(args.min_train_fills)),
        min_validate_fills=max(1, int(args.min_validate_fills)),
    )
    ranked_best_candidate = _candidate_from_profile_result(
        profile=active_profile,
        evaluated=top[0] if top else None,
    )
    active_candidate = _candidate_from_profile_result(
        profile=active_profile,
        evaluated=active_result,
    )
    hold_current_candidate = _hold_current_candidate(active_candidate)
    last_improvement_at = _last_improvement_for_hypothesis(
        enriched_priced_rows,
        (top[0] or {}).get("hypothesis") if top else None,
    )
    hours_since_last_improvement = (
        round((_now_utc() - last_improvement_at).total_seconds() / 3600.0, 4)
        if last_improvement_at is not None
        else None
    )
    output_dir = args.output_dir
    all_follow_ups = _follow_up_candidates_with_tradeoffs(top, active_candidate=active_candidate, limit=None)
    ranked_candidate_by_name = {str(item.get("name") or ""): item for item in all_follow_ups}
    ranked_best_candidate = ranked_candidate_by_name.get(ranked_best_candidate["name"], ranked_best_candidate)
    best_promote_ready_candidate = _best_candidate_by_class(all_follow_ups, "promote")
    best_probe_only_candidate = _best_candidate_by_class(all_follow_ups, "probe_only")
    deployment_candidate = dict(best_promote_ready_candidate or hold_current_candidate)
    follow_ups = all_follow_ups[:5]
    loss_clusters = _loss_cluster_suppression_candidates(
        enriched_priced_rows,
        top[0] if top else None,
    )
    candidate_class_breakdown = _class_breakdown(all_follow_ups + loss_clusters + [hold_current_candidate])
    summary = {
        "generated_at": _now_utc().isoformat(),
        "metric_name": "validation_p05_arr_pct",
        "db_path": str(args.db_path),
        "input": {
            "observed_window_rows": len(rows),
            "priced_window_rows": len(enriched_priced_rows),
            "generated_candidates": len(generated),
            "ranked_candidates": len(candidates),
            "walk_forward_candidates": len(evaluated),
        },
        "simulation": {
            "paths": int(args.paths),
            "block_size": int(args.block_size),
            "loss_limit_usd": round(float(args.loss_limit_usd), 4),
            "seed": int(args.seed),
            "min_train_rows": int(args.min_train_rows),
            "min_validate_rows": int(args.min_validate_rows),
            "min_train_fills": int(args.min_train_fills),
            "min_validate_fills": int(args.min_validate_fills),
        },
        "baseline": baseline,
        "active_profile": {
            "name": active_candidate["name"],
            "session_name": active_candidate["session_name"],
            "et_hours": active_candidate["et_hours"],
            "max_abs_delta": active_candidate["max_abs_delta"],
            "up_max_buy_price": active_candidate["up_max_buy_price"],
            "down_max_buy_price": active_candidate["down_max_buy_price"],
        },
        "best_candidate": deployment_candidate,
        "best_ranked_candidate": ranked_best_candidate,
        "best_promote_ready_candidate": best_promote_ready_candidate,
        "best_probe_only_candidate": best_probe_only_candidate,
        "hold_current_candidate": hold_current_candidate,
        "deployment_recommendation": "promote" if best_promote_ready_candidate is not None else "hold_current",
        "candidate_class_breakdown": candidate_class_breakdown,
        "arr_delta_vs_active_pct": round(
            _safe_float(deployment_candidate.get("validation_median_arr_pct"), 0.0)
            - _safe_float(active_candidate.get("validation_median_arr_pct"), 0.0),
            4,
        ),
        "p05_arr_delta_vs_active_pct": round(
            _safe_float(deployment_candidate.get("validation_p05_arr_pct"), 0.0)
            - _safe_float(active_candidate.get("validation_p05_arr_pct"), 0.0),
            4,
        ),
        "validation_live_filled_rows": _safe_int(deployment_candidate.get("validation_live_filled_rows"), 0),
        "generalization_ratio": _safe_float(deployment_candidate.get("generalization_ratio"), 0.0),
        "evidence_band": str(deployment_candidate.get("evidence_band") or "exploratory"),
        "last_improvement_at": (
            last_improvement_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if last_improvement_at is not None
            else None
        ),
        "hours_since_last_improvement": hours_since_last_improvement,
        "best_hypothesis": top[0] if top else None,
        "recommended_session_policy": _recommended_session_policy(best_promote_ready_candidate),
        "follow_up_candidates": follow_ups,
        "best_live_followups": _best_live_followups(follow_ups),
        "best_one_sided_followups": _best_one_sided_followups(follow_ups),
        "high_conviction_followups": _high_conviction_followups(follow_ups),
        "size_ready_followups": _size_ready_followups(
            enriched_priced_rows,
            follow_ups,
            paths=max(1, int(args.paths)),
            block_size=max(1, int(args.block_size)),
            loss_limit_usd=float(args.loss_limit_usd),
            seed=int(args.seed),
        ),
        "loss_cluster_suppression_candidates": loss_clusters,
        "loss_cluster_filters": _loss_cluster_filters(loss_clusters),
        "capacity_stress_candidates": _capacity_stress_candidates(
            enriched_priced_rows,
            top[0] if top else None,
            paths=max(1, int(args.paths)),
            block_size=max(1, int(args.block_size)),
            loss_limit_usd=float(args.loss_limit_usd),
            seed=int(args.seed),
            min_train_rows=max(1, int(args.min_train_rows)),
            min_validate_rows=max(1, int(args.min_validate_rows)),
            min_train_fills=max(1, int(args.min_train_fills)),
            min_validate_fills=max(1, int(args.min_validate_fills)),
        ),
        "top_hypotheses": top,
        "top_by_direction": _top_by_key(top, "direction"),
        "top_by_session": _top_by_key(top, "session_name"),
    }
    json_path, md_path = _write_outputs(output_dir, summary=summary, write_latest=bool(args.write_latest))
    print(json.dumps({"summary_json": str(json_path), "report_md": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
