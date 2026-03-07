"""Feature engineering for Polymarket BTC up/down edge research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import bisect
import math
from pathlib import Path
import sqlite3
import statistics
from typing import Any


@dataclass
class FeatureBundle:
    markets: list[dict[str, Any]]
    btc_prices: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    features: list[dict[str, Any]]
    resolutions: dict[str, str]
    wallet_scores: dict[str, dict[str, float]]


class FeatureEngineer:
    """Build features and labels from SQLite data."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _nearest_price(ts: int, btc_ts: list[int], btc_prices: list[float]) -> float | None:
        if not btc_ts:
            return None
        idx = bisect.bisect_left(btc_ts, ts)
        if idx == 0:
            return btc_prices[0]
        if idx >= len(btc_ts):
            return btc_prices[-1]
        before = idx - 1
        after = idx
        if abs(btc_ts[after] - ts) < abs(btc_ts[before] - ts):
            return btc_prices[after]
        return btc_prices[before]

    @staticmethod
    def _window_series(ts: int, btc_ts: list[int], btc_prices: list[float], window_sec: int) -> list[float]:
        start = ts - window_sec
        lo = bisect.bisect_left(btc_ts, start)
        hi = bisect.bisect_right(btc_ts, ts)
        return btc_prices[lo:hi]

    @staticmethod
    def _realized_vol(series: list[float]) -> float:
        if len(series) < 3:
            return 0.0
        rets = []
        for i in range(1, len(series)):
            if series[i - 1] <= 0.0 or series[i] <= 0.0:
                continue
            rets.append(math.log(series[i] / series[i - 1]))
        if len(rets) < 2:
            return 0.0
        return statistics.pstdev(rets)

    @staticmethod
    def _drift_per_sec(series: list[float], duration_sec: int) -> float:
        if len(series) < 2 or duration_sec <= 0:
            return 0.0
        if series[0] <= 0.0 or series[-1] <= 0.0:
            return 0.0
        total = math.log(series[-1] / series[0])
        return total / duration_sec

    @staticmethod
    def _range_position(series: list[float], value: float) -> float:
        if not series:
            return 0.5
        low = min(series)
        high = max(series)
        if high <= low:
            return 0.5
        return (value - low) / (high - low)

    def build_feature_bundle(self, lookback_hours: int = 72) -> FeatureBundle:
        with self._connect() as conn:
            now_ts = int(datetime.now(tz=timezone.utc).timestamp())
            min_ts = now_ts - (lookback_hours * 3600)

            markets = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM markets
                    WHERE window_end_ts >= ?
                    ORDER BY window_start_ts ASC
                    """,
                    (min_ts,),
                ).fetchall()
            ]

            prices = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT mp.*, m.timeframe, m.window_start_ts, m.window_end_ts,
                           m.final_resolution, m.yes_token_id, m.no_token_id
                    FROM market_prices mp
                    JOIN markets m ON m.condition_id = mp.condition_id
                    WHERE mp.timestamp_ts >= ?
                    ORDER BY mp.timestamp_ts ASC
                    """,
                    (min_ts,),
                ).fetchall()
            ]

            btc_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT timestamp_ts, price FROM btc_spot WHERE timestamp_ts >= ? ORDER BY timestamp_ts ASC",
                    (min_ts - 7200,),
                ).fetchall()
            ]

            trades = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM trades WHERE timestamp_ts >= ? ORDER BY timestamp_ts ASC",
                    (min_ts - 7200,),
                ).fetchall()
            ]

            orderbook = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM orderbook_snapshots WHERE timestamp_ts >= ? ORDER BY timestamp_ts ASC",
                    (min_ts,),
                ).fetchall()
            ]

        btc_ts = [int(row["timestamp_ts"]) for row in btc_rows]
        btc_price_vals = [float(row["price"]) for row in btc_rows]

        market_by_condition = {str(row.get("condition_id")): row for row in markets}
        resolutions = {
            str(row.get("condition_id")): str(row.get("final_resolution"))
            for row in markets
            if row.get("final_resolution") in ("UP", "DOWN")
        }

        trades_by_condition: dict[str, list[dict[str, Any]]] = {}
        wallet_trade_history: dict[str, list[dict[str, Any]]] = {}
        for row in trades:
            trades_by_condition.setdefault(str(row["condition_id"]), []).append(row)
            wallet = str(row.get("wallet") or "")
            if wallet:
                wallet_trade_history.setdefault(wallet, []).append(row)

        book_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for row in orderbook:
            book_by_key[(str(row["condition_id"]), int(row["timestamp_ts"]))] = row

        condition_resolution_info = self._condition_resolution_info(markets)
        wallet_scores = self._compute_wallet_scores(trades, condition_resolution_info)
        wallet_score_cache: dict[tuple[str, int, str], dict[str, float] | None] = {}

        timeframe_windows: dict[str, list[dict[str, Any]]] = {"5m": [], "15m": [], "4h": []}
        for market in markets:
            tf = str(market.get("timeframe") or "")
            if tf in timeframe_windows:
                timeframe_windows[tf].append(market)

        for tf in timeframe_windows:
            timeframe_windows[tf].sort(key=lambda m: int(m.get("window_start_ts") or 0))

        features: list[dict[str, Any]] = []
        for row in prices:
            ts = int(row["timestamp_ts"])
            condition_id = str(row["condition_id"])
            market = market_by_condition.get(condition_id)
            if not market:
                continue

            current_price = self._nearest_price(ts, btc_ts, btc_price_vals)
            open_price = self._nearest_price(int(market.get("window_start_ts") or 0), btc_ts, btc_price_vals)
            if current_price is None or open_price is None or open_price <= 0.0:
                continue

            series_30m = self._window_series(ts, btc_ts, btc_price_vals, 1800)
            series_1h = self._window_series(ts, btc_ts, btc_price_vals, 3600)
            series_2h = self._window_series(ts, btc_ts, btc_price_vals, 7200)

            vol_30m = self._realized_vol(series_30m)
            vol_1h = self._realized_vol(series_1h)
            vol_2h = self._realized_vol(series_2h)
            mu = self._drift_per_sec(series_1h, min(3600, max(1, len(series_1h) - 1)))

            end_ts = int(row.get("window_end_ts") or ts)
            time_remaining = max(0, end_ts - ts)
            yes_price = float(row.get("yes_price") or 0.5)
            no_price = float(row.get("no_price") or (1.0 - yes_price))

            trade_stats = self._trade_stats(trades_by_condition.get(condition_id, []), ts)
            book_imbalance = self._book_imbalance(condition_id, ts, book_by_key)
            wallet_signal = self._wallet_signal(
                trades_by_condition.get(condition_id, []),
                condition_id,
                int(market.get("window_start_ts") or ts),
                ts,
                wallet_trade_history,
                condition_resolution_info,
                wallet_score_cache,
            )

            hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
            weekday = datetime.fromtimestamp(ts, tz=timezone.utc).weekday()
            prior_return = self._previous_window_return(
                market,
                timeframe_windows.get("15m", []),
                btc_ts,
                btc_price_vals,
            )

            inner_resolved_count, inner_up_bias = self._inner_window_bias(
                market,
                ts,
                timeframe_windows,
            )

            btc_ret_open = (current_price / open_price) - 1.0
            price_60s_ago = self._nearest_price(max(ts - 60, int(market.get("window_start_ts") or ts)), btc_ts, btc_price_vals)
            btc_ret_60s = 0.0
            if price_60s_ago and price_60s_ago > 0.0:
                btc_ret_60s = (current_price / price_60s_ago) - 1.0

            market_momentum = (yes_price - 0.5) * 2.0
            basis_lag_score = (btc_ret_open * 60.0) - market_momentum

            features.append(
                {
                    "condition_id": condition_id,
                    "timeframe": str(row.get("timeframe") or ""),
                    "timestamp_ts": ts,
                    "window_start_ts": int(row.get("window_start_ts") or 0),
                    "window_end_ts": end_ts,
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "btc_price": current_price,
                    "open_price": open_price,
                    "btc_return_since_open": btc_ret_open,
                    "btc_return_60s": btc_ret_60s,
                    "realized_vol_30m": vol_30m,
                    "realized_vol_1h": vol_1h,
                    "realized_vol_2h": vol_2h,
                    "mu_per_sec": mu,
                    "sigma_per_sqrt_sec": max(vol_2h, 1e-4),
                    "time_remaining_sec": time_remaining,
                    "range_position_2h": self._range_position(series_2h, current_price),
                    "trade_count_60s": trade_stats["count"],
                    "trade_buy_volume_60s": trade_stats["buy_volume"],
                    "trade_sell_volume_60s": trade_stats["sell_volume"],
                    "trade_flow_imbalance": trade_stats["imbalance"],
                    "book_imbalance": book_imbalance,
                    "wallet_signal_wallets": wallet_signal["wallets"],
                    "wallet_signal_trades": wallet_signal["trades"],
                    "wallet_up_bias": wallet_signal["up_bias"],
                    "wallet_avg_win_rate": wallet_signal["avg_win_rate"],
                    "wallet_avg_trades": wallet_signal["avg_trades"],
                    "wallet_consensus_strength": wallet_signal["consensus_strength"],
                    "wallet_dominance": wallet_signal["dominance"],
                    "wallet_signal_fallback": wallet_signal["fallback_used"],
                    "hour_utc": hour,
                    "weekday": weekday,
                    "prev_window_return": prior_return,
                    "inner_resolved_count": inner_resolved_count,
                    "inner_up_bias": inner_up_bias,
                    "basis_lag_score": basis_lag_score,
                    "label_up": 1 if resolutions.get(condition_id) == "UP" else (0 if resolutions.get(condition_id) == "DOWN" else None),
                }
            )

        return FeatureBundle(
            markets=markets,
            btc_prices=btc_rows,
            trades=trades,
            features=features,
            resolutions=resolutions,
            wallet_scores=wallet_scores,
        )

    @staticmethod
    def _trade_stats(rows: list[dict[str, Any]], ts: int) -> dict[str, float]:
        lookback = ts - 60
        relevant = [r for r in rows if lookback <= int(r["timestamp_ts"]) <= ts]
        count = len(relevant)
        buy_volume = 0.0
        sell_volume = 0.0
        for row in relevant:
            size = float(row.get("size") or 0.0)
            if str(row.get("side") or "").upper() == "BUY":
                buy_volume += size
            else:
                sell_volume += size

        total = buy_volume + sell_volume
        imbalance = (buy_volume - sell_volume) / total if total > 0 else 0.0
        return {"count": float(count), "buy_volume": buy_volume, "sell_volume": sell_volume, "imbalance": imbalance}

    @staticmethod
    def _book_imbalance(condition_id: str, ts: int, book_by_key: dict[tuple[str, int], dict[str, Any]]) -> float:
        keys = [key for key in book_by_key if key[0] == condition_id and key[1] <= ts]
        if not keys:
            return 0.0
        key = max(keys, key=lambda k: k[1])
        row = book_by_key[key]
        bid_total = 0.0
        ask_total = 0.0
        for level in range(1, 6):
            bid_total += float(row.get(f"bid_{level}_size") or 0.0)
            ask_total += float(row.get(f"ask_{level}_size") or 0.0)
        total = bid_total + ask_total
        if total <= 0.0:
            return 0.0
        return (bid_total - ask_total) / total

    @staticmethod
    def _condition_resolution_info(markets: list[dict[str, Any]]) -> dict[str, dict[str, float | str]]:
        info: dict[str, dict[str, float | str]] = {}
        for market in markets:
            condition_id = str(market.get("condition_id") or "")
            if not condition_id:
                continue

            resolution = str(market.get("final_resolution") or "")
            if resolution not in ("UP", "DOWN"):
                resolution = ""

            resolution_ts = int(market.get("window_end_ts") or market.get("market_end_ts") or 0)
            info[condition_id] = {
                "resolution": resolution,
                "resolution_ts": float(resolution_ts),
            }
        return info

    @staticmethod
    def _normalize_market_side(outcome: str) -> str:
        text = str(outcome or "").strip().upper()
        if text in ("UP", "YES", "LONG"):
            return "UP"
        if text in ("DOWN", "NO", "SHORT"):
            return "DOWN"
        return ""

    @staticmethod
    def _compute_wallet_scores(
        trades: list[dict[str, Any]],
        condition_resolution_info: dict[str, dict[str, float | str]],
    ) -> dict[str, dict[str, float]]:
        scores: dict[str, dict[str, float]] = {}
        for row in trades:
            condition_id = str(row.get("condition_id") or "")
            outcome = FeatureEngineer._normalize_market_side(str(row.get("outcome") or ""))
            wallet = str(row.get("wallet") or "")
            info = condition_resolution_info.get(condition_id)
            resolution = str((info or {}).get("resolution") or "")
            resolution_ts = int((info or {}).get("resolution_ts") or 0)
            ts = int(row.get("timestamp_ts") or 0)

            if not wallet or not info or not resolution or resolution_ts <= 0 or ts <= 0:
                # Keep activity stats even when the market is unresolved.
                if wallet:
                    item = scores.setdefault(
                        wallet,
                        {
                            "wins": 0.0,
                            "trades": 0.0,
                            "win_rate": 0.5,
                            "all_trades": 0.0,
                            "volume": 0.0,
                            "posterior_win_rate": 0.5,
                            "reliability": 0.0,
                            "quality_score": 0.5,
                        },
                    )
                    item["all_trades"] += 1.0
                    item["volume"] += float(row.get("size") or 0.0)
                continue

            # Only score outcome quality if this trade can be causally evaluated.
            # For whole-bundle summary scores we consider trades whose market has resolved by "now".
            # Resolution timestamps protect against unresolved/future-labeled rows.
            if outcome not in ("UP", "DOWN"):
                item = scores.setdefault(
                    wallet,
                    {
                        "wins": 0.0,
                        "trades": 0.0,
                        "win_rate": 0.5,
                        "all_trades": 0.0,
                        "volume": 0.0,
                        "posterior_win_rate": 0.5,
                        "reliability": 0.0,
                        "quality_score": 0.5,
                    },
                )
                item["all_trades"] += 1.0
                item["volume"] += float(row.get("size") or 0.0)
                continue

            win = int((outcome == "UP" and resolution == "UP") or (outcome == "DOWN" and resolution == "DOWN"))
            item = scores.setdefault(
                wallet,
                {
                    "wins": 0.0,
                    "trades": 0.0,
                    "win_rate": 0.5,
                    "all_trades": 0.0,
                    "volume": 0.0,
                    "posterior_win_rate": 0.5,
                    "reliability": 0.0,
                    "quality_score": 0.5,
                },
            )
            item["wins"] += win
            item["trades"] += 1.0
            item["all_trades"] += 1.0
            item["volume"] += float(row.get("size") or 0.0)

        # Empirical-Bayes shrinkage to avoid overconfidence on tiny resolved samples.
        prior_alpha = 2.5
        prior_beta = 2.5
        for item in scores.values():
            resolved_n = float(item.get("trades") or 0.0)
            wins = float(item.get("wins") or 0.0)
            all_n = float(item.get("all_trades") or 0.0)

            item["win_rate"] = (wins / resolved_n) if resolved_n > 0 else 0.5

            posterior = (wins + prior_alpha) / (resolved_n + prior_alpha + prior_beta)
            resolved_conf = 1.0 - math.exp(-resolved_n / 6.0)
            activity_conf = 1.0 - math.exp(-all_n / 10.0)
            reliability = 0.65 * resolved_conf + 0.35 * activity_conf
            quality = 0.5 + (posterior - 0.5) * reliability

            item["posterior_win_rate"] = posterior
            item["reliability"] = reliability
            item["quality_score"] = quality

        return scores

    def _wallet_signal(
        self,
        market_trades: list[dict[str, Any]],
        current_condition_id: str,
        window_start_ts: int,
        asof_ts: int,
        wallet_trade_history: dict[str, list[dict[str, Any]]],
        condition_resolution_info: dict[str, dict[str, float | str]],
        wallet_score_cache: dict[tuple[str, int, str], dict[str, float] | None],
    ) -> dict[str, float]:
        early_cutoff = window_start_ts + 300
        relevant = [r for r in market_trades if int(r["timestamp_ts"]) <= early_cutoff]

        trusted = []
        trusted_scores: list[dict[str, float]] = []
        relaxed = []
        relaxed_scores: list[dict[str, float]] = []
        for row in relevant:
            wallet = str(row.get("wallet") or "")
            score = self._wallet_score_asof(
                wallet=wallet,
                asof_ts=asof_ts,
                exclude_condition_id=current_condition_id,
                wallet_trade_history=wallet_trade_history,
                condition_resolution_info=condition_resolution_info,
                cache=wallet_score_cache,
            )
            if not score:
                continue

            all_trades = float(score.get("all_trades") or 0.0)
            posterior = float(score.get("posterior_win_rate") or 0.5)
            reliability = float(score.get("reliability") or 0.0)

            if all_trades >= 3 and posterior >= 0.52 and reliability >= 0.12:
                trusted.append(row)
                trusted_scores.append(score)
                continue

            # Cold-start fallback cohort for exploratory research only.
            if all_trades >= 3 and posterior >= 0.48 and reliability >= 0.10:
                relaxed.append(row)
                relaxed_scores.append(score)

        fallback_used = False
        if not trusted and relaxed:
            trusted = relaxed
            trusted_scores = relaxed_scores
            fallback_used = True

        wallets = len({str(r.get("wallet") or "") for r in trusted})
        if not trusted:
            return {
                "wallets": float(wallets),
                "trades": 0.0,
                "up_bias": 0.0,
                "avg_win_rate": 0.5,
                "avg_trades": 0.0,
                "consensus_strength": 0.0,
                "dominance": 0.0,
                "fallback_used": 0.0,
            }

        up = sum(1 for row in trusted if str(row.get("outcome") or "").upper() == "UP")
        down = sum(1 for row in trusted if str(row.get("outcome") or "").upper() == "DOWN")
        total = up + down
        bias = (up - down) / total if total else 0.0

        avg_win_rate = sum(float(item.get("posterior_win_rate") or 0.5) for item in trusted_scores) / max(len(trusted_scores), 1)
        avg_trades = sum(float(item.get("all_trades") or 0.0) for item in trusted_scores) / max(len(trusted_scores), 1)

        per_wallet_trades: dict[str, int] = {}
        for row in trusted:
            wallet = str(row.get("wallet") or "")
            per_wallet_trades[wallet] = per_wallet_trades.get(wallet, 0) + 1
        top_share = (max(per_wallet_trades.values()) / total) if total and per_wallet_trades else 0.0

        consensus_strength = abs(bias)
        consensus_strength *= min(1.0, wallets / 4.0)
        consensus_strength *= min(1.0, total / 30.0)

        return {
            "wallets": float(wallets),
            "trades": float(total),
            "up_bias": bias,
            "avg_win_rate": avg_win_rate,
            "avg_trades": avg_trades,
            "consensus_strength": consensus_strength,
            "dominance": top_share,
            "fallback_used": 1.0 if fallback_used else 0.0,
        }

    def _wallet_score_asof(
        self,
        wallet: str,
        asof_ts: int,
        exclude_condition_id: str,
        wallet_trade_history: dict[str, list[dict[str, Any]]],
        condition_resolution_info: dict[str, dict[str, float | str]],
        cache: dict[tuple[str, int, str], dict[str, float] | None],
    ) -> dict[str, float] | None:
        if not wallet:
            return None

        key = (wallet, asof_ts, exclude_condition_id)
        if key in cache:
            return cache[key]

        rows = wallet_trade_history.get(wallet, [])
        if not rows:
            cache[key] = None
            return None

        wins = 0.0
        resolved_n = 0.0
        all_n = 0.0
        volume = 0.0

        for row in rows:
            trade_ts = int(row.get("timestamp_ts") or 0)
            if trade_ts <= 0:
                continue
            if trade_ts > asof_ts:
                break

            condition_id = str(row.get("condition_id") or "")
            if condition_id == exclude_condition_id:
                continue

            all_n += 1.0
            volume += float(row.get("size") or 0.0)

            info = condition_resolution_info.get(condition_id)
            if not info:
                continue

            resolution = str(info.get("resolution") or "")
            resolution_ts = int(info.get("resolution_ts") or 0)
            if resolution not in ("UP", "DOWN") or resolution_ts <= 0 or resolution_ts > asof_ts:
                continue

            outcome = self._normalize_market_side(str(row.get("outcome") or ""))
            if outcome not in ("UP", "DOWN"):
                continue

            resolved_n += 1.0
            if outcome == resolution:
                wins += 1.0

        posterior, reliability, quality = self._bayesian_wallet_quality(wins, resolved_n, all_n)
        score = {
            "wins": wins,
            "trades": resolved_n,
            "win_rate": (wins / resolved_n) if resolved_n > 0 else 0.5,
            "all_trades": all_n,
            "volume": volume,
            "posterior_win_rate": posterior,
            "reliability": reliability,
            "quality_score": quality,
        }
        cache[key] = score
        return score

    @staticmethod
    def _bayesian_wallet_quality(wins: float, resolved_n: float, all_n: float) -> tuple[float, float, float]:
        prior_alpha = 2.5
        prior_beta = 2.5
        posterior = (wins + prior_alpha) / (resolved_n + prior_alpha + prior_beta)
        resolved_conf = 1.0 - math.exp(-resolved_n / 6.0)
        activity_conf = 1.0 - math.exp(-all_n / 10.0)
        reliability = 0.65 * resolved_conf + 0.35 * activity_conf
        quality = 0.5 + (posterior - 0.5) * reliability
        return posterior, reliability, quality

    def _previous_window_return(
        self,
        market: dict[str, Any],
        markets_15m: list[dict[str, Any]],
        btc_ts: list[int],
        btc_prices: list[float],
    ) -> float:
        this_start = int(market.get("window_start_ts") or 0)
        candidates = [m for m in markets_15m if int(m.get("window_start_ts") or 0) < this_start]
        if not candidates:
            return 0.0

        prev = max(candidates, key=lambda m: int(m.get("window_start_ts") or 0))
        prev_start = int(prev.get("window_start_ts") or 0)
        prev_end = int(prev.get("window_end_ts") or 0)

        p0 = self._nearest_price(prev_start, btc_ts, btc_prices)
        p1 = self._nearest_price(prev_end, btc_ts, btc_prices)
        if p0 is None or p1 is None or p0 <= 0.0:
            return 0.0
        return (p1 / p0) - 1.0

    @staticmethod
    def _inner_window_bias(
        market: dict[str, Any],
        ts: int,
        windows: dict[str, list[dict[str, Any]]],
    ) -> tuple[int, float]:
        timeframe = str(market.get("timeframe") or "")
        start = int(market.get("window_start_ts") or 0)
        end = int(market.get("window_end_ts") or 0)

        if timeframe == "15m":
            inner = windows.get("5m", [])
        elif timeframe == "4h":
            inner = windows.get("15m", [])
        else:
            return 0, 0.5

        relevant = [
            m
            for m in inner
            if start <= int(m.get("window_start_ts") or 0) < end and int(m.get("window_end_ts") or 0) <= ts
        ]
        if not relevant:
            return 0, 0.5

        up_count = sum(1 for m in relevant if str(m.get("final_resolution") or "") == "UP")
        down_count = sum(1 for m in relevant if str(m.get("final_resolution") or "") == "DOWN")
        total = up_count + down_count
        if total <= 0:
            return 0, 0.5
        return total, up_count / total
