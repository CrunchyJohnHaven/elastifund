#!/usr/bin/env python3
"""Run the end-to-end Alpaca first-trade automation cycle."""

from __future__ import annotations

import argparse
import json
import sys
import time

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env so Alpaca credentials are available via os.environ
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    pass  # dotenv not installed; rely on shell environment

from bot.alpaca_first_trade import (  # noqa: E402
    AlpacaFirstTradeConfig,
    AlpacaFirstTradeSystem,
    send_alpaca_trade_alert,
)
from bot.alpaca_client import AlpacaClientError  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["shadow", "paper", "live"], default=None)
    parser.add_argument("--daemon", action="store_true", help="Loop continuously.")
    parser.add_argument("--interval-seconds", type=int, default=300)
    return parser.parse_args(argv)


def run_once(mode: str | None = None) -> tuple[int, dict]:
    config = AlpacaFirstTradeConfig.from_env(mode=mode)
    system = AlpacaFirstTradeSystem(config)
    try:
        report = system.run_full_cycle()
    except AlpacaClientError as exc:
        return 1, {"status": "error", "error": str(exc)}
    return 0, report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.daemon:
        code, report = run_once(mode=args.mode)
        if code == 0:
            send_alpaca_trade_alert(report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return code

    while True:
        code, report = run_once(mode=args.mode)
        if code == 0:
            send_alpaca_trade_alert(report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        if code != 0:
            return code
        time.sleep(max(30, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
