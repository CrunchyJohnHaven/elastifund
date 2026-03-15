"""Scenario simulator for late-day Kalshi weather strategies.

This module is intentionally a scenario simulator, not a quote-history backtest.
It uses real point-in-time weather observations and official settlement highs from
``research/weather_validation/``, then prices synthetic Kalshi contracts with an
explicit "stale market" model so candidate weather strategies can be compared
without inventing historical Kalshi order books that do not exist in the repo.

The main purpose is to answer a practical ranking question:

- Is weather the next non-BTC lane worth adding?
- If yes, which weather style looks strongest under transparent assumptions?

Default comparison set:

- ``range_fade``: fade tight 2-degree range buckets when the nowcast disagrees.
- ``range_tail_yes``: buy cheap underpriced range tails when the nowcast has room.
- ``binary_threshold``: trade threshold contracts (``X or above``) when the same
  nowcast finds a cleaner directional edge.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .weather_arb import (
    DECISIONS_LOG,
    FORECAST_SNAPSHOT_LOG,
    SETTLEMENT_LOG,
    ForecastSnapshot,
    _kelly_size_usd,
    build_weather_signal,
    load_forecast_snapshot_archive,
    reconcile_decisions_with_settlements,
    temperature_probability,
)

ROOT = Path(__file__).resolve().parent.parent
WEATHER_VALIDATION_DIR = ROOT / "research" / "weather_validation"
RAW_ASOS_DIR = WEATHER_VALIDATION_DIR / "raw_asos"
NWS_DAILY_DIR = WEATHER_VALIDATION_DIR / "nws_daily"

DEFAULT_DECISION_HOURS_UTC = [18, 20, 22]
DEFAULT_MARKET_STD_MULTIPLIERS = [1.0, 1.15, 1.30]
DEFAULT_MARKET_INFORMATION_RATIO = 0.50
DEFAULT_MIN_TRAINING_DAYS = 20
DEFAULT_EDGE_THRESHOLD = 0.05
DEFAULT_MAX_SPREAD = 0.05
DEFAULT_SPREAD = 0.02
DEFAULT_BANKROLL_USD = 100.0
DEFAULT_MAX_ORDER_USD = 5.0
DEFAULT_KELLY_FRACTION = 0.25
DEFAULT_MAX_SIGNALS_PER_DAY = 1
DEFAULT_TAIL_YES_MAX_PRICE = 0.20
DEFAULT_CONTRACT_RADIUS_DEGREES = 6
DEFAULT_MIN_ORDER_USD = 1.0
MIN_MODEL_STD_F = 1.0
MIN_MARKET_STD_F = 1.0

STATION_META = {
    "NYC": {
        "city_code": "NYC",
        "display": "NYC",
        "ticker_prefix": "KXHIGHNY",
    },
    "ORD": {
        "city_code": "CHI",
        "display": "Chicago",
        "ticker_prefix": "KXHIGHCHI",
    },
    "AUS": {
        "city_code": "AUS",
        "display": "Austin",
        "ticker_prefix": "KXHIGHAUS",
    },
}


@dataclass(frozen=True)
class StationHistory:
    station_code: str
    city_code: str
    display_name: str
    ticker_prefix: str
    hourly_by_day: dict[str, list[tuple[datetime, float]]]
    official_high_by_day: dict[str, float]


@dataclass(frozen=True)
class DecisionSnapshot:
    station_code: str
    city_code: str
    display_name: str
    ticker_prefix: str
    target_date: str
    decision_hour_utc: int
    observed_max_f: float
    final_high_f: float


@dataclass(frozen=True)
class ScenarioSpec:
    decision_hour_utc: int
    market_std_multiplier: float
    market_information_ratio: float = DEFAULT_MARKET_INFORMATION_RATIO
    min_training_days: int = DEFAULT_MIN_TRAINING_DAYS
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD
    max_spread: float = DEFAULT_MAX_SPREAD
    spread: float = DEFAULT_SPREAD
    bankroll_usd: float = DEFAULT_BANKROLL_USD
    max_order_usd: float = DEFAULT_MAX_ORDER_USD
    kelly_fraction: float = DEFAULT_KELLY_FRACTION
    max_signals_per_day: int = DEFAULT_MAX_SIGNALS_PER_DAY
    tail_yes_max_price: float = DEFAULT_TAIL_YES_MAX_PRICE
    contract_radius_degrees: int = DEFAULT_CONTRACT_RADIUS_DEGREES
    min_order_usd: float = DEFAULT_MIN_ORDER_USD

    @property
    def scenario_id(self) -> str:
        return (
            f"h{self.decision_hour_utc}"
            f"_std{self.market_std_multiplier:.2f}"
            f"_info{self.market_information_ratio:.2f}"
        )


@dataclass(frozen=True)
class ContractSpec:
    family: str  # range | above
    kind: str    # range | above
    title: str
    subtitle: str
    lower_f: float
    upper_f: float | None
    market_probability: float
    market: dict[str, Any]


@dataclass(frozen=True)
class TradeCandidate:
    strategy: str
    scenario_id: str
    station_code: str
    city_code: str
    target_date: str
    contract_family: str
    contract_kind: str
    title: str
    side: str
    edge: float
    model_probability: float
    order_probability: float
    observed_max_f: float
    final_high_f: float
    model_point_f: float
    model_std_f: float
    market_point_f: float
    market_std_f: float
    lower_f: float
    upper_f: float | None
    won: bool


@dataclass(frozen=True)
class TradeResult:
    strategy: str
    scenario_id: str
    station_code: str
    target_date: str
    title: str
    side: str
    edge: float
    model_probability: float
    order_probability: float
    won: bool
    size_usd: float
    pnl_usd: float
    bankroll_before_usd: float
    bankroll_after_usd: float
    observed_max_f: float
    final_high_f: float
    model_point_f: float
    market_point_f: float


@dataclass(frozen=True)
class ScenarioSummary:
    strategy: str
    scenario_id: str
    decision_hour_utc: int
    market_std_multiplier: float
    market_information_ratio: float
    raw_candidates: int
    selected_candidates: int
    trades: int
    wins: int
    win_rate: float
    total_pnl_usd: float
    final_bankroll_usd: float
    avg_edge: float
    avg_order_probability: float
    avg_size_usd: float
    max_drawdown_pct: float
    top_examples: list[dict[str, Any]] = field(default_factory=list)


def _parse_float_grid(raw: str) -> list[float]:
    out: list[float] = []
    for piece in str(raw or "").split(","):
        piece = piece.strip()
        if not piece:
            continue
        out.append(float(piece))
    return out


def _parse_int_grid(raw: str) -> list[int]:
    out: list[int] = []
    for piece in str(raw or "").split(","):
        piece = piece.strip()
        if not piece:
            continue
        out.append(int(piece))
    return out


def _load_station_history(station_code: str, *, base_dir: Path = WEATHER_VALIDATION_DIR) -> StationHistory:
    raw_path = base_dir / "raw_asos" / f"{station_code}_asos.csv"
    daily_path = base_dir / "nws_daily" / f"{station_code}_daily.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"missing raw ASOS file: {raw_path}")
    if not daily_path.exists():
        raise FileNotFoundError(f"missing official daily file: {daily_path}")

    hourly_by_day: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    with raw_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(line for line in f if not line.startswith("#"))
        for row in reader:
            temp_raw = str(row.get("tmpf") or "").strip()
            valid = str(row.get("valid") or "").strip()
            if not temp_raw or temp_raw == "M" or not valid:
                continue
            dt = datetime.strptime(valid, "%Y-%m-%d %H:%M")
            hourly_by_day[dt.date().isoformat()].append((dt, float(temp_raw)))

    official_high_by_day = {
        str(row["day"]): float(row["max_tmpf"])
        for row in json.loads(daily_path.read_text(encoding="utf-8"))
        if row.get("day") and row.get("max_tmpf") is not None
    }

    meta = STATION_META[station_code]
    return StationHistory(
        station_code=station_code,
        city_code=meta["city_code"],
        display_name=meta["display"],
        ticker_prefix=meta["ticker_prefix"],
        hourly_by_day={day: sorted(rows, key=lambda item: item[0]) for day, rows in hourly_by_day.items()},
        official_high_by_day=official_high_by_day,
    )


def load_histories(*, base_dir: Path = WEATHER_VALIDATION_DIR) -> dict[str, StationHistory]:
    return {
        station_code: _load_station_history(station_code, base_dir=base_dir)
        for station_code in STATION_META
    }


def build_decision_snapshots(history: StationHistory, decision_hour_utc: int) -> list[DecisionSnapshot]:
    snapshots: list[DecisionSnapshot] = []
    common_days = sorted(set(history.hourly_by_day) & set(history.official_high_by_day))
    for day in common_days:
        rows = history.hourly_by_day[day]
        observed = [temp_f for dt, temp_f in rows if dt.hour <= decision_hour_utc]
        if not observed:
            continue
        snapshots.append(
            DecisionSnapshot(
                station_code=history.station_code,
                city_code=history.city_code,
                display_name=history.display_name,
                ticker_prefix=history.ticker_prefix,
                target_date=day,
                decision_hour_utc=decision_hour_utc,
                observed_max_f=max(observed),
                final_high_f=float(history.official_high_by_day[day]),
            )
        )
    return snapshots


def _estimate_nowcast(prior_snapshots: Iterable[DecisionSnapshot]) -> tuple[float, float]:
    residuals = [snapshot.final_high_f - snapshot.observed_max_f for snapshot in prior_snapshots]
    if not residuals:
        raise ValueError("at least one prior snapshot is required")
    mean_residual = statistics.mean(residuals)
    std_residual = statistics.pstdev(residuals) if len(residuals) > 1 else 0.0
    return mean_residual, max(MIN_MODEL_STD_F, std_residual)


def _clip_probability(value: float) -> float:
    return max(0.01, min(0.99, float(value)))


def _format_event_ticker(prefix: str, target_date: str) -> str:
    dt = datetime.fromisoformat(target_date)
    return f"{prefix}-{dt.strftime('%y%b%d').upper()}"


def _build_synthetic_market(
    *,
    ticker_prefix: str,
    target_date: str,
    title: str,
    subtitle: str,
    slug: str,
    market_probability: float,
    spread: float,
) -> dict[str, Any]:
    midpoint = _clip_probability(market_probability)
    half_spread = max(0.005, float(spread) / 2.0)

    yes_ask = _clip_probability(midpoint + half_spread)
    yes_bid = _clip_probability(min(yes_ask - 0.01, midpoint - half_spread))

    no_midpoint = 1.0 - midpoint
    no_ask = _clip_probability(no_midpoint + half_spread)
    no_bid = _clip_probability(min(no_ask - 0.01, no_midpoint - half_spread))

    event_ticker = _format_event_ticker(ticker_prefix, target_date)
    return {
        "ticker": f"{event_ticker}-{slug}",
        "event_ticker": event_ticker,
        "title": title,
        "subtitle": subtitle,
        "yes_ask": round(yes_ask * 100.0),
        "yes_bid": round(yes_bid * 100.0),
        "no_ask": round(no_ask * 100.0),
        "no_bid": round(no_bid * 100.0),
    }


def generate_contracts(
    *,
    snapshot: DecisionSnapshot,
    model_point_f: float,
    market_point_f: float,
    market_std_f: float,
    spread: float,
    contract_radius_degrees: int,
) -> list[ContractSpec]:
    center = int(2 * round(model_point_f / 2.0))
    start = center - max(2, contract_radius_degrees)
    end = center + max(2, contract_radius_degrees) + 2

    contracts: list[ContractSpec] = []
    for lower in range(start, end, 2):
        upper = lower + 1
        title = (
            f"Will the high temperature in {snapshot.display_name} "
            f"be between {lower} and {upper} degrees?"
        )
        subtitle = f"Between {lower} and {upper}"
        market_probability = temperature_probability(
            market_point_f,
            ("range", float(lower), float(upper)),
            std_f=market_std_f,
        )
        contracts.append(
            ContractSpec(
                family="range",
                kind="range",
                title=title,
                subtitle=subtitle,
                lower_f=float(lower),
                upper_f=float(upper),
                market_probability=market_probability,
                market=_build_synthetic_market(
                    ticker_prefix=snapshot.ticker_prefix,
                    target_date=snapshot.target_date,
                    title=title,
                    subtitle=subtitle,
                    slug=f"R{lower}{upper}",
                    market_probability=market_probability,
                    spread=spread,
                ),
            )
        )

        title = f"Will {snapshot.display_name} high be {lower} or above?"
        subtitle = f"{lower} or above"
        market_probability = temperature_probability(
            market_point_f,
            ("above", float(lower), None),
            std_f=market_std_f,
        )
        contracts.append(
            ContractSpec(
                family="above",
                kind="above",
                title=title,
                subtitle=subtitle,
                lower_f=float(lower),
                upper_f=None,
                market_probability=market_probability,
                market=_build_synthetic_market(
                    ticker_prefix=snapshot.ticker_prefix,
                    target_date=snapshot.target_date,
                    title=title,
                    subtitle=subtitle,
                    slug=f"A{lower}",
                    market_probability=market_probability,
                    spread=spread,
                ),
            )
        )
    return contracts


def resolve_contract(kind: str, lower_f: float, upper_f: float | None, final_high_f: float) -> bool:
    if kind == "above":
        return final_high_f >= lower_f
    if kind == "range":
        assert upper_f is not None
        return lower_f <= final_high_f <= upper_f
    raise ValueError(f"unsupported contract kind: {kind}")


def classify_strategy(
    *,
    contract_family: str,
    side: str,
    order_probability: float,
    tail_yes_max_price: float,
) -> str | None:
    if contract_family == "above":
        return "binary_threshold"
    if contract_family != "range":
        return None
    if side == "no":
        return "range_fade"
    if side == "yes" and order_probability <= tail_yes_max_price:
        return "range_tail_yes"
    return None


def build_trade_candidates(
    histories: dict[str, StationHistory],
    scenario: ScenarioSpec,
) -> list[TradeCandidate]:
    candidates: list[TradeCandidate] = []

    for history in histories.values():
        snapshots = build_decision_snapshots(history, scenario.decision_hour_utc)
        for idx, snapshot in enumerate(snapshots):
            prior = snapshots[:idx]
            if len(prior) < scenario.min_training_days:
                continue

            mean_residual_f, model_std_f = _estimate_nowcast(prior)
            model_point_f = snapshot.observed_max_f + mean_residual_f
            market_point_f = snapshot.observed_max_f + (scenario.market_information_ratio * mean_residual_f)
            market_std_f = max(MIN_MARKET_STD_F, model_std_f * scenario.market_std_multiplier)

            weather_snapshot = ForecastSnapshot(
                city=snapshot.city_code,
                target_date=snapshot.target_date,
                high_temp_f=model_point_f,
                pop_probability=None,
                source_period=f"{scenario.decision_hour_utc:02d}:00 UTC",
            )

            contracts = generate_contracts(
                snapshot=snapshot,
                model_point_f=model_point_f,
                market_point_f=market_point_f,
                market_std_f=market_std_f,
                spread=scenario.spread,
                contract_radius_degrees=scenario.contract_radius_degrees,
            )
            for contract in contracts:
                signal = build_weather_signal(
                    snapshot.city_code,
                    weather_snapshot,
                    contract.market,
                    edge_threshold=scenario.edge_threshold,
                    max_spread=scenario.max_spread,
                    temp_std_f=model_std_f,
                )
                if signal is None:
                    continue

                strategy = classify_strategy(
                    contract_family=contract.family,
                    side=signal.side,
                    order_probability=signal.order_probability,
                    tail_yes_max_price=scenario.tail_yes_max_price,
                )
                if strategy is None:
                    continue

                contract_yes_won = resolve_contract(
                    contract.kind,
                    contract.lower_f,
                    contract.upper_f,
                    snapshot.final_high_f,
                )
                won = contract_yes_won if signal.side == "yes" else (not contract_yes_won)
                candidates.append(
                    TradeCandidate(
                        strategy=strategy,
                        scenario_id=scenario.scenario_id,
                        station_code=snapshot.station_code,
                        city_code=snapshot.city_code,
                        target_date=snapshot.target_date,
                        contract_family=contract.family,
                        contract_kind=contract.kind,
                        title=contract.title,
                        side=signal.side,
                        edge=float(signal.edge),
                        model_probability=float(signal.model_probability),
                        order_probability=float(signal.order_probability),
                        observed_max_f=float(snapshot.observed_max_f),
                        final_high_f=float(snapshot.final_high_f),
                        model_point_f=float(model_point_f),
                        model_std_f=float(model_std_f),
                        market_point_f=float(market_point_f),
                        market_std_f=float(market_std_f),
                        lower_f=float(contract.lower_f),
                        upper_f=float(contract.upper_f) if contract.upper_f is not None else None,
                        won=bool(won),
                    )
                )

    return sorted(
        candidates,
        key=lambda item: (item.target_date, item.strategy, -item.edge, item.station_code, item.title),
    )


def _compute_max_drawdown(bankroll_curve: list[float]) -> float:
    peak = bankroll_curve[0] if bankroll_curve else 0.0
    max_dd = 0.0
    for value in bankroll_curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return max_dd


def simulate_strategy(
    strategy: str,
    candidates: list[TradeCandidate],
    scenario: ScenarioSpec,
) -> tuple[ScenarioSummary, list[TradeResult]]:
    raw_candidates = [candidate for candidate in candidates if candidate.strategy == strategy]
    if not raw_candidates:
        return (
            ScenarioSummary(
                strategy=strategy,
                scenario_id=scenario.scenario_id,
                decision_hour_utc=scenario.decision_hour_utc,
                market_std_multiplier=scenario.market_std_multiplier,
                market_information_ratio=scenario.market_information_ratio,
                raw_candidates=0,
                selected_candidates=0,
                trades=0,
                wins=0,
                win_rate=0.0,
                total_pnl_usd=0.0,
                final_bankroll_usd=scenario.bankroll_usd,
                avg_edge=0.0,
                avg_order_probability=0.0,
                avg_size_usd=0.0,
                max_drawdown_pct=0.0,
                top_examples=[],
            ),
            [],
        )

    by_day: dict[str, list[TradeCandidate]] = defaultdict(list)
    for candidate in raw_candidates:
        by_day[candidate.target_date].append(candidate)

    selected: list[TradeCandidate] = []
    for target_date in sorted(by_day):
        day_candidates = sorted(
            by_day[target_date],
            key=lambda item: (-item.edge, item.station_code, item.title),
        )
        selected.extend(day_candidates[: scenario.max_signals_per_day])

    bankroll = scenario.bankroll_usd
    bankroll_curve = [bankroll]
    trades: list[TradeResult] = []

    for candidate in selected:
        size_usd = _kelly_size_usd(
            side=candidate.side,
            model_probability=candidate.model_probability,
            order_probability=candidate.order_probability,
            bankroll_usd=bankroll,
            kelly_fraction=scenario.kelly_fraction,
            max_order_usd=scenario.max_order_usd,
        )
        if size_usd < scenario.min_order_usd:
            continue

        bankroll_before = bankroll
        shares = size_usd / candidate.order_probability
        pnl_usd = (shares * (1.0 - candidate.order_probability)) if candidate.won else (-size_usd)
        bankroll += pnl_usd
        bankroll_curve.append(bankroll)

        trades.append(
            TradeResult(
                strategy=strategy,
                scenario_id=scenario.scenario_id,
                station_code=candidate.station_code,
                target_date=candidate.target_date,
                title=candidate.title,
                side=candidate.side,
                edge=candidate.edge,
                model_probability=candidate.model_probability,
                order_probability=candidate.order_probability,
                won=candidate.won,
                size_usd=round(size_usd, 4),
                pnl_usd=round(pnl_usd, 4),
                bankroll_before_usd=round(bankroll_before, 4),
                bankroll_after_usd=round(bankroll, 4),
                observed_max_f=round(candidate.observed_max_f, 4),
                final_high_f=round(candidate.final_high_f, 4),
                model_point_f=round(candidate.model_point_f, 4),
                market_point_f=round(candidate.market_point_f, 4),
            )
        )

    wins = sum(1 for trade in trades if trade.won)
    total_pnl_usd = sum(trade.pnl_usd for trade in trades)
    avg_edge = statistics.mean(trade.edge for trade in trades) if trades else 0.0
    avg_order_probability = statistics.mean(trade.order_probability for trade in trades) if trades else 0.0
    avg_size_usd = statistics.mean(trade.size_usd for trade in trades) if trades else 0.0
    top_examples = [
        {
            "date": trade.target_date,
            "station": trade.station_code,
            "side": trade.side,
            "title": trade.title,
            "edge": round(trade.edge, 4),
            "price": round(trade.order_probability, 4),
            "won": trade.won,
            "pnl_usd": trade.pnl_usd,
        }
        for trade in sorted(trades, key=lambda item: item.edge, reverse=True)[:5]
    ]
    summary = ScenarioSummary(
        strategy=strategy,
        scenario_id=scenario.scenario_id,
        decision_hour_utc=scenario.decision_hour_utc,
        market_std_multiplier=scenario.market_std_multiplier,
        market_information_ratio=scenario.market_information_ratio,
        raw_candidates=len(raw_candidates),
        selected_candidates=len(selected),
        trades=len(trades),
        wins=wins,
        win_rate=round((wins / len(trades)) if trades else 0.0, 4),
        total_pnl_usd=round(total_pnl_usd, 4),
        final_bankroll_usd=round(bankroll, 4),
        avg_edge=round(avg_edge, 4),
        avg_order_probability=round(avg_order_probability, 4),
        avg_size_usd=round(avg_size_usd, 4),
        max_drawdown_pct=round(_compute_max_drawdown(bankroll_curve), 4),
        top_examples=top_examples,
    )
    return summary, trades


def _uncertainty_regime(multiplier: float) -> str:
    if multiplier <= 1.05:
        return "low"
    if multiplier <= 1.20:
        return "medium"
    return "high"


def _build_operator_guidance(
    *,
    scenario_summaries: list[ScenarioSummary],
    rollup: dict[str, dict[str, Any]],
    assumptions: dict[str, Any],
) -> dict[str, Any]:
    binary_rollup = rollup.get("binary_threshold", {})
    binary_candidates = [
        summary
        for summary in scenario_summaries
        if summary.strategy == "binary_threshold" and summary.trades > 0
    ]
    best_binary = max(
        binary_candidates,
        key=lambda item: (item.total_pnl_usd, item.win_rate, item.trades),
        default=None,
    )
    recommended_binary = (
        bool(binary_candidates)
        and float(binary_rollup.get("median_total_pnl_usd", 0.0)) >= 0.0
        and float(binary_rollup.get("positive_scenario_ratio", 0.0)) >= 0.34
    )

    if recommended_binary:
        return {
            "recommended_contract_family": "binary_threshold",
            "rationale": (
                "Binary thresholds are prioritized as the primary weather lane "
                "because they meet robustness gates across scenario variants."
            ),
            "decision_hour_utc": best_binary.decision_hour_utc if best_binary else None,
            "uncertainty_regime": _uncertainty_regime(best_binary.market_std_multiplier) if best_binary else "unknown",
            "paper_trade_parameters": {
                "mode": "paper",
                "edge_threshold": assumptions.get("edge_threshold"),
                "max_spread": assumptions.get("max_spread"),
                "max_signals_per_day": assumptions.get("max_signals_per_day"),
                "bankroll_usd": assumptions.get("bankroll_usd"),
                "max_order_usd": assumptions.get("max_order_usd"),
            },
            "range_contracts_secondary": True,
        }

    reason = "binary_threshold lacks enough robust evidence versus range contracts."
    if not binary_candidates:
        reason = "binary_threshold produced no executable trades under current assumptions."
    return {
        "recommended_contract_family": None,
        "rationale": reason,
        "decision_hour_utc": None,
        "uncertainty_regime": "unknown",
        "paper_trade_parameters": {
            "mode": "paper",
            "edge_threshold": assumptions.get("edge_threshold"),
            "max_spread": assumptions.get("max_spread"),
            "max_signals_per_day": assumptions.get("max_signals_per_day"),
            "bankroll_usd": assumptions.get("bankroll_usd"),
            "max_order_usd": assumptions.get("max_order_usd"),
        },
        "range_contracts_secondary": True,
    }


def _forecast_archive_summary(
    *,
    forecast_archive_path: Path,
) -> dict[str, Any]:
    rows = load_forecast_snapshot_archive(archive_path=forecast_archive_path)
    unique_pairs = {(str(row.get("city", "")), str(row.get("target_date", ""))) for row in rows}
    latest_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("city", "")), str(row.get("target_date", "")))
        if not key[0] or not key[1]:
            continue
        existing = latest_by_pair.get(key)
        if existing is None or str(row.get("captured_at", "")) > str(existing.get("captured_at", "")):
            latest_by_pair[key] = row
    return {
        "archive_path": str(forecast_archive_path),
        "snapshot_rows": len(rows),
        "city_date_pairs": len(unique_pairs),
        "latest_replayable_snapshots": sorted(latest_by_pair.values(), key=lambda row: (row.get("city", ""), row.get("target_date", ""))),
    }


def run_scenarios(
    histories: dict[str, StationHistory],
    scenarios: list[ScenarioSpec],
    *,
    forecast_archive_path: Path = FORECAST_SNAPSHOT_LOG,
    decisions_log_path: Path = DECISIONS_LOG,
    settlement_log_path: Path = SETTLEMENT_LOG,
) -> dict[str, Any]:
    scenario_summaries: list[ScenarioSummary] = []
    scenario_trade_logs: list[dict[str, Any]] = []

    for scenario in scenarios:
        candidates = build_trade_candidates(histories, scenario)
        for strategy in ("range_fade", "range_tail_yes", "binary_threshold"):
            summary, trades = simulate_strategy(strategy, candidates, scenario)
            scenario_summaries.append(summary)
            scenario_trade_logs.extend(asdict(trade) for trade in trades)

    rollup: dict[str, dict[str, Any]] = {}
    for strategy in ("range_fade", "range_tail_yes", "binary_threshold"):
        summaries = [summary for summary in scenario_summaries if summary.strategy == strategy]
        pnl_values = [summary.total_pnl_usd for summary in summaries]
        bankroll_values = [summary.final_bankroll_usd for summary in summaries]
        win_rates = [summary.win_rate for summary in summaries]
        trades = [summary.trades for summary in summaries]
        positive_scenarios = sum(1 for value in pnl_values if value > 0.0)
        rollup[strategy] = {
            "scenario_count": len(summaries),
            "positive_scenario_count": positive_scenarios,
            "positive_scenario_ratio": round(positive_scenarios / len(summaries), 4) if summaries else 0.0,
            "median_total_pnl_usd": round(statistics.median(pnl_values), 4) if pnl_values else 0.0,
            "median_final_bankroll_usd": round(statistics.median(bankroll_values), 4) if bankroll_values else 0.0,
            "median_win_rate": round(statistics.median(win_rates), 4) if win_rates else 0.0,
            "median_trades": round(statistics.median(trades), 4) if trades else 0.0,
            "best_total_pnl_usd": round(max(pnl_values), 4) if pnl_values else 0.0,
            "worst_total_pnl_usd": round(min(pnl_values), 4) if pnl_values else 0.0,
        }

    recommended_strategy = None
    if rollup:
        recommended_strategy = max(
            rollup.items(),
            key=lambda item: (
                item[1]["median_total_pnl_usd"],
                item[1]["positive_scenario_ratio"],
                item[1]["worst_total_pnl_usd"],
            ),
        )[0]

    assumptions = {
        "stations": list(STATION_META.keys()),
        "data_dir": str(WEATHER_VALIDATION_DIR),
        "market_information_ratio": scenarios[0].market_information_ratio if scenarios else DEFAULT_MARKET_INFORMATION_RATIO,
        "decision_hours_utc": [scenario.decision_hour_utc for scenario in scenarios],
        "market_std_multipliers": [scenario.market_std_multiplier for scenario in scenarios],
        "edge_threshold": scenarios[0].edge_threshold if scenarios else DEFAULT_EDGE_THRESHOLD,
        "max_spread": scenarios[0].max_spread if scenarios else DEFAULT_MAX_SPREAD,
        "spread": scenarios[0].spread if scenarios else DEFAULT_SPREAD,
        "max_signals_per_day": scenarios[0].max_signals_per_day if scenarios else DEFAULT_MAX_SIGNALS_PER_DAY,
        "tail_yes_max_price": scenarios[0].tail_yes_max_price if scenarios else DEFAULT_TAIL_YES_MAX_PRICE,
        "bankroll_usd": scenarios[0].bankroll_usd if scenarios else DEFAULT_BANKROLL_USD,
        "max_order_usd": scenarios[0].max_order_usd if scenarios else DEFAULT_MAX_ORDER_USD,
    }

    operator_guidance = _build_operator_guidance(
        scenario_summaries=scenario_summaries,
        rollup=rollup,
        assumptions=assumptions,
    )
    forecast_replay = _forecast_archive_summary(forecast_archive_path=forecast_archive_path)
    settlement_reconciliation = reconcile_decisions_with_settlements(
        decisions_log=decisions_log_path,
        settlement_log=settlement_log_path,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "simulation_type": "weather_scenario_simulation",
        "note": (
            "Uses real ASOS intraday observations + official daily settlement highs, "
            "but synthetic market prices derived from an explicit stale-market model. "
            "Treat this as a scenario simulator, not a historical quote replay."
        ),
        "limitations": [
            "No archived historical Kalshi quote tape is available in this repo for these markets.",
            "Forecast archive coverage depends on weather_arb snapshot capture cadence.",
            "Results are sensitive to the market-uncertainty assumption (market_std_multiplier).",
        ],
        "assumptions": assumptions,
        "recommended_strategy": recommended_strategy,
        "operator_guidance": operator_guidance,
        "forecast_replay": forecast_replay,
        "settlement_reconciliation": settlement_reconciliation,
        "robustness_summary": rollup,
        "scenario_summaries": [asdict(summary) for summary in scenario_summaries],
        "trade_log": scenario_trade_logs,
    }


def build_default_scenarios(
    *,
    decision_hours_utc: list[int] | None = None,
    market_std_multipliers: list[float] | None = None,
    market_information_ratio: float = DEFAULT_MARKET_INFORMATION_RATIO,
    min_training_days: int = DEFAULT_MIN_TRAINING_DAYS,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    max_spread: float = DEFAULT_MAX_SPREAD,
    spread: float = DEFAULT_SPREAD,
    bankroll_usd: float = DEFAULT_BANKROLL_USD,
    max_order_usd: float = DEFAULT_MAX_ORDER_USD,
    kelly_fraction: float = DEFAULT_KELLY_FRACTION,
    max_signals_per_day: int = DEFAULT_MAX_SIGNALS_PER_DAY,
    tail_yes_max_price: float = DEFAULT_TAIL_YES_MAX_PRICE,
    contract_radius_degrees: int = DEFAULT_CONTRACT_RADIUS_DEGREES,
    min_order_usd: float = DEFAULT_MIN_ORDER_USD,
) -> list[ScenarioSpec]:
    scenarios: list[ScenarioSpec] = []
    for decision_hour_utc in decision_hours_utc or DEFAULT_DECISION_HOURS_UTC:
        for market_std_multiplier in market_std_multipliers or DEFAULT_MARKET_STD_MULTIPLIERS:
            scenarios.append(
                ScenarioSpec(
                    decision_hour_utc=decision_hour_utc,
                    market_std_multiplier=market_std_multiplier,
                    market_information_ratio=market_information_ratio,
                    min_training_days=min_training_days,
                    edge_threshold=edge_threshold,
                    max_spread=max_spread,
                    spread=spread,
                    bankroll_usd=bankroll_usd,
                    max_order_usd=max_order_usd,
                    kelly_fraction=kelly_fraction,
                    max_signals_per_day=max_signals_per_day,
                    tail_yes_max_price=tail_yes_max_price,
                    contract_radius_degrees=contract_radius_degrees,
                    min_order_usd=min_order_usd,
                )
            )
    return scenarios


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scenario simulator for Kalshi weather strategies")
    parser.add_argument("--decision-hours-utc", default="18,20,22")
    parser.add_argument("--market-std-multipliers", default="1.0,1.15,1.30")
    parser.add_argument("--market-information-ratio", type=float, default=DEFAULT_MARKET_INFORMATION_RATIO)
    parser.add_argument("--min-training-days", type=int, default=DEFAULT_MIN_TRAINING_DAYS)
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    parser.add_argument("--max-spread", type=float, default=DEFAULT_MAX_SPREAD)
    parser.add_argument("--spread", type=float, default=DEFAULT_SPREAD)
    parser.add_argument("--bankroll-usd", type=float, default=DEFAULT_BANKROLL_USD)
    parser.add_argument("--max-order-usd", type=float, default=DEFAULT_MAX_ORDER_USD)
    parser.add_argument("--kelly-fraction", type=float, default=DEFAULT_KELLY_FRACTION)
    parser.add_argument("--max-signals-per-day", type=int, default=DEFAULT_MAX_SIGNALS_PER_DAY)
    parser.add_argument("--tail-yes-max-price", type=float, default=DEFAULT_TAIL_YES_MAX_PRICE)
    parser.add_argument("--contract-radius-degrees", type=int, default=DEFAULT_CONTRACT_RADIUS_DEGREES)
    parser.add_argument("--min-order-usd", type=float, default=DEFAULT_MIN_ORDER_USD)
    parser.add_argument("--json-out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    histories = load_histories()
    scenarios = build_default_scenarios(
        decision_hours_utc=_parse_int_grid(args.decision_hours_utc),
        market_std_multipliers=_parse_float_grid(args.market_std_multipliers),
        market_information_ratio=float(args.market_information_ratio),
        min_training_days=int(args.min_training_days),
        edge_threshold=float(args.edge_threshold),
        max_spread=float(args.max_spread),
        spread=float(args.spread),
        bankroll_usd=float(args.bankroll_usd),
        max_order_usd=float(args.max_order_usd),
        kelly_fraction=float(args.kelly_fraction),
        max_signals_per_day=int(args.max_signals_per_day),
        tail_yes_max_price=float(args.tail_yes_max_price),
        contract_radius_degrees=int(args.contract_radius_degrees),
        min_order_usd=float(args.min_order_usd),
    )
    report = run_scenarios(histories, scenarios)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report["robustness_summary"], indent=2))
    print(f"recommended_strategy={report['recommended_strategy']}")
    if args.json_out is not None:
        print(f"json_out={args.json_out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
