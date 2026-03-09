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
    DEFAULT_LOSS_LIMIT_USD,
    DEFAULT_REMOTE_ROWS_JSON,
    REPORTS_DIR,
    _percentile,
    _round_metrics,
    _safe_float,
    _safe_int,
    assemble_observed_rows,
    summarize_continuation_arr,
)


DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_REPORT_DIR = Path("reports/btc5_hypothesis_lab")
ET_ZONE = ZoneInfo("America/New_York")
SESSION_FILTERS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("any", tuple()),
    ("open_et", (9, 10, 11)),
    ("midday_et", (12, 13)),
    ("late_et", (14, 15, 16)),
)


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


def _window_dt_et(row: dict[str, Any]) -> datetime | None:
    window_start_ts = _safe_int(row.get("window_start_ts"), 0)
    if window_start_ts > 0:
        return datetime.fromtimestamp(window_start_ts, tz=timezone.utc).astimezone(ET_ZONE)
    updated_at = _parse_iso(row.get("updated_at"))
    if updated_at is not None:
        return updated_at.astimezone(ET_ZONE)
    return None


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
            for max_abs_delta in (None, 0.00005, 0.00010, 0.00015):
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


def _render_markdown(summary: dict[str, Any]) -> str:
    top = summary.get("top_hypotheses") or []
    best = summary.get("best_hypothesis") or {}
    lines = [
        "# BTC5 Hypothesis Lab",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Source rows: `{summary['input']['observed_window_rows']}` total, `{summary['input']['priced_window_rows']}` priced observations",
        f"- Candidate pool: `{summary['input']['generated_candidates']}` generated, `{summary['input']['walk_forward_candidates']}` walk-forward validated",
        f"- Validation metric: `{summary['metric_name']}`",
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
    parser.add_argument("--output-dir", type=Path, default=None)
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
    rows, baseline = assemble_observed_rows(
        db_path=args.db_path,
        include_archive_csvs=bool(args.include_archive_csvs),
        archive_glob=str(args.archive_glob),
        refresh_remote=bool(args.refresh_remote),
        remote_cache_json=args.remote_cache_json,
    )
    enriched_priced_rows = priced_rows(rows)
    if not enriched_priced_rows:
        raise SystemExit("No priced BTC5 observations available for the hypothesis lab.")
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
    output_dir = args.output_dir or (REPORTS_DIR / f"btc5_hypothesis_lab_{_stamp()}")
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
        "best_hypothesis": top[0] if top else None,
        "top_hypotheses": top,
        "top_by_direction": _top_by_key(top, "direction"),
        "top_by_session": _top_by_key(top, "session_name"),
    }
    json_path, md_path = _write_outputs(output_dir, summary=summary, write_latest=bool(args.write_latest))
    print(json.dumps({"summary_json": str(json_path), "report_md": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
