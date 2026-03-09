#!/usr/bin/env python3
"""Run the BTC5 autoresearch cycle continuously on the local machine."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path("data/btc_5min_maker.db")
DEFAULT_BASE_ENV = Path("config/btc5_strategy.env")
DEFAULT_OVERRIDE_ENV = Path("state/btc5_autoresearch.env")
DEFAULT_CYCLE_REPORT_DIR = Path("reports/btc5_autoresearch")
DEFAULT_LOOP_REPORT_DIR = Path("reports/btc5_autoresearch_loop")
DEFAULT_ARR_TSV = Path("research/btc5_arr_progress.tsv")
DEFAULT_ARR_SVG = Path("research/btc5_arr_progress.svg")
DEFAULT_ARR_SUMMARY_MD = Path("research/btc5_arr_summary.md")
DEFAULT_ARR_LATEST_JSON = Path("research/btc5_arr_latest.json")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_cycle_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_btc5_autoresearch_cycle.py"),
        "--db-path",
        str(args.db_path),
        "--strategy-env",
        str(args.strategy_env),
        "--override-env",
        str(args.override_env),
        "--report-dir",
        str(args.cycle_report_dir),
        "--paths",
        str(args.paths),
        "--block-size",
        str(args.block_size),
        "--top-grid-candidates",
        str(args.top_grid_candidates),
        "--min-replay-fills",
        str(args.min_replay_fills),
        "--loss-limit-usd",
        str(args.loss_limit_usd),
        "--seed",
        str(args.seed),
        "--archive-glob",
        str(args.archive_glob),
        "--remote-cache-json",
        str(args.remote_cache_json),
        "--min-median-arr-improvement-pct",
        str(args.min_median_arr_improvement_pct),
        "--min-median-pnl-improvement-usd",
        str(args.min_median_pnl_improvement_usd),
        "--min-replay-pnl-improvement-usd",
        str(args.min_replay_pnl_improvement_usd),
        "--max-profit-prob-drop",
        str(args.max_profit_prob_drop),
        "--max-p95-drawdown-increase-usd",
        str(args.max_p95_drawdown_increase_usd),
        "--max-loss-hit-prob-increase",
        str(args.max_loss_hit_prob_increase),
        "--min-fill-lift",
        str(args.min_fill_lift),
    ]
    if args.service_name:
        cmd.extend(["--service-name", str(args.service_name)])
    if args.include_archive_csvs:
        cmd.append("--include-archive-csvs")
    if args.refresh_remote:
        cmd.append("--refresh-remote")
    if args.restart_on_promote:
        cmd.append("--restart-on-promote")
    return cmd


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _run_hook(command: str) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
    }


def _render_arr_progress(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "render_btc5_arr_progress.py"),
        "--history-jsonl",
        str(args.loop_report_dir / "history.jsonl"),
        "--tsv-out",
        str(args.arr_tsv_out),
        "--svg-out",
        str(args.arr_svg_out),
        "--summary-md-out",
        str(args.arr_summary_md_out),
        "--latest-json-out",
        str(args.arr_latest_json_out),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
    }


def _build_entry(
    *,
    cycle_command: list[str],
    cycle_result: subprocess.CompletedProcess[str],
    cycle_payload: dict[str, Any] | None,
    started_at: datetime,
    finished_at: datetime,
    hook_result: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = (cycle_payload or {}).get("decision") or {}
    best_profile = ((cycle_payload or {}).get("best_candidate") or {}).get("profile") or {}
    active_profile = (cycle_payload or {}).get("active_profile") or {}
    arr = (cycle_payload or {}).get("arr_tracking") or {}
    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "cycle_command": cycle_command,
        "cycle_returncode": cycle_result.returncode,
        "status": "ok" if cycle_result.returncode == 0 and cycle_payload else "error",
        "decision": decision,
        "best_profile": best_profile,
        "active_profile": active_profile,
        "arr": {
            "active_median_arr_pct": arr.get("current_median_arr_pct"),
            "best_median_arr_pct": arr.get("best_median_arr_pct"),
            "median_arr_delta_pct": arr.get("median_arr_delta_pct"),
            "active_p05_arr_pct": arr.get("current_p05_arr_pct"),
            "best_p05_arr_pct": arr.get("best_p05_arr_pct"),
            "historical_arr_delta_pct": arr.get("historical_arr_delta_pct"),
        },
        "artifacts": (cycle_payload or {}).get("artifacts") or {},
        "hook": hook_result,
        "stdout_tail": (cycle_result.stdout or "").strip()[-1000:],
        "stderr_tail": (cycle_result.stderr or "").strip()[-1000:],
    }


def _write_loop_reports(loop_report_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    loop_report_dir.mkdir(parents=True, exist_ok=True)
    latest_path = loop_report_dir / "latest.json"
    latest_md_path = loop_report_dir / "latest.md"
    history_path = loop_report_dir / "history.jsonl"
    previous = _load_json(latest_path) or {}
    previous_summary = previous.get("summary") or {}
    summary = {
        "cycles_total": int(previous_summary.get("cycles_total") or 0) + 1,
        "holds_total": int(previous_summary.get("holds_total") or 0)
        + (1 if entry.get("decision", {}).get("action") == "hold" else 0),
        "promotions_total": int(previous_summary.get("promotions_total") or 0)
        + (1 if entry.get("decision", {}).get("action") == "promote" else 0),
        "errors_total": int(previous_summary.get("errors_total") or 0)
        + (1 if entry.get("status") != "ok" else 0),
        "last_cycle_started_at": entry["started_at"],
        "last_cycle_finished_at": entry["finished_at"],
    }
    payload = {"summary": summary, "latest_entry": entry}
    latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    latest_md_path.write_text(
        "\n".join(
            [
                "# BTC5 Local Autoresearch Loop",
                "",
                f"- Cycles total: `{summary['cycles_total']}`",
                f"- Promotions total: `{summary['promotions_total']}`",
                f"- Holds total: `{summary['holds_total']}`",
                f"- Errors total: `{summary['errors_total']}`",
                f"- Last status: `{entry['status']}`",
                f"- Last action: `{entry.get('decision', {}).get('action', 'error')}`",
                f"- Last reason: `{entry.get('decision', {}).get('reason', 'cycle_failed')}`",
                f"- Last best profile: `{entry.get('best_profile', {}).get('name', 'none')}`",
                f"- Last active profile: `{entry.get('active_profile', {}).get('name', 'none')}`",
                f"- Last finished at: `{entry['finished_at']}`",
            ]
        )
        + "\n"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--strategy-env", type=Path, default=DEFAULT_BASE_ENV)
    parser.add_argument("--override-env", type=Path, default=DEFAULT_OVERRIDE_ENV)
    parser.add_argument("--cycle-report-dir", type=Path, default=DEFAULT_CYCLE_REPORT_DIR)
    parser.add_argument("--loop-report-dir", type=Path, default=DEFAULT_LOOP_REPORT_DIR)
    parser.add_argument("--service-name", default="")
    parser.add_argument("--paths", type=int, default=2000)
    parser.add_argument("--block-size", type=int, default=4)
    parser.add_argument("--top-grid-candidates", type=int, default=5)
    parser.add_argument("--min-replay-fills", type=int, default=12)
    parser.add_argument("--loss-limit-usd", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-archive-csvs", action="store_true")
    parser.add_argument(
        "--archive-glob",
        default="reports/btc_intraday_llm_bundle_*/raw/remote_btc5_window_trades.csv",
    )
    parser.add_argument("--refresh-remote", action="store_true")
    parser.add_argument("--remote-cache-json", type=Path, default=Path("reports/tmp_remote_btc5_window_rows.json"))
    parser.add_argument("--min-median-arr-improvement-pct", type=float, default=0.0)
    parser.add_argument("--min-median-pnl-improvement-usd", type=float, default=2.0)
    parser.add_argument("--min-replay-pnl-improvement-usd", type=float, default=1.0)
    parser.add_argument("--max-profit-prob-drop", type=float, default=0.01)
    parser.add_argument("--max-p95-drawdown-increase-usd", type=float, default=3.0)
    parser.add_argument("--max-loss-hit-prob-increase", type=float, default=0.03)
    parser.add_argument("--min-fill-lift", type=int, default=0)
    parser.add_argument("--restart-on-promote", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--on-promote-command", default="")
    parser.add_argument("--arr-tsv-out", type=Path, default=DEFAULT_ARR_TSV)
    parser.add_argument("--arr-svg-out", type=Path, default=DEFAULT_ARR_SVG)
    parser.add_argument("--arr-summary-md-out", type=Path, default=DEFAULT_ARR_SUMMARY_MD)
    parser.add_argument("--arr-latest-json-out", type=Path, default=DEFAULT_ARR_LATEST_JSON)
    parser.add_argument("--skip-arr-render", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cycle_count = 0
    while True:
        started_at = _now_utc()
        cycle_command = _build_cycle_command(args)
        cycle_result = subprocess.run(
            cycle_command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        cycle_payload = _load_json(args.cycle_report_dir / "latest.json")
        hook_result = None
        if (
            cycle_result.returncode == 0
            and cycle_payload
            and (cycle_payload.get("decision") or {}).get("action") == "promote"
            and args.on_promote_command
        ):
            hook_result = _run_hook(args.on_promote_command)
        finished_at = _now_utc()
        entry = _build_entry(
            cycle_command=cycle_command,
            cycle_result=cycle_result,
            cycle_payload=cycle_payload,
            started_at=started_at,
            finished_at=finished_at,
            hook_result=hook_result,
        )
        loop_payload = _write_loop_reports(args.loop_report_dir, entry)
        if not args.skip_arr_render:
            loop_payload["arr_render"] = _render_arr_progress(args)
        print(json.dumps(loop_payload, indent=2, sort_keys=True))
        cycle_count += 1
        if args.max_cycles and cycle_count >= args.max_cycles:
            return 0
        sleep_seconds = max(0.0, float(args.interval_seconds) - (finished_at - started_at).total_seconds())
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
