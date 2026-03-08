#!/usr/bin/env python3
"""Write the compact remote-cycle status report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flywheel.status_report import write_remote_cycle_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the remote-cycle status artifact.")
    parser.add_argument("--config", default="config/remote_cycle_status.json")
    parser.add_argument("--output-md", default="reports/remote_cycle_status.md")
    parser.add_argument("--output-json", default="reports/remote_cycle_status.json")
    args = parser.parse_args()

    result = write_remote_cycle_status(
        ROOT,
        markdown_path=Path(args.output_md),
        json_path=Path(args.output_json),
        config_path=Path(args.config),
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
