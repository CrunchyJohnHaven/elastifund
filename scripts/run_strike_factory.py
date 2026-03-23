#!/usr/bin/env python3
"""Strike Factory runner.

Coordinates the revenue-first execution path:
strike desk -> event tape -> promotion snapshot -> optional intelligence harness.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.strike_factory import (  # noqa: E402
    DEFAULT_MARKDOWN_PATH,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_PROMOTION_DB_PATH,
    DEFAULT_RESOLUTION_MARKETS_PATH,
    DEFAULT_TAPE_DB_PATH,
    build_default_strike_factory_packets,
    run_strike_factory_cycle,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_PATH)
    parser.add_argument("--tape-db", type=Path, default=DEFAULT_TAPE_DB_PATH)
    parser.add_argument("--promotion-db", type=Path, default=DEFAULT_PROMOTION_DB_PATH)
    parser.add_argument(
        "--packets-json",
        type=Path,
        default=None,
        help="Optional prebuilt packet fixture. If omitted, the local BTC5 resolution fixture is used.",
    )
    parser.add_argument(
        "--resolution-markets-json",
        type=Path,
        default=DEFAULT_RESOLUTION_MARKETS_PATH,
        help="Local BTC5 dual-sided market fixture used when --packets-json is not supplied.",
    )
    parser.add_argument("--run-harness", action="store_true", help="Include the intelligence harness result in the output")
    parser.add_argument("--harness-output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_mode = ""
    source_inputs: dict[str, object] = {}
    desk = None
    raw_packets = None

    if args.packets_json is not None:
        payload = json.loads(args.packets_json.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            packet_rows = payload
        elif isinstance(payload, dict):
            for key in ("packets", "execution_packets", "items", "queue", "data"):
                maybe = payload.get(key)
                if isinstance(maybe, list):
                    packet_rows = maybe
                    break
            else:
                packet_rows = []
        else:
            packet_rows = []
        from scripts.run_strike_desk import _packet_from_dict  # noqa: E402

        raw_packets = [_packet_from_dict(row) for row in packet_rows if isinstance(row, dict)]
        source_mode = f"fixture:{args.packets_json}"
        source_inputs = {"packets_json": str(args.packets_json), "raw_packet_count": len(raw_packets)}
    else:
        from bot.strike_desk import StrikeDesk  # noqa: E402

        desk = StrikeDesk()
        raw_packets, source_inputs = build_default_strike_factory_packets(
            desk=desk,
            markets_path=args.resolution_markets_json,
        )
        source_mode = f"fixture:{args.resolution_markets_json}"

    report = run_strike_factory_cycle(
        desk=desk,
        raw_packets=raw_packets,
        output_path=args.output,
        markdown_path=args.markdown_output,
        tape_db_path=args.tape_db,
        promotion_db_path=args.promotion_db,
        run_harness=args.run_harness,
        harness_output_path=args.harness_output,
        source_mode=source_mode,
        source_inputs=source_inputs,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
