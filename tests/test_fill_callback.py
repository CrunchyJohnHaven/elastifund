"""Tests for bot/fill_callback.py"""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from bot.fill_callback import (
    ExecutionQualityMetrics,
    FillCallbackManager,
    FillEvent,
)


@pytest.fixture
def tmp_output_dir(tmp_path):
    return str(tmp_path / "execution_feedback")


@pytest.fixture
def manager(tmp_output_dir):
    return FillCallbackManager(output_dir=tmp_output_dir)


@pytest.fixture
def mock_ledger():
    ledger = MagicMock()
    ledger.get_trades.return_value = []
    ledger.get_skip_stats.return_value = {}
    return ledger


@pytest.fixture
def manager_with_ledger(tmp_output_dir, mock_ledger):
    return FillCallbackManager(ledger=mock_ledger, output_dir=tmp_output_dir)


@pytest.fixture
def sample_fill():
    return FillEvent(
        trade_id="t-001",
        order_id="o-001",
        fill_price=0.55,
        fill_size=10.0,
        fill_time="2026-03-14T10:00:00+00:00",
        strategy_name="btc5",
        expected_price=0.54,
        expected_size=10.0,
        latency_seconds=1.5,
    )


class TestFillEvent:
    def test_basic_creation(self, sample_fill):
        assert sample_fill.trade_id == "t-001"
        assert sample_fill.fill_price == 0.55
        assert sample_fill.latency_seconds == 1.5


class TestFillCallbackManager:
    def test_init_creates_output_dir(self, manager, tmp_output_dir):
        assert Path(tmp_output_dir).exists()

    def test_on_fill_buffers_event(self, manager, sample_fill):
        manager.on_fill(sample_fill)
        assert len(manager._fill_buffer) == 1
        assert manager._fill_buffer[0].trade_id == "t-001"

    def test_on_fill_updates_ledger(self, manager_with_ledger, sample_fill):
        manager_with_ledger.on_fill(sample_fill)
        manager_with_ledger.ledger.record_fill.assert_called_once_with(
            trade_id="t-001",
            order_id="o-001",
            fill_price=0.55,
            fill_size=10.0,
            fill_time="2026-03-14T10:00:00+00:00",
        )

    def test_on_fill_high_slippage_warning(self, manager, caplog):
        event = FillEvent(
            trade_id="t-002",
            order_id="o-002",
            fill_price=0.60,
            fill_size=10.0,
            fill_time="2026-03-14T10:00:00+00:00",
            expected_price=0.50,  # 20% slippage
        )
        import logging
        with caplog.at_level(logging.WARNING):
            manager.on_fill(event)
        assert "HIGH SLIPPAGE" in caplog.text

    def test_on_fill_no_warning_normal_slippage(self, manager, caplog):
        event = FillEvent(
            trade_id="t-003",
            order_id="o-003",
            fill_price=0.501,
            fill_size=10.0,
            fill_time="2026-03-14T10:00:00+00:00",
            expected_price=0.50,  # 0.2% slippage
        )
        import logging
        with caplog.at_level(logging.WARNING):
            manager.on_fill(event)
        assert "HIGH SLIPPAGE" not in caplog.text

    def test_on_skip_delegates_to_ledger(self, manager_with_ledger):
        manager_with_ledger.on_skip("btc5", "delta_too_large", delta=0.008)
        manager_with_ledger.ledger.record_skip.assert_called_once_with(
            "btc5", "delta_too_large", delta=0.008
        )

    def test_compute_execution_quality_no_ledger(self, manager):
        metrics = manager.compute_execution_quality("btc5")
        assert metrics.strategy_name == "btc5"
        assert metrics.total_fills == 0

    def test_compute_execution_quality_with_trades(self, manager_with_ledger, mock_ledger):
        mock_ledger.get_trades.return_value = [
            {"order_status": "filled", "order_price": 0.50, "fill_price": 0.51, "fill_latency_seconds": 2.0},
            {"order_status": "filled", "order_price": 0.50, "fill_price": 0.50, "fill_latency_seconds": 1.0},
            {"order_status": "pending"},
        ]
        mock_ledger.get_skip_stats.return_value = {"delta_too_large": 5}

        metrics = manager_with_ledger.compute_execution_quality("btc5", hours=24)
        assert metrics.total_fills == 2
        assert metrics.total_orders == 3
        assert metrics.total_skips == 5
        assert metrics.total_signals == 8  # 3 trades + 5 skips
        assert metrics.actual_fill_rate == pytest.approx(0.25)  # 2/8
        assert metrics.actual_slippage_bps > 0
        assert metrics.avg_fill_latency_seconds == pytest.approx(1.5)

    def test_write_feedback_artifact(self, manager, tmp_output_dir):
        metrics = ExecutionQualityMetrics(
            strategy_name="btc5",
            period_start="2026-03-13T00:00:00",
            period_end="2026-03-14T00:00:00",
            actual_fill_rate=0.3,
            actual_slippage_bps=8.5,
            total_fills=15,
            total_skips=35,
        )
        artifact = manager.write_feedback_artifact(metrics)

        assert artifact["strategy"] == "btc5"
        assert artifact["fill_quality"]["actual_fill_rate"] == 0.3

        latest_path = Path(tmp_output_dir) / "btc5_latest.json"
        assert latest_path.exists()
        with open(latest_path) as f:
            saved = json.load(f)
        assert saved["strategy"] == "btc5"

        history_path = Path(tmp_output_dir) / "btc5_history.jsonl"
        assert history_path.exists()
        lines = history_path.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_write_feedback_appends_history(self, manager, tmp_output_dir):
        for i in range(3):
            metrics = ExecutionQualityMetrics(
                strategy_name="btc5",
                period_start=f"2026-03-{10+i}T00:00:00",
                period_end=f"2026-03-{11+i}T00:00:00",
            )
            manager.write_feedback_artifact(metrics)

        history_path = Path(tmp_output_dir) / "btc5_history.jsonl"
        lines = history_path.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_generate_research_context_no_ledger(self, manager):
        ctx = manager.generate_research_context("btc5")
        assert "execution_reality" in ctx
        assert "cost_model_calibration" in ctx
        assert "warnings" in ctx

    def test_generate_research_context_warns_fill_gap(self, manager_with_ledger, mock_ledger):
        mock_ledger.get_trades.return_value = [
            {"order_status": "filled", "order_price": 0.50, "fill_price": 0.50},
        ]
        mock_ledger.get_skip_stats.return_value = {"delta_too_large": 20}

        ctx = manager_with_ledger.generate_research_context("btc5")
        # fill rate = 1/21 = 0.048, gap = 0.6 - 0.048 = 0.552 > 0.2
        fill_warnings = [w for w in ctx["warnings"] if "Fill rate gap" in w]
        assert len(fill_warnings) == 1


class TestExecutionQualityMetrics:
    def test_defaults(self):
        m = ExecutionQualityMetrics(
            strategy_name="test",
            period_start="2026-03-13",
            period_end="2026-03-14",
        )
        assert m.expected_fill_rate == 0.6
        assert m.expected_slippage_bps == 5.0
        assert m.total_fills == 0
