from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping

from config.runtime_profile import (
    DEFAULT_EFFECTIVE_OUTPUT_PATH,
    DEFAULT_PROFILE_NAME,
    PROFILE_DIR,
    RuntimeProfile,
    RuntimeProfileError,
    load_runtime_profile as load_canonical_runtime_profile,
)


_LAST_SYNTHETIC_ENV: dict[str, str] = {}


@dataclass(frozen=True)
class RuntimeProfileBundle:
    selected_profile: str
    source_path: str
    config: dict[str, Any]
    effective_env: dict[str, str]
    legacy_overrides: dict[str, str]
    profile: RuntimeProfile


def _bool_str(value: bool) -> str:
    return "true" if bool(value) else "false"


def _filtered_env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    if env is not None:
        return env

    source = dict(os.environ)
    for key, synthetic_value in _LAST_SYNTHETIC_ENV.items():
        if key == "JJ_RUNTIME_PROFILE":
            continue
        if source.get(key) == synthetic_value:
            source.pop(key, None)
    return source


def _profile_to_effective_env(profile: RuntimeProfile) -> dict[str, str]:
    effective_env = {
        "JJ_RUNTIME_PROFILE": profile.profile_name,
        "JJ_REQUESTED_EXECUTION_MODE": profile.mode.execution_mode,
        "JJ_EFFECTIVE_EXECUTION_MODE": profile.mode.execution_mode,
        "JJ_LAUNCH_GATE": profile.mode.launch_gate,
        "JJ_LAUNCH_GATE_REASON": profile.mode.launch_gate,
        "JJ_ALLOW_ORDER_SUBMISSION": _bool_str(profile.mode.allow_order_submission),
        "PAPER_TRADING": _bool_str(profile.mode.paper_trading),
        "ENABLE_LLM_SIGNALS": _bool_str(profile.feature_flags.enable_llm_signals),
        "ENABLE_WALLET_FLOW": _bool_str(profile.feature_flags.enable_wallet_flow),
        "ENABLE_LMSR": _bool_str(profile.feature_flags.enable_lmsr),
        "ENABLE_CROSS_PLATFORM_ARB": _bool_str(profile.feature_flags.enable_cross_platform_arb),
        "ENABLE_SUM_VIOLATION": _bool_str(not profile.feature_flags.fast_flow_only),
        "JJ_FAST_FLOW_ONLY": _bool_str(profile.feature_flags.fast_flow_only),
        "ENABLE_A6_SHADOW": _bool_str(profile.feature_flags.enable_a6_shadow),
        "ENABLE_A6_LIVE": _bool_str(profile.feature_flags.enable_a6_live),
        "ENABLE_B1_SHADOW": _bool_str(profile.feature_flags.enable_b1_shadow),
        "ENABLE_B1_LIVE": _bool_str(profile.feature_flags.enable_b1_live),
        "JJ_A6_EMBEDDED_SHADOW_SCANNER": _bool_str(profile.feature_flags.enable_a6_embedded_shadow_scanner),
        "JJ_MAX_POSITION_USD": str(profile.risk_limits.max_position_usd),
        "JJ_MAX_DAILY_LOSS_USD": str(profile.risk_limits.max_daily_loss_usd),
        "JJ_MAX_EXPOSURE_PCT": str(profile.risk_limits.max_exposure_pct),
        "JJ_KELLY_FRACTION": str(profile.risk_limits.kelly_fraction),
        "JJ_MAX_KELLY_FRACTION": str(profile.risk_limits.max_kelly_fraction),
        "JJ_SCAN_INTERVAL": str(profile.risk_limits.scan_interval_seconds),
        "JJ_MAX_OPEN_POSITIONS": str(profile.risk_limits.max_open_positions),
        "JJ_MIN_EDGE": str(profile.risk_limits.min_edge),
        "JJ_INITIAL_BANKROLL": str(profile.risk_limits.initial_bankroll),
        "JJ_MAX_RESOLUTION_HOURS": str(profile.market_filters.max_resolution_hours),
        "JJ_MIN_CATEGORY_PRIORITY": str(profile.market_filters.min_category_priority),
        "JJ_YES_THRESHOLD": str(profile.signal_thresholds.yes_threshold),
        "JJ_NO_THRESHOLD": str(profile.signal_thresholds.no_threshold),
        "JJ_LMSR_THRESHOLD": str(profile.signal_thresholds.lmsr_entry_threshold),
        "JJ_A6_BUY_THRESHOLD": str(profile.combinatorial_thresholds.a6_buy_threshold),
        "JJ_A6_UNWIND_THRESHOLD": str(profile.combinatorial_thresholds.a6_unwind_threshold),
        "JJ_B1_IMPLICATION_THRESHOLD": str(profile.combinatorial_thresholds.b1_implication_threshold),
        "JJ_COMBINATORIAL_STALE_BOOK_MAX_AGE_SECONDS": str(profile.combinatorial_thresholds.stale_book_max_age_seconds),
        "JJ_COMBINATORIAL_FILL_TIMEOUT_SECONDS": str(profile.combinatorial_thresholds.fill_timeout_seconds),
        "JJ_COMBINATORIAL_CANCEL_REPLACE_COUNT": str(profile.combinatorial_thresholds.cancel_replace_count),
        "JJ_COMBINATORIAL_MAX_NOTIONAL_PER_LEG_USD": str(profile.combinatorial_thresholds.max_notional_per_leg_usd),
        "JJ_COMBINATORIAL_ARB_BUDGET_USD": str(profile.combinatorial_thresholds.arb_budget_usd),
        "JJ_COMBINATORIAL_MERGE_MIN_NOTIONAL_USD": str(profile.combinatorial_thresholds.merge_min_notional_usd),
        "JJ_COMBINATORIAL_PROMOTION_MIN_SIGNALS": str(profile.combinatorial_thresholds.promotion_min_signals),
        "JJ_COMBINATORIAL_REQUIRED_CAPTURE_RATE": str(profile.combinatorial_thresholds.required_capture_rate),
        "JJ_COMBINATORIAL_REQUIRED_CLASSIFICATION_ACCURACY": str(profile.combinatorial_thresholds.required_classification_accuracy),
        "JJ_COMBINATORIAL_MAX_FALSE_POSITIVE_RATE": str(profile.combinatorial_thresholds.max_false_positive_rate),
        "JJ_COMBINATORIAL_MAX_CONSECUTIVE_ROLLBACKS": str(profile.combinatorial_thresholds.max_consecutive_rollbacks),
        "JJ_CONSTRAINT_ARB_DB_PATH": str(profile.combinatorial_thresholds.constraint_db_path),
        "JJ_DEP_GRAPH_DB_PATH": str(profile.combinatorial_thresholds.dep_graph_db_path),
        "JJ_VPIN_BUCKET_SIZE": str(profile.microstructure_thresholds.vpin_bucket_size),
        "JJ_VPIN_WINDOW": str(profile.microstructure_thresholds.vpin_window_size),
        "JJ_VPIN_TOXIC_THRESHOLD": str(profile.microstructure_thresholds.vpin_toxic_threshold),
        "JJ_VPIN_SAFE_THRESHOLD": str(profile.microstructure_thresholds.vpin_safe_threshold),
        "JJ_WS_HEARTBEAT_INTERVAL": str(profile.microstructure_thresholds.ws_heartbeat_interval_seconds),
        "JJ_WS_REST_POLL_INTERVAL": str(profile.microstructure_thresholds.ws_rest_poll_interval_seconds),
    }

    for category, value in profile.market_filters.category_priorities.items():
        effective_env[f"JJ_CAT_PRIORITY_{category.upper()}"] = str(value)

    return effective_env


def _bundle_from_profile(profile: RuntimeProfile) -> RuntimeProfileBundle:
    config = profile.to_dict()
    config.setdefault("mode", {})
    config["mode"]["requested_execution_mode"] = profile.mode.execution_mode
    config["mode"]["effective_execution_mode"] = profile.mode.execution_mode
    config["mode"]["launch_gate_reason"] = profile.mode.launch_gate
    return RuntimeProfileBundle(
        selected_profile=profile.profile_name,
        source_path=str(profile.profile_path),
        config=config,
        effective_env=_profile_to_effective_env(profile),
        legacy_overrides={override.env_var: override.raw_value for override in profile.applied_overrides},
        profile=profile,
    )


def load_runtime_profile(
    *,
    env: Mapping[str, str] | None = None,
    profile_name: str | None = None,
    profile_dir: Path | None = None,
    remote_cycle_status_path: Path | None = None,
) -> RuntimeProfileBundle:
    del remote_cycle_status_path
    profile = load_canonical_runtime_profile(
        profile_name=profile_name,
        env=_filtered_env(env),
        profile_dir=profile_dir or PROFILE_DIR,
    )
    return _bundle_from_profile(profile)


def write_effective_runtime_profile(
    bundle: RuntimeProfileBundle,
    *,
    output_path: Path | None = None,
) -> Path:
    output = output_path or DEFAULT_EFFECTIVE_OUTPUT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(bundle.config)
    payload["selected_profile"] = bundle.selected_profile
    payload["source_path"] = bundle.source_path
    payload["legacy_overrides"] = dict(bundle.legacy_overrides)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return output


def activate_runtime_profile_env(
    *,
    env: Mapping[str, str] | None = None,
    profile_name: str | None = None,
    profile_dir: Path | None = None,
    remote_cycle_status_path: Path | None = None,
    persist: bool = False,
) -> RuntimeProfileBundle:
    global _LAST_SYNTHETIC_ENV
    bundle = load_runtime_profile(
        env=env,
        profile_name=profile_name,
        profile_dir=profile_dir,
        remote_cycle_status_path=remote_cycle_status_path,
    )

    if env is None:
        for key, value in bundle.effective_env.items():
            os.environ[key] = value
        _LAST_SYNTHETIC_ENV = dict(bundle.effective_env)

    if persist:
        write_effective_runtime_profile(bundle)

    return bundle


__all__ = [
    "DEFAULT_PROFILE_NAME",
    "PROFILE_DIR",
    "RuntimeProfileBundle",
    "RuntimeProfileError",
    "activate_runtime_profile_env",
    "load_runtime_profile",
    "write_effective_runtime_profile",
]
