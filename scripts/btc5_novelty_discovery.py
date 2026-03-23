#!/usr/bin/env python3
"""BTC5 Novelty Discovery: source_observations → novelty_discovery + novel_edge artifacts.

Reads assemble_observed_rows from the local DB (and optionally archives/remote cache),
computes segment-level evidence stats, identifies edges and under-explored segments,
and writes two canonical artifacts:

  reports/autoresearch/novelty_discovery/latest.json
  reports/autoresearch/novel_edge/latest.json

These artifacts are consumed by the autoresearch cycle core (thesis layer input) and
the supervisor (promotion gate input). When fresh observations exist, the cycle core
suppresses fallback_requires_revalidation and uses these surfaces instead.

Usage:
  python -m scripts.btc5_novelty_discovery [--db-path PATH] [--include-archive-csvs]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.btc5_monte_carlo import (  # noqa: E402
    _is_live_filled_row,
    _safe_float,
    assemble_observed_rows,
)

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

NOVELTY_DISCOVERY_DIR = ROOT / "reports" / "autoresearch" / "novelty_discovery"
NOVEL_EDGE_DIR = ROOT / "reports" / "autoresearch" / "novel_edge"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

FRESH_OBS_HOURS = 6.0          # obs within this window = "fresh"
MIN_EDGE_FILLS = 5             # minimum live fills to assert an edge
MIN_EDGE_WIN_RATE = 0.55       # minimum win rate for positive-edge label
MIN_EDGE_PNL_USD = 0.0         # minimum cumulative PnL for positive-edge label
UNDER_EXPLORED_MAX_FILLS = 3   # fewer than this = under-explored (novelty signal)
MAX_EDGES_OUTPUT = 20          # cap on novel_edge list length
MAX_UNDER_EXPLORED_OUTPUT = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _obs_freshness_hours(rows: list[dict[str, Any]]) -> float:
    """Hours since the most recently observed filled row (9999 if none)."""
    filled = [r for r in rows if _is_live_filled_row(r)]
    if not filled:
        return 9999.0
    latest_ts = max(
        (int(r.get("window_start_ts") or 0) for r in filled),
        default=0,
    )
    if latest_ts <= 0:
        return 9999.0
    return max(0.0, (time.time() - latest_ts) / 3600.0)


def _segment_stats(
    rows: list[dict[str, Any]],
    key_fn: Any,
) -> list[dict[str, Any]]:
    """Compute per-segment fill/win/PnL stats over live-filled rows."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _is_live_filled_row(row):
            continue
        key = str(key_fn(row) or "unknown")
        b = buckets.setdefault(
            key,
            {"segment": key, "fills": 0, "wins": 0, "pnl_usd": 0.0},
        )
        b["fills"] += 1
        if bool(row.get("won")) or _safe_float(row.get("pnl_usd"), 0.0) > 0.0:
            b["wins"] += 1
        b["pnl_usd"] += _safe_float(row.get("pnl_usd"), 0.0)

    result: list[dict[str, Any]] = []
    for b in buckets.values():
        fills = int(b["fills"])
        losses = fills - int(b["wins"])
        result.append(
            {
                "segment": b["segment"],
                "fills": fills,
                "wins": int(b["wins"]),
                "losses": losses,
                "win_rate": round(b["wins"] / fills, 4) if fills > 0 else 0.0,
                "pnl_usd": round(b["pnl_usd"], 4),
                "profit_factor": round(b["wins"] / max(losses, 1), 4),
            }
        )
    return sorted(result, key=lambda x: (-x["fills"], x["segment"]))


def _identify_novel_edges(segs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return segments that satisfy the positive-edge criteria."""
    return [
        {**s, "edge_type": "positive_edge"}
        for s in segs
        if (
            s["fills"] >= MIN_EDGE_FILLS
            and s["win_rate"] >= MIN_EDGE_WIN_RATE
            and s["pnl_usd"] >= MIN_EDGE_PNL_USD
        )
    ]


def _identify_under_explored(segs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return segments with fewer than UNDER_EXPLORED_MAX_FILLS fills."""
    return [s for s in segs if s["fills"] < UNDER_EXPLORED_MAX_FILLS]


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------


def compute_novelty_discovery(
    rows: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Compute the novelty_discovery artifact from source_observations (rows)."""
    freshness_hours = _obs_freshness_hours(rows)
    filled_rows = [r for r in rows if _is_live_filled_row(r)]

    # Segment across five independent dimensions + one cross dimension
    segments = {
        "by_direction": _segment_stats(rows, lambda r: r.get("direction")),
        "by_price_bucket": _segment_stats(rows, lambda r: r.get("price_bucket")),
        "by_delta_bucket": _segment_stats(rows, lambda r: r.get("delta_bucket")),
        "by_session": _segment_stats(rows, lambda r: r.get("session_name")),
        "by_et_hour": _segment_stats(
            rows, lambda r: str(r.get("et_hour", "?")).zfill(2)
        ),
        "by_direction_x_session": _segment_stats(
            rows,
            lambda r: f"{r.get('direction','?')}_{r.get('session_name','?')}",
        ),
    }

    return {
        "generated_at": _now_utc().isoformat(),
        "obs_row_count": len(rows),
        "obs_filled_count": len(filled_rows),
        "obs_freshness_hours": round(freshness_hours, 3),
        "obs_is_fresh": freshness_hours <= FRESH_OBS_HOURS,
        "fresh_threshold_hours": FRESH_OBS_HOURS,
        "segments": segments,
        "baseline": baseline,
    }


def compute_novel_edge(novelty_discovery: dict[str, Any]) -> dict[str, Any]:
    """Derive the novel_edge artifact from novelty_discovery."""
    segments = novelty_discovery.get("segments") or {}

    all_edges: list[dict[str, Any]] = []
    all_under_explored: list[dict[str, Any]] = []

    for dim_name, segs in segments.items():
        if not isinstance(segs, list):
            continue
        for edge in _identify_novel_edges(segs):
            all_edges.append({"dimension": dim_name, **edge})
        for u in _identify_under_explored(segs):
            all_under_explored.append({"dimension": dim_name, **u})

    all_edges.sort(key=lambda x: (-x["pnl_usd"], -x["win_rate"], -x["fills"]))
    all_under_explored.sort(key=lambda x: (x["fills"], x["dimension"]))

    top_edge = all_edges[0] if all_edges else None

    return {
        "generated_at": novelty_discovery["generated_at"],
        "obs_freshness_hours": novelty_discovery["obs_freshness_hours"],
        "obs_is_fresh": novelty_discovery["obs_is_fresh"],
        "edge_count": len(all_edges),
        "under_explored_count": len(all_under_explored),
        "novel_edges": all_edges[:MAX_EDGES_OUTPUT],
        "under_explored_segments": all_under_explored[:MAX_UNDER_EXPLORED_OUTPUT],
        "top_edge": top_edge,
        "thesis_prompt": _build_thesis_prompt(all_edges, novelty_discovery),
    }


def _build_thesis_prompt(
    edges: list[dict[str, Any]],
    novelty: dict[str, Any],
) -> str:
    """Build a compact thesis-layer prompt summarising the strongest evidence."""
    fresh = novelty.get("obs_is_fresh", False)
    filled = novelty.get("obs_filled_count", 0)
    freshness = novelty.get("obs_freshness_hours", 9999.0)

    if not edges:
        return (
            f"No positive edges detected. "
            f"obs_is_fresh={fresh}, filled={filled}, freshness={freshness:.1f}h. "
            f"Prioritise exploration of under-represented segments."
        )

    top = edges[0]
    lines = [
        f"Top edge: {top['dimension']}={top['segment']} "
        f"({top['fills']} fills, WR={top['win_rate']:.2f}, PnL=${top['pnl_usd']:.2f}).",
        f"obs_is_fresh={fresh}, {len(edges)} edges detected, freshness={freshness:.1f}h.",
        f"Prioritise hypothesis generation around '{top['segment']}' in '{top['dimension']}'.",
    ]
    if len(edges) > 1:
        second = edges[1]
        lines.append(
            f"Second edge: {second['dimension']}={second['segment']} "
            f"(WR={second['win_rate']:.2f}, PnL=${second['pnl_usd']:.2f})."
        )
    return " ".join(lines)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def run_discovery(
    *,
    db_path: Path | None,
    include_archive_csvs: bool = False,
    archive_glob: str = "reports/archive/**/*_trades.csv",
    refresh_remote: bool = False,
    remote_cache_json: Path | None = None,
    novelty_dir: Path | None = None,
    edge_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run discovery and write artifacts. Returns (novelty_discovery, novel_edge)."""
    if remote_cache_json is None:
        remote_cache_json = ROOT / "state" / "remote_rows_cache.json"

    rows, baseline = assemble_observed_rows(
        db_path=db_path if (db_path is not None and db_path.exists()) else None,
        include_archive_csvs=include_archive_csvs,
        archive_glob=archive_glob,
        refresh_remote=refresh_remote,
        remote_cache_json=remote_cache_json,
    )

    novelty_discovery = compute_novelty_discovery(rows, baseline)
    novel_edge = compute_novel_edge(novelty_discovery)

    nd_dir = novelty_dir or NOVELTY_DISCOVERY_DIR
    ne_dir = edge_dir or NOVEL_EDGE_DIR
    nd_dir.mkdir(parents=True, exist_ok=True)
    ne_dir.mkdir(parents=True, exist_ok=True)

    (nd_dir / "latest.json").write_text(
        json.dumps(novelty_discovery, indent=2) + "\n"
    )
    (ne_dir / "latest.json").write_text(
        json.dumps(novel_edge, indent=2) + "\n"
    )

    return novelty_discovery, novel_edge


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="BTC5 novelty discovery: source_observations → novelty_discovery + novel_edge artifacts"
    )
    p.add_argument(
        "--db-path",
        default=str(ROOT / "data" / "btc_5min_maker.db"),
        help="Path to SQLite fill database (default: data/btc_5min_maker.db)",
    )
    p.add_argument(
        "--include-archive-csvs",
        action="store_true",
        help="Include archived CSV rows",
    )
    p.add_argument(
        "--archive-glob",
        default="reports/archive/**/*_trades.csv",
        help="Glob pattern for archive CSVs",
    )
    p.add_argument(
        "--refresh-remote",
        action="store_true",
        help="Fetch rows from VPS via SSH",
    )
    p.add_argument(
        "--remote-cache-json",
        default=str(ROOT / "state" / "remote_rows_cache.json"),
        help="Path for remote row cache",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory for novelty_discovery artifact",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db_path)
    remote_cache = Path(args.remote_cache_json)
    novelty_dir = Path(args.output_dir) if args.output_dir else None

    novelty_discovery, novel_edge = run_discovery(
        db_path=db_path,
        include_archive_csvs=args.include_archive_csvs,
        archive_glob=args.archive_glob,
        refresh_remote=args.refresh_remote,
        remote_cache_json=remote_cache,
        novelty_dir=novelty_dir,
    )

    nd_path = (novelty_dir or NOVELTY_DISCOVERY_DIR) / "latest.json"
    ne_path = NOVEL_EDGE_DIR / "latest.json"

    print(f"novelty_discovery → {nd_path}")
    print(f"novel_edge        → {ne_path}")
    print(
        f"obs_freshness: {novelty_discovery['obs_freshness_hours']:.1f}h  "
        f"fresh={novelty_discovery['obs_is_fresh']}"
    )
    print(
        f"edges: {novel_edge['edge_count']}  "
        f"under_explored: {novel_edge['under_explored_count']}"
    )
    top = novel_edge.get("top_edge")
    if top:
        print(
            f"top_edge: {top['dimension']}={top['segment']}  "
            f"WR={top['win_rate']:.2f}  PnL=${top['pnl_usd']:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
