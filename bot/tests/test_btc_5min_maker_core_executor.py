#!/usr/bin/env python3
"""Targeted executor regression tests for bot/btc_5min_maker_core.py."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bot.btc_5min_maker_core import CLOBExecutor, MakerConfig  # noqa: E402


def _install_fake_clob_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    py_clob_root = types.ModuleType("py_clob_client")
    clob_types = types.ModuleType("py_clob_client.clob_types")
    order_builder = types.ModuleType("py_clob_client.order_builder")
    constants = types.ModuleType("py_clob_client.order_builder.constants")

    class FakeOrderArgs:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeOrderType:
        GTC = "GTC"

    clob_types.OrderArgs = FakeOrderArgs
    clob_types.OrderType = FakeOrderType
    constants.BUY = "BUY"

    monkeypatch.setitem(sys.modules, "py_clob_client", py_clob_root)
    monkeypatch.setitem(sys.modules, "py_clob_client.clob_types", clob_types)
    monkeypatch.setitem(sys.modules, "py_clob_client.order_builder", order_builder)
    monkeypatch.setitem(sys.modules, "py_clob_client.order_builder.constants", constants)


def test_place_post_only_buy_fails_closed_when_post_only_unsupported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = MakerConfig(db_path=tmp_path / "btc5_core.db")
    executor = CLOBExecutor(cfg)
    _install_fake_clob_modules(monkeypatch)

    class FakeClient:
        def create_order(self, order_args):
            return {"signed": order_args.kwargs}

        def post_order(self, _signed, _order_type, **kwargs):
            if "post_only" in kwargs:
                raise TypeError("post_only unsupported")
            raise AssertionError("non-post-only fallback should never execute")

    monkeypatch.setattr(executor, "ensure_client", lambda: FakeClient())

    with pytest.raises(RuntimeError, match="post_only=True"):
        executor.place_post_only_buy("tok-1", 0.49, 10.0)
