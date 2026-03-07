"""Backtest engine: run Claude analysis on resolved markets, compute performance."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Simulated entry prices for Monte Carlo P&L
ENTRY_PRICES = [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]

# Anti-anchoring prompt — does NOT show market price to Claude
ANALYSIS_PROMPT = """You are a probability estimation expert. Estimate the TRUE probability that this event resolves YES.

Question: {question}

Additional context: {description}

IMPORTANT RULES:
1. Estimate from FIRST PRINCIPLES using your knowledge
2. Do NOT assume any particular market price
3. Consider base rates, historical precedents, and current conditions
4. Be well-calibrated — a 70% estimate should be right about 70% of the time

Respond in EXACTLY this format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentence explanation>"""


@dataclass
class TradeResult:
    question: str
    actual_outcome: str
    claude_prob: float
    confidence: str
    entry_price: float
    direction: str  # "buy_yes" or "buy_no"
    size: float
    pnl: float
    won: bool
    edge: float


class ClaudeCache:
    """Persistent cache for Claude estimates to avoid re-calling API."""

    def __init__(self, cache_path: Optional[str] = None):
        self.path = cache_path or os.path.join(DATA_DIR, "claude_cache.json")
        self._cache = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                self._cache = json.load(f)
            logger.info(f"Claude cache: {len(self._cache)} entries")

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._cache, f, indent=2)

    def _key(self, question: str) -> str:
        return hashlib.sha256(question.encode()).hexdigest()[:16]

    def get(self, question: str) -> Optional[dict]:
        return self._cache.get(self._key(question))

    def put(self, question: str, result: dict):
        self._cache[self._key(question)] = result
        self._save()


class BacktestEngine:
    """Run backtests against resolved Polymarket markets."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001",
        edge_threshold: float = 0.05,
        position_size: float = 2.0,
        starting_capital: float = 75.0,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.edge_threshold = edge_threshold
        self.position_size = position_size
        self.starting_capital = starting_capital
        self.cache = ClaudeCache()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def _get_estimate(self, question: str, description: str = "") -> dict:
        """Get Claude's probability estimate, using cache if available."""
        cached = self.cache.get(question)
        if cached:
            return cached

        prompt = ANALYSIS_PROMPT.format(question=question, description=description[:300])
        client = self._get_client()

        try:
            msg = client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            result = self._parse_response(text)
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            result = {"probability": 0.5, "confidence": "low", "reasoning": f"API error: {e}"}

        self.cache.put(question, result)
        return result

    @staticmethod
    def _parse_response(text: str) -> dict:
        prob = 0.5
        confidence = "medium"
        reasoning = text

        for line in text.split("\n"):
            line = line.strip()
            if line.upper().startswith("PROBABILITY:"):
                try:
                    val = line.split(":", 1)[1].strip()
                    prob = float(val)
                    prob = max(0.01, min(0.99, prob))
                except (ValueError, IndexError):
                    pass
            elif line.upper().startswith("CONFIDENCE:"):
                confidence = line.split(":", 1)[1].strip().lower()
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        return {"probability": prob, "confidence": confidence, "reasoning": reasoning}

    def _kelly_size(self, est_prob: float, market_price: float, direction: str) -> float:
        """Quarter-Kelly position sizing with fee adjustment.

        Uses quarter-Kelly (research consensus for prediction markets) and
        accounts for 2% winner fee reducing effective payout from $1.00 to $0.98.
        Never exceeds 20% of capital on a single position.
        """
        winner_fee = 0.02
        payout = 1.0 - winner_fee  # Net $0.98 per winning share

        if direction == "buy_yes":
            p = est_prob
            cost = market_price
        else:
            p = 1.0 - est_prob
            cost = 1.0 - market_price

        if cost <= 0 or cost >= payout:
            return 0.0

        odds = (payout - cost) / cost
        if odds <= 0:
            return 0.0

        kelly = (p * odds - (1.0 - p)) / odds
        quarter_kelly = kelly / 4.0  # Quarter-Kelly (was half)
        if quarter_kelly <= 0:
            return 0.0

        max_alloc = 0.20 * self.starting_capital  # Never >20% per position
        return min(quarter_kelly * self.starting_capital, self.position_size, max_alloc)

    def _resolve_trade(self, direction: str, entry_price: float, size: float, actual: str) -> tuple[bool, float]:
        """Resolve a trade. Returns (won, pnl).

        Applies 2% winner fee for weather markets and spread-based slippage.
        See validation.py for detailed cost modeling.
        """
        winner_fee = 0.02  # 2% winner fee on weather market resolved positions
        half_spread = 0.035  # ~3.5¢ half-spread for US weather major markets

        if direction == "buy_yes":
            effective_entry = min(entry_price + half_spread, 0.99)
            if actual == "YES_WON":
                shares = size / effective_entry
                gross_payout = shares * 1.0
                fee = gross_payout * winner_fee
                pnl = gross_payout - fee - size
                return True, pnl
            else:
                return False, -size
        else:  # buy_no
            effective_no_price = min((1.0 - entry_price) + half_spread, 0.99)
            if actual == "NO_WON":
                shares = size / effective_no_price
                gross_payout = shares * 1.0
                fee = gross_payout * winner_fee
                pnl = gross_payout - fee - size
                return True, pnl
            else:
                return False, -size

    def run(self, max_markets: int = 0) -> dict:
        """Run full backtest on cached historical markets."""
        markets_path = os.path.join(DATA_DIR, "historical_markets.json")
        if not os.path.exists(markets_path):
            raise FileNotFoundError(f"No data at {markets_path}. Run collector first.")

        with open(markets_path) as f:
            data = json.load(f)

        markets = data.get("markets", [])
        if max_markets > 0:
            markets = markets[:max_markets]

        logger.info(f"Running backtest on {len(markets)} markets")

        all_trades: list[TradeResult] = []
        brier_scores = []
        calibration_buckets: dict[str, list] = {
            "0.0-0.1": [], "0.1-0.2": [], "0.2-0.3": [], "0.3-0.4": [], "0.4-0.5": [],
            "0.5-0.6": [], "0.6-0.7": [], "0.7-0.8": [], "0.8-0.9": [], "0.9-1.0": [],
        }

        for i, market in enumerate(markets):
            question = market["question"]
            actual = market["actual_outcome"]
            description = market.get("description", "")

            # Get Claude's estimate
            est = self._get_estimate(question, description)
            claude_prob = est["probability"]
            confidence = est["confidence"]

            # Brier score: (estimate - actual)^2
            actual_binary = 1.0 if actual == "YES_WON" else 0.0
            brier = (claude_prob - actual_binary) ** 2
            brier_scores.append(brier)

            # Calibration
            bucket_idx = min(int(claude_prob * 10), 9)
            bucket_keys = list(calibration_buckets.keys())
            calibration_buckets[bucket_keys[bucket_idx]].append(actual_binary)

            # Monte Carlo: simulate trades at various entry prices
            for entry_price in ENTRY_PRICES:
                edge = claude_prob - entry_price
                abs_edge = abs(edge)

                if abs_edge < self.edge_threshold:
                    continue

                if edge > 0:
                    direction = "buy_yes"
                else:
                    direction = "buy_no"

                size = self._kelly_size(claude_prob, entry_price, direction)
                if size < 0.10:
                    continue

                won, pnl = self._resolve_trade(direction, entry_price, size, actual)

                all_trades.append(TradeResult(
                    question=question,
                    actual_outcome=actual,
                    claude_prob=claude_prob,
                    confidence=confidence,
                    entry_price=entry_price,
                    direction=direction,
                    size=size,
                    pnl=pnl,
                    won=won,
                    edge=abs_edge,
                ))

            if (i + 1) % 50 == 0:
                logger.info(f"Processed {i + 1}/{len(markets)} markets, {len(all_trades)} trades so far")

        results = self._compute_results(markets, all_trades, brier_scores, calibration_buckets)

        # Save
        results_path = os.path.join(DATA_DIR, "backtest_results.json")
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results saved to {results_path}")

        return results

    def _compute_results(
        self,
        markets: list,
        trades: list[TradeResult],
        brier_scores: list,
        calibration_buckets: dict,
    ) -> dict:
        """Compute comprehensive backtest metrics."""
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.won)
        win_rate = wins / total_trades if total_trades > 0 else 0.0

        total_pnl = sum(t.pnl for t in trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0

        # Drawdown
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for t in trades:
            cumulative += t.pnl
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_drawdown = max(max_drawdown, dd)

        # Brier score
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else 0.5

        # Calibration
        cal_summary = {}
        for bucket, actuals in calibration_buckets.items():
            if actuals:
                cal_summary[bucket] = {
                    "count": len(actuals),
                    "actual_rate": sum(actuals) / len(actuals),
                }
            else:
                cal_summary[bucket] = {"count": 0, "actual_rate": None}

        # ARR estimate
        # Assume 5 trades/day based on live bot behavior
        trades_per_market = total_trades / len(markets) if markets else 0
        daily_gross = avg_pnl * 5 if avg_pnl > 0 else avg_pnl * 5
        monthly_gross = daily_gross * 30
        monthly_net = monthly_gross - 20  # $20/mo infra
        annual_net = monthly_net * 12
        arr_pct = (annual_net / self.starting_capital) * 100

        # Edge distribution
        edges = [t.edge for t in trades]
        avg_edge = sum(edges) / len(edges) if edges else 0.0

        # By direction
        yes_trades = [t for t in trades if t.direction == "buy_yes"]
        no_trades = [t for t in trades if t.direction == "buy_no"]
        yes_win = sum(1 for t in yes_trades if t.won) / len(yes_trades) if yes_trades else 0
        no_win = sum(1 for t in no_trades if t.won) / len(no_trades) if no_trades else 0

        # By confidence
        conf_stats = {}
        for conf in ["low", "medium", "high"]:
            ct = [t for t in trades if t.confidence == conf]
            if ct:
                conf_stats[conf] = {
                    "count": len(ct),
                    "win_rate": sum(1 for t in ct if t.won) / len(ct),
                    "avg_pnl": sum(t.pnl for t in ct) / len(ct),
                }

        return {
            "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "markets_analyzed": len(markets),
            "total_trades": total_trades,
            "summary": {
                "win_rate": round(win_rate, 4),
                "total_pnl": round(total_pnl, 2),
                "avg_pnl_per_trade": round(avg_pnl, 4),
                "max_drawdown": round(max_drawdown, 2),
                "avg_brier_score": round(avg_brier, 4),
                "avg_edge": round(avg_edge, 4),
            },
            "by_direction": {
                "buy_yes": {"count": len(yes_trades), "win_rate": round(yes_win, 4)},
                "buy_no": {"count": len(no_trades), "win_rate": round(no_win, 4)},
            },
            "by_confidence": conf_stats,
            "calibration": cal_summary,
            "arr_estimate": {
                "daily_gross": round(daily_gross, 2),
                "monthly_gross": round(monthly_gross, 2),
                "monthly_net": round(monthly_net, 2),
                "annual_net": round(annual_net, 2),
                "arr_pct": round(arr_pct, 1),
                "note": "Based on 5 trades/day, $20/mo infra, $75 capital",
            },
            "sample_trades": [
                {
                    "question": t.question[:80],
                    "direction": t.direction,
                    "entry": t.entry_price,
                    "claude_prob": t.claude_prob,
                    "actual": t.actual_outcome,
                    "won": t.won,
                    "pnl": round(t.pnl, 4),
                }
                for t in trades[:20]
            ],
        }


def print_report(results: dict):
    """Pretty-print backtest results."""
    s = results["summary"]
    arr = results["arr_estimate"]
    cal = results["calibration"]

    print("\n" + "=" * 60)
    print("  BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Markets analyzed:    {results['markets_analyzed']}")
    print(f"  Total trades:        {results['total_trades']}")
    print(f"  Win rate:            {s['win_rate']:.1%}")
    print(f"  Total P&L:           ${s['total_pnl']:+.2f}")
    print(f"  Avg P&L/trade:       ${s['avg_pnl_per_trade']:+.4f}")
    print(f"  Max drawdown:        ${s['max_drawdown']:.2f}")
    print(f"  Avg Brier score:     {s['avg_brier_score']:.4f} (0.25 = random)")
    print(f"  Avg edge:            {s['avg_edge']:.1%}")

    print(f"\n  By Direction:")
    for d, stats in results["by_direction"].items():
        print(f"    {d}: {stats['count']} trades, {stats['win_rate']:.1%} win rate")

    if results.get("by_confidence"):
        print(f"\n  By Confidence:")
        for conf, stats in results["by_confidence"].items():
            print(f"    {conf}: {stats['count']} trades, {stats['win_rate']:.1%} win, ${stats['avg_pnl']:+.4f}/trade")

    print(f"\n  Calibration (Claude est → actual YES rate):")
    for bucket, stats in cal.items():
        if stats["count"] > 0:
            print(f"    {bucket}: {stats['count']:3d} markets, actual YES = {stats['actual_rate']:.1%}")

    print(f"\n  ARR Estimate ({arr['note']}):")
    print(f"    Daily gross:       ${arr['daily_gross']:+.2f}")
    print(f"    Monthly gross:     ${arr['monthly_gross']:+.2f}")
    print(f"    Monthly net:       ${arr['monthly_net']:+.2f}")
    print(f"    Annual net:        ${arr['annual_net']:+.2f}")
    print(f"    ARR %:             {arr['arr_pct']:+.1f}%")

    # Sample trades
    if results.get("sample_trades"):
        print(f"\n  Sample Trades (first 10):")
        for t in results["sample_trades"][:10]:
            status = "WIN" if t["won"] else "LOSS"
            print(f"    [{status}] {t['direction']:8s} @ {t['entry']:.2f} "
                  f"(Claude: {t['claude_prob']:.2f}, actual: {t['actual']}) "
                  f"P&L: ${t['pnl']:+.4f}")
            print(f"           {t['question']}")

    print("=" * 60)
