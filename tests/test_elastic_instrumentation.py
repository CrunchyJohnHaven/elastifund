from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

from bot import elastic_client
from bot import jj_live as jj_live_module
from bot.jj_live import JJLive
from bot import kill_rules
from bot.lead_lag_engine import LeadLagEngine, PairDirection
from bot.ws_trade_stream import OrderBookLevel, OrderBookState, TradeStreamManager


async def _noop_async(*args, **kwargs):
    return None


def test_record_live_fill_indexes_trade(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(elastic_client, "index_trade", lambda payload: captured.append(payload) or True)

    engine = JJLive.__new__(JJLive)
    engine.db = SimpleNamespace(log_trade=lambda trade: "trade-123")
    engine.fill_tracker = SimpleNamespace(
        attach_trade_id=lambda order_id, trade_id: None,
        format_fill_rate_line=lambda hours=24: "fill-rate",
    )
    engine.multi_sim = SimpleNamespace(simulate_trade=lambda signal, trade_id: None)
    engine.state = SimpleNamespace(record_trade=lambda **kwargs: None)
    engine.notifier = SimpleNamespace(send_message=_noop_async)

    fill_event = SimpleNamespace(
        metadata={
            "trade_record": {
                "question": "Will X happen?",
                "direction": "buy_yes",
                "edge": 0.12,
                "confidence": 0.81,
                "source": "llm",
            },
            "signal_context": {"edge": 0.12, "market_price": 0.45, "direction": "buy_yes"},
        },
        market_id="market-1",
        question="Will X happen?",
        direction="buy_yes",
        fill_price=0.45,
        fill_size=10.0,
        fill_size_usd=4.5,
        category="politics",
        token_id="token-1",
        order_id="order-1",
        order_price=0.45,
        latency_seconds=1.25,
    )

    asyncio.run(JJLive._record_live_fill(engine, fill_event))

    assert len(captured) == 1
    payload = captured[0]
    assert payload["market_id"] == "market-1"
    assert payload["execution_stage"] == "fill_detected"
    assert payload["fill_status"] == "filled"
    assert payload["trade_id"] == "trade-123"


def test_signal_events_can_be_emitted_for_all_requested_sources():
    captured: list[dict] = []

    engine = JJLive.__new__(JJLive)
    engine._safe_elastic_call = lambda method_name, payload: captured.append(payload)

    for source in ("llm", "debate", "vpin", "ofi", "leadlag", "ensemble"):
        JJLive._record_signal_evaluation(
            engine,
            signal_source=source,
            market_id="market-1",
            signal_value=0.42,
            confidence=0.73,
            acted_on=source != "debate",
            reason_skipped="debate_data_unavailable" if source == "debate" else None,
        )

    assert {payload["signal_source"] for payload in captured} == {
        "llm",
        "debate",
        "vpin",
        "ofi",
        "leadlag",
        "ensemble",
    }


def test_ws_trade_stream_emits_vpin_and_ofi_signals(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(elastic_client, "index_signal", lambda payload: captured.append(payload) or True)

    manager = TradeStreamManager(token_ids=["token-1"])

    initial_book = {
        "event_type": "book",
        "asset_id": "token-1",
        "bids": [{"price": "0.49", "size": "100"}],
        "asks": [{"price": "0.51", "size": "100"}],
    }
    trade = {
        "event_type": "trade",
        "asset_id": "token-1",
        "price": "0.50",
        "size": "25",
        "side": "BUY",
        "timestamp": time.time(),
    }
    updated_book = {
        "event_type": "book",
        "asset_id": "token-1",
        "bids": [{"price": "0.49", "size": "140"}],
        "asks": [{"price": "0.51", "size": "80"}],
    }

    asyncio.run(manager._handle_message(json.dumps(initial_book)))
    asyncio.run(manager._handle_message(json.dumps(trade)))
    asyncio.run(manager._handle_message(json.dumps(updated_book)))

    sources = {payload["signal_source"] for payload in captured}
    assert "vpin" in sources
    assert "ofi" in sources
    ofi_payload = next(payload for payload in captured if payload["signal_source"] == "ofi")
    assert "raw_ofi" in ofi_payload
    assert "vpin_estimate" in ofi_payload


def test_lead_lag_scan_emits_signal_events(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(elastic_client, "index_signal", lambda payload: captured.append(payload) or True)
    monkeypatch.setattr(
        "bot.lead_lag_engine.GrangerCausalityTest.test",
        lambda self, x, y, max_lag=5: (0.01, 8.5, 1),
    )

    async def validate_pair(pair):
        pair.semantic_valid = True
        pair.semantic_confidence = 0.82
        pair.semantic_direction = PairDirection.ALIGNED
        pair.last_validated = time.time()
        pair.compute_combined_score()
        return pair

    engine = LeadLagEngine()
    engine._validator = SimpleNamespace(validate_pair=validate_pair)

    for idx in range(25):
        leader_price = 0.35 + idx * 0.01
        follower_price = 0.50
        engine.update_price("leader", float(idx), leader_price, "Leader market?")
        engine.update_price("follower", float(idx), follower_price, "Follower market?")

    asyncio.run(engine.scan_for_pairs())
    signals = engine.get_signals()

    assert signals
    assert any(payload.get("pair_selected") for payload in captured)
    assert any(payload.get("signal_source") == "leadlag" for payload in captured)
    assert any("granger_p_value" in payload for payload in captured)


def test_kill_events_emit_once_per_failure_state(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(elastic_client, "index_kill", lambda payload: captured.append(payload) or True)
    kill_rules._LAST_KILL_EVENT_STATE.clear()

    kill_rules.check_semantic_decay(0.10, threshold=0.30)
    kill_rules.check_semantic_decay(0.10, threshold=0.30)
    kill_rules.check_semantic_decay(0.35, threshold=0.30)
    kill_rules.check_semantic_decay(0.10, threshold=0.30)

    assert len(captured) == 2
    assert captured[0]["kill_rule"] == "semantic_decay"
    assert captured[0]["semantic_decay_rate"] == 0.10


def test_orderbook_snapshot_loop_runs_on_schedule(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(jj_live_module, "ELASTIC_ORDERBOOK_SNAPSHOT_INTERVAL_SECONDS", 0.001)

    engine = JJLive.__new__(JJLive)
    engine._emit_orderbook_snapshots = lambda: calls.append(time.monotonic()) or 1

    async def runner():
        task = asyncio.create_task(JJLive._orderbook_snapshot_loop(engine))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(runner())

    assert calls


def test_emit_orderbook_snapshots_indexes_current_book(monkeypatch):
    captured: list[dict] = []
    monkeypatch.setattr(elastic_client, "index_orderbook_snapshot", lambda payload: captured.append(payload) or True)

    book = OrderBookState(
        token_id="token-1",
        bids=[OrderBookLevel(0.49, 120.0), OrderBookLevel(0.48, 90.0)],
        asks=[OrderBookLevel(0.51, 95.0), OrderBookLevel(0.52, 88.0)],
        last_update=time.time(),
    )
    trade_stream = SimpleNamespace(
        token_ids=["token-1"],
        get_book=lambda token_id: book,
        get_microstructure=lambda token_id: {
            "vpin": 0.61,
            "ofi": 1.2,
            "ofi_raw": 42.0,
            "regime": "toxic",
            "connection_mode": "websocket",
        },
    )

    engine = JJLive.__new__(JJLive)
    engine.trade_stream = trade_stream
    engine._elastic_token_market_index = {"token-1": "market-1"}
    engine._safe_elastic_call = lambda method_name, payload: captured.append(payload)

    emitted = JJLive._emit_orderbook_snapshots(engine)

    assert emitted == 1
    assert captured[0]["market_id"] == "market-1"
    assert captured[0]["best_bid"] == 0.49
    assert captured[0]["best_ask"] == 0.51
