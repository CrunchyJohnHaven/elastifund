from __future__ import annotations

import json
from pathlib import Path

import pytest

import bot.jj_live as jj_live_module
from bot.jj_live import JJLive, JJState, TradeDatabase, build_trade_record
from scripts.signal_attribution_report import (
    build_signal_attribution_report,
    write_signal_attribution_report,
)


def test_build_trade_record_includes_signal_sources_and_metadata():
    record = build_trade_record(
        {
            "question": "Will BTC close above $100k?",
            "direction": "buy_yes",
            "estimated_prob": 0.61,
            "raw_prob": 0.72,
            "calibrated_prob": 0.61,
            "edge": 0.11,
            "confidence": 0.82,
            "source": "llm",
            "source_components": ["llm", "wallet_flow"],
            "source_combo": "llm+wallet_flow",
            "n_sources": 2,
        },
        market_id="m1",
        category="crypto",
        entry_price=0.50,
        position_size_usd=5.0,
        token_id="token-1",
    )

    assert record["signal_sources"] == ["llm", "wallet_flow"]
    assert record["signal_metadata"] == {
        "llm_prob": 0.61,
        "llm_raw_prob": 0.72,
        "wallet_consensus": 0.82,
    }


def test_jj_state_persists_signal_sources_and_metadata(tmp_path: Path):
    state = JJState(state_file=tmp_path / "jj_state.json")

    state.record_trade(
        market_id="m1",
        question="Will BTC close above $100k?",
        direction="buy_yes",
        price=0.50,
        size_usd=5.0,
        edge=0.11,
        confidence=0.82,
        order_id="paper-123",
        source="llm",
        source_combo="llm+wallet_flow",
        source_components=["llm", "wallet_flow"],
        source_count=2,
        signal_sources=["llm", "wallet_flow"],
        signal_metadata={"llm_prob": 0.61, "wallet_consensus": 0.82},
    )

    saved = json.loads((tmp_path / "jj_state.json").read_text())
    open_position = saved["open_positions"]["m1"]
    trade_entry = saved["trade_log"][-1]

    assert open_position["signal_sources"] == ["llm", "wallet_flow"]
    assert open_position["signal_metadata"] == {"llm_prob": 0.61, "wallet_consensus": 0.82}
    assert trade_entry["signal_sources"] == ["llm", "wallet_flow"]
    assert trade_entry["signal_metadata"] == {"llm_prob": 0.61, "wallet_consensus": 0.82}


def test_signal_attribution_report_groups_by_component_source(tmp_path: Path):
    db_path = tmp_path / "jj_trades.db"
    state_path = tmp_path / "jj_state.json"
    output_path = tmp_path / "reports" / "signal_attribution.json"

    db = TradeDatabase(db_path=db_path)
    confirmed_id = db.log_trade(
        {
            "market_id": "m-confirmed",
            "question": "Confirmed trade",
            "direction": "buy_yes",
            "entry_price": 0.42,
            "edge": 0.12,
            "confidence": 0.81,
            "position_size_usd": 5.0,
            "source": "llm",
            "source_combo": "llm+wallet_flow",
            "source_components": ["llm", "wallet_flow"],
            "source_count": 2,
        }
    )
    llm_only_id = db.log_trade(
        {
            "market_id": "m-llm",
            "question": "LLM trade",
            "direction": "buy_no",
            "entry_price": 0.58,
            "edge": 0.08,
            "confidence": 0.67,
            "position_size_usd": 5.0,
            "source": "llm",
            "source_combo": "llm",
            "source_components": ["llm"],
            "source_count": 1,
        }
    )

    db.conn.execute(
        "UPDATE trades SET outcome = 'won', pnl = 0.25 WHERE id = ?",
        (confirmed_id,),
    )
    db.conn.execute(
        "UPDATE trades SET outcome = 'lost', pnl = -0.10 WHERE id = ?",
        (llm_only_id,),
    )
    db.conn.commit()
    db.close()

    state_path.write_text(
        json.dumps(
            {
                "open_positions": {},
                "trade_log": [
                    {
                        "market_id": "m-confirmed",
                        "question": "Confirmed trade",
                        "direction": "buy_yes",
                        "price": 0.42,
                        "size_usd": 5.0,
                        "edge": 0.12,
                        "source": "llm",
                        "source_combo": "llm+wallet_flow",
                        "source_components": ["llm", "wallet_flow"],
                        "source_count": 2,
                        "signal_sources": ["llm", "wallet_flow"],
                        "signal_metadata": {"llm_prob": 0.61, "wallet_consensus": 0.82},
                        "timestamp": "2026-03-09T00:00:00+00:00",
                    }
                ],
            }
        )
    )

    payload = build_signal_attribution_report(db_path=db_path, state_path=state_path)
    written = write_signal_attribution_report(payload, output_path=output_path)

    assert written == output_path
    assert output_path.exists()
    assert payload["trade_totals"]["unique_trade_count"] == 2
    assert payload["state_snapshot"]["trade_log_has_signal_sources"] is True
    assert payload["state_snapshot"]["trade_log_has_signal_metadata"] is True
    assert payload["by_source"]["llm"]["trade_count"] == 2
    assert payload["by_source"]["llm"]["wins"] == 1
    assert payload["by_source"]["llm"]["losses"] == 1
    assert payload["by_source"]["llm"]["total_pnl"] == 0.15
    assert payload["by_source"]["wallet_flow"]["trade_count"] == 1
    assert payload["by_source"]["wallet_flow"]["wins"] == 1
    assert payload["by_source"]["wallet_flow"]["total_pnl"] == 0.25


@pytest.mark.asyncio
async def test_collect_cross_platform_arb_signals_prefers_async_helper(monkeypatch):
    live = JJLive.__new__(JJLive)
    live.arb_available = True
    live._has_cross_platform_credentials = lambda: True

    calls = {"async": 0}

    async def fake_async_signals():
        calls["async"] += 1
        return [
            {
                "market_id": "123",
                "question": "Arb market",
                "direction": "buy_yes",
                "edge": 0.05,
                "confidence": 0.91,
                "estimated_prob": 0.55,
                "market_price": 0.50,
                "category": "arbitrage",
                "resolution_hours": 1.0,
                "velocity_score": 12.0,
            }
        ]

    def fail_sync_signals():
        raise AssertionError("sync arb helper should not be used inside run_cycle")

    monkeypatch.setattr(jj_live_module, "arb_get_signals_async", fake_async_signals)
    monkeypatch.setattr(jj_live_module, "arb_get_signals", fail_sync_signals)

    signals = await JJLive._collect_cross_platform_arb_signals(
        live,
        {
            "123": {
                "question": "Arb market",
                "category": "arbitrage",
                "yes_price": 0.50,
                "resolution_hours": 1.0,
            }
        },
    )

    assert calls["async"] == 1
    assert len(signals) == 1
    assert signals[0]["source"] == "cross_platform_arb"
    assert signals[0]["source_components"] == ["cross_platform_arb"]
