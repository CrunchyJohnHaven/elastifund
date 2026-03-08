#!/usr/bin/env python3
"""Tests for WebSocket latency monitoring and persistent storage."""

import asyncio
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.ws_trade_stream import (
    LatencyPersistence,
    TradeStreamManager,
    LATENCY_P99_ALERT_THRESHOLD_MS,
    _percentile,
)


def run(coro):
    return asyncio.run(coro)


class TestPercentile:
    def test_empty_list(self):
        assert _percentile([], 0.5) == 0.0

    def test_single_element(self):
        assert _percentile([42.0], 0.5) == 42.0

    def test_p50_two_elements(self):
        result = _percentile([10.0, 20.0], 0.5)
        # With round-half-to-even, idx=round(0.5)=0 → returns 10.0
        assert 10.0 <= result <= 20.0

    def test_p99_large_list(self):
        values = list(range(100))
        result = _percentile(values, 0.99)
        assert result >= 95.0


class TestLatencyPersistence:
    def test_creates_db_and_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_latency.db"
            persistence = LatencyPersistence(db_path=db_path)
            assert db_path.exists()

            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='latency_snapshots'"
            )
            assert cursor.fetchone() is not None
            conn.close()

    def test_record_writes_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_latency.db"
            persistence = LatencyPersistence(db_path=db_path)

            stats = {
                "exchange_p50_ms": 10.0,
                "exchange_p95_ms": 25.0,
                "exchange_p99_ms": 50.0,
                "processing_p50_ms": 1.0,
                "processing_p95_ms": 3.0,
                "processing_p99_ms": 5.0,
                "samples": 100,
            }
            persistence.record(stats, connection_mode="websocket")

            conn = sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT * FROM latency_snapshots").fetchall()
            conn.close()

            assert len(rows) == 1
            # columns: id, timestamp, source, exchange_p50, p95, p99, processing_p50, p95, p99, samples, connection_mode
            assert rows[0][2] == "ws_trade_stream"  # source
            assert rows[0][3] == 10.0  # exchange_p50
            assert rows[0][10] == "websocket"  # connection_mode

    def test_multiple_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_latency.db"
            persistence = LatencyPersistence(db_path=db_path)

            for i in range(5):
                persistence.record(
                    {"exchange_p50_ms": float(i), "samples": i + 1},
                    connection_mode="ws",
                )

            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM latency_snapshots").fetchone()[0]
            conn.close()
            assert count == 5

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "subdir" / "nested" / "latency.db"
            persistence = LatencyPersistence(db_path=db_path)
            assert db_path.parent.exists()


class TestTradeStreamLatencyIntegration:
    def test_latency_stats_populated_after_trade(self):
        manager = TradeStreamManager(token_ids=["t1"], latency_log_interval=3600)
        payload = json.dumps({
            "event_type": "trade",
            "asset_id": "t1",
            "price": "0.63",
            "size": "10",
            "side": "BUY",
            "timestamp": time.time() - 0.05,
        })
        run(manager._handle_message(payload))

        stats = manager.get_latency_stats()
        assert stats["samples"] >= 1
        assert stats["exchange_p50_ms"] >= 40.0  # ~50ms delay
        assert stats["processing_p50_ms"] >= 0.0

    def test_latency_persistence_wired_in(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "latency.db"
            manager = TradeStreamManager(
                token_ids=["t1"],
                latency_db_path=str(db_path),
                latency_log_interval=3600,
            )

            # Simulate some trades
            for i in range(5):
                run(manager._handle_message(json.dumps({
                    "event_type": "trade",
                    "asset_id": "t1",
                    "price": "0.63",
                    "size": "10",
                    "side": "BUY",
                    "timestamp": time.time() - 0.01,
                })))

            # Manually trigger persistence
            persistence = manager._ensure_latency_persistence()
            stats = manager.get_latency_stats()
            persistence.record(stats, connection_mode="test")

            conn = sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT * FROM latency_snapshots").fetchall()
            conn.close()
            assert len(rows) == 1
            assert rows[0][9] >= 5  # sample_count

    def test_latency_stats_with_no_data(self):
        manager = TradeStreamManager(latency_log_interval=3600)
        stats = manager.get_latency_stats()
        assert stats["samples"] == 0
        assert stats["exchange_p50_ms"] == 0.0

    def test_processing_latency_tracked_for_book_messages(self):
        manager = TradeStreamManager(token_ids=["t1"], latency_log_interval=3600)
        run(manager._handle_message(json.dumps({
            "event_type": "book",
            "asset_id": "t1",
            "bids": [{"price": "0.50", "size": "100"}],
            "asks": [{"price": "0.52", "size": "100"}],
        })))
        stats = manager.get_latency_stats()
        assert stats["processing_p50_ms"] >= 0.0
