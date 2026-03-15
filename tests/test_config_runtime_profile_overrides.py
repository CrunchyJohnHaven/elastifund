from __future__ import annotations

import pytest

from config.runtime_profile import RuntimeProfileError, load_runtime_profile


def test_invalid_risk_limit_override_is_revalidated() -> None:
    with pytest.raises(RuntimeProfileError, match="risk_limits.max_daily_loss_usd must be > 0"):
        load_runtime_profile(
            env={
                "JJ_RUNTIME_PROFILE": "blocked_safe",
                "JJ_MAX_DAILY_LOSS_USD": "-1",
            }
        )


def test_kelly_override_cannot_exceed_max_kelly_after_overrides() -> None:
    with pytest.raises(RuntimeProfileError, match="risk_limits.kelly_fraction cannot exceed"):
        load_runtime_profile(
            env={
                "JJ_RUNTIME_PROFILE": "blocked_safe",
                "JJ_KELLY_FRACTION": "0.9",
                "JJ_MAX_KELLY_FRACTION": "0.5",
            }
        )
