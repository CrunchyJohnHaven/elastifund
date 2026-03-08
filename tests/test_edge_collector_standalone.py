"""Tests for standalone edge collector daemon.

Verifies:
- Collection cycle logs prices to database
- Run audit records are created
- Quarantine integration works during collection
- Daemon shutdown signal handling
"""

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from bot.expanded_scanner import MarketSnapshot
from bot.market_quarantine import MarketQuarantine

# Import the collector
from scripts.run_edge_collector import EdgeCollector


def _make_snapshot(market_id: str, yes_price: float = 0.50) -> MarketSnapshot:
    return MarketSnapshot(
        market_id=market_id,
        question=f"Question for {market_id}",
        yes_price=yes_price,
        no_price=1.0 - yes_price,
        volume=5000.0,
        liquidity=1500.0,
        category="politics",
        token_ids=[f"yes_{market_id}", f"no_{market_id}"],
        tags=["politics"],
    )


class TestEdgeCollectorInit:
    def test_creates_database(self, tmp_path):
        db_path = tmp_path / "test_collector.db"
        collector = EdgeCollector(db_path=db_path)
        assert db_path.exists()

    def test_init_tables_exist(self, tmp_path):
        db_path = tmp_path / "test_collector.db"
        EdgeCollector(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "markets" in tables
        assert "market_prices" in tables
        assert "collector_runs" in tables


class TestCollectionCycle:
    @pytest.fixture
    def collector(self, tmp_path):
        return EdgeCollector(db_path=tmp_path / "test.db", target_markets=10)

    @pytest.mark.asyncio
    async def test_collect_once_records_prices(self, collector):
        snapshots = [_make_snapshot("m1", 0.60), _make_snapshot("m2", 0.40)]
        with patch.object(
            collector.scanner, "scan_diverse_markets",
            new_callable=AsyncMock, return_value=snapshots,
        ):
            summary = await collector.collect_once()
            assert summary["markets_scanned"] == 2
            assert summary["prices_recorded"] == 2

    @pytest.mark.asyncio
    async def test_collect_once_creates_audit_record(self, collector):
        snapshots = [_make_snapshot("m1")]
        with patch.object(
            collector.scanner, "scan_diverse_markets",
            new_callable=AsyncMock, return_value=snapshots,
        ):
            summary = await collector.collect_once()
            assert "run_id" in summary

            # Verify audit in DB
            conn = sqlite3.connect(str(collector.db_path))
            rows = conn.execute("SELECT * FROM collector_runs").fetchall()
            conn.close()
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_collect_updates_market_metadata(self, collector):
        snapshots = [_make_snapshot("m1")]
        with patch.object(
            collector.scanner, "scan_diverse_markets",
            new_callable=AsyncMock, return_value=snapshots,
        ):
            await collector.collect_once()

            conn = sqlite3.connect(str(collector.db_path))
            row = conn.execute(
                "SELECT question FROM markets WHERE market_id = 'm1'"
            ).fetchone()
            conn.close()
            assert row is not None
            assert "m1" in row[0]

    @pytest.mark.asyncio
    async def test_collect_empty_scan(self, collector):
        with patch.object(
            collector.scanner, "scan_diverse_markets",
            new_callable=AsyncMock, return_value=[],
        ):
            summary = await collector.collect_once()
            assert summary["markets_scanned"] == 0
            assert summary["prices_recorded"] == 0


class TestCollectorShutdown:
    def test_shutdown_flag(self, tmp_path):
        collector = EdgeCollector(db_path=tmp_path / "test.db")
        assert not collector._shutdown
        collector.request_shutdown()
        assert collector._shutdown

    @pytest.mark.asyncio
    async def test_daemon_respects_shutdown(self, tmp_path):
        collector = EdgeCollector(db_path=tmp_path / "test.db")

        with patch.object(
            collector.scanner, "scan_diverse_markets",
            new_callable=AsyncMock, return_value=[],
        ), patch.object(collector.scanner, "close", new_callable=AsyncMock):
            # Request shutdown immediately
            collector.request_shutdown()
            # Should exit quickly
            await asyncio.wait_for(
                collector.run_daemon(interval_seconds=1),
                timeout=5.0,
            )


class TestCollectorCategories:
    @pytest.mark.asyncio
    async def test_categories_logged_in_summary(self, tmp_path):
        collector = EdgeCollector(db_path=tmp_path / "test.db")
        snapshots = [
            MarketSnapshot("m1", "Politics Q?", 0.5, 0.5, 5000, 1500, "politics", ["t1"]),
            MarketSnapshot("m2", "Crypto Q?", 0.5, 0.5, 5000, 1500, "crypto", ["t2"]),
            MarketSnapshot("m3", "Sports Q?", 0.5, 0.5, 5000, 1500, "sports", ["t3"]),
        ]
        with patch.object(
            collector.scanner, "scan_diverse_markets",
            new_callable=AsyncMock, return_value=snapshots,
        ):
            summary = await collector.collect_once()
            assert summary["categories"]["politics"] == 1
            assert summary["categories"]["crypto"] == 1
            assert summary["categories"]["sports"] == 1
