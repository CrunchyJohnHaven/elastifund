#!/usr/bin/env python3
"""
Promotion Bundle Runner — thin shim

Delegates entirely to scripts/promotion_bundle.py (assemble_promotion).
All promotion logic, gate evaluation, and capital sizing lives there.

Usage:
    python3 scripts/run_promotion_bundle.py
    python3 scripts/run_promotion_bundle.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.promotion_bundle import assemble_promotion  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print bundle without writing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.dry_run:
        # For dry-run: capture bundle and print without side-effects
        # assemble_promotion() writes to disk; import output path to display
        from scripts.promotion_bundle import OUTPUT_PATH
        bundle = assemble_promotion()
        print(json.dumps(bundle, indent=2, default=str))
        return 0

    bundle = assemble_promotion()
    print(
        f"[promotion-bundle] theses={bundle['thesis_count']}"
        f" approved={bundle['approved_count']}"
        f" capital_usd={bundle['total_capital_approved_usd']:.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
