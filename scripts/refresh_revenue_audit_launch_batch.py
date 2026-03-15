#!/usr/bin/env python3
"""Refresh the JJ-N Website Growth Audit launch batch and bridge artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nontrading.config import RevenueAgentSettings
from nontrading.revenue_audit.acquisition_bridge import (
    DEFAULT_OUTPUT_PATH as DEFAULT_BRIDGE_OUTPUT_PATH,
    RevenueAuditAcquisitionBridge,
    write_acquisition_bridge_artifact,
)
from nontrading.revenue_audit.discovery import FetchPolicy, PageFetcher
from nontrading.revenue_audit.launch_batch import (
    CURATED_BATCH_LIMIT,
    DEFAULT_CURATED_SOURCE_PATH,
    DEFAULT_OUTPUT_PATH as DEFAULT_BATCH_OUTPUT_PATH,
    refresh_curated_launch_batch,
    write_launch_batch_artifact,
)
from nontrading.store import RevenueStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to the JJ-N revenue SQLite database.",
    )
    parser.add_argument(
        "--curated-source",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_CURATED_SOURCE_PATH,
        help="JSON seed list for the curated public-web launch batch.",
    )
    parser.add_argument(
        "--batch-output",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_BATCH_OUTPUT_PATH,
        help="Where to write the launch-batch artifact.",
    )
    parser.add_argument(
        "--bridge-output",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_BRIDGE_OUTPUT_PATH,
        help="Where to write the ranked bridge artifact.",
    )
    parser.add_argument(
        "--max-prospects",
        type=int,
        default=CURATED_BATCH_LIMIT,
        help="Maximum number of prospects to stage in the active launch batch.",
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    fetcher: PageFetcher | None = None,
    policy: FetchPolicy | None = None,
) -> int:
    args = parse_args(argv)
    settings = RevenueAgentSettings.from_env()
    store = RevenueStore(args.db_path or settings.db_path)
    batch_artifact = refresh_curated_launch_batch(
        store,
        source_path=args.curated_source,
        fetcher=fetcher,
        policy=policy,
        max_prospects=args.max_prospects,
    )
    batch_output = write_launch_batch_artifact(batch_artifact, args.batch_output)
    bridge = RevenueAuditAcquisitionBridge(store, settings, max_prospects=args.max_prospects)
    bridge_artifact = bridge.build_artifact()
    bridge_output = write_acquisition_bridge_artifact(bridge_artifact, args.bridge_output)
    print(
        "revenue-audit launch-batch refresh "
        f"seeds={batch_artifact.seeds_loaded} "
        f"qualified={batch_artifact.qualified_candidates} "
        f"selected={batch_artifact.selected_prospects} "
        f"overflow={batch_artifact.overflow_count} "
        f"mode={bridge_artifact.launch_mode} "
        f"batch_output={batch_output} "
        f"bridge_output={bridge_output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
