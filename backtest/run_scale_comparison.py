#!/usr/bin/env python3
"""Bankroll scale comparison for currently evidenced strategy lanes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.run_combined import _build_calibrator, load_data as load_llm_backtest_data
from simulator.fill_model import simulate_fill
from simulator.metrics import compute_max_drawdown
from simulator.simulator import SimulatorEngine, load_config as load_simulator_config
from simulator.sizing import capped_size
from src.config import load_config as load_edge_config
from src.feature_engineering import FeatureEngineer
from src.strategies.wallet_flow import WalletFlowMomentumStrategy, build_wallet_flow_replay_entry


LOGGER = logging.getLogger(__name__)

DEFAULT_BANKROLLS = [1000.0, 10000.0, 100000.0]
DEFAULT_MARKDOWN_PATH = ROOT / "reports" / "strategy_scale_comparison.md"
DEFAULT_JSON_PATH = ROOT / "reports" / "strategy_scale_comparison.json"
DEFAULT_WALLET_FLOW_ARCHIVE_PATH = ROOT / "reports" / "wallet_flow_resolved_signals.json"
DEFAULT_SIGNAL_SOURCE_AUDIT_PATH = ROOT / "reports" / "signal_source_audit.json"
DEFAULT_RUNTIME_TRUTH_PATH = ROOT / "reports" / "runtime_truth_latest.json"
DEFAULT_PUBLIC_RUNTIME_SNAPSHOT_PATH = ROOT / "reports" / "public_runtime_snapshot.json"
DEFAULT_BTC5_AUTORESEARCH_PATH = ROOT / "reports" / "btc5_autoresearch" / "latest.json"
DEFAULT_KALSHI_WEATHER_LANE_PATH = ROOT / "reports" / "parallel" / "instance05_weather_lane.json"
DEFAULT_KALSHI_ORDERS_PATH = ROOT / "data" / "kalshi_weather_orders.jsonl"
DEFAULT_KALSHI_SETTLEMENTS_PATH = ROOT / "data" / "kalshi_weather_settlements.jsonl"
DEFAULT_KALSHI_DECISIONS_PATH = ROOT / "data" / "kalshi_weather_decisions.jsonl"

LLM_KELLY_FRACTION = 0.25
FAST_KELLY_FRACTION = 1.0 / 16.0
MAX_ALLOCATION = 0.20
MAX_POSITION_USD = 5.0
MIN_POSITION_USD = 1.0
LLM_ENTRY_PRICE = 0.50
LLM_YES_THRESHOLD = 0.15
LLM_NO_THRESHOLD = 0.05
WALLET_FLOW_ARCHIVE_SCHEMA = "wallet_flow_resolved_signal_archive.v1"
MIN_WALLET_FLOW_RESOLVED_SIGNALS = 3
MIN_WALLET_FLOW_UNIQUE_MARKETS = 2
TIMEFRAME_RE = re.compile(r"(?<!\d)(\d{1,3})\s*(m|min|minute|minutes|h|hr|hour|hours)\b", re.IGNORECASE)
VENUE_STALE_HOURS = 6.0
FUND_BLOCKING_CHECKS = {
    "polymarket_capital_truth_drift",
    "accounting_reconciliation_drift",
}


@dataclass(frozen=True)
class TradeOpportunity:
    """Single replayable trade opportunity for a strategy lane."""

    lane: str
    signal_id: str
    timestamp: str
    question: str
    direction: str
    market_price: float
    win_probability: float
    actual_outcome: str
    edge: float
    volume: float
    liquidity: float
    kelly_fraction: float


@dataclass
class LaneEvidence:
    """Evidence status for one lane."""

    lane: str
    status: str
    reasons: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    opportunities: list[TradeOpportunity] = field(default_factory=list)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _market_key(opportunity: TradeOpportunity) -> str:
    if opportunity.lane == "wallet_flow" and ":" in opportunity.signal_id:
        return opportunity.signal_id.split(":", 1)[0]
    return str(opportunity.question or opportunity.signal_id)


def _sample_size_summary(
    opportunities: list[TradeOpportunity],
    *,
    unique_markets: int | None = None,
    resolved_signals: int | None = None,
) -> dict[str, int]:
    replayable_opportunities = len(opportunities)
    if unique_markets is None:
        unique_markets = len({_market_key(opportunity) for opportunity in opportunities if _market_key(opportunity)})
    if resolved_signals is None:
        resolved_signals = sum(1 for opportunity in opportunities if str(opportunity.actual_outcome or "").strip())
    return {
        "replayable_opportunities": int(replayable_opportunities),
        "unique_markets": int(unique_markets),
        "resolved_signals": int(resolved_signals),
    }


def _empty_timebound_evidence_window(source_class: str = "replayable_opportunities") -> dict[str, Any]:
    return {
        "status": "insufficient_data",
        "source_class": source_class,
        "start": None,
        "end": None,
        "elapsed_hours": None,
        "observation_count": 0,
    }


def _build_timebound_evidence_window(
    opportunities: list[TradeOpportunity],
    *,
    source_class: str = "replayable_opportunities",
) -> dict[str, Any]:
    timestamps = [parsed for opportunity in opportunities if (parsed := _parse_timestamp(opportunity.timestamp)) is not None]
    if not timestamps:
        return _empty_timebound_evidence_window(source_class)
    start = min(timestamps)
    end = max(timestamps)
    return {
        "status": "ready",
        "source_class": source_class,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "elapsed_hours": round(max((end - start).total_seconds() / 3600.0, 0.0), 6),
        "observation_count": len(timestamps),
    }


def build_conservative_simulation_config(bankroll: float) -> dict[str, Any]:
    """Reuse simulator cost assumptions while restoring conservative bankroll limits."""

    config = copy.deepcopy(load_simulator_config())
    config["capital"]["initial"] = float(bankroll)
    config["sizing"]["method"] = "capped_kelly"
    config["sizing"]["kelly"]["kelly_fraction"] = LLM_KELLY_FRACTION
    config["sizing"]["kelly"]["max_allocation"] = MAX_ALLOCATION
    config["sizing"]["kelly"]["min_size"] = MIN_POSITION_USD
    config["sizing"]["capped"]["max_position_usd"] = MAX_POSITION_USD
    config["sizing"]["capped"]["min_position_usd"] = MIN_POSITION_USD
    config["execution"]["mode"] = "taker"
    config["execution"]["max_concurrent_positions"] = 1
    config["execution"]["min_edge_threshold"] = LLM_NO_THRESHOLD
    config["filters"]["min_liquidity"] = 0
    config["filters"]["min_volume"] = 0
    config["filters"]["price_range"] = [0.10, 0.90]
    return config


def load_llm_only_evidence() -> LaneEvidence:
    """Convert the existing LLM backtest surface into replayable opportunities."""

    markets, cache, hashes = load_llm_backtest_data()
    calibrator = _build_calibrator()

    opportunities: list[TradeOpportunity] = []
    cached_estimates = 0
    qualified_signals = 0

    for market in sorted(markets, key=lambda row: (row.get("end_date") or "", row.get("id") or "")):
        question = str(market["question"])
        key = hashlib.sha256(question.encode()).hexdigest()[:16]
        estimate = cache.get(key)
        if estimate is None:
            continue

        cached_estimates += 1
        raw_probability = float(estimate["probability"])
        calibrated_probability = float(calibrator.correct(raw_probability))
        edge = calibrated_probability - LLM_ENTRY_PRICE
        direction = "buy_yes" if edge > 0 else "buy_no"
        abs_edge = abs(edge)
        threshold = LLM_YES_THRESHOLD if direction == "buy_yes" else LLM_NO_THRESHOLD

        if abs_edge < threshold:
            continue

        qualified_signals += 1
        win_probability = calibrated_probability if direction == "buy_yes" else 1.0 - calibrated_probability
        opportunities.append(
            TradeOpportunity(
                lane="llm_only",
                signal_id=str(market.get("id") or qualified_signals),
                timestamp=str(market.get("end_date") or ""),
                question=question,
                direction=direction,
                market_price=LLM_ENTRY_PRICE,
                win_probability=win_probability,
                actual_outcome=str(market["actual_outcome"]),
                edge=abs_edge,
                volume=float(market.get("volume") or 0.0),
                liquidity=float(market.get("liquidity") or 0.0),
                kelly_fraction=LLM_KELLY_FRACTION,
            )
        )

    if not opportunities:
        sample_size_summary = _sample_size_summary(opportunities)
        return LaneEvidence(
            lane="llm_only",
            status="insufficient_data",
            reasons=["No qualified LLM signals were available after calibration and asymmetric thresholding."],
            assumptions=[
                "Fixed 0.50 entry-price baseline from backtest/kelly_comparison.py because historical entry snapshots are not stored.",
                "Quarter-Kelly sizing with a hard $5 position cap and 20% max allocation.",
                "Simulator taker fill model for deterministic fee/slippage replay.",
            ],
            evidence_summary={
                "historical_markets": len(markets),
                "cached_estimates": cached_estimates,
                "qualified_signals": qualified_signals,
                **sample_size_summary,
                "timebound_evidence_window": _build_timebound_evidence_window(opportunities),
                "data_hashes": hashes,
            },
        )

    sample_size_summary = _sample_size_summary(opportunities)
    return LaneEvidence(
        lane="llm_only",
        status="ready",
        reasons=[],
        assumptions=[
            "Fixed 0.50 entry-price baseline from backtest/kelly_comparison.py because historical entry snapshots are not stored.",
            "Calibrated Claude probabilities via backtest/run_combined.py with live-style asymmetric thresholds (YES 15%, NO 5%).",
            "Quarter-Kelly sizing with a hard $5 position cap and 20% max allocation.",
            "Simulator taker fill model for deterministic fee/slippage replay.",
        ],
        evidence_summary={
            "historical_markets": len(markets),
            "cached_estimates": cached_estimates,
            "qualified_signals": qualified_signals,
            **sample_size_summary,
            "timebound_evidence_window": _build_timebound_evidence_window(opportunities),
            "data_hashes": hashes,
        },
        opportunities=opportunities,
    )


def _wallet_flow_proxy_volume_and_liquidity(signal: dict[str, Any]) -> tuple[float, float]:
    """Derive deterministic fill-model proxies from wallet-flow metadata fields."""
    wallets = max(1, int(signal.get("wallets") or 0))
    wallet_trades = max(1, int(signal.get("wallet_trades") or 0))
    flow_imbalance = abs(float(signal.get("trade_flow_imbalance") or 0.0))
    imbalance = abs(float(signal.get("book_imbalance") or 0.0))

    # Proxies use only existing wallet/feature fields and stay deterministic.
    volume_proxy = max(200.0, (wallets * wallet_trades) * (20.0 + flow_imbalance * 20.0))
    liquidity_proxy = max(150.0, (wallets * 80.0) + ((1.0 - min(1.0, imbalance)) * 250.0))
    return volume_proxy, liquidity_proxy


def _validate_wallet_flow_archive(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schema") != WALLET_FLOW_ARCHIVE_SCHEMA:
        return False
    signals = payload.get("signals")
    return isinstance(signals, list)


def _build_wallet_flow_replay_archive(db_path: str) -> dict[str, Any]:
    """Build resolved wallet-flow replay entries from edge-discovery features."""
    try:
        bundle = FeatureEngineer(db_path).build_feature_bundle()
    except Exception as exc:
        return {
            "schema": WALLET_FLOW_ARCHIVE_SCHEMA,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "status": "insufficient_data",
            "requirements": {
                "min_resolved_signals": MIN_WALLET_FLOW_RESOLVED_SIGNALS,
                "min_unique_markets": MIN_WALLET_FLOW_UNIQUE_MARKETS,
            },
            "counts": {
                "markets": 0,
                "features": 0,
                "trades": 0,
                "resolved_markets": 0,
                "qualifying_signals": 0,
                "resolved_qualifying_signals": 0,
                "replayable_signals": 0,
                "unique_markets": 0,
            },
            "source": {
                "db_path": db_path,
                "strategy": "WalletFlowMomentumStrategy",
                "strategy_module": "src/strategies/wallet_flow.py",
            },
            "missing_requirements": [
                f"feature_bundle_unavailable: {exc.__class__.__name__}: {exc}",
                f"resolved_signals 0 < required {MIN_WALLET_FLOW_RESOLVED_SIGNALS}",
                f"unique_markets 0 < required {MIN_WALLET_FLOW_UNIQUE_MARKETS}",
            ],
            "signals": [],
        }
    strategy = WalletFlowMomentumStrategy()
    signals = strategy.generate_signals(bundle.markets, bundle.btc_prices, bundle.trades, bundle.features)
    resolved_signals = [signal for signal in signals if signal.condition_id in bundle.resolutions]
    market_titles = {str(row.get("condition_id")): str(row.get("title") or row.get("question") or "") for row in bundle.markets}

    replay_signals: list[dict[str, Any]] = []
    for signal in resolved_signals:
        resolution = str(bundle.resolutions.get(signal.condition_id) or "")
        if resolution not in {"UP", "DOWN"}:
            continue
        synthetic_row = {
            "wallets": int((signal.metadata or {}).get("wallets") or 0),
            "wallet_trades": int((signal.metadata or {}).get("wallet_trades") or 0),
            "trade_flow_imbalance": float((signal.metadata or {}).get("trade_flow_imbalance") or 0.0),
            "book_imbalance": float((signal.metadata or {}).get("book_imbalance") or 0.0),
        }
        volume_proxy, liquidity_proxy = _wallet_flow_proxy_volume_and_liquidity(synthetic_row)
        replay_signals.append(
            build_wallet_flow_replay_entry(
                signal=signal,
                resolution=resolution,
                market_title=market_titles.get(signal.condition_id) or signal.condition_id,
                volume_proxy=volume_proxy,
                liquidity_proxy=liquidity_proxy,
            )
        )

    unique_markets = {str(row.get("condition_id")) for row in replay_signals}
    missing_requirements: list[str] = []
    if len(replay_signals) < MIN_WALLET_FLOW_RESOLVED_SIGNALS:
        missing_requirements.append(
            f"resolved_signals {len(replay_signals)} < required {MIN_WALLET_FLOW_RESOLVED_SIGNALS}"
        )
    if len(unique_markets) < MIN_WALLET_FLOW_UNIQUE_MARKETS:
        missing_requirements.append(
            f"unique_markets {len(unique_markets)} < required {MIN_WALLET_FLOW_UNIQUE_MARKETS}"
        )

    return {
        "schema": WALLET_FLOW_ARCHIVE_SCHEMA,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "status": "ready" if not missing_requirements else "insufficient_data",
        "requirements": {
            "min_resolved_signals": MIN_WALLET_FLOW_RESOLVED_SIGNALS,
            "min_unique_markets": MIN_WALLET_FLOW_UNIQUE_MARKETS,
        },
        "counts": {
            "markets": len(bundle.markets),
            "features": len(bundle.features),
            "trades": len(bundle.trades),
            "resolved_markets": len(bundle.resolutions),
            "qualifying_signals": len(signals),
            "resolved_qualifying_signals": len(resolved_signals),
            "replayable_signals": len(replay_signals),
            "unique_markets": len(unique_markets),
        },
        "source": {
            "db_path": db_path,
            "strategy": "WalletFlowMomentumStrategy",
            "strategy_module": "src/strategies/wallet_flow.py",
        },
        "missing_requirements": missing_requirements,
        "signals": replay_signals,
    }


def load_or_build_wallet_flow_archive(db_path: str, archive_path: Path | None = None) -> tuple[dict[str, Any], str]:
    """Load a durable archive when present; otherwise build from current DB surfaces."""
    if archive_path and archive_path.exists():
        try:
            payload = json.loads(archive_path.read_text())
            if _validate_wallet_flow_archive(payload):
                return payload, "loaded"
        except json.JSONDecodeError:
            LOGGER.warning("wallet-flow archive exists but is invalid JSON: %s", archive_path)

    return _build_wallet_flow_replay_archive(db_path), "built"


def wallet_flow_archive_to_opportunities(archive: dict[str, Any]) -> list[TradeOpportunity]:
    """Convert archive rows into simulator opportunities."""
    opportunities: list[TradeOpportunity] = []
    for row in archive.get("signals", []):
        opportunities.append(
            TradeOpportunity(
                lane="wallet_flow",
                signal_id=f"{row.get('condition_id')}:{row.get('timestamp_ts')}",
                timestamp=str(row.get("timestamp")),
                question=str(row.get("market_title") or row.get("condition_id") or ""),
                direction=str(row.get("direction") or "buy_yes"),
                market_price=float(row.get("entry_price") or 0.5),
                win_probability=float(row.get("win_probability") or 0.5),
                actual_outcome=str(row.get("actual_outcome") or ""),
                edge=abs(float(row.get("edge") or 0.0)),
                volume=float(row.get("volume_proxy") or 0.0),
                liquidity=float(row.get("liquidity_proxy") or 0.0),
                kelly_fraction=FAST_KELLY_FRACTION,
            )
        )
    return opportunities


def load_wallet_flow_evidence(archive_path: Path | None = None) -> LaneEvidence:
    """Use resolved wallet-flow archive evidence when available, else return explicit insufficiency reasons."""
    config = load_edge_config()
    archive, archive_source = load_or_build_wallet_flow_archive(
        db_path=config.system.db_path,
        archive_path=archive_path,
    )
    counts = archive.get("counts", {})
    requirements = archive.get("requirements", {})
    missing = [str(item) for item in archive.get("missing_requirements", [])]
    opportunities = wallet_flow_archive_to_opportunities(archive)
    timeframe_mix = _wallet_flow_timeframe_mix(archive)
    sample_size_summary = _sample_size_summary(
        opportunities,
        unique_markets=int(counts.get("unique_markets", 0) or 0),
        resolved_signals=int(counts.get("resolved_qualifying_signals", 0) or 0),
    )
    summary_base = {
        **counts,
        "db_path": config.system.db_path,
        "archive_schema": archive.get("schema"),
        "archive_source": archive_source,
        "resolved_replayable_signals": int(counts.get("replayable_signals", 0) or 0),
        "unique_markets": int(counts.get("unique_markets", 0) or 0),
        **sample_size_summary,
        "timebound_evidence_window": _build_timebound_evidence_window(opportunities),
        "missing_requirements": missing,
    }
    if timeframe_mix:
        summary_base["timeframe_mix"] = timeframe_mix

    if missing or not opportunities:
        reasons = [
            "Wallet-flow replay requirements not met.",
            (
                "Resolved qualifying signals: "
                f"{int(counts.get('resolved_qualifying_signals', 0))} "
                f"(required >= {int(requirements.get('min_resolved_signals', MIN_WALLET_FLOW_RESOLVED_SIGNALS))})."
            ),
            (
                "Unique resolved markets: "
                f"{int(counts.get('unique_markets', 0))} "
                f"(required >= {int(requirements.get('min_unique_markets', MIN_WALLET_FLOW_UNIQUE_MARKETS))})."
            ),
        ]
        reasons.extend(f"Missing requirement: {item}" for item in missing)
        return LaneEvidence(
            lane="wallet_flow",
            status="insufficient_data",
            reasons=reasons,
            assumptions=[
                "Replay archive rows come from src/strategies/wallet_flow.py signals joined with final market resolutions in data/edge_discovery.db.",
                "Fast-lane sizing uses 1/16 Kelly with the same conservative position and allocation caps as other lanes.",
            ],
            evidence_summary={
                **summary_base,
            },
        )

    return LaneEvidence(
        lane="wallet_flow",
        status="ready",
        reasons=[],
        assumptions=[
            "Resolved wallet-flow signals are archived with stable schema wallet_flow_resolved_signal_archive.v1.",
            "Replay archive rows come from src/strategies/wallet_flow.py signals joined with final market resolutions in data/edge_discovery.db.",
            "Fast-lane sizing uses 1/16 Kelly with the same conservative position and allocation caps as other lanes.",
            "Volume/liquidity inputs use deterministic proxies from wallet participation and book imbalance fields to avoid fabricated external data.",
        ],
        evidence_summary={
            **summary_base,
        },
        opportunities=opportunities,
    )


def _wallet_flow_timeframe_mix(archive: dict[str, Any]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for row in archive.get("signals") or []:
        title = str(row.get("market_title") or "")
        match = TIMEFRAME_RE.search(title)
        if not match:
            continue
        size = int(match.group(1))
        unit = match.group(2).lower()
        label = f"{size}h" if unit.startswith("h") else f"{size}m"
        mix[label] = mix.get(label, 0) + 1
    return dict(sorted(mix.items(), key=lambda item: item[0]))


def load_lmsr_evidence() -> LaneEvidence:
    """Surface the current repo truth for LMSR replay readiness."""

    return LaneEvidence(
        lane="lmsr",
        status="insufficient_data",
        reasons=[
            "bot/lmsr_engine.py is implemented, but the repo does not contain a resolved historical LMSR signal archive for bankroll replay.",
            "No existing backtest/simulator adapter in this repo maps historical resolutions to LMSR engine decisions without inventing fills.",
        ],
        assumptions=[
            "Fast-lane sizing target would be 1/16 Kelly under the current operating rules once resolved signals exist.",
        ],
        evidence_summary={
            "engine_file": "bot/lmsr_engine.py",
            "resolved_signal_archive_present": False,
            "replay_adapter_present": False,
            **_sample_size_summary([]),
            "timebound_evidence_window": _empty_timebound_evidence_window(),
        },
    )


def load_cross_platform_arb_evidence() -> LaneEvidence:
    """Surface the current repo truth for cross-platform arb replay readiness."""

    return LaneEvidence(
        lane="cross_platform_arb",
        status="insufficient_data",
        reasons=[
            "bot/cross_platform_arb.py is unit-tested, but the repo does not contain a matched historical Polymarket/Kalshi execution archive with closed arbitrage outcomes.",
            "Assigning replay P&L without matched historical fills would be fabricated.",
        ],
        assumptions=[
            "High-confidence lane sizing remains quarter-Kelly with the same $5 hard cap once matched fills are archived.",
        ],
        evidence_summary={
            "scanner_file": "bot/cross_platform_arb.py",
            "matched_fill_archive_present": False,
            "closed_trade_archive_present": False,
            **_sample_size_summary([]),
            "timebound_evidence_window": _empty_timebound_evidence_window(),
        },
    )


def load_lane_evidences(wallet_flow_archive_path: Path | None = None) -> dict[str, LaneEvidence]:
    """Collect the current replay readiness state for every requested lane."""

    return {
        "llm_only": load_llm_only_evidence(),
        "wallet_flow": load_wallet_flow_evidence(archive_path=wallet_flow_archive_path),
        "lmsr": load_lmsr_evidence(),
        "cross_platform_arb": load_cross_platform_arb_evidence(),
    }


def simulate_lane(opportunities: list[TradeOpportunity], bankroll: float) -> dict[str, Any]:
    """Replay one lane using simulator fill logic and conservative bankroll caps."""

    if not opportunities:
        return {
            "status": "insufficient_data",
            "reasons": ["No replayable opportunities were available."],
        }

    config = build_conservative_simulation_config(bankroll)
    engine = SimulatorEngine(config)

    capital = float(bankroll)
    equity_curve = [capital]
    trade_count = 0
    attempts = 0
    wins = 0
    total_turnover = 0.0
    total_fees = 0.0
    total_slippage_cost = 0.0
    total_spread_cost = 0.0
    utilization_samples: list[float] = []

    for opportunity in sorted(opportunities, key=lambda item: (item.timestamp, item.signal_id)):
        size = capped_size(
            capital=capital,
            edge=opportunity.edge,
            win_probability=opportunity.win_probability,
            kelly_fraction=opportunity.kelly_fraction,
            max_allocation=MAX_ALLOCATION,
            max_position_usd=MAX_POSITION_USD,
            min_position_usd=MIN_POSITION_USD,
        )
        if size <= 0.0:
            continue

        attempts += 1
        capital_before = capital
        fill = simulate_fill(
            market_price=opportunity.market_price,
            direction=opportunity.direction,
            edge=opportunity.edge,
            order_size_usd=size,
            volume=opportunity.volume,
            liquidity=max(opportunity.liquidity, 1.0),
            config=config,
            rng=engine.rng,
        )
        if not fill.filled:
            continue

        won, pnl, winner_fee = engine._resolve(
            direction=opportunity.direction,
            fill_price=fill.fill_price,
            size=size,
            actual=opportunity.actual_outcome,
            entry_fee=fill.fee,
        )
        capital += pnl
        equity_curve.append(capital)

        trade_count += 1
        wins += int(won)
        total_turnover += size
        total_fees += fill.fee + winner_fee
        total_slippage_cost += fill.slippage * size
        total_spread_cost += fill.spread_cost * size
        utilization_samples.append(size / capital_before if capital_before > 0 else 0.0)

    max_drawdown_usd, max_drawdown_pct = compute_max_drawdown(equity_curve)
    return {
        "status": "simulated",
        "attempted_trades": attempts,
        "trade_count": trade_count,
        "wins": wins,
        "win_rate": round((wins / trade_count) if trade_count else 0.0, 6),
        "starting_bankroll_usd": round(float(bankroll), 2),
        "final_capital_usd": round(capital, 2),
        "return_pct": round(((capital - bankroll) / bankroll) if bankroll else 0.0, 6),
        "max_drawdown_usd": round(max_drawdown_usd, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "capital_utilization_pct": round(statistics.mean(utilization_samples) if utilization_samples else 0.0, 6),
        "fee_drag_pct": round((total_fees / total_turnover) if total_turnover else 0.0, 6),
        "total_turnover_usd": round(total_turnover, 2),
        "total_fees_usd": round(total_fees, 2),
        "total_slippage_cost_usd": round(total_slippage_cost, 2),
        "total_spread_cost_usd": round(total_spread_cost, 2),
    }


def build_insufficient_results(evidence: LaneEvidence, bankrolls: list[float]) -> dict[str, Any]:
    """Expand one insufficient-data lane across all bankrolls."""

    return {
        str(int(bankroll)): {
            "status": "insufficient_data",
            "reasons": evidence.reasons,
            "evidence_summary": evidence.evidence_summary,
        }
        for bankroll in bankrolls
    }


def build_combined_evidence(lane_evidences: dict[str, LaneEvidence]) -> LaneEvidence:
    """Build the combined executable lane from all ready evidence."""

    supported = [lane for lane, evidence in lane_evidences.items() if evidence.status == "ready" and evidence.opportunities]
    unsupported = [lane for lane, evidence in lane_evidences.items() if evidence.status != "ready" or not evidence.opportunities]

    if not supported:
        return LaneEvidence(
            lane="combined",
            status="insufficient_data",
            reasons=["No lane has enough evidence for replay, so combined cannot produce defensible P&L."],
            assumptions=["Combined only includes lanes with replayable evidence."],
            evidence_summary={
                "included_lanes": [],
                "excluded_lanes": unsupported,
                **_sample_size_summary([]),
                "timebound_evidence_window": _empty_timebound_evidence_window(),
            },
        )

    combined_opportunities: list[TradeOpportunity] = []
    combined_assumptions: list[str] = ["Combined only includes lanes with replayable evidence."]
    for lane in supported:
        combined_opportunities.extend(lane_evidences[lane].opportunities)
        combined_assumptions.extend(lane_evidences[lane].assumptions)

    combined_assumptions.append(
        "Unsupported lanes remain excluded until they produce resolved replayable evidence; no synthetic P&L is assigned."
    )
    return LaneEvidence(
        lane="combined",
        status="ready",
        reasons=[],
        assumptions=_dedupe_preserve_order(combined_assumptions),
        evidence_summary={
            "included_lanes": supported,
            "excluded_lanes": unsupported,
            "combined_opportunities": len(combined_opportunities),
            **_sample_size_summary(combined_opportunities),
            "timebound_evidence_window": _build_timebound_evidence_window(combined_opportunities),
        },
        opportunities=combined_opportunities,
    )


def _normalized_evidence_summary(evidence: LaneEvidence) -> dict[str, Any]:
    summary = dict(evidence.evidence_summary)
    sample_size_summary = _sample_size_summary(
        evidence.opportunities,
        unique_markets=summary.get("unique_markets"),
        resolved_signals=summary.get("resolved_signals")
        or summary.get("resolved_replayable_signals")
        or summary.get("resolved_qualifying_signals"),
    )
    for key, value in sample_size_summary.items():
        summary.setdefault(key, value)
    summary.setdefault(
        "timebound_evidence_window",
        _build_timebound_evidence_window(evidence.opportunities),
    )
    return summary


def build_report(bankrolls: list[float], wallet_flow_archive_path: Path | None = None) -> dict[str, Any]:
    """Build the full scale-comparison payload."""

    lane_evidences = load_lane_evidences(wallet_flow_archive_path=wallet_flow_archive_path)
    combined_evidence = build_combined_evidence(lane_evidences)
    all_evidences = {
        **lane_evidences,
        "combined": combined_evidence,
    }

    results: dict[str, dict[str, Any]] = {}
    for lane, evidence in all_evidences.items():
        if evidence.status != "ready" or not evidence.opportunities:
            results[lane] = build_insufficient_results(evidence, bankrolls)
            continue

        lane_results: dict[str, Any] = {}
        for bankroll in bankrolls:
            lane_results[str(int(bankroll))] = simulate_lane(evidence.opportunities, bankroll)
        results[lane] = lane_results

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "as_of_date": "2026-03-08",
        "bankrolls": [int(bankroll) for bankroll in bankrolls],
        "risk_caps": {
            "max_position_usd": MAX_POSITION_USD,
            "max_allocation_pct": MAX_ALLOCATION,
            "llm_kelly_fraction": LLM_KELLY_FRACTION,
            "fast_kelly_fraction": FAST_KELLY_FRACTION,
            "min_position_usd": MIN_POSITION_USD,
        },
        "execution_assumptions": {
            "simulator_mode": "taker",
            "winner_fee_rate": load_simulator_config()["fees"]["winner_fee"],
            "entry_price_baseline_llm": LLM_ENTRY_PRICE,
            "yes_threshold_llm": LLM_YES_THRESHOLD,
            "no_threshold_llm": LLM_NO_THRESHOLD,
        },
        "lane_evidence": {
            lane: {
                "status": evidence.status,
                "reasons": evidence.reasons,
                "assumptions": evidence.assumptions,
                "evidence_summary": _normalized_evidence_summary(evidence),
            }
            for lane, evidence in all_evidences.items()
        },
        "results": results,
    }


def _lane_sample_size_summary(evidence_summary: dict[str, Any]) -> dict[str, int]:
    replayable = int(
        evidence_summary.get("replayable_opportunities")
        or evidence_summary.get("replayable_signals")
        or evidence_summary.get("combined_opportunities")
        or evidence_summary.get("qualified_signals")
        or 0
    )
    unique_markets = evidence_summary.get("unique_markets")
    if unique_markets is None and replayable:
        unique_markets = replayable
    resolved_signals = evidence_summary.get("resolved_signals")
    if resolved_signals is None:
        resolved_signals = evidence_summary.get("resolved_replayable_signals")
    if resolved_signals is None:
        resolved_signals = evidence_summary.get("resolved_qualifying_signals")
    if resolved_signals is None and replayable:
        resolved_signals = replayable
    return {
        "replayable_opportunities": replayable,
        "unique_markets": int(unique_markets or 0),
        "resolved_signals": int(resolved_signals or 0),
    }


def _lane_confidence_label(*, lane_status: str, sample_size_summary: dict[str, int]) -> str:
    if lane_status != "ready":
        return "low"
    replayable = int(sample_size_summary.get("replayable_opportunities", 0) or 0)
    unique_markets = int(sample_size_summary.get("unique_markets", 0) or 0)
    resolved_signals = int(sample_size_summary.get("resolved_signals", 0) or 0)
    if replayable >= 20 and unique_markets >= 10 and resolved_signals >= 20:
        return "high"
    if replayable >= 8 and unique_markets >= 4 and resolved_signals >= 8:
        return "medium"
    return "low"


def _deployment_readiness(*, lane_status: str, confidence_label: str) -> str:
    if lane_status != "ready":
        return "insufficient_data"
    if confidence_label in {"high", "medium"}:
        return "live_candidate"
    return "research_candidate"


def _ranking_score(
    *,
    lane_status: str,
    confidence_label: str,
    lane_results: dict[str, Any],
) -> tuple[float | None, float, float, float]:
    if lane_status != "ready":
        return None, 0.0, 0.0, 0.0

    return_pcts: list[float] = []
    drawdowns: list[float] = []
    for result in lane_results.values():
        if str(result.get("status")) != "simulated":
            continue
        return_pcts.append(_safe_float(result.get("return_pct"), 0.0))
        drawdowns.append(_safe_float(result.get("max_drawdown_pct"), 0.0))
    if not return_pcts:
        return None, 0.0, 0.0, 0.0

    median_return_pct = statistics.median(return_pcts)
    max_drawdown_pct = statistics.median(drawdowns) if drawdowns else 0.0
    p05_return_pct = _percentile(return_pcts, 5)
    score = median_return_pct - (2.0 * max_drawdown_pct) + (0.5 * p05_return_pct)
    if confidence_label == "low":
        score *= 0.5
    return round(score, 6), round(median_return_pct, 6), round(p05_return_pct, 6), round(max_drawdown_pct, 6)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pct = max(0.0, min(100.0, float(pct)))
    index = (len(ordered) - 1) * (pct / 100.0)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    frac = index - lower
    return (ordered[lower] * (1.0 - frac)) + (ordered[upper] * frac)


def _load_signal_source_audit(audit_path: Path | None) -> dict[str, Any] | None:
    if audit_path is None or not audit_path.exists():
        return None
    try:
        payload = json.loads(audit_path.read_text())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _load_json_dict(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _load_jsonl_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _freshness_hours(timestamp: Any, *, now: datetime) -> float | None:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return None
    return round(max((now - parsed).total_seconds() / 3600.0, 0.0), 4)


def _max_freshness_hours(timestamps: list[Any], *, now: datetime) -> float | None:
    ages = [age for age in (_freshness_hours(timestamp, now=now) for timestamp in timestamps) if age is not None]
    if not ages:
        return None
    return round(max(ages), 4)


def _source_evidence_from_audit(audit_payload: dict[str, Any] | None, lane: str) -> dict[str, Any]:
    empty = {
        "signal_source_audit_loaded": False,
        "wallet_flow_beats_llm_only": None,
        "combined_sources_beat_single_source_lanes": None,
        "lane_source_status": "unknown",
        "lane_source_reason": "signal_source_audit_missing",
        "best_component_source": None,
        "best_component_source_win_rate": None,
        "best_source_combo": None,
        "best_source_combo_win_rate": None,
    }
    if not audit_payload:
        return empty

    wallet_flow_vs_llm = audit_payload.get("wallet_flow_vs_llm") or {}
    combined_vs_single = audit_payload.get("combined_sources_vs_single_source") or {}
    ranking_snapshot = audit_payload.get("ranking_snapshot") or {}
    best_component_source = ranking_snapshot.get("best_component_source") or {}
    best_source_combo = ranking_snapshot.get("best_source_combo") or {}

    wallet_delta = wallet_flow_vs_llm.get("wallet_flow_any_win_rate_delta_vs_llm_only")
    wallet_beats = None
    if str(wallet_flow_vs_llm.get("status") or "").lower() == "ready" and wallet_delta is not None:
        wallet_beats = _safe_float(wallet_delta, 0.0) > 0.0

    combined_beats = combined_vs_single.get("combined_sources_beat_single_source_lanes")
    lane_source_status = "not_audited"
    lane_source_reason = "no_lane_specific_signal_source_comparison"

    if lane == "wallet_flow":
        winner = wallet_flow_vs_llm.get("winner")
        status = str(wallet_flow_vs_llm.get("status") or "").lower()
        if status == "ready":
            lane_source_status = "winning" if winner == "wallet_flow" else "lagging" if winner == "llm_only" else "tied"
            lane_source_reason = f"wallet_flow_vs_llm winner={winner}"
        else:
            lane_source_status = "unknown"
            lane_source_reason = f"wallet_flow_vs_llm status={status or 'missing'}"
    elif lane == "llm_only":
        winner = wallet_flow_vs_llm.get("winner")
        status = str(wallet_flow_vs_llm.get("status") or "").lower()
        if status == "ready":
            lane_source_status = "winning" if winner == "llm_only" else "lagging" if winner == "wallet_flow" else "tied"
            lane_source_reason = f"wallet_flow_vs_llm winner={winner}"
        else:
            lane_source_status = "unknown"
            lane_source_reason = f"wallet_flow_vs_llm status={status or 'missing'}"
    elif lane == "combined":
        winner = combined_vs_single.get("winner")
        status = str(combined_vs_single.get("status") or "").lower()
        if status == "ready":
            lane_source_status = "winning" if winner == "combined" else "lagging" if winner == "single_source" else "tied"
            lane_source_reason = f"combined_sources_vs_single_source winner={winner}"
        else:
            lane_source_status = "unknown"
            lane_source_reason = f"combined_sources_vs_single_source status={status or 'missing'}"

    return {
        "signal_source_audit_loaded": True,
        "wallet_flow_beats_llm_only": wallet_beats,
        "combined_sources_beat_single_source_lanes": combined_beats,
        "lane_source_status": lane_source_status,
        "lane_source_reason": lane_source_reason,
        "best_component_source": best_component_source.get("source"),
        "best_component_source_win_rate": best_component_source.get("win_rate"),
        "best_source_combo": best_source_combo.get("source_combo"),
        "best_source_combo_win_rate": best_source_combo.get("win_rate"),
    }


def _build_btc5_venue_entry(
    *,
    runtime_truth_path: Path,
    public_runtime_snapshot_path: Path,
    btc5_autoresearch_path: Path,
    now: datetime,
) -> dict[str, Any]:
    runtime_truth = _load_json_dict(runtime_truth_path) or {}
    public_runtime_snapshot = _load_json_dict(public_runtime_snapshot_path) or {}
    forecast_payload = _load_json_dict(btc5_autoresearch_path) or {}
    runtime_block = runtime_truth.get("runtime") or {}
    strategy_recommendations = (
        runtime_truth.get("state_improvement", {}).get("strategy_recommendations")
        or public_runtime_snapshot.get("state_improvement", {}).get("strategy_recommendations")
        or {}
    )
    public_scoreboard = strategy_recommendations.get("public_performance_scoreboard") or {}
    launch = runtime_truth.get("launch") or public_runtime_snapshot.get("launch") or {}
    blocked_checks = [str(check) for check in launch.get("blocked_checks") or []]
    fund_blockers = [check for check in blocked_checks if check in FUND_BLOCKING_CHECKS]
    forecast_selected = (forecast_payload.get("public_forecast_selection") or {}).get("selected") or {}
    forecast_generated_at = forecast_selected.get("generated_at") or forecast_payload.get("generated_at")
    latest_live_filled_at = (
        runtime_block.get("latest_live_filled_at")
        or runtime_truth.get("latest_live_filled_at")
        or public_runtime_snapshot.get("latest_live_filled_at")
    )
    freshness_hours = _max_freshness_hours(
        [
            runtime_truth.get("generated_at") or public_runtime_snapshot.get("generated_at"),
            latest_live_filled_at,
            forecast_generated_at,
        ],
        now=now,
    )
    is_stale = freshness_hours is None or freshness_hours > VENUE_STALE_HOURS
    deploy_recommendation = str(
        forecast_payload.get("deploy_recommendation")
        or forecast_selected.get("deploy_recommendation")
        or public_scoreboard.get("deploy_recommendation")
        or "hold"
    ).lower()
    confidence_label = str(
        forecast_payload.get("package_confidence_label")
        or forecast_selected.get("package_confidence_label")
        or public_scoreboard.get("forecast_confidence_label")
        or "low"
    ).lower()
    trailing_window_pnl_usd = _safe_float(
        public_scoreboard.get("realized_btc5_sleeve_window_pnl_usd"),
        runtime_block.get("btc5_recent_live_filled_pnl_usd"),
    )
    trailing_window_live_fills = int(
        public_scoreboard.get("realized_btc5_sleeve_window_live_fills")
        or runtime_block.get("btc5_recent_live_filled_rows")
        or 0
    )
    trailing_window_hours = _safe_float(
        public_scoreboard.get("realized_btc5_sleeve_window_hours"),
        0.0,
    )
    live_filled_rows = int(runtime_block.get("btc5_live_filled_rows") or 0)
    live_filled_pnl_usd = _safe_float(runtime_block.get("btc5_live_filled_pnl_usd"), 0.0)
    validation_live_filled_rows = int(
        forecast_selected.get("validation_live_filled_rows")
        or forecast_payload.get("validation_live_filled_rows")
        or 0
    )
    trailing_window_positive = trailing_window_live_fills >= 12 and trailing_window_pnl_usd > 0.0

    capital_status = "hold"
    if not is_stale and deploy_recommendation == "promote" and confidence_label == "high" and trailing_window_positive:
        capital_status = "ready_scale" if not fund_blockers else "ready_test_tranche"

    reasons: list[str] = []
    blocking_checks: list[str] = []
    if trailing_window_positive:
        reasons.append(
            "Trailing 12 live-filled BTC5 rows are net positive "
            f"({trailing_window_live_fills} fills, ${trailing_window_pnl_usd:.4f})."
        )
    else:
        blocking_checks.append("btc5_trailing_12_live_fills_not_positive")
        reasons.append(
            "Trailing 12 live-filled BTC5 rows are not net positive "
            f"({trailing_window_live_fills} fills, ${trailing_window_pnl_usd:.4f})."
        )
    if deploy_recommendation == "promote" and confidence_label == "high":
        reasons.append("BTC5 forecast remains `promote` with `high` confidence.")
    else:
        blocking_checks.append("btc5_forecast_not_promote_high")
        reasons.append(
            "BTC5 forecast is not simultaneously `promote` and `high` confidence "
            f"(deploy_recommendation={deploy_recommendation}, confidence_label={confidence_label})."
        )
    if is_stale:
        blocking_checks.append("btc5_artifacts_stale")
        reasons.append(
            f"BTC5 runtime or forecast evidence is stale for venue allocation ({freshness_hours}h old)."
        )
    if fund_blockers:
        blocking_checks.extend(fund_blockers)
        reasons.append(
            "Fund capital truth is still blocked by "
            + ", ".join(f"`{check}`" for check in fund_blockers)
            + "."
        )

    ranking_score = 0.0
    if not is_stale:
        ranking_score += 30.0
    if confidence_label == "high":
        ranking_score += 30.0
    elif confidence_label == "medium":
        ranking_score += 18.0
    else:
        ranking_score += 6.0
    if deploy_recommendation == "promote":
        ranking_score += 20.0
    elif deploy_recommendation == "shadow_only":
        ranking_score += 10.0
    if trailing_window_positive:
        ranking_score += 20.0
    ranking_score += min(max(trailing_window_pnl_usd, -25.0), 25.0)
    if fund_blockers:
        ranking_score -= 15.0

    return {
        "venue": "polymarket",
        "lane": "btc5",
        "confidence_label": "high"
        if capital_status in {"ready_test_tranche", "ready_scale"}
        else "medium"
        if not is_stale and trailing_window_positive
        else "low",
        "deployment_readiness": capital_status,
        "freshness_hours": freshness_hours,
        "sample_size_summary": {
            "live_filled_rows": live_filled_rows,
            "validation_live_filled_rows": validation_live_filled_rows,
            "trailing_window_live_fills": trailing_window_live_fills,
            "trailing_window_hours": trailing_window_hours,
        },
        "ranking_score": round(ranking_score, 6),
        "settlement_match_rate": None,
        "capital_status": capital_status,
        "recommended_amount_usd": 100 if capital_status == "ready_test_tranche" else 1000 if capital_status == "ready_scale" else 0,
        "basis_window_fills": trailing_window_live_fills,
        "basis_window_pnl_usd": round(trailing_window_pnl_usd, 4),
        "basis_window_hours": trailing_window_hours,
        "live_filled_pnl_usd": round(live_filled_pnl_usd, 4),
        "deploy_recommendation": deploy_recommendation,
        "forecast_confidence_label": confidence_label,
        "blocking_checks": blocking_checks,
        "reasons": reasons,
        "source_artifacts": [
            str(runtime_truth_path),
            str(public_runtime_snapshot_path),
            str(btc5_autoresearch_path),
        ],
    }


def _build_kalshi_weather_entry(
    *,
    kalshi_weather_lane_path: Path,
    kalshi_orders_path: Path,
    kalshi_settlements_path: Path,
    kalshi_decisions_path: Path,
    now: datetime,
) -> dict[str, Any]:
    weather_payload = _load_json_dict(kalshi_weather_lane_path) or {}
    order_rows = _load_jsonl_rows(kalshi_orders_path)
    settlement_reconciliation = weather_payload.get("settlement_reconciliation") or {}
    operator_guidance = weather_payload.get("operator_guidance") or {}
    paper_mode = str(
        (operator_guidance.get("paper_trade_parameters") or {}).get("mode")
        or operator_guidance.get("mode")
        or ""
    ).lower() == "paper"
    match_rate = _safe_float(
        settlement_reconciliation.get("match_rate"),
        0.0,
    )
    matched_settlements = int(
        settlement_reconciliation.get("matched_settlements")
        or settlement_reconciliation.get("matched_decisions")
        or 0
    )
    unmatched_settlements = int(
        settlement_reconciliation.get("unmatched_settlements")
        or settlement_reconciliation.get("unmatched_decisions")
        or 0
    )
    live_orders_logged = 0
    unique_exposures: set[tuple[str, str]] = set()
    latest_order_timestamp: str | None = None
    for row in order_rows:
        order = row.get("order") or {}
        status = str(order.get("status") or row.get("execution_result") or "").lower()
        if status == "live":
            live_orders_logged += 1
        ticker = str(order.get("ticker") or row.get("market_ticker") or "")
        side = str(order.get("side") or row.get("side") or "")
        if ticker and side:
            unique_exposures.add((ticker, side))
        row_timestamp = row.get("timestamp") or (row.get("signal") or {}).get("timestamp")
        if latest_order_timestamp is None:
            latest_order_timestamp = str(row_timestamp or "")
            continue
        candidate = _parse_timestamp(row_timestamp)
        baseline = _parse_timestamp(latest_order_timestamp)
        if candidate is not None and (baseline is None or candidate > baseline):
            latest_order_timestamp = str(row_timestamp)

    recommended_strategy = str(weather_payload.get("recommended_strategy") or "")
    robustness_summary = weather_payload.get("robustness_summary") or {}
    recommended_summary = robustness_summary.get(recommended_strategy) or {}
    freshness_hours = _max_freshness_hours(
        [weather_payload.get("generated_at"), latest_order_timestamp],
        now=now,
    )
    is_stale = freshness_hours is None or freshness_hours > VENUE_STALE_HOURS
    settlements_present = kalshi_settlements_path.exists()
    decisions_present = kalshi_decisions_path.exists()
    blocking_checks: list[str] = []
    reasons: list[str] = []
    if is_stale:
        blocking_checks.append("kalshi_weather_artifacts_stale")
        reasons.append(
            f"Kalshi weather evidence is stale for venue allocation ({freshness_hours}h old)."
        )
    if paper_mode:
        blocking_checks.append("kalshi_weather_paper_mode_guidance")
        reasons.append("Operator guidance is still paper-mode only.")
    if not settlements_present:
        blocking_checks.append("kalshi_weather_settlement_log_missing")
        reasons.append("Settlement reconciliation log is missing.")
    if not decisions_present:
        blocking_checks.append("kalshi_weather_decisions_log_missing")
        reasons.append("Decisions log is missing.")
    if match_rate <= 0.0:
        blocking_checks.append("kalshi_weather_settlement_match_rate_zero")
        reasons.append("Settlement match rate is still 0.0.")

    ranking_score = 0.0
    if not is_stale:
        ranking_score += 10.0
    ranking_score += 10.0 * _safe_float(recommended_summary.get("positive_scenario_ratio"), 0.0)
    ranking_score += min(max(_safe_float(recommended_summary.get("median_total_pnl_usd"), 0.0) / 5.0, -10.0), 20.0)
    ranking_score += min(len(order_rows) / 10.0, 10.0)
    if paper_mode:
        ranking_score -= 15.0
    if not settlements_present:
        ranking_score -= 25.0
    if not decisions_present:
        ranking_score -= 10.0
    if match_rate <= 0.0:
        ranking_score -= 25.0
    if is_stale:
        ranking_score -= 15.0

    return {
        "venue": "kalshi",
        "lane": "weather",
        "confidence_label": "low",
        "deployment_readiness": "hold",
        "freshness_hours": freshness_hours,
        "sample_size_summary": {
            "orders_logged": len(order_rows),
            "live_orders_logged": live_orders_logged,
            "unique_exposures": len(unique_exposures),
            "matched_settlements": matched_settlements,
            "unmatched_settlements": unmatched_settlements,
            "scenario_count": int(recommended_summary.get("scenario_count") or 0),
        },
        "ranking_score": round(ranking_score, 6),
        "settlement_match_rate": match_rate,
        "capital_status": "hold",
        "recommended_amount_usd": 0,
        "blocking_checks": blocking_checks,
        "reasons": reasons,
        "recommended_strategy": recommended_strategy or None,
        "source_artifacts": [
            str(kalshi_weather_lane_path),
            str(kalshi_orders_path),
            str(kalshi_settlements_path),
            str(kalshi_decisions_path),
        ],
    }


def _build_capital_allocation_recommendation(
    venue_scoreboard: list[dict[str, Any]],
    *,
    runtime_truth_path: Path,
    btc5_autoresearch_path: Path,
    kalshi_weather_lane_path: Path,
) -> dict[str, Any]:
    best_first = sorted(
        venue_scoreboard,
        key=lambda item: (_safe_float(item.get("ranking_score"), float("-inf")), item.get("venue"), item.get("lane")),
        reverse=True,
    )
    btc5_entry = next((item for item in best_first if item.get("venue") == "polymarket" and item.get("lane") == "btc5"), None)
    kalshi_entry = next((item for item in best_first if item.get("venue") == "kalshi" and item.get("lane") == "weather"), None)

    next_100 = {
        "status": "hold",
        "venue": None,
        "lane": None,
        "recommended_amount_usd": 0,
        "confidence_label": "low",
        "reasons": ["No venue currently clears even the test-tranche bar."],
        "blocking_checks": [],
        "source_artifacts": [],
    }
    if btc5_entry and btc5_entry.get("capital_status") in {"ready_test_tranche", "ready_scale"}:
        next_100 = {
            "status": "ready_test_tranche",
            "venue": "polymarket",
            "lane": "btc5",
            "recommended_amount_usd": 100,
            "confidence_label": btc5_entry.get("confidence_label"),
            "reasons": [
                "BTC5 is the top-ranked venue and the only lane that clears the current test-tranche bar.",
                "Hold the full $1,000 until fund reconciliation and capital truth drift are resolved.",
            ],
            "blocking_checks": [],
            "source_artifacts": btc5_entry.get("source_artifacts") or [],
        }

    next_1000 = {
        "status": "hold",
        "venue": None,
        "lane": None,
        "recommended_amount_usd": 0,
        "confidence_label": btc5_entry.get("confidence_label") if btc5_entry else "low",
        "reasons": ["Do not add the next $1,000 while fund-level capital truth is still blocked."],
        "blocking_checks": list(btc5_entry.get("blocking_checks") or []) if btc5_entry else [],
        "source_artifacts": [
            str(runtime_truth_path),
            str(btc5_autoresearch_path),
            str(kalshi_weather_lane_path),
        ],
    }
    if btc5_entry and btc5_entry.get("capital_status") == "ready_scale":
        next_1000 = {
            "status": "ready_scale",
            "venue": "polymarket",
            "lane": "btc5",
            "recommended_amount_usd": 1000,
            "confidence_label": btc5_entry.get("confidence_label"),
            "reasons": ["BTC5 is top-ranked and fund capital truth no longer blocks scaling."],
            "blocking_checks": [],
            "source_artifacts": btc5_entry.get("source_artifacts") or [],
        }

    overall_recommendation = "hold_full_1000"
    if next_100.get("status") == "ready_test_tranche":
        overall_recommendation = "btc5_test_tranche_only"
    if next_1000.get("status") == "ready_scale":
        overall_recommendation = "btc5_scale_add"

    return {
        "overall_recommendation": overall_recommendation,
        "ranked_venues": [f"{item.get('venue')}:{item.get('lane')}" for item in best_first],
        "next_100_usd": next_100,
        "next_1000_usd": next_1000,
        "kalshi_weather_status": kalshi_entry.get("capital_status") if kalshi_entry else "hold",
    }


def _attach_venue_scoreboard(
    report: dict[str, Any],
    *,
    runtime_truth_path: Path,
    public_runtime_snapshot_path: Path,
    btc5_autoresearch_path: Path,
    kalshi_weather_lane_path: Path,
    kalshi_orders_path: Path,
    kalshi_settlements_path: Path,
    kalshi_decisions_path: Path,
) -> dict[str, Any]:
    now = _utc_now()
    venue_scoreboard = [
        _build_btc5_venue_entry(
            runtime_truth_path=runtime_truth_path,
            public_runtime_snapshot_path=public_runtime_snapshot_path,
            btc5_autoresearch_path=btc5_autoresearch_path,
            now=now,
        ),
        _build_kalshi_weather_entry(
            kalshi_weather_lane_path=kalshi_weather_lane_path,
            kalshi_orders_path=kalshi_orders_path,
            kalshi_settlements_path=kalshi_settlements_path,
            kalshi_decisions_path=kalshi_decisions_path,
            now=now,
        ),
    ]
    venue_scoreboard.sort(
        key=lambda item: (_safe_float(item.get("ranking_score"), float("-inf")), item.get("venue"), item.get("lane")),
        reverse=True,
    )
    report["venue_scoreboard"] = venue_scoreboard
    report["capital_allocation_recommendation"] = _build_capital_allocation_recommendation(
        venue_scoreboard,
        runtime_truth_path=runtime_truth_path,
        btc5_autoresearch_path=btc5_autoresearch_path,
        kalshi_weather_lane_path=kalshi_weather_lane_path,
    )
    return report


def _attach_scoreboard(
    report: dict[str, Any],
    audit_payload: dict[str, Any] | None,
    *,
    signal_source_audit_path: Path | None,
) -> dict[str, Any]:
    scoreboard: dict[str, dict[str, Any]] = {}
    ranking: list[dict[str, Any]] = []
    lane_evidence = report.get("lane_evidence") or {}
    results = report.get("results") or {}

    for lane, evidence in lane_evidence.items():
        lane_status = str(evidence.get("status") or "insufficient_data")
        evidence_summary = evidence.get("evidence_summary") or {}
        sample_size_summary = _lane_sample_size_summary(evidence_summary)
        confidence_label = _lane_confidence_label(
            lane_status=lane_status,
            sample_size_summary=sample_size_summary,
        )
        readiness = _deployment_readiness(lane_status=lane_status, confidence_label=confidence_label)
        score, median_return_pct, p05_return_pct, max_drawdown_pct = _ranking_score(
            lane_status=lane_status,
            confidence_label=confidence_label,
            lane_results=results.get(lane) or {},
        )
        source_evidence = _source_evidence_from_audit(audit_payload, lane)
        entry = {
            "lane": lane,
            "status": lane_status,
            "confidence_label": confidence_label,
            "deployment_readiness": readiness,
            "ranking_score": score,
            "sample_size_summary": sample_size_summary,
            "timebound_evidence_window": evidence_summary.get("timebound_evidence_window")
            or _empty_timebound_evidence_window(),
            "median_return_pct": median_return_pct,
            "p05_return_pct": p05_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "source_evidence": source_evidence,
        }
        scoreboard[lane] = entry
        if score is not None:
            ranking.append(entry)
    ranking.sort(key=lambda item: (_safe_float(item.get("ranking_score"), float("-inf")), item.get("lane")), reverse=True)

    report["scoreboard"] = scoreboard
    report["ranking"] = ranking
    report["source_audit"] = {
        "loaded": bool(audit_payload),
        "path": str(signal_source_audit_path) if signal_source_audit_path is not None else None,
        "ranking_snapshot": (audit_payload or {}).get("ranking_snapshot"),
        "capital_ranking_support": (audit_payload or {}).get("capital_ranking_support"),
        "freshness_hours": _freshness_hours((audit_payload or {}).get("generated_at"), now=_utc_now()),
        "stale_for_venue_allocation": (
            _freshness_hours((audit_payload or {}).get("generated_at"), now=_utc_now()) is not None
            and _freshness_hours((audit_payload or {}).get("generated_at"), now=_utc_now()) > VENUE_STALE_HOURS
        ),
    }
    return report


def write_report(report: dict[str, Any], json_output_path: Path, markdown_output_path: Path) -> None:
    """Write the JSON and Markdown artifacts."""

    json_output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_output_path.parent.mkdir(parents=True, exist_ok=True)

    json_output_path.write_text(json.dumps(report, indent=2))
    markdown_output_path.write_text(render_markdown(report))


def write_wallet_flow_archive(archive: dict[str, Any], output_path: Path) -> None:
    """Persist wallet-flow replay archive to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(archive, indent=2))


def render_markdown(report: dict[str, Any]) -> str:
    """Render the scale-comparison payload as Markdown."""

    lines: list[str] = []
    lines.append("# Strategy Scale Comparison")
    lines.append("")

    lines.append("## Lane Scoreboard")
    lines.append("")
    lines.append(
        "| Lane | Status | Confidence | Deployment Readiness | Ranking Score | Replayable | Unique Markets | "
        "Resolved | Window Hrs | Source Status | Median Return | P05 Return | Max Drawdown |"
    )
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|")
    for lane in ("llm_only", "wallet_flow", "lmsr", "cross_platform_arb", "combined"):
        item = (report.get("scoreboard") or {}).get(lane) or {}
        sample_size_summary = item.get("sample_size_summary") or {}
        evidence_window = item.get("timebound_evidence_window") or {}
        source_evidence = item.get("source_evidence") or {}
        ranking_score = item.get("ranking_score")
        ranking_text = f"{ranking_score:.6f}" if isinstance(ranking_score, float) else "—"
        elapsed_hours = evidence_window.get("elapsed_hours")
        elapsed_hours_text = f"{_safe_float(elapsed_hours, 0.0):.2f}" if elapsed_hours is not None else "—"
        lines.append(
            "| "
            + f"{lane} | {item.get('status', 'insufficient_data')} | {item.get('confidence_label', 'low')} | "
            + f"{item.get('deployment_readiness', 'insufficient_data')} | {ranking_text} | "
            + f"{int(sample_size_summary.get('replayable_opportunities', 0) or 0)} | "
            + f"{int(sample_size_summary.get('unique_markets', 0) or 0)} | "
            + f"{int(sample_size_summary.get('resolved_signals', 0) or 0)} | "
            + f"{elapsed_hours_text} | "
            + f"{source_evidence.get('lane_source_status', 'unknown')} | "
            + f"{_safe_float(item.get('median_return_pct'), 0.0):.2%} | "
            + f"{_safe_float(item.get('p05_return_pct'), 0.0):.2%} | "
            + f"{_safe_float(item.get('max_drawdown_pct'), 0.0):.2%} |"
        )
    lines.append("")
    source_evidence = ((report.get("scoreboard") or {}).get("llm_only") or {}).get("source_evidence") or {}
    if source_evidence:
        lines.append("Signal-source audit evidence:")
        lines.append(f"- wallet_flow_beats_llm_only: {source_evidence.get('wallet_flow_beats_llm_only')}")
        lines.append(
            "- combined_sources_beat_single_source_lanes: "
            + str(source_evidence.get("combined_sources_beat_single_source_lanes"))
        )
        lines.append(f"- best_component_source: {source_evidence.get('best_component_source')}")
        lines.append(f"- best_source_combo: {source_evidence.get('best_source_combo')}")
        lines.append("")
    venue_scoreboard = report.get("venue_scoreboard") or []
    if venue_scoreboard:
        lines.append("## Venue Capital Scoreboard")
        lines.append("")
        lines.append(
            "| Venue | Lane | Capital Status | Confidence | Deployment Readiness | Freshness Hrs | Ranking Score | Settlement Match | Sample Size |"
        )
        lines.append("|---|---|---|---|---|---:|---:|---:|---|")
        for item in venue_scoreboard:
            freshness_text = (
                f"{_safe_float(item.get('freshness_hours'), 0.0):.2f}"
                if item.get("freshness_hours") is not None
                else "—"
            )
            ranking_text = f"{_safe_float(item.get('ranking_score'), 0.0):.2f}"
            settlement_match = item.get("settlement_match_rate")
            settlement_text = f"{_safe_float(settlement_match, 0.0):.2%}" if settlement_match is not None else "—"
            sample_text = ", ".join(
                f"{key}={value}"
                for key, value in (item.get("sample_size_summary") or {}).items()
            )
            lines.append(
                "| "
                + f"{item.get('venue')} | {item.get('lane')} | {item.get('capital_status')} | "
                + f"{item.get('confidence_label')} | {item.get('deployment_readiness')} | {freshness_text} | "
                + f"{ranking_text} | {settlement_text} | {sample_text} |"
            )
        lines.append("")
    capital_allocation = report.get("capital_allocation_recommendation") or {}
    if capital_allocation:
        lines.append("## Capital Allocation Recommendation")
        lines.append("")
        next_100 = capital_allocation.get("next_100_usd") or {}
        next_1000 = capital_allocation.get("next_1000_usd") or {}
        lines.append(
            "- Where should the next $100 go? "
            + (
                f"{next_100.get('venue')} {next_100.get('lane')} (${int(next_100.get('recommended_amount_usd') or 0)})"
                if next_100.get("venue") and next_100.get("lane")
                else "hold ($0)"
            )
            + "."
        )
        for reason in next_100.get("reasons") or []:
            lines.append(f"  - {reason}")
        lines.append(
            "- Where should the next $1,000 go? "
            + (
                f"{next_1000.get('venue')} {next_1000.get('lane')} (${int(next_1000.get('recommended_amount_usd') or 0)})"
                if next_1000.get("venue") and next_1000.get("lane")
                else "hold ($0)"
            )
            + "."
        )
        for reason in next_1000.get("reasons") or []:
            lines.append(f"  - {reason}")
        lines.append("")
    lines.append(f"- Generated: {report['generated_at']}")
    lines.append(f"- Repo truth date: {report['as_of_date']}")
    lines.append(
        "- Conservative caps: "
        f"${report['risk_caps']['max_position_usd']:.0f} max position, "
        f"{report['risk_caps']['llm_kelly_fraction']:.2f} LLM Kelly fraction, "
        f"{report['risk_caps']['fast_kelly_fraction']:.4f} fast-lane Kelly fraction, "
        f"{report['risk_caps']['max_allocation_pct']:.0%} max allocation."
    )
    lines.append(
        "- Execution replay: "
        f"{report['execution_assumptions']['simulator_mode']} fills from `simulator/`, "
        f"LLM entry baseline {report['execution_assumptions']['entry_price_baseline_llm']:.2f}."
    )
    lines.append("")

    lines.append("## Current Readiness")
    for lane in ("llm_only", "wallet_flow", "lmsr", "cross_platform_arb", "combined"):
        evidence = report["lane_evidence"][lane]
        status = evidence["status"]
        if status == "ready":
            summary = evidence["evidence_summary"]
            if lane == "combined":
                lines.append(
                    f"- `{lane}`: ready; includes {', '.join(summary.get('included_lanes', [])) or 'no lanes'}."
                )
            else:
                lines.append(f"- `{lane}`: ready.")
        else:
            lines.append(f"- `{lane}`: `insufficient_data`.")
            for reason in evidence["reasons"]:
                lines.append(f"  - {reason}")
    lines.append("")

    for bankroll in report["bankrolls"]:
        lines.append(f"## Starting Bankroll ${bankroll:,.0f}")
        lines.append("")
        lines.append("| Lane | Status | Return | Max Drawdown | Trades | Capital Utilization | Fee Drag | Notes |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---|")

        for lane in ("llm_only", "wallet_flow", "lmsr", "cross_platform_arb", "combined"):
            result = report["results"][lane][str(bankroll)]
            if result["status"] == "simulated":
                note = ""
                if lane == "combined":
                    combined_meta = report["lane_evidence"]["combined"]["evidence_summary"]
                    note = "included: " + ", ".join(combined_meta.get("included_lanes", []))
                lines.append(
                    "| "
                    f"{lane} | simulated | {result['return_pct']:.2%} | {result['max_drawdown_pct']:.2%} "
                    f"(${result['max_drawdown_usd']:.2f}) | {result['trade_count']} | "
                    f"{result['capital_utilization_pct']:.2%} | {result['fee_drag_pct']:.2%} | {note} |"
                )
            else:
                reason = "; ".join(result.get("reasons", []))
                lines.append(
                    f"| {lane} | insufficient_data | — | — | — | — | — | {reason} |"
                )
        lines.append("")

    lines.append("## Assumptions")
    assumptions = _dedupe_preserve_order(
        assumption
        for evidence in report["lane_evidence"].values()
        for assumption in evidence.get("assumptions", [])
    )
    for assumption in assumptions:
        lines.append(f"- {assumption}")
    lines.append("")

    lines.append("## Evidence Summary")
    for lane in ("llm_only", "wallet_flow", "lmsr", "cross_platform_arb", "combined"):
        lines.append(f"### {lane}")
        summary = report["lane_evidence"][lane]["evidence_summary"]
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_scale_comparison(
    bankrolls: list[float] | None = None,
    json_output_path: Path = DEFAULT_JSON_PATH,
    markdown_output_path: Path = DEFAULT_MARKDOWN_PATH,
    wallet_flow_archive_path: Path | None = None,
    signal_source_audit_path: Path | None = DEFAULT_SIGNAL_SOURCE_AUDIT_PATH,
    runtime_truth_path: Path = DEFAULT_RUNTIME_TRUTH_PATH,
    public_runtime_snapshot_path: Path = DEFAULT_PUBLIC_RUNTIME_SNAPSHOT_PATH,
    btc5_autoresearch_path: Path = DEFAULT_BTC5_AUTORESEARCH_PATH,
    kalshi_weather_lane_path: Path = DEFAULT_KALSHI_WEATHER_LANE_PATH,
    kalshi_orders_path: Path = DEFAULT_KALSHI_ORDERS_PATH,
    kalshi_settlements_path: Path = DEFAULT_KALSHI_SETTLEMENTS_PATH,
    kalshi_decisions_path: Path = DEFAULT_KALSHI_DECISIONS_PATH,
) -> dict[str, Any]:
    """Public entry point for tests and the CLI."""

    bankrolls = bankrolls or DEFAULT_BANKROLLS
    report = build_report(
        [float(bankroll) for bankroll in bankrolls],
        wallet_flow_archive_path=wallet_flow_archive_path,
    )
    report = _attach_scoreboard(
        report,
        _load_signal_source_audit(signal_source_audit_path),
        signal_source_audit_path=signal_source_audit_path,
    )
    report = _attach_venue_scoreboard(
        report,
        runtime_truth_path=runtime_truth_path,
        public_runtime_snapshot_path=public_runtime_snapshot_path,
        btc5_autoresearch_path=btc5_autoresearch_path,
        kalshi_weather_lane_path=kalshi_weather_lane_path,
        kalshi_orders_path=kalshi_orders_path,
        kalshi_settlements_path=kalshi_settlements_path,
        kalshi_decisions_path=kalshi_decisions_path,
    )
    write_report(report, json_output_path=json_output_path, markdown_output_path=markdown_output_path)
    return report


def _dedupe_preserve_order(values: Any) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare strategy scale outcomes at multiple bankrolls.")
    parser.add_argument(
        "--bankrolls",
        nargs="+",
        type=float,
        default=DEFAULT_BANKROLLS,
        help="Starting bankrolls in USD (default: 1000 10000 100000)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"JSON output path (default: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_PATH,
        help=f"Markdown output path (default: {DEFAULT_MARKDOWN_PATH})",
    )
    parser.add_argument(
        "--wallet-flow-archive",
        type=Path,
        default=DEFAULT_WALLET_FLOW_ARCHIVE_PATH,
        help=(
            "Optional wallet-flow replay archive path. "
            "If present and valid, it is loaded; otherwise a fresh archive is built and written."
        ),
    )
    parser.add_argument(
        "--signal-source-audit",
        type=Path,
        default=DEFAULT_SIGNAL_SOURCE_AUDIT_PATH,
        help=(
            "Optional signal-source audit JSON path. "
            "When present, scoreboard includes wallet-flow-vs-LLM and combined-source evidence."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(logging.WARNING)
    edge_cfg = load_edge_config()
    archive, _ = load_or_build_wallet_flow_archive(
        db_path=edge_cfg.system.db_path,
        archive_path=args.wallet_flow_archive,
    )
    write_wallet_flow_archive(archive, args.wallet_flow_archive)
    report = run_scale_comparison(
        bankrolls=args.bankrolls,
        json_output_path=args.json_output,
        markdown_output_path=args.markdown_output,
        wallet_flow_archive_path=args.wallet_flow_archive,
        signal_source_audit_path=args.signal_source_audit,
    )
    combined = report["lane_evidence"]["combined"]["evidence_summary"]
    included = ", ".join(combined.get("included_lanes", [])) or "none"
    print(f"Wrote {args.json_output}")
    print(f"Wrote {args.markdown_output}")
    print(f"Combined executable lanes: {included}")


if __name__ == "__main__":
    main()
