#!/usr/bin/env python3
"""Generate the JJ-N Website Growth Audit launch bridge artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nontrading.config import RevenueAgentSettings
from nontrading.revenue_audit.acquisition_bridge import (
    DEFAULT_OUTPUT_PATH,
    RevenueAuditAcquisitionBridge,
    write_acquisition_bridge_artifact,
)
from nontrading.revenue_audit.discovery import FetchPolicy, PageFetcher
from nontrading.revenue_audit.launch_batch import ingest_curated_launch_batch
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
        "--output",
        type=Path,
        default=PROJECT_ROOT / DEFAULT_OUTPUT_PATH,
        help="Where to write the acquisition bridge artifact.",
    )
    parser.add_argument(
        "--curated-source",
        type=Path,
        default=None,
        help="Optional JSON seed list for the curated public-web launch batch.",
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
    store = RevenueStore(args.db_path)
    if args.curated_source is not None:
        ingestion = ingest_curated_launch_batch(
            store,
            source_path=args.curated_source,
            fetcher=fetcher,
            policy=policy,
        )
    else:
        ingestion = None
    bridge = RevenueAuditAcquisitionBridge(store, settings)
    artifact = bridge.build_artifact()
    output_path = write_acquisition_bridge_artifact(artifact, args.output)
    print(
        "revenue-audit acquisition bridge "
        f"mode={artifact.launch_mode} "
        f"selected={artifact.selected_prospects} "
        f"seeded={(ingestion.seeded_accounts if ingestion is not None else 0)} "
        f"output={output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
