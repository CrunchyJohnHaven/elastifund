"""Claude AI market analyzer for probability estimation.

Research-backed design (2026-03-05):
- Base-rate-first prompting: only consistently beneficial prompt technique (-0.014 Brier)
- Anti-anchoring: market price NOT shown to Claude (prevents systematic anchoring)
- Explicit debiasing: Claude told about its YES overconfidence bias
- Calibration layer: temperature scaling post-hoc correction
- Asymmetric thresholds: higher bar for YES trades (56% win) vs NO trades (76% win)
- Category routing: prioritize politics/weather, deprioritize crypto/sports
- Taker fee awareness: edge must exceed fee(p) = p*(1-p)*r to be profitable

References:
- Schoenegger et al. (2025): 38 prompts tested, only base-rate-first works
- Halawi et al. (NeurIPS 2024): RAG system Brier 0.179
- Bridgewater AIA Forecaster (2025): Platt-scaling calibration
- Polymarket taker fees introduced Feb 18, 2026
"""
import math
import os
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# CalibrationV2: Platt scaling parameters (logit-space)
# Fitted on 70% train set, validated on 30% test set (out-of-sample)
# Test-set Brier: 0.286 (raw) → 0.245 (Platt) — improvement of +0.041
# A and B map: calibrated = sigmoid(A * logit(raw) + B)
def _float_env(name: str, default: str) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


PLATT_A = _float_env("PLATT_A", "0.5914")
PLATT_B = _float_env("PLATT_B", "-0.3977")

# Market category keywords for routing
CATEGORY_KEYWORDS = {
    "politics": ["election", "president", "congress", "senate", "governor", "vote",
                  "democrat", "republican", "trump", "biden", "party", "primary",
                  "legislation", "bill", "law", "executive order", "cabinet",
                  "impeach", "poll", "ballot", "nominee", "campaign"],
    "weather": ["temperature", "rain", "snow", "weather", "hurricane", "storm",
                "heat", "cold", "wind", "flood", "drought", "celsius", "fahrenheit",
                "high of", "low of", "degrees"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
               "token", "defi", "nft", "blockchain", "altcoin", "dogecoin", "xrp"],
    "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
               "baseball", "tennis", "golf", "championship", "playoff", "world cup",
               "super bowl", "mvp", "draft", "stanley cup", "series"],
    "geopolitical": ["war", "invasion", "nato", "china", "russia", "taiwan",
                     "sanctions", "ceasefire", "nuclear", "military", "conflict"],
    "fed_rates": ["fed", "federal reserve", "interest rate", "fomc",
                  "recession", "treasury"],
    "economic": ["inflation", "cpi", "gdp", "unemployment rate", "jobs report",
                 "nonfarm", "payroll", "retail sales", "housing starts",
                 "consumer confidence", "pmi", "manufacturing", "trade deficit",
                 "economic growth", "bls", "bureau of labor"],
}

# Category priority: higher = better expected LLM edge
# Research (March 2026 GPT-4.5 analysis): Sports/crypto rank #1/#2 for
# overall bot profitability, but edge comes from arbitrage/speed, NOT
# LLM forecasting. Our system's edge is forecasting-based, so politics/
# weather/economic remain our priority categories.
CATEGORY_PRIORITY = {
    "politics": 3,    # Best LLM category (Lu 2025, confirmed by GPT-4.5 research)
    "weather": 3,     # Structural arbitrage opportunity (NOAA/GFS/HRRR data)
    "economic": 2,    # NEW: Scheduled releases, 95% consensus alignment, ~5% surprise edge (Dysrupt Labs)
    "crypto": 0,      # No LLM edge, latency arb dead post-fees (research confirms speed-based)
    "sports": 0,      # Minimal LLM edge, quant teams set lines (research: #1 for arb bots, not LLMs)
    "geopolitical": 1, # ~30% worse than experts (RAND), high uncertainty
    "fed_rates": 0,   # Worst category — systematic overconfidence
    "unknown": 0,     # REJECT — unclassifiable markets have no structural LLM edge
}

# Polymarket taker fee rates (introduced Feb 18, 2026)
TAKER_FEE_RATES = {
    "crypto": 0.025,   # ~1.56% max effective at p=0.50
    "sports": 0.007,   # ~0.44% max effective at p=0.50
    "default": 0.0,    # Other categories: no taker fee yet
}


def classify_market_category(question: str) -> str:
    """Classify a market question into a category based on keywords."""
    question_lower = question.lower()
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for kw in keywords if kw in question_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def calculate_taker_fee(price: float, category: str) -> float:
    """Calculate Polymarket taker fee for a given price and category.

    Fee formula: fee(p) = p * (1-p) * r
    At p=0.50 with r=0.025 (crypto): fee = 0.00625 per share (1.25%)
    """
    rate = TAKER_FEE_RATES.get(category, TAKER_FEE_RATES["default"])
    return price * (1 - price) * rate


def calibrate_probability(raw_prob: float) -> float:
    """Apply Platt scaling calibration to Claude's raw probability.

    Uses logit-space logistic regression fitted on 70% of 532 resolved markets,
    validated on held-out 30% test set. Reduces Brier from 0.286 to 0.245
    out-of-sample. Corrects Claude's systematic YES overconfidence:
    90% → 71%, 80% → 60%, 70% → 53%.
    """
    raw_prob = max(0.001, min(0.999, raw_prob))
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5

    # Preserve symmetry around 50% so underconfidence/overconfidence are treated
    # consistently on YES and NO sides.
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability(1.0 - raw_prob)

    logit_input = math.log(raw_prob / (1 - raw_prob))
    logit_output = PLATT_A * logit_input + PLATT_B
    logit_output = max(-30, min(30, logit_output))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


class ClaudeAnalyzer:
    """Uses Claude AI to estimate market probabilities and identify mispricings.

    Research-backed improvements (2026-03-05):
    - Anti-anchoring prompt (no market price shown)
    - Base-rate-first reasoning (only prompt strategy proven to help)
    - Explicit debiasing instruction (Claude overestimates YES by 20-30%)
    - Post-hoc calibration layer (temperature scaling from 532-market backtest)
    - Asymmetric edge thresholds (NO trades: 5%, YES trades: 15%)
    - Category-based market filtering (skip crypto/sports, prioritize politics/weather)
    - Taker fee subtraction from edge calculations
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
        yes_threshold: float = 0.15,
        no_threshold: float = 0.05,
        min_category_priority: int = 1,
        use_calibration: bool = True,
        account_for_fees: bool = True,
        use_ensemble: bool = False,
    ):
        """Initialize the Claude analyzer.

        Args:
            api_key: Anthropic API key (falls back to ANTHROPIC_API_KEY env var)
            model: Claude model to use
            yes_threshold: Minimum edge to signal buy_yes (higher bar: 56% historical win rate)
            no_threshold: Minimum edge to signal buy_no (lower bar: 76% historical win rate)
            min_category_priority: Minimum category priority to analyze (0=skip, 1=cautious, 2+=analyze)
            use_calibration: Whether to apply post-hoc calibration
            account_for_fees: Whether to subtract taker fees from edge
            use_ensemble: Whether to use multi-model ensemble when available
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.yes_threshold = yes_threshold
        self.no_threshold = no_threshold
        self.min_category_priority = min_category_priority
        self.use_calibration = use_calibration
        self.account_for_fees = account_for_fees
        self.use_ensemble = use_ensemble
        self._client = None
        self._ensemble = None

        if self.api_key:
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.api_key)
                logger.info("claude_analyzer_initialized", model=model,
                           yes_threshold=yes_threshold, no_threshold=no_threshold,
                           calibration=use_calibration, fees=account_for_fees)
            except ImportError:
                logger.error("anthropic_package_not_installed")
        else:
            logger.warning("claude_analyzer_no_api_key")

        if self.use_ensemble:
            try:
                from src.ensemble import LLMEnsemble
                self._ensemble = LLMEnsemble()
                logger.info("claude_analyzer_ensemble_enabled")
            except Exception as e:
                logger.warning("claude_analyzer_ensemble_init_failed", error=str(e))
                self._ensemble = None

    @property
    def is_available(self) -> bool:
        """Check if the analyzer is ready to use."""
        return self._client is not None

    async def analyze_market(
        self,
        question: str,
        current_price: float,
        context: str = "",
        news_section: str = "",
    ) -> dict:
        """Analyze a market and return probability estimate with reasoning.

        Anti-anchoring: current_price is NOT shown to Claude. It is only used
        after estimation to compute edge and direction.

        Args:
            question: The market question (e.g., "Will Bitcoin reach $100K by June?")
            current_price: Current YES price on Polymarket (0.0–1.0)
            context: Additional context (news, data, etc.)

        Returns:
            Dict with keys:
                - probability: float (raw Claude estimate)
                - calibrated_probability: float (after calibration correction)
                - confidence: float (0.0–1.0) confidence in the estimate
                - reasoning: str explanation
                - mispriced: bool whether market appears mispriced
                - direction: str "buy_yes", "buy_no", or "hold"
                - edge: float net edge after calibration and fees
                - raw_edge: float raw edge before adjustments
                - category: str detected market category
                - category_priority: int priority score for this category
                - taker_fee: float estimated taker fee
                - skipped: bool whether this market was skipped (low-priority category)
        """
        # Classify market category
        category = classify_market_category(question)
        priority = CATEGORY_PRIORITY.get(category, 2)
        client = getattr(self, "_client", None)
        ensemble = getattr(self, "_ensemble", None)

        if not client and not ensemble:
            return {
                "probability": current_price,
                "calibrated_probability": current_price,
                "confidence": 0.0,
                "reasoning": "Analyzer not available (Claude and ensemble unavailable)",
                "mispriced": False,
                "direction": "hold",
                "edge": 0.0,
                "raw_edge": 0.0,
                "category": category,
                "category_priority": priority,
                "taker_fee": 0.0,
                "skipped": False,
            }

        # Skip low-priority categories
        if priority < self.min_category_priority:
            logger.info("market_skipped_low_priority",
                       question=question[:80], category=category, priority=priority)
            return {
                "probability": current_price,
                "calibrated_probability": current_price,
                "confidence": 0.0,
                "reasoning": f"Skipped: {category} category has low LLM edge (priority {priority})",
                "mispriced": False,
                "direction": "hold",
                "edge": 0.0,
                "raw_edge": 0.0,
                "category": category,
                "category_priority": priority,
                "taker_fee": 0.0,
                "skipped": True,
            }

        # Build prompt WITHOUT market price (anti-anchoring)
        prompt = self._build_prompt(question, context, news_section=news_section)

        try:
            response_text: Optional[str] = None

            # Ensemble path (optional): falls back to Claude if unavailable/failed.
            if ensemble:
                response_text = await self._analyze_with_ensemble(
                    question=question,
                    context=context,
                    category=category,
                )

            if response_text is None:
                if not client:
                    raise RuntimeError("Claude API not available and ensemble failed")
                message = client.messages.create(
                    model=self.model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = message.content[0].text.strip()

            result = self._parse_response(response_text, current_price, category)

            logger.info(
                "market_analyzed",
                question=question[:80],
                category=category,
                priority=priority,
                market_price=current_price,
                raw_prob=result["probability"],
                calibrated_prob=result["calibrated_probability"],
                mispriced=result["mispriced"],
                direction=result["direction"],
                edge=result["edge"],
                taker_fee=result["taker_fee"],
            )
            return result

        except Exception as e:
            logger.error("claude_analysis_failed", error=str(e), question=question[:80])
            return {
                "probability": current_price,
                "calibrated_probability": current_price,
                "confidence": 0.0,
                "reasoning": f"Analysis failed: {str(e)}",
                "mispriced": False,
                "direction": "hold",
                "edge": 0.0,
                "raw_edge": 0.0,
                "category": category,
                "category_priority": priority,
                "taker_fee": 0.0,
                "skipped": False,
            }

    async def _analyze_with_ensemble(
        self, question: str, context: str, category: str
    ) -> Optional[str]:
        """Run ensemble estimate and return parser-compatible response text."""
        if not self._ensemble:
            return None

        try:
            ensemble_result = await self._ensemble.estimate_probability(
                question=question,
                context=context,
                category=category,
            )
            probability = float(ensemble_result.get("ensemble_prob", 0.5))
            agreement = float(ensemble_result.get("agreement_score", 0.0))
            confidence = "high" if agreement >= 0.75 else "medium" if agreement >= 0.55 else "low"

            reasons = ensemble_result.get("reasoning", {})
            reasoning = ""
            if isinstance(reasons, dict) and reasons:
                # Keep reasoning short and deterministic.
                first_key = sorted(reasons.keys())[0]
                reasoning = str(reasons.get(first_key, "")).strip()

            if not reasoning:
                reasoning = "Ensemble estimate generated from available models."

            logger.info(
                "ensemble_analysis_used",
                agreement=agreement,
                probability=probability,
                models=len(ensemble_result.get("model_probs", {})),
            )

            return (
                f"PROBABILITY: {probability:.4f}\n"
                f"CONFIDENCE: {confidence}\n"
                f"REASONING: {reasoning}"
            )
        except Exception as e:
            logger.warning("ensemble_analysis_failed_fallback_to_claude", error=str(e))
            return None

    async def batch_analyze(
        self,
        markets: list[dict],
        delay_between: float = 1.0,
    ) -> list[dict]:
        """Analyze multiple markets sequentially with rate limiting.

        Args:
            markets: List of dicts with keys: question, current_price, context (optional)
            delay_between: Seconds between API calls

        Returns:
            List of analysis result dicts
        """
        import asyncio

        results = []
        for i, market in enumerate(markets):
            result = await self.analyze_market(
                question=market["question"],
                current_price=market["current_price"],
                context=market.get("context", ""),
            )
            result["market_id"] = market.get("market_id", f"market_{i}")
            result["question"] = market["question"]
            results.append(result)

            if i < len(markets) - 1:
                await asyncio.sleep(delay_between)

        mispriced_count = sum(1 for r in results if r["mispriced"])
        logger.info(
            "batch_analysis_complete",
            total=len(results),
            mispriced=mispriced_count,
        )
        return results

    def _build_prompt(self, question: str, context: str, news_section: str = "") -> str:
        """Build the analysis prompt for Claude.

        Research-backed design:
        - NO market price shown (anti-anchoring, per 2026-03-05 diagnosis)
        - Base-rate-first reasoning (Schoenegger 2025: -0.014 Brier, best prompt technique)
        - Explicit debiasing (Claude overestimates YES by 20-30%, per 532-market backtest)
        - Frequency framing (asking for historical frequency, not probability)
        - NO chain-of-thought (Lu 2025: extended reasoning makes Claude underconfident)
        - NO Bayesian reasoning (Schoenegger 2025: +0.030 Brier, significantly HURTS)
        - News enrichment: recent headlines injected after question (if available)
        """
        ctx_section = f"\nRelevant context:\n{context}\n" if context else ""
        news_block = f"\n{news_section}\n" if news_section else ""

        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"""Estimate the probability that this event resolves YES.

Today's date: {current_date}

Question: {question}
{ctx_section}{news_block}
Step 1: What is the historical base rate for events like this? (What fraction of similar events in the past resolved YES?)
Step 2: What specific evidence adjusts the probability up or down from the base rate?
Step 3: Give your final estimate.

IMPORTANT CALIBRATION NOTE: You have a documented tendency to overestimate YES probabilities by 20-30%. When you feel 70-80% confident in YES, the true rate is closer to 50-55%. When you feel 90%+ confident in YES, the true rate is closer to 63%. Adjust your estimate downward accordingly.

IMPORTANT DATE NOTE: Use today's date above to ground your reasoning. Do NOT rely on training-data assumptions about future events. If an event's deadline has already passed, account for that. If a product has already launched, that changes the probability.

If recent news headlines are provided above, weight them appropriately — breaking developments may shift probabilities meaningfully, but do not anchor solely on headlines.

Respond in this exact format:
PROBABILITY: <number between 0.01 and 0.99>
CONFIDENCE: <low, medium, or high>
REASONING: <1-2 sentences>"""

    def _parse_response(self, response_text: str, current_price: float, category: str) -> dict:
        """Parse Claude's response into structured result with calibration and fee adjustments."""
        probability = 0.5  # Default to 50% (not market price — avoid anchoring)
        confidence = 0.5
        reasoning = response_text

        for line in response_text.split("\n"):
            line = line.strip()
            if line.upper().startswith("PROBABILITY:"):
                try:
                    val = line.split(":", 1)[1].strip()
                    probability = float(val)
                    probability = max(0.01, min(0.99, probability))
                except (ValueError, IndexError):
                    pass
            elif line.upper().startswith("CONFIDENCE:"):
                try:
                    val = line.split(":", 1)[1].strip().lower()
                    confidence_map = {"low": 0.3, "medium": 0.6, "high": 0.9}
                    confidence = confidence_map.get(val, 0.5)
                    # Also handle numeric values
                    try:
                        confidence = float(val)
                        confidence = max(0.0, min(1.0, confidence))
                    except ValueError:
                        pass
                except (ValueError, IndexError):
                    pass
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        # Apply calibration correction
        raw_probability = probability
        if self.use_calibration:
            probability = calibrate_probability(raw_probability)

        # Calculate raw edge (calibrated estimate vs market price)
        raw_edge = probability - current_price

        # Calculate taker fee
        if self.account_for_fees:
            # Fee applies to the price we'd be buying at
            buy_price = current_price if raw_edge > 0 else (1 - current_price)
            taker_fee = calculate_taker_fee(buy_price, category)
        else:
            taker_fee = 0.0

        # Net edge after fees
        net_edge = abs(raw_edge) - taker_fee

        # Apply asymmetric thresholds
        if raw_edge > 0:
            # Buying YES — higher threshold required (56% historical win rate)
            mispriced = net_edge >= self.yes_threshold
            direction = "buy_yes" if mispriced else "hold"
        elif raw_edge < 0:
            # Buying NO — lower threshold (76% historical win rate, our primary edge)
            mispriced = net_edge >= self.no_threshold
            direction = "buy_no" if mispriced else "hold"
        else:
            mispriced = False
            direction = "hold"

        return {
            "probability": raw_probability,
            "calibrated_probability": probability,
            "confidence": confidence,
            "reasoning": reasoning,
            "mispriced": mispriced,
            "direction": direction,
            "edge": net_edge if mispriced else 0.0,
            "raw_edge": raw_edge,
            "category": category,
            "category_priority": CATEGORY_PRIORITY.get(category, 2),
            "taker_fee": taker_fee,
            "skipped": False,
        }

    def estimate_monthly_cost(self, analyses_per_day: int = 50) -> float:
        """Estimate monthly API cost.

        Args:
            analyses_per_day: Number of market analyses per day

        Returns:
            Estimated monthly cost in USD
        """
        # Approximate model rates ($/MTok input/output).
        # Defaults to Haiku pricing for unknown model names.
        model = getattr(self, "model", "claude-haiku-4-5").lower()
        in_rate = 1.0
        out_rate = 5.0
        if "sonnet" in model:
            in_rate = 3.0
            out_rate = 15.0

        avg_input_tokens = 500
        avg_output_tokens = 100
        calls_per_month = analyses_per_day * 30

        input_cost = (avg_input_tokens * calls_per_month / 1_000_000) * in_rate
        output_cost = (avg_output_tokens * calls_per_month / 1_000_000) * out_rate

        return input_cost + output_cost
