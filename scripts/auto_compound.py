#!/usr/bin/env python3
"""Auto-compound: sync BTC5_BANKROLL_USD with live CLOB balance.

Run every 30 minutes via cron. Reads actual balance from Polymarket CLOB,
updates state/btc5_capital_stage.env so the graduated Kelly ramp sizes
positions against the real portfolio — creating automatic compound growth.

Logs every update to data/compound_log.json for audit trail.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "polymarket-bot"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_clob_balance() -> float | None:
    """Fetch USDC balance from Polymarket CLOB using same auth as the bot."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))
        from polymarket_clob import build_authenticated_clob_client
        import logging

        private_key = os.environ.get("POLY_PRIVATE_KEY", "") or os.environ.get("POLYMARKET_PK", "")
        safe_address = os.environ.get("POLY_SAFE_ADDRESS", "") or os.environ.get("POLYMARKET_FUNDER", "")

        if not private_key or not safe_address:
            print("Missing POLY_PRIVATE_KEY or POLY_SAFE_ADDRESS")
            return None

        client, sig_type, probes = build_authenticated_clob_client(
            private_key=private_key,
            safe_address=safe_address,
            configured_signature_type=1,
            logger=logging.getLogger("auto_compound"),
        )
        # Extract balance from the probe that authenticated successfully
        balance = 0.0
        for p in probes:
            if p.get("auth_ok"):
                balance = float(p.get("balance_usd", 0))
                break
        if balance == 0:
            # Fallback: direct balance check
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            resp = client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig_type)
            )
            raw = float(resp.get("balance", 0))
            balance = raw / 1e6 if raw > 1e4 else raw
        return round(balance, 2)
    except Exception as e:
        print(f"CLOB balance fetch failed: {e}")
        return None


def update_capital_stage(new_bankroll: float) -> tuple[float, float]:
    """Update BTC5_BANKROLL_USD in capital_stage.env. Returns (old, new)."""
    env_path = Path(__file__).resolve().parent.parent / "state" / "btc5_capital_stage.env"
    content = env_path.read_text()
    match = re.search(r"BTC5_BANKROLL_USD=(\S+)", content)
    old_val = float(match.group(1)) if match else 0.0
    new_content = re.sub(
        r"BTC5_BANKROLL_USD=\S+",
        f"BTC5_BANKROLL_USD={int(new_bankroll)}",
        content,
    )
    env_path.write_text(new_content)
    return old_val, new_bankroll


def log_update(old_bankroll: float, new_bankroll: float, balance: float) -> None:
    """Append to compound log."""
    log_path = Path(__file__).resolve().parent.parent / "data" / "compound_log.json"
    try:
        existing = json.loads(log_path.read_text()) if log_path.exists() else []
    except Exception:
        existing = []
    existing.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "clob_balance": balance,
        "old_bankroll": old_bankroll,
        "new_bankroll": new_bankroll,
        "change_pct": round((new_bankroll - old_bankroll) / old_bankroll * 100, 2) if old_bankroll > 0 else 0,
    })
    if len(existing) > 1000:
        existing = existing[-1000:]
    log_path.write_text(json.dumps(existing, indent=2))


def main() -> None:
    balance = get_clob_balance()
    if balance is None:
        print("Could not fetch balance. Skipping.")
        return
    if balance < 10:
        print(f"Balance suspiciously low (${balance}). Skipping.")
        return

    old, new = update_capital_stage(balance)
    change = new - old
    pct = (change / old * 100) if old > 0 else 0
    log_update(old, new, balance)
    print(f"Bankroll synced: ${old:.0f} → ${new:.0f} ({pct:+.1f}%) [CLOB balance: ${balance:.2f}]")


if __name__ == "__main__":
    main()
