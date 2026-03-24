#!/usr/bin/env python3
"""Check the latest edge tracker recommendation and compare to current mode.

Usage:
    python scripts/check_edge_recommendation.py [--log-path data/edge_tracker_log.json] [--current-mode both]

Exit codes:
    0 — current mode matches recommendation (or no data)
    1 — current mode does NOT match recommendation (consider switching)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check BTC5 edge tracker recommendation")
    parser.add_argument(
        "--log-path",
        type=Path,
        default=Path(os.environ.get("BTC5_EDGE_TRACKER_LOG_PATH", "data/edge_tracker_log.json")),
        help="Path to edge_tracker_log.json",
    )
    parser.add_argument(
        "--current-mode",
        type=str,
        default=os.environ.get("BTC5_DIRECTION_MODE", "both"),
        help="Current BTC5_DIRECTION_MODE value",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of recent recommendations to show",
    )
    args = parser.parse_args()

    if not args.log_path.exists():
        print(f"No edge tracker log found at {args.log_path}")
        print("Run the BTC5 bot for at least 100 cycles to generate recommendations.")
        return 0

    try:
        entries = json.loads(args.log_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read log: {exc}")
        return 0

    if not isinstance(entries, list) or not entries:
        print("Edge tracker log is empty.")
        return 0

    recent = entries[-args.limit:]
    latest = entries[-1]

    print("=" * 60)
    print("BTC5 ROLLING EDGE TRACKER")
    print("=" * 60)
    print()
    print(f"Current mode:      {args.current_mode}")
    print(f"Recommended mode:  {latest.get('recommended_mode', 'unknown')}")
    print(f"Confidence:        {latest.get('confidence', 0):.1%}")
    print(f"Reason:            {latest.get('reason', 'n/a')}")
    print()
    print(f"DOWN stats:  WR={latest.get('down_wr', 0):.1%}  fills={latest.get('down_fills', 0)}  PnL=${latest.get('down_pnl_usd', 0):.2f}")
    print(f"UP stats:    WR={latest.get('up_wr', 0):.1%}  fills={latest.get('up_fills', 0)}  PnL=${latest.get('up_pnl_usd', 0):.2f}")
    print()

    if len(recent) > 1:
        print(f"Trend (last {len(recent)} recommendations):")
        for entry in recent:
            ts = entry.get("timestamp", "?")[:19]
            mode = entry.get("recommended_mode", "?")
            conf = entry.get("confidence", 0)
            print(f"  {ts}  mode={mode:<12s}  confidence={conf:.1%}")
        print()

    recommended = str(latest.get("recommended_mode", "both")).strip().lower()
    current = str(args.current_mode).strip().lower()

    if recommended == current:
        print("STATUS: Current mode matches recommendation.")
        return 0
    elif recommended == "pause":
        print("WARNING: Edge tracker recommends PAUSE. Both sides are losing.")
        print("Action: Consider stopping the bot until conditions improve.")
        return 1
    else:
        print(f"MISMATCH: Current mode '{current}' differs from recommendation '{recommended}'.")
        print(f"Action: Consider setting BTC5_DIRECTION_MODE={recommended}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
