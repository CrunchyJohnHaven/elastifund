"""Fetch resolved markets from Gamma API for backtesting."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def fetch_resolved_markets(target_count: int = 500, rate_limit: float = 1.0) -> list[dict]:
    """Paginate Gamma API for closed, resolved binary Yes/No markets."""
    markets = []
    offset = 0
    page_size = 100

    while len(markets) < target_count:
        params = {
            "closed": "true",
            "limit": page_size,
            "offset": offset,
        }
        try:
            resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=30)
            resp.raise_for_status()
            page = resp.json()
        except Exception as e:
            logger.error(f"Gamma API error at offset {offset}: {e}")
            break

        if not page:
            logger.info(f"No more markets at offset {offset}")
            break

        for m in page:
            parsed = _parse_market(m)
            if parsed:
                markets.append(parsed)

        logger.info(f"Fetched page offset={offset}, got {len(page)} raw, {len(markets)} valid total")

        if len(page) < page_size:
            break

        offset += page_size
        time.sleep(rate_limit)

    logger.info(f"Collection complete: {len(markets)} valid Yes/No binary markets")
    return markets


def _parse_market(raw: dict) -> Optional[dict]:
    """Parse a raw Gamma market into our format, filtering non-binary."""
    # Must have outcomes
    outcomes = raw.get("outcomes")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            return None

    if not outcomes or not isinstance(outcomes, list):
        return None

    # STRICT: only Yes/No binary markets
    outcome_lower = [o.strip().lower() for o in outcomes]
    if outcome_lower != ["yes", "no"]:
        return None

    # Must have outcome prices to determine result
    prices_raw = raw.get("outcomePrices")
    if isinstance(prices_raw, str):
        try:
            prices_raw = json.loads(prices_raw)
        except json.JSONDecodeError:
            return None

    if not prices_raw or not isinstance(prices_raw, list) or len(prices_raw) < 2:
        return None

    try:
        yes_price = float(prices_raw[0])
        no_price = float(prices_raw[1])
    except (ValueError, TypeError):
        return None

    # Determine actual outcome — resolved markets have one side near 1.0
    if yes_price > 0.90:
        actual_outcome = "YES_WON"
    elif no_price > 0.90:
        actual_outcome = "NO_WON"
    else:
        # Not clearly resolved
        return None

    question = raw.get("question", "").strip()
    if not question:
        return None

    return {
        "id": raw.get("id", ""),
        "question": question,
        "outcomes": outcomes,
        "actual_outcome": actual_outcome,
        "final_yes_price": yes_price,
        "final_no_price": no_price,
        "volume": float(raw.get("volume", 0) or 0),
        "liquidity": float(raw.get("liquidity", 0) or 0),
        "end_date": raw.get("endDate") or raw.get("end_date_iso", ""),
        "description": (raw.get("description") or "")[:500],
    }


def collect(target_count: int = 500) -> dict:
    """Main collection pipeline with incremental caching."""
    cache_path = os.path.join(DATA_DIR, "historical_markets.json")
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load existing cache
    existing = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            data = json.load(f)
            existing = {m["id"]: m for m in data.get("markets", [])}
        logger.info(f"Loaded {len(existing)} cached markets")

    # Fetch new
    fetched = fetch_resolved_markets(target_count=target_count)

    # Merge
    for m in fetched:
        existing[m["id"]] = m

    markets_list = list(existing.values())

    # Stats
    yes_won = sum(1 for m in markets_list if m["actual_outcome"] == "YES_WON")
    no_won = sum(1 for m in markets_list if m["actual_outcome"] == "NO_WON")

    result = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_markets": len(markets_list),
        "yes_won": yes_won,
        "no_won": no_won,
        "markets": markets_list,
    }

    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)

    logger.info(f"Saved {len(markets_list)} markets ({yes_won} YES, {no_won} NO)")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500)
    args = parser.parse_args()
    result = collect(target_count=args.count)
    print(f"\nCollected {result['total_markets']} markets")
    print(f"  YES won: {result['yes_won']}")
    print(f"  NO won: {result['no_won']}")
