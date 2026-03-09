#!/usr/bin/env python3
"""Empirical BTC5 Monte Carlo engine for guardrail iteration."""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_REMOTE_DB = REPORTS_DIR / "tmp_remote_btc_5min_maker.db"
DEFAULT_LOCAL_DB = REPO_ROOT / "data" / "btc_5min_maker.db"
DEFAULT_RUNTIME_TRUTH = REPORTS_DIR / "runtime_truth_latest.json"
DEFAULT_UP_MAX = 0.49
DEFAULT_DOWN_MAX = 0.51
DEFAULT_MAX_ABS_DELTA = 0.00015
DEFAULT_LOSS_LIMIT_USD = 10.0


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


def load_live_filled_rows(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"BTC5 DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                direction,
                delta,
                order_price,
                trade_size_usd,
                won,
                pnl_usd,
                updated_at
            FROM window_trades
            WHERE order_status = 'live_filled'
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    live_rows: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["id"] = _safe_int(payload.get("id"))
        payload["direction"] = str(payload.get("direction") or "").strip().upper()
        payload["delta"] = _safe_float(payload.get("delta"), 0.0)
        payload["abs_delta"] = abs(payload["delta"])
        payload["order_price"] = _safe_float(payload.get("order_price"), 0.0)
        payload["trade_size_usd"] = _safe_float(payload.get("trade_size_usd"), 0.0)
        payload["won"] = bool(payload.get("won"))
        payload["pnl_usd"] = _safe_float(payload.get("pnl_usd"), 0.0)
        payload["updated_at"] = payload.get("updated_at")
        live_rows.append(payload)
    return live_rows


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
    wins = sum(1 for row in matched if _safe_float(row.get("pnl_usd"), 0.0) > 0)
    total_rows = len(rows)
    matched_rows = len(matched)
    replay_pnl = sum(_safe_float(row.get("pnl_usd"), 0.0) for row in matched)
    total_notional = sum(_safe_float(row.get("trade_size_usd"), 0.0) for row in matched)
    return _round_metrics(
        {
            "baseline_live_filled_rows": total_rows,
            "replay_live_filled_rows": matched_rows,
            "coverage_ratio": (matched_rows / total_rows) if total_rows else 0.0,
            "replay_live_filled_pnl_usd": replay_pnl,
            "avg_pnl_usd": (replay_pnl / matched_rows) if matched_rows else 0.0,
            "win_rate": (wins / matched_rows) if matched_rows else 0.0,
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
    series = [
        _safe_float(row.get("pnl_usd"), 0.0) if row_matches_profile(row, profile) else 0.0
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
            "active_trade_ratio": 0.0,
            "mean_total_pnl_usd": 0.0,
            "median_total_pnl_usd": 0.0,
            "p05_total_pnl_usd": 0.0,
            "p95_total_pnl_usd": 0.0,
            "avg_max_drawdown_usd": 0.0,
            "p95_max_drawdown_usd": 0.0,
            "loss_limit_hit_probability": 0.0,
            "avg_active_trades": 0.0,
            "avg_win_rate": 0.0,
            "ranking_score": 0.0,
        }

    rng = random.Random(f"{seed}:{_profile_key(profile)}")
    total_pnls: list[float] = []
    max_drawdowns: list[float] = []
    active_counts: list[int] = []
    win_rates: list[float] = []
    loss_limit_hits = 0

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
        wins = 0
        loss_limit_hit = False

        for pnl in path:
            if abs(pnl) > 1e-12:
                active_trades += 1
                if pnl > 0:
                    wins += 1
            running_pnl += pnl
            peak_pnl = max(peak_pnl, running_pnl)
            max_drawdown = max(max_drawdown, peak_pnl - running_pnl)
            if running_pnl <= -abs(loss_limit_usd):
                loss_limit_hit = True

        if loss_limit_hit:
            loss_limit_hits += 1
        total_pnls.append(running_pnl)
        max_drawdowns.append(max_drawdown)
        active_counts.append(active_trades)
        win_rates.append((wins / active_trades) if active_trades else 0.0)

    profit_probability = sum(1 for value in total_pnls if value > 0) / len(total_pnls)
    avg_active_trades = sum(active_counts) / len(active_counts)
    avg_win_rate = sum(win_rates) / len(win_rates)
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
            "avg_active_trades": avg_active_trades,
            "avg_win_rate": avg_win_rate,
            "ranking_score": ranking_score,
        }
    )


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# BTC5 Monte Carlo Report",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Source DB: `{summary['db_path']}`",
        f"- Live-filled sample rows: `{summary['input']['live_filled_rows']}`",
        f"- Observed realized PnL: `{summary['input']['observed_pnl_usd']:.4f}` USD",
        f"- Monte Carlo paths: `{summary['simulation']['paths']}`",
        f"- Horizon trades per path: `{summary['simulation']['horizon_trades']}`",
        f"- Bootstrap block size: `{summary['simulation']['block_size']}`",
        "",
        "## Candidate Ranking",
        "",
        "| Rank | Profile | Replay PnL | Replay Fills | MC Median PnL | Profit Prob | P95 Drawdown | Loss-Limit Hit |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for index, candidate in enumerate(summary["candidates"], start=1):
        historical = candidate["historical"]
        monte_carlo = candidate["monte_carlo"]
        lines.append(
            "| "
            + f"{index} | {candidate['profile']['name']} | "
            + f"{historical['replay_live_filled_pnl_usd']:.4f} | "
            + f"{historical['replay_live_filled_rows']} | "
            + f"{monte_carlo['median_total_pnl_usd']:.4f} | "
            + f"{monte_carlo['profit_probability']:.2%} | "
            + f"{monte_carlo['p95_max_drawdown_usd']:.4f} | "
            + f"{monte_carlo['loss_limit_hit_probability']:.2%} |"
        )

    best = summary["best_candidate"]
    comparison = summary.get("best_vs_current") or {}
    lines.extend(
        [
            "",
            "## Best Candidate",
            "",
            f"- Name: `{best['profile']['name']}`",
            f"- Max abs delta: `{best['profile']['max_abs_delta']}`",
            f"- UP max buy price: `{best['profile']['up_max_buy_price']}`",
            f"- DOWN max buy price: `{best['profile']['down_max_buy_price']}`",
            f"- Replay PnL: `{best['historical']['replay_live_filled_pnl_usd']:.4f}` USD on `{best['historical']['replay_live_filled_rows']}` fills",
            f"- Monte Carlo median PnL: `{best['monte_carlo']['median_total_pnl_usd']:.4f}` USD",
            f"- Monte Carlo profit probability: `{best['monte_carlo']['profit_probability']:.2%}`",
            f"- Monte Carlo P95 drawdown: `{best['monte_carlo']['p95_max_drawdown_usd']:.4f}` USD",
            "",
            "## Best vs Current Live",
            "",
            f"- Best candidate: `{comparison.get('best_candidate_name')}`",
            f"- Current live candidate: `{comparison.get('current_candidate_name')}`",
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
        evaluated.append(
            {
                "profile": asdict(profile),
                "historical": historical,
                "monte_carlo": monte_carlo,
            }
        )

    evaluated.sort(
        key=lambda candidate: (
            _safe_float(candidate["monte_carlo"].get("median_total_pnl_usd"), 0.0),
            _safe_float(candidate["monte_carlo"].get("profit_probability"), 0.0),
            -_safe_float(candidate["monte_carlo"].get("p95_max_drawdown_usd"), 0.0),
            _safe_float(candidate["historical"].get("replay_live_filled_pnl_usd"), 0.0),
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

    return {
        "generated_at": _now_utc().isoformat(),
        "db_path": str(db_path),
        "input": {
            "live_filled_rows": len(rows),
            "observed_pnl_usd": round(sum(_safe_float(row.get("pnl_usd"), 0.0) for row in rows), 4),
        },
        "simulation": {
            "paths": int(paths),
            "horizon_trades": int(horizon_trades),
            "block_size": int(block_size),
            "loss_limit_usd": round(loss_limit_usd, 4),
            "seed": int(seed),
        },
        "current_live_profile": asdict(current_live_profile),
        "runtime_recommended_profile": asdict(runtime_recommended_profile),
        "candidates": evaluated,
        "best_candidate": best_candidate,
        "best_vs_current": best_vs_current,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=None, help="Path to BTC5 SQLite DB.")
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
    rows = load_live_filled_rows(db_path)
    if not rows:
        raise SystemExit(f"No live_filled BTC5 rows found in {db_path}")

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
        paths=max(1, int(args.paths)),
        horizon_trades=horizon_trades,
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        top_grid_candidates=max(1, int(args.top_grid_candidates)),
        min_replay_fills=max(1, int(args.min_replay_fills)),
    )
    json_path, md_path = _write_outputs(output_dir, summary=summary, write_latest=bool(args.write_latest))
    print(json.dumps({"summary_json": str(json_path), "report_md": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
