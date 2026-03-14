#!/usr/bin/env python3
"""Build cross-asset historical backfill, vendor ranking, and instance #3 artifact."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.cross_asset_history import run_cross_asset_history_dispatch, settings_from_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", default=str(REPO_ROOT))
    parser.add_argument("--lookback-days", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = settings_from_env(workspace_root=Path(args.workspace_root))
    if args.lookback_days is not None:
        settings = replace(settings, lookback_days=args.lookback_days)
    history_report, vendor_stack_report, instance_artifact = run_cross_asset_history_dispatch(settings)
    print(
        json.dumps(
            {
                "history_report": str(settings.history_report_path),
                "vendor_stack_report": str(settings.vendor_stack_report_path),
                "instance_artifact": str(settings.instance_report_path),
                "summary": history_report.get("summary", {}),
                "recommendation": vendor_stack_report.get("recommendation", {}),
                "instance": instance_artifact,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
