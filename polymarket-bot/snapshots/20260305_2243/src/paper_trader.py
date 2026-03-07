"""Paper trading loop that continuously scans markets and simulates trades."""
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from src.scanner import MarketScanner
from src.claude_analyzer import ClaudeAnalyzer
from src.noaa_client import NOAAClient
from src.telegram import TelegramNotifier
from src.sizing import kelly_fraction, position_size

logger = structlog.get_logger(__name__)

# Default path for paper trading state
STATE_FILE = Path("paper_trading_state.json")


class PaperTrader:
    """Continuous paper trading loop that scans markets and logs simulated trades."""

    def __init__(
        self,
        scanner: Optional[MarketScanner] = None,
        analyzer: Optional[ClaudeAnalyzer] = None,
        noaa: Optional[NOAAClient] = None,
        notifier: Optional[TelegramNotifier] = None,
        check_interval: int = 300,
        max_position_usd: float = 25.0,
        kelly_fraction: float = 0.5,
        initial_capital: float = 75.0,
        state_file: Optional[Path] = None,
    ):
        """Initialize the paper trader.

        Args:
            scanner: MarketScanner instance
            analyzer: ClaudeAnalyzer instance
            noaa: NOAAClient instance
            notifier: TelegramNotifier instance
            check_interval: Seconds between market scans
            max_position_usd: Maximum position size in USD
            kelly_fraction: Kelly fraction for position sizing (0.5 = half-Kelly)
            initial_capital: Starting capital in USD
            state_file: Path to JSON state file
        """
        self.scanner = scanner or MarketScanner()
        self.analyzer = analyzer
        self.noaa = noaa
        self.notifier = notifier
        self.check_interval = check_interval
        self.max_position_usd = max_position_usd
        self.kelly_fraction = kelly_fraction
        self.state_file = state_file or STATE_FILE

        self._running = False
        self._state = self._load_state(initial_capital)

    def _load_state(self, default_capital: float) -> dict:
        """Load state from JSON file or create default."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                logger.info("paper_state_loaded", trades=len(state.get("trades", [])))
                return state
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("paper_state_load_failed", error=str(e))

        return {
            "initial_capital": default_capital,
            "current_capital": default_capital,
            "trades": [],
            "open_positions": {},
            "daily_pnl": {},
            "total_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "started_at": datetime.utcnow().isoformat(),
        }

    def _save_state(self) -> None:
        """Save state to JSON file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self._state, f, indent=2, default=str)
        except IOError as e:
            logger.error("paper_state_save_failed", error=str(e))

    async def run(self) -> None:
        """Start the continuous paper trading loop."""
        self._running = True
        logger.info(
            "paper_trader_started",
            interval=self.check_interval,
            capital=self._state["current_capital"],
        )

        if self.notifier:
            await self.notifier.send_startup(mode="paper")

        iteration = 0
        while self._running:
            try:
                iteration += 1
                logger.info("paper_scan_start", iteration=iteration)

                # Run market scan and analysis
                signals = await self._scan_and_analyze()

                # Process signals
                for signal in signals:
                    await self._process_signal(signal)

                # Save state after each scan
                self._save_state()

                # Send daily summary at end of day (every 24th iteration approximately)
                if iteration % (86400 // self.check_interval) == 0:
                    await self._send_daily_summary()

                logger.info(
                    "paper_scan_complete",
                    iteration=iteration,
                    signals=len(signals),
                    capital=self._state["current_capital"],
                    total_pnl=self._state["total_pnl"],
                )

            except asyncio.CancelledError:
                logger.info("paper_trader_cancelled")
                break
            except Exception as e:
                logger.error("paper_scan_error", error=str(e))
                if self.notifier:
                    await self.notifier.send_error(str(e), context="paper_trading_loop")

            await asyncio.sleep(self.check_interval)

        logger.info("paper_trader_stopped")

    async def stop(self) -> None:
        """Stop the paper trading loop."""
        self._running = False
        self._save_state()

    async def _scan_and_analyze(self) -> list[dict]:
        """Scan markets and generate trade signals.

        Returns:
            List of signal dicts with market info and trade recommendation
        """
        signals = []

        # 1. Scan for liquid markets
        try:
            opportunities = await self.scanner.scan_for_opportunities(
                min_volume=500.0, min_liquidity=200.0
            )
        except Exception as e:
            logger.error("market_scan_failed", error=str(e))
            opportunities = []

        # 2. Analyze with Claude AI if available
        if self.analyzer and self.analyzer.is_available and opportunities:
            # Limit to top 50 markets by volume
            sorted_markets = sorted(
                opportunities, key=lambda m: m.get("volume", 0), reverse=True
            )[:50]

            markets_for_analysis = []
            for m in sorted_markets:
                prices = m.get("prices", {})
                yes_price = prices.get("YES", 0.5)
                if 0.05 < yes_price < 0.95:  # Skip extreme-priced markets
                    markets_for_analysis.append({
                        "market_id": m["market_id"],
                        "question": m["question"],
                        "current_price": yes_price,
                    })

            if markets_for_analysis:
                try:
                    results = await self.analyzer.batch_analyze(
                        markets_for_analysis[:20], delay_between=2.0
                    )
                    for r in results:
                        if r.get("mispriced"):
                            signals.append({
                                "source": "claude_ai",
                                "market_id": r["market_id"],
                                "question": r.get("question", ""),
                                "direction": r["direction"],
                                "market_price": r.get("probability", 0.5),
                                "estimated_prob": r["probability"],
                                "edge": r["edge"],
                                "confidence": r["confidence"],
                                "reasoning": r["reasoning"],
                            })
                except Exception as e:
                    logger.error("claude_batch_analysis_failed", error=str(e))

        # 3. Check weather markets with NOAA
        if self.noaa:
            try:
                weather_markets = await self.scanner.fetch_weather_markets()
                cities_str = os.getenv("NOAA_CITIES", "Chicago,NYC,Dallas,Miami,Seattle,Atlanta")
                cities = [c.strip() for c in cities_str.split(",")]
                forecasts = await self.noaa.scan_cities(cities)

                for wm in weather_markets:
                    question = wm.get("question", "")
                    prices = MarketScanner.extract_prices(wm)
                    yes_price = prices.get("YES", 0.5)

                    # Try to match weather market to a city forecast
                    for city, forecast in forecasts.items():
                        if forecast.get("error"):
                            continue
                        if city.lower() in question.lower():
                            high = forecast.get("high_f")
                            low = forecast.get("low_f")
                            if high is not None and low is not None:
                                eval_result = self.noaa.evaluate_weather_market(
                                    high, low, question, yes_price
                                )
                                if eval_result["signal"] != "hold":
                                    signals.append({
                                        "source": "noaa_weather",
                                        "market_id": wm.get("id", ""),
                                        "question": question,
                                        "direction": eval_result["signal"],
                                        "market_price": yes_price,
                                        "estimated_prob": eval_result["estimated_prob"],
                                        "edge": eval_result["edge"],
                                        "confidence": 0.85,
                                        "reasoning": eval_result["reasoning"],
                                    })
                            break

            except Exception as e:
                logger.error("weather_scan_failed", error=str(e))

        return signals

    def _get_bankroll(self) -> float:
        """Calculate total bankroll: cash + estimated value of open positions."""
        cash = self._state["current_capital"]
        open_value = sum(
            pos.get("size_usd", 0) for pos in self._state["open_positions"].values()
        )
        return cash + open_value

    def _get_category_counts(self) -> dict[str, int]:
        """Count open positions by category."""
        counts: dict[str, int] = {}
        for pos in self._state["open_positions"].values():
            cat = pos.get("category", "Unknown")
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    async def _process_signal(self, signal: dict) -> None:
        """Process a trade signal: log it, update P&L simulation."""
        direction = signal.get("direction", "hold")
        if direction == "hold":
            return

        market_id = signal.get("market_id", "unknown")
        edge = abs(signal.get("edge", 0))
        confidence = signal.get("confidence", 0.5)
        market_price = signal.get("market_price", 0.5)
        estimated_prob = signal.get("estimated_prob", 0.5)
        category = signal.get("category", "Unknown")

        # Quarter-Kelly position sizing
        kelly_f = kelly_fraction(estimated_prob, market_price, direction)
        if kelly_f <= 0:
            logger.info("kelly_skip", market=market_id, kelly_f=0, reason="negative_ev")
            return

        bankroll = self._get_bankroll()
        category_counts = self._get_category_counts()
        sized = position_size(
            bankroll=bankroll,
            kelly_f=kelly_f,
            side=direction,
            category=category,
            category_counts=category_counts,
            max_position_override=self.max_position_usd,
        )

        if sized <= 0:
            return

        # Log the simulated trade
        trade = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": signal.get("source", "unknown"),
            "market_id": market_id,
            "question": signal.get("question", "")[:200],
            "direction": direction,
            "market_price": market_price,
            "estimated_prob": estimated_prob,
            "edge": signal.get("edge"),
            "confidence": confidence,
            "kelly_f": round(kelly_f, 4),
            "position_size_usd": sized,
            "bankroll": round(bankroll, 2),
            "category": category,
            "reasoning": signal.get("reasoning", "")[:300],
            "status": "simulated",
        }

        self._state["trades"].append(trade)
        self._state["total_trades"] += 1

        # Track in open positions
        self._state["open_positions"][market_id] = {
            "direction": direction,
            "entry_price": market_price,
            "size_usd": sized,
            "category": category,
            "timestamp": trade["timestamp"],
        }

        logger.info(
            "paper_trade_logged",
            source=signal.get("source"),
            market=signal.get("question", "")[:60],
            direction=direction,
            size=f"${sized:.2f}",
            kelly_f=f"{kelly_f:.4f}",
            edge=f"{edge:.1%}",
            bankroll=f"${bankroll:.2f}",
        )

        # Send Telegram notification
        if self.notifier:
            await self.notifier.send_trade_signal(
                market_name=signal.get("question", "Unknown"),
                direction=direction,
                price=market_price,
                size=sized,
                reasoning=signal.get("reasoning", ""),
            )

    async def _send_daily_summary(self) -> None:
        """Send daily trading summary via Telegram."""
        if not self.notifier:
            return

        today = datetime.utcnow().strftime("%Y-%m-%d")
        today_trades = [
            t for t in self._state["trades"]
            if t.get("timestamp", "").startswith(today)
        ]

        await self.notifier.send_daily_summary(
            total_trades=len(today_trades),
            winning_trades=self._state["winning_trades"],
            total_pnl=self._state["total_pnl"],
            current_balance=self._state["current_capital"],
        )

    def get_summary(self) -> dict:
        """Get current paper trading summary."""
        return {
            "initial_capital": self._state["initial_capital"],
            "current_capital": self._state["current_capital"],
            "total_pnl": self._state["total_pnl"],
            "total_trades": self._state["total_trades"],
            "winning_trades": self._state["winning_trades"],
            "win_rate": (
                self._state["winning_trades"] / self._state["total_trades"] * 100
                if self._state["total_trades"] > 0
                else 0
            ),
            "open_positions": len(self._state["open_positions"]),
            "started_at": self._state.get("started_at", ""),
        }
