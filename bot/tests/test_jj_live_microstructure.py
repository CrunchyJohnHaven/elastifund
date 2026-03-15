#!/usr/bin/env python3
"""Focused integration tests for jj_live microstructure wiring."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.jj_live import JJLive


class FakeTradeStream:
    def get_microstructure(self, token_id: str):
        snapshots = {
            "yes-token": {
                "token_id": "yes-token",
                "vpin": 0.82,
                "regime": "toxic",
                "ofi": -2.4,
                "ofi_skew": 0.71,
                "connection_mode": "websocket",
                "fallback_active": False,
                "latency_p99_ms": 18.5,
            },
            "no-token": {
                "token_id": "no-token",
                "vpin": 0.44,
                "regime": "neutral",
                "ofi": 0.8,
                "ofi_skew": 0.53,
                "connection_mode": "websocket",
                "fallback_active": False,
                "latency_p99_ms": 18.5,
            },
        }
        return snapshots.get(token_id)

    def get_status(self):
        return {
            "connection_mode": "websocket",
            "fallback_active": False,
            "latency": {"processing_p99_ms": 18.5},
        }


def test_attach_microstructure_context_logs_vpin_and_ofi(caplog):
    live = JJLive.__new__(JJLive)
    live.trade_stream = FakeTradeStream()

    signal = {
        "market_id": "market-1",
        "question": "Will the test market resolve yes?",
        "estimated_prob": 0.63,
    }
    market_lookup = {"market-1": {"token_ids": ["yes-token", "no-token"]}}

    with caplog.at_level(logging.INFO, logger="JJ"):
        updated = live._attach_microstructure_context(signal, market_lookup)

    assert updated["vpin"] == 0.82
    assert updated["flow_regime"] == "toxic"
    assert updated["ofi"] == -2.4
    assert updated["ofi_skew"] == 0.71
    assert updated["microstructure_mode"] == "websocket"
    assert updated["ws_latency_p99_ms"] == 18.5
    assert "vpin=0.820" in caplog.text
    assert "ofi=-2.400" in caplog.text
