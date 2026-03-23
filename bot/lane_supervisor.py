#!/usr/bin/env python3
"""Lane Supervisor: selects top thesis candidates per lane and routes to execution.

Reads:
- reports/autoresearch/thesis_candidates.json

Produces:
- reports/autoresearch/supervisor_selection.json

For weather candidates, appends selected shadow candidates to
data/kalshi_weather_supervisor_queue.jsonl so the Kalshi weather service
path can consume them without enabling live order submission.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Reads from the unified thesis_bundle — the single authoritative thesis compiler.
# thesis_foundry candidates (weather + BTC5) are merged into thesis_bundle by
# scripts/thesis_bundle.py and carry execution metadata (lane, rank_score, execution_mode).
DEFAULT_THESIS_PATH = REPO_ROOT / "reports" / "thesis_bundle.json"
# Kept for backwards-compat; the foundry path is no longer the primary source.
_LEGACY_THESIS_CANDIDATES_PATH = REPO_ROOT / "reports" / "autoresearch" / "thesis_candidates.json"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "reports" / "autoresearch" / "supervisor_selection.json"
DEFAULT_WEATHER_QUEUE_PATH = REPO_ROOT / "data" / "kalshi_weather_supervisor_queue.jsonl"

# Minimum spread-adjusted edge to qualify a weather candidate for selection
MIN_WEATHER_EDGE = 0.03
# Maximum candidates routed per supervisor cycle per lane
MAX_CANDIDATES_PER_LANE = 3


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _select_per_lane(
    candidates: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for thesis in candidates:
        lane = str(thesis.get("lane") or "unknown")
        rank = float(thesis.get("rank_score") or 0.0)
        mode = str(thesis.get("execution_mode") or "shadow")

        # Live-mode lanes (btc5) always included; shadow lanes need minimum edge
        if mode != "live" and rank < MIN_WEATHER_EDGE:
            continue
        by_lane.setdefault(lane, []).append(thesis)

    selected: dict[str, list[dict[str, Any]]] = {}
    for lane, theses in by_lane.items():
        sorted_theses = sorted(theses, key=lambda t: float(t.get("rank_score") or 0.0), reverse=True)
        selected[lane] = sorted_theses[:MAX_CANDIDATES_PER_LANE]
    return selected


def _route_weather_candidates(
    selections: list[dict[str, Any]],
    queue_path: Path,
    now: datetime,
) -> int:
    """Append shadow weather candidates to the Kalshi supervisor queue."""
    if not selections:
        return 0
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    routed = 0
    with queue_path.open("a", encoding="utf-8") as fh:
        for thesis in selections:
            row = {
                "queued_at": _iso_z(now),
                "thesis_id": thesis.get("thesis_id"),
                "ticker": thesis.get("ticker"),
                "event_ticker": thesis.get("event_ticker"),
                "side": thesis.get("side"),
                "spread_adjusted_edge": thesis.get("spread_adjusted_edge"),
                "model_probability": thesis.get("model_probability"),
                "execution_mode": thesis.get("execution_mode", "shadow"),
                "city": thesis.get("city"),
                "target_date": thesis.get("target_date"),
                "source": "lane_supervisor",
            }
            fh.write(json.dumps(row) + "\n")
            routed += 1
    return routed


def run_supervisor(
    *,
    thesis_path: Path = DEFAULT_THESIS_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    weather_queue_path: Path = DEFAULT_WEATHER_QUEUE_PATH,
    now: datetime | None = None,
    route_weather: bool = True,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)

    thesis_payload = _read_json(thesis_path)
    # thesis_bundle uses "theses"; thesis_candidates uses "candidates" (legacy).
    # Filter to items that carry execution metadata (lane + execution_mode) — these
    # are the thesis_foundry entries merged in by thesis_bundle.py.
    raw_items = (
        thesis_payload.get("theses")
        or thesis_payload.get("candidates")
        or []
    )
    all_candidates = [
        item for item in raw_items
        if isinstance(item, dict) and item.get("lane") and item.get("execution_mode")
    ]

    # Fallback: if thesis_bundle has no routable items, try legacy path
    if not all_candidates and thesis_path == DEFAULT_THESIS_PATH:
        legacy = _read_json(_LEGACY_THESIS_CANDIDATES_PATH)
        all_candidates = legacy.get("candidates") or legacy.get("theses") or []

    selected_by_lane = _select_per_lane(all_candidates)

    weather_routed = 0
    if route_weather and "weather" in selected_by_lane:
        weather_routed = _route_weather_candidates(
            selected_by_lane["weather"],
            weather_queue_path,
            now,
        )

    lane_actions: dict[str, Any] = {}
    for lane, selections in selected_by_lane.items():
        top = selections[0] if selections else {}
        lane_actions[lane] = {
            "selected_count": len(selections),
            "top_edge": max(
                (float(t.get("rank_score") or 0.0) for t in selections),
                default=None,
            ),
            "top_thesis_id": top.get("thesis_id"),
            "execution_mode": top.get("execution_mode"),
            "routed_to_queue": weather_routed if lane == "weather" else 0,
        }

    result: dict[str, Any] = {
        "artifact": "supervisor_selection.v1",
        "generated_at": _iso_z(now),
        "thesis_source": str(thesis_path),
        "thesis_count_evaluated": len(all_candidates),
        "lanes_with_selections": sorted(selected_by_lane.keys()),
        "lane_actions": lane_actions,
        "weather_candidates_routed": weather_routed,
        "weather_queue_path": str(weather_queue_path),
        "selected_by_lane": selected_by_lane,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thesis-path", type=Path, default=DEFAULT_THESIS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--weather-queue", type=Path, default=DEFAULT_WEATHER_QUEUE_PATH)
    parser.add_argument("--no-route-weather", action="store_true")
    args = parser.parse_args(argv)

    result = run_supervisor(
        thesis_path=args.thesis_path,
        output_path=args.output,
        weather_queue_path=args.weather_queue,
        route_weather=not args.no_route_weather,
    )

    print(f"Wrote {args.output}")
    for lane, action in result["lane_actions"].items():
        print(
            f"  {lane}: selected={action['selected_count']} "
            f"top_edge={action['top_edge']} "
            f"mode={action['execution_mode']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
