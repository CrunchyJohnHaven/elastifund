#!/usr/bin/env python3
"""Generate the Alpaca crypto candidate lane artifact."""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    pass

from bot.alpaca_first_trade import AlpacaFirstTradeConfig, AlpacaFirstTradeSystem  # noqa: E402
from bot.alpaca_client import AlpacaClientError  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["shadow", "paper", "live"], default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = AlpacaFirstTradeConfig.from_env(mode=args.mode)
    system = AlpacaFirstTradeSystem(config)
    try:
        with system.build_client() as client:
            report = system.run_lane(client)
    except AlpacaClientError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
