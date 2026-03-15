#!/usr/bin/env python3
"""Analyze smart-wallet BTC5 entry timing from Polymarket trade tape."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
WINDOW_SECONDS = 300
BTC5_PREFIX = "btc-updown-5m-"

DEFAULT_DB_PATH = Path(os.environ.get("BTC5_DB_PATH", "data/btc_5min_maker.db"))
DEFAULT_WALLET_SCORES = Path("inventory/data/smart_wallets_scored.json")
DEFAULT_OUTPUT_PATH = Path("reports/smart_wallet_timing_analysis.json")

KNOWN_ELITE_WALLETS: dict[str, str] = {
    "k9Q2mX4L8A7ZP3R": "0xd0d6053c3c37e727402d84c14069780d360993aa",
    "0x8dxd": "0x63ce342161250d705dc0b16df89036c8e5f9ba9a",
    "BoneReader": "0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9",
    "vidarx": "0x2d8b401d2f0e6937afebf18e19e11ca568a5260a",
    "gabagool22": "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d",
    "0x1979": "0x1979ae6b7e6534de9c4539d0c205e582ca637c9d",
}

BUCKETS: list[tuple[str, int, int]] = [
    ("0-60s", 0, 60),
    ("60-120s", 60, 120),
    ("120-180s", 120, 180),
    ("180-240s", 180, 240),
    ("240-300s", 240, 300),
]

LOG = logging.getLogger("smart_wallet_timing")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_wallet(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("0x") and len(text) == 42:
        return text
    return ""


def _normalize_timestamp_seconds(raw_ts: Any) -> int:
    ts = _safe_int(raw_ts, default=0)
    if ts <= 0:
        return 0
    # Data API timestamps are occasionally milliseconds.
    if ts > 10_000_000_000:
        ts = ts // 1000
    return ts


def _window_start_from_slug(slug: str) -> int:
    text = str(slug or "").strip().lower()
    if not text.startswith(BTC5_PREFIX):
        return 0
    suffix = text[len(BTC5_PREFIX) :]
    return _safe_int(suffix, default=0)


def _bucket_label_for_offset(offset_seconds: int) -> str | None:
    for label, lo, hi in BUCKETS:
        if lo <= offset_seconds < hi:
            return label
    return None


def _effective_outcome_index(trade: dict[str, Any]) -> int:
    idx = _safe_int(trade.get("outcomeIndex"), default=0)
    side = str(trade.get("side") or "").strip().upper()
    return idx if side == "BUY" else 1 - idx


def _trade_notional_usd(trade: dict[str, Any]) -> float:
    usdc_size = _safe_float(trade.get("usdcSize"), default=0.0)
    if usdc_size > 0:
        return usdc_size
    return _safe_float(trade.get("size"), default=0.0) * _safe_float(trade.get("price"), default=0.0)


@dataclass(frozen=True)
class MarketWindow:
    condition_id: str
    slug: str
    window_start_ts: int
    source: str


class ApiClient:
    def __init__(self, *, min_interval_seconds: float = 0.12, timeout_seconds: float = 20.0):
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.timeout_seconds = float(timeout_seconds)
        self._last_request_monotonic = 0.0
        self.session = requests.Session()

    def _throttle(self) -> None:
        if self.min_interval_seconds <= 0.0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_monotonic
        sleep_for = self.min_interval_seconds - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)

    def get_json(self, url: str, params: dict[str, Any] | None = None, *, retries: int = 4) -> Any:
        for attempt in range(retries):
            self._throttle()
            try:
                response = self.session.get(url, params=params, timeout=self.timeout_seconds)
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    raise RuntimeError(f"request failed for {url}: {exc}") from exc
                time.sleep(2**attempt)
                continue

            self._last_request_monotonic = time.monotonic()
            if response.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code >= 400:
                if attempt == retries - 1:
                    raise RuntimeError(f"http {response.status_code} for {url} params={params}")
                time.sleep(2**attempt)
                continue
            return response.json()
        raise RuntimeError(f"exhausted retries for {url}")

    def fetch_condition_trades(self, condition_id: str, *, limit: int) -> list[dict[str, Any]]:
        payload = self.get_json(
            f"{DATA_API_BASE}/trades",
            params={"conditionId": condition_id, "limit": int(limit), "takerOnly": "false"},
        )
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _wallet_match_ratio(expected_wallet: str, trades: list[dict[str, Any]]) -> float:
        expected = _normalize_wallet(expected_wallet)
        if not trades or not expected:
            return 0.0
        matched = 0
        for trade in trades:
            if _normalize_wallet(trade.get("proxyWallet")) == expected:
                matched += 1
        return matched / float(len(trades))

    def fetch_wallet_trades(self, wallet: str, *, limit: int) -> list[dict[str, Any]]:
        fallback_rows: list[dict[str, Any]] = []
        for param_key in ("user", "proxyWallet"):
            payload = self.get_json(
                f"{DATA_API_BASE}/trades",
                params={param_key: wallet, "limit": int(limit), "takerOnly": "false"},
            )
            rows = payload if isinstance(payload, list) else []
            if not rows:
                continue
            ratio = self._wallet_match_ratio(wallet, rows)
            if ratio >= 0.6:
                return rows
            if not fallback_rows:
                fallback_rows = rows
        return fallback_rows

    def fetch_markets_page(
        self,
        *,
        closed: bool,
        limit: int,
        offset: int,
        order: str | None = None,
        ascending: bool | None = None,
        active: bool | None = None,
        slug: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "closed": str(closed).lower(),
            "limit": int(limit),
            "offset": int(offset),
        }
        if active is not None:
            params["active"] = str(active).lower()
        if order:
            params["order"] = order
        if ascending is not None:
            params["ascending"] = str(bool(ascending)).lower()
        if slug:
            params["slug"] = slug
        payload = self.get_json(f"{GAMMA_API_BASE}/markets", params=params)
        return payload if isinstance(payload, list) else []

    def fetch_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        page = self.fetch_markets_page(closed=False, active=True, limit=20, offset=0, slug=slug)
        for row in page:
            if str(row.get("slug") or "").strip() == slug:
                return row
        page = self.fetch_markets_page(closed=True, limit=50, offset=0, order="endDate", ascending=False, slug=slug)
        for row in page:
            if str(row.get("slug") or "").strip() == slug:
                return row
        return None

    def fetch_market_exact_slug(self, slug: str) -> dict[str, Any] | None:
        page = self.fetch_markets_page(closed=False, limit=5, offset=0, slug=slug)
        for row in page:
            if str(row.get("slug") or "").strip() == slug:
                return row
        return None


def _load_top_wallets(wallet_scores_path: Path, *, top_n: int) -> tuple[list[str], dict[str, float]]:
    wallets: list[str] = []
    wallet_win_rate_estimate: dict[str, float] = {}
    seed_seen: set[str] = set()

    for addr in KNOWN_ELITE_WALLETS.values():
        norm = _normalize_wallet(addr)
        if norm and norm not in seed_seen:
            seed_seen.add(norm)
            wallets.append(norm)

    if wallet_scores_path.exists():
        payload = json.loads(wallet_scores_path.read_text(encoding="utf-8"))
        ranked = payload.get("ranked_wallets")
        if isinstance(ranked, list):
            for row in ranked:
                if not isinstance(row, dict):
                    continue
                addr = _normalize_wallet(row.get("address"))
                if not addr or addr in seed_seen:
                    continue
                seed_seen.add(addr)
                wallets.append(addr)
                win_est = _safe_float(row.get("estimated_win_rate"), default=-1.0)
                if 0.0 <= win_est <= 1.0:
                    wallet_win_rate_estimate[addr] = win_est
                if len(wallets) >= max(top_n * 3, top_n):
                    break
        wallet_map = payload.get("wallets")
        if isinstance(wallet_map, dict):
            for raw_addr, row in wallet_map.items():
                if not isinstance(row, dict):
                    continue
                addr = _normalize_wallet(raw_addr)
                if not addr:
                    continue
                win_est = _safe_float(row.get("win_rate"), default=-1.0)
                if 0.0 <= win_est <= 1.0 and addr not in wallet_win_rate_estimate:
                    wallet_win_rate_estimate[addr] = win_est

    # Keep elites + top-ranked candidates; trim to requested top-N.
    selected = wallets[: max(1, top_n)]
    return selected, wallet_win_rate_estimate


def _extract_historical_fill_windows(db_path: Path, *, max_rows: int) -> list[dict[str, Any]]:
    if not db_path.exists():
        LOG.warning("historical fill DB not found: %s", db_path)
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='window_trades'").fetchone()
        if table is None:
            LOG.warning("window_trades table missing in %s", db_path)
            return []
        rows = conn.execute(
            """
            SELECT window_start_ts, slug, won, order_status
            FROM window_trades
            WHERE order_status = 'live_filled'
              AND COALESCE(won, 0) = 1
            ORDER BY decision_ts DESC, id DESC
            LIMIT ?
            """,
            (int(max_rows),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            ws = _safe_int(row["window_start_ts"], default=0)
            slug = str(row["slug"] or "").strip()
            if ws <= 0 and slug:
                ws = _window_start_from_slug(slug)
            if ws <= 0:
                continue
            out.append(
                {
                    "window_start_ts": ws,
                    "slug": slug or f"{BTC5_PREFIX}{ws}",
                    "won": 1,
                }
            )
        return out
    finally:
        conn.close()


def _collect_recent_btc5_markets(
    api: ApiClient,
    *,
    now_ts: int,
    lookback_hours: int,
    max_markets: int,
) -> list[MarketWindow]:
    earliest_ts = now_ts - int(lookback_hours * 3600)
    out: dict[str, MarketWindow] = {}

    # Pull active markets first (usually newest windows).
    active_rows = api.fetch_markets_page(closed=False, active=True, limit=500, offset=0)
    for market in active_rows:
        slug = str(market.get("slug") or "").strip()
        condition_id = str(market.get("conditionId") or market.get("condition_id") or "").strip()
        ws = _window_start_from_slug(slug)
        if not condition_id or ws <= 0 or ws < earliest_ts:
            continue
        out[condition_id] = MarketWindow(condition_id=condition_id, slug=slug, window_start_ts=ws, source="live")

    # Pull recently closed pages until enough windows.
    offset = 0
    page_limit = 500
    for _ in range(8):
        page = api.fetch_markets_page(
            closed=True,
            limit=page_limit,
            offset=offset,
            order="endDate",
            ascending=False,
        )
        if not page:
            break
        stop_for_age = False
        for market in page:
            slug = str(market.get("slug") or "").strip()
            if not slug.startswith(BTC5_PREFIX):
                continue
            condition_id = str(market.get("conditionId") or market.get("condition_id") or "").strip()
            if not condition_id:
                continue
            ws = _window_start_from_slug(slug)
            if ws <= 0:
                continue
            if ws < earliest_ts:
                stop_for_age = True
                continue
            if condition_id not in out:
                out[condition_id] = MarketWindow(
                    condition_id=condition_id,
                    slug=slug,
                    window_start_ts=ws,
                    source="recent_closed",
                )
        if stop_for_age and len(out) >= max_markets:
            break
        if len(page) < page_limit:
            break
        if len(out) >= max_markets * 2:
            break
        offset += page_limit

    ordered = sorted(out.values(), key=lambda row: row.window_start_ts, reverse=True)
    return ordered[:max_markets]


def _collect_recent_btc5_markets_from_wallets(
    api: ApiClient,
    *,
    wallets: list[str],
    now_ts: int,
    lookback_hours: int,
    max_markets: int,
    per_wallet_trade_limit: int,
) -> list[MarketWindow]:
    earliest_ts = now_ts - int(lookback_hours * 3600)
    out: dict[str, MarketWindow] = {}
    for wallet in wallets:
        rows = api.fetch_wallet_trades(wallet=wallet, limit=per_wallet_trade_limit)
        for trade in rows:
            ts = _normalize_timestamp_seconds(trade.get("timestamp") or trade.get("matchTime"))
            if ts <= 0 or ts < earliest_ts:
                continue
            slug = str(trade.get("slug") or trade.get("eventSlug") or "").strip()
            condition_id = str(trade.get("conditionId") or "").strip()
            if not slug.startswith(BTC5_PREFIX) or not condition_id:
                continue
            ws = _window_start_from_slug(slug)
            if ws <= 0 or ws < earliest_ts:
                continue
            if condition_id not in out:
                out[condition_id] = MarketWindow(
                    condition_id=condition_id,
                    slug=slug,
                    window_start_ts=ws,
                    source="wallet_tape_recent",
                )
            if len(out) >= max_markets * 3:
                break
        if len(out) >= max_markets * 3:
            break
    ordered = sorted(out.values(), key=lambda row: row.window_start_ts, reverse=True)
    return ordered[:max_markets]


def _collect_recent_btc5_markets_from_slug_probe(
    api: ApiClient,
    *,
    now_ts: int,
    lookback_hours: int,
    max_markets: int,
) -> list[MarketWindow]:
    latest_window = (now_ts // WINDOW_SECONDS) * WINDOW_SECONDS
    earliest_window = latest_window - int(lookback_hours * 3600)
    out: list[MarketWindow] = []
    seen: set[str] = set()
    for ws in range(latest_window, earliest_window - 1, -WINDOW_SECONDS):
        slug = f"{BTC5_PREFIX}{ws}"
        market = api.fetch_market_exact_slug(slug)
        if not isinstance(market, dict):
            continue
        condition_id = str(market.get("conditionId") or market.get("condition_id") or "").strip()
        if not condition_id or condition_id in seen:
            continue
        seen.add(condition_id)
        out.append(
            MarketWindow(
                condition_id=condition_id,
                slug=slug,
                window_start_ts=ws,
                source="slug_probe",
            )
        )
        if len(out) >= max_markets:
            break
    return out


def _enrich_fill_windows_with_condition_ids(
    api: ApiClient,
    fill_rows: list[dict[str, Any]],
    known_markets: list[MarketWindow],
) -> list[MarketWindow]:
    by_slug = {row.slug: row for row in known_markets}
    by_ws = {row.window_start_ts: row for row in known_markets}
    out: list[MarketWindow] = []
    for row in fill_rows:
        slug = str(row.get("slug") or "").strip()
        ws = _safe_int(row.get("window_start_ts"), default=0)
        found = by_slug.get(slug) if slug else None
        if found is None and ws > 0:
            found = by_ws.get(ws)
        if found is None and slug:
            maybe = api.fetch_market_by_slug(slug)
            if isinstance(maybe, dict):
                cid = str(maybe.get("conditionId") or maybe.get("condition_id") or "").strip()
                ws = ws or _window_start_from_slug(str(maybe.get("slug") or slug))
                if cid and ws > 0:
                    found = MarketWindow(condition_id=cid, slug=slug, window_start_ts=ws, source="historical_fill")
        if found is not None:
            out.append(
                MarketWindow(
                    condition_id=found.condition_id,
                    slug=found.slug,
                    window_start_ts=found.window_start_ts,
                    source="historical_fill",
                )
            )
    dedup: dict[str, MarketWindow] = {}
    for row in out:
        dedup[row.condition_id] = row
    return list(dedup.values())


def _compute_verdict(
    *,
    bucket_counts: dict[str, int],
    bucket_avg_price: dict[str, float | None],
    sample_size: int,
    active_market_size: int,
    min_sample_size: int,
) -> tuple[str, float, int]:
    total_entries = sum(bucket_counts.values())
    early = bucket_counts["0-60s"] + bucket_counts["60-120s"] + bucket_counts["120-180s"]
    late = bucket_counts["180-240s"] + bucket_counts["240-300s"]
    early_share = (early / float(total_entries)) if total_entries > 0 else 0.0

    weighted_price_numerator = 0.0
    weighted_price_denominator = 0
    for label, count in bucket_counts.items():
        avg_px = bucket_avg_price.get(label)
        if avg_px is None or count <= 0:
            continue
        weighted_price_numerator += avg_px * count
        weighted_price_denominator += count
    weighted_avg_price = (
        weighted_price_numerator / float(weighted_price_denominator)
        if weighted_price_denominator > 0
        else 1.0
    )

    min_active_markets = max(5, min_sample_size // 4)
    actionable = (
        sample_size >= min_sample_size
        and active_market_size >= min_active_markets
        and total_entries >= 20
        and early_share >= 0.58
        and weighted_avg_price <= 0.96
        and early > late
    )
    verdict = "ACTIONABLE" if actionable else "NOT_ACTIONABLE"

    # Confidence scales with sample size and signal separation.
    sample_term = min(1.0, sample_size / 60.0)
    activity_term = min(1.0, active_market_size / 20.0)
    entry_term = min(1.0, total_entries / 80.0)
    timing_term = min(1.0, abs(early_share - 0.5) * 2.0)
    price_term = 1.0 if weighted_avg_price <= 0.94 else max(0.0, 1.0 - ((weighted_avg_price - 0.94) / 0.08))
    confidence = 0.30 + 0.22 * sample_term + 0.18 * activity_term + 0.15 * entry_term + 0.10 * timing_term + 0.05 * price_term
    confidence = max(0.05, min(0.97, confidence))

    if bucket_counts["0-60s"] + bucket_counts["60-120s"] >= int(0.55 * max(1, total_entries)):
        observation_window = 120
    elif bucket_counts["0-60s"] + bucket_counts["60-120s"] + bucket_counts["120-180s"] >= int(
        0.70 * max(1, total_entries)
    ):
        observation_window = 180
    else:
        observation_window = 240
    return verdict, round(confidence, 4), observation_window


def run(args: argparse.Namespace) -> dict[str, Any]:
    api = ApiClient(min_interval_seconds=args.min_interval_seconds, timeout_seconds=args.timeout_seconds)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    top_wallets, wallet_win_estimates = _load_top_wallets(args.wallet_scores, top_n=args.top_wallets)
    top_wallet_set = set(top_wallets)
    if not top_wallets:
        raise RuntimeError("no smart-wallet addresses available; cannot run timing analysis")

    historical_fill_rows = _extract_historical_fill_windows(args.db_path, max_rows=args.historical_fill_limit)
    recent_market_pool = _collect_recent_btc5_markets_from_slug_probe(
        api,
        now_ts=now_ts,
        lookback_hours=args.lookback_hours,
        max_markets=max(args.live_market_sample * 3, args.live_market_sample + 40),
    )
    wallet_market_pool = _collect_recent_btc5_markets_from_wallets(
        api,
        wallets=top_wallets,
        now_ts=now_ts,
        lookback_hours=args.lookback_hours,
        max_markets=max(args.live_market_sample * 3, args.live_market_sample + 40),
        per_wallet_trade_limit=args.wallet_trade_limit,
    )
    if wallet_market_pool:
        recent_market_pool.extend(wallet_market_pool)
    gamma_market_pool = _collect_recent_btc5_markets(
        api,
        now_ts=now_ts,
        lookback_hours=args.lookback_hours,
        max_markets=max(args.live_market_sample * 3, args.live_market_sample + 40),
    )
    if gamma_market_pool:
        for row in gamma_market_pool:
            recent_market_pool.append(row)
    dedup_market_pool: dict[str, MarketWindow] = {}
    for row in recent_market_pool:
        dedup_market_pool[row.condition_id] = row
    recent_market_pool = sorted(dedup_market_pool.values(), key=lambda row: row.window_start_ts, reverse=True)
    historical_markets = _enrich_fill_windows_with_condition_ids(api, historical_fill_rows, recent_market_pool)

    selected_live_markets: list[MarketWindow] = []
    historical_condition_ids = {row.condition_id for row in historical_markets}
    for market in recent_market_pool:
        if market.condition_id in historical_condition_ids:
            continue
        selected_live_markets.append(MarketWindow(**{**market.__dict__, "source": "live_sample"}))
        if len(selected_live_markets) >= args.live_market_sample:
            break

    analysis_markets = historical_markets + selected_live_markets
    deduped_markets: dict[str, MarketWindow] = {}
    for row in analysis_markets:
        deduped_markets[row.condition_id] = row
    markets = sorted(deduped_markets.values(), key=lambda row: row.window_start_ts, reverse=True)

    bucket_stats: dict[str, dict[str, float]] = {
        label: {"count": 0.0, "price_sum": 0.0, "win_sum": 0.0, "win_count": 0.0}
        for label, _, _ in BUCKETS
    }
    sampled_market_rows: list[dict[str, Any]] = []
    analyzed_market_rows: list[dict[str, Any]] = []
    smart_trades_total = 0

    for market in markets:
        trades = api.fetch_condition_trades(market.condition_id, limit=args.trade_limit)
        smart_trades_market = 0
        for trade in trades:
            wallet = _normalize_wallet(trade.get("proxyWallet"))
            if wallet not in top_wallet_set:
                continue
            ts = _normalize_timestamp_seconds(trade.get("timestamp") or trade.get("matchTime"))
            if ts <= 0:
                continue
            offset_seconds = ts - market.window_start_ts
            bucket = _bucket_label_for_offset(offset_seconds)
            if bucket is None:
                continue
            price = _safe_float(trade.get("price"), default=-1.0)
            if not (0.0 < price < 1.0):
                continue
            stat = bucket_stats[bucket]
            stat["count"] += 1.0
            stat["price_sum"] += price
            win_est = wallet_win_estimates.get(wallet)
            if win_est is not None and 0.0 <= win_est <= 1.0:
                stat["win_sum"] += float(win_est)
                stat["win_count"] += 1.0
            smart_trades_market += 1
            smart_trades_total += 1

        analyzed_market_rows.append(
            {
                "condition_id": market.condition_id,
                "slug": market.slug,
                "window_start_ts": market.window_start_ts,
                "source": market.source,
                "smart_wallet_trade_count": smart_trades_market,
            }
        )
        if smart_trades_market > 0:
            sampled_market_rows.append(analyzed_market_rows[-1])

    distribution: dict[str, dict[str, Any]] = {}
    bucket_counts: dict[str, int] = {}
    bucket_avg_price: dict[str, float | None] = {}
    for label, _, _ in BUCKETS:
        stat = bucket_stats[label]
        count = int(stat["count"])
        avg_price = (stat["price_sum"] / stat["count"]) if stat["count"] > 0 else None
        win_rate = (stat["win_sum"] / stat["win_count"]) if stat["win_count"] > 0 else None
        bucket_counts[label] = count
        bucket_avg_price[label] = round(avg_price, 4) if avg_price is not None else None
        distribution[label] = {
            "count": count,
            "avg_price": round(avg_price, 4) if avg_price is not None else None,
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
        }

    verdict, confidence, observation_window = _compute_verdict(
        bucket_counts=bucket_counts,
        bucket_avg_price=bucket_avg_price,
        sample_size=len(analyzed_market_rows),
        active_market_size=len(sampled_market_rows),
        min_sample_size=args.min_sample_size,
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "confidence": confidence,
        "sample_size": len(analyzed_market_rows),
        "smart_wallet_entry_distribution": distribution,
        "optimal_observation_window_sec": observation_window,
        "min_consensus_wallets": 3,
        "min_consensus_notional_usd": 200,
        "metadata": {
            "total_smart_wallet_trade_entries": smart_trades_total,
            "historical_fill_windows_requested": args.historical_fill_limit,
            "historical_fill_windows_used": len(historical_markets),
            "live_market_sample_requested": args.live_market_sample,
            "live_market_sample_used": len([r for r in analyzed_market_rows if r["source"] == "live_sample"]),
            "markets_with_smart_wallet_activity": len(sampled_market_rows),
            "wallet_source_path": str(args.wallet_scores.resolve()),
            "db_path": str(args.db_path),
            "top_wallet_addresses": top_wallets,
            "markets_analyzed": analyzed_market_rows,
        },
    }
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze smart-wallet BTC5 entry timing.")
    parser.add_argument("--wallet-scores", type=Path, default=DEFAULT_WALLET_SCORES)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-wallets", type=int, default=20)
    parser.add_argument("--historical-fill-limit", type=int, default=8)
    parser.add_argument("--live-market-sample", type=int, default=30)
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--trade-limit", type=int, default=200)
    parser.add_argument("--wallet-trade-limit", type=int, default=500)
    parser.add_argument("--min-sample-size", type=int, default=20)
    parser.add_argument("--min-interval-seconds", type=float, default=0.12)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"wrote {args.output} | verdict={payload['verdict']} "
        f"confidence={payload['confidence']} sample_size={payload['sample_size']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())