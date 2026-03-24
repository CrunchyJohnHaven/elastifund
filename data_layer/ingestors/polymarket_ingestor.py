"""Polymarket historical data ingestor."""
import json
import logging
import time
import requests
from datetime import datetime, timezone
from typing import Generator, Dict, Optional

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"

# Rate limit: 15000/10s for Gamma, 9000/10s for CLOB
GAMMA_DELAY = 0.001  # ~1ms between requests (well within limits)
CLOB_DELAY = 0.002


def _utc_ts(dt_str: str) -> Optional[int]:
    """Parse ISO8601 string to unix timestamp."""
    if not dt_str:
        return None
    try:
        return int(datetime.fromisoformat(dt_str.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        try:
            return int(float(dt_str))
        except (ValueError, TypeError):
            return None


def _http_get(url: str, params: dict = None, max_retries: int = 5, delay: float = 0.001) -> Optional[dict]:
    """HTTP GET with retry and backoff."""
    for attempt in range(max_retries):
        try:
            time.sleep(delay)
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429 or (500 <= r.status_code <= 599):
                backoff = min(60, 2 ** attempt)
                logger.warning(f"HTTP {r.status_code} from {url}, retrying in {backoff}s")
                time.sleep(backoff)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed after {max_retries} retries: {url}: {e}")
                return None
            time.sleep(min(60, 2 ** attempt))
    return None


def scan_closed_markets(watermark_ts: int = 0) -> Generator[Dict, None, None]:
    """Scan Gamma for closed/resolved markets newer than watermark."""
    offset = 0
    limit = 200
    while True:
        data = _http_get(
            f"{GAMMA_BASE}/markets",
            params={"closed": "true", "limit": limit, "offset": offset},
            delay=GAMMA_DELAY,
        )
        if not data or len(data) == 0:
            return

        for m in data:
            closed_time = m.get("closedTime") or m.get("endDate")
            if closed_time:
                ct = _utc_ts(closed_time)
                if ct and ct <= watermark_ts:
                    continue  # Already ingested
            yield m

        if len(data) < limit:
            return
        offset += limit


def parse_market(m: dict) -> dict:
    """Parse a Gamma market response into our schema fields."""
    condition_id = m.get("conditionId", "")
    clob_token_ids = m.get("clobTokenIds", [])
    yes_token = clob_token_ids[0] if clob_token_ids else ""

    # Try to determine resolution outcome
    # Gamma doesn't have a clean "winner" field; use heuristics
    uma_status = m.get("umaResolutionStatus", "")
    outcome_yes = None
    if uma_status in ("resolved", "settled"):
        # Check if outcomes/prices indicate YES won
        outcomes = m.get("outcomes", [])
        outcome_prices = m.get("outcomePrices", [])
        if outcome_prices and len(outcome_prices) >= 2:
            try:
                yes_final = float(outcome_prices[0])
                if yes_final > 0.95:
                    outcome_yes = 1
                elif yes_final < 0.05:
                    outcome_yes = 0
            except (ValueError, TypeError):
                pass

    return {
        "venue": "polymarket",
        "market_id": condition_id,
        "title": m.get("question", m.get("title", "")),
        "category": m.get("category"),
        "rule_type": "binary",
        "settlement_source": m.get("resolutionSource"),
        "resolution_source": m.get("resolutionSource"),
        "open_ts": _utc_ts(m.get("startDate")),
        "close_ts": _utc_ts(m.get("endDate") or m.get("closedTime")),
        "settle_ts": _utc_ts(m.get("closedTime")),
        "fee_model": "polymarket_basefee",
        "taker_fee_param": m.get("takerBaseFee"),
        "maker_fee_param": m.get("makerBaseFee"),
        "metadata_json": json.dumps(m),
        "yes_token_id": yes_token,
        "outcome_yes": outcome_yes,
    }


def fetch_yes_price_history(yes_token_id: str, start_ts: int, end_ts: int,
                             interval: str = "1h") -> list:
    """Fetch YES price history from CLOB."""
    if not yes_token_id:
        return []

    data = _http_get(
        f"{CLOB_BASE}/prices-history",
        params={
            "market": yes_token_id,
            "interval": interval,
            "startTs": start_ts,
            "endTs": end_ts,
        },
        delay=CLOB_DELAY,
    )

    if not data or "history" not in data:
        return []

    return [
        {"ts": int(pt["t"]), "price": float(pt["p"])}
        for pt in data["history"]
        if "t" in pt and "p" in pt
    ]
