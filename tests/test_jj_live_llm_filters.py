from __future__ import annotations

import bot.jj_live as jj_live


def test_apply_llm_market_filters_rejects_unknown_resolution_when_gate_active():
    original_max = jj_live.MAX_RESOLUTION_HOURS
    try:
        jj_live.MAX_RESOLUTION_HOURS = 24.0
        allowed, reason, category, normalized_resolution = jj_live.apply_llm_market_filters(
            "Will parliament pass bill X this week?",
            resolution_hours=None,
            slug="",
        )
    finally:
        jj_live.MAX_RESOLUTION_HOURS = original_max

    assert allowed is False
    assert reason == "unknown_resolution"
    assert category in {"politics", "unknown"}
    assert normalized_resolution is None


def test_apply_llm_market_filters_uses_slug_to_block_dedicated_btc5_markets():
    allowed, reason, _category, _normalized_resolution = jj_live.apply_llm_market_filters(
        "Will this market resolve YES?",
        resolution_hours=0.25,
        slug="btc-up-or-down-march-15-12-35-5m",
    )
    assert allowed is False
    assert reason == "btc5_dedicated"
