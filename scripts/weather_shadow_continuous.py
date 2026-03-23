#!/usr/bin/env python3
"""Weather shadow lane continuous runner.

Runs at :25 and :55 each hour, refreshing the instance04 weather divergence
shadow artifact. Shadow-only: no live capital is ever submitted from this process.

Usage:
  python scripts/weather_shadow_continuous.py          # single run
  python scripts/weather_shadow_continuous.py --daemon  # continuous
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_instance4_weather_shadow_lane import (  # noqa: E402
    DEFAULT_MARKDOWN_PATH,
    DEFAULT_OUTPUT_PATH,
    build_instance4_weather_lane_artifact,
    render_markdown,
)

DEFAULT_HISTORY_PATH = REPO_ROOT / "data" / "weather_shadow_history.jsonl"

SCAN_MINUTES = (25, 55)
WINDOW_HALF_WIDTH_MINUTES = 4  # minutes either side of :25/:55


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_scan_window(now: datetime) -> bool:
    utc = now.astimezone(timezone.utc)
    for target in SCAN_MINUTES:
        if abs(utc.minute - target) <= WINDOW_HALF_WIDTH_MINUTES:
            return True
    return False


def _seconds_until_next_window(now: datetime) -> float:
    utc = now.astimezone(timezone.utc)
    current_minute = utc.minute
    current_second = utc.second

    candidates: list[float] = []
    for target in SCAN_MINUTES:
        delta_minutes = target - current_minute
        if delta_minutes < 0:
            delta_minutes += 60
        total_seconds = delta_minutes * 60 - current_second
        candidates.append(max(0.0, float(total_seconds)))

    return min(candidates) if candidates else 60.0


def run_once(
    *,
    history_path: Path = DEFAULT_HISTORY_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    markdown_path: Path = DEFAULT_MARKDOWN_PATH,
) -> dict:
    now = datetime.now(timezone.utc)
    payload = build_instance4_weather_lane_artifact(now=now)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")

    history_row = {
        "run_at": _iso_z(now),
        "candidate_count": (payload.get("market_scan") or {}).get("candidate_count", 0),
        "clean_city_count": (payload.get("source_mapping_summary") or {}).get("clean_city_count", 0),
        "finance_gate_pass": payload.get("finance_gate_pass"),
        "block_reasons": payload.get("block_reasons", []),
    }
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(history_row) + "\n")

    return payload


def run_daemon(
    *,
    poll_interval_seconds: float = 30.0,
    history_path: Path = DEFAULT_HISTORY_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    markdown_path: Path = DEFAULT_MARKDOWN_PATH,
) -> None:
    print(f"[weather_shadow_continuous] daemon started, poll={poll_interval_seconds}s, windows={SCAN_MINUTES}")
    last_run_minute: int | None = None

    while True:
        now = datetime.now(timezone.utc)
        if _is_scan_window(now) and now.minute != last_run_minute:
            try:
                payload = run_once(
                    history_path=history_path,
                    output_path=output_path,
                    markdown_path=markdown_path,
                )
                candidates = (payload.get("market_scan") or {}).get("candidate_count", 0)
                print(
                    f"[weather_shadow_continuous] {_iso_z(now)} "
                    f"candidates={candidates} "
                    f"finance_gate={payload.get('finance_gate_pass')}"
                )
                last_run_minute = now.minute
            except Exception as exc:
                print(f"[weather_shadow_continuous] ERROR: {exc}", file=sys.stderr)
        time.sleep(poll_interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daemon", action="store_true", help="Run continuously at :25/:55 each hour")
    parser.add_argument("--interval", type=float, default=30.0, help="Poll interval seconds (daemon only)")
    parser.add_argument("--history-path", type=Path, default=DEFAULT_HISTORY_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--markdown-path", type=Path, default=DEFAULT_MARKDOWN_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.daemon:
        run_daemon(
            poll_interval_seconds=args.interval,
            history_path=args.history_path,
            output_path=args.output_path,
            markdown_path=args.markdown_path,
        )
        return 0
    payload = run_once(
        history_path=args.history_path,
        output_path=args.output_path,
        markdown_path=args.markdown_path,
    )
    print(f"Wrote {args.output_path}")
    scan = payload.get("market_scan") or {}
    print(
        f"candidates={scan.get('candidate_count')} "
        f"clean_cities={(payload.get('source_mapping_summary') or {}).get('clean_city_count')} "
        f"finance_gate={payload.get('finance_gate_pass')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
