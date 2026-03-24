"""Alpaca historical data ingestor."""
import json
import logging
import os
import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

STOCKS_BASE = "https://data.alpaca.markets/v2/stocks"
CRYPTO_BASE = "https://data.alpaca.markets/v1beta3/crypto/us"
OPTIONS_BASE = "https://data.alpaca.markets/v1beta1/options"

API_KEY = os.environ.get("ALPACA_API_KEY", "")
API_SECRET = os.environ.get("ALPACA_API_SECRET", "")


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": API_SECRET,
    }


def _http_get(url: str, params: dict = None, max_retries: int = 5) -> Optional[dict]:
    for attempt in range(max_retries):
        try:
            time.sleep(0.01)
            r = requests.get(url, params=params, headers=_headers(), timeout=30)
            if r.status_code == 429 or (500 <= r.status_code <= 599):
                time.sleep(min(60, 2 ** attempt))
                continue
            if r.status_code == 403:
                logger.warning(f"Alpaca 403 (check API keys): {url}")
                return None
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Alpaca GET failed: {url}: {e}")
                return None
            time.sleep(min(60, 2 ** attempt))
    return None


def fetch_stock_bars(symbols: List[str], start_iso: str, end_iso: str,
                      timeframe: str = "1Hour") -> Dict[str, list]:
    """Fetch historical stock bars."""
    data = _http_get(
        f"{STOCKS_BASE}/bars",
        params={
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start_iso,
            "end": end_iso,
            "limit": 10000,
        },
    )
    return data.get("bars", {}) if data else {}


def fetch_crypto_bars(symbols: List[str], start_iso: str, end_iso: str,
                       timeframe: str = "1Hour") -> Dict[str, list]:
    """Fetch historical crypto bars."""
    data = _http_get(
        f"{CRYPTO_BASE}/bars",
        params={
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start_iso,
            "end": end_iso,
            "limit": 10000,
        },
    )
    return data.get("bars", {}) if data else {}


def fetch_option_snapshots(underlying: str) -> list:
    """Fetch current option chain snapshots (includes Greeks)."""
    data = _http_get(f"{OPTIONS_BASE}/snapshots/{underlying}")
    return data.get("snapshots", {}) if data else {}
