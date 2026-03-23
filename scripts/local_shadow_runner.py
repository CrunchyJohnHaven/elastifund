#!/usr/bin/env python3
"""
Local Twin Control Plane — Shadow Runner
=========================================
Runs key Elastifund loops locally against live data in shadow mode.
No orders are placed.  All outputs go to reports/local_shadow/.

This is the documented local entrypoint for live-data testing, orchestration
debugging, and artifact generation without touching the Lightsail execution host.

Modes
-----
  btc5        — Pull live Polymarket BTC5 markets, simulate signal decisions
  sensorium   — Collect live market observations into sensorium artifact
  reconcile   — Compare wallet-export truth vs runtime_truth_latest.json
  all         — Run all three lanes sequentially

Usage
-----
  python3 scripts/local_shadow_runner.py --mode all --once
  python3 scripts/local_shadow_runner.py --mode btc5
  python3 scripts/local_shadow_runner.py --mode reconcile --once

Environment
-----------
  POLY_DATA_API_ADDRESS   — Polymarket proxy wallet address (for reconcile)
  POLY_USDC_ADDRESS       — USDC contract (optional, for balance check)

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.request

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHADOW_DIR = PROJECT_ROOT / "reports" / "local_shadow"
RUNTIME_TRUTH = PROJECT_ROOT / "reports" / "runtime_truth_latest.json"
LAUNCH_PACKET = PROJECT_ROOT / "reports" / "launch_packet_latest.json"

PROXY_WALLET = os.environ.get(
    "POLY_DATA_API_ADDRESS", "0xb2fef31cf185b75d0c9c77bd1f8fe9fd576f69a5"
)
DATA_API = "https://data-api.polymarket.com"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("JJ.local_shadow")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "elastifund-shadow/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def write_shadow(name: str, payload: dict[str, Any]) -> Path:
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    path = SHADOW_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info("wrote %s", path.relative_to(PROJECT_ROOT))
    return path


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Lane: BTC5 shadow
# ---------------------------------------------------------------------------


BTC5_MARKETS_URL = (
    f"{DATA_API}/markets"
    "?tag=crypto&active=true&closed=false&limit=50"
)

_BTC5_KEYWORDS = ("bitcoin", "btc", "5-minute", "5min")


def _is_btc5_market(market: dict[str, Any]) -> bool:
    q = (market.get("question") or "").lower()
    return any(k in q for k in _BTC5_KEYWORDS)


def _shadow_signal(market: dict[str, Any]) -> dict[str, Any]:
    """Simulate what the BTC5 maker would decide — shadow only, no order placed."""
    tokens = market.get("tokens") or []
    yes_tok = next((t for t in tokens if t.get("outcome") == "YES"), {})
    no_tok = next((t for t in tokens if t.get("outcome") == "NO"), {})
    yes_price = float(yes_tok.get("price", 0.5))
    no_price = float(no_tok.get("price", 0.5))

    # Rough signal: if YES is near 0.5 and below, prefer maker DOWN (BUY NO)
    mid = yes_price
    decision = "SKIP"
    reason = "midpoint_neutral"
    if mid < 0.45:
        decision = "MAKER_BUY_NO"
        reason = "down_bias_signal"
    elif mid > 0.55:
        decision = "MAKER_BUY_YES"
        reason = "up_bias_signal"

    return {
        "market_id": market.get("conditionId") or market.get("id"),
        "question": market.get("question"),
        "yes_price": yes_price,
        "no_price": no_price,
        "shadow_decision": decision,
        "shadow_reason": reason,
        "volume_24h": market.get("volume24hr"),
    }


async def run_btc5_shadow() -> dict[str, Any]:
    logger.info("[btc5] fetching live BTC5 markets from Polymarket data API")
    try:
        raw = fetch_json(BTC5_MARKETS_URL)
        markets = raw if isinstance(raw, list) else raw.get("data") or raw.get("markets") or []
    except Exception as exc:
        logger.error("[btc5] fetch failed: %s", exc)
        markets = []

    btc5 = [m for m in markets if _is_btc5_market(m)]
    signals = [_shadow_signal(m) for m in btc5]

    maker = [s for s in signals if s["shadow_decision"].startswith("MAKER")]
    skips = [s for s in signals if s["shadow_decision"] == "SKIP"]

    summary = {
        "artifact": "btc5_shadow",
        "generated_at": utc_now(),
        "mode": "shadow",
        "btc5_markets_found": len(btc5),
        "shadow_maker_signals": len(maker),
        "shadow_skips": len(skips),
        "signals": signals,
    }
    write_shadow("btc5_shadow", summary)
    logger.info("[btc5] %d markets, %d maker signals, %d skips", len(btc5), len(maker), len(skips))
    return summary


# ---------------------------------------------------------------------------
# Lane: Sensorium
# ---------------------------------------------------------------------------


async def run_sensorium() -> dict[str, Any]:
    """Collect live market observations into a sensorium artifact."""
    logger.info("[sensorium] collecting market observations")

    observations: list[dict[str, Any]] = []

    # 1. Active market count by category
    try:
        raw = fetch_json(f"{DATA_API}/markets?active=true&closed=false&limit=200")
        markets = raw if isinstance(raw, list) else raw.get("data") or raw.get("markets") or []
        total = len(markets)
        by_tag: dict[str, int] = {}
        for m in markets:
            for tag in (m.get("tags") or []):
                by_tag[tag] = by_tag.get(tag, 0) + 1
        observations.append({
            "type": "market_census",
            "total_active": total,
            "by_tag": by_tag,
        })
        logger.info("[sensorium] %d active markets across %d tags", total, len(by_tag))
    except Exception as exc:
        logger.warning("[sensorium] market census failed: %s", exc)

    # 2. Recent wallet activity
    try:
        raw = fetch_json(
            f"{DATA_API}/activity?user={PROXY_WALLET}&limit=20"
        )
        trades = raw if isinstance(raw, list) else raw.get("data") or []
        observations.append({
            "type": "wallet_activity",
            "recent_trade_count": len(trades),
            "trades": trades[:5],  # store top 5 for context
        })
        logger.info("[sensorium] %d recent wallet trades", len(trades))
    except Exception as exc:
        logger.warning("[sensorium] wallet activity failed: %s", exc)

    # 3. Open positions snapshot
    try:
        raw = fetch_json(
            f"{DATA_API}/positions?user={PROXY_WALLET}&sizeThreshold=0.01"
        )
        positions = raw if isinstance(raw, list) else raw.get("data") or raw.get("positions") or []
        open_pos = [p for p in positions if float(p.get("size", 0)) > 0]
        observations.append({
            "type": "open_positions_snapshot",
            "count": len(open_pos),
            "positions": open_pos[:10],
        })
        logger.info("[sensorium] %d open positions", len(open_pos))
    except Exception as exc:
        logger.warning("[sensorium] positions fetch failed: %s", exc)

    summary = {
        "artifact": "sensorium",
        "generated_at": utc_now(),
        "mode": "shadow",
        "observation_count": len(observations),
        "observations": observations,
    }
    write_shadow("sensorium", summary)
    return summary


# ---------------------------------------------------------------------------
# Lane: Reconcile
# ---------------------------------------------------------------------------


async def run_reconcile() -> dict[str, Any]:
    """Compare local runtime_truth with live wallet data."""
    logger.info("[reconcile] loading runtime_truth_latest.json")
    runtime_truth = load_json(RUNTIME_TRUTH) or {}
    launch_packet = load_json(LAUNCH_PACKET) or {}

    # Fetch live wallet value
    live_open: list[dict] = []
    live_closed: list[dict] = []
    live_free: float = 0.0

    try:
        raw = fetch_json(
            f"{DATA_API}/positions?user={PROXY_WALLET}&sizeThreshold=0.01"
        )
        positions = raw if isinstance(raw, list) else raw.get("data") or raw.get("positions") or []
        live_open = [p for p in positions if float(p.get("size", 0)) > 0]
        live_free = sum(float(p.get("cashBalance", 0)) for p in positions[:1])
    except Exception as exc:
        logger.warning("[reconcile] live positions fetch failed: %s", exc)

    try:
        raw = fetch_json(
            f"{DATA_API}/value?user={PROXY_WALLET}"
        )
        live_free = float(raw.get("portfolioValue") or raw.get("value") or live_free)
    except Exception as exc:
        logger.warning("[reconcile] portfolio value fetch failed: %s", exc)

    # Extract runtime truth fields
    rt_mode = runtime_truth.get("trading_mode") or runtime_truth.get("mode") or "unknown"
    rt_open = runtime_truth.get("open_positions") or []
    rt_capital = runtime_truth.get("free_capital_usd") or runtime_truth.get("wallet_free_usd") or 0.0

    # Compare
    open_count_match = len(live_open) == len(rt_open) if isinstance(rt_open, list) else False
    discrepancies: list[str] = []
    if not open_count_match:
        discrepancies.append(
            f"open_positions: live={len(live_open)} runtime={len(rt_open) if isinstance(rt_open, list) else 'n/a'}"
        )

    lp_mode = launch_packet.get("trading_mode") or launch_packet.get("mode") or "unknown"
    mode_match = (rt_mode == lp_mode)
    if not mode_match:
        discrepancies.append(f"mode: runtime_truth={rt_mode!r} launch_packet={lp_mode!r}")

    summary = {
        "artifact": "truth_reconciliation",
        "generated_at": utc_now(),
        "live": {
            "open_positions": len(live_open),
            "free_capital_usd": live_free,
        },
        "runtime_truth": {
            "mode": rt_mode,
            "open_positions": len(rt_open) if isinstance(rt_open, list) else rt_open,
            "free_capital_usd": rt_capital,
        },
        "launch_packet_mode": lp_mode,
        "discrepancies": discrepancies,
        "reconciled": len(discrepancies) == 0,
    }
    write_shadow("truth_reconciliation", summary)

    if discrepancies:
        logger.warning("[reconcile] %d discrepancies: %s", len(discrepancies), discrepancies)
    else:
        logger.info("[reconcile] truth reconciled — no discrepancies")
    return summary


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


LANE_MAP = {
    "btc5": run_btc5_shadow,
    "sensorium": run_sensorium,
    "reconcile": run_reconcile,
}

INTERVAL_SECONDS = int(os.environ.get("SHADOW_INTERVAL_SECONDS", "300"))


async def run_once(mode: str) -> None:
    lanes = list(LANE_MAP.keys()) if mode == "all" else [mode]
    for lane in lanes:
        fn = LANE_MAP[lane]
        try:
            await fn()
        except Exception as exc:
            logger.error("[%s] lane failed: %s", lane, exc)


async def run_daemon(mode: str) -> None:
    logger.info("Local shadow runner starting — mode=%s interval=%ds", mode, INTERVAL_SECONDS)
    while True:
        t0 = time.monotonic()
        await run_once(mode)
        elapsed = time.monotonic() - t0
        sleep = max(0.0, INTERVAL_SECONDS - elapsed)
        logger.info("cycle done in %.1fs, sleeping %.0fs", elapsed, sleep)
        await asyncio.sleep(sleep)


def main() -> None:
    global INTERVAL_SECONDS
    parser = argparse.ArgumentParser(description="Elastifund local shadow runner")
    parser.add_argument(
        "--mode",
        choices=["btc5", "sensorium", "reconcile", "all"],
        default="all",
        help="Which shadow lane(s) to run",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle then exit (default: continuous daemon)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=INTERVAL_SECONDS,
        help="Seconds between cycles in daemon mode",
    )
    args = parser.parse_args()

    INTERVAL_SECONDS = args.interval

    if args.once:
        asyncio.run(run_once(args.mode))
    else:
        asyncio.run(run_daemon(args.mode))


if __name__ == "__main__":
    main()
