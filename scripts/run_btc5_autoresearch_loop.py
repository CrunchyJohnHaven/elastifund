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
DEFAULT_HYPOTHESIS_REPORT_DIR = Path("reports/btc5_hypothesis_lab")
DEFAULT_REGIME_POLICY_REPORT_DIR = Path("reports/btc5_regime_policy_lab")
DEFAULT_ARR_TSV = Path("research/btc5_arr_progress.tsv")
DEFAULT_ARR_SVG = Path("research/btc5_arr_progress.svg")
DEFAULT_ARR_SUMMARY_MD = Path("research/btc5_arr_summary.md")
DEFAULT_ARR_LATEST_JSON = Path("research/btc5_arr_latest.json")
DEFAULT_HYPOTHESIS_FRONTIER_TSV = Path("research/btc5_hypothesis_frontier.tsv")
DEFAULT_HYPOTHESIS_FRONTIER_SVG = Path("research/btc5_hypothesis_frontier.svg")
DEFAULT_HYPOTHESIS_FRONTIER_SUMMARY_MD = Path("research/btc5_hypothesis_frontier_summary.md")
DEFAULT_HYPOTHESIS_FRONTIER_LATEST_JSON = Path("research/btc5_hypothesis_frontier_latest.json")


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
        "--min-fill-retention-ratio",
        str(args.min_fill_retention_ratio),
        "--regime-max-session-overrides",
        str(args.regime_max_session_overrides),
        "--regime-top-single-overrides-per-session",
        str(args.regime_top_single_overrides_per_session),
        "--regime-max-composed-candidates",
        str(args.regime_max_composed_candidates),
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


def _run_hypothesis_lab(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "btc5_hypothesis_lab.py"),
        "--db-path",
        str(args.db_path),
        "--output-dir",
        str(args.hypothesis_report_dir),
        "--paths",
        str(args.paths),
        "--block-size",
        str(args.block_size),
        "--loss-limit-usd",
        str(args.loss_limit_usd),
        "--seed",
        str(args.seed),
    ]
    if args.include_archive_csvs:
        command.append("--include-archive-csvs")
    if args.refresh_remote:
        command.append("--refresh-remote")
    command.extend(["--archive-glob", str(args.archive_glob)])
    command.extend(["--remote-cache-json", str(args.remote_cache_json)])
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=240,
    )
    latest_summary = _load_json(args.hypothesis_report_dir / "summary.json")
    best_hypothesis = (latest_summary or {}).get("best_hypothesis") or {}
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
        "best_hypothesis": (best_hypothesis.get("hypothesis") or {}),
        "best_summary": (best_hypothesis.get("summary") or {}),
        "recommended_session_policy": (latest_summary or {}).get("recommended_session_policy") or [],
    }


def _run_regime_policy_lab(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "btc5_regime_policy_lab.py"),
        "--db-path",
        str(args.db_path),
        "--strategy-env",
        str(args.strategy_env),
        "--override-env",
        str(args.override_env),
        "--output-dir",
        str(args.regime_policy_report_dir),
        "--paths",
        str(args.paths),
        "--block-size",
        str(args.block_size),
        "--loss-limit-usd",
        str(args.loss_limit_usd),
        "--seed",
        str(args.seed),
        "--min-replay-fills",
        str(args.min_replay_fills),
    ]
    if args.include_archive_csvs:
        command.append("--include-archive-csvs")
    if args.refresh_remote:
        command.append("--refresh-remote")
    command.extend(["--archive-glob", str(args.archive_glob)])
    command.extend(["--remote-cache-json", str(args.remote_cache_json)])
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=240,
    )
    latest_summary = _load_json(args.regime_policy_report_dir / "summary.json")
    best_policy = (latest_summary or {}).get("best_policy") or {}
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": (result.stdout or "").strip()[-500:],
        "stderr_tail": (result.stderr or "").strip()[-500:],
        "best_policy": (best_policy.get("policy") or {}),
        "best_summary": {
            "continuation": (best_policy.get("continuation") or {}),
            "historical": (best_policy.get("historical") or {}),
            "monte_carlo": (best_policy.get("monte_carlo") or {}),
        },
        "recommended_session_policy": (latest_summary or {}).get("recommended_session_policy") or [],
    }


def _render_hypothesis_frontier(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "render_btc5_hypothesis_frontier.py"),
        "--history-jsonl",
        str(args.loop_report_dir / "history.jsonl"),
        "--tsv-out",
        str(args.hypothesis_frontier_tsv_out),
        "--svg-out",
        str(args.hypothesis_frontier_svg_out),
        "--summary-md-out",
        str(args.hypothesis_frontier_summary_md_out),
        "--latest-json-out",
        str(args.hypothesis_frontier_latest_json_out),
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
    package_confidence_reasons = list((cycle_payload or {}).get("package_confidence_reasons") or [])
    package_missing_evidence = list((cycle_payload or {}).get("package_missing_evidence") or [])
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
            "replay_pnl_delta_usd": decision.get("replay_pnl_delta_usd"),
            "profit_probability_delta": decision.get("profit_probability_delta"),
            "fill_lift": decision.get("fill_lift"),
        },
        "active_runtime_package": (cycle_payload or {}).get("active_runtime_package") or {},
        "best_runtime_package": (cycle_payload or {}).get("best_runtime_package") or {},
        "deploy_recommendation": (cycle_payload or {}).get("deploy_recommendation") or "hold",
        "package_confidence_label": (cycle_payload or {}).get("package_confidence_label") or "low",
        "package_confidence_reasons": package_confidence_reasons,
        "package_missing_evidence": package_missing_evidence,
        "validation_live_filled_rows": int((cycle_payload or {}).get("validation_live_filled_rows") or 0),
        "generalization_ratio": float((cycle_payload or {}).get("generalization_ratio") or 0.0),
        "recommended_session_policy": (cycle_payload or {}).get("recommended_session_policy") or [],
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
                f"- Last best hypothesis: `{((entry.get('hypothesis_lab') or {}).get('best_hypothesis') or {}).get('name', 'none')}`",
                f"- Last best regime policy: `{((entry.get('regime_policy_lab') or {}).get('best_policy') or {}).get('name', 'none')}`",
                f"- Last best session policy records: `{len(entry.get('recommended_session_policy') or [])}`",
                f"- Last package decision: `{entry.get('deploy_recommendation', 'hold')}`",
                f"- Last package confidence: `{entry.get('package_confidence_label', 'low')}`",
                f"- Last package confidence reasons: `{'; '.join(entry.get('package_confidence_reasons') or ['none'])}`",
                f"- Last missing evidence: `{'; '.join(entry.get('package_missing_evidence') or ['none'])}`",
                f"- Last best package profile: `{((entry.get('best_runtime_package') or {}).get('profile') or {}).get('name', 'none')}`",
                f"- Last active package profile: `{((entry.get('active_runtime_package') or {}).get('profile') or {}).get('name', 'none')}`",
                f"- Last best package session-policy records: `{len(((entry.get('best_runtime_package') or {}).get('session_policy') or []))}`",
                f"- Last median ARR delta: `{(entry.get('arr') or {}).get('median_arr_delta_pct', 0.0)}`",
                f"- Last replay PnL delta (USD): `{(entry.get('arr') or {}).get('replay_pnl_delta_usd', 0.0)}`",
                f"- Last profit-probability delta: `{(entry.get('arr') or {}).get('profit_probability_delta', 0.0)}`",
                f"- Last fill lift: `{(entry.get('arr') or {}).get('fill_lift', 0)}`",
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
    parser.add_argument("--hypothesis-report-dir", type=Path, default=DEFAULT_HYPOTHESIS_REPORT_DIR)
    parser.add_argument("--regime-policy-report-dir", type=Path, default=DEFAULT_REGIME_POLICY_REPORT_DIR)
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
    parser.add_argument("--min-fill-retention-ratio", type=float, default=0.85)
    parser.add_argument("--regime-max-session-overrides", type=int, default=2)
    parser.add_argument("--regime-top-single-overrides-per-session", type=int, default=2)
    parser.add_argument("--regime-max-composed-candidates", type=int, default=64)
    parser.add_argument("--restart-on-promote", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--on-promote-command", default="")
    parser.add_argument("--arr-tsv-out", type=Path, default=DEFAULT_ARR_TSV)
    parser.add_argument("--arr-svg-out", type=Path, default=DEFAULT_ARR_SVG)
    parser.add_argument("--arr-summary-md-out", type=Path, default=DEFAULT_ARR_SUMMARY_MD)
    parser.add_argument("--arr-latest-json-out", type=Path, default=DEFAULT_ARR_LATEST_JSON)
    parser.add_argument("--hypothesis-frontier-tsv-out", type=Path, default=DEFAULT_HYPOTHESIS_FRONTIER_TSV)
    parser.add_argument("--hypothesis-frontier-svg-out", type=Path, default=DEFAULT_HYPOTHESIS_FRONTIER_SVG)
    parser.add_argument(
        "--hypothesis-frontier-summary-md-out",
        type=Path,
        default=DEFAULT_HYPOTHESIS_FRONTIER_SUMMARY_MD,
    )
    parser.add_argument(
        "--hypothesis-frontier-latest-json-out",
        type=Path,
        default=DEFAULT_HYPOTHESIS_FRONTIER_LATEST_JSON,
    )
    parser.add_argument("--skip-arr-render", action="store_true")
    parser.add_argument("--skip-hypothesis-lab", action="store_true")
    parser.add_argument("--skip-regime-policy-lab", action="store_true")
    parser.add_argument("--skip-hypothesis-frontier-render", action="store_true")
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
        if not args.skip_hypothesis_lab:
            entry["hypothesis_lab"] = _run_hypothesis_lab(args)
        if not args.skip_regime_policy_lab:
            entry["regime_policy_lab"] = _run_regime_policy_lab(args)
        loop_payload = _write_loop_reports(args.loop_report_dir, entry)
        if not args.skip_arr_render:
            loop_payload["arr_render"] = _render_arr_progress(args)
        if not args.skip_hypothesis_frontier_render:
            loop_payload["hypothesis_frontier_render"] = _render_hypothesis_frontier(args)
        print(json.dumps(loop_payload, indent=2, sort_keys=True))
        cycle_count += 1
        if args.max_cycles and cycle_count >= args.max_cycles:
            return 0
        sleep_seconds = max(0.0, float(args.interval_seconds) - (finished_at - started_at).total_seconds())
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
