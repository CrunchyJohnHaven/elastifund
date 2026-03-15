#!/usr/bin/env python3
"""Stable service entrypoint for one supervised BTC5 market mutation cycle."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.btc5_dual_autoresearch_ops as dual_ops


def main(argv: Sequence[str] | None = None) -> int:
    args = ["run-lane", "--lane", "market", "--write-morning-report"]
    if argv:
        args.extend(argv)
    return dual_ops.main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
