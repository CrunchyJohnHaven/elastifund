#!/usr/bin/env python3
"""Run the flywheel automation from a checked-in config file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flywheel.automation import run_from_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Elastifund flywheel automation once.")
    parser.add_argument("--config", required=True, help="Path to flywheel runtime JSON config")
    args = parser.parse_args()

    result = run_from_config(args.config)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
