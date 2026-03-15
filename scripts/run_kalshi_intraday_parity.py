#!/usr/bin/env python3
"""Run Instance #4 Kalshi intraday parity surface + cross-venue audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.kalshi_intraday_parity import run_intraday_parity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kalshi-pages",
        type=int,
        default=2,
        help="Number of Kalshi open-market pages to scan (default: 2).",
    )
    parser.add_argument(
        "--polymarket-pages",
        type=int,
        default=2,
        help="Number of Polymarket pages to scan (default: 2).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    outputs = run_intraday_parity(
        kalshi_pages=max(1, int(args.kalshi_pages)),
        polymarket_pages=max(1, int(args.polymarket_pages)),
    )
    print(outputs.surface_path)
    print(outputs.audit_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
