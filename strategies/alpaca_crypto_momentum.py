"""Minimal self-improving Alpaca crypto momentum policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from statistics import fmean, mean, pstdev
from typing import Any, Iterable, Mapping

from bot.bayesian_promoter import LogGrowthPosterior
from signals.tail_bins import TailPosterior, posterior_from_results


def _parse_timestamp(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("-", "/")


def _normalize_symbol_key(symbol: str) -> str:
    return _normalize_symbol(symbol).replace("/", "")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CryptoBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "CryptoBar":
        return cls(
            timestamp=str(payload.get("t") or payload.get("timestamp") or ""),
            open=_safe_float(payload.get("o")),
            high=_safe_float(payload.get("h")),
            low=_safe_float(payload.get("l")),
            close=_safe_float(payload.get("c")),
            volume=_safe_float(payload.get("v")),
        )


@dataclass(frozen=True)
class CryptoQuote:
    bid: float
    ask: float
    mid: float

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], *, fallback_price: float) -> "CryptoQuote":
        quote = payload.get("latestQuote") if isinstance(payload.get("latestQuote"), Mapping) else {}
        bid = _safe_float((quote or {}).get("bp"), fallback_price)
        ask = _safe_float((quote or {}).get("ap"), fallback_price)
        if bid <= 0 and ask > 0:
            bid = ask
        if ask <= 0 and bid > 0:
            ask = bid
        mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else fallback_price
        return cls(bid=bid, ask=ask, mid=mid)


@dataclass
class LearningStats:
    wins: int = 0
    losses: int = 0
    gross_return_bps: float = 0.0
    recent_returns_bps: list[float] = field(default_factory=list)

    @property
    def resolved(self) -> int:
        return self.wins + self.losses

    @property
    def average_recent_return_bps(self) -> float:
        if not self.recent_returns_bps:
            return 0.0
        return fmean(self.recent_returns_bps)

    def record(self, return_bps: float) -> None:
        self.gross_return_bps += float(return_bps)
        if return_bps > 0:
            self.wins += 1
        else:
            self.losses += 1
        self.recent_returns_bps.append(float(return_bps))
        if len(self.recent_returns_bps) > 50:
            self.recent_returns_bps = self.recent_returns_bps[-50:]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["resolved"] = self.resolved
        payload["average_recent_return_bps"] = self.average_recent_return_bps
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LearningStats":
        return cls(
            wins=int(payload.get("wins") or 0),
            losses=int(payload.get("losses") or 0),
            gross_return_bps=_safe_float(payload.get("gross_return_bps")),
            recent_returns_bps=[_safe_float(item) for item in list(payload.get("recent_returns_bps") or [])],
        )


@dataclass
class PendingTrade:
    symbol: str
    side: str
    entered_at: str
    entry_price: float
    hold_minutes: int
    notional_usd: float
    packet_id: str = ""
    order_id: str | None = None
    edge_bps: float = 0.0

    @property
    def mature_at(self) -> datetime:
        return _parse_timestamp(self.entered_at) + timedelta(minutes=int(self.hold_minutes))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PendingTrade":
        return cls(
            symbol=_normalize_symbol(str(payload.get("symbol") or "")),
            side=str(payload.get("side") or "buy").strip().lower(),
            entered_at=str(payload.get("entered_at") or ""),
            entry_price=_safe_float(payload.get("entry_price")),
            hold_minutes=int(payload.get("hold_minutes") or 15),
            notional_usd=_safe_float(payload.get("notional_usd")),
            packet_id=str(payload.get("packet_id") or ""),
            order_id=str(payload.get("order_id") or "") or None,
            edge_bps=_safe_float(payload.get("edge_bps")),
        )


@dataclass
class LearningState:
    version: int = 1
    pending: list[PendingTrade] = field(default_factory=list)
    stats: dict[str, LearningStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "pending": [item.to_dict() for item in self.pending],
            "stats": {symbol: stat.to_dict() for symbol, stat in self.stats.items()},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LearningState":
        stats_payload = payload.get("stats") or {}
        return cls(
            version=int(payload.get("version") or 1),
            pending=[PendingTrade.from_dict(item) for item in list(payload.get("pending") or []) if isinstance(item, Mapping)],
            stats={
                _normalize_symbol(symbol): LearningStats.from_dict(value)
                for symbol, value in dict(stats_payload).items()
                if isinstance(value, Mapping)
            },
        )


@dataclass(frozen=True)
class AlpacaCryptoMomentumConfig:
    short_window: int = 5
    long_window: int = 20
    hold_minutes: int = 15
    min_signal_bps: float = 8.0
    max_spread_bps: float = 30.0
    alpha_prior: float = 6.0
    beta_prior: float = 4.0
    posterior_confidence: float = 0.90
    min_resolved_for_scaling: int = 8
    min_posterior_lower: float = 0.51
    bootstrap_notional_usd: float = 25.0
    max_notional_usd: float = 100.0
    recent_return_floor_bps: float = -10.0
    min_position_qty_to_exit: float = 1e-9


@dataclass(frozen=True)
class TradePlan:
    symbol: str
    side: str
    order_type: str
    time_in_force: str
    reference_price: float
    limit_price: float | None
    notional_usd: float
    confidence: float
    edge_bps: float
    hold_minutes: int
    bootstrap_mode: bool
    posterior_mean: float | None
    posterior_lower: float | None
    rationale: tuple[str, ...]
    learning_snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_learning_state(path: Path) -> LearningState:
    if not path.exists():
        return LearningState()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        return LearningState()
    return LearningState.from_dict(payload)


def save_learning_state(path: Path, state: LearningState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def _select_exit_price(bars: list[CryptoBar], mature_at: datetime) -> float | None:
    ordered = sorted(bars, key=lambda item: _parse_timestamp(item.timestamp))
    for bar in ordered:
        if _parse_timestamp(bar.timestamp) >= mature_at:
            return bar.close
    return None


def resolve_pending_trades(
    state: LearningState,
    *,
    bars_by_symbol: Mapping[str, list[CryptoBar]],
    now: datetime | None = None,
) -> dict[str, int]:
    resolved = 0
    still_pending: list[PendingTrade] = []
    current_time = now or datetime.now(timezone.utc)
    for trade in state.pending:
        if trade.mature_at > current_time:
            still_pending.append(trade)
            continue
        symbol = _normalize_symbol(trade.symbol)
        exit_price = _select_exit_price(list(bars_by_symbol.get(symbol) or []), trade.mature_at)
        if exit_price is None or exit_price <= 0:
            still_pending.append(trade)
            continue
        direction = 1.0 if trade.side == "buy" else -1.0
        return_bps = direction * ((exit_price / max(trade.entry_price, 1e-12)) - 1.0) * 10000.0
        stats = state.stats.setdefault(symbol, LearningStats())
        stats.record(return_bps)
        resolved += 1
    state.pending = still_pending
    return {"resolved": resolved, "pending": len(state.pending)}


def _posterior_for_symbol(
    state: LearningState,
    symbol: str,
    *,
    config: AlpacaCryptoMomentumConfig,
) -> TailPosterior | None:
    stats = state.stats.get(_normalize_symbol(symbol))
    if stats is None or stats.resolved <= 0:
        return None
    return posterior_from_results(
        wins=stats.wins,
        losses=stats.losses,
        alpha_prior=config.alpha_prior,
        beta_prior=config.beta_prior,
        confidence=config.posterior_confidence,
    )


def _rolling_signal_bps(closes: list[float], *, short_window: int, long_window: int) -> float:
    short_avg = fmean(closes[-short_window:])
    long_avg = fmean(closes[-long_window:])
    if long_avg <= 0:
        return 0.0
    return ((short_avg / long_avg) - 1.0) * 10000.0


def _realized_volatility_bps(closes: list[float], *, long_window: int) -> float:
    if len(closes) < 3:
        return 0.0
    returns = []
    for left, right in zip(closes[-long_window:-1], closes[-long_window + 1 :], strict=False):
        if left <= 0 or right <= 0:
            continue
        returns.append(math.log(right / left) * 10000.0)
    if len(returns) < 2:
        return 0.0
    return pstdev(returns)


def build_trade_plan(
    *,
    symbol: str,
    bars: list[CryptoBar],
    quote: CryptoQuote,
    state: LearningState,
    config: AlpacaCryptoMomentumConfig,
    position_qty: float = 0.0,
) -> TradePlan | None:
    normalized = _normalize_symbol(symbol)
    ordered = sorted(bars, key=lambda item: _parse_timestamp(item.timestamp))
    closes = [bar.close for bar in ordered if bar.close > 0]
    if len(closes) < max(config.short_window, config.long_window):
        return None

    reference_price = quote.mid if quote.mid > 0 else closes[-1]
    if reference_price <= 0:
        return None

    spread_bps = ((quote.ask - quote.bid) / reference_price) * 10000.0 if quote.ask > 0 and quote.bid > 0 else 0.0
    signal_bps = _rolling_signal_bps(closes, short_window=config.short_window, long_window=config.long_window)
    if abs(signal_bps) < config.min_signal_bps:
        return None
    if spread_bps > config.max_spread_bps:
        return None

    side = "buy" if signal_bps > 0 else "sell"

    posterior = _posterior_for_symbol(state, normalized, config=config)
    stats = state.stats.get(normalized, LearningStats())
    bootstrap_mode = stats.resolved < config.min_resolved_for_scaling

    # In bootstrap mode: allow sell side as a buy-the-dip signal, and accept
    # any positive signal even if smaller than spread (spread is the cost of
    # learning, and $25 notional caps the risk)
    if not bootstrap_mode:
        if side == "sell" and position_qty <= config.min_position_qty_to_exit:
            return None

    edge_bps = abs(signal_bps) - spread_bps
    if not bootstrap_mode and edge_bps <= 0:
        return None
    # In bootstrap: floor edge_bps at the raw signal strength
    if bootstrap_mode and edge_bps <= 0:
        edge_bps = abs(signal_bps)
    if not bootstrap_mode:
        if posterior is None or posterior.lower_bound < config.min_posterior_lower:
            return None
        if stats.average_recent_return_bps < config.recent_return_floor_bps:
            return None

    if bootstrap_mode:
        notional_usd = config.bootstrap_notional_usd
        order_type = "market"
        time_in_force = "gtc"
    else:
        posterior_edge = max(0.0, (posterior.lower_bound if posterior is not None else 0.5) - 0.50)
        scale = min(1.0, posterior_edge / 0.10) * min(1.0, edge_bps / 25.0)
        notional_usd = max(config.bootstrap_notional_usd, config.max_notional_usd * max(0.10, scale))
        order_type = "limit"
        time_in_force = "ioc"

    limit_price: float | None
    if order_type == "limit":
        limit_price = quote.ask * 1.001 if side == "buy" else quote.bid * 0.999
    else:
        limit_price = None

    realized_vol_bps = _realized_volatility_bps(closes, long_window=config.long_window)
    confidence = min(
        0.99,
        0.55 + min(0.30, abs(signal_bps) / 100.0) + min(0.10, max(0.0, edge_bps) / 100.0),
    )
    if posterior is not None:
        confidence = min(0.99, max(confidence, posterior.mean))

    rationale = (
        f"signal_bps={signal_bps:.2f}",
        f"spread_bps={spread_bps:.2f}",
        f"edge_bps={edge_bps:.2f}",
        f"realized_vol_bps={realized_vol_bps:.2f}",
        f"bootstrap_mode={bootstrap_mode}",
        f"resolved={stats.resolved}",
    )
    if posterior is not None:
        rationale += (
            f"posterior_mean={posterior.mean:.4f}",
            f"posterior_lower={posterior.lower_bound:.4f}",
        )

    return TradePlan(
        symbol=normalized,
        side=side,
        order_type=order_type,
        time_in_force=time_in_force,
        reference_price=reference_price,
        limit_price=limit_price,
        notional_usd=round(notional_usd, 2),
        confidence=round(confidence, 4),
        edge_bps=round(edge_bps, 2),
        hold_minutes=config.hold_minutes,
        bootstrap_mode=bootstrap_mode,
        posterior_mean=round(posterior.mean, 6) if posterior is not None else None,
        posterior_lower=round(posterior.lower_bound, 6) if posterior is not None else None,
        rationale=rationale,
        learning_snapshot={
            "symbol": normalized,
            "wins": stats.wins,
            "losses": stats.losses,
            "resolved": stats.resolved,
            "average_recent_return_bps": round(stats.average_recent_return_bps, 4),
        },
    )


def append_pending_trade(
    state: LearningState,
    *,
    plan: TradePlan,
    entered_at: datetime,
    entry_price: float,
    packet_id: str,
    order_id: str | None = None,
) -> None:
    state.pending.append(
        PendingTrade(
            symbol=plan.symbol,
            side=plan.side,
            entered_at=entered_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            entry_price=float(entry_price),
            hold_minutes=int(plan.hold_minutes),
            notional_usd=float(plan.notional_usd),
            packet_id=packet_id,
            order_id=order_id,
            edge_bps=float(plan.edge_bps),
        )
    )


# ---------------------------------------------------------------------------
# Compatibility surface for the Alpaca first-trade lane
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TopOfBook:
    symbol: str
    bid_price: float
    ask_price: float
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def mid_price(self) -> float:
        if self.bid_price > 0 and self.ask_price > 0:
            return (self.bid_price + self.ask_price) / 2.0
        return max(self.bid_price, self.ask_price)

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid <= 0:
            return 0.0
        return max(0.0, ((self.ask_price - self.bid_price) / mid) * 10000.0)


@dataclass(frozen=True)
class AlpacaMomentumVariant:
    variant_id: str
    symbol: str
    hold_bars: int
    stop_loss_bps: float
    take_profit_bps: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VariantScore:
    symbol: str
    variant_id: str
    action: str
    rank_score: float
    expected_edge_bps: float
    prob_positive: float
    posterior_mean_log_return: float
    replay_trade_count: int
    momentum_bps: float
    trend_gap_bps: float
    volatility_bps: float
    spread_bps: float
    last_price: float
    hold_bars: int
    recommended_notional_usd: float
    variant: AlpacaMomentumVariant

    def to_candidate_row(self, *, execution_mode: str) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "variant_id": self.variant_id,
            "side": self.action,
            "action": self.action,
            "rank_score": round(self.rank_score, 6),
            "expected_edge_bps": round(self.expected_edge_bps, 2),
            "prob_positive": round(self.prob_positive, 6),
            "posterior_mean_log_return": round(self.posterior_mean_log_return, 8),
            "replay_trade_count": self.replay_trade_count,
            "momentum_bps": round(self.momentum_bps, 2),
            "trend_gap_bps": round(self.trend_gap_bps, 2),
            "volatility_bps": round(self.volatility_bps, 2),
            "spread_bps": round(self.spread_bps, 2),
            "last_price": round(self.last_price, 6),
            "hold_bars": self.hold_bars,
            "recommended_notional_usd": round(self.recommended_notional_usd, 2),
            "stop_loss_bps": round(self.variant.stop_loss_bps, 2),
            "take_profit_bps": round(self.variant.take_profit_bps, 2),
            "execution_mode": execution_mode,
            "variant": self.variant.to_dict(),
        }


def parse_crypto_bars_response(payload: Mapping[str, Any]) -> dict[str, list[CryptoBar]]:
    bars_payload = payload.get("bars") if isinstance(payload, Mapping) else {}
    if not isinstance(bars_payload, Mapping):
        return {}
    parsed: dict[str, list[CryptoBar]] = {}
    for symbol, rows in dict(bars_payload).items():
        if not isinstance(rows, list):
            continue
        parsed[_normalize_symbol(str(symbol))] = [CryptoBar.from_api(row) for row in rows if isinstance(row, Mapping)]
    return parsed


def parse_latest_orderbooks_response(payload: Mapping[str, Any]) -> dict[str, TopOfBook]:
    books_payload = payload.get("orderbooks") if isinstance(payload, Mapping) else {}
    if not isinstance(books_payload, Mapping):
        return {}
    parsed: dict[str, TopOfBook] = {}
    for symbol, row in dict(books_payload).items():
        if not isinstance(row, Mapping):
            continue
        bids = list(row.get("b") or [])
        asks = list(row.get("a") or [])
        top_bid = bids[0] if bids else {}
        top_ask = asks[0] if asks else {}
        parsed[_normalize_symbol(str(symbol))] = TopOfBook(
            symbol=_normalize_symbol(str(symbol)),
            bid_price=_safe_float((top_bid or {}).get("p")),
            ask_price=_safe_float((top_ask or {}).get("p")),
            bid_size=_safe_float((top_bid or {}).get("s")),
            ask_size=_safe_float((top_ask or {}).get("s")),
        )
    return parsed


def default_alpaca_momentum_variants(symbols: Iterable[str]) -> tuple[AlpacaMomentumVariant, ...]:
    return tuple(
        AlpacaMomentumVariant(
            variant_id=f"{_normalize_symbol_key(symbol)}_momo_v1",
            symbol=_normalize_symbol(symbol),
            hold_bars=15,
            stop_loss_bps=70.0,
            take_profit_bps=150.0,
        )
        for symbol in symbols
    )


def rank_momentum_candidates(
    *,
    bars_by_symbol: dict[str, list[CryptoBar]],
    books_by_symbol: dict[str, TopOfBook],
    variants: Iterable[AlpacaMomentumVariant],
    live_return_map: dict[str, list[float]] | None = None,
    recommended_notional_usd: float = 25.0,
    min_prob_positive: float = 0.55,
    min_expected_edge_bps: float = 60.0,
    max_spread_bps: float = 35.0,
) -> list[VariantScore]:
    live_return_map = live_return_map or {}
    scores: list[VariantScore] = []
    state = LearningState()

    for variant in variants:
        symbol = _normalize_symbol(variant.symbol)
        bars = list(bars_by_symbol.get(symbol) or [])
        if not bars:
            continue
        quote = books_by_symbol.get(symbol)
        if quote is None:
            fallback = bars[-1].close
            quote = TopOfBook(symbol=symbol, bid_price=fallback, ask_price=fallback)

        # Determine bootstrap mode: no resolved trades yet for this variant
        variant_returns = list(live_return_map.get(variant.variant_id) or [])
        is_bootstrap = len(variant_returns) < 8

        trade_plan = build_trade_plan(
            symbol=symbol,
            bars=bars,
            quote=CryptoQuote(bid=quote.bid_price, ask=quote.ask_price, mid=quote.mid_price),
            state=state,
            config=AlpacaCryptoMomentumConfig(
                hold_minutes=variant.hold_bars,
                bootstrap_notional_usd=recommended_notional_usd,
                max_notional_usd=recommended_notional_usd,
                max_spread_bps=max_spread_bps,
                # Bootstrap: accept any signal >= 1 bps; mature: use configured threshold
                min_signal_bps=1.0 if is_bootstrap else max(1.0, min_expected_edge_bps / 10.0),
            ),
        )
        if trade_plan is None:
            continue
        # Bootstrap: allow both buy and sell; mature: buy only
        if not is_bootstrap and trade_plan.side != "buy":
            continue
        if quote.spread_bps > max_spread_bps:
            continue

        stats = LearningStats()
        for value in variant_returns:
            stats.record(float(value) * 10000.0)
        posterior = posterior_from_results(
            wins=stats.wins,
            losses=stats.losses,
            alpha_prior=6.0,
            beta_prior=4.0,
            confidence=0.90,
        ) if stats.resolved > 0 else None
        prob_positive = posterior.mean if posterior is not None else trade_plan.confidence
        # Bootstrap: lower probability gate to 0.51 (just above coin flip)
        effective_min_prob = 0.51 if is_bootstrap else min_prob_positive
        if prob_positive < effective_min_prob:
            continue
        expected_edge_bps = float(trade_plan.edge_bps)
        # Bootstrap: accept any positive edge; mature: use configured threshold
        effective_min_edge = 1.0 if is_bootstrap else min_expected_edge_bps
        if expected_edge_bps < effective_min_edge:
            continue

        closes = [bar.close for bar in bars if bar.close > 0]
        short_window = max(2, min(5, len(closes)))
        long_window = max(short_window + 1, min(20, len(closes)))
        momentum_bps = _rolling_signal_bps(closes, short_window=short_window, long_window=long_window)
        trend_gap_bps = momentum_bps
        volatility_bps = _realized_volatility_bps(closes, long_window=long_window)
        rank_score = max(0.0, expected_edge_bps / 10000.0) * max(prob_positive, trade_plan.confidence)

        scores.append(
            VariantScore(
                symbol=symbol,
                variant_id=variant.variant_id,
                action=trade_plan.side,
                rank_score=rank_score,
                expected_edge_bps=expected_edge_bps,
                prob_positive=max(prob_positive, trade_plan.confidence),
                posterior_mean_log_return=max(0.0, expected_edge_bps / 10000.0),
                replay_trade_count=max(1, stats.resolved),
                momentum_bps=momentum_bps,
                trend_gap_bps=trend_gap_bps,
                volatility_bps=volatility_bps,
                spread_bps=quote.spread_bps,
                last_price=trade_plan.reference_price,
                hold_bars=variant.hold_bars,
                recommended_notional_usd=trade_plan.notional_usd,
                variant=variant,
            )
        )

    return sorted(scores, key=lambda item: item.rank_score, reverse=True)
