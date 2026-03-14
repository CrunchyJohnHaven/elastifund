from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time

from infra.cross_asset_data_plane import (
    BinanceAdapter,
    CoinbaseAdapter,
    CrossAssetDataPlane,
    CrossAssetDataPlaneConfig,
    DeribitAdapter,
    build_market_envelope,
)


def _tmp_config(tmp: str) -> CrossAssetDataPlaneConfig:
    base = Path(tmp)
    return CrossAssetDataPlaneConfig(
        db_path=base / "state" / "cross_asset_ticks.db",
        parquet_root=base / "state" / "cross_asset_ticks_parquet",
        health_latest_path=base / "reports" / "data_plane_health" / "latest.json",
        assets=("BTC", "ETH", "SOL", "XRP", "DOGE"),
        anchor_timeframes_seconds=(60,),
        max_staleness_seconds=60,
    )


def test_binance_parse_message_normalizes_trade_to_market_envelope() -> None:
    adapter = BinanceAdapter(("BTC", "ETH", "SOL", "XRP", "DOGE"))
    payload = {
        "stream": "btcusdt@trade",
        "data": {
            "e": "trade",
            "E": 1_730_000_100_000,
            "s": "BTCUSDT",
            "t": 12345,
            "p": "65000.10",
            "q": "0.0025",
            "T": 1_730_000_099_990,
            "m": False,
        },
    }
    envelopes = adapter.parse_message(payload)
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope["schema_version"] == "market_envelope.v1"
    assert envelope["venue"] == "binance"
    assert envelope["asset"] == "BTC"
    assert envelope["symbol"] == "BTCUSDT"
    assert envelope["sequence"] == 12345
    assert envelope["price"] == 65000.10
    assert envelope["size"] == 0.0025


def test_coinbase_parse_message_handles_advanced_trade_ticker_shape() -> None:
    adapter = CoinbaseAdapter(("BTC", "ETH", "SOL", "XRP", "DOGE"))
    payload = {
        "channel": "ticker",
        "events": [
            {
                "type": "snapshot",
                "tickers": [
                    {
                        "product_id": "ETH-USD",
                        "price": "3500.5",
                        "best_bid": "3500.4",
                        "best_ask": "3500.6",
                        "sequence_num": 777,
                        "time": "2026-03-11T00:00:01.000Z",
                    }
                ],
            }
        ],
    }
    envelopes = adapter.parse_message(payload)
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope["venue"] == "coinbase"
    assert envelope["asset"] == "ETH"
    assert envelope["sequence"] == 777
    assert envelope["price"] == 3500.5
    assert envelope["bid"] == 3500.4
    assert envelope["ask"] == 3500.6


def test_deribit_parse_message_handles_subscription_shape() -> None:
    adapter = DeribitAdapter(("BTC", "ETH", "SOL", "XRP", "DOGE"))
    payload = {
        "jsonrpc": "2.0",
        "method": "subscription",
        "params": {
            "channel": "deribit_price_index.btc_usd",
            "data": {
                "price": 64999.2,
                "timestamp": 1_730_000_000_123,
                "change_id": 444,
            },
        },
    }
    envelopes = adapter.parse_message(payload)
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope["venue"] == "deribit"
    assert envelope["asset"] == "BTC"
    assert envelope["sequence"] == 444
    assert envelope["price"] == 64999.2


def test_ingest_tracks_sequence_gap_and_candle_anchor_and_health_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _tmp_config(tmp)
        plane = CrossAssetDataPlane(config=config)
        base_ts_ms = int(datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)

        envelope_1 = build_market_envelope(
            venue="binance",
            venue_stream="btcusdt@trade",
            asset="BTC",
            symbol="BTCUSDT",
            event_type="trade",
            event_ts_ms=base_ts_ms,
            sequence=100,
            price=65000.0,
            size=0.1,
        )
        envelope_2 = build_market_envelope(
            venue="binance",
            venue_stream="btcusdt@trade",
            asset="BTC",
            symbol="BTCUSDT",
            event_type="trade",
            event_ts_ms=base_ts_ms + 1000,
            sequence=102,
            price=65010.0,
            size=0.2,
        )
        assert asyncio.run(plane.ingest_envelope(envelope_1)) is True
        assert asyncio.run(plane.ingest_envelope(envelope_2)) is True

        latest_path, timestamped_path, payload = plane.write_health_report()
        assert latest_path.exists()
        assert timestamped_path.exists()
        btc_row = payload["venues"]["binance"]["assets"]["BTC"]
        assert btc_row["sequence_gap_count"] == 1
        assert btc_row["events_ingested"] == 2

        with plane._connect() as conn:
            envelope_count = conn.execute("SELECT COUNT(*) AS count FROM market_envelopes").fetchone()["count"]
            anchor_count = conn.execute("SELECT COUNT(*) AS count FROM candle_anchors").fetchone()["count"]
        assert envelope_count == 2
        assert anchor_count == 1


def test_compaction_returns_skip_when_parquet_engine_unavailable(monkeypatch) -> None:
    import infra.cross_asset_data_plane as module

    with tempfile.TemporaryDirectory() as tmp:
        config = _tmp_config(tmp)
        plane = CrossAssetDataPlane(config=config)
        current_hour_start = int(time.time()) - (int(time.time()) % 3600)
        target_hour_start = current_hour_start - 3600
        envelope = build_market_envelope(
            venue="coinbase",
            venue_stream="rest.ticker",
            asset="ETH",
            symbol="ETH-USD",
            event_type="ticker",
            event_ts_ms=(target_hour_start + 10) * 1000,
            sequence=12,
            price=3400.0,
            bid=3399.0,
            ask=3401.0,
        )
        assert asyncio.run(plane.ingest_envelope(envelope)) is True

        monkeypatch.setattr(module, "pd", None)
        result = plane.compact_completed_hours(now_ts=current_hour_start + 120)
        assert result["status"] == "skipped_no_parquet_engine"
        assert result["hours_compacted"] == 0


def test_health_payload_marks_polymarket_followers_no_data_cleanly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _tmp_config(tmp)
        plane = CrossAssetDataPlane(config=config)
        envelope = build_market_envelope(
            venue="polymarket",
            venue_stream="rest.gamma_clob",
            asset="BTC",
            symbol="btc-5m-condition",
            event_type="market_quote",
            price=0.51,
            bid=0.5,
            ask=0.52,
        )
        assert asyncio.run(plane.ingest_envelope(envelope)) is True

        payload = plane.build_health_payload()
        overall = payload["overall"]
        assert overall["has_polymarket_altcoin_data"] is False
        assert overall["fresh_polymarket_assets"] == ["BTC"]
        assert overall["best_venue_by_asset"]["BTC"] == "polymarket"
        assert overall["best_venue_by_asset"]["ETH"] is None


def test_health_payload_freshness_marks_stale_asset_from_old_event_time() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        config = CrossAssetDataPlaneConfig(
            db_path=base / "state" / "cross_asset_ticks.db",
            parquet_root=base / "state" / "cross_asset_ticks_parquet",
            health_latest_path=base / "reports" / "data_plane_health" / "latest.json",
            assets=("BTC",),
            anchor_timeframes_seconds=(60,),
            max_staleness_seconds=5,
        )
        plane = CrossAssetDataPlane(config=config)
        old_event_ts_ms = int((time.time() - 120) * 1000)
        envelope = build_market_envelope(
            venue="binance",
            venue_stream="btcusdt@trade",
            asset="BTC",
            symbol="BTCUSDT",
            event_type="trade",
            event_ts_ms=old_event_ts_ms,
            sequence=22,
            price=63000.0,
            size=0.1,
        )
        assert asyncio.run(plane.ingest_envelope(envelope)) is True

        payload = plane.build_health_payload()
        btc_row = payload["venues"]["binance"]["assets"]["BTC"]
        assert btc_row["freshness_status"] == "stale"
        assert "BTC" in payload["overall"]["stale_assets"]
        assert payload["overall"]["fresh_asset_coverage_ratio"] == 0.0
