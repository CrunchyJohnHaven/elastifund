#!/usr/bin/env python3
"""Minimal smoke test: Gamma scan → analyzer (no trade) → metrics write → exit 0.

Validates that the core pipeline components can initialize and run
without errors. Does NOT place any trades or require API keys.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure we can import from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///bot.db")

import structlog

logger = structlog.get_logger("smoke_test")

RESULTS = {}


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS[name] = {"passed": passed, "detail": detail}
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


async def test_gamma_scan() -> list:
    """Step 1: Fetch markets from Gamma API."""
    from src.scanner import MarketScanner

    scanner = MarketScanner(timeout=15.0)
    try:
        markets = await scanner.fetch_active_markets(limit=10)
        await scanner.close()
        record("gamma_scan", len(markets) > 0, f"{len(markets)} markets fetched")
        return markets
    except Exception as e:
        record("gamma_scan", False, str(e))
        return []


async def test_analyzer(markets: list) -> dict:
    """Step 2: Run Claude analyzer on one market (no trade).

    Without an API key, analyzer returns a safe 'hold' result — this is expected
    and still validates the analysis pipeline code path.
    """
    from src.claude_analyzer import ClaudeAnalyzer, classify_market_category

    analyzer = ClaudeAnalyzer()  # No API key = dry-run mode

    if not markets:
        record("analyzer", False, "No markets to analyze")
        return {}

    # Pick first market with a question
    market = markets[0]
    question = market.get("question", "Test question")

    # Extract price
    from src.scanner import MarketScanner
    prices = MarketScanner.extract_prices(market)
    current_price = prices.get("YES", 0.5)

    # Classify category (exercises category routing)
    category = classify_market_category(question)

    # Run analysis (will return hold without API key, but exercises full code path)
    result = await analyzer.analyze_market(
        question=question,
        current_price=current_price,
    )

    record(
        "analyzer",
        result.get("direction") in ("hold", "buy_yes", "buy_no"),
        f"direction={result.get('direction')}, category={category}, "
        f"raw_prob={result.get('probability', 0):.2f}",
    )
    return result


async def test_db_write() -> None:
    """Step 3: Write and read from SQLite to validate DB pipeline."""
    from src.store.database import DatabaseManager
    from src.store.repository import Repository

    await DatabaseManager.init_db()

    async with DatabaseManager.get_session() as session:
        # Create a bot state entry
        bot_state = await Repository.get_or_create_bot_state(session)
        bot_state.last_heartbeat = datetime.now(timezone.utc)
        await session.commit()

        # Read it back
        bot_state2 = await Repository.get_or_create_bot_state(session)
        has_heartbeat = bot_state2.last_heartbeat is not None
        record("db_write_read", has_heartbeat, f"heartbeat={bot_state2.last_heartbeat}")

    await DatabaseManager.close()


async def test_metrics_write() -> None:
    """Step 4: Write one metrics entry to validate JSON output."""
    metrics_file = Path(__file__).resolve().parent.parent / "smoke_metrics.json"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test": "smoke_test",
        "markets_scanned": RESULTS.get("gamma_scan", {}).get("detail", "0"),
        "analyzer_result": RESULTS.get("analyzer", {}).get("detail", "n/a"),
        "db_ok": RESULTS.get("db_write_read", {}).get("passed", False),
    }

    metrics_file.write_text(json.dumps(entry, indent=2))
    record("metrics_write", metrics_file.exists(), f"wrote {metrics_file.name}")


async def main() -> int:
    print("=" * 60)
    print("POLYMARKET BOT — SMOKE TEST")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # Step 1: Gamma scan
    print("\n[1/4] Gamma API scan...")
    markets = await test_gamma_scan()

    # Step 2: Analyzer (no trade)
    print("\n[2/4] Claude analyzer (dry-run, no API key)...")
    await test_analyzer(markets)

    # Step 3: DB write/read
    print("\n[3/4] SQLite DB write/read...")
    await test_db_write()

    # Step 4: Metrics write
    print("\n[4/4] Metrics JSON write...")
    await test_metrics_write()

    # Summary
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS.values() if r["passed"])
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
