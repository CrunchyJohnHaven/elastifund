from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from bot.runtime_profile import RuntimeProfileBundle
except ImportError:
    from runtime_profile import RuntimeProfileBundle  # type: ignore


DEFAULT_CATEGORY_PRIORITY = {
    "politics": 3,
    "weather": 3,
    "economic": 2,
    "crypto": 0,
    "sports": 0,
    "financial_speculation": 0,
    "geopolitical": 1,
    "fed_rates": 0,
    "unknown": 0,
}


def float_env(name: str, default: str) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def sum_violation_lane_enabled(profile_name: str) -> bool:
    if not bool_env("ENABLE_SUM_VIOLATION", True):
        return False
    return profile_name != "paper_aggressive"


def category_priority_from_env(defaults: dict[str, int]) -> dict[str, int]:
    priorities = {
        category: int(float_env(f"JJ_CAT_PRIORITY_{category.upper()}", str(default)))
        for category, default in defaults.items()
    }
    for env_name, raw in os.environ.items():
        if not env_name.startswith("JJ_CAT_PRIORITY_") or raw in ("", None):
            continue
        category = env_name.removeprefix("JJ_CAT_PRIORITY_").strip().lower()
        if not category:
            continue
        try:
            priorities[category] = int(float(raw))
        except ValueError:
            continue
    return priorities


def csv_list_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class RuntimeSettings:
    runtime_profile_name: str
    runtime_execution_mode: str
    allow_order_submission: bool
    max_position_usd: float
    poly_min_order_shares: float
    max_daily_loss_usd: float
    max_exposure_pct: float
    kelly_fraction: float
    max_kelly_fraction: float
    scan_interval: int
    elastic_orderbook_snapshot_interval_seconds: float
    max_open_positions: int
    min_edge: float
    initial_bankroll: float
    max_resolution_hours: float
    allowed_fast_assets: list[str]
    signal_dedup_ttl_seconds: int
    paper_trading: bool
    max_order_age_hours: float
    fill_report_hours: int
    auto_merge_positions: bool
    min_merge_freed_usdc: float
    yes_threshold: float
    no_threshold: float
    min_category_priority: int
    category_priority: dict[str, int]
    adaptive_platt_enabled: bool
    adaptive_platt_min_samples: int
    adaptive_platt_window: int
    adaptive_platt_refit_seconds: int
    adaptive_platt_runtime_variant: str
    adaptive_platt_report_path: str
    adaptive_platt_report_json_path: str
    disagreement_confirmation_std: float
    disagreement_signal_std: float
    disagreement_reduce_size_std: float
    disagreement_wide_std: float
    ensemble_daily_cost_cap_usd: float
    ensemble_enable_second_claude: bool
    pm_hourly_campaign_enabled: bool
    pm_hourly_notional_cap_usd: float
    pm_campaign_max_resolution_hours: float
    pm_campaign_window_seconds: int
    pm_campaign_decision_log_path: Path


def load_runtime_settings(
    *,
    activate_runtime_profile_env_fn: Callable[..., RuntimeProfileBundle],
    default_category_priority: dict[str, int],
    clob_hard_min_shares: float,
    persist: bool = False,
) -> tuple[RuntimeProfileBundle, RuntimeSettings]:
    bundle = activate_runtime_profile_env_fn(persist=persist)
    settings = RuntimeSettings(
        runtime_profile_name=bundle.selected_profile,
        runtime_execution_mode=str(os.environ.get("JJ_EFFECTIVE_EXECUTION_MODE", "paper")).strip().lower(),
        allow_order_submission=bool_env("JJ_ALLOW_ORDER_SUBMISSION", False),
        max_position_usd=float(os.environ.get("JJ_MAX_POSITION_USD", "5.00")),
        poly_min_order_shares=max(clob_hard_min_shares, float(os.environ.get("JJ_POLY_MIN_ORDER_SHARES", "5.0"))),
        max_daily_loss_usd=float(os.environ.get("JJ_MAX_DAILY_LOSS_USD", "10")),
        max_exposure_pct=float(os.environ.get("JJ_MAX_EXPOSURE_PCT", "0.90")),
        kelly_fraction=float(os.environ.get("JJ_KELLY_FRACTION", "0.25")),
        max_kelly_fraction=float(os.environ.get("JJ_MAX_KELLY_FRACTION", "0.25")),
        scan_interval=int(os.environ.get("JJ_SCAN_INTERVAL", "180")),
        elastic_orderbook_snapshot_interval_seconds=float(
            os.environ.get("JJ_ELASTIC_ORDERBOOK_SNAPSHOT_INTERVAL", "30")
        ),
        max_open_positions=int(os.environ.get("JJ_MAX_OPEN_POSITIONS", "30")),
        min_edge=float(os.environ.get("JJ_MIN_EDGE", "0.05")),
        initial_bankroll=float(os.environ.get("JJ_INITIAL_BANKROLL", "250.0")),
        max_resolution_hours=float(os.environ.get("JJ_MAX_RESOLUTION_HOURS", "48")),
        allowed_fast_assets=csv_list_env("JJ_ALLOWED_FAST_ASSETS"),
        signal_dedup_ttl_seconds=int(os.environ.get("JJ_SIGNAL_DEDUP_TTL", "3600")),
        paper_trading=bool_env("PAPER_TRADING", True),
        max_order_age_hours=float(os.environ.get("JJ_MAX_ORDER_AGE_HOURS", "2")),
        fill_report_hours=int(os.environ.get("JJ_FILL_REPORT_HOURS", "24")),
        auto_merge_positions=bool_env("JJ_AUTO_MERGE_POSITIONS", False),
        min_merge_freed_usdc=float(os.environ.get("JJ_MIN_MERGE_FREED_USDC", "0.50")),
        yes_threshold=float_env("JJ_YES_THRESHOLD", "0.15"),
        no_threshold=float_env("JJ_NO_THRESHOLD", "0.05"),
        min_category_priority=int(float_env("JJ_MIN_CATEGORY_PRIORITY", "1")),
        category_priority=category_priority_from_env(default_category_priority),
        adaptive_platt_enabled=bool_env("JJ_ADAPTIVE_PLATT_ENABLED", False),
        adaptive_platt_min_samples=int(os.environ.get("JJ_ADAPTIVE_PLATT_MIN_SAMPLES", "30")),
        adaptive_platt_window=int(os.environ.get("JJ_ADAPTIVE_PLATT_WINDOW", "100")),
        adaptive_platt_refit_seconds=int(os.environ.get("JJ_ADAPTIVE_PLATT_REFIT_SECONDS", "300")),
        adaptive_platt_runtime_variant=os.environ.get("JJ_ADAPTIVE_PLATT_VARIANT", "auto").strip().lower(),
        adaptive_platt_report_path=os.environ.get("JJ_ADAPTIVE_PLATT_REPORT_PATH", "reports/platt_comparison.md"),
        adaptive_platt_report_json_path=os.environ.get(
            "JJ_ADAPTIVE_PLATT_REPORT_JSON_PATH",
            "reports/platt_comparison.json",
        ),
        disagreement_confirmation_std=float(os.environ.get("JJ_DISAGREEMENT_CONFIRMATION_STD", "0.05")),
        disagreement_signal_std=float(os.environ.get("JJ_DISAGREEMENT_SIGNAL_STD", "0.10")),
        disagreement_reduce_size_std=float(os.environ.get("JJ_DISAGREEMENT_REDUCE_SIZE_STD", "0.15")),
        disagreement_wide_std=float(os.environ.get("JJ_DISAGREEMENT_WIDE_STD", "0.20")),
        ensemble_daily_cost_cap_usd=float(os.environ.get("JJ_ENSEMBLE_DAILY_COST_CAP_USD", "2.0")),
        ensemble_enable_second_claude=bool_env("JJ_ENSEMBLE_ENABLE_SECOND_CLAUDE", False),
        pm_hourly_campaign_enabled=bool_env("JJ_PM_HOURLY_CAMPAIGN_ENABLED", False),
        pm_hourly_notional_cap_usd=max(0.0, float(os.environ.get("JJ_PM_HOURLY_NOTIONAL_CAP_USD", "50.0"))),
        pm_campaign_max_resolution_hours=max(
            0.0,
            float(os.environ.get("JJ_PM_CAMPAIGN_MAX_RESOLUTION_HOURS", "24.0")),
        ),
        pm_campaign_window_seconds=max(60, int(float(os.environ.get("JJ_PM_CAMPAIGN_WINDOW_SECONDS", "3600")))),
        pm_campaign_decision_log_path=Path(
            os.environ.get("JJ_PM_CAMPAIGN_DECISION_LOG_PATH", "reports/pm_campaign_decisions.jsonl")
        ),
    )
    return bundle, settings
