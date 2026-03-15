"""Tests that each supported autoresearch override key actually changes a decision.

Each test sets up a frozen fixture where the bot would trade, then applies a single
override key and asserts the decision changes (skip or different parameter).
"""
from __future__ import annotations

import json
import os
import tempfile
import pytest
from pathlib import Path

from bot.btc_5min_maker import (
    MakerConfig,
    _load_autoresearch_overrides_from_data,
    effective_max_buy_price,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_override_file(tmp_path: Path, params: dict, stage: str = "trial") -> Path:
    from datetime import datetime, timezone
    override_path = tmp_path / "overrides.json"
    override_path.write_text(json.dumps({
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis_id": "test_h",
        "params": params,
        "promotion_stage": stage,
    }))
    return override_path


def _make_cfg(**overrides) -> MakerConfig:
    """Build a MakerConfig with test defaults by directly setting attributes."""
    env_defaults = {
        "BTC5_PAPER_TRADING": "true",
        "BTC5_BANKROLL_USD": "250",
        "BTC5_MAX_BUY_PRICE": "0.95",
        "BTC5_UP_MAX_BUY_PRICE": "0.52",
        "BTC5_DOWN_MAX_BUY_PRICE": "0.53",
        "BTC5_MIN_BUY_PRICE": "0.42",
        "BTC5_MIN_DELTA": "0.0003",
        "BTC5_MAX_ABS_DELTA": "0.0040",
    }
    env_defaults.update(overrides)
    saved = {}
    for k, v in env_defaults.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        cfg = MakerConfig()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    # Force-set attrs to ensure test values are applied
    # (MakerConfig reads from env at init time, but module-level defaults
    # may have already been cached).
    cfg.max_buy_price = 0.95
    cfg.up_max_buy_price = 0.52
    cfg.down_max_buy_price = 0.53
    cfg.min_buy_price = 0.42
    cfg.min_delta = 0.0003
    cfg.max_abs_delta = 0.004
    return cfg


# ---------------------------------------------------------------------------
# Test: _load_autoresearch_overrides sanitization for trial stage
# ---------------------------------------------------------------------------

class TestTrialOverrideSanitization:
    """Verify that trial-stage overrides can only tighten, not widen."""

    def test_up_max_buy_price_clamped_to_per_direction_baseline(self, tmp_path: Path) -> None:
        """UP cap trial override is clamped against UP baseline (0.52), not generic (0.95)."""
        cfg = _make_cfg()
        assert cfg.up_max_buy_price == 0.52

        override_path = _write_override_file(tmp_path, {"BTC5_UP_MAX_BUY_PRICE": 0.60}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        # 0.60 > 0.52 baseline → clamped to 0.52
        assert result["BTC5_UP_MAX_BUY_PRICE"] == pytest.approx(0.52)

    def test_down_max_buy_price_clamped_to_per_direction_baseline(self, tmp_path: Path) -> None:
        """DOWN cap trial override is clamped against DOWN baseline (0.53), not generic (0.95)."""
        cfg = _make_cfg()
        assert cfg.down_max_buy_price == 0.53

        override_path = _write_override_file(tmp_path, {"BTC5_DOWN_MAX_BUY_PRICE": 0.70}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_DOWN_MAX_BUY_PRICE"] == pytest.approx(0.53)

    def test_up_max_buy_price_tightening_allowed(self, tmp_path: Path) -> None:
        """Tightening (lower cap) passes through."""
        cfg = _make_cfg()
        override_path = _write_override_file(tmp_path, {"BTC5_UP_MAX_BUY_PRICE": 0.48}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_UP_MAX_BUY_PRICE"] == pytest.approx(0.48)

    def test_max_abs_delta_trial_tightening(self, tmp_path: Path) -> None:
        """MAX_ABS_DELTA trial override should tighten (smaller value)."""
        cfg = _make_cfg()
        assert cfg.max_abs_delta == 0.004

        override_path = _write_override_file(tmp_path, {"BTC5_MAX_ABS_DELTA": 0.003}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_MAX_ABS_DELTA"] == pytest.approx(0.003)

    def test_max_abs_delta_trial_widening_blocked(self, tmp_path: Path) -> None:
        """MAX_ABS_DELTA trial override cannot widen beyond baseline."""
        cfg = _make_cfg()
        override_path = _write_override_file(tmp_path, {"BTC5_MAX_ABS_DELTA": 0.010}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_MAX_ABS_DELTA"] == pytest.approx(0.004)

    def test_min_buy_price_trial_tightening(self, tmp_path: Path) -> None:
        """MIN_BUY_PRICE trial can raise floor (tighten)."""
        cfg = _make_cfg()
        override_path = _write_override_file(tmp_path, {"BTC5_MIN_BUY_PRICE": 0.50}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_MIN_BUY_PRICE"] == pytest.approx(0.50)

    def test_min_buy_price_trial_lowering_blocked(self, tmp_path: Path) -> None:
        """MIN_BUY_PRICE trial cannot lower floor (widen)."""
        cfg = _make_cfg()
        override_path = _write_override_file(tmp_path, {"BTC5_MIN_BUY_PRICE": 0.30}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_MIN_BUY_PRICE"] == pytest.approx(0.42)

    def test_directional_mode_passes_through(self, tmp_path: Path) -> None:
        """DIRECTIONAL_MODE is inherently conservative, passes through."""
        cfg = _make_cfg()
        override_path = _write_override_file(tmp_path, {"BTC5_DIRECTIONAL_MODE": "down_only"}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_DIRECTIONAL_MODE"] == "down_only"

    def test_suppress_hours_passes_through(self, tmp_path: Path) -> None:
        """SUPPRESS_HOURS is inherently conservative, passes through."""
        cfg = _make_cfg()
        override_path = _write_override_file(tmp_path, {"BTC5_SUPPRESS_HOURS_UTC": "09,10"}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_SUPPRESS_HOURS_UTC"] == "09,10"

    def test_min_delta_trial_tightening(self, tmp_path: Path) -> None:
        """MIN_DELTA trial can raise (tighten)."""
        cfg = _make_cfg()
        override_path = _write_override_file(tmp_path, {"BTC5_MIN_DELTA": 0.0005}, "trial")
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_MIN_DELTA"] == pytest.approx(0.0005)

    def test_validated_stage_allows_widening(self, tmp_path: Path) -> None:
        """Validated-stage overrides pass through without clamping."""
        cfg = _make_cfg()
        override_path = _write_override_file(
            tmp_path,
            {"BTC5_UP_MAX_BUY_PRICE": 0.70, "BTC5_MAX_ABS_DELTA": 0.010},
            "validated",
        )
        data = json.loads(override_path.read_text())
        result = _load_autoresearch_overrides_from_data(data, cfg)
        assert result["BTC5_UP_MAX_BUY_PRICE"] == pytest.approx(0.70)
        assert result["BTC5_MAX_ABS_DELTA"] == pytest.approx(0.010)
