#!/usr/bin/env python3
"""[Historical Utility] Fix portfolio: deduplicate positions, reset cash.

This script targets legacy local paths and is not part of canonical backtest flow.
"""
import json
import sys
from pathlib import Path

TRADES_FILE = Path("/home/botuser/polymarket-trading-bot/paper_trades.json")

def fix():
    with open(TRADES_FILE) as f:
        data = json.load(f)

    positions = data.get("open_positions", [])
    portfolio = data.get("portfolio", {})
    print("Current: %d open positions, $%.2f cash" % (len(positions), portfolio.get("cash", 0)))

    # Deduplicate: keep only the FIRST position per market question
    seen = {}
    unique = []
    duplicates = []
    for p in positions:
        q = p["question"]
        if q not in seen:
            seen[q] = True
            unique.append(p)
        else:
            duplicates.append(p)

    print("Unique markets: %d, duplicates removed: %d" % (len(unique), len(duplicates)))

    # Refund cash for duplicate positions
    deployed = sum(p["size_usdc"] for p in unique)

    # Reset: starting capital minus deployed unique positions
    new_cash = 75.0 - deployed
    print("Deployed in unique positions: $%.2f" % deployed)
    print("New cash balance: $%.2f" % new_cash)

    data["open_positions"] = unique
    data["portfolio"]["cash"] = new_cash

    with open(TRADES_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print("Fixed! %d positions, $%.2f cash" % (len(unique), new_cash))

if __name__ == "__main__":
    fix()
