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
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

try:
    from kalshi_python import Configuration as KalshiConfig, KalshiClient
    from kalshi_python.api import MarketsApi, PortfolioApi
except ImportError:  # pragma: no cover - handled in runtime checks
    KalshiClient = None
    KalshiConfig = None
    MarketsApi = None
    PortfolioApi = None

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - optional convenience only
    pass


NWS_BASE = "https://api.weather.gov"
KALSHI_API_BASE = os.environ.get(
    "KALSHI_API_BASE",
    "https://api.elections.kalshi.com/trade-api/v2",
)
DATA_DIR = Path("data")
SIGNALS_LOG = DATA_DIR / "kalshi_weather_signals.jsonl"
ORDERS_LOG = DATA_DIR / "kalshi_weather_orders.jsonl"
DECISIONS_LOG = DATA_DIR / "kalshi_weather_decisions.jsonl"
MAX_FORECAST_HORIZON_DAYS = 7
DEFAULT_HOURLY_BUDGET_USD = 50.0

CITY_CONFIG = {
    "NYC": {
        "name": "New York City",
        "lat": 40.7829,
        "lon": -73.9654,
        "aliases": ["new york city", "new york", "nyc", "central park"],
        "ticker_prefixes": ["KXHIGHNY", "KXRAINNYC", "KXRAINNYCM"],
    },
    "CHI": {
        "name": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "aliases": ["chicago", "o'hare", "ohare"],
        "ticker_prefixes": ["KXHIGHCHI", "KXHIGHCH"],
    },
    "MIA": {
        "name": "Miami",
        # Miami temperature contracts settle off MIA airport climate reports.
        "lat": 25.7959,
        "lon": -80.2870,
        "aliases": ["miami", "miami international airport", "mia airport"],
        "ticker_prefixes": ["KXHIGHMIA", "KXHIGHMI"],
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
        "aliases": ["los angeles", "lax"],
        "ticker_prefixes": ["KXHIGHLAX", "KXHIGHLA"],
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


@dataclass
class KalshiSession:
    api_client: Any | None = None
    markets_api: Any | None = None
    portfolio_api: Any | None = None
    auth_configured: bool = False


@dataclass
class HourlyUsage:
    order_count: int = 0
    notional_usd: float = 0.0


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes")


def _json_get(url: str, *, params: Optional[dict[str, Any]] = None, timeout: float = 12.0) -> dict:
    resp = requests.get(
        url,
        params=params,
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


def _parse_timestamp(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _current_hourly_usage(
    *,
    now: Optional[datetime] = None,
    lookback: timedelta = timedelta(hours=1),
    orders_log: Path = ORDERS_LOG,
) -> HourlyUsage:
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - lookback
    usage = HourlyUsage()
    if not orders_log.exists():
        return usage

    with orders_log.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_timestamp(str(row.get("timestamp", "")).strip())
            if ts is None or ts < cutoff:
                continue

            execution_result = str(row.get("execution_result", "")).strip().lower()
            if execution_result not in {"paper", "live"}:
                continue

            usage.order_count += 1
            usage.notional_usd += max(0.0, _safe_float(row.get("notional_usd"), 0.0) or 0.0)
    usage.notional_usd = round(usage.notional_usd, 2)
    return usage


def _resolve_hourly_budget_usd(
    explicit_budget: Optional[float],
    *,
    env: Optional[dict[str, str]] = None,
) -> float:
    if explicit_budget is not None:
        return float(explicit_budget)
    env_source = env or os.environ
    for key in (
        "KALSHI_WEATHER_HOURLY_BUDGET_USD",
        "JJ_HOURLY_NOTIONAL_BUDGET_USD",
        "JJ_HOURLY_BUDGET_USD",
    ):
        raw = str(env_source.get(key, "")).strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return DEFAULT_HOURLY_BUDGET_USD


def _normalize_mode(args: argparse.Namespace) -> None:
    mode = str(getattr(args, "mode", "paper") or "paper").strip().lower()
    if mode not in {"paper", "live"}:
        raise ValueError(f"unsupported mode {mode!r}; expected 'paper' or 'live'")
    execute_flag = bool(getattr(args, "execute", False))
    if mode == "paper" and execute_flag:
        raise ValueError("conflicting mode flags: --mode paper cannot be combined with --execute")
    args.mode = mode
    args.execute = mode == "live" or execute_flag


def _validate_args(args: argparse.Namespace) -> None:
    if not (0.0 <= float(args.edge_threshold) <= 1.0):
        raise ValueError("--edge-threshold must be in [0.0, 1.0]")
    if not (0.0 <= float(args.max_spread) <= 1.0):
        raise ValueError("--max-spread must be in [0.0, 1.0]")
    if float(args.temp_std_f) <= 0.0:
        raise ValueError("--temp-std-f must be > 0")
    if int(args.maker_offset_cents) < 0:
        raise ValueError("--maker-offset-cents must be >= 0")
    if float(args.bankroll_usd) <= 0.0:
        raise ValueError("--bankroll-usd must be > 0")
    if float(args.max_order_usd) <= 0.0:
        raise ValueError("--max-order-usd must be > 0")
    if not (0.0 < float(args.kelly_fraction) <= 1.0):
        raise ValueError("--kelly-fraction must be in (0.0, 1.0]")
    if int(args.max_pages) < 1:
        raise ValueError("--max-pages must be >= 1")
    if int(args.max_signals) < 1:
        raise ValueError("--max-signals must be >= 1")
    if int(args.max_orders) < 0:
        raise ValueError("--max-orders must be >= 0")
    if int(args.max_orders_per_hour) < 0:
        raise ValueError("--max-orders-per-hour must be >= 0")
    if float(args.hourly_budget_usd) <= 0.0:
        raise ValueError("--hourly-budget-usd must be > 0")
    if int(args.interval_seconds) < 1:
        raise ValueError("--interval-seconds must be >= 1")


def _record_decision(
    *,
    signal: WeatherSignal,
    size_usd: float,
    execution_result: str,
    reason_code: str,
    execute: bool,
) -> None:
    _append_jsonl(
        DECISIONS_LOG,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "venue": "kalshi",
            "source": signal.source,
            "market_ticker": signal.market_ticker,
            "market_title": signal.market_title,
            "city": signal.city,
            "side": signal.side,
            "edge": signal.edge,
            "reason": signal.reason,
            "confidence": signal.confidence,
            "spread": signal.spread,
            "order_probability": signal.order_probability,
            "notional_usd": round(max(0.0, float(size_usd)), 2),
            "execution_mode": "live" if execute else "paper",
            "execution_result": execution_result,
            "reason_code": reason_code,
        },
    )


def _norm_cdf(x: float, mean: float, std: float) -> float:
    z = (x - mean) / (std * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def parse_temperature_contract(text: str) -> Optional[tuple[str, float, Optional[float]]]:
    """Parse basic temp contract shapes from market title/subtitle."""
    s = text.lower()

    # e.g., "60-64" or "between 60 and 64"
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


def _is_tight_temp_range_contract(contract: tuple[str, float, Optional[float]]) -> bool:
    kind, lo, hi = contract
    if kind != "range" or hi is None:
        return False
    return (hi - lo) <= 2.0


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

    target_periods = []
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
        target_periods.append(p)
        # Prefer daytime period for daily high.
        if p.get("isDaytime"):
            best_period = p
        elif best_period is None:
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

    pop_probs: list[float] = []
    for period in target_periods or [best_period]:
        pop_val = period.get("probabilityOfPrecipitation", {}).get("value")
        pop = _safe_float(pop_val, None)
        if pop is None:
            continue
        pop_probs.append(max(0.0, min(1.0, pop / 100.0)))

    daily_pop = None
    if pop_probs:
        no_precip_prob = 1.0
        for pop in pop_probs:
            no_precip_prob *= 1.0 - pop
        daily_pop = max(0.0, min(1.0, 1.0 - no_precip_prob))

    return ForecastSnapshot(
        city=city_code,
        target_date=target_day.isoformat(),
        high_temp_f=temp,
        pop_probability=daily_pop,
        source_period=best_period.get("name", ""),
    )


def _load_kalshi_key_path() -> Optional[Path]:
    key_path = os.environ.get("KALSHI_RSA_KEY_PATH", "").strip()
    candidates = [
        Path(key_path) if key_path else None,
        Path("bot/kalshi/kalshi_rsa_private.pem"),
        Path("kalshi/kalshi_rsa_private.pem"),
    ]
    for path in candidates:
        if path and path.exists():
            return path
    return None


def get_kalshi_client(*, execute: bool = False) -> KalshiSession:
    if KalshiClient is None or KalshiConfig is None or MarketsApi is None or PortfolioApi is None:
        if execute:
            raise RuntimeError("kalshi_python is required for live Kalshi orders")
        logger.warning("kalshi_python is not installed; using public HTTP market scan only")
        return KalshiSession()

    api_key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    private_key_path = _load_kalshi_key_path()

    config = KalshiConfig()
    api_client = KalshiClient(configuration=config)
    auth_configured = bool(api_key_id and private_key_path)
    if auth_configured:
        api_client.set_kalshi_auth(api_key_id, str(private_key_path))
    elif execute:
        missing = []
        if not api_key_id:
            missing.append("KALSHI_API_KEY_ID")
        if not private_key_path:
            missing.append("KALSHI_RSA_KEY_PATH/private key")
        raise RuntimeError(f"Missing Kalshi auth for --execute: {', '.join(missing)}")
    if not auth_configured:
        logger.warning("Kalshi auth not configured; attempting read-only public market scan")
    return KalshiSession(
        api_client=api_client,
        markets_api=MarketsApi(api_client),
        portfolio_api=PortfolioApi(api_client),
        auth_configured=auth_configured,
    )


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name, default)
    return default


def _public_get_markets(**params: Any) -> list[dict[str, Any]]:
    resp = _json_get(f"{KALSHI_API_BASE}/markets", params=params, timeout=20.0)
    return list(resp.get("markets", []) or [])


def fetch_open_markets(session: KalshiSession, max_pages: int = 3) -> list[Any]:
    markets = []
    cursor = None
    for _ in range(max(1, max_pages)):
        kwargs: dict[str, Any] = {"status": "open", "limit": 1000}
        if cursor:
            kwargs["cursor"] = cursor
        if session.markets_api is not None:
            resp = session.markets_api.get_markets(**kwargs)
            page_markets = list(_field(resp, "markets", []) or [])
            cursor = _field(resp, "cursor")
        else:
            resp = _json_get(f"{KALSHI_API_BASE}/markets", params=kwargs, timeout=20.0)
            page_markets = list(resp.get("markets", []) or [])
            cursor = resp.get("cursor")
        markets.extend(page_markets)
        if not cursor:
            break
    return markets


def fetch_weather_series_markets(session: KalshiSession) -> list[Any]:
    """Fetch open markets directly from known weather series tickers."""
    markets: list[Any] = []
    seen: set[str] = set()
    for city_cfg in CITY_CONFIG.values():
        for series in city_cfg.get("ticker_prefixes", []):
            try:
                if session.markets_api is not None:
                    resp = session.markets_api.get_markets(
                        series_ticker=series,
                        status="open",
                        limit=200,
                    )
                    page_markets = list(_field(resp, "markets", []) or [])
                else:
                    page_markets = _public_get_markets(series_ticker=series, status="open", limit=200)
                for m in page_markets:
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
    text = " ".join(
        str(_field(market, key, "") or "")
        for key in ("ticker", "event_ticker", "title", "subtitle")
    ).lower()
    for city_code, cfg in CITY_CONFIG.items():
        prefixes = cfg.get("ticker_prefixes", [])
        if any(ticker.startswith(prefix) or event_ticker.startswith(prefix) for prefix in prefixes):
            return city_code
        if any(alias in text for alias in cfg.get("aliases", [])):
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


def extract_market_target_date(market: Any) -> Optional[date]:
    for raw in (
        str(_field(market, "event_ticker", "") or ""),
        str(_field(market, "ticker", "") or ""),
    ):
        match = re.search(r"-(\d{2})([A-Z]{3})(\d{2})(?:-|$)", raw.upper())
        if not match:
            continue
        yy, month_abbr, dd = match.groups()
        try:
            return datetime.strptime(f"{yy}{month_abbr}{dd}", "%y%b%d").date()
        except ValueError:
            continue

    title = " ".join(
        str(_field(market, key, "") or "")
        for key in ("title", "subtitle")
    ).replace("*", "")
    match = re.search(r"on\s+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", title)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%b %d, %Y").date()
    except ValueError:
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").date()
        except ValueError:
            return None


def _maker_order_probability(
    best_bid: Optional[float],
    best_ask: Optional[float],
    *,
    passive_offset_cents: int = 1,
) -> Optional[float]:
    ask = _safe_float(best_ask, None)
    if ask is None:
        return None

    ask_cents = int(round(max(0.0, min(0.99, ask)) * 100))
    if ask_cents <= 1:
        return None

    offset = max(0, int(passive_offset_cents))
    bid = _safe_float(best_bid, None)
    if bid is None:
        price_cents = ask_cents - max(1, offset)
    else:
        bid_cents = int(round(max(0.0, min(0.99, bid)) * 100))
        price_cents = bid_cents + offset
        if price_cents >= ask_cents:
            price_cents = ask_cents - 1

    if price_cents < 1:
        return None
    return price_cents / 100.0


def build_weather_signal(
    city_code: str,
    snapshot: ForecastSnapshot,
    market: Any,
    *,
    edge_threshold: float = 0.10,
    max_spread: float = 0.15,
    temp_std_f: float = 3.0,
    maker_offset_cents: int = 1,
) -> Optional[WeatherSignal]:
    mtype = _market_type(market)
    if mtype is None:
        return None

    market_target_date = extract_market_target_date(market)
    if market_target_date is not None and market_target_date.isoformat() != snapshot.target_date:
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

    contract: Optional[tuple[str, float, Optional[float]]] = None
    if mtype == "rain":
        if snapshot.pop_probability is None:
            return None
        model_prob = snapshot.pop_probability
        reason = f"NWS daily PoP={model_prob:.1%} vs market"
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

    yes_order_prob = _maker_order_probability(
        yes_bid,
        yes_ask,
        passive_offset_cents=maker_offset_cents,
    )
    no_order_prob = _maker_order_probability(
        no_bid,
        no_ask,
        passive_offset_cents=maker_offset_cents,
    )

    yes_edge = model_prob - yes_order_prob if yes_order_prob is not None else float("-inf")
    no_edge = (1.0 - model_prob) - no_order_prob if no_order_prob is not None else float("-inf")
    if yes_edge <= 0 and no_edge <= 0:
        return None

    side = "yes" if yes_edge >= no_edge else "no"
    edge = yes_edge if side == "yes" else no_edge

    # Avoid generic fades of modal 2-degree center buckets when the point forecast
    # still sits inside the bracket; require a directional thesis first.
    if (
        mtype == "temperature"
        and contract is not None
        and side == "no"
        and _is_tight_temp_range_contract(contract)
    ):
        _, lo, hi = contract
        if hi is not None and lo <= snapshot.high_temp_f <= hi:
            return None

    if edge < edge_threshold:
        return None

    yes_spread = yes_ask - (yes_bid if yes_bid is not None else max(0.0, yes_ask - 0.01))
    no_spread = no_ask - (no_bid if no_bid is not None else max(0.0, no_ask - 0.01))
    spread = yes_spread if side == "yes" else no_spread
    if spread > max_spread:
        return None

    order_prob = yes_order_prob if side == "yes" else no_order_prob
    if order_prob is None:
        return None
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
    session: KalshiSession,
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

    if session.portfolio_api is None:
        raise RuntimeError("kalshi_python is required for live Kalshi orders")

    response = session.portfolio_api.create_order(**payload)
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
    session: KalshiSession,
    *,
    edge_threshold: float = 0.10,
    max_spread: float = 0.15,
    temp_std_f: float = 3.0,
    maker_offset_cents: int = 1,
    max_pages: int = 3,
) -> list[WeatherSignal]:
    markets = fetch_weather_series_markets(session)
    if not markets:
        markets = fetch_open_markets(session, max_pages=max_pages)
    by_city_and_date: dict[tuple[str, date], list[Any]] = {}
    today_utc = datetime.now(timezone.utc).date()
    for market in markets:
        if _market_type(market) is None:
            continue
        city = _market_city_code(market)
        if not city:
            continue
        target_day = extract_market_target_date(market)
        if target_day is None:
            continue
        horizon_days = (target_day - today_utc).days
        if horizon_days < 0 or horizon_days > MAX_FORECAST_HORIZON_DAYS:
            continue
        by_city_and_date.setdefault((city, target_day), []).append(market)

    signals: list[WeatherSignal] = []
    for (city_code, target_day), city_markets in sorted(by_city_and_date.items()):
        try:
            snapshot = fetch_nws_snapshot(
                city_code,
                datetime(
                    target_day.year,
                    target_day.month,
                    target_day.day,
                    12,
                    tzinfo=timezone.utc,
                ),
            )
        except Exception as e:
            logger.warning(
                "NWS snapshot failed for %s %s: %s",
                city_code,
                target_day.isoformat(),
                e,
            )
            continue

        for market in city_markets:
            sig = build_weather_signal(
                city_code,
                snapshot,
                market,
                edge_threshold=edge_threshold,
                max_spread=max_spread,
                temp_std_f=temp_std_f,
                maker_offset_cents=maker_offset_cents,
            )
            if sig:
                signals.append(sig)

    signals.sort(key=lambda s: s.edge, reverse=True)
    return signals


def run_once(args: argparse.Namespace) -> int:
    session = get_kalshi_client(execute=args.execute)
    signals = scan_weather_signals(
        session,
        edge_threshold=args.edge_threshold,
        max_spread=args.max_spread,
        temp_std_f=args.temp_std_f,
        maker_offset_cents=args.maker_offset_cents,
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
    hourly_usage = _current_hourly_usage()
    hour_orders_placed = hourly_usage.order_count
    hour_notional = hourly_usage.notional_usd
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
            _record_decision(
                signal=sig,
                size_usd=size_usd,
                execution_result="rejected",
                reason_code="size_too_small",
                execute=args.execute,
            )
            continue
        remaining_hourly_budget = max(0.0, float(args.hourly_budget_usd) - hour_notional)
        if hour_orders_placed >= int(args.max_orders_per_hour):
            _record_decision(
                signal=sig,
                size_usd=0.0,
                execution_result="rejected",
                reason_code="hourly_order_limit_reached",
                execute=args.execute,
            )
            break
        if remaining_hourly_budget < 1.0:
            _record_decision(
                signal=sig,
                size_usd=0.0,
                execution_result="rejected",
                reason_code="hourly_budget_exhausted",
                execute=args.execute,
            )
            break
        size_usd = min(size_usd, remaining_hourly_budget, float(args.max_order_usd))
        size_usd = round(size_usd, 2)
        if size_usd < 1.0:
            _record_decision(
                signal=sig,
                size_usd=size_usd,
                execution_result="rejected",
                reason_code="remaining_budget_too_small",
                execute=args.execute,
            )
            continue

        row = asdict(sig)
        row["size_usd"] = size_usd
        row["venue"] = "kalshi"
        row["execution_mode"] = "live" if args.execute else "paper"
        _append_jsonl(SIGNALS_LOG, row)

        order = place_order(session, sig, size_usd, execute=args.execute)
        execution_result = str(order.get("status", "unknown"))
        order_row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "venue": "kalshi",
            "source": sig.source,
            "market_ticker": sig.market_ticker,
            "side": sig.side,
            "edge": sig.edge,
            "reason": sig.reason,
            "execution_mode": "live" if args.execute else "paper",
            "execution_result": execution_result,
            "reason_code": "order_submitted" if execution_result in {"paper", "live"} else str(order.get("reason", "unknown")),
            "notional_usd": size_usd,
            "execute": args.execute,
            "signal": row,
            "order": order,
        }
        _append_jsonl(ORDERS_LOG, order_row)
        _record_decision(
            signal=sig,
            size_usd=size_usd,
            execution_result=execution_result,
            reason_code=order_row["reason_code"],
            execute=args.execute,
        )
        orders_placed += 1
        if execution_result in {"paper", "live"}:
            hour_orders_placed += 1
            hour_notional = round(hour_notional + size_usd, 2)

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
        f"Decisions logged to {DECISIONS_LOG}. "
        f"{'LIVE' if args.execute else 'PAPER'} orders={orders_placed}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Kalshi weather + NWS arbitrage")
    p.add_argument("--mode", choices=("paper", "live"), default=os.environ.get("KALSHI_WEATHER_MODE", "paper"), help="Explicit run mode")
    p.add_argument("--execute", action="store_true", help="Legacy alias for --mode live")
    p.add_argument("--edge-threshold", type=float, default=float(os.environ.get("KALSHI_WEATHER_EDGE_THRESHOLD", "0.10")))
    p.add_argument("--max-spread", type=float, default=float(os.environ.get("KALSHI_WEATHER_MAX_SPREAD", "0.15")))
    p.add_argument("--temp-std-f", type=float, default=float(os.environ.get("KALSHI_WEATHER_TEMP_STD_F", "3.0")))
    p.add_argument("--maker-offset-cents", type=int, default=int(os.environ.get("KALSHI_WEATHER_MAKER_OFFSET_CENTS", "1")))
    p.add_argument("--bankroll-usd", type=float, default=float(os.environ.get("KALSHI_WEATHER_BANKROLL_USD", "25")))
    p.add_argument("--max-order-usd", type=float, default=float(os.environ.get("KALSHI_WEATHER_MAX_ORDER_USD", "5")))
    p.add_argument("--kelly-fraction", type=float, default=float(os.environ.get("KALSHI_WEATHER_KELLY_FRACTION", "0.25")))
    p.add_argument(
        "--hourly-budget-usd",
        type=float,
        default=_resolve_hourly_budget_usd(None),
        help="Rolling 60-minute notional budget cap",
    )
    p.add_argument("--max-pages", type=int, default=int(os.environ.get("KALSHI_WEATHER_MAX_PAGES", "3")))
    p.add_argument("--max-signals", type=int, default=int(os.environ.get("KALSHI_WEATHER_MAX_SIGNALS", "20")))
    p.add_argument("--max-orders", type=int, default=int(os.environ.get("KALSHI_WEATHER_MAX_ORDERS", "5")))
    p.add_argument(
        "--max-orders-per-hour",
        type=int,
        default=int(os.environ.get("KALSHI_WEATHER_MAX_ORDERS_PER_HOUR", os.environ.get("KALSHI_WEATHER_MAX_ORDERS", "5"))),
        help="Rolling 60-minute order count cap",
    )
    p.add_argument("--loop", action="store_true", help="Run continuously")
    p.add_argument("--interval-seconds", type=int, default=int(os.environ.get("KALSHI_WEATHER_LOOP_INTERVAL_SECONDS", "300")))
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        _normalize_mode(args)
        args.hourly_budget_usd = _resolve_hourly_budget_usd(float(args.hourly_budget_usd))
        _validate_args(args)
    except ValueError as exc:
        logger.error("Invalid config: %s", exc)
        return 2

    if not args.execute and not _bool_env("KALSHI_WEATHER_PAPER_TRADING", True):
        logger.warning("KALSHI_WEATHER_PAPER_TRADING is false but --execute not supplied; using paper mode")

    try:
        if not args.loop:
            return run_once(args)

        logger.info(
            "Starting continuous Kalshi weather lane mode=%s interval=%ss hourly_budget=$%.2f max_orders_hour=%d",
            args.mode,
            args.interval_seconds,
            float(args.hourly_budget_usd),
            int(args.max_orders_per_hour),
        )
        while True:
            cycle_started = datetime.now(timezone.utc)
            exit_code = run_once(args)
            if exit_code != 0:
                return exit_code
            elapsed = (datetime.now(timezone.utc) - cycle_started).total_seconds()
            sleep_for = max(0.0, float(args.interval_seconds) - elapsed)
            logger.info("Cycle complete in %.2fs; sleeping %.2fs", elapsed, sleep_for)
            time.sleep(sleep_for)
    except Exception as e:
        logger.error("weather_arb failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
