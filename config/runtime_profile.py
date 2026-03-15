"""Checked-in runtime profile loader for JJ threshold and launch control."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping


PROFILE_SELECTOR_ENV = "JJ_RUNTIME_PROFILE"
DEFAULT_PROFILE_NAME = "blocked_safe"
PROFILE_DIR = Path(__file__).resolve().parent / "runtime_profiles"
DEFAULT_EFFECTIVE_OUTPUT_PATH = Path("reports") / "runtime_profile_effective.json"

REQUIRED_SECTIONS = (
    "mode",
    "feature_flags",
    "risk_limits",
    "market_filters",
    "signal_thresholds",
    "combinatorial_thresholds",
    "microstructure_thresholds",
)
ALLOWED_TOP_LEVEL_KEYS = set(REQUIRED_SECTIONS) | {"schema_version", "description"}
ALLOWED_EXECUTION_MODES = {"blocked", "shadow", "research"}
ALLOWED_LAUNCH_GATES = {"blocked", "wallet_flow_ready", "none"}

BOOLEAN_TRUE = {"1", "true", "yes", "on"}
BOOLEAN_FALSE = {"0", "false", "no", "off"}


class RuntimeProfileError(ValueError):
    """Raised when a runtime profile or override is invalid."""


@dataclass(frozen=True)
class AppliedOverride:
    env_var: str
    section: str
    key: str
    raw_value: str
    value: Any


@dataclass
class RuntimeModeConfig:
    execution_mode: str = "blocked"
    paper_trading: bool = True
    allow_order_submission: bool = False
    launch_gate: str = "blocked"

    def __post_init__(self) -> None:
        self.execution_mode = str(self.execution_mode).strip().lower()
        self.launch_gate = str(self.launch_gate).strip().lower()
        if self.execution_mode not in ALLOWED_EXECUTION_MODES:
            raise RuntimeProfileError(f"unsupported execution_mode: {self.execution_mode}")
        if self.launch_gate not in ALLOWED_LAUNCH_GATES:
            raise RuntimeProfileError(f"unsupported launch_gate: {self.launch_gate}")


@dataclass
class FeatureFlagsConfig:
    enable_llm_signals: bool = True
    enable_wallet_flow: bool = False
    enable_lmsr: bool = False
    enable_cross_platform_arb: bool = False
    enable_polymarket_venue: bool = True
    enable_kalshi_venue: bool = True
    fast_flow_only: bool = False
    enable_a6_shadow: bool = False
    enable_a6_live: bool = False
    enable_b1_shadow: bool = False
    enable_b1_live: bool = False
    enable_a6_embedded_shadow_scanner: bool = True


@dataclass
class RiskLimitsConfig:
    max_position_usd: float = 5.0
    max_daily_loss_usd: float = 5.0
    max_exposure_pct: float = 0.10
    kelly_fraction: float = 0.125
    max_kelly_fraction: float = 0.25
    scan_interval_seconds: int = 300
    max_open_positions: int = 5
    min_edge: float = 0.05
    initial_bankroll: float = 250.0
    hourly_notional_budget_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.max_position_usd <= 0:
            raise RuntimeProfileError("risk_limits.max_position_usd must be > 0")
        if self.max_daily_loss_usd <= 0:
            raise RuntimeProfileError("risk_limits.max_daily_loss_usd must be > 0")
        if not 0 < self.max_exposure_pct <= 1:
            raise RuntimeProfileError("risk_limits.max_exposure_pct must be in (0, 1]")
        if not 0 < self.kelly_fraction <= 1:
            raise RuntimeProfileError("risk_limits.kelly_fraction must be in (0, 1]")
        if not 0 < self.max_kelly_fraction <= 1:
            raise RuntimeProfileError("risk_limits.max_kelly_fraction must be in (0, 1]")
        if self.kelly_fraction > self.max_kelly_fraction:
            raise RuntimeProfileError("risk_limits.kelly_fraction cannot exceed risk_limits.max_kelly_fraction")
        if self.scan_interval_seconds <= 0:
            raise RuntimeProfileError("risk_limits.scan_interval_seconds must be > 0")
        if self.max_open_positions <= 0:
            raise RuntimeProfileError("risk_limits.max_open_positions must be > 0")
        if not 0 <= self.min_edge <= 1:
            raise RuntimeProfileError("risk_limits.min_edge must be in [0, 1]")
        if self.initial_bankroll <= 0:
            raise RuntimeProfileError("risk_limits.initial_bankroll must be > 0")
        if self.hourly_notional_budget_usd < 0:
            raise RuntimeProfileError("risk_limits.hourly_notional_budget_usd must be >= 0")


@dataclass
class MarketFiltersConfig:
    max_resolution_hours: float = 48.0
    min_category_priority: int = 1
    category_priorities: dict[str, int] = field(
        default_factory=lambda: {
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
    )

    def __post_init__(self) -> None:
        if self.max_resolution_hours <= 0:
            raise RuntimeProfileError("market_filters.max_resolution_hours must be > 0")
        if self.min_category_priority < 0:
            raise RuntimeProfileError("market_filters.min_category_priority must be >= 0")
        self.category_priorities = {
            str(key).strip().lower(): int(value)
            for key, value in dict(self.category_priorities).items()
        }


@dataclass
class SignalThresholdsConfig:
    yes_threshold: float = 0.15
    no_threshold: float = 0.05
    lmsr_entry_threshold: float = 0.05

    def __post_init__(self) -> None:
        if not 0 <= self.yes_threshold <= 1:
            raise RuntimeProfileError("signal_thresholds.yes_threshold must be in [0, 1]")
        if not 0 <= self.no_threshold <= 1:
            raise RuntimeProfileError("signal_thresholds.no_threshold must be in [0, 1]")
        if not 0 <= self.lmsr_entry_threshold <= 1:
            raise RuntimeProfileError("signal_thresholds.lmsr_entry_threshold must be in [0, 1]")


@dataclass
class CombinatorialThresholdsConfig:
    a6_buy_threshold: float = 0.97
    a6_unwind_threshold: float = 1.03
    b1_implication_threshold: float = 0.03
    stale_book_max_age_seconds: int = 45
    fill_timeout_seconds: float = 3.0
    cancel_replace_count: int = 1
    max_notional_per_leg_usd: float = 5.0
    arb_budget_usd: float = 100.0
    merge_min_notional_usd: float = 20.0
    promotion_min_signals: int = 20
    required_capture_rate: float = 0.50
    required_classification_accuracy: float = 0.80
    max_false_positive_rate: float = 0.05
    max_consecutive_rollbacks: int = 3
    constraint_db_path: Path = Path("data") / "constraint_arb.db"
    dep_graph_db_path: Path = Path("data") / "dep_graph.sqlite"

    def __post_init__(self) -> None:
        self.constraint_db_path = Path(self.constraint_db_path)
        self.dep_graph_db_path = Path(self.dep_graph_db_path)


@dataclass
class MicrostructureThresholdsConfig:
    vpin_bucket_size: float = 500.0
    vpin_window_size: int = 10
    vpin_toxic_threshold: float = 0.75
    vpin_safe_threshold: float = 0.25
    ws_heartbeat_interval_seconds: float = 10.0
    ws_rest_poll_interval_seconds: float = 5.0


@dataclass
class RuntimeProfile:
    profile_name: str
    profile_path: Path
    selector_source: str
    selector_value: str
    schema_version: int = 1
    description: str = ""
    mode: RuntimeModeConfig = field(default_factory=RuntimeModeConfig)
    feature_flags: FeatureFlagsConfig = field(default_factory=FeatureFlagsConfig)
    risk_limits: RiskLimitsConfig = field(default_factory=RiskLimitsConfig)
    market_filters: MarketFiltersConfig = field(default_factory=MarketFiltersConfig)
    signal_thresholds: SignalThresholdsConfig = field(default_factory=SignalThresholdsConfig)
    combinatorial_thresholds: CombinatorialThresholdsConfig = field(default_factory=CombinatorialThresholdsConfig)
    microstructure_thresholds: MicrostructureThresholdsConfig = field(default_factory=MicrostructureThresholdsConfig)
    applied_overrides: tuple[AppliedOverride, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=str))


@dataclass(frozen=True)
class OverrideSpec:
    section: str
    key: str
    aliases: tuple[tuple[str, Callable[[str], Any]], ...]


def _parse_bool(raw: str) -> bool:
    normalized = str(raw).strip().lower()
    if normalized in BOOLEAN_TRUE:
        return True
    if normalized in BOOLEAN_FALSE:
        return False
    raise RuntimeProfileError(f"invalid boolean override value: {raw!r}")


def _parse_int(raw: str) -> int:
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise RuntimeProfileError(f"invalid integer override value: {raw!r}") from exc


def _parse_float(raw: str) -> float:
    try:
        return float(str(raw).strip())
    except ValueError as exc:
        raise RuntimeProfileError(f"invalid float override value: {raw!r}") from exc


def _parse_fill_timeout_ms(raw: str) -> float:
    return _parse_float(raw) / 1000.0


OVERRIDE_SPECS: tuple[OverrideSpec, ...] = (
    OverrideSpec("mode", "paper_trading", (("PAPER_TRADING", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_llm_signals", (("ENABLE_LLM_SIGNALS", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_wallet_flow", (("ENABLE_WALLET_FLOW", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_lmsr", (("ENABLE_LMSR", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_cross_platform_arb", (("ENABLE_CROSS_PLATFORM_ARB", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_polymarket_venue", (("JJ_ENABLE_POLYMARKET_VENUE", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_kalshi_venue", (("JJ_ENABLE_KALSHI_VENUE", _parse_bool),)),
    OverrideSpec("feature_flags", "fast_flow_only", (("JJ_FAST_FLOW_ONLY", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_a6_shadow", (("ENABLE_A6_SHADOW", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_a6_live", (("ENABLE_A6_LIVE", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_b1_shadow", (("ENABLE_B1_SHADOW", _parse_bool),)),
    OverrideSpec("feature_flags", "enable_b1_live", (("ENABLE_B1_LIVE", _parse_bool),)),
    OverrideSpec(
        "feature_flags",
        "enable_a6_embedded_shadow_scanner",
        (("JJ_A6_EMBEDDED_SHADOW_SCANNER", _parse_bool),),
    ),
    OverrideSpec("risk_limits", "max_position_usd", (("JJ_MAX_POSITION_USD", _parse_float),)),
    OverrideSpec("risk_limits", "max_daily_loss_usd", (("JJ_MAX_DAILY_LOSS_USD", _parse_float),)),
    OverrideSpec("risk_limits", "max_exposure_pct", (("JJ_MAX_EXPOSURE_PCT", _parse_float),)),
    OverrideSpec("risk_limits", "kelly_fraction", (("JJ_KELLY_FRACTION", _parse_float),)),
    OverrideSpec("risk_limits", "max_kelly_fraction", (("JJ_MAX_KELLY_FRACTION", _parse_float),)),
    OverrideSpec("risk_limits", "scan_interval_seconds", (("JJ_SCAN_INTERVAL", _parse_int),)),
    OverrideSpec("risk_limits", "max_open_positions", (("JJ_MAX_OPEN_POSITIONS", _parse_int),)),
    OverrideSpec("risk_limits", "min_edge", (("JJ_MIN_EDGE", _parse_float),)),
    OverrideSpec("risk_limits", "initial_bankroll", (("JJ_INITIAL_BANKROLL", _parse_float),)),
    OverrideSpec("risk_limits", "hourly_notional_budget_usd", (("JJ_HOURLY_NOTIONAL_BUDGET_USD", _parse_float),)),
    OverrideSpec("market_filters", "max_resolution_hours", (("JJ_MAX_RESOLUTION_HOURS", _parse_float),)),
    OverrideSpec("market_filters", "min_category_priority", (("JJ_MIN_CATEGORY_PRIORITY", _parse_int),)),
    OverrideSpec("signal_thresholds", "yes_threshold", (("JJ_YES_THRESHOLD", _parse_float),)),
    OverrideSpec("signal_thresholds", "no_threshold", (("JJ_NO_THRESHOLD", _parse_float),)),
    OverrideSpec("signal_thresholds", "lmsr_entry_threshold", (("JJ_LMSR_THRESHOLD", _parse_float),)),
    OverrideSpec("combinatorial_thresholds", "a6_buy_threshold", (("JJ_A6_BUY_THRESHOLD", _parse_float),)),
    OverrideSpec("combinatorial_thresholds", "a6_unwind_threshold", (("JJ_A6_UNWIND_THRESHOLD", _parse_float),)),
    OverrideSpec(
        "combinatorial_thresholds",
        "b1_implication_threshold",
        (("JJ_B1_IMPLICATION_THRESHOLD", _parse_float),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "stale_book_max_age_seconds",
        (("JJ_COMBINATORIAL_STALE_BOOK_MAX_AGE_SECONDS", _parse_int),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "fill_timeout_seconds",
        (
            ("JJ_COMBINATORIAL_FILL_TIMEOUT_SECONDS", _parse_float),
            ("JJ_COMBINATORIAL_FILL_TIMEOUT_MS", _parse_fill_timeout_ms),
        ),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "cancel_replace_count",
        (("JJ_COMBINATORIAL_CANCEL_REPLACE_COUNT", _parse_int),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "max_notional_per_leg_usd",
        (("JJ_COMBINATORIAL_MAX_NOTIONAL_PER_LEG_USD", _parse_float),),
    ),
    OverrideSpec("combinatorial_thresholds", "arb_budget_usd", (("JJ_COMBINATORIAL_ARB_BUDGET_USD", _parse_float),)),
    OverrideSpec(
        "combinatorial_thresholds",
        "merge_min_notional_usd",
        (("JJ_COMBINATORIAL_MERGE_MIN_NOTIONAL_USD", _parse_float),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "promotion_min_signals",
        (("JJ_COMBINATORIAL_PROMOTION_MIN_SIGNALS", _parse_int),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "required_capture_rate",
        (("JJ_COMBINATORIAL_REQUIRED_CAPTURE_RATE", _parse_float),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "required_classification_accuracy",
        (("JJ_COMBINATORIAL_REQUIRED_CLASSIFICATION_ACCURACY", _parse_float),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "max_false_positive_rate",
        (("JJ_COMBINATORIAL_MAX_FALSE_POSITIVE_RATE", _parse_float),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "max_consecutive_rollbacks",
        (("JJ_COMBINATORIAL_MAX_CONSECUTIVE_ROLLBACKS", _parse_int),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "constraint_db_path",
        (("JJ_CONSTRAINT_ARB_DB_PATH", lambda raw: Path(str(raw).strip())),),
    ),
    OverrideSpec(
        "combinatorial_thresholds",
        "dep_graph_db_path",
        (("JJ_DEP_GRAPH_DB_PATH", lambda raw: Path(str(raw).strip())),),
    ),
    OverrideSpec("microstructure_thresholds", "vpin_bucket_size", (("JJ_VPIN_BUCKET_SIZE", _parse_float),)),
    OverrideSpec("microstructure_thresholds", "vpin_window_size", (("JJ_VPIN_WINDOW", _parse_int),)),
    OverrideSpec(
        "microstructure_thresholds",
        "vpin_toxic_threshold",
        (("JJ_VPIN_TOXIC_THRESHOLD", _parse_float),),
    ),
    OverrideSpec(
        "microstructure_thresholds",
        "vpin_safe_threshold",
        (("JJ_VPIN_SAFE_THRESHOLD", _parse_float),),
    ),
    OverrideSpec(
        "microstructure_thresholds",
        "ws_heartbeat_interval_seconds",
        (("JJ_WS_HEARTBEAT_INTERVAL", _parse_float),),
    ),
    OverrideSpec(
        "microstructure_thresholds",
        "ws_rest_poll_interval_seconds",
        (("JJ_WS_REST_POLL_INTERVAL", _parse_float),),
    ),
)


def available_runtime_profiles(profile_dir: Path = PROFILE_DIR) -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in profile_dir.glob("*.json")))


def _load_profile_document(profile_name: str, profile_dir: Path = PROFILE_DIR) -> tuple[dict[str, Any], Path]:
    if not profile_name:
        raise RuntimeProfileError("runtime profile name cannot be empty")

    path = profile_dir / f"{profile_name}.json"
    if not path.exists():
        raise RuntimeProfileError(
            f"unknown runtime profile {profile_name!r}; available profiles: {', '.join(available_runtime_profiles(profile_dir))}"
        )

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeProfileError(f"invalid JSON in runtime profile {path}") from exc

    if not isinstance(raw, dict):
        raise RuntimeProfileError(f"runtime profile {path} must contain a JSON object")

    missing_sections = [section for section in REQUIRED_SECTIONS if section not in raw]
    if missing_sections:
        raise RuntimeProfileError(f"runtime profile {path} missing sections: {', '.join(missing_sections)}")

    unknown_top_level = sorted(set(raw) - ALLOWED_TOP_LEVEL_KEYS)
    if unknown_top_level:
        raise RuntimeProfileError(f"runtime profile {path} has unsupported keys: {', '.join(unknown_top_level)}")

    return raw, path


def _merge_section(section_name: str, raw_section: Any, cls: type[Any]) -> Any:
    if raw_section is None:
        raw_section = {}
    if not isinstance(raw_section, Mapping):
        raise RuntimeProfileError(f"section {section_name!r} must be a JSON object")

    defaults = asdict(cls())
    unknown_keys = sorted(set(raw_section) - set(defaults))
    if unknown_keys:
        raise RuntimeProfileError(f"section {section_name!r} has unsupported keys: {', '.join(unknown_keys)}")

    merged = {**defaults, **dict(raw_section)}
    return cls(**merged)


def _build_runtime_profile(
    document: Mapping[str, Any],
    *,
    profile_name: str,
    profile_path: Path,
    selector_source: str,
    selector_value: str,
) -> RuntimeProfile:
    schema_version = int(document.get("schema_version", 1))
    if schema_version != 1:
        raise RuntimeProfileError(f"unsupported runtime profile schema_version: {schema_version}")

    return RuntimeProfile(
        profile_name=profile_name,
        profile_path=profile_path,
        selector_source=selector_source,
        selector_value=selector_value,
        schema_version=schema_version,
        description=str(document.get("description", "")).strip(),
        mode=_merge_section("mode", document.get("mode"), RuntimeModeConfig),
        feature_flags=_merge_section("feature_flags", document.get("feature_flags"), FeatureFlagsConfig),
        risk_limits=_merge_section("risk_limits", document.get("risk_limits"), RiskLimitsConfig),
        market_filters=_merge_section("market_filters", document.get("market_filters"), MarketFiltersConfig),
        signal_thresholds=_merge_section("signal_thresholds", document.get("signal_thresholds"), SignalThresholdsConfig),
        combinatorial_thresholds=_merge_section(
            "combinatorial_thresholds",
            document.get("combinatorial_thresholds"),
            CombinatorialThresholdsConfig,
        ),
        microstructure_thresholds=_merge_section(
            "microstructure_thresholds",
            document.get("microstructure_thresholds"),
            MicrostructureThresholdsConfig,
        ),
    )


def _set_override(profile: RuntimeProfile, section: str, key: str, env_var: str, raw_value: str, value: Any) -> None:
    target_section = getattr(profile, section)
    setattr(target_section, key, value)
    profile.applied_overrides += (
        AppliedOverride(
            env_var=env_var,
            section=section,
            key=key,
            raw_value=raw_value,
            value=value,
        ),
    )


def _apply_env_overrides(profile: RuntimeProfile, env: Mapping[str, str]) -> RuntimeProfile:
    for spec in OVERRIDE_SPECS:
        for env_var, parser in spec.aliases:
            raw_value = env.get(env_var)
            if raw_value in (None, ""):
                continue
            value = parser(raw_value)
            _set_override(profile, spec.section, spec.key, env_var, raw_value, value)
            break

    prefix = "JJ_CAT_PRIORITY_"
    for env_var, raw_value in env.items():
        if not env_var.startswith(prefix) or raw_value in (None, ""):
            continue
        category = env_var[len(prefix):].strip().lower()
        if not category:
            continue
        value = _parse_int(raw_value)
        profile.market_filters.category_priorities[category] = value
        profile.applied_overrides += (
            AppliedOverride(
                env_var=env_var,
                section="market_filters",
                key=f"category_priorities.{category}",
                raw_value=raw_value,
                value=value,
            ),
        )

    return profile


def load_runtime_profile(
    profile_name: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    profile_dir: Path = PROFILE_DIR,
) -> RuntimeProfile:
    source_env = os.environ if env is None else env
    selector_source = "argument"
    selector_value = profile_name or ""

    if not profile_name:
        env_selected = str(source_env.get(PROFILE_SELECTOR_ENV, "")).strip()
        if env_selected:
            profile_name = env_selected
            selector_source = PROFILE_SELECTOR_ENV
            selector_value = env_selected
        else:
            profile_name = DEFAULT_PROFILE_NAME
            selector_source = "default"
            selector_value = DEFAULT_PROFILE_NAME

    document, profile_path = _load_profile_document(profile_name, profile_dir)
    profile = _build_runtime_profile(
        document,
        profile_name=profile_name,
        profile_path=profile_path,
        selector_source=selector_source,
        selector_value=selector_value or profile_name,
    )
    return _apply_env_overrides(profile, source_env)


def write_effective_runtime_profile(
    profile_name: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    output_path: str | Path = DEFAULT_EFFECTIVE_OUTPUT_PATH,
    profile_dir: Path = PROFILE_DIR,
) -> Path:
    profile = load_runtime_profile(profile_name=profile_name, env=env, profile_dir=profile_dir)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = profile.to_dict()
    payload["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load a checked-in JJ runtime profile and dump the effective config.")
    parser.add_argument(
        "--profile",
        default=None,
        help=f"Profile name to load (default: ${PROFILE_SELECTOR_ENV} or {DEFAULT_PROFILE_NAME})",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_EFFECTIVE_OUTPUT_PATH),
        help=f"Path to write the effective runtime profile JSON (default: {DEFAULT_EFFECTIVE_OUTPUT_PATH})",
    )
    parser.add_argument("--list", action="store_true", help="List available checked-in runtime profiles and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list:
        for profile_name in available_runtime_profiles():
            print(profile_name)
        return 0

    output = write_effective_runtime_profile(profile_name=args.profile, output_path=args.output)
    print(output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
