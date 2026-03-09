#!/usr/bin/env python3
"""Run one BTC5 autoresearch cycle and optionally promote a better profile."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo import (  # noqa: E402
    GuardrailProfile,
    _safe_float,
    assemble_observed_rows,
    build_summary,
)


DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BASE_ENV = Path("config/btc5_strategy.env")
DEFAULT_OVERRIDE_ENV = Path("state/btc5_autoresearch.env")
DEFAULT_REPORT_DIR = Path("reports/btc5_autoresearch")
DEFAULT_SERVICE_NAME = "btc-5min-maker.service"


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
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _merged_strategy_env(base_env: Path, override_env: Path) -> dict[str, str]:
    merged = _load_env_file(base_env)
    merged.update(_load_env_file(override_env))
    return merged


def _profile_from_env(name: str, env: dict[str, str]) -> GuardrailProfile:
    return GuardrailProfile(
        name=name,
        max_abs_delta=_safe_float(env.get("BTC5_MAX_ABS_DELTA"), 0.0) or None,
        up_max_buy_price=_safe_float(env.get("BTC5_UP_MAX_BUY_PRICE"), 0.0) or None,
        down_max_buy_price=_safe_float(env.get("BTC5_DOWN_MAX_BUY_PRICE"), 0.0) or None,
        note="loaded from strategy env",
    )


def _arr_for_candidate(candidate: dict[str, Any] | None) -> dict[str, float]:
    continuation = (candidate or {}).get("continuation") or {}
    return {
        "historical_arr_pct": _safe_float(continuation.get("historical_arr_pct"), 0.0),
        "median_arr_pct": _safe_float(continuation.get("median_arr_pct"), 0.0),
        "p05_arr_pct": _safe_float(continuation.get("p05_arr_pct"), 0.0),
    }


def _arr_tracking(best: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    best_arr = _arr_for_candidate(best)
    current_arr = _arr_for_candidate(current)
    return {
        "metric_name": "continuation_arr_pct",
        "current_historical_arr_pct": round(current_arr["historical_arr_pct"], 4),
        "current_median_arr_pct": round(current_arr["median_arr_pct"], 4),
        "current_p05_arr_pct": round(current_arr["p05_arr_pct"], 4),
        "best_historical_arr_pct": round(best_arr["historical_arr_pct"], 4),
        "best_median_arr_pct": round(best_arr["median_arr_pct"], 4),
        "best_p05_arr_pct": round(best_arr["p05_arr_pct"], 4),
        "historical_arr_delta_pct": round(best_arr["historical_arr_pct"] - current_arr["historical_arr_pct"], 4),
        "median_arr_delta_pct": round(best_arr["median_arr_pct"] - current_arr["median_arr_pct"], 4),
        "p05_arr_delta_pct": round(best_arr["p05_arr_pct"] - current_arr["p05_arr_pct"], 4),
    }


def _find_candidate(summary: dict[str, Any], name: str) -> dict[str, Any] | None:
    for candidate in summary.get("candidates") or []:
        if candidate.get("profile", {}).get("name") == name:
            return candidate
    return None


def _promotion_decision(
    *,
    best: dict[str, Any] | None,
    current: dict[str, Any] | None,
    min_median_arr_improvement_pct: float,
    min_median_pnl_improvement_usd: float,
    min_replay_pnl_improvement_usd: float,
    max_profit_prob_drop: float,
    max_p95_drawdown_increase_usd: float,
    max_loss_hit_prob_increase: float,
    min_fill_lift: int,
) -> dict[str, Any]:
    if best is None or current is None:
        return {"action": "hold", "reason": "missing_candidate_data"}

    best_profile = best.get("profile") or {}
    current_profile = current.get("profile") or {}
    if (
        best_profile.get("max_abs_delta") == current_profile.get("max_abs_delta")
        and best_profile.get("up_max_buy_price") == current_profile.get("up_max_buy_price")
        and best_profile.get("down_max_buy_price") == current_profile.get("down_max_buy_price")
    ):
        return {"action": "hold", "reason": "current_profile_is_best"}

    best_hist = best.get("historical") or {}
    current_hist = current.get("historical") or {}
    best_mc = best.get("monte_carlo") or {}
    current_mc = current.get("monte_carlo") or {}
    best_arr = _arr_for_candidate(best)
    current_arr = _arr_for_candidate(current)

    median_arr_delta = best_arr["median_arr_pct"] - current_arr["median_arr_pct"]
    median_pnl_delta = _safe_float(best_mc.get("median_total_pnl_usd")) - _safe_float(
        current_mc.get("median_total_pnl_usd")
    )
    replay_pnl_delta = _safe_float(best_hist.get("replay_live_filled_pnl_usd")) - _safe_float(
        current_hist.get("replay_live_filled_pnl_usd")
    )
    profit_prob_delta = _safe_float(best_mc.get("profit_probability")) - _safe_float(
        current_mc.get("profit_probability")
    )
    p95_drawdown_delta = _safe_float(best_mc.get("p95_max_drawdown_usd")) - _safe_float(
        current_mc.get("p95_max_drawdown_usd")
    )
    loss_hit_delta = _safe_float(best_mc.get("loss_limit_hit_probability")) - _safe_float(
        current_mc.get("loss_limit_hit_probability")
    )
    fill_lift = int(best_hist.get("replay_live_filled_rows") or 0) - int(
        current_hist.get("replay_live_filled_rows") or 0
    )

    reasons: list[str] = []
    if median_arr_delta < min_median_arr_improvement_pct:
        reasons.append(
            f"median_arr_delta_below_threshold:{median_arr_delta:.4f}<{min_median_arr_improvement_pct:.4f}"
        )
    if median_pnl_delta < min_median_pnl_improvement_usd:
        reasons.append(
            f"median_pnl_delta_below_threshold:{median_pnl_delta:.4f}<{min_median_pnl_improvement_usd:.4f}"
        )
    if replay_pnl_delta < min_replay_pnl_improvement_usd:
        reasons.append(
            f"replay_pnl_delta_below_threshold:{replay_pnl_delta:.4f}<{min_replay_pnl_improvement_usd:.4f}"
        )
    if profit_prob_delta < -abs(max_profit_prob_drop):
        reasons.append(
            f"profit_probability_drop_too_large:{profit_prob_delta:.4f}<-{abs(max_profit_prob_drop):.4f}"
        )
    if p95_drawdown_delta > max_p95_drawdown_increase_usd:
        reasons.append(
            f"drawdown_increase_too_large:{p95_drawdown_delta:.4f}>{max_p95_drawdown_increase_usd:.4f}"
        )
    if loss_hit_delta > max_loss_hit_prob_increase:
        reasons.append(
            f"loss_hit_increase_too_large:{loss_hit_delta:.4f}>{max_loss_hit_prob_increase:.4f}"
        )
    if fill_lift < min_fill_lift:
        reasons.append(f"fill_lift_below_threshold:{fill_lift}<{min_fill_lift}")

    decision = {
        "action": "promote" if not reasons else "hold",
        "reason": "promotion_thresholds_met" if not reasons else ";".join(reasons),
        "median_arr_delta_pct": round(median_arr_delta, 4),
        "historical_arr_delta_pct": round(best_arr["historical_arr_pct"] - current_arr["historical_arr_pct"], 4),
        "p05_arr_delta_pct": round(best_arr["p05_arr_pct"] - current_arr["p05_arr_pct"], 4),
        "median_pnl_delta_usd": round(median_pnl_delta, 4),
        "replay_pnl_delta_usd": round(replay_pnl_delta, 4),
        "profit_probability_delta": round(profit_prob_delta, 4),
        "p95_drawdown_delta_usd": round(p95_drawdown_delta, 4),
        "loss_hit_probability_delta": round(loss_hit_delta, 4),
        "fill_lift": int(fill_lift),
    }
    return decision


def render_strategy_env(profile: dict[str, Any], metadata: dict[str, Any]) -> str:
    lines = [
        "# Managed by scripts/run_btc5_autoresearch_cycle.py",
        f"# generated_at={metadata['generated_at']}",
        f"# candidate={profile.get('name')}",
        f"# reason={metadata['reason']}",
        f"BTC5_MAX_ABS_DELTA={profile.get('max_abs_delta')}",
        f"BTC5_UP_MAX_BUY_PRICE={profile.get('up_max_buy_price')}",
        f"BTC5_DOWN_MAX_BUY_PRICE={profile.get('down_max_buy_price')}",
        f"BTC5_PROBE_MAX_ABS_DELTA={profile.get('max_abs_delta')}",
        f"BTC5_PROBE_UP_MAX_BUY_PRICE={profile.get('up_max_buy_price')}",
        f"BTC5_PROBE_DOWN_MAX_BUY_PRICE={profile.get('down_max_buy_price')}",
    ]
    return "\n".join(lines) + "\n"


def _write_override_env(path: Path, *, best_profile: dict[str, Any], decision: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_strategy_env(
            best_profile,
            {
                "generated_at": _now_utc().isoformat(),
                "reason": decision.get("reason"),
            },
        )
    )


def _restart_service(service_name: str) -> dict[str, Any]:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    active = subprocess.run(
        ["sudo", "systemctl", "is-active", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return {
        "restart_returncode": result.returncode,
        "restart_stderr_tail": (result.stderr or "").strip()[-300:],
        "restart_stdout_tail": (result.stdout or "").strip()[-300:],
        "service_state": (active.stdout or "").strip(),
    }


def _write_reports(report_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    json_path = report_dir / f"cycle_{stamp}.json"
    latest_json = report_dir / "latest.json"
    latest_md = report_dir / "latest.md"
    artifacts = {
        "cycle_json": str(json_path),
        "latest_json": str(latest_json),
        "latest_md": str(latest_md),
    }
    json_payload = dict(payload, artifacts=artifacts)
    md_lines = [
        "# BTC5 Autoresearch Cycle",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Action: `{payload['decision']['action']}`",
        f"- Reason: `{payload['decision']['reason']}`",
        f"- Active profile: `{payload['active_profile']['name']}`",
        f"- Best profile: `{payload['best_candidate']['profile']['name'] if payload.get('best_candidate') else 'none'}`",
        f"- Observed window rows: `{payload['simulation_summary']['input']['observed_window_rows']}`",
        f"- Observed live-filled rows: `{payload['simulation_summary']['input']['live_filled_rows']}`",
        "",
        "## Deltas",
        "",
        f"- Median continuation ARR delta: `{payload['decision'].get('median_arr_delta_pct', 0.0):.2f}` percentage points",
        f"- Historical continuation ARR delta: `{payload['decision'].get('historical_arr_delta_pct', 0.0):.2f}` percentage points",
        f"- P05 continuation ARR delta: `{payload['decision'].get('p05_arr_delta_pct', 0.0):.2f}` percentage points",
        f"- Replay PnL delta: `{payload['decision'].get('replay_pnl_delta_usd', 0.0):.4f}` USD",
        f"- Median Monte Carlo PnL delta: `{payload['decision'].get('median_pnl_delta_usd', 0.0):.4f}` USD",
        f"- Profit-probability delta: `{payload['decision'].get('profit_probability_delta', 0.0):.2%}`",
        f"- P95 drawdown delta: `{payload['decision'].get('p95_drawdown_delta_usd', 0.0):.4f}` USD",
        f"- Loss-hit delta: `{payload['decision'].get('loss_hit_probability_delta', 0.0):.2%}`",
        "",
        "## Best Candidate",
        "",
        json.dumps(payload.get("best_candidate") or {}, indent=2, sort_keys=True),
    ]
    json_path.write_text(json.dumps(json_payload, indent=2, sort_keys=True) + "\n")
    latest_json.write_text(json.dumps(json_payload, indent=2, sort_keys=True) + "\n")
    latest_md.write_text("\n".join(md_lines) + "\n")
    return artifacts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--strategy-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--override-env", type=Path, default=DEFAULT_OVERRIDE_ENV)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--top-grid-candidates", type=int, default=5)
    parser.add_argument("--min-replay-fills", type=int, default=12)
    parser.add_argument("--loss-limit-usd", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--restart-on-promote", action="store_true")
    parser.add_argument("--include-archive-csvs", action="store_true")
    parser.add_argument("--archive-glob", default="reports/btc_intraday_llm_bundle_*/raw/remote_btc5_window_trades.csv")
    parser.add_argument("--refresh-remote", action="store_true")
    parser.add_argument("--remote-cache-json", type=Path, default=Path("reports/tmp_remote_btc5_window_rows.json"))
    parser.add_argument("--min-median-arr-improvement-pct", type=float, default=0.0)
    parser.add_argument("--min-median-pnl-improvement-usd", type=float, default=2.0)
    parser.add_argument("--min-replay-pnl-improvement-usd", type=float, default=1.0)
    parser.add_argument("--max-profit-prob-drop", type=float, default=0.01)
    parser.add_argument("--max-p95-drawdown-increase-usd", type=float, default=3.0)
    parser.add_argument("--max-loss-hit-prob-increase", type=float, default=0.03)
    parser.add_argument("--min-fill-lift", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_env = _load_env_file(args.strategy_env)
    merged_env = _merged_strategy_env(args.strategy_env, args.override_env)
    active_profile = _profile_from_env("current_live_profile", merged_env)
    runtime_profile = _profile_from_env("runtime_recommended", merged_env)

    rows, baseline = assemble_observed_rows(
        db_path=args.db_path,
        include_archive_csvs=bool(args.include_archive_csvs),
        archive_glob=str(args.archive_glob),
        refresh_remote=bool(args.refresh_remote),
        remote_cache_json=args.remote_cache_json,
    )
    horizon_trades = max(len(rows), 40)
    summary = build_summary(
        rows=rows,
        db_path=args.db_path,
        current_live_profile=active_profile,
        runtime_recommended_profile=runtime_profile,
        paths=max(1, int(args.paths)),
        horizon_trades=horizon_trades,
        block_size=max(1, int(args.block_size)),
        loss_limit_usd=float(args.loss_limit_usd),
        seed=int(args.seed),
        top_grid_candidates=max(1, int(args.top_grid_candidates)),
        min_replay_fills=max(1, int(args.min_replay_fills)),
    )
    summary["baseline"] = baseline

    best_candidate = summary.get("best_candidate")
    current_candidate = _find_candidate(summary, "current_live_profile")
    decision = _promotion_decision(
        best=best_candidate,
        current=current_candidate,
        min_median_arr_improvement_pct=float(args.min_median_arr_improvement_pct),
        min_median_pnl_improvement_usd=float(args.min_median_pnl_improvement_usd),
        min_replay_pnl_improvement_usd=float(args.min_replay_pnl_improvement_usd),
        max_profit_prob_drop=float(args.max_profit_prob_drop),
        max_p95_drawdown_increase_usd=float(args.max_p95_drawdown_increase_usd),
        max_loss_hit_prob_increase=float(args.max_loss_hit_prob_increase),
        min_fill_lift=int(args.min_fill_lift),
    )

    restart_result: dict[str, Any] | None = None
    if decision["action"] == "promote" and best_candidate is not None:
        _write_override_env(
            args.override_env,
            best_profile=best_candidate.get("profile") or {},
            decision=decision,
        )
        if args.restart_on_promote:
            restart_result = _restart_service(str(args.service_name))

    payload = {
        "generated_at": _now_utc().isoformat(),
        "base_strategy_env": str(args.strategy_env),
        "override_env": str(args.override_env),
        "base_strategy_values": base_env,
        "active_profile": {
            "name": active_profile.name,
            "max_abs_delta": active_profile.max_abs_delta,
            "up_max_buy_price": active_profile.up_max_buy_price,
            "down_max_buy_price": active_profile.down_max_buy_price,
        },
        "decision": decision,
        "arr_tracking": _arr_tracking(best_candidate, current_candidate),
        "best_candidate": best_candidate,
        "current_candidate": current_candidate,
        "simulation_summary": summary,
        "service_restart": restart_result,
    }
    artifacts = _write_reports(args.report_dir, payload)
    payload["artifacts"] = artifacts
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
