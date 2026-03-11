#!/usr/bin/env python3
"""Generate staged revenue-audit conversion packets from the launch bridge."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nontrading.config import RevenueAgentSettings
from nontrading.revenue_audit.conversion_engine import (
    DEFAULT_PACKET_DIR,
    DEFAULT_SUMMARY_PATH,
    RevenueAuditConversionEngine,
    load_acquisition_bridge_payload,
    write_conversion_artifacts,
)
from nontrading.store import RevenueStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=PROJECT_ROOT / "data" / "revenue_agent.db",
        help="Path to the JJ-N revenue SQLite database.",
    )
    parser.add_argument(
        "--bridge-input",
        type=Path,
        default=None,
        help="Optional existing launch-bridge artifact to stage from.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_SUMMARY_PATH,
        help="Where to write the staged conversion summary artifact.",
    )
    parser.add_argument(
        "--packet-dir",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_PACKET_DIR,
        help="Where to write one per-prospect conversion packet.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = RevenueAgentSettings.from_env()
    store = RevenueStore(args.db_path)
    engine = RevenueAuditConversionEngine(store, settings)
    if args.bridge_input is not None:
        bridge_payload = load_acquisition_bridge_payload(args.bridge_input)
        summary, packets = engine.build_artifact(bridge_payload, source_bridge_path=args.bridge_input)
    else:
        summary, packets = engine.build_from_store()
    summary_path, packet_paths, persisted_summary, _ = write_conversion_artifacts(
        summary,
        packets,
        summary_output=args.summary_output,
        packet_dir=args.packet_dir,
    )
    print(
        "revenue-audit conversion packets "
        f"mode={persisted_summary.launch_mode} "
        f"prospects={persisted_summary.staged_packets} "
        f"proposals={persisted_summary.staged_proposals} "
        f"followups={persisted_summary.staged_follow_ups} "
        f"output={summary_path} "
        f"packet_dir={args.packet_dir} "
        f"packet_count={len(packet_paths)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
