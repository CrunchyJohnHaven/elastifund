"""Walk-forward backtesting and cost-aware trade simulation."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
import math
import statistics
from typing import Any, Callable

from .confidence_calibration import CalibrationSummary, sequential_bayes_isotonic
from .config import BacktestConfig
from .maker_fill_model import compute_queue_aware_maker_fill_probability
from .models import ClosedFormInput, MonteCarloEngine, MCParams, TwoStateRegimeModel, closed_form_up_probability
from .models.classifiers import GradientBoostClassifier, LogisticClassifier, TreeClassifier
from .models.resampler import HistoricalResampler
from .strategies.base import BacktestResult, Signal


@dataclass
class TradePnL:
    maker: float
    taker: float
    win: bool
    confidence: float
    maker_fill_probability: float = 0.0


@dataclass
class _TradeSeries:
    timestamps: list[int]
    prices: list[float]
    sizes: list[float]


class Backtester:
    """Evaluate strategy signals with realistic execution assumptions."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self._trade_tape_by_key: dict[tuple[str, str, str], _TradeSeries] = {}
        self._condition_trade_counts: dict[str, int] = {}

    @staticmethod
    def taker_fee_formula(notional: float, price: float) -> float:
        p = min(0.999, max(0.001, price))
        return notional * p * 0.25 * ((p * (1 - p)) ** 2)

    def set_trade_tape(self, trades: list[dict[str, Any]]) -> None:
        """Attach trade tape so strict maker fill models can use trade-through evidence."""
        series_map: dict[tuple[str, str, str], list[tuple[int, float, float]]] = {}
        condition_counts: dict[str, int] = {}

        for row in trades:
            condition_id = str(row.get("condition_id") or "")
            if not condition_id:
                continue
            ts = int(row.get("timestamp_ts") or 0)
            if ts <= 0:
                continue

            price = float(row.get("price") or 0.0)
            size = float(row.get("size") or 0.0)
            if price <= 0.0 or size <= 0.0:
                continue

            outcome = self._canonical_outcome(str(row.get("outcome") or ""))
            side = str(row.get("side") or "").strip().upper()
            if side not in {"BUY", "SELL"}:
                continue
            if outcome not in {"UP", "DOWN"}:
                continue

            key = (condition_id, outcome, side)
            series_map.setdefault(key, []).append((ts, price, size))
            condition_counts[condition_id] = condition_counts.get(condition_id, 0) + 1

        out: dict[tuple[str, str, str], _TradeSeries] = {}
        for key, rows in series_map.items():
            rows.sort(key=lambda item: item[0])
            out[key] = _TradeSeries(
                timestamps=[item[0] for item in rows],
                prices=[item[1] for item in rows],
                sizes=[item[2] for item in rows],
            )

        self._trade_tape_by_key = out
        self._condition_trade_counts = condition_counts

    @staticmethod
    def _canonical_outcome(outcome: str) -> str:
        text = str(outcome or "").strip().upper()
        if text in {"YES", "UP"} or text.startswith("UP"):
            return "UP"
        if text in {"NO", "DOWN"} or text.startswith("DOWN"):
            return "DOWN"
        return text

    @staticmethod
    def _model_name(config: BacktestConfig) -> str:
        model = str(getattr(config, "maker_fill_model", "") or "").strip().lower()
        if model in {"constant", "queue_aware", "trade_through"}:
            return model
        return "queue_aware" if bool(config.queue_aware_maker_fill) else "constant"

    def _estimate_trade_through_fill_ratio(self, signal: Signal) -> float | None:
        condition_id = str(signal.condition_id or "")
        if not condition_id:
            return None
        if self._condition_trade_counts.get(condition_id, 0) <= 0:
            # No trade tape for this market: treat as missing evidence (fallback path).
            return None

        target_outcome = "UP" if str(signal.side).upper() == "YES" else "DOWN"
        series = self._trade_tape_by_key.get((condition_id, target_outcome, "SELL"))
        if series is None:
            # We saw this market in tape, but no qualifying opposite-aggressor flow.
            return 0.0

        start_ts = int(signal.timestamp_ts)
        wait_sec = float(signal.metadata.get("time_remaining_sec") or 0.0) if signal.metadata else 0.0
        if wait_sec <= 0.0:
            wait_sec = float(self.config.maker_fill_horizon_sec)
        end_ts = start_ts + int(max(1.0, wait_sec))

        lo = bisect.bisect_right(series.timestamps, start_ts)
        hi = bisect.bisect_right(series.timestamps, end_ts)
        if lo >= hi:
            return 0.0

        buffer = max(0.0, float(self.config.maker_fill_trade_through_buffer))
        max_fill_price = float(signal.entry_price) - buffer
        required_shares = self.config.position_size_usd / max(1e-6, float(signal.entry_price))
        if required_shares <= 0:
            return 0.0

        filled = 0.0
        for idx in range(lo, hi):
            if series.prices[idx] <= max_fill_price:
                filled += max(0.0, series.sizes[idx])
                if filled >= required_shares:
                    return 1.0
        return max(0.0, min(1.0, filled / required_shares))

    def _trade_pnl(
        self,
        signal: Signal,
        resolution: str,
        maker_fill_probability_override: float | None = None,
    ) -> TradePnL:
        stake = self.config.position_size_usd
        price = min(0.99, max(0.01, signal.entry_price))
        shares = stake / price

        up_win = signal.side == "YES" and resolution == "UP"
        down_win = signal.side == "NO" and resolution == "DOWN"
        win = up_win or down_win

        gross = shares * (1 - price) if win else -stake

        spread_cost = stake * self.config.default_spread
        taker_fee = self.taker_fee_formula(stake, price)
        taker_slippage = stake * self.config.slippage_taker

        maker_fill_probability = (
            max(0.0, min(1.0, float(maker_fill_probability_override)))
            if maker_fill_probability_override is not None
            else self._maker_fill_probability(signal)
        )
        maker_pnl = maker_fill_probability * (gross - spread_cost * 0.5)
        taker_pnl = gross - spread_cost - taker_fee - taker_slippage

        return TradePnL(
            maker=maker_pnl,
            taker=taker_pnl,
            win=win,
            confidence=signal.confidence,
            maker_fill_probability=maker_fill_probability,
        )

    def _maker_fill_probability(self, signal: Signal) -> float:
        model = self._model_name(self.config)
        if model == "constant":
            return max(0.0, min(1.0, float(self.config.maker_fill_rate)))

        if model == "trade_through":
            trade_through_ratio = self._estimate_trade_through_fill_ratio(signal)
            if trade_through_ratio is not None:
                return max(0.0, min(1.0, trade_through_ratio))
            # Missing tape evidence fallback.
            if self.config.queue_aware_maker_fill:
                return compute_queue_aware_maker_fill_probability(signal, self.config)
            return max(0.0, min(1.0, float(self.config.maker_fill_rate)))

        return compute_queue_aware_maker_fill_probability(signal, self.config)

    def _calibrated_signals(
        self,
        signals: list[Signal],
        outcomes: list[bool],
    ) -> tuple[list[Signal], CalibrationSummary]:
        if not signals:
            return (
                [],
                CalibrationSummary(
                    applied=False,
                    method="none",
                    avg_raw_confidence=0.0,
                    avg_calibrated_confidence=0.0,
                    mean_abs_adjustment=0.0,
                ),
            )

        if not self.config.confidence_calibration_enabled:
            avg = statistics.mean([float(s.confidence) for s in signals])
            return (
                signals,
                CalibrationSummary(
                    applied=False,
                    method="disabled",
                    avg_raw_confidence=avg,
                    avg_calibrated_confidence=avg,
                    mean_abs_adjustment=0.0,
                ),
            )

        calibrated_confidences, summary = sequential_bayes_isotonic(
            [float(s.confidence) for s in signals],
            outcomes,
            bins=self.config.confidence_calibration_bins,
            prior_strength=self.config.confidence_calibration_prior_strength,
            min_history=self.config.confidence_calibration_min_history,
            floor=self.config.confidence_calibration_floor,
            ceiling=self.config.confidence_calibration_ceiling,
        )

        calibrated_signals: list[Signal] = []
        for signal, calibrated in zip(signals, calibrated_confidences, strict=False):
            metadata = dict(signal.metadata or {})
            metadata["raw_confidence"] = float(signal.confidence)
            metadata["calibrated_confidence"] = float(calibrated)
            calibrated_signals.append(
                Signal(
                    strategy=signal.strategy,
                    condition_id=signal.condition_id,
                    timestamp_ts=signal.timestamp_ts,
                    side=signal.side,
                    entry_price=signal.entry_price,
                    confidence=float(calibrated),
                    edge_estimate=signal.edge_estimate,
                    metadata=metadata,
                )
            )
        return calibrated_signals, summary

    @staticmethod
    def _wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
        if n <= 0:
            return 0.0, 1.0
        p = wins / n
        denom = 1 + z * z / n
        center = p + z * z / (2 * n)
        radius = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
        return max(0.0, (center - radius) / denom), min(1.0, (center + radius) / denom)

    @staticmethod
    def _binomial_p_value(wins: int, n: int, p0: float = 0.5) -> float:
        if n <= 0:
            return 1.0
        expected = n * p0
        variance = n * p0 * (1 - p0)
        if variance <= 0:
            return 1.0
        z = abs(wins - expected) / math.sqrt(variance)
        # Two-sided normal approximation.
        tail = 0.5 * (1 - math.erf(z / math.sqrt(2)))
        return min(1.0, max(0.0, 2 * tail))

    @staticmethod
    def _max_drawdown(pnls: list[float]) -> float:
        if not pnls:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in pnls:
            equity += pnl
            peak = max(peak, equity)
            dd = peak - equity
            max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def _calibration_error(signals: list[Signal], outcomes: list[bool], bins: int = 10) -> float:
        if not signals:
            return 1.0
        bin_totals = [0] * bins
        bin_hits = [0] * bins
        bin_conf_sum = [0.0] * bins

        for signal, outcome in zip(signals, outcomes, strict=False):
            idx = min(bins - 1, max(0, int(signal.confidence * bins)))
            bin_totals[idx] += 1
            bin_hits[idx] += int(outcome)
            bin_conf_sum[idx] += signal.confidence

        err = 0.0
        weight_sum = 0.0
        for i in range(bins):
            if bin_totals[i] == 0:
                continue
            pred = bin_conf_sum[i] / bin_totals[i]
            obs = bin_hits[i] / bin_totals[i]
            weight = bin_totals[i]
            err += abs(pred - obs) * weight
            weight_sum += weight
        return err / weight_sum if weight_sum else 1.0

    @staticmethod
    def _kelly_fraction(win_rate: float, avg_price: float) -> float:
        avg_price = min(0.99, max(0.01, avg_price))
        b = (1 - avg_price) / avg_price
        p = win_rate
        q = 1 - p
        if b <= 0:
            return 0.0
        k = (b * p - q) / b
        return max(0.0, min(1.0, k))

    def evaluate(self, strategy_name: str, signals: list[Signal], resolutions: dict[str, str]) -> BacktestResult:
        valid_signals = [s for s in signals if s.condition_id in resolutions]
        valid_signals.sort(key=lambda s: (int(s.timestamp_ts), s.condition_id, s.side))
        if not valid_signals:
            return BacktestResult(
                strategy=strategy_name,
                signals=0,
                wins=0,
                win_rate=0.0,
                ev_maker=0.0,
                ev_taker=0.0,
                sharpe=0.0,
                max_drawdown=0.0,
                p_value=1.0,
                calibration_error=1.0,
                regime_decay=False,
                kelly_fraction=0.0,
                wilson_low=0.0,
                wilson_high=1.0,
                notes=["No resolved signals available."],
            )

        raw_outcomes = [
            ((signal.side == "YES") and (resolutions[signal.condition_id] == "UP"))
            or ((signal.side == "NO") and (resolutions[signal.condition_id] == "DOWN"))
            for signal in valid_signals
        ]
        calibrated_signals, calibration = self._calibrated_signals(valid_signals, raw_outcomes)
        fill_model = self._model_name(self.config)

        maker_pnls: list[float] = []
        taker_pnls: list[float] = []
        outcomes: list[bool] = []
        maker_fill_probs: list[float] = []
        trade_through_coverage = 0
        trade_through_overrides: list[float | None] = []
        if fill_model == "trade_through":
            for signal in calibrated_signals:
                override = self._estimate_trade_through_fill_ratio(signal)
                trade_through_overrides.append(override)
                if override is not None:
                    trade_through_coverage += 1
        else:
            trade_through_overrides = [None] * len(calibrated_signals)
        wins = 0

        for signal, override in zip(calibrated_signals, trade_through_overrides, strict=False):
            result = self._trade_pnl(
                signal,
                resolutions[signal.condition_id],
                maker_fill_probability_override=override,
            )
            maker_pnls.append(result.maker)
            taker_pnls.append(result.taker)
            outcomes.append(result.win)
            maker_fill_probs.append(result.maker_fill_probability)
            wins += int(result.win)

        n = len(calibrated_signals)
        win_rate = wins / n
        ev_maker = statistics.mean(maker_pnls)
        ev_taker = statistics.mean(taker_pnls)
        sharpe = 0.0
        if len(maker_pnls) > 1:
            std = statistics.pstdev(maker_pnls)
            if std > 1e-9:
                sharpe = statistics.mean(maker_pnls) / std

        mdd = self._max_drawdown(maker_pnls)
        p_value = self._binomial_p_value(wins, n)
        low, high = self._wilson_interval(wins, n)
        raw_cal_err = self._calibration_error(valid_signals, outcomes)
        cal_err = self._calibration_error(calibrated_signals, outcomes)

        split = max(1, int(0.75 * n))
        early = outcomes[:split]
        late = outcomes[split:]
        regime_decay = (sum(late) / max(len(late), 1)) < (sum(early) / max(len(early), 1))

        avg_price = statistics.mean([s.entry_price for s in calibrated_signals])
        kelly = self._kelly_fraction(win_rate, avg_price)

        notes: list[str] = []
        if n < 100:
            notes.append("Insufficient sample size (<100 signals).")
        if ev_taker < 0:
            notes.append("Negative expectancy after taker costs.")
        if regime_decay:
            notes.append("Recent sample shows regime decay.")
        if maker_fill_probs:
            notes.append(f"Avg maker fill probability: {statistics.mean(maker_fill_probs):.3f}")
        notes.append(f"Maker fill model: {fill_model}")
        if fill_model == "trade_through":
            notes.append(f"Trade-through tape coverage: {trade_through_coverage}/{n} signals")
        if calibration.applied:
            notes.append(
                "Confidence calibration: "
                f"{calibration.method} (raw={raw_cal_err:.3f} -> calibrated={cal_err:.3f}, "
                f"mean_adjustment={calibration.mean_abs_adjustment:.3f})"
            )
        else:
            notes.append(f"Confidence calibration: {calibration.method}")

        return BacktestResult(
            strategy=strategy_name,
            signals=n,
            wins=wins,
            win_rate=win_rate,
            ev_maker=ev_maker,
            ev_taker=ev_taker,
            sharpe=sharpe,
            max_drawdown=mdd,
            p_value=p_value,
            calibration_error=cal_err,
            regime_decay=regime_decay,
            kelly_fraction=kelly,
            wilson_low=low,
            wilson_high=high,
            notes=notes,
        )

    def stress_costs(self, signals: list[Signal], resolutions: dict[str, str]) -> dict[str, float]:
        """Sensitivity of expectancy under +/-20% cost changes."""
        if not signals:
            return {"base": 0.0, "cost_up": 0.0, "cost_down": 0.0}
        base = self.evaluate("stress_base", signals, resolutions).ev_taker

        original_slippage = self.config.slippage_taker
        original_spread = self.config.default_spread

        bump = self.config.cost_stress_pct
        self.config.slippage_taker = original_slippage * (1 + bump)
        self.config.default_spread = original_spread * (1 + bump)
        up = self.evaluate("stress_up", signals, resolutions).ev_taker

        self.config.slippage_taker = original_slippage * (1 - bump)
        self.config.default_spread = original_spread * (1 - bump)
        down = self.evaluate("stress_down", signals, resolutions).ev_taker

        self.config.slippage_taker = original_slippage
        self.config.default_spread = original_spread
        return {"base": base, "cost_up": up, "cost_down": down}


def walk_forward_model_competition(
    features: list[dict[str, Any]],
    model_seed: int,
    mc_paths: int,
) -> list[dict[str, Any]]:
    """Run model-family competition on resolved 15m rows using rolling windows."""
    resolved = [row for row in features if row.get("timeframe") == "15m" and row.get("label_up") is not None]
    resolved.sort(key=lambda row: int(row.get("timestamp_ts") or 0))
    if len(resolved) < 80:
        return []

    feature_cols = [
        "yes_price",
        "btc_return_since_open",
        "btc_return_60s",
        "realized_vol_30m",
        "realized_vol_1h",
        "realized_vol_2h",
        "range_position_2h",
        "trade_count_60s",
        "trade_flow_imbalance",
        "book_imbalance",
        "basis_lag_score",
        "time_remaining_sec",
        "inner_up_bias",
        "prev_window_return",
        "hour_utc",
        "weekday",
    ]

    split = int(len(resolved) * 0.8)
    train = resolved[:split]
    test = resolved[split:]
    y_test = [int(row["label_up"]) for row in test]

    logistic = LogisticClassifier(feature_cols)
    logistic.fit(train, [int(row["label_up"]) for row in train])
    logistic_probs = logistic.predict_proba(test)

    tree = TreeClassifier(feature_cols)
    tree.fit(train, [int(row["label_up"]) for row in train])
    tree_probs = tree.predict_proba(test)

    xgb = GradientBoostClassifier(feature_cols)
    xgb.fit(train, [int(row["label_up"]) for row in train])
    xgb_probs = xgb.predict_proba(test)

    mc_engine = MonteCarloEngine(seed=model_seed)
    regime = TwoStateRegimeModel()
    regime.fit([float(row.get("realized_vol_1h") or 0.0) for row in train])

    resampler = HistoricalResampler(seed=model_seed)
    realized_returns = [
        float(row.get("btc_return_60s") or 0.0)
        for row in train
        if abs(float(row.get("btc_return_60s") or 0.0)) < 0.2
    ]

    baseline_probs: list[float] = []
    closed_form_probs: list[float] = []
    mc_gbm_probs: list[float] = []
    mc_regime_probs: list[float] = []
    bootstrap_probs: list[float] = []

    for row in test:
        baseline_probs.append(float(row.get("yes_price") or 0.5))

        closed_form_probs.append(
            closed_form_up_probability(
                ClosedFormInput(
                    current_price=float(row.get("btc_price") or 0.0),
                    open_price=float(row.get("open_price") or 0.0),
                    mu_per_sec=float(row.get("mu_per_sec") or 0.0),
                    sigma_per_sqrt_sec=float(row.get("sigma_per_sqrt_sec") or 1e-4),
                    time_remaining_sec=float(row.get("time_remaining_sec") or 1.0),
                )
            )
        )

        params = MCParams(
            s0=float(row.get("btc_price") or 0.0),
            mu_per_sec=float(row.get("mu_per_sec") or 0.0),
            sigma_per_sqrt_sec=max(float(row.get("sigma_per_sqrt_sec") or 1e-4), 1e-4),
            horizon_sec=max(1, int(row.get("time_remaining_sec") or 1)),
            paths=mc_paths,
            seed=model_seed,
        )
        gbm_paths = mc_engine.simulate_gbm(params)
        mc_gbm_probs.append(mc_engine.probability_close_above(gbm_paths, float(row.get("open_price") or 0.0)))

        state = regime.predict_state(float(row.get("realized_vol_1h") or 0.0))
        trans = regime.transition_probs()
        regime_paths = mc_engine.simulate_regime_switching(
            params,
            low_sigma=max(regime.low_sigma, 1e-4),
            high_sigma=max(regime.high_sigma, regime.low_sigma * 1.2, 2e-4),
            p_low_to_high=trans["p_low_to_high"],
            p_high_to_low=trans["p_high_to_low"],
        )
        mc_regime_probs.append(mc_engine.probability_close_above(regime_paths, float(row.get("open_price") or 0.0)))

        bootstrap_probs.append(
            resampler.probability_up(
                current_price=float(row.get("btc_price") or 0.0),
                open_price=float(row.get("open_price") or 0.0),
                realized_log_returns=realized_returns,
                horizon_steps=max(1, int(float(row.get("time_remaining_sec") or 1) // 60)),
                paths=max(500, mc_paths // 5),
            )
        )

    def brier(probs: list[float], labels: list[int]) -> float:
        return sum((p - y) ** 2 for p, y in zip(probs, labels, strict=False)) / max(len(labels), 1)

    def expectancy(probs: list[float], labels: list[int]) -> float:
        # Expected edge per $1 contract by choosing side with higher probability.
        total = 0.0
        for p, y in zip(probs, labels, strict=False):
            side_yes = p >= 0.5
            market_p = 0.5
            if side_yes:
                pnl = (1 - market_p) if y == 1 else -market_p
            else:
                pnl = market_p if y == 0 else -(1 - market_p)
            total += pnl
        return total / max(len(labels), 1)

    rows = [
        ("Naive baseline", baseline_probs),
        ("Closed-form Φ", closed_form_probs),
        ("Logistic regression", logistic_probs),
        ("Tree baseline", tree_probs),
        ("Monte Carlo GBM", mc_gbm_probs),
        ("MC regime-switching", mc_regime_probs),
        ("Historical resample", bootstrap_probs),
        ("XGBoost", xgb_probs),
    ]

    baseline_expectancy = expectancy(baseline_probs, y_test)
    table: list[dict[str, Any]] = []
    for name, probs in rows:
        exp = expectancy(probs, y_test)
        std = statistics.pstdev(probs) if len(probs) > 1 else 0.0
        sharpe_like = (statistics.mean(probs) - 0.5) / std if std > 1e-8 else 0.0
        table.append(
            {
                "model": name,
                "oos_expectancy": exp,
                "sharpe_like": sharpe_like,
                "calibration_error": brier(probs, y_test),
                "beats_baseline": exp > baseline_expectancy,
            }
        )

    return table
