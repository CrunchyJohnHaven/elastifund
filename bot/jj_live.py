#!/usr/bin/env python3
"""
JJ LIVE TRADING LOOP — Autonomous Polymarket Trader
====================================================
Bridges the signal-finding brain (MarketScanner + ClaudeAnalyzer)
with real order execution via Polymarket CLOB.

Designed to run on VPS (AWS Lightsail Dublin) as systemd service.

Features (March 7, 2026):
  - Velocity filtering: only trade markets resolving within MAX_RESOLUTION_HOURS
  - Velocity scoring: rank signals by annualized edge/lockup (faster = higher priority)
  - Geoblock check on startup (fail-fast if in restricted country)
  - Platt scaling calibration (reduces overconfidence: 90% → 71%, 80% → 60%)
  - Category filtering (skip crypto/sports, prioritize politics/weather/economic)
  - Taker fee awareness (subtract fees from edge before trading)
  - Post-only orders on fee-enabled markets (zero fees + maker rebates)
  - Asymmetric thresholds (YES: 15% edge, NO: 5% edge)
  - Anti-anchoring (market price NOT shown to Claude)
  - Half-Kelly position sizing with daily loss limits

Usage:
    python jj_live.py                # single cycle (test)
    python jj_live.py --continuous   # 24/7 daemon mode
    python jj_live.py --status       # show current state

Environment Variables (from .env):
    POLY_PRIVATE_KEY or POLYMARKET_PK  — wallet private key
    POLY_SAFE_ADDRESS                  — funder wallet address
    POLY_BUILDER_API_KEY/SECRET/PASSPHRASE — CLOB API creds
    ANTHROPIC_API_KEY                  — Claude AI key
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — notifications

JJ Parameters (override via env):
    JJ_MAX_POSITION_USD       — max per trade (default: 15)
    JJ_MAX_DAILY_LOSS_USD     — daily loss limit (default: 25)
    JJ_MAX_EXPOSURE_PCT       — max % of bankroll deployed (default: 0.90)
    JJ_KELLY_FRACTION         — Kelly multiplier (default: 0.50)
    JJ_SCAN_INTERVAL          — seconds between cycles (default: 180)
    JJ_MAX_OPEN_POSITIONS     — max concurrent positions (default: 30)
    JJ_MIN_EDGE               — min edge to trade (default: 0.05)
    JJ_INITIAL_BANKROLL       — starting bankroll (default: 1000)
    JJ_MAX_RESOLUTION_HOURS   — max hours to resolution (default: 1.0 = 60min)
"""

import os
import sys
import json
import time
import math
import asyncio
import logging
import argparse
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import numpy as np

# Auto-load .env
from dotenv import load_dotenv
load_dotenv()

# Ensure POLY_PRIVATE_KEY is set (VPS may use POLYMARKET_PK instead)
if not os.environ.get("POLY_PRIVATE_KEY"):
    pk = os.environ.get("POLYMARKET_PK", "")
    if pk:
        # Add 0x prefix if missing
        if not pk.startswith("0x"):
            pk = "0x" + pk
        os.environ["POLY_PRIVATE_KEY"] = pk

bot_root = Path(__file__).resolve().parent
project_root = bot_root.parent
sys.path.insert(0, str(bot_root))
sys.path.insert(0, str(project_root))
# Support this repository layout where src lives under polymarket-bot/src.
poly_root = project_root / "polymarket-bot"
if (poly_root / "src").exists():
    sys.path.insert(0, str(poly_root))

from src.scanner import MarketScanner
from src.claude_analyzer import ClaudeAnalyzer

# LLM Ensemble: multi-model + agentic RAG (preferred over single Claude)
try:
    from bot.llm_ensemble import LLMEnsemble, disagreement_kelly_modifier
except ImportError:
    try:
        from llm_ensemble import LLMEnsemble, disagreement_kelly_modifier
    except ImportError:
        LLMEnsemble = None

        def disagreement_kelly_modifier(std_dev: float) -> float:
            return 1.0

# Use official py-clob-client for order placement (the custom src/bot.py
# has HMAC body mismatch and wrong EIP-712 domain bugs that cause 403s)
try:
    from py_clob_client.client import ClobClient as OfficialClobClient
    from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL
except ImportError:
    OfficialClobClient = None
    ApiCreds = None
    OrderArgs = None
    OrderType = None
    BUY = None
    SELL = None

# Handle different Telegram class names across codebase versions
try:
    from src.telegram import TelegramNotifier
except ImportError:
    try:
        from src.telegram import TelegramBot as TelegramNotifier
    except ImportError:
        TelegramNotifier = None

# Signal sources #2 and #3
try:
    from bot.lmsr_engine import LMSREngine
except ImportError:
    try:
        from lmsr_engine import LMSREngine
    except ImportError:
        LMSREngine = None

try:
    from bot.wallet_flow_detector import get_signals_for_engine as wallet_flow_get_signals
except ImportError:
    try:
        from wallet_flow_detector import get_signals_for_engine as wallet_flow_get_signals
    except ImportError:
        wallet_flow_get_signals = None

try:
    from bot.cross_platform_arb import get_signals_for_engine as arb_get_signals
except ImportError:
    try:
        from cross_platform_arb import get_signals_for_engine as arb_get_signals
    except ImportError:
        arb_get_signals = None

# Market quarantine for CLOB 404 handling
try:
    from bot.market_quarantine import MarketQuarantine
except ImportError:
    try:
        from market_quarantine import MarketQuarantine
    except ImportError:
        MarketQuarantine = None

# Signal source #5: WebSocket Trade Stream + VPIN/OFI microstructure defense
try:
    from bot.ws_trade_stream import TradeStreamManager, FlowRegime
except ImportError:
    try:
        from ws_trade_stream import TradeStreamManager, FlowRegime
    except ImportError:
        TradeStreamManager = None
        FlowRegime = None

# Signal source #6: Semantic Lead-Lag Arbitrage Engine
try:
    from bot.lead_lag_engine import LeadLagEngine
except ImportError:
    try:
        from lead_lag_engine import LeadLagEngine
    except ImportError:
        LeadLagEngine = None

try:
    from bot.combinatorial_integration import (
        CombinatorialConfig,
        CombinatorialSignalStore,
        attach_signal_source_metadata,
        evaluate_combinatorial_risk,
        is_combinatorial_signal,
    )
except ImportError:
    try:
        from combinatorial_integration import (  # type: ignore
            CombinatorialConfig,
            CombinatorialSignalStore,
            attach_signal_source_metadata,
            evaluate_combinatorial_risk,
            is_combinatorial_signal,
        )
    except ImportError:
        CombinatorialConfig = None
        CombinatorialSignalStore = None

        def attach_signal_source_metadata(signal: dict) -> dict:  # type: ignore[no-redef]
            return signal

        def is_combinatorial_signal(signal: dict) -> bool:  # type: ignore[no-redef]
            return False

        def evaluate_combinatorial_risk(*args, **kwargs):  # type: ignore[no-redef]
            return None

try:
    from bot.sum_violation_scanner import SumViolationScanner
except ImportError:
    try:
        from sum_violation_scanner import SumViolationScanner  # type: ignore
    except ImportError:
        SumViolationScanner = None

# A-6 live execution: state machine + order routing
try:
    from bot.a6_executor import A6BasketExecutor, A6ExecutorConfig, A6BasketState
    from bot.a6_command_router import A6CommandRouter
except ImportError:
    try:
        from a6_executor import A6BasketExecutor, A6ExecutorConfig, A6BasketState  # type: ignore
        from a6_command_router import A6CommandRouter  # type: ignore
    except ImportError:
        A6BasketExecutor = None
        A6ExecutorConfig = None
        A6BasketState = None
        A6CommandRouter = None

try:
    from bot.kill_rules import run_combinatorial_promotion_battery
except ImportError:
    try:
        from kill_rules import run_combinatorial_promotion_battery  # type: ignore
    except ImportError:
        run_combinatorial_promotion_battery = None

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/jj_live.log"),
    ],
)
logger = logging.getLogger("JJ")

# ---------------------------------------------------------------------------
# JJ Configuration
# ---------------------------------------------------------------------------
MAX_POSITION_USD = float(os.environ.get("JJ_MAX_POSITION_USD", "2.00"))
MAX_DAILY_LOSS_USD = float(os.environ.get("JJ_MAX_DAILY_LOSS_USD", "10"))
MAX_EXPOSURE_PCT = float(os.environ.get("JJ_MAX_EXPOSURE_PCT", "0.90"))
KELLY_FRACTION = float(os.environ.get("JJ_KELLY_FRACTION", "0.25"))
MAX_KELLY_FRACTION = float(os.environ.get("JJ_MAX_KELLY_FRACTION", "0.25"))
SCAN_INTERVAL = int(os.environ.get("JJ_SCAN_INTERVAL", "180"))
MAX_OPEN_POSITIONS = int(os.environ.get("JJ_MAX_OPEN_POSITIONS", "30"))
MIN_EDGE = float(os.environ.get("JJ_MIN_EDGE", "0.05"))
INITIAL_BANKROLL = float(os.environ.get("JJ_INITIAL_BANKROLL", "247.51"))

# Adaptive calibration and ensemble conviction controls (Instance 6)
ADAPTIVE_PLATT_ENABLED = os.environ.get("JJ_ADAPTIVE_PLATT_ENABLED", "false").lower() in ("true", "1", "yes")
ADAPTIVE_PLATT_MIN_SAMPLES = int(os.environ.get("JJ_ADAPTIVE_PLATT_MIN_SAMPLES", "50"))
ADAPTIVE_PLATT_WINDOW = int(os.environ.get("JJ_ADAPTIVE_PLATT_WINDOW", "100"))
ADAPTIVE_PLATT_REFIT_SECONDS = int(os.environ.get("JJ_ADAPTIVE_PLATT_REFIT_SECONDS", "300"))
ENSEMBLE_MIN_AGREEMENT = float(os.environ.get("JJ_ENSEMBLE_MIN_AGREEMENT", "0.25"))
DISAGREEMENT_LOW_STD = float(os.environ.get("JJ_DISAGREEMENT_LOW_STD", "0.05"))
DISAGREEMENT_HIGH_STD = float(os.environ.get("JJ_DISAGREEMENT_HIGH_STD", "0.15"))
DISAGREEMENT_MIN_KELLY = float(os.environ.get("JJ_DISAGREEMENT_MIN_KELLY", f"{1.0 / 32.0:.5f}"))
ENSEMBLE_SKIP_FRAGILE_CONVICTION = os.environ.get(
    "JJ_ENSEMBLE_SKIP_FRAGILE_CONVICTION",
    "true",
).lower() in ("true", "1", "yes")

# Velocity filter — maximum hours until resolution (default: 48 = 2 days)
# Slow-market edge: LLM ensemble + RAG on politics/weather/economics
# Set to 0 to disable (allow all markets regardless of resolution time)
MAX_RESOLUTION_HOURS = float(os.environ.get("JJ_MAX_RESOLUTION_HOURS", "48"))

# Paper trading mode — simulate trades without posting to CLOB
PAPER_TRADING = os.environ.get("PAPER_TRADING", "false").lower() in ("true", "1", "yes")

# Multi-bankroll simulation levels
BANKROLL_LEVELS = [1_000, 10_000, 100_000]

STATE_FILE = Path("jj_state.json")
DB_FILE = Path("data/jj_trades.db")

# ---------------------------------------------------------------------------
# Platt Scaling Calibration (ported from local claude_analyzer.py)
# Fitted on 70% of 532 resolved markets, validated on 30% test set
# Test-set Brier: 0.286 (raw) → 0.245 (Platt) — improvement of +0.041
# ---------------------------------------------------------------------------
PLATT_A = float(os.environ.get("PLATT_A", "0.5914"))
PLATT_B = float(os.environ.get("PLATT_B", "-0.3977"))


def calibrate_probability_with_params(raw_prob: float, a: float, b: float) -> float:
    """Apply Platt scaling. Maps: 90% → 71%, 80% → 60%, 70% → 53%."""
    raw_prob = max(0.001, min(0.999, raw_prob))
    if abs(raw_prob - 0.5) < 1e-9:
        return 0.5
    if raw_prob < 0.5:
        return 1.0 - calibrate_probability_with_params(1.0 - raw_prob, a, b)
    logit_input = math.log(raw_prob / (1 - raw_prob))
    logit_output = a * logit_input + b
    logit_output = max(-30, min(30, logit_output))
    calibrated = 1.0 / (1.0 + math.exp(-logit_output))
    return max(0.01, min(0.99, calibrated))


def calibrate_probability(raw_prob: float) -> float:
    """Apply static Platt scaling with configured global params."""
    return calibrate_probability_with_params(raw_prob, PLATT_A, PLATT_B)


def fit_platt_parameters(raw_probs: list[float], outcomes: list[int]) -> tuple[float, float]:
    """Fit Platt A/B on logit(raw_prob) via simple L2-regularized gradient descent."""
    if len(raw_probs) < 20 or len(raw_probs) != len(outcomes):
        return PLATT_A, PLATT_B

    x = np.array(
        [
            math.log(max(0.001, min(0.999, p)) / (1.0 - max(0.001, min(0.999, p))))
            for p in raw_probs
        ],
        dtype=float,
    )
    y = np.array([1.0 if int(v) == 1 else 0.0 for v in outcomes], dtype=float)

    a = float(PLATT_A)
    b = float(PLATT_B)
    lr = 0.08
    l2 = 1e-3
    prev_loss = float("inf")

    for _ in range(300):
        z = np.clip(a * x + b, -30.0, 30.0)
        p = 1.0 / (1.0 + np.exp(-z))
        eps = 1e-9
        loss = -np.mean(y * np.log(p + eps) + (1.0 - y) * np.log(1.0 - p + eps)) + l2 * (a * a + b * b)

        grad_a = float(np.mean((p - y) * x) + 2.0 * l2 * a)
        grad_b = float(np.mean(p - y) + 2.0 * l2 * b)

        cand_a = a - lr * grad_a
        cand_b = b - lr * grad_b

        cand_z = np.clip(cand_a * x + cand_b, -30.0, 30.0)
        cand_p = 1.0 / (1.0 + np.exp(-cand_z))
        cand_loss = -np.mean(y * np.log(cand_p + eps) + (1.0 - y) * np.log(1.0 - cand_p + eps)) + l2 * (
            cand_a * cand_a + cand_b * cand_b
        )

        if cand_loss <= loss:
            a, b = cand_a, cand_b
            if abs(prev_loss - float(cand_loss)) < 1e-7:
                break
            prev_loss = float(cand_loss)
        else:
            lr *= 0.5
            if lr < 1e-4:
                break

    return float(a), float(b)


# ---------------------------------------------------------------------------
# Category Classification (ported from local claude_analyzer.py)
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = {
    "politics": ["election", "president", "congress", "senate", "governor", "vote",
                 "democrat", "republican", "trump", "biden", "party", "primary",
                 "legislation", "bill", "law", "executive order", "cabinet",
                 "impeach", "poll", "ballot", "nominee", "campaign"],
    "weather": ["temperature", "rain", "snow", "weather", "hurricane", "storm",
                "heat", "cold", "wind", "flood", "drought", "celsius", "fahrenheit",
                "high of", "low of", "degrees"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
               "token", "defi", "nft", "blockchain", "altcoin", "dogecoin", "xrp",
               "up or down", "above", "below", "hit $", "reach $", "price",
               "market cap", "memecoin", "meme coin", "cardano", "ada",
               "polkadot", "litecoin",
               "cex", "dex", "binance", "coinbase", "kraken exchange",
               "insolvent"],
    "sports": ["nba", "nfl", "mlb", "nhl", "mls", "soccer", "football", "basketball",
               "baseball", "tennis", "golf", "championship", "playoff", "world cup",
               "super bowl", "mvp", "draft", "stanley cup", "series", "ufc",
               "boxing", "grand slam", "formula 1", "f1", "premier league",
               "champions league", "serie a", "la liga", "bundesliga", "ncaab",
               "ncaaf", "ligue 1", "eredivisie", "wnba", "atp", "wta",
               " vs ", " vs. ", "moneyline", "spread", "o/u ", "over/under",
               "rebounds", "assists", "points", "touchdowns", "goals",
               "win on 202", "win the 202", "qualify",
               # MMA/UFC/Fighting
               "fight", "fighter", "bout", "knockout", "mma", "bellator",
               "middleweight", "heavyweight", "lightweight", "featherweight",
               "welterweight", "bantamweight", "flyweight",
               # Soccer leagues and terms
               "epl", "top 4", "top four", "relegat", "promoted",
               "brentford", "wolves", "everton", "aston villa", "west ham",
               "brighton", "fulham", "bournemouth", "crystal palace",
               "nottingham forest", "leicester", "newcastle", "ipswich",
               "southampton",
               # NHL teams
               "bruins", "celtics", "penguins", "rangers", "blackhawks", "canadiens",
               "maple leafs", "red wings", "flyers", "capitals", "lightning",
               "avalanche", "oilers", "flames", "canucks", "kraken", "predators",
               "blue jackets", "hurricanes", "panthers", "devils", "islanders",
               "sabres", "senators", "jets", "wild", "coyotes", "sharks", "ducks",
               "golden knights", "blues", "stars",
               # NBA teams
               "lakers", "warriors", "celtics", "nets", "knicks", "bucks",
               "76ers", "sixers", "suns", "mavericks", "nuggets", "cavaliers",
               "timberwolves", "clippers", "grizzlies", "pelicans", "pacers",
               "hawks", "heat", "magic", "raptors", "spurs", "rockets", "pistons",
               "wizards", "hornets", "trail blazers", "blazers", "thunder",
               # Soccer
               "galatasaray", "fenerbahce", "besiktas", "real madrid", "barcelona",
               "manchester", "liverpool", "chelsea", "arsenal", "tottenham",
               "juventus", "ac milan", "inter milan", "bayern", "dortmund",
               "psg", "atletico", "benfica", "porto", "ajax",
               "charlotte fc", "smouha", "modern sport",
               # Tennis
               "bnp paribas", "roland garros", "wimbledon", "us open tennis",
               "australian open",
               # Other
               "super league", "copa america", "euro 202", "nations league"],
    "geopolitical": ["war", "invasion", "nato", "china", "russia", "taiwan",
                     "sanctions", "ceasefire", "nuclear", "military", "conflict"],
    "financial_speculation": ["dip to", "drop to", "fall to", "rise to",
                              "stock price", "share price", "ipo",
                              "close above", "close below",
                              "market close", "all-time high", "ath",
                              "52-week", "s&p 500", "nasdaq", "dow jones"],
    "fed_rates": ["fed", "federal reserve", "interest rate", "fomc",
                  "recession", "treasury"],
    "economic": ["inflation", "cpi", "gdp", "unemployment rate", "jobs report",
                 "nonfarm", "payroll", "retail sales", "housing starts",
                 "consumer confidence", "pmi", "manufacturing", "trade deficit",
                 "economic growth", "bls", "bureau of labor"],
}

# Category priority: higher = better expected LLM edge
CATEGORY_PRIORITY = {
    "politics": 3,      # Best LLM category (Lu 2025)
    "weather": 3,       # Structural arbitrage (NOAA/GFS data)
    "economic": 2,      # Scheduled releases, consensus alignment
    "crypto": 0,        # No LLM edge — skip
    "sports": 0,        # No LLM edge — skip
    "financial_speculation": 0,  # No LLM edge on precise price movements
    "geopolitical": 1,  # ~30% worse than experts (RAND)
    "fed_rates": 0,     # Worst category — systematic overconfidence
    "unknown": 2,       # Default — still analyze
}

# Polymarket taker fee rates (introduced Feb 18, 2026)
# NOTE: With universal post-only (Dispatch #75), these are only used for
# logging/comparison. Maker orders pay 0% fee and earn rebates.
TAKER_FEE_RATES = {
    "crypto": 0.025,    # ~1.56% max at p=0.50 (polynomial: rate=0.25, exp=2)
    "sports": 0.007,    # ~0.44% max at p=0.50 (linear: rate=0.0175, exp=1)
    "default": 0.0,     # Other categories: no taker fee
}

# Maker rebate rates by category (Dispatch #75)
MAKER_REBATE_RATES = {
    "crypto": 0.20,     # 20% of taker fee pool
    "sports": 0.25,     # 25% of taker fee pool — BEST for maker strategies
    "default": 0.0,     # No fee = no rebate pool
}

# Asymmetric thresholds (from 532-market backtest)
YES_THRESHOLD = 0.15    # Higher bar — 56% historical win rate on YES
NO_THRESHOLD = 0.05     # Lower bar — 76% historical win rate on NO

# Minimum category priority to analyze (0=skip, 1=cautious, 2+=analyze)
MIN_CATEGORY_PRIORITY = 1


import re


# ---------------------------------------------------------------------------
# Resolution Time Estimation (ported from VPS scanner_velocity_v2)
# ---------------------------------------------------------------------------
def estimate_resolution_hours(market: dict) -> float | None:
    """Estimate hours until market resolves.

    Uses endDate from API if available, otherwise keyword matching.
    Returns None if cannot estimate.
    Returns None for past endDates (market already expired / awaiting resolution).
    """
    end_date_str = market.get("endDate") or market.get("end_date_iso")
    if end_date_str:
        try:
            for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"]:
                try:
                    end_dt = datetime.strptime(end_date_str, fmt).replace(tzinfo=timezone.utc)
                    hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                    if hours <= 0:
                        # Past endDate — awaiting resolution, treat as unknown
                        return None
                    return hours
                except ValueError:
                    continue
        except Exception:
            pass

    # Keyword-based estimation from question text
    question = (market.get("question") or "").lower()

    # Crypto 5m/15m/1h time-windowed markets
    if re.search(r'up or down.*\d{1,2}:\d{2}', question):
        return 0.25  # 15 minutes
    if "5m" in question or "5-minute" in question or "5 minute" in question:
        return 0.083  # 5 minutes
    if "15m" in question or "15-minute" in question or "15 minute" in question:
        return 0.25

    # Time-based keywords
    if any(kw in question for kw in ["today", "tonight"]):
        return 12.0
    if "tomorrow" in question:
        return 36.0
    if any(kw in question for kw in ["this week", "this weekend"]):
        return 120.0

    # Date patterns like "March 7", "March 8", etc.
    now = datetime.now(timezone.utc)
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    for month_name, month_num in month_names.items():
        date_match = re.search(rf'{month_name}\s+(\d{{1,2}})', question)
        if date_match:
            day = int(date_match.group(1))
            try:
                year = now.year
                target = datetime(year, month_num, day, 23, 59, tzinfo=timezone.utc)
                hours = (target - now).total_seconds() / 3600
                if 0 < hours < 8760:  # Within a year
                    return hours
            except ValueError:
                pass

    # ISO date patterns like "2026-03-08"
    iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', question)
    if iso_match:
        try:
            target = datetime(
                int(iso_match.group(1)), int(iso_match.group(2)),
                int(iso_match.group(3)), 23, 59, tzinfo=timezone.utc,
            )
            hours = (target - now).total_seconds() / 3600
            if 0 < hours < 8760:
                return hours
        except ValueError:
            pass

    # "by [Month] [Year]" patterns → long-dated, use end of month
    by_match = re.search(r'by\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})', question)
    if by_match:
        month_num = month_names.get(by_match.group(1))
        year = int(by_match.group(2))
        if month_num:
            try:
                if month_num == 12:
                    target = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                else:
                    target = datetime(year, month_num + 1, 1, tzinfo=timezone.utc)
                hours = (target - now).total_seconds() / 3600
                if hours > 0:
                    return hours
            except ValueError:
                pass

    # "by [Month] [Day]" or "by [Month] [Day], [Year]"
    by_day_match = re.search(r'by\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})', question)
    if by_day_match:
        month_num = month_names.get(by_day_match.group(1))
        day = int(by_day_match.group(2))
        if month_num:
            try:
                target = datetime(now.year, month_num, day, 23, 59, tzinfo=timezone.utc)
                hours = (target - now).total_seconds() / 3600
                if hours > 0:
                    return hours
            except ValueError:
                pass

    return None


def velocity_score(edge: float, resolution_hours: float) -> float:
    """Capital velocity: annualized edge per unit of lockup time.

    Higher = better. A 5% edge on a 1-hour market beats a 20% edge
    on a 1-month market for capital efficiency.
    """
    if resolution_hours <= 0:
        resolution_hours = 1.0
    resolution_days = resolution_hours / 24.0
    return abs(edge) / max(resolution_days, 0.01) * 365


# Regex patterns for categories that keyword matching misses
SPORTS_REGEX_PATTERNS = [
    re.compile(r'\bvs\.?\b.*\b(FC|SC|SK|CF|AC|CD|RC)\b', re.IGNORECASE),
    re.compile(r'\b(FC|SC|SK|CF|AC|CD|RC)\b.*\bvs\.?\b', re.IGNORECASE),
    re.compile(r'(Spread|O/U|Over/Under|Moneyline)\s*[:\(]', re.IGNORECASE),  # Spread: or Spread(
    re.compile(r'(Rebounds|Assists|Points|Touchdowns|Goals|Strikeouts)\s+O/U', re.IGNORECASE),
    re.compile(r'\b\d+:\d+\s*[AP]M\s*(ET|PT|CT|EST|PST|CST)', re.IGNORECASE),  # Time-windowed sports
    re.compile(r'\bSet\s+(Handicap|Winner|\d)', re.IGNORECASE),  # Tennis set handicap/winner
    re.compile(r'\bGames?\s+Total\b', re.IGNORECASE),  # Games total O/U
    re.compile(r'\bBO\d\b', re.IGNORECASE),  # Best of N (esports)
    re.compile(r'\bFirst\s+Round\s+Pool\b', re.IGNORECASE),  # Tournament pools
    re.compile(r'\b(Bulldogs|Panthers|Wolfpack|Eagles|Tigers|Bears|Cardinals|Hawks|Wildcats|Blue\s+Hens|Camels|Fighting)\b.*\bvs\.?\b', re.IGNORECASE),  # College sports mascots
    re.compile(r'\bvs\.?\b.*\b(Bulldogs|Panthers|Wolfpack|Eagles|Tigers|Bears|Cardinals|Hawks|Wildcats|Blue\s+Hens|Camels|Fighting)\b', re.IGNORECASE),
    re.compile(r'\b(Flyers|Penguins|Blues|Ducks|Mavericks|Bucks|Giants|Diamondbacks)\s+vs\.?\b', re.IGNORECASE),  # NHL/NBA/MLB team names
    re.compile(r'\bvs\.?\s+(Flyers|Penguins|Blues|Ducks|Mavericks|Bucks|Giants|Diamondbacks)\b', re.IGNORECASE),
    re.compile(r'\b(Stanley Cup|Super Bowl|World Series|Champions League|Premier League|EPL|La Liga|Serie A|Bundesliga|Ligue 1)\b', re.IGNORECASE),  # Major leagues
    re.compile(r'\b(T20|World Cup|Grand Prix|F1|Formula 1|NASCAR|MLS|WNBA|ATP|WTA)\b', re.IGNORECASE),  # More leagues
    re.compile(r'\btop\s+goal\s+scorer\b', re.IGNORECASE),  # Sports scoring
    re.compile(r'\b(Norris|Hart|MVP|Cy Young|Ballon d.Or)\s+(Trophy|Memorial|Award)\b', re.IGNORECASE),  # Sports awards
]

CRYPTO_REGEX_PATTERNS = [
    re.compile(r'(Bitcoin|Ethereum|Solana|XRP|BTC|ETH|SOL)\s+(Up|Down)', re.IGNORECASE),
    re.compile(r'\d+:\d+\s*[AP]M.*ET.*\b(Up|Down)\b', re.IGNORECASE),  # Time-windowed crypto
    re.compile(r'price of (Bitcoin|Ethereum|Solana|XRP|BTC|ETH|SOL)', re.IGNORECASE),  # Crypto price brackets
    re.compile(r'\b(Chainlink|Ethena|MetaMask|CEX)\b.*\b(dip|token|insolvent)\b', re.IGNORECASE),  # Crypto projects
]

FINANCIAL_SPEC_REGEX_PATTERNS = [
    re.compile(r'(dip|drop|fall|rise|rally|crash)\s+to\s+\$\d+', re.IGNORECASE),
    re.compile(r'\$(AAPL|GOOG|GOOGL|AMZN|MSFT|META|TSLA|NVDA|AMD|NFLX)\b', re.IGNORECASE),
    re.compile(r'\b(Apple|Google|Amazon|Microsoft|Tesla|Nvidia|Netflix|Meta)\s+(dip|drop|fall|rise|stock)', re.IGNORECASE),
]


def _keyword_match(keyword: str, text: str) -> bool:
    """Match keyword in text, using word boundaries for short keywords (<=4 chars)
    to avoid false positives like 'nfl' matching 'inflation'."""
    if len(keyword) <= 4:
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))
    return keyword in text


def classify_market_category(question: str) -> str:
    """Classify a market question into a category based on keywords and regex."""
    question_lower = question.lower()
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for kw in keywords if _keyword_match(kw, question_lower))

    # Regex-based boost for sports/crypto/financial patterns
    for pattern in SPORTS_REGEX_PATTERNS:
        if pattern.search(question):
            scores["sports"] = scores.get("sports", 0) + 3
    for pattern in CRYPTO_REGEX_PATTERNS:
        if pattern.search(question):
            scores["crypto"] = scores.get("crypto", 0) + 3
    for pattern in FINANCIAL_SPEC_REGEX_PATTERNS:
        if pattern.search(question):
            scores["financial_speculation"] = scores.get("financial_speculation", 0) + 3

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def calculate_taker_fee(price: float, category: str) -> float:
    """Calculate Polymarket taker fee. Fee formula: p * (1-p) * rate."""
    rate = TAKER_FEE_RATES.get(category, TAKER_FEE_RATES["default"])
    return price * (1 - price) * rate


def is_low_edge_category(question: str) -> bool:
    """Return True if question is in a category where LLMs have low edge."""
    category = classify_market_category(question)
    priority = CATEGORY_PRIORITY.get(category, 2)
    return priority < MIN_CATEGORY_PRIORITY


def _safe_float(value, default: float = 0.5) -> float:
    """Parse a float from mixed analyzer payloads."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_confidence(value) -> float:
    """Normalize confidence into [0, 1] float."""
    if isinstance(value, str):
        conf_map = {"high": 0.85, "medium": 0.6, "med": 0.6, "low": 0.3}
        return conf_map.get(value.lower().strip(), 0.5)
    return max(0.0, min(1.0, _safe_float(value, 0.5)))


def map_vps_signal_direction(result: dict, market_price: float) -> str:
    """Map VPS analyzer output into internal buy_yes/buy_no/hold."""
    direction = str(result.get("direction", "") or "").strip().lower()
    if direction in ("buy_yes", "buy_no", "hold"):
        return direction

    signal = str(result.get("signal", result.get("action", "hold")) or "").strip().upper()
    if signal in ("NO", "BUY_NO", "SELL", "SHORT"):
        return "buy_no"
    if signal in ("BUY", "YES", "BUY_YES"):
        est_prob = _safe_float(
            result.get("estimated_prob", result.get("probability", 0.5)),
            0.5,
        )
        return "buy_yes" if est_prob >= market_price else "buy_no"
    return "hold"


def extract_probability_fields(result: dict) -> dict:
    """Normalize raw/calibrated probability fields from mixed analyzer payloads."""
    raw_prob = None
    for key in (
        "raw_prob",
        "raw_probability",
        "probability",
        "estimated_probability",
        "estimated_prob",
        "prob",
        "estimate",
    ):
        if result.get(key) is not None:
            raw_prob = _safe_float(result.get(key), None)
            break

    calibrated_prob = None
    for key in ("calibrated_probability", "calibrated_prob"):
        if result.get(key) is not None:
            calibrated_prob = _safe_float(result.get(key), None)
            break

    if raw_prob is not None and not (0.0 <= raw_prob <= 1.0):
        raw_prob = None
    if calibrated_prob is not None and not (0.0 <= calibrated_prob <= 1.0):
        calibrated_prob = None

    already_calibrated = raw_prob is None and calibrated_prob is not None
    execution_prob = (
        calibrated_prob
        if calibrated_prob is not None
        else raw_prob
    )

    return {
        "raw_prob": raw_prob,
        "calibrated_prob": calibrated_prob,
        "execution_prob": execution_prob,
        "already_calibrated": already_calibrated,
    }


def compute_calibrated_signal(
    raw_prob: float,
    market_price: float,
    category: str,
    *,
    already_calibrated: bool = False,
    calibrate_fn=calibrate_probability,
) -> dict:
    """Full signal computation: calibrate → fee → threshold → direction.

    This is the core improvement over the VPS analyzer: applies Platt scaling,
    taker fee subtraction, and asymmetric thresholds.
    """
    # 1. Calibrate (or pass-through when upstream already calibrated)
    calibrated = raw_prob if already_calibrated else calibrate_fn(raw_prob)
    calibrated = max(0.01, min(0.99, calibrated))

    # 2. Raw edge
    raw_edge = calibrated - market_price

    # 3. Fee calculation
    # DISPATCH #75: All orders are now post-only (maker). Maker fee = 0%.
    # We still calculate the hypothetical taker fee for logging/comparison,
    # but net_edge is no longer reduced by it. Maker rebate (20%, 25% sports)
    # is a bonus not yet modeled — conservative.
    buy_price = market_price if raw_edge > 0 else (1 - market_price)
    taker_fee = calculate_taker_fee(buy_price, category)  # for logging only

    # 4. Net edge (maker orders pay zero fees)
    net_edge = abs(raw_edge)

    # 5. Asymmetric thresholds
    if raw_edge > 0 and net_edge >= YES_THRESHOLD:
        return {
            "mispriced": True, "direction": "buy_yes", "edge": net_edge,
            "raw_edge": raw_edge, "calibrated_prob": calibrated,
            "taker_fee": taker_fee, "category": category,
        }
    elif raw_edge < 0 and net_edge >= NO_THRESHOLD:
        return {
            "mispriced": True, "direction": "buy_no", "edge": net_edge,
            "raw_edge": raw_edge, "calibrated_prob": calibrated,
            "taker_fee": taker_fee, "category": category,
        }
    else:
        return {
            "mispriced": False, "direction": "hold", "edge": 0.0,
            "raw_edge": raw_edge, "calibrated_prob": calibrated,
            "taker_fee": taker_fee, "category": category,
        }


def build_trade_record(
    signal: dict,
    *,
    market_id: str,
    category: str,
    entry_price: float,
    position_size_usd: float,
    token_id: str,
    order_id: str = "",
) -> dict:
    """Build a normalized trade record with Stream 6 telemetry preserved."""
    raw_prob = _safe_float(signal.get("raw_prob"), None)
    calibrated_prob = _safe_float(signal.get("calibrated_prob"), None)
    execution_prob = _safe_float(signal.get("estimated_prob"), None)

    if raw_prob is None:
        raw_prob = execution_prob
    if calibrated_prob is None:
        calibrated_prob = execution_prob if execution_prob is not None else raw_prob

    def _as_bool(value) -> bool:
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1")
        return bool(value)

    return {
        "market_id": market_id,
        "question": signal.get("question", ""),
        "direction": signal.get("direction", ""),
        "entry_price": entry_price,
        "raw_prob": raw_prob,
        "calibrated_prob": calibrated_prob,
        "edge": signal.get("edge", 0.0),
        "taker_fee": signal.get("taker_fee", 0.0),
        "position_size_usd": position_size_usd,
        "kelly_fraction": signal.get("_kelly_override", KELLY_FRACTION),
        "category": category,
        "confidence": signal.get("confidence", 0.5),
        "reasoning": signal.get("reasoning", ""),
        "token_id": token_id,
        "order_id": order_id,
        "source": signal.get("source", "llm"),
        "n_models": int(_safe_float(signal.get("n_models", 0), 0)),
        "model_spread": _safe_float(signal.get("model_spread"), None),
        "model_stddev": _safe_float(signal.get("model_stddev"), None),
        "agreement": _safe_float(signal.get("agreement"), None),
        "kelly_multiplier": _safe_float(signal.get("kelly_multiplier"), None),
        "disagreement_kelly_fraction": _safe_float(
            signal.get("disagreement_kelly_fraction"),
            None,
        ),
        "models_agree": _as_bool(signal.get("models_agree", False)),
        "search_context_used": _as_bool(signal.get("search_context_used", False)),
        "counter_shift": _safe_float(signal.get("counter_shift"), None),
        "counter_fragile": _as_bool(signal.get("counter_fragile", False)),
        "platt_mode": signal.get("platt_mode"),
        "platt_a": _safe_float(signal.get("platt_a"), None),
        "platt_b": _safe_float(signal.get("platt_b"), None),
    }


class _DummyNotifier:
    """Fallback when Telegram is not available."""
    is_configured = False
    async def send_message(self, *a, **kw): return False
    async def send_trade_signal(self, *a, **kw): return False
    async def send_error(self, *a, **kw): return False
    async def send_startup(self, *a, **kw): return False
    async def close(self): pass


# ---------------------------------------------------------------------------
# SQLite Data Pipeline
# ---------------------------------------------------------------------------
class TradeDatabase:
    """SQLite database for trade logging, multi-bankroll tracking, and resolution."""

    def __init__(self, db_path: Path = DB_FILE):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        c = self.conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                market_id TEXT NOT NULL,
                question TEXT,
                direction TEXT,
                entry_price REAL,
                raw_prob REAL,
                calibrated_prob REAL,
                edge REAL,
                taker_fee REAL,
                position_size_usd REAL,
                kelly_fraction REAL,
                category TEXT,
                confidence REAL,
                reasoning TEXT,
                token_id TEXT,
                order_id TEXT,
                paper INTEGER DEFAULT 1,
                outcome TEXT,          -- 'won', 'lost', NULL (unresolved)
                resolution_price REAL, -- 1.0 (YES) or 0.0 (NO)
                pnl REAL,
                resolved_at TEXT,
                bankroll_level INTEGER DEFAULT 1000,
                source TEXT,
                n_models INTEGER,
                model_spread REAL,
                model_stddev REAL,
                agreement REAL,
                kelly_multiplier REAL,
                disagreement_kelly_fraction REAL,
                models_agree INTEGER DEFAULT 0,
                search_context_used INTEGER DEFAULT 0,
                counter_shift REAL,
                counter_fragile INTEGER DEFAULT 0,
                platt_mode TEXT,
                platt_a REAL,
                platt_b REAL
            );

            CREATE TABLE IF NOT EXISTS cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cycle_number INTEGER,
                markets_scanned INTEGER,
                markets_filtered INTEGER,
                markets_analyzed INTEGER,
                signals_found INTEGER,
                trades_placed INTEGER,
                elapsed_seconds REAL,
                bankroll REAL,
                daily_pnl REAL,
                open_positions INTEGER,
                paper INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS multi_bankroll (
                id TEXT PRIMARY KEY,
                trade_id TEXT REFERENCES trades(id),
                bankroll_level INTEGER,
                position_size_usd REAL,
                kelly_fraction REAL,
                running_bankroll REAL,
                running_pnl REAL,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                trades_placed INTEGER DEFAULT 0,
                trades_resolved INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                daily_pnl REAL DEFAULT 0.0,
                cumulative_pnl REAL DEFAULT 0.0,
                brier_score REAL,
                best_trade_id TEXT,
                worst_trade_id TEXT,
                best_trade_pnl REAL,
                worst_trade_pnl REAL,
                report_sent INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS combinatorial_baskets (
                basket_id TEXT PRIMARY KEY,
                violation_id TEXT NOT NULL,
                lane TEXT NOT NULL,
                source_id INTEGER DEFAULT 0,
                source_tag TEXT,
                relation_type TEXT,
                confirmation_mode TEXT,
                execution_mode TEXT NOT NULL,
                state TEXT NOT NULL,
                state_reason TEXT,
                event_id TEXT,
                market_ids_json TEXT NOT NULL,
                theoretical_edge REAL,
                realized_edge REAL,
                capture_rate REAL,
                partial_fill_loss REAL,
                classification_accuracy REAL,
                resolution_gate_status TEXT,
                budget_usd REAL DEFAULT 0.0,
                kill_rule_trigger TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS combinatorial_cycle_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cycle_number INTEGER,
                a6_detected INTEGER DEFAULT 0,
                b1_detected INTEGER DEFAULT 0,
                shadow_logged INTEGER DEFAULT 0,
                live_attempted INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                active_baskets INTEGER DEFAULT 0,
                arb_budget_in_use_usd REAL DEFAULT 0.0,
                kill_triggers_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
            CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome);
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
            CREATE INDEX IF NOT EXISTS idx_multi_bankroll_level ON multi_bankroll(bankroll_level);
            CREATE INDEX IF NOT EXISTS idx_comb_baskets_lane_state ON combinatorial_baskets(lane, state);
            CREATE INDEX IF NOT EXISTS idx_comb_baskets_updated ON combinatorial_baskets(updated_at);
            CREATE INDEX IF NOT EXISTS idx_comb_cycle_ts ON combinatorial_cycle_metrics(timestamp);
        """)
        self._ensure_columns(
            "trades",
            {
                "source": "TEXT",
                "n_models": "INTEGER",
                "model_spread": "REAL",
                "model_stddev": "REAL",
                "agreement": "REAL",
                "kelly_multiplier": "REAL",
                "disagreement_kelly_fraction": "REAL",
                "models_agree": "INTEGER DEFAULT 0",
                "search_context_used": "INTEGER DEFAULT 0",
                "counter_shift": "REAL",
                "counter_fragile": "INTEGER DEFAULT 0",
                "platt_mode": "TEXT",
                "platt_a": "REAL",
                "platt_b": "REAL",
            },
        )
        self.conn.commit()

    def _ensure_columns(self, table_name: str, columns: dict[str, str]) -> None:
        """Backfill additive columns for existing SQLite databases."""
        c = self.conn.cursor()
        existing = {
            row[1]
            for row in c.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, ddl in columns.items():
            if column_name in existing:
                continue
            c.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")

    def log_trade(self, trade: dict, bankroll_level: int = 1000) -> str:
        """Log a trade to the database. Returns trade_id."""
        trade_id = str(uuid.uuid4())[:12]
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO trades (id, timestamp, market_id, question, direction,
                entry_price, raw_prob, calibrated_prob, edge, taker_fee,
                position_size_usd, kelly_fraction, category, confidence,
                reasoning, token_id, order_id, paper, bankroll_level, source,
                n_models, model_spread, model_stddev, agreement,
                kelly_multiplier, disagreement_kelly_fraction, models_agree,
                search_context_used, counter_shift, counter_fragile, platt_mode,
                platt_a, platt_b)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_id,
            datetime.now(timezone.utc).isoformat(),
            trade.get("market_id", ""),
            trade.get("question", ""),
            trade.get("direction", ""),
            trade.get("entry_price", 0.0),
            trade.get("raw_prob"),
            trade.get("calibrated_prob"),
            trade.get("edge", 0.0),
            trade.get("taker_fee", 0.0),
            trade.get("position_size_usd", 0.0),
            trade.get("kelly_fraction", KELLY_FRACTION),
            trade.get("category", "unknown"),
            trade.get("confidence", 0.5),
            trade.get("reasoning", ""),
            trade.get("token_id", ""),
            trade.get("order_id", ""),
            1 if PAPER_TRADING else 0,
            bankroll_level,
            trade.get("source", "llm"),
            trade.get("n_models"),
            trade.get("model_spread"),
            trade.get("model_stddev"),
            trade.get("agreement"),
            trade.get("kelly_multiplier"),
            trade.get("disagreement_kelly_fraction"),
            1 if trade.get("models_agree") else 0,
            1 if trade.get("search_context_used") else 0,
            trade.get("counter_shift"),
            1 if trade.get("counter_fragile") else 0,
            trade.get("platt_mode"),
            trade.get("platt_a"),
            trade.get("platt_b"),
        ))
        self.conn.commit()
        return trade_id

    def log_multi_bankroll(self, trade_id: str, bankroll_level: int,
                            position_size: float, running_bankroll: float,
                            running_pnl: float):
        """Log a multi-bankroll simulation entry."""
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO multi_bankroll (id, trade_id, bankroll_level,
                position_size_usd, kelly_fraction, running_bankroll,
                running_pnl, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4())[:12],
            trade_id,
            bankroll_level,
            position_size,
            KELLY_FRACTION,
            running_bankroll,
            running_pnl,
            datetime.now(timezone.utc).isoformat(),
        ))
        self.conn.commit()

    def log_cycle(self, cycle_data: dict):
        """Log a cycle summary."""
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO cycles (timestamp, cycle_number, markets_scanned,
                markets_filtered, markets_analyzed, signals_found,
                trades_placed, elapsed_seconds, bankroll, daily_pnl,
                open_positions, paper)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            cycle_data.get("cycle", 0),
            cycle_data.get("scanned", 0),
            cycle_data.get("filtered", 0),
            cycle_data.get("analyzed", 0),
            cycle_data.get("signals", 0),
            cycle_data.get("trades_placed", 0),
            cycle_data.get("elapsed_seconds", 0.0),
            cycle_data.get("bankroll", INITIAL_BANKROLL),
            cycle_data.get("daily_pnl", 0.0),
            cycle_data.get("open_positions", 0),
            1 if PAPER_TRADING else 0,
        ))
        self.conn.commit()

    def upsert_combinatorial_basket(self, basket: dict) -> None:
        """Persist the latest lifecycle snapshot for an A-6 or B-1 basket."""
        now = datetime.now(timezone.utc).isoformat()
        state = str(basket.get("state", "DETECTED"))
        closed_at = basket.get("closed_at")
        if state in {
            "BLOCKED",
            "COMPLETE",
            "CLOSED",
            "EXECUTOR_PENDING",
            "EXPIRED",
            "ROLLED_BACK",
            "SHADOW_LOGGED",
        } and not closed_at:
            closed_at = now

        market_ids = basket.get("market_ids") or []
        metadata = basket.get("metadata") or {}
        c = self.conn.cursor()
        c.execute(
            """
            INSERT INTO combinatorial_baskets (
                basket_id,
                violation_id,
                lane,
                source_id,
                source_tag,
                relation_type,
                confirmation_mode,
                execution_mode,
                state,
                state_reason,
                event_id,
                market_ids_json,
                theoretical_edge,
                realized_edge,
                capture_rate,
                partial_fill_loss,
                classification_accuracy,
                resolution_gate_status,
                budget_usd,
                kill_rule_trigger,
                metadata_json,
                created_at,
                updated_at,
                closed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(basket_id) DO UPDATE SET
                violation_id=excluded.violation_id,
                lane=excluded.lane,
                source_id=excluded.source_id,
                source_tag=excluded.source_tag,
                relation_type=excluded.relation_type,
                confirmation_mode=excluded.confirmation_mode,
                execution_mode=excluded.execution_mode,
                state=excluded.state,
                state_reason=excluded.state_reason,
                event_id=excluded.event_id,
                market_ids_json=excluded.market_ids_json,
                theoretical_edge=excluded.theoretical_edge,
                realized_edge=excluded.realized_edge,
                capture_rate=excluded.capture_rate,
                partial_fill_loss=excluded.partial_fill_loss,
                classification_accuracy=excluded.classification_accuracy,
                resolution_gate_status=excluded.resolution_gate_status,
                budget_usd=excluded.budget_usd,
                kill_rule_trigger=excluded.kill_rule_trigger,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at,
                closed_at=excluded.closed_at
            """,
            (
                basket.get("basket_id"),
                basket.get("violation_id", basket.get("basket_id")),
                basket.get("lane", "unknown"),
                basket.get("source_id", 0),
                basket.get("source_tag", ""),
                basket.get("relation_type", ""),
                basket.get("confirmation_mode", "bypass"),
                basket.get("execution_mode", "shadow"),
                state,
                basket.get("state_reason", ""),
                basket.get("event_id", ""),
                json.dumps(list(market_ids), sort_keys=True),
                basket.get("theoretical_edge"),
                basket.get("realized_edge"),
                basket.get("capture_rate"),
                basket.get("partial_fill_loss"),
                basket.get("classification_accuracy"),
                basket.get("resolution_gate_status", ""),
                basket.get("budget_usd", 0.0),
                basket.get("kill_rule_trigger"),
                json.dumps(metadata, sort_keys=True),
                basket.get("created_at", now),
                now,
                closed_at,
            ),
        )
        self.conn.commit()

    def log_combinatorial_cycle(self, cycle_data: dict) -> None:
        """Persist per-cycle A-6/B-1 integration metrics."""
        c = self.conn.cursor()
        c.execute(
            """
            INSERT INTO combinatorial_cycle_metrics (
                timestamp,
                cycle_number,
                a6_detected,
                b1_detected,
                shadow_logged,
                live_attempted,
                blocked,
                active_baskets,
                arb_budget_in_use_usd,
                kill_triggers_json,
                metrics_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                cycle_data.get("cycle_number"),
                cycle_data.get("a6_detected", 0),
                cycle_data.get("b1_detected", 0),
                cycle_data.get("shadow_logged", 0),
                cycle_data.get("live_attempted", 0),
                cycle_data.get("blocked", 0),
                cycle_data.get("active_baskets", 0),
                cycle_data.get("arb_budget_in_use_usd", 0.0),
                json.dumps(cycle_data.get("kill_triggers", []), sort_keys=True),
                json.dumps(cycle_data.get("metrics", {}), sort_keys=True),
            ),
        )
        self.conn.commit()

    def get_combinatorial_summary(self, hours: int = 24) -> dict:
        """Aggregate recent A-6/B-1 telemetry for reporting and promotion gates."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
        rows = self.conn.execute(
            """
            SELECT *
            FROM combinatorial_baskets
            WHERE updated_at >= ?
            ORDER BY updated_at ASC, basket_id ASC
            """,
            (cutoff,),
        ).fetchall()

        def _lane_default() -> dict:
            return {
                "detected": 0,
                "shadow_logged": 0,
                "live_attempted": 0,
                "blocked": 0,
                "active": 0,
                "avg_capture_rate": None,
                "avg_classification_accuracy": None,
                "false_positive_rate": None,
                "consecutive_rollbacks": 0,
                "kill_triggers": [],
            }

        summary = {
            "hours": hours,
            "lanes": {"a6": _lane_default(), "b1": _lane_default()},
            "active_baskets": 0,
            "arb_budget_in_use_usd": 0.0,
            "kill_triggers": [],
        }
        terminal_states = {
            "BLOCKED",
            "COMPLETE",
            "CLOSED",
            "EXECUTOR_PENDING",
            "EXPIRED",
            "ROLLED_BACK",
            "SHADOW_LOGGED",
        }
        capture_samples: dict[str, list[float]] = {"a6": [], "b1": []}
        accuracy_samples: dict[str, list[float]] = {"a6": [], "b1": []}
        false_positive_counts: dict[str, int] = {"a6": 0, "b1": 0}
        resolved_fp_counts: dict[str, int] = {"a6": 0, "b1": 0}
        rollback_streaks: dict[str, int] = {"a6": 0, "b1": 0}

        for row in rows:
            payload = dict(row)
            lane = str(payload.get("lane") or "unknown")
            if lane not in summary["lanes"]:
                summary["lanes"][lane] = _lane_default()
                capture_samples[lane] = []
                accuracy_samples[lane] = []
                false_positive_counts[lane] = 0
                resolved_fp_counts[lane] = 0
                rollback_streaks[lane] = 0

            lane_summary = summary["lanes"][lane]
            lane_summary["detected"] += 1
            if payload.get("execution_mode") == "shadow":
                lane_summary["shadow_logged"] += 1
            elif payload.get("execution_mode") == "live":
                lane_summary["live_attempted"] += 1
            elif payload.get("execution_mode") == "blocked":
                lane_summary["blocked"] += 1

            state = str(payload.get("state") or "")
            partial_fill_loss = payload.get("partial_fill_loss")
            if state not in terminal_states:
                lane_summary["active"] += 1
                summary["active_baskets"] += 1
                summary["arb_budget_in_use_usd"] += _safe_float(payload.get("budget_usd"), 0.0)
            if partial_fill_loss not in (None, "") and _safe_float(partial_fill_loss, 0.0) > 0:
                rollback_streaks[lane] += 1
            else:
                rollback_streaks[lane] = 0
            lane_summary["consecutive_rollbacks"] = max(
                int(lane_summary["consecutive_rollbacks"]),
                int(rollback_streaks[lane]),
            )

            capture_rate = payload.get("capture_rate")
            if capture_rate not in (None, ""):
                capture_samples[lane].append(_safe_float(capture_rate, 0.0))

            classification_accuracy = payload.get("classification_accuracy")
            if classification_accuracy not in (None, ""):
                accuracy_samples[lane].append(_safe_float(classification_accuracy, 0.0))

            kill_trigger = payload.get("kill_rule_trigger")
            if kill_trigger:
                lane_summary["kill_triggers"].append(str(kill_trigger))
                summary["kill_triggers"].append(str(kill_trigger))

            metadata = {}
            raw_metadata = payload.get("metadata_json")
            if raw_metadata:
                try:
                    metadata = json.loads(raw_metadata)
                except (TypeError, json.JSONDecodeError):
                    metadata = {}
            if "false_positive" in metadata:
                resolved_fp_counts[lane] += 1
                if metadata.get("false_positive"):
                    false_positive_counts[lane] += 1

        for lane, lane_summary in summary["lanes"].items():
            if capture_samples.get(lane):
                lane_summary["avg_capture_rate"] = sum(capture_samples[lane]) / len(capture_samples[lane])
            if accuracy_samples.get(lane):
                lane_summary["avg_classification_accuracy"] = (
                    sum(accuracy_samples[lane]) / len(accuracy_samples[lane])
                )
            total_fp = resolved_fp_counts.get(lane, 0)
            if total_fp:
                lane_summary["false_positive_rate"] = false_positive_counts.get(lane, 0) / total_fp
            lane_summary["kill_triggers"] = sorted(set(lane_summary["kill_triggers"]))

        summary["kill_triggers"] = sorted(set(summary["kill_triggers"]))
        summary["arb_budget_in_use_usd"] = round(summary["arb_budget_in_use_usd"], 2)
        return summary

    def get_unresolved_trades(self) -> list:
        """Get all trades that haven't been resolved yet."""
        c = self.conn.cursor()
        c.execute("SELECT * FROM trades WHERE outcome IS NULL ORDER BY timestamp")
        return [dict(row) for row in c.fetchall()]

    def resolve_trade(self, trade_id: str, won: bool, resolution_price: float):
        """Mark a trade as resolved."""
        c = self.conn.cursor()
        row = c.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if not row:
            return

        trade = dict(row)
        direction = trade["direction"]
        entry_price = trade["entry_price"]
        size_usd = trade["position_size_usd"]

        # Calculate P&L
        if won:
            # Winner fee is 2%
            payout = size_usd / entry_price * (1.0 - 0.02)
            pnl = payout - size_usd
        else:
            pnl = -size_usd

        outcome = "won" if won else "lost"
        c.execute("""
            UPDATE trades
            SET outcome = ?, resolution_price = ?, pnl = ?, resolved_at = ?
            WHERE id = ?
        """, (outcome, resolution_price, pnl,
              datetime.now(timezone.utc).isoformat(), trade_id))
        self.conn.commit()
        return pnl

    def get_stats(self) -> dict:
        """Get overall trading statistics."""
        c = self.conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        resolved = c.execute("SELECT COUNT(*) FROM trades WHERE outcome IS NOT NULL").fetchone()[0]
        wins = c.execute("SELECT COUNT(*) FROM trades WHERE outcome = 'won'").fetchone()[0]
        losses = c.execute("SELECT COUNT(*) FROM trades WHERE outcome = 'lost'").fetchone()[0]
        total_pnl = c.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE pnl IS NOT NULL").fetchone()[0]

        # Brier score: average (calibrated_prob - outcome)^2
        brier_rows = c.execute("""
            SELECT calibrated_prob, resolution_price
            FROM trades
            WHERE outcome IS NOT NULL AND calibrated_prob IS NOT NULL
        """).fetchall()
        brier = None
        if brier_rows:
            brier = sum((row[0] - row[1]) ** 2 for row in brier_rows) / len(brier_rows)

        return {
            "total_trades": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / resolved if resolved > 0 else 0,
            "total_pnl": total_pnl,
            "brier_score": brier,
        }

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Adaptive Rolling Platt Calibration (Instance 6 / D-12)
# ---------------------------------------------------------------------------
class AdaptivePlattCalibrator:
    """Select between static and rolling Platt params using recent Brier."""

    def __init__(
        self,
        db: TradeDatabase,
        *,
        enabled: bool = ADAPTIVE_PLATT_ENABLED,
        min_samples: int = ADAPTIVE_PLATT_MIN_SAMPLES,
        window: int = ADAPTIVE_PLATT_WINDOW,
        refit_seconds: int = ADAPTIVE_PLATT_REFIT_SECONDS,
    ):
        self.db = db
        self.enabled = enabled
        self.min_samples = max(20, int(min_samples))
        self.window = max(self.min_samples, int(window))
        self.refit_seconds = max(30, int(refit_seconds))

        self.active_a = float(PLATT_A)
        self.active_b = float(PLATT_B)
        self.active_mode = "static"
        self.last_refit_ts = 0.0
        self.sample_size = 0
        self.static_brier = None
        self.rolling_brier = None

    def _recent_resolved_rows(self) -> list[tuple[float, int]]:
        """Load only LLM-calibrated trades with trustworthy raw probabilities."""
        c = self.db.conn.cursor()
        rows = c.execute(
            """
            SELECT raw_prob, resolution_price
            FROM trades
            WHERE outcome IS NOT NULL
              AND raw_prob IS NOT NULL
              AND resolution_price IS NOT NULL
              AND platt_mode IS NOT NULL
            ORDER BY resolved_at DESC
            LIMIT ?
            """,
            (self.window,),
        ).fetchall()
        parsed: list[tuple[float, int]] = []
        for row in rows:
            raw_prob = _safe_float(row[0], None)
            resolved_price = _safe_float(row[1], None)
            if raw_prob is None or resolved_price is None:
                continue
            if not (0.0 <= raw_prob <= 1.0):
                continue
            outcome = 1 if resolved_price >= 0.5 else 0
            parsed.append((raw_prob, outcome))
        return parsed

    def _brier(self, rows: list[tuple[float, int]], a: float, b: float) -> float:
        if not rows:
            return float("inf")
        errs = [
            (calibrate_probability_with_params(raw, a, b) - float(outcome)) ** 2
            for raw, outcome in rows
        ]
        return float(sum(errs) / len(errs))

    def refresh(self, force: bool = False) -> None:
        """Refit rolling Platt and choose static vs rolling by recent Brier."""
        if not self.enabled:
            self.active_mode = "static"
            self.active_a = float(PLATT_A)
            self.active_b = float(PLATT_B)
            return

        now_ts = time.time()
        if not force and (now_ts - self.last_refit_ts) < self.refit_seconds:
            return

        rows = self._recent_resolved_rows()
        self.sample_size = len(rows)
        self.last_refit_ts = now_ts

        if len(rows) < self.min_samples:
            self.active_mode = "static"
            self.active_a = float(PLATT_A)
            self.active_b = float(PLATT_B)
            self.static_brier = self._brier(rows, PLATT_A, PLATT_B) if rows else None
            self.rolling_brier = None
            return

        raw_probs = [r[0] for r in rows]
        outcomes = [r[1] for r in rows]
        rolling_a, rolling_b = fit_platt_parameters(raw_probs, outcomes)

        static_brier = self._brier(rows, PLATT_A, PLATT_B)
        rolling_brier = self._brier(rows, rolling_a, rolling_b)
        self.static_brier = static_brier
        self.rolling_brier = rolling_brier

        if rolling_brier + 1e-6 < static_brier:
            self.active_mode = "rolling"
            self.active_a = rolling_a
            self.active_b = rolling_b
        else:
            self.active_mode = "static"
            self.active_a = float(PLATT_A)
            self.active_b = float(PLATT_B)

    def calibrate(self, raw_prob: float) -> float:
        return calibrate_probability_with_params(raw_prob, self.active_a, self.active_b)

    def summary(self) -> dict:
        return {
            "enabled": self.enabled,
            "mode": self.active_mode,
            "a": self.active_a,
            "b": self.active_b,
            "samples": self.sample_size,
            "static_brier": self.static_brier,
            "rolling_brier": self.rolling_brier,
        }


# ---------------------------------------------------------------------------
# Multi-Bankroll Simulator
# ---------------------------------------------------------------------------
class MultiBankrollSimulator:
    """Runs parallel paper portfolios at different bankroll levels."""

    def __init__(self, db: TradeDatabase, levels: list = None):
        self.db = db
        self.levels = levels or BANKROLL_LEVELS
        # Load running state from file
        self._state_file = Path("data/multi_bankroll_state.json")
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {str(level): {"bankroll": level, "pnl": 0.0, "trades": 0}
                for level in self.levels}

    def _save_state(self):
        with open(self._state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def simulate_trade(self, signal: dict, base_trade_id: str):
        """Simulate this trade at all bankroll levels."""
        for level in self.levels:
            key = str(level)
            if key not in self.state:
                self.state[key] = {"bankroll": level, "pnl": 0.0, "trades": 0}

            current_bankroll = self.state[key]["bankroll"]

            # Scale position by bankroll level
            size = kelly_size(
                edge=signal["edge"],
                market_price=signal["market_price"],
                direction=signal["direction"],
                bankroll=current_bankroll,
                kelly_fraction_override=signal.get("_kelly_override"),
            )
            # Scale max position proportionally
            max_pos = MAX_POSITION_USD * (level / 1000)
            size = min(size, max_pos)

            if size <= 0:
                continue

            self.state[key]["trades"] += 1

            self.db.log_multi_bankroll(
                trade_id=base_trade_id,
                bankroll_level=level,
                position_size=size,
                running_bankroll=current_bankroll,
                running_pnl=self.state[key]["pnl"],
            )

        self._save_state()

    def get_summary(self) -> dict:
        return {int(k): v for k, v in self.state.items()}

# ---------------------------------------------------------------------------
# Kelly Sizing
# ---------------------------------------------------------------------------
def kelly_size(
    edge: float,
    market_price: float,
    direction: str,
    bankroll: float,
    *,
    kelly_fraction_override: float | None = None,
) -> float:
    """Half-Kelly position sizing for binary prediction markets.

    Args:
        edge: Net edge after fees (e.g., 0.15 = 15%)
        market_price: Current YES price (0-1)
        direction: 'buy_yes' or 'buy_no'
        bankroll: Current total bankroll

    Returns:
        Position size in USD, clamped to limits.
    """
    if edge <= 0 or bankroll <= 0:
        return 0.0

    # Cost basis
    if direction == "buy_yes":
        cost = market_price
    else:  # buy_no
        cost = 1.0 - market_price

    if cost <= 0 or cost >= 1.0:
        return 0.0

    # Payout (after 2% winner fee)
    payout = 1.0 - 0.02
    odds = (payout - cost) / cost

    if odds <= 0:
        return 0.0

    # Kelly fraction
    p_win = cost + edge  # rough estimate
    p_win = max(0.01, min(0.99, p_win))

    kelly_f = (p_win * odds - (1.0 - p_win)) / odds
    kelly_f = max(0.0, kelly_f)

    # Apply configurable Kelly fraction
    kelly_fraction = (
        max(0.0, float(kelly_fraction_override))
        if kelly_fraction_override is not None
        else KELLY_FRACTION
    )
    raw_size = kelly_f * kelly_fraction * bankroll

    # Clamp
    final_size = min(raw_size, MAX_POSITION_USD)
    final_size = max(0.0, final_size)

    # Floor: minimum viable trade
    if final_size < 0.50:
        return 0.0

    return round(final_size, 2)


def apply_disagreement_size_modifier(
    size_usd: float,
    std_dev: float | None,
    *,
    modifier: float | None = None,
) -> tuple[float, float]:
    """Apply the Stream 6 disagreement multiplier to a Kelly-sized trade."""
    if size_usd <= 0:
        return 0.0, 1.0
    if std_dev is None:
        return round(size_usd, 2), 1.0

    resolved_modifier = (
        max(0.0, float(modifier))
        if modifier is not None
        else disagreement_kelly_modifier(std_dev)
    )
    final_size = round(size_usd * resolved_modifier, 2)
    if final_size < 0.50:
        return 0.0, resolved_modifier
    return final_size, resolved_modifier


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------
class JJState:
    """Persistent state for JJ trading system."""

    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self.state = self._load()

    @staticmethod
    def _default_state() -> dict:
        return {
            "bankroll": INITIAL_BANKROLL,
            "total_deployed": 0.0,
            "total_pnl": 0.0,
            "daily_pnl": 0.0,
            "daily_pnl_date": "",
            "trades_today": 0,
            "total_trades": 0,
            "winning_trades": 0,
            "open_positions": {},  # market_id -> position info
            "trade_log": [],      # last 100 trades
            "cycles_completed": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "veterans_allocation": 0.0,  # 20% of net profits
            "linked_legs": {},  # attempt_id -> multi-leg basket state
            "a6_state": {
                "attempts": {},
                "quarantined_tokens_path": "data/a6_quarantine_tokens.json",
                "last_watch_refresh_ts": None,
            },
            "b1_state": {
                "attempts": {},
                "validation_accuracy": None,
                "dep_graph_db_path": "data/dep_graph.sqlite",
            },
        }

    def _load(self) -> dict:
        default_state = self._default_state()
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    merged = dict(default_state)
                    merged.update(raw)
                    if isinstance(raw.get("a6_state"), dict):
                        merged["a6_state"] = {**default_state["a6_state"], **raw["a6_state"]}
                    if isinstance(raw.get("b1_state"), dict):
                        merged["b1_state"] = {**default_state["b1_state"], **raw["b1_state"]}
                    if not isinstance(merged.get("open_positions"), dict):
                        merged["open_positions"] = {}
                    if not isinstance(merged.get("trade_log"), list):
                        merged["trade_log"] = []
                    if not isinstance(merged.get("linked_legs"), dict):
                        merged["linked_legs"] = {}
                    return merged
            except Exception:
                pass
        return default_state

    def save(self):
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    def reset_daily(self):
        """Reset daily counters if new day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state["daily_pnl_date"] != today:
            self.state["daily_pnl"] = 0.0
            self.state["trades_today"] = 0
            self.state["daily_pnl_date"] = today

    def check_daily_loss_limit(self) -> bool:
        """Returns True if trading is allowed (not at daily loss limit)."""
        self.reset_daily()
        return self.state["daily_pnl"] > -MAX_DAILY_LOSS_USD

    def check_exposure_limit(self) -> bool:
        """Returns True if we can take more positions."""
        max_exposure = self.state["bankroll"] * MAX_EXPOSURE_PCT
        return self.state["total_deployed"] < max_exposure

    def has_position(self, market_id: str) -> bool:
        return market_id in self.state["open_positions"]

    def upsert_linked_legs(self, attempt_id: str, payload: dict) -> None:
        record = dict(payload)
        record.setdefault("attempt_id", str(attempt_id))
        record.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        state = str(record.get("state", "")).upper()
        record["active"] = state not in {
            "BLOCKED",
            "COMPLETE",
            "CLOSED",
            "EXECUTOR_PENDING",
            "EXPIRED",
            "ROLLED_BACK",
            "SHADOW_LOGGED",
        }
        self.state.setdefault("linked_legs", {})[str(attempt_id)] = record
        self.save()

    def clear_linked_legs(self, attempt_id: str) -> None:
        linked = self.state.setdefault("linked_legs", {})
        if str(attempt_id) in linked:
            linked.pop(str(attempt_id), None)
            self.save()

    def count_active_linked_baskets(self) -> int:
        return sum(
            1
            for payload in self.state.get("linked_legs", {}).values()
            if bool(payload.get("active"))
        )

    def get_arb_budget_in_use_usd(self) -> float:
        total = 0.0
        for payload in self.state.get("linked_legs", {}).values():
            if not bool(payload.get("active")):
                continue
            total += _safe_float(payload.get("reserved_budget_usd"), 0.0)
        return round(total, 2)

    def record_trade(self, market_id: str, question: str, direction: str,
                     price: float, size_usd: float, edge: float,
                     confidence: float, order_id: str = ""):
        """Record a new trade."""
        self.state["open_positions"][market_id] = {
            "question": question,
            "direction": direction,
            "entry_price": price,
            "size_usd": size_usd,
            "edge": edge,
            "confidence": confidence,
            "order_id": order_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.state["total_deployed"] += size_usd
        self.state["total_trades"] += 1
        self.state["trades_today"] += 1

        # Trade log (keep last 100)
        self.state["trade_log"].append({
            "market_id": market_id,
            "question": question[:80],
            "direction": direction,
            "price": price,
            "size_usd": size_usd,
            "edge": edge,
            "order_id": order_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.state["trade_log"] = self.state["trade_log"][-100:]

        self.save()

    def get_category_counts(self) -> dict:
        """Count open positions by rough category."""
        counts = {}
        for pos in self.state["open_positions"].values():
            q = pos.get("question", "").lower()
            if any(w in q for w in ["world cup", "nba", "nhl", "nfl", "sports"]):
                cat = "sports"
            elif any(w in q for w in ["trump", "president", "congress", "elect"]):
                cat = "politics"
            elif any(w in q for w in ["bitcoin", "eth", "crypto", "token"]):
                cat = "crypto"
            else:
                cat = "other"
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def sync_resolved_positions(self, db: 'TradeDatabase'):
        """Remove resolved trades from open_positions and update bankroll/P&L.

        Called at the start of each cycle to keep jj_state.json in sync with
        the SQLite DB (where resolution tracker marks trades as won/lost).
        Without this, resolved positions accumulate and hit MAX_OPEN_POSITIONS.
        """
        if not self.state["open_positions"]:
            return 0

        # Get all resolved trade market_ids from DB
        c = db.conn.cursor()
        resolved_rows = c.execute("""
            SELECT DISTINCT market_id, outcome, pnl, position_size_usd
            FROM trades
            WHERE outcome IS NOT NULL
        """).fetchall()

        if not resolved_rows:
            return 0

        resolved_market_ids = {row[0] for row in resolved_rows}

        # Find open positions that have been resolved
        to_remove = []
        for market_id in list(self.state["open_positions"].keys()):
            if market_id in resolved_market_ids:
                to_remove.append(market_id)

        if not to_remove:
            return 0

        # Get aggregate P&L for resolved markets
        for market_id in to_remove:
            pos = self.state["open_positions"].pop(market_id)

            # Look up actual P&L from DB
            pnl_row = c.execute("""
                SELECT COALESCE(SUM(pnl), 0), outcome
                FROM trades
                WHERE market_id = ? AND outcome IS NOT NULL
                GROUP BY market_id
            """, (market_id,)).fetchone()

            if pnl_row:
                pnl = pnl_row[0]
                won = pnl_row[1] == "won"

                # Update bankroll and P&L tracking
                self.state["bankroll"] += pnl
                self.state["total_pnl"] += pnl
                self.state["daily_pnl"] += pnl
                self.state["total_deployed"] -= pos.get("size_usd", 0)
                if won:
                    self.state["winning_trades"] += 1

                # Update veterans allocation (20% of net profits)
                if self.state["total_pnl"] > 0:
                    self.state["veterans_allocation"] = self.state["total_pnl"] * 0.20

        # Clamp total_deployed to non-negative
        self.state["total_deployed"] = max(0, self.state["total_deployed"])

        self.save()
        logger.info(f"Synced {len(to_remove)} resolved positions from state "
                    f"(open: {len(self.state['open_positions'])} remaining)")
        return len(to_remove)


# ---------------------------------------------------------------------------
# Geoblock Check
# ---------------------------------------------------------------------------
def check_geoblock() -> dict:
    """Check if current IP is geo-blocked by Polymarket.

    Returns:
        Dict with 'blocked', 'country', 'ip' keys.

    Raises:
        RuntimeError if blocked.
    """
    import requests as _req
    try:
        resp = _req.get("https://polymarket.com/api/geoblock", timeout=10).json()
        if resp.get("blocked"):
            raise RuntimeError(
                f"GEO-BLOCKED: country={resp.get('country')} ip={resp.get('ip')} "
                f"— Polymarket trading not available from this region"
            )
        logger.info(f"Geoblock check PASSED: country={resp.get('country')} ip={resp.get('ip')}")
        return resp
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f"Geoblock check failed (non-fatal): {e}")
        return {"blocked": None, "country": "unknown", "ip": "unknown"}


# ---------------------------------------------------------------------------
# JJ Live Trading Engine
# ---------------------------------------------------------------------------
class JJLive:
    """JJ Autonomous Live Trading System."""

    def __init__(self):
        # Early geoblock check — fail fast if in restricted region
        check_geoblock()

        self.paper_mode = PAPER_TRADING
        self.state = JJState()
        self.scanner = MarketScanner()

        # Market quarantine: gracefully handle CLOB 404s with exponential backoff
        if MarketQuarantine is not None:
            self.quarantine = MarketQuarantine(db_path="data/edge_discovery.db")
            logger.info("Market quarantine initialized (%d active)", self.quarantine.stats()["active_count"])
        else:
            self.quarantine = None

        # LLM Analyzer: prefer ensemble (multi-model + RAG) over single Claude
        self.ensemble_mode = False
        if LLMEnsemble is not None:
            try:
                self.analyzer = LLMEnsemble(enable_rag=True, enable_brier=True)
                self.ensemble_mode = True
                logger.info(f"LLM Ensemble initialized: {len(self.analyzer.models)} models, RAG=ON, Brier=ON")
            except Exception as e:
                logger.warning(f"LLM Ensemble init failed, falling back to Claude-only: {e}")
                self.analyzer = ClaudeAnalyzer()
        else:
            self.analyzer = ClaudeAnalyzer()
            logger.info("Using single-model ClaudeAnalyzer (LLM Ensemble not available)")

        self.notifier = self._init_telegram()
        self.db = TradeDatabase()
        self.adaptive_platt = AdaptivePlattCalibrator(self.db)
        self.adaptive_platt.refresh(force=True)
        if self.adaptive_platt.enabled:
            cal = self.adaptive_platt.summary()
            logger.info(
                "Adaptive Platt: mode=%s A=%.4f B=%.4f samples=%d static_brier=%s rolling_brier=%s",
                cal["mode"],
                cal["a"],
                cal["b"],
                cal["samples"],
                f"{cal['static_brier']:.4f}" if cal["static_brier"] is not None else "n/a",
                f"{cal['rolling_brier']:.4f}" if cal["rolling_brier"] is not None else "n/a",
            )
        self.multi_sim = MultiBankrollSimulator(self.db)

        # Only init CLOB client for live trading
        if not self.paper_mode:
            self.clob = self._init_clob_client()
        else:
            self.clob = None
            logger.info("PAPER TRADING MODE — orders will be simulated locally")

        # Signal source #2: LMSR Bayesian Engine
        if LMSREngine is not None:
            self.lmsr_engine = LMSREngine(
                entry_threshold=float(os.environ.get("JJ_LMSR_THRESHOLD", "0.05")),
            )
            logger.info("LMSR Bayesian Engine initialized")
        else:
            self.lmsr_engine = None
            logger.warning("LMSR engine not available — running without")

        # Signal source #3: Smart Wallet Flow Detector
        self.wallet_flow_available = wallet_flow_get_signals is not None
        if self.wallet_flow_available:
            logger.info("Smart Wallet Flow Detector available")
        else:
            logger.warning("Wallet flow detector not available — running without")

        # Signal source #4: Cross-Platform Arbitrage Scanner
        self.arb_available = arb_get_signals is not None
        if self.arb_available:
            logger.info("Cross-platform arb scanner available")
        else:
            logger.warning("Cross-platform arb scanner not available — running without")

        # Signal source #5: WebSocket Trade Stream + VPIN/OFI defense
        self.trade_stream = None
        self._trade_stream_task = None
        if TradeStreamManager is not None:
            try:
                self.trade_stream = TradeStreamManager(
                    vpin_bucket_size=float(os.environ.get("JJ_VPIN_BUCKET_SIZE", "500")),
                    vpin_window_size=int(os.environ.get("JJ_VPIN_WINDOW", "10")),
                    on_regime_change=self._on_regime_change,
                    on_ofi_alert=self._on_ofi_alert,
                    heartbeat_interval=float(os.environ.get("JJ_WS_HEARTBEAT_INTERVAL", "10")),
                    rest_poll_interval=float(os.environ.get("JJ_WS_REST_POLL_INTERVAL", "5")),
                )
                logger.info("WebSocket Trade Stream + VPIN/OFI initialized")
            except Exception as e:
                logger.warning(f"Trade stream init failed: {e}")
                self.trade_stream = None
        else:
            logger.warning("Trade stream not available — running without microstructure defense")

        # Signal source #6: Semantic Lead-Lag Arbitrage Engine
        self.lead_lag = None
        if LeadLagEngine is not None:
            try:
                self.lead_lag = LeadLagEngine()
                logger.info("Semantic Lead-Lag Engine initialized")
            except Exception as e:
                logger.warning(f"Lead-lag engine init failed: {e}")
                self.lead_lag = None
        else:
            logger.warning("Lead-lag engine not available — running without")

        # Signals 5/6: A-6 + B-1 structural alpha integration.
        self.combinatorial_cfg = (
            CombinatorialConfig.from_env() if CombinatorialConfig is not None else None
        )
        self.constraint_signal_store = None
        self.a6_shadow_scanner = None
        self._constraint_last_seen_ts = 0
        self._seen_combinatorial_baskets: set[str] = set()
        self._last_combinatorial_cycle = {
            "a6_detected": 0,
            "b1_detected": 0,
            "shadow_logged": 0,
            "live_attempted": 0,
            "blocked": 0,
            "active_baskets": 0,
            "arb_budget_in_use_usd": 0.0,
            "kill_triggers": [],
            "metrics": {},
        }
        if self.combinatorial_cfg is not None and self.combinatorial_cfg.any_enabled():
            if CombinatorialSignalStore is not None:
                self.constraint_signal_store = CombinatorialSignalStore(
                    self.combinatorial_cfg.constraint_db_path
                )
                self._constraint_last_seen_ts = max(
                    0,
                    int(time.time()) - max(1, int(self.combinatorial_cfg.stale_book_max_age_seconds)),
                )
            if (
                SumViolationScanner is not None
                and self.combinatorial_cfg.embedded_a6_scanner_enabled
                and (self.combinatorial_cfg.enable_a6_shadow or self.combinatorial_cfg.enable_a6_live)
            ):
                try:
                    self.a6_shadow_scanner = SumViolationScanner(
                        db_path=self.combinatorial_cfg.constraint_db_path,
                        buy_threshold=self.combinatorial_cfg.a6_buy_threshold,
                        unwind_threshold=self.combinatorial_cfg.a6_unwind_threshold,
                        stale_quote_seconds=self.combinatorial_cfg.stale_book_max_age_seconds,
                    )
                    logger.info("A-6 embedded shadow scanner enabled")
                except Exception as e:
                    logger.warning(f"A-6 embedded shadow scanner init failed: {e}")
                    self.a6_shadow_scanner = None

        # A-6 live execution: basket state machine + order routing
        self.a6_executor = None
        self.a6_command_router = None
        self._a6_order_map: dict[str, str] = {}
        if (
            A6BasketExecutor is not None
            and A6CommandRouter is not None
            and self.combinatorial_cfg is not None
            and self.combinatorial_cfg.enable_a6_live
        ):
            try:
                self.a6_executor = A6BasketExecutor(
                    config=A6ExecutorConfig(
                        max_leg_notional_usd=min(
                            MAX_POSITION_USD,
                            self.combinatorial_cfg.max_notional_per_leg_usd,
                        ),
                        max_open_baskets=5,
                        max_daily_loss_usd=MAX_DAILY_LOSS_USD,
                        fill_timeout_seconds=self.combinatorial_cfg.fill_timeout_seconds,
                        signature_type=1,
                    ),
                )
                if self.clob is not None:
                    self.a6_command_router = A6CommandRouter(
                        self.clob,
                        order_args_cls=OrderArgs,
                        order_type_cls=OrderType,
                        buy_const=BUY,
                        sell_const=SELL,
                        paper_mode=self.paper_mode,
                    )
                logger.info("A-6 basket executor initialized (router=%s)", "live" if self.a6_command_router else "none")
            except Exception as e:
                logger.warning(f"A-6 executor init failed: {e}")
                self.a6_executor = None

        mode_str = "PAPER" if self.paper_mode else "LIVE"
        logger.info("=" * 60)
        logger.info(f"JJ {mode_str} TRADING SYSTEM — INITIALIZED")
        logger.info(f"  Mode: {mode_str}")
        logger.info(f"  Bankroll: ${self.state.state['bankroll']:.2f}")
        logger.info(f"  Multi-bankroll: {BANKROLL_LEVELS}")
        logger.info(
            "  Open positions: %s single-leg / %s linked baskets",
            len(self.state.state["open_positions"]),
            self.state.count_active_linked_baskets(),
        )
        logger.info(f"  Max per trade: ${MAX_POSITION_USD}")
        logger.info(f"  Daily loss limit: ${MAX_DAILY_LOSS_USD}")
        logger.info(f"  Kelly fraction: {KELLY_FRACTION} (max {MAX_KELLY_FRACTION})")
        logger.info(f"  Scan interval: {SCAN_INTERVAL}s")
        logger.info(f"  Platt calibration: A={PLATT_A}, B={PLATT_B}")
        if self.adaptive_platt.enabled:
            logger.info(
                f"  Adaptive Platt: EXPERIMENTAL ON (window={ADAPTIVE_PLATT_WINDOW}, "
                f"min={ADAPTIVE_PLATT_MIN_SAMPLES}, refit={ADAPTIVE_PLATT_REFIT_SECONDS}s)"
            )
        else:
            logger.info("  Adaptive Platt: OFF (static params preserved)")
        logger.info(
            f"  Ensemble agreement floor: {ENSEMBLE_MIN_AGREEMENT:.2f} "
            f"(fragile conviction skip={'ON' if ENSEMBLE_SKIP_FRAGILE_CONVICTION else 'OFF'})"
        )
        logger.info(
            f"  Disagreement Kelly: std<={DISAGREEMENT_LOW_STD:.2f} => {MAX_KELLY_FRACTION:.4f}, "
            f"std>={DISAGREEMENT_HIGH_STD:.2f} => {DISAGREEMENT_MIN_KELLY:.5f}"
        )
        logger.info(f"  Thresholds: YES={YES_THRESHOLD:.0%}, NO={NO_THRESHOLD:.0%}")
        logger.info(f"  Category filter: skip priority < {MIN_CATEGORY_PRIORITY}")
        if self.combinatorial_cfg is not None:
            logger.info(
                "  Combinatorial flags: A6(shadow=%s live=%s) B1(shadow=%s live=%s)",
                self.combinatorial_cfg.enable_a6_shadow,
                self.combinatorial_cfg.enable_a6_live,
                self.combinatorial_cfg.enable_b1_shadow,
                self.combinatorial_cfg.enable_b1_live,
            )
            logger.info(
                "  Combinatorial caps: max_leg=$%.2f arb_budget=$%.2f stale=%ss fill_timeout=%sms merge_min=$%.2f",
                self.combinatorial_cfg.max_notional_per_leg_usd,
                self.combinatorial_cfg.arb_budget_usd,
                self.combinatorial_cfg.stale_book_max_age_seconds,
                self.combinatorial_cfg.fill_timeout_ms,
                self.combinatorial_cfg.merge_min_notional_usd,
            )
        logger.info(f"  Database: {DB_FILE}")
        logger.info("=" * 60)

    def _init_telegram(self):
        """Initialize Telegram notifier (handles both class versions)."""
        if TelegramNotifier is None:
            logger.warning("Telegram module not available — notifications disabled")
            return _DummyNotifier()

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        try:
            # Try keyword args (local codebase style)
            return TelegramNotifier(bot_token=token, chat_id=chat_id)
        except TypeError:
            try:
                # Try positional args (VPS codebase style)
                return TelegramNotifier(token, chat_id)
            except TypeError:
                try:
                    # Try no-arg constructor (reads from env)
                    return TelegramNotifier()
                except Exception:
                    logger.warning("Could not init Telegram — notifications disabled")
                    return _DummyNotifier()

    def _run_embedded_a6_shadow_scan(self) -> tuple[dict, list]:
        """Refresh the shared constraint DB and extract A6Opportunity objects.

        Returns (scan_metrics_dict, list_of_A6Opportunity).
        """
        if self.a6_shadow_scanner is None:
            return {}, []
        try:
            stats = self.a6_shadow_scanner.scan_once()
            opportunities = list(getattr(self.a6_shadow_scanner, "_latest_opportunities", []))
            return {
                "events_fetched": stats.events_fetched,
                "candidate_events": stats.candidate_events,
                "candidate_markets": stats.candidate_markets,
                "quotes_updated": stats.quotes_updated,
                "violations_found": stats.violations_found,
                "opportunities_found": len(opportunities),
                "elapsed_seconds": stats.elapsed_seconds,
            }, opportunities
        except Exception as e:
            logger.warning(f"A-6 embedded shadow scan failed: {e}")
            return {"error": str(e)}, []

    def _execute_a6_live_cycle(self, new_opportunities: list) -> dict:
        """Tick active A-6 baskets and submit new opportunities.

        1. Poll fill status for all active basket legs.
        2. Advance time on active baskets (handles timeout/reprice).
        3. Filter and submit new executable opportunities.
        4. Route resulting commands through A6CommandRouter.

        Returns metrics dict for cycle logging.
        """
        if self.a6_executor is None or self.a6_command_router is None:
            return {}

        now_ts = int(time.time())
        stats = {
            "active_baskets": len(self.a6_executor.active_baskets),
            "fills_detected": 0,
            "commands_routed": 0,
            "submitted": 0,
            "completed": 0,
            "rolled_back": 0,
            "expired": 0,
        }

        # Step 1: Poll fills for active baskets
        for basket_id, basket in list(self.a6_executor.active_baskets.items()):
            for leg in basket.legs:
                if leg.order_id is None or leg.remaining_quantity <= 1e-9:
                    continue
                clob_id = self.a6_command_router.get_clob_order_id(leg.leg_id)
                if not clob_id:
                    continue
                fill = self.a6_command_router.poll_fill_status(clob_id)
                if fill is None or fill.size_matched <= 0:
                    continue
                if fill.size_matched > leg.filled_quantity + 1e-9:
                    delta = fill.size_matched - leg.filled_quantity
                    update = self.a6_executor.apply_fill(
                        basket_id,
                        leg_id=leg.leg_id,
                        filled_quantity=delta,
                        avg_price=fill.avg_price if fill.avg_price > 0 else leg.quote_price,
                        now_ts=now_ts,
                    )
                    stats["fills_detected"] += 1
                    self._process_a6_update(update, stats)

        # Step 2: Advance time on active baskets (timeout/reprice)
        for basket_id in list(self.a6_executor.active_baskets.keys()):
            update = self.a6_executor.advance_time(basket_id, now_ts=now_ts)
            self._process_a6_update(update, stats)

        # Step 3: Submit new opportunities
        min_depth_usd = 10.0
        for opp in new_opportunities:
            if not opp.executable or opp.signal_type not in {"buy_yes_basket", "buy_yes_no_straddle"}:
                continue
            if opp.theoretical_edge <= 0.0 or opp.readiness_status != "ready":
                continue
            # Check depth: all legs need >$10 at best ask
            depth_ok = all(
                leg.best_ask > 0 and (min_depth_usd / max(leg.best_ask, 0.01)) <= 1000
                for leg in opp.legs
            )
            if not depth_ok:
                continue
            try:
                update = self.a6_executor.submit_opportunity(opp, now_ts=now_ts)
                stats["submitted"] += 1
                self._process_a6_update(update, stats)
                logger.info(
                    "A-6 SUBMITTED: basket=%s event=%s edge=%.3f legs=%d construction=%s",
                    opp.basket_id[:16],
                    opp.event_id[:16],
                    opp.theoretical_edge,
                    len(opp.legs),
                    opp.selected_construction,
                )
            except ValueError as e:
                logger.debug("A-6 submission rejected: %s", e)
            except Exception as e:
                logger.warning("A-6 submission failed: %s", e)

        stats["active_baskets"] = len(self.a6_executor.active_baskets)
        return stats

    def _process_a6_update(self, update, stats: dict) -> None:
        """Route commands from an A6ExecutorUpdate and handle lifecycle events."""
        if not update.commands and not update.events:
            return

        # Route commands to CLOB
        if update.commands and self.a6_command_router is not None:
            results = self.a6_command_router.execute_commands(update.commands)
            stats["commands_routed"] += len(results)
            for result in results:
                if result.success:
                    logger.info(
                        "A-6 %s OK: basket=%s leg=%s order=%s",
                        result.command_action,
                        result.basket_id[:12],
                        result.leg_id[:12] if result.leg_id else "?",
                        result.order_id[:16] if result.order_id else "?",
                    )
                else:
                    logger.warning(
                        "A-6 %s FAILED: basket=%s leg=%s error=%s",
                        result.command_action,
                        result.basket_id[:12],
                        result.leg_id[:12] if result.leg_id else "?",
                        result.error,
                    )

        # Handle lifecycle events (state transitions, completions, rollbacks)
        for event in update.events:
            if not hasattr(event, "state"):
                continue
            if hasattr(A6BasketState, "COMPLETE") and event.state == A6BasketState.COMPLETE.value:
                stats["completed"] += 1
                self._on_a6_basket_complete(update.basket, event)
            elif hasattr(A6BasketState, "ROLLED_BACK") and event.state == A6BasketState.ROLLED_BACK.value:
                stats["rolled_back"] += 1
                self._on_a6_basket_rollback(update.basket, event)
            elif hasattr(A6BasketState, "EXPIRED") and event.state == A6BasketState.EXPIRED.value:
                stats["expired"] += 1

    async def _send_a6_notification(self, message: str) -> None:
        """Send A-6 event notification via Telegram."""
        try:
            await self.notifier.send_message(message)
        except Exception:
            pass

    def _on_a6_basket_complete(self, basket, event) -> None:
        """Handle A-6 basket completion: log fill, update position tracking."""
        profit = getattr(basket, "realized_profit_usd", 0.0)
        logger.info(
            "A-6 COMPLETE: basket=%s event=%s profit=$%.4f legs=%d",
            basket.basket_id[:16],
            basket.event_id[:16],
            profit,
            len(basket.legs),
        )
        # Position tracking: fills already recorded by executor's internal
        # NegRiskInventory.  Log to constraint_arb.db for historical analysis.
        try:
            self.db.log_trade({
                "market_id": basket.event_id,
                "question": f"A-6 basket {basket.basket_id[:16]}",
                "direction": "buy_yes_basket",
                "price": sum(leg.avg_fill_price for leg in basket.filled_legs) / max(1, len(basket.filled_legs)),
                "size_usd": basket.filled_notional_usd,
                "edge": basket.theoretical_edge,
                "confidence": 1.0,
                "order_id": basket.basket_id,
                "source": "a6",
            })
        except Exception as e:
            logger.debug("A-6 trade log failed: %s", e)

    def _on_a6_basket_rollback(self, basket, event) -> None:
        """Handle A-6 basket rollback: log loss."""
        loss = getattr(basket, "rollback_loss_usd", 0.0)
        logger.warning(
            "A-6 ROLLBACK: basket=%s event=%s loss=$%.4f filled=%d/%d legs",
            basket.basket_id[:16],
            basket.event_id[:16],
            loss,
            len(basket.filled_legs),
            len(basket.legs),
        )

    def _evaluate_combinatorial_health(self) -> dict:
        summary = self.db.get_combinatorial_summary(hours=24 * 14)
        lane_health: dict[str, dict] = {}
        if self.combinatorial_cfg is None or run_combinatorial_promotion_battery is None:
            summary["lane_health"] = lane_health
            return summary

        for lane, metrics in summary.get("lanes", {}).items():
            lane_enabled = self.combinatorial_cfg.shadow_enabled(lane) or self.combinatorial_cfg.live_enabled(lane)
            if not lane_enabled:
                continue
            if metrics.get("detected", 0) <= 0:
                lane_health[lane] = {"ready_for_live": False, "status": "no_samples", "kill_triggers": []}
                continue

            require_classification = lane == "b1"
            passed, results = run_combinatorial_promotion_battery(
                signal_count=int(metrics.get("detected", 0)),
                capture_rate=metrics.get("avg_capture_rate"),
                false_positive_rate=metrics.get("false_positive_rate"),
                consecutive_rollbacks=int(metrics.get("consecutive_rollbacks", 0)),
                minimum_signals=self.combinatorial_cfg.shadow_promotion_min_signals,
                minimum_capture_rate=self.combinatorial_cfg.required_capture_rate,
                maximum_false_positive_rate=self.combinatorial_cfg.max_false_positive_rate,
                maximum_consecutive_rollbacks=self.combinatorial_cfg.max_consecutive_rollbacks,
                require_classification=require_classification,
                classification_accuracy=metrics.get("avg_classification_accuracy"),
                minimum_classification_accuracy=self.combinatorial_cfg.required_classification_accuracy,
            )
            triggers = [
                result.reason.value
                for result in results
                if not result.passed and result.reason is not None
            ]
            lane_health[lane] = {
                "ready_for_live": passed,
                "status": "ready" if passed else "blocked",
                "kill_triggers": triggers,
            }
            summary.setdefault("kill_triggers", []).extend(triggers)

        summary["kill_triggers"] = sorted(set(summary.get("kill_triggers", [])))
        summary["lane_health"] = lane_health
        return summary

    def _record_combinatorial_basket(
        self,
        signal: dict,
        *,
        execution_mode: str,
        state: str,
        state_reason: str,
        budget_usd: float,
        kill_rule_trigger: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        created_at = signal.get("created_at") or datetime.now(timezone.utc).isoformat()
        payload = {
            "attempt_id": signal.get("basket_id", signal.get("violation_id", "")),
            "basket_id": signal.get("basket_id", signal.get("violation_id", "")),
            "violation_id": signal.get("violation_id", signal.get("basket_id", "")),
            "lane": signal.get("source", "unknown"),
            "source_id": signal.get("source_id", 0),
            "source_tag": signal.get("source_tag", ""),
            "relation_type": signal.get("relation_type", ""),
            "confirmation_mode": signal.get("confirmation_mode", "bypass"),
            "execution_mode": execution_mode,
            "state": state,
            "state_reason": state_reason,
            "event_id": signal.get("event_id", ""),
            "market_ids": signal.get("market_ids", []),
            "theoretical_edge": signal.get("theoretical_edge", signal.get("edge", 0.0)),
            "realized_edge": signal.get("realized_edge"),
            "capture_rate": signal.get("capture_rate"),
            "partial_fill_loss": signal.get("partial_fill_loss"),
            "classification_accuracy": signal.get("classification_accuracy"),
            "resolution_gate_status": signal.get("resolution_gate_status", ""),
            "reserved_budget_usd": budget_usd if execution_mode == "live" else 0.0,
            "budget_usd": budget_usd if execution_mode == "live" else 0.0,
            "kill_rule_trigger": kill_rule_trigger,
            "created_at": created_at,
            "metadata": {
                "details": signal.get("details", {}),
                "live_eligible": bool(signal.get("live_eligible", False)),
                **(metadata or {}),
            },
        }
        self.state.upsert_linked_legs(payload["basket_id"], payload)
        self.db.upsert_combinatorial_basket(payload)

    def _process_combinatorial_cycle(self, cycle_number: int) -> tuple[list[dict], dict]:
        empty_summary = {
            "cycle_number": cycle_number,
            "a6_detected": 0,
            "b1_detected": 0,
            "shadow_logged": 0,
            "live_attempted": 0,
            "blocked": 0,
            "active_baskets": self.state.count_active_linked_baskets(),
            "arb_budget_in_use_usd": self.state.get_arb_budget_in_use_usd(),
            "kill_triggers": [],
            "metrics": {},
        }
        if (
            self.combinatorial_cfg is None
            or not self.combinatorial_cfg.any_enabled()
            or self.constraint_signal_store is None
        ):
            self._last_combinatorial_cycle = empty_summary
            return [], empty_summary

        cycle_metrics: dict[str, Any] = {}
        embedded_scan, a6_opportunities = self._run_embedded_a6_shadow_scan()
        if embedded_scan:
            cycle_metrics["embedded_a6_scan"] = embedded_scan

        # Execute A-6 live cycle: tick active baskets + submit new opportunities
        a6_live_stats = self._execute_a6_live_cycle(a6_opportunities)
        if a6_live_stats:
            cycle_metrics["a6_live"] = a6_live_stats
            empty_summary["live_attempted"] += a6_live_stats.get("submitted", 0)

        now_ts = int(time.time())
        opportunities = self.constraint_signal_store.poll_new_opportunities(
            since_ts=self._constraint_last_seen_ts,
            config=self.combinatorial_cfg,
            now_ts=now_ts,
        )
        if opportunities:
            self._constraint_last_seen_ts = max(
                self._constraint_last_seen_ts,
                max(opportunity.detected_at_ts for opportunity in opportunities) - 1,
            )

        emitted_signals: list[dict] = []
        summary = dict(empty_summary)
        for opportunity in opportunities:
            if opportunity.basket_id in self._seen_combinatorial_baskets:
                continue
            signal = attach_signal_source_metadata(opportunity.to_signal())
            lane = signal.get("source", "unknown")
            if lane == "a6":
                summary["a6_detected"] += 1
            elif lane == "b1":
                summary["b1_detected"] += 1

            decision = evaluate_combinatorial_risk(
                opportunity,
                config=self.combinatorial_cfg,
                daily_pnl=self.state.state["daily_pnl"],
                max_daily_loss_usd=MAX_DAILY_LOSS_USD,
                open_positions=len(self.state.state["open_positions"]),
                open_baskets=self.state.count_active_linked_baskets(),
                max_open_positions=MAX_OPEN_POSITIONS,
                arb_budget_in_use_usd=self.state.get_arb_budget_in_use_usd(),
            )

            if decision is None or not decision.allow:
                summary["blocked"] += 1
                trigger = decision.kill_trigger if decision is not None else "risk_router_unavailable"
                if trigger:
                    summary["kill_triggers"].append(trigger)
                self._record_combinatorial_basket(
                    signal,
                    execution_mode="blocked",
                    state="BLOCKED",
                    state_reason=decision.reason if decision is not None else "risk_router_unavailable",
                    budget_usd=0.0,
                    kill_rule_trigger=trigger,
                )
                self._seen_combinatorial_baskets.add(opportunity.basket_id)
                continue

            if opportunity.live_eligible and self.combinatorial_cfg.live_enabled(lane) and not self.paper_mode:
                if self.a6_executor is None or self.a6_command_router is None or lane != "a6":
                    # Executor not available for this lane — block
                    summary["blocked"] += 1
                    summary["kill_triggers"].append("executor_unavailable")
                    self._record_combinatorial_basket(
                        signal,
                        execution_mode="blocked",
                        state="EXECUTOR_PENDING",
                        state_reason="executor adapter not wired" if lane != "a6" else "b1 executor pending",
                        budget_usd=0.0,
                        kill_rule_trigger="executor_unavailable",
                    )
                else:
                    # A-6 live execution: opportunity will be handled by
                    # _execute_a6_live_cycle via scanner-produced A6Opportunity
                    # objects.  Record as live-routed for tracking.
                    summary["live_attempted"] += 1
                    self._record_combinatorial_basket(
                        signal,
                        execution_mode="live",
                        state="LIVE_ROUTED",
                        state_reason="a6_executor_active",
                        budget_usd=decision.reserved_budget_usd,
                    )
                self._seen_combinatorial_baskets.add(opportunity.basket_id)
                continue

            if self.combinatorial_cfg.shadow_enabled(lane) or self.paper_mode:
                summary["shadow_logged"] += 1
                emitted_signals.append(signal)
                self._record_combinatorial_basket(
                    signal,
                    execution_mode="shadow",
                    state="SHADOW_LOGGED",
                    state_reason="shadow_mode",
                    budget_usd=0.0,
                )
                self._seen_combinatorial_baskets.add(opportunity.basket_id)
                continue

            summary["blocked"] += 1
            summary["kill_triggers"].append("lane_disabled")
            self._record_combinatorial_basket(
                signal,
                execution_mode="blocked",
                state="BLOCKED",
                state_reason="lane_disabled",
                budget_usd=0.0,
                kill_rule_trigger="lane_disabled",
            )
            self._seen_combinatorial_baskets.add(opportunity.basket_id)

        health = self._evaluate_combinatorial_health()
        cycle_metrics["health"] = health
        summary["active_baskets"] = self.state.count_active_linked_baskets()
        summary["arb_budget_in_use_usd"] = self.state.get_arb_budget_in_use_usd()
        summary["kill_triggers"].extend(health.get("kill_triggers", []))
        summary["kill_triggers"] = sorted(set(summary["kill_triggers"]))
        summary["metrics"] = cycle_metrics
        self.db.log_combinatorial_cycle(summary)
        self._last_combinatorial_cycle = summary
        return emitted_signals, summary

    def _on_regime_change(self, token_id: str, prev_regime, new_regime):
        """Callback when VPIN regime changes for a market."""
        logger.info(f"VPIN regime change: {token_id[:12]}... {prev_regime.value} → {new_regime.value}")
        if new_regime.value == "toxic":
            logger.warning(f"TOXIC FLOW detected on {token_id[:12]}... — should pull maker quotes")
            # In live mode, cancel resting orders on this token
            if self.clob and not self.paper_mode:
                try:
                    self.clob.cancel_all()
                    logger.info("Cancelled all resting orders due to toxic flow")
                except Exception as e:
                    logger.error(f"Failed to cancel orders on toxic flow: {e}")

    def _on_ofi_alert(self, token_id: str, ofi_snapshot):
        """Callback when OFI kill switch triggers."""
        logger.warning(
            f"OFI KILL SWITCH: {token_id[:12]}... "
            f"skew={ofi_snapshot.directional_skew:.2f} z={ofi_snapshot.normalized_ofi:.2f}"
        )

    def _get_market_microstructure(self, market_id: str, market_lookup: dict) -> dict | None:
        """Aggregate token-level VPIN/OFI state into a market-level snapshot."""
        if self.trade_stream is None:
            return None

        market_data = market_lookup.get(market_id)
        if market_data is None:
            market_data = market_lookup.get(str(market_id))
        if market_data is None:
            try:
                market_data = market_lookup.get(int(market_id))
            except (TypeError, ValueError):
                market_data = None
        if not isinstance(market_data, dict):
            return None

        token_ids = [str(token_id) for token_id in market_data.get("token_ids", []) if token_id]
        if not token_ids:
            return None

        snapshots = [self.trade_stream.get_microstructure(token_id) for token_id in token_ids]
        snapshots = [snapshot for snapshot in snapshots if snapshot]
        if not snapshots:
            return None

        worst_vpin = max(snapshots, key=lambda snapshot: _safe_float(snapshot.get("vpin"), 0.5))
        strongest_ofi = max(
            snapshots,
            key=lambda snapshot: abs(_safe_float(snapshot.get("ofi"), 0.0)),
        )
        status = self.trade_stream.get_status()
        latency = status.get("latency", {}) if isinstance(status.get("latency", {}), dict) else {}

        return {
            "tokens": token_ids,
            "vpin": _safe_float(worst_vpin.get("vpin"), 0.5),
            "regime": worst_vpin.get("regime", "neutral"),
            "ofi": strongest_ofi.get("ofi"),
            "ofi_skew": strongest_ofi.get("ofi_skew"),
            "connection_mode": strongest_ofi.get("connection_mode", status.get("connection_mode", "unknown")),
            "fallback_active": bool(
                strongest_ofi.get("fallback_active", status.get("fallback_active", False))
            ),
            "latency_p99_ms": _safe_float(
                strongest_ofi.get("latency_p99_ms"),
                _safe_float(latency.get("processing_p99_ms"), 0.0),
            ),
        }

    def _attach_microstructure_context(self, signal: dict, market_lookup: dict) -> dict:
        """Attach VPIN/OFI context to a signal and log it alongside the LLM probability."""
        micro = self._get_market_microstructure(signal.get("market_id", ""), market_lookup)
        if not micro:
            return signal

        signal.update(
            {
                "vpin": micro["vpin"],
                "flow_regime": micro["regime"],
                "ofi": micro["ofi"],
                "ofi_skew": micro["ofi_skew"],
                "microstructure_mode": micro["connection_mode"],
                "microstructure_fallback": micro["fallback_active"],
                "ws_latency_p99_ms": micro["latency_p99_ms"],
            }
        )

        est_prob = _safe_float(signal.get("estimated_prob"), 0.5)
        ofi_val = micro.get("ofi")
        ofi_skew = micro.get("ofi_skew")
        ofi_str = f"{ofi_val:.3f}" if isinstance(ofi_val, (int, float)) else "n/a"
        skew_str = f"{ofi_skew:.3f}" if isinstance(ofi_skew, (int, float)) else "n/a"
        logger.info(
            "LLM+Microstructure: prob=%.3f vpin=%.3f regime=%s ofi=%s skew=%s mode=%s p99=%.2fms | %s",
            est_prob,
            micro["vpin"],
            micro["regime"],
            ofi_str,
            skew_str,
            micro["connection_mode"],
            micro["latency_p99_ms"],
            signal.get("question", "")[:60],
        )
        return signal

    def _init_clob_client(self) -> OfficialClobClient:
        """Initialize CLOB client using official py-clob-client library.

        Derives L2 API credentials on startup and caches them for the session.
        """
        if OfficialClobClient is None or ApiCreds is None:
            raise RuntimeError("py_clob_client is required for live trading mode")

        private_key = os.environ.get("POLY_PRIVATE_KEY", "")
        safe_address = os.environ.get("POLY_SAFE_ADDRESS", "")

        if not private_key:
            logger.error("NO PRIVATE KEY — cannot trade")
            sys.exit(1)
        if not safe_address:
            logger.error("NO SAFE ADDRESS — cannot trade")
            sys.exit(1)

        if not private_key.startswith("0x"):
            private_key = "0x" + private_key

        # Create client without creds first to derive them
        # signature_type=1 (POLY_PROXY) — Polymarket proxy wallet
        # signature_type=2 (Gnosis Safe) causes "invalid signature" on orders
        client = OfficialClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            signature_type=1,
            funder=safe_address,
        )

        # Derive L2 API credentials (the .env builder creds are NOT valid L2 creds)
        try:
            derived = client.derive_api_key()
            logger.info(f"Derived L2 API key: {derived.api_key[:12]}...")
        except Exception:
            try:
                derived = client.create_api_key()
                logger.info(f"Created L2 API key: {derived.api_key[:12]}...")
            except Exception as e:
                logger.error(f"Failed to get L2 API credentials: {e}")
                sys.exit(1)

        # Re-create client with derived credentials
        creds = ApiCreds(
            api_key=derived.api_key,
            api_secret=derived.api_secret,
            api_passphrase=derived.api_passphrase,
        )
        client = OfficialClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            creds=creds,
            signature_type=1,
            funder=safe_address,
        )

        # Verify auth works
        try:
            client.get_orders()
            logger.info("CLOB auth verified — orders endpoint accessible")
        except Exception as e:
            logger.warning(f"Auth verification warning: {e}")

        return client

    async def run_cycle(self) -> dict:
        """Run one scan → analyze → trade cycle.

        Returns:
            Cycle summary dict.
        """
        cycle_start = time.time()
        cycle_num = self.state.state["cycles_completed"] + 1
        logger.info(f"=== JJ Cycle {cycle_num} starting ===")

        # Sync resolved positions: remove closed trades from state to free
        # position slots.  Without this, open_positions grows forever and
        # the bot stops at MAX_OPEN_POSITIONS.
        try:
            synced = self.state.sync_resolved_positions(self.db)
            if synced > 0:
                logger.info(f"Cleared {synced} resolved positions")
        except Exception as e:
            logger.warning(f"Position sync failed (non-fatal): {e}")

        # Safety check: daily loss limit
        if not self.state.check_daily_loss_limit():
            logger.warning(f"DAILY LOSS LIMIT HIT: ${self.state.state['daily_pnl']:.2f}")
            await self.notifier.send_message(
                f"⛔ JJ DAILY LOSS LIMIT — P&L: ${self.state.state['daily_pnl']:.2f}\n"
                f"Pausing until tomorrow."
            )
            return {"status": "paused", "reason": "daily_loss_limit"}

        # Refresh adaptive calibration window from latest resolved trades.
        try:
            self.adaptive_platt.refresh()
        except Exception as e:
            logger.warning(f"Adaptive Platt refresh failed (non-fatal): {e}")

        combinatorial_signals, combinatorial_cycle = self._process_combinatorial_cycle(cycle_num)
        if combinatorial_cycle["a6_detected"] or combinatorial_cycle["b1_detected"]:
            logger.info(
                "Combinatorial cycle: A6=%s B1=%s shadow=%s blocked=%s active=%s budget=$%.2f",
                combinatorial_cycle["a6_detected"],
                combinatorial_cycle["b1_detected"],
                combinatorial_cycle["shadow_logged"],
                combinatorial_cycle["blocked"],
                combinatorial_cycle["active_baskets"],
                combinatorial_cycle["arb_budget_in_use_usd"],
            )

        # A-6 Telegram notifications
        a6_live = combinatorial_cycle.get("metrics", {}).get("a6_live", {})
        if a6_live.get("submitted", 0) > 0:
            await self._send_a6_notification(
                f"A-6 EXEC: {a6_live['submitted']} baskets submitted, "
                f"{a6_live.get('commands_routed', 0)} orders routed, "
                f"{a6_live.get('active_baskets', 0)} active"
            )
        if a6_live.get("completed", 0) > 0:
            await self._send_a6_notification(
                f"A-6 COMPLETE: {a6_live['completed']} baskets filled"
            )
        if a6_live.get("rolled_back", 0) > 0:
            await self._send_a6_notification(
                f"A-6 ROLLBACK: {a6_live['rolled_back']} baskets rolled back"
            )
        a6_scan = combinatorial_cycle.get("metrics", {}).get("embedded_a6_scan", {})
        if a6_scan.get("violations_found", 0) > 0:
            await self._send_a6_notification(
                f"A-6 SCAN: {a6_scan['violations_found']} violations found, "
                f"{a6_scan.get('opportunities_found', 0)} executable opportunities"
            )

        # 1. SCAN
        try:
            result = self.scanner.fetch_active_markets(limit=100)
            # Handle both sync and async scanners
            if asyncio.iscoroutine(result):
                markets = await result
            else:
                markets = result
            logger.info(f"Scanned {len(markets)} active markets")
        except Exception as e:
            logger.error(f"Scanner failed: {e}")
            return {"status": "error", "reason": f"scanner: {e}"}

        # Filter actionable (price between 10-90%)
        actionable = []
        market_lookup = {}  # market_id -> market data

        skipped_category = 0
        skipped_too_slow = 0
        skipped_no_resolution = 0
        skipped_quarantined = 0
        for m in markets:
            try:
                # Quarantine filter: skip markets with recent CLOB errors
                if self.quarantine is not None:
                    mid = m.get("id", m.get("condition_id", ""))
                    if mid and self.quarantine.is_quarantined(mid):
                        skipped_quarantined += 1
                        continue

                # Category filter: skip sports/crypto where LLM has low edge
                question = m.get("question", "")
                if is_low_edge_category(question):
                    skipped_category += 1
                    continue

                # Velocity filter: skip markets that resolve too slowly
                # NOTE: If resolution time is unknown, ALLOW the market through
                # with a default estimate. Rejecting unknowns killed all markets
                # because most Polymarket markets lack parseable endDate fields.
                if MAX_RESOLUTION_HOURS > 0:
                    res_hours = estimate_resolution_hours(m)
                    if res_hours is None:
                        # Default: assume 24h resolution for unknown markets
                        # This lets them through the filter while deprioritizing
                        # them in velocity scoring vs markets with known times.
                        res_hours = 24.0
                    if res_hours > MAX_RESOLUTION_HOURS:
                        skipped_too_slow += 1
                        continue
                    # Store for later use in velocity scoring
                    m["_resolution_hours"] = res_hours

                # Extract YES price — handle multiple formats
                yes_price = None

                # Method 1: Use scanner's extract_prices if available
                try:
                    prices = self.scanner.extract_prices(m)
                    yes_price = prices.get("YES", prices.get("yes", None))
                except Exception:
                    pass

                # Method 2: Parse outcomePrices directly (Gamma API format)
                if yes_price is None:
                    raw_prices = m.get("outcomePrices", "")
                    if isinstance(raw_prices, str) and raw_prices:
                        try:
                            parsed = json.loads(raw_prices)
                            if isinstance(parsed, list) and len(parsed) >= 1:
                                yes_price = float(parsed[0])
                        except (json.JSONDecodeError, ValueError):
                            pass
                    elif isinstance(raw_prices, list) and len(raw_prices) >= 1:
                        yes_price = float(raw_prices[0])

                # Method 3: Check for 'price' or 'yes_price' fields
                if yes_price is None:
                    yes_price = m.get("price", m.get("yes_price", None))
                    if yes_price is not None:
                        yes_price = float(yes_price)

                if yes_price is None:
                    continue

                if not (0.10 <= yes_price <= 0.90):
                    continue

                # Extract token IDs
                token_ids = []
                try:
                    token_ids = self.scanner.extract_token_ids(m)
                except Exception:
                    pass

                if not token_ids:
                    raw_tokens = m.get("clobTokenIds", "")
                    if isinstance(raw_tokens, str) and raw_tokens:
                        try:
                            token_ids = json.loads(raw_tokens)
                        except json.JSONDecodeError:
                            pass
                    elif isinstance(raw_tokens, list):
                        token_ids = raw_tokens

                # Extract market ID
                market_id = m.get("id", m.get("condition_id", m.get("market_id", "")))

                if not market_id or not token_ids:
                    continue

                res_hours = m.get("_resolution_hours")
                actionable.append(m)
                market_lookup[market_id] = {
                    "question": m.get("question", ""),
                    "token_ids": token_ids,
                    "yes_price": yes_price,
                    "volume": float(m.get("volume", 0) or 0),
                    "liquidity": float(m.get("liquidity", 0) or 0),
                    "tags": m.get("tags", []) or [],
                    "resolution_hours": res_hours,
                }
            except Exception as e:
                logger.debug(f"Skip market: {e}")
                continue

        if skipped_quarantined:
            logger.info(f"Skipped {skipped_quarantined} quarantined markets (CLOB errors)")
        if skipped_category:
            logger.info(f"Skipped {skipped_category} low-edge-category markets (sports/crypto)")
        if skipped_too_slow or skipped_no_resolution:
            logger.info(
                f"Velocity filter: skipped {skipped_too_slow} too slow "
                f"(>{MAX_RESOLUTION_HOURS}h) + {skipped_no_resolution} unknown resolution"
            )
        logger.info(f"Found {len(actionable)} actionable markets (resolve within {MAX_RESOLUTION_HOURS}h)")

        # Register actionable market tokens with the trade stream
        if self.trade_stream:
            for m in actionable:
                mid = m.get("id", m.get("condition_id", ""))
                mdata = market_lookup.get(mid, {})
                for tid in mdata.get("token_ids", []):
                    self.trade_stream.add_token(tid)
            stream_status = self.trade_stream.get_status()
            latency = stream_status.get("latency", {}) if isinstance(stream_status.get("latency", {}), dict) else {}
            logger.info(
                "Trade stream status: mode=%s connected=%s fallback=%s reconnects=%s p99=%.2fms tokens=%s",
                stream_status.get("connection_mode", "unknown"),
                stream_status.get("connected", False),
                stream_status.get("fallback_active", False),
                stream_status.get("reconnect_count", 0),
                _safe_float(latency.get("processing_p99_ms"), 0.0),
                stream_status.get("tokens_tracked", 0),
            )

        # 2. ANALYZE with Claude (batch mode — matches VPS paper_trader)
        signals = []

        # Build batch for analyzer — skip markets we already hold
        markets_for_analysis = []
        active_position_slots = len(self.state.state["open_positions"]) + self.state.count_active_linked_baskets()
        for m in actionable[:20]:
            market_id = m.get("id", m.get("condition_id", ""))

            if self.state.has_position(market_id):
                continue

            if active_position_slots + len(markets_for_analysis) >= MAX_OPEN_POSITIONS:
                logger.info(f"Position limit reached ({MAX_OPEN_POSITIONS})")
                break

            if not self.state.check_exposure_limit():
                logger.info("Exposure limit reached")
                break

            mdata_lookup = market_lookup.get(market_id, {})
            markets_for_analysis.append({
                "market_id": str(market_id),
                "question": m.get("question", ""),
                "current_price": mdata_lookup.get("yes_price", 0.5),
            })

        if markets_for_analysis:
            analyzer_label = "ensemble" if self.ensemble_mode else "Claude"
            logger.info(f"Sending {len(markets_for_analysis)} markets to {analyzer_label} for analysis...")

            # Auto-discover analyzer methods
            analyzer_methods = [m for m in dir(self.analyzer) if not m.startswith('_')]

            results = []
            try:
                # Strategy 1: batch_analyze (local codebase — returns dicts)
                if hasattr(self.analyzer, 'batch_analyze'):
                    r = self.analyzer.batch_analyze(markets_for_analysis, delay_between=2.0)
                    if asyncio.iscoroutine(r):
                        r = await r
                    results = r

                # Strategy 2: analyze_market one at a time (proven to work on VPS)
                elif hasattr(self.analyzer, 'analyze_market'):
                    import inspect
                    sig = inspect.signature(self.analyzer.analyze_market)
                    params = list(sig.parameters.keys())

                    for mkt in markets_for_analysis:
                        try:
                            # Try various call signatures
                            if 'current_price' in params:
                                r = self.analyzer.analyze_market(
                                    question=mkt["question"],
                                    current_price=mkt["current_price"],
                                )
                            elif 'market_price' in params:
                                r = self.analyzer.analyze_market(
                                    question=mkt["question"],
                                    market_price=mkt["current_price"],
                                )
                            elif 'price' in params:
                                r = self.analyzer.analyze_market(
                                    question=mkt["question"],
                                    price=mkt["current_price"],
                                )
                            else:
                                # Just pass question, let it figure it out
                                r = self.analyzer.analyze_market(mkt["question"])

                            if asyncio.iscoroutine(r):
                                r = await r

                            # Convert AnalysisResult/dataclass to dict
                            if not isinstance(r, dict):
                                try:
                                    r = vars(r)
                                except TypeError:
                                    r = {k: getattr(r, k) for k in dir(r) if not k.startswith('_')}

                            r["market_id"] = mkt["market_id"]
                            r["question"] = mkt["question"]
                            results.append(r)

                            await asyncio.sleep(2.0)
                        except Exception as e:
                            logger.error(f"Single analysis failed: {e}")
                            continue

                # Strategy 3: generic analyze method
                elif hasattr(self.analyzer, 'analyze'):
                    for mkt in markets_for_analysis:
                        try:
                            r = self.analyzer.analyze(mkt["question"], mkt["current_price"])
                            if asyncio.iscoroutine(r):
                                r = await r
                            r["market_id"] = mkt["market_id"]
                            r["question"] = mkt["question"]
                            results.append(r)
                            await asyncio.sleep(2.0)
                        except Exception as e:
                            logger.error(f"Analyze failed: {e}")
                            continue

                else:
                    logger.error(f"No usable analyze method found! Available: {analyzer_methods}")

            except Exception as e:
                logger.error(f"Analysis failed: {e}", exc_info=True)

            # Process results into signals
            # Handle both LOCAL analyzer (returns dicts with mispriced/direction/edge)
            # and VPS analyzer (returns AnalysisResult with different field names)
            for r in results:
                mid = r.get("market_id", "")
                mdata_lookup = market_lookup.get(mid, {})
                if not mdata_lookup:
                    try:
                        mdata_lookup = market_lookup.get(int(mid), {})
                    except (ValueError, TypeError):
                        pass

                market_price = mdata_lookup.get("yes_price", 0.5)

                # Try format_result if available (VPS analyzer may need this)
                if hasattr(self.analyzer, 'format_result') and "mispriced" not in r:
                    try:
                        formatted = self.analyzer.format_result(r)
                        if isinstance(formatted, dict):
                            r.update(formatted)
                        elif isinstance(formatted, str):
                            logger.info(f"format_result returned string: {formatted[:100]}")
                    except Exception as e:
                        logger.debug(f"format_result failed: {e}")

                # If result doesn't have mispriced/direction/edge, compute them
                # using full calibration pipeline (Platt scaling + fees + thresholds)
                if "mispriced" not in r:
                    prob_fields = extract_probability_fields(r)
                    prob = prob_fields["raw_prob"]
                    already_calibrated = prob_fields["already_calibrated"]
                    if prob is None and prob_fields["calibrated_prob"] is not None:
                        prob = prob_fields["calibrated_prob"]

                    if prob is not None and market_price > 0:
                        # Classify category for fee calculation
                        question = r.get("question", "")
                        category = classify_market_category(question)

                        # Full calibrated signal: Platt + fees + thresholds
                        sig = compute_calibrated_signal(
                            prob,
                            market_price,
                            category,
                            already_calibrated=already_calibrated,
                            calibrate_fn=self.adaptive_platt.calibrate,
                        )
                        r.update(sig)

                        logger.info(
                            f"Calibrated signal: prob_in={prob:.3f} cal={sig['calibrated_prob']:.3f} "
                            f"market={market_price:.3f} edge={sig['edge']:.3f} "
                            f"fee={sig['taker_fee']:.4f} dir={sig['direction']} "
                            f"cat={category} mispriced={sig['mispriced']} "
                            f"already_calibrated={already_calibrated}"
                        )

                prob_fields = extract_probability_fields(r)
                raw_prob = prob_fields["raw_prob"]
                calibrated_prob = prob_fields["calibrated_prob"]
                execution_prob = prob_fields["execution_prob"]
                if execution_prob is None:
                    execution_prob = 0.5
                if raw_prob is None:
                    raw_prob = execution_prob
                if calibrated_prob is None:
                    calibrated_prob = execution_prob

                # Also handle case where "mispriced" key exists but uses different
                # truthy representations (string "True", 1, etc.)
                is_mispriced = r.get("mispriced", False)
                if isinstance(is_mispriced, str):
                    is_mispriced = is_mispriced.lower() in ("true", "yes", "1")

                # Map direction from various VPS formats
                direction = map_vps_signal_direction(r, market_price)

                if direction == "hold" or not is_mispriced:
                    continue

                edge = abs(_safe_float(r.get("edge", 0.0), 0.0))
                if edge < MIN_EDGE:
                    continue

                # Convert confidence string to float
                confidence = normalize_confidence(r.get("confidence", 0.5))

                # Get resolution hours for velocity scoring
                res_hours = mdata_lookup.get("resolution_hours")
                vel_score = velocity_score(edge, res_hours) if res_hours else 0.0

                # Ensemble metadata (if available)
                n_models = int(_safe_float(r.get("n_models", 1), 1))
                models_agree = r.get("models_agree", True)
                model_spread = _safe_float(r.get("model_spread", 0.0), 0.0)
                model_stddev = _safe_float(
                    r.get("disagreement", r.get("model_stddev", r.get("stdev", 0.0))),
                    0.0,
                )
                rag_used = r.get("search_context_used", False)
                agreement = _safe_float(
                    r.get("agreement"),
                    max(0.0, 1.0 - min(1.0, model_spread / 0.25)),
                )
                kelly_multiplier = _safe_float(
                    r.get("kelly_multiplier"),
                    disagreement_kelly_modifier(model_stddev),
                )
                disagreement_kelly_fraction = _safe_float(
                    r.get("disagreement_kelly_fraction"),
                    min(MAX_KELLY_FRACTION, max(0.0, MAX_KELLY_FRACTION * kelly_multiplier)),
                )
                counter_shift = _safe_float(r.get("counter_shift", 0.0), 0.0)
                counter_fragile = r.get("counter_fragile", False)
                if isinstance(counter_fragile, str):
                    counter_fragile = counter_fragile.lower() in ("true", "yes", "1")

                if n_models > 1:
                    logger.info(
                        f"  Ensemble: {n_models} models, spread={model_spread:.3f}, std={model_stddev:.3f}, "
                        f"agree={models_agree}, agreement={agreement:.3f}, "
                        f"kelly_mult={kelly_multiplier:.2f}, kelly_cap={disagreement_kelly_fraction:.4f}, "
                        f"counter_shift={counter_shift:.3f}, "
                        f"fragile={counter_fragile}, RAG={rag_used}"
                    )

                if n_models > 1 and agreement < ENSEMBLE_MIN_AGREEMENT:
                    logger.info(
                        f"  SKIP weak ensemble agreement: {agreement:.3f} "
                        f"< floor {ENSEMBLE_MIN_AGREEMENT:.3f} | "
                        f"{r.get('question', '')[:60]}"
                    )
                    continue

                if ENSEMBLE_SKIP_FRAGILE_CONVICTION and counter_fragile:
                    logger.info(
                        f"  SKIP fragile conviction (shift={counter_shift:.3f}) | "
                        f"{r.get('question', '')[:60]}"
                    )
                    continue

                signal_payload = {
                    "market_id": mid,
                    "question": r.get("question", ""),
                    "direction": direction,
                    "market_price": market_price,
                    "estimated_prob": execution_prob,
                    "raw_prob": raw_prob,
                    "calibrated_prob": calibrated_prob,
                    "edge": edge,
                    "confidence": confidence,
                    "reasoning": r.get("reasoning", ""),
                    "taker_fee": float(r.get("taker_fee", 0.0)),
                    "category": r.get("category", "unknown"),
                    "resolution_hours": res_hours,
                    "velocity_score": vel_score,
                    "n_models": n_models,
                    "model_spread": model_spread,
                    "model_stddev": model_stddev,
                    "disagreement": model_stddev,
                    "agreement": agreement,
                    "kelly_multiplier": kelly_multiplier,
                    "disagreement_kelly_fraction": disagreement_kelly_fraction,
                    "models_agree": bool(models_agree),
                    "search_context_used": bool(rag_used),
                    "counter_shift": counter_shift,
                    "counter_fragile": bool(counter_fragile),
                    "platt_mode": self.adaptive_platt.active_mode,
                    "platt_a": self.adaptive_platt.active_a,
                    "platt_b": self.adaptive_platt.active_b,
                }
                self._attach_microstructure_context(signal_payload, market_lookup)
                signals.append(signal_payload)

        # Tag LLM signals with source
        for s in signals:
            s.setdefault("source", "llm")
            attach_signal_source_metadata(s)

        # --- SIGNAL SOURCE #2: Smart Wallet Flow Detector ---
        wallet_signals = []
        if self.wallet_flow_available:
            try:
                wallet_signals = wallet_flow_get_signals()
                if wallet_signals:
                    logger.info(f"Wallet flow: {len(wallet_signals)} signals")
                    for ws in wallet_signals:
                        ws["source"] = "wallet_flow"
                        attach_signal_source_metadata(ws)
            except Exception as e:
                logger.warning(f"Wallet flow scan failed (non-fatal): {e}")

        # --- SIGNAL SOURCE #3: LMSR Bayesian Engine ---
        lmsr_signals = []
        if self.lmsr_engine is not None and actionable:
            try:
                lmsr_signals = self.lmsr_engine.get_signals(actionable)
                if lmsr_signals:
                    logger.info(f"LMSR engine: {len(lmsr_signals)} signals")
                    for ls in lmsr_signals:
                        attach_signal_source_metadata(ls)
            except Exception as e:
                logger.warning(f"LMSR scan failed (non-fatal): {e}")

        # --- SIGNAL SOURCE #4: Cross-Platform Arbitrage ---
        arb_signals = []
        if self.arb_available:
            try:
                arb_signals = arb_get_signals()
                if arb_signals:
                    logger.info(f"Cross-platform arb: {len(arb_signals)} signals")
                    for asig in arb_signals:
                        asig["source"] = "cross_platform_arb"
                        attach_signal_source_metadata(asig)
            except Exception as e:
                logger.warning(f"Cross-platform arb scan failed (non-fatal): {e}")

        # --- SIGNAL SOURCE #5: Lead-Lag Arbitrage Engine ---
        lead_lag_signals = []
        if self.lead_lag is not None and actionable:
            try:
                # Feed current prices to the lead-lag engine
                now = time.time()
                for m in actionable:
                    mid = m.get("id", m.get("condition_id", ""))
                    mdata = market_lookup.get(mid, {})
                    price = mdata.get("yes_price", 0.5)
                    question = mdata.get("question", "")
                    if mid and price:
                        self.lead_lag.update_price(mid, now, price, question)

                # Check for actionable signals from validated pairs
                ll_sigs = self.lead_lag.get_signals()
                for ll in ll_sigs:
                    follower_data = market_lookup.get(ll.follower_id, {})
                    if not follower_data:
                        continue

                    # Convert lead-lag signal to standard signal format
                    follower_price = follower_data.get("yes_price", 0.5)
                    direction = "buy_yes" if ll.expected_follower_move > 0 else "buy_no"
                    edge = abs(ll.expected_follower_move) * 0.5  # Conservative: 50% of expected move
                    edge = min(edge, 0.15)  # Cap at 15%

                    if edge >= MIN_EDGE:
                        lead_lag_signals.append({
                            "market_id": ll.follower_id,
                            "question": follower_data.get("question", ""),
                            "direction": direction,
                            "market_price": follower_price,
                            "estimated_prob": follower_price + (edge if direction == "buy_yes" else -edge),
                            "edge": edge,
                            "confidence": ll.confidence,
                            "reasoning": f"Lead-lag: {ll.leader_id[:12]} leads this market",
                            "taker_fee": 0.0,  # Maker only
                            "category": "lead_lag",
                            "resolution_hours": follower_data.get("resolution_hours"),
                            "velocity_score": velocity_score(edge, follower_data.get("resolution_hours")),
                            "source": "lead_lag",
                        })

                if lead_lag_signals:
                    logger.info(f"Lead-lag engine: {len(lead_lag_signals)} signals")
                    for lsig in lead_lag_signals:
                        attach_signal_source_metadata(lsig)
            except Exception as e:
                logger.warning(f"Lead-lag scan failed (non-fatal): {e}")

        # --- VPIN GATE: filter signals where flow is toxic ---
        if self.trade_stream:
            pre_vpin = len(signals)
            filtered_signals = []
            for s in signals:
                mid = s["market_id"]
                # Check all token IDs for this market
                mdata = market_lookup.get(mid, {})
                token_ids = mdata.get("token_ids", [])
                is_toxic = False
                for tid in token_ids:
                    if not self.trade_stream.should_quote(tid):
                        is_toxic = True
                        vpin_val = self.trade_stream.vpin.get_vpin(tid)
                        logger.info(
                            f"VPIN GATE: blocking {s['question'][:40]}... "
                            f"(VPIN={vpin_val:.3f}, toxic)"
                        )
                        break
                if not is_toxic:
                    filtered_signals.append(s)

            if pre_vpin > len(filtered_signals):
                logger.info(f"VPIN gate: blocked {pre_vpin - len(filtered_signals)} signals due to toxic flow")
            signals = filtered_signals

        # --- CONFIRMATION LAYER: blend all signal sources ---
        # Group all signals by market_id + direction
        from collections import defaultdict as _defaultdict
        signal_groups = _defaultdict(list)
        combinatorial_bypass_signals = []
        all_signals = (
            signals
            + wallet_signals
            + lmsr_signals
            + arb_signals
            + lead_lag_signals
            + combinatorial_signals
        )
        for s in all_signals:
            attach_signal_source_metadata(s)
            if is_combinatorial_signal(s):
                s["_confirmation"] = False
                s["_kelly_override"] = 0.0
                combinatorial_bypass_signals.append(s)
                continue
            key = (s["market_id"], s["direction"])
            signal_groups[key].append(s)

        # Apply confirmation logic
        confirmed_signals = []
        for (mid, direction), group in signal_groups.items():
            sources = set(s.get("source", "unknown") for s in group)
            n_sources = len(sources)

            # Pick the signal with the highest edge as the primary
            primary = max(group, key=lambda s: s.get("edge", 0))
            primary["source"] = "+".join(sorted(sources))
            primary["n_sources"] = n_sources

            # Confirmation boost: 2+ sources agree → higher confidence sizing
            res_hours = primary.get("resolution_hours")
            if n_sources >= 2:
                # Boosted: highest confidence, use quarter-Kelly even on fast markets
                primary["_kelly_override"] = MAX_KELLY_FRACTION
                primary["_confirmation"] = True
                logger.info(
                    f"  CONFIRMED ({n_sources} sources: {primary['source']}): "
                    f"{primary['question'][:50]} → {direction} edge={primary['edge']:.3f}"
                )
            elif "llm" in sources and res_hours and res_hours > 12:
                # LLM alone on slow market → standard quarter-Kelly
                primary["_kelly_override"] = KELLY_FRACTION
                primary["_confirmation"] = False
            elif "wallet_flow" in sources and res_hours and res_hours < 1:
                # Wallet flow alone on fast market → 1/16 Kelly
                primary["_kelly_override"] = 1.0 / 16.0
                primary["_confirmation"] = False
            elif "lead_lag" in sources:
                # Lead-lag alone → 1/8 Kelly (structural alpha, moderate sizing)
                primary["_kelly_override"] = 1.0 / 8.0
                primary["_confirmation"] = False
            elif "lmsr" in sources:
                # LMSR alone → 1/16 Kelly
                primary["_kelly_override"] = 1.0 / 16.0
                primary["_confirmation"] = False
            else:
                # Single source, default Kelly
                primary["_kelly_override"] = KELLY_FRACTION
                primary["_confirmation"] = False

            # Keep the base Kelly decision here; apply disagreement to final USD size.
            base_kelly = _safe_float(primary.get("_kelly_override", KELLY_FRACTION), KELLY_FRACTION)
            primary["_kelly_override"] = min(MAX_KELLY_FRACTION, max(0.0, base_kelly))

            confirmed_signals.append(primary)

        signals = confirmed_signals

        # Sort by velocity score (capital efficiency), not raw edge
        # Velocity = annualized edge / lockup time — faster resolution wins
        signals.sort(key=lambda s: s.get("velocity_score", 0), reverse=True)
        for s in signals[:5]:
            res_str = f"{s['resolution_hours']:.1f}h" if s.get('resolution_hours') else "?"
            src = s.get("source", "?")
            conf = " [CONFIRMED]" if s.get("_confirmation") else ""
            logger.info(
                f"  SIGNAL: {s['question'][:50]} | edge={s['edge']:.3f} "
                f"| res={res_str} | vel={s.get('velocity_score', 0):.0f} "
                f"| dir={s['direction']} | src={src}{conf}"
            )
        for s in combinatorial_bypass_signals[:5]:
            logger.info(
                "  COMBINATORIAL: %s | edge=%.3f | relation=%s | src=%s [%s]",
                s.get("question", "")[:50],
                _safe_float(s.get("edge"), 0.0),
                s.get("relation_type", ""),
                s.get("source_tag", s.get("source", "?")),
                s.get("confirmation_mode", "bypass"),
            )
        logger.info(
            f"Found {len(signals)} predictive signals + {len(combinatorial_bypass_signals)} combinatorial bypass signals "
            f"(LLM:{len([s for s in signals if 'llm' in s.get('source', '')])} "
            f"wallet:{len(wallet_signals)} lmsr:{len(lmsr_signals)} A6:{combinatorial_cycle['a6_detected']} B1:{combinatorial_cycle['b1_detected']})"
        )

        # 3. EXECUTE TRADES
        trades_placed = 0

        for signal in signals:
            if len(self.state.state["open_positions"]) + self.state.count_active_linked_baskets() >= MAX_OPEN_POSITIONS:
                logger.info(f"Composite position limit reached ({MAX_OPEN_POSITIONS})")
                break
            market_id = signal["market_id"]
            mdata = market_lookup.get(market_id)

            if not mdata:
                continue

            # Position sizing
            size_usd = kelly_size(
                edge=signal["edge"],
                market_price=signal["market_price"],
                direction=signal["direction"],
                bankroll=self.state.state["bankroll"],
                kelly_fraction_override=signal.get("_kelly_override"),
            )
            size_usd, disagreement_modifier = apply_disagreement_size_modifier(
                size_usd,
                _safe_float(signal.get("disagreement", signal.get("model_stddev")), None),
                modifier=_safe_float(signal.get("kelly_multiplier"), None),
            )
            if signal.get("disagreement", signal.get("model_stddev")) is not None:
                logger.info(
                    "Disagreement: %.3f, Kelly modifier: %.2f, final size: $%.2f",
                    _safe_float(signal.get("disagreement", signal.get("model_stddev")), 0.0),
                    disagreement_modifier,
                    size_usd,
                )

            if size_usd <= 0:
                logger.info(f"  SKIP (size=0): {signal['question'][:50]}...")
                continue

            # Determine token and price
            if signal["direction"] == "buy_yes":
                token_id = mdata["token_ids"][0]  # YES token
                price = signal["market_price"]
                side = "BUY"
            elif signal["direction"] == "buy_no":
                token_id = mdata["token_ids"][1] if len(mdata["token_ids"]) > 1 else mdata["token_ids"][0]
                price = 1.0 - signal["market_price"]  # NO token price
                side = "BUY"
            else:
                continue

            # Calculate shares
            if price <= 0 or price >= 1:
                continue
            shares = size_usd / price

            category = classify_market_category(signal.get("question", ""))
            mode_tag = "PAPER" if self.paper_mode else "LIVE"

            logger.info(
                f"  [{mode_tag}] {signal['direction']} ${size_usd:.2f} "
                f"@ {price:.3f} | edge={signal['edge']:.1%} | "
                f"cat={category} | {signal['question'][:50]}..."
            )

            trade_record = build_trade_record(
                signal,
                market_id=market_id,
                category=category,
                entry_price=price,
                position_size_usd=size_usd,
                token_id=token_id,
            )

            if self.paper_mode:
                # ---- PAPER TRADING: simulate locally ----
                paper_order_id = f"paper-{uuid.uuid4().hex[:8]}"
                trade_record["order_id"] = paper_order_id

                # Log to SQLite
                trade_id = self.db.log_trade(trade_record)

                # Multi-bankroll simulation
                self.multi_sim.simulate_trade(signal, trade_id)

                # Record in state tracker
                self.state.record_trade(
                    market_id=market_id,
                    question=signal["question"],
                    direction=signal["direction"],
                    price=price,
                    size_usd=size_usd,
                    edge=signal["edge"],
                    confidence=signal["confidence"],
                    order_id=paper_order_id,
                )

                logger.info(f"  PAPER TRADE LOGGED: {paper_order_id} (db: {trade_id})")

                try:
                    src = signal.get('source', 'llm')
                    conf_tag = " [CONFIRMED]" if signal.get('_confirmation') else ""
                    await self.notifier.send_message(
                        f"JJ PAPER TRADE{conf_tag}\n"
                        f"{signal['direction'].upper()} ${size_usd:.2f}\n"
                        f"{signal['question'][:60]}\n"
                        f"Edge: {signal['edge']:.1%} | Price: {price:.3f}\n"
                        f"Source: {src} | Cat: {category}\n"
                        f"ID: {paper_order_id}"
                    )
                except Exception:
                    pass

                trades_placed += 1

            else:
                # ---- LIVE TRADING: post to CLOB ----
                # DISPATCH #75 FIX: ALL orders must be post-only (maker).
                # At $347 capital, taker fees (up to 1.56% at the money)
                # are mathematically fatal. Maker orders = 0% fee + rebate.
                # Previously only crypto/sports were post-only. Now universal.
                use_post_only = True

                try:
                    order_args = OrderArgs(
                        token_id=token_id,
                        price=round(price, 2),
                        size=round(shares, 2),
                        side=BUY,
                    )
                    signed_order = self.clob.create_order(order_args)
                    result = self.clob.post_order(
                        signed_order, OrderType.GTC,
                        post_only=use_post_only,
                    )

                    order_id = ""
                    if isinstance(result, dict):
                        order_id = result.get("orderID", result.get("id", ""))
                        success = not result.get("error")
                    else:
                        success = bool(result)

                    if success:
                        logger.info(f"  ORDER PLACED: {order_id}")
                        trade_record["order_id"] = order_id
                        trade_id = self.db.log_trade(trade_record)
                        self.multi_sim.simulate_trade(signal, trade_id)

                        self.state.record_trade(
                            market_id=market_id,
                            question=signal["question"],
                            direction=signal["direction"],
                            price=price,
                            size_usd=size_usd,
                            edge=signal["edge"],
                            confidence=signal["confidence"],
                            order_id=order_id,
                        )

                        try:
                            res_h = signal.get('resolution_hours')
                            res_str = f"{res_h:.1f}h" if res_h else "?"
                            vel = signal.get('velocity_score', 0)
                            src = signal.get('source', 'llm')
                            conf_tag = " [CONFIRMED]" if signal.get('_confirmation') else ""
                            await self.notifier.send_message(
                                f"JJ LIVE TRADE{conf_tag}\n"
                                f"{signal['direction'].upper()} ${size_usd:.2f}\n"
                                f"{signal['question'][:60]}\n"
                                f"Edge: {signal['edge']:.1%} | Price: {price:.3f}\n"
                                f"Resolves: {res_str} | Velocity: {vel:.0f}\n"
                                f"Source: {src} | Cat: {category} | Fee: {signal['taker_fee']:.4f}\n"
                                f"Order: {order_id[:16]}..."
                            )
                        except Exception:
                            pass

                        trades_placed += 1
                    else:
                        err_msg = result.get("error", str(result)) if isinstance(result, dict) else str(result)
                        logger.warning(f"  ORDER FAILED: {err_msg}")

                except Exception as e:
                    logger.error(f"  ORDER ERROR: {e}")
                    try:
                        await self.notifier.send_error(str(e), context="place_order")
                    except Exception:
                        pass

            # Small delay between orders
            await asyncio.sleep(0.5)

        # Update cycle count
        self.state.state["cycles_completed"] = cycle_num
        self.state.save()

        elapsed = time.time() - cycle_start
        summary = {
            "status": "ok",
            "cycle": cycle_num,
            "scanned": len(markets),
            "filtered_category": skipped_category,
            "filtered_too_slow": skipped_too_slow,
            "filtered_no_resolution": skipped_no_resolution,
            "analyzed": len(markets_for_analysis) if markets_for_analysis else 0,
            "actionable": len(actionable),
            "signals": len(signals) + len(combinatorial_bypass_signals),
            "predictive_signals": len(signals),
            "combinatorial_signals": len(combinatorial_bypass_signals),
            "trades_placed": trades_placed,
            "open_positions": len(self.state.state["open_positions"]),
            "linked_baskets": self.state.count_active_linked_baskets(),
            "arb_budget_in_use_usd": self.state.get_arb_budget_in_use_usd(),
            "bankroll": self.state.state["bankroll"],
            "max_resolution_hours": MAX_RESOLUTION_HOURS,
            "platt_mode": self.adaptive_platt.active_mode,
            "daily_pnl": self.state.state["daily_pnl"],
            "combinatorial": combinatorial_cycle,
            "elapsed_seconds": round(elapsed, 1),
        }

        # Log cycle to database
        self.db.log_cycle(summary)

        # Write intel snapshot for SystemIntel.docx generation
        self._write_intel_snapshot(
            summary,
            signals,
            actionable,
            combinatorial_signals=combinatorial_bypass_signals,
        )

        mode_tag = "PAPER" if self.paper_mode else "LIVE"
        logger.info(
            f"=== JJ [{mode_tag}] Cycle {cycle_num} complete in {elapsed:.1f}s | "
            f"scanned={len(markets)} cat_skip={skipped_category} "
            f"slow_skip={skipped_too_slow} no_res={skipped_no_resolution} "
            f"actionable={len(actionable)} predictive={len(signals)} combinatorial={len(combinatorial_bypass_signals)} "
            f"trades={trades_placed} (max_res={MAX_RESOLUTION_HOURS}h "
            f"platt={self.adaptive_platt.active_mode}) ==="
        )

        return summary

    def _write_intel_snapshot(
        self,
        summary: dict,
        signals: list,
        actionable: list,
        combinatorial_signals: list | None = None,
    ):
        """Write a JSON intel snapshot for SystemIntel.docx generation.

        Captures per-cycle intelligence: what the bot saw, what it traded,
        and what patterns emerged. Accumulates a rolling window of recent
        cycles for trend analysis.
        """
        try:
            snapshot_path = Path("data/intel_snapshot.json")
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)

            # Load existing snapshot (accumulate rolling window)
            existing = {}
            if snapshot_path.exists():
                try:
                    with open(snapshot_path) as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    existing = {}

            # Current cycle intel
            now = datetime.now(timezone.utc).isoformat()
            cycle_intel = {
                "timestamp": now,
                "cycle": summary.get("cycle", 0),
                "markets_scanned": summary.get("scanned", 0),
                "markets_actionable": summary.get("actionable", 0),
                "signals_generated": summary.get("signals", 0),
                "predictive_signals": summary.get("predictive_signals", 0),
                "combinatorial_signals": summary.get("combinatorial_signals", 0),
                "trades_placed": summary.get("trades_placed", 0),
                "bankroll": summary.get("bankroll", 0),
                "daily_pnl": summary.get("daily_pnl", 0),
                "open_positions": summary.get("open_positions", 0),
                "linked_baskets": summary.get("linked_baskets", 0),
            }

            # Accumulate signal details (last 100 signals for pattern detection)
            signal_records = existing.get("recent_signals", [])
            for sig in signals:
                if isinstance(sig, dict):
                    signal_records.append({
                        "timestamp": now,
                        "market_id": sig.get("market_id", ""),
                        "question": (sig.get("question", ""))[:80],
                        "direction": sig.get("direction", ""),
                        "edge": sig.get("edge", 0),
                        "calibrated_prob": sig.get("calibrated_prob", 0),
                        "category": sig.get("category", "unknown"),
                        "confidence": sig.get("confidence", ""),
                    })
            for sig in combinatorial_signals or []:
                if isinstance(sig, dict):
                    signal_records.append({
                        "timestamp": now,
                        "market_id": sig.get("market_id", ""),
                        "question": (sig.get("question", ""))[:80],
                        "direction": sig.get("direction", ""),
                        "edge": sig.get("edge", 0),
                        "category": sig.get("source_tag", sig.get("source", "unknown")),
                        "confidence": sig.get("confidence", ""),
                        "relation_type": sig.get("relation_type", ""),
                    })
            signal_records = signal_records[-200:]  # Keep last 200

            # Accumulate cycle summaries (last 100 cycles)
            cycle_history = existing.get("cycle_history", [])
            cycle_history.append(cycle_intel)
            cycle_history = cycle_history[-100:]

            # Category frequency tracking
            cat_freq = existing.get("category_frequency", {})
            for sig in signals:
                if isinstance(sig, dict):
                    cat = sig.get("category", "unknown")
                    cat_freq[cat] = cat_freq.get(cat, 0) + 1

            # Write snapshot
            snapshot = {
                "last_updated": now,
                "total_cycles": self.state.state.get("cycles_completed", 0),
                "total_signals": self.state.state.get("total_signals", 0),
                "signals_by_confidence": self.state.state.get("signals_by_confidence", {}),
                "current_bankroll": summary.get("bankroll", 0),
                "current_daily_pnl": summary.get("daily_pnl", 0),
                "open_positions": summary.get("open_positions", 0),
                "linked_baskets": summary.get("linked_baskets", 0),
                "combinatorial": summary.get("combinatorial", {}),
                "cycle_history": cycle_history,
                "recent_signals": signal_records,
                "category_frequency": cat_freq,
                "system_params": {
                    "max_position_usd": MAX_POSITION_USD,
                    "max_daily_loss_usd": MAX_DAILY_LOSS_USD,
                    "kelly_fraction": KELLY_FRACTION,
                    "max_kelly_fraction": MAX_KELLY_FRACTION,
                    "max_resolution_hours": MAX_RESOLUTION_HOURS,
                    "yes_threshold": YES_THRESHOLD,
                    "no_threshold": NO_THRESHOLD,
                    "adaptive_platt_enabled": ADAPTIVE_PLATT_ENABLED,
                    "adaptive_platt_mode": self.adaptive_platt.active_mode,
                    "adaptive_platt_a": self.adaptive_platt.active_a,
                    "adaptive_platt_b": self.adaptive_platt.active_b,
                    "ensemble_min_agreement": ENSEMBLE_MIN_AGREEMENT,
                    "ensemble_skip_fragile_conviction": ENSEMBLE_SKIP_FRAGILE_CONVICTION,
                    "paper_mode": self.paper_mode,
                },
                "combinatorial_params": {
                    "enabled": bool(self.combinatorial_cfg and self.combinatorial_cfg.any_enabled()),
                    "a6_shadow": bool(self.combinatorial_cfg and self.combinatorial_cfg.enable_a6_shadow),
                    "a6_live": bool(self.combinatorial_cfg and self.combinatorial_cfg.enable_a6_live),
                    "b1_shadow": bool(self.combinatorial_cfg and self.combinatorial_cfg.enable_b1_shadow),
                    "b1_live": bool(self.combinatorial_cfg and self.combinatorial_cfg.enable_b1_live),
                    "max_leg_notional_usd": (
                        self.combinatorial_cfg.max_notional_per_leg_usd if self.combinatorial_cfg else None
                    ),
                    "arb_budget_usd": self.combinatorial_cfg.arb_budget_usd if self.combinatorial_cfg else None,
                    "merge_min_notional_usd": (
                        self.combinatorial_cfg.merge_min_notional_usd if self.combinatorial_cfg else None
                    ),
                },
            }

            with open(snapshot_path, "w") as f:
                json.dump(snapshot, f, indent=2)

        except Exception as e:
            logger.warning(f"Intel snapshot write failed: {e}")

    async def run_continuous(self):
        """Run JJ continuously (daemon mode)."""
        mode_tag = "PAPER" if self.paper_mode else "LIVE"
        logger.info(f"JJ {mode_tag} — Starting continuous mode")
        try:
            try:
                if self.ensemble_mode:
                    sources = [f"LLM Ensemble ({len(self.analyzer.models)} models + RAG)"]
                else:
                    sources = ["LLM (Claude-only)"]
                if self.lmsr_engine:
                    sources.append("LMSR")
                if self.wallet_flow_available:
                    sources.append("WalletFlow")
                if self.arb_available:
                    sources.append("CrossPlatformArb")
                if self.trade_stream:
                    sources.append("VPIN/OFI")
                if self.lead_lag:
                    sources.append("LeadLag")
                if self.combinatorial_cfg and self.combinatorial_cfg.enable_a6_shadow:
                    sources.append("A6-Shadow")
                if self.combinatorial_cfg and self.combinatorial_cfg.enable_b1_shadow:
                    sources.append("B1-Shadow")
                await self.notifier.send_message(
                    f"JJ {mode_tag} TRADING ONLINE\n"
                    f"Bankroll: ${self.state.state['bankroll']:.2f}\n"
                    f"Signal sources: {' + '.join(sources)}\n"
                    f"Max/trade: ${MAX_POSITION_USD}\n"
                    f"Kelly: {KELLY_FRACTION}\n"
                    f"Scan every {SCAN_INTERVAL}s\n"
                    f"Daily loss limit: ${MAX_DAILY_LOSS_USD}"
                )
            except Exception:
                pass

            if self.trade_stream:
                self._trade_stream_task = asyncio.create_task(self.trade_stream.start())
                logger.info("WebSocket trade stream started as background task")

            while True:
                try:
                    summary = await self.run_cycle()

                    if summary.get("status") == "paused":
                        now = datetime.now(timezone.utc)
                        tomorrow = (now + timedelta(days=1)).replace(
                            hour=0, minute=5, second=0, microsecond=0
                        )
                        sleep_seconds = (tomorrow - now).total_seconds()
                        logger.info(f"Paused — sleeping {sleep_seconds:.0f}s until tomorrow")
                        await asyncio.sleep(sleep_seconds)
                    else:
                        logger.info(f"Sleeping {SCAN_INTERVAL}s...")
                        await asyncio.sleep(SCAN_INTERVAL)

                except KeyboardInterrupt:
                    logger.info("JJ shutting down (KeyboardInterrupt)")
                    break
                except Exception as e:
                    logger.error(f"Cycle error: {e}", exc_info=True)
                    try:
                        await self.notifier.send_error(str(e), context="cycle_error")
                    except Exception:
                        pass
                    await asyncio.sleep(60)
        finally:
            if self.a6_shadow_scanner is not None:
                try:
                    self.a6_shadow_scanner.close()
                except Exception:
                    pass

    async def show_status(self):
        """Print current JJ state with database stats."""
        s = self.state.state
        db_stats = self.db.get_stats()
        multi = self.multi_sim.get_summary()
        combinatorial_summary = self.db.get_combinatorial_summary(hours=24 * 14)

        mode_str = "PAPER" if self.paper_mode else "LIVE"
        print(f"\n{'='*50}")
        print(f"JJ {mode_str} TRADING STATUS")
        print(f"{'='*50}")
        print(f"Bankroll:         ${s['bankroll']:.2f}")
        print(f"Total deployed:   ${s['total_deployed']:.2f}")
        print(f"Total P&L:        ${s['total_pnl']:.2f}")
        print(f"Daily P&L:        ${s['daily_pnl']:.2f}")
        print(f"Total trades:     {s['total_trades']}")
        print(f"Trades today:     {s['trades_today']}")
        print(f"Open positions:   {len(s['open_positions'])}")
        print(f"Linked baskets:   {self.state.count_active_linked_baskets()}")
        print(f"Cycles completed: {s['cycles_completed']}")
        print(f"Veterans fund:    ${s['veterans_allocation']:.2f}")
        print(f"Started:          {s['started_at']}")

        print(f"\nDatabase Stats:")
        print(f"  Total trades (DB): {db_stats['total_trades']}")
        print(f"  Resolved:          {db_stats['resolved']}")
        print(f"  Unresolved:        {db_stats['unresolved']}")
        print(f"  Wins:              {db_stats['wins']}")
        print(f"  Losses:            {db_stats['losses']}")
        print(f"  Win rate:          {db_stats['win_rate']:.1%}")
        print(f"  Total P&L (DB):    ${db_stats['total_pnl']:.2f}")
        if db_stats['brier_score'] is not None:
            print(f"  Brier score:       {db_stats['brier_score']:.4f}")

        if multi:
            print(f"\nMulti-Bankroll Simulation:")
            for level in sorted(multi.keys()):
                data = multi[level]
                print(f"  ${level:>7,}: bankroll=${data['bankroll']:,.2f} "
                      f"pnl=${data['pnl']:,.2f} trades={data['trades']}")

        print(f"\nCombinatorial Summary (14d):")
        print(f"  Active baskets:    {combinatorial_summary['active_baskets']}")
        print(f"  Arb budget in use: ${combinatorial_summary['arb_budget_in_use_usd']:.2f}")
        for lane in ("a6", "b1"):
            metrics = combinatorial_summary["lanes"].get(lane, {})
            print(
                f"  {lane.upper()}: detected={metrics.get('detected', 0)} "
                f"shadow={metrics.get('shadow_logged', 0)} "
                f"blocked={metrics.get('blocked', 0)} "
                f"capture={metrics.get('avg_capture_rate') if metrics.get('avg_capture_rate') is not None else 'n/a'}"
            )

        if s["open_positions"]:
            print(f"\nOpen Positions:")
            for mid, pos in list(s["open_positions"].items())[:10]:
                print(f"  {pos['direction']:8s} ${pos['size_usd']:6.2f} "
                      f"@ {pos['entry_price']:.3f} | "
                      f"edge={pos['edge']:.1%} | "
                      f"{pos['question'][:50]}...")

        if s["trade_log"]:
            print(f"\nLast 5 trades:")
            for t in s["trade_log"][-5:]:
                print(f"  [{t['timestamp'][:19]}] {t['direction']:8s} "
                      f"${t['size_usd']:6.2f} | {t['question'][:50]}...")

        print(f"{'='*50}\n")


# ---------------------------------------------------------------------------
# Resolution Tracker — checks resolved markets and marks trades won/lost
# ---------------------------------------------------------------------------
def run_resolution_tracker():
    """Check for resolved markets and update trade outcomes.

    Run as: python jj_live.py --resolve
    Or via cron every 15 minutes.
    """
    import requests as _req

    db = TradeDatabase()
    unresolved = db.get_unresolved_trades()

    if not unresolved:
        print("No unresolved trades to check.")
        return

    print(f"Checking {len(unresolved)} unresolved trades...")

    # Batch fetch resolved markets from Gamma API
    market_ids = list(set(t["market_id"] for t in unresolved))

    resolved_count = 0
    for market_id in market_ids:
        try:
            resp = _req.get(
                f"https://gamma-api.polymarket.com/markets/{market_id}",
                timeout=10,
            )
            if resp.status_code != 200:
                continue

            mkt = resp.json()
            is_closed = mkt.get("closed", False)
            if not is_closed:
                continue

            # Get resolution: outcomePrices shows final prices
            outcome_prices = mkt.get("outcomePrices", "")
            if isinstance(outcome_prices, str) and outcome_prices:
                try:
                    prices = json.loads(outcome_prices)
                except json.JSONDecodeError:
                    continue
            elif isinstance(outcome_prices, list):
                prices = outcome_prices
            else:
                continue

            if not prices:
                continue

            yes_resolved = float(prices[0])  # 1.0 = YES won, 0.0 = NO won

            # Resolve all trades on this market
            for trade in unresolved:
                if trade["market_id"] != market_id:
                    continue

                direction = trade["direction"]
                if direction == "buy_yes":
                    won = yes_resolved >= 0.99
                elif direction == "buy_no":
                    won = yes_resolved <= 0.01
                else:
                    continue

                pnl = db.resolve_trade(trade["id"], won, yes_resolved)
                outcome = "WON" if won else "LOST"
                print(f"  [{outcome}] {trade['question'][:60]} | P&L: ${pnl:.2f}")
                resolved_count += 1

        except Exception as e:
            logger.debug(f"Resolution check failed for {market_id}: {e}")
            continue

        time.sleep(0.3)  # Rate limiting

    # Sync resolved positions to jj_state.json so the main loop knows
    # these slots are free.  This is critical — without it, the bot
    # hits MAX_OPEN_POSITIONS and stops trading.
    if resolved_count > 0:
        try:
            state = JJState()
            synced = state.sync_resolved_positions(db)
            print(f"Synced {synced} resolved positions from state file "
                  f"(open: {len(state.state['open_positions'])} remaining)")
        except Exception as e:
            print(f"Warning: state sync failed: {e}")

    stats = db.get_stats()
    combinatorial_summary = db.get_combinatorial_summary(hours=24 * 14)
    print(f"\nResolved {resolved_count} trades this run.")
    print(f"Overall: {stats['wins']}W / {stats['losses']}L "
          f"({stats['win_rate']:.1%}) | P&L: ${stats['total_pnl']:.2f}")
    if stats['brier_score'] is not None:
        print(f"Brier score: {stats['brier_score']:.4f}")

    db.close()


# ---------------------------------------------------------------------------
# Daily Report Generator
# ---------------------------------------------------------------------------
async def generate_daily_report():
    """Generate and send daily trading summary.

    Run as: python jj_live.py --daily-report
    """
    db = TradeDatabase()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    c = db.conn.cursor()

    # Trades placed today
    trades_today = c.execute(
        "SELECT COUNT(*) FROM trades WHERE timestamp LIKE ?",
        (f"{today}%",)
    ).fetchone()[0]

    # Trades resolved today
    resolved_today = c.execute(
        "SELECT COUNT(*) FROM trades WHERE resolved_at LIKE ?",
        (f"{today}%",)
    ).fetchone()[0]

    wins_today = c.execute(
        "SELECT COUNT(*) FROM trades WHERE resolved_at LIKE ? AND outcome = 'won'",
        (f"{today}%",)
    ).fetchone()[0]

    losses_today = c.execute(
        "SELECT COUNT(*) FROM trades WHERE resolved_at LIKE ? AND outcome = 'lost'",
        (f"{today}%",)
    ).fetchone()[0]

    daily_pnl = c.execute(
        "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE resolved_at LIKE ?",
        (f"{today}%",)
    ).fetchone()[0]

    # Cumulative stats
    stats = db.get_stats()

    # Best/worst trade today
    best = c.execute(
        "SELECT question, pnl FROM trades WHERE resolved_at LIKE ? AND pnl IS NOT NULL ORDER BY pnl DESC LIMIT 1",
        (f"{today}%",)
    ).fetchone()

    worst = c.execute(
        "SELECT question, pnl FROM trades WHERE resolved_at LIKE ? AND pnl IS NOT NULL ORDER BY pnl ASC LIMIT 1",
        (f"{today}%",)
    ).fetchone()

    # Cycles today
    cycles_today = c.execute(
        "SELECT COUNT(*) FROM cycles WHERE timestamp LIKE ?",
        (f"{today}%",)
    ).fetchone()[0]

    # Unresolved positions
    unresolved = stats["unresolved"]

    # Multi-bankroll state
    multi_sim = MultiBankrollSimulator(db)
    multi = multi_sim.get_summary()

    # Build report
    report_lines = [
        f"JJ DAILY REPORT - {today}",
        f"{'=' * 40}",
        f"",
        f"Cycles run: {cycles_today}",
        f"Trades placed: {trades_today}",
        f"Trades resolved: {resolved_today}",
        f"  Wins: {wins_today} | Losses: {losses_today}",
        f"  Win rate: {wins_today / resolved_today:.0%}" if resolved_today > 0 else "  Win rate: N/A",
        f"",
        f"Daily P&L: ${daily_pnl:+.2f}",
        f"Cumulative P&L: ${stats['total_pnl']:+.2f}",
        f"Open positions: {unresolved}",
        f"Linked baskets: {combinatorial_summary['active_baskets']}",
    ]

    if stats['brier_score'] is not None:
        report_lines.append(f"Brier score: {stats['brier_score']:.4f}")

    if best:
        report_lines.append(f"\nBest trade: ${best[1]:+.2f} | {best[0][:50]}")
    if worst:
        report_lines.append(f"Worst trade: ${worst[1]:+.2f} | {worst[0][:50]}")

    report_lines.append(f"\nMulti-Bankroll Simulation:")
    for level in sorted(multi.keys()):
        data = multi[level]
        report_lines.append(
            f"  ${level:>7,}: bankroll=${data['bankroll']:,.2f} "
            f"pnl=${data['pnl']:,.2f} trades={data['trades']}"
        )

    report_lines.append(f"\nCombinatorial Summary (14d):")
    report_lines.append(
        f"  Active baskets: {combinatorial_summary['active_baskets']} | "
        f"Arb budget in use: ${combinatorial_summary['arb_budget_in_use_usd']:.2f}"
    )
    for lane in ("a6", "b1"):
        metrics = combinatorial_summary["lanes"].get(lane, {})
        capture = metrics.get("avg_capture_rate")
        capture_str = f"{capture:.1%}" if isinstance(capture, (int, float)) else "n/a"
        report_lines.append(
            f"  {lane.upper()}: detected={metrics.get('detected', 0)} "
            f"shadow={metrics.get('shadow_logged', 0)} "
            f"blocked={metrics.get('blocked', 0)} "
            f"capture={capture_str}"
        )

    report_text = "\n".join(report_lines)
    print(report_text)

    # Save to markdown file
    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"{today}.md"
    with open(report_file, "w") as f:
        f.write(f"# {report_lines[0]}\n\n")
        f.write("```\n")
        f.write(report_text)
        f.write("\n```\n")
    print(f"\nReport saved to {report_file}")

    # Send via Telegram
    from dotenv import load_dotenv as _ld
    _ld()
    try:
        from src.telegram import TelegramBot
        bot = TelegramBot()
        if bot.enabled:
            bot.send(report_text, parse_mode="")
            print("Report sent via Telegram")
    except Exception as e:
        print(f"Telegram send failed: {e}")

    # Save to daily_reports table
    c.execute("""
        INSERT OR REPLACE INTO daily_reports
            (date, trades_placed, trades_resolved, wins, losses,
             daily_pnl, cumulative_pnl, brier_score, report_sent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (today, trades_today, resolved_today, wins_today, losses_today,
          daily_pnl, stats['total_pnl'], stats['brier_score']))
    db.conn.commit()
    db.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="JJ Live Trading System")
    parser.add_argument("--continuous", action="store_true",
                        help="Run continuously (daemon mode)")
    parser.add_argument("--status", action="store_true",
                        help="Show current trading state")
    parser.add_argument("--resolve", action="store_true",
                        help="Check resolved markets and update trade outcomes")
    parser.add_argument("--daily-report", action="store_true",
                        help="Generate and send daily report")
    parser.add_argument("--sync", action="store_true",
                        help="Sync resolved positions from DB to state file")
    args = parser.parse_args()

    if args.sync:
        db = TradeDatabase()
        state = JJState()
        before = len(state.state["open_positions"])
        synced = state.sync_resolved_positions(db)
        after = len(state.state["open_positions"])
        print(f"Synced: {synced} positions cleared ({before} → {after} open)")
        stats = db.get_stats()
        print(f"DB: {stats['total_trades']} trades, {stats['resolved']} resolved, "
              f"{stats['unresolved']} unresolved")
        db.close()
    elif args.resolve:
        run_resolution_tracker()
    elif args.daily_report:
        asyncio.run(generate_daily_report())
    else:
        jj = JJLive()

        if args.status:
            asyncio.run(jj.show_status())
        elif args.continuous:
            asyncio.run(jj.run_continuous())
        else:
            # Single cycle (test mode)
            summary = asyncio.run(jj.run_cycle())
            print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJJ terminated.")
        sys.exit(0)
