#!/usr/bin/env python3
"""Shadow data collector — lightweight market intelligence that runs unattended.

Pulls Polymarket market snapshots every cycle (default: 30 min via launchd),
stores them in ~/.elastifund/shadow_data/ outside macOS protected folders.

No trading. No secrets required. No Desktop path access.
Collects: market prices, volumes, liquidity, order flow metrics.

Usage:
    python3 shadow_collector.py              # single collection cycle
    python3 shadow_collector.py --loop       # continuous (30-min interval)
    python3 shadow_collector.py --summary    # print latest collection stats
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


# ── Paths (all under ~/.elastifund, NOT ~/Desktop) ──
SHADOW_ROOT = Path.home() / ".elastifund" / "shadow_data"
DB_PATH = SHADOW_ROOT / "shadow_markets.db"
LOG_PATH = SHADOW_ROOT / "collector.log"
LATEST_PATH = SHADOW_ROOT / "latest_snapshot.json"

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events?closed=false&limit=500"
GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets?closed=false&limit=200&order=liquidityClob&ascending=false"
DEFAULT_INTERVAL = 1800  # 30 minutes


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    ts = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def fetch_json(url: str, timeout: int = 30) -> list | dict:
    req = Request(url, headers={"User-Agent": "ElastifundShadow/1.0", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        log(f"FETCH ERROR {url}: {exc}")
        return []


def init_db() -> sqlite3.Connection:
    SHADOW_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collected_at TEXT NOT NULL,
            total_events INTEGER,
            total_markets INTEGER,
            markets_under_24h INTEGER,
            markets_under_48h INTEGER,
            markets_in_price_window INTEGER,
            avg_liquidity REAL,
            avg_volume REAL,
            category_counts TEXT,
            top_markets TEXT
        );

        CREATE TABLE IF NOT EXISTS market_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collected_at TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            question TEXT,
            category TEXT,
            yes_price REAL,
            liquidity REAL,
            volume REAL,
            resolution_hours REAL,
            spread REAL
        );

        CREATE INDEX IF NOT EXISTS idx_prices_time ON market_prices(collected_at);
        CREATE INDEX IF NOT EXISTS idx_prices_market ON market_prices(condition_id);
        CREATE INDEX IF NOT EXISTS idx_snapshots_time ON snapshots(collected_at);
    """)
    return conn


def parse_yes_price(market: dict) -> float | None:
    raw = market.get("outcomePrices")
    values = []
    if isinstance(raw, str):
        try:
            values = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            values = []
    elif isinstance(raw, list):
        values = raw
    if len(values) >= 1:
        try:
            return max(0.0, min(1.0, float(values[0])))
        except (TypeError, ValueError):
            pass
    try:
        return max(0.0, min(1.0, float(market.get("bestAsk", 0))))
    except (TypeError, ValueError):
        return None


def safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


TAG_CATEGORY_MAP = {
    "politics": "politics", "political": "politics", "election": "politics",
    "weather": "weather", "climate": "weather", "storm": "weather",
    "crypto": "crypto", "bitcoin": "crypto", "ethereum": "crypto",
    "sports": "sports", "nba": "sports", "nfl": "sports",
    "economy": "economic", "economic": "economic", "finance": "economic",
    "fed": "economic", "stocks": "economic",
}


def classify_category(tags: list[dict], question: str) -> str:
    for tag in tags:
        slug = str(tag.get("slug") or tag.get("label") or "").lower()
        if slug in TAG_CATEGORY_MAP:
            return TAG_CATEGORY_MAP[slug]
    lowered = question.lower()
    keywords = {
        "weather": ("temperature", "snow", "rain", "storm", "hurricane"),
        "politics": ("election", "president", "senate", "congress", "tariff"),
        "crypto": ("bitcoin", "btc", "ethereum", "eth", "crypto"),
        "sports": ("super bowl", "nba", "nfl", "mlb", "nhl"),
        "economic": ("cpi", "inflation", "fed", "gdp", "earnings"),
    }
    for cat, kws in keywords.items():
        if any(kw in lowered for kw in kws):
            return cat
    return "other"


def iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def collect_cycle(conn: sqlite3.Connection) -> dict:
    """Run one collection cycle. Returns summary stats."""
    now = utc_now()
    now_iso = now.isoformat()

    log("Pulling Gamma events...")
    events = fetch_json(GAMMA_EVENTS_URL)
    if not isinstance(events, list):
        events = []

    # Flatten markets from events
    markets = []
    for event in events:
        tags = list(event.get("tags") or [])
        for market in event.get("markets") or []:
            if bool(market.get("closed")):
                continue
            end_dt = iso_to_dt(str(market.get("endDate") or market.get("endDateIso") or ""))
            yes_price = parse_yes_price(market)
            category = classify_category(tags, str(market.get("question") or event.get("title") or ""))
            liquidity = safe_float(market.get("liquidity") or market.get("liquidityClob"))
            volume = safe_float(market.get("volume") or market.get("volumeClob"))
            resolution_hours = (
                (end_dt - now).total_seconds() / 3600.0 if end_dt else None
            )

            # Compute spread from best bid/ask if available
            best_bid = safe_float(market.get("bestBid"))
            best_ask = safe_float(market.get("bestAsk"))
            spread = round(best_ask - best_bid, 4) if best_ask > 0 and best_bid > 0 else None

            markets.append({
                "condition_id": str(market.get("conditionId") or market.get("id") or ""),
                "question": str(market.get("question") or event.get("title") or "")[:200],
                "category": category,
                "yes_price": yes_price,
                "liquidity": liquidity,
                "volume": volume,
                "resolution_hours": resolution_hours,
                "spread": spread,
            })

    # Compute stats
    under_24h = [m for m in markets if m["resolution_hours"] and 0 < m["resolution_hours"] <= 24]
    under_48h = [m for m in markets if m["resolution_hours"] and 0 < m["resolution_hours"] <= 48]
    in_price_window = [
        m for m in markets
        if m["yes_price"] is not None and 0.10 <= m["yes_price"] <= 0.90
    ]
    avg_liq = sum(m["liquidity"] for m in markets if m["liquidity"]) / max(len(markets), 1)
    avg_vol = sum(m["volume"] for m in markets if m["volume"]) / max(len(markets), 1)

    # Category breakdown
    cat_counts: dict[str, int] = {}
    for m in markets:
        cat_counts[m["category"]] = cat_counts.get(m["category"], 0) + 1

    # Top 20 most liquid markets in price window (any resolution time)
    # When short-dated markets are scarce, we still collect data from the
    # most liquid markets for calibration and spread tracking.
    candidates = [
        m for m in markets
        if m["yes_price"] is not None and 0.10 <= m["yes_price"] <= 0.90
    ]
    candidates.sort(key=lambda m: m["liquidity"] or 0, reverse=True)
    top_markets = candidates[:20]

    # Also track short-dated candidates separately
    short_candidates = [
        m for m in under_48h
        if m["yes_price"] is not None and 0.10 <= m["yes_price"] <= 0.90
    ]
    short_candidates.sort(key=lambda m: m["liquidity"] or 0, reverse=True)

    # Store snapshot
    conn.execute(
        """INSERT INTO snapshots
           (collected_at, total_events, total_markets, markets_under_24h,
            markets_under_48h, markets_in_price_window, avg_liquidity,
            avg_volume, category_counts, top_markets)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            now_iso, len(events), len(markets), len(under_24h),
            len(under_48h), len(in_price_window), round(avg_liq, 2),
            round(avg_vol, 2), json.dumps(cat_counts),
            json.dumps([{
                "question": m["question"][:100],
                "category": m["category"],
                "yes_price": m["yes_price"],
                "liquidity": m["liquidity"],
                "resolution_hours": round(m["resolution_hours"], 1) if m["resolution_hours"] else None,
                "spread": m["spread"],
            } for m in top_markets]),
        ),
    )

    # Store individual market prices for time-series analysis
    for m in candidates[:50]:  # Top 50 most liquid markets
        conn.execute(
            """INSERT INTO market_prices
               (collected_at, condition_id, question, category,
                yes_price, liquidity, volume, resolution_hours, spread)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_iso, m["condition_id"], m["question"], m["category"],
                m["yes_price"], m["liquidity"], m["volume"],
                round(m["resolution_hours"], 4) if m["resolution_hours"] else None,
                m["spread"],
            ),
        )

    conn.commit()

    summary = {
        "collected_at": now_iso,
        "events": len(events),
        "markets": len(markets),
        "under_24h": len(under_24h),
        "under_48h": len(under_48h),
        "in_price_window": len(in_price_window),
        "candidates_tracked": min(len(candidates), 50),
        "short_candidates": len(short_candidates),
        "avg_liquidity": round(avg_liq, 2),
        "avg_volume": round(avg_vol, 2),
        "categories": cat_counts,
        "top_3": [
            {"q": m["question"][:80], "price": m["yes_price"], "liq": m["liquidity"]}
            for m in top_markets[:3]
        ],
    }

    # Write latest snapshot for quick reads
    LATEST_PATH.write_text(json.dumps(summary, indent=2))

    log(
        f"Collected: {len(events)} events, {len(markets)} markets, "
        f"{len(under_24h)} <24h, {len(short_candidates)} short candidates, "
        f"{min(len(candidates), 50)} price-tracked"
    )
    return summary


def print_summary(conn: sqlite3.Connection) -> None:
    """Print stats from the shadow database."""
    row = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()
    snap_count = row[0] if row else 0

    row = conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()
    price_count = row[0] if row else 0

    row = conn.execute("SELECT MIN(collected_at), MAX(collected_at) FROM snapshots").fetchone()
    first, last = (row[0], row[1]) if row else ("n/a", "n/a")

    row = conn.execute("SELECT COUNT(DISTINCT condition_id) FROM market_prices").fetchone()
    unique_markets = row[0] if row else 0

    print(f"\n{'='*50}")
    print(f"  Shadow Collector Database: {DB_PATH}")
    print(f"{'='*50}")
    print(f"  Snapshots collected:  {snap_count}")
    print(f"  Price data points:    {price_count}")
    print(f"  Unique markets:       {unique_markets}")
    print(f"  First collection:     {first}")
    print(f"  Latest collection:    {last}")

    if snap_count > 0:
        row = conn.execute(
            "SELECT total_markets, markets_under_24h, markets_under_48h, "
            "markets_in_price_window, avg_liquidity FROM snapshots ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
        if row:
            print(f"\n  Latest snapshot:")
            print(f"    Total markets:      {row[0]}")
            print(f"    Under 24h:          {row[1]}")
            print(f"    Under 48h:          {row[2]}")
            print(f"    In price window:    {row[3]}")
            print(f"    Avg liquidity:      ${row[4]:,.2f}")
    print(f"{'='*50}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Elastifund shadow data collector")
    parser.add_argument("--loop", action="store_true", help="Run continuously (30-min interval)")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Loop interval in seconds")
    parser.add_argument("--summary", action="store_true", help="Print database summary")
    args = parser.parse_args()

    conn = init_db()

    if args.summary:
        print_summary(conn)
        return

    if args.loop:
        log(f"Starting continuous collection (interval={args.interval}s)")
        while True:
            try:
                collect_cycle(conn)
            except Exception as exc:
                log(f"Cycle error: {exc}")
            time.sleep(args.interval)
    else:
        collect_cycle(conn)

    conn.close()


if __name__ == "__main__":
    main()
