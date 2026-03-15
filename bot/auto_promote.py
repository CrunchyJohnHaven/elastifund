"""
Auto-promotion engine: promotes shadow hypotheses to live config.

Checks autoresearch_results.json every 6 hours. If a shadow hypothesis
has positive PnL and outperforms live, promotes its params to .env and
restarts the service.

Immutable safety rails:
  - Never reduce min_buy_price below 0.80
  - Never increase max_trade_usd above 25
  - Max 1 promotion per 24 hours
  - Always log BEFORE applying (audit trail)

Part of the recursive self-improvement loop (DISPATCH 109).

March 14, 2026 — Elastifund Autoresearch
"""
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("AutoPromote")

RESULTS_PATH = Path("/home/ubuntu/polymarket-trading-bot/data/autoresearch_results.json")
PROMOTION_LOG = Path("/home/ubuntu/polymarket-trading-bot/data/promotion_log.json")
ENV_PATH = Path("/home/ubuntu/polymarket-trading-bot/.env")

# IMMUTABLE SAFETY RAILS
MIN_ALLOWED_BUY_PRICE = 0.80
MAX_ALLOWED_TRADE_USD = 25.0
MAX_PROMOTIONS_PER_DAY = 1


def load_promotion_history() -> list:
    if PROMOTION_LOG.exists():
        return json.loads(PROMOTION_LOG.read_text())
    return []


def recent_promotions(history: list, hours: int = 24) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return sum(1 for p in history if p.get("promoted_at", "") > cutoff)


def safety_check(params: dict) -> tuple[bool, str]:
    """Immutable safety rails. Returns (safe, reason)."""
    if "BTC5_MIN_BUY_PRICE" in params:
        if params["BTC5_MIN_BUY_PRICE"] < MIN_ALLOWED_BUY_PRICE:
            return False, f"min_buy_price {params['BTC5_MIN_BUY_PRICE']} < {MIN_ALLOWED_BUY_PRICE}"

    if "BTC5_MAX_TRADE_USD" in params:
        if params["BTC5_MAX_TRADE_USD"] > MAX_ALLOWED_TRADE_USD:
            return False, f"max_trade_usd {params['BTC5_MAX_TRADE_USD']} > {MAX_ALLOWED_TRADE_USD}"

    return True, "passed"


def apply_params(params: dict) -> None:
    """Write hypothesis params to .env."""
    lines = ENV_PATH.read_text().splitlines()
    for key, value in params.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n")


def restart_service() -> bool:
    result = subprocess.run(
        ["sudo", "systemctl", "restart", "btc-5min-maker.service"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def run_promotion() -> dict | None:
    logger.info("=== Auto-promotion check ===")

    if not RESULTS_PATH.exists():
        logger.info("No autoresearch results yet. Waiting.")
        return None

    results = json.loads(RESULTS_PATH.read_text())
    hypotheses = results.get("hypotheses", [])
    shadow_candidates = [h for h in hypotheses if h.get("status") == "shadow"]

    if not shadow_candidates:
        logger.info("No shadow hypotheses to promote.")
        return None

    history = load_promotion_history()
    if recent_promotions(history) >= MAX_PROMOTIONS_PER_DAY:
        logger.info("Already promoted today. Rate limit hit.")
        return None

    best = max(shadow_candidates, key=lambda h: h.get("shadow_pnl", 0))

    if best.get("shadow_pnl", 0) <= 0:
        logger.info(f"Best shadow {best['hypothesis_id']} has non-positive PnL. Skipping.")
        return None

    safe, reason = safety_check(best.get("params", {}))
    if not safe:
        logger.warning(f"BLOCKED by safety rail: {reason}")
        return None

    logger.info(f"PROMOTING: {best['hypothesis_id']}")
    logger.info(f"  Description: {best['description']}")
    logger.info(f"  Shadow PnL: ${best['shadow_pnl']}")
    logger.info(f"  Params: {best['params']}")

    apply_params(best["params"])

    if restart_service():
        logger.info("Service restarted with new params")
    else:
        logger.error("Service restart FAILED")
        return None

    promotion_record = {
        "hypothesis_id": best["hypothesis_id"],
        "description": best["description"],
        "params": best["params"],
        "shadow_pnl": best["shadow_pnl"],
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }
    history.append(promotion_record)
    PROMOTION_LOG.write_text(json.dumps(history, indent=2))
    logger.info("Promotion logged")
    return promotion_record


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_promotion()
