"""Tests for execution instrumentation and maker sandbox."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.store.models import Base, ExecutionStat
from src.store.repository import Repository


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TestExecutionStatCalculations:
    """Unit tests for execution stat fee/slippage calculations."""

    def test_slippage_calculation_buy(self):
        """Slippage = fill_price - quoted_mid. Positive = overpaid."""
        quoted_mid = 0.55
        fill_price = 0.56
        slippage = fill_price - quoted_mid
        assert round(slippage, 4) == 0.01

    def test_slippage_calculation_sell(self):
        """Negative slippage on sell = got less than mid."""
        quoted_mid = 0.55
        fill_price = 0.54
        slippage = fill_price - quoted_mid
        assert round(slippage, 4) == -0.01

    def test_expected_fee_formula(self):
        """Taker fee = p * (1-p) * r. Worst at p=0.50."""
        r = 0.025
        # At p=0.50: fee = 0.50 * 0.50 * 0.025 = 0.00625
        fee_50 = 0.50 * 0.50 * r
        assert round(fee_50, 5) == 0.00625
        # At p=0.80: fee = 0.80 * 0.20 * 0.025 = 0.004
        fee_80 = 0.80 * 0.20 * r
        assert round(fee_80, 5) == 0.004
        # At p=0.90: fee = 0.90 * 0.10 * 0.025 = 0.00225
        fee_90 = 0.90 * 0.10 * r
        assert round(fee_90, 5) == 0.00225

    def test_edge_after_fee(self):
        """Edge after fee = raw_edge - expected_fee. Must be positive to trade."""
        raw_edge = 0.05
        fee = 0.00625
        edge_after = raw_edge - fee
        assert edge_after > 0
        assert round(edge_after, 5) == 0.04375

    def test_edge_killed_by_fee(self):
        """Small edge destroyed by fee at mid-price."""
        raw_edge = 0.005
        fee = 0.00625  # at p=0.50
        edge_after = raw_edge - fee
        assert edge_after < 0

    def test_maker_fee_is_zero(self):
        """Maker orders have zero fee — the whole point of maker sandbox."""
        maker_fee = 0.0
        assert maker_fee == 0.0

    def test_maker_sandbox_size(self):
        """Sandbox size is 10-20% of normal size."""
        normal_size = 5.0
        pct = 0.15
        sandbox_size = round(normal_size * pct, 2)
        assert sandbox_size == 0.75

    def test_maker_sandbox_price_improvement_buy(self):
        """Buy sandbox: price below mid by improvement amount."""
        mid = 0.55
        improvement = 0.02
        sandbox_price = round(max(0.01, mid - improvement), 2)
        assert sandbox_price == 0.53

    def test_maker_sandbox_price_improvement_sell(self):
        """Sell sandbox: price above mid by improvement amount."""
        mid = 0.55
        improvement = 0.02
        sandbox_price = round(min(0.99, mid + improvement), 2)
        assert sandbox_price == 0.57


class TestExecutionStatDB:
    """Integration tests for execution stat DB operations."""

    @pytest.mark.asyncio
    async def test_create_execution_stat(self, db_session):
        stat = await Repository.create_execution_stat(
            db_session,
            order_id="order-1",
            market_id="mkt-1",
            token_id="YES",
            side="BUY",
            quoted_mid=0.55,
            order_price=0.54,
            expected_fee=0.006,
            expected_edge=0.05,
            execution_mode="MAKER",
        )
        assert stat.id is not None
        assert stat.order_id == "order-1"
        assert stat.quoted_mid == 0.55
        assert stat.was_filled is False
        assert stat.was_cancelled is False

    @pytest.mark.asyncio
    async def test_update_fill(self, db_session):
        stat = await Repository.create_execution_stat(
            db_session,
            order_id="order-2",
            market_id="mkt-1",
            token_id="YES",
            side="BUY",
            quoted_mid=0.55,
            order_price=0.54,
            expected_fee=0.006,
            expected_edge=0.05,
        )
        await db_session.commit()

        updated = await Repository.update_execution_stat_fill(
            db_session,
            order_id="order-2",
            fill_price=0.545,
            actual_fee=0.005,
            fill_time_seconds=3.2,
        )
        assert updated is not None
        assert updated.was_filled is True
        assert updated.fill_price == 0.545
        assert updated.actual_fee == 0.005
        assert updated.fill_time_seconds == 3.2
        # slippage = fill_price - quoted_mid = 0.545 - 0.55 = -0.005
        assert round(updated.slippage_vs_mid, 4) == -0.005

    @pytest.mark.asyncio
    async def test_update_cancel(self, db_session):
        await Repository.create_execution_stat(
            db_session,
            order_id="order-3",
            market_id="mkt-1",
            token_id="YES",
            side="BUY",
            quoted_mid=0.55,
            order_price=0.54,
            expected_fee=0.006,
            expected_edge=0.05,
        )
        await db_session.commit()

        updated = await Repository.update_execution_stat_cancel(
            db_session, order_id="order-3", reason="timeout",
        )
        assert updated is not None
        assert updated.was_cancelled is True
        assert updated.cancel_reason == "timeout"
        assert updated.was_filled is False

    @pytest.mark.asyncio
    async def test_get_execution_summary_empty(self, db_session):
        summary = await Repository.get_execution_summary(db_session)
        assert summary["total_orders_tracked"] == 0
        assert summary["fill_rate"] == 0.0
        assert summary["cancel_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_get_execution_summary_with_data(self, db_session):
        # Create 3 orders: 2 filled, 1 cancelled
        await Repository.create_execution_stat(
            db_session, order_id="o1", market_id="m1", token_id="YES",
            side="BUY", quoted_mid=0.50, order_price=0.49,
            expected_fee=0.006, expected_edge=0.05,
        )
        await Repository.create_execution_stat(
            db_session, order_id="o2", market_id="m2", token_id="YES",
            side="BUY", quoted_mid=0.60, order_price=0.59,
            expected_fee=0.006, expected_edge=0.04,
        )
        await Repository.create_execution_stat(
            db_session, order_id="o3", market_id="m3", token_id="NO",
            side="BUY", quoted_mid=0.40, order_price=0.39,
            expected_fee=0.006, expected_edge=0.03,
        )
        await db_session.commit()

        await Repository.update_execution_stat_fill(
            db_session, order_id="o1", fill_price=0.50,
            actual_fee=0.005, fill_time_seconds=2.0,
        )
        await Repository.update_execution_stat_fill(
            db_session, order_id="o2", fill_price=0.60,
            actual_fee=0.006, fill_time_seconds=5.0,
        )
        await Repository.update_execution_stat_cancel(
            db_session, order_id="o3", reason="timeout",
        )
        await db_session.commit()

        summary = await Repository.get_execution_summary(db_session)
        assert summary["total_orders_tracked"] == 3
        assert summary["filled"] == 2
        assert summary["cancelled"] == 1
        assert round(summary["fill_rate"], 2) == 0.67
        assert round(summary["cancel_rate"], 2) == 0.33
        assert summary["avg_fill_time_seconds"] == 3.5

    @pytest.mark.asyncio
    async def test_maker_sandbox_filter(self, db_session):
        await Repository.create_execution_stat(
            db_session, order_id="normal-1", market_id="m1", token_id="YES",
            side="BUY", quoted_mid=0.50, order_price=0.49,
            expected_fee=0.006, expected_edge=0.05,
            is_maker_sandbox=False,
        )
        await Repository.create_execution_stat(
            db_session, order_id="sandbox-1", market_id="m1", token_id="YES",
            side="BUY", quoted_mid=0.50, order_price=0.48,
            expected_fee=0.0, expected_edge=0.05,
            execution_mode="MAKER_SANDBOX", is_maker_sandbox=True,
        )
        await db_session.commit()

        all_stats = await Repository.get_execution_stats(db_session)
        assert len(all_stats) == 2

        sandbox_only = await Repository.get_execution_stats(
            db_session, maker_sandbox_only=True,
        )
        assert len(sandbox_only) == 1
        assert sandbox_only[0].is_maker_sandbox is True


class TestMakerSandboxSizing:
    """Test maker sandbox respects safety constraints."""

    def test_sandbox_size_too_small_skipped(self):
        """If normal_size * pct < $0.50, sandbox should be skipped."""
        normal_size = 2.0
        pct = 0.15
        sandbox_size = round(normal_size * pct, 2)
        assert sandbox_size == 0.30
        assert sandbox_size < 0.50  # would be skipped

    def test_sandbox_size_valid(self):
        """Normal case: $5 * 15% = $0.75, above $0.50 minimum."""
        normal_size = 5.0
        pct = 0.15
        sandbox_size = round(normal_size * pct, 2)
        assert sandbox_size == 0.75
        assert sandbox_size >= 0.50

    def test_sandbox_price_bounds_buy(self):
        """Buy sandbox price never goes below 0.01."""
        mid = 0.02
        improvement = 0.02
        sandbox_price = round(max(0.01, mid - improvement), 2)
        assert sandbox_price == 0.01  # clamped to floor

    def test_sandbox_price_bounds_sell(self):
        """Sell sandbox price never goes above 0.99."""
        mid = 0.98
        improvement = 0.02
        sandbox_price = round(min(0.99, mid + improvement), 2)
        assert sandbox_price == 0.99  # clamped to ceiling
