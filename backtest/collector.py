"""Fetch resolved markets from Gamma API for backtesting."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Filters for expanded dataset
MIN_VOLUME_USD = 500.0   # Only markets with >$500 volume
MAX_AGE_DAYS = 90        # Resolved within last 90 days


def fetch_resolved_markets(
    target_count: int = 2000,
    rate_limit: float = 0.5,
    min_volume: float = MIN_VOLUME_USD,
    max_age_days: int = MAX_AGE_DAYS,
    exhaust_all: bool = True,
) -> list[dict]:
    """Paginate through ALL resolved markets on Gamma API.

    Args:
        target_count: Minimum number of markets to fetch. If exhaust_all is True,
            continues until API is exhausted regardless of this count.
        rate_limit: Seconds between API requests.
        min_volume: Minimum market volume in USD.
        max_age_days: Only include markets resolved within this many days.
        exhaust_all: If True, keep paginating until API returns no more results,
            not just until target_count is reached.
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    markets = []
    offset = 0
    page_size = 100
    empty_pages = 0
    max_empty_pages = 3  # Stop after 3 consecutive empty pages

    while exhaust_all or len(markets) < target_count:
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
            empty_pages += 1
            logger.info(f"Empty page at offset {offset} ({empty_pages}/{max_empty_pages})")
            if empty_pages >= max_empty_pages:
                logger.info("Max empty pages reached, stopping pagination")
                break
            offset += page_size
            time.sleep(rate_limit)
            continue

        empty_pages = 0  # Reset on non-empty page
        page_valid = 0

        for m in page:
            parsed = _parse_market(m, min_volume=min_volume, cutoff_date=cutoff_date)
            if parsed:
                markets.append(parsed)
                page_valid += 1

        logger.info(
            f"Fetched page offset={offset}, got {len(page)} raw, "
            f"{page_valid} valid this page, {len(markets)} valid total"
        )

        if len(page) < page_size:
            logger.info("Partial page received, API exhausted")
            break

        offset += page_size
        time.sleep(rate_limit)

    logger.info(f"Collection complete: {len(markets)} valid Yes/No binary markets")
    return markets


def _parse_market(
    raw: dict,
    min_volume: float = MIN_VOLUME_USD,
    cutoff_date: Optional[datetime] = None,
) -> Optional[dict]:
    """Parse a raw Gamma market into our format, filtering non-binary.

    Args:
        raw: Raw market dict from Gamma API.
        min_volume: Minimum volume in USD to include.
        cutoff_date: Only include markets resolved after this date.
    """
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

    # Volume filter
    volume = float(raw.get("volume", 0) or 0)
    if volume < min_volume:
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

    # Date filter — check endDate or endDateIso
    end_date_str = raw.get("endDate") or raw.get("end_date_iso", "")
    if cutoff_date and end_date_str:
        try:
            end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            if end_dt < cutoff_date:
                return None
        except (ValueError, TypeError):
            pass  # If we can't parse the date, still include it

    return {
        "id": raw.get("id", ""),
        "question": question,
        "outcomes": outcomes,
        "actual_outcome": actual_outcome,
        "final_yes_price": yes_price,
        "final_no_price": no_price,
        "volume": volume,
        "liquidity": float(raw.get("liquidity", 0) or 0),
        "end_date": end_date_str,
        "description": (raw.get("description") or "")[:500],
    }


def collect(
    target_count: int = 2000,
    min_volume: float = MIN_VOLUME_USD,
    max_age_days: int = MAX_AGE_DAYS,
    exhaust_all: bool = True,
) -> dict:
    """Main collection pipeline with incremental caching.

    Args:
        target_count: Minimum markets to collect.
        min_volume: Volume filter in USD.
        max_age_days: Recency filter in days.
        exhaust_all: Paginate until API exhausted (ignore target_count cap).
    """
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
    fetched = fetch_resolved_markets(
        target_count=target_count,
        min_volume=min_volume,
        max_age_days=max_age_days,
        exhaust_all=exhaust_all,
    )

    # Merge (new data overwrites old for same id)
    for m in fetched:
        existing[m["id"]] = m

    markets_list = list(existing.values())

    # Stats
    yes_won = sum(1 for m in markets_list if m["actual_outcome"] == "YES_WON")
    no_won = sum(1 for m in markets_list if m["actual_outcome"] == "NO_WON")
    avg_volume = sum(m.get("volume", 0) for m in markets_list) / len(markets_list) if markets_list else 0

    result = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_markets": len(markets_list),
        "yes_won": yes_won,
        "no_won": no_won,
        "avg_volume": round(avg_volume, 2),
        "min_volume_filter": min_volume,
        "max_age_days_filter": max_age_days,
        "markets": markets_list,
    }

    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)

    logger.info(f"Saved {len(markets_list)} markets ({yes_won} YES, {no_won} NO, avg vol ${avg_volume:.0f})")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Collect resolved Polymarket markets for backtesting")
    parser.add_argument("--count", type=int, default=2000, help="Target market count")
    parser.add_argument("--min-volume", type=float, default=MIN_VOLUME_USD, help="Min volume USD")
    parser.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS, help="Max age in days")
    parser.add_argument("--no-exhaust", action="store_true", help="Stop at target count instead of exhausting API")
    args = parser.parse_args()
    result = collect(
        target_count=args.count,
        min_volume=args.min_volume,
        max_age_days=args.max_age_days,
        exhaust_all=not args.no_exhaust,
    )
    print(f"\nCollected {result['total_markets']} markets")
    print(f"  YES won: {result['yes_won']}")
    print(f"  NO won: {result['no_won']}")
    print(f"  Avg volume: ${result['avg_volume']:,.2f}")
