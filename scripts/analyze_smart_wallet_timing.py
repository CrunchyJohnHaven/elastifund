#!/usr/bin/env python3
"""
Analyze smart-wallet BTC5 entry timing and produce an actionable verdict.

Primary output:
  reports/smart_wallet_timing_analysis.json

The script prefers local artifacts when available:
  1) data/wallet_scores.db / wallet_analysis.json / data/smart_wallets*.json
  2) data/btc_5min_maker.db filled windows

If local artifacts are missing, it falls back to public Polymarket APIs.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
BTC5_SLUG_PREFIX = "btc-updown-5m-"
BUCKETS: tuple[tuple[int, int], ...] = (
    (0, 60),
    (60, 120),
    (120, 180),
    (180, 240),
    (240, 300),
)

LOG = logging.getLogger("smart_wallet_timing_analysis")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@dataclass
class SmartWallet:
    address: str
    rank: int
    pnl_usd: float
    volume_usd: float
    source: str


@dataclass
class MarketWindow:
    condition_id: str
    slug: str
    window_start_ts: int
    winner_index: int | None
    outcomes: list[str]
    outcome_prices: list[float]
    source: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_wallet(value: Any) -> str:
    if not value:
        return ""
    wallet = str(value).strip().lower()
    if wallet.startswith("0x") and len(wallet) == 42:
        return wallet
    return ""


def parse_json_maybe(value: Any, default: Any) -> Any:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except json.JSONDecodeError:
            return default
    return default


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
    retries: int = 4,
    sleep_base: float = 0.75,
) -> Any:
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            if response.status_code == 429:
                wait = sleep_base * (2 ** attempt)
                LOG.warning("429 from %s params=%s; waiting %.1fs", url, params, wait)
                time.sleep(wait)
                continue
            if 400 <= response.status_code < 500:
                # Non-429 client errors are generally deterministic and should not be retried.
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Request failed url={url} params={params}: {exc}") from exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and 400 <= int(status) < 500 and int(status) != 429:
                raise RuntimeError(f"Request failed url={url} params={params}: {exc}") from exc
            wait = sleep_base * (2 ** attempt)
            LOG.warning("Request error %s; retrying in %.1fs", exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Exhausted retries url={url} params={params}")


def bucket_name(offset_seconds: int) -> str:
    for lo, hi in BUCKETS:
        if lo <= offset_seconds < hi:
            return f"{lo}-{hi}s"
    return "out_of_window"


def parse_window_start_from_slug(slug: str) -> int | None:
    slug = str(slug or "")
    if not slug.startswith(BTC5_SLUG_PREFIX):
        return None
    suffix = slug[len(BTC5_SLUG_PREFIX) :]
    if suffix.isdigit():
        return int(suffix)
    return None


def parse_winner_index(outcome_prices: list[float]) -> int | None:
    if len(outcome_prices) < 2:
        return None
    yes = parse_float(outcome_prices[0], default=-1.0)
    no = parse_float(outcome_prices[1], default=-1.0)
    if yes >= 0.99 and no <= 0.01:
        return 0
    if no >= 0.99 and yes <= 0.01:
        return 1
    return None


def effective_outcome_index(side: str, outcome_index: int) -> int:
    return outcome_index if str(side).upper() == "BUY" else 1 - outcome_index


def notional_usd(trade: dict[str, Any]) -> float:
    usdc = parse_float(trade.get("usdcSize"), default=0.0)
    if usdc > 0:
        return usdc
    price = parse_float(trade.get("price"), default=0.0)
    size = parse_float(trade.get("size"), default=0.0)
    return max(0.0, price * size)


def wilson_lower_bound(successes: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = successes / total
    denom = 1.0 + (z * z) / total
    centre = phat + (z * z) / (2 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4 * total)) / total)
    return max(0.0, (centre - margin) / denom)


def load_wallets_from_scores_db(db_path: Path, top_n: int) -> list[SmartWallet]:
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT wallet, total_pnl, total_volume
                FROM wallet_scores
                ORDER BY total_pnl DESC, total_volume DESC
                LIMIT ?
                """,
                (int(top_n),),
            ).fetchall()
    except sqlite3.Error as exc:
        LOG.warning("wallet_scores query failed: %s", exc)
        return []
    wallets: list[SmartWallet] = []
    for idx, row in enumerate(rows, start=1):
        address = normalize_wallet(row["wallet"])
        if not address:
            continue
        wallets.append(
            SmartWallet(
                address=address,
                rank=idx,
                pnl_usd=round(parse_float(row["total_pnl"]), 6),
                volume_usd=round(parse_float(row["total_volume"]), 6),
                source=f"db:{db_path}",
            )
        )
    return wallets


def _coerce_wallet_items(items: list[dict[str, Any]], source: str) -> list[SmartWallet]:
    wallets: list[SmartWallet] = []
    for row in items:
        address = normalize_wallet(
            row.get("address")
            or row.get("wallet")
            or row.get("proxyWallet")
            or row.get("walletAddress")
        )
        if not address:
            continue
        rank = parse_int(row.get("rank"), default=0)
        pnl = parse_float(
            row.get("pnl_usd", row.get("total_pnl", row.get("pnl", row.get("realized_pnl", 0.0)))),
            default=0.0,
        )
        volume = parse_float(
            row.get("volume_usd", row.get("total_volume", row.get("volume", 0.0))),
            default=0.0,
        )
        wallets.append(
            SmartWallet(
                address=address,
                rank=rank,
                pnl_usd=round(pnl, 6),
                volume_usd=round(volume, 6),
                source=source,
            )
        )
    return wallets


def load_wallets_from_json(json_path: Path, top_n: int) -> list[SmartWallet]:
    if not json_path.exists():
        return []
    try:
        payload = json.loads(json_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("Unable to read %s: %s", json_path, exc)
        return []

    rows: list[dict[str, Any]] = []
    if isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        if isinstance(payload.get("ranked_wallets"), list):
            rows = [x for x in payload["ranked_wallets"] if isinstance(x, dict)]
        elif isinstance(payload.get("wallets"), dict):
            rows = [
                {"address": address, **(data if isinstance(data, dict) else {})}
                for address, data in payload["wallets"].items()
            ]
        elif isinstance(payload.get("wallets"), list):
            rows = [x for x in payload["wallets"] if isinstance(x, dict)]
    wallets = _coerce_wallet_items(rows, source=f"json:{json_path}")
    wallets.sort(key=lambda w: (-w.pnl_usd, -w.volume_usd, w.address))
    out: list[SmartWallet] = []
    for idx, wallet in enumerate(wallets[:top_n], start=1):
        out.append(
            SmartWallet(
                address=wallet.address,
                rank=idx,
                pnl_usd=wallet.pnl_usd,
                volume_usd=wallet.volume_usd,
                source=wallet.source,
            )
        )
    return out


def load_wallets_from_leaderboard(top_n: int) -> list[SmartWallet]:
    payload = request_json(
        f"{DATA_API}/v1/leaderboard",
        params={
            "category": "CRYPTO",
            "timePeriod": "ALL",
            "orderBy": "PNL",
            "limit": max(50, top_n),
        },
    )
    if not isinstance(payload, list):
        return []
    wallets: list[SmartWallet] = []
    for idx, row in enumerate(payload, start=1):
        address = normalize_wallet(row.get("proxyWallet") or row.get("walletAddress") or row.get("wallet"))
        if not address:
            continue
        wallets.append(
            SmartWallet(
                address=address,
                rank=idx,
                pnl_usd=round(parse_float(row.get("pnl"), default=0.0), 6),
                volume_usd=round(parse_float(row.get("volume"), default=0.0), 6),
                source="api:data-api-v1-leaderboard-pnl-all",
            )
        )
        if len(wallets) >= top_n:
            break
    return wallets


def load_top_smart_wallets(top_n: int, wallet_scores_db: Path, wallet_json_paths: list[Path]) -> tuple[list[SmartWallet], dict[str, Any]]:
    db_wallets = load_wallets_from_scores_db(wallet_scores_db, top_n=top_n)
    if len(db_wallets) >= top_n:
        return db_wallets[:top_n], {
            "primary_source": f"db:{wallet_scores_db}",
            "source_fallback_used": False,
            "db_rows": len(db_wallets),
        }

    merged: dict[str, SmartWallet] = {w.address: w for w in db_wallets}
    file_counts: dict[str, int] = {}
    for path in wallet_json_paths:
        rows = load_wallets_from_json(path, top_n=max(100, top_n))
        file_counts[str(path)] = len(rows)
        for wallet in rows:
            existing = merged.get(wallet.address)
            if existing is None or (wallet.pnl_usd, wallet.volume_usd) > (
                existing.pnl_usd,
                existing.volume_usd,
            ):
                merged[wallet.address] = wallet

    if len(merged) < top_n:
        api_wallets = load_wallets_from_leaderboard(top_n=max(60, top_n))
        for wallet in api_wallets:
            existing = merged.get(wallet.address)
            if existing is None or (wallet.pnl_usd, wallet.volume_usd) > (
                existing.pnl_usd,
                existing.volume_usd,
            ):
                merged[wallet.address] = wallet

    ranked = sorted(
        merged.values(),
        key=lambda w: (-w.pnl_usd, -w.volume_usd, w.address),
    )[:top_n]
    normalized: list[SmartWallet] = []
    for idx, wallet in enumerate(ranked, start=1):
        normalized.append(
            SmartWallet(
                address=wallet.address,
                rank=idx,
                pnl_usd=wallet.pnl_usd,
                volume_usd=wallet.volume_usd,
                source=wallet.source,
            )
        )
    return normalized, {
        "primary_source": normalized[0].source if normalized else "none",
        "source_fallback_used": True,
        "db_rows": len(db_wallets),
        "json_rows": file_counts,
        "selected_count": len(normalized),
    }


def load_btc5_filled_windows(db_path: Path, limit: int) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    window_start_ts,
                    slug,
                    order_price,
                    direction,
                    won,
                    pnl_usd,
                    order_status,
                    filled
                FROM window_trades
                WHERE COALESCE(filled, 0) = 1
                   OR LOWER(COALESCE(order_status, '')) = 'live_filled'
                ORDER BY window_start_ts DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
    except sqlite3.Error as exc:
        LOG.warning("Failed reading %s: %s", db_path, exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({key: row[key] for key in row.keys()})
    return out


def fetch_btc5_markets_page(offset: int, limit: int = 500) -> list[dict[str, Any]]:
    payload = request_json(
        f"{GAMMA_API}/markets",
        params={"limit": limit, "offset": offset, "order": "createdAt", "ascending": "false"},
    )
    return payload if isinstance(payload, list) else []


def row_to_market_window(row: dict[str, Any], source: str) -> MarketWindow | None:
    slug = str(row.get("slug") or "")
    if not slug.startswith(BTC5_SLUG_PREFIX):
        return None
    window_start = parse_window_start_from_slug(slug)
    if window_start is None:
        return None
    condition_id = str(row.get("conditionId") or row.get("condition_id") or "").strip()
    if not condition_id:
        return None
    outcomes = parse_json_maybe(row.get("outcomes"), [])
    outcomes = [str(x) for x in outcomes] if isinstance(outcomes, list) else []
    prices_raw = parse_json_maybe(row.get("outcomePrices"), [])
    outcome_prices = [parse_float(x, default=-1.0) for x in prices_raw] if isinstance(prices_raw, list) else []
    winner_idx = parse_winner_index(outcome_prices)
    return MarketWindow(
        condition_id=condition_id,
        slug=slug,
        window_start_ts=window_start,
        winner_index=winner_idx,
        outcomes=outcomes if outcomes else ["Outcome0", "Outcome1"],
        outcome_prices=outcome_prices,
        source=source,
    )


def map_slugs_to_markets(slugs: set[str], max_pages: int = 120, page_size: int = 500) -> dict[str, MarketWindow]:
    if not slugs:
        return {}
    unresolved = set(slugs)
    mapping: dict[str, MarketWindow] = {}
    for page in range(max_pages):
        offset = page * page_size
        rows = fetch_btc5_markets_page(offset=offset, limit=page_size)
        if not rows:
            break
        for row in rows:
            slug = str(row.get("slug") or "")
            if slug not in unresolved:
                continue
            market = row_to_market_window(row, source="gamma:slug_map")
            if market is None:
                continue
            mapping[slug] = market
            unresolved.discard(slug)
        if not unresolved:
            break
        if len(rows) < page_size:
            break
    if unresolved:
        LOG.warning("Unable to map %d slugs to condition IDs", len(unresolved))
    return mapping


def fetch_resolved_btc5_markets(max_markets: int, max_pages: int = 260, page_size: int = 500) -> list[MarketWindow]:
    markets: list[MarketWindow] = []
    for page in range(max_pages):
        offset = page * page_size
        rows = fetch_btc5_markets_page(offset=offset, limit=page_size)
        if not rows:
            break
        for row in rows:
            market = row_to_market_window(row, source="gamma:resolved_scan")
            if market is None:
                continue
            if market.winner_index is None:
                continue
            markets.append(market)
            if len(markets) >= max_markets:
                return markets
        if len(rows) < page_size:
            break
    return markets


def choose_target_markets(
    *,
    btc5_db_path: Path,
    target_market_count: int,
    prefer_db_fill_windows: bool,
) -> tuple[list[MarketWindow], dict[str, Any]]:
    if prefer_db_fill_windows:
        fills = load_btc5_filled_windows(btc5_db_path, limit=max(100, target_market_count * 3))
    else:
        fills = []

    high_price_fills = [r for r in fills if parse_float(r.get("order_price"), default=0.0) >= 0.90]
    prioritized = high_price_fills if high_price_fills else fills
    prioritized = prioritized[:target_market_count]
    slugs = {
        str(row.get("slug") or "")
        for row in prioritized
        if str(row.get("slug") or "").startswith(BTC5_SLUG_PREFIX)
    }

    if slugs:
        mapping = map_slugs_to_markets(slugs)
        selected = [mapping[s] for s in sorted(slugs) if s in mapping]
        if selected:
            return selected, {
                "source": f"db:{btc5_db_path}",
                "filled_windows_found": len(fills),
                "high_price_filled_windows_found": len(high_price_fills),
                "selected_windows": len(selected),
            }

    fallback = fetch_resolved_btc5_markets(max_markets=target_market_count)
    return fallback, {
        "source": "gamma_api_fallback_resolved_markets",
        "filled_windows_found": len(fills),
        "high_price_filled_windows_found": len(high_price_fills),
        "selected_windows": len(fallback),
    }


def fetch_market_trades(
    condition_id: str,
    *,
    max_rows: int = 0,
    page_size: int = 200,
    max_pages_safety: int = 500,
) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    page = 0
    while True:
        if max_rows > 0 and len(all_rows) >= max_rows:
            break
        if page >= max_pages_safety:
            LOG.warning(
                "Stopping trade pagination for %s at safety page cap=%d",
                condition_id,
                max_pages_safety,
            )
            break
        offset = page * page_size
        try:
            payload = request_json(
                f"{DATA_API}/trades",
                params={"market": condition_id, "limit": page_size, "offset": offset, "takerOnly": "false"},
            )
        except RuntimeError as exc:
            message = str(exc)
            if "400 Client Error" in message and offset > 0:
                # Current Data API surface rejects deep offsets (typically beyond ~3000).
                LOG.info(
                    "Stopping pagination for %s at offset=%d due to API offset cap",
                    condition_id,
                    offset,
                )
                break
            raise
        if not isinstance(payload, list) or not payload:
            break
        if max_rows > 0 and len(all_rows) + len(payload) > max_rows:
            take = max(0, max_rows - len(all_rows))
            all_rows.extend(payload[:take])
            break
        all_rows.extend(payload)
        if len(payload) < page_size:
            break
        page += 1
    return all_rows


def maybe_trade_pnl_usd(trade: dict[str, Any], won: bool) -> float:
    # Interpretable PnL proxy for BUY trades only; SELL rows return 0 for this metric.
    if str(trade.get("side") or "").upper() != "BUY":
        return 0.0
    px = parse_float(trade.get("price"), default=0.0)
    notion = notional_usd(trade)
    if px <= 0.0 or notion <= 0.0:
        return 0.0
    if won:
        return notion * ((1.0 - px) / px)
    return -notion


def summarize_timing_distribution(
    smart_wallets: dict[str, SmartWallet],
    markets: list[MarketWindow],
    market_trades: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, int], list[dict[str, Any]]]:
    per_wallet: dict[str, dict[str, Any]] = {}
    global_buckets = {f"{lo}-{hi}s": 0 for lo, hi in BUCKETS}
    global_buckets["out_of_window"] = 0
    sampled_rows: list[dict[str, Any]] = []

    market_map = {m.condition_id: m for m in markets}
    for condition_id, trades in market_trades.items():
        market = market_map.get(condition_id)
        if market is None:
            continue
        for trade in trades:
            wallet = normalize_wallet(trade.get("proxyWallet"))
            if wallet not in smart_wallets:
                continue
            ts = parse_int(trade.get("timestamp"), default=0)
            offset = ts - market.window_start_ts
            bucket = bucket_name(offset)
            global_buckets[bucket] = global_buckets.get(bucket, 0) + 1
            effective_idx = effective_outcome_index(
                str(trade.get("side") or ""),
                parse_int(trade.get("outcomeIndex"), default=0),
            )
            won = market.winner_index is not None and effective_idx == market.winner_index
            direction = (
                market.outcomes[effective_idx]
                if 0 <= effective_idx < len(market.outcomes)
                else f"outcome_{effective_idx}"
            )
            notion = round(notional_usd(trade), 6)
            price = round(parse_float(trade.get("price"), default=0.0), 6)

            rec = per_wallet.setdefault(
                wallet,
                {
                    "address": wallet,
                    "rank": smart_wallets[wallet].rank,
                    "source": smart_wallets[wallet].source,
                    "pnl_usd_reference": smart_wallets[wallet].pnl_usd,
                    "volume_usd_reference": smart_wallets[wallet].volume_usd,
                    "total_smart_trades_analyzed": 0,
                    "entry_timing_buckets": {f"{lo}-{hi}s": 0 for lo, hi in BUCKETS} | {"out_of_window": 0},
                    "entry_timing_notional_usd": {
                        f"{lo}-{hi}s": 0.0 for lo, hi in BUCKETS
                    }
                    | {"out_of_window": 0.0},
                    "high_price_early_trades_0_120_0p90_0p94": 0,
                    "high_price_early_wins_0_120_0p90_0p94": 0,
                },
            )
            rec["total_smart_trades_analyzed"] += 1
            rec["entry_timing_buckets"][bucket] += 1
            rec["entry_timing_notional_usd"][bucket] = round(
                rec["entry_timing_notional_usd"][bucket] + notion,
                6,
            )
            if (
                0 <= offset < 120
                and 0.90 <= price <= 0.94
                and str(trade.get("side") or "").upper() == "BUY"
            ):
                rec["high_price_early_trades_0_120_0p90_0p94"] += 1
                rec["high_price_early_wins_0_120_0p90_0p94"] += int(bool(won))

            sampled_rows.append(
                {
                    "condition_id": condition_id,
                    "slug": market.slug,
                    "wallet": wallet,
                    "timestamp": ts,
                    "entry_time_offset_sec": offset,
                    "bucket": bucket,
                    "side": str(trade.get("side") or ""),
                    "direction": direction,
                    "price": price,
                    "notional_usd": notion,
                    "won": bool(won),
                }
            )
    return per_wallet, global_buckets, sampled_rows


def compute_early_vs_late_correlation(
    sampled_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    def _group(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        wins = sum(1 for r in rows if bool(r.get("won")))
        total_notional = sum(parse_float(r.get("notional_usd"), default=0.0) for r in rows)
        pnl = 0.0
        for row in rows:
            price = parse_float(row.get("price"), default=0.0)
            notion = parse_float(row.get("notional_usd"), default=0.0)
            if price <= 0.0 or notion <= 0.0:
                continue
            if bool(row.get("won")):
                pnl += notion * ((1.0 - price) / price)
            else:
                pnl -= notion
        return {
            "trade_count": n,
            "wins": wins,
            "win_rate": round(wins / n, 6) if n else None,
            "wilson_95_lower": round(wilson_lower_bound(wins, n), 6) if n else None,
            "total_notional_usd": round(total_notional, 6),
            "approx_pnl_usd": round(pnl, 6),
        }

    buy_rows = [r for r in sampled_rows if str(r.get("side") or "").upper() == "BUY"]
    early_price_band = [
        r
        for r in buy_rows
        if 0 <= parse_int(r.get("entry_time_offset_sec"), default=-9999) < 120
        and 0.90 <= parse_float(r.get("price"), default=0.0) <= 0.94
    ]
    late_price_band = [
        r
        for r in buy_rows
        if 180 <= parse_int(r.get("entry_time_offset_sec"), default=-9999) < 300
        and 0.90 <= parse_float(r.get("price"), default=0.0) <= 0.94
    ]
    early_high_price = [
        r
        for r in buy_rows
        if 0 <= parse_int(r.get("entry_time_offset_sec"), default=-9999) < 180
        and parse_float(r.get("price"), default=0.0) >= 0.90
    ]
    late_high_price = [
        r
        for r in buy_rows
        if 180 <= parse_int(r.get("entry_time_offset_sec"), default=-9999) < 300
        and parse_float(r.get("price"), default=0.0) >= 0.90
    ]
    in_window = [
        r for r in buy_rows if 0 <= parse_int(r.get("entry_time_offset_sec"), default=-9999) < 300
    ]
    early_share = (
        len([r for r in in_window if parse_int(r.get("entry_time_offset_sec"), default=9999) < 180]) / len(in_window)
        if in_window
        else 0.0
    )
    return {
        "definition": "BUY trades by smart wallets; outcome judged by effective side vs resolved winner",
        "early_price_band_0_120s_price_0p90_0p94": _group(early_price_band),
        "late_price_band_180_300s_price_0p90_0p94": _group(late_price_band),
        "early_high_price_0_180s_price_gte_0p90": _group(early_high_price),
        "late_high_price_180_300s_price_gte_0p90": _group(late_high_price),
        "in_window_buy_trades": len(in_window),
        "early_share_0_180_over_0_300": round(early_share, 6),
    }


def evaluate_consensus_grid(
    *,
    markets: list[MarketWindow],
    market_trades: dict[str, list[dict[str, Any]]],
    smart_wallet_set: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    observation_windows = [60, 90, 120, 150, 180, 210, 240]
    min_wallet_grid = [2, 3, 4, 5]
    min_notional_grid = [100.0, 150.0, 200.0, 300.0, 500.0]
    grid_results: list[dict[str, Any]] = []

    market_lookup = {m.condition_id: m for m in markets}

    for obs_secs in observation_windows:
        for min_wallets in min_wallet_grid:
            for min_notional in min_notional_grid:
                signal_count = 0
                wins = 0
                copy_prices: list[float] = []
                per_signal_rows: list[dict[str, Any]] = []

                for condition_id, trades in market_trades.items():
                    market = market_lookup.get(condition_id)
                    if market is None or market.winner_index is None:
                        continue
                    by_side: dict[int, dict[str, Any]] = {}
                    for trade in trades:
                        wallet = normalize_wallet(trade.get("proxyWallet"))
                        if wallet not in smart_wallet_set:
                            continue
                        ts = parse_int(trade.get("timestamp"), default=0)
                        offset = ts - market.window_start_ts
                        if not (0 <= offset <= obs_secs):
                            continue
                        price = parse_float(trade.get("price"), default=0.0)
                        if price < 0.90:
                            continue
                        eff_idx = effective_outcome_index(
                            str(trade.get("side") or ""),
                            parse_int(trade.get("outcomeIndex"), default=0),
                        )
                        side_rec = by_side.setdefault(
                            eff_idx,
                            {"wallets": set(), "notional": 0.0, "prices": []},
                        )
                        side_rec["wallets"].add(wallet)
                        side_rec["notional"] += notional_usd(trade)
                        side_rec["prices"].append(price)

                    if not by_side:
                        continue

                    best_idx, best_side = max(
                        by_side.items(),
                        key=lambda item: (item[1]["notional"], len(item[1]["wallets"])),
                    )
                    wallet_count = len(best_side["wallets"])
                    notional = best_side["notional"]
                    if wallet_count < min_wallets or notional < min_notional:
                        continue

                    signal_count += 1
                    won = best_idx == market.winner_index
                    wins += int(won)
                    if best_side["prices"]:
                        copy_prices.extend(best_side["prices"])
                    per_signal_rows.append(
                        {
                            "condition_id": condition_id,
                            "slug": market.slug,
                            "winner_index": market.winner_index,
                            "predicted_index": best_idx,
                            "won": won,
                            "smart_wallet_count": wallet_count,
                            "combined_notional_usd": round(notional, 6),
                            "min_price": round(min(best_side["prices"]), 6) if best_side["prices"] else None,
                            "max_price": round(max(best_side["prices"]), 6) if best_side["prices"] else None,
                        }
                    )

                if signal_count == 0:
                    continue
                win_rate = wins / signal_count
                result = {
                    "observation_window_secs": obs_secs,
                    "min_wallets": min_wallets,
                    "min_notional_usd": min_notional,
                    "signals": signal_count,
                    "wins": wins,
                    "win_rate": round(win_rate, 6),
                    "wilson_95_lower": round(wilson_lower_bound(wins, signal_count), 6),
                    "copy_price_min": round(min(copy_prices), 6) if copy_prices else None,
                    "copy_price_max": round(max(copy_prices), 6) if copy_prices else None,
                    "copy_price_avg": round(sum(copy_prices) / len(copy_prices), 6) if copy_prices else None,
                    "sample_signals": per_signal_rows[:8],
                }
                grid_results.append(result)

    grid_results.sort(
        key=lambda r: (
            -r["wilson_95_lower"],
            -r["signals"],
            -r["win_rate"],
            r["copy_price_avg"] if r["copy_price_avg"] is not None else 9.99,
        )
    )
    best = grid_results[0] if grid_results else {}
    return grid_results, best


def build_verdict(
    *,
    early_correlation: dict[str, Any],
    best_consensus: dict[str, Any],
) -> dict[str, Any]:
    early_share = parse_float(early_correlation.get("early_share_0_180_over_0_300"), default=0.0)
    evidence_n = parse_int(early_correlation.get("in_window_buy_trades"), default=0)
    signals = parse_int(best_consensus.get("signals"), default=0)
    wr = parse_float(best_consensus.get("win_rate"), default=0.0)
    lb = parse_float(best_consensus.get("wilson_95_lower"), default=0.0)
    copy_price_avg = parse_float(best_consensus.get("copy_price_avg"), default=99.0)
    actionable = bool(
        signals >= 8
        and wr >= 0.85
        and lb >= 0.70
        and early_share >= 0.50
        and copy_price_avg <= 0.96
    )
    if actionable:
        confidence = max(0.0, min(0.99, lb * 0.7 + min(1.0, signals / 20.0) * 0.3))
    else:
        confidence = 0.35
        if evidence_n >= 80:
            confidence += min(0.35, evidence_n / 500.0)
        if early_share < 0.30:
            confidence += 0.20
        if signals == 0:
            confidence += 0.05
        confidence = max(0.0, min(0.95, confidence))
    if actionable:
        rationale = (
            "Smart-wallet consensus meets threshold quality: enough signals, high win rate, "
            "strong lower confidence bound, and copy prices still below the late-window cliff."
        )
    else:
        rationale = (
            "Signal quality is insufficient for live copy deployment under current thresholds "
            "(too few qualifying signals, weak confidence bound, late-dominant entries, or copy "
            "prices too close to expiry)."
        )
    return {
        "actionable_signal": actionable,
        "confidence": round(confidence, 6),
        "binary_question_answer": "minute_1_to_3" if early_share >= 0.5 else "minute_4_to_5",
        "rationale": rationale,
        "gates": {
            "signals_gte_8": signals >= 8,
            "win_rate_gte_0p85": wr >= 0.85,
            "wilson_95_lower_gte_0p70": lb >= 0.70,
            "early_share_gte_0p50": early_share >= 0.50,
            "copy_price_avg_lte_0p96": copy_price_avg <= 0.96,
        },
    }


def run_analysis(args: argparse.Namespace) -> dict[str, Any]:
    wallet_json_candidates = [
        Path("wallet_analysis.json"),
        Path("data/smart_wallets_scored.json"),
        Path("data/smart_wallets.json"),
        Path("config/smart_wallets.json"),
    ]
    if args.wallet_json:
        wallet_json_candidates.extend(Path(p) for p in args.wallet_json)

    top_wallets, wallet_source_info = load_top_smart_wallets(
        top_n=args.top_wallets,
        wallet_scores_db=Path(args.wallet_scores_db),
        wallet_json_paths=wallet_json_candidates,
    )
    if not top_wallets:
        raise RuntimeError("Unable to load smart wallets from DB/files/API")

    smart_wallet_map = {w.address: w for w in top_wallets}
    smart_wallet_set = set(smart_wallet_map.keys())

    target_markets, market_source_info = choose_target_markets(
        btc5_db_path=Path(args.btc5_db),
        target_market_count=args.market_count,
        prefer_db_fill_windows=not args.skip_db_windows,
    )
    if not target_markets:
        raise RuntimeError("No target BTC5 markets available for timing analysis")

    market_trades: dict[str, list[dict[str, Any]]] = {}
    market_summaries: list[dict[str, Any]] = []
    for market in target_markets:
        trades = fetch_market_trades(
            market.condition_id,
            max_rows=args.max_trades_per_market,
            page_size=args.trade_page_size,
            max_pages_safety=args.max_market_pages,
        )
        market_trades[market.condition_id] = trades
        smart_trade_count = sum(
            1
            for t in trades
            if normalize_wallet(t.get("proxyWallet")) in smart_wallet_set
        )
        market_summaries.append(
            {
                "condition_id": market.condition_id,
                "slug": market.slug,
                "window_start_ts": market.window_start_ts,
                "winner_index": market.winner_index,
                "winner_label": (
                    market.outcomes[market.winner_index]
                    if market.winner_index is not None and 0 <= market.winner_index < len(market.outcomes)
                    else None
                ),
                "outcomes": market.outcomes,
                "outcome_prices": market.outcome_prices,
                "trade_count": len(trades),
                "smart_wallet_trade_count": smart_trade_count,
                "source": market.source,
            }
        )

    per_wallet, global_buckets, sampled_rows = summarize_timing_distribution(
        smart_wallets=smart_wallet_map,
        markets=target_markets,
        market_trades=market_trades,
    )
    early_correlation = compute_early_vs_late_correlation(sampled_rows)
    consensus_grid, best_consensus = evaluate_consensus_grid(
        markets=target_markets,
        market_trades=market_trades,
        smart_wallet_set=smart_wallet_set,
    )
    verdict = build_verdict(
        early_correlation=early_correlation,
        best_consensus=best_consensus,
    )

    recommendations: dict[str, Any] = {}
    if verdict["actionable_signal"] and best_consensus:
        recommendations = {
            "optimal_observation_window_secs": best_consensus.get("observation_window_secs"),
            "minimum_consensus_threshold": {
                "wallets": best_consensus.get("min_wallets"),
                "combined_notional_usd": best_consensus.get("min_notional_usd"),
            },
            "expected_price_range_at_copy_time": {
                "min": best_consensus.get("copy_price_min"),
                "max": best_consensus.get("copy_price_max"),
                "avg": best_consensus.get("copy_price_avg"),
            },
        }

    return {
        "generated_at": now_iso(),
        "analysis_version": "1.0.0",
        "analysis_parameters": {
            "top_wallets": args.top_wallets,
            "market_count": args.market_count,
            "max_trades_per_market": args.max_trades_per_market,
            "trade_page_size": args.trade_page_size,
            "max_market_pages": args.max_market_pages,
            "skip_db_windows": bool(args.skip_db_windows),
        },
        "data_sources": {
            "wallet_source": wallet_source_info,
            "market_source": market_source_info,
            "db_paths": {
                "wallet_scores_db": args.wallet_scores_db,
                "btc5_db": args.btc5_db,
            },
        },
        "top_smart_wallets": [
            {
                "address": w.address,
                "rank": w.rank,
                "pnl_usd": w.pnl_usd,
                "volume_usd": w.volume_usd,
                "source": w.source,
            }
            for w in top_wallets
        ],
        "markets_analyzed": market_summaries,
        "per_wallet_entry_timing_distribution": per_wallet,
        "global_entry_timing_buckets": global_buckets,
        "early_entry_correlation": early_correlation,
        "consensus_grid_top_results": consensus_grid[:20],
        "best_consensus_result": best_consensus,
        "verdict": verdict,
        "recommendations_if_actionable": recommendations,
        "notes": [
            "If local data/btc_5min_maker.db is unavailable, fallback uses recent resolved BTC5 markets from Gamma.",
            "Trade API market filter uses ?market=<condition_id>; conditionId parameter is not reliable on current API surface.",
            "Outcome correctness uses effective side (BUY keeps outcomeIndex, SELL flips outcomeIndex).",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze smart-wallet entry timing for BTC5 markets")
    parser.add_argument(
        "--wallet-scores-db",
        default="data/wallet_scores.db",
        help="Path to wallet_scores.db (default: data/wallet_scores.db)",
    )
    parser.add_argument(
        "--btc5-db",
        default="data/btc_5min_maker.db",
        help="Path to btc_5min_maker.db (default: data/btc_5min_maker.db)",
    )
    parser.add_argument(
        "--wallet-json",
        action="append",
        default=[],
        help="Additional wallet JSON artifact path(s). Can be provided multiple times.",
    )
    parser.add_argument(
        "--output",
        default="reports/smart_wallet_timing_analysis.json",
        help="Output path (default: reports/smart_wallet_timing_analysis.json)",
    )
    parser.add_argument("--top-wallets", type=int, default=20)
    parser.add_argument("--market-count", type=int, default=30)
    parser.add_argument(
        "--max-trades-per-market",
        type=int,
        default=0,
        help="0 means no explicit row cap (paginate until API exhaustion)",
    )
    parser.add_argument("--trade-page-size", type=int, default=200)
    parser.add_argument(
        "--max-market-pages",
        type=int,
        default=500,
        help="Safety cap on paginated trade requests per market",
    )
    parser.add_argument(
        "--skip-db-windows",
        action="store_true",
        help="Ignore btc_5min_maker.db and force API fallback market selection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = run_analysis(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    LOG.info("Wrote timing analysis report to %s", output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "actionable_signal": payload["verdict"]["actionable_signal"],
                "confidence": payload["verdict"]["confidence"],
                "binary_question_answer": payload["verdict"]["binary_question_answer"],
                "markets_analyzed": len(payload["markets_analyzed"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
