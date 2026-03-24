"""
Fill Callback System -- Closes the loop from execution to research.

When fills come in (via wallet poller or direct CLOB response):
1. Updates the unified ledger
2. Computes execution quality metrics (slippage, latency, fill rate)
3. Feeds results back to the research pipeline
4. Triggers liveness alerts if anomalies detected

This is the missing link that makes the system self-improving.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionQualityMetrics:
    """Tracks gap between simulated and live behavior."""
    strategy_name: str
    period_start: str
    period_end: str

    # Fill quality
    expected_fill_rate: float = 0.6  # From backtest
    actual_fill_rate: float = 0.0
    fill_rate_gap: float = 0.0

    # Slippage
    expected_slippage_bps: float = 5.0  # From cost model
    actual_slippage_bps: float = 0.0
    slippage_gap_bps: float = 0.0

    # Latency
    avg_fill_latency_seconds: float = 0.0
    p95_fill_latency_seconds: float = 0.0

    # P&L attribution
    predicted_alpha_bps: float = 0.0
    realized_alpha_bps: float = 0.0
    execution_effect_bps: float = 0.0  # predicted - realized

    # Counts
    total_signals: int = 0
    total_orders: int = 0
    total_fills: int = 0
    total_skips: int = 0
    total_rejects: int = 0


@dataclass
class FillEvent:
    """A single fill event from the CLOB or wallet poller."""
    trade_id: str
    order_id: str
    fill_price: float
    fill_size: float
    fill_time: str
    strategy_name: str = ""
    expected_price: float = 0.0  # What the backtest predicted
    expected_size: float = 0.0
    latency_seconds: float = 0.0


class FillCallbackManager:
    """
    Manages the feedback loop from fill events to research pipeline.

    Flow:
    1. Wallet poller or CLOB detects fill -> calls on_fill()
    2. on_fill() updates unified ledger + computes execution quality
    3. Periodically, compute_execution_quality() generates metrics
    4. Metrics feed into research pipeline via write_feedback_artifact()
    5. Research pipeline uses metrics to adjust cost models and validate strategies
    """

    # Slippage threshold for warning (2%)
    HIGH_SLIPPAGE_THRESHOLD = 0.02

    def __init__(self, ledger=None, output_dir: str = "reports/execution_feedback"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self._fill_buffer: List[FillEvent] = []

    def on_fill(self, event: FillEvent):
        """Called when a fill is detected. Updates ledger and buffers for analysis."""
        self._fill_buffer.append(event)

        # Update unified ledger if available
        if self.ledger:
            self.ledger.record_fill(
                trade_id=event.trade_id,
                order_id=event.order_id,
                fill_price=event.fill_price,
                fill_size=event.fill_size,
                fill_time=event.fill_time,
            )

        logger.info(
            "Fill callback: trade=%s price=%s size=%s latency=%.2fs",
            event.trade_id, event.fill_price,
            event.fill_size, event.latency_seconds,
        )

        # Check for anomalies
        if event.expected_price > 0:
            slippage = (
                abs(event.fill_price - event.expected_price) / event.expected_price
            )
            if slippage > self.HIGH_SLIPPAGE_THRESHOLD:
                logger.warning(
                    "HIGH SLIPPAGE: %.4f on trade %s", slippage, event.trade_id
                )

    def on_skip(self, instance_id: str, reason: str, **kwargs):
        """Called when a trade is skipped. Records to ledger skip log."""
        if self.ledger:
            self.ledger.record_skip(instance_id, reason, **kwargs)

    def compute_execution_quality(
        self, strategy_name: str, hours: int = 24
    ) -> ExecutionQualityMetrics:
        """Compute execution quality metrics for a strategy over a time window."""
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=hours)).isoformat()

        metrics = ExecutionQualityMetrics(
            strategy_name=strategy_name,
            period_start=start,
            period_end=now.isoformat(),
        )

        if not self.ledger:
            return metrics

        trades = self.ledger.get_trades(instance_id=strategy_name, since=start)
        skip_stats = self.ledger.get_skip_stats(
            instance_id=strategy_name, hours=hours
        )

        total_orders = len(
            [t for t in trades if t.get("order_status") != "skipped"]
        )
        total_fills = len(
            [t for t in trades if t.get("order_status") == "filled"]
        )
        total_skips = sum(skip_stats.values())

        metrics.total_signals = len(trades) + total_skips
        metrics.total_orders = total_orders
        metrics.total_fills = total_fills
        metrics.total_skips = total_skips

        if metrics.total_signals > 0:
            metrics.actual_fill_rate = total_fills / metrics.total_signals
            metrics.fill_rate_gap = (
                metrics.expected_fill_rate - metrics.actual_fill_rate
            )

        # Slippage from fills
        slippages: List[float] = []
        latencies: List[float] = []
        for t in trades:
            if (
                t.get("order_status") == "filled"
                and t.get("order_price", 0) > 0
            ):
                slip = (
                    abs(t["fill_price"] - t["order_price"])
                    / t["order_price"]
                    * 10000
                )
                slippages.append(slip)
            if t.get("fill_latency_seconds", 0) > 0:
                latencies.append(t["fill_latency_seconds"])

        if slippages:
            metrics.actual_slippage_bps = sum(slippages) / len(slippages)
            metrics.slippage_gap_bps = (
                metrics.actual_slippage_bps - metrics.expected_slippage_bps
            )

        if latencies:
            metrics.avg_fill_latency_seconds = sum(latencies) / len(latencies)
            sorted_lat = sorted(latencies)
            p95_idx = int(len(sorted_lat) * 0.95)
            metrics.p95_fill_latency_seconds = sorted_lat[
                min(p95_idx, len(sorted_lat) - 1)
            ]

        return metrics

    def write_feedback_artifact(
        self, metrics: ExecutionQualityMetrics
    ) -> dict:
        """Write execution feedback to a JSON artifact for the research pipeline."""
        artifact = {
            "strategy": metrics.strategy_name,
            "period": {
                "start": metrics.period_start,
                "end": metrics.period_end,
            },
            "fill_quality": {
                "expected_fill_rate": metrics.expected_fill_rate,
                "actual_fill_rate": metrics.actual_fill_rate,
                "gap": metrics.fill_rate_gap,
            },
            "slippage": {
                "expected_bps": metrics.expected_slippage_bps,
                "actual_bps": metrics.actual_slippage_bps,
                "gap_bps": metrics.slippage_gap_bps,
            },
            "latency": {
                "avg_seconds": metrics.avg_fill_latency_seconds,
                "p95_seconds": metrics.p95_fill_latency_seconds,
            },
            "counts": {
                "signals": metrics.total_signals,
                "orders": metrics.total_orders,
                "fills": metrics.total_fills,
                "skips": metrics.total_skips,
                "rejects": metrics.total_rejects,
            },
            "alpha_attribution": {
                "predicted_bps": metrics.predicted_alpha_bps,
                "realized_bps": metrics.realized_alpha_bps,
                "execution_effect_bps": metrics.execution_effect_bps,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Write latest
        latest_path = self.output_dir / f"{metrics.strategy_name}_latest.json"
        with open(latest_path, "w") as f:
            json.dump(artifact, f, indent=2)

        # Append to history
        history_path = self.output_dir / f"{metrics.strategy_name}_history.jsonl"
        with open(history_path, "a") as f:
            f.write(json.dumps(artifact) + "\n")

        logger.info("Execution feedback written: %s", latest_path)
        return artifact

    def generate_research_context(self, strategy_name: str) -> dict:
        """
        Generate context for the research pipeline about execution reality.

        This feeds back into hypothesis generation so new strategies account
        for actual execution conditions, not fantasy assumptions.
        """
        metrics = self.compute_execution_quality(strategy_name, hours=168)  # 7 days

        context = {
            "execution_reality": {
                "actual_fill_rate": metrics.actual_fill_rate,
                "actual_slippage_bps": metrics.actual_slippage_bps,
                "avg_latency_seconds": metrics.avg_fill_latency_seconds,
                "skip_rate": metrics.total_skips / max(metrics.total_signals, 1),
            },
            "cost_model_calibration": {
                "recommended_fill_rate": max(
                    0.1, metrics.actual_fill_rate - 0.1
                ),
                "recommended_slippage_bps": metrics.actual_slippage_bps * 1.5,
                "recommended_latency_seconds": metrics.p95_fill_latency_seconds,
            },
            "warnings": [],
        }

        if metrics.fill_rate_gap > 0.2:
            context["warnings"].append(
                f"Fill rate gap is {metrics.fill_rate_gap:.1%}"
                " -- backtest assumptions too optimistic"
            )
        if metrics.slippage_gap_bps > 10:
            context["warnings"].append(
                f"Slippage gap is {metrics.slippage_gap_bps:.1f} bps"
                " -- cost model needs recalibration"
            )

        return context
