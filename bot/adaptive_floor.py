"""
Adaptive price floor: computes optimal BTC5_MIN_BUY_PRICE from realized fills.

Runs every 2 hours via cron. Finds the price threshold that maximizes
cumulative PnL from historical fills. Writes the result to .env and
restarts the service.

Part of the recursive self-improvement loop (DISPATCH 107).

March 14, 2026 — Elastifund Autoresearch
"""
import logging
import sqlite3
import subprocess
from pathlib import Path

logger = logging.getLogger("AdaptiveFloor")

DB_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/btc_5min_maker.db")
ENV_PATH = Path("/home/ubuntu/polymarket-trading-bot/.env")
MIN_FILLS_FOR_ADAPTATION = 20
FLOOR_CANDIDATES = [round(x * 0.01, 2) for x in range(50, 100)]
SAFETY_MARGIN = 0.02
ABSOLUTE_MIN_FLOOR = 0.80  # immutable safety rail


def compute_optimal_floor() -> float | None:
    """Find the min_buy_price that maximizes cumulative PnL."""
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("""
        SELECT order_price, pnl_usd, won
        FROM window_trades
        WHERE order_status = 'live_filled'
          AND order_price IS NOT NULL
          AND pnl_usd IS NOT NULL
        ORDER BY created_at
    """).fetchall()
    conn.close()

    if len(rows) < MIN_FILLS_FOR_ADAPTATION:
        logger.info(f"Only {len(rows)} fills, need {MIN_FILLS_FOR_ADAPTATION}. Skipping.")
        return None

    best_floor = 0.50
    best_pnl = float("-inf")

    for floor in FLOOR_CANDIDATES:
        eligible = [(price, pnl) for price, pnl, _ in rows if price >= floor]
        if len(eligible) < 5:
            continue
        total_pnl = sum(pnl for _, pnl in eligible)
        if total_pnl > best_pnl:
            best_pnl = total_pnl
            best_floor = floor

    optimal = min(best_floor + SAFETY_MARGIN, 0.98)
    optimal = max(optimal, ABSOLUTE_MIN_FLOOR)  # safety rail
    logger.info(
        f"Optimal floor: {best_floor:.2f} + {SAFETY_MARGIN:.2f} safety = {optimal:.2f} "
        f"(best cumulative PnL: ${best_pnl:.2f} from {len(rows)} fills)"
    )
    return optimal


def apply_floor(new_floor: float) -> None:
    """Update .env with new BTC5_MIN_BUY_PRICE and restart service."""
    lines = ENV_PATH.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("BTC5_MIN_BUY_PRICE="):
            lines[i] = f"BTC5_MIN_BUY_PRICE={new_floor:.2f}"
            updated = True
            break
    if not updated:
        lines.append(f"BTC5_MIN_BUY_PRICE={new_floor:.2f}")

    ENV_PATH.write_text("\n".join(lines) + "\n")
    logger.info(f"Updated BTC5_MIN_BUY_PRICE={new_floor:.2f}")

    result = subprocess.run(
        ["sudo", "systemctl", "restart", "btc-5min-maker.service"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info("Service restarted successfully")
    else:
        logger.error(f"Restart failed: {result.stderr}")


def run_adaptation() -> float | None:
    optimal = compute_optimal_floor()
    if optimal is not None:
        apply_floor(optimal)
    return optimal


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    result = run_adaptation()
    if result:
        print(f"Applied new floor: {result:.2f}")
    else:
        print("Not enough data yet")
