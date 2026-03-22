#!/usr/bin/env python3
"""
Tests for bot/capital_router.py — Capital Router
=================================================
Validates structural priority enforcement, lane budget calculations,
freeze/unfreeze audit trail, and directional blocking logic.

35+ tests covering:
  - Default routing table structure and priority ordering
  - Directional BTC5 frozen by default
  - Lane budget calculations
  - Freeze/unfreeze with logging
  - Capital allocation proportional to enabled lanes
  - Directional blocking when promotion not passed
  - Allocation respects max_capital_pct caps
  - Edge cases: zero capital, all lanes frozen, unknown lanes

Author: JJ (autonomous)
Date: 2026-03-22
"""

from __future__ import annotations

import sys
import os
import pytest

# Ensure repo root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.capital_router import (
    CapitalRouter,
    LaneConfig,
    FreezeRecord,
    _default_lane_configs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def router() -> CapitalRouter:
    """Standard router with $1000 capital and default config."""
    return CapitalRouter(total_capital=1000.0)


@pytest.fixture
def small_router() -> CapitalRouter:
    """Two-lane router for isolated tests."""
    lanes = [
        LaneConfig(lane_name="alpha", priority=0, enabled=True, max_capital_pct=0.40),
        LaneConfig(lane_name="beta", priority=1, enabled=True, max_capital_pct=0.30),
    ]
    return CapitalRouter(total_capital=500.0, config=lanes)


# ---------------------------------------------------------------------------
# Default routing table structure
# ---------------------------------------------------------------------------


class TestDefaultRoutingTable:
    def test_has_eight_lanes(self, router: CapitalRouter) -> None:
        table = router.get_routing_table()
        assert len(table) == 8

    def test_sorted_by_priority(self, router: CapitalRouter) -> None:
        table = router.get_routing_table()
        priorities = [row["priority"] for row in table]
        assert priorities == ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7"]

    def test_structural_lanes_before_directional(self, router: CapitalRouter) -> None:
        table = router.get_routing_table()
        structural = ["neg_risk", "cross_plat", "resolution_sniper", "dual_sided_pair"]
        for row in table:
            if row["lane"] in structural:
                assert row["enabled"] is True, f"{row['lane']} should be enabled"

    def test_neg_risk_is_p0(self, router: CapitalRouter) -> None:
        table = router.get_routing_table()
        assert table[0]["lane"] == "neg_risk"
        assert table[0]["priority"] == "P0"

    def test_resolution_sniper_is_p2(self, router: CapitalRouter) -> None:
        table = router.get_routing_table()
        p2 = [r for r in table if r["priority"] == "P2"]
        assert len(p2) == 1
        assert p2[0]["lane"] == "resolution_sniper"

    def test_directional_btc5_is_p7(self, router: CapitalRouter) -> None:
        table = router.get_routing_table()
        assert table[-1]["lane"] == "directional_btc5"
        assert table[-1]["priority"] == "P7"

    def test_all_lanes_use_maker_orders(self, router: CapitalRouter) -> None:
        table = router.get_routing_table()
        for row in table:
            assert row["order_type"] == "maker"


# ---------------------------------------------------------------------------
# BTC5 frozen by default
# ---------------------------------------------------------------------------


class TestBtc5FrozenByDefault:
    def test_btc5_disabled(self, router: CapitalRouter) -> None:
        assert router.is_lane_enabled("directional_btc5") is False

    def test_btc5_budget_is_zero(self, router: CapitalRouter) -> None:
        assert router.get_lane_budget("directional_btc5") == 0.0

    def test_btc5_blocked_by_default(self, router: CapitalRouter) -> None:
        assert router.should_block_directional() is True

    def test_btc5_blocked_even_with_promotion_if_frozen(self, router: CapitalRouter) -> None:
        # Promotion passed but lane still frozen => blocked
        assert router.should_block_directional(btc5_promotion_passed=True) is True

    def test_llm_tournament_also_disabled(self, router: CapitalRouter) -> None:
        assert router.is_lane_enabled("llm_tournament") is False


# ---------------------------------------------------------------------------
# Lane budget calculations
# ---------------------------------------------------------------------------


class TestLaneBudget:
    def test_neg_risk_budget(self, router: CapitalRouter) -> None:
        assert router.get_lane_budget("neg_risk") == pytest.approx(150.0)

    def test_resolution_sniper_budget(self, router: CapitalRouter) -> None:
        assert router.get_lane_budget("resolution_sniper") == pytest.approx(200.0)

    def test_dual_sided_pair_budget(self, router: CapitalRouter) -> None:
        assert router.get_lane_budget("dual_sided_pair") == pytest.approx(150.0)

    def test_whale_copy_budget(self, router: CapitalRouter) -> None:
        assert router.get_lane_budget("whale_copy") == pytest.approx(100.0)

    def test_disabled_lane_budget_zero(self, router: CapitalRouter) -> None:
        assert router.get_lane_budget("llm_tournament") == 0.0

    def test_unknown_lane_budget_zero(self, router: CapitalRouter) -> None:
        assert router.get_lane_budget("nonexistent_lane") == 0.0

    def test_budget_scales_with_capital(self) -> None:
        r = CapitalRouter(total_capital=2000.0)
        assert r.get_lane_budget("neg_risk") == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# Freeze / unfreeze
# ---------------------------------------------------------------------------


class TestFreezeUnfreeze:
    def test_freeze_disables_lane(self, router: CapitalRouter) -> None:
        assert router.is_lane_enabled("whale_copy") is True
        router.freeze_lane("whale_copy", "poor signal quality")
        assert router.is_lane_enabled("whale_copy") is False

    def test_freeze_zeroes_budget(self, router: CapitalRouter) -> None:
        router.freeze_lane("whale_copy", "test")
        assert router.get_lane_budget("whale_copy") == 0.0

    def test_freeze_logged(self, router: CapitalRouter) -> None:
        router.freeze_lane("whale_copy", "drawdown exceeded")
        log = router.get_freeze_log()
        assert len(log) == 1
        assert log[0]["lane"] == "whale_copy"
        assert log[0]["action"] == "freeze"
        assert log[0]["reason"] == "drawdown exceeded"

    def test_unfreeze_enables_lane(self, router: CapitalRouter) -> None:
        router.freeze_lane("whale_copy", "test")
        router.unfreeze_lane("whale_copy")
        assert router.is_lane_enabled("whale_copy") is True

    def test_unfreeze_logged(self, router: CapitalRouter) -> None:
        router.freeze_lane("whale_copy", "test")
        router.unfreeze_lane("whale_copy")
        log = router.get_freeze_log()
        assert len(log) == 2
        assert log[1]["action"] == "unfreeze"

    def test_freeze_unknown_lane_no_crash(self, router: CapitalRouter) -> None:
        router.freeze_lane("nonexistent", "test")
        assert len(router.get_freeze_log()) == 0

    def test_unfreeze_unknown_lane_no_crash(self, router: CapitalRouter) -> None:
        router.unfreeze_lane("nonexistent")
        assert len(router.get_freeze_log()) == 0

    def test_double_freeze_idempotent(self, router: CapitalRouter) -> None:
        router.freeze_lane("whale_copy", "first")
        router.freeze_lane("whale_copy", "second")
        # Only one log entry since second is a no-op
        assert len(router.get_freeze_log()) == 1

    def test_double_unfreeze_idempotent(self, router: CapitalRouter) -> None:
        # whale_copy starts enabled, unfreezing is a no-op
        router.unfreeze_lane("whale_copy")
        assert len(router.get_freeze_log()) == 0


# ---------------------------------------------------------------------------
# Capital allocation
# ---------------------------------------------------------------------------


class TestAllocation:
    def test_allocation_returns_all_lanes(self, router: CapitalRouter) -> None:
        alloc = router.allocate(1000.0)
        assert len(alloc) == 8

    def test_disabled_lanes_get_zero(self, router: CapitalRouter) -> None:
        alloc = router.allocate(1000.0)
        assert alloc["directional_btc5"] == 0.0
        assert alloc["llm_tournament"] == 0.0

    def test_enabled_lanes_get_positive(self, router: CapitalRouter) -> None:
        alloc = router.allocate(1000.0)
        for name in ["neg_risk", "resolution_sniper", "dual_sided_pair", "whale_copy"]:
            assert alloc[name] > 0.0, f"{name} should get positive allocation"

    def test_allocation_respects_caps(self, router: CapitalRouter) -> None:
        alloc = router.allocate(1000.0)
        for name, lc in router._lanes.items():
            if lc.enabled:
                assert alloc[name] <= 1000.0 * lc.max_capital_pct + 0.01

    def test_allocation_updates_total_capital(self, router: CapitalRouter) -> None:
        router.allocate(2000.0)
        assert router.total_capital == 2000.0

    def test_proportional_allocation_small_router(self, small_router: CapitalRouter) -> None:
        alloc = small_router.allocate(500.0)
        # total_pct = 0.70, under 1.0 so each gets full share
        assert alloc["alpha"] == pytest.approx(200.0)
        assert alloc["beta"] == pytest.approx(150.0)

    def test_over_allocated_scales_down(self) -> None:
        lanes = [
            LaneConfig(lane_name="a", priority=0, enabled=True, max_capital_pct=0.60),
            LaneConfig(lane_name="b", priority=1, enabled=True, max_capital_pct=0.60),
        ]
        r = CapitalRouter(total_capital=1000.0, config=lanes)
        alloc = r.allocate(1000.0)
        # total_pct = 1.2, so each gets 0.6/1.2 = 0.5 share
        assert alloc["a"] == pytest.approx(500.0)
        assert alloc["b"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Directional blocking
# ---------------------------------------------------------------------------


class TestDirectionalBlocking:
    def test_blocked_by_default(self, router: CapitalRouter) -> None:
        assert router.should_block_directional() is True

    def test_blocked_with_promotion_but_frozen(self, router: CapitalRouter) -> None:
        assert router.should_block_directional(btc5_promotion_passed=True) is True

    def test_unblocked_after_unfreeze_and_promotion(self, router: CapitalRouter) -> None:
        router.unfreeze_lane("directional_btc5")
        assert router.should_block_directional(btc5_promotion_passed=True) is False

    def test_still_blocked_after_unfreeze_without_promotion(self, router: CapitalRouter) -> None:
        router.unfreeze_lane("directional_btc5")
        assert router.should_block_directional(btc5_promotion_passed=False) is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_capital(self) -> None:
        r = CapitalRouter(total_capital=0.0)
        alloc = r.allocate(0.0)
        for v in alloc.values():
            assert v == 0.0

    def test_negative_capital_clamped(self) -> None:
        r = CapitalRouter(total_capital=-100.0)
        assert r.total_capital == 0.0

    def test_all_lanes_frozen(self, router: CapitalRouter) -> None:
        for name in list(router._lanes.keys()):
            router.freeze_lane(name, "test")
        alloc = router.allocate(1000.0)
        for v in alloc.values():
            assert v == 0.0

    def test_repr(self, router: CapitalRouter) -> None:
        r = repr(router)
        assert "CapitalRouter" in r
        assert "$1000.00" in r

    def test_get_lane_config_exists(self, router: CapitalRouter) -> None:
        lc = router.get_lane_config("neg_risk")
        assert lc is not None
        assert lc.priority == 0

    def test_get_lane_config_unknown(self, router: CapitalRouter) -> None:
        assert router.get_lane_config("nonexistent") is None


# ---------------------------------------------------------------------------
# LaneConfig validation
# ---------------------------------------------------------------------------


class TestLaneConfigValidation:
    def test_invalid_priority_raises(self) -> None:
        with pytest.raises(ValueError, match="Priority"):
            LaneConfig(lane_name="bad", priority=8)

    def test_negative_priority_raises(self) -> None:
        with pytest.raises(ValueError, match="Priority"):
            LaneConfig(lane_name="bad", priority=-1)

    def test_invalid_capital_pct_raises(self) -> None:
        with pytest.raises(ValueError, match="max_capital_pct"):
            LaneConfig(lane_name="bad", priority=0, max_capital_pct=1.5)

    def test_invalid_order_type_raises(self) -> None:
        with pytest.raises(ValueError, match="order_type"):
            LaneConfig(lane_name="bad", priority=0, order_type="limit")

    def test_valid_config_no_error(self) -> None:
        lc = LaneConfig(lane_name="good", priority=3, max_capital_pct=0.25, order_type="taker")
        assert lc.lane_name == "good"


# ---------------------------------------------------------------------------
# Default config integrity
# ---------------------------------------------------------------------------


class TestDefaultConfigs:
    def test_default_configs_valid(self) -> None:
        configs = _default_lane_configs()
        assert len(configs) == 8

    def test_no_duplicate_priorities(self) -> None:
        configs = _default_lane_configs()
        priorities = [c.priority for c in configs]
        assert len(priorities) == len(set(priorities))

    def test_no_duplicate_names(self) -> None:
        configs = _default_lane_configs()
        names = [c.lane_name for c in configs]
        assert len(names) == len(set(names))

    def test_dual_sided_has_pair_config(self) -> None:
        configs = _default_lane_configs()
        ds = [c for c in configs if c.lane_name == "dual_sided_pair"][0]
        assert ds.combined_cost_cap == 0.97
        assert ds.reserve_pct == 0.20
        assert ds.per_market_cap_usd == 10.0
        assert ds.max_markets == 6
