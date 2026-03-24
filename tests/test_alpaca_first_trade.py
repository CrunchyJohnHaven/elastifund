from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.alpaca_first_trade import (  # noqa: E402
    AlpacaFirstTradeConfig,
    AlpacaFirstTradeSystem,
    build_alpaca_trade_alert,
    send_alpaca_trade_alert,
)


class FakeAlpacaClient:
    def __init__(self):
        self.orders: list[dict] = []

    def get_crypto_bars(self, *, symbols: list[str], timeframe: str, limit: int) -> dict:
        symbol = symbols[0]
        rows = []
        price = 100.0
        for idx in range(220):
            open_price = price
            if idx % 20 < 12:
                price *= 1.0018
            else:
                price *= 0.9992
            hour = idx // 60
            minute = idx % 60
            rows.append({"t": f"2026-03-23T{hour:02d}:{minute:02d}:00Z", "o": open_price, "h": max(open_price, price), "l": min(open_price, price), "c": price, "v": 1000})
        for idx in range(20):
            open_price = price
            price *= 1.0022
            rows.append({"t": f"2026-03-23T04:{idx:02d}:00Z", "o": open_price, "h": max(open_price, price), "l": min(open_price, price), "c": price, "v": 1000})
        return {"bars": {symbol: rows}}

    def get_latest_crypto_orderbooks(self, *, symbols: list[str]) -> dict:
        symbol = symbols[0]
        return {"orderbooks": {symbol: {"b": [{"p": 120.0, "s": 1.0}], "a": [{"p": 120.05, "s": 1.0}]}}}

    def get_account(self) -> dict:
        return {"cash": "1000.00"}

    def list_positions(self) -> list[dict]:
        return []

    def submit_order(self, **payload) -> dict:
        self.orders.append(payload)
        return {
            "id": "order-1",
            "symbol": payload["symbol"],
            "filled_avg_price": "120.01",
            "filled_qty": "0.2083",
            "qty": payload.get("qty"),
            "notional": payload.get("notional"),
        }


def test_run_lane_writes_candidate_report(tmp_path: Path) -> None:
    config = AlpacaFirstTradeConfig(
        mode="paper",
        symbols=("BTC/USD",),
        lane_path=tmp_path / "lane.json",
        execution_path=tmp_path / "exec.json",
        execution_history_path=tmp_path / "history.jsonl",
        state_path=tmp_path / "state.json",
        foundry_output_path=tmp_path / "foundry.json",
        supervisor_output_path=tmp_path / "supervisor.json",
        alpaca_queue_path=tmp_path / "queue.jsonl",
        min_expected_edge_bps=5.0,
        max_spread_bps=10.0,
    )
    system = AlpacaFirstTradeSystem(config)
    report = system.run_lane(FakeAlpacaClient())
    assert report["status"] == "fresh"
    assert report["candidate_count"] > 0


def test_execute_from_queue_submits_paper_order(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.jsonl"
    queue_path.write_text(
        json.dumps(
            {
                "thesis_id": "alpaca:BTC/USD:btcusd_momo_1",
                "ticker": "BTC/USD",
                "symbol": "BTC/USD",
                "variant_id": "btcusd_momo_1",
                "model_probability": 0.72,
                "expected_edge_bps": 150.0,
                "recommended_notional_usd": 25.0,
                "hold_bars": 15,
                "stop_loss_bps": 70.0,
                "take_profit_bps": 150.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = AlpacaFirstTradeConfig(
        mode="paper",
        symbols=("BTC/USD",),
        execution_path=tmp_path / "exec.json",
        execution_history_path=tmp_path / "history.jsonl",
        state_path=tmp_path / "state.json",
        lane_path=tmp_path / "lane.json",
        foundry_output_path=tmp_path / "foundry.json",
        supervisor_output_path=tmp_path / "supervisor.json",
        alpaca_queue_path=queue_path,
    )
    system = AlpacaFirstTradeSystem(config)
    client = FakeAlpacaClient()

    report = system.execute_from_queue(client)

    assert report["status"] == "fresh"
    assert report["action"] == "entry"
    assert client.orders
    assert client.orders[0]["symbol"] == "BTC/USD"
    saved_state = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert saved_state["open_trade"]["symbol"] == "BTC/USD"


def test_build_alpaca_trade_alert_formats_entry() -> None:
    message = build_alpaca_trade_alert(
        {
            "execution_report": {
                "mode": "paper",
                "action": "entry",
                "symbol": "BTC/USD",
                "notional_usd": 25.0,
                "order": {
                    "id": "order-1",
                    "filled_avg_price": "120.01",
                },
                "queue_entry": {
                    "variant_id": "btcusd_momo_1",
                    "model_probability": 0.72,
                    "expected_edge_bps": 150.0,
                },
                "summary": "alpaca first-trade system entered BTC/USD",
            }
        }
    )

    assert message is not None
    assert "ALPACA ENTRY [PAPER]" in message
    assert "Prob positive: 72.0%" in message
    assert "Expected edge: 150.0 bps" in message


def test_send_alpaca_trade_alert_skips_non_trade_events() -> None:
    sent: list[str] = []

    result = send_alpaca_trade_alert(
        {
            "execution_report": {
                "mode": "paper",
                "action": "hold_open_position",
                "symbol": "BTC/USD",
            }
        },
        send_message=sent.append,
    )

    assert result is False
    assert sent == []
