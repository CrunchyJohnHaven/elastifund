import asyncio
import unittest
from unittest.mock import patch

import bot.jj_live as jj_live_module
from bot.jj_live import JJLive


class _DummyState:
    def __init__(self):
        self.state = {"open_positions": {}}
        self.recorded = []

    def count_active_linked_baskets(self):
        return 0

    def check_exposure_limit(self):
        return True

    def has_position(self, market_id: str):
        return market_id in self.state["open_positions"]

    def record_trade(self, **kwargs):
        self.state["open_positions"][kwargs["market_id"]] = kwargs
        self.recorded.append(kwargs)


class _DummyDB:
    def __init__(self):
        self.trades = []

    def log_trade(self, payload):
        self.trades.append(payload)
        return f"trade-{len(self.trades)}"


class _DummyMultiSim:
    def simulate_trade(self, signal, trade_id):
        return None


class _DummyNotifier:
    async def send_message(self, *_args, **_kwargs):
        return True


class _DummyFillTracker:
    def __init__(self):
        self.orders = []

    def record_order(self, **kwargs):
        self.orders.append(kwargs)


class _CaptureOrderArgs:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _CaptureOrderType:
    GTC = "GTC"


class _CaptureClob:
    def __init__(self):
        self.orders = []

    def create_order(self, order_args):
        self.orders.append(order_args.kwargs)
        return {"signed": True, "order": order_args.kwargs}

    def post_order(self, signed_order, *_args, **_kwargs):
        return {"orderID": f"live-{len(self.orders)}"}


class TestJJLiveSumViolationExecution(unittest.TestCase):
    def test_execute_sum_violation_signals_paper_mode(self) -> None:
        live = JJLive.__new__(JJLive)
        live.paper_mode = True
        live.allow_order_submission = True
        live.clob = None
        live.state = _DummyState()
        live.db = _DummyDB()
        live.multi_sim = _DummyMultiSim()
        live.notifier = _DummyNotifier()
        live.fill_tracker = _DummyFillTracker()
        live.fill_tracker = _DummyFillTracker()

        signal = {
            "signal_id": "sumv-1",
            "violation_id": "sumv-1",
            "question": "Who wins the election?",
            "trade_side": "buy_yes_basket",
            "details": {"violation_amount": 0.08},
            "edge": 0.08,
            "confidence": 0.95,
            "source": "sum_violation",
            "strategy_type": "combinatorial",
            "relation_type": "same_event_sum",
            "sum_violation_legs": [
                {
                    "market_id": "m1",
                    "outcome": "Alice",
                    "category": "politics",
                    "quote_side": "YES",
                    "token_id": "m1-yes",
                    "limit_price": 0.30,
                    "position_size_usd": 0.50,
                },
                {
                    "market_id": "m2",
                    "outcome": "Bob",
                    "category": "politics",
                    "quote_side": "YES",
                    "token_id": "m2-yes",
                    "limit_price": 0.31,
                    "position_size_usd": 0.50,
                },
                {
                    "market_id": "m3",
                    "outcome": "Carol",
                    "category": "politics",
                    "quote_side": "YES",
                    "token_id": "m3-yes",
                    "limit_price": 0.31,
                    "position_size_usd": 0.50,
                },
            ],
        }

        with patch.object(jj_live_module, "MAX_OPEN_POSITIONS", 10):
            orders_placed, action_map = asyncio.run(live._execute_sum_violation_signals([signal]))

        self.assertEqual(orders_placed, 3)
        self.assertEqual(action_map["sumv-1"], "traded")
        self.assertEqual(len(live.db.trades), 3)
        self.assertEqual(len(live.state.recorded), 3)

    def test_execute_sum_violation_signals_live_bumps_to_exchange_minimum(self) -> None:
        live = JJLive.__new__(JJLive)
        live.paper_mode = False
        live.allow_order_submission = True
        live.clob = _CaptureClob()
        live.state = _DummyState()
        live.db = _DummyDB()
        live.multi_sim = _DummyMultiSim()
        live.notifier = _DummyNotifier()
        live.fill_tracker = _DummyFillTracker()

        signal = {
            "signal_id": "sumv-1",
            "violation_id": "sumv-1",
            "question": "Who wins the election?",
            "trade_side": "buy_yes_basket",
            "details": {"violation_amount": 0.08},
            "edge": 0.08,
            "confidence": 0.95,
            "source": "sum_violation",
            "strategy_type": "combinatorial",
            "relation_type": "same_event_sum",
            "sum_violation_legs": [
                {
                    "market_id": "m1",
                    "outcome": "Alice",
                    "category": "politics",
                    "quote_side": "YES",
                    "token_id": "m1-yes",
                    "limit_price": 0.30,
                    "position_size_usd": 0.50,
                },
                {
                    "market_id": "m2",
                    "outcome": "Bob",
                    "category": "politics",
                    "quote_side": "YES",
                    "token_id": "m2-yes",
                    "limit_price": 0.31,
                    "position_size_usd": 0.50,
                },
                {
                    "market_id": "m3",
                    "outcome": "Carol",
                    "category": "politics",
                    "quote_side": "YES",
                    "token_id": "m3-yes",
                    "limit_price": 0.31,
                    "position_size_usd": 0.50,
                },
            ],
        }

        with (
            patch.object(jj_live_module, "OrderArgs", _CaptureOrderArgs),
            patch.object(jj_live_module, "OrderType", _CaptureOrderType),
            patch.object(jj_live_module, "BUY", "BUY"),
            patch.object(jj_live_module, "MAX_OPEN_POSITIONS", 10),
        ):
            orders_placed, action_map = asyncio.run(live._execute_sum_violation_signals([signal]))

        self.assertEqual(orders_placed, 3)
        self.assertEqual(action_map["sumv-1"], "traded")
        self.assertEqual([order["size"] for order in live.clob.orders], [16.67, 16.13, 16.13])
        self.assertEqual(len(live.db.trades), 0)
        self.assertEqual(len(live.state.recorded), 0)
        self.assertEqual(len(live.fill_tracker.orders), 3)
        self.assertEqual(
            [order["order_id"] for order in live.fill_tracker.orders],
            ["live-1", "live-2", "live-3"],
        )
        first_metadata = live.fill_tracker.orders[0]["metadata"]
        self.assertIn("trade_record", first_metadata)
        self.assertIn("signal_context", first_metadata)


if __name__ == "__main__":
    unittest.main()
