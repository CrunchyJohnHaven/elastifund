#!/usr/bin/env python3
"""Dynamic delta calibrator — adjusts BTC5_MAX_ABS_DELTA based on realized volatility.

Runs every 30 min via cron. Reads Binance price history from the bot's DB,
computes rolling realized volatility, and writes optimal delta bounds to
the autoresearch overrides file.

The key insight: skip_delta_too_large is the #1 blocker (22% of windows).
During high-vol periods, we need wider delta thresholds. During low-vol,
tighter thresholds prevent false signals.
"""
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OVERRIDES_PATH = ROOT / "config" / "autoresearch_overrides.json"
CALIBRATION_LOG = DATA / "delta_calibration_log.json"

# All asset DBs to aggregate volatility data
DBS = {
    "btc": DATA / "btc_5min_maker.db",
    "eth": DATA / "eth_5min_maker.db",
    "sol": DATA / "sol_5min_maker.db",
}

# Volatility regime → delta bounds
# Based on 5-minute absolute delta observations:
#   Low vol: most deltas < 0.001
#   Med vol: deltas 0.001-0.003
#   High vol: deltas > 0.003
REGIMES = [
    {"name": "low_vol",  "max_vol": 0.0008,  "min_delta": 0.00005, "max_delta": 0.0025},
    {"name": "med_vol",  "max_vol": 0.0020,  "min_delta": 0.0001,  "max_delta": 0.0050},
    {"name": "high_vol", "max_vol": 0.0050,  "min_delta": 0.0002,  "max_delta": 0.0080},
    {"name": "extreme",  "max_vol": 999.0,   "min_delta": 0.0003,  "max_delta": 0.0120},
]


def compute_realized_vol(db_path: Path, lookback_windows: int = 48) -> float | None:
    """Compute realized volatility from recent delta values in the DB."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("""
            SELECT delta FROM window_trades
            WHERE delta IS NOT NULL
            ORDER BY window_start_ts DESC
            LIMIT ?
        """, (lookback_windows,)).fetchall()
        conn.close()

        if len(rows) < 10:
            return None

        deltas = [abs(r[0]) for r in rows if r[0] is not None]
        if not deltas:
            return None

        # Realized vol = standard deviation of absolute deltas
        mean_d = sum(deltas) / len(deltas)
        variance = sum((d - mean_d) ** 2 for d in deltas) / len(deltas)
        return math.sqrt(variance)
    except Exception:
        return None


def classify_regime(vol: float) -> dict:
    """Map realized volatility to a regime with delta bounds."""
    for regime in REGIMES:
        if vol <= regime["max_vol"]:
            return regime
    return REGIMES[-1]


def get_current_overrides() -> dict:
    """Read current autoresearch overrides."""
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(OVERRIDES_PATH.read_text())
    except Exception:
        return {}


def update_overrides(regime: dict, vol: float) -> None:
    """Write delta calibration to capital_stage.env (read as env var by bot)."""
    env_path = ROOT / "state" / "btc5_capital_stage.env"
    import re
    content = env_path.read_text()

    # Update or add BTC5_MAX_ABS_DELTA
    if "BTC5_MAX_ABS_DELTA=" in content:
        content = re.sub(r"BTC5_MAX_ABS_DELTA=\S+", f"BTC5_MAX_ABS_DELTA={regime['max_delta']}", content)
    else:
        content += f"\n# Dynamic delta calibration (auto-updated by delta_calibrator.py)\nBTC5_MAX_ABS_DELTA={regime['max_delta']}\n"

    env_path.write_text(content)

    # Also write metadata to overrides for audit trail
    current = get_current_overrides()
    current["_delta_calibration"] = {
        "regime": regime["name"],
        "realized_vol": round(vol, 6),
        "max_delta": regime["max_delta"],
        "min_delta": regime["min_delta"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    OVERRIDES_PATH.write_text(json.dumps(current, indent=2))


def log_calibration(vol: float, regime: dict, old_max: str | None) -> None:
    """Append to calibration log."""
    try:
        existing = json.loads(CALIBRATION_LOG.read_text()) if CALIBRATION_LOG.exists() else []
    except Exception:
        existing = []

    existing.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "realized_vol": round(vol, 6),
        "regime": regime["name"],
        "new_max_delta": regime["max_delta"],
        "new_min_delta": regime["min_delta"],
        "old_max_delta": old_max,
    })

    if len(existing) > 500:
        existing = existing[-500:]
    CALIBRATION_LOG.write_text(json.dumps(existing, indent=2))


def main():
    # Aggregate volatility across primary assets (BTC has most data)
    vols = []
    for asset, db_path in DBS.items():
        v = compute_realized_vol(db_path)
        if v is not None:
            vols.append(v)

    if not vols:
        print("No volatility data available. Skipping calibration.")
        return

    # Use max volatility across assets (most conservative)
    vol = max(vols)
    regime = classify_regime(vol)

    # Check if this is actually a change
    current = get_current_overrides()
    old_max = current.get("BTC5_MAX_ABS_DELTA")
    new_max = str(regime["max_delta"])

    if old_max == new_max:
        print(f"Delta calibration unchanged: regime={regime['name']} vol={vol:.6f} max_delta={new_max}")
        return

    update_overrides(regime, vol)
    log_calibration(vol, regime, old_max)
    print(
        f"Delta calibrated: regime={regime['name']} vol={vol:.6f} "
        f"max_delta={old_max}->{new_max} min_delta={regime['min_delta']}"
    )


if __name__ == "__main__":
    main()
