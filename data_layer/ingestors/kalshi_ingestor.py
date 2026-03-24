"""Kalshi historical data ingestor."""
import json
import logging
import time
import math
import requests
from datetime import datetime, timezone
from typing import Generator, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
RATE_DELAY = 0.01  # Conservative delay between requests


def _utc_ts(dt_str: str) -> Optional[int]:
    if not dt_str:
        return None
    try:
        return int(datetime.fromisoformat(dt_str.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def _http_get(url: str, params: dict = None, max_retries: int = 5) -> Optional[dict]:
    for attempt in range(max_retries):
        try:
            time.sleep(RATE_DELAY)
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429 or (500 <= r.status_code <= 599):
                time.sleep(min(60, 2 ** attempt))
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Kalshi GET failed: {url}: {e}")
                return None
            time.sleep(min(60, 2 ** attempt))
    return None


def get_cutoff() -> dict:
    """Get Kalshi's historical data cutoff timestamps."""
    data = _http_get(f"{BASE_URL}/historical/cutoff")
    return data or {}


def compute_taker_fee(contracts: int, price: float) -> float:
    """Compute Kalshi taker fee: round_up(0.07 * C * P * (1-P)) to nearest $0.0001."""
    raw = 0.07 * contracts * price * (1 - price)
    return math.ceil(raw * 10000) / 10000


def compute_maker_fee(contracts: int, price: float) -> float:
    """Compute Kalshi maker fee: round_up(0.0175 * C * P * (1-P)) to nearest $0.0001."""
    raw = 0.0175 * contracts * price * (1 - price)
    return math.ceil(raw * 10000) / 10000


def scan_settled_markets(min_settled_ts: int = 0) -> Generator[Dict, None, None]:
    """Scan for settled markets since timestamp."""
    cursor = None
    while True:
        params = {"status": "settled", "limit": 200}
        if min_settled_ts > 0:
            params["min_settled_ts"] = min_settled_ts
        if cursor:
            params["cursor"] = cursor

        resp = _http_get(f"{BASE_URL}/markets", params=params)
        if not resp or "markets" not in resp:
            return

        for m in resp["markets"]:
            yield m

        cursor = resp.get("cursor")
        if not cursor:
            return


def scan_historical_markets(min_settled_ts: int = 0) -> Generator[Dict, None, None]:
    """Scan historical partition for older settled markets."""
    cursor = None
    while True:
        params = {"status": "settled", "limit": 200}
        if min_settled_ts > 0:
            params["min_settled_ts"] = min_settled_ts
        if cursor:
            params["cursor"] = cursor

        resp = _http_get(f"{BASE_URL}/historical/markets", params=params)
        if not resp or "markets" not in resp:
            return

        for m in resp["markets"]:
            yield m

        cursor = resp.get("cursor")
        if not cursor:
            return


def parse_market(m: dict) -> dict:
    """Parse a Kalshi market response into our schema."""
    ticker = m.get("ticker", "")
    close_ts = _utc_ts(m.get("close_time"))
    settle_ts = _utc_ts(m.get("settlement_ts"))

    outcome_yes = None
    settlement_value = 0.0
    if m.get("result") == "yes":
        outcome_yes = 1
        settlement_value = float(m.get("settlement_value_dollars", "1.0"))
    elif m.get("result") == "no":
        outcome_yes = 0
        settlement_value = 0.0
    elif m.get("result"):
        # Other result values
        outcome_yes = 0
        settlement_value = float(m.get("settlement_value_dollars", "0.0"))

    ttr = (settle_ts - close_ts) if (settle_ts and close_ts) else 0

    return {
        "venue": "kalshi",
        "market_id": ticker,
        "title": m.get("title"),
        "category": m.get("category"),
        "rule_type": m.get("market_type", "binary"),
        "rules_primary": m.get("rules_primary"),
        "rules_secondary": m.get("rules_secondary"),
        "settlement_source": None,  # Fill from series/event metadata
        "open_ts": _utc_ts(m.get("open_time")),
        "close_ts": close_ts,
        "settle_ts": settle_ts,
        "fee_model": "kalshi_parabolic",
        "taker_fee_param": 0.07,
        "maker_fee_param": 0.0175,
        "metadata_json": json.dumps(m),
        "outcome_yes": outcome_yes,
        "settlement_value": settlement_value,
        "time_to_resolution_s": ttr,
    }


def fetch_candlesticks(ticker: str, start_ts: int, end_ts: int,
                        period_minutes: int = 60, use_historical: bool = False) -> list:
    """Fetch candlestick data for a market."""
    base = f"{BASE_URL}/historical" if use_historical else BASE_URL

    data = _http_get(
        f"{base}/markets/{ticker}/candlesticks",
        params={
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": period_minutes,
        },
    )

    if not data or "candlesticks" not in data:
        return []

    return data["candlesticks"]
