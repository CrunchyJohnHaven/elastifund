"""Standalone resource allocator for trading and non-trading budgets."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
import logging
import os
from pathlib import Path
import random
import statistics
from typing import Mapping

from .models import (
    AllocationDecision,
    AllocationMode,
    ArmStats,
    DeliverabilityRisk,
    NON_TRADING_AGENT,
    PerformanceObservation,
    TRADING_AGENT,
)
from .store import AllocatorStore, DEFAULT_DB_PATH

logger = logging.getLogger("JJ.resource_allocator")

AGENT_NAMES = (TRADING_AGENT, NON_TRADING_AGENT)


def _env_bool(name: str, default: bool = False, *, env: Mapping[str, str] | None = None) -> bool:
    source = env or os.environ
    raw = source.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, env: Mapping[str, str] | None = None) -> float:
    source = env or os.environ
    raw = source.get(name)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int, *, env: Mapping[str, str] | None = None) -> int:
    source = env or os.environ
    raw = source.get(name)
    if raw is None:
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _clamp_share(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def _iso_week_key(day: date) -> str:
    iso_year, iso_week, _ = day.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


@dataclass(frozen=True)
class AllocatorConfig:
    """Env-driven configuration for the resource allocator."""

    db_path: Path = DEFAULT_DB_PATH
    default_mode: AllocationMode = AllocationMode.THREE_LAYER
    enable_thompson_sampling: bool = True
    trading_budget_cap_usd: float = 100.0
    non_trading_send_quota_cap: int = 100
    non_trading_llm_token_cap: int = 50_000
    fixed_trading_share: float = 0.80
    min_non_trading_share: float = 0.10
    min_observations_per_arm: int = 5
    prior_alpha: float = 1.0
    prior_beta: float = 1.0
    roi_success_threshold: float = 0.0
    observation_lookback_days: int = 90
    risk_parity_min_observations: int = 20
    volatility_floor: float = 0.0001
    thompson_discount_gamma: float = 0.995
    thompson_tilt_max_pct: float = 0.35
    agent_min_share: float = 0.15
    agent_max_share: float = 0.85
    cash_reserve_min_share: float = 0.10
    cash_reserve_yellow_share: float = 0.15
    cash_reserve_max_share: float = 0.20
    kelly_bootstrap_observations: int = 21
    kelly_high_confidence_observations: int = 63
    kelly_bootstrap_fraction: float = 0.25
    kelly_medium_fraction: float = 1.0 / 3.0
    kelly_high_fraction: float = 0.50
    high_confidence_information_ratio: float = 0.25
    cusum_threshold_sigma: float = 3.0
    cusum_drift_sigma: float = 0.25

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AllocatorConfig":
        source = env or os.environ
        return cls(
            db_path=Path(source.get("JJ_ALLOCATOR_DB_PATH", str(DEFAULT_DB_PATH))),
            default_mode=AllocationMode.normalize(
                source.get("JJ_ALLOCATOR_MODE", AllocationMode.THREE_LAYER.value)
            ),
            enable_thompson_sampling=_env_bool(
                "JJ_ALLOCATOR_ENABLE_THOMPSON_SAMPLING",
                True,
                env=source,
            ),
            trading_budget_cap_usd=_env_float(
                "JJ_ALLOCATOR_TRADING_DAILY_BUDGET_USD",
                100.0,
                env=source,
            ),
            non_trading_send_quota_cap=_env_int(
                "JJ_ALLOCATOR_NON_TRADING_DAILY_SEND_QUOTA",
                100,
                env=source,
            ),
            non_trading_llm_token_cap=_env_int(
                "JJ_ALLOCATOR_NON_TRADING_DAILY_LLM_TOKENS",
                50_000,
                env=source,
            ),
            fixed_trading_share=_clamp_share(
                _env_float("JJ_ALLOCATOR_FIXED_TRADING_SHARE", 0.80, env=source)
            ),
            min_non_trading_share=_clamp_share(
                _env_float("JJ_ALLOCATOR_MIN_NON_TRADING_SHARE", 0.10, env=source)
            ),
            min_observations_per_arm=max(
                1,
                _env_int("JJ_ALLOCATOR_MIN_OBSERVATIONS_PER_ARM", 5, env=source),
            ),
            prior_alpha=max(0.1, _env_float("JJ_ALLOCATOR_PRIOR_ALPHA", 1.0, env=source)),
            prior_beta=max(0.1, _env_float("JJ_ALLOCATOR_PRIOR_BETA", 1.0, env=source)),
            roi_success_threshold=_env_float(
                "JJ_ALLOCATOR_SUCCESS_ROI_THRESHOLD",
                0.0,
                env=source,
            ),
            observation_lookback_days=max(
                1,
                _env_int("JJ_ALLOCATOR_OBSERVATION_LOOKBACK_DAYS", 90, env=source),
            ),
            risk_parity_min_observations=max(
                2,
                _env_int("JJ_ALLOCATOR_RISK_PARITY_MIN_OBSERVATIONS", 20, env=source),
            ),
            volatility_floor=max(
                1e-6,
                _env_float("JJ_ALLOCATOR_VOLATILITY_FLOOR", 0.0001, env=source),
            ),
            thompson_discount_gamma=max(
                0.90,
                min(
                    0.9999,
                    _env_float("JJ_ALLOCATOR_THOMPSON_DISCOUNT_GAMMA", 0.995, env=source),
                ),
            ),
            thompson_tilt_max_pct=_clamp_share(
                _env_float("JJ_ALLOCATOR_THOMPSON_TILT_MAX_PCT", 0.35, env=source)
            ),
            agent_min_share=_clamp_share(
                _env_float("JJ_ALLOCATOR_AGENT_MIN_SHARE", 0.15, env=source)
            ),
            agent_max_share=_clamp_share(
                _env_float("JJ_ALLOCATOR_AGENT_MAX_SHARE", 0.85, env=source)
            ),
            cash_reserve_min_share=_clamp_share(
                _env_float("JJ_ALLOCATOR_CASH_RESERVE_MIN_SHARE", 0.10, env=source)
            ),
            cash_reserve_yellow_share=_clamp_share(
                _env_float("JJ_ALLOCATOR_CASH_RESERVE_YELLOW_SHARE", 0.15, env=source)
            ),
            cash_reserve_max_share=_clamp_share(
                _env_float("JJ_ALLOCATOR_CASH_RESERVE_MAX_SHARE", 0.20, env=source)
            ),
            kelly_bootstrap_observations=max(
                1,
                _env_int("JJ_ALLOCATOR_KELLY_BOOTSTRAP_OBSERVATIONS", 21, env=source),
            ),
            kelly_high_confidence_observations=max(
                2,
                _env_int("JJ_ALLOCATOR_KELLY_HIGH_CONFIDENCE_OBSERVATIONS", 63, env=source),
            ),
            kelly_bootstrap_fraction=_clamp_share(
                _env_float("JJ_ALLOCATOR_KELLY_BOOTSTRAP_FRACTION", 0.25, env=source)
            ),
            kelly_medium_fraction=_clamp_share(
                _env_float("JJ_ALLOCATOR_KELLY_MEDIUM_FRACTION", 1.0 / 3.0, env=source)
            ),
            kelly_high_fraction=_clamp_share(
                _env_float("JJ_ALLOCATOR_KELLY_HIGH_FRACTION", 0.50, env=source)
            ),
            high_confidence_information_ratio=_env_float(
                "JJ_ALLOCATOR_HIGH_CONFIDENCE_INFORMATION_RATIO",
                0.25,
                env=source,
            ),
            cusum_threshold_sigma=max(
                0.5,
                _env_float("JJ_ALLOCATOR_CUSUM_THRESHOLD_SIGMA", 3.0, env=source),
            ),
            cusum_drift_sigma=max(
                0.0,
                _env_float("JJ_ALLOCATOR_CUSUM_DRIFT_SIGMA", 0.25, env=source),
            ),
        )

    @property
    def fixed_non_trading_share(self) -> float:
        return 1.0 - self.fixed_trading_share


class ResourceAllocator:
    """Decides daily budgets for trading and non-trading lanes."""

    def __init__(
        self,
        *,
        store: AllocatorStore | None = None,
        config: AllocatorConfig | None = None,
    ) -> None:
        self.config = config or AllocatorConfig.from_env()
        self.store = store or AllocatorStore(self.config.db_path)
        self.store.init_db()

    def record_performance(
        self,
        *,
        agent_name: str,
        observed_on: date,
        roi: float,
        metadata: dict | None = None,
    ) -> PerformanceObservation:
        observation = PerformanceObservation(
            agent_name=agent_name,
            observed_on=observed_on,
            roi=roi,
            metadata=metadata or {},
        )
        return self.store.record_observation(observation)

    def decide(
        self,
        *,
        decision_date: date | None = None,
        mode: AllocationMode | str | None = None,
        deliverability_risk: DeliverabilityRisk | str = DeliverabilityRisk.GREEN,
        seed: int | None = None,
        persist: bool = True,
    ) -> AllocationDecision:
        today = decision_date or date.today()
        risk = DeliverabilityRisk.normalize(deliverability_risk)
        requested_mode = AllocationMode.normalize(mode or self.config.default_mode)
        previous = self.store.latest_decision(before_date=today)

        if requested_mode is AllocationMode.THREE_LAYER:
            decision = self._three_layer_decision(
                decision_date=today,
                deliverability_risk=risk,
                previous=previous,
                seed=seed,
            )
        elif requested_mode is AllocationMode.THOMPSON_SAMPLING:
            decision = self._thompson_decision(
                decision_date=today,
                deliverability_risk=risk,
                previous=previous,
                seed=seed,
            )
        else:
            decision = self._fixed_split_decision(
                decision_date=today,
                deliverability_risk=risk,
                rationale="Fixed split mode.",
            )

        if persist:
            decision = self.store.record_decision(decision)

        logger.info(
            "allocation decision date=%s mode=%s trading_share=%.3f non_trading_share=%.3f "
            "cash_reserve_share=%.3f trading_budget_usd=%.2f non_trading_send_quota=%d "
            "non_trading_llm_tokens=%d deliverability_risk=%s risk_override=%s",
            decision.decision_date.isoformat(),
            decision.mode.value,
            decision.trading_share,
            decision.non_trading_share,
            decision.cash_reserve_share,
            decision.trading_budget_usd,
            decision.non_trading_send_quota,
            decision.non_trading_llm_token_budget,
            decision.deliverability_risk.value,
            decision.risk_override_applied,
        )
        return decision

    def _fixed_split_decision(
        self,
        *,
        decision_date: date,
        deliverability_risk: DeliverabilityRisk,
        rationale: str,
    ) -> AllocationDecision:
        trading_share = self.config.fixed_trading_share
        non_trading_share = 1.0 - trading_share
        return self._build_decision(
            decision_date=decision_date,
            mode=AllocationMode.FIXED_SPLIT,
            trading_share=trading_share,
            non_trading_share=non_trading_share,
            cash_reserve_share=0.0,
            deliverability_risk=deliverability_risk,
            rationale=rationale,
            metadata={
                "requested_mode": AllocationMode.FIXED_SPLIT.value,
                "layers": {},
            },
        )

    def _three_layer_decision(
        self,
        *,
        decision_date: date,
        deliverability_risk: DeliverabilityRisk,
        previous: AllocationDecision | None,
        seed: int | None,
    ) -> AllocationDecision:
        stats = self._compute_arm_stats(decision_date=decision_date)
        baseline_month = _month_key(decision_date)
        tilt_week = _iso_week_key(decision_date)

        baseline_shares, baseline_note, baseline_source = self._risk_parity_baseline(
            decision_date=decision_date,
            previous=previous,
            stats=stats,
            baseline_month=baseline_month,
        )
        tilted_shares, samples, tilt_note, tilt_source = self._thompson_tilt(
            decision_date=decision_date,
            previous=previous,
            stats=stats,
            baseline_shares=baseline_shares,
            tilt_week=tilt_week,
            seed=seed,
        )
        bounded_shares = self._apply_hard_share_bounds(tilted_shares)

        risk_override_applied = False
        risk_note = ""
        risk_ceiling = (
            previous.non_trading_share if previous is not None else self.config.fixed_non_trading_share
        )
        if (
            deliverability_risk in {DeliverabilityRisk.YELLOW, DeliverabilityRisk.RED}
            and bounded_shares[NON_TRADING_AGENT] > risk_ceiling
        ):
            bounded_shares = self._shares_from_non_trading_share(risk_ceiling, hard_bounds=True)
            risk_override_applied = True
            risk_note = (
                f"Deliverability risk {deliverability_risk.value} blocked a non-trading increase "
                f"above {risk_ceiling:.1%}."
            )

        cash_reserve_share = self._cash_reserve_share(
            deliverability_risk=deliverability_risk,
            stats=stats,
        )
        kelly_layer = {
            arm: {
                "fraction": stats[arm].kelly_fraction,
                "tier": stats[arm].confidence_tier,
                "recommended_active_share": round(
                    bounded_shares[arm] * stats[arm].kelly_fraction,
                    6,
                ),
            }
            for arm in AGENT_NAMES
        }
        metadata = {
            "requested_mode": AllocationMode.THREE_LAYER.value,
            "seed": seed if seed is not None else decision_date.toordinal(),
            "success_threshold": self.config.roi_success_threshold,
            "observation_lookback_days": self.config.observation_lookback_days,
            "periods": {
                "baseline_month": baseline_month,
                "tilt_week": tilt_week,
            },
            "layers": {
                "risk_parity": {
                    "shares": baseline_shares,
                    "source": baseline_source,
                    "rationale": baseline_note,
                },
                "thompson_tilt": {
                    "shares": tilted_shares,
                    "source": tilt_source,
                    "rationale": tilt_note,
                    "discount_gamma": self.config.thompson_discount_gamma,
                    "samples": samples,
                },
                "kelly": kelly_layer,
                "cusum": {
                    arm: {
                        "score_sigma": stats[arm].cusum_score_sigma,
                        "decay_detected": stats[arm].decay_detected,
                    }
                    for arm in AGENT_NAMES
                },
            },
            "constraints": {
                "agent_min_share": self.config.agent_min_share,
                "agent_max_share": self.config.agent_max_share,
                "cash_reserve_share": cash_reserve_share,
                "deliverability_risk": deliverability_risk.value,
                "risk_override_applied": risk_override_applied,
            },
            "stats": {
                arm: asdict(stats[arm])
                for arm in AGENT_NAMES
            },
        }
        rationale_parts = [
            "Three-layer allocator active.",
            baseline_note,
            tilt_note,
            (
                f"Cash reserve set to {cash_reserve_share:.0%}."
                if cash_reserve_share > self.config.cash_reserve_min_share
                else f"Cash reserve held at floor {cash_reserve_share:.0%}."
            ),
            (
                f"Kelly tiers: trading={stats[TRADING_AGENT].confidence_tier} "
                f"({stats[TRADING_AGENT].kelly_fraction:.2f}), "
                f"non-trading={stats[NON_TRADING_AGENT].confidence_tier} "
                f"({stats[NON_TRADING_AGENT].kelly_fraction:.2f})."
            ),
        ]
        if risk_note:
            rationale_parts.append(risk_note)

        strategy_documents = self._build_strategy_documents(
            decision_date=decision_date,
            stats=stats,
            baseline_shares=baseline_shares,
            tilted_shares=tilted_shares,
            final_shares=bounded_shares,
            cash_reserve_share=cash_reserve_share,
            deliverability_risk=deliverability_risk,
            rationale=" ".join(rationale_parts),
        )
        return self._build_decision(
            decision_date=decision_date,
            mode=AllocationMode.THREE_LAYER,
            trading_share=bounded_shares[TRADING_AGENT],
            non_trading_share=bounded_shares[NON_TRADING_AGENT],
            cash_reserve_share=cash_reserve_share,
            deliverability_risk=deliverability_risk,
            rationale=" ".join(rationale_parts),
            risk_override_applied=risk_override_applied,
            bandit_sample_trading=samples.get(TRADING_AGENT),
            bandit_sample_non_trading=samples.get(NON_TRADING_AGENT),
            metadata=metadata,
            strategy_documents=strategy_documents,
        )

    def _thompson_decision(
        self,
        *,
        decision_date: date,
        deliverability_risk: DeliverabilityRisk,
        previous: AllocationDecision | None,
        seed: int | None,
    ) -> AllocationDecision:
        if not self.config.enable_thompson_sampling:
            return self._fixed_split_decision(
                decision_date=decision_date,
                deliverability_risk=deliverability_risk,
                rationale="Thompson Sampling requested but feature flag is disabled; using fixed split.",
            )

        since_date = decision_date - timedelta(days=self.config.observation_lookback_days)
        stats = self.store.arm_stats(
            success_threshold=self.config.roi_success_threshold,
            since_date=since_date,
        )
        min_samples = min(
            stats[TRADING_AGENT].observations,
            stats[NON_TRADING_AGENT].observations,
        )
        if min_samples < self.config.min_observations_per_arm:
            return self._fixed_split_decision(
                decision_date=decision_date,
                deliverability_risk=deliverability_risk,
                rationale=(
                    "Thompson Sampling requested but observations are below the per-arm "
                    f"minimum ({min_samples} < {self.config.min_observations_per_arm}); using fixed split."
                ),
            )

        rng = self._rng(seed, decision_date)
        trading_sample = self._sample_arm(stats[TRADING_AGENT], rng)
        non_trading_sample = self._sample_arm(stats[NON_TRADING_AGENT], rng)
        sample_total = trading_sample + non_trading_sample
        raw_non_trading_share = (
            non_trading_sample / sample_total
            if sample_total > 0
            else self.config.fixed_non_trading_share
        )
        exploratory_non_trading_share = max(
            raw_non_trading_share,
            self.config.min_non_trading_share,
        )
        exploratory_non_trading_share = _clamp_share(exploratory_non_trading_share)
        risk_ceiling = (
            previous.non_trading_share
            if previous is not None
            else self.config.fixed_non_trading_share
        )
        final_non_trading_share = exploratory_non_trading_share
        risk_override_applied = False
        rationale = (
            "Thompson Sampling mode from ROI observations. "
            f"Trading arm sample={trading_sample:.4f}, non-trading arm sample={non_trading_sample:.4f}."
        )
        if (
            deliverability_risk in {DeliverabilityRisk.YELLOW, DeliverabilityRisk.RED}
            and final_non_trading_share > risk_ceiling
        ):
            final_non_trading_share = risk_ceiling
            risk_override_applied = True
            rationale += (
                f" Deliverability risk {deliverability_risk.value} blocked a non-trading increase "
                f"above {risk_ceiling:.1%}."
            )

        trading_share = 1.0 - final_non_trading_share
        metadata = {
            "requested_mode": AllocationMode.THOMPSON_SAMPLING.value,
            "seed": seed if seed is not None else decision_date.toordinal(),
            "success_threshold": self.config.roi_success_threshold,
            "observation_lookback_days": self.config.observation_lookback_days,
            "stats": {
                TRADING_AGENT: asdict(stats[TRADING_AGENT]),
                NON_TRADING_AGENT: asdict(stats[NON_TRADING_AGENT]),
            },
        }
        return self._build_decision(
            decision_date=decision_date,
            mode=AllocationMode.THOMPSON_SAMPLING,
            trading_share=trading_share,
            non_trading_share=final_non_trading_share,
            cash_reserve_share=0.0,
            deliverability_risk=deliverability_risk,
            rationale=rationale,
            risk_override_applied=risk_override_applied,
            bandit_sample_trading=trading_sample,
            bandit_sample_non_trading=non_trading_sample,
            metadata=metadata,
        )

    def _compute_arm_stats(self, *, decision_date: date) -> dict[str, ArmStats]:
        since_date = decision_date - timedelta(days=self.config.observation_lookback_days)
        stats: dict[str, ArmStats] = {}
        for agent_name in AGENT_NAMES:
            observations = self.store.list_observations(
                agent_name=agent_name,
                since_date=since_date,
            )
            stats[agent_name] = self._stats_for_observations(
                agent_name=agent_name,
                observations=observations,
                decision_date=decision_date,
            )
        return stats

    def _stats_for_observations(
        self,
        *,
        agent_name: str,
        observations: list[PerformanceObservation],
        decision_date: date,
    ) -> ArmStats:
        rois = [float(observation.roi) for observation in observations]
        successes = sum(1 for roi in rois if roi >= self.config.roi_success_threshold)
        failures = len(rois) - successes
        avg_roi = statistics.fmean(rois) if rois else 0.0
        volatility = statistics.stdev(rois) if len(rois) >= 2 else 0.0
        effective_volatility = max(volatility, self.config.volatility_floor)
        information_ratio = (
            avg_roi / effective_volatility
            if rois
            else 0.0
        )
        discounted_successes = 0.0
        discounted_failures = 0.0
        for observation in observations:
            age_days = max(0, (decision_date - observation.observed_on).days)
            weight = self.config.thompson_discount_gamma ** age_days
            if observation.roi >= self.config.roi_success_threshold:
                discounted_successes += weight
            else:
                discounted_failures += weight
        cusum_score_sigma, decay_detected = self._cusum_decay_signal(
            rois=rois,
            mean_roi=avg_roi,
            sigma=effective_volatility,
        )
        confidence_tier, kelly_fraction = self._kelly_profile(
            observations=len(rois),
            avg_roi=avg_roi,
            information_ratio=information_ratio,
            decay_detected=decay_detected,
        )
        return ArmStats(
            agent_name=agent_name,
            observations=len(rois),
            successes=successes,
            failures=failures,
            avg_roi=avg_roi,
            volatility=volatility,
            latest_roi=rois[-1] if rois else None,
            discounted_successes=discounted_successes,
            discounted_failures=discounted_failures,
            information_ratio=information_ratio,
            confidence_tier=confidence_tier,
            kelly_fraction=kelly_fraction,
            cusum_score_sigma=cusum_score_sigma,
            decay_detected=decay_detected,
        )

    def _cusum_decay_signal(
        self,
        *,
        rois: list[float],
        mean_roi: float,
        sigma: float,
    ) -> tuple[float, bool]:
        if len(rois) < 2 or sigma <= 0:
            return 0.0, False
        allowance = self.config.cusum_drift_sigma * sigma
        negative_cusum = 0.0
        min_negative_cusum = 0.0
        for roi in rois:
            negative_cusum = min(0.0, negative_cusum + roi - mean_roi + allowance)
            min_negative_cusum = min(min_negative_cusum, negative_cusum)
        score_sigma = abs(min_negative_cusum) / sigma
        return score_sigma, score_sigma >= self.config.cusum_threshold_sigma

    def _kelly_profile(
        self,
        *,
        observations: int,
        avg_roi: float,
        information_ratio: float,
        decay_detected: bool,
    ) -> tuple[str, float]:
        if decay_detected or avg_roi <= self.config.roi_success_threshold:
            return "bootstrapping", self.config.kelly_bootstrap_fraction
        if observations < self.config.kelly_bootstrap_observations:
            return "bootstrapping", self.config.kelly_bootstrap_fraction
        if (
            observations >= self.config.kelly_high_confidence_observations
            and information_ratio >= self.config.high_confidence_information_ratio
        ):
            return "high_confidence", self.config.kelly_high_fraction
        return "medium_confidence", self.config.kelly_medium_fraction

    def _risk_parity_baseline(
        self,
        *,
        decision_date: date,
        previous: AllocationDecision | None,
        stats: dict[str, ArmStats],
        baseline_month: str,
    ) -> tuple[dict[str, float], str, str]:
        reused = self._reuse_layer_shares(
            previous=previous,
            layer_name="risk_parity",
            period_name="baseline_month",
            period_value=baseline_month,
        )
        if reused is not None:
            return reused, "Reused prior monthly risk-parity baseline.", "reused"

        min_samples = min(stats[TRADING_AGENT].observations, stats[NON_TRADING_AGENT].observations)
        if min_samples < self.config.risk_parity_min_observations:
            return (
                self._fixed_split_shares(),
                (
                    "Risk parity fallback to fixed split because trailing 90-day observations "
                    f"are below the monthly threshold ({min_samples} < {self.config.risk_parity_min_observations})."
                ),
                "fallback_fixed_split",
            )

        inverse_volatility = {}
        for agent_name in AGENT_NAMES:
            sigma = max(stats[agent_name].volatility, self.config.volatility_floor)
            inverse_volatility[agent_name] = 1.0 / sigma
        total = sum(inverse_volatility.values())
        if total <= 0:
            return self._fixed_split_shares(), "Risk parity fallback to fixed split because sigma was degenerate.", "fallback_fixed_split"
        shares = {
            agent_name: inverse_volatility[agent_name] / total
            for agent_name in AGENT_NAMES
        }
        return shares, "Risk parity baseline from trailing 90-day inverse volatility.", "recomputed"

    def _thompson_tilt(
        self,
        *,
        decision_date: date,
        previous: AllocationDecision | None,
        stats: dict[str, ArmStats],
        baseline_shares: dict[str, float],
        tilt_week: str,
        seed: int | None,
    ) -> tuple[dict[str, float], dict[str, float], str, str]:
        if not self.config.enable_thompson_sampling:
            return baseline_shares, {}, "Tactical Thompson tilt disabled; using risk-parity baseline.", "disabled"

        reused = self._reuse_layer(previous=previous, layer_name="thompson_tilt", period_name="tilt_week", period_value=tilt_week)
        if reused is not None:
            shares = reused.get("shares")
            if isinstance(shares, dict):
                normalized_shares = self._shares_from_non_trading_share(
                    float(shares.get(NON_TRADING_AGENT, self.config.fixed_non_trading_share)),
                    hard_bounds=False,
                )
                samples = reused.get("samples")
                return (
                    normalized_shares,
                    {
                        TRADING_AGENT: float((samples or {}).get(TRADING_AGENT, 0.0)),
                        NON_TRADING_AGENT: float((samples or {}).get(NON_TRADING_AGENT, 0.0)),
                    },
                    "Reused prior weekly Thompson tilt.",
                    "reused",
                )

        min_samples = min(stats[TRADING_AGENT].observations, stats[NON_TRADING_AGENT].observations)
        if min_samples < self.config.min_observations_per_arm:
            return (
                baseline_shares,
                {},
                (
                    "Tactical Thompson tilt skipped because observations are below the weekly minimum "
                    f"({min_samples} < {self.config.min_observations_per_arm})."
                ),
                "insufficient_observations",
            )

        rng = self._rng(seed, decision_date)
        samples = {
            agent_name: self._sample_discounted_arm(stats[agent_name], rng)
            for agent_name in AGENT_NAMES
        }
        sample_total = sum(samples.values())
        if sample_total <= 0:
            return baseline_shares, samples, "Tactical Thompson tilt degenerated; using risk-parity baseline.", "degenerate"
        raw_target = {
            agent_name: samples[agent_name] / sample_total
            for agent_name in AGENT_NAMES
        }
        adjusted = {}
        for agent_name in AGENT_NAMES:
            baseline_share = max(baseline_shares[agent_name], self.config.volatility_floor)
            multiplier = raw_target[agent_name] / baseline_share
            multiplier = max(
                1.0 - self.config.thompson_tilt_max_pct,
                min(1.0 + self.config.thompson_tilt_max_pct, multiplier),
            )
            if stats[agent_name].decay_detected and multiplier > 1.0:
                multiplier = 1.0
            adjusted[agent_name] = baseline_shares[agent_name] * multiplier
        total_adjusted = sum(adjusted.values())
        if total_adjusted <= 0:
            return baseline_shares, samples, "Tactical Thompson tilt collapsed; using risk-parity baseline.", "degenerate"
        shares = {
            agent_name: adjusted[agent_name] / total_adjusted
            for agent_name in AGENT_NAMES
        }
        return shares, samples, "Weekly discounted Thompson tilt applied on top of risk parity.", "recomputed"

    def _rng(self, seed: int | None, decision_date: date) -> random.Random:
        return random.Random(seed if seed is not None else decision_date.toordinal())

    def _sample_arm(self, stats: ArmStats, rng: random.Random) -> float:
        alpha = self.config.prior_alpha + stats.successes
        beta = self.config.prior_beta + stats.failures
        return rng.betavariate(alpha, beta)

    def _sample_discounted_arm(self, stats: ArmStats, rng: random.Random) -> float:
        alpha = self.config.prior_alpha + stats.discounted_successes
        beta = self.config.prior_beta + stats.discounted_failures
        return rng.betavariate(alpha, beta)

    def _cash_reserve_share(
        self,
        *,
        deliverability_risk: DeliverabilityRisk,
        stats: dict[str, ArmStats],
    ) -> float:
        if deliverability_risk is DeliverabilityRisk.RED or any(
            stat.decay_detected for stat in stats.values()
        ):
            return self.config.cash_reserve_max_share
        if deliverability_risk is DeliverabilityRisk.YELLOW:
            return max(self.config.cash_reserve_min_share, self.config.cash_reserve_yellow_share)
        return self.config.cash_reserve_min_share

    def _apply_hard_share_bounds(self, shares: dict[str, float]) -> dict[str, float]:
        return self._shares_from_non_trading_share(
            shares[NON_TRADING_AGENT],
            hard_bounds=True,
        )

    def _shares_from_non_trading_share(
        self,
        non_trading_share: float,
        *,
        hard_bounds: bool,
    ) -> dict[str, float]:
        floor = self.config.min_non_trading_share
        ceiling = 1.0 - floor
        if hard_bounds:
            floor = max(floor, self.config.agent_min_share)
            ceiling = min(ceiling, self.config.agent_max_share)
        bounded_non_trading = max(floor, min(ceiling, _clamp_share(non_trading_share)))
        return {
            TRADING_AGENT: round(1.0 - bounded_non_trading, 6),
            NON_TRADING_AGENT: round(bounded_non_trading, 6),
        }

    def _fixed_split_shares(self) -> dict[str, float]:
        return {
            TRADING_AGENT: self.config.fixed_trading_share,
            NON_TRADING_AGENT: self.config.fixed_non_trading_share,
        }

    def _reuse_layer_shares(
        self,
        *,
        previous: AllocationDecision | None,
        layer_name: str,
        period_name: str,
        period_value: str,
    ) -> dict[str, float] | None:
        layer = self._reuse_layer(
            previous=previous,
            layer_name=layer_name,
            period_name=period_name,
            period_value=period_value,
        )
        if layer is None:
            return None
        shares = layer.get("shares")
        if not isinstance(shares, dict):
            return None
        try:
            return {
                TRADING_AGENT: float(shares[TRADING_AGENT]),
                NON_TRADING_AGENT: float(shares[NON_TRADING_AGENT]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def _reuse_layer(
        self,
        *,
        previous: AllocationDecision | None,
        layer_name: str,
        period_name: str,
        period_value: str,
    ) -> dict | None:
        if previous is None:
            return None
        periods = previous.metadata.get("periods", {})
        if periods.get(period_name) != period_value:
            return None
        layers = previous.metadata.get("layers", {})
        layer = layers.get(layer_name)
        return layer if isinstance(layer, dict) else None

    def _build_strategy_documents(
        self,
        *,
        decision_date: date,
        stats: dict[str, ArmStats],
        baseline_shares: dict[str, float],
        tilted_shares: dict[str, float],
        final_shares: dict[str, float],
        cash_reserve_share: float,
        deliverability_risk: DeliverabilityRisk,
        rationale: str,
    ) -> tuple[dict[str, object], ...]:
        capital_pool_usd = self.config.trading_budget_cap_usd * (1.0 - cash_reserve_share)
        documents: list[dict[str, object]] = []
        for agent_name in AGENT_NAMES:
            active_multiplier = stats[agent_name].kelly_fraction
            trading_budget = round(capital_pool_usd * final_shares[agent_name], 2)
            send_quota = int(round(self.config.non_trading_send_quota_cap * final_shares[agent_name]))
            llm_tokens = int(round(self.config.non_trading_llm_token_cap * final_shares[agent_name]))
            document = {
                "index": "elastifund-strategies",
                "strategy_key": f"capital_allocator:{agent_name}",
                "decision_date": decision_date.isoformat(),
                "agent_name": agent_name,
                "strategy_type": "capital_allocator",
                "allocation_mode": AllocationMode.THREE_LAYER.value,
                "baseline_share": round(baseline_shares[agent_name], 6),
                "tilted_share": round(tilted_shares[agent_name], 6),
                "final_share": round(final_shares[agent_name], 6),
                "cash_reserve_share": round(cash_reserve_share, 6),
                "kelly_fraction": round(active_multiplier, 6),
                "confidence_tier": stats[agent_name].confidence_tier,
                "volatility_90d": round(stats[agent_name].volatility, 8),
                "avg_roi_90d": round(stats[agent_name].avg_roi, 8),
                "cusum_score_sigma": round(stats[agent_name].cusum_score_sigma, 6),
                "decay_detected": stats[agent_name].decay_detected,
                "deliverability_risk": deliverability_risk.value,
                "trading_budget_usd": trading_budget,
                "non_trading_send_quota": send_quota,
                "non_trading_llm_token_budget": llm_tokens,
                "recommended_active_capital_usd": round(trading_budget * active_multiplier, 2),
                "recommended_active_send_quota": int(round(send_quota * active_multiplier)),
                "recommended_active_llm_token_budget": int(round(llm_tokens * active_multiplier)),
                "rationale": rationale,
            }
            documents.append(document)
        return tuple(documents)

    def _build_decision(
        self,
        *,
        decision_date: date,
        mode: AllocationMode,
        trading_share: float,
        non_trading_share: float,
        cash_reserve_share: float,
        deliverability_risk: DeliverabilityRisk,
        rationale: str,
        risk_override_applied: bool = False,
        bandit_sample_trading: float | None = None,
        bandit_sample_non_trading: float | None = None,
        metadata: dict | None = None,
        strategy_documents: tuple[dict[str, object], ...] = (),
    ) -> AllocationDecision:
        trading_share = _clamp_share(trading_share)
        non_trading_share = _clamp_share(non_trading_share)
        cash_reserve_share = _clamp_share(cash_reserve_share)
        trading_capital_pool = self.config.trading_budget_cap_usd * (1.0 - cash_reserve_share)
        return AllocationDecision(
            decision_date=decision_date,
            mode=mode,
            trading_share=trading_share,
            non_trading_share=non_trading_share,
            trading_budget_usd=round(trading_capital_pool * trading_share, 2),
            non_trading_send_quota=int(round(self.config.non_trading_send_quota_cap * non_trading_share)),
            non_trading_llm_token_budget=int(
                round(self.config.non_trading_llm_token_cap * non_trading_share)
            ),
            deliverability_risk=deliverability_risk,
            rationale=rationale,
            cash_reserve_share=cash_reserve_share,
            risk_override_applied=risk_override_applied,
            bandit_sample_trading=bandit_sample_trading,
            bandit_sample_non_trading=bandit_sample_non_trading,
            metadata=metadata or {},
            strategy_documents=strategy_documents,
        )

    @staticmethod
    def format_decision(decision: AllocationDecision) -> str:
        kelly = decision.metadata.get("layers", {}).get("kelly", {})
        trading_kelly = kelly.get(TRADING_AGENT, {}).get("fraction")
        non_trading_kelly = kelly.get(NON_TRADING_AGENT, {}).get("fraction")
        formatted = (
            f"date={decision.decision_date.isoformat()} mode={decision.mode.value} "
            f"trading_share={decision.trading_share:.3f} non_trading_share={decision.non_trading_share:.3f} "
            f"cash_reserve_share={decision.cash_reserve_share:.3f} "
            f"trading_budget_usd={decision.trading_budget_usd:.2f} "
            f"non_trading_send_quota={decision.non_trading_send_quota} "
            f"non_trading_llm_tokens={decision.non_trading_llm_token_budget} "
            f"deliverability_risk={decision.deliverability_risk.value} "
            f"risk_override={decision.risk_override_applied}"
        )
        if trading_kelly is not None and non_trading_kelly is not None:
            formatted += (
                f" trading_kelly={float(trading_kelly):.3f} "
                f"non_trading_kelly={float(non_trading_kelly):.3f}"
            )
        return formatted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standalone resource allocator")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in AllocationMode],
        default=None,
        help="Allocator mode. Defaults to JJ_ALLOCATOR_MODE or three_layer.",
    )
    parser.add_argument(
        "--deliverability-risk",
        choices=[risk.value for risk in DeliverabilityRisk],
        default=DeliverabilityRisk.GREEN.value,
        help="Risk state for the non-trading lane.",
    )
    parser.add_argument(
        "--decision-date",
        default=date.today().isoformat(),
        help="Decision date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Deterministic seed for Thompson sampling layers.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override allocator DB path for this run.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Compute a decision without writing it to SQLite.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = AllocatorConfig.from_env()
    if args.db_path:
        config = replace(config, db_path=Path(args.db_path))

    allocator = ResourceAllocator(config=config)
    decision = allocator.decide(
        decision_date=date.fromisoformat(args.decision_date),
        mode=args.mode,
        deliverability_risk=args.deliverability_risk,
        seed=args.seed,
        persist=not args.no_persist,
    )
    print(ResourceAllocator.format_decision(decision))
    print(allocator.store.status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
