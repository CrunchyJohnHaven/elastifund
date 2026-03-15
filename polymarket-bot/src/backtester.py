"""Monte Carlo backtesting engine for JJ strategy assumptions."""

from __future__ import annotations

import csv
import math
import random
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


@dataclass
class BacktestConfig:
    starting_capital: float
    monthly_injection: float
    win_rate: float
    avg_edge_after_calibration: float
    trades_per_day: int
    max_position_usd: float
    kelly_fraction: float
    daily_loss_limit: float
    fee_rate: float
    days: int = 365
    simulations: int = 1000
    start_date: date = date(2026, 1, 1)


@dataclass
class BacktestResult:
    daily_balances: list[float]
    monthly_returns: list[float]
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    time_to_target: dict[int, int | None]
    total_trades: int
    win_count: int
    p05_final_balance: float
    median_final_balance: float
    p95_final_balance: float


class Backtester:
    @staticmethod
    def _half_kelly_size(bankroll: float, p_win: float, p_market: float, fee_rate: float, kelly_fraction: float, max_position_usd: float) -> float:
        payout = 1.0 - fee_rate
        cost = p_market
        if cost <= 0 or cost >= payout:
            return 0.0
        odds = (payout - cost) / cost
        if odds <= 0:
            return 0.0
        kelly_f = (p_win * odds - (1 - p_win)) / odds
        kelly_f = max(0.0, kelly_f)
        size = bankroll * kelly_f * kelly_fraction
        return max(0.0, min(max_position_usd, size))

    def _run_once(self, cfg: BacktestConfig) -> tuple[list[float], int, int, dict[int, int | None]]:
        balance = cfg.starting_capital
        balances: list[float] = [balance]
        wins = 0
        total_trades = 0
        p_market = 0.5
        targets = {10_000: None, 50_000: None, 100_000: None}

        for day_idx in range(1, cfg.days + 1):
            now = cfg.start_date + timedelta(days=day_idx - 1)
            if now.day in (1, 15):
                balance += cfg.monthly_injection

            day_start = balance
            daily_pnl = 0.0

            for _ in range(cfg.trades_per_day):
                if daily_pnl <= -cfg.daily_loss_limit:
                    break

                size = self._half_kelly_size(
                    bankroll=balance,
                    p_win=cfg.win_rate,
                    p_market=p_market,
                    fee_rate=cfg.fee_rate,
                    kelly_fraction=cfg.kelly_fraction,
                    max_position_usd=cfg.max_position_usd,
                )
                if size <= 0:
                    continue

                total_trades += 1
                won = random.random() < cfg.win_rate
                if won:
                    pnl = size * ((1.0 - cfg.fee_rate) - p_market)
                    wins += 1
                else:
                    pnl = -size * p_market

                balance += pnl
                daily_pnl += pnl
                if balance <= 0:
                    balance = 0.0
                    break

            balances.append(balance)
            for target in targets:
                if targets[target] is None and balance >= target:
                    targets[target] = day_idx

            if balance <= 0 and day_start <= 0:
                break

        return balances, total_trades, wins, targets

    def run(self, config: BacktestConfig) -> BacktestResult:
        all_paths: list[list[float]] = []
        final_balances: list[float] = []
        trades = 0
        wins = 0
        target_hits = {10_000: [], 50_000: [], 100_000: []}

        for _ in range(config.simulations):
            path, sim_trades, sim_wins, sim_targets = self._run_once(config)
            all_paths.append(path)
            final_balances.append(path[-1])
            trades += sim_trades
            wins += sim_wins
            for k, v in sim_targets.items():
                if v is not None:
                    target_hits[k].append(v)

        final_balances_sorted = sorted(final_balances)
        p05 = final_balances_sorted[max(0, int(0.05 * (len(final_balances_sorted) - 1)))]
        median = final_balances_sorted[len(final_balances_sorted) // 2]
        p95 = final_balances_sorted[min(len(final_balances_sorted) - 1, int(0.95 * (len(final_balances_sorted) - 1)))]

        # Use median-length path (all equal length in this simulation setup).
        representative = sorted(all_paths, key=lambda p: p[-1])[len(all_paths) // 2]
        daily_returns = []
        for i in range(1, len(representative)):
            prev = representative[i - 1]
            curr = representative[i]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)

        running_peak = 0.0
        max_drawdown = 0.0
        monthly_returns = []
        month_start = representative[0]
        for idx, bal in enumerate(representative):
            running_peak = max(running_peak, bal)
            if running_peak > 0:
                dd = (running_peak - bal) / running_peak
                max_drawdown = max(max_drawdown, dd)
            if idx > 0 and idx % 30 == 0:
                if month_start > 0:
                    monthly_returns.append((bal - month_start) / month_start)
                month_start = bal

        if daily_returns and statistics.pstdev(daily_returns) > 0:
            sharpe = statistics.mean(daily_returns) / statistics.pstdev(daily_returns) * math.sqrt(365)
        else:
            sharpe = 0.0

        annualized_return = 0.0
        if representative and representative[0] > 0:
            years = max(1.0 / 365.0, (len(representative) - 1) / 365.0)
            annualized_return = (representative[-1] / representative[0]) ** (1.0 / years) - 1.0

        time_to_target = {}
        for target, hits in target_hits.items():
            time_to_target[target] = int(statistics.median(hits)) if hits else None

        return BacktestResult(
            daily_balances=representative,
            monthly_returns=monthly_returns,
            annualized_return=annualized_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            time_to_target=time_to_target,
            total_trades=trades // max(1, config.simulations),
            win_count=wins // max(1, config.simulations),
            p05_final_balance=p05,
            median_final_balance=median,
            p95_final_balance=p95,
        )


def _save_balances_csv(path: Path, balances: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["day", "balance"])
        for i, bal in enumerate(balances):
            writer.writerow([i, round(bal, 4)])


def _print_summary(name: str, result: BacktestResult) -> None:
    print(f"{name:12} | median={result.median_final_balance:10.2f} | p05={result.p05_final_balance:10.2f} | "
          f"p95={result.p95_final_balance:10.2f} | sharpe={result.sharpe_ratio:6.2f} | maxDD={result.max_drawdown:6.2%}")


def main() -> int:
    scenarios = {
        "Conservative": BacktestConfig(
            starting_capital=1000.0,
            monthly_injection=100.0,
            win_rate=0.55,
            avg_edge_after_calibration=0.08,
            trades_per_day=3,
            max_position_usd=15.0,
            kelly_fraction=0.5,
            daily_loss_limit=25.0,
            fee_rate=0.02,
        ),
        "Base": BacktestConfig(
            starting_capital=1000.0,
            monthly_injection=100.0,
            win_rate=0.60,
            avg_edge_after_calibration=0.12,
            trades_per_day=5,
            max_position_usd=15.0,
            kelly_fraction=0.5,
            daily_loss_limit=25.0,
            fee_rate=0.02,
        ),
        "Optimistic": BacktestConfig(
            starting_capital=1000.0,
            monthly_injection=100.0,
            win_rate=0.65,
            avg_edge_after_calibration=0.15,
            trades_per_day=8,
            max_position_usd=15.0,
            kelly_fraction=0.5,
            daily_loss_limit=25.0,
            fee_rate=0.02,
        ),
    }

    bt = Backtester()
    print("Scenario      | Summary")
    print("-" * 110)
    for name, cfg in scenarios.items():
        result = bt.run(cfg)
        _print_summary(name, result)
        out_csv = Path("backtest_output") / f"{name.lower()}_daily_balances.csv"
        _save_balances_csv(out_csv, result.daily_balances)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
