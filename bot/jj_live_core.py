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
import contextlib
import logging
import argparse
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Mapping

import httpx
import numpy as np

try:
    from bot import jj_live_signal_sources as _signal_source_helpers
except ImportError:
    import jj_live_signal_sources as _signal_source_helpers  # type: ignore
try:
    from bot import jj_live_runtime_settings as _runtime_settings
except ImportError:
    import jj_live_runtime_settings as _runtime_settings  # type: ignore
try:
    from bot.kalshi_auth import load_kalshi_credentials
except ImportError:
    from kalshi_auth import load_kalshi_credentials  # type: ignore

# Auto-load .env
from dotenv import load_dotenv
load_dotenv()

try:
    from bot import elastic_client
except ImportError:
    import elastic_client  # type: ignore

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
try:
    from bot.runtime_profile import RuntimeProfileBundle, activate_runtime_profile_env
except ImportError:
    from runtime_profile import RuntimeProfileBundle, activate_runtime_profile_env  # type: ignore

try:
    from bot.polymarket_clob import build_authenticated_clob_client, parse_signature_type
except ImportError:
    from polymarket_clob import build_authenticated_clob_client, parse_signature_type  # type: ignore

_ACTIVE_RUNTIME_PROFILE = activate_runtime_profile_env()
try:
    from bot.health_monitor import HeartbeatWriter
except ImportError:
    from health_monitor import HeartbeatWriter  # type: ignore

try:
    from bot.apm_setup import apm_transaction, capture_span, get_apm_runtime, initialize_apm
    from bot.log_config import configure_logging, ecs_extra
    from bot.latency_tracker import track_latency
except Exception:
    try:
        from apm_setup import apm_transaction, capture_span, get_apm_runtime, initialize_apm  # type: ignore
        from log_config import configure_logging, ecs_extra  # type: ignore
        from latency_tracker import track_latency  # type: ignore
    except Exception:
        class _NoopAPMRuntime:
            def set_labels(self, *args, **kwargs):
                return None

            def set_context(self, *args, **kwargs):
                return None

            def record_metric(self, *args, **kwargs):
                return None

            def capture_metric(self, *args, **kwargs):
                return None

        _NOOP_APM_RUNTIME = _NoopAPMRuntime()

        def initialize_apm():
            return _NOOP_APM_RUNTIME

        def get_apm_runtime():
            return _NOOP_APM_RUNTIME

        @contextlib.contextmanager
        def capture_span(*args, **kwargs):
            yield

        def apm_transaction(*args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def track_latency(*args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def configure_logging(*args, **kwargs):
            return None

        def ecs_extra(**kwargs):
            return kwargs

try:
    from bot.polymarket_runtime import (
        ClaudeAnalyzer,
        MarketScanner,
        TelegramBot,
        TelegramNotifier,
    )
except ImportError:
    from polymarket_runtime import (  # type: ignore
        ClaudeAnalyzer,
        MarketScanner,
        TelegramBot,
        TelegramNotifier,
    )

try:
    from bot.ensemble_estimator import EnsembleEstimator, LLMCostTracker
    from bot.disagreement_signal import confidence_multiplier_from_std
except ImportError:
    try:
        from ensemble_estimator import EnsembleEstimator, LLMCostTracker  # type: ignore
        from disagreement_signal import confidence_multiplier_from_std  # type: ignore
    except ImportError:
        EnsembleEstimator = None
        LLMCostTracker = None

        def confidence_multiplier_from_std(std_dev: float, model_count: int = 1) -> float:
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

# Signal sources #2 and #3
try:
    from bot.lmsr_engine import LMSREngine
except ImportError:
    try:
        from lmsr_engine import LMSREngine
    except ImportError:
        LMSREngine = None

try:
    from bot import wallet_flow_detector as wallet_flow_detector_module
except ImportError:
    try:
        import wallet_flow_detector as wallet_flow_detector_module  # type: ignore
    except ImportError:
        wallet_flow_detector_module = None

if wallet_flow_detector_module is not None:
    wallet_flow_get_signals = getattr(wallet_flow_detector_module, "get_signals_for_engine", None)
    wallet_flow_ensure_bootstrap = getattr(wallet_flow_detector_module, "ensure_bootstrap_artifacts", None)
    wallet_flow_get_bootstrap_status = getattr(wallet_flow_detector_module, "get_bootstrap_status", None)
else:
    wallet_flow_get_signals = None
    wallet_flow_ensure_bootstrap = None
    wallet_flow_get_bootstrap_status = None

try:
    from bot.cross_platform_arb import (
        get_signals_for_engine as arb_get_signals,
        get_signals_for_engine_async as arb_get_signals_async,
    )
except ImportError:
    try:
        from cross_platform_arb import (  # type: ignore
            get_signals_for_engine as arb_get_signals,
            get_signals_for_engine_async as arb_get_signals_async,
        )
    except ImportError:
        arb_get_signals = None
        arb_get_signals_async = None

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
    from bot.anomaly_consumer import ElasticAnomalyConsumer
except ImportError:
    try:
        from anomaly_consumer import ElasticAnomalyConsumer  # type: ignore
    except ImportError:
        ElasticAnomalyConsumer = None

try:
    from bot.combinatorial_integration import (
        CombinatorialConfig,
        CombinatorialSignalStore,
        attach_signal_source_metadata,
        canonical_source_key,
        evaluate_combinatorial_risk,
        is_combinatorial_signal,
        normalize_source_components,
    )
except ImportError:
    try:
        from combinatorial_integration import (  # type: ignore
            CombinatorialConfig,
            CombinatorialSignalStore,
            attach_signal_source_metadata,
            canonical_source_key,
            evaluate_combinatorial_risk,
            is_combinatorial_signal,
            normalize_source_components,
        )
    except ImportError:
        CombinatorialConfig = None
        CombinatorialSignalStore = None

        def attach_signal_source_metadata(signal: dict) -> dict:  # type: ignore[no-redef]
            return signal

        def is_combinatorial_signal(signal: dict) -> bool:  # type: ignore[no-redef]
            return False

        def canonical_source_key(source: str | None) -> str:  # type: ignore[no-redef]
            return str(source or "unknown")

        def normalize_source_components(raw_sources: Any) -> tuple[str, ...]:  # type: ignore[no-redef]
            if raw_sources is None:
                return ()
            if isinstance(raw_sources, (list, tuple, set)):
                return tuple(str(item) for item in raw_sources if str(item).strip())
            raw = str(raw_sources).strip()
            if not raw:
                return ()
            return tuple(part.strip() for part in raw.split("+") if part.strip())

        def evaluate_combinatorial_risk(*args, **kwargs):  # type: ignore[no-redef]
            return None

try:
    from bot.sum_violation_scanner import SumViolationScanner
except ImportError:
    try:
        from sum_violation_scanner import SumViolationScanner  # type: ignore
    except ImportError:
        SumViolationScanner = None

try:
    from bot.sum_violation_strategy import SumViolationStrategy
except ImportError:
    try:
        from sum_violation_strategy import SumViolationStrategy  # type: ignore
    except ImportError:
        SumViolationStrategy = None

try:
    from bot.adaptive_platt import PlattCalibrator as RuntimePlattCalibrator
except ImportError:
    try:
        from adaptive_platt import PlattCalibrator as RuntimePlattCalibrator  # type: ignore
    except ImportError:
        RuntimePlattCalibrator = None

try:
    from bot.fill_tracker import FillTracker, OrderFillEvent
except ImportError:
    try:
        from fill_tracker import FillTracker, OrderFillEvent  # type: ignore
    except ImportError:
        FillTracker = None
        OrderFillEvent = None

try:
    from execution.shadow_order_lifecycle import ShadowOrderLifecycle
except Exception:
    ShadowOrderLifecycle = None

try:
    from bot.position_merger import (
        LivePositionMerger,
        NodePolyMergerExecutor,
        RelayerMergeExecutor,
    )
except ImportError:
    try:
        from position_merger import (  # type: ignore
            LivePositionMerger,
            NodePolyMergerExecutor,
            RelayerMergeExecutor,
        )
    except ImportError:
        LivePositionMerger = None
        NodePolyMergerExecutor = None
        RelayerMergeExecutor = None

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
configure_logging(service_name="elastifund-bot", force=True)
initialize_apm()
logger = logging.getLogger("JJ")

# ---------------------------------------------------------------------------
# JJ Configuration
# ---------------------------------------------------------------------------
_CLOB_HARD_MIN_SHARES = 5.0  # Polymarket CLOB protocol minimum — not configurable
_CLOB_HARD_MIN_NOTIONAL_USD = 5.0  # Polymarket live orders must also be at least $5 notional

_DEFAULT_CATEGORY_PRIORITY = dict(_runtime_settings.DEFAULT_CATEGORY_PRIORITY)

MAX_POSITION_USD = 5.0
POLY_MIN_ORDER_SHARES = _CLOB_HARD_MIN_SHARES
MAX_DAILY_LOSS_USD = 10.0
MAX_EXPOSURE_PCT = 0.90
KELLY_FRACTION = 0.25
MAX_KELLY_FRACTION = 0.25
SCAN_INTERVAL = 180
ELASTIC_ORDERBOOK_SNAPSHOT_INTERVAL_SECONDS = 30.0
MAX_OPEN_POSITIONS = 30
MIN_EDGE = 0.05
INITIAL_BANKROLL = 250.0
MAX_RESOLUTION_HOURS = 48.0
ALLOWED_FAST_ASSETS: set[str] = set()
SIGNAL_DEDUP_TTL_SECONDS = 3600
PAPER_TRADING = True
MAX_ORDER_AGE_HOURS = 2.0
FILL_REPORT_HOURS = 24
AUTO_MERGE_POSITIONS = False
MIN_MERGE_FREED_USDC = 0.50
YES_THRESHOLD = 0.15
NO_THRESHOLD = 0.05
MIN_CATEGORY_PRIORITY = 1
CATEGORY_PRIORITY: dict[str, int] = dict(_DEFAULT_CATEGORY_PRIORITY)
RUNTIME_PROFILE: RuntimeProfileBundle | None = None
RUNTIME_PROFILE_NAME = "blocked_safe"
RUNTIME_EXECUTION_MODE = "blocked"
ALLOW_ORDER_SUBMISSION = False
ADAPTIVE_PLATT_ENABLED = False
ADAPTIVE_PLATT_MIN_SAMPLES = 30
ADAPTIVE_PLATT_WINDOW = 100
ADAPTIVE_PLATT_REFIT_SECONDS = 300
ADAPTIVE_PLATT_RUNTIME_VARIANT = "auto"
ADAPTIVE_PLATT_REPORT_PATH = "reports/platt_comparison.md"
ADAPTIVE_PLATT_REPORT_JSON_PATH = "reports/platt_comparison.json"
DISAGREEMENT_CONFIRMATION_STD = 0.05
DISAGREEMENT_SIGNAL_STD = 0.10
DISAGREEMENT_REDUCE_SIZE_STD = 0.15
DISAGREEMENT_WIDE_STD = 0.20
ENSEMBLE_DAILY_COST_CAP_USD = 2.0
ENSEMBLE_ENABLE_SECOND_CLAUDE = False
FAST_FLOW_RECENT_TRADES_LIMIT = 1000
FAST_FLOW_HYDRATION_MAX_MARKETS = 60
FAST_FLOW_WALLET_SIGNAL_STALE_SECONDS = 120.0
FAST_FLOW_WALLET_MIN_CONSENSUS_SHARE = 0.60
FAST_FLOW_WALLET_MIN_CONSENSUS_NOTIONAL_USD = 20.0
PM_HOURLY_CAMPAIGN_ENABLED = False
PM_HOURLY_NOTIONAL_CAP_USD = 50.0
PM_CAMPAIGN_MAX_RESOLUTION_HOURS = 24.0
PM_CAMPAIGN_WINDOW_SECONDS = 3600
PM_CAMPAIGN_DECISION_LOG_PATH = Path("reports/pm_campaign_decisions.jsonl")


_float_env = _runtime_settings.float_env
_bool_env = _runtime_settings.bool_env
_sum_violation_lane_enabled = _runtime_settings.sum_violation_lane_enabled


def _category_priority_from_env() -> dict[str, int]:
    return _runtime_settings.category_priority_from_env(_DEFAULT_CATEGORY_PRIORITY)


def _reload_runtime_settings(*, persist: bool = False) -> RuntimeProfileBundle:
    global RUNTIME_PROFILE
    global RUNTIME_PROFILE_NAME
    global RUNTIME_EXECUTION_MODE
    global ALLOW_ORDER_SUBMISSION
    global MAX_POSITION_USD
    global POLY_MIN_ORDER_SHARES
    global MAX_DAILY_LOSS_USD
    global MAX_EXPOSURE_PCT
    global KELLY_FRACTION
    global MAX_KELLY_FRACTION
    global SCAN_INTERVAL
    global ELASTIC_ORDERBOOK_SNAPSHOT_INTERVAL_SECONDS
    global MAX_OPEN_POSITIONS
    global MIN_EDGE
    global INITIAL_BANKROLL
    global MAX_RESOLUTION_HOURS
    global ALLOWED_FAST_ASSETS
    global SIGNAL_DEDUP_TTL_SECONDS
    global PAPER_TRADING
    global MAX_ORDER_AGE_HOURS
    global FILL_REPORT_HOURS
    global AUTO_MERGE_POSITIONS
    global MIN_MERGE_FREED_USDC
    global YES_THRESHOLD
    global NO_THRESHOLD
    global MIN_CATEGORY_PRIORITY
    global CATEGORY_PRIORITY
    global ADAPTIVE_PLATT_ENABLED
    global ADAPTIVE_PLATT_MIN_SAMPLES
    global ADAPTIVE_PLATT_WINDOW
    global ADAPTIVE_PLATT_REFIT_SECONDS
    global ADAPTIVE_PLATT_RUNTIME_VARIANT
    global ADAPTIVE_PLATT_REPORT_PATH
    global ADAPTIVE_PLATT_REPORT_JSON_PATH
    global DISAGREEMENT_CONFIRMATION_STD
    global DISAGREEMENT_SIGNAL_STD
    global DISAGREEMENT_REDUCE_SIZE_STD
    global DISAGREEMENT_WIDE_STD
    global ENSEMBLE_DAILY_COST_CAP_USD
    global ENSEMBLE_ENABLE_SECOND_CLAUDE
    global PM_HOURLY_CAMPAIGN_ENABLED
    global PM_HOURLY_NOTIONAL_CAP_USD
    global PM_CAMPAIGN_MAX_RESOLUTION_HOURS
    global PM_CAMPAIGN_WINDOW_SECONDS
    global PM_CAMPAIGN_DECISION_LOG_PATH

    bundle, settings = _runtime_settings.load_runtime_settings(
        activate_runtime_profile_env_fn=activate_runtime_profile_env,
        default_category_priority=_DEFAULT_CATEGORY_PRIORITY,
        clob_hard_min_shares=_CLOB_HARD_MIN_SHARES,
        persist=persist,
    )
    RUNTIME_PROFILE = bundle
    RUNTIME_PROFILE_NAME = settings.runtime_profile_name
    RUNTIME_EXECUTION_MODE = settings.runtime_execution_mode
    ALLOW_ORDER_SUBMISSION = settings.allow_order_submission
    MAX_POSITION_USD = settings.max_position_usd
    POLY_MIN_ORDER_SHARES = settings.poly_min_order_shares
    MAX_DAILY_LOSS_USD = settings.max_daily_loss_usd
    MAX_EXPOSURE_PCT = settings.max_exposure_pct
    KELLY_FRACTION = settings.kelly_fraction
    MAX_KELLY_FRACTION = settings.max_kelly_fraction
    SCAN_INTERVAL = settings.scan_interval
    ELASTIC_ORDERBOOK_SNAPSHOT_INTERVAL_SECONDS = settings.elastic_orderbook_snapshot_interval_seconds
    MAX_OPEN_POSITIONS = settings.max_open_positions
    MIN_EDGE = settings.min_edge
    INITIAL_BANKROLL = settings.initial_bankroll
    MAX_RESOLUTION_HOURS = settings.max_resolution_hours
    ALLOWED_FAST_ASSETS = set(settings.allowed_fast_assets)
    SIGNAL_DEDUP_TTL_SECONDS = settings.signal_dedup_ttl_seconds
    PAPER_TRADING = settings.paper_trading
    MAX_ORDER_AGE_HOURS = settings.max_order_age_hours
    FILL_REPORT_HOURS = settings.fill_report_hours
    AUTO_MERGE_POSITIONS = settings.auto_merge_positions
    MIN_MERGE_FREED_USDC = settings.min_merge_freed_usdc
    YES_THRESHOLD = settings.yes_threshold
    NO_THRESHOLD = settings.no_threshold
    MIN_CATEGORY_PRIORITY = settings.min_category_priority
    CATEGORY_PRIORITY = settings.category_priority
    ADAPTIVE_PLATT_ENABLED = settings.adaptive_platt_enabled
    ADAPTIVE_PLATT_MIN_SAMPLES = settings.adaptive_platt_min_samples
    ADAPTIVE_PLATT_WINDOW = settings.adaptive_platt_window
    ADAPTIVE_PLATT_REFIT_SECONDS = settings.adaptive_platt_refit_seconds
    ADAPTIVE_PLATT_RUNTIME_VARIANT = settings.adaptive_platt_runtime_variant
    ADAPTIVE_PLATT_REPORT_PATH = settings.adaptive_platt_report_path
    ADAPTIVE_PLATT_REPORT_JSON_PATH = settings.adaptive_platt_report_json_path
    DISAGREEMENT_CONFIRMATION_STD = settings.disagreement_confirmation_std
    DISAGREEMENT_SIGNAL_STD = settings.disagreement_signal_std
    DISAGREEMENT_REDUCE_SIZE_STD = settings.disagreement_reduce_size_std
    DISAGREEMENT_WIDE_STD = settings.disagreement_wide_std
    ENSEMBLE_DAILY_COST_CAP_USD = settings.ensemble_daily_cost_cap_usd
    ENSEMBLE_ENABLE_SECOND_CLAUDE = settings.ensemble_enable_second_claude
    PM_HOURLY_CAMPAIGN_ENABLED = settings.pm_hourly_campaign_enabled
    PM_HOURLY_NOTIONAL_CAP_USD = settings.pm_hourly_notional_cap_usd
    PM_CAMPAIGN_MAX_RESOLUTION_HOURS = settings.pm_campaign_max_resolution_hours
    PM_CAMPAIGN_WINDOW_SECONDS = settings.pm_campaign_window_seconds
    PM_CAMPAIGN_DECISION_LOG_PATH = settings.pm_campaign_decision_log_path

    return bundle


_reload_runtime_settings(persist=False)


def _round_up(value: float, decimals: int = 2) -> float:
    scale = 10 ** max(0, int(decimals))
    return math.ceil(max(0.0, float(value)) * scale - 1e-12) / scale


def clob_order_size_for_usd(size_usd: float, price: float) -> float:
    """Convert a capped USD order into rounded CLOB shares at the quoted price."""
    size_usd = max(0.0, float(size_usd))
    price = float(price)
    if size_usd <= 0.0 or price <= 0.0 or price >= 1.0:
        return 0.0
    return _round_up(size_usd / price, decimals=2)


def clob_min_order_size(price: float, *, min_shares: float = _CLOB_HARD_MIN_SHARES) -> float:
    """Return the live CLOB minimum size at a quoted price.

    Polymarket enforces both a share floor and a $5 notional floor, so low-price
    tokens can require far more than 5 shares to clear the live minimum.
    """
    price = max(0.0, float(price))
    required = max(float(min_shares), (_CLOB_HARD_MIN_NOTIONAL_USD / price) if price > 0.0 else float(min_shares))
    return _round_up(required, decimals=2)

# Multi-bankroll simulation levels
BANKROLL_LEVELS = [1_000, 10_000, 100_000]

STATE_FILE = Path("jj_state.json")
DB_FILE = Path("data/jj_trades.db")

# ---------------------------------------------------------------------------
# Platt Scaling Calibration (ported from local claude_analyzer.py)
# Fitted on 70% of 532 resolved markets, validated on 30% test set
# Test-set Brier: 0.286 (raw) → 0.245 (Platt) — improvement of +0.041
# ---------------------------------------------------------------------------
PLATT_A = _float_env("PLATT_A", "0.5914")
PLATT_B = _float_env("PLATT_B", "-0.3977")


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
# Telegram Signal Dedup Cache
# ---------------------------------------------------------------------------
class SignalDedupCache:
    """Prevents duplicate Telegram notifications on bot restarts.

    Stores (market_id, direction) → timestamp. Notifications are suppressed
    if the same signal was sent within SIGNAL_DEDUP_TTL_SECONDS.
    """

    def __init__(self, ttl_seconds: int = SIGNAL_DEDUP_TTL_SECONDS):
        self._cache: dict[tuple[str, str], float] = {}
        self._ttl = ttl_seconds

    def should_notify(self, market_id: str, direction: str) -> bool:
        """Return True if this signal hasn't been notified recently."""
        key = (str(market_id), str(direction))
        now = time.time()
        # Prune expired entries (cheap, runs every call)
        expired = [k for k, ts in self._cache.items() if now - ts > self._ttl]
        for k in expired:
            del self._cache[k]
        if key in self._cache:
            return False
        self._cache[key] = now
        return True

    def mark_notified(self, market_id: str, direction: str) -> None:
        """Explicitly mark a signal as notified (used after successful send)."""
        self._cache[(str(market_id), str(direction))] = time.time()

    @property
    def size(self) -> int:
        return len(self._cache)


class RollingNotionalBudgetTracker:
    """Tracks notional consumption over a rolling time window."""

    def __init__(self, *, cap_usd: float, window_seconds: int = 3600):
        self.cap_usd = max(0.0, float(cap_usd))
        self.window_seconds = max(60, int(window_seconds))
        self._events: list[tuple[float, float]] = []

    def _prune(self, now_ts: float | None = None) -> None:
        now = float(now_ts if now_ts is not None else time.time())
        cutoff = now - float(self.window_seconds)
        self._events = [(ts, amt) for ts, amt in self._events if ts >= cutoff]

    def used_usd(self, *, now_ts: float | None = None) -> float:
        self._prune(now_ts=now_ts)
        return round(sum(amt for _, amt in self._events), 4)

    def remaining_usd(self, *, now_ts: float | None = None) -> float:
        used = self.used_usd(now_ts=now_ts)
        return round(max(0.0, self.cap_usd - used), 4)

    def can_spend(
        self,
        amount_usd: float,
        *,
        now_ts: float | None = None,
    ) -> tuple[bool, str, float]:
        amount = max(0.0, float(amount_usd))
        if amount <= 0.0:
            return False, "pm_campaign_non_positive_notional", self.remaining_usd(now_ts=now_ts)
        if self.cap_usd <= 0.0:
            return False, "pm_campaign_budget_zero", 0.0
        remaining = self.remaining_usd(now_ts=now_ts)
        if amount > remaining + 1e-9:
            return False, "pm_campaign_budget_exceeded", remaining
        return True, "pm_campaign_ok", remaining

    def record_spend(self, amount_usd: float, *, now_ts: float | None = None) -> None:
        amount = max(0.0, float(amount_usd))
        if amount <= 0.0:
            return
        ts = float(now_ts if now_ts is not None else time.time())
        self._events.append((ts, amount))
        self._prune(now_ts=ts)

    def snapshot(self, *, now_ts: float | None = None) -> dict[str, float]:
        used = self.used_usd(now_ts=now_ts)
        remaining = max(0.0, self.cap_usd - used)
        return {
            "cap_usd": round(self.cap_usd, 2),
            "used_usd": round(used, 2),
            "remaining_usd": round(remaining, 2),
            "window_seconds": int(self.window_seconds),
        }


# ---------------------------------------------------------------------------
# Category Classification (ported from local claude_analyzer.py)
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = {
    "politics": ["election", "president", "congress", "senate", "governor", "vote",
                 "democrat", "republican", "trump", "biden", "party", "primary",
                 "legislation", "bill", "law", "executive order", "cabinet",
                 "impeach", "poll", "ballot", "nominee", "campaign",
                 "prime minister", "chancellor", "parliament", "coalition",
                 "ruling party", "seats", "mayor", "referendum"],
    "weather": ["temperature", "rain", "snow", "weather", "hurricane", "storm",
                "heat", "cold", "wind", "flood", "drought", "celsius", "fahrenheit",
                "high of", "low of", "degrees"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
               "token", "defi", "nft", "blockchain", "altcoin", "dogecoin", "xrp",
               "up or down", "above", "below", "hit $", "reach $", "price",
               "market cap", "memecoin", "meme coin", "cardano", "ada",
               "polkadot", "litecoin",
               "cex", "dex", "binance", "coinbase", "kraken exchange",
               "insolvent", "airdrop", "staking", "validator", "layer 2",
               "l2", "mainnet", "testnet", "megaeth", "gas fee"],
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
               "super league", "copa america", "euro 202", "nations league",
               # German/Italian/French lower-league teams that slip through
               "darmstadt", "heidenheim", "hoffenheim", "holstein kiel",
               "strasbourg", "reggiana", "avellino", "padova", "venezia",
               "smouha", "mallorca", "gamecocks", "miners", "cougars",
               "villanova", "marquette", "huskies", "golden eagles",
               # Betting line patterns
               "leading at halftime", "halftime", "first half",
               "win on 2026", "win on 2027",
               # FIFA qualification
               "qualify for the 202", "qualify for the fifa"],
    "geopolitical": ["war", "invasion", "nato", "china", "russia", "taiwan",
                     "sanctions", "ceasefire", "nuclear", "military", "conflict",
                     "strike on", "airstrike", "missile", "occupation",
                     "annex", "blockade", "coup", "regime change"],
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

# Category priority values come from the active runtime profile, with
# `JJ_CAT_PRIORITY_*` env overrides preserved for temporary compatibility.

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

# Asymmetric thresholds also come from the active runtime profile, with the
# legacy `JJ_*` env vars retained as override inputs.


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


def _parse_iso8601_utc(value: str | None) -> datetime | None:
    """Parse a runtime timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _infer_intraday_interval_minutes(question: str) -> int | None:
    """Infer candle/window length from natural-language intraday titles."""
    title = str(question or "")
    match = re.search(
        r"(\d{1,2}):(\d{2})\s*(am|pm)\s*-\s*(\d{1,2}):(\d{2})\s*(am|pm)",
        title,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    def _to_minutes(hour_text: str, minute_text: str, ampm: str) -> int:
        hour = int(hour_text) % 12
        if ampm.lower() == "pm":
            hour += 12
        minute = int(minute_text)
        return (hour * 60) + minute

    start = _to_minutes(match.group(1), match.group(2), match.group(3))
    end = _to_minutes(match.group(4), match.group(5), match.group(6))
    if end < start:
        end += 24 * 60
    diff = end - start
    return diff if diff > 0 else None


def looks_like_fast_flow_market(question: str) -> bool:
    """Identify the short-duration crypto markets tracked by wallet flow."""
    lowered = (question or "").lower()
    if "up or down" not in lowered:
        return False
    if any(token in lowered for token in ("5m", "15m", "5-minute", "15-minute", "5 minute", "15 minute")):
        return True
    return _infer_intraday_interval_minutes(question) in {5, 15}


def is_dedicated_btc5_market(question: str, *, slug: str | None = None) -> bool:
    """Return True when the market belongs to the standalone BTC5 service."""
    normalized_slug = str(slug or "").strip().lower()
    if normalized_slug.startswith("btc-updown-5m"):
        return True

    lowered = (question or "").lower()
    if "up or down" not in lowered:
        return False
    if "bitcoin" not in lowered and "btc" not in lowered:
        return False
    if any(token in lowered for token in ("5m", "5-minute", "5 minute")):
        return True
    return _infer_intraday_interval_minutes(question) == 5


def infer_fast_flow_asset(question: str) -> str | None:
    lowered = str(question or "").lower()
    if re.search(r"\b(bitcoin|btc)\b", lowered):
        return "btc"
    if re.search(r"\b(ethereum|eth)\b", lowered):
        return "eth"
    if re.search(r"\b(solana|sol)\b", lowered):
        return "sol"
    if re.search(r"\b(xrp|ripple)\b", lowered):
        return "xrp"
    if re.search(r"\b(dogecoin|doge)\b", lowered):
        return "doge"
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


def apply_llm_market_filters(
    question: str,
    *,
    resolution_hours: float | None,
    slug: str | None = None,
) -> tuple[bool, str, str, float | None]:
    """Enforce the LLM category and velocity gates in one place.

    Returns:
        (allowed, reason, category, normalized_resolution_hours)
    """
    category = classify_market_category(question)
    if is_dedicated_btc5_market(question, slug=slug):
        return False, "btc5_dedicated", category, resolution_hours
    fast_asset = infer_fast_flow_asset(question) if looks_like_fast_flow_market(question) else None
    if fast_asset is not None and ALLOWED_FAST_ASSETS and fast_asset not in ALLOWED_FAST_ASSETS:
        return False, "fast_asset_not_allowed", category, resolution_hours
    if CATEGORY_PRIORITY.get(category, 2) < MIN_CATEGORY_PRIORITY:
        return False, "category", category, resolution_hours

    normalized_resolution = resolution_hours
    if MAX_RESOLUTION_HOURS > 0:
        if normalized_resolution is None:
            # SAFETY: Markets without parseable end dates are rejected when a
            # velocity gate is active.  The old 24h fallback let multi-month
            # markets (Morocco Dec 2026, Russia April) slip through because
            # their end dates were unparseable.  Better to miss a fast market
            # than to lock capital in a 9-month position.
            logger.info(
                "Velocity gate: rejecting %s — no parseable resolution_hours (category=%s)",
                question[:60], category,
            )
            return False, "unknown_resolution", category, None
        if normalized_resolution > MAX_RESOLUTION_HOURS:
            return False, "velocity", category, normalized_resolution

    return True, "ok", category, normalized_resolution


def normalize_token_ids(raw: Any) -> list[str]:
    """Normalize Gamma/Scanner token-id payloads into clean strings."""
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        try:
            return normalize_token_ids(json.loads(stripped))
        except json.JSONDecodeError:
            raw = stripped.split(",")

    token_ids: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                cleaned = item.strip().strip("[]").strip().strip('"').strip("'")
                if cleaned:
                    token_ids.append(cleaned)
            elif isinstance(item, dict):
                token = item.get("token_id") or item.get("tokenId") or item.get("id")
                if isinstance(token, str):
                    cleaned = token.strip()
                    if cleaned:
                        token_ids.append(cleaned)
    return token_ids


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

    source_components = extract_signal_source_components(signal)
    signal_sources = extract_signal_sources(signal) or list(source_components)
    primary_source = str(signal.get("source", "") or "").strip() or "llm"
    if primary_source not in source_components:
        source_components = [primary_source, *source_components]
    source_combo = (
        str(signal.get("source_combo", "") or "").strip()
        or "+".join(source_components)
        or primary_source
    )
    source_count = max(
        len(source_components),
        int(_safe_float(signal.get("n_sources", 0), 0)),
        1,
    )
    signal_metadata = extract_signal_metadata(signal)

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
        "source": primary_source,
        "source_combo": source_combo,
        "source_components": source_components,
        "source_count": source_count,
        "signal_sources": signal_sources,
        "signal_metadata": signal_metadata,
        "n_models": int(_safe_float(signal.get("n_models", 0), 0)),
        "model_spread": _safe_float(signal.get("model_spread"), None),
        "model_stddev": _safe_float(signal.get("model_stddev"), None),
        "agreement": _safe_float(signal.get("agreement"), None),
        "kelly_multiplier": _safe_float(signal.get("confidence_multiplier", signal.get("kelly_multiplier")), None),
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


def extract_signal_source_components(payload: Mapping[str, Any] | None) -> list[str]:
    """Return a stable, de-duplicated ordered source list for a signal payload."""
    return _signal_source_helpers.extract_signal_source_components(
        payload,
        canonical_source_key_fn=canonical_source_key,
        normalize_source_components_fn=normalize_source_components,
    )


def extract_signal_sources(payload: Mapping[str, Any] | None) -> list[str]:
    """Return canonical source aliases for persisted trade state."""
    return _signal_source_helpers.extract_signal_sources(
        payload,
        canonical_source_key_fn=canonical_source_key,
        normalize_source_components_fn=normalize_source_components,
    )


def extract_signal_metadata(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Collect additive attribution metadata from a signal or trade payload."""
    return _signal_source_helpers.extract_signal_metadata(
        payload,
        safe_float_fn=_safe_float,
        canonical_source_key_fn=canonical_source_key,
        normalize_source_components_fn=normalize_source_components,
    )


def merge_signal_metadata(payloads: list[Mapping[str, Any] | None]) -> dict[str, Any]:
    """Merge per-source metadata across all confirming signal payloads."""
    return _signal_source_helpers.merge_signal_metadata(
        payloads,
        safe_float_fn=_safe_float,
        canonical_source_key_fn=canonical_source_key,
        normalize_source_components_fn=normalize_source_components,
    )


def signal_has_source(payload: Mapping[str, Any] | None, source: str) -> bool:
    """Check whether a signal payload contains a given source in its attribution set."""
    return _signal_source_helpers.signal_has_source(
        payload,
        source,
        canonical_source_key_fn=canonical_source_key,
        normalize_source_components_fn=normalize_source_components,
    )


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
                source_combo TEXT,
                source_components_json TEXT,
                source_count INTEGER DEFAULT 1,
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
                "source_combo": "TEXT",
                "source_components_json": "TEXT",
                "source_count": "INTEGER DEFAULT 1",
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
        source_components = extract_signal_source_components(trade)
        source_combo = (
            str(trade.get("source_combo", "") or "").strip()
            or "+".join(source_components)
            or str(trade.get("source", "llm") or "llm")
        )
        source_count = max(
            int(_safe_float(trade.get("source_count", 0), 0)),
            len(source_components),
            1,
        )
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO trades (id, timestamp, market_id, question, direction,
                entry_price, raw_prob, calibrated_prob, edge, taker_fee,
                position_size_usd, kelly_fraction, category, confidence,
                reasoning, token_id, order_id, paper, bankroll_level, source,
                source_combo, source_components_json, source_count,
                n_models, model_spread, model_stddev, agreement,
                kelly_multiplier, disagreement_kelly_fraction, models_agree,
                search_context_used, counter_shift, counter_fragile, platt_mode,
                platt_a, platt_b)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            source_combo,
            json.dumps(source_components, sort_keys=True),
            source_count,
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

    def get_source_breakdown(
        self,
        *,
        date_prefix: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Summarize trade volume and outcomes by recorded source attribution."""
        limit = max(1, int(limit))
        where_clause = ""
        params: list[Any] = []
        if date_prefix:
            where_clause = "WHERE timestamp LIKE ?"
            params.append(f"{date_prefix}%")
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT
                COALESCE(NULLIF(source_combo, ''), NULLIF(source, ''), 'unknown') AS source_label,
                COUNT(*) AS total_trades,
                SUM(CASE WHEN outcome = 'won' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN outcome = 'lost' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN outcome IS NULL THEN 1 ELSE 0 END) AS unresolved,
                COALESCE(SUM(pnl), 0.0) AS pnl
            FROM trades
            {where_clause}
            GROUP BY source_label
            ORDER BY total_trades DESC, source_label ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

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
    """Thin wrapper around bot.adaptive_platt.PlattCalibrator for live use."""

    def __init__(
        self,
        db: TradeDatabase,
        *,
        enabled: bool = ADAPTIVE_PLATT_ENABLED,
        min_samples: int = ADAPTIVE_PLATT_MIN_SAMPLES,
        window: int = ADAPTIVE_PLATT_WINDOW,
        refit_seconds: int = ADAPTIVE_PLATT_REFIT_SECONDS,
        runtime_variant: str = ADAPTIVE_PLATT_RUNTIME_VARIANT,
    ):
        selected_variant = runtime_variant
        if selected_variant in ("rolling", "window"):
            selected_variant = f"rolling_{max(30, int(window))}"

        self._impl = None
        if RuntimePlattCalibrator is not None:
            self._impl = RuntimePlattCalibrator(
                db,
                enabled=enabled,
                min_observations=min_samples,
                runtime_variant=selected_variant,
                refit_seconds=refit_seconds,
                report_path=ADAPTIVE_PLATT_REPORT_PATH,
                report_json_path=ADAPTIVE_PLATT_REPORT_JSON_PATH,
                static_a=PLATT_A,
                static_b=PLATT_B,
            )
        else:
            logger.warning("Adaptive Platt module unavailable; falling back to static Platt")
            self.enabled = False
            self.active_mode = "static"
            self.active_a = float(PLATT_A)
            self.active_b = float(PLATT_B)
            self.sample_size = 0
            self.selected_variant = "static"

    def __getattr__(self, name: str):
        if self._impl is not None:
            return getattr(self._impl, name)
        raise AttributeError(name)

    def ensure_report(self, force: bool = False) -> dict | None:
        if self._impl is None:
            return None
        return self._impl.ensure_report(force=force)

    def refresh(self, force: bool = False) -> bool:
        if self._impl is None:
            return False
        return self._impl.refresh(force=force)

    def calibrate(self, raw_prob: float) -> float:
        if self._impl is None:
            return calibrate_probability_with_params(raw_prob, PLATT_A, PLATT_B)
        return self._impl.calibrate(raw_prob)

    def summary(self) -> dict:
        if self._impl is None:
            return {
                "enabled": False,
                "selected_variant": "static",
                "active_mode": "static",
                "mode": "static",
                "a": float(PLATT_A),
                "b": float(PLATT_B),
                "samples": 0,
                "last_refit_at": "",
                "last_refit_rows": 0,
                "report_path": ADAPTIVE_PLATT_REPORT_PATH,
            }
        summary = dict(self._impl.summary())
        summary["mode"] = summary.get("active_mode", summary.get("mode"))
        return summary


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
    model_count: int = 2,
) -> tuple[float, float]:
    """Apply the ensemble confidence multiplier to a Kelly-sized trade."""
    if size_usd <= 0:
        return 0.0, 1.0
    if std_dev is None:
        return round(size_usd, 2), 1.0

    resolved_modifier = (
        max(0.0, float(modifier))
        if modifier is not None
        else confidence_multiplier_from_std(std_dev, model_count)
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
                    normalized_open_positions: dict[str, dict[str, Any]] = {}
                    for market_id, payload in merged["open_positions"].items():
                        if not isinstance(payload, dict):
                            continue
                        normalized = dict(payload)
                        normalized_components = extract_signal_source_components(normalized)
                        normalized_source = (
                            str(normalized.get("source", "") or "").strip()
                            or (normalized_components[0] if normalized_components else "")
                        )
                        normalized["source"] = normalized_source
                        normalized["source_combo"] = (
                            str(normalized.get("source_combo", "") or "").strip()
                            or "+".join(normalized_components)
                            or normalized_source
                        )
                        normalized["source_components"] = normalized_components
                        normalized["source_count"] = max(
                            int(_safe_float(normalized.get("source_count"), 0)),
                            len(normalized_components),
                            1 if normalized_source else 0,
                        )
                        normalized["signal_sources"] = extract_signal_sources(normalized) or list(normalized_components)
                        normalized["signal_metadata"] = extract_signal_metadata(normalized)
                        normalized_open_positions[str(market_id)] = normalized
                    merged["open_positions"] = normalized_open_positions

                    normalized_trade_log: list[dict[str, Any]] = []
                    for payload in merged["trade_log"]:
                        if not isinstance(payload, dict):
                            continue
                        normalized = dict(payload)
                        normalized_components = extract_signal_source_components(normalized)
                        normalized_source = (
                            str(normalized.get("source", "") or "").strip()
                            or (normalized_components[0] if normalized_components else "")
                        )
                        normalized["source"] = normalized_source
                        normalized["source_combo"] = (
                            str(normalized.get("source_combo", "") or "").strip()
                            or "+".join(normalized_components)
                            or normalized_source
                        )
                        normalized["source_components"] = normalized_components
                        normalized["source_count"] = max(
                            int(_safe_float(normalized.get("source_count"), 0)),
                            len(normalized_components),
                            1 if normalized_source else 0,
                        )
                        normalized["signal_sources"] = extract_signal_sources(normalized) or list(normalized_components)
                        normalized["signal_metadata"] = extract_signal_metadata(normalized)
                        normalized_trade_log.append(normalized)
                    merged["trade_log"] = normalized_trade_log[-100:]
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

    def open_notional_for_market(self, market_id: str, direction: str | None = None) -> float:
        position = self.state.get("open_positions", {}).get(str(market_id))
        if not isinstance(position, dict):
            return 0.0
        if direction is not None and str(position.get("direction") or "").strip() != str(direction).strip():
            return 0.0
        return round(_safe_float(position.get("size_usd"), 0.0), 6)

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

    def record_trade(
        self,
        market_id: str,
        question: str,
        direction: str,
        price: float,
        size_usd: float,
        edge: float,
        confidence: float,
        order_id: str = "",
        *,
        source: str = "",
        source_combo: str = "",
        source_components: list[str] | None = None,
        source_count: int | None = None,
        signal_sources: list[str] | None = None,
        signal_metadata: Mapping[str, Any] | None = None,
    ):
        """Record a new filled trade, aggregating repeated fills on the same side."""
        now_iso = datetime.now(timezone.utc).isoformat()
        incoming_components = extract_signal_source_components(
            {
                "source": source,
                "source_combo": source_combo,
                "source_components": source_components or [],
                "signal_sources": signal_sources or [],
            }
        )
        incoming_signal_sources = extract_signal_sources(
            {
                "source": source,
                "source_combo": source_combo,
                "source_components": incoming_components,
                "signal_sources": signal_sources or [],
            }
        ) or list(incoming_components)
        incoming_signal_metadata = extract_signal_metadata(
            {
                "source": source,
                "source_combo": source_combo,
                "source_components": incoming_components,
                "signal_sources": incoming_signal_sources,
                "signal_metadata": dict(signal_metadata or {}),
                "confidence": confidence,
                "edge": edge,
            }
        )
        existing = self.state["open_positions"].get(market_id)
        if existing and existing.get("direction") == direction:
            prev_price = _safe_float(existing.get("entry_price"), price) or price
            prev_size_usd = _safe_float(existing.get("size_usd"), 0.0) or 0.0
            prev_shares = prev_size_usd / prev_price if prev_price > 0 else 0.0
            new_shares = size_usd / price if price > 0 else 0.0
            total_shares = prev_shares + new_shares
            total_size_usd = prev_size_usd + size_usd
            avg_entry_price = (
                total_size_usd / total_shares
                if total_shares > 0
                else price
            )
            order_ids = [
                oid
                for oid in existing.get("order_ids", [existing.get("order_id", "")])
                if oid
            ]
            if order_id and order_id not in order_ids:
                order_ids.append(order_id)
            merged_components = extract_signal_source_components(existing)
            for component in incoming_components:
                if component not in merged_components:
                    merged_components.append(component)
            merged_signal_metadata = extract_signal_metadata(existing)
            merged_signal_metadata.update(incoming_signal_metadata)
            primary_source = str(existing.get("source", "") or source or "").strip()
            if not primary_source and merged_components:
                primary_source = merged_components[0]
            resolved_source_combo = (
                "+".join(merged_components)
                or str(existing.get("source_combo", "") or "").strip()
                or str(source_combo or "").strip()
                or primary_source
            )
            resolved_source_count = max(
                int(_safe_float(existing.get("source_count"), 0)),
                int(source_count or 0),
                len(merged_components),
                1 if primary_source else 0,
            )
            self.state["open_positions"][market_id] = {
                "question": question or existing.get("question", ""),
                "direction": direction,
                "entry_price": avg_entry_price,
                "size_usd": total_size_usd,
                "shares": total_shares,
                "edge": ((existing.get("edge", edge) or edge) * prev_size_usd + edge * size_usd)
                / max(total_size_usd, 1e-9),
                "confidence": (
                    (_safe_float(existing.get("confidence"), confidence) or confidence) * prev_size_usd
                    + confidence * size_usd
                ) / max(total_size_usd, 1e-9),
                "order_id": order_id or existing.get("order_id", ""),
                "order_ids": order_ids,
                "source": primary_source,
                "source_combo": resolved_source_combo,
                "source_components": merged_components,
                "source_count": resolved_source_count,
                "signal_sources": list(merged_components),
                "signal_metadata": merged_signal_metadata,
                "timestamp": existing.get("timestamp", now_iso),
                "updated_at": now_iso,
            }
        else:
            primary_source = str(source or "").strip() or (incoming_components[0] if incoming_components else "")
            resolved_source_combo = (
                str(source_combo or "").strip()
                or "+".join(incoming_components)
                or primary_source
            )
            resolved_source_count = max(
                int(source_count or 0),
                len(incoming_components),
                1 if primary_source else 0,
            )
            self.state["open_positions"][market_id] = {
                "question": question,
                "direction": direction,
                "entry_price": price,
                "size_usd": size_usd,
                "shares": size_usd / price if price > 0 else 0.0,
                "edge": edge,
                "confidence": confidence,
                "order_id": order_id,
                "order_ids": [order_id] if order_id else [],
                "source": primary_source,
                "source_combo": resolved_source_combo,
                "source_components": incoming_components,
                "source_count": resolved_source_count,
                "signal_sources": list(incoming_signal_sources),
                "signal_metadata": incoming_signal_metadata,
                "timestamp": now_iso,
                "updated_at": now_iso,
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
            "source": primary_source,
            "source_combo": resolved_source_combo,
            "source_components": incoming_components,
            "source_count": resolved_source_count,
            "signal_sources": list(incoming_signal_sources),
            "signal_metadata": incoming_signal_metadata,
            "timestamp": now_iso,
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

        self.runtime_profile = _reload_runtime_settings(persist=True)
        self.profile_name = self.runtime_profile.selected_profile
        self.runtime_mode = str(self.runtime_profile.config.get("mode", {}).get("effective_execution_mode", "paper"))
        self.launch_gate_reason = str(self.runtime_profile.config.get("mode", {}).get("launch_gate_reason", "") or "")
        self.paper_mode = PAPER_TRADING
        self.allow_order_submission = ALLOW_ORDER_SUBMISSION
        self.enable_llm_signals = _bool_env("ENABLE_LLM_SIGNALS", True)
        self.enable_wallet_flow = _bool_env("ENABLE_WALLET_FLOW", True)
        self.enable_lmsr = _bool_env("ENABLE_LMSR", True)
        self.enable_cross_platform_arb = _bool_env("ENABLE_CROSS_PLATFORM_ARB", True)
        self.enable_sum_violation = _sum_violation_lane_enabled(self.profile_name)
        self.fast_flow_only = _bool_env("JJ_FAST_FLOW_ONLY", False)
        self.wallet_flow_scores_file = Path(
            os.environ.get("JJ_WALLET_FLOW_SCORES_FILE", "data/smart_wallets.json")
        )
        self.wallet_flow_db_file = Path(
            os.environ.get("JJ_WALLET_FLOW_DB_FILE", "data/wallet_scores.db")
        )
        self._configure_wallet_flow_paths()
        self._startup_lane_health: dict[str, dict[str, Any]] = {}
        self._last_lane_health: dict[str, dict[str, Any]] = {}
        self._elastic_orderbook_task = None
        self._elastic_market_lookup: dict[str, dict[str, Any]] = {}
        self._elastic_token_market_index: dict[str, str] = {}
        self.pm_hourly_campaign_enabled = PM_HOURLY_CAMPAIGN_ENABLED
        self.pm_campaign_max_resolution_hours = PM_CAMPAIGN_MAX_RESOLUTION_HOURS
        self.pm_campaign_budget = RollingNotionalBudgetTracker(
            cap_usd=PM_HOURLY_NOTIONAL_CAP_USD,
            window_seconds=PM_CAMPAIGN_WINDOW_SECONDS,
        )
        self.pm_campaign_decision_log_path = PM_CAMPAIGN_DECISION_LOG_PATH
        self.pm_campaign_decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        self._pm_campaign_recent_decisions: list[dict[str, Any]] = []
        self.enforce_runtime_truth_guard = True
        self.runtime_truth_guard = self._evaluate_runtime_truth_guard()
        if not self.runtime_truth_guard.get("greenlight", False):
            if self.allow_order_submission:
                logger.warning(
                    "Runtime truth guard blocked order submission: %s",
                    self.runtime_truth_guard.get("reason", "runtime_truth_not_green"),
                )
            self.allow_order_submission = False
        self.shadow_order_lifecycle = (
            ShadowOrderLifecycle(
                ttl_seconds=_float_env("JJ_SHADOW_ORDER_TTL_SECONDS", "120"),
                expected_fill_window_seconds=_float_env("JJ_SHADOW_EXPECTED_FILL_WINDOW_SECONDS", "30"),
                markout_windows_seconds=(5, 30, 120),
            )
            if ShadowOrderLifecycle is not None
            else None
        )
        self.state = JJState()
        self.heartbeat_writer = HeartbeatWriter()
        self.scanner = MarketScanner()

        # Market quarantine: gracefully handle CLOB 404s with exponential backoff
        if MarketQuarantine is not None:
            self.quarantine = MarketQuarantine(db_path="data/edge_discovery.db")
            logger.info("Market quarantine initialized (%d active)", self.quarantine.stats()["active_count"])
        else:
            self.quarantine = None

        self.notifier = self._init_telegram()
        self.signal_dedup = SignalDedupCache(ttl_seconds=SIGNAL_DEDUP_TTL_SECONDS)
        self.db = TradeDatabase()
        self.adaptive_platt = AdaptivePlattCalibrator(self.db)
        if self.adaptive_platt.enabled:
            try:
                self.adaptive_platt.ensure_report(force=False)
            except Exception as e:
                logger.warning(f"Adaptive Platt report generation failed (non-fatal): {e}")
        self.adaptive_platt.refresh(force=True)
        if self.adaptive_platt.enabled:
            cal = self.adaptive_platt.summary()
            logger.info(
                "Adaptive Platt: winner=%s active=%s A=%.4f B=%.4f samples=%d refit_rows=%d report=%s",
                cal.get("selected_variant", "static"),
                cal.get("active_mode", cal.get("mode", "static")),
                cal["a"],
                cal["b"],
                cal["samples"],
                cal.get("last_refit_rows", 0),
                cal.get("report_path", ADAPTIVE_PLATT_REPORT_PATH),
            )
        self.multi_sim = MultiBankrollSimulator(self.db)

        # LLM Analyzer: prefer the new multi-model ensemble over single Claude.
        self.ensemble_mode = False
        self.ensemble_cost_tracker = None
        self.analyzer = None
        if self._llm_lane_enabled():
            if self._has_llm_credentials():
                if EnsembleEstimator is not None:
                    try:
                        if LLMCostTracker is not None:
                            self.ensemble_cost_tracker = LLMCostTracker(
                                daily_cap_usd=ENSEMBLE_DAILY_COST_CAP_USD,
                            )
                        self.analyzer = EnsembleEstimator(
                            calibrate_fn=self.adaptive_platt.calibrate,
                            min_edge=MIN_EDGE,
                            daily_cost_cap_usd=ENSEMBLE_DAILY_COST_CAP_USD,
                            cost_tracker=self.ensemble_cost_tracker,
                            enable_second_claude=ENSEMBLE_ENABLE_SECOND_CLAUDE,
                        )
                        self.ensemble_cost_tracker = self.analyzer.cost_tracker
                        self.ensemble_mode = True
                        logger.info(
                            "Ensemble estimator initialized: models=%s cost_cap=$%.2f second_claude=%s",
                            ", ".join(self.analyzer.models) or "none",
                            ENSEMBLE_DAILY_COST_CAP_USD,
                            ENSEMBLE_ENABLE_SECOND_CLAUDE,
                        )
                    except Exception as e:
                        logger.warning(f"Ensemble estimator init failed, falling back to Claude-only: {e}")
                        self.analyzer = ClaudeAnalyzer()
                else:
                    self.analyzer = ClaudeAnalyzer()
                    logger.info("Using single-model ClaudeAnalyzer (ensemble estimator not available)")
            else:
                logger.warning("LLM signal lane enabled but no model credentials found — skipping LLM initialization")
        else:
            logger.info(
                "LLM signal lane disabled (ENABLE_LLM_SIGNALS=%s, JJ_FAST_FLOW_ONLY=%s)",
                self.enable_llm_signals,
                self.fast_flow_only,
            )
        self.fill_tracker = (
            FillTracker(db_path=self.db.db_path, report_path=Path("reports/fill_rate_report.md"))
            if FillTracker is not None
            else None
        )

        # Only init CLOB client for live trading
        if not self.paper_mode:
            self.clob = self._init_clob_client()
        else:
            self.clob = None
            logger.info("PAPER TRADING MODE — orders will be simulated locally")

        merge_executor = None
        if not self.paper_mode:
            if NodePolyMergerExecutor is not None and os.environ.get("POLY_MERGER_SCRIPT"):
                merge_executor = NodePolyMergerExecutor(os.environ.get("POLY_MERGER_SCRIPT"))
            elif RelayerMergeExecutor is not None:
                merge_executor = RelayerMergeExecutor()
        self.position_merger = (
            LivePositionMerger(
                user_address=os.environ.get("POLY_SAFE_ADDRESS") or os.environ.get("POLYMARKET_FUNDER"),
                executor=merge_executor,
                min_freed_capital_usdc=MIN_MERGE_FREED_USDC,
                auto_submit=AUTO_MERGE_POSITIONS,
            )
            if LivePositionMerger is not None
            else None
        )

        # Signal source #2: LMSR Bayesian Engine
        self.lmsr_module_available = LMSREngine is not None
        if self.enable_lmsr and LMSREngine is not None:
            self.lmsr_engine = LMSREngine(
                entry_threshold=float(os.environ.get("JJ_LMSR_THRESHOLD", "0.05")),
            )
            logger.info("LMSR Bayesian Engine initialized")
        else:
            self.lmsr_engine = None
            if not self.enable_lmsr:
                logger.info("LMSR lane disabled by config")
            else:
                logger.warning("LMSR engine not available — running without")

        # Signal source #3: Smart Wallet Flow Detector
        self.wallet_flow_module_available = wallet_flow_get_signals is not None
        self.wallet_flow_available = self.enable_wallet_flow and self.wallet_flow_module_available
        if self.wallet_flow_available:
            logger.info("Smart Wallet Flow Detector available")
            self._maybe_initialize_wallet_flow_bootstrap()
        else:
            if not self.enable_wallet_flow:
                logger.info("Wallet flow lane disabled by config")
            else:
                logger.warning("Wallet flow detector not available — running without")

        # Signal source #4: Cross-Platform Arbitrage Scanner
        self.arb_module_available = arb_get_signals is not None
        self.arb_available = self.enable_cross_platform_arb and self.arb_module_available
        if self.arb_available:
            logger.info("Cross-platform arb scanner available")
        else:
            if not self.enable_cross_platform_arb:
                logger.info("Cross-platform arb lane disabled by config")
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
                    vpin_toxic_threshold=float(os.environ.get("JJ_VPIN_TOXIC_THRESHOLD", "0.75")),
                    vpin_safe_threshold=float(os.environ.get("JJ_VPIN_SAFE_THRESHOLD", "0.25")),
                    ofi_skew_threshold=float(os.environ.get("JJ_OFI_SKEW_THRESHOLD", "0.90")),
                    ofi_ratio_threshold=float(os.environ.get("JJ_OFI_ZSCORE_THRESHOLD", "3.0")),
                    on_regime_change=self._on_regime_change,
                    on_ofi_update=self._on_ofi_update,
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

        # Signal source #7: Elastic ML anomaly feedback
        self.anomaly_consumer = None
        self._anomaly_task = None
        if ElasticAnomalyConsumer is not None:
            try:
                self.anomaly_consumer = ElasticAnomalyConsumer()
                if self.anomaly_consumer.enabled:
                    logger.info(
                        "Elastic ML anomaly consumer initialized (threshold=%.1f interval=%ss)",
                        self.anomaly_consumer.score_threshold,
                        self.anomaly_consumer.poll_interval_seconds,
                    )
                else:
                    logger.info("Elastic ML anomaly consumer available but disabled")
            except Exception as e:
                logger.warning(f"Elastic ML anomaly consumer init failed: {e}")
                self.anomaly_consumer = None
        else:
            logger.warning("Elastic ML anomaly consumer not available — running without")

        # Signal source #8: Multi-outcome sum-violation scanner
        self.sum_violation_scanner = None
        self.sum_violation_strategy = None
        if not self.enable_sum_violation:
            logger.info("Sum-violation lane disabled by config")
        elif self.fast_flow_only:
            logger.info("Sum-violation lane disabled in fast-flow-only mode")
        elif SumViolationScanner is not None and SumViolationStrategy is not None:
            try:
                self.sum_violation_scanner = SumViolationScanner(
                    interval_seconds=SCAN_INTERVAL,
                    max_pages=int(os.environ.get("JJ_SUM_VIOLATION_MAX_PAGES", "20")),
                    page_size=int(os.environ.get("JJ_SUM_VIOLATION_PAGE_SIZE", "100")),
                    max_events=int(os.environ.get("JJ_SUM_VIOLATION_MAX_EVENTS", "60")),
                    min_event_markets=3,
                    prefilter_buffer=float(os.environ.get("JJ_SUM_VIOLATION_PREFILTER_BUFFER", "0.025")),
                    timeout_seconds=float(os.environ.get("JJ_SUM_VIOLATION_TIMEOUT_SECONDS", "12.0")),
                    use_websocket=False,
                )
                self.sum_violation_strategy = SumViolationStrategy(
                    scanner=self.sum_violation_scanner,
                    threshold=float(os.environ.get("JJ_SUM_VIOLATION_THRESHOLD", "0.05")),
                    min_depth_usd=float(os.environ.get("JJ_SUM_VIOLATION_MIN_DEPTH_USD", "50.0")),
                    max_resolution_hours=MAX_RESOLUTION_HOURS,
                    position_size_usd=min(MAX_POSITION_USD, 0.50),
                    report_path=os.environ.get(
                        "JJ_SUM_VIOLATION_REPORT_PATH",
                        "reports/sum_violations_log.md",
                    ),
                )
                logger.info("Signal source #8: Multi-outcome Sum Violation initialized")
            except Exception as e:
                logger.warning(f"Sum-violation strategy init failed: {e}")
                self.sum_violation_scanner = None
                self.sum_violation_strategy = None
        else:
            logger.warning("Sum-violation strategy not available — running without")

        # Signals 5/6: A-6 + B-1 structural alpha integration.
        self.combinatorial_cfg = (
            CombinatorialConfig.from_runtime_profile(self.runtime_profile)
            if (not self.fast_flow_only and CombinatorialConfig is not None)
            else None
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
        if self.fast_flow_only:
            logger.info("Combinatorial lanes disabled in fast-flow-only mode")
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

        mode_str = self.runtime_mode.upper()
        logger.info("=" * 60)
        logger.info(f"JJ {mode_str} TRADING SYSTEM — INITIALIZED")
        logger.info(f"  Mode: {mode_str}")
        logger.info(
            "  Runtime profile: %s | requested=%s | paper=%s | launch_gate=%s",
            self.profile_name,
            self.runtime_profile.config.get("mode", {}).get("requested_execution_mode", "unknown"),
            self.paper_mode,
            self.launch_gate_reason or "none",
        )
        logger.info("  Order submission: %s", self.allow_order_submission)
        logger.info(f"  Bankroll: ${self.state.state['bankroll']:.2f}")
        logger.info(f"  Multi-bankroll: {BANKROLL_LEVELS}")
        logger.info(
            "  Open positions: %s single-leg / %s linked baskets",
            len(self.state.state["open_positions"]),
            self.state.count_active_linked_baskets(),
        )
        logger.info(
            "  Effective config: position=$%.2f max_positions=%d daily_loss=$%.2f kelly=%.2f max_res=%.1fh paper=%s",
            MAX_POSITION_USD,
            MAX_OPEN_POSITIONS,
            MAX_DAILY_LOSS_USD,
            KELLY_FRACTION,
            MAX_RESOLUTION_HOURS,
            self.paper_mode,
        )
        logger.info(
            "  PM campaign: enabled=%s cap=$%.2f/%.0fmin max_res=%.1fh log=%s",
            self.pm_hourly_campaign_enabled,
            self.pm_campaign_budget.cap_usd,
            self.pm_campaign_budget.window_seconds / 60.0,
            self.pm_campaign_max_resolution_hours,
            self.pm_campaign_decision_log_path,
        )
        logger.info(
            "  Lane toggles: llm=%s wallet=%s lmsr=%s cross_platform=%s sum_violation=%s fast_flow_only=%s",
            self.enable_llm_signals,
            self.enable_wallet_flow,
            self.enable_lmsr,
            self.enable_cross_platform_arb,
            self.enable_sum_violation,
            self.fast_flow_only,
        )
        logger.info(f"  Max per trade: ${MAX_POSITION_USD}")
        logger.info(f"  Daily loss limit: ${MAX_DAILY_LOSS_USD}")
        logger.info(f"  Kelly fraction: {KELLY_FRACTION} (max {MAX_KELLY_FRACTION})")
        logger.info(f"  Scan interval: {SCAN_INTERVAL}s")
        logger.info(
            "  Fill tracker: %s | stale order age=%.1fh | report=%sh",
            "ON" if self.fill_tracker is not None else "OFF",
            MAX_ORDER_AGE_HOURS,
            FILL_REPORT_HOURS,
        )
        logger.info(
            "  Position merger: %s | auto_submit=%s | min_freed=$%.2f",
            "ON" if self.position_merger is not None else "OFF",
            AUTO_MERGE_POSITIONS,
            MIN_MERGE_FREED_USDC,
        )
        logger.info(f"  Platt calibration: A={PLATT_A}, B={PLATT_B}")
        if self.adaptive_platt.enabled:
            cal = self.adaptive_platt.summary()
            logger.info(
                "  Adaptive Platt: ON (winner=%s active=%s min=%d refit=%ss report=%s)",
                cal.get("selected_variant", "static"),
                cal.get("active_mode", cal.get("mode", "static")),
                ADAPTIVE_PLATT_MIN_SAMPLES,
                ADAPTIVE_PLATT_REFIT_SECONDS,
                cal.get("report_path", ADAPTIVE_PLATT_REPORT_PATH),
            )
        else:
            logger.info("  Adaptive Platt: OFF (static params preserved)")
        logger.info(
            "  Disagreement bands: confirmation<%.2f signal>%.2f reduce_size>%.2f wide>%.2f",
            DISAGREEMENT_CONFIRMATION_STD,
            DISAGREEMENT_SIGNAL_STD,
            DISAGREEMENT_REDUCE_SIZE_STD,
            DISAGREEMENT_WIDE_STD,
        )
        logger.info(
            "  Ensemble cost cap: $%.2f/day (fallback=Haiku-only, second_claude=%s)",
            ENSEMBLE_DAILY_COST_CAP_USD,
            ENSEMBLE_ENABLE_SECOND_CLAUDE,
        )
        logger.info(f"  Thresholds: YES={YES_THRESHOLD:.0%}, NO={NO_THRESHOLD:.0%}")
        logger.info(f"  Category filter: skip priority < {MIN_CATEGORY_PRIORITY}")
        if self.sum_violation_strategy is not None:
            logger.info(
                "  Sum violation: threshold=%.3f min_depth=$%.2f per_leg=$%.2f max_res=%.1fh",
                self.sum_violation_strategy.threshold,
                self.sum_violation_strategy.min_depth_usd,
                self.sum_violation_strategy.position_size_usd,
                self.sum_violation_strategy.max_resolution_hours,
            )
        if self.combinatorial_cfg is not None:
            logger.info(
                "  Combinatorial flags: A6(shadow=%s live=%s) B1(shadow=%s live=%s)",
                self.combinatorial_cfg.enable_a6_shadow,
                self.combinatorial_cfg.enable_a6_live,
                self.combinatorial_cfg.enable_b1_shadow,
                self.combinatorial_cfg.enable_b1_live,
            )
            logger.info(
                "  Combinatorial caps: max_leg=$%.2f arb_budget=$%.2f stale=%ss fill_timeout=%ss merge_min=$%.2f",
                self.combinatorial_cfg.max_notional_per_leg_usd,
                self.combinatorial_cfg.arb_budget_usd,
                self.combinatorial_cfg.stale_book_max_age_seconds,
                self.combinatorial_cfg.fill_timeout_seconds,
                self.combinatorial_cfg.merge_min_notional_usd,
            )
        self._startup_lane_health = self._build_startup_lane_health()
        self._log_lane_health_summary("startup", self._startup_lane_health)
        logger.info(f"  Database: {DB_FILE}")
        logger.info("=" * 60)

    def _mode_tag(self) -> str:
        return str(getattr(self, "runtime_mode", "paper" if getattr(self, "paper_mode", True) else "live")).upper()

    @staticmethod
    def _read_json_file(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _extract_launch_posture(runtime_truth: Mapping[str, Any]) -> str:
        summary = runtime_truth.get("summary")
        if isinstance(summary, Mapping):
            launch_posture = str(summary.get("launch_posture", "") or "").strip().lower()
            if launch_posture:
                return launch_posture
        launch = runtime_truth.get("launch")
        if isinstance(launch, Mapping):
            launch_posture = str(launch.get("posture", "") or "").strip().lower()
            if launch_posture:
                return launch_posture
        return str(runtime_truth.get("launch_posture", "") or "").strip().lower()

    def _evaluate_runtime_truth_guard(self) -> dict[str, Any]:
        runtime_truth_path = Path(
            os.environ.get("JJ_RUNTIME_TRUTH_PATH", "reports/runtime_truth_latest.json")
        ).expanduser()
        runtime_profile_path = Path(
            os.environ.get("JJ_RUNTIME_PROFILE_EFFECTIVE_PATH", "reports/runtime_profile_effective.json")
        ).expanduser()
        runtime_truth = self._read_json_file(runtime_truth_path)
        runtime_profile = self._read_json_file(runtime_profile_path)
        mode_payload = runtime_profile.get("mode") if isinstance(runtime_profile.get("mode"), Mapping) else {}

        launch_posture = self._extract_launch_posture(runtime_truth)
        paper_trading = mode_payload.get("paper_trading")
        if paper_trading is None:
            paper_trading = _bool_env("PAPER_TRADING", True)
        else:
            paper_trading = bool(paper_trading)

        order_submit_enabled = mode_payload.get("allow_order_submission")
        if order_submit_enabled is None:
            order_submit_enabled = _bool_env("JJ_ALLOW_ORDER_SUBMISSION", False)
        else:
            order_submit_enabled = bool(order_submit_enabled)

        force_live_attempt = _bool_env("JJ_FORCE_LIVE_ATTEMPT", False)

        agent_run_mode = str(
            os.environ.get("ELASTIFUND_AGENT_RUN_MODE")
            or runtime_truth.get("agent_run_mode")
            or runtime_profile.get("agent_run_mode")
            or ""
        ).strip().lower()

        posture_green = force_live_attempt or launch_posture in {"clear", "green", "unblocked"}
        paper_green = paper_trading is False
        mode_green = force_live_attempt or agent_run_mode in {"shadow", "micro_live", "live"}
        submit_green = order_submit_enabled is True
        greenlight = posture_green and paper_green and mode_green and submit_green

        reasons: list[str] = []
        if force_live_attempt:
            reasons.append("force_live_attempt=true")
        if not posture_green:
            reasons.append(f"launch_posture={launch_posture or 'unknown'}")
        if not paper_green:
            reasons.append(f"paper_trading={paper_trading}")
        if not mode_green:
            reasons.append(f"agent_run_mode={agent_run_mode or 'unknown'}")
        if not submit_green:
            reasons.append(f"order_submit_enabled={order_submit_enabled}")

        return {
            "greenlight": greenlight,
            "reason": ",".join(reasons) if reasons else "green",
            "runtime_truth_path": str(runtime_truth_path),
            "runtime_profile_path": str(runtime_profile_path),
            "launch_posture": launch_posture or "unknown",
            "paper_trading": paper_trading,
            "agent_run_mode": agent_run_mode or "unknown",
            "order_submit_enabled": order_submit_enabled,
        }

    def _refresh_runtime_truth_guard(self) -> None:
        if not bool(getattr(self, "enforce_runtime_truth_guard", False)):
            return
        guard = self._evaluate_runtime_truth_guard()
        self.runtime_truth_guard = guard
        if not guard.get("greenlight", False):
            self.allow_order_submission = False

    def _log_shadow_order_only(
        self,
        *,
        signal: Mapping[str, Any],
        market_id: str,
        side: str,
        reference_price: float,
        size_usd: float,
        reason: str,
    ) -> None:
        shadow_lifecycle = getattr(self, "shadow_order_lifecycle", None)
        if shadow_lifecycle is None:
            return
        order = shadow_lifecycle.place_synthetic_order(
            market_id=market_id,
            side=side,
            reference_price=float(reference_price),
            size_usd=float(size_usd),
            expected_fill_probability=_safe_float(signal.get("expected_maker_fill_probability"), 0.5),
            expected_fill_window_seconds=_safe_float(signal.get("expected_fill_window_seconds"), 30.0),
            metadata={
                "source": signal.get("source_combo", signal.get("source", "unknown")),
                "question": str(signal.get("question", "") or "")[:200],
                "reason": reason,
                "edge": _safe_float(signal.get("edge"), 0.0),
                "toxicity_state": signal.get("toxicity_state"),
                "route_score": _safe_float(signal.get("route_score"), None),
            },
        )
        if order is None:
            return
        logger.info(
            "  SHADOW ORDER LOGGED: %s market=%s side=%s size=$%.2f ttl=%ss reason=%s",
            order.order_id,
            order.market_id[:16],
            order.side,
            order.size_usd,
            int(order.ttl_seconds),
            reason,
        )

    def _llm_lane_enabled(self) -> bool:
        return bool(self.enable_llm_signals) and not bool(self.fast_flow_only)

    def _combinatorial_lane_enabled(self) -> bool:
        return not bool(self.fast_flow_only)

    def _execution_signal_guard_reason(
        self,
        signal: Mapping[str, Any],
        market_metadata: Mapping[str, Any] | None = None,
    ) -> str | None:
        """Return a blocking reason when a signal is unsafe for execution."""
        sources = set(extract_signal_source_components(signal))
        if not sources:
            fallback_source = canonical_source_key(str(signal.get("source", "") or ""))
            if fallback_source and fallback_source != "unknown":
                sources.add(fallback_source)

        reasoning = str(signal.get("reasoning", "") or "").strip().lower()
        fallback_mode = str(signal.get("fallback_mode", "") or "").strip().lower()
        if (
            "all ensemble model calls failed" in reasoning
            or "no ensemble models available" in reasoning
            or "failed to parse model response" in reasoning
            or fallback_mode in {"all_models_failed", "parse_failure", "no_models_available"}
        ):
            return "ensemble_failure_fallback"

        if not self.enable_llm_signals and sources == {"llm"}:
            return "llm_lane_disabled"

        if self.fast_flow_only:
            if sources == {"llm"}:
                return "fast_flow_llm_only"

            metadata = market_metadata if isinstance(market_metadata, Mapping) else {}
            question = str(signal.get("question") or metadata.get("question") or "")
            slug = str(signal.get("slug") or metadata.get("slug") or "")
            category = str(
                signal.get("category")
                or metadata.get("category")
                or ""
            ).strip().lower()
            if re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp)\b", f"{question} {slug}".lower()):
                category = "crypto"
            if category and category != "crypto":
                return "fast_flow_non_crypto"

            resolution_hours = _safe_float(
                signal.get("resolution_hours"),
                _safe_float(metadata.get("resolution_hours"), None),
            )
            if resolution_hours is None:
                return "fast_flow_unknown_resolution"
            if resolution_hours > MAX_RESOLUTION_HOURS:
                return "fast_flow_out_of_window"

        return None

    @staticmethod
    def _signal_wallet_metadata_value(signal: Mapping[str, Any], key: str) -> Any:
        direct = signal.get(key)
        if direct is not None:
            return direct
        metadata = signal.get("signal_metadata")
        if isinstance(metadata, Mapping):
            return metadata.get(key)
        return None

    @staticmethod
    def _signal_has_wallet_quality_fields(signal: Mapping[str, Any]) -> bool:
        for key in (
            "wallet_signal_age_seconds",
            "wallet_consensus_share",
            "wallet_consensus_notional_usd",
        ):
            if JJLive._signal_wallet_metadata_value(signal, key) is not None:
                return True
        return False

    def _wallet_quality_guard_reason(self, signal: Mapping[str, Any]) -> str | None:
        if not self._signal_has_wallet_quality_fields(signal):
            return None

        signal_age_seconds = _safe_float(
            self._signal_wallet_metadata_value(signal, "wallet_signal_age_seconds"),
            None,
        )
        consensus_share = _safe_float(
            self._signal_wallet_metadata_value(signal, "wallet_consensus_share"),
            None,
        )
        consensus_notional_usd = _safe_float(
            self._signal_wallet_metadata_value(signal, "wallet_consensus_notional_usd"),
            None,
        )

        if (
            signal_age_seconds is not None
            and signal_age_seconds > FAST_FLOW_WALLET_SIGNAL_STALE_SECONDS
        ):
            return "wallet_signal_stale"
        if (
            consensus_share is not None
            and consensus_share < FAST_FLOW_WALLET_MIN_CONSENSUS_SHARE
        ):
            return "wallet_consensus_low"
        if (
            consensus_notional_usd is not None
            and consensus_notional_usd < FAST_FLOW_WALLET_MIN_CONSENSUS_NOTIONAL_USD
        ):
            return "wallet_notional_low"
        return None

    @staticmethod
    def _parse_wallet_window_start(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        return _parse_iso8601_utc(str(value))

    async def _late_hydrate_wallet_signal_from_window(
        self,
        signal: dict[str, Any],
        market_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not signal_has_source(signal, "wallet_flow"):
            return None

        original_market_id = str(signal.get("market_id", "") or "").strip()
        window_start = self._parse_wallet_window_start(
            self._signal_wallet_metadata_value(signal, "wallet_window_start_ts")
        )
        window_minutes = int(
            _safe_float(
                self._signal_wallet_metadata_value(signal, "wallet_window_minutes"),
                0.0,
            )
        )
        if window_start is None or window_minutes <= 0:
            return None

        hydrated_markets, _stats = await self._fetch_recent_trade_hydrated_markets()
        if not hydrated_markets:
            return None

        best_match_id: str | None = None
        best_drift_seconds: float | None = None
        drift_tolerance_seconds = 120.0
        for market in hydrated_markets:
            question = str(market.get("question", "") or "")
            slug = str(market.get("slug", "") or "")
            if not looks_like_fast_flow_market(question):
                continue
            if not re.search(r"\b(bitcoin|btc)\b", f"{question} {slug}".lower()):
                continue
            end_ts = _parse_iso8601_utc(str(market.get("endDate", "") or ""))
            if end_ts is None:
                continue
            candidate_start = end_ts - timedelta(minutes=window_minutes)
            drift_seconds = abs((candidate_start - window_start).total_seconds())
            if drift_seconds > drift_tolerance_seconds:
                continue

            market_id = str(
                market.get("condition_id", market.get("conditionId", market.get("id", ""))) or ""
            ).strip()
            if not market_id:
                market_id = str(market.get("id", "") or "").strip()
            if not market_id:
                continue

            if best_drift_seconds is None or drift_seconds < best_drift_seconds:
                best_match_id = market_id
                best_drift_seconds = drift_seconds

        if not best_match_id:
            return None

        hydrated = market_lookup.get(best_match_id)
        if not isinstance(hydrated, dict):
            hydrated = await self._fetch_market_metadata_for_signal(best_match_id, market_lookup)
        if not isinstance(hydrated, dict):
            return None

        if original_market_id and original_market_id not in market_lookup:
            market_lookup[original_market_id] = hydrated
            self._elastic_market_lookup[str(original_market_id)] = dict(hydrated)
        signal.setdefault("wallet_hydration_source", "window_context")
        signal.setdefault("wallet_hydrated_market_id", best_match_id)
        return hydrated

    def _has_llm_credentials(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))

    def _wallet_flow_bootstrap_status(self) -> tuple[bool, str | None]:
        scores_path = Path(getattr(self, "wallet_flow_scores_file", Path("data/smart_wallets.json")))
        db_path = Path(getattr(self, "wallet_flow_db_file", Path("data/wallet_scores.db")))
        if wallet_flow_get_bootstrap_status is not None:
            try:
                status = wallet_flow_get_bootstrap_status(scores_path=scores_path, db_path=db_path)
            except Exception:
                status = None
            else:
                if status.ready:
                    return True, None
                if status.reasons:
                    return False, ",".join(str(reason) for reason in status.reasons)
                return False, "not_bootstrapped"
        if not scores_path.exists() or not db_path.exists():
            return False, "not_bootstrapped"
        try:
            with open(scores_path) as f:
                payload = json.load(f)
            wallets = payload.get("wallets", {}) if isinstance(payload, dict) else {}
            if not isinstance(wallets, dict) or not wallets:
                return False, "not_bootstrapped"
        except Exception:
            return False, "not_bootstrapped"
        return True, None

    def _configure_wallet_flow_paths(self) -> None:
        if wallet_flow_detector_module is None:
            return
        wallet_flow_detector_module.SCORES_FILE = Path(self.wallet_flow_scores_file)
        wallet_flow_detector_module.DB_FILE = Path(self.wallet_flow_db_file)

    def _maybe_initialize_wallet_flow_bootstrap(self) -> None:
        if not self.enable_wallet_flow or not getattr(self, "wallet_flow_module_available", False):
            return
        if wallet_flow_ensure_bootstrap is None:
            return

        wallet_ready, wallet_reason = self._wallet_flow_bootstrap_status()
        if wallet_ready:
            return

        logger.info(
            "Wallet flow bootstrap missing (%s) — attempting automatic rebuild",
            wallet_reason or "unknown",
        )
        try:
            status = wallet_flow_ensure_bootstrap(
                scores_path=self.wallet_flow_scores_file,
                db_path=self.wallet_flow_db_file,
            )
        except Exception as exc:
            logger.warning(f"Wallet flow bootstrap initialization failed (non-fatal): {exc}")
            return

        if status.ready:
            logger.info(
                "Wallet flow bootstrap ready with %d smart wallets",
                status.wallet_count,
            )
        else:
            logger.warning(
                "Wallet flow bootstrap still not ready: %s",
                ", ".join(status.reasons) if status.reasons else "unknown",
            )

    @staticmethod
    def _market_identifier(payload: dict[str, Any]) -> str:
        return str(
            payload.get("id")
            or payload.get("conditionId")
            or payload.get("condition_id")
            or payload.get("market_id")
            or ""
        ).strip()

    def _should_hydrate_recent_fast_markets(self, markets: list[dict[str, Any]]) -> bool:
        if not (self.fast_flow_only or self.enable_wallet_flow or self.enable_lmsr):
            return False

        max_hours = float(MAX_RESOLUTION_HOURS)
        for market in markets:
            question = str(market.get("question") or "")
            if not looks_like_fast_flow_market(question):
                continue
            end_dt = _parse_iso8601_utc(str(market.get("endDate") or market.get("end_date_iso") or ""))
            if end_dt is None:
                return False
            hours = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600.0
            if 0.0 < hours <= max_hours:
                return False
        return True

    async def _fetch_recent_trade_hydrated_markets(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        now = datetime.now(timezone.utc)
        timeout = httpx.Timeout(15.0, connect=15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    "https://data-api.polymarket.com/trades",
                    params={"limit": FAST_FLOW_RECENT_TRADES_LIMIT},
                )
                response.raise_for_status()
                payload = response.json()
                recent_trades = payload if isinstance(payload, list) else []

                recent_condition_ids: list[str] = []
                fast_market_titles: set[str] = set()
                for trade in recent_trades:
                    title = str(trade.get("title") or "")
                    if not looks_like_fast_flow_market(title):
                        continue
                    fast_market_titles.add(title)
                    condition_id = str(trade.get("conditionId") or "").strip()
                    if condition_id and condition_id not in recent_condition_ids:
                        recent_condition_ids.append(condition_id)
                    if len(recent_condition_ids) >= FAST_FLOW_HYDRATION_MAX_MARKETS:
                        break

                hydrated_payloads = await asyncio.gather(
                    *[
                        client.get(
                            "https://gamma-api.polymarket.com/markets",
                            params={"condition_ids": condition_id},
                        )
                        for condition_id in recent_condition_ids
                    ],
                    return_exceptions=True,
                )
        except Exception as exc:
            logger.warning("Recent fast-market hydration failed: %s", exc)
            return [], {
                "recent_trades_fetched": 0,
                "recent_market_hydrations": 0,
                "recent_fast_markets_seen": 0,
            }

        hydrated_markets: list[dict[str, Any]] = []
        max_hours = float(MAX_RESOLUTION_HOURS)
        for item in hydrated_payloads:
            if isinstance(item, Exception):
                continue
            try:
                item.raise_for_status()
            except Exception:
                continue
            market_payload = item.json()
            if not isinstance(market_payload, list) or not market_payload:
                continue
            market = market_payload[0]
            if not isinstance(market, dict):
                continue
            if bool(market.get("closed")):
                continue
            if not bool(market.get("acceptingOrders", True)):
                continue
            end_dt = _parse_iso8601_utc(str(market.get("endDate") or market.get("end_date_iso") or ""))
            if end_dt is None:
                continue
            hours = (end_dt - now).total_seconds() / 3600.0
            if hours <= 0.0 or hours > max_hours:
                continue
            hydrated_markets.append(market)

        return hydrated_markets, {
            "recent_trades_fetched": len(recent_trades),
            "recent_market_hydrations": len(hydrated_payloads),
            "recent_fast_markets_seen": len(fast_market_titles),
        }

    def _merge_markets(
        self,
        primary_markets: list[dict[str, Any]],
        supplemental_markets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_market_ids: set[str] = set()
        for market in list(primary_markets) + list(supplemental_markets):
            market_id = self._market_identifier(market)
            if not market_id or market_id in seen_market_ids:
                continue
            seen_market_ids.add(market_id)
            merged.append(market)
        return merged

    def _cross_platform_key_paths(self) -> list[Path]:
        configured = os.environ.get("KALSHI_RSA_KEY_PATH", "")
        candidates = [
            Path(__file__).resolve().parent / "kalshi" / "kalshi_rsa_private.pem",
        ]
        if configured:
            candidates.append(Path(configured).expanduser())
        candidates.extend(
            [
                Path.home() / "Desktop" / "Elastifund" / "bot" / "kalshi" / "kalshi_rsa_private.pem",
                Path.home() / "Desktop" / "Elastifund" / "kalshi" / "kalshi_rsa_private.pem",
            ]
        )
        deduped: list[Path] = []
        seen: set[Path] = set()
        for path in candidates:
            resolved = path.expanduser()
            if resolved in seen:
                continue
            seen.add(resolved)
            deduped.append(resolved)
        return deduped

    def _has_cross_platform_credentials(self) -> bool:
        return load_kalshi_credentials().configured

    @staticmethod
    def _lane_health_payload(
        status: str,
        *,
        reason: str | None = None,
        signals: int | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if reason:
            payload["reason"] = reason
        if signals is not None:
            payload["signals"] = int(signals)
        if detail:
            payload["detail"] = detail
        return payload

    def _build_startup_lane_health(self) -> dict[str, dict[str, Any]]:
        health: dict[str, dict[str, Any]] = {}

        if not self._llm_lane_enabled():
            health["llm"] = self._lane_health_payload("disabled", reason="disabled")
        elif self.analyzer is None or not self._has_llm_credentials():
            health["llm"] = self._lane_health_payload("not_ready", reason="no_credentials")
        else:
            health["llm"] = self._lane_health_payload("active")

        if not self.enable_wallet_flow:
            health["wallet_flow"] = self._lane_health_payload("disabled", reason="disabled")
        elif not getattr(self, "wallet_flow_module_available", False):
            health["wallet_flow"] = self._lane_health_payload("disabled", reason="unavailable")
        else:
            wallet_ready, wallet_reason = self._wallet_flow_bootstrap_status()
            if wallet_ready:
                health["wallet_flow"] = self._lane_health_payload("active")
            else:
                health["wallet_flow"] = self._lane_health_payload("not_ready", reason=wallet_reason)

        if not self.enable_lmsr:
            health["lmsr"] = self._lane_health_payload("disabled", reason="disabled")
        elif not getattr(self, "lmsr_module_available", False) or self.lmsr_engine is None:
            health["lmsr"] = self._lane_health_payload("disabled", reason="unavailable")
        else:
            health["lmsr"] = self._lane_health_payload("active")

        if not self.enable_cross_platform_arb:
            health["cross_platform_arb"] = self._lane_health_payload("disabled", reason="disabled")
        elif not getattr(self, "arb_module_available", False):
            health["cross_platform_arb"] = self._lane_health_payload("disabled", reason="unavailable")
        elif not self._has_cross_platform_credentials():
            health["cross_platform_arb"] = self._lane_health_payload("not_ready", reason="no_credentials")
        else:
            health["cross_platform_arb"] = self._lane_health_payload("active")

        combinatorial_enabled = bool(
            self.sum_violation_strategy is not None
            or (self.combinatorial_cfg is not None and self.combinatorial_cfg.any_enabled())
        )
        if not self._combinatorial_lane_enabled() or not combinatorial_enabled:
            health["combinatorial"] = self._lane_health_payload("disabled", reason="disabled")
        else:
            health["combinatorial"] = self._lane_health_payload("active")

        return health

    def _build_cycle_lane_health(
        self,
        *,
        llm_signals: list[dict],
        wallet_signals: list[dict],
        lmsr_signals: list[dict],
        arb_signals: list[dict],
        combinatorial_signals: list[dict],
        sum_violation_signals: list[dict],
        combinatorial_cycle: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        health = {
            lane: dict(payload)
            for lane, payload in self._build_startup_lane_health().items()
        }

        if health["llm"]["status"] == "active":
            health["llm"] = self._lane_health_payload(
                "active" if llm_signals else "idle",
                reason=None if llm_signals else "no_signals",
                signals=len(llm_signals),
            )

        if health["wallet_flow"]["status"] == "active":
            health["wallet_flow"] = self._lane_health_payload(
                "active" if wallet_signals else "idle",
                reason=None if wallet_signals else "no_signals",
                signals=len(wallet_signals),
            )

        if health["lmsr"]["status"] == "active":
            health["lmsr"] = self._lane_health_payload(
                "active" if lmsr_signals else "idle",
                reason=None if lmsr_signals else "no_signals",
                signals=len(lmsr_signals),
            )

        if health["cross_platform_arb"]["status"] == "active":
            health["cross_platform_arb"] = self._lane_health_payload(
                "active" if arb_signals else "idle",
                reason=None if arb_signals else "no_signals",
                signals=len(arb_signals),
            )

        if health["combinatorial"]["status"] == "active":
            comb_signal_count = len(combinatorial_signals) + len(sum_violation_signals)
            gate_health = combinatorial_cycle.get("metrics", {}).get("health", {})
            gate_blocked = bool(combinatorial_cycle.get("blocked", 0))
            if isinstance(gate_health, dict):
                gate_blocked = gate_blocked or any(
                    isinstance(payload, dict) and payload.get("status") == "blocked"
                    for payload in gate_health.values()
                )
            if gate_blocked:
                health["combinatorial"] = self._lane_health_payload(
                    "blocked",
                    reason="blocked_by_gate",
                    signals=comb_signal_count,
                )
            else:
                health["combinatorial"] = self._lane_health_payload(
                    "active" if comb_signal_count else "idle",
                    reason=None if comb_signal_count else "no_signals",
                    signals=comb_signal_count,
                )

        return health

    @staticmethod
    def _format_lane_health_summary(lane_health: dict[str, dict[str, Any]]) -> str:
        parts = []
        for lane, payload in lane_health.items():
            label = f"{lane}={payload.get('status', 'unknown')}"
            reason = payload.get("reason")
            if reason:
                label += f"({reason})"
            if "signals" in payload:
                label += f":{payload['signals']}"
            parts.append(label)
        return " | ".join(parts)

    def _log_lane_health_summary(
        self,
        stage: str,
        lane_health: dict[str, dict[str, Any]],
        *,
        cycle_num: int | None = None,
    ) -> None:
        self._last_lane_health = {
            lane: dict(payload)
            for lane, payload in lane_health.items()
        }
        suffix = f" cycle={cycle_num}" if cycle_num is not None else ""
        logger.info(
            "Lane health [%s%s]: %s",
            stage,
            suffix,
            self._format_lane_health_summary(lane_health),
        )

    @staticmethod
    def _hydrate_signal_market_context(signal: dict[str, Any], market_lookup: dict[str, dict[str, Any]]) -> None:
        market_id = str(signal.get("market_id", ""))
        market = market_lookup.get(market_id)
        if market is None and market_id:
            try:
                market = market_lookup.get(str(int(market_id)))
            except (TypeError, ValueError):
                market = None
        if not isinstance(market, dict):
            return

        signal.setdefault("question", market.get("question", ""))
        signal.setdefault("category", market.get("category", "unknown"))
        signal.setdefault("slug", market.get("slug", ""))
        signal.setdefault("market_gate_reason", market.get("market_gate_reason", "ok"))

        source = str(signal.get("source", "") or "")
        if source == "wallet_flow" or signal.get("market_price") in (None, 0, 0.0, 0.5):
            signal["market_price"] = market.get("yes_price", signal.get("market_price", 0.5))

        if signal.get("resolution_hours") in (None, 0, 0.0):
            signal["resolution_hours"] = market.get("resolution_hours")

        if (
            signal.get("velocity_score") in (None, 0, 0.0)
            and signal.get("edge") is not None
            and signal.get("resolution_hours") not in (None, 0, 0.0)
        ):
            signal["velocity_score"] = velocity_score(
                _safe_float(signal.get("edge"), 0.0),
                _safe_float(signal.get("resolution_hours"), 1.0),
            )

    async def _fetch_market_metadata_for_signal(
        self,
        market_id: str,
        market_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        market_id = str(market_id or "").strip()
        if not market_id:
            return None

        existing = market_lookup.get(market_id)
        if isinstance(existing, dict):
            return existing

        fetched_market: dict[str, Any] | None = None
        timeout = httpx.Timeout(10.0, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                fetch_attempts = (
                    (
                        "https://gamma-api.polymarket.com/markets",
                        {"condition_ids": market_id},
                    ),
                    (
                        f"https://gamma-api.polymarket.com/markets/{market_id}",
                        None,
                    ),
                )
                for url, params in fetch_attempts:
                    try:
                        response = await client.get(url, params=params)
                        response.raise_for_status()
                        payload = response.json()
                    except Exception:
                        continue

                    if isinstance(payload, list):
                        payload = payload[0] if payload else None
                    if isinstance(payload, dict):
                        fetched_market = payload
                        break
        except Exception as exc:
            logger.debug("Late market hydration failed for %s: %s", market_id[:16], exc)
            return None

        if not isinstance(fetched_market, dict):
            return None
        if bool(fetched_market.get("closed")):
            return None
        if not bool(fetched_market.get("acceptingOrders", True)):
            return None

        question = str(fetched_market.get("question", "") or "")
        slug = str(fetched_market.get("slug", "") or "").strip()
        raw_resolution_hours = estimate_resolution_hours(fetched_market) if MAX_RESOLUTION_HOURS > 0 else None
        allowed, filter_reason, category, llm_resolution_hours = apply_llm_market_filters(
            question,
            resolution_hours=raw_resolution_hours,
            slug=slug,
        )

        yes_price = None
        try:
            prices = self.scanner.extract_prices(fetched_market)
            yes_price = prices.get("YES", prices.get("yes", None))
        except Exception:
            pass

        if yes_price is None:
            raw_prices = fetched_market.get("outcomePrices", "")
            if isinstance(raw_prices, str) and raw_prices:
                try:
                    parsed = json.loads(raw_prices)
                    if isinstance(parsed, list) and len(parsed) >= 1:
                        yes_price = float(parsed[0])
                except (json.JSONDecodeError, ValueError):
                    yes_price = None
            elif isinstance(raw_prices, list) and len(raw_prices) >= 1:
                yes_price = float(raw_prices[0])

        if yes_price is None:
            yes_price = fetched_market.get("price", fetched_market.get("yes_price", None))
            if yes_price is not None:
                yes_price = float(yes_price)

        if yes_price is None or not (0.10 <= yes_price <= 0.90):
            return None

        token_ids = []
        try:
            token_ids = self.scanner.extract_token_ids(fetched_market)
        except Exception:
            pass
        token_ids = normalize_token_ids(token_ids)

        if not token_ids:
            token_ids = normalize_token_ids(fetched_market.get("clobTokenIds", ""))
        if not token_ids:
            return None

        primary_market_id = str(fetched_market.get("id", "") or "").strip()
        condition_market_id = str(
            fetched_market.get("condition_id", fetched_market.get("conditionId", fetched_market.get("market_id", "")))
            or ""
        ).strip()
        resolution_hours = (
            llm_resolution_hours
            if allowed and llm_resolution_hours is not None
            else raw_resolution_hours
        )
        market_payload = {
            "question": question,
            "slug": slug,
            "token_ids": token_ids,
            "yes_price": yes_price,
            "volume": float(fetched_market.get("volume", 0) or 0),
            "liquidity": float(fetched_market.get("liquidity", 0) or 0),
            "tags": fetched_market.get("tags", []) or [],
            "category": category,
            "resolution_hours": resolution_hours,
            "llm_allowed": allowed,
            "market_gate_reason": filter_reason if not allowed else "ok",
        }
        aliases = {
            market_id,
            primary_market_id,
            condition_market_id,
            str(fetched_market.get("market_id", "") or "").strip(),
        }
        aliases.discard("")
        if not aliases:
            return None

        for alias in aliases:
            market_lookup[alias] = market_payload
            self._elastic_market_lookup[str(alias)] = dict(market_payload)

        canonical_market_id = primary_market_id or condition_market_id or market_id
        for token_id in token_ids:
            clean_token = str(token_id).strip()
            if not clean_token:
                continue
            self._elastic_token_market_index[clean_token] = canonical_market_id
            if self.trade_stream is not None:
                self.trade_stream.add_token(clean_token)

        logger.info(
            "Late-hydrated market metadata for %s | %s",
            market_id[:16],
            question[:60],
        )
        return market_lookup.get(market_id, market_payload)

    async def _late_hydrate_signal_markets(
        self,
        signals: list[dict[str, Any]],
        market_lookup: dict[str, dict[str, Any]],
    ) -> None:
        for signal in signals:
            market_id = str(signal.get("market_id", "") or "").strip()
            if not market_id:
                continue
            if isinstance(market_lookup.get(market_id), dict):
                self._hydrate_signal_market_context(signal, market_lookup)
                continue
            hydrated = await self._fetch_market_metadata_for_signal(market_id, market_lookup)
            if hydrated is None:
                hydrated = await self._late_hydrate_wallet_signal_from_window(signal, market_lookup)
            if hydrated is not None:
                self._hydrate_signal_market_context(signal, market_lookup)

    async def _collect_cross_platform_arb_signals(
        self,
        market_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Collect cross-platform arb signals without nesting event loops."""
        if not self.arb_available:
            return []
        if not self._has_cross_platform_credentials():
            logger.info("Cross-platform arb skipped — no_credentials")
            return []

        try:
            if arb_get_signals_async is not None:
                arb_signals = await arb_get_signals_async()
            elif arb_get_signals is not None:
                arb_signals = await asyncio.to_thread(arb_get_signals)
            else:
                return []

            if arb_signals:
                logger.info("Cross-platform arb: %d signals", len(arb_signals))
            for signal in arb_signals:
                signal["source"] = "cross_platform_arb"
                self._hydrate_signal_market_context(signal, market_lookup)
                attach_signal_source_metadata(signal)
                signal["signal_sources"] = extract_signal_sources(signal)
                signal["signal_metadata"] = extract_signal_metadata(signal)
            return arb_signals
        except Exception as e:
            logger.warning(f"Cross-platform arb scan failed (non-fatal): {e}")
            return []

    def _init_telegram(self):
        """Initialize Telegram notifier (handles both class versions)."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "") or os.environ.get("TELEGRAM_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "") or os.environ.get("TELEGRAM_CHAT", "")

        if TelegramNotifier is None:
            logger.warning(
                "Telegram module not available — notifications disabled "
                "(token_configured=%s chat_configured=%s)",
                bool(token),
                bool(chat_id),
            )
            return _DummyNotifier()

        if not token or not chat_id:
            logger.info(
                "Telegram not configured — notifications disabled "
                "(token_configured=%s chat_configured=%s)",
                bool(token),
                bool(chat_id),
            )
            return _DummyNotifier()

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
                    logger.warning("Could not init Telegram — notifications disabled", exc_info=True)
                    return _DummyNotifier()

    def _write_startup_heartbeat(self) -> None:
        try:
            self.heartbeat_writer.mark_startup(
                profile_name=self.profile_name,
                runtime_mode=self.runtime_mode,
                paper_mode=self.paper_mode,
                scan_interval_seconds=SCAN_INTERVAL,
            )
        except Exception as exc:
            logger.warning("Heartbeat startup write failed: %s", exc)

    def _write_cycle_started_heartbeat(self, cycle_num: int) -> None:
        try:
            self.heartbeat_writer.mark_cycle_started(
                cycle_num,
                profile_name=self.profile_name,
                runtime_mode=self.runtime_mode,
                paper_mode=self.paper_mode,
                scan_interval_seconds=SCAN_INTERVAL,
            )
        except Exception as exc:
            logger.warning("Heartbeat cycle-start write failed: %s", exc)

    def _write_cycle_completed_heartbeat(self, summary: dict[str, Any]) -> None:
        try:
            heartbeat_summary = dict(summary)
            heartbeat_summary.setdefault(
                "lane_health",
                self._last_lane_health or self._startup_lane_health or self._build_startup_lane_health(),
            )
            self.heartbeat_writer.mark_cycle_completed(
                heartbeat_summary,
                profile_name=self.profile_name,
                runtime_mode=self.runtime_mode,
                paper_mode=self.paper_mode,
                scan_interval_seconds=SCAN_INTERVAL,
                total_trades=int(self.state.state.get("total_trades", 0)),
                trades_today=int(self.state.state.get("trades_today", 0)),
                open_positions=len(self.state.state.get("open_positions", {})),
            )
        except Exception as exc:
            logger.warning("Heartbeat cycle-complete write failed: %s", exc)

    def _write_cycle_error_heartbeat(self, message: str, *, cycle_num: int | None = None) -> None:
        try:
            self.heartbeat_writer.mark_cycle_error(
                message,
                cycle_number=cycle_num,
                profile_name=self.profile_name,
                runtime_mode=self.runtime_mode,
                paper_mode=self.paper_mode,
                scan_interval_seconds=SCAN_INTERVAL,
            )
        except Exception as exc:
            logger.warning("Heartbeat error write failed: %s", exc)

    def _safe_elastic_call(self, method_name: str, payload: dict[str, Any]) -> None:
        try:
            method = getattr(elastic_client, method_name, None)
            if callable(method):
                method(payload)
        except Exception as exc:
            logger.warning("Elastic telemetry failed (%s): %s", method_name, exc)

    def _record_signal_evaluation(
        self,
        *,
        signal_source: str,
        market_id: str,
        signal_value: float | None,
        confidence: float | None,
        acted_on: bool,
        reason_skipped: str | None = None,
        extra: dict[str, Any] | None = None,
        signal_payload: Mapping[str, Any] | None = None,
    ) -> None:
        attribution_payload: Mapping[str, Any]
        if isinstance(signal_payload, Mapping):
            attribution_payload = signal_payload
        else:
            attribution_payload = {
                "source": signal_source,
                "source_combo": signal_source,
                "signal_sources": normalize_source_components(signal_source),
            }

        source_components = extract_signal_source_components(attribution_payload)
        signal_sources = extract_signal_sources(attribution_payload) or list(source_components)
        source_combo = (
            str(attribution_payload.get("source_combo", "") or "").strip()
            or "+".join(source_components)
            or canonical_source_key(signal_source)
            or str(signal_source or "").strip()
            or "unknown"
        )
        payload = {
            "signal_source": signal_source,
            "source_combo": source_combo,
            "source_components": source_components,
            "signal_sources": signal_sources,
            "source_count": max(
                len(source_components),
                int(_safe_float(attribution_payload.get("source_count"), 0)),
                1 if source_combo and source_combo != "unknown" else 0,
            ),
            "market_id": str(market_id),
            "signal_value": signal_value,
            "confidence": confidence,
            "acted_on": acted_on,
        }
        signal_metadata = extract_signal_metadata(attribution_payload)
        if signal_metadata:
            payload["signal_metadata"] = signal_metadata
        if reason_skipped:
            payload["reason_skipped"] = reason_skipped
        if extra:
            payload.update(extra)
        self._safe_elastic_call("index_signal", payload)

    def _record_trade_telemetry(
        self,
        trade_record: dict[str, Any],
        *,
        fill_status: str,
        execution_stage: str,
    ) -> None:
        payload = dict(trade_record)
        payload["fill_status"] = fill_status
        payload["execution_stage"] = execution_stage
        self._safe_elastic_call("index_trade", payload)

    def _record_kill_telemetry(
        self,
        *,
        kill_rule: str,
        metric_value: float | None,
        threshold: float | None,
        action_taken: str,
        market_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "kill_rule": kill_rule,
            "market_id": str(market_id),
            "metric_value": metric_value,
            "threshold": threshold,
            "action_taken": action_taken,
        }
        if extra:
            payload.update(extra)
        self._safe_elastic_call("index_kill", payload)

    def _build_orderbook_snapshot(self, token_id: str) -> dict[str, Any] | None:
        if self.trade_stream is None:
            return None

        book = self.trade_stream.get_book(token_id)
        micro = self.trade_stream.get_microstructure(token_id)
        if book is None or micro is None:
            return None

        best_bid = book.bids[0].price if book.bids else None
        best_ask = book.asks[0].price if book.asks else None
        midpoint = book.midpoint
        spread_bps = None
        if best_bid is not None and best_ask is not None and midpoint > 0:
            spread_bps = ((best_ask - best_bid) / midpoint) * 10_000.0

        return {
            "market_id": self._elastic_token_market_index.get(token_id, token_id),
            "token_id": token_id,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_bps": spread_bps,
            "depth_5lvl_bid": sum(level.size for level in book.bids[:5]),
            "depth_5lvl_ask": sum(level.size for level in book.asks[:5]),
            "vpin": micro.get("vpin"),
            "ofi": micro.get("ofi"),
            "ofi_raw": micro.get("ofi_raw"),
            "flow_regime": micro.get("regime"),
            "midpoint": midpoint,
            "connection_mode": micro.get("connection_mode"),
        }

    def _emit_orderbook_snapshots(self) -> int:
        if self.trade_stream is None:
            return 0

        emitted = 0
        for token_id in list(getattr(self.trade_stream, "token_ids", [])):
            snapshot = self._build_orderbook_snapshot(str(token_id))
            if snapshot is None:
                continue
            self._safe_elastic_call("index_orderbook_snapshot", snapshot)
            emitted += 1
        return emitted

    async def _orderbook_snapshot_loop(self) -> None:
        while True:
            await asyncio.sleep(ELASTIC_ORDERBOOK_SNAPSHOT_INTERVAL_SECONDS)
            emitted = self._emit_orderbook_snapshots()
            if emitted:
                logger.debug("Elastic orderbook snapshots emitted: %d", emitted)

    async def _refresh_elastic_ml_state(self, *, force: bool = False) -> dict[str, Any]:
        """Poll Elastic ML results when configured and summarize active controls."""
        if self.anomaly_consumer is None:
            return {}

        try:
            records = await self.anomaly_consumer.poll_if_due(force=force)
            snapshot = self.anomaly_consumer.snapshot()
            if records:
                logger.info(
                    "Elastic ML: processed=%d paused=%d cautioned=%d flagged=%d",
                    len(records),
                    len(snapshot.get("paused_markets", [])),
                    len(snapshot.get("cautioned_markets", [])),
                    len(snapshot.get("flagged_signal_sources", [])),
                )
            if snapshot.get("flagged_signal_sources"):
                logger.warning(
                    "Elastic ML review flags active: %s",
                    ", ".join(snapshot["flagged_signal_sources"]),
                )
            return snapshot
        except Exception as e:
            logger.warning(f"Elastic ML refresh failed (non-fatal): {e}")
            return {}

    def _get_elastic_ml_feedback(self, market_id: str) -> dict[str, Any]:
        """Return best-effort Elastic ML control state for a market."""
        if self.anomaly_consumer is None:
            return {
                "market_id": str(market_id),
                "size_multiplier": 1.0,
                "score": 0.0,
                "jobs": [],
                "paused": False,
                "pause_reason": "",
            }

        try:
            return self.anomaly_consumer.get_market_feedback(str(market_id))
        except Exception as e:
            logger.warning(f"Elastic ML feedback lookup failed (non-fatal): {e}")
            return {
                "market_id": str(market_id),
                "size_multiplier": 1.0,
                "score": 0.0,
                "jobs": [],
                "paused": False,
                "pause_reason": "",
            }

    def _apply_elastic_ml_size_modifier(
        self,
        signal: dict[str, Any],
        *,
        market_id: str,
        size_usd: float,
    ) -> float:
        """Reduce size when Elastic ML has flagged toxic flow for the market."""
        feedback = self._get_elastic_ml_feedback(market_id)
        signal["elastic_ml_feedback"] = feedback

        size_multiplier = float(feedback.get("size_multiplier", 1.0) or 1.0)
        if size_multiplier >= 0.999:
            return size_usd

        adjusted = round(max(0.0, size_usd) * max(0.0, min(1.0, size_multiplier)), 2)
        signal["elastic_ml_modifier"] = size_multiplier
        signal["elastic_ml_score"] = feedback.get("score", 0.0)
        signal["elastic_ml_jobs"] = feedback.get("jobs", [])
        logger.warning(
            "Elastic ML caution: market=%s size=$%.2f->$%.2f score=%.1f jobs=%s",
            str(market_id)[:16],
            size_usd,
            adjusted,
            float(feedback.get("score", 0.0) or 0.0),
            ",".join(feedback.get("jobs", [])) or "none",
        )
        return adjusted

    def _record_pm_campaign_decision(
        self,
        *,
        cycle_num: int,
        signal: Mapping[str, Any],
        decision: str,
        reason_code: str,
        requested_usd: float | None,
        approved_usd: float | None,
        order_submitted: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        market_id = str(signal.get("market_id", "") or "")
        resolution_hours = _safe_float(signal.get("resolution_hours"), None)
        budget_snapshot = self.pm_campaign_budget.snapshot()
        payload = {
            "timestamp": now,
            "cycle": int(cycle_num),
            "market_id": market_id,
            "question": str(signal.get("question", "") or "")[:200],
            "direction": str(signal.get("direction", "") or ""),
            "decision": str(decision),
            "reason_code": str(reason_code),
            "requested_usd": _safe_float(requested_usd, 0.0),
            "approved_usd": _safe_float(approved_usd, 0.0),
            "order_submitted": bool(order_submitted),
            "resolution_hours": resolution_hours,
            "campaign_max_resolution_hours": float(self.pm_campaign_max_resolution_hours),
            "campaign_enabled": bool(self.pm_hourly_campaign_enabled),
            "budget_cap_usd": budget_snapshot["cap_usd"],
            "budget_used_usd": budget_snapshot["used_usd"],
            "budget_remaining_usd": budget_snapshot["remaining_usd"],
            "paper_mode": bool(self.paper_mode),
            "runtime_mode": str(self.runtime_mode),
            "allow_order_submission": bool(self.allow_order_submission),
        }
        self._pm_campaign_recent_decisions.append(payload)
        self._pm_campaign_recent_decisions = self._pm_campaign_recent_decisions[-200:]
        try:
            with self.pm_campaign_decision_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True))
                handle.write("\n")
        except OSError as e:
            logger.warning("PM campaign decision log write failed: %s", e)
        return payload

    def _check_pm_campaign_gate(
        self,
        *,
        signal: Mapping[str, Any],
        size_usd: float,
    ) -> tuple[bool, str]:
        if not self.pm_hourly_campaign_enabled:
            return True, "pm_campaign_disabled"
        if size_usd <= 0.0:
            return False, "pm_campaign_non_positive_notional"
        resolution_hours = _safe_float(signal.get("resolution_hours"), None)
        if resolution_hours is None:
            return False, "pm_campaign_resolution_unknown"
        if resolution_hours <= 0.0:
            return False, "pm_campaign_resolution_invalid"
        if (
            self.pm_campaign_max_resolution_hours > 0.0
            and resolution_hours > self.pm_campaign_max_resolution_hours
        ):
            return False, "pm_campaign_resolution_too_long"
        allowed, reason, _remaining = self.pm_campaign_budget.can_spend(size_usd)
        if not allowed:
            return False, reason
        return True, "pm_campaign_ok"

    def _pm_campaign_cycle_summary(self) -> dict[str, Any]:
        counter = Counter(
            str(item.get("reason_code", "unknown"))
            for item in self._pm_campaign_recent_decisions
        )
        accepted = sum(
            1 for item in self._pm_campaign_recent_decisions if str(item.get("decision")) == "accepted"
        )
        rejected = sum(
            1 for item in self._pm_campaign_recent_decisions if str(item.get("decision")) == "rejected"
        )
        return {
            "enabled": bool(self.pm_hourly_campaign_enabled),
            "max_resolution_hours": float(self.pm_campaign_max_resolution_hours),
            "budget": self.pm_campaign_budget.snapshot(),
            "accepted": accepted,
            "rejected": rejected,
            "reason_counts": dict(counter),
            "decision_log_path": str(self.pm_campaign_decision_log_path),
        }

    def _cancel_live_order(self, order_id: str) -> bool:
        """Cancel a live CLOB order, tolerating response shape differences."""
        if not order_id or self.clob is None:
            return False
        try:
            response = self.clob.cancel(order_id)
            if isinstance(response, dict):
                if response.get("error"):
                    return False
                if response.get("success") is False:
                    return False
            return True
        except Exception:
            return False

    @track_latency("place_order")
    async def place_order(
        self,
        *,
        signal: dict[str, Any],
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        order_price: float,
        order_size: float,
        size_usd: float,
        category: str,
        trade_record: dict[str, Any],
        order_metadata: dict[str, Any],
    ) -> bool:
        strategy = str(signal.get("source", "jj_live"))
        with capture_span(
            "order_placement",
            span_type="trading.execution",
            labels={
                "market_id": market_id,
                "strategy": strategy,
                "paper_mode": self.paper_mode,
            },
        ):
            if not getattr(self, "allow_order_submission", True):
                self._log_shadow_order_only(
                    signal=signal,
                    market_id=market_id,
                    side=str(signal.get("direction", "") or "").lower(),
                    reference_price=order_price,
                    size_usd=size_usd,
                    reason=str(getattr(self, "runtime_truth_guard", {}).get("reason", "runtime_blocked")),
                )
                logger.info(
                    "  SKIP order submission blocked by runtime mode (%s): %s",
                    getattr(self, "runtime_mode", "unknown"),
                    signal.get("question", "")[:50],
                    extra=ecs_extra(market_id=market_id, strategy=strategy),
                )
                return False

            if self.paper_mode:
                paper_order_id = f"paper-{uuid.uuid4().hex[:8]}"
                trade_record["order_id"] = paper_order_id

                trade_id = self.db.log_trade(trade_record)
                self._record_trade_telemetry(
                    {
                        **trade_record,
                        "trade_id": trade_id,
                        "order_price": order_price,
                        "order_size": order_size,
                    },
                    fill_status="filled",
                    execution_stage="paper_trade",
                )

                if self.fill_tracker is not None:
                    self.fill_tracker.record_order(
                        order_id=paper_order_id,
                        trade_id=trade_id,
                        market_id=market_id,
                        token_id=token_id,
                        question=signal["question"],
                        category=category,
                        side=side,
                        direction=signal["direction"],
                        price=order_price,
                        size=order_size,
                        size_usd=size_usd,
                        order_type="maker",
                        paper=True,
                        metadata=order_metadata,
                    )
                    self.fill_tracker.record_fill(
                        order_id=paper_order_id,
                        trade_id=trade_id,
                        market_id=market_id,
                        token_id=token_id,
                        fill_price=price,
                        fill_size=order_size,
                        fill_size_usd=size_usd,
                        latency_seconds=0.0,
                        cumulative_size_matched=order_size,
                        status="filled",
                    )

                self.multi_sim.simulate_trade(signal, trade_id)
                self.state.record_trade(
                    market_id=market_id,
                    question=signal["question"],
                    direction=signal["direction"],
                    price=price,
                    size_usd=size_usd,
                    edge=signal["edge"],
                    confidence=signal["confidence"],
                    order_id=paper_order_id,
                    source=trade_record.get("source", ""),
                    source_combo=trade_record.get("source_combo", ""),
                    source_components=trade_record.get("source_components", []),
                    source_count=int(_safe_float(trade_record.get("source_count", 0), 0)),
                    signal_sources=list(trade_record.get("signal_sources") or []),
                    signal_metadata=dict(trade_record.get("signal_metadata") or {}),
                )

                logger.info(
                    "  PAPER TRADE LOGGED: %s (db: %s)",
                    paper_order_id,
                    trade_id,
                    extra=ecs_extra(
                        market_id=market_id,
                        strategy=strategy,
                        order_id=paper_order_id,
                        trade_id=trade_id,
                    ),
                )

                try:
                    if self.signal_dedup.should_notify(market_id, signal["direction"]):
                        conf_tag = " [CONFIRMED]" if signal.get("_confirmation") else ""
                        await self.notifier.send_message(
                            f"JJ PAPER TRADE{conf_tag}\n"
                            f"{signal['direction'].upper()} ${size_usd:.2f}\n"
                            f"{signal['question'][:60]}\n"
                            f"Edge: {signal['edge']:.1%} | Price: {price:.3f}\n"
                            f"Source: {trade_record.get('source_combo', strategy)} | Cat: {category}\n"
                            f"ID: {paper_order_id}"
                        )
                    else:
                        logger.debug(
                            "Dedup suppressed notification: %s %s",
                            market_id[:16],
                            signal["direction"],
                            extra=ecs_extra(market_id=market_id, strategy=strategy),
                        )
                except Exception:
                    pass

                return True

            use_post_only = True
            min_order_size = clob_min_order_size(order_price, min_shares=POLY_MIN_ORDER_SHARES)
            if order_size < min_order_size:
                logger.info(
                    "  SKIP (%.2f shares / $%.2f below live min %.2f shares / $%.2f): %s",
                    order_size,
                    order_size * order_price,
                    min_order_size,
                    _CLOB_HARD_MIN_NOTIONAL_USD,
                    signal.get("question", "")[:50],
                    extra=ecs_extra(market_id=market_id, strategy=strategy),
                )
                return False

            try:
                order_args = OrderArgs(
                    token_id=token_id,
                    price=order_price,
                    size=order_size,
                    side=BUY,
                )
                signed_order = self.clob.create_order(order_args)
                result = self.clob.post_order(
                    signed_order,
                    OrderType.GTC,
                    post_only=use_post_only,
                )

                order_id = ""
                if isinstance(result, dict):
                    order_id = result.get("orderID", result.get("id", ""))
                    success = not result.get("error")
                else:
                    success = bool(result)

                if success and order_id:
                    logger.info(
                        "  ORDER PLACED: %s",
                        order_id,
                        extra=ecs_extra(
                            market_id=market_id,
                            strategy=strategy,
                            order_id=order_id,
                            order_size=order_size,
                            order_price=order_price,
                        ),
                    )
                    self._record_trade_telemetry(
                        {
                            **trade_record,
                            "order_id": order_id,
                            "order_price": order_price,
                            "order_size": order_size,
                        },
                        fill_status="posted",
                        execution_stage="live_order_posted",
                    )
                    if self.fill_tracker is not None:
                        self.fill_tracker.record_order(
                            order_id=order_id,
                            market_id=market_id,
                            token_id=token_id,
                            question=signal["question"],
                            category=category,
                            side=side,
                            direction=signal["direction"],
                            price=order_price,
                            size=order_size,
                            size_usd=size_usd,
                            order_type="maker",
                            metadata=order_metadata,
                        )

                    try:
                        res_h = signal.get("resolution_hours")
                        res_str = f"{res_h:.1f}h" if res_h else "?"
                        vel = signal.get("velocity_score", 0)
                        conf_tag = " [CONFIRMED]" if signal.get("_confirmation") else ""
                        fill_line = (
                            self.fill_tracker.format_fill_rate_line(hours=FILL_REPORT_HOURS)
                            if self.fill_tracker is not None
                            else "Fill rate last 24h: n/a"
                        )
                        await self.notifier.send_message(
                            f"JJ LIVE ORDER POSTED{conf_tag}\n"
                            f"{signal['direction'].upper()} ${size_usd:.2f}\n"
                            f"{signal['question'][:60]}\n"
                            f"Edge: {signal['edge']:.1%} | Price: {price:.3f}\n"
                            f"Resolves: {res_str} | Velocity: {vel:.0f}\n"
                            f"Source: {strategy} | Cat: {category} | Fee: {signal['taker_fee']:.4f}\n"
                            f"{fill_line}\n"
                            f"Order: {order_id[:16]}..."
                        )
                    except Exception:
                        pass

                    return True

                if success:
                    logger.warning(
                        "  ORDER ACKNOWLEDGED WITHOUT ID: %s",
                        result,
                        extra=ecs_extra(market_id=market_id, strategy=strategy),
                    )
                    return False

                err_msg = result.get("error", str(result)) if isinstance(result, dict) else str(result)
                logger.warning(
                    "  ORDER FAILED: %s",
                    err_msg,
                    extra=ecs_extra(market_id=market_id, strategy=strategy),
                )
                return False

            except Exception as e:
                logger.error(
                    "  ORDER ERROR: %s",
                    e,
                    extra=ecs_extra(market_id=market_id, strategy=strategy),
                )
                try:
                    await self.notifier.send_error(str(e), context="place_order")
                except Exception:
                    pass
                return False

    @track_latency("order_to_fill")
    async def _record_live_fill(self, fill_event: "OrderFillEvent") -> None:
        """Translate a detected maker fill into a trade record and state update."""
        get_apm_runtime().record_metric(
            "order_to_fill_ms",
            float(fill_event.latency_seconds) * 1000.0,
            labels={"market_id": fill_event.market_id},
        )
        metadata = fill_event.metadata if isinstance(fill_event.metadata, dict) else {}
        trade_record = dict(metadata.get("trade_record") or {})
        signal_context = dict(metadata.get("signal_context") or {})
        trade_record.update(
            {
                "market_id": fill_event.market_id,
                "question": fill_event.question or trade_record.get("question", ""),
                "direction": fill_event.direction or trade_record.get("direction", ""),
                "entry_price": fill_event.fill_price,
                "position_size_usd": fill_event.fill_size_usd,
                "category": fill_event.category or trade_record.get("category", "unknown"),
                "token_id": fill_event.token_id or trade_record.get("token_id", ""),
                "order_id": fill_event.order_id,
            }
        )
        trade_id = self.db.log_trade(trade_record)
        self._record_trade_telemetry(
            {
                **trade_record,
                "trade_id": trade_id,
                "latency_seconds": fill_event.latency_seconds,
                "fill_price": fill_event.fill_price,
                "fill_size": fill_event.fill_size,
            },
            fill_status="filled",
            execution_stage="fill_detected",
        )
        if self.fill_tracker is not None:
            self.fill_tracker.attach_trade_id(fill_event.order_id, trade_id)

        signal_for_sim = {
            "edge": _safe_float(signal_context.get("edge"), _safe_float(trade_record.get("edge"), 0.0)),
            "market_price": _safe_float(
                signal_context.get("market_price"),
                fill_event.order_price if fill_event.order_price is not None else fill_event.fill_price,
            ),
            "direction": trade_record.get("direction", fill_event.direction),
            "_kelly_override": signal_context.get("_kelly_override"),
        }
        try:
            self.multi_sim.simulate_trade(signal_for_sim, trade_id)
        except Exception as e:
            logger.debug("Multi-bankroll fill simulation failed: %s", e)

        self.state.record_trade(
            market_id=fill_event.market_id,
            question=trade_record.get("question", fill_event.question),
            direction=trade_record.get("direction", fill_event.direction),
            price=fill_event.fill_price,
            size_usd=fill_event.fill_size_usd,
            edge=_safe_float(trade_record.get("edge"), 0.0),
            confidence=_safe_float(trade_record.get("confidence"), 0.5),
            order_id=fill_event.order_id,
            source=str(trade_record.get("source", "") or ""),
            source_combo=str(trade_record.get("source_combo", "") or ""),
            source_components=list(trade_record.get("source_components") or []),
            source_count=int(_safe_float(trade_record.get("source_count", 0), 0)),
            signal_sources=list(trade_record.get("signal_sources") or []),
            signal_metadata=dict(trade_record.get("signal_metadata") or {}),
        )
        logger.info(
            "FILL DETECTED: order=%s market=%s size=%.4f price=%.3f latency=%.1fs",
            fill_event.order_id[:16],
            fill_event.market_id,
            fill_event.fill_size,
            fill_event.fill_price,
            fill_event.latency_seconds,
            extra=ecs_extra(
                market_id=fill_event.market_id,
                strategy="fill_detection",
                order_id=fill_event.order_id,
                latency_seconds=fill_event.latency_seconds,
            ),
        )
        try:
            fill_line = (
                self.fill_tracker.format_fill_rate_line(hours=FILL_REPORT_HOURS)
                if self.fill_tracker is not None
                else "Fill rate last 24h: n/a"
            )
            await self.notifier.send_message(
                f"JJ LIVE FILL\n"
                f"{trade_record.get('direction', fill_event.direction).upper()} ${fill_event.fill_size_usd:.2f}\n"
                f"{trade_record.get('question', fill_event.question)[:60]}\n"
                f"Fill: {fill_event.fill_size:.2f} @ {fill_event.fill_price:.3f}\n"
                f"Latency: {fill_event.latency_seconds / 60:.1f}m\n"
                f"{fill_line}"
            )
        except Exception:
            pass

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

    async def _execute_sum_violation_signals(self, signals: list[dict]) -> tuple[int, dict[str, str]]:
        """Place maker orders for multi-leg sum-violation baskets."""
        if not signals:
            return 0, {}
        if not getattr(self, "allow_order_submission", True):
            return 0, {
                str(signal.get("signal_id") or signal.get("violation_id") or ""): "blocked_mode"
                for signal in signals
                if signal.get("signal_id") or signal.get("violation_id")
            }
        if not self.paper_mode and (self.clob is None or OrderArgs is None or OrderType is None or BUY is None):
            return 0, {
                str(signal.get("signal_id") or signal.get("violation_id") or ""): "order_failed"
                for signal in signals
                if signal.get("signal_id") or signal.get("violation_id")
            }

        orders_placed = 0
        action_map: dict[str, str] = {}
        per_leg_usd = min(MAX_POSITION_USD, 0.50)

        for signal in signals:
            signal_id = str(signal.get("signal_id") or signal.get("violation_id") or "")
            legs = signal.get("sum_violation_legs") or []
            if not signal_id or not isinstance(legs, list) or not legs:
                if signal_id:
                    action_map[signal_id] = "killed_by_filter"
                continue

            active_slots = len(self.state.state["open_positions"]) + self.state.count_active_linked_baskets()
            if active_slots + len(legs) > MAX_OPEN_POSITIONS:
                action_map[signal_id] = "killed_by_filter"
                continue
            if not self.state.check_exposure_limit():
                action_map[signal_id] = "killed_by_filter"
                continue
            if any(self.state.has_position(str(leg.get("market_id", ""))) for leg in legs):
                action_map[signal_id] = "killed_by_filter"
                continue

            basket_successes = 0
            for leg in legs:
                market_id = str(leg.get("market_id") or "").strip()
                token_id = str(leg.get("token_id") or "").strip()
                outcome = str(leg.get("outcome") or market_id).strip()
                price = _safe_float(leg.get("limit_price"), 0.0)
                order_price = round(price, 2)
                if not market_id or not token_id or not (0.0 < price < 1.0) or not (0.0 < order_price < 1.0):
                    continue

                size_usd = min(per_leg_usd, _safe_float(leg.get("position_size_usd"), per_leg_usd))
                if size_usd <= 0.0:
                    continue
                shares = clob_order_size_for_usd(size_usd, order_price)
                min_order_size = clob_min_order_size(order_price, min_shares=POLY_MIN_ORDER_SHARES)
                if shares < min_order_size:
                    bumped_usd = round(min_order_size * order_price, 2)
                    if bumped_usd > MAX_POSITION_USD * 2:
                        logger.info(
                            "  SKIP sum-violation leg (%.2f shares / $%.2f below live min %.2f shares / $%.2f): %s",
                            shares,
                            shares * order_price,
                            min_order_size,
                            _CLOB_HARD_MIN_NOTIONAL_USD,
                            outcome,
                        )
                        continue
                    shares = min_order_size
                    size_usd = bumped_usd
                else:
                    size_usd = round(shares * order_price, 2)
                direction = "buy_yes" if str(leg.get("quote_side")).upper() == "YES" else "buy_no"
                category = str(leg.get("category") or "unknown")
                leg_signal = {
                    "market_id": market_id,
                    "question": f"{signal.get('question', '')} - {outcome}",
                    "direction": direction,
                    "edge": _safe_float(signal.get("edge"), 0.0),
                    "confidence": _safe_float(signal.get("confidence"), 0.95),
                    "reasoning": signal.get("reasoning", ""),
                    "estimated_prob": price,
                    "raw_prob": price,
                    "calibrated_prob": price,
                    "taker_fee": 0.0,
                    "source": signal.get("source", "sum_violation"),
                    "strategy_type": signal.get("strategy_type", "combinatorial"),
                    "relation_type": signal.get("relation_type", "same_event_sum"),
                }
                trade_record = build_trade_record(
                    leg_signal,
                    market_id=market_id,
                    category=category,
                    entry_price=price,
                    position_size_usd=size_usd,
                    token_id=token_id,
                )

                if self.paper_mode:
                    order_id = f"paper-sumv-{uuid.uuid4().hex[:8]}"
                    trade_record["order_id"] = order_id
                    trade_id = self.db.log_trade(trade_record)
                    self._record_trade_telemetry(
                        {**trade_record, "trade_id": trade_id, "order_size": shares},
                        fill_status="filled",
                        execution_stage="paper_sum_violation",
                    )
                    self.multi_sim.simulate_trade(leg_signal, trade_id)
                    self.state.record_trade(
                        market_id=market_id,
                        question=leg_signal["question"],
                        direction=direction,
                        price=price,
                        size_usd=size_usd,
                        edge=leg_signal["edge"],
                        confidence=leg_signal["confidence"],
                        order_id=order_id,
                        source=trade_record.get("source", ""),
                        source_combo=trade_record.get("source_combo", ""),
                        source_components=trade_record.get("source_components", []),
                        source_count=int(_safe_float(trade_record.get("source_count", 0), 0)),
                        signal_sources=list(trade_record.get("signal_sources") or []),
                        signal_metadata=dict(trade_record.get("signal_metadata") or {}),
                    )
                    basket_successes += 1
                    orders_placed += 1
                    continue

                min_order_size = clob_min_order_size(order_price, min_shares=POLY_MIN_ORDER_SHARES)
                if shares < min_order_size:
                    logger.info(
                        "  SKIP sum-viol leg (%.2f shares / $%.2f below live min %.2f shares / $%.2f): %s",
                        shares,
                        shares * order_price,
                        min_order_size,
                        _CLOB_HARD_MIN_NOTIONAL_USD,
                        outcome,
                    )
                    continue

                try:
                    order_args = OrderArgs(
                        token_id=token_id,
                        price=order_price,
                        size=shares,
                        side=BUY,
                    )
                    signed_order = self.clob.create_order(order_args)
                    result = self.clob.post_order(
                        signed_order,
                        OrderType.GTC,
                        post_only=True,
                    )
                    order_id = ""
                    success = False
                    if isinstance(result, dict):
                        order_id = result.get("orderID", result.get("id", ""))
                        success = not result.get("error")
                    else:
                        success = bool(result)

                    if not success:
                        logger.warning(
                            "SUM-VIOL order failed: event=%s leg=%s result=%s",
                            signal.get("event_id", ""),
                            market_id,
                            result,
                        )
                        continue

                    if not order_id:
                        logger.warning(
                            "SUM-VIOL order acknowledged without id: event=%s leg=%s result=%s",
                            signal.get("event_id", ""),
                            market_id,
                            result,
                        )
                        continue

                    trade_record["order_id"] = order_id
                    self._record_trade_telemetry(
                        {**trade_record, "order_size": shares},
                        fill_status="posted",
                        execution_stage="live_sum_violation_posted",
                    )
                    if self.fill_tracker is not None:
                        self.fill_tracker.record_order(
                            order_id=order_id,
                            market_id=market_id,
                            token_id=token_id,
                            question=leg_signal["question"],
                            category=category,
                            side="BUY",
                            direction=direction,
                            price=order_price,
                            size=shares,
                            size_usd=size_usd,
                            order_type="maker",
                            metadata={
                                "trade_record": dict(trade_record),
                                "signal_context": {
                                    "edge": leg_signal.get("edge", 0.0),
                                    "market_price": leg_signal.get("market_price", order_price),
                                    "direction": leg_signal.get("direction", direction),
                                },
                            },
                        )
                    basket_successes += 1
                    orders_placed += 1
                except Exception as e:
                    logger.warning(
                        "SUM-VIOL order error: event=%s leg=%s error=%s",
                        signal.get("event_id", ""),
                        market_id,
                        e,
                    )

                await asyncio.sleep(0.1)

            if basket_successes == len(legs):
                action_map[signal_id] = "traded"
            elif basket_successes > 0:
                action_map[signal_id] = "partial_execution"
            else:
                action_map[signal_id] = "order_failed"

            if basket_successes > 0:
                try:
                    await self.notifier.send_message(
                        "SUM VIOLATION {mode}\n{event}\nSide: {side}\nViolation: {violation:.3f}\nOrders: {filled}/{total}".format(
                            mode=self._mode_tag(),
                            event=signal.get("question", "")[:100],
                            side=signal.get("trade_side", ""),
                            violation=_safe_float(signal.get("details", {}).get("violation_amount"), 0.0),
                            filled=basket_successes,
                            total=len(legs),
                        )
                    )
                except Exception:
                    pass

        return orders_placed, action_map

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
            trade_record = {
                "market_id": basket.event_id,
                "question": f"A-6 basket {basket.basket_id[:16]}",
                "direction": "buy_yes_basket",
                "price": sum(leg.avg_fill_price for leg in basket.filled_legs) / max(1, len(basket.filled_legs)),
                "size_usd": basket.filled_notional_usd,
                "edge": basket.theoretical_edge,
                "confidence": 1.0,
                "order_id": basket.basket_id,
                "source": "a6",
            }
            trade_id = self.db.log_trade(trade_record)
            self._record_trade_telemetry(
                {**trade_record, "trade_id": trade_id},
                fill_status="filled",
                execution_stage="a6_basket_complete",
            )
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
        vpin_value = None
        if self.trade_stream is not None:
            try:
                vpin_value = self.trade_stream.vpin.get_vpin(token_id)
            except Exception:
                vpin_value = None
        self._record_signal_evaluation(
            signal_source="vpin",
            market_id=self._elastic_token_market_index.get(token_id, token_id),
            signal_value=vpin_value,
            confidence=max(0.0, min(1.0, 1.0 - abs((vpin_value or 0.5) - 0.5) * 2.0)),
            acted_on=new_regime.value != "toxic",
            reason_skipped="toxic_flow" if new_regime.value == "toxic" else None,
            extra={"token_id": token_id, "previous_regime": prev_regime.value, "new_regime": new_regime.value},
        )
        if new_regime.value == "toxic":
            logger.warning(f"TOXIC FLOW detected on {token_id[:12]}... — should pull maker quotes")
            # In live mode, cancel resting orders on this token
            if self.clob and not self.paper_mode:
                try:
                    self.clob.cancel_all()
                    logger.info("Cancelled all resting orders due to toxic flow")
                except Exception as e:
                    logger.error(f"Failed to cancel orders on toxic flow: {e}")

    def _on_ofi_update(self, token_id: str, ofi_snapshot) -> None:
        self._record_signal_evaluation(
            signal_source="ofi",
            market_id=self._elastic_token_market_index.get(token_id, token_id),
            signal_value=_safe_float(getattr(ofi_snapshot, "normalized_ofi", None), None),
            confidence=max(
                0.0,
                min(
                    1.0,
                    abs(_safe_float(getattr(ofi_snapshot, "normalized_ofi", 0.0), 0.0))
                    / max(getattr(self.trade_stream.ofi, "RATIO_THRESHOLD", 1.0), 1e-9),
                ),
            )
            if self.trade_stream is not None
            else 0.0,
            acted_on=True,
            extra={
                "token_id": token_id,
                "raw_ofi": _safe_float(getattr(ofi_snapshot, "raw_ofi", None), None),
                "levels_used": getattr(ofi_snapshot, "levels_used", None),
                "directional_skew": _safe_float(getattr(ofi_snapshot, "directional_skew", None), None),
            },
        )

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
            "ofi_raw": strongest_ofi.get("ofi_raw"),
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
        self._record_signal_evaluation(
            signal_source="ofi",
            market_id=str(signal.get("market_id", "")),
            signal_value=_safe_float(micro.get("ofi"), None),
            confidence=max(
                0.0,
                min(
                    1.0,
                    abs(_safe_float(micro.get("ofi"), 0.0))
                    / max(
                        getattr(getattr(self.trade_stream, "ofi", None), "RATIO_THRESHOLD", 1.0),
                        1e-9,
                    ),
                ),
            )
            if self.trade_stream is not None
            else 0.0,
            acted_on=True,
            extra={
                "question": signal.get("question", ""),
                "token_ids": micro.get("tokens", []),
                "raw_ofi": micro.get("ofi_raw"),
                "directional_skew": micro.get("ofi_skew"),
                "vpin_estimate": micro.get("vpin"),
            },
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

        signature_type = parse_signature_type(os.environ.get("JJ_CLOB_SIGNATURE_TYPE", "1"), default=1)
        try:
            client, _, _ = build_authenticated_clob_client(
                private_key=private_key,
                safe_address=safe_address,
                configured_signature_type=signature_type,
                logger=logger,
            )
        except Exception as e:
            logger.error(f"Failed to get L2 API credentials: {e}")
            sys.exit(1)

        try:
            client.get_orders()
            logger.info("CLOB auth verified — orders endpoint accessible")
        except Exception as e:
            logger.warning(f"Auth verification warning: {e}")

        return client

    @apm_transaction("signal_evaluation_cycle", transaction_type="trading")
    async def run_cycle(self) -> dict:
        """Run one scan → analyze → trade cycle.

        Returns:
            Cycle summary dict.
        """
        cycle_start = time.time()
        cycle_num = self.state.state["cycles_completed"] + 1
        get_apm_runtime().set_labels(
            {
                "cycle": cycle_num,
                "paper_mode": self.paper_mode,
            }
        )
        logger.info(
            "=== JJ Cycle %s starting ===",
            cycle_num,
            extra=ecs_extra(strategy="jj_live", cycle=cycle_num, paper_mode=self.paper_mode),
        )
        self._write_cycle_started_heartbeat(cycle_num)
        self._refresh_runtime_truth_guard()
        shadow_lifecycle = getattr(self, "shadow_order_lifecycle", None)
        if shadow_lifecycle is not None:
            shadow_lifecycle.expire()

        # Sync resolved positions: remove closed trades from state to free
        # position slots.  Without this, open_positions grows forever and
        # the bot stops at MAX_OPEN_POSITIONS.
        try:
            synced = self.state.sync_resolved_positions(self.db)
            if synced > 0:
                logger.info(f"Cleared {synced} resolved positions")
                if self.adaptive_platt.enabled:
                    changed = self.adaptive_platt.refresh(force=False)
                    cal = self.adaptive_platt.summary()
                    if changed:
                        logger.info(
                            "Adaptive Platt refit after resolution sync: winner=%s active=%s A=%.6f B=%.6f samples=%d rows=%d",
                            cal.get("selected_variant", "static"),
                            cal.get("active_mode", cal.get("mode", "static")),
                            cal["a"],
                            cal["b"],
                            cal["samples"],
                            cal.get("last_refit_rows", 0),
                        )
        except Exception as e:
            logger.warning(f"Position sync failed (non-fatal): {e}")

        # Safety check: daily loss limit
        if not self.state.check_daily_loss_limit():
            logger.warning(f"DAILY LOSS LIMIT HIT: ${self.state.state['daily_pnl']:.2f}")
            self._record_kill_telemetry(
                kill_rule="daily_loss",
                metric_value=_safe_float(self.state.state.get("daily_pnl"), 0.0),
                threshold=-abs(MAX_DAILY_LOSS_USD),
                action_taken="pause_trading",
            )
            await self.notifier.send_message(
                f"⛔ JJ DAILY LOSS LIMIT — P&L: ${self.state.state['daily_pnl']:.2f}\n"
                f"Pausing until tomorrow."
            )
            paused_summary = {
                "status": "paused",
                "reason": "daily_loss_limit",
                "cycle": cycle_num,
                "bankroll": self.state.state["bankroll"],
                "daily_pnl": self.state.state["daily_pnl"],
                "open_positions": len(self.state.state["open_positions"]),
                "signals": 0,
                "trades_placed": 0,
                "elapsed_seconds": round(time.time() - cycle_start, 1),
            }
            self._write_cycle_completed_heartbeat(paused_summary)
            return paused_summary

        # Refresh adaptive calibration window from latest resolved trades.
        try:
            changed = self.adaptive_platt.refresh()
            if changed:
                cal = self.adaptive_platt.summary()
                logger.info(
                    "Adaptive Platt refit: winner=%s active=%s A=%.6f B=%.6f samples=%d rows=%d",
                    cal.get("selected_variant", "static"),
                    cal.get("active_mode", cal.get("mode", "static")),
                    cal["a"],
                    cal["b"],
                    cal["samples"],
                    cal.get("last_refit_rows", 0),
                )
        except Exception as e:
            logger.warning(f"Adaptive Platt refresh failed (non-fatal): {e}")

        elastic_ml_snapshot = await self._refresh_elastic_ml_state(
            force=self._anomaly_task is None
        )

        fill_reconciliation = None
        if not self.paper_mode and self.fill_tracker is not None and self.clob is not None:
            try:
                with capture_span("fill_detection", span_type="trading.fill"):
                    fill_reconciliation = self.fill_tracker.reconcile_open_orders(
                        fetch_order=self.clob.get_order,
                        cancel_order=self._cancel_live_order,
                        max_order_age_hours=MAX_ORDER_AGE_HOURS,
                    )
                    if (
                        fill_reconciliation.fills_detected > 0
                        or fill_reconciliation.stale_cancelled > 0
                    ):
                        logger.info(
                            "Live order reconciliation: checked=%d fills=%d stale_cancelled=%d",
                            fill_reconciliation.orders_checked,
                            fill_reconciliation.fills_detected,
                            fill_reconciliation.stale_cancelled,
                            extra=ecs_extra(strategy="fill_detection"),
                        )
                    for fill_event in fill_reconciliation.fill_events:
                        await self._record_live_fill(fill_event)
                    for stale_order_id in fill_reconciliation.stale_order_ids:
                        logger.info(
                            "STALE ORDER CANCELLED: %s",
                            stale_order_id[:16],
                            extra=ecs_extra(strategy="fill_detection", order_id=stale_order_id),
                        )
            except Exception as e:
                logger.warning(f"Fill reconciliation failed (non-fatal): {e}")

        merge_result = None
        if not self.paper_mode and self.position_merger is not None:
            try:
                merge_result = self.position_merger.check_and_merge()
                if merge_result.get("candidates_found", 0) > 0 or merge_result.get("duplicate_groups", 0) > 0:
                    logger.info(
                        "Position merger: duplicates=%d candidates=%d submitted=%d freed=$%.2f reason=%s",
                        merge_result.get("duplicate_groups", 0),
                        merge_result.get("candidates_found", 0),
                        merge_result.get("submitted", 0),
                        _safe_float(merge_result.get("freed_capital_usdc"), 0.0),
                        merge_result.get("reason", "unknown"),
                    )
            except Exception as e:
                logger.warning(f"Position merge audit failed (non-fatal): {e}")

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
            with capture_span("market_scan", span_type="signal.scan"):
                result = self.scanner.fetch_active_markets(limit=100)
            # Handle both sync and async scanners
            if asyncio.iscoroutine(result):
                markets = await result
            else:
                markets = result
            logger.info(f"Scanned {len(markets)} active markets")

            if self._should_hydrate_recent_fast_markets(markets):
                hydrated_markets, hydration_stats = await self._fetch_recent_trade_hydrated_markets()
                if hydrated_markets:
                    original_count = len(markets)
                    markets = self._merge_markets(markets, hydrated_markets)
                    logger.info(
                        "Fast-flow hydration added %d recent markets (scanner=%d merged=%d trades=%d hydrated=%d fast_titles=%d)",
                        max(0, len(markets) - original_count),
                        original_count,
                        len(markets),
                        int(hydration_stats.get("recent_trades_fetched", 0)),
                        int(hydration_stats.get("recent_market_hydrations", 0)),
                        int(hydration_stats.get("recent_fast_markets_seen", 0)),
                    )
        except Exception as e:
            logger.error(f"Scanner failed: {e}")
            self._write_cycle_error_heartbeat(f"scanner: {e}", cycle_num=cycle_num)
            return {"status": "error", "reason": f"scanner: {e}"}

        # Build a broad execution universe for all lanes, then derive the
        # narrower LLM-eligible subset from it.
        actionable = []
        llm_actionable = []
        market_lookup = {}  # market_id -> market data

        skipped_category = 0
        skipped_too_slow = 0
        skipped_no_resolution = 0
        skipped_dedicated_btc5 = 0
        skipped_quarantined = 0
        for m in markets:
            try:
                # Quarantine filter: skip markets with recent CLOB errors
                if self.quarantine is not None:
                    mid = m.get("id", m.get("condition_id", ""))
                    if mid and self.quarantine.is_quarantined(mid):
                        skipped_quarantined += 1
                        continue

                question = m.get("question", "")
                slug = str(m.get("slug", "") or "").strip()
                raw_resolution_hours = estimate_resolution_hours(m) if MAX_RESOLUTION_HOURS > 0 else None
                allowed, filter_reason, category, llm_resolution_hours = apply_llm_market_filters(
                    question,
                    resolution_hours=raw_resolution_hours,
                    slug=slug,
                )
                if not allowed:
                    if filter_reason == "btc5_dedicated":
                        skipped_dedicated_btc5 += 1
                    elif filter_reason == "category":
                        skipped_category += 1
                    elif filter_reason == "velocity":
                        skipped_too_slow += 1
                    elif filter_reason == "resolution":
                        skipped_no_resolution += 1

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
                token_ids = normalize_token_ids(token_ids)

                if not token_ids:
                    raw_tokens = m.get("clobTokenIds", "")
                    token_ids = normalize_token_ids(raw_tokens)

                # Extract market IDs. Wallet-flow and some hydrated payloads use
                # condition_id as the signal market key, while scanner payloads
                # often key by id. Keep aliases so execution does not silently
                # drop valid signals due to key mismatch.
                primary_market_id = str(m.get("id", "") or "").strip()
                condition_market_id = str(
                    m.get("condition_id", m.get("conditionId", m.get("market_id", ""))) or ""
                ).strip()

                if (not primary_market_id and not condition_market_id) or not token_ids:
                    continue

                m["_resolution_hours"] = (
                    llm_resolution_hours
                    if allowed and llm_resolution_hours is not None
                    else raw_resolution_hours
                )
                market_payload = {
                    "question": m.get("question", ""),
                    "slug": slug,
                    "token_ids": token_ids,
                    "yes_price": yes_price,
                    "volume": float(m.get("volume", 0) or 0),
                    "liquidity": float(m.get("liquidity", 0) or 0),
                    "tags": m.get("tags", []) or [],
                    "category": category,
                    "resolution_hours": m.get("_resolution_hours"),
                    "llm_allowed": allowed,
                    "market_gate_reason": filter_reason if not allowed else "ok",
                }
                market_ids = {
                    primary_market_id,
                    condition_market_id,
                    str(m.get("market_id", "") or "").strip(),
                }
                market_ids.discard("")
                for market_id in market_ids:
                    market_lookup[market_id] = market_payload
                if self.fast_flow_only and not allowed:
                    continue
                actionable.append(m)
                if allowed:
                    llm_actionable.append(m)
            except Exception as e:
                logger.debug(f"Skip market: {e}")
                continue

        if skipped_quarantined:
            logger.info(f"Skipped {skipped_quarantined} quarantined markets (CLOB errors)")
        if skipped_category:
            logger.info(f"Skipped {skipped_category} low-edge-category markets (sports/crypto)")
        if skipped_dedicated_btc5:
            logger.info("Skipped %d dedicated BTC5 markets owned by btc_5min_maker", skipped_dedicated_btc5)
        if skipped_too_slow or skipped_no_resolution:
            logger.info(
                f"Velocity filter: skipped {skipped_too_slow} too slow "
                f"(>{MAX_RESOLUTION_HOURS}h) + {skipped_no_resolution} unknown resolution"
            )
        logger.info(
            "Found %d executable markets; %d pass LLM gates (max_res=%sh)",
            len(actionable),
            len(llm_actionable),
            MAX_RESOLUTION_HOURS,
        )
        self._elastic_market_lookup = {
            str(market_id): dict(metadata)
            for market_id, metadata in market_lookup.items()
            if isinstance(metadata, dict)
        }
        self._elastic_token_market_index = {}
        for market_id, metadata in self._elastic_market_lookup.items():
            for token_id in metadata.get("token_ids", []):
                if token_id:
                    self._elastic_token_market_index[str(token_id)] = str(market_id)
        shadow_lifecycle = getattr(self, "shadow_order_lifecycle", None)
        if shadow_lifecycle is not None and self._elastic_market_lookup:
            shadow_lifecycle.record_markouts(
                market_prices={
                    str(market_id): _safe_float(metadata.get("yes_price"), 0.5)
                    for market_id, metadata in self._elastic_market_lookup.items()
                }
            )

        # Register actionable market tokens with the trade stream
        if self.trade_stream:
            for m in actionable:
                mid = str(m.get("id", m.get("condition_id", "")))
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
        pending_order_count = self.fill_tracker.pending_order_count() if self.fill_tracker is not None else 0
        pending_market_ids = self.fill_tracker.pending_market_ids() if self.fill_tracker is not None else set()
        pending_order_notional = self.fill_tracker.pending_order_notional() if self.fill_tracker is not None else 0.0
        active_position_slots = (
            len(self.state.state["open_positions"])
            + self.state.count_active_linked_baskets()
            + pending_order_count
        )
        for m in llm_actionable[:20]:
            market_id = str(m.get("id", m.get("condition_id", "")))

            if self.state.has_position(market_id) or str(market_id) in pending_market_ids:
                continue

            feedback = self._get_elastic_ml_feedback(str(market_id))
            if feedback.get("paused"):
                logger.info(
                    "Elastic ML pause: skipping analysis for market=%s reason=%s",
                    str(market_id)[:16],
                    feedback.get("pause_reason", ""),
                )
                continue

            if active_position_slots + len(markets_for_analysis) >= MAX_OPEN_POSITIONS:
                logger.info(f"Position limit reached ({MAX_OPEN_POSITIONS})")
                break

            effective_deployed = self.state.state["total_deployed"] + pending_order_notional
            if effective_deployed >= self.state.state["bankroll"] * MAX_EXPOSURE_PCT:
                logger.info("Exposure limit reached")
                break

            mdata_lookup = market_lookup.get(str(market_id), {})
            markets_for_analysis.append({
                "market_id": str(market_id),
                "question": m.get("question", ""),
                "current_price": mdata_lookup.get("yes_price", 0.5),
                "category": mdata_lookup.get("category", "unknown"),
            })

        if self._llm_lane_enabled() and self.analyzer is None:
            logger.warning("LLM lane skipped for cycle — credentials or analyzer unavailable")

        if self._llm_lane_enabled() and self.analyzer is not None and markets_for_analysis:
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
                            kwargs = {"question": mkt["question"]}
                            if 'category' in params:
                                kwargs["category"] = mkt.get("category", "unknown")
                            if 'market_id' in params:
                                kwargs["market_id"] = mkt["market_id"]

                            if 'current_price' in params:
                                r = self.analyzer.analyze_market(
                                    current_price=mkt["current_price"],
                                    **kwargs,
                                )
                            elif 'market_price' in params:
                                r = self.analyzer.analyze_market(
                                    market_price=mkt["current_price"],
                                    **kwargs,
                                )
                            elif 'price' in params:
                                r = self.analyzer.analyze_market(
                                    price=mkt["current_price"],
                                    **kwargs,
                                )
                            else:
                                # Just pass question, let it figure it out
                                r = self.analyzer.analyze_market(**kwargs)

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
                            r = self.analyzer.analyze(
                                mkt["question"],
                                mkt["current_price"],
                                mkt.get("category", "unknown"),
                            )
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

                question = r.get("question", "")
                signal_allowed, filter_reason, category, res_hours = apply_llm_market_filters(
                    question,
                    resolution_hours=mdata_lookup.get("resolution_hours"),
                )
                if not signal_allowed:
                    logger.info(
                        "SKIP LLM result blocked by %s filter: cat=%s res=%s | %s",
                        filter_reason,
                        category,
                        f"{res_hours:.1f}h" if isinstance(res_hours, (int, float)) else "?",
                        question[:80],
                    )
                    continue

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

                # Convert confidence string to float
                confidence = normalize_confidence(r.get("confidence", 0.5))

                # Ensemble metadata (if available)
                n_models = int(_safe_float(r.get("n_models", 1), 1))
                model_spread = _safe_float(
                    r.get("range_estimate", r.get("model_spread", 0.0)),
                    0.0,
                )
                model_stddev = _safe_float(
                    r.get("std_estimate", r.get("disagreement", r.get("model_stddev", r.get("stdev", 0.0)))),
                    0.0,
                )
                models_agree = r.get("confirmation_signal", r.get("models_agree", False))
                rag_used = r.get("search_context_used", False)
                agreement = _safe_float(
                    r.get("agreement"),
                    max(0.0, 1.0 - min(1.0, model_stddev / max(DISAGREEMENT_WIDE_STD, 1e-9))),
                )
                confidence_multiplier = _safe_float(
                    r.get("confidence_multiplier", r.get("kelly_multiplier")),
                    confidence_multiplier_from_std(model_stddev, n_models),
                )
                disagreement_kelly_fraction = _safe_float(
                    r.get("disagreement_kelly_fraction"),
                    min(MAX_KELLY_FRACTION, max(0.0, MAX_KELLY_FRACTION * confidence_multiplier)),
                )
                disagreement_signal = bool(r.get("disagreement_signal", False))
                confirmation_signal = bool(r.get("confirmation_signal", False))
                uncertainty_reduction = bool(r.get("uncertainty_reduction", False))
                ensemble_call_cost = _safe_float(r.get("ensemble_call_cost_usd"), 0.0)
                ensemble_daily_cost = _safe_float(r.get("ensemble_daily_cost_usd"), 0.0)
                cost_cap_triggered = bool(r.get("cost_cap_triggered", False))
                fallback_mode = str(r.get("fallback_mode", "unknown") or "unknown")

                individual_model_estimates = r.get("individual_model_estimates", {})
                if not isinstance(individual_model_estimates, dict):
                    individual_model_estimates = {}
                counter_probability = _safe_float(r.get("counter_probability"), None)
                counter_shift = _safe_float(r.get("counter_shift"), None)
                debate_available = counter_probability is not None or counter_shift is not None

                def emit_llm_family_events(*, acted_on: bool, reason_skipped: str | None = None) -> None:
                    self._record_signal_evaluation(
                        signal_source="llm",
                        market_id=mid,
                        signal_value=calibrated_prob,
                        confidence=confidence,
                        acted_on=acted_on,
                        reason_skipped=reason_skipped,
                        extra={
                            "question": question,
                            "market_price": market_price,
                            "raw_probability": raw_prob,
                            "calibrated_probability": calibrated_prob,
                            "direction": direction,
                        },
                    )
                    self._record_signal_evaluation(
                        signal_source="ensemble",
                        market_id=mid,
                        signal_value=calibrated_prob if n_models > 1 else raw_prob,
                        confidence=agreement if n_models > 1 else confidence,
                        acted_on=acted_on and n_models > 1,
                        reason_skipped=reason_skipped if n_models > 1 else "single_model_only",
                        extra={
                            "question": question,
                            "market_price": market_price,
                            "model_count": n_models,
                            "model_spread": model_spread,
                            "model_stddev": model_stddev,
                            "agreement": agreement,
                        },
                    )
                    self._record_signal_evaluation(
                        signal_source="debate",
                        market_id=mid,
                        signal_value=counter_shift if counter_shift is not None else counter_probability,
                        confidence=agreement if debate_available else 0.0,
                        acted_on=acted_on and debate_available,
                        reason_skipped=reason_skipped if debate_available else "debate_data_unavailable",
                        extra={
                            "question": question,
                            "market_price": market_price,
                            "counter_probability": counter_probability,
                            "counter_shift": counter_shift,
                        },
                    )

                # ── ENSEMBLE FAILURE GUARD ──────────────────────────────────
                # If all LLM model calls failed, the ensemble returns 0.5 as
                # a fallback — that's a coin flip, not a signal. Do NOT trade.
                _ensemble_errors = r.get("errors", [])
                _ensemble_reasoning = str(r.get("reasoning", ""))
                if (
                    "all_models_failed" in _ensemble_errors
                    or "All ensemble model calls failed" in _ensemble_reasoning
                ):
                    logger.warning(
                        "ENSEMBLE FAILURE GUARD: Skipping %s — all model calls failed, "
                        "refusing to trade on 0.5 fallback probability",
                        mid,
                    )
                    emit_llm_family_events(acted_on=False, reason_skipped="ensemble_all_models_failed")
                    continue
                # ────────────────────────────────────────────────────────────

                # Map direction from various VPS formats
                direction = map_vps_signal_direction(r, market_price)

                if direction == "hold" or not is_mispriced:
                    emit_llm_family_events(acted_on=False, reason_skipped="not_mispriced")
                    continue

                edge = abs(_safe_float(r.get("edge", 0.0), 0.0))
                if edge < MIN_EDGE:
                    emit_llm_family_events(acted_on=False, reason_skipped="edge_below_minimum")
                    continue

                # Get resolution hours for velocity scoring
                vel_score = velocity_score(edge, res_hours) if res_hours else 0.0

                if n_models > 1:
                    logger.info(
                        "  Ensemble: n=%d mean=%.3f cal=%.3f std=%.3f range=%.3f confirm=%s disagree=%s "
                        "mult=%.2f call_cost=$%.4f daily_cost=$%.4f mode=%s cost_cap=%s",
                        n_models,
                        raw_prob,
                        calibrated_prob,
                        model_stddev,
                        model_spread,
                        confirmation_signal,
                        disagreement_signal,
                        confidence_multiplier,
                        ensemble_call_cost,
                        ensemble_daily_cost,
                        fallback_mode,
                        cost_cap_triggered,
                    )
                    logger.info(
                        "  Model estimates: %s",
                        ", ".join(
                            f"{model_name}={float(probability):.3f}"
                            for model_name, probability in sorted(individual_model_estimates.items())
                        ) or "none",
                    )
                elif n_models == 1 and self.ensemble_mode:
                    logger.info(
                        "  Ensemble fallback: single-model mode raw=%.3f cal=%.3f cost=$%.4f daily=$%.4f mode=%s",
                        raw_prob,
                        calibrated_prob,
                        ensemble_call_cost,
                        ensemble_daily_cost,
                        fallback_mode,
                    )

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
                    "category": category,
                    "resolution_hours": res_hours,
                    "velocity_score": vel_score,
                    "n_models": n_models,
                    "model_spread": model_spread,
                    "model_stddev": model_stddev,
                    "disagreement": model_stddev,
                    "agreement": agreement,
                    "confidence_multiplier": confidence_multiplier,
                    "kelly_multiplier": confidence_multiplier,
                    "disagreement_kelly_fraction": disagreement_kelly_fraction,
                    "models_agree": bool(models_agree),
                    "disagreement_signal": disagreement_signal,
                    "confirmation_signal": confirmation_signal,
                    "uncertainty_reduction": uncertainty_reduction,
                    "individual_model_estimates": individual_model_estimates,
                    "ensemble_call_cost_usd": ensemble_call_cost,
                    "ensemble_daily_cost_usd": ensemble_daily_cost,
                    "cost_cap_triggered": cost_cap_triggered,
                    "fallback_mode": fallback_mode,
                    "search_context_used": bool(rag_used),
                    "platt_mode": self.adaptive_platt.active_mode,
                    "platt_a": self.adaptive_platt.active_a,
                    "platt_b": self.adaptive_platt.active_b,
                }
                self._attach_microstructure_context(signal_payload, market_lookup)
                emit_llm_family_events(acted_on=True)
                signals.append(signal_payload)

        # Tag LLM signals with source
        for s in signals:
            s.setdefault("source", "llm")
            attach_signal_source_metadata(s)

        # --- SIGNAL SOURCE #2: Smart Wallet Flow Detector ---
        wallet_signals = []
        if self.wallet_flow_available:
            wallet_ready, wallet_reason = self._wallet_flow_bootstrap_status()
            if not wallet_ready:
                logger.info("Wallet flow skipped — %s", wallet_reason)
            else:
                try:
                    wallet_signals = wallet_flow_get_signals()
                    if wallet_signals:
                        logger.info(f"Wallet flow: {len(wallet_signals)} signals")
                    for ws in wallet_signals:
                        ws["source"] = "wallet_flow"
                        self._hydrate_signal_market_context(ws, market_lookup)
                        attach_signal_source_metadata(ws)
                    await self._late_hydrate_signal_markets(wallet_signals, market_lookup)
                except Exception as e:
                    logger.warning(f"Wallet flow scan failed (non-fatal): {e}")

        # --- SIGNAL SOURCE #3: LMSR Bayesian Engine ---
        lmsr_signals = []
        if self.lmsr_engine is not None and actionable:
            logger.info("Signal stage: starting LMSR scan (%d actionable markets)", len(actionable))
            try:
                lmsr_signals = self.lmsr_engine.get_signals(actionable)
                logger.info("Signal stage: LMSR scan complete (%d signals)", len(lmsr_signals))
                if lmsr_signals:
                    logger.info(f"LMSR engine: {len(lmsr_signals)} signals")
                for ls in lmsr_signals:
                    self._hydrate_signal_market_context(ls, market_lookup)
                    attach_signal_source_metadata(ls)
            except Exception as e:
                logger.warning(f"LMSR scan failed (non-fatal): {e}")

        # --- SIGNAL SOURCE #4: Cross-Platform Arbitrage ---
        arb_signals = await self._collect_cross_platform_arb_signals(market_lookup)

        # --- SIGNAL SOURCE #5: Lead-Lag Arbitrage Engine ---
        lead_lag_signals = []
        if self.lead_lag is not None and actionable:
            logger.info("Signal stage: starting lead-lag scan (%d actionable markets)", len(actionable))
            try:
                # Feed current prices to the lead-lag engine
                now = time.time()
                for m in actionable:
                    mid = str(m.get("id", m.get("condition_id", "")))
                    mdata = market_lookup.get(mid, {})
                    price = mdata.get("yes_price", 0.5)
                    question = mdata.get("question", "")
                    if mid and price:
                        self.lead_lag.update_price(mid, now, price, question)

                # Check for actionable signals from validated pairs
                ll_sigs = self.lead_lag.get_signals()
                logger.info("Signal stage: lead-lag scan complete (%d candidate signals)", len(ll_sigs))
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
                        lead_lag_signal = {
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
                        }
                        self._record_signal_evaluation(
                            signal_source="leadlag",
                            market_id=ll.follower_id,
                            signal_value=ll.expected_follower_move,
                            confidence=ll.confidence,
                            acted_on=True,
                            extra={
                                "leader_id": ll.leader_id,
                                "question": follower_data.get("question", ""),
                                "pair_score": ll.pair_score,
                                "leader_price_change": ll.leader_price_change,
                            },
                        )
                        lead_lag_signals.append(lead_lag_signal)
                    else:
                        self._record_signal_evaluation(
                            signal_source="leadlag",
                            market_id=ll.follower_id,
                            signal_value=ll.expected_follower_move,
                            confidence=ll.confidence,
                            acted_on=False,
                            reason_skipped="edge_below_minimum",
                            extra={"leader_id": ll.leader_id, "pair_score": ll.pair_score},
                        )

                if lead_lag_signals:
                    logger.info(f"Lead-lag engine: {len(lead_lag_signals)} signals")
                    for lsig in lead_lag_signals:
                        self._hydrate_signal_market_context(lsig, market_lookup)
                        attach_signal_source_metadata(lsig)
            except Exception as e:
                logger.warning(f"Lead-lag scan failed (non-fatal): {e}")

        # --- SIGNAL SOURCE #8: Multi-Outcome Sum Violations ---
        sum_violation_signals = []
        if self.sum_violation_strategy is not None:
            logger.info("Signal stage: starting sum-violation scan")
            try:
                generated = self.sum_violation_strategy.generate_signals()
                logger.info("Signal stage: sum-violation scan complete (%d signals)", len(generated))
                sum_violation_signals = [signal.to_signal_dict() for signal in generated]
                if self.sum_violation_strategy.last_evaluations:
                    ready = sum(
                        1
                        for evaluation in self.sum_violation_strategy.last_evaluations
                        if evaluation.action == "ready"
                    )
                    logger.info(
                        "Sum-violation scanner: %s detected, %s tradable",
                        len(self.sum_violation_strategy.last_evaluations),
                        ready,
                    )
                    for ssig in sum_violation_signals[:5]:
                        logger.info(
                            "  SUM-VIOL: %s | side=%s | viol=%.3f | edge=%.3f",
                            ssig.get("question", "")[:60],
                            ssig.get("trade_side", ""),
                            _safe_float(ssig.get("details", {}).get("violation_amount"), 0.0),
                            _safe_float(ssig.get("edge"), 0.0),
                        )
                for ssig in sum_violation_signals:
                    self._hydrate_signal_market_context(ssig, market_lookup)
            except Exception as e:
                logger.warning(f"Sum-violation scan failed (non-fatal): {e}")

        # --- VPIN GATE: filter signals where flow is toxic ---
        logger.info("Signal stage: entering VPIN gate (%d llm signals)", len(signals))
        if self.trade_stream:
            pre_vpin = len(signals)
            filtered_signals = []
            for s in signals:
                mid = s["market_id"]
                # Check all token IDs for this market
                mdata = market_lookup.get(mid, {})
                token_ids = mdata.get("token_ids", [])
                is_toxic = False
                max_vpin = 0.0
                dominant_token_id = token_ids[0] if token_ids else ""
                for tid in token_ids:
                    current_vpin = self.trade_stream.vpin.get_vpin(tid)
                    if current_vpin >= max_vpin:
                        max_vpin = current_vpin
                        dominant_token_id = tid
                    if not self.trade_stream.should_quote(tid):
                        is_toxic = True
                        logger.info(
                            f"VPIN GATE: blocking {s['question'][:40]}... "
                            f"(VPIN={current_vpin:.3f}, toxic)"
                        )
                        break
                self._record_signal_evaluation(
                    signal_source="vpin",
                    market_id=str(mid),
                    signal_value=max_vpin if token_ids else None,
                    confidence=max(0.0, min(1.0, 1.0 - abs(max_vpin - 0.5) * 2.0)) if token_ids else 0.0,
                    acted_on=not is_toxic,
                    reason_skipped="toxic_flow" if is_toxic else None,
                    extra={
                        "question": s.get("question", ""),
                        "token_id": dominant_token_id,
                        "token_ids": token_ids,
                    },
                )
                if not is_toxic:
                    filtered_signals.append(s)

            if pre_vpin > len(filtered_signals):
                logger.info(f"VPIN gate: blocked {pre_vpin - len(filtered_signals)} signals due to toxic flow")
            signals = filtered_signals

        # --- CONFIRMATION LAYER: blend all signal sources ---
        logger.info(
            "Signal stage: entering confirmation layer (llm=%d wallet=%d lmsr=%d arb=%d lead_lag=%d combinatorial=%d sumv=%d)",
            len(signals),
            len(wallet_signals),
            len(lmsr_signals),
            len(arb_signals),
            len(lead_lag_signals),
            len(combinatorial_signals),
            len(sum_violation_signals),
        )
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
            + sum_violation_signals
        )
        for s in all_signals:
            attach_signal_source_metadata(s)
            s["signal_sources"] = extract_signal_sources(s)
            s["signal_metadata"] = extract_signal_metadata(s)
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
            primary["source_components"] = list(normalize_source_components(sources)) or sorted(sources)
            primary["source_combo"] = "+".join(primary["source_components"])
            primary["n_sources"] = n_sources
            primary["signal_sources"] = list(primary["source_components"])
            primary["signal_metadata"] = merge_signal_metadata(group)

            # Confirmation boost: 2+ sources agree → higher confidence sizing
            res_hours = primary.get("resolution_hours")
            if n_sources >= 2:
                # Boosted: highest confidence, use quarter-Kelly even on fast markets
                primary["_kelly_override"] = MAX_KELLY_FRACTION
                primary["_confirmation"] = True
                logger.info(
                    f"  CONFIRMED ({n_sources} sources: {primary['source_combo']}): "
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
            src = s.get("source_combo", s.get("source", "?"))
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
            f"(LLM:{len([s for s in signals if signal_has_source(s, 'llm')])} "
            f"wallet:{len(wallet_signals)} lmsr:{len(lmsr_signals)} "
            f"A6:{combinatorial_cycle['a6_detected']} B1:{combinatorial_cycle['b1_detected']} "
            f"sumv:{len(sum_violation_signals)})"
        )
        llm_cycle_signals = [s for s in signals if signal_has_source(s, "llm")]
        wallet_cycle_signals = [s for s in signals if signal_has_source(s, "wallet_flow")]
        lmsr_cycle_signals = [s for s in signals if signal_has_source(s, "lmsr")]
        arb_cycle_signals = [
            s for s in signals if signal_has_source(s, "cross_platform_arb")
        ]
        lane_health = self._build_cycle_lane_health(
            llm_signals=llm_cycle_signals,
            wallet_signals=wallet_cycle_signals,
            lmsr_signals=lmsr_cycle_signals,
            arb_signals=arb_cycle_signals,
            combinatorial_signals=combinatorial_bypass_signals,
            sum_violation_signals=sum_violation_signals,
            combinatorial_cycle=combinatorial_cycle,
        )
        self._log_lane_health_summary("cycle", lane_health, cycle_num=cycle_num)

        # 3. EXECUTE TRADES
        logger.info(
            "Signal stage: entering execution (%d predictive, %d combinatorial)",
            len(signals),
            len(combinatorial_bypass_signals),
        )
        trades_placed = 0
        self._pm_campaign_recent_decisions = []

        for signal in signals:
            pending_order_count = self.fill_tracker.pending_order_count() if self.fill_tracker is not None else 0
            pending_order_notional = self.fill_tracker.pending_order_notional() if self.fill_tracker is not None else 0.0
            if (
                len(self.state.state["open_positions"])
                + self.state.count_active_linked_baskets()
                + pending_order_count
                >= MAX_OPEN_POSITIONS
            ):
                logger.info(f"Composite position limit reached ({MAX_OPEN_POSITIONS})")
                break
            effective_deployed = self.state.state["total_deployed"] + pending_order_notional
            if effective_deployed >= self.state.state["bankroll"] * MAX_EXPOSURE_PCT:
                logger.info("Exposure limit reached by pending + filled positions")
                break
            market_id = signal["market_id"]
            mdata = market_lookup.get(market_id)
            if not mdata:
                mdata = await self._fetch_market_metadata_for_signal(str(market_id), market_lookup)
                if mdata is None:
                    mdata = await self._late_hydrate_wallet_signal_from_window(signal, market_lookup)
                if mdata is not None:
                    self._hydrate_signal_market_context(signal, market_lookup)

            if not mdata:
                reason_skipped = (
                    "wallet_window_hydration_miss"
                    if self._signal_wallet_metadata_value(signal, "wallet_window_start_ts") is not None
                    else "missing_market_metadata"
                )
                self._record_signal_evaluation(
                    signal_source=str(signal.get("source_combo", signal.get("source", "unknown"))),
                    market_id=str(market_id),
                    signal_value=_safe_float(signal.get("edge"), None),
                    confidence=_safe_float(signal.get("confidence"), None),
                    acted_on=False,
                    reason_skipped=reason_skipped,
                    extra={"question": signal.get("question", "")},
                    signal_payload=signal,
                )
                logger.warning(
                    "Execution skip: missing market metadata for signal market_id=%s question=%s",
                    str(market_id)[:32],
                    signal.get("question", "")[:60],
                )
                continue

            market_gate_reason = str(mdata.get("market_gate_reason", "ok") or "ok")
            if market_gate_reason == "btc5_dedicated":
                self._record_signal_evaluation(
                    signal_source=str(signal.get("source_combo", signal.get("source", "unknown"))),
                    market_id=str(market_id),
                    signal_value=_safe_float(signal.get("edge"), None),
                    confidence=_safe_float(signal.get("confidence"), None),
                    acted_on=False,
                    reason_skipped="btc5_dedicated",
                    extra={
                        "question": signal.get("question", ""),
                        "market_gate_reason": market_gate_reason,
                    },
                    signal_payload=signal,
                )
                logger.info(
                    "SKIP execution blocked by dedicated BTC5 ownership: %s",
                    signal.get("question", "")[:80],
                )
                continue

            feedback = self._get_elastic_ml_feedback(str(market_id))
            signal["elastic_ml_feedback"] = feedback
            if feedback.get("paused"):
                self._record_signal_evaluation(
                    signal_source=str(signal.get("source_combo", signal.get("source", "unknown"))),
                    market_id=str(market_id),
                    signal_value=_safe_float(signal.get("edge"), None),
                    confidence=_safe_float(signal.get("confidence"), None),
                    acted_on=False,
                    reason_skipped="elastic_ml_paused",
                    extra={
                        "question": signal.get("question", ""),
                        "pause_reason": feedback.get("pause_reason", ""),
                    },
                    signal_payload=signal,
                )
                logger.warning(
                    "Elastic ML pause: skipping order placement market=%s reason=%s | %s",
                    str(market_id)[:16],
                    feedback.get("pause_reason", ""),
                    signal.get("question", "")[:60],
                )
                continue

            if signal_has_source(signal, "llm"):
                allowed, filter_reason, category, normalized_resolution = apply_llm_market_filters(
                    signal.get("question", ""),
                    resolution_hours=signal.get("resolution_hours"),
                    slug=mdata.get("slug", signal.get("slug", "")),
                )
                if not allowed:
                    logger.info(
                        "SKIP execution blocked by %s filter: cat=%s res=%s | %s",
                        filter_reason,
                        category,
                        f"{normalized_resolution:.1f}h" if isinstance(normalized_resolution, (int, float)) else "?",
                        signal.get("question", "")[:80],
                    )
                    continue
                signal["category"] = category
                signal["resolution_hours"] = normalized_resolution

            execution_guard_reason = self._execution_signal_guard_reason(signal, mdata)
            if execution_guard_reason:
                self._record_signal_evaluation(
                    signal_source=str(signal.get("source_combo", signal.get("source", "unknown"))),
                    market_id=str(market_id),
                    signal_value=_safe_float(signal.get("edge"), None),
                    confidence=_safe_float(signal.get("confidence"), None),
                    acted_on=False,
                    reason_skipped=execution_guard_reason,
                    extra={"question": signal.get("question", "")},
                    signal_payload=signal,
                )
                logger.info(
                    "SKIP execution blocked by %s guard: sources=%s cat=%s res=%s | %s",
                    execution_guard_reason,
                    signal.get("source_combo", signal.get("source", "")),
                    signal.get("category", mdata.get("category", "")),
                    signal.get("resolution_hours", mdata.get("resolution_hours", "?")),
                    signal.get("question", "")[:80],
                )
                continue

            wallet_quality_guard_reason = self._wallet_quality_guard_reason(signal)
            if wallet_quality_guard_reason:
                self._record_signal_evaluation(
                    signal_source=str(signal.get("source_combo", signal.get("source", "unknown"))),
                    market_id=str(market_id),
                    signal_value=_safe_float(signal.get("edge"), None),
                    confidence=_safe_float(signal.get("confidence"), None),
                    acted_on=False,
                    reason_skipped=wallet_quality_guard_reason,
                    extra={
                        "question": signal.get("question", ""),
                        "wallet_signal_age_seconds": self._signal_wallet_metadata_value(
                            signal,
                            "wallet_signal_age_seconds",
                        ),
                        "wallet_consensus_share": self._signal_wallet_metadata_value(
                            signal,
                            "wallet_consensus_share",
                        ),
                        "wallet_consensus_notional_usd": self._signal_wallet_metadata_value(
                            signal,
                            "wallet_consensus_notional_usd",
                        ),
                    },
                    signal_payload=signal,
                )
                logger.info(
                    "SKIP execution blocked by %s wallet gate: sources=%s age=%s share=%s notional=%s | %s",
                    wallet_quality_guard_reason,
                    signal.get("source_combo", signal.get("source", "")),
                    self._signal_wallet_metadata_value(signal, "wallet_signal_age_seconds"),
                    self._signal_wallet_metadata_value(signal, "wallet_consensus_share"),
                    self._signal_wallet_metadata_value(signal, "wallet_consensus_notional_usd"),
                    signal.get("question", "")[:80],
                )
                continue

            # Position sizing
            base_size_usd = kelly_size(
                edge=signal["edge"],
                market_price=signal["market_price"],
                direction=signal["direction"],
                bankroll=self.state.state["bankroll"],
                kelly_fraction_override=signal.get("_kelly_override"),
            )
            size_usd, disagreement_modifier = apply_disagreement_size_modifier(
                base_size_usd,
                _safe_float(signal.get("disagreement", signal.get("model_stddev")), None),
                modifier=_safe_float(signal.get("confidence_multiplier", signal.get("kelly_multiplier")), None),
                model_count=int(_safe_float(signal.get("n_models", 1), 1)),
            )
            if signal.get("disagreement", signal.get("model_stddev")) is not None:
                logger.info(
                    "Disagreement: %.3f, confidence multiplier: %.2f, final size: $%.2f",
                    _safe_float(signal.get("disagreement", signal.get("model_stddev")), 0.0),
                    disagreement_modifier,
                    size_usd,
                )

            size_usd = self._apply_elastic_ml_size_modifier(
                signal,
                market_id=str(market_id),
                size_usd=size_usd,
            )

            if (
                size_usd <= 0
                and 0 < MAX_POSITION_USD <= 0.50
                and base_size_usd >= MAX_POSITION_USD
            ):
                size_usd = round(MAX_POSITION_USD, 2)
                logger.info(
                    "Micro-size override: keeping test order at $%.2f for live data collection",
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
            order_price = round(price, 2)
            if order_price <= 0 or order_price >= 1:
                continue
            order_size = clob_order_size_for_usd(size_usd, order_price)
            if order_size <= 0:
                continue

            # Polymarket minimum order size enforcement
            min_order_size = clob_min_order_size(order_price, min_shares=POLY_MIN_ORDER_SHARES)
            if order_size < min_order_size:
                bumped_usd = round(min_order_size * order_price, 2)
                if bumped_usd > MAX_POSITION_USD * 2:
                    logger.info(
                        "  SKIP (%.2f shares / $%.2f below live min %.2f shares / $%.2f; bump to $%.2f exceeds 2x max $%.2f): %s",
                        order_size,
                        order_size * order_price,
                        min_order_size,
                        _CLOB_HARD_MIN_NOTIONAL_USD,
                        bumped_usd,
                        MAX_POSITION_USD,
                        signal.get("question", "")[:50],
                    )
                    continue
                logger.info(
                    "  Bump order from %.2f shares / $%.2f to %.2f shares / $%.2f to meet live CLOB minimum",
                    order_size,
                    order_size * order_price,
                    min_order_size,
                    bumped_usd,
                )
                order_size = min_order_size
            shares = order_size
            size_usd = round(order_size * order_price, 2)

            category = classify_market_category(signal.get("question", ""))
            mode_tag = self._mode_tag()

            logger.info(
                f"  [{mode_tag}] {signal['direction']} ${size_usd:.2f} "
                f"@ {price:.3f} | edge={signal['edge']:.1%} | "
                f"cat={category} | {signal['question'][:50]}..."
            )

            campaign_allowed, campaign_reason = self._check_pm_campaign_gate(
                signal=signal,
                size_usd=size_usd,
            )
            if not campaign_allowed:
                self._record_pm_campaign_decision(
                    cycle_num=cycle_num,
                    signal=signal,
                    decision="rejected",
                    reason_code=campaign_reason,
                    requested_usd=size_usd,
                    approved_usd=0.0,
                )
                logger.info(
                    "  SKIP (campaign gate %s): %s",
                    campaign_reason,
                    signal.get("question", "")[:60],
                )
                continue

            if not self.allow_order_submission:
                self._record_pm_campaign_decision(
                    cycle_num=cycle_num,
                    signal=signal,
                    decision="rejected",
                    reason_code="runtime_submission_blocked",
                    requested_usd=size_usd,
                    approved_usd=0.0,
                )
                logger.info(
                    "  SKIP order submission blocked by runtime mode (%s): %s",
                    self.runtime_mode,
                    signal.get("question", "")[:50],
                )
                continue

            trade_record = build_trade_record(
                signal,
                market_id=market_id,
                category=category,
                entry_price=price,
                position_size_usd=size_usd,
                token_id=token_id,
            )
            order_metadata = {
                "trade_record": trade_record,
                "signal_context": {
                    "edge": signal.get("edge", 0.0),
                    "market_price": signal.get("market_price", 0.5),
                    "direction": signal.get("direction", ""),
                    "_kelly_override": signal.get("_kelly_override"),
                },
            }

            order_ok = await self.place_order(
                signal=signal,
                market_id=market_id,
                token_id=token_id,
                side=side,
                price=price,
                order_price=order_price,
                order_size=order_size,
                size_usd=size_usd,
                category=category,
                trade_record=trade_record,
                order_metadata=order_metadata,
            )
            if order_ok:
                trades_placed += 1
                if self.pm_hourly_campaign_enabled:
                    self.pm_campaign_budget.record_spend(size_usd)
                self._record_pm_campaign_decision(
                    cycle_num=cycle_num,
                    signal=signal,
                    decision="accepted",
                    reason_code="pm_campaign_order_submitted",
                    requested_usd=size_usd,
                    approved_usd=size_usd,
                    order_submitted=True,
                )
            else:
                self._record_pm_campaign_decision(
                    cycle_num=cycle_num,
                    signal=signal,
                    decision="rejected",
                    reason_code="order_submission_failed",
                    requested_usd=size_usd,
                    approved_usd=0.0,
                )

            # Small delay between orders
            await asyncio.sleep(0.5)

        sum_violation_orders = 0
        sum_violation_actions: dict[str, str] = {}
        if sum_violation_signals:
            sum_violation_orders, sum_violation_actions = await self._execute_sum_violation_signals(
                sum_violation_signals
            )
            trades_placed += sum_violation_orders
        if self.sum_violation_strategy is not None:
            try:
                self.sum_violation_strategy.write_report(sum_violation_actions)
            except Exception as e:
                logger.warning(f"Sum-violation report write failed: {e}")

        # Update cycle count
        self.state.state["cycles_completed"] = cycle_num
        self.state.save()

        fill_summary_24h = None
        if self.fill_tracker is not None:
            try:
                self.fill_tracker.write_report(hours=FILL_REPORT_HOURS, live_only=not self.paper_mode)
                fill_summary_24h = self.fill_tracker.get_summary(
                    hours=FILL_REPORT_HOURS,
                    live_only=not self.paper_mode,
                )
            except Exception as e:
                logger.warning(f"Fill-rate report generation failed (non-fatal): {e}")

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
            "sum_violation_detected": (
                len(self.sum_violation_strategy.last_evaluations)
                if self.sum_violation_strategy is not None
                else 0
            ),
            "sum_violation_tradable": len(sum_violation_signals),
            "sum_violation_orders": sum_violation_orders,
            "trades_placed": trades_placed,
            "open_positions": len(self.state.state["open_positions"]),
            "linked_baskets": self.state.count_active_linked_baskets(),
            "arb_budget_in_use_usd": self.state.get_arb_budget_in_use_usd(),
            "bankroll": self.state.state["bankroll"],
            "max_resolution_hours": MAX_RESOLUTION_HOURS,
            "platt_mode": self.adaptive_platt.active_mode,
            "daily_pnl": self.state.state["daily_pnl"],
            "fills_detected": (
                fill_reconciliation.fills_detected
                if fill_reconciliation is not None
                else 0
            ),
            "stale_orders_cancelled": (
                fill_reconciliation.stale_cancelled
                if fill_reconciliation is not None
                else 0
            ),
            "fill_rate_24h": (
                fill_summary_24h.get("fill_rate", 0.0)
                if isinstance(fill_summary_24h, dict)
                else 0.0
            ),
            "pm_campaign": self._pm_campaign_cycle_summary(),
            "merge_candidates": (
                merge_result.get("candidates_found", 0)
                if isinstance(merge_result, dict)
                else 0
            ),
            "merge_submitted": (
                merge_result.get("submitted", 0)
                if isinstance(merge_result, dict)
                else 0
            ),
            "lane_health": lane_health,
            "elastic_ml": elastic_ml_snapshot,
            "combinatorial": combinatorial_cycle,
            "runtime_truth_guard": dict(getattr(self, "runtime_truth_guard", {})),
            "shadow_order_lifecycle": (
                getattr(self, "shadow_order_lifecycle").to_report()
                if getattr(self, "shadow_order_lifecycle", None) is not None
                else {}
            ),
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

        mode_tag = self._mode_tag()
        logger.info(
            f"=== JJ [{mode_tag}] Cycle {cycle_num} complete in {elapsed:.1f}s | "
            f"scanned={len(markets)} cat_skip={skipped_category} "
            f"slow_skip={skipped_too_slow} no_res={skipped_no_resolution} "
            f"actionable={len(actionable)} predictive={len(signals)} combinatorial={len(combinatorial_bypass_signals)} "
            f"sumv_orders={sum_violation_orders} trades={trades_placed} "
            f"fills={summary['fills_detected']} stale={summary['stale_orders_cancelled']} "
            f"ml_paused={len(summary['elastic_ml'].get('paused_markets', [])) if isinstance(summary.get('elastic_ml'), dict) else 0} "
            f"fill24h={summary['fill_rate_24h']:.1%} (max_res={MAX_RESOLUTION_HOURS}h "
            f"platt={self.adaptive_platt.active_mode}) ==="
        )

        self._write_cycle_completed_heartbeat(summary)
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
                "sum_violation_detected": summary.get("sum_violation_detected", 0),
                "sum_violation_tradable": summary.get("sum_violation_tradable", 0),
                "sum_violation_orders": summary.get("sum_violation_orders", 0),
                "trades_placed": summary.get("trades_placed", 0),
                "bankroll": summary.get("bankroll", 0),
                "daily_pnl": summary.get("daily_pnl", 0),
                "open_positions": summary.get("open_positions", 0),
                "linked_baskets": summary.get("linked_baskets", 0),
                "fills_detected": summary.get("fills_detected", 0),
                "stale_orders_cancelled": summary.get("stale_orders_cancelled", 0),
                "fill_rate_24h": summary.get("fill_rate_24h", 0.0),
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
                        "source": sig.get("source_combo", sig.get("source", "")),
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
                    "disagreement_confirmation_std": DISAGREEMENT_CONFIRMATION_STD,
                    "disagreement_signal_std": DISAGREEMENT_SIGNAL_STD,
                    "disagreement_reduce_size_std": DISAGREEMENT_REDUCE_SIZE_STD,
                    "disagreement_wide_std": DISAGREEMENT_WIDE_STD,
                    "ensemble_daily_cost_cap_usd": ENSEMBLE_DAILY_COST_CAP_USD,
                    "ensemble_enable_second_claude": ENSEMBLE_ENABLE_SECOND_CLAUDE,
                    "runtime_profile": self.profile_name,
                    "runtime_mode": self.runtime_mode,
                    "launch_gate_reason": self.launch_gate_reason or None,
                    "paper_mode": self.paper_mode,
                    "pm_campaign_enabled": self.pm_hourly_campaign_enabled,
                    "pm_campaign_max_resolution_hours": self.pm_campaign_max_resolution_hours,
                    "pm_campaign_budget_cap_usd": self.pm_campaign_budget.cap_usd,
                    "pm_campaign_window_seconds": self.pm_campaign_budget.window_seconds,
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
        mode_tag = self._mode_tag()
        logger.info(f"JJ {mode_tag} — Starting continuous mode")
        self._write_startup_heartbeat()
        try:
            try:
                startup_lane_health = self._startup_lane_health or self._build_startup_lane_health()
                if self.ensemble_mode:
                    sources = [f"LLM Ensemble ({len(self.analyzer.models)} models + RAG)"]
                elif self.analyzer is not None:
                    sources = ["LLM (Claude-only)"]
                else:
                    sources = []
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
                if self.anomaly_consumer is not None and self.anomaly_consumer.enabled:
                    sources.append("ElasticML")
                if self.sum_violation_strategy is not None:
                    sources.append("SumViolation")
                if self.combinatorial_cfg and self.combinatorial_cfg.enable_a6_shadow:
                    sources.append("A6-Shadow")
                if self.combinatorial_cfg and self.combinatorial_cfg.enable_b1_shadow:
                    sources.append("B1-Shadow")
                await self.notifier.send_message(
                    f"JJ {mode_tag} TRADING ONLINE\n"
                    f"Profile: {self.profile_name}\n"
                    f"Bankroll: ${self.state.state['bankroll']:.2f}\n"
                    f"Signal sources: {' + '.join(sources)}\n"
                    f"Lane health: {self._format_lane_health_summary(startup_lane_health)}\n"
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
                self._elastic_orderbook_task = asyncio.create_task(self._orderbook_snapshot_loop())
                logger.info(
                    "Elastic orderbook snapshot task started (interval=%ss)",
                    ELASTIC_ORDERBOOK_SNAPSHOT_INTERVAL_SECONDS,
                )
            if self.anomaly_consumer is not None and self.anomaly_consumer.enabled:
                self._anomaly_task = asyncio.create_task(self.anomaly_consumer.start())
                logger.info("Elastic ML anomaly consumer started as background task")

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
                    self._write_cycle_error_heartbeat(
                        str(e),
                        cycle_num=int(self.state.state.get("cycles_completed", 0)) + 1,
                    )
                    try:
                        await self.notifier.send_error(str(e), context="cycle_error")
                    except Exception:
                        pass
                    await asyncio.sleep(60)
        finally:
            if self.anomaly_consumer is not None:
                self.anomaly_consumer.stop()
            if self._anomaly_task is not None:
                self._anomaly_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._anomaly_task
                self._anomaly_task = None
            if self._elastic_orderbook_task is not None:
                self._elastic_orderbook_task.cancel()
                try:
                    await self._elastic_orderbook_task
                except asyncio.CancelledError:
                    pass
                self._elastic_orderbook_task = None
            if self.trade_stream is not None:
                try:
                    await self.trade_stream.stop()
                except Exception:
                    pass
            if self._trade_stream_task is not None:
                self._trade_stream_task.cancel()
                try:
                    await self._trade_stream_task
                except asyncio.CancelledError:
                    pass
                self._trade_stream_task = None
            if self.a6_shadow_scanner is not None:
                try:
                    self.a6_shadow_scanner.close()
                except Exception:
                    pass
            if self.sum_violation_scanner is not None:
                try:
                    self.sum_violation_scanner.close()
                except Exception:
                    pass
            if self.fill_tracker is not None:
                try:
                    self.fill_tracker.close()
                except Exception:
                    pass

    async def show_status(self):
        """Print current JJ state with database stats."""
        s = self.state.state
        db_stats = self.db.get_stats()
        multi = self.multi_sim.get_summary()
        combinatorial_summary = self.db.get_combinatorial_summary(hours=24 * 14)
        lane_health = self._last_lane_health or self._startup_lane_health or self._build_startup_lane_health()

        mode_str = self._mode_tag()
        print(f"\n{'='*50}")
        print(f"JJ {mode_str} TRADING STATUS")
        print(f"{'='*50}")
        print(f"Profile:          {self.profile_name}")
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
        if self.fill_tracker is not None:
            fill_summary = self.fill_tracker.get_summary(hours=FILL_REPORT_HOURS, live_only=not self.paper_mode)
            print(f"\nFill Tracking ({FILL_REPORT_HOURS}h):")
            print(f"  Orders placed:      {fill_summary['total_orders']}")
            print(f"  Orders with fills:  {fill_summary['filled_orders']}")
            print(f"  Fill rate:          {fill_summary['fill_rate']:.1%}")
            print(f"  Stale cancelled:    {fill_summary['stale_cancelled']}")
            latency = fill_summary.get("median_fill_latency_seconds")
            if latency is not None:
                print(f"  Median latency:     {latency / 60:.1f} min")

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

        if lane_health:
            print(f"\nLane Health:")
            for lane, payload in lane_health.items():
                reason = payload.get("reason")
                signals = payload.get("signals")
                reason_str = f" ({reason})" if reason else ""
                signals_str = f" signals={signals}" if signals is not None else ""
                print(f"  {lane}: {payload.get('status', 'unknown')}{reason_str}{signals_str}")

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
        try:
            calibrator = AdaptivePlattCalibrator(db)
            changed = calibrator.refresh(force=True)
            if changed:
                cal = calibrator.summary()
                print(
                    "Adaptive Platt refit: "
                    f"winner={cal.get('selected_variant', 'static')} "
                    f"active={cal.get('active_mode', cal.get('mode', 'static'))} "
                    f"A={cal['a']:.6f} B={cal['b']:.6f} "
                    f"samples={cal['samples']}"
                )
        except Exception as e:
            print(f"Warning: adaptive Platt refresh failed: {e}")

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
    fill_tracker = FillTracker(db_path=db.db_path) if FillTracker is not None else None
    fill_summary = (
        fill_tracker.get_summary(hours=24, live_only=not PAPER_TRADING)
        if fill_tracker is not None
        else None
    )
    source_breakdown = db.get_source_breakdown(date_prefix=today, limit=5)

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

    if isinstance(fill_summary, dict):
        report_lines.extend(
            [
                f"Fill rate (24h): {fill_summary['fill_rate']:.1%} "
                f"({fill_summary['filled_orders']}/{fill_summary['total_orders']})",
                f"Stale cancels (24h): {fill_summary['stale_cancelled']}",
            ]
        )

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

    if source_breakdown:
        report_lines.append(f"\nSource Mix Today:")
        for row in source_breakdown:
            resolved_count = int(row["wins"]) + int(row["losses"])
            win_rate = (
                f" win={int(row['wins']) / resolved_count:.0%}"
                if resolved_count > 0
                else ""
            )
            report_lines.append(
                f"  {row['source_label']}: {int(row['total_trades'])} placed, "
                f"{int(row['unresolved'])} open{win_rate}"
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
        if TelegramBot is None:
            raise ImportError("TelegramBot is unavailable")
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
    if fill_tracker is not None:
        fill_tracker.write_report(hours=24, live_only=not PAPER_TRADING)
        fill_tracker.close()
    db.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
TradingBot = JJLive


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
