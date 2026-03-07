#!/usr/bin/env python3
"""
Kalshi Weather + NWS Arbitrage Scanner (Instance 5).

Default mode is paper-only. Live order placement requires --execute.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

try:
    from kalshi_python import Configuration as KalshiConfig, KalshiClient
except ImportError:  # pragma: no cover - handled in runtime checks
    KalshiClient = None
    KalshiConfig = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - optional convenience only
    pass


NWS_BASE = "https://api.weather.gov"
DATA_DIR = Path("data")
SIGNALS_LOG = DATA_DIR / "kalshi_weather_signals.jsonl"
ORDERS_LOG = DATA_DIR / "kalshi_weather_orders.jsonl"

CITY_CONFIG = {
    "NYC": {
        "name": "New York City",
        "lat": 40.7829,
        "lon": -73.9654,
        "aliases": ["new york", "nyc", "central park"],
        "ticker_prefixes": ["KXHIGHNY", "KXRAINNYC", "KXRAINNYCM"],
    },
    "CHI": {
        "name": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "aliases": ["chicago", "o'hare", "ohare"],
        "ticker_prefixes": ["KXHIGHCH"],
    },
    "MIA": {
        "name": "Miami",
        "lat": 25.7617,
        "lon": -80.1918,
        "aliases": ["miami"],
        "ticker_prefixes": ["KXHIGHMI"],
    },
    "AUS": {
        "name": "Austin",
        "lat": 30.2672,
        "lon": -97.7431,
        "aliases": ["austin"],
        "ticker_prefixes": ["KXHIGHAUS"],
    },
    "LAX": {
        "name": "Los Angeles",
        "lat": 34.0522,
        "lon": -118.2437,
        "aliases": ["los angeles"],
        "ticker_prefixes": ["KXHIGHLA"],
    },
}

logger = logging.getLogger("kalshi.weather_arb")


@dataclass
class ForecastSnapshot:
    city: str
    target_date: str
    high_temp_f: Optional[float]
    pop_probability: Optional[float]
    source_period: str


@dataclass
class WeatherSignal:
    timestamp: str
    city: str
    market_ticker: str
    market_title: str
    market_type: str  # rain | temperature
    side: str  # yes | no
    edge: float
    model_probability: float
    order_probability: float
    spread: float
    reason: str
    source: str = "kalshi_weather_nws"
    confidence: float = 0.0


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes")


def _json_get(url: str, timeout: float = 12.0) -> dict:
    resp = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Elastifund/1.0 (weather-arb)"},
    )
    resp.raise_for_status()
    return resp.json()


def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _to_prob(val: Any) -> Optional[float]:
    """Convert Kalshi cents-like field to [0,1] probability."""
    f = _safe_float(val, None)
    if f is None:
        return None
    if f > 1.0:
        f /= 100.0
    return max(0.0, min(1.0, f))


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _norm_cdf(x: float, mean: float, std: float) -> float:
    z = (x - mean) / (std * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def parse_temperature_contract(text: str) -> Optional[tuple[str, float, Optional[float]]]:
    """Parse basic temp contract shapes from market title/subtitle."""
    s = text.lower()

    # e.g., "60-64" or "between 60 and 64"
    import re
    m = re.search(r"(\d{1,3})\s*[-–]\s*(\d{1,3})", s)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2))
        if hi >= lo:
            return ("range", lo, hi)

    m = re.search(r"between\s+(\d{1,3})\s+and\s+(\d{1,3})", s)
    if m:
        lo = float(m.group(1))
        hi = float(m.group(2))
        if hi >= lo:
            return ("range", lo, hi)

    # e.g., "60 or above", "above 60", "at least 60"
    m = re.search(r"(\d{1,3})\s*(?:°|degrees)?\s*(?:or\s+above|or\s+higher)", s)
    if m:
        return ("above", float(m.group(1)), None)
    m = re.search(r"(?:above|over|at\s+least|higher\s+than)\s*(\d{1,3})", s)
    if m:
        return ("above", float(m.group(1)), None)

    # e.g., "below 60", "under 60", "at most 60"
    m = re.search(r"(?:below|under|at\s+most|less\s+than)\s*(\d{1,3})", s)
    if m:
        return ("below", float(m.group(1)), None)

    return None


def temperature_probability(
    forecast_high_f: float,
    contract: tuple[str, float, Optional[float]],
    std_f: float = 3.0,
) -> float:
    """Estimate P(YES) for a temperature contract from forecast high."""
    kind, a, b = contract
    std_f = max(0.5, float(std_f))
    mean = float(forecast_high_f)

    if kind == "above":
        # Discrete threshold smoothing by 0.5F.
        p = 1.0 - _norm_cdf(a - 0.5, mean, std_f)
    elif kind == "below":
        p = _norm_cdf(a - 0.5, mean, std_f)
    else:
        hi = float(b if b is not None else a)
        p = _norm_cdf(hi + 0.5, mean, std_f) - _norm_cdf(a - 0.5, mean, std_f)

    return max(0.01, min(0.99, p))


def fetch_nws_snapshot(city_code: str, target_date: Optional[datetime] = None) -> ForecastSnapshot:
    cfg = CITY_CONFIG[city_code]
    lat = cfg["lat"]
    lon = cfg["lon"]
    points = _json_get(f"{NWS_BASE}/points/{lat},{lon}")
    forecast_url = points.get("properties", {}).get("forecast")
    if not forecast_url:
        raise RuntimeError(f"NWS forecast URL missing for {city_code}")

    forecast = _json_get(forecast_url)
    periods = forecast.get("properties", {}).get("periods", [])
    if not periods:
        raise RuntimeError(f"NWS periods empty for {city_code}")

    if target_date is None:
        target_date = datetime.now(timezone.utc) + timedelta(days=1)
    target_day = target_date.date()

    best_period = None
    for p in periods:
        start = p.get("startTime")
        if not start:
            continue
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            continue
        if start_dt.date() != target_day:
            continue
        # Prefer daytime period for daily high.
        if p.get("isDaytime"):
            best_period = p
            break
        if best_period is None:
            best_period = p

    if best_period is None:
        # Fallback to first daytime period.
        for p in periods:
            if p.get("isDaytime"):
                best_period = p
                break
        best_period = best_period or periods[0]

    temp = _safe_float(best_period.get("temperature"), None)
    if temp is not None and str(best_period.get("temperatureUnit", "F")).upper() == "C":
        temp = temp * 9.0 / 5.0 + 32.0

    pop_val = best_period.get("probabilityOfPrecipitation", {}).get("value")
    pop = _safe_float(pop_val, None)
    if pop is not None:
        pop = max(0.0, min(1.0, pop / 100.0))

    return ForecastSnapshot(
        city=city_code,
        target_date=target_day.isoformat(),
        high_temp_f=temp,
        pop_probability=pop,
        source_period=best_period.get("name", ""),
    )


def _load_kalshi_key() -> Optional[str]:
    key_path = os.environ.get("KALSHI_RSA_KEY_PATH", "").strip()
    candidates = [
        Path(key_path) if key_path else None,
        Path("bot/kalshi/kalshi_rsa_private.pem"),
        Path("kalshi/kalshi_rsa_private.pem"),
    ]
    for path in candidates:
        if path and path.exists():
            return path.read_text(encoding="utf-8")
    return None


def get_kalshi_client(*, execute: bool = False) -> KalshiClient:
    if KalshiClient is None or KalshiConfig is None:
        raise RuntimeError("kalshi_python is not installed")

    api_key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    private_key_pem = _load_kalshi_key()

    config = KalshiConfig()
    if api_key_id and private_key_pem:
        config.api_key_id = api_key_id
        config.private_key_pem = private_key_pem
    elif execute:
        missing = []
        if not api_key_id:
            missing.append("KALSHI_API_KEY_ID")
        if not private_key_pem:
            missing.append("KALSHI_RSA_KEY_PATH/private key")
        raise RuntimeError(f"Missing Kalshi auth for --execute: {', '.join(missing)}")
    else:
        logger.warning("Kalshi auth not configured; attempting read-only public market scan")
    return KalshiClient(configuration=config)


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def fetch_open_markets(client: KalshiClient, max_pages: int = 3) -> list[Any]:
    markets = []
    cursor = None
    for _ in range(max(1, max_pages)):
        kwargs: dict[str, Any] = {"status": "open", "limit": 1000}
        if cursor:
            kwargs["cursor"] = cursor
        resp = client.get_markets(**kwargs)
        page_markets = list(_field(resp, "markets", []) or [])
        markets.extend(page_markets)
        cursor = _field(resp, "cursor")
        if not cursor:
            break
    return markets


def fetch_weather_series_markets(client: KalshiClient) -> list[Any]:
    """Fetch open markets directly from known weather series tickers."""
    markets: list[Any] = []
    seen: set[str] = set()
    for city_cfg in CITY_CONFIG.values():
        for series in city_cfg.get("ticker_prefixes", []):
            try:
                resp = client.get_markets(series_ticker=series, status="open", limit=200)
                for m in list(_field(resp, "markets", []) or []):
                    ticker = str(_field(m, "ticker", "") or "")
                    if not ticker or ticker in seen:
                        continue
                    seen.add(ticker)
                    markets.append(m)
            except Exception as e:
                logger.debug("Series fetch failed for %s: %s", series, e)
    return markets


def _market_city_code(market: Any) -> Optional[str]:
    ticker = str(_field(market, "ticker", "") or "").upper()
    event_ticker = str(_field(market, "event_ticker", "") or "").upper()
    for city_code, cfg in CITY_CONFIG.items():
        prefixes = cfg.get("ticker_prefixes", [])
        if any(ticker.startswith(prefix) or event_ticker.startswith(prefix) for prefix in prefixes):
            return city_code
    return None


def _market_type(market: Any) -> Optional[str]:
    text = " ".join(
        str(_field(market, k, "") or "")
        for k in ("ticker", "title", "subtitle")
    ).lower()
    if "rain" in text or "precip" in text or "snow" in text:
        return "rain"
    if "temp" in text or "temperature" in text or "degree" in text or "high" in text:
        return "temperature"
    return None


def build_weather_signal(
    city_code: str,
    snapshot: ForecastSnapshot,
    market: Any,
    *,
    edge_threshold: float = 0.10,
    max_spread: float = 0.15,
    temp_std_f: float = 3.0,
) -> Optional[WeatherSignal]:
    mtype = _market_type(market)
    if mtype is None:
        return None

    yes_ask = _to_prob(_field(market, "yes_ask"))
    yes_bid = _to_prob(_field(market, "yes_bid"))
    no_ask = _to_prob(_field(market, "no_ask"))
    no_bid = _to_prob(_field(market, "no_bid"))
    if yes_ask is None or no_ask is None:
        return None

    title = str(_field(market, "title", "") or _field(market, "subtitle", ""))
    if not title:
        title = str(_field(market, "ticker", ""))

    if mtype == "rain":
        if snapshot.pop_probability is None:
            return None
        model_prob = snapshot.pop_probability
        reason = f"NWS PoP={model_prob:.1%} vs market"
    else:
        if snapshot.high_temp_f is None:
            return None
        contract = parse_temperature_contract(
            f"{_field(market, 'title', '')} {_field(market, 'subtitle', '')}"
        )
        if not contract:
            return None
        model_prob = temperature_probability(snapshot.high_temp_f, contract, std_f=temp_std_f)
        reason = f"NWS high={snapshot.high_temp_f:.1f}F -> model P(YES)={model_prob:.1%}"

    yes_edge = model_prob - yes_ask
    no_edge = (1.0 - model_prob) - no_ask
    if yes_edge <= 0 and no_edge <= 0:
        return None

    side = "yes" if yes_edge >= no_edge else "no"
    edge = yes_edge if side == "yes" else no_edge
    if edge < edge_threshold:
        return None

    spread = (yes_ask - (yes_bid or yes_ask)) if side == "yes" else (no_ask - (no_bid or no_ask))
    if spread > max_spread:
        return None

    order_prob = yes_ask if side == "yes" else no_ask
    confidence = max(0.0, min(1.0, edge / max(edge_threshold, 1e-6)))
    return WeatherSignal(
        timestamp=datetime.now(timezone.utc).isoformat(),
        city=city_code,
        market_ticker=str(_field(market, "ticker", "")),
        market_title=title,
        market_type=mtype,
        side=side,
        edge=float(edge),
        model_probability=float(model_prob),
        order_probability=float(order_prob),
        spread=float(spread),
        reason=reason,
        confidence=float(confidence),
    )


def _kelly_size_usd(
    side: str,
    model_probability: float,
    order_probability: float,
    bankroll_usd: float,
    kelly_fraction: float,
    max_order_usd: float,
) -> float:
    cost = max(0.01, min(0.99, order_probability))
    p_win = model_probability if side == "yes" else (1.0 - model_probability)
    p_win = max(0.01, min(0.99, p_win))
    odds = (1.0 - cost) / cost
    if odds <= 0:
        return 0.0
    kelly = max(0.0, (p_win * odds - (1.0 - p_win)) / odds)
    size = bankroll_usd * kelly_fraction * kelly
    return round(max(0.0, min(size, max_order_usd)), 2)


def place_order(
    client: KalshiClient,
    signal: WeatherSignal,
    size_usd: float,
    *,
    execute: bool = False,
) -> dict:
    order_prob = max(0.01, min(0.99, signal.order_probability))
    count = int(size_usd / order_prob)
    if count < 1:
        return {"status": "skipped", "reason": "size_too_small", "count": 0}

    price_cents = int(round(order_prob * 100))
    payload = {
        "ticker": signal.market_ticker,
        "side": signal.side,
        "action": "buy",
        "count": count,
        "type": "limit",
        "client_order_id": f"weather-{uuid.uuid4().hex[:12]}",
    }
    if signal.side == "yes":
        payload["yes_price"] = price_cents
    else:
        payload["no_price"] = price_cents

    if not execute:
        payload["status"] = "paper"
        return payload

    response = client.create_order(**payload)
    order = _field(response, "order")
    return {
        "status": "live",
        "order_id": _field(order, "order_id"),
        "client_order_id": _field(order, "client_order_id"),
        "ticker": _field(order, "ticker"),
        "side": _field(order, "side"),
        "count": _field(order, "count"),
        "yes_price": _field(order, "yes_price"),
        "no_price": _field(order, "no_price"),
    }


def scan_weather_signals(
    client: KalshiClient,
    *,
    edge_threshold: float = 0.10,
    max_spread: float = 0.15,
    temp_std_f: float = 3.0,
    max_pages: int = 3,
) -> list[WeatherSignal]:
    markets = fetch_weather_series_markets(client)
    if not markets:
        markets = fetch_open_markets(client, max_pages=max_pages)
    by_city: dict[str, list[Any]] = {city: [] for city in CITY_CONFIG}
    for market in markets:
        city = _market_city_code(market)
        if not city:
            continue
        by_city[city].append(market)

    signals: list[WeatherSignal] = []
    for city_code in CITY_CONFIG:
        if not by_city[city_code]:
            continue
        try:
            snapshot = fetch_nws_snapshot(city_code)
        except Exception as e:
            logger.warning("NWS snapshot failed for %s: %s", city_code, e)
            continue

        for market in by_city[city_code]:
            sig = build_weather_signal(
                city_code,
                snapshot,
                market,
                edge_threshold=edge_threshold,
                max_spread=max_spread,
                temp_std_f=temp_std_f,
            )
            if sig:
                signals.append(sig)

    signals.sort(key=lambda s: s.edge, reverse=True)
    return signals


def run_once(args: argparse.Namespace) -> int:
    client = get_kalshi_client(execute=args.execute)
    signals = scan_weather_signals(
        client,
        edge_threshold=args.edge_threshold,
        max_spread=args.max_spread,
        temp_std_f=args.temp_std_f,
        max_pages=args.max_pages,
    )
    if not signals:
        print("No qualifying weather signals.")
        return 0

    print(f"Found {len(signals)} weather signals")
    bankroll = float(args.bankroll_usd)
    max_order_usd = float(args.max_order_usd)
    kelly_fraction = float(args.kelly_fraction)

    orders_placed = 0
    for sig in signals[: args.max_signals]:
        size_usd = _kelly_size_usd(
            side=sig.side,
            model_probability=sig.model_probability,
            order_probability=sig.order_probability,
            bankroll_usd=bankroll,
            kelly_fraction=kelly_fraction,
            max_order_usd=max_order_usd,
        )
        if size_usd < 1.0:
            continue

        row = asdict(sig)
        row["size_usd"] = size_usd
        _append_jsonl(SIGNALS_LOG, row)

        order = place_order(client, sig, size_usd, execute=args.execute)
        order_row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execute": args.execute,
            "signal": row,
            "order": order,
        }
        _append_jsonl(ORDERS_LOG, order_row)
        orders_placed += 1

        print(
            f"[{sig.city}] {sig.market_ticker} {sig.side.upper()} "
            f"edge={sig.edge:.1%} size=${size_usd:.2f} "
            f"price={sig.order_probability:.2f} | {sig.reason}"
        )
        if orders_placed >= args.max_orders:
            break

    print(
        f"Done. Signals logged to {SIGNALS_LOG}. "
        f"Orders logged to {ORDERS_LOG}. "
        f"{'LIVE' if args.execute else 'PAPER'} orders={orders_placed}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Kalshi weather + NWS arbitrage")
    p.add_argument("--execute", action="store_true", help="Place live Kalshi orders (default is paper)")
    p.add_argument("--edge-threshold", type=float, default=float(os.environ.get("KALSHI_WEATHER_EDGE_THRESHOLD", "0.10")))
    p.add_argument("--max-spread", type=float, default=float(os.environ.get("KALSHI_WEATHER_MAX_SPREAD", "0.15")))
    p.add_argument("--temp-std-f", type=float, default=float(os.environ.get("KALSHI_WEATHER_TEMP_STD_F", "3.0")))
    p.add_argument("--bankroll-usd", type=float, default=float(os.environ.get("KALSHI_WEATHER_BANKROLL_USD", "25")))
    p.add_argument("--max-order-usd", type=float, default=float(os.environ.get("KALSHI_WEATHER_MAX_ORDER_USD", "5")))
    p.add_argument("--kelly-fraction", type=float, default=float(os.environ.get("KALSHI_WEATHER_KELLY_FRACTION", "0.25")))
    p.add_argument("--max-pages", type=int, default=int(os.environ.get("KALSHI_WEATHER_MAX_PAGES", "3")))
    p.add_argument("--max-signals", type=int, default=int(os.environ.get("KALSHI_WEATHER_MAX_SIGNALS", "20")))
    p.add_argument("--max-orders", type=int, default=int(os.environ.get("KALSHI_WEATHER_MAX_ORDERS", "5")))
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if not args.execute and not _bool_env("KALSHI_WEATHER_PAPER_TRADING", True):
        logger.warning("KALSHI_WEATHER_PAPER_TRADING is false but --execute not supplied; using paper mode")

    try:
        return run_once(args)
    except Exception as e:
        logger.error("weather_arb failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
